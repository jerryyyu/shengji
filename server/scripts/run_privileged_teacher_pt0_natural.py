#!/usr/bin/env python3
"""Recoverable filesystem boundary for the score-free natural PT0 packet.

The natural core remains in-memory.  This runner is the only component here
which opens paths, and every path is explicit, canonical, and fail-closed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
from types import ModuleType
from typing import Mapping, Sequence

RUNNER_SCHEMA = "privileged-teacher-pt0-natural-runner-v1"
PARTIAL_SCHEMA = "privileged-teacher-pt0-natural-partial-v1"
PROGRESS_SCHEMA = "privileged-teacher-pt0-natural-progress-v1"
MANIFEST_SCHEMA = "privileged-teacher-pt0-natural-manifest-v1"
RECORD_DIR = "records"
PACKET_NAME = "packet.json"
MANIFEST_NAME = "manifest.json"
PARTIAL_NAME = ".partial"
AUTHORITY = {
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "deployment_authorized": False,
    "training_authorized": False,
}
RECORD_KEYS = {
    "schema", "capture_id_sha256", "trump_rank", "banker", "role",
    "remaining_hand_threshold", "public_state_sha256",
    "proposal_world_population_sha256", "proposal_world_count",
    "proposal_unique_underlying_world_count",
    "evaluation_world_population_sha256", "evaluation_world_count",
    "evaluation_unique_underlying_world_count",
    "cross_cohort_underlying_world_overlap_count",
    "world_population_sha256", "world_count", "target_sha256",
    "target_argmax", "proposal_action", "evaluation_argmax",
    "proposal_action_rank", "proposal_action_rank_in_evaluation",
    "target_dispersion", "baselines", "work", "authority",
}
core: ModuleType | None = None


class RunnerRefused(ValueError):
    """The filesystem runner detected identity, integrity, or authority drift."""


def canonical_json_bytes(value: object) -> bytes:
    """Encode runner bootstrap records without importing project code."""
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True) + "\n").encode("ascii")


def _load_core(repo_root: Path | None = None) -> ModuleType:
    """Import the reviewed project module only after the bootstrap gate."""
    global core
    if core is None:
        core = importlib.import_module(
            "shengji.rl.privileged_teacher_pt0_natural")
    if repo_root is not None:
        expected = (repo_root / "server" / "shengji" / "rl"
                    / "privileged_teacher_pt0_natural.py").resolve()
        actual = Path(str(core.__file__)).resolve()
        if actual != expected:
            raise RunnerRefused("natural core import path drift")
    return core


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_load(data: bytes, label: str) -> object:
    try:
        value = json.loads(data.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunnerRefused(f"{label} is not canonical JSON") from exc
    if canonical_json_bytes(value) != data:
        raise RunnerRefused(f"{label} is not canonical JSON")
    return value


def _safe_record(data: bytes, label: str) -> object:
    value = _canonical_load(data, label)
    forbidden = {"round_seed", "capture_seed_index", "true_world",
                 "hidden_world", "hidden_hands", "hands", "buried"}

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if forbidden.intersection(node):
                raise RunnerRefused(f"unsafe hidden field in {label}")
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return value


def _lstat(path: Path, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise RunnerRefused(f"missing {label}: {path}") from exc
    if stat.S_ISLNK(info.st_mode):
        raise RunnerRefused(f"symlink refused: {path}")
    return info


def _regular(path: Path, label: str) -> None:
    info = _lstat(path, label)
    if not stat.S_ISREG(info.st_mode):
        raise RunnerRefused(f"non-regular file refused: {path}")


def _directory(path: Path, label: str) -> None:
    info = _lstat(path, label)
    if not stat.S_ISDIR(info.st_mode):
        raise RunnerRefused(f"non-directory refused: {path}")


def _mkdir(path: Path) -> None:
    if path.exists() or path.is_symlink():
        _directory(path, "output directory")
    else:
        path.mkdir(parents=True)
    _directory(path, "output directory")


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_exclusive(path: Path, data: bytes, *, allow_identical: bool = True) -> None:
    """Write bytes with O_EXCL temp creation, fsync, and atomic rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        _regular(path, "existing artifact")
        old = path.read_bytes()
        if allow_identical and old == data:
            return
        raise RunnerRefused(f"existing artifact bytes mismatch: {path}")
    token = next(tempfile._get_candidate_names())
    temporary = path.parent / f".{path.name}.{token}.tmp"
    fd = None
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            fd = None
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_dir(path.parent)
    except FileExistsError as exc:
        raise RunnerRefused(f"temporary artifact collision: {temporary}") from exc
    finally:
        if fd is not None:
            os.close(fd)
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()


def _atomic_replace(path: Path, data: bytes) -> None:
    """Atomically replace a runner-owned mutable receipt (progress only)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        _regular(path, "existing mutable artifact")
    token = next(tempfile._get_candidate_names())
    temporary = path.parent / f".{path.name}.{token}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = None
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_dir(path.parent)
    finally:
        if fd is not None:
            os.close(fd)
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()


def _design_from_bytes(data: bytes) -> object:
    active_core = _load_core()
    value = _canonical_load(data, "design")
    if not isinstance(value, dict):
        raise RunnerRefused("design must be a JSON object")
    required = set(active_core.NaturalPT0Design(
        capture_secret_sha256="0" * 64, trump_ranks=("2",)).payload())
    if set(value) != required:
        raise RunnerRefused("design keys are not the frozen design schema")
    if value.get("authority") != AUTHORITY:
        raise RunnerRefused("design authority is not all false")
    try:
        proposal = value["proposal_worlds_per_state"]
        evaluation = value["evaluation_worlds_per_state"]
        design = active_core.NaturalPT0Design(
            capture_secret_sha256=value["capture_secret_sha256"],
            trump_ranks=tuple(value["trump_ranks"]),
            production_policy=value["production_policy"],
            banker_seats=tuple(value["banker_seats"]),
            role_buckets=tuple(value["role_buckets"]),
            remaining_hand_thresholds=tuple(value["remaining_hand_thresholds"]),
            capture_attempts_per_cell=value["capture_attempts_per_cell"],
            unique_worlds_per_state=proposal,
            proposal_worlds_per_state=proposal,
            evaluation_worlds_per_state=evaluation,
            max_sampler_attempts=value["max_sampler_attempts"],
            max_exact_nodes=value["max_exact_nodes"],
            baseline_policies=tuple(value["baseline_policies"]),
            baseline_seeds_per_state=value["baseline_seeds_per_state"],
            bootstrap_replicates=value["bootstrap_replicates"],
        )
    except (KeyError, TypeError, ValueError,
            active_core.NaturalPT0Error) as exc:
        raise RunnerRefused("design values are invalid") from exc
    if canonical_json_bytes(design.payload()) != data:
        raise RunnerRefused("design does not round-trip canonically")
    return design


def _capture_secret_from_path(
        path_value: str | os.PathLike[str],
        design: object) -> bytes:
    active_core = _load_core()
    path = Path(path_value)
    _regular(path, "capture secret")
    info = path.lstat()
    if (info.st_uid != os.geteuid() or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise RunnerRefused("capture secret ownership mode/link drift")
    data = path.read_bytes()
    try:
        return active_core._check_capture_secret(design, data)
    except active_core.NaturalPT0Error as exc:
        raise RunnerRefused("capture secret commitment drift") from exc


def _require_isolated_runtime() -> None:
    if (not sys.flags.safe_path or not sys.dont_write_bytecode
            or os.environ.get("PYTHONPATH")):
        raise RunnerRefused(
            "natural PT0 runner requires Python -P -B and no PYTHONPATH")


def _git_identity(repo_root: Path) -> str:
    try:
        head = subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(
            ["git", "-C", str(repo_root), "status", "--porcelain",
             "--untracked-files=all"],
            text=True).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RunnerRefused("could not verify source git identity") from exc
    if dirty:
        raise RunnerRefused("source tree is dirty")
    try:
        tracked_raw = subprocess.check_output(
            ["git", "-C", str(repo_root), "ls-files", "-z"])
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RunnerRefused("could not inventory tracked source") from exc
    tracked = {item.decode("utf-8") for item in tracked_raw.split(b"\0")
               if item}
    server = repo_root / "server"
    loadable_suffixes = {".py", ".pyc", ".pyo", ".so", ".pyd", ".dylib"}
    candidates = set()
    candidates.update(path for path in server.iterdir()
                      if path.is_file() and path.suffix in loadable_suffixes)
    candidates.update(path for path in server.glob("*/__init__.py"))
    for scan_root in (server / "shengji", server / "scripts"):
        candidates.update(path for path in scan_root.rglob("*")
                          if path.is_file()
                          and path.suffix in loadable_suffixes)
    native = []
    for path in sorted(candidates):
        relative = path.relative_to(repo_root).as_posix()
        if path.suffix in {".pyc", ".pyo"}:
            raise RunnerRefused("importable bytecode cache is present")
        if (path.suffix in {".so", ".pyd", ".dylib"}
                and path.parent == server / "shengji" / "engine"
                and path.name.startswith("_fast.")):
            native.append(path)
            continue
        if relative not in tracked:
            raise RunnerRefused("untracked import shadow is present")
    if len(native) > 1:
        raise RunnerRefused("native extension population drift")
    if len(head) != 40 or any(ch not in "0123456789abcdef" for ch in head):
        raise RunnerRefused("live git HEAD is not a SHA-1")
    return head


def _check_expected_source(expected: str, repo_root: Path) -> str:
    if type(expected) is not str or len(expected) != 40 \
            or any(ch not in "0123456789abcdef" for ch in expected):
        raise RunnerRefused("expected-source-git must be a 40-character SHA-1")
    live = _git_identity(repo_root)
    if live != expected:
        raise RunnerRefused("source git identity mismatch")
    return live


def _partial_meta(design: object, source_git: str) -> dict[str, object]:
    return {
        "schema": PARTIAL_SCHEMA,
        "design_sha256": _sha(canonical_json_bytes(design.payload())),
        "source_git": source_git,
        "total_record_count": len(design.bucket_keys),
        "authority": AUTHORITY,
    }


def _progress(completed: int, total: int, status: str) -> bytes:
    return canonical_json_bytes({
        "schema": PROGRESS_SCHEMA,
        "status": status,
        "completed_units": completed,
        "total_units": total,
        "percent_basis_points": (completed * 10_000) // total,
        "authority": AUTHORITY,
    })


def _validate_partial(partial: Path, design: object,
                      source_git: str) -> Path:
    _directory(partial, "partial directory")
    entries = {item.name for item in partial.iterdir()}
    required = {"meta.json", "progress.json", RECORD_DIR}
    if not required.issubset(entries) \
            or not entries.issubset(required | {PACKET_NAME, MANIFEST_NAME}):
        raise RunnerRefused("partial directory has extra or missing files")
    _regular(partial / "meta.json", "partial metadata")
    meta = _canonical_load((partial / "meta.json").read_bytes(), "partial metadata")
    expected = _partial_meta(design, source_git)
    if meta != expected:
        raise RunnerRefused("partial design/source identity mismatch")
    _regular(partial / "progress.json", "partial progress")
    progress = _canonical_load((partial / "progress.json").read_bytes(), "partial progress")
    if not isinstance(progress, dict) or progress.get("authority") != AUTHORITY:
        raise RunnerRefused("partial progress authority drift")
    records = partial / RECORD_DIR
    _directory(records, "partial record directory")
    for item in records.iterdir():
        if item.name.startswith("."):
            raise RunnerRefused("partial record filename drift")
        _regular(item, "partial record")
    for optional in (PACKET_NAME, MANIFEST_NAME):
        if optional in entries:
            _regular(partial / optional, f"partial {optional}")
    return records


def _record_path(records: Path, index: int) -> Path:
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise RunnerRefused("record index drift")
    return records / f"record-{index:06d}.json"


def _population(records: Path, record_count: int) -> list[dict[str, object]]:
    rows = []
    for index in range(record_count):
        path = _record_path(records, index)
        _regular(path, "record")
        data = path.read_bytes()
        _safe_record(data, f"record {index}")
        rows.append({"index": index, "name": path.name, "sha256": _sha(data)})
    expected = {f"record-{index:06d}.json" for index in range(record_count)}
    actual = {item.name for item in records.iterdir()}
    if actual != expected:
        raise RunnerRefused("record population is not closed")
    return rows


def _existing_records(
        records: Path, design: object) -> list[dict[str, object]]:
    """Reopen the exact contiguous prefix already durably published."""
    names = sorted(item.name for item in records.iterdir())
    expected = [f"record-{index:06d}.json" for index in range(len(names))]
    if names != expected:
        raise RunnerRefused("partial record prefix is not contiguous")
    values = []
    for index, name in enumerate(names):
        path = records / name
        _regular(path, "partial record")
        value = _safe_record(path.read_bytes(), f"record {index}")
        values.append(value)
    _validate_packet_records(design, values)
    return values


def _packet_hash(packet: Mapping[str, object]) -> str:
    if "packet_sha256" not in packet:
        raise RunnerRefused("packet hash missing")
    copy_packet = dict(packet)
    claimed = copy_packet.pop("packet_sha256")
    actual = _sha(canonical_json_bytes(copy_packet))
    if claimed != actual:
        raise RunnerRefused("packet hash mismatch")
    return claimed


def _manifest_hash(manifest: Mapping[str, object]) -> str:
    if "manifest_sha256" not in manifest:
        raise RunnerRefused("manifest hash missing")
    copy_manifest = dict(manifest)
    claimed = copy_manifest.pop("manifest_sha256")
    actual = _sha(canonical_json_bytes(copy_manifest))
    if claimed != actual:
        raise RunnerRefused("manifest hash mismatch")
    return claimed


def _hex_sha256(value: object) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _validate_packet_records(
        design: object,
        records: Sequence[object]) -> None:
    active_core = _load_core()
    expected_keys = sorted(design.bucket_keys)[:len(records)]
    actual_keys = []
    capture_ids = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != RECORD_KEYS:
            raise RunnerRefused("natural record field population drift")
        key = (record["trump_rank"], record["banker"], record["role"],
               record["remaining_hand_threshold"])
        actual_keys.append(key)
        if (record["schema"] != active_core.NATURAL_PT0_RECORD_SCHEMA
                or record["authority"] != AUTHORITY
                or not _hex_sha256(record["capture_id_sha256"])
                or not _hex_sha256(record["public_state_sha256"])
                or not _hex_sha256(record["proposal_world_population_sha256"])
                or not _hex_sha256(record["evaluation_world_population_sha256"])
                or not _hex_sha256(record["world_population_sha256"])
                or not _hex_sha256(record["target_sha256"])
                or record["proposal_world_count"]
                != design.proposal_worlds_per_state
                or record["evaluation_world_count"]
                != design.evaluation_worlds_per_state
                or isinstance(
                    record["proposal_unique_underlying_world_count"], bool)
                or not isinstance(
                    record["proposal_unique_underlying_world_count"], int)
                or not 1 <= record[
                    "proposal_unique_underlying_world_count"] \
                    <= record["proposal_world_count"]
                or isinstance(
                    record["evaluation_unique_underlying_world_count"], bool)
                or not isinstance(
                    record["evaluation_unique_underlying_world_count"], int)
                or not 1 <= record[
                    "evaluation_unique_underlying_world_count"] \
                    <= record["evaluation_world_count"]
                or isinstance(
                    record["cross_cohort_underlying_world_overlap_count"], bool)
                or not isinstance(
                    record["cross_cohort_underlying_world_overlap_count"], int)
                or not 0 <= record[
                    "cross_cohort_underlying_world_overlap_count"] \
                    <= min(
                        record["proposal_unique_underlying_world_count"],
                        record["evaluation_unique_underlying_world_count"])
                or record["world_count"] != record["proposal_world_count"]
                or record["world_population_sha256"]
                != record["proposal_world_population_sha256"]
                or record["proposal_action_rank"] != 0):
            raise RunnerRefused("natural record identity drift")
        capture_ids.add(record["capture_id_sha256"])
        baselines = record["baselines"]
        if not isinstance(baselines, list):
            raise RunnerRefused("natural baseline population drift")
        expected_baselines = {
            (policy, seed_index)
            for policy in design.baseline_policies
            for seed_index in range(design.baseline_seeds_per_state)
        }
        actual_baselines = set()
        for baseline in baselines:
            if (not isinstance(baseline, dict)
                    or set(baseline) != {
                        "policy", "seed_index", "selected_cards",
                        "evaluation_delta_pt0_minus_baseline"}
                    or not isinstance(baseline["selected_cards"], list)
                    or any(type(card) is not str
                           for card in baseline["selected_cards"])):
                raise RunnerRefused("natural baseline row drift")
            delta = baseline["evaluation_delta_pt0_minus_baseline"]
            if (not isinstance(delta, dict)
                    or set(delta) != {"numerator", "denominator"}
                    or isinstance(delta["numerator"], bool)
                    or not isinstance(delta["numerator"], int)
                    or isinstance(delta["denominator"], bool)
                    or not isinstance(delta["denominator"], int)
                    or delta["denominator"] <= 0):
                raise RunnerRefused("natural baseline delta drift")
            actual_baselines.add((baseline["policy"], baseline["seed_index"]))
        if actual_baselines != expected_baselines \
                or len(baselines) != len(expected_baselines):
            raise RunnerRefused("natural baseline population drift")
    if actual_keys != expected_keys or len(capture_ids) != len(records):
        raise RunnerRefused("natural state population drift")


def verify_bundle(
        output_root: str | os.PathLike[str], *,
        design: object,
        expected_source_git: str | None = None) -> dict[str, object]:
    """Independently reopen and verify a COMPLETE/TRUNCATED final bundle."""
    active_core = _load_core()
    root = Path(output_root)
    _directory(root, "bundle root")
    entries = {item.name for item in root.iterdir()}
    if entries != {PACKET_NAME, MANIFEST_NAME, RECORD_DIR,
                   "meta.json", "progress.json"}:
        raise RunnerRefused("final bundle has extra or missing files")
    _regular(root / PACKET_NAME, "packet")
    _regular(root / MANIFEST_NAME, "manifest")
    packet = _canonical_load((root / PACKET_NAME).read_bytes(), "packet")
    manifest = _canonical_load((root / MANIFEST_NAME).read_bytes(), "manifest")
    meta = _canonical_load((root / "meta.json").read_bytes(), "bundle metadata")
    progress = _canonical_load(
        (root / "progress.json").read_bytes(), "bundle progress")
    if not isinstance(packet, dict) or not isinstance(manifest, dict):
        raise RunnerRefused("packet/manifest must be objects")
    packet_hash = _packet_hash(packet)
    manifest_hash = _manifest_hash(manifest)
    design_sha256 = _sha(canonical_json_bytes(design.payload()))
    record_count = packet.get("record_count")
    total_record_count = packet.get("total_record_count")
    status = packet.get("status")
    if (isinstance(record_count, bool) or not isinstance(record_count, int)
            or record_count < 0
            or isinstance(total_record_count, bool)
            or not isinstance(total_record_count, int)
            or total_record_count != len(design.bucket_keys)
            or record_count > total_record_count):
        raise RunnerRefused("packet record counts drift")
    if (packet.get("schema") != active_core.NATURAL_PT0_SCHEMA
            or packet.get("authority") != AUTHORITY
            or not isinstance(packet.get("records"), list)
            or record_count != len(packet["records"])
            or packet.get("design_sha256") != design_sha256
            or status not in {"COMPLETE", "TRUNCATED"}
            or (status == "COMPLETE") != (record_count == total_record_count)
            or packet.get("truncated_by_deadline") != (status == "TRUNCATED")
            or packet.get("progress") != {
                "completed_units": record_count,
                "total_units": total_record_count,
                "percent_basis_points": (
                    record_count * 10_000) // total_record_count,
            }
            or manifest.get("schema") != MANIFEST_SCHEMA) \
            or manifest.get("packet_schema") != active_core.NATURAL_PT0_SCHEMA \
            or manifest.get("packet_sha256") != packet_hash \
            or manifest.get("packet_bytes_sha256") != _sha((root / PACKET_NAME).read_bytes()) \
            or manifest.get("authority") != AUTHORITY \
            or manifest.get("design_sha256") != design_sha256:
        raise RunnerRefused("manifest coordination drift")
    if expected_source_git is not None and manifest.get("source_git") != expected_source_git:
        raise RunnerRefused("manifest source identity drift")
    records = root / RECORD_DIR
    _directory(records, "record directory")
    if manifest.get("record_count") != record_count \
            or manifest.get("total_record_count") != total_record_count:
        raise RunnerRefused("manifest record counts drift")
    population = _population(records, record_count)
    if population != manifest.get("record_population"):
        raise RunnerRefused("record population hash rows drift")
    if manifest.get("record_population_sha256") != _sha(canonical_json_bytes(population)):
        raise RunnerRefused("record population hash mismatch")
    if status != manifest.get("status"):
        raise RunnerRefused("packet/manifest status drift")
    for index, record in enumerate(packet["records"]):
        if canonical_json_bytes(record) != _record_path(records, index).read_bytes():
            raise RunnerRefused("packet/record bytes drift")
    _validate_packet_records(design, packet["records"])
    expected_summary = active_core.summarize_natural_records(
        design, packet["records"], complete=status == "COMPLETE")
    if packet.get("summary") != expected_summary:
        raise RunnerRefused("packet summary reconstruction drift")
    expected_meta = _partial_meta(
        design, str(manifest.get("source_git", "")))
    if meta != expected_meta:
        raise RunnerRefused("bundle metadata drift")
    if progress != json.loads(_progress(
            record_count, total_record_count, status)):
        raise RunnerRefused("bundle progress drift")
    return {"status": manifest["status"], "packet_sha256": packet_hash,
            "manifest_sha256": manifest_hash,
            "record_count": manifest["record_count"],
            "authority": AUTHORITY}


def run_bundle(design_path: str | os.PathLike[str],
               capture_secret_path: str | os.PathLike[str],
               output_root: str | os.PathLike[str], expected_source_git: str,
               *, deadline_seconds: float | None = None,
               repo_root: str | os.PathLike[str] | None = None) -> dict[str, object]:
    _require_isolated_runtime()
    repo = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
    source_git = _check_expected_source(expected_source_git, repo)
    active_core = _load_core(repo)
    design_data = Path(design_path).read_bytes()
    design = _design_from_bytes(design_data)
    root = Path(output_root)
    partial = root.with_name(root.name + PARTIAL_NAME)
    if root.is_symlink() or partial.is_symlink():
        raise RunnerRefused("output symlink refused")
    if root.exists():
        if partial.exists():
            raise RunnerRefused("final and partial output both exist")
        return verify_bundle(
            root, design=design, expected_source_git=source_git)
    capture_secret = _capture_secret_from_path(capture_secret_path, design)
    if partial.exists():
        records_dir = _validate_partial(partial, design, source_git)
        if (partial / PACKET_NAME).exists() \
                and (partial / MANIFEST_NAME).exists():
            result = verify_bundle(
                partial, design=design, expected_source_git=source_git)
            os.replace(partial, root)
            os.chmod(root, 0o555)
            _fsync_dir(root.parent)
            return result
    else:
        if not root.parent.exists() or root.parent.is_symlink():
            raise RunnerRefused("output parent must be an existing directory")
        _directory(root.parent, "output parent")
        partial.mkdir(mode=0o700)
        _fsync_dir(root.parent)
        records_dir = partial / RECORD_DIR
        records_dir.mkdir()
        _atomic_exclusive(partial / "meta.json",
                          canonical_json_bytes(_partial_meta(design, source_git)))
        _atomic_exclusive(partial / "progress.json",
                          _progress(0, len(design.bucket_keys), "RUNNING"))

    completed_prefix = _existing_records(records_dir, design)

    def record_sink(index: int, data: bytes) -> None:
        _safe_record(data, f"record {index}")
        _atomic_exclusive(_record_path(records_dir, index), data)
        _atomic_replace(partial / "progress.json",
                        _progress(index + 1, len(design.bucket_keys), "RUNNING"))

    kwargs: dict[str, object] = {
        "record_sink": record_sink,
        "capture_secret": capture_secret,
        # Completed rows are not trusted blindly: the core deterministically
        # recomputes this exact prefix and record_sink demands byte identity.
        # Deadline expiry may stop only after that integrity replay, never by
        # returning a shorter population than is already durable on disk.
        "deadline_exempt_prefix": len(completed_prefix),
    }
    if deadline_seconds is not None:
        if (isinstance(deadline_seconds, bool)
                or not isinstance(deadline_seconds, (int, float))
                or not math.isfinite(deadline_seconds)
                or deadline_seconds < 0):
            raise RunnerRefused("deadline_seconds must be nonnegative")
        kwargs["deadline"] = time.monotonic() + deadline_seconds
    try:
        packet = active_core.run_natural_packet(design, **kwargs)
        if not isinstance(packet, dict):
            raise RunnerRefused("natural core returned a non-object packet")
        for index, record in enumerate(packet.get("records", [])):
            record_sink(index, canonical_json_bytes(record))
        status = packet.get("status")
        if status not in {"COMPLETE", "TRUNCATED"}:
            raise RunnerRefused("natural core returned an invalid final status")
        record_count = int(packet.get("record_count", -1))
        population = _population(records_dir, record_count)
        _atomic_replace(partial / "progress.json",
                        _progress(record_count, int(packet["total_record_count"]), status))
        packet_data = canonical_json_bytes(packet)
        _packet_hash(packet)
        _atomic_exclusive(partial / PACKET_NAME, packet_data)
        manifest_without_hash = {
            "schema": MANIFEST_SCHEMA,
            "runner_schema": RUNNER_SCHEMA,
            "status": status,
            "design_sha256": _sha(canonical_json_bytes(design.payload())),
            "source_git": source_git,
            "record_count": record_count,
            "total_record_count": packet["total_record_count"],
            "packet_sha256": packet["packet_sha256"],
            "packet_schema": active_core.NATURAL_PT0_SCHEMA,
            "packet_bytes_sha256": _sha(packet_data),
            "record_population": population,
            "record_population_sha256": _sha(canonical_json_bytes(population)),
            "authority": AUTHORITY,
        }
        manifest = dict(manifest_without_hash)
        manifest["manifest_sha256"] = _sha(canonical_json_bytes(manifest_without_hash))
        _atomic_exclusive(partial / MANIFEST_NAME, canonical_json_bytes(manifest))
        # The whole staged directory is renamed in one filesystem operation.
        # There is no intermediate final bundle with a split population.
        for path in (partial / PACKET_NAME, partial / MANIFEST_NAME,
                     partial / "meta.json", partial / "progress.json"):
            os.chmod(path, 0o444)
        for path in (partial / RECORD_DIR,):
            os.chmod(path, 0o555)
            for child in path.iterdir():
                os.chmod(child, 0o444)
        os.replace(partial, root)
        os.chmod(root, 0o555)
        _fsync_dir(root.parent)
        return verify_bundle(
            root, design=design, expected_source_git=source_git)
    except Exception:
        # Keep .partial intact and resumable; no cleanup may erase evidence.
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", required=True)
    parser.add_argument("--capture-secret")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--expected-source-git", required=True)
    parser.add_argument("--deadline-seconds", type=float)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            _require_isolated_runtime()
            repo = Path(__file__).resolve().parents[2]
            source_git = _check_expected_source(args.expected_source_git, repo)
            _load_core(repo)
            design = _design_from_bytes(Path(args.design).read_bytes())
            result = verify_bundle(
                args.output_root, design=design,
                expected_source_git=source_git)
        else:
            if args.capture_secret is None:
                raise RunnerRefused("--capture-secret is required for execution")
            result = run_bundle(
                args.design, args.capture_secret, args.output_root,
                args.expected_source_git,
                deadline_seconds=args.deadline_seconds)
    except RunnerRefused as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI boundary
    sys.exit(main())

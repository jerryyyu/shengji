#!/usr/bin/env python3
"""Review-gated aggregation of the sealed 64-state bury/S6 scored-DEV run.

The source review and exact input review are deliberately consolidated into
one canonical marker.  Before that marker is authenticated this module may
inspect only the already-reviewed score-free packet, admission, supervisor
final, review snapshots, and record metadata.  Record bytes are opened only
after a new one-shot aggregate admission is consumed.

The aggregate remains opened-DEV exploration.  It can recommend a fresh
screen design, but it cannot launch that screen, claim strength, train, promote
or deploy.  There is no retry, resume, extension, REPORT, or gameplay command.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import secrets
import stat
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any


SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[2]
SERVER = REPO / "server"

SOURCE_GIT = "a93c2f58d2e152adfd854c4416e9a92c5a005e68"
SOURCE_ROOT = Path("/var/tmp/shengji-s6-v3-optimized-recovery-v1")
SOURCE_SERVER = SOURCE_ROOT / "server"
SOURCE_SCRIPTS = SOURCE_SERVER / "scripts"
CONTROLLER_PATH = SOURCE_SCRIPTS / "bury_lead_combo_scored_dev_controller.py"
SCORER_PATH = SOURCE_SCRIPTS / "bury_lead_combo_scored_dev.py"
DESIGN_PATH = SOURCE_SCRIPTS / "bury_lead_combo_scored_dev_design.py"
CONTROLLER_SHA256 = (
    "744b4c5d3bc6d80e39d3d3f8cea78b2a8078d87cd314681ba48f04c7995eeaa9"
)
SCORER_SHA256 = (
    "3d26bc17f2ad88fb54765c227092041f4db5ec22e1fbc2d591b193a38ea9a91b"
)
DESIGN_SHA256 = (
    "0a63916f0bb83c46080ad0efdd41ac1e4ef9941f323bc3ad9d0b4e8404a34496"
)

RUN_ID = "bury-lead-combo-scored-dev-64-v3-shadow-gate"
SOURCE_RUN_DIR = SOURCE_SERVER / "runs/logs" / RUN_ID
PACKET_PATH = SOURCE_RUN_DIR / "controller-packet.json"
IMPLEMENTATION_REVIEW_PATH = SOURCE_RUN_DIR / "implementation-review-snapshot.md"
PACKET_REVIEW_PATH = SOURCE_RUN_DIR / "packet-review-snapshot.md"
ADMISSION_PATH = SOURCE_SERVER / "runs/locks" / f"{RUN_ID}.admission.consumed.json"
RECORDS_DIR = SOURCE_RUN_DIR / "sealed-state-records"
FINAL_PATH = SOURCE_RUN_DIR / "supervisor-final.json"

PACKET_SHA256 = (
    "0e9ee5890bc0ae5e7793e51906ef1ba8d82f9e1412682eb246eaee7a7562bbee"
)
IMPLEMENTATION_REVIEW_SHA256 = (
    "a657dc37bf21bcf8efbdb44fd440156dd45dfb741ee0c6ac52d9c80584e9e9a0"
)
PACKET_REVIEW_SHA256 = (
    "8bbfa3e703a0f04598970b6f74d9c5cf424f9ef428161993eed374c128a1627b"
)
ADMISSION_SHA256 = (
    "de8d6c011826c106a819f08591ab21edac2991d3096965821d65324edf83d16a"
)
FINAL_SHA256 = (
    "d5136a273156b87e8d08d34efa612e1500482ed34b102115ca442a9d92d58617"
)

TERMINAL_REVIEW_COMMIT = "482119b8956fe42f1a932c80a39fd620f388556f"
TERMINAL_REVIEW_PARENT = "f46cad5cc87f99090686eb420981aab44394f7f8"
TERMINAL_REVIEW_APPEND_SHA256 = (
    "577de1c0c5686ed130b741fc17d2496f65a7da623db4e1d9cbbd7766908fc43a"
)
CANONICAL_REVIEW_REF = "origin/main"
REVIEW_LEDGER = "HANDOFF_REVIEW.md"
REVIEWER_NAME = "Claude"
REVIEWER_EMAIL = "noreply@anthropic.com"
REVIEWER_SESSION_TRAILER = "Claude-Session: https://claude.ai/code/session_"

AGGREGATE_RUN_ID = "bury-lead-combo-scored-dev-64-v3-aggregate-v1"
AGGREGATE_ROOT = Path("/var/tmp") / AGGREGATE_RUN_ID
GATE_PATH = AGGREGATE_ROOT / "execution.consumed"
OUTPUT_PATH = AGGREGATE_ROOT / "aggregate.json"
OUTPUT_PARTIAL_PATH = AGGREGATE_ROOT / "aggregate.json.partial"

IMPLEMENTATION_REVIEW_PREFIX = (
    "BURY_LEAD_COMBO_SCORED_DEV_AGGREGATE_V1_REVIEW "
)
RESULT_REVIEW_PREFIX = (
    "BURY_LEAD_COMBO_SCORED_DEV_AGGREGATE_RESULT_V1_REVIEW "
)
IMPLEMENTATION_REVIEW_SCHEMA = (
    "bury-lead-combo-scored-dev-aggregate-review-v1"
)
ADMISSION_SCHEMA = "bury-lead-combo-scored-dev-aggregate-admission-v1"
RESULT_SCHEMA = "bury-lead-combo-scored-dev-aggregate-v1"
RESULT_REVIEW_SCHEMA = "bury-lead-combo-scored-dev-aggregate-result-review-v1"

STATE_COUNT = 64
REPORT_WORLDS = 30
POSITIVE_STATE_GATE = 41
MODES = ("baseline", "all_boss", "boss_near")
SLOTS = ("incumbent_live", "incumbent_widened", "expanded")
CONTRASTS = {
    "lead_source": ("incumbent_widened", "incumbent_live"),
    "joint_bury_source": ("expanded", "incumbent_widened"),
    "joint_total": ("expanded", "incumbent_live"),
}
GROUPS = ("shape_rich", "hash_uniform_anchor")

FALSE_AUTHORITY = {
    "fresh_screen_execution_authorized": False,
    "confirmatory_inference_authorized": False,
    "retry_authorized": False,
    "resume_authorized": False,
    "extension_authorized": False,
    "report_access_authorized": False,
    "strength_claim": False,
    "training_authorized": False,
    "production_promotion": False,
    "production_deployment": False,
}


class AggregateRefused(RuntimeError):
    """A provenance, integrity, one-shot, or statistical contract drifted."""


def canonical(value: object) -> bytes:
    return (json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False) + "\n").encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def is_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def is_git_sha(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 40
            and all(character in "0123456789abcdef" for character in value))


def _integer(value: object, *, minimum: int | None = None) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool)
            and (minimum is None or value >= minimum))


def _reject_constant(value: str) -> None:
    raise ValueError(f"nonfinite JSON constant {value}")


def _pairs(values: list[tuple[str, object]]) -> dict:
    result: dict[str, object] = {}
    for key, value in values:
        if key in result:
            raise ValueError(f"duplicate JSON key {key}")
        result[key] = value
    return result


def strict_json(raw: bytes) -> Any:
    return json.loads(
        raw, object_pairs_hook=_pairs, parse_constant=_reject_constant)


def git(*args: str, cwd: Path = REPO) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True,
        capture_output=True, text=True).stdout.strip()


def git_bytes(*args: str, cwd: Path = REPO) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True,
        capture_output=True).stdout


def require_clean_exact_git(expected_git: str, *, cwd: Path = REPO) -> None:
    if (not is_git_sha(expected_git)
            or git("rev-parse", "HEAD", cwd=cwd) != expected_git
            or git("status", "--porcelain", "--untracked-files=all", cwd=cwd)):
        raise AggregateRefused(f"exact clean Git required at {cwd}")


def stable_bytes(path: Path, *, label: str, root_owned: bool = True,
                 nonwritable: bool = True) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except (FileNotFoundError, OSError) as exc:
        raise AggregateRefused(f"{label} is missing or linked") from exc
    try:
        before = os.fstat(descriptor)
        path_before = path.lstat()
        chunks = []
        while True:
            chunk = os.read(descriptor, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        path_after = path.lstat()
    except (FileNotFoundError, OSError) as exc:
        raise AggregateRefused(f"{label} changed during read") from exc
    finally:
        os.close(descriptor)
    identity = lambda item: (
        item.st_dev, item.st_ino, item.st_mode, item.st_nlink,
        item.st_uid, item.st_size, item.st_mtime_ns,
    )
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or identity(before) != identity(after)
            or identity(before) != identity(path_before)
            or identity(before) != identity(path_after)
            or (root_owned and before.st_uid != 0)
            or (nonwritable and before.st_mode & 0o222)
            or os.path.lexists(str(path) + ".partial")):
        raise AggregateRefused(
            f"{label} is nonregular, linked, mutable, unowned, or unstable")
    raw = b"".join(chunks)
    if len(raw) != before.st_size:
        raise AggregateRefused(f"{label} size changed during read")
    return raw


def strict_object(path: Path, *, label: str) -> tuple[dict, bytes]:
    raw = stable_bytes(path, label=label)
    value = strict_json(raw)
    if not isinstance(value, dict):
        raise AggregateRefused(f"{label} is not an object")
    return value, raw


def _load_exact_module(name: str, path: Path, expected_sha: str) -> ModuleType:
    raw = stable_bytes(
        path, label=f"source {path.name}", root_owned=False,
        nonwritable=False)
    if sha256_bytes(raw) != expected_sha:
        raise AggregateRefused(f"source {path.name} SHA drift")
    if name in sys.modules:
        raise AggregateRefused(f"module {name} was preloaded")
    module = ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    try:
        exec(compile(raw, str(path), "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    if (sys.modules.get(name) is not module
            or Path(module.__file__).resolve() != path.resolve()):
        raise AggregateRefused(f"module {name} origin drift")
    return module


def load_controller() -> ModuleType:
    return _load_exact_module(
        "bury_lead_combo_scored_dev_controller", CONTROLLER_PATH,
        CONTROLLER_SHA256)


def require_fresh_process() -> None:
    if not sys.dont_write_bytecode:
        raise AggregateRefused("PYTHONDONTWRITEBYTECODE/-B is required")
    for name, module in tuple(sys.modules.items()):
        if name == "__main__":
            continue
        if (name == "shengji" or name.startswith("shengji.")
                or name in {
                    "bury_lead_combo_scored_dev_controller",
                    "bury_lead_combo_scored_dev_design",
                    "bury_lead_combo_scored_dev",
                    "bury_lead_combo_population",
                    "bury_lead_combo_exploration",
                }):
            raise AggregateRefused(f"source module {name} was preloaded")
        location = getattr(module, "__file__", None)
        if not location:
            continue
        try:
            Path(location).resolve().relative_to(SOURCE_SERVER.resolve())
        except (OSError, ValueError):
            continue
        raise AggregateRefused(f"source module {name} was preloaded")


def terminal_review() -> dict:
    try:
        if subprocess.run(
                ["git", "merge-base", "--is-ancestor",
                 TERMINAL_REVIEW_COMMIT, CANONICAL_REVIEW_REF], cwd=REPO,
                capture_output=True, check=False).returncode != 0:
            raise AggregateRefused("S6 terminal review is not canonical")
        parent = git("show", "-s", "--format=%P", TERMINAL_REVIEW_COMMIT)
        identity = tuple(git(
            "show", "-s", f"--format={field}", TERMINAL_REVIEW_COMMIT)
            for field in ("%an", "%ae", "%cn", "%ce"))
        changed = git(
            "diff-tree", "--no-commit-id", "--name-only", "-r",
            TERMINAL_REVIEW_COMMIT).splitlines()
        body = git("show", "-s", "--format=%B", TERMINAL_REVIEW_COMMIT)
        current = git_bytes(
            "show", f"{TERMINAL_REVIEW_COMMIT}:{REVIEW_LEDGER}")
        previous = git_bytes(
            "show", f"{TERMINAL_REVIEW_PARENT}:{REVIEW_LEDGER}")
        tip = git_bytes("show", f"{CANONICAL_REVIEW_REF}:{REVIEW_LEDGER}")
    except subprocess.CalledProcessError as exc:
        raise AggregateRefused("cannot authenticate S6 terminal review") from exc
    delta = current[len(previous):] if current.startswith(previous) else b""
    required = (
        b"S6 V3 score-free terminal PASS",
        b"exactly 64 closed state receipts",
        b"scored_records_opened=false",
        b"aggregation_authorized=false",
        b"aggregation gate is a separate, not-yet-authorized step",
    )
    if (parent != TERMINAL_REVIEW_PARENT
            or identity != (REVIEWER_NAME, REVIEWER_EMAIL,
                            REVIEWER_NAME, REVIEWER_EMAIL)
            or changed != [REVIEW_LEDGER]
            or REVIEWER_SESSION_TRAILER not in body
            or not current.startswith(previous) or not tip.startswith(current)
            or sha256_bytes(delta) != TERMINAL_REVIEW_APPEND_SHA256
            or any(token not in delta for token in required)):
        raise AggregateRefused("S6 terminal review provenance drift")
    return {
        "commit": TERMINAL_REVIEW_COMMIT,
        "parent_commit": parent,
        "append_sha256": TERMINAL_REVIEW_APPEND_SHA256,
        "ledger_sha256": sha256_bytes(current),
    }


def _review_record(*, commit: str, prefix: str, expected: dict,
                   label: str) -> tuple[dict, bytes]:
    if not is_git_sha(commit):
        raise AggregateRefused(f"{label} commit is invalid")
    try:
        if subprocess.run(
                ["git", "merge-base", "--is-ancestor", commit,
                 CANONICAL_REVIEW_REF], cwd=REPO,
                capture_output=True, check=False).returncode != 0:
            raise AggregateRefused(f"{label} is not canonical")
        parents = git("show", "-s", "--format=%P", commit).split()
        identity = tuple(git("show", "-s", f"--format={field}", commit)
                         for field in ("%an", "%ae", "%cn", "%ce"))
        body = git("show", "-s", "--format=%B", commit)
        changed = git(
            "diff-tree", "--no-commit-id", "--name-only", "-r",
            commit).splitlines()
        current = git_bytes("show", f"{commit}:{REVIEW_LEDGER}")
        previous = git_bytes("show", f"{parents[0]}:{REVIEW_LEDGER}")
        tip = git_bytes("show", f"{CANONICAL_REVIEW_REF}:{REVIEW_LEDGER}")
    except (subprocess.CalledProcessError, IndexError) as exc:
        raise AggregateRefused(f"cannot authenticate {label}") from exc
    marker = prefix.encode() + canonical(expected)
    prefix_bytes = prefix.encode()
    count_prefix = lambda raw: sum(
        line.startswith(prefix_bytes) for line in raw.splitlines())
    if (len(parents) != 1
            or identity != (REVIEWER_NAME, REVIEWER_EMAIL,
                            REVIEWER_NAME, REVIEWER_EMAIL)
            or changed != [REVIEW_LEDGER]
            or REVIEWER_SESSION_TRAILER not in body
            or not current.startswith(previous) or not tip.startswith(current)
            or previous.count(marker) != 0
            or current.count(marker) != 1
            or tip.count(marker) != 1
            or current[len(previous):].count(marker) != 1
            or count_prefix(previous) != 0
            or count_prefix(current) != 1
            or count_prefix(tip) != 1):
        raise AggregateRefused(f"{label} provenance or marker drift")
    return ({
        "commit": commit,
        "parent_commit": parents[0],
        "ledger_sha256": sha256_bytes(current),
        "marker_sha256": sha256_bytes(marker),
        "claim": expected,
    }, marker)


def _source_tree_problems(packet: Mapping[str, object]) -> list[str]:
    problems = []
    try:
        require_clean_exact_git(SOURCE_GIT, cwd=SOURCE_ROOT)
    except AggregateRefused as exc:
        problems.append(str(exc))
    runtime = packet.get("runtime")
    sources = runtime.get("source_sha256s") if isinstance(runtime, Mapping) else None
    if not isinstance(sources, Mapping) or not sources:
        return problems + ["packet runtime source manifest missing"]
    for relative, expected in sources.items():
        if not isinstance(relative, str) or not is_sha256(expected):
            problems.append("packet runtime source entry malformed")
            continue
        path = SOURCE_ROOT / relative
        try:
            raw = stable_bytes(path, label=f"runtime source {relative}")
        except AggregateRefused as exc:
            problems.append(str(exc))
            continue
        if sha256_bytes(raw) != expected:
            problems.append(f"runtime source {relative} SHA drift")
    native = runtime.get("native") if isinstance(runtime, Mapping) else None
    python = runtime.get("python") if isinstance(runtime, Mapping) else None
    if (not isinstance(native, Mapping)
            or not isinstance(native.get("path"), str)
            or not is_sha256(native.get("sha256"))):
        problems.append("packet native identity malformed")
    else:
        native_path = Path(native["path"])
        try:
            raw = stable_bytes(native_path, label="reviewed native binary")
            if sha256_bytes(raw) != native["sha256"]:
                problems.append("reviewed native binary SHA drift")
        except AggregateRefused as exc:
            problems.append(str(exc))
        tracked = set(git(
            "ls-tree", "-r", "--name-only", "HEAD", cwd=SOURCE_ROOT
        ).splitlines())
        allowed_native = str(native_path.resolve())
        for root in (SOURCE_SERVER / "shengji", SOURCE_SCRIPTS):
            for path in root.rglob("*"):
                if (path.is_file() and path.suffix in {".py", ".pyc", ".so"}
                        and str(path.resolve()) != allowed_native
                        and str(path.relative_to(SOURCE_ROOT)) not in tracked):
                    problems.append(
                        f"loadable runtime shadow {path.relative_to(SOURCE_ROOT)}")
        allowed_directories = {
            "shengji", "scripts", "tests", "runs", "rl_data", ".venv",
            "build", "shengji.egg-info", "__pycache__",
        }
        for child in SOURCE_SERVER.iterdir():
            relative = str(child.relative_to(SOURCE_ROOT))
            if (child.is_file() and child.suffix in {".py", ".pyc", ".so"}
                    and relative not in tracked):
                problems.append(f"loadable runtime shadow {relative}")
            if (child.is_dir() and child.name not in allowed_directories
                    and (child / "__init__.py").exists()):
                problems.append(f"loadable runtime package shadow {relative}")
    if (not isinstance(python, Mapping)
            or not isinstance(python.get("resolved"), str)
            or not is_sha256(python.get("sha256"))
            or not isinstance(python.get("version"), str)):
        problems.append("packet Python identity malformed")
    else:
        python_path = Path(python["resolved"])
        try:
            raw = stable_bytes(python_path, label="reviewed Python binary")
            if sha256_bytes(raw) != python["sha256"]:
                problems.append("reviewed Python binary SHA drift")
        except AggregateRefused as exc:
            problems.append(str(exc))
        if (Path(sys.executable).resolve() != python_path.resolve()
                or platform.python_version() != python["version"]):
            problems.append("current Python identity drift")
    return problems


def _require_loaded_origins(packet: Mapping[str, object]) -> None:
    runtime = packet["runtime"]
    sources = runtime["source_sha256s"]
    native_path = Path(runtime["native"]["path"]).resolve()
    for name, module in tuple(sys.modules.items()):
        if not (name == "shengji" or name.startswith("shengji.")
                or name.startswith("bury_lead_combo")):
            continue
        location = getattr(module, "__file__", None)
        if not location:
            continue
        path = Path(location).resolve()
        if path == native_path:
            if sha256_file(path) != runtime["native"]["sha256"]:
                raise AggregateRefused("loaded native binary SHA drift")
            continue
        try:
            relative = str(path.relative_to(SOURCE_ROOT.resolve()))
        except ValueError as exc:
            raise AggregateRefused(f"loaded module {name} escaped source root") \
                from exc
        if relative not in sources or sha256_file(path) != sources[relative]:
            raise AggregateRefused(f"loaded module {name} source drift")


def _record_manifest(final: Mapping[str, object]) -> list[dict]:
    receipts = final.get("state_receipts")
    if not isinstance(receipts, list) or len(receipts) != STATE_COUNT:
        raise AggregateRefused("state receipt population drift")
    result = []
    for index, receipt in enumerate(receipts):
        if not isinstance(receipt, Mapping):
            raise AggregateRefused(f"state receipt {index} malformed")
        result.append({
            "state_index": index,
            "deal_seed": receipt.get("deal_seed"),
            "state_id": receipt.get("state_id"),
            "record_file": receipt.get("record_file"),
            "record_sha256": receipt.get("record_sha256"),
            "record_internal_sha256": receipt.get("record_internal_sha256"),
            "record_bytes": receipt.get("record_bytes"),
        })
    return result


def _verify_record_metadata(manifest: list[dict], *, require_root: bool = True) -> None:
    expected_names = [f"state-{index:02d}-of-{STATE_COUNT}.json"
                      for index in range(STATE_COUNT)]
    try:
        observed_names = sorted(child.name for child in RECORDS_DIR.iterdir())
    except OSError as exc:
        raise AggregateRefused("sealed record directory is unavailable") from exc
    if observed_names != expected_names:
        raise AggregateRefused("sealed record directory population drift")
    for index, (entry, expected_name) in enumerate(
            zip(manifest, expected_names, strict=True)):
        path = RECORDS_DIR / expected_name
        try:
            info = path.lstat()
        except OSError as exc:
            raise AggregateRefused(f"sealed record {index} is missing") from exc
        if (entry.get("state_index") != index
                or entry.get("record_file") != expected_name
                or not is_sha256(entry.get("record_sha256"))
                or not is_sha256(entry.get("record_internal_sha256"))
                or not _integer(entry.get("record_bytes"), minimum=1)
                or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or (require_root and info.st_uid != 0)
                or info.st_mode & 0o222
                or info.st_size != entry["record_bytes"]
                or os.path.lexists(str(path) + ".partial")):
            raise AggregateRefused(f"sealed record {index} metadata drift")


def verify_inputs(*, require_root: bool = True) -> tuple[dict, ModuleType]:
    controller = load_controller()
    packet = controller.load_packet(
        PACKET_PATH, PACKET_SHA256, expected_git=SOURCE_GIT)
    source_problems = _source_tree_problems(packet)
    if source_problems:
        raise AggregateRefused("; ".join(source_problems))
    final, final_raw = strict_object(FINAL_PATH, label="score-free final")
    if sha256_bytes(final_raw) != FINAL_SHA256:
        raise AggregateRefused("score-free final SHA drift")
    problems = controller.final_problems(
        final, packet=packet, packet_sha256=PACKET_SHA256)
    admission, admission_raw = strict_object(
        ADMISSION_PATH, label="scored execution admission")
    if sha256_bytes(admission_raw) != ADMISSION_SHA256:
        problems.append("scored execution admission file SHA drift")
    if final.get("admission_sha256") != ADMISSION_SHA256:
        problems.append("score-free final admission binding drift")
    problems.extend(controller.admission_problems(
        admission, packet=packet, packet_sha256=PACKET_SHA256, final=final))
    implementation_snapshot = stable_bytes(
        IMPLEMENTATION_REVIEW_PATH, label="implementation review snapshot")
    packet_snapshot = stable_bytes(
        PACKET_REVIEW_PATH, label="packet review snapshot")
    if sha256_bytes(implementation_snapshot) != IMPLEMENTATION_REVIEW_SHA256:
        problems.append("implementation review snapshot SHA drift")
    if sha256_bytes(packet_snapshot) != PACKET_REVIEW_SHA256:
        problems.append("packet review snapshot SHA drift")
    claim = controller.packet_review_claim(
        packet=packet, packet_sha256=PACKET_SHA256)
    review, marker = controller.canonical_review_record(
        commit=final.get("packet_review_commit", ""),
        prefix=controller.PACKET_REVIEW_PREFIX, expected=claim,
        label="S6 V3 packet review")
    if (marker != packet_snapshot
            or review.get("marker_sha256")
            != final.get("packet_review_marker_sha256")):
        problems.append("packet review final/snapshot binding drift")
    terminal = terminal_review()
    manifest = _record_manifest(final)
    _verify_record_metadata(manifest, require_root=require_root)
    if problems:
        raise AggregateRefused("; ".join(sorted(set(problems))))
    return ({
        "packet": packet,
        "final": final,
        "terminal_review": terminal,
        "record_manifest": manifest,
        "record_manifest_sha256": digest(manifest),
    }, controller)


def implementation_review_claim(*, expected_git: str,
                                inputs: Mapping[str, object]) -> dict:
    return {
        "schema": IMPLEMENTATION_REVIEW_SCHEMA,
        "git": expected_git,
        "source_git": SOURCE_GIT,
        "aggregate_script_sha256": sha256_file(SCRIPT),
        "controller_sha256": CONTROLLER_SHA256,
        "scorer_sha256": SCORER_SHA256,
        "design_sha256": DESIGN_SHA256,
        "packet_sha256": PACKET_SHA256,
        "admission_sha256": ADMISSION_SHA256,
        "supervisor_final_sha256": FINAL_SHA256,
        "terminal_review_commit": TERMINAL_REVIEW_COMMIT,
        "record_manifest_sha256": inputs["record_manifest_sha256"],
        "states": STATE_COUNT,
        "one_aggregate_execution_authorized": True,
        "scored_record_access_authorized": True,
        "fresh_screen_execution_authorized": False,
        "retry_authorized": False,
        "resume_authorized": False,
        "extension_authorized": False,
        "report_access_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
    }


def admission_payload(*, expected_git: str, review: Mapping[str, object],
                      inputs: Mapping[str, object]) -> dict:
    value = {
        "schema": ADMISSION_SCHEMA,
        "run_id": AGGREGATE_RUN_ID,
        "git": expected_git,
        "source_git": SOURCE_GIT,
        "implementation_review_commit": review["commit"],
        "implementation_review_marker_sha256": review["marker_sha256"],
        "packet_sha256": PACKET_SHA256,
        "scored_execution_admission_sha256": ADMISSION_SHA256,
        "supervisor_final_sha256": FINAL_SHA256,
        "record_manifest_sha256": inputs["record_manifest_sha256"],
        "nonce": secrets.token_hex(32),
        "created_time_ns": time.time_ns(),
        "one_aggregate_execution_authorized": True,
        "scored_record_access_authorized": True,
        **FALSE_AUTHORITY,
    }
    value["internal_sha256"] = digest(value)
    return value


def admission_problems(value: object, *, expected_git: str,
                       review: Mapping[str, object],
                       inputs: Mapping[str, object]) -> list[str]:
    if not isinstance(value, Mapping):
        return ["aggregate admission is not an object"]
    expected_fields = {
        "schema", "run_id", "git", "source_git",
        "implementation_review_commit",
        "implementation_review_marker_sha256", "packet_sha256",
        "scored_execution_admission_sha256", "supervisor_final_sha256",
        "record_manifest_sha256", "nonce", "created_time_ns",
        "one_aggregate_execution_authorized", "scored_record_access_authorized",
        *FALSE_AUTHORITY, "internal_sha256",
    }
    material = dict(value)
    recorded = material.pop("internal_sha256", None)
    problems = []
    if set(value) != expected_fields:
        problems.append("aggregate admission field population drift")
    if (recorded != digest(material)
            or value.get("schema") != ADMISSION_SCHEMA
            or value.get("run_id") != AGGREGATE_RUN_ID
            or value.get("git") != expected_git
            or value.get("source_git") != SOURCE_GIT
            or value.get("implementation_review_commit") != review.get("commit")
            or value.get("implementation_review_marker_sha256")
            != review.get("marker_sha256")
            or value.get("packet_sha256") != PACKET_SHA256
            or value.get("scored_execution_admission_sha256")
            != ADMISSION_SHA256
            or value.get("supervisor_final_sha256") != FINAL_SHA256
            or value.get("record_manifest_sha256")
            != inputs.get("record_manifest_sha256")
            or not is_sha256(value.get("nonce"))
            or not _integer(value.get("created_time_ns"), minimum=1)
            or value.get("one_aggregate_execution_authorized") is not True
            or value.get("scored_record_access_authorized") is not True
            or any(value.get(field) is not False for field in FALSE_AUTHORITY)):
        problems.append("aggregate admission identity/authority drift")
    return sorted(set(problems))


def _write_all(descriptor: int, raw: bytes) -> None:
    offset = 0
    while offset < len(raw):
        written = os.write(descriptor, raw[offset:])
        if written <= 0:
            raise AggregateRefused("short filesystem write")
        offset += written


def _require_root_directory(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise AggregateRefused(f"aggregate directory {path} is unavailable") \
            from exc
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
            or info.st_mode & 0o022):
        raise AggregateRefused(
            f"aggregate directory {path} is linked, unowned, or writable")


def _require_members(path: Path, expected: set[str]) -> None:
    _require_root_directory(path)
    try:
        members = {child.name for child in path.iterdir()}
    except OSError as exc:
        raise AggregateRefused(f"cannot enumerate aggregate directory {path}") \
            from exc
    if members != expected:
        raise AggregateRefused(f"aggregate directory {path} population drift")


def _validate_gate() -> None:
    _require_members(
        GATE_PATH, {"implementation-review-snapshot.md", "admission.json"})
    if GATE_PATH.stat().st_mode & 0o222:
        raise AggregateRefused("aggregate gate is writable")


def _write_gate(*, marker: bytes, admission: Mapping[str, object]) -> bytes:
    if os.path.lexists(AGGREGATE_ROOT):
        _require_members(AGGREGATE_ROOT, set())
    else:
        AGGREGATE_ROOT.mkdir(mode=0o755, parents=False)
        _require_members(AGGREGATE_ROOT, set())
    if (os.path.lexists(GATE_PATH) or os.path.lexists(OUTPUT_PATH)
            or os.path.lexists(OUTPUT_PARTIAL_PATH)):
        raise AggregateRefused("aggregate execution slot is already consumed")
    try:
        GATE_PATH.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise AggregateRefused("aggregate execution slot is already consumed") from exc
    review_path = GATE_PATH / "implementation-review-snapshot.md"
    admission_path = GATE_PATH / "admission.json"
    try:
        for path, raw in (
                (review_path, marker), (admission_path, canonical(admission))):
            descriptor = os.open(
                path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0), 0o444)
            try:
                _write_all(descriptor, raw)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            path.chmod(0o444)
        directory = os.open(GATE_PATH, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        GATE_PATH.chmod(0o555)
    except BaseException:
        # The directory itself is the spent admission.  Preserve it on error.
        raise
    return canonical(admission)


def _open_records(*, inputs: Mapping[str, object], controller: ModuleType,
                  expected_root_members: set[str] | None = None) \
        -> tuple[list[dict], list[dict]]:
    # This function is called only after the aggregate gate exists.
    _require_members(
        AGGREGATE_ROOT,
        expected_root_members if expected_root_members is not None
        else {GATE_PATH.name})
    _validate_gate()
    design, scorer = controller._load_scorer(inputs["packet"])
    _require_loaded_origins(inputs["packet"])
    records = []
    for entry in inputs["record_manifest"]:
        index = entry["state_index"]
        path = RECORDS_DIR / entry["record_file"]
        raw = stable_bytes(path, label=f"sealed scored record {index}")
        if (len(raw) != entry["record_bytes"]
                or sha256_bytes(raw) != entry["record_sha256"]):
            raise AggregateRefused(f"sealed scored record {index} SHA/size drift")
        record = strict_json(raw)
        if (not isinstance(record, dict)
                or record.get("internal_sha256")
                != entry["record_internal_sha256"]
                or record.get("deal_seed") != entry["deal_seed"]
                or record.get("state_id") != entry["state_id"]):
            raise AggregateRefused(f"sealed scored record {index} identity drift")
        problems = scorer.record_problems(
            record, expected_seed=entry["deal_seed"])
        if problems:
            raise AggregateRefused(
                f"sealed scored record {index}: {'; '.join(problems)}")
        records.append(record)
    if len(records) != STATE_COUNT:
        raise AggregateRefused("sealed scored record population drift")
    selection_rows = design._selection_rows()
    if not isinstance(selection_rows, list) or len(selection_rows) != STATE_COUNT:
        raise AggregateRefused("reviewed selection row population drift")
    return records, selection_rows


def _exact_mean(total: int, observations: int) -> dict:
    divisor = math.gcd(abs(total), observations)
    return {
        "sum": total,
        "observations": observations,
        "fraction": f"{total // divisor}/{observations // divisor}",
    }


def aggregate_records(records: list[dict], *, selection_rows: list[dict]) -> dict:
    if len(records) != STATE_COUNT or len(selection_rows) != STATE_COUNT:
        raise AggregateRefused("aggregate population is not 64 states")
    mode_state: dict[str, list[dict[str, int]]] = {mode: [] for mode in MODES}
    selected_differences = {"lead_source": 0, "joint_bury_source": 0}
    groups = []
    for index, (record, selection_row) in enumerate(
            zip(records, selection_rows, strict=True)):
        if (record.get("deal_seed") != selection_row.get("deal_seed")
                or selection_row.get("selection_group") not in GROUPS):
            raise AggregateRefused(f"aggregate state {index} selection identity drift")
        groups.append(selection_row["selection_group"])
        selected = record["selection"]["selected_indices"]
        selected_differences["lead_source"] += int(
            selected["incumbent_widened"] != selected["incumbent_live"])
        selected_differences["joint_bury_source"] += int(
            selected["expanded"] != selected["incumbent_widened"])
        for mode in MODES:
            slot_sums = {slot: 0 for slot in SLOTS}
            rows = record["report"]["modes"][mode]["rows"]
            if len(rows) != REPORT_WORLDS:
                raise AggregateRefused(f"aggregate state {index} report rows drift")
            for row in rows:
                outcomes = row["slot_outcomes"]
                if [outcome["slot"] for outcome in outcomes] != list(SLOTS):
                    raise AggregateRefused(
                        f"aggregate state {index} slot order drift")
                for outcome in outcomes:
                    points = outcome["attacker_points"]
                    if not _integer(points, minimum=0):
                        raise AggregateRefused(
                            f"aggregate state {index} attacker points drift")
                    slot_sums[outcome["slot"]] -= points
            mode_state[mode].append(slot_sums)
    modes = {}
    for mode in MODES:
        slot_totals = {
            slot: sum(state[slot] for state in mode_state[mode])
            for slot in SLOTS
        }
        contrasts = {}
        for contrast, (treatment, control) in CONTRASTS.items():
            values = [state[treatment] - state[control]
                      for state in mode_state[mode]]
            by_group = {}
            for group in GROUPS:
                selected = [value for value, observed_group in zip(
                    values, groups, strict=True) if observed_group == group]
                by_group[group] = {
                    **_exact_mean(sum(selected), len(selected) * REPORT_WORLDS),
                    "states": len(selected),
                    "positive_states": sum(value > 0 for value in selected),
                    "zero_states": sum(value == 0 for value in selected),
                    "negative_states": sum(value < 0 for value in selected),
                }
            contrasts[contrast] = {
                **_exact_mean(sum(values), STATE_COUNT * REPORT_WORLDS),
                "states": STATE_COUNT,
                "positive_states": sum(value > 0 for value in values),
                "zero_states": sum(value == 0 for value in values),
                "negative_states": sum(value < 0 for value in values),
                "by_selection_group": by_group,
            }
        modes[mode] = {
            "slots": {
                slot: _exact_mean(total, STATE_COUNT * REPORT_WORLDS)
                for slot, total in slot_totals.items()
            },
            "contrasts": contrasts,
        }
    primary = ("lead_source", "joint_bury_source")
    criteria = {
        "all_64_states_and_exact_work_complete": True,
        "positive_state_threshold": POSITIVE_STATE_GATE,
        "positive_state_threshold_met": {
            gate: modes["baseline"]["contrasts"][gate]["positive_states"]
            >= POSITIVE_STATE_GATE for gate in primary
        },
        "baseline_report_mean_strictly_positive": {
            gate: modes["baseline"]["contrasts"][gate]["sum"] > 0
            for gate in primary
        },
        "baseline_selection_group_means_nonnegative": {
            gate: {
                group: modes["baseline"]["contrasts"][gate]
                ["by_selection_group"][group]["sum"] >= 0
                for group in GROUPS
            } for gate in primary
        },
        "alternative_continuation_means_nonnegative": {
            mode: {
                gate: modes[mode]["contrasts"][gate]["sum"] >= 0
                for gate in primary
            } for mode in ("all_boss", "boss_near")
        },
        "at_least_one_selected_slot_differs_from_control": (
            sum(selected_differences.values()) > 0),
    }
    booleans = [criteria["all_64_states_and_exact_work_complete"]]
    booleans.extend(criteria["positive_state_threshold_met"].values())
    booleans.extend(criteria["baseline_report_mean_strictly_positive"].values())
    booleans.extend(
        value for item in criteria[
            "baseline_selection_group_means_nonnegative"].values()
        for value in item.values())
    booleans.extend(
        value for item in criteria[
            "alternative_continuation_means_nonnegative"].values()
        for value in item.values())
    booleans.append(criteria["at_least_one_selected_slot_differs_from_control"])
    criteria["all_requirements_met"] = all(booleans)
    return {
        "states": STATE_COUNT,
        "report_worlds_per_state": REPORT_WORLDS,
        "observations_per_mode_slot": STATE_COUNT * REPORT_WORLDS,
        "selected_candidate_differences": selected_differences,
        "modes": modes,
        "criteria": criteria,
        "decision": (
            "ADVANCE_TO_FRESH_SCREEN_DESIGN"
            if criteria["all_requirements_met"] else
            "SELECT_NONE_FOR_FRESH_SCREEN_DESIGN"),
    }


def result_payload(*, expected_git: str, review: Mapping[str, object],
                   inputs: Mapping[str, object], admission_raw: bytes,
                   records: list[dict], selection_rows: list[dict]) -> dict:
    aggregate = aggregate_records(records, selection_rows=selection_rows)
    value = {
        "schema": RESULT_SCHEMA,
        "run_id": AGGREGATE_RUN_ID,
        "git": expected_git,
        "source_git": SOURCE_GIT,
        "implementation_review_commit": review["commit"],
        "implementation_review_marker_sha256": review["marker_sha256"],
        "packet_sha256": PACKET_SHA256,
        "scored_execution_admission_sha256": ADMISSION_SHA256,
        "supervisor_final_sha256": FINAL_SHA256,
        "terminal_review_commit": TERMINAL_REVIEW_COMMIT,
        "record_manifest_sha256": inputs["record_manifest_sha256"],
        "aggregate_admission_sha256": sha256_bytes(admission_raw),
        "records_opened": STATE_COUNT,
        "records_remain_immutable": True,
        "exploration_only": True,
        "confirmatory_inference": False,
        "statistics": aggregate,
        "authority": dict(FALSE_AUTHORITY),
    }
    value["internal_sha256"] = digest(value)
    return value


def result_problems(value: object, *, expected: Mapping[str, object]) -> list[str]:
    if not isinstance(value, Mapping):
        return ["aggregate result is not an object"]
    material = dict(value)
    observed = material.pop("internal_sha256", None)
    problems = []
    if observed != digest(material):
        problems.append("aggregate result internal digest drift")
    if value != expected:
        problems.append("aggregate result reconstruction drift")
    if (value.get("schema") != RESULT_SCHEMA
            or value.get("records_opened") != STATE_COUNT
            or value.get("records_remain_immutable") is not True
            or value.get("exploration_only") is not True
            or value.get("confirmatory_inference") is not False
            or value.get("authority") != FALSE_AUTHORITY):
        problems.append("aggregate result identity/authority drift")
    return sorted(set(problems))


def _write_output(value: Mapping[str, object]) -> bytes:
    raw = canonical(value)
    _require_members(AGGREGATE_ROOT, {GATE_PATH.name})
    if os.path.lexists(OUTPUT_PATH) or os.path.lexists(OUTPUT_PARTIAL_PATH):
        raise AggregateRefused("aggregate output slot is already consumed")
    descriptor = os.open(
        OUTPUT_PARTIAL_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0), 0o444)
    try:
        _write_all(descriptor, raw)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.link(OUTPUT_PARTIAL_PATH, OUTPUT_PATH)
    OUTPUT_PARTIAL_PATH.unlink()
    OUTPUT_PATH.chmod(0o444)
    if stable_bytes(OUTPUT_PATH, label="published aggregate") != raw:
        raise AggregateRefused("published aggregate bytes drift")
    return raw


def review_claim_command(args: argparse.Namespace) -> None:
    require_fresh_process()
    require_clean_exact_git(args.expected_git)
    inputs, _controller = verify_inputs()
    claim = implementation_review_claim(
        expected_git=args.expected_git, inputs=inputs)
    print(IMPLEMENTATION_REVIEW_PREFIX + canonical(claim).decode().rstrip())


def verify_inputs_command(args: argparse.Namespace) -> None:
    require_fresh_process()
    require_clean_exact_git(args.expected_git)
    inputs, _controller = verify_inputs()
    print(json.dumps({
        "verified": True,
        "git": args.expected_git,
        "source_git": SOURCE_GIT,
        "packet_sha256": PACKET_SHA256,
        "supervisor_final_sha256": FINAL_SHA256,
        "states": STATE_COUNT,
        "record_manifest_sha256": inputs["record_manifest_sha256"],
        "scored_records_opened": False,
        "aggregate_execution_authorized": False,
    }, sort_keys=True))


def run_command(args: argparse.Namespace) -> None:
    require_fresh_process()
    if os.geteuid() != 0:
        raise AggregateRefused("aggregate execution requires root")
    require_clean_exact_git(args.expected_git)
    inputs, controller = verify_inputs()
    claim = implementation_review_claim(
        expected_git=args.expected_git, inputs=inputs)
    review, marker = _review_record(
        commit=args.review_commit, prefix=IMPLEMENTATION_REVIEW_PREFIX,
        expected=claim, label="S6 aggregate implementation/input review")
    admission = admission_payload(
        expected_git=args.expected_git, review=review, inputs=inputs)
    problems = admission_problems(
        admission, expected_git=args.expected_git,
        review=review, inputs=inputs)
    if problems:
        raise AggregateRefused("; ".join(problems))
    admission_raw = _write_gate(marker=marker, admission=admission)
    records, selection_rows = _open_records(
        inputs=inputs, controller=controller)
    result = result_payload(
        expected_git=args.expected_git, review=review, inputs=inputs,
        admission_raw=admission_raw, records=records,
        selection_rows=selection_rows)
    raw = _write_output(result)
    print(json.dumps({
        "status": "COMPLETE_AWAITING_AGGREGATE_RESULT_REVIEW",
        "aggregate_sha256": sha256_bytes(raw),
        "records_opened": STATE_COUNT,
        "decision_sealed_until_review": True,
        "strength_claim": False,
    }, sort_keys=True))


def _reconstruct_output(args: argparse.Namespace) -> tuple[dict, bytes, dict]:
    require_fresh_process()
    require_clean_exact_git(args.expected_git)
    inputs, controller = verify_inputs()
    claim = implementation_review_claim(
        expected_git=args.expected_git, inputs=inputs)
    review, marker = _review_record(
        commit=args.review_commit, prefix=IMPLEMENTATION_REVIEW_PREFIX,
        expected=claim, label="S6 aggregate implementation/input review")
    _require_members(AGGREGATE_ROOT, {GATE_PATH.name, OUTPUT_PATH.name})
    _validate_gate()
    review_raw = stable_bytes(
        GATE_PATH / "implementation-review-snapshot.md",
        label="aggregate review snapshot")
    if review_raw != marker:
        raise AggregateRefused("aggregate review snapshot drift")
    admission, admission_raw = strict_object(
        GATE_PATH / "admission.json", label="aggregate admission")
    problems = admission_problems(
        admission, expected_git=args.expected_git,
        review=review, inputs=inputs)
    if problems:
        raise AggregateRefused("; ".join(problems))
    records, selection_rows = _open_records(
        inputs=inputs, controller=controller,
        expected_root_members={GATE_PATH.name, OUTPUT_PATH.name})
    expected = result_payload(
        expected_git=args.expected_git, review=review, inputs=inputs,
        admission_raw=admission_raw, records=records,
        selection_rows=selection_rows)
    value, raw = strict_object(OUTPUT_PATH, label="aggregate result")
    if sha256_bytes(raw) != args.expected_result_sha256:
        raise AggregateRefused("aggregate result file SHA drift")
    result_issues = result_problems(value, expected=expected)
    if result_issues:
        raise AggregateRefused("; ".join(result_issues))
    return value, raw, inputs


def verify_result_command(args: argparse.Namespace) -> None:
    value, raw, _inputs = _reconstruct_output(args)
    print(json.dumps({
        "verified": True,
        "aggregate_sha256": sha256_bytes(raw),
        "records_reopened": STATE_COUNT,
        "decision": value["statistics"]["decision"],
        "criteria": value["statistics"]["criteria"],
        "fresh_screen_execution_authorized": False,
        "strength_claim": False,
    }, sort_keys=True))


def result_review_claim_command(args: argparse.Namespace) -> None:
    value, raw, _inputs = _reconstruct_output(args)
    decision = value["statistics"]["decision"]
    claim = {
        "schema": RESULT_REVIEW_SCHEMA,
        "git": args.expected_git,
        "source_git": SOURCE_GIT,
        "aggregate_sha256": sha256_bytes(raw),
        "aggregate_internal_sha256": value["internal_sha256"],
        "record_manifest_sha256": value["record_manifest_sha256"],
        "decision": decision,
        "independent_review": True,
        "fresh_screen_design_authorized": (
            decision == "ADVANCE_TO_FRESH_SCREEN_DESIGN"),
        "fresh_screen_execution_authorized": False,
        "retry_authorized": False,
        "resume_authorized": False,
        "extension_authorized": False,
        "report_access_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    print(RESULT_REVIEW_PREFIX + canonical(claim).decode().rstrip())


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    commands = value.add_subparsers(dest="command", required=True)
    verify_inputs_parser = commands.add_parser("verify-inputs")
    verify_inputs_parser.add_argument("--expected-git", required=True)
    claim = commands.add_parser("aggregate-review-claim")
    claim.add_argument("--expected-git", required=True)
    run = commands.add_parser("run")
    run.add_argument("--expected-git", required=True)
    run.add_argument("--review-commit", required=True)
    for name in ("verify-result", "result-review-claim"):
        command = commands.add_parser(name)
        command.add_argument("--expected-git", required=True)
        command.add_argument("--review-commit", required=True)
        command.add_argument("--expected-result-sha256", required=True)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "verify-inputs":
        verify_inputs_command(args)
    elif args.command == "aggregate-review-claim":
        review_claim_command(args)
    elif args.command == "run":
        run_command(args)
    elif args.command == "verify-result":
        verify_result_command(args)
    else:
        result_review_claim_command(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AggregateRefused as exc:
        raise SystemExit(f"REFUSED: {exc}") from exc

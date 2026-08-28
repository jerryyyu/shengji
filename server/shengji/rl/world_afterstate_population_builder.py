"""Build, publish, and independently reopen the exact E3/E4 population.

The builder reads only reviewed complete-state trajectories and simulator
states selected before continuation outcomes exist.  It writes a public
manifest, a separately sealed private audit tree, deterministic source
schedules, and one closed population packet.  It never runs continuations,
trains a model, or opens report outcomes.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate_experiment import reviewed_teacher_binding
from .world_afterstate_population import (
    build_population_audit_manifest, build_population_manifest,
    reopen_population_audit_manifest, select_population_groups,
    validate_population_audit_manifest, validate_population_manifest)
from .world_afterstate_population_packet import (
    build_population_packet, validate_population_packet)
from .world_afterstate_sources import (
    StateGroupMaterialV0, build_round_source_schedule,
    capture_scheduled_round_materials, pt_sol_state_materials,
    validate_round_source_schedule)


PUBLIC_NAME = "population.json"
AUDIT_MANIFEST_NAME = "audit-manifest.json"
PACKET_NAME = "packet.json"
PRODUCTION_SCHEDULE_NAME = "schedules/production-policy.json"
MECHANICS_SCHEDULE_NAME = "schedules/mechanics-hard.json"
AUDIT_ROOT_NAME = "audits"


class WorldAfterstatePopulationBuildError(ValueError):
    """A source file, inventory, publication, or reopen boundary drifted."""


@dataclass(frozen=True)
class PopulationBuildV0:
    population_manifest: dict[str, Any]
    audit_manifest: dict[str, Any]
    production_schedule: dict[str, Any]
    mechanics_schedule: dict[str, Any]
    packet: dict[str, Any]
    materials: tuple[StateGroupMaterialV0, ...]


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(raw: bytes, label: str) -> dict[str, Any]:
    if type(raw) is not bytes:
        raise WorldAfterstatePopulationBuildError(
            f"{label} byte type drift")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstatePopulationBuildError(
            f"{label} is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstatePopulationBuildError(
            f"{label} is not canonical JSON")
    return value


def _stable_source_read(path: Path) -> bytes:
    if not isinstance(path, Path) or path.is_symlink():
        raise WorldAfterstatePopulationBuildError(
            "PT-Sol private path identity drift")
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            raw = handle.read()
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise WorldAfterstatePopulationBuildError(
            "PT-Sol private file cannot be read") from exc
    identity = lambda value: (
        value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
        value.st_ctime_ns)
    if identity(before) != identity(after) or before.st_size != len(raw) \
            or before.st_nlink != 1 or not stat.S_ISREG(before.st_mode) \
            or stat.S_IMODE(before.st_mode) not in (0o400, 0o600):
        raise WorldAfterstatePopulationBuildError(
            "PT-Sol private file is mutable or changed while read")
    return raw


def load_pt_sol_state_materials(
        report_raw: bytes, private_root: Path, *,
        progress: Callable[[str, int, int], None] | None = None) \
        -> tuple[tuple[StateGroupMaterialV0, ...], dict[str, str]]:
    """Open the reviewed 52-record private inventory exactly once."""
    report = _canonical(report_raw, "PT-Sol report")
    binding = reviewed_teacher_binding(report_raw, model="gpt-5.6-sol")
    records = report.get("records")
    if type(records) is not list or len(records) != 52 \
            or not isinstance(private_root, Path) \
            or not private_root.is_dir() or private_root.is_symlink():
        raise WorldAfterstatePopulationBuildError(
            "PT-Sol private inventory identity drift")
    paths = sorted(path for path in private_root.rglob("*") if path.is_file())
    if len(paths) != 52 \
            or any(path.suffix != ".json" for path in paths):
        raise WorldAfterstatePopulationBuildError(
            "PT-Sol private file population drift")
    by_sha: dict[str, bytes] = {}
    for path in paths:
        raw = _stable_source_read(path)
        digest = _sha_bytes(raw)
        if digest in by_sha:
            raise WorldAfterstatePopulationBuildError(
                "PT-Sol private duplicate digest")
        by_sha[digest] = raw
    materials = []
    claimed = set()
    ordered_records = sorted(
        records, key=lambda row: row.get("root_sha256", ""))
    for record_index, record in enumerate(ordered_records, start=1):
        if type(record) is not dict:
            raise WorldAfterstatePopulationBuildError(
                "PT-Sol public record type drift")
        digest = record.get("private_evidence_sha256")
        if type(digest) is not str or digest in claimed \
                or digest not in by_sha:
            raise WorldAfterstatePopulationBuildError(
                "PT-Sol private/public binding drift")
        claimed.add(digest)
        materials.extend(pt_sol_state_materials(by_sha[digest], record))
        if progress is not None:
            progress("pt-sol-import", record_index, len(ordered_records))
    if claimed != set(by_sha) or not materials:
        raise WorldAfterstatePopulationBuildError(
            "PT-Sol private inventory completeness drift")
    return tuple(materials), binding


def _deduplicate_materials(
        values: Sequence[StateGroupMaterialV0]) \
        -> tuple[StateGroupMaterialV0, ...]:
    if type(values) not in (list, tuple):
        raise WorldAfterstatePopulationBuildError(
            "population material type drift")
    rows: dict[str, StateGroupMaterialV0] = {}
    decisions: dict[str, str] = {}
    for value in values:
        if type(value) is not StateGroupMaterialV0:
            raise WorldAfterstatePopulationBuildError(
                "population material identity drift")
        value.validate()
        group = value.group
        key = group["state_group_id"]
        decision = group["decision_sha256"]
        previous = rows.get(key)
        previous_key = decisions.get(decision)
        if previous is not None:
            if canonical_json_bytes(previous.group) \
                    != canonical_json_bytes(group) \
                    or previous.audit_raws != value.audit_raws:
                raise WorldAfterstatePopulationBuildError(
                    "population repeated state changed bytes")
            continue
        if previous_key is not None:
            raise WorldAfterstatePopulationBuildError(
                "population actor-visible decision maps to multiple worlds")
        rows[key] = value
        decisions[decision] = key
    return tuple(rows[key] for key in sorted(rows))


def _scheduled_materials(
        schedule: Mapping[str, Any], *,
        progress: Callable[[str, int, int], None] | None = None) \
        -> tuple[StateGroupMaterialV0, ...]:
    validate_round_source_schedule(schedule)
    rows = []
    for index, spec in enumerate(schedule["rows"], start=1):
        rows.extend(capture_scheduled_round_materials(spec))
        if progress is not None:
            progress(f"{schedule['source']}-capture", index,
                     len(schedule["rows"]))
    return tuple(rows)


def build_outcome_blind_population(
        *, source_git: str, pt_sol_report_raw: bytes,
        pt_sol_private_root: Path,
        progress: Callable[[str, int, int], None] | None = None) \
        -> PopulationBuildV0:
    """Generate the exact 520 groups and their sealed pre-outcome packet."""
    pt_materials, teacher = load_pt_sol_state_materials(
        pt_sol_report_raw, pt_sol_private_root, progress=progress)
    production = build_round_source_schedule("production-policy")
    mechanics = build_round_source_schedule("mechanics-hard")
    inventory = _deduplicate_materials(tuple(
        _scheduled_materials(production, progress=progress)
        + _scheduled_materials(mechanics, progress=progress) + pt_materials))
    selected_groups = select_population_groups(
        tuple(material.group for material in inventory))
    by_id = {material.group["state_group_id"]: material
             for material in inventory}
    selected = tuple(by_id[group["state_group_id"]]
                     for group in selected_groups)
    public = build_population_manifest(
        tuple(material.group for material in selected))
    audit = build_population_audit_manifest(
        public, tuple((material.group, material.audit_raws)
                      for material in selected))
    public_raw = canonical_json_bytes(public)
    audit_raw = canonical_json_bytes(audit)
    production_raw = canonical_json_bytes(production)
    mechanics_raw = canonical_json_bytes(mechanics)
    packet = build_population_packet(
        source_git=source_git, population_manifest_raw=public_raw,
        audit_manifest_raw=audit_raw,
        production_schedule_raw=production_raw,
        mechanics_schedule_raw=mechanics_raw,
        pt_sol0_external_sha256=teacher["external_sha256"],
        pt_sol0_report_sha256=teacher["report_sha256"],
        pt_sol0_execution_git=teacher["execution_git"])
    return PopulationBuildV0(
        population_manifest=public, audit_manifest=audit,
        production_schedule=production, mechanics_schedule=mechanics,
        packet=packet, materials=selected)


def _write_once(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o400)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_population_build(target: Path, build: PopulationBuildV0) -> None:
    if not isinstance(target, Path) or type(build) is not PopulationBuildV0:
        raise WorldAfterstatePopulationBuildError(
            "population publication request drift")
    parent = target.resolve().parent
    resolved = parent / target.name
    partial = parent / f".{target.name}.partial"
    parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists() or resolved.is_symlink() \
            or partial.exists() or partial.is_symlink():
        raise WorldAfterstatePopulationBuildError(
            "population publication namespace occupied")
    partial.mkdir(mode=0o700)
    try:
        _write_once(partial / PUBLIC_NAME,
                    canonical_json_bytes(build.population_manifest))
        _write_once(partial / AUDIT_MANIFEST_NAME,
                    canonical_json_bytes(build.audit_manifest))
        _write_once(partial / PRODUCTION_SCHEDULE_NAME,
                    canonical_json_bytes(build.production_schedule))
        _write_once(partial / MECHANICS_SCHEDULE_NAME,
                    canonical_json_bytes(build.mechanics_schedule))
        _write_once(partial / PACKET_NAME, canonical_json_bytes(build.packet))
        by_id = {material.group["state_group_id"]: material
                 for material in build.materials}
        for row in build.audit_manifest["rows"]:
            raw = by_id[row["state_group_id"]].audit_raws[
                row["candidate_index"]]
            _write_once(partial / AUDIT_ROOT_NAME / row["relative_path"], raw)
        _ = reopen_population_build(partial)
        for directory in sorted(
                (path for path in partial.rglob("*") if path.is_dir()),
                key=lambda path: len(path.parts), reverse=True):
            os.chmod(directory, 0o500)
            _fsync_directory(directory)
        _fsync_directory(partial)
        os.rename(partial, resolved)
        os.chmod(resolved, 0o500)
        _fsync_directory(resolved)
        _fsync_directory(parent)
    except BaseException:
        # Preserve the partial tree as a fail-stop forensic artifact.
        raise


def _sealed_read(path: Path) -> bytes:
    if path.is_symlink():
        raise WorldAfterstatePopulationBuildError(
            "population artifact path is a symlink")
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        raw = handle.read()
        after = os.fstat(handle.fileno())
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
            before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
            after.st_ctime_ns) or before.st_size != len(raw) \
            or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o400 \
            or not stat.S_ISREG(before.st_mode):
        raise WorldAfterstatePopulationBuildError(
            "population artifact is mutable or changed while read")
    return raw


def reopen_population_build(root: Path) -> dict[str, Any]:
    if not isinstance(root, Path) or not root.is_dir() or root.is_symlink():
        raise WorldAfterstatePopulationBuildError(
            "population root identity drift")
    public_raw = _sealed_read(root / PUBLIC_NAME)
    audit_raw = _sealed_read(root / AUDIT_MANIFEST_NAME)
    packet_raw = _sealed_read(root / PACKET_NAME)
    production_raw = _sealed_read(root / PRODUCTION_SCHEDULE_NAME)
    mechanics_raw = _sealed_read(root / MECHANICS_SCHEDULE_NAME)
    public = _canonical(public_raw, "population manifest")
    audit = _canonical(audit_raw, "population audit manifest")
    packet = _canonical(packet_raw, "population packet")
    production = _canonical(production_raw, "production schedule")
    mechanics = _canonical(mechanics_raw, "mechanics schedule")
    validate_population_manifest(public)
    validate_population_audit_manifest(audit, public)
    validate_round_source_schedule(production)
    validate_round_source_schedule(mechanics)
    validate_population_packet(
        packet, population_manifest_raw=public_raw,
        audit_manifest_raw=audit_raw,
        production_schedule_raw=production_raw,
        mechanics_schedule_raw=mechanics_raw)
    reopened = reopen_population_audit_manifest(
        audit, public, root / AUDIT_ROOT_NAME)
    expected_files = {
        root / PUBLIC_NAME, root / AUDIT_MANIFEST_NAME, root / PACKET_NAME,
        root / PRODUCTION_SCHEDULE_NAME, root / MECHANICS_SCHEDULE_NAME,
    } | {root / AUDIT_ROOT_NAME / row["relative_path"]
         for row in audit["rows"]}
    observed_files = {path for path in root.rglob("*") if path.is_file()}
    if observed_files != expected_files:
        raise WorldAfterstatePopulationBuildError(
            "population publication file set drift")
    return {
        "packet_sha256": packet["packet_sha256"],
        "population_manifest_sha256": public["manifest_sha256"],
        "audit_manifest_sha256": audit["manifest_sha256"],
        "group_count": public["group_count"],
        "candidate_count": public["candidate_count"],
        "private_group_count": len(reopened),
        "outcome_opened": False,
    }


__all__ = [
    "PopulationBuildV0", "WorldAfterstatePopulationBuildError",
    "build_outcome_blind_population", "load_pt_sol_state_materials",
    "publish_population_build", "reopen_population_build",
]

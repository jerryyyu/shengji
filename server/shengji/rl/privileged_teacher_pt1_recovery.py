"""One-shot terminal recovery for a fully sealed PT1 execution.

The recovery lane is deliberately narrower than scientific execution.  It
never captures or evaluates a state.  It binds one terminal failure root, all
416 immutable group byte hashes, and one external review marker before opening
any score/action record.  The source root remains untouched; the sole
preregistered aggregate is written into a fresh recovery namespace.
"""

from __future__ import annotations

import copy
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
import stat
from typing import Mapping, Sequence

from .privileged_teacher_pt0 import canonical_json_bytes
from .privileged_teacher_pt1_execution import (
    AUTHORITIES, DEADLINE_NAME, FAILURE_NAME, FREEZE_NAME, GROUP_DIR,
    MANIFEST_NAME, PACKET_NAME, PROGRESS_NAME, REVIEW_LEDGER,
    SCIENTIFIC_CAP_KEYS, PT1ExecutionError, PT1ExecutionFreeze,
    _authenticate_review_provenance, _canonical_load, _git_sha, _hash_bytes,
    _fsync_dir, _require_owned_directory, _resource_cap_overages, _resource_totals,
    _runtime_identity, _sha, _source_identity, _validate_group_population,
    _validate_resource_overages, _verify_deadline_receipt,
    _verify_group_bytes, authenticate_review_marker, verify_freeze,
    _write_once,
)
from .privileged_teacher_pt1_natural import TARGET_STATE_COUNT, NaturalPT1Design
from .privileged_teacher_pt1_statistics import (
    TOTAL_RECORD_COUNT, reduce_reopened_pt1_statistics,
    verify_statistics_report,
)


RECOVERY_FREEZE_SCHEMA = "privileged-teacher-pt1-terminal-recovery-freeze-v1"
RECOVERY_REVIEW_SCHEMA = "privileged-teacher-pt1-terminal-recovery-review-v1"
RECOVERY_ATTEMPT_SCHEMA = "privileged-teacher-pt1-terminal-recovery-attempt-v1"
RECOVERY_PACKET_SCHEMA = "privileged-teacher-pt1-terminal-recovery-packet-v1"
RECOVERY_MANIFEST_SCHEMA = "privileged-teacher-pt1-terminal-recovery-manifest-v1"
RECOVERY_FAILURE_SCHEMA = "privileged-teacher-pt1-terminal-recovery-failure-v1"
RECOVERY_STATUS = "RECOVERED_TERMINAL"
RECOVERY_FREEZE_NAME = "recovery-freeze.json"
RECOVERY_ATTEMPT_NAME = "attempt.json"
RECOVERY_FAILURE_NAME = "failure.json"
RECOVERY_SOURCE_PATHS = (
    "server/shengji/rl/privileged_teacher_pt1_recovery.py",
    "server/scripts/privileged_teacher_pt1_recovery.py",
)


class PT1RecoveryError(PT1ExecutionError):
    """The terminal-only recovery refused a source, identity or output."""


def _safe_bytes(path: Path, label: str, *, modes: Sequence[int]) -> bytes:
    """Read one stable, owned, non-linked file at an allowed exact mode."""
    try:
        before = path.lstat()
        if (path.is_symlink() or not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.geteuid() or before.st_nlink != 1
                or stat.S_IMODE(before.st_mode) not in modes):
            raise PT1RecoveryError(f"{label} safe-file drift")
        raw = path.read_bytes()
        after = path.lstat()
    except OSError as exc:
        raise PT1RecoveryError(f"{label} unavailable") from exc
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size,
                              value.st_mtime_ns, value.st_nlink, value.st_mode)
    if identity(before) != identity(after) or len(raw) != before.st_size:
        raise PT1RecoveryError(f"{label} changed while read")
    return raw


def _recovery_source_identity(repo_root: Path | None = None) -> dict[str, object]:
    root = repo_root or Path(__file__).resolve().parents[3]
    base = _source_identity(root)
    files = list(base["files"])
    for relative in RECOVERY_SOURCE_PATHS:
        path = root / relative
        if not path.is_file():
            raise PT1RecoveryError("recovery source file population incomplete")
        files.append({"path": relative, "sha256": _hash_bytes(path.read_bytes())})
    return {"git_head": base["git_head"], "source_tree_dirty": False,
            "files": files,
            "files_sha256": _hash_bytes(canonical_json_bytes(files))}


def _group_tree_sha256(group_hashes: Sequence[str]) -> str:
    if len(group_hashes) != TARGET_STATE_COUNT:
        raise PT1RecoveryError("recovery group population must contain 416 hashes")
    rows = []
    for index, value in enumerate(group_hashes):
        _sha(value, f"recovery group {index}")
        rows.append([index, value])
    return _hash_bytes(canonical_json_bytes(rows))


def _recovery_marker_claim(raw: bytes) -> dict[str, object]:
    value = _canonical_load(raw, "recovery review marker")
    fields = {"schema", "source_git", "source_execution_freeze_sha256",
              "source_failure_sha256", "source_progress_sha256",
              "source_deadline_sha256", "source_group_tree_sha256",
              "source_review_commit", "runtime_sha256",
              "recovery_evidence_root", "authority"}
    if (not isinstance(value, dict) or set(value) != fields
            or value.get("schema") != RECOVERY_REVIEW_SCHEMA
            or value.get("authority") != AUTHORITIES
            or type(value.get("recovery_evidence_root")) is not str
            or not os.path.isabs(value["recovery_evidence_root"])):
        raise PT1RecoveryError("recovery review marker fields drift")
    _git_sha(value["source_git"], "recovery review source")
    _git_sha(value["source_review_commit"], "recovery source review commit")
    for name in ("source_execution_freeze_sha256", "source_failure_sha256",
                 "source_progress_sha256", "source_deadline_sha256",
                 "source_group_tree_sha256", "runtime_sha256"):
        _sha(value[name], f"recovery review {name}")
    return value


def _validate_failed_source_root(source_root: Path) -> dict[str, object]:
    if source_root.is_symlink():
        raise PT1RecoveryError("source execution root symlink refused")
    _require_owned_directory(source_root, "source execution root")
    expected = {FREEZE_NAME, PROGRESS_NAME, DEADLINE_NAME, FAILURE_NAME,
                GROUP_DIR}
    if {path.name for path in source_root.iterdir()} != expected:
        raise PT1RecoveryError("source execution namespace is not closed")
    groups = source_root / GROUP_DIR
    _require_owned_directory(groups, "source execution group directory")
    names = sorted(path.name for path in groups.iterdir())
    expected_names = [f"group-{index:04d}.json"
                      for index in range(TARGET_STATE_COUNT)]
    if names != expected_names:
        raise PT1RecoveryError("source execution group namespace is not closed")

    freeze_raw = _safe_bytes(source_root / FREEZE_NAME, "source freeze",
                             modes=(0o400,))
    source_freeze = verify_freeze(freeze_raw)
    if Path(source_freeze.evidence_root).resolve() != source_root.resolve():
        raise PT1RecoveryError("source freeze root binding drift")
    _verify_deadline_receipt(source_freeze, source_root)
    progress_raw = _safe_bytes(source_root / PROGRESS_NAME, "source progress",
                               modes=(0o600,))
    progress = _canonical_load(progress_raw, "source progress")
    expected_progress = {
        "schema": "privileged-teacher-pt1-execution-progress-v1",
        "freeze_sha256": _hash_bytes(freeze_raw),
        "completed_units": TARGET_STATE_COUNT,
        "total_units": TARGET_STATE_COUNT,
        "percent_basis_points": 10_000,
        "eta_nanoseconds": 0,
        "status": "FAILED",
        "authority": dict(AUTHORITIES),
    }
    if progress != expected_progress:
        raise PT1RecoveryError("source execution is not exact 416/416 FAILED")
    failure_raw = _safe_bytes(source_root / FAILURE_NAME, "source failure",
                              modes=(0o400,))
    failure = _canonical_load(failure_raw, "source failure")
    failure_fields = {
        "schema", "freeze_sha256", "failure_code", "completed_units",
        "total_units", "wave_start", "wave_stop", "resource_overages",
        "score_or_action_bytes_persisted", "retry_authorized", "authority"}
    if (not isinstance(failure, dict) or set(failure) != failure_fields
            or failure.get("schema")
            != "privileged-teacher-pt1-execution-failure-v2"
            or failure.get("freeze_sha256") != _hash_bytes(freeze_raw)
            or failure.get("failure_code") != "cli_failure"
            or failure.get("completed_units") != TARGET_STATE_COUNT
            or failure.get("total_units") != TARGET_STATE_COUNT
            or failure.get("wave_start") is not None
            or failure.get("wave_stop") is not None
            or failure.get("score_or_action_bytes_persisted") is not False
            or failure.get("retry_authorized") is not False
            or failure.get("authority") != AUTHORITIES
            or _validate_resource_overages(
                failure.get("resource_overages")) != ()):
        raise PT1RecoveryError("source execution failure receipt drift")
    deadline_raw = _safe_bytes(source_root / DEADLINE_NAME, "source deadline",
                               modes=(0o400,))
    group_hashes = tuple(_hash_bytes(_safe_bytes(
        groups / name, f"source {name}", modes=(0o400,)))
        for name in expected_names)
    return {
        "source_freeze": source_freeze,
        "freeze_sha256": _hash_bytes(freeze_raw),
        "failure_sha256": _hash_bytes(failure_raw),
        "progress_sha256": _hash_bytes(progress_raw),
        "deadline_sha256": _hash_bytes(deadline_raw),
        "group_hashes": group_hashes,
        "group_tree_sha256": _group_tree_sha256(group_hashes),
    }


@dataclass(frozen=True)
class PT1TerminalRecoveryFreeze:
    source_execution_freeze_sha256: str
    source_failure_sha256: str
    source_progress_sha256: str
    source_deadline_sha256: str
    source_group_hashes: tuple[str, ...]
    source_group_tree_sha256: str
    source_evidence_root: str
    recovery_evidence_root: str
    source_review_commit: str
    source: Mapping[str, object]
    runtime: Mapping[str, object]
    review_marker_sha256: str
    review_marker: Mapping[str, object]
    authority: Mapping[str, bool]
    schema: str = RECOVERY_FREEZE_SCHEMA

    def __post_init__(self) -> None:
        for value, label in (
                (self.source_execution_freeze_sha256, "source freeze"),
                (self.source_failure_sha256, "source failure"),
                (self.source_progress_sha256, "source progress"),
                (self.source_deadline_sha256, "source deadline"),
                (self.source_group_tree_sha256, "source group tree"),
                (self.review_marker_sha256, "review marker")):
            _sha(value, f"recovery {label}")
        _git_sha(self.source_review_commit, "source review commit")
        if (_group_tree_sha256(self.source_group_hashes)
                != self.source_group_tree_sha256):
            raise PT1RecoveryError("recovery source group tree drift")
        if (type(self.source_evidence_root) is not str
                or type(self.recovery_evidence_root) is not str
                or not os.path.isabs(self.source_evidence_root)
                or not os.path.isabs(self.recovery_evidence_root)
                or Path(self.source_evidence_root).resolve()
                == Path(self.recovery_evidence_root).resolve()):
            raise PT1RecoveryError("recovery root identity drift")
        if (type(self.source) is not dict or type(self.runtime) is not dict
                or self.runtime.get("worker_count") != 1
                or self.runtime.get("compiled_engine") is not True
                or self.runtime.get("strict_voids") is not True
                or self.authority != AUTHORITIES):
            raise PT1RecoveryError("recovery source/runtime/authority drift")
        claim = _recovery_marker_claim(
            canonical_json_bytes(dict(self.review_marker)))
        if (_hash_bytes(canonical_json_bytes(claim)) != self.review_marker_sha256
                or claim["source_git"] != self.source.get("git_head")
                or claim["source_execution_freeze_sha256"]
                != self.source_execution_freeze_sha256
                or claim["source_failure_sha256"] != self.source_failure_sha256
                or claim["source_progress_sha256"]
                != self.source_progress_sha256
                or claim["source_deadline_sha256"]
                != self.source_deadline_sha256
                or claim["source_group_tree_sha256"]
                != self.source_group_tree_sha256
                or claim["source_review_commit"] != self.source_review_commit
                or claim["runtime_sha256"] != _hash_bytes(
                    canonical_json_bytes(dict(self.runtime)))
                or claim["recovery_evidence_root"]
                != self.recovery_evidence_root):
            raise PT1RecoveryError("recovery marker does not bind freeze")

    def payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "source_execution_freeze_sha256":
                self.source_execution_freeze_sha256,
            "source_failure_sha256": self.source_failure_sha256,
            "source_progress_sha256": self.source_progress_sha256,
            "source_deadline_sha256": self.source_deadline_sha256,
            "source_group_hashes": list(self.source_group_hashes),
            "source_group_tree_sha256": self.source_group_tree_sha256,
            "source_evidence_root": self.source_evidence_root,
            "recovery_evidence_root": self.recovery_evidence_root,
            "source_review_commit": self.source_review_commit,
            "source": copy.deepcopy(dict(self.source)),
            "runtime": copy.deepcopy(dict(self.runtime)),
            "review_marker_sha256": self.review_marker_sha256,
            "review_marker": copy.deepcopy(dict(self.review_marker)),
            "authority": dict(AUTHORITIES),
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.payload())


def freeze_terminal_recovery(
        *, source_evidence_root: str | os.PathLike[str],
        recovery_evidence_root: str | os.PathLike[str],
        source_review_commit: str, review_marker: bytes | None = None,
        source: Mapping[str, object] | None = None,
        runtime: Mapping[str, object] | None = None) \
        -> PT1TerminalRecoveryFreeze:
    source_root = Path(source_evidence_root).expanduser().resolve()
    recovery_root = Path(recovery_evidence_root).expanduser().resolve()
    if recovery_root.exists() or recovery_root.is_symlink():
        raise PT1RecoveryError("recovery output root must not exist at freeze")
    inputs = _validate_failed_source_root(source_root)
    source_value = (dict(source) if source is not None
                    else _recovery_source_identity())
    runtime_value = dict(runtime) if runtime is not None else _runtime_identity(1)
    _git_sha(source_value.get("git_head"), "recovery source")
    _git_sha(source_review_commit, "source review commit")
    claim = {
        "schema": RECOVERY_REVIEW_SCHEMA,
        "source_git": source_value["git_head"],
        "source_execution_freeze_sha256": inputs["freeze_sha256"],
        "source_failure_sha256": inputs["failure_sha256"],
        "source_progress_sha256": inputs["progress_sha256"],
        "source_deadline_sha256": inputs["deadline_sha256"],
        "source_group_tree_sha256": inputs["group_tree_sha256"],
        "source_review_commit": source_review_commit,
        "runtime_sha256": _hash_bytes(canonical_json_bytes(runtime_value)),
        "recovery_evidence_root": str(recovery_root),
        "authority": dict(AUTHORITIES),
    }
    marker_raw = canonical_json_bytes(claim) if review_marker is None else review_marker
    if _recovery_marker_claim(marker_raw) != claim:
        raise PT1RecoveryError("recovery review marker claim drift")
    return PT1TerminalRecoveryFreeze(
        inputs["freeze_sha256"], inputs["failure_sha256"],
        inputs["progress_sha256"], inputs["deadline_sha256"],
        inputs["group_hashes"], inputs["group_tree_sha256"],
        str(source_root), str(recovery_root), source_review_commit,
        source_value, runtime_value, _hash_bytes(marker_raw), claim,
        dict(AUTHORITIES))


def verify_recovery_freeze(
        value: PT1TerminalRecoveryFreeze | Mapping[str, object] | bytes) \
        -> PT1TerminalRecoveryFreeze:
    if isinstance(value, bytes):
        payload = _canonical_load(value, "recovery freeze")
    elif isinstance(value, PT1TerminalRecoveryFreeze):
        payload = value.payload()
    elif isinstance(value, Mapping):
        payload = copy.deepcopy(dict(value))
    else:
        raise PT1RecoveryError("recovery freeze type refused")
    fields = set(PT1TerminalRecoveryFreeze.__dataclass_fields__) - {"schema"}
    fields.add("schema")
    if (not isinstance(payload, dict) or set(payload) != fields
            or payload.get("schema") != RECOVERY_FREEZE_SCHEMA):
        raise PT1RecoveryError("recovery freeze fields/schema drift")
    try:
        typed = PT1TerminalRecoveryFreeze(
            payload["source_execution_freeze_sha256"],
            payload["source_failure_sha256"], payload["source_progress_sha256"],
            payload["source_deadline_sha256"],
            tuple(payload["source_group_hashes"]),
            payload["source_group_tree_sha256"],
            payload["source_evidence_root"], payload["recovery_evidence_root"],
            payload["source_review_commit"], payload["source"],
            payload["runtime"], payload["review_marker_sha256"],
            payload["review_marker"], payload["authority"], payload["schema"])
    except PT1RecoveryError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise PT1RecoveryError("recovery freeze values drift") from exc
    if typed.canonical_bytes() != canonical_json_bytes(payload):
        raise PT1RecoveryError("recovery freeze round-trip drift")
    return typed


def authenticate_recovery_marker(
        marker: bytes, freeze: PT1TerminalRecoveryFreeze, *,
        review_commit: str, repo_root: Path | None = None) -> None:
    typed = verify_recovery_freeze(freeze)
    if (marker != canonical_json_bytes(dict(typed.review_marker))
            or _hash_bytes(marker) != typed.review_marker_sha256):
        raise PT1RecoveryError("recovery review marker does not bind freeze")
    _recovery_marker_claim(marker)
    _git_sha(review_commit, "recovery review commit")
    root = repo_root or Path(__file__).resolve().parents[3]
    _authenticate_review_provenance(root, review_commit, marker)


def _require_live_recovery_bindings(
        freeze: PT1TerminalRecoveryFreeze, *,
        repo_root: Path | None = None) -> None:
    if _recovery_source_identity(repo_root) != dict(freeze.source):
        raise PT1RecoveryError("recovery live source identity drift")
    if _runtime_identity(1) != dict(freeze.runtime):
        raise PT1RecoveryError("recovery live runtime identity drift")


def _reopen_inputs(freeze: PT1TerminalRecoveryFreeze) \
        -> tuple[PT1ExecutionFreeze, list[Mapping[str, object]]]:
    current = _validate_failed_source_root(Path(freeze.source_evidence_root))
    expected = {
        "freeze_sha256": freeze.source_execution_freeze_sha256,
        "failure_sha256": freeze.source_failure_sha256,
        "progress_sha256": freeze.source_progress_sha256,
        "deadline_sha256": freeze.source_deadline_sha256,
        "group_hashes": freeze.source_group_hashes,
        "group_tree_sha256": freeze.source_group_tree_sha256,
    }
    if any(current[name] != value for name, value in expected.items()):
        raise PT1RecoveryError("recovery source bytes changed after freeze")
    source_freeze = current["source_freeze"]
    source_marker = canonical_json_bytes(dict(source_freeze.review_marker))
    authenticate_review_marker(
        source_marker, source_freeze,
        review_commit=freeze.source_review_commit)
    natural = NaturalPT1Design(source_freeze.scientific_capture_secret_sha256)
    groups = []
    directory = Path(freeze.source_evidence_root) / GROUP_DIR
    for index, (key, expected_hash) in enumerate(
            zip(natural.state_keys, freeze.source_group_hashes, strict=True)):
        raw = _safe_bytes(directory / f"group-{index:04d}.json",
                          f"source group {index}", modes=(0o400,))
        if _hash_bytes(raw) != expected_hash:
            raise PT1RecoveryError("recovery group byte hash drift")
        groups.append(_verify_group_bytes(raw, index, key=key))
    return source_freeze, groups


def _derive_packet(freeze: PT1TerminalRecoveryFreeze) -> dict[str, object]:
    source_freeze, groups = _reopen_inputs(freeze)
    natural = NaturalPT1Design(source_freeze.scientific_capture_secret_sha256)
    states = _validate_group_population(
        natural, groups, source_freeze.population_manifest)
    records = tuple(record for group in groups for record in group["records"])
    if len(records) != TOTAL_RECORD_COUNT:
        raise PT1RecoveryError("recovery record population drift")
    resources = _resource_totals(groups, source_freeze.worker_count)
    if (_resource_cap_overages(resources, source_freeze.capacity_caps)
            or set(resources) != SCIENTIFIC_CAP_KEYS):
        raise PT1RecoveryError("recovery source scientific resources exceed caps")
    statistics = reduce_reopened_pt1_statistics(natural, states, records)
    verify_statistics_report(statistics, design=natural)
    packet = {
        "schema": RECOVERY_PACKET_SCHEMA,
        "recovery_freeze_sha256": _hash_bytes(freeze.canonical_bytes()),
        "source_execution_freeze_sha256":
            freeze.source_execution_freeze_sha256,
        "source_failure_sha256": freeze.source_failure_sha256,
        "source_group_tree_sha256": freeze.source_group_tree_sha256,
        "status": RECOVERY_STATUS,
        "completed_units": TARGET_STATE_COUNT,
        "total_units": TARGET_STATE_COUNT,
        "resources": resources,
        "statistics": statistics.payload(),
        "authority": dict(AUTHORITIES),
    }
    packet["packet_sha256"] = _hash_bytes(canonical_json_bytes(packet))
    return packet


def run_terminal_recovery(
        freeze: PT1TerminalRecoveryFreeze | Mapping[str, object] | bytes, *,
        review_marker: bytes, review_commit: str,
        repo_root: Path | None = None) -> dict[str, object]:
    typed = verify_recovery_freeze(freeze)
    _require_live_recovery_bindings(typed, repo_root=repo_root)
    authenticate_recovery_marker(
        review_marker, typed, review_commit=review_commit,
        repo_root=repo_root)
    root = Path(typed.recovery_evidence_root)
    if root.exists() or root.is_symlink():
        raise PT1RecoveryError("recovery namespace is already consumed")
    root.mkdir(mode=0o700, parents=False)
    if stat.S_IMODE(root.stat().st_mode) != 0o700:
        raise PT1RecoveryError("recovery namespace mode drift")
    _fsync_dir(root.parent)
    _write_once(root / RECOVERY_FREEZE_NAME, typed.canonical_bytes())
    attempt = {
        "schema": RECOVERY_ATTEMPT_SCHEMA,
        "recovery_freeze_sha256": _hash_bytes(typed.canonical_bytes()),
        "source_execution_freeze_sha256":
            typed.source_execution_freeze_sha256,
        "source_failure_sha256": typed.source_failure_sha256,
        "source_group_tree_sha256": typed.source_group_tree_sha256,
        "group_count": TARGET_STATE_COUNT,
        "record_count": TOTAL_RECORD_COUNT,
        "status": "OPENED",
        "authority": dict(AUTHORITIES),
    }
    _write_once(root / RECOVERY_ATTEMPT_NAME, canonical_json_bytes(attempt))
    try:
        packet = _derive_packet(typed)
        packet_raw = canonical_json_bytes(packet)
        manifest = {
            "schema": RECOVERY_MANIFEST_SCHEMA,
            "recovery_freeze_sha256": _hash_bytes(typed.canonical_bytes()),
            "source_execution_freeze_sha256":
                typed.source_execution_freeze_sha256,
            "source_failure_sha256": typed.source_failure_sha256,
            "source_group_tree_sha256": typed.source_group_tree_sha256,
            "source_group_hashes": list(typed.source_group_hashes),
            "packet_sha256": packet["packet_sha256"],
            "packet_bytes_sha256": _hash_bytes(packet_raw),
            "group_count": TARGET_STATE_COUNT,
            "record_count": TOTAL_RECORD_COUNT,
            "status": RECOVERY_STATUS,
            "authority": dict(AUTHORITIES),
        }
        manifest["manifest_sha256"] = _hash_bytes(
            canonical_json_bytes(manifest))
        _write_once(root / MANIFEST_NAME, canonical_json_bytes(manifest))
        # Publish the outcome-bearing packet last. If anything above refuses,
        # the fresh namespace contains no result bytes and cannot be retried.
        _write_once(root / PACKET_NAME, packet_raw)
        return packet
    except Exception:
        failure = {
            "schema": RECOVERY_FAILURE_SCHEMA,
            "recovery_freeze_sha256": _hash_bytes(typed.canonical_bytes()),
            "source_execution_freeze_sha256":
                typed.source_execution_freeze_sha256,
            "source_group_tree_sha256": typed.source_group_tree_sha256,
            "status": "FAILED",
            "result_persisted": False,
            "retry_authorized": False,
            "authority": dict(AUTHORITIES),
        }
        _write_once(root / RECOVERY_FAILURE_NAME,
                    canonical_json_bytes(failure))
        raise


def verify_terminal_recovery(
        recovery_root: str | os.PathLike[str],
        freeze: PT1TerminalRecoveryFreeze | Mapping[str, object] | bytes, *,
        review_marker: bytes, review_commit: str,
        repo_root: Path | None = None) -> dict[str, object]:
    typed = verify_recovery_freeze(freeze)
    _require_live_recovery_bindings(typed, repo_root=repo_root)
    authenticate_recovery_marker(
        review_marker, typed, review_commit=review_commit,
        repo_root=repo_root)
    root = Path(recovery_root).expanduser().resolve()
    if root != Path(typed.recovery_evidence_root).resolve():
        raise PT1RecoveryError("recovery output root binding drift")
    _require_owned_directory(root, "recovery output root")
    expected_names = {RECOVERY_FREEZE_NAME, RECOVERY_ATTEMPT_NAME,
                      PACKET_NAME, MANIFEST_NAME}
    if {path.name for path in root.iterdir()} != expected_names:
        raise PT1RecoveryError("recovery output namespace is not closed")
    if (_safe_bytes(root / RECOVERY_FREEZE_NAME, "published recovery freeze",
                    modes=(0o400,)) != typed.canonical_bytes()):
        raise PT1RecoveryError("published recovery freeze drift")
    attempt = _canonical_load(_safe_bytes(
        root / RECOVERY_ATTEMPT_NAME, "recovery attempt", modes=(0o400,)),
        "recovery attempt")
    attempt_fields = {
        "schema", "recovery_freeze_sha256",
        "source_execution_freeze_sha256", "source_failure_sha256",
        "source_group_tree_sha256", "group_count", "record_count",
        "status", "authority"}
    if (not isinstance(attempt, dict) or set(attempt) != attempt_fields
            or attempt.get("schema") != RECOVERY_ATTEMPT_SCHEMA
            or attempt.get("recovery_freeze_sha256")
            != _hash_bytes(typed.canonical_bytes())
            or attempt.get("source_group_tree_sha256")
            != typed.source_group_tree_sha256
            or attempt.get("group_count") != TARGET_STATE_COUNT
            or attempt.get("record_count") != TOTAL_RECORD_COUNT
            or attempt.get("status") != "OPENED"
            or attempt.get("authority") != AUTHORITIES):
        raise PT1RecoveryError("recovery attempt drift")
    packet_raw = _safe_bytes(root / PACKET_NAME, "recovery packet",
                             modes=(0o400,))
    manifest_raw = _safe_bytes(root / MANIFEST_NAME, "recovery manifest",
                               modes=(0o400,))
    packet = _canonical_load(packet_raw, "recovery packet")
    manifest = _canonical_load(manifest_raw, "recovery manifest")
    reconstructed = _derive_packet(typed)
    if packet != reconstructed or packet_raw != canonical_json_bytes(reconstructed):
        raise PT1RecoveryError("recovery packet reconstruction drift")
    expected_manifest = {
        "schema": RECOVERY_MANIFEST_SCHEMA,
        "recovery_freeze_sha256": _hash_bytes(typed.canonical_bytes()),
        "source_execution_freeze_sha256":
            typed.source_execution_freeze_sha256,
        "source_failure_sha256": typed.source_failure_sha256,
        "source_group_tree_sha256": typed.source_group_tree_sha256,
        "source_group_hashes": list(typed.source_group_hashes),
        "packet_sha256": packet["packet_sha256"],
        "packet_bytes_sha256": _hash_bytes(packet_raw),
        "group_count": TARGET_STATE_COUNT,
        "record_count": TOTAL_RECORD_COUNT,
        "status": RECOVERY_STATUS,
        "authority": dict(AUTHORITIES),
    }
    expected_manifest["manifest_sha256"] = _hash_bytes(
        canonical_json_bytes(expected_manifest))
    if manifest != expected_manifest:
        raise PT1RecoveryError("recovery manifest reconstruction drift")
    return packet


__all__ = [
    "PT1RecoveryError", "PT1TerminalRecoveryFreeze",
    "RECOVERY_ATTEMPT_NAME", "RECOVERY_FAILURE_NAME", "RECOVERY_FREEZE_NAME",
    "RECOVERY_MANIFEST_SCHEMA", "RECOVERY_PACKET_SCHEMA",
    "RECOVERY_REVIEW_SCHEMA", "RECOVERY_STATUS",
    "authenticate_recovery_marker", "freeze_terminal_recovery",
    "run_terminal_recovery", "verify_recovery_freeze",
    "verify_terminal_recovery",
]

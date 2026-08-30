#!/usr/bin/env python3
"""Initialize, preflight, execute and reconstruct optimized R4 terminal."""

from __future__ import annotations

import sys

if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("R4 terminal parallel runner requires Python -P -B")

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


SOURCE_ROOT = Path(__file__).resolve().parents[1]
SEALED_SCIENTIFIC_SOURCE_ROOT = Path(
    "/opt/belief-r4-terminal-final/server")


def _prepare_recovery_import_roots() -> None:
    """Execute new Python source with the sealed native extension.

    The frozen venv has an editable-path entry for the old scientific source.
    A recovery checkout must not import its Python modules, but the live
    runtime identity deliberately binds the already-compiled native extension
    at that old path.  Put this reviewed source first, remove only the exact
    old Python import root, then extend the new engine package path solely for
    the byte-bound native module.  ``validate_live_execution`` later proves
    both the new Python source and the frozen native/runtime identity.
    """
    sealed = SEALED_SCIENTIFIC_SOURCE_ROOT.resolve()
    source = SOURCE_ROOT.resolve()
    retained = []
    for entry in sys.path:
        if type(entry) is not str or not entry:
            retained.append(entry)
            continue
        try:
            resolved = Path(entry).resolve()
        except OSError:
            retained.append(entry)
            continue
        if source != sealed and resolved == sealed:
            continue
        retained.append(entry)
    retained = [entry for entry in retained
                if type(entry) is not str
                or not entry
                or Path(entry).resolve() != source]
    sys.path[:] = [str(source), *retained]
    native_root = sealed / "shengji" / "engine"
    if source != sealed and native_root.is_dir() \
            and any(native_root.glob("_fast*.so")):
        __import__("shengji.engine")
        engine = sys.modules["shengji.engine"]
        if str(native_root) not in engine.__path__:
            engine.__path__.append(str(native_root))


_prepare_recovery_import_roots()


def _refuse_foreign_import_roots() -> None:
    """Require every import root to belong to Python, this venv, or source.

    A ``.pth`` file can add another experiment's site-packages even when
    ``-P`` is active and ``PYTHONPATH`` is absent.  The terminal scorer is a
    one-shot consumer, so refuse that cross-run coupling before importing any
    project or numerical package.
    """
    allowed_roots = (
        Path(sys.base_prefix).resolve(),
        Path(sys.prefix).resolve(),
        SOURCE_ROOT,
    )
    for entry in sys.path:
        if type(entry) is not str or not entry:
            continue
        resolved = Path(entry).resolve()
        if not any(resolved.is_relative_to(root) for root in allowed_roots):
            raise RuntimeError(
                "R4 terminal parallel runner refuses foreign import roots")


_refuse_foreign_import_roots()

from shengji.rl.belief_artifacts import (
    publish_exclusive_bytes,
    stable_read_bytes,
)
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.belief_v2_execution_identity import (
    build_source_bindings,
    configure_numerical_runtime,
    source_manifest_sha256,
    validate_live_execution,
)
from shengji.rl.belief_v2_freeze import execution_freeze_from_bytes
from shengji.rl.belief_v2_progress import V2ProgressReporter
from shengji.rl.belief_v2_r4_completion import (
    PENDING_RECOVERY_REVIEW_PREFIX,
    RECOVERY_EXECUTION_REVIEW_PREFIX,
    authenticate_r4_recovery_execution_review,
    build_r4_completion_admission,
    expected_r4_recovery_execution_review_marker,
    r4_completion_admission_from_bytes,
    r4_completion_consumption_tombstone_bytes,
    reauthenticate_r4_completion_admission,
    validate_r4_completion_consumption_tombstone,
)
from shengji.rl.belief_v2_r4_terminal_parallel import (
    CAPACITY_FIELDS,
    CAPACITY_MEASUREMENT_ORDER,
    CAPACITY_SCHEMA,
    HOST_MEMORY_MEASUREMENT,
    MAXIMUM_SYNTHETIC_DECISIONS_PER_ROUND,
    V2_DECISION_WORKERS,
    build_r4_terminal_calibration_import,
    build_r4_terminal_parallel_freeze,
    load_calibration_import,
    load_terminal_source_spec,
    r4_terminal_parallel_capacity,
    r4_terminal_parallel_pending_recovery_review_claim,
    r4_terminal_parallel_readiness,
    r4_terminal_parallel_timeout_receipt,
    finalize_r4_terminal_parallel_pending,
    recover_r4_terminal_parallel,
    recover_r4_terminal_parallel_pending,
    reopen_r4_terminal_parallel,
    run_r4_terminal_parallel,
    synthetic_round_key,
)
from shengji.rl.belief_v2_protocol import (
    V2_RANKS,
    V2_SPLIT_COUNTS,
    v2_round_coordinates,
)


REPO = Path(__file__).resolve().parents[2]
ROOT_POPULATION = {
    "freeze.json", "review.md", "admission.json", "inventory.json",
    "group-split.json", "capacity.json",
}
TERMINAL_POPULATION = {
    "r4-completion-test-attempt.json", "terminal.partial", "terminal",
    "r4-completion-terminal.json",
    "r4-completion-timeout-receipt.json",
    "r4-completion-terminal.pending.json",
    "r4-completion-pending-recovery-tombstone.json",
    "r4-completion-pending-verifier-attempt.json",
    "r4-completion-pending-verifier-receipt.json",
    "r4-completion-recovery-route-claim.json",
}
R4_SCIENTIFIC_SERVICE = (
    "belief-r4-terminal-scientific-56bd35f-r1.service")
R4_SCIENTIFIC_RUNTIME_MAX_MICROSECONDS = 172_800_000_000


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _fsync_parent(path: Path) -> None:
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _output(payload: dict) -> None:
    print(canonical_json_bytes(payload).decode("ascii"), end="")


def _progress(stage: str):
    return V2ProgressReporter(stage=stage, worker="all-cohorts").update


def _validate_private_inputs(raw_inventory: bytes, raw_split: bytes, freeze) \
        -> None:
    if _sha256(raw_inventory) != freeze.h0_inventory_sha256 \
            or _sha256(raw_split) != freeze.human_group_split_sha256:
        raise ValueError("R4 terminal private input identity drift")


def _reopen_frozen_capacity_binding(
        raw: bytes, *, freeze, terminal_spec, calibration_import) -> dict:
    """Reopen a capacity receipt already deep-verified into the freeze.

    The capacity command and freeze builder independently reconstruct the
    imported calibration and trained cohorts.  Once the reviewed freeze binds
    those exact receipt bytes, later stage gates must authenticate the binding,
    runtime and authority surface without replaying that multi-hour verifier on
    every command.
    """
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("R4 terminal frozen capacity is not JSON") from exc
    coordinate_population = v2_round_coordinates()
    matches_by_rank = tuple(tuple(
        row for row in coordinate_population
        if row.trump_rank == rank and row.split == "calibration")
        for rank in V2_RANKS)
    if any(len(matches) == 0 for matches in matches_by_rank):
        raise ValueError("R4 terminal frozen capacity rank drift")
    coordinates = tuple(matches[0] for matches in matches_by_rank)
    positive_fields = (
        "rank_count", "decision_count", "serial_wall_nanoseconds",
        "parallel_wall_nanoseconds", "serial_cpu_nanoseconds",
        "parallel_cpu_nanoseconds", "speedup_ppb",
        "aggregate_peak_host_memory_bytes",
        "host_memory_cap_bytes", "worker_count",
        "synthetic_test_round_count", "human_test_decision_count",
        "maximum_synthetic_decisions_per_round",
        "projected_maximum_test_decision_count",
        "scientific_unit_scoring_pass_count",
        "independent_verifier_scoring_pass_count",
        "control_reopen_wall_nanoseconds",
        "scientific_unit_control_reopen_count",
        "independent_verifier_control_reopen_count",
        "projected_scientific_control_wall_nanoseconds",
        "projected_independent_verifier_control_wall_nanoseconds",
        "projected_one_pass_wall_nanoseconds",
        "projected_scientific_unit_wall_nanoseconds",
        "projected_independent_verifier_wall_nanoseconds",
        "terminal_wall_cap_nanoseconds",
        "deadline_safety_reserve_nanoseconds",
    )
    expected_test_rounds = dict(V2_SPLIT_COUNTS)["test"]
    if type(payload) is not dict or set(payload) != CAPACITY_FIELDS \
            or canonical_json_bytes(payload) != raw \
            or any(type(payload[key]) is not int or payload[key] <= 0
                   for key in positive_fields) \
            or payload["schema"] != CAPACITY_SCHEMA \
            or payload["execution_git"] != freeze.execution_git \
            or payload["source_manifest_sha256"] \
            != freeze.source_manifest_sha256 \
            or payload["runtime_sha256"] \
            != freeze.preflight_runtime_sha256 \
            or payload["terminal_source_spec_sha256"] \
            != terminal_spec.sha256() \
            or payload["calibration_import_sha256"] \
            != calibration_import.sha256() \
            or payload["calibration_manifest_sha256"] \
            != calibration_import.calibration_selection_manifest_sha256 \
            or payload["hostname"] != freeze.runtime.hostname \
            or payload["machine"] != freeze.runtime.machine \
            or payload["rank_count"] != len(V2_RANKS) \
            or payload["trump_ranks"] != list(V2_RANKS) \
            or payload["round_keys"] != [
                synthetic_round_key(row.round_seed) for row in coordinates] \
            or payload["measurement_order"] != CAPACITY_MEASUREMENT_ORDER \
            or payload["parallel_wall_nanoseconds"] \
            >= payload["serial_wall_nanoseconds"] \
            or payload["speedup_ppb"] != (
                payload["serial_wall_nanoseconds"] * 1_000_000_000
                // payload["parallel_wall_nanoseconds"]) \
            or payload["host_memory_cap_bytes"] \
            != freeze.resource_caps.training_host_memory_bytes \
            or payload["aggregate_peak_host_memory_measurement"] \
            != HOST_MEMORY_MEASUREMENT \
            or payload["aggregate_peak_host_memory_bytes"] \
            > payload["host_memory_cap_bytes"] \
            or payload["host_memory_within_cap"] is not True \
            or payload["worker_count"] != V2_DECISION_WORKERS \
            or payload["synthetic_test_round_count"] \
            != expected_test_rounds \
            or payload["human_test_decision_count"] \
            != freeze.human_test_eligible_decision_count \
            or payload["maximum_synthetic_decisions_per_round"] \
            != MAXIMUM_SYNTHETIC_DECISIONS_PER_ROUND \
            or payload["terminal_wall_cap_nanoseconds"] \
            != freeze.resource_caps.training_wall_seconds * 1_000_000_000 \
            or payload["deadline_safety_reserve_nanoseconds"] \
            != freeze.resource_caps.deadline_safety_reserve_nanoseconds \
            or payload["projected_scientific_unit_wall_nanoseconds"] \
            + payload["deadline_safety_reserve_nanoseconds"] \
            >= payload["terminal_wall_cap_nanoseconds"] \
            or payload["projected_independent_verifier_wall_nanoseconds"] \
            + payload["deadline_safety_reserve_nanoseconds"] \
            >= payload["terminal_wall_cap_nanoseconds"] \
            or payload["exact_serial_parallel_parity"] is not True \
            or payload["projected_within_wall_cap"] is not True \
            or payload["test_split_decision_open_count"] != 0 \
            or payload["test_opening_executed"] is not False \
            or payload["execution_authorized"] is not False \
            or payload["strength_claim_authorized"] is not False \
            or payload["deployment_authorized"] is not False:
        raise ValueError("R4 terminal frozen capacity binding drift")
    return payload


def _repository_protocol_inputs(repo: Path):
    scripts = repo / "server" / "scripts"
    terminal_spec = load_terminal_source_spec(stable_read_bytes(
        scripts / "belief_v2_r4_terminal_parallel_source.v1.json"))
    calibration_import = load_calibration_import(stable_read_bytes(
        scripts / "belief_v2_r4_terminal_parallel_import.v1.json"))
    return terminal_spec, calibration_import


def _load_root(root: Path, *, repo: Path = REPO):
    terminal_spec, calibration_import = _repository_protocol_inputs(repo)
    names = {path.name for path in root.iterdir()}
    if not root.is_absolute() or root.is_symlink() or not root.is_dir() \
            or root != terminal_spec.destination_evidence_root \
            or not ROOT_POPULATION.issubset(names) \
            or not names.issubset(ROOT_POPULATION | TERMINAL_POPULATION):
        raise ValueError("R4 terminal evidence root shape drift")
    freeze_raw = stable_read_bytes(root / "freeze.json")
    marker = stable_read_bytes(root / "review.md")
    admission_raw = stable_read_bytes(root / "admission.json")
    inventory_raw = stable_read_bytes(root / "inventory.json")
    split_raw = stable_read_bytes(root / "group-split.json")
    capacity_raw = stable_read_bytes(root / "capacity.json")
    freeze = execution_freeze_from_bytes(freeze_raw)
    if Path(freeze.evidence_root) != root:
        raise ValueError("R4 terminal freeze root drift")
    admission = r4_completion_admission_from_bytes(
        admission_raw, freeze=freeze, review_marker=marker,
        spec=terminal_spec)
    tombstone_raw = stable_read_bytes(
        root.with_name(root.name + ".consumed.json"))
    validate_r4_completion_consumption_tombstone(
        tombstone_raw, admission=admission)
    _validate_private_inputs(inventory_raw, split_raw, freeze)
    if _sha256(capacity_raw) != freeze.preflight_result_sha256 \
            or _sha256(capacity_raw) \
            != freeze.deadline_estimate_receipt_sha256:
        raise ValueError("R4 terminal capacity/freeze binding drift")
    capacity = _reopen_frozen_capacity_binding(
        capacity_raw, freeze=freeze, terminal_spec=terminal_spec,
        calibration_import=calibration_import)
    if capacity["runtime_sha256"] != freeze.preflight_runtime_sha256:
        raise ValueError("R4 terminal capacity runtime binding drift")
    reauthenticate_r4_completion_admission(
        freeze, admission, repo=repo, review_marker=marker,
        spec=terminal_spec)
    validate_live_execution(
        repo=repo, execution_git=freeze.execution_git,
        source_bindings=freeze.source_bindings, runtime=freeze.runtime)
    return freeze, admission, marker


def _strict_recovery_repo(path: Path, *, label: str) -> Path:
    """Refuse an ambiguous checkout before any recovery evidence is opened."""
    path = Path(path)
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"R4 {label} repository absent") from exc
    if not path.is_absolute() or path.is_symlink() or resolved != path \
            or not path.is_dir():
        raise ValueError(f"R4 {label} repository identity drift")
    return path


def _recovery_review_inputs(
        root: Path, *, sealed_repo: Path, recovery_execution_git: str):
    """Validate old evidence and new code as two independent identities."""
    sealed_repo = _strict_recovery_repo(
        sealed_repo, label="sealed scientific")
    recovery_repo = _strict_recovery_repo(
        REPO, label="recovery execution")
    freeze, admission, marker = _load_root(root, repo=sealed_repo)
    if sealed_repo == recovery_repo \
            or recovery_execution_git == freeze.execution_git:
        raise ValueError("R4 recovery dual execution identity drift")
    terminal_spec, calibration_import = _repository_protocol_inputs(
        recovery_repo)
    capacity_sha256 = _sha256(stable_read_bytes(root / "capacity.json"))
    bindings = build_source_bindings(
        recovery_repo, expected_git=recovery_execution_git)
    recovery_source_manifest_sha256 = source_manifest_sha256(
        recovery_execution_git, bindings)
    validate_live_execution(
        repo=recovery_repo, execution_git=recovery_execution_git,
        source_bindings=bindings, runtime=freeze.runtime)
    values = {
        "freeze": freeze,
        "admission": admission,
        "recovery_execution_git": recovery_execution_git,
        "recovery_source_manifest_sha256": (
            recovery_source_manifest_sha256),
        "terminal_source_spec_sha256": terminal_spec.sha256(),
        "calibration_import_sha256": calibration_import.sha256(),
        "capacity_sha256": capacity_sha256,
    }
    return freeze, admission, marker, sealed_repo, values


def _load_recovery_root(args: argparse.Namespace):
    """Authenticate both checkouts before a timeout-recovery command."""
    root = Path(args.root)
    (freeze, admission, marker, sealed_repo,
     values) = _recovery_review_inputs(
         root, sealed_repo=Path(args.sealed_repo),
         recovery_execution_git=args.recovery_execution_git)
    recovery_execution = authenticate_r4_recovery_execution_review(
        freeze, admission, repo=REPO,
        recovery_execution_git=args.recovery_execution_git,
        review_commit=args.recovery_source_review_commit,
        terminal_source_spec_sha256=(
            values["terminal_source_spec_sha256"]),
        calibration_import_sha256=(
            values["calibration_import_sha256"]),
        capacity_sha256=values["capacity_sha256"])
    return (root, freeze, admission, marker, sealed_repo,
            recovery_execution)


def recovery_execution_review_claim(args: argparse.Namespace) -> None:
    """Print the exact new-code marker without authenticating it yet."""
    root = Path(args.root)
    (_freeze, _admission, _marker, _sealed_repo,
     values) = _recovery_review_inputs(
         root, sealed_repo=Path(args.sealed_repo),
         recovery_execution_git=args.recovery_execution_git)
    sys.stdout.buffer.write(expected_r4_recovery_execution_review_marker(
        **values))


def initialize(args: argparse.Namespace) -> None:
    freeze_path = Path(args.freeze)
    freeze_raw = stable_read_bytes(freeze_path)
    if _sha256(freeze_raw) != args.expected_freeze_sha256:
        raise ValueError("R4 terminal freeze file SHA drift")
    freeze = execution_freeze_from_bytes(freeze_raw)
    terminal_spec = load_terminal_source_spec()
    calibration_import = load_calibration_import()
    root = Path(freeze.evidence_root)
    if root != terminal_spec.destination_evidence_root \
            or freeze_path.parent != root.parent:
        raise ValueError("R4 terminal initialization destination drift")
    validate_live_execution(
        repo=REPO, execution_git=freeze.execution_git,
        source_bindings=freeze.source_bindings, runtime=freeze.runtime)
    inventory_raw = stable_read_bytes(Path(args.inventory))
    split_raw = stable_read_bytes(Path(args.group_split))
    capacity_raw = stable_read_bytes(Path(args.capacity))
    _validate_private_inputs(inventory_raw, split_raw, freeze)
    if _sha256(capacity_raw) != args.expected_capacity_sha256 \
            or _sha256(capacity_raw) != freeze.preflight_result_sha256 \
            or _sha256(capacity_raw) \
            != freeze.deadline_estimate_receipt_sha256:
        raise ValueError("R4 terminal capacity file SHA drift")
    capacity = _reopen_frozen_capacity_binding(
        capacity_raw, freeze=freeze, terminal_spec=terminal_spec,
        calibration_import=calibration_import)
    if capacity["runtime_sha256"] != freeze.preflight_runtime_sha256:
        raise ValueError("R4 terminal capacity runtime binding drift")
    admission, marker = build_r4_completion_admission(
        freeze, repo=REPO, review_commit=args.review_commit,
        spec=terminal_spec)
    tombstone_raw = r4_completion_consumption_tombstone_bytes(admission)
    partial = root.with_name(root.name + ".partial")
    tombstone = root.with_name(root.name + ".consumed.json")
    if root.exists() or root.is_symlink() or partial.exists() \
            or partial.is_symlink() or tombstone.exists() \
            or tombstone.is_symlink():
        raise ValueError("R4 terminal evidence namespace is occupied")
    publish_exclusive_bytes(tombstone, tombstone_raw)
    _fsync_parent(tombstone)
    partial.mkdir(mode=0o700)
    publish_exclusive_bytes(partial / "freeze.json", freeze_raw)
    publish_exclusive_bytes(partial / "review.md", marker)
    publish_exclusive_bytes(
        partial / "admission.json", admission.canonical_bytes())
    publish_exclusive_bytes(partial / "inventory.json", inventory_raw)
    publish_exclusive_bytes(partial / "group-split.json", split_raw)
    publish_exclusive_bytes(partial / "capacity.json", capacity_raw)
    os.rename(partial, root)
    _fsync_parent(root)
    _load_root(root)
    _output({
        "schema": "belief-v1-v2-r4-terminal-parallel-initialized-v1",
        "evidence_root": str(root),
        "freeze_sha256": freeze.sha256(),
        "admission_sha256": admission.sha256(),
        "review_commit": admission.review_commit,
        "calibration_generation_authorized": False,
        "one_test_split_open_authorized": True,
        "test_opening_executed": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    })


def readiness(args: argparse.Namespace) -> None:
    root = Path(args.root)
    freeze, admission, marker = _load_root(root)
    _output(r4_terminal_parallel_readiness(
        root, freeze, admission, repo=REPO, review_marker=marker))


def capacity(args: argparse.Namespace) -> None:
    output = Path(args.out)
    if not output.is_absolute() or output.exists() or output.is_symlink():
        raise ValueError("R4 terminal capacity output path drift")
    receipt = r4_terminal_parallel_capacity(
        repo=REPO, expected_git=args.expected_git,
        progress=_progress("r4-terminal-parallel-capacity"))
    raw = canonical_json_bytes(receipt)
    digest = publish_exclusive_bytes(output, raw)
    _fsync_parent(output)
    _output({
        "schema": "belief-v1-v2-r4-terminal-capacity-published-v1",
        "receipt_path": str(output),
        "receipt_sha256": digest,
        "exact_serial_parallel_parity": True,
        "test_opening_executed": False,
        "execution_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    })


def build_calibration_import(args: argparse.Namespace) -> None:
    output = Path(args.out)
    if not output.is_absolute() or output.exists() or output.is_symlink():
        raise ValueError("R4 terminal calibration import output path drift")
    imported = build_r4_terminal_calibration_import(repo=REPO)
    digest = publish_exclusive_bytes(output, imported.canonical_bytes())
    _fsync_parent(output)
    _output({
        "schema": "belief-v1-v2-r4-terminal-calibration-import-published-v2",
        "import_path": str(output),
        "import_sha256": digest,
        "sealed_calibration_reconstructed": True,
        "test_opening_executed": False,
        "execution_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    })


def build_freeze(args: argparse.Namespace) -> None:
    output = Path(args.out)
    capacity_raw = stable_read_bytes(Path(args.capacity))
    if not output.is_absolute() or output.exists() or output.is_symlink() \
            or _sha256(capacity_raw) != args.expected_capacity_sha256:
        raise ValueError("R4 terminal freeze output/capacity drift")
    freeze = build_r4_terminal_parallel_freeze(
        repo=REPO, expected_git=args.expected_git,
        source_review_commit=args.source_review_commit,
        capacity_raw=capacity_raw)
    if output.parent != Path(freeze.evidence_root).parent:
        raise ValueError("R4 terminal freeze publication parent drift")
    digest = publish_exclusive_bytes(output, freeze.canonical_bytes())
    _fsync_parent(output)
    _output({
        "schema": "belief-v1-v2-r4-terminal-freeze-published-v1",
        "freeze_path": str(output),
        "freeze_sha256": digest,
        "capacity_sha256": _sha256(capacity_raw),
        "source_review_commit": freeze.source_review_commit,
        "design_freeze_authorized": True,
        "execution_authorized": False,
        "test_opening_executed": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    })


def open_test(args: argparse.Namespace) -> None:
    root = Path(args.root)
    freeze, admission, marker = _load_root(root)
    _output(run_r4_terminal_parallel(
        root, freeze, admission, repo=REPO, review_marker=marker,
        progress=_progress("r4-terminal-parallel")))


def verify_terminal(args: argparse.Namespace) -> None:
    root = Path(args.root)
    freeze, admission, marker = _load_root(root)
    _output(reopen_r4_terminal_parallel(
        root, freeze, admission, repo=REPO, review_marker=marker,
        progress=_progress("r4-terminal-parallel-verification")))


def _systemd_service_properties() -> dict[str, str]:
    """Read the immutable live-service properties used by recovery routing."""
    names = (
        "ActiveState", "SubState", "Result", "MainPID", "NRestarts",
        "RuntimeMaxUSec",
    )
    completed = subprocess.run(
        ("systemctl", "show", R4_SCIENTIFIC_SERVICE,
         *(f"--property={name}" for name in names), "--no-pager"),
        check=True, capture_output=True, text=True)
    pairs: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        if "=" not in line:
            raise ValueError("R4 terminal systemd observation shape drift")
        key, value = line.split("=", 1)
        if key in pairs:
            raise ValueError("R4 terminal systemd observation duplicate")
        pairs[key] = value
    if set(pairs) != set(names):
        raise ValueError("R4 terminal systemd observation population drift")
    return pairs


def recover_terminal(args: argparse.Namespace) -> None:
    service = _systemd_service_properties()
    if service["ActiveState"] not in {"inactive", "failed"} \
            or service["MainPID"] != "0":
        raise ValueError(
            "R4 terminal recovery requires an inactive scientific service")
    if service["ActiveState"] == "failed" \
            and service["Result"] == "timeout":
        raise ValueError(
            "R4 timed-out terminal requires reviewed pending recovery")
    root = Path(args.root)
    freeze, admission, marker = _load_root(root)
    _output(recover_r4_terminal_parallel(
        root, freeze, admission, repo=REPO, review_marker=marker,
        progress=_progress("r4-terminal-parallel-recovery")))


def _systemd_timeout_observation() -> dict[str, object]:
    """Read the exact failed service state without opening evidence bytes."""
    pairs = _systemd_service_properties()
    if pairs["SubState"] != "failed" \
            or pairs["RuntimeMaxUSec"] not in {
                "2d", str(R4_SCIENTIFIC_RUNTIME_MAX_MICROSECONDS)}:
        raise ValueError("R4 terminal systemd observation drift")
    try:
        main_pid = int(pairs["MainPID"])
        restart_count = int(pairs["NRestarts"])
    except ValueError as exc:
        raise ValueError("R4 terminal systemd counter drift") from exc
    return {
        "service_unit": R4_SCIENTIFIC_SERVICE,
        "observed_at_unix_nanoseconds": time.time_ns(),
        "runtime_max_microseconds": R4_SCIENTIFIC_RUNTIME_MAX_MICROSECONDS,
        "active_state": pairs["ActiveState"],
        "service_result": pairs["Result"],
        "main_pid": main_pid,
        "restart_count": restart_count,
    }


def build_timeout_receipt(args: argparse.Namespace) -> None:
    (root, freeze, admission, marker, sealed_repo,
     _recovery_execution) = _load_recovery_root(args)
    raw = r4_terminal_parallel_timeout_receipt(
        root, freeze, admission, repo=sealed_repo, review_marker=marker,
        **_systemd_timeout_observation())
    output = root / "r4-completion-timeout-receipt.json"
    digest = publish_exclusive_bytes(output, raw)
    _fsync_parent(output)
    _output({
        "schema": "belief-v1-v2-r4-timeout-receipt-published-v1",
        "receipt_path": str(output),
        "receipt_sha256": digest,
        "recovery_authorized": False,
        "outcome_bytes_opened": False,
        "test_split_reopened": False,
        "retry_authorized": False,
    })


def pending_recovery_review_claim(args: argparse.Namespace) -> None:
    (root, freeze, admission, marker, sealed_repo,
     recovery_execution) = _load_recovery_root(args)
    claim = r4_terminal_parallel_pending_recovery_review_claim(
        root, freeze, admission, repo=sealed_repo, review_marker=marker,
        recovery_execution=recovery_execution)
    sys.stdout.buffer.write(
        PENDING_RECOVERY_REVIEW_PREFIX.encode("ascii")
        + canonical_json_bytes(claim))


def recover_pending(args: argparse.Namespace) -> None:
    (root, freeze, admission, marker, sealed_repo,
     recovery_execution) = _load_recovery_root(args)
    _output(recover_r4_terminal_parallel_pending(
        root, freeze, admission, repo=sealed_repo, review_marker=marker,
        recovery_review_commit=args.recovery_review_commit,
        recovery_execution=recovery_execution))


def finalize_pending(args: argparse.Namespace) -> None:
    (root, freeze, admission, marker, sealed_repo,
     recovery_execution) = _load_recovery_root(args)
    _output(finalize_r4_terminal_parallel_pending(
        root, freeze, admission, repo=sealed_repo, review_marker=marker,
        recovery_review_commit=args.recovery_review_commit,
        recovery_execution=recovery_execution,
        progress=_progress("r4-terminal-pending-verifier")))


def verify_recovered_terminal(args: argparse.Namespace) -> None:
    """Receipt-only reopen after the sole pending verifier has completed."""
    (root, freeze, admission, marker, sealed_repo,
     _recovery_execution) = _load_recovery_root(args)
    _output(reopen_r4_terminal_parallel(
        root, freeze, admission, repo=sealed_repo, review_marker=marker,
        progress=_progress("r4-terminal-recovered-reopen")))


def _add_recovery_identity_arguments(
        command: argparse.ArgumentParser, *, reviewed: bool) -> None:
    command.add_argument("--root", required=True)
    command.add_argument("--sealed-repo", required=True)
    command.add_argument("--recovery-execution-git", required=True)
    if reviewed:
        command.add_argument(
            "--recovery-source-review-commit", required=True)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    initialize_command = commands.add_parser("initialize")
    initialize_command.add_argument("--freeze", required=True)
    initialize_command.add_argument("--expected-freeze-sha256", required=True)
    initialize_command.add_argument("--review-commit", required=True)
    initialize_command.add_argument("--inventory", required=True)
    initialize_command.add_argument("--group-split", required=True)
    initialize_command.add_argument("--capacity", required=True)
    initialize_command.add_argument(
        "--expected-capacity-sha256", required=True)
    initialize_command.set_defaults(function=initialize)
    capacity_command = commands.add_parser("capacity")
    capacity_command.add_argument("--expected-git", required=True)
    capacity_command.add_argument("--out", required=True)
    capacity_command.set_defaults(function=capacity)
    import_command = commands.add_parser("build-calibration-import")
    import_command.add_argument("--out", required=True)
    import_command.set_defaults(function=build_calibration_import)
    freeze_command = commands.add_parser("build-freeze")
    freeze_command.add_argument("--expected-git", required=True)
    freeze_command.add_argument("--source-review-commit", required=True)
    freeze_command.add_argument("--capacity", required=True)
    freeze_command.add_argument(
        "--expected-capacity-sha256", required=True)
    freeze_command.add_argument("--out", required=True)
    freeze_command.set_defaults(function=build_freeze)
    readiness_command = commands.add_parser("pretest-readiness")
    readiness_command.add_argument("--root", required=True)
    readiness_command.set_defaults(function=readiness)
    test_command = commands.add_parser("open-test")
    test_command.add_argument("--root", required=True)
    test_command.set_defaults(function=open_test)
    verify_command = commands.add_parser("verify-terminal")
    verify_command.add_argument("--root", required=True)
    verify_command.set_defaults(function=verify_terminal)
    recover_command = commands.add_parser("recover-terminal-binding")
    recover_command.add_argument("--root", required=True)
    recover_command.set_defaults(function=recover_terminal)
    timeout_command = commands.add_parser("build-timeout-receipt")
    _add_recovery_identity_arguments(timeout_command, reviewed=True)
    timeout_command.set_defaults(function=build_timeout_receipt)
    source_claim_command = commands.add_parser(
        "recovery-execution-review-claim")
    _add_recovery_identity_arguments(source_claim_command, reviewed=False)
    source_claim_command.set_defaults(
        function=recovery_execution_review_claim)
    claim_command = commands.add_parser("pending-recovery-review-claim")
    _add_recovery_identity_arguments(claim_command, reviewed=True)
    claim_command.set_defaults(function=pending_recovery_review_claim)
    pending_command = commands.add_parser("recover-pending")
    _add_recovery_identity_arguments(pending_command, reviewed=True)
    pending_command.add_argument("--recovery-review-commit", required=True)
    pending_command.set_defaults(function=recover_pending)
    finalize_command = commands.add_parser("finalize-pending")
    _add_recovery_identity_arguments(finalize_command, reviewed=True)
    finalize_command.add_argument("--recovery-review-commit", required=True)
    finalize_command.set_defaults(function=finalize_pending)
    verify_recovered_command = commands.add_parser(
        "verify-recovered-terminal")
    _add_recovery_identity_arguments(
        verify_recovered_command, reviewed=True)
    verify_recovered_command.set_defaults(function=verify_recovered_terminal)
    return result


def main() -> None:
    configure_numerical_runtime()
    args = parser().parse_args()
    args.function(args)


if __name__ == "__main__":
    main()

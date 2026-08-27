"""Terminal-only R4 successor importing one sealed calibration result.

The optimized terminal executable has a fresh reviewed freeze/admission and
fresh output namespace.  It never relabels the code that produced calibration:
the prior completion freeze, admission, review, source spec, calibration outer
manifest and selection manifest are all byte-bound and independently reopened
before the optimized scorer can consume the original R4 test split once.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import platform
from pathlib import Path
import resource
import time
from typing import Any

from .belief_artifacts import stable_read_bytes
from .belief_contract import canonical_json_bytes
from .belief_v2_freeze import (
    V2ExecutionFreezeV1,
    V2PipelineAdmissionV1,
    execution_freeze_from_bytes,
    validate_execution_freeze,
)
from .belief_v2_execution_identity import (
    V2RuntimeProfileV1,
    build_runtime_profile,
    build_source_bindings,
    source_manifest_sha256,
)
from .belief_v2_accelerator import build_training_device_profile
from .belief_v2_device_qualification import qualification_protocol_sha256
from .belief_v2_device_runner import host_peak_memory_bytes
from .belief_v2_input_index_controller import reopen_training_input_index
from .belief_v2_progress import ProgressCallback
from .belief_v2_r4_completion import (
    R4CompletionAdmissionV1,
    R4CompletionSourceSpecV1,
    R4CompletionSourceV1,
    _calibration_outer_manifest,
    _completion_stage_gate,
    _process_tree_cpu_time_ns,
    _projection_pool,
    _recover_r4_completion_terminal_reopened,
    _warm_projection_pool,
    _reopen_r4_completion_terminal_reopened,
    _run_r4_completion_terminal_reopened,
    load_r4_completion_source_spec,
    r4_completion_admission_from_bytes,
    reauthenticate_r4_completion_admission,
    reopen_r4_completion_source,
    validate_r4_completion_consumption_tombstone,
)
from .belief_v2_calibration_controller import (
    CALIBRATION_STAGE_SCHEMA,
    POPULATION_FILES as CALIBRATION_POPULATION_FILES,
    RESULT_FILES as CALIBRATION_RESULT_FILES,
    reopen_v2_calibration_selection,
)
from .belief_v2_scoring import (
    V2_DECISION_WORKERS,
    V2DecisionScoringPool,
    score_v2_round,
)
from .belief_v2_scoring_controller import (
    reopen_synthetic_scoring_round,
    reopen_trained_scoring_cohorts,
    synthetic_round_key,
)
from .belief_v2_protocol import (
    V2_RANKS,
    V2_SPLIT_COUNTS,
    v2_round_coordinates,
)
from .belief_v2_statistics import v2_round_population_bytes


IMPORT_SCHEMA = (
    "belief-v1-v2-r4-terminal-sealed-calibration-import-v2")
READINESS_SCHEMA = "belief-v1-v2-r4-terminal-parallel-readiness-v1"
CAPACITY_SCHEMA = "belief-v1-v2-r4-terminal-parallel-capacity-v1"
CAPACITY_MEASUREMENT_ORDER = "parallel-cold-then-serial-warm"
MAXIMUM_SYNTHETIC_DECISIONS_PER_ROUND = 128
SCIENTIFIC_UNIT_SCORING_PASSES = 2
INDEPENDENT_VERIFIER_SCORING_PASSES = 1
SCIENTIFIC_UNIT_CONTROL_REOPENS = 3
INDEPENDENT_VERIFIER_CONTROL_REOPENS = 2
CAPACITY_FIELDS = {
    "schema", "execution_git", "source_manifest_sha256", "runtime_sha256",
    "terminal_source_spec_sha256", "calibration_import_sha256",
    "calibration_manifest_sha256", "hostname", "machine", "rank_count",
    "trump_ranks", "round_keys", "decision_count", "population_sha256",
    "exact_serial_parallel_parity", "measurement_order",
    "serial_wall_nanoseconds",
    "parallel_wall_nanoseconds", "serial_cpu_nanoseconds",
    "parallel_cpu_nanoseconds", "speedup_ppb",
    "aggregate_peak_host_memory_upper_bound_bytes", "host_memory_cap_bytes",
    "host_memory_within_cap", "worker_count",
    "worker_cohort_identity", "synthetic_test_round_count",
    "human_test_decision_count", "maximum_synthetic_decisions_per_round",
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
    "deadline_safety_reserve_nanoseconds", "projected_within_wall_cap",
    "test_split_decision_open_count", "test_opening_executed",
    "execution_authorized", "strength_claim_authorized",
    "deployment_authorized",
}
IMPORT_AUTHORITY = {
    "calibration_generation_authorized": False,
    "calibration_import_authorized": True,
    "one_test_split_open_authorized": False,
    "terminal_reconstruction_authorized": True,
    "retry_authorized": False,
    "strength_claim_authorized": False,
    "deployment_authorized": False,
}
TERMINAL_SOURCE_SPEC_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" /
    "belief_v2_r4_terminal_parallel_source.v1.json")
CALIBRATION_IMPORT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" /
    "belief_v2_r4_terminal_parallel_import.v1.json")
ORIGINAL_COMPLETION_SOURCE_SPEC_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" /
    "belief_v2_r4_terminal_parallel_calibration_source.v1.json")
CALIBRATION_ROOT_POPULATION = {
    "admission.json", "calibration", "freeze.json", "group-split.json",
    "inventory.json", "review.md",
}
TERMINAL_NAMESPACE = {
    "r4-completion-test-attempt.json", "terminal.partial", "terminal",
    "r4-completion-terminal.json",
}


class BeliefV2R4TerminalParallelError(ValueError):
    """A terminal import, readiness boundary, or result drifted."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_sha256(value: Any) -> bool:
    return type(value) is str and len(value) == 64 and all(
        char in "0123456789abcdef" for char in value)


def _is_git_sha(value: Any) -> bool:
    return type(value) is str and len(value) == 40 and all(
        char in "0123456789abcdef" for char in value)


def _ceiling_ratio(numerator: int, denominator: int) -> int:
    if type(numerator) is not int or numerator <= 0 \
            or type(denominator) is not int or denominator <= 0:
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal capacity projection input drift")
    return (numerator + denominator - 1) // denominator


def _usage_memory_bytes(who: int) -> int:
    value = resource.getrusage(who).ru_maxrss
    if type(value) not in {int, float} or value < 0:
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal host memory measurement drift")
    return int(value) if platform.system() == "Darwin" else int(value) * 1024


def _aggregate_peak_host_memory_bytes(worker_count: int) -> int:
    if type(worker_count) is not int or worker_count <= 0:
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal worker memory population drift")
    parent = max(
        host_peak_memory_bytes(), _usage_memory_bytes(resource.RUSAGE_SELF))
    child = _usage_memory_bytes(resource.RUSAGE_CHILDREN)
    return max(parent, parent + child * worker_count if child else parent)


@dataclass(frozen=True)
class _CapacityContext:
    terminal_spec: R4CompletionSourceSpecV1
    calibration_import: R4TerminalCalibrationImportV1
    calibration: dict[str, Any]
    source: R4CompletionSourceV1
    source_bindings: tuple[Any, ...]
    runtime: V2RuntimeProfileV1
    cohorts: tuple[Any, ...]
    coordinates: tuple[Any, ...]
    decision_counts: tuple[int, ...]


@dataclass(frozen=True)
class R4TerminalCalibrationImportV1:
    calibration_evidence_root: Path
    calibration_execution_git: str
    calibration_freeze_sha256: str
    calibration_admission_sha256: str
    calibration_review_marker_sha256: str
    calibration_consumption_tombstone_sha256: str
    calibration_source_spec_sha256: str
    calibration_reconstructed_outer_sha256: str
    calibration_selection_manifest_sha256: str
    schema: str = IMPORT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "calibration_evidence_root": str(self.calibration_evidence_root),
            "calibration_execution_git": self.calibration_execution_git,
            "calibration_freeze_sha256": self.calibration_freeze_sha256,
            "calibration_admission_sha256": self.calibration_admission_sha256,
            "calibration_review_marker_sha256": (
                self.calibration_review_marker_sha256),
            "calibration_consumption_tombstone_sha256": (
                self.calibration_consumption_tombstone_sha256),
            "calibration_source_spec_sha256": (
                self.calibration_source_spec_sha256),
            "calibration_reconstructed_outer_sha256": (
                self.calibration_reconstructed_outer_sha256),
            "calibration_selection_manifest_sha256": (
                self.calibration_selection_manifest_sha256),
            "calibration_completion_outer_absent": True,
            "authority": dict(IMPORT_AUTHORITY),
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return _sha256(self.canonical_bytes())


def load_terminal_source_spec(
        raw: bytes | None = None) -> R4CompletionSourceSpecV1:
    if raw is None:
        raw = TERMINAL_SOURCE_SPEC_PATH.read_bytes()
    try:
        result = load_r4_completion_source_spec(raw)
    except ValueError as exc:
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal source spec refused") from exc
    return result


def load_calibration_import(
        raw: bytes | None = None) -> R4TerminalCalibrationImportV1:
    if raw is None:
        raw = CALIBRATION_IMPORT_PATH.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal calibration import is not JSON") from exc
    expected = {
        "schema", "calibration_evidence_root", "calibration_execution_git",
        "calibration_freeze_sha256", "calibration_admission_sha256",
        "calibration_review_marker_sha256",
        "calibration_consumption_tombstone_sha256",
        "calibration_source_spec_sha256",
        "calibration_reconstructed_outer_sha256",
        "calibration_selection_manifest_sha256", "authority",
        "calibration_completion_outer_absent",
    }
    hash_keys = expected - {
        "schema", "calibration_evidence_root", "calibration_execution_git",
        "authority", "calibration_completion_outer_absent",
    }
    if type(payload) is not dict or set(payload) != expected \
            or canonical_json_bytes(payload) != raw \
            or payload["schema"] != IMPORT_SCHEMA \
            or payload["authority"] != IMPORT_AUTHORITY \
            or payload["calibration_completion_outer_absent"] is not True \
            or any(not _is_sha256(payload[key]) for key in hash_keys) \
            or type(payload["calibration_execution_git"]) is not str \
            or len(payload["calibration_execution_git"]) != 40 \
            or any(char not in "0123456789abcdef"
                   for char in payload["calibration_execution_git"]):
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal calibration import field drift")
    root = Path(payload["calibration_evidence_root"])
    if not root.is_absolute():
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal calibration import path drift")
    result = R4TerminalCalibrationImportV1(
        calibration_evidence_root=root,
        calibration_execution_git=payload["calibration_execution_git"],
        calibration_freeze_sha256=payload["calibration_freeze_sha256"],
        calibration_admission_sha256=payload[
            "calibration_admission_sha256"],
        calibration_review_marker_sha256=payload[
            "calibration_review_marker_sha256"],
        calibration_consumption_tombstone_sha256=payload[
            "calibration_consumption_tombstone_sha256"],
        calibration_source_spec_sha256=payload[
            "calibration_source_spec_sha256"],
        calibration_reconstructed_outer_sha256=payload[
            "calibration_reconstructed_outer_sha256"],
        calibration_selection_manifest_sha256=payload[
            "calibration_selection_manifest_sha256"],
    )
    if result.canonical_bytes() != raw:
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal calibration import reconstruction drift")
    return result


def _reopen_bound_calibration_selection(
        directory: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1) -> dict[str, Any]:
    """Reopen exact selection bytes after their deep import was committed.

    This does not re-score epoch curves.  The import builder does that once;
    this path proves that every immutable byte consumed later is the same byte
    population that the deep reconstruction certified.
    """
    filenames = {
        **CALIBRATION_POPULATION_FILES, **CALIBRATION_RESULT_FILES}
    expected_names = {"manifest.json", *filenames.values()}
    if not isinstance(directory, Path) or directory.is_symlink() \
            or not directory.is_dir() \
            or {path.name for path in directory.iterdir()} != expected_names:
        raise BeliefV2R4TerminalParallelError(
            "R4 bound calibration directory population drift")
    manifest_raw = stable_read_bytes(directory / "manifest.json")
    try:
        payload = json.loads(manifest_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2R4TerminalParallelError(
            "R4 bound calibration manifest is not JSON") from exc
    expected_keys = {
        "schema", "freeze_sha256", "admission_sha256",
        "training_input_sha256", "qualification_plan_sha256",
        "qualification_result_sha256", "training_manifest_sha256s",
        "cohort_ids", "files",
        "synthetic_reference_replicates_stable",
        "human_reference_replicates_stable", "calibration_passed",
        "human_mixture_retained", "selected_cohort_id", "resources",
        "selection_completed_before_test_open", "test_split_opened",
        "test_open_authorized_by_this_artifact",
        "sampler_implementation_authorized",
        "gameplay_strength_screen_authorized", "strength_claim_authorized",
        "deployment_authorized",
    }
    cohort_ids = [row.cohort_id for row in freeze.cohorts]
    if type(payload) is not dict or set(payload) != expected_keys \
            or canonical_json_bytes(payload) != manifest_raw \
            or payload["schema"] != CALIBRATION_STAGE_SCHEMA \
            or payload["freeze_sha256"] != freeze.sha256() \
            or payload["admission_sha256"] != admission.sha256() \
            or payload["cohort_ids"] != cohort_ids \
            or type(payload["files"]) is not dict \
            or set(payload["files"]) != set(filenames) \
            or payload["calibration_passed"] is not True \
            or payload["selected_cohort_id"] not in cohort_ids \
            or payload["selection_completed_before_test_open"] is not True \
            or payload["test_split_opened"] is not False \
            or any(payload[key] is not False for key in (
                "test_open_authorized_by_this_artifact",
                "sampler_implementation_authorized",
                "gameplay_strength_screen_authorized",
                "strength_claim_authorized", "deployment_authorized")):
        raise BeliefV2R4TerminalParallelError(
            "R4 bound calibration manifest identity/authority drift")
    for key, filename in filenames.items():
        raw = stable_read_bytes(directory / filename)
        row = payload["files"].get(key)
        if type(row) is not dict or set(row) != {
                "filename", "byte_count", "sha256"} \
                or row["filename"] != filename \
                or row["byte_count"] != len(raw) \
                or row["sha256"] != _sha256(raw):
            raise BeliefV2R4TerminalParallelError(
                "R4 bound calibration file byte binding drift")
    return payload


def _reopen_sealed_calibration_source(
        terminal_spec: R4CompletionSourceSpecV1, *, repo: Path,
        rederive_selection: bool = True) -> tuple[
            dict[str, Any], R4CompletionSourceV1, Path,
            R4CompletionSourceSpecV1, V2ExecutionFreezeV1,
            R4CompletionAdmissionV1, dict[str, bytes]]:
    """Authenticate and reconstruct the prior sealed inner selection."""
    old_spec_raw = ORIGINAL_COMPLETION_SOURCE_SPEC_PATH.read_bytes()
    old_spec = load_r4_completion_source_spec(old_spec_raw)
    root = old_spec.destination_evidence_root
    if root.is_symlink() or not root.is_dir() \
            or {path.name for path in root.iterdir()} \
            != CALIBRATION_ROOT_POPULATION \
            or {path.name for path in (root / "calibration").iterdir()} \
            != {"selection"} \
            or (root / "calibration" / "completion.json").exists() \
            or (root / "calibration" / "completion.json").is_symlink() \
            or any((root / name).exists() or (root / name).is_symlink()
                   for name in TERMINAL_NAMESPACE):
        raise BeliefV2R4TerminalParallelError(
            "R4 imported calibration namespace drift")
    freeze_raw = stable_read_bytes(root / "freeze.json")
    admission_raw = stable_read_bytes(root / "admission.json")
    marker = stable_read_bytes(root / "review.md")
    tombstone_raw = stable_read_bytes(
        root.with_name(root.name + ".consumed.json"))
    selection_raw = stable_read_bytes(
        root / "calibration" / "selection" / "manifest.json")
    try:
        old_freeze = execution_freeze_from_bytes(freeze_raw)
        old_admission = r4_completion_admission_from_bytes(
            admission_raw, freeze=old_freeze, review_marker=marker,
            spec=old_spec)
        validate_r4_completion_consumption_tombstone(
            tombstone_raw, admission=old_admission)
        reauthenticate_r4_completion_admission(
            old_freeze, old_admission, repo=repo, review_marker=marker,
            spec=old_spec)
        source = reopen_r4_completion_source(old_spec, repo=repo)
        selection = root / "calibration" / "selection"
        calibration = (
            reopen_v2_calibration_selection(
                selection, freeze=source.freeze,
                admission=source.admission, inventory=source.inventory,
                group_split=source.group_split,
                legacy_tensor_cache_manifest_sha256=(
                    source.spec.source_tensor_cache_manifest_sha256))
            if rederive_selection else
            _reopen_bound_calibration_selection(
                selection, freeze=source.freeze,
                admission=source.admission))
    except (ValueError, json.JSONDecodeError) as exc:
        raise BeliefV2R4TerminalParallelError(
            "R4 imported calibration reopen refused") from exc
    expected_outer = _calibration_outer_manifest(
        completion_freeze=old_freeze,
        completion_admission=old_admission, source=source,
        source_calibration_manifest=calibration)
    rebound_source = R4CompletionSourceV1(
        terminal_spec, source.freeze, source.admission,
        source.review_marker, source.inventory, source.group_split)
    raw_inputs = {
        "freeze": freeze_raw,
        "admission": admission_raw,
        "review": marker,
        "consumption": tombstone_raw,
        "source_spec": old_spec_raw,
        "selection": selection_raw,
        "reconstructed_outer": canonical_json_bytes(expected_outer),
    }
    return (
        calibration, rebound_source, root / "calibration" / "selection",
        old_spec, old_freeze, old_admission, raw_inputs)


def build_r4_terminal_calibration_import(*, repo: Path) \
        -> R4TerminalCalibrationImportV1:
    """Build one exact import after independently reopening sealed selection."""
    terminal_spec = load_terminal_source_spec()
    _, _, selection, old_spec, old_freeze, _, raw = (
        _reopen_sealed_calibration_source(terminal_spec, repo=repo))
    if selection.parent.parent != old_spec.destination_evidence_root:
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal calibration import source root drift")
    return R4TerminalCalibrationImportV1(
        calibration_evidence_root=old_spec.destination_evidence_root,
        calibration_execution_git=old_freeze.execution_git,
        calibration_freeze_sha256=_sha256(raw["freeze"]),
        calibration_admission_sha256=_sha256(raw["admission"]),
        calibration_review_marker_sha256=_sha256(raw["review"]),
        calibration_consumption_tombstone_sha256=_sha256(
            raw["consumption"]),
        calibration_source_spec_sha256=_sha256(raw["source_spec"]),
        calibration_reconstructed_outer_sha256=_sha256(
            raw["reconstructed_outer"]),
        calibration_selection_manifest_sha256=_sha256(raw["selection"]),
    )


def reopen_imported_calibration(
        terminal_spec: R4CompletionSourceSpecV1,
        calibration_import: R4TerminalCalibrationImportV1, *, repo: Path) \
        -> tuple[dict[str, Any], R4CompletionSourceV1, Path]:
    """Authenticate a sealed selection whose outer reconstruction failed."""
    calibration, source, selection, old_spec, old_freeze, _, raw = (
        _reopen_sealed_calibration_source(terminal_spec, repo=repo))
    expected = {
        "freeze": calibration_import.calibration_freeze_sha256,
        "admission": calibration_import.calibration_admission_sha256,
        "review": calibration_import.calibration_review_marker_sha256,
        "consumption": (
            calibration_import.calibration_consumption_tombstone_sha256),
        "source_spec": calibration_import.calibration_source_spec_sha256,
        "selection": calibration_import.calibration_selection_manifest_sha256,
        "reconstructed_outer": (
            calibration_import.calibration_reconstructed_outer_sha256),
    }
    if any(_sha256(raw[key]) != digest for key, digest in expected.items()):
        raise BeliefV2R4TerminalParallelError(
            "R4 imported calibration byte binding drift")
    if old_freeze.execution_git \
            != calibration_import.calibration_execution_git \
            or old_spec.destination_evidence_root \
            != calibration_import.calibration_evidence_root:
        raise BeliefV2R4TerminalParallelError(
            "R4 imported calibration reconstructed outer binding drift")
    return calibration, source, selection


def reopen_bound_imported_calibration(
        terminal_spec: R4CompletionSourceSpecV1,
        calibration_import: R4TerminalCalibrationImportV1, *, repo: Path) \
        -> tuple[dict[str, Any], R4CompletionSourceV1, Path]:
    """Authenticate imported bytes without repeating their deep derivation."""
    calibration, source, selection, old_spec, old_freeze, _, raw = (
        _reopen_sealed_calibration_source(
            terminal_spec, repo=repo, rederive_selection=False))
    expected = {
        "freeze": calibration_import.calibration_freeze_sha256,
        "admission": calibration_import.calibration_admission_sha256,
        "review": calibration_import.calibration_review_marker_sha256,
        "consumption": (
            calibration_import.calibration_consumption_tombstone_sha256),
        "source_spec": calibration_import.calibration_source_spec_sha256,
        "selection": calibration_import.calibration_selection_manifest_sha256,
        "reconstructed_outer": (
            calibration_import.calibration_reconstructed_outer_sha256),
    }
    if any(_sha256(raw[key]) != digest for key, digest in expected.items()):
        raise BeliefV2R4TerminalParallelError(
            "R4 bound calibration byte binding drift")
    if old_freeze.execution_git \
            != calibration_import.calibration_execution_git \
            or old_spec.destination_evidence_root \
            != calibration_import.calibration_evidence_root:
        raise BeliefV2R4TerminalParallelError(
            "R4 bound calibration reconstructed outer binding drift")
    return calibration, source, selection


def _parity_coordinates():
    rows = []
    for rank in V2_RANKS:
        matches = tuple(
            row for row in v2_round_coordinates()
            if row.trump_rank == rank and row.split == "calibration")
        if not matches:
            raise BeliefV2R4TerminalParallelError(
                "R4 terminal parity calibration rank is empty")
        rows.append(matches[0])
    return tuple(rows)


def _capacity_context(*, repo: Path, expected_git: str) -> _CapacityContext:
    if not _is_git_sha(expected_git):
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal capacity execution Git drift")
    terminal_spec = load_terminal_source_spec()
    calibration_import = load_calibration_import()
    bindings = build_source_bindings(repo, expected_git=expected_git)
    runtime = build_runtime_profile()
    calibration, source, _ = reopen_bound_imported_calibration(
        terminal_spec, calibration_import, repo=repo)
    coordinates = _parity_coordinates()
    try:
        _, training_inputs = reopen_training_input_index(
            source.spec.source_evidence_root / "training-input-index" /
            "result", freeze=source.freeze, admission=source.admission)
        cohorts, _, _, _ = reopen_trained_scoring_cohorts(
            source.spec.source_evidence_root, freeze=source.freeze,
            admission=source.admission, training_inputs=training_inputs,
            legacy_tensor_cache_manifest_sha256=(
                source.spec.source_tensor_cache_manifest_sha256))
        decision_counts = tuple(len(reopen_synthetic_scoring_round(
            source.spec.source_evidence_root, freeze=source.freeze,
            admission=source.admission, coordinate=coordinate,
            replicate="calibration-replicate-0",
            allowed_split="calibration")) for coordinate in coordinates)
    except ValueError as exc:
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal capacity model/input reopen refused") from exc
    if any(type(value) is not int or value <= 0
           or value > MAXIMUM_SYNTHETIC_DECISIONS_PER_ROUND
           for value in decision_counts):
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal capacity decision population drift")
    return _CapacityContext(
        terminal_spec=terminal_spec,
        calibration_import=calibration_import,
        calibration=calibration,
        source=source,
        source_bindings=bindings,
        runtime=runtime,
        cohorts=cohorts,
        coordinates=coordinates,
        decision_counts=decision_counts)


def r4_terminal_parallel_capacity(
        *, repo: Path, expected_git: str,
        progress: ProgressCallback | None = None) -> dict[str, Any]:
    """Measure exact old/new parity on calibration only, never test."""
    control_reopen_started = time.monotonic_ns()
    context = _capacity_context(repo=repo, expected_git=expected_git)
    control_reopen_wall = time.monotonic_ns() - control_reopen_started
    if control_reopen_wall <= 0:
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal control reopen capacity clock drift")
    terminal_spec = context.terminal_spec
    calibration_import = context.calibration_import
    calibration = context.calibration
    source = context.source
    bindings = context.source_bindings
    runtime = context.runtime
    cohorts = context.cohorts
    coordinates = context.coordinates
    cohort_ids = tuple(row.cohort_id for row in cohorts)

    # Run the candidate first so it pays cold worker/runtime startup while the
    # serial control gets any cache benefit.  A speedup that survives this
    # ordering is conservative enough to size the one-shot terminal deadline.
    capacity_units = 2 * len(coordinates)
    if progress is not None:
        progress(0, capacity_units, "measure-terminal-capacity-ranks")
    parallel_started = time.monotonic_ns()
    parallel_cpu_started = _process_tree_cpu_time_ns()
    parallel = []
    with V2DecisionScoringPool(cohorts) as decision_pool:
        decision_pool.warm()
        for index, coordinate in enumerate(coordinates):
            decisions = reopen_synthetic_scoring_round(
                source.spec.source_evidence_root, freeze=source.freeze,
                admission=source.admission, coordinate=coordinate,
                replicate="calibration-replicate-0",
                allowed_split="calibration")
            parallel.append(score_v2_round(
                round_key=synthetic_round_key(coordinate.round_seed),
                source_kind="synthetic", split="calibration",
                trump_rank=coordinate.trump_rank, decisions=decisions,
                cohorts=cohorts, decision_pool=decision_pool))
            if progress is not None:
                progress(index + 1, capacity_units,
                         "measure-terminal-capacity-ranks")
        worker_identity = decision_pool.cohort_identity
    parallel_finished = time.monotonic_ns()
    parallel_cpu = _process_tree_cpu_time_ns() - parallel_cpu_started

    serial_started = time.monotonic_ns()
    serial_cpu_started = _process_tree_cpu_time_ns()
    serial = []
    with _projection_pool() as projection_executor:
        _warm_projection_pool(projection_executor)
        for index, coordinate in enumerate(coordinates):
            decisions = reopen_synthetic_scoring_round(
                source.spec.source_evidence_root, freeze=source.freeze,
                admission=source.admission, coordinate=coordinate,
                replicate="calibration-replicate-0",
                allowed_split="calibration")
            serial.append(score_v2_round(
                round_key=synthetic_round_key(coordinate.round_seed),
                source_kind="synthetic", split="calibration",
                trump_rank=coordinate.trump_rank, decisions=decisions,
                cohorts=cohorts, projection_executor=projection_executor))
            if progress is not None:
                progress(len(coordinates) + index + 1, capacity_units,
                         "measure-terminal-capacity-ranks")
    serial_finished = time.monotonic_ns()
    serial_cpu = _process_tree_cpu_time_ns() - serial_cpu_started

    serial_raw = v2_round_population_bytes(
        tuple(serial), cohort_ids=cohort_ids,
        label="r4-terminal-parity")
    parallel_raw = v2_round_population_bytes(
        tuple(parallel), cohort_ids=cohort_ids,
        label="r4-terminal-parity")
    serial_wall = serial_finished - serial_started
    parallel_wall = parallel_finished - parallel_started
    if serial_raw != parallel_raw or parallel_wall <= 0 \
            or parallel_wall >= serial_wall:
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal parity or capacity gate refused")
    if any((calibration_import.calibration_evidence_root / name).exists()
           or (calibration_import.calibration_evidence_root / name).is_symlink()
           for name in TERMINAL_NAMESPACE):
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal capacity observed a consumed test namespace")
    decision_count = sum(context.decision_counts)
    if decision_count != sum(row.decision_count for row in serial) \
            or decision_count != sum(row.decision_count for row in parallel):
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal parity decision count drift")
    synthetic_test_round_count = dict(V2_SPLIT_COUNTS)["test"]
    human_test_decision_count = (
        source.freeze.human_test_eligible_decision_count)
    projected_maximum_test_decision_count = (
        synthetic_test_round_count
        * MAXIMUM_SYNTHETIC_DECISIONS_PER_ROUND
        + human_test_decision_count)
    projected_one_pass_wall = _ceiling_ratio(
        parallel_wall * projected_maximum_test_decision_count,
        decision_count)
    projected_scientific_control_wall = (
        control_reopen_wall * SCIENTIFIC_UNIT_CONTROL_REOPENS)
    projected_verifier_control_wall = (
        control_reopen_wall * INDEPENDENT_VERIFIER_CONTROL_REOPENS)
    projected_scientific_wall = (
        projected_one_pass_wall * SCIENTIFIC_UNIT_SCORING_PASSES
        + projected_scientific_control_wall)
    projected_verifier_wall = (
        projected_one_pass_wall * INDEPENDENT_VERIFIER_SCORING_PASSES
        + projected_verifier_control_wall)
    caps = source.freeze.resource_caps
    wall_cap = caps.training_wall_seconds * 1_000_000_000
    reserve = caps.deadline_safety_reserve_nanoseconds
    aggregate_peak_host_memory = _aggregate_peak_host_memory_bytes(
        V2_DECISION_WORKERS)
    if projected_scientific_wall + reserve >= wall_cap \
            or projected_verifier_wall + reserve >= wall_cap \
            or aggregate_peak_host_memory \
            > caps.training_host_memory_bytes:
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal projected scorer exceeds frozen resource cap")
    return {
        "schema": CAPACITY_SCHEMA,
        "execution_git": expected_git,
        "source_manifest_sha256": source_manifest_sha256(
            expected_git, bindings),
        "runtime_sha256": _sha256(canonical_json_bytes(runtime.to_dict())),
        "terminal_source_spec_sha256": terminal_spec.sha256(),
        "calibration_import_sha256": calibration_import.sha256(),
        "calibration_manifest_sha256": _sha256(
            canonical_json_bytes(calibration)),
        "hostname": platform.node(),
        "machine": platform.machine(),
        "rank_count": len(coordinates),
        "trump_ranks": [row.trump_rank for row in coordinates],
        "round_keys": [synthetic_round_key(row.round_seed)
                       for row in coordinates],
        "decision_count": decision_count,
        "population_sha256": _sha256(serial_raw),
        "exact_serial_parallel_parity": True,
        "measurement_order": CAPACITY_MEASUREMENT_ORDER,
        "serial_wall_nanoseconds": serial_wall,
        "parallel_wall_nanoseconds": parallel_wall,
        "serial_cpu_nanoseconds": serial_cpu,
        "parallel_cpu_nanoseconds": parallel_cpu,
        "speedup_ppb": (serial_wall * 1_000_000_000 // parallel_wall),
        "aggregate_peak_host_memory_upper_bound_bytes": (
            aggregate_peak_host_memory),
        "host_memory_cap_bytes": caps.training_host_memory_bytes,
        "host_memory_within_cap": True,
        "worker_count": V2_DECISION_WORKERS,
        "worker_cohort_identity": [
            [cohort_id, list(digests)]
            for cohort_id, digests in worker_identity],
        "synthetic_test_round_count": synthetic_test_round_count,
        "human_test_decision_count": human_test_decision_count,
        "maximum_synthetic_decisions_per_round": (
            MAXIMUM_SYNTHETIC_DECISIONS_PER_ROUND),
        "projected_maximum_test_decision_count": (
            projected_maximum_test_decision_count),
        "scientific_unit_scoring_pass_count": (
            SCIENTIFIC_UNIT_SCORING_PASSES),
        "independent_verifier_scoring_pass_count": (
            INDEPENDENT_VERIFIER_SCORING_PASSES),
        "control_reopen_wall_nanoseconds": control_reopen_wall,
        "scientific_unit_control_reopen_count": (
            SCIENTIFIC_UNIT_CONTROL_REOPENS),
        "independent_verifier_control_reopen_count": (
            INDEPENDENT_VERIFIER_CONTROL_REOPENS),
        "projected_scientific_control_wall_nanoseconds": (
            projected_scientific_control_wall),
        "projected_independent_verifier_control_wall_nanoseconds": (
            projected_verifier_control_wall),
        "projected_one_pass_wall_nanoseconds": projected_one_pass_wall,
        "projected_scientific_unit_wall_nanoseconds": (
            projected_scientific_wall),
        "projected_independent_verifier_wall_nanoseconds": (
            projected_verifier_wall),
        "terminal_wall_cap_nanoseconds": wall_cap,
        "deadline_safety_reserve_nanoseconds": reserve,
        "projected_within_wall_cap": True,
        "test_split_decision_open_count": 0,
        "test_opening_executed": False,
        "execution_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def _validate_capacity_receipt(
        raw: bytes, *, context: _CapacityContext,
        expected_git: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal capacity receipt is not JSON") from exc
    if type(payload) is not dict or set(payload) != CAPACITY_FIELDS \
            or canonical_json_bytes(payload) != raw:
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal capacity receipt field/canonical drift")
    coordinates = context.coordinates
    expected_cohort_identity = [
        [row.cohort_id, list(row.model_sha256s)]
        for row in context.cohorts]
    decision_count = sum(context.decision_counts)
    synthetic_test_round_count = dict(V2_SPLIT_COUNTS)["test"]
    human_test_decision_count = (
        context.source.freeze.human_test_eligible_decision_count)
    maximum_test_decisions = (
        synthetic_test_round_count * MAXIMUM_SYNTHETIC_DECISIONS_PER_ROUND
        + human_test_decision_count)
    caps = context.source.freeze.resource_caps
    wall_cap = caps.training_wall_seconds * 1_000_000_000
    reserve = caps.deadline_safety_reserve_nanoseconds
    positive_integer_fields = (
        "rank_count", "decision_count", "serial_wall_nanoseconds",
        "parallel_wall_nanoseconds", "serial_cpu_nanoseconds",
        "parallel_cpu_nanoseconds", "speedup_ppb",
        "aggregate_peak_host_memory_upper_bound_bytes",
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
    if any(type(payload[key]) is not int or payload[key] <= 0
           for key in positive_integer_fields):
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal capacity receipt reconstruction drift")
    serial_wall = payload["serial_wall_nanoseconds"]
    parallel_wall = payload["parallel_wall_nanoseconds"]
    one_pass = _ceiling_ratio(
        parallel_wall * maximum_test_decisions, decision_count)
    control_reopen_wall = payload["control_reopen_wall_nanoseconds"]
    scientific_control_wall = (
        control_reopen_wall * SCIENTIFIC_UNIT_CONTROL_REOPENS)
    verifier_control_wall = (
        control_reopen_wall * INDEPENDENT_VERIFIER_CONTROL_REOPENS)
    scientific_wall = (
        one_pass * SCIENTIFIC_UNIT_SCORING_PASSES
        + scientific_control_wall)
    verifier_wall = (
        one_pass * INDEPENDENT_VERIFIER_SCORING_PASSES
        + verifier_control_wall)
    expected_runtime_sha = _sha256(canonical_json_bytes(
        context.runtime.to_dict()))
    if payload["schema"] != CAPACITY_SCHEMA \
            or payload["execution_git"] != expected_git \
            or payload["source_manifest_sha256"] \
            != source_manifest_sha256(
                expected_git, context.source_bindings) \
            or payload["runtime_sha256"] != expected_runtime_sha \
            or payload["terminal_source_spec_sha256"] \
            != context.terminal_spec.sha256() \
            or payload["calibration_import_sha256"] \
            != context.calibration_import.sha256() \
            or payload["calibration_manifest_sha256"] != _sha256(
                canonical_json_bytes(context.calibration)) \
            or payload["hostname"] != context.runtime.hostname \
            or payload["machine"] != context.runtime.machine \
            or payload["rank_count"] != len(V2_RANKS) \
            or payload["trump_ranks"] \
            != [row.trump_rank for row in coordinates] \
            or payload["round_keys"] != [
                synthetic_round_key(row.round_seed) for row in coordinates] \
            or payload["decision_count"] != decision_count \
            or not _is_sha256(payload["population_sha256"]) \
            or payload["exact_serial_parallel_parity"] is not True \
            or payload["measurement_order"] \
            != CAPACITY_MEASUREMENT_ORDER \
            or parallel_wall >= serial_wall \
            or payload["speedup_ppb"] \
            != serial_wall * 1_000_000_000 // parallel_wall \
            or payload["speedup_ppb"] <= 1_000_000_000 \
            or payload["host_memory_cap_bytes"] \
            != caps.training_host_memory_bytes \
            or payload["aggregate_peak_host_memory_upper_bound_bytes"] \
            > payload["host_memory_cap_bytes"] \
            or payload["host_memory_within_cap"] is not True \
            or payload["worker_count"] != V2_DECISION_WORKERS \
            or payload["worker_cohort_identity"] \
            != expected_cohort_identity \
            or payload["synthetic_test_round_count"] \
            != synthetic_test_round_count \
            or payload["human_test_decision_count"] \
            != human_test_decision_count \
            or payload["maximum_synthetic_decisions_per_round"] \
            != MAXIMUM_SYNTHETIC_DECISIONS_PER_ROUND \
            or payload["projected_maximum_test_decision_count"] \
            != maximum_test_decisions \
            or payload["scientific_unit_scoring_pass_count"] \
            != SCIENTIFIC_UNIT_SCORING_PASSES \
            or payload["independent_verifier_scoring_pass_count"] \
            != INDEPENDENT_VERIFIER_SCORING_PASSES \
            or payload["scientific_unit_control_reopen_count"] \
            != SCIENTIFIC_UNIT_CONTROL_REOPENS \
            or payload["independent_verifier_control_reopen_count"] \
            != INDEPENDENT_VERIFIER_CONTROL_REOPENS \
            or payload["projected_scientific_control_wall_nanoseconds"] \
            != scientific_control_wall \
            or payload[
                "projected_independent_verifier_control_wall_nanoseconds"] \
            != verifier_control_wall \
            or payload["projected_one_pass_wall_nanoseconds"] != one_pass \
            or payload["projected_scientific_unit_wall_nanoseconds"] \
            != scientific_wall \
            or payload["projected_independent_verifier_wall_nanoseconds"] \
            != verifier_wall \
            or payload["terminal_wall_cap_nanoseconds"] != wall_cap \
            or payload["deadline_safety_reserve_nanoseconds"] != reserve \
            or scientific_wall + reserve >= wall_cap \
            or verifier_wall + reserve >= wall_cap \
            or payload["projected_within_wall_cap"] is not True \
            or payload["test_split_decision_open_count"] != 0 \
            or payload["test_opening_executed"] is not False \
            or payload["execution_authorized"] is not False \
            or payload["strength_claim_authorized"] is not False \
            or payload["deployment_authorized"] is not False:
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal capacity receipt reconstruction drift")
    return payload


def reopen_r4_terminal_parallel_capacity(
        raw: bytes, *, repo: Path, expected_git: str) -> dict[str, Any]:
    """Reopen the exact all-rank parity/deadline receipt without test."""
    context = _capacity_context(repo=repo, expected_git=expected_git)
    return _validate_capacity_receipt(
        raw, context=context, expected_git=expected_git)


def build_r4_terminal_parallel_freeze(
        *, repo: Path, expected_git: str, source_review_commit: str,
        capacity_raw: bytes) -> V2ExecutionFreezeV1:
    """Bind the terminal source, live runtime, capacity and imported R4."""
    if not _is_git_sha(source_review_commit):
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal source review commit drift")
    context = _capacity_context(repo=repo, expected_git=expected_git)
    capacity = _validate_capacity_receipt(
        capacity_raw, context=context, expected_git=expected_git)
    try:
        device_profile = build_training_device_profile(
            context.source.freeze.training_candidate_device)
    except ValueError as exc:
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal live device profile refused") from exc
    capacity_sha = _sha256(capacity_raw)
    runtime_sha = _sha256(canonical_json_bytes(context.runtime.to_dict()))
    if capacity["runtime_sha256"] != runtime_sha:
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal capacity/runtime binding drift")
    freeze = replace(
        context.source.freeze,
        execution_git=expected_git,
        source_manifest_sha256=source_manifest_sha256(
            expected_git, context.source_bindings),
        source_bindings=context.source_bindings,
        runtime=context.runtime,
        source_review_commit=source_review_commit,
        preflight_result_sha256=capacity_sha,
        preflight_runtime_sha256=runtime_sha,
        deadline_estimate_receipt_sha256=capacity_sha,
        training_device_profile=device_profile,
        device_qualification_protocol_sha256=(
            qualification_protocol_sha256(
                context.source.freeze.training_candidate_device)),
        evidence_root=str(context.terminal_spec.destination_evidence_root))
    try:
        validate_execution_freeze(freeze)
    except ValueError as exc:
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal execution freeze refused") from exc
    return freeze


def _stage(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: R4CompletionAdmissionV1, *, repo: Path,
        review_marker: bytes) -> tuple[
            R4CompletionSourceSpecV1, R4TerminalCalibrationImportV1]:
    terminal_spec = load_terminal_source_spec()
    calibration_import = load_calibration_import()
    _completion_stage_gate(
        root, freeze, admission, repo=repo, review_marker=review_marker,
        spec=terminal_spec)
    if root == calibration_import.calibration_evidence_root:
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal and calibration roots overlap")
    return terminal_spec, calibration_import


def r4_terminal_parallel_readiness(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: R4CompletionAdmissionV1, *, repo: Path,
        review_marker: bytes) -> dict[str, Any]:
    """Prove imported calibration, workers and untouched test namespace."""
    terminal_spec, calibration_import = _stage(
        root, freeze, admission, repo=repo, review_marker=review_marker)
    if any((root / name).exists() or (root / name).is_symlink()
           for name in TERMINAL_NAMESPACE):
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal pretest namespace is occupied")
    calibration, source, calibration_directory = (
        reopen_bound_imported_calibration(
            terminal_spec, calibration_import, repo=repo))
    try:
        _, training_inputs = reopen_training_input_index(
            source.spec.source_evidence_root / "training-input-index" /
            "result", freeze=source.freeze, admission=source.admission)
        cohorts, _, _, _ = reopen_trained_scoring_cohorts(
            source.spec.source_evidence_root, freeze=source.freeze,
            admission=source.admission, training_inputs=training_inputs,
            legacy_tensor_cache_manifest_sha256=(
                source.spec.source_tensor_cache_manifest_sha256))
        with V2DecisionScoringPool(cohorts) as decision_pool:
            decision_pool.warm()
            worker_identity = decision_pool.cohort_identity
    except ValueError as exc:
        raise BeliefV2R4TerminalParallelError(
            "R4 terminal pretest worker qualification refused") from exc
    return {
        "schema": READINESS_SCHEMA,
        "freeze_sha256": freeze.sha256(),
        "admission_sha256": admission.sha256(),
        "terminal_source_spec_sha256": terminal_spec.sha256(),
        "calibration_import_sha256": calibration_import.sha256(),
        "calibration_manifest_sha256": _sha256(
            canonical_json_bytes(calibration)),
        "calibration_directory": str(calibration_directory),
        "worker_cohort_identity": [
            [cohort_id, list(digests)]
            for cohort_id, digests in worker_identity],
        "worker_startup_passed": True,
        "test_attempt_absent": True,
        "terminal_population_absent": True,
        "test_opening_executed": False,
        "execution_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def run_r4_terminal_parallel(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: R4CompletionAdmissionV1, *, repo: Path,
        review_marker: bytes,
        progress: ProgressCallback | None = None) -> dict[str, Any]:
    terminal_spec, calibration_import = _stage(
        root, freeze, admission, repo=repo, review_marker=review_marker)
    calibration, source, calibration_directory = (
        reopen_bound_imported_calibration(
            terminal_spec, calibration_import, repo=repo))
    return _run_r4_completion_terminal_reopened(
        root, freeze, admission, calibration=calibration, source=source,
        calibration_directory=calibration_directory,
        bound_calibration_manifest=calibration, progress=progress)


def reopen_r4_terminal_parallel(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: R4CompletionAdmissionV1, *, repo: Path,
        review_marker: bytes,
        progress: ProgressCallback | None = None) -> dict[str, Any]:
    terminal_spec, calibration_import = _stage(
        root, freeze, admission, repo=repo, review_marker=review_marker)
    calibration, source, calibration_directory = (
        reopen_bound_imported_calibration(
            terminal_spec, calibration_import, repo=repo))
    return _reopen_r4_completion_terminal_reopened(
        root, freeze, admission, calibration=calibration, source=source,
        calibration_directory=calibration_directory,
        bound_calibration_manifest=calibration, progress=progress)


def recover_r4_terminal_parallel(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: R4CompletionAdmissionV1, *, repo: Path,
        review_marker: bytes,
        progress: ProgressCallback | None = None) -> dict[str, Any]:
    """Recover only a missing outer binding from a sealed inner terminal."""
    terminal_spec, calibration_import = _stage(
        root, freeze, admission, repo=repo, review_marker=review_marker)
    calibration, source, calibration_directory = (
        reopen_bound_imported_calibration(
            terminal_spec, calibration_import, repo=repo))
    return _recover_r4_completion_terminal_reopened(
        root, freeze, admission, calibration=calibration, source=source,
        calibration_directory=calibration_directory,
        bound_calibration_manifest=calibration, progress=progress)


__all__ = [
    "BeliefV2R4TerminalParallelError", "R4TerminalCalibrationImportV1",
    "build_r4_terminal_calibration_import",
    "build_r4_terminal_parallel_freeze",
    "load_calibration_import", "load_terminal_source_spec",
    "r4_terminal_parallel_capacity", "reopen_r4_terminal_parallel_capacity",
    "r4_terminal_parallel_readiness", "reopen_bound_imported_calibration",
    "reopen_imported_calibration",
    "recover_r4_terminal_parallel", "reopen_r4_terminal_parallel",
    "run_r4_terminal_parallel",
]

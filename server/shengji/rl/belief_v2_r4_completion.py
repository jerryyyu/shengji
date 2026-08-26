"""Fresh, one-shot completion of the sealed BELIEF R4 scientific run.

R4 sealed every capture, reference, cache, device and training artifact before
the first trained-model calibration pass exposed a projection defect.  Its
admission is spent and its evidence tree is immutable.  This module therefore
uses two deliberately separate identities:

* a fresh reviewed V2 freeze/admission gates the repaired executable and the
  new completion namespace; and
* the original R4 freeze/admission authenticates every scientific input and
  remains the identity used by calibration and terminal statistics.

Nothing is copied, resumed or relabelled.  Calibration is published beneath
the fresh root, and a fresh durable attempt is written before the original R4
test bytes are opened once.  Reproduction reopens the original inputs and
re-scores them through the repaired executable.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing
import os
import resource
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .belief_artifacts import publish_exclusive_bytes, stable_read_bytes
from .belief_contract import canonical_json_bytes
from .belief_v2_calibration_controller import (
    POPULATION_FILES,
    RESULT_FILES,
    _expected_synthetic_rounds,
    _manifest as calibration_manifest,
    _resource_row,
    _scale_fractions,
    _score_human,
    _score_synthetic,
    reopen_v2_calibration_selection,
)
from .belief_v2_accelerator import build_training_device_profile
from .belief_v2_execution_identity import (
    BeliefV2ExecutionIdentityError,
    validate_live_execution,
)
from .belief_v2_freeze import (
    BeliefV2FreezeError,
    HUMAN_COHORT_ID,
    PRIMARY_COHORT_ID,
    V2ExecutionFreezeV1,
    V2PipelineAdmissionV1,
    _authenticate_review_marker_at_tip,
    _canonical_remote_tip,
    _git,
    execution_freeze_from_bytes,
    expected_execution_review_claim,
    pipeline_admission_from_bytes,
    reauthenticate_pipeline_admission,
    validate_execution_freeze,
    validate_pipeline_consumption_tombstone,
)
from .belief_v2_input_index_controller import reopen_training_input_index
from .belief_v2_progress import ProgressCallback
from .belief_v2_scoring_controller import reopen_trained_scoring_cohorts
from .belief_v2_statistics import (
    evaluate_human_transfer_test,
    evaluate_human_mixture_selection,
    evaluate_label_control_test,
    evaluate_primary_test,
    evaluate_scale_curve,
    v2_reference_replicates_are_stable,
    v2_round_population_bytes,
)
from .belief_v2_result import derive_terminal_result
from .belief_v2_terminal_controller import (
    STATISTIC_FILES,
    TEST_POPULATION_FILES,
    _attempt as source_terminal_attempt,
    _calibration_statistics,
    _derive_integrity_receipt,
    _expected_test_human_rounds,
    _expected_test_synthetic_rounds,
    _score_test_populations,
    _stage_manifest as source_terminal_manifest,
    reopen_v2_terminal,
)


SOURCE_SPEC_SCHEMA = "belief-v1-v2-r4-completion-source-spec-v1"
CALIBRATION_OUTER_SCHEMA = "belief-v1-v2-r4-completion-calibration-v1"
PRETEST_READINESS_SCHEMA = (
    "belief-v1-v2-r4-completion-pretest-readiness-v1")
TEST_ATTEMPT_SCHEMA = "belief-v1-v2-r4-completion-test-attempt-v1"
TERMINAL_OUTER_SCHEMA = "belief-v1-v2-r4-completion-terminal-v1"
COMPLETION_REVIEW_SCHEMA = (
    "belief-v1-v2-r4-completion-execution-review-v1")
COMPLETION_ADMISSION_SCHEMA = (
    "belief-v1-v2-r4-completion-pipeline-admission-v1")
COMPLETION_CONSUMPTION_SCHEMA = (
    "belief-v1-v2-r4-completion-consumption-tombstone-v1")
COMPLETION_REVIEW_PREFIX = (
    "BELIEF_V1_V2_R4_COMPLETION_EXECUTION_V1_REVIEW ")
R4_PROJECTION_WORKERS = 16
SOURCE_SPEC_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts" / "belief_v2_r4_completion.v1.json")
SOURCE_SPEC_REPO_PATH = "server/scripts/belief_v2_r4_completion.v1.json"
SOURCE_TOP_LEVEL = {
    "admission.json", "capture", "device-qualification", "freeze.json",
    "group-split.json", "human-capture", "human-reference",
    "inventory.json", "reference", "review.md", "training",
    "training-input-index", "training-tensor-cache",
}
SOURCE_COHORT_IDS = (
    "synthetic-primary", "hard-geometry-label-permutation",
    "human-mixture", "synthetic-scale-50",
)
COMPLETION_AUTHORITY = {
    "calibration_open_authorized": True,
    "one_test_split_open_authorized": True,
    "training_authorized": False,
    "retry_authorized": False,
    "sampler_implementation_authorized": False,
    "gameplay_strength_screen_authorized": False,
    "strength_claim_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "merge_authorized": False,
}
COMPLETION_ADMISSION_AUTHORITY = {
    "capture_authorized": False,
    "reference_generation_authorized": False,
    "training_authorized": False,
    "calibration_open_authorized": True,
    "one_test_split_open_authorized": True,
    "terminal_reconstruction_authorized": True,
    "retry_authorized": False,
    "sampler_implementation_authorized": False,
    "gameplay_strength_screen_authorized": False,
    "strength_claim_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
}


class BeliefV2R4CompletionError(ValueError):
    """An R4 source, recovery admission or completion artifact drifted."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _process_tree_cpu_time_ns() -> int:
    usages = (resource.getrusage(resource.RUSAGE_SELF),
              resource.getrusage(resource.RUSAGE_CHILDREN))
    return int(sum(row.ru_utime + row.ru_stime for row in usages)
               * 1_000_000_000)


def _projection_worker_probe(_: int) -> int:
    return os.getpid()


def _projection_pool() -> ProcessPoolExecutor:
    if "forkserver" not in multiprocessing.get_all_start_methods():
        raise BeliefV2R4CompletionError(
            "R4 projection worker start method is unavailable")
    return ProcessPoolExecutor(
        max_workers=R4_PROJECTION_WORKERS,
        mp_context=multiprocessing.get_context("forkserver"))


def _warm_projection_pool(executor: ProcessPoolExecutor) -> None:
    try:
        pids = tuple(executor.map(
            _projection_worker_probe, range(R4_PROJECTION_WORKERS),
            chunksize=1))
    except (OSError, RuntimeError) as exc:
        raise BeliefV2R4CompletionError(
            "R4 projection worker startup refused") from exc
    if len(pids) != R4_PROJECTION_WORKERS \
            or any(type(pid) is not int or pid <= 0 for pid in pids):
        raise BeliefV2R4CompletionError(
            "R4 projection worker startup population drift")


def _is_sha256(value: Any) -> bool:
    return type(value) is str and len(value) == 64 and all(
        char in "0123456789abcdef" for char in value)


def _is_git_sha(value: Any) -> bool:
    return type(value) is str and len(value) == 40 and all(
        char in "0123456789abcdef" for char in value)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BeliefV2R4CompletionError(
                "R4 completion source spec contains a duplicate key")
        result[key] = value
    return result


@dataclass(frozen=True)
class R4CompletionSourceSpecV1:
    destination_evidence_root: Path
    source_evidence_root: Path
    source_execution_git: str
    source_freeze_sha256: str
    source_admission_sha256: str
    source_review_marker_sha256: str
    source_consumption_tombstone_sha256: str
    source_inventory_sha256: str
    source_group_split_sha256: str
    source_input_index_manifest_sha256: str
    source_tensor_cache_manifest_sha256: str
    source_device_qualification_manifest_sha256: str
    source_training_manifest_sha256s: tuple[tuple[str, str], ...]
    schema: str = SOURCE_SPEC_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "destination_evidence_root": str(
                self.destination_evidence_root),
            "source_evidence_root": str(self.source_evidence_root),
            "source_execution_git": self.source_execution_git,
            "source_freeze_sha256": self.source_freeze_sha256,
            "source_admission_sha256": self.source_admission_sha256,
            "source_review_marker_sha256": (
                self.source_review_marker_sha256),
            "source_consumption_tombstone_sha256": (
                self.source_consumption_tombstone_sha256),
            "source_inventory_sha256": self.source_inventory_sha256,
            "source_group_split_sha256": self.source_group_split_sha256,
            "source_input_index_manifest_sha256": (
                self.source_input_index_manifest_sha256),
            "source_tensor_cache_manifest_sha256": (
                self.source_tensor_cache_manifest_sha256),
            "source_device_qualification_manifest_sha256": (
                self.source_device_qualification_manifest_sha256),
            "source_training_manifest_sha256s": dict(
                self.source_training_manifest_sha256s),
            "authority": dict(COMPLETION_AUTHORITY),
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return _sha256(self.canonical_bytes())


@dataclass(frozen=True)
class R4CompletionSourceV1:
    spec: R4CompletionSourceSpecV1
    freeze: V2ExecutionFreezeV1
    admission: V2PipelineAdmissionV1
    review_marker: bytes
    inventory: dict[str, Any]
    group_split: dict[str, Any]


@dataclass(frozen=True)
class R4CompletionAdmissionV1:
    """Durable authority for calibration/test completion, never training."""

    freeze_sha256: str
    execution_git: str
    source_manifest_sha256: str
    seed_registry_sha256: str
    source_spec_sha256: str
    review_commit: str
    canonical_remote_tip: str
    review_marker_sha256: str
    evidence_root: str
    schema: str = COMPLETION_ADMISSION_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "freeze_sha256": self.freeze_sha256,
            "execution_git": self.execution_git,
            "source_manifest_sha256": self.source_manifest_sha256,
            "seed_registry_sha256": self.seed_registry_sha256,
            "source_spec_sha256": self.source_spec_sha256,
            "review_commit": self.review_commit,
            "canonical_remote_tip": self.canonical_remote_tip,
            "review_marker_sha256": self.review_marker_sha256,
            "evidence_root": self.evidence_root,
            "authority": dict(COMPLETION_ADMISSION_AUTHORITY),
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return _sha256(self.canonical_bytes())


def load_r4_completion_source_spec(
        raw: bytes | None = None) -> R4CompletionSourceSpecV1:
    """Strictly reopen the tracked, exact R4 source commitment."""
    if raw is None:
        raw = SOURCE_SPEC_PATH.read_bytes()
    if type(raw) is not bytes or not raw:
        raise BeliefV2R4CompletionError(
            "R4 completion source spec bytes are empty")
    try:
        payload = json.loads(
            raw.decode("ascii"), object_pairs_hook=_strict_object,
            parse_float=lambda value: (_ for _ in ()).throw(
                BeliefV2R4CompletionError(
                    f"R4 completion spec invalid number {value}")),
            parse_constant=lambda value: (_ for _ in ()).throw(
                BeliefV2R4CompletionError(
                    f"R4 completion spec invalid number {value}")))
    except BeliefV2R4CompletionError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2R4CompletionError(
            "R4 completion source spec is not strict JSON") from exc
    expected = {
        "schema", "destination_evidence_root", "source_evidence_root",
        "source_execution_git", "source_freeze_sha256",
        "source_admission_sha256", "source_review_marker_sha256",
        "source_consumption_tombstone_sha256", "source_inventory_sha256",
        "source_group_split_sha256", "source_input_index_manifest_sha256",
        "source_tensor_cache_manifest_sha256",
        "source_device_qualification_manifest_sha256",
        "source_training_manifest_sha256s", "authority",
    }
    hashes = (
        "source_freeze_sha256", "source_admission_sha256",
        "source_review_marker_sha256",
        "source_consumption_tombstone_sha256",
        "source_inventory_sha256", "source_group_split_sha256",
        "source_input_index_manifest_sha256",
        "source_tensor_cache_manifest_sha256",
        "source_device_qualification_manifest_sha256",
    )
    training = payload.get("source_training_manifest_sha256s") \
        if type(payload) is dict else None
    if type(payload) is not dict or set(payload) != expected \
            or canonical_json_bytes(payload) != raw \
            or payload["schema"] != SOURCE_SPEC_SCHEMA \
            or payload["authority"] != COMPLETION_AUTHORITY \
            or type(training) is not dict \
            or set(training) != set(SOURCE_COHORT_IDS) \
            or any(not _is_sha256(payload[key]) for key in hashes) \
            or any(not _is_sha256(value) for value in training.values()) \
            or type(payload["source_execution_git"]) is not str \
            or len(payload["source_execution_git"]) != 40 \
            or any(char not in "0123456789abcdef"
                   for char in payload["source_execution_git"]):
        raise BeliefV2R4CompletionError(
            "R4 completion source spec field/authority drift")
    destination = Path(payload["destination_evidence_root"])
    source = Path(payload["source_evidence_root"])
    if not destination.is_absolute() or not source.is_absolute() \
            or destination == source:
        raise BeliefV2R4CompletionError(
            "R4 completion source/destination path drift")
    result = R4CompletionSourceSpecV1(
        destination_evidence_root=destination,
        source_evidence_root=source,
        source_execution_git=payload["source_execution_git"],
        source_freeze_sha256=payload["source_freeze_sha256"],
        source_admission_sha256=payload["source_admission_sha256"],
        source_review_marker_sha256=(
            payload["source_review_marker_sha256"]),
        source_consumption_tombstone_sha256=(
            payload["source_consumption_tombstone_sha256"]),
        source_inventory_sha256=payload["source_inventory_sha256"],
        source_group_split_sha256=payload["source_group_split_sha256"],
        source_input_index_manifest_sha256=(
            payload["source_input_index_manifest_sha256"]),
        source_tensor_cache_manifest_sha256=(
            payload["source_tensor_cache_manifest_sha256"]),
        source_device_qualification_manifest_sha256=(
            payload["source_device_qualification_manifest_sha256"]),
        source_training_manifest_sha256s=tuple(
            (cohort_id, training[cohort_id])
            for cohort_id in SOURCE_COHORT_IDS),
    )
    if result.canonical_bytes() != raw:
        raise BeliefV2R4CompletionError(
            "R4 completion source spec reconstruction drift")
    return result


def expected_r4_completion_review_claim(
        freeze: V2ExecutionFreezeV1,
        spec: R4CompletionSourceSpecV1 | None = None) -> dict[str, Any]:
    """Return the exact marker claim for completion-only execution."""
    validate_execution_freeze(freeze)
    if spec is None:
        spec = load_r4_completion_source_spec()
    if type(spec) is not R4CompletionSourceSpecV1 \
            or Path(freeze.evidence_root) != spec.destination_evidence_root:
        raise BeliefV2R4CompletionError(
            "R4 completion review destination drift")
    claim = expected_execution_review_claim(freeze)
    claim["schema"] = COMPLETION_REVIEW_SCHEMA
    claim.pop(
        "bounded_capture_reference_training_and_one_test_open_authorized")
    claim["source_spec_sha256"] = spec.sha256()
    claim["execution_mode"] = "r4-calibration-test-terminal-only"
    claim["authority"] = dict(COMPLETION_ADMISSION_AUTHORITY)
    return claim


def expected_r4_completion_review_marker(
        freeze: V2ExecutionFreezeV1,
        spec: R4CompletionSourceSpecV1 | None = None) -> bytes:
    return COMPLETION_REVIEW_PREFIX.encode("ascii") + canonical_json_bytes(
        expected_r4_completion_review_claim(freeze, spec))


def validate_r4_completion_admission(
        freeze: V2ExecutionFreezeV1,
        admission: R4CompletionAdmissionV1, *, review_marker: bytes,
        spec: R4CompletionSourceSpecV1 | None = None) -> None:
    validate_execution_freeze(freeze)
    if spec is None:
        spec = load_r4_completion_source_spec()
    expected_marker = expected_r4_completion_review_marker(freeze, spec)
    if type(admission) is not R4CompletionAdmissionV1 \
            or admission.schema != COMPLETION_ADMISSION_SCHEMA \
            or admission.freeze_sha256 != freeze.sha256() \
            or admission.execution_git != freeze.execution_git \
            or admission.source_manifest_sha256 \
            != freeze.source_manifest_sha256 \
            or admission.seed_registry_sha256 \
            != freeze.seed_registry_sha256 \
            or admission.source_spec_sha256 != spec.sha256() \
            or not _is_git_sha(admission.review_commit) \
            or not _is_git_sha(admission.canonical_remote_tip) \
            or type(review_marker) is not bytes \
            or review_marker != expected_marker \
            or admission.review_marker_sha256 != _sha256(review_marker) \
            or admission.evidence_root != freeze.evidence_root \
            or Path(admission.evidence_root) \
            != spec.destination_evidence_root:
        raise BeliefV2R4CompletionError(
            "R4 completion admission identity/authority drift")


def authenticate_r4_completion_review(
        freeze: V2ExecutionFreezeV1, *, repo: Path, review_commit: str,
        spec: R4CompletionSourceSpecV1 | None = None) \
        -> tuple[bytes, str]:
    """Authenticate the narrow marker against the real canonical main tip."""
    if spec is None:
        spec = load_r4_completion_source_spec()
    if not isinstance(repo, Path) or not repo.is_absolute() \
            or not _is_git_sha(review_commit):
        raise BeliefV2R4CompletionError(
            "R4 completion review input drift")
    marker = expected_r4_completion_review_marker(freeze, spec)
    try:
        remote_tip = _canonical_remote_tip(repo)
        if _git(repo, "rev-parse", "origin/main") != remote_tip:
            raise BeliefV2R4CompletionError(
                "R4 completion local canonical ref differs from real remote")
        _authenticate_review_marker_at_tip(
            freeze, repo=repo, review_commit=review_commit,
            canonical_tip=remote_tip, marker=marker,
            marker_prefix=COMPLETION_REVIEW_PREFIX)
    except BeliefV2FreezeError as exc:
        raise BeliefV2R4CompletionError(
            "R4 completion external review authentication refused") from exc
    return marker, remote_tip


def build_r4_completion_admission(
        freeze: V2ExecutionFreezeV1, *, repo: Path, review_commit: str,
        spec: R4CompletionSourceSpecV1 | None = None) \
        -> tuple[R4CompletionAdmissionV1, bytes]:
    if spec is None:
        spec = load_r4_completion_source_spec()
    marker, remote_tip = authenticate_r4_completion_review(
        freeze, repo=repo, review_commit=review_commit, spec=spec)
    admission = R4CompletionAdmissionV1(
        freeze_sha256=freeze.sha256(),
        execution_git=freeze.execution_git,
        source_manifest_sha256=freeze.source_manifest_sha256,
        seed_registry_sha256=freeze.seed_registry_sha256,
        source_spec_sha256=spec.sha256(), review_commit=review_commit,
        canonical_remote_tip=remote_tip,
        review_marker_sha256=_sha256(marker),
        evidence_root=freeze.evidence_root)
    validate_r4_completion_admission(
        freeze, admission, review_marker=marker, spec=spec)
    return admission, marker


def r4_completion_admission_from_bytes(
        raw: bytes, *, freeze: V2ExecutionFreezeV1,
        review_marker: bytes,
        spec: R4CompletionSourceSpecV1 | None = None) \
        -> R4CompletionAdmissionV1:
    if type(raw) is not bytes or not raw:
        raise BeliefV2R4CompletionError(
            "R4 completion admission bytes are empty")
    try:
        payload = json.loads(
            raw.decode("ascii"), object_pairs_hook=_strict_object,
            parse_float=lambda value: (_ for _ in ()).throw(
                BeliefV2R4CompletionError(
                    f"R4 completion admission invalid number {value}")),
            parse_constant=lambda value: (_ for _ in ()).throw(
                BeliefV2R4CompletionError(
                    f"R4 completion admission invalid number {value}")))
    except BeliefV2R4CompletionError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2R4CompletionError(
            "R4 completion admission is not strict JSON") from exc
    expected = {
        "schema", "freeze_sha256", "execution_git",
        "source_manifest_sha256", "seed_registry_sha256",
        "source_spec_sha256", "review_commit", "canonical_remote_tip",
        "review_marker_sha256", "evidence_root", "authority",
    }
    if type(payload) is not dict or set(payload) != expected \
            or payload.get("authority") != COMPLETION_ADMISSION_AUTHORITY:
        raise BeliefV2R4CompletionError(
            "R4 completion admission field/authority drift")
    try:
        admission = R4CompletionAdmissionV1(
            schema=payload["schema"],
            freeze_sha256=payload["freeze_sha256"],
            execution_git=payload["execution_git"],
            source_manifest_sha256=payload["source_manifest_sha256"],
            seed_registry_sha256=payload["seed_registry_sha256"],
            source_spec_sha256=payload["source_spec_sha256"],
            review_commit=payload["review_commit"],
            canonical_remote_tip=payload["canonical_remote_tip"],
            review_marker_sha256=payload["review_marker_sha256"],
            evidence_root=payload["evidence_root"])
    except (KeyError, TypeError) as exc:
        raise BeliefV2R4CompletionError(
            "R4 completion admission field drift") from exc
    validate_r4_completion_admission(
        freeze, admission, review_marker=review_marker, spec=spec)
    if admission.canonical_bytes() != raw:
        raise BeliefV2R4CompletionError(
            "R4 completion admission reconstruction drift")
    return admission


def reauthenticate_r4_completion_admission(
        freeze: V2ExecutionFreezeV1,
        admission: R4CompletionAdmissionV1, *, repo: Path,
        review_marker: bytes,
        spec: R4CompletionSourceSpecV1 | None = None) -> None:
    if spec is None:
        spec = load_r4_completion_source_spec()
    validate_r4_completion_admission(
        freeze, admission, review_marker=review_marker, spec=spec)
    try:
        _authenticate_review_marker_at_tip(
            freeze, repo=repo, review_commit=admission.review_commit,
            canonical_tip=admission.canonical_remote_tip,
            marker=review_marker, marker_prefix=COMPLETION_REVIEW_PREFIX)
    except BeliefV2FreezeError as exc:
        raise BeliefV2R4CompletionError(
            "R4 completion admission remote authentication refused") \
            from exc


def r4_completion_consumption_tombstone_bytes(
        admission: R4CompletionAdmissionV1) -> bytes:
    if type(admission) is not R4CompletionAdmissionV1:
        raise BeliefV2R4CompletionError(
            "R4 completion tombstone admission drift")
    return canonical_json_bytes({
        "schema": COMPLETION_CONSUMPTION_SCHEMA,
        "admission_sha256": admission.sha256(),
        "freeze_sha256": admission.freeze_sha256,
        "source_spec_sha256": admission.source_spec_sha256,
        "review_commit": admission.review_commit,
        "canonical_remote_tip": admission.canonical_remote_tip,
        "evidence_root": admission.evidence_root,
        "initialization_consumed": True,
        "retry_authorized": False,
    })


def validate_r4_completion_consumption_tombstone(
        raw: bytes, *, admission: R4CompletionAdmissionV1) -> None:
    if type(raw) is not bytes \
            or raw != r4_completion_consumption_tombstone_bytes(admission):
        raise BeliefV2R4CompletionError(
            "R4 completion consumption tombstone drift")


def reopen_r4_completion_source(
        spec: R4CompletionSourceSpecV1, *, repo: Path) \
        -> R4CompletionSourceV1:
    """Authenticate the original spent R4 tree without mutating it."""
    if type(spec) is not R4CompletionSourceSpecV1 \
            or not isinstance(repo, Path) or not repo.is_absolute():
        raise BeliefV2R4CompletionError(
            "R4 completion source reopen input drift")
    root = spec.source_evidence_root
    if root.is_symlink() or not root.is_dir() \
            or {path.name for path in root.iterdir()} != SOURCE_TOP_LEVEL \
            or any((root / name).exists() or (root / name).is_symlink()
                   for name in ("calibration", "terminal.partial", "terminal")):
        raise BeliefV2R4CompletionError(
            "R4 source population or unopened-result boundary drift")
    try:
        freeze_raw = stable_read_bytes(root / "freeze.json")
        admission_raw = stable_read_bytes(root / "admission.json")
        marker = stable_read_bytes(root / "review.md")
        inventory_raw = stable_read_bytes(root / "inventory.json")
        split_raw = stable_read_bytes(root / "group-split.json")
        tombstone_raw = stable_read_bytes(
            root.with_name(root.name + ".consumed.json"))
    except ValueError as exc:
        raise BeliefV2R4CompletionError(
            "R4 source control artifact reopen refused") from exc
    expected_hashes = (
        (freeze_raw, spec.source_freeze_sha256),
        (admission_raw, spec.source_admission_sha256),
        (marker, spec.source_review_marker_sha256),
        (inventory_raw, spec.source_inventory_sha256),
        (split_raw, spec.source_group_split_sha256),
        (tombstone_raw, spec.source_consumption_tombstone_sha256),
    )
    if any(_sha256(raw) != expected for raw, expected in expected_hashes):
        raise BeliefV2R4CompletionError(
            "R4 source control artifact byte binding drift")
    try:
        source_freeze = execution_freeze_from_bytes(freeze_raw)
        source_admission = pipeline_admission_from_bytes(
            admission_raw, freeze=source_freeze, review_marker=marker)
        validate_pipeline_consumption_tombstone(
            tombstone_raw, admission=source_admission)
        reauthenticate_pipeline_admission(
            source_freeze, source_admission, repo=repo,
            review_marker=marker)
        inventory = json.loads(inventory_raw)
        group_split = json.loads(split_raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise BeliefV2R4CompletionError(
            "R4 source identity/authentication refused") from exc
    if source_freeze.execution_git != spec.source_execution_git \
            or source_freeze.evidence_root != str(root) \
            or source_freeze.sha256() != spec.source_freeze_sha256 \
            or source_admission.sha256() != spec.source_admission_sha256:
        raise BeliefV2R4CompletionError(
            "R4 source freeze/admission identity drift")
    manifest_paths = (
        (root / "training-input-index" / "result" / "manifest.json",
         spec.source_input_index_manifest_sha256),
        (root / "training-tensor-cache" / "result" / "manifest.json",
         spec.source_tensor_cache_manifest_sha256),
        (root / "device-qualification" / "result" / "manifest.json",
         spec.source_device_qualification_manifest_sha256),
        *((root / "training" / cohort_id / "manifest.json", expected)
          for cohort_id, expected
          in spec.source_training_manifest_sha256s),
    )
    try:
        if any(_sha256(stable_read_bytes(path)) != expected
               for path, expected in manifest_paths):
            raise BeliefV2R4CompletionError(
                "R4 source stage manifest byte binding drift")
    except ValueError as exc:
        raise BeliefV2R4CompletionError(
            "R4 source stage manifest reopen refused") from exc
    return R4CompletionSourceV1(
        spec, source_freeze, source_admission, marker,
        inventory, group_split)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _completion_stage_gate(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: R4CompletionAdmissionV1, *, repo: Path,
        review_marker: bytes, spec: R4CompletionSourceSpecV1) -> None:
    try:
        validate_execution_freeze(freeze)
        reauthenticate_r4_completion_admission(
            freeze, admission, repo=repo, review_marker=review_marker,
            spec=spec)
        validate_live_execution(
            repo=repo, execution_git=freeze.execution_git,
            source_bindings=freeze.source_bindings, runtime=freeze.runtime)
        if build_training_device_profile(
                freeze.training_candidate_device) \
                != freeze.training_device_profile:
            raise BeliefV2ExecutionIdentityError(
                "R4 completion live device identity drift")
    except (ValueError, BeliefV2ExecutionIdentityError) as exc:
        raise BeliefV2R4CompletionError(
            "R4 completion fresh stage admission refused") from exc
    if not isinstance(root, Path) or not root.is_absolute() \
            or root.is_symlink() or not root.is_dir() \
            or root != spec.destination_evidence_root \
            or root != Path(freeze.evidence_root):
        raise BeliefV2R4CompletionError(
            "R4 completion destination binding drift")


def _calibration_outer_manifest(
        *, completion_freeze: V2ExecutionFreezeV1,
        completion_admission: R4CompletionAdmissionV1,
        source: R4CompletionSourceV1,
        source_calibration_manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": CALIBRATION_OUTER_SCHEMA,
        "completion_freeze_sha256": completion_freeze.sha256(),
        "completion_admission_sha256": completion_admission.sha256(),
        "completion_execution_git": completion_freeze.execution_git,
        "source_spec_sha256": source.spec.sha256(),
        "source_evidence_root": str(source.spec.source_evidence_root),
        "source_freeze_sha256": source.freeze.sha256(),
        "source_admission_sha256": source.admission.sha256(),
        "source_calibration_manifest_sha256": _sha256(
            canonical_json_bytes(source_calibration_manifest)),
        "calibration_completed_before_test_open": True,
        "source_test_split_opened": False,
        "authority": dict(COMPLETION_AUTHORITY),
    }


def run_r4_completion_calibration(
        root: Path, completion_freeze: V2ExecutionFreezeV1,
        completion_admission: R4CompletionAdmissionV1, *, repo: Path,
        review_marker: bytes,
        progress: ProgressCallback | None = None) -> dict[str, Any]:
    """Re-score the sealed R4 calibration split and publish it freshly."""
    spec = load_r4_completion_source_spec()
    _completion_stage_gate(
        root, completion_freeze, completion_admission, repo=repo,
        review_marker=review_marker, spec=spec)
    source = reopen_r4_completion_source(spec, repo=repo)
    parent = root / "calibration"
    final = parent / "selection"
    partial = parent / "selection.partial"
    outer_path = parent / "completion.json"
    if parent.is_symlink() or final.exists() or partial.exists() \
            or outer_path.exists() or final.is_symlink() \
            or partial.is_symlink() or outer_path.is_symlink():
        raise BeliefV2R4CompletionError(
            "R4 completion calibration slot is occupied")
    try:
        _, training_inputs = reopen_training_input_index(
            source.spec.source_evidence_root / "training-input-index"
            / "result", freeze=source.freeze,
            admission=source.admission)
        cohorts, plan, qualification, training_hashes = (
            reopen_trained_scoring_cohorts(
                source.spec.source_evidence_root,
                freeze=source.freeze, admission=source.admission,
                training_inputs=training_inputs,
                legacy_tensor_cache_manifest_sha256=(
                    source.spec.source_tensor_cache_manifest_sha256)))
    except ValueError as exc:
        raise BeliefV2R4CompletionError(
            "R4 completion training population refused") from exc
    cohort_ids = tuple(row.cohort_id for row in cohorts)
    started = time.monotonic_ns()
    cpu_started = _process_tree_cpu_time_ns()
    if progress is not None:
        progress(0, 6, "score-r4-calibration-populations")
    with _projection_pool() as projection_executor:
        _warm_projection_pool(projection_executor)
        try:
            synthetic_0 = _score_synthetic(
                source.spec.source_evidence_root, source.freeze,
                source.admission, cohorts,
                replicate="calibration-replicate-0",
                projection_executor=projection_executor,
                progress=progress,
                progress_phase="score-r4-synthetic-ref0-rounds")
            if progress is not None:
                progress(1, 6, "score-r4-calibration-populations")
            synthetic_1 = _score_synthetic(
                source.spec.source_evidence_root, source.freeze,
                source.admission, cohorts,
                replicate="calibration-replicate-1",
                projection_executor=projection_executor,
                progress=progress,
                progress_phase="score-r4-synthetic-ref1-rounds")
            if progress is not None:
                progress(2, 6, "score-r4-calibration-populations")
            human_0 = _score_human(
                source.spec.source_evidence_root, source.freeze,
                source.admission, source.group_split, cohorts,
                replicate="calibration-replicate-0",
                projection_executor=projection_executor,
                progress=progress,
                progress_phase="score-r4-human-ref0-groups")
            if progress is not None:
                progress(3, 6, "score-r4-calibration-populations")
            human_1 = _score_human(
                source.spec.source_evidence_root, source.freeze,
                source.admission, source.group_split, cohorts,
                replicate="calibration-replicate-1",
                projection_executor=projection_executor,
                progress=progress,
                progress_phase="score-r4-human-ref1-groups")
            if progress is not None:
                progress(4, 6, "score-r4-calibration-populations")
        except ValueError as exc:
            raise BeliefV2R4CompletionError(
                "R4 completion calibration scoring refused") from exc
    try:
        expected_synthetic = _expected_synthetic_rounds()
        expected_human = tuple((row.round_key, row.trump_rank)
                               for row in human_0)
        synthetic_stable = v2_reference_replicates_are_stable(
            synthetic_0, synthetic_1, cohort_ids=cohort_ids,
            expected_rounds=expected_synthetic, source_kind="synthetic")
        human_stable = v2_reference_replicates_are_stable(
            human_0, human_1, cohort_ids=cohort_ids,
            expected_rounds=expected_human, source_kind="human")
        human_selection = evaluate_human_mixture_selection(
            synthetic_0, human_0,
            expected_synthetic_rounds=expected_synthetic,
            expected_human_rounds=expected_human,
            cohort_ids=cohort_ids)
        scale_curve = evaluate_scale_curve(
            synthetic_0,
            expected_synthetic_rounds=expected_synthetic,
            cohort_ids=cohort_ids,
            scale_fractions=_scale_fractions(source.freeze))
    except ValueError as exc:
        raise BeliefV2R4CompletionError(
            "R4 completion calibration statistic refused") from exc
    if progress is not None:
        progress(5, 6, "derive-r4-calibration-statistics")
    stable = synthetic_stable and human_stable
    selected = None if not stable else (
        HUMAN_COHORT_ID if human_selection.retained else PRIMARY_COHORT_ID)
    population_rows = {
        "synthetic_ref0": synthetic_0,
        "synthetic_ref1": synthetic_1,
        "human_ref0": human_0,
        "human_ref1": human_1,
    }
    files = {
        key: v2_round_population_bytes(
            rows, cohort_ids=cohort_ids, label=key)
        for key, rows in population_rows.items()
    }
    files.update({
        "human_selection": human_selection.canonical_bytes(),
        "scale_curve": scale_curve.canonical_bytes(),
    })
    finished = time.monotonic_ns()
    resources = _resource_row(
        started=started, finished=finished,
        cpu_nanoseconds=_process_tree_cpu_time_ns() - cpu_started,
        artifact_bytes=sum(len(raw) for raw in files.values()))
    if resources["wall_nanoseconds"] \
            > completion_freeze.resource_caps.training_wall_seconds \
            * 1_000_000_000:
        raise BeliefV2R4CompletionError(
            "R4 completion calibration wall cap exceeded")
    inner = calibration_manifest(
        source.freeze, source.admission,
        training_input_sha256=training_inputs.sha256(),
        qualification_plan_sha256=plan.sha256(),
        qualification_result_sha256=_sha256(
            qualification.canonical_bytes(plan)),
        training_manifest_sha256s=training_hashes,
        files=files, synthetic_stable=synthetic_stable,
        human_stable=human_stable,
        human_retained=human_selection.retained,
        selected_cohort_id=selected, resources=resources)
    parent.mkdir(mode=0o700, exist_ok=False)
    partial.mkdir(mode=0o700)
    for key, raw in files.items():
        publish_exclusive_bytes(
            partial / POPULATION_FILES.get(key, RESULT_FILES.get(key)), raw)
    publish_exclusive_bytes(
        partial / "manifest.json", canonical_json_bytes(inner))
    os.rename(partial, final)
    _fsync_directory(parent)
    reopened = reopen_v2_calibration_selection(
        final, freeze=source.freeze, admission=source.admission,
        inventory=source.inventory, group_split=source.group_split)
    if reopened != inner:
        raise BeliefV2R4CompletionError(
            "R4 completion calibration post-publish drift")
    outer = _calibration_outer_manifest(
        completion_freeze=completion_freeze,
        completion_admission=completion_admission,
        source=source, source_calibration_manifest=inner)
    publish_exclusive_bytes(
        outer_path, canonical_json_bytes(outer))
    _fsync_directory(parent)
    if progress is not None:
        progress(6, 6, "r4-calibration-complete")
    return outer


def reopen_r4_completion_calibration(
        root: Path, completion_freeze: V2ExecutionFreezeV1,
        completion_admission: R4CompletionAdmissionV1, *, repo: Path,
        review_marker: bytes) \
        -> tuple[dict[str, Any], R4CompletionSourceV1]:
    """Reopen the fresh outer binding and rederive original R4 selection."""
    spec = load_r4_completion_source_spec()
    _completion_stage_gate(
        root, completion_freeze, completion_admission, repo=repo,
        review_marker=review_marker, spec=spec)
    source = reopen_r4_completion_source(spec, repo=repo)
    try:
        raw = stable_read_bytes(root / "calibration" / "completion.json")
        outer = json.loads(raw)
        inner = reopen_v2_calibration_selection(
            root / "calibration" / "selection",
            freeze=source.freeze, admission=source.admission,
            inventory=source.inventory, group_split=source.group_split)
    except (ValueError, json.JSONDecodeError) as exc:
        raise BeliefV2R4CompletionError(
            "R4 completion calibration reopen refused") from exc
    expected = _calibration_outer_manifest(
        completion_freeze=completion_freeze,
        completion_admission=completion_admission,
        source=source, source_calibration_manifest=inner)
    if canonical_json_bytes(outer) != raw or outer != expected:
        raise BeliefV2R4CompletionError(
            "R4 completion calibration outer binding drift")
    return inner, source


def r4_completion_pretest_readiness(
        root: Path, completion_freeze: V2ExecutionFreezeV1,
        completion_admission: R4CompletionAdmissionV1, *, repo: Path,
        review_marker: bytes) -> dict[str, Any]:
    """Reopen calibration and prove the one-shot test slot is untouched."""
    forbidden = (
        root / "calibration" / "selection.partial",
        root / "r4-completion-test-attempt.json",
        root / "terminal.partial",
        root / "terminal",
        root / "r4-completion-terminal.json",
    )
    if any(path.exists() or path.is_symlink() for path in forbidden):
        raise BeliefV2R4CompletionError(
            "R4 completion pretest namespace is already consumed")
    calibration, source = reopen_r4_completion_calibration(
        root, completion_freeze, completion_admission, repo=repo,
        review_marker=review_marker)
    return {
        "schema": PRETEST_READINESS_SCHEMA,
        "completion_freeze_sha256": completion_freeze.sha256(),
        "completion_admission_sha256": completion_admission.sha256(),
        "completion_execution_git": completion_freeze.execution_git,
        "source_spec_sha256": source.spec.sha256(),
        "source_freeze_sha256": source.freeze.sha256(),
        "source_admission_sha256": source.admission.sha256(),
        "source_calibration_manifest_sha256": _sha256(
            canonical_json_bytes(calibration)),
        "synthetic_test_expected_round_count": len(
            _expected_test_synthetic_rounds()),
        "calibration_independently_reopened": True,
        "test_population_metadata_opened": False,
        "test_attempt_file_absent": True,
        "terminal_population_absent": True,
        "source_test_split_decision_open_count": 0,
        "test_opening_executed": False,
        "execution_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def _completion_test_attempt(
        *, completion_freeze: V2ExecutionFreezeV1,
        completion_admission: R4CompletionAdmissionV1,
        source: R4CompletionSourceV1,
        source_calibration_manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": TEST_ATTEMPT_SCHEMA,
        "completion_freeze_sha256": completion_freeze.sha256(),
        "completion_admission_sha256": completion_admission.sha256(),
        "completion_execution_git": completion_freeze.execution_git,
        "source_spec_sha256": source.spec.sha256(),
        "source_evidence_root": str(source.spec.source_evidence_root),
        "source_freeze_sha256": source.freeze.sha256(),
        "source_admission_sha256": source.admission.sha256(),
        "source_calibration_manifest_sha256": _sha256(
            canonical_json_bytes(source_calibration_manifest)),
        "source_test_split_decision_open_count": 1,
        "retry_count": 0,
        "published_and_fsynced_before_source_test_target_read": True,
        "authority": dict(COMPLETION_AUTHORITY),
    }


def _terminal_outer_manifest(
        *, completion_freeze: V2ExecutionFreezeV1,
        completion_admission: R4CompletionAdmissionV1,
        source: R4CompletionSourceV1,
        source_calibration_manifest: dict[str, Any],
        completion_attempt: dict[str, Any],
        source_terminal_manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": TERMINAL_OUTER_SCHEMA,
        "completion_freeze_sha256": completion_freeze.sha256(),
        "completion_admission_sha256": completion_admission.sha256(),
        "completion_execution_git": completion_freeze.execution_git,
        "source_spec_sha256": source.spec.sha256(),
        "source_evidence_root": str(source.spec.source_evidence_root),
        "source_freeze_sha256": source.freeze.sha256(),
        "source_admission_sha256": source.admission.sha256(),
        "source_calibration_manifest_sha256": _sha256(
            canonical_json_bytes(source_calibration_manifest)),
        "completion_attempt_sha256": _sha256(
            canonical_json_bytes(completion_attempt)),
        "source_terminal_manifest_sha256": _sha256(
            canonical_json_bytes(source_terminal_manifest)),
        "terminal_route": source_terminal_manifest["terminal_route"],
        "source_test_split_decision_open_count": 1,
        "retry_count": 0,
        "source_result_reconstruction_authorized": True,
        "authority": dict(COMPLETION_AUTHORITY),
    }


def run_r4_completion_terminal(
        root: Path, completion_freeze: V2ExecutionFreezeV1,
        completion_admission: R4CompletionAdmissionV1, *, repo: Path,
        review_marker: bytes,
        progress: ProgressCallback | None = None) -> dict[str, Any]:
    """Open the original R4 test split once under a fresh durable attempt."""
    spec = load_r4_completion_source_spec()
    _completion_stage_gate(
        root, completion_freeze, completion_admission, repo=repo,
        review_marker=review_marker, spec=spec)
    calibration, source = reopen_r4_completion_calibration(
        root, completion_freeze, completion_admission, repo=repo,
        review_marker=review_marker)
    try:
        calibration_reopened, human_selection, scale_curve = (
            _calibration_statistics(
                source.spec.source_evidence_root, source.freeze,
                source.admission, source.inventory, source.group_split,
                calibration_directory=(
                    root / "calibration" / "selection")))
    except ValueError as exc:
        raise BeliefV2R4CompletionError(
            "R4 completion calibration is not eligible for test opening") \
            from exc
    if calibration_reopened != calibration:
        raise BeliefV2R4CompletionError(
            "R4 completion calibration changed before test opening")
    if progress is not None:
        progress(0, 6, "prepare-r4-test-opening")
    completion_attempt = _completion_test_attempt(
        completion_freeze=completion_freeze,
        completion_admission=completion_admission, source=source,
        source_calibration_manifest=calibration)
    completion_attempt_path = root / "r4-completion-test-attempt.json"
    partial = root / "terminal.partial"
    final = root / "terminal"
    outer_path = root / "r4-completion-terminal.json"
    if completion_attempt_path.exists() \
            or completion_attempt_path.is_symlink() \
            or final.exists() or final.is_symlink() \
            or partial.exists() or partial.is_symlink() \
            or outer_path.exists() or outer_path.is_symlink():
        raise BeliefV2R4CompletionError(
            "R4 completion terminal namespace is already occupied")
    publish_exclusive_bytes(
        completion_attempt_path, canonical_json_bytes(completion_attempt))
    _fsync_directory(root)
    if progress is not None:
        progress(1, 6, "r4-test-opening-recorded")

    # The inner attempt and result intentionally retain the original R4
    # freeze/admission identity.  The fresh outer attempt above binds the
    # repaired executable and prevents any second opening under this recovery.
    inner_attempt = source_terminal_attempt(
        source.freeze, source.admission, calibration)
    partial.mkdir(mode=0o700)
    publish_exclusive_bytes(
        partial / "attempt.json", canonical_json_bytes(inner_attempt))
    _fsync_directory(root)
    try:
        input_index_manifest, training_inputs = reopen_training_input_index(
            source.spec.source_evidence_root / "training-input-index" /
            "result", freeze=source.freeze, admission=source.admission)
        cohorts, plan, qualification, training_hashes = (
            reopen_trained_scoring_cohorts(
                source.spec.source_evidence_root, freeze=source.freeze,
                admission=source.admission, training_inputs=training_inputs,
                legacy_tensor_cache_manifest_sha256=(
                    source.spec.source_tensor_cache_manifest_sha256)))
        if progress is not None:
            progress(2, 6, "r4-test-inputs-reopened")
        with _projection_pool() as projection_executor:
            _warm_projection_pool(projection_executor)
            synthetic, human = _score_test_populations(
                source.spec.source_evidence_root, source.freeze,
                source.admission, source.group_split, cohorts,
                projection_executor=projection_executor)
        if progress is not None:
            progress(3, 6, "r4-test-populations-scored")
        cohort_ids = tuple(row.cohort_id for row in cohorts)
        expected_synthetic = _expected_test_synthetic_rounds()
        expected_human = _expected_test_human_rounds(
            source.spec.source_evidence_root, source.freeze,
            source.admission, source.group_split)
        primary = evaluate_primary_test(
            synthetic, selected_cohort_id=calibration["selected_cohort_id"],
            expected_synthetic_rounds=expected_synthetic,
            cohort_ids=cohort_ids)
        control = evaluate_label_control_test(
            synthetic, expected_synthetic_rounds=expected_synthetic,
            cohort_ids=cohort_ids)
        human_transfer = evaluate_human_transfer_test(
            human, selected_cohort_id=calibration["selected_cohort_id"],
            expected_human_rounds=expected_human, cohort_ids=cohort_ids)
        receipt = _derive_integrity_receipt(
            source.spec.source_evidence_root, source.freeze,
            source.admission, source.group_split, plan=plan,
            qualification=qualification,
            input_index_manifest=input_index_manifest,
            training_hashes=training_hashes,
            synthetic_test_count=len(synthetic),
            human_test_decision_count=sum(
                row.decision_count for row in human))
        result = derive_terminal_result(
            source.freeze, plan, qualification, receipt,
            human_selection, scale_curve, primary, control, human_transfer)
        if progress is not None:
            progress(4, 6, "r4-terminal-statistics-derived")
    except ValueError as exc:
        raise BeliefV2R4CompletionError(
            "R4 completion test derivation refused after durable attempt") \
            from exc
    files = {
        "synthetic_test": v2_round_population_bytes(
            synthetic, cohort_ids=cohort_ids, label="synthetic_test"),
        "human_test": v2_round_population_bytes(
            human, cohort_ids=cohort_ids, label="human_test"),
        "human_selection": human_selection.canonical_bytes(),
        "scale_curve": scale_curve.canonical_bytes(),
        "primary_test": primary.canonical_bytes(),
        "label_control_test": control.canonical_bytes(),
        "human_transfer": human_transfer.canonical_bytes(),
        "integrity_receipt": receipt.canonical_bytes(),
        "terminal_result": result.canonical_bytes(),
    }
    for key, raw in files.items():
        publish_exclusive_bytes(
            partial / (TEST_POPULATION_FILES | STATISTIC_FILES)[key], raw)
    inner_manifest = source_terminal_manifest(
        source.freeze, source.admission, calibration, inner_attempt, files,
        result.terminal_route)
    publish_exclusive_bytes(
        partial / "manifest.json", canonical_json_bytes(inner_manifest))
    os.rename(partial, final)
    _fsync_directory(root)
    with _projection_pool() as projection_executor:
        _warm_projection_pool(projection_executor)
        reopened = reopen_v2_terminal(
            final, freeze=source.freeze, admission=source.admission,
            inventory=source.inventory, group_split=source.group_split,
            calibration_directory=(root / "calibration" / "selection"),
            projection_executor=projection_executor)
    if reopened != inner_manifest:
        raise BeliefV2R4CompletionError(
            "R4 completion terminal post-publish reconstruction drift")
    outer = _terminal_outer_manifest(
        completion_freeze=completion_freeze,
        completion_admission=completion_admission, source=source,
        source_calibration_manifest=calibration,
        completion_attempt=completion_attempt,
        source_terminal_manifest=inner_manifest)
    publish_exclusive_bytes(outer_path, canonical_json_bytes(outer))
    _fsync_directory(root)
    if progress is not None:
        progress(6, 6, "r4-terminal-complete")
    return outer


def reopen_r4_completion_terminal(
        root: Path, completion_freeze: V2ExecutionFreezeV1,
        completion_admission: R4CompletionAdmissionV1, *, repo: Path,
        review_marker: bytes,
        progress: ProgressCallback | None = None) -> dict[str, Any]:
    """Re-score original R4 test bytes and reconstruct the fresh binding."""
    spec = load_r4_completion_source_spec()
    _completion_stage_gate(
        root, completion_freeze, completion_admission, repo=repo,
        review_marker=review_marker, spec=spec)
    calibration, source = reopen_r4_completion_calibration(
        root, completion_freeze, completion_admission, repo=repo,
        review_marker=review_marker)
    try:
        attempt_raw = stable_read_bytes(
            root / "r4-completion-test-attempt.json")
        outer_raw = stable_read_bytes(root / "r4-completion-terminal.json")
        attempt = json.loads(attempt_raw)
        outer = json.loads(outer_raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise BeliefV2R4CompletionError(
            "R4 completion terminal control reopen refused") from exc
    expected_attempt = _completion_test_attempt(
        completion_freeze=completion_freeze,
        completion_admission=completion_admission, source=source,
        source_calibration_manifest=calibration)
    if attempt != expected_attempt \
            or canonical_json_bytes(attempt) != attempt_raw:
        raise BeliefV2R4CompletionError(
            "R4 completion test attempt reconstruction drift")
    with _projection_pool() as projection_executor:
        _warm_projection_pool(projection_executor)
        inner = reopen_v2_terminal(
            root / "terminal", freeze=source.freeze,
            admission=source.admission, inventory=source.inventory,
            group_split=source.group_split, progress=progress,
            calibration_directory=(root / "calibration" / "selection"),
            projection_executor=projection_executor)
    expected_outer = _terminal_outer_manifest(
        completion_freeze=completion_freeze,
        completion_admission=completion_admission, source=source,
        source_calibration_manifest=calibration,
        completion_attempt=attempt, source_terminal_manifest=inner)
    if outer != expected_outer or canonical_json_bytes(outer) != outer_raw:
        raise BeliefV2R4CompletionError(
            "R4 completion terminal outer binding drift")
    return outer


__all__ = [
    "BeliefV2R4CompletionError", "R4CompletionSourceSpecV1",
    "R4CompletionSourceV1", "load_r4_completion_source_spec",
    "r4_completion_pretest_readiness",
    "reopen_r4_completion_calibration", "reopen_r4_completion_source",
    "reopen_r4_completion_terminal", "run_r4_completion_calibration",
    "run_r4_completion_terminal",
]

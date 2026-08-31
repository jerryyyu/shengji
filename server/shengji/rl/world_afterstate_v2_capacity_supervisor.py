"""The measured, score-free full-DAG capacity supervisor.

This module is deliberately a narrow execution boundary.  It keeps labels and
scores in local variables while running the reviewed V2 primitives, and emits
only timings and artifact sizes.  A hash loop (or a caller supplied stage
callback) cannot satisfy the ``actual`` witness required for admission.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import hashlib
import inspect
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Callable, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_artifacts import (
    WorldAfterstateV2ArtifactError,
    publish_checkpoint_shard, publish_continuation_shard,
    reopen_checkpoint_shard, reopen_continuation_manifest,
    reopen_continuation_shard,
)
from .world_afterstate_v2_capacity import (
    COMPOSED_STAGE_NAMES, MAX_COMMAND_WALL_SECONDS, PINNED_TORCH_THREADS)
from .world_afterstate_v2_controls import (
    CONTROL_NAMES, action_association_permutation, complete_world_shuffle,
    control_training_examples, label_permutation,
)
from .world_afterstate_v2_dataset import build_training_examples_v2
from .world_afterstate_v2_evaluation import evaluate_control_difference, evaluate_v2
from .world_afterstate_v2_inference import (
    build_inference_root_v2, prediction_population_manifest_v2,
)
from .world_afterstate_v2_label import (
    MECHANICS_SURFACES, P0_DEALS, ContinuationOutcomeV2,
    build_p0_mechanics_evidence, evaluate_precision_label,
    validate_precision_label,
)
from .world_afterstate_v2_metrics import build_natural_fit_prior
from .world_afterstate_v2_population import PopulationMaterialV2
from .world_afterstate_v2_selection import EpochSelectPopulationV2
from .world_afterstate_v2_training import WorldAfterstateV2TrainingConfig
from .world_afterstate_v2_training import (
    collate_training_examples, new_optimizer, train_epoch)
from .world_afterstate_v2_model import new_world_afterstate_v2_model
from .world_afterstate_v2_training_controller import (
    reopen_cohort_build, reopen_member_build, train_named_cohort,
    train_named_member,
)
from .world_afterstate_v2_protocol import (
    TIER_SPECS, StateCandidateV2, build_population_slot_ledger,
    fit_pair_id_from_slot_sha256, fit_slot_from_slot_sha256,
    select_p0_population,
)
from .world_afterstate_v2_continuation import (
    WorldAfterstateV2ContinuationError,
    reopen_continuation_bundle_v2,
)
from .world_afterstate_v2_label_controller import build_continuation_population_v2


FULL_DAG_STAGES = COMPOSED_STAGE_NAMES
TRAINING_BATCH_EXAMPLE_CAP = 256
FULL_DAG_MISSING_DEPENDENCY = (
    "scientific AuditDerivationInputV2 and audit receipts are intentionally "
    "outside the retained-32 score-free capacity witness; P0, canary, "
    "training, control, selection, audit-arithmetic, and reconstruction "
    "workloads execute with non-scientific capacity inputs"
)

_RECOVERY_CAPABILITY_NAMES = (
    "reports_stage_counts", "reports_active_workers_and_cpu",
    "reports_elapsed_eta_headroom", "reports_current_peak_cgroup_memory",
    "reports_immutable_shard_checkpoint_count", "resumes_verified_shards_only",
    "resume_same_admission", "resume_cannot_regenerate_replace_select",
    "checkpoints_each_common_epoch", "deadline_truncation_keeps_complete_epoch",
    "audit_requires_complete_upstream", "audit_attempt_fsynced_before_open",
    "one_audit_open", "reconstruction_without_retraining",
    "reconstruction_reuses_immutable_continuations",
    "reconstruction_rederives_audit_arithmetic")


class FullDAGCapacityDependencyBlocked(RuntimeError):
    """A required reviewed primitive did not execute successfully."""

    def __init__(self, message: str, *, stage: str = "full-dag",
                 reason_code: str = "full-dag-dependency-failed") -> None:
        super().__init__(message)
        self.stage = stage
        self.reason_code = reason_code


def _exact_cpu_utilization_ppm(*, wall_ns: int,
                               process_cpu_ns: int) -> int:
    """Derive aggregate host utilization from one exact stage interval."""
    if (type(wall_ns) is not int or wall_ns < 1
            or type(process_cpu_ns) is not int or process_cpu_ns < 1):
        raise FullDAGCapacityDependencyBlocked(
            "full-DAG exact CPU utilization witness drift")
    if process_cpu_ns > wall_ns * 16:
        raise FullDAGCapacityDependencyBlocked(
            "full-DAG exact CPU utilization bound drift")
    return max(1, process_cpu_ns * 1_000_000 // (wall_ns * 16))


def _predict_roots_batched(predictor: Callable[..., Any], model: Any,
                           roots: Sequence[Any], *, seed_block: int,
                           member_index: int, control_name: str,
                           inference_batch: int) -> tuple[Any, ...]:
    """Call the reviewed whole-root predictor with its batch-cap spelling."""
    parameters = inspect.signature(predictor).parameters
    if ("batch_candidate_cap" in parameters
            or any(parameter.kind is inspect.Parameter.VAR_KEYWORD
                   for parameter in parameters.values())):
        keyword = "batch_candidate_cap"
    elif "inference_batch_cap" in parameters:
        # Current inference implementation uses this equivalent spelling;
        # retain the explicit batch cap until the public name settles.
        keyword = "inference_batch_cap"
    elif "candidate_cap" in parameters:
        keyword = "candidate_cap"
    else:
        raise FullDAGCapacityDependencyBlocked(
            "batched predictor has no candidate-cap parameter")
    return tuple(predictor(
        model, roots, seed_block=seed_block, member_index=member_index,
        control_name=control_name, **{keyword: inference_batch}))


def _verified_continuation_population(
        artifact_root: Path, materials: Sequence[Any],
        bundles: Sequence[Any]) -> bool:
    """Reopen the persisted label population by deal identity, not order."""
    bundle_by_deal = {bundle.deal_sha256: bundle for bundle in bundles}
    return (len(bundle_by_deal) == len(materials)
            and all(
                material.deal_sha256 in bundle_by_deal
                and reopen_continuation_shard(
                    artifact_root, material).bundle_sha256
                == bundle_by_deal[material.deal_sha256].bundle_sha256
                for material in materials))


@dataclass(frozen=True)
class FullDAGCapacityMeasurementV2:
    """Receipt-free result consumed by the capacity runner."""

    stage_wall_nanoseconds: tuple[tuple[str, int], ...]
    artifact_bytes: int
    actual_stage_witnesses: tuple[str, ...]
    reconstruction_continuation_builds: int = 0
    admissible: bool = False
    # No default capability witness is admissible.  The supervisor must fill
    # this map from probes that ran against the sealed sample artifacts.
    progress_recovery: Mapping[str, bool] = field(default_factory=dict)
    provenance_token: object | None = None
    # Representative unit counts bind each measured stage wall to the
    # population actually executed; this prevents a 16-material label stage
    # from being mistaken for the aggregate retained-32 stage.
    stage_source_unit_counts: tuple[tuple[str, int], ...] = ()
    stage_process_cpu_nanoseconds: tuple[tuple[str, int], ...] = ()
    member_workers: int = 0
    continuation_workers: int = 0
    torch_threads: int = 0
    inference_batch: int = 0
    reconstruction_workers: int = 0
    @property
    def stage_cpu_nanoseconds(self) -> tuple[tuple[str, int], ...]:
        """Compatibility spelling for the process-CPU witness."""
        return self.stage_process_cpu_nanoseconds

    def validate(self) -> None:
        if (type(self.stage_wall_nanoseconds) is not tuple
                or tuple(name for name, _ in self.stage_wall_nanoseconds)
                != FULL_DAG_STAGES):
            raise FullDAGCapacityDependencyBlocked("full-DAG stage population drift")
        if any(type(value) is not int or value < 1
               for _, value in self.stage_wall_nanoseconds):
            raise FullDAGCapacityDependencyBlocked("full-DAG timing drift")
        wall_by_stage = dict(self.stage_wall_nanoseconds)
        if self.stage_source_unit_counts:
            if tuple(name for name, _ in self.stage_source_unit_counts) != FULL_DAG_STAGES \
                    or any(type(value) is not int or value < 1
                           for _, value in self.stage_source_unit_counts):
                raise FullDAGCapacityDependencyBlocked(
                    "full-DAG representative unit witness drift")
        if self.stage_process_cpu_nanoseconds and (
                type(self.stage_process_cpu_nanoseconds) is not tuple
                or tuple(name for name, _ in self.stage_process_cpu_nanoseconds)
                != FULL_DAG_STAGES
                or any(type(value) is not int or value < 1
                       for _, value in self.stage_process_cpu_nanoseconds)):
            raise FullDAGCapacityDependencyBlocked(
                "full-DAG process CPU witness drift")
        if self.stage_process_cpu_nanoseconds and any(
                cpu > wall_by_stage[stage] * 16
                for stage, cpu in self.stage_process_cpu_nanoseconds):
            raise FullDAGCapacityDependencyBlocked(
                "full-DAG process CPU bound drift")
        if any((self.member_workers, self.torch_threads, self.inference_batch,
                self.continuation_workers)) \
                and (self.member_workers not in (1, 2, 4)
                     or self.continuation_workers not in (1, 2, 4, 8, 12, 16, 32)
                     or type(self.torch_threads) is not int
                     or self.torch_threads != PINNED_TORCH_THREADS
                     or self.inference_batch not in (32, 64, 128, 256)
                     or self.reconstruction_workers not in (1, 4, 8, 16, 32)):
            raise FullDAGCapacityDependencyBlocked(
                "full-DAG resource layout missing")
        if self.reconstruction_workers and not self.member_workers:
            raise FullDAGCapacityDependencyBlocked(
                "full-DAG resource layout missing")
        if self.member_workers and not self.stage_process_cpu_nanoseconds:
            raise FullDAGCapacityDependencyBlocked(
                "full-DAG process/cgroup CPU witness missing")
        if self.artifact_bytes < 1 or self.reconstruction_continuation_builds != 0:
            raise FullDAGCapacityDependencyBlocked("full-DAG artifact/reconstruction drift")
        if (len(self.actual_stage_witnesses) != len(FULL_DAG_STAGES)
                or set(self.actual_stage_witnesses) != set(FULL_DAG_STAGES)
                or tuple(self.actual_stage_witnesses) != FULL_DAG_STAGES
                or not self.admissible):
            raise FullDAGCapacityDependencyBlocked("full-DAG actual witness missing")
        if (type(self.progress_recovery) is not dict
                or set(self.progress_recovery) != set(_RECOVERY_CAPABILITY_NAMES)
                or any(
                self.progress_recovery.get(name) is not True
                for name in _RECOVERY_CAPABILITY_NAMES)):
            raise FullDAGCapacityDependencyBlocked(
                "full-DAG progress/recovery capability missing")


class FullDAGCapacitySupervisorV2:
    """Small explicit wrapper used by callers that prefer an object API."""

    def __init__(self, fixtures: Sequence[Any], *, backend: Any,
                 progress: Callable[[dict[str, Any]], None] | None = None,
                 deadline_ns: int | None = None,
                 output_root: Path | None = None,
                 member_workers: int | None = None,
                 continuation_workers: int | None = None,
                 torch_threads: int | None = None,
                 inference_batch: int | None = None,
                 reconstruction_workers: int | None = None) -> None:
        self.fixtures = tuple(fixtures)
        self.backend = backend
        self.progress = progress
        self.deadline_ns = deadline_ns
        self.output_root = output_root
        self.member_workers = member_workers
        self.continuation_workers = continuation_workers
        self.torch_threads = torch_threads
        self.inference_batch = inference_batch
        self.reconstruction_workers = reconstruction_workers

    def run(self) -> FullDAGCapacityMeasurementV2:
        return run_full_dag_supervisor(
            self.fixtures, backend=self.backend, progress=self.progress,
            deadline_ns=self.deadline_ns, output_root=self.output_root,
            member_workers=self.member_workers, torch_threads=self.torch_threads,
            continuation_workers=self.continuation_workers,
            inference_batch=self.inference_batch,
            reconstruction_workers=self.reconstruction_workers)


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _identity(fixtures: Sequence[Any]) -> str:
    return _sha([fixture.fixture_sha256 for fixture in fixtures])


def _capacity_p0_inputs() -> tuple[
        tuple[ContinuationOutcomeV2, ...], Mapping[str, Any],
        tuple[StateCandidateV2, ...], Mapping[str, Any]]:
    """Build deterministic score-free inputs for the real P0 evaluator.

    Scientific P0 continuation labels are not available during capacity.
    These in-memory categories are workload values derived solely from public
    slot identities.  They exercise the exact 128-to-96 selection,
    cross-fitting, bootstrap, mechanics, and route arithmetic without opening
    or persisting a scientific outcome.
    """
    tier = TIER_SPECS[0]
    natural_slots = tuple(
        slot for slot in build_population_slot_ledger(tier)
        if slot.group == "natural-fit")
    natural = tuple(StateCandidateV2(
        deal_sha256=_sha(["capacity-p0-deal", index]),
        slot_sha256=slot.slot_sha256,
        state_sha256=_sha(["capacity-p0-state", index]),
        source="natural", split="fit", phase=slot.phase,
        position=slot.position, role=slot.role,
        trump_rank=slot.trump_rank, trump_mode=slot.trump_mode,
        select_subfold=slot.select_subfold, mechanics_surfaces=(),
        legal_candidate_count=3)
        for index, slot in enumerate(natural_slots))
    selected = select_p0_population(natural, tier=tier)
    slot_by_sha = {slot.slot_sha256: slot for slot in natural_slots}
    required = {state.deal_sha256: slot_by_sha[state.slot_sha256]
                for state in selected}
    rows: list[ContinuationOutcomeV2] = []
    for deal_index, state in enumerate(selected):
        slot = required[state.deal_sha256]
        successors = tuple(
            _sha(["capacity-p0-successor", deal_index, candidate])
            for candidate in range(3))
        candidate_set = _sha({
            "schema": "world-afterstate-v2-candidate-set-v1",
            "state_sha256": state.state_sha256,
            "successor_sha256s": list(successors),
        })
        for replica in range(8):
            for candidate in range(3):
                # Nonconstant deterministic siblings keep every statistical
                # branch live while remaining unrelated to game outcomes.
                multiplier = 4 if candidate == 2 and replica >= 4 else candidate
                rows.append(ContinuationOutcomeV2(
                    deal_sha256=state.deal_sha256,
                    slot_sha256=slot.slot_sha256,
                    state_sha256=state.state_sha256,
                    candidate_set_sha256=candidate_set,
                    source="natural", split="fit", role=slot.role,
                    phase=slot.phase, position=slot.position,
                    trump_rank=slot.trump_rank, trump_mode=slot.trump_mode,
                    points_bucket="40-79", candidate_index=candidate,
                    protected_incumbent=candidate == 0,
                    successor_sha256=successors[candidate],
                    continuation_sha256=_sha([
                        "capacity-p0-continuation", deal_index, replica]),
                    replica=replica,
                    signed_level_category=100 + candidate * multiplier))
    digest = _sha("capacity-p0-mechanics-match")
    checks = {surface: ((digest, digest),) for surface in MECHANICS_SURFACES}
    outcomes = tuple(rows)
    evidence = build_p0_mechanics_evidence(
        outcomes, required_slots=required,
        natural_fit_population=natural, tier=tier, checks=checks)
    return outcomes, required, natural, evidence


def _execute_capacity_p0(
        materials: Sequence[PopulationMaterialV2],
        inputs: tuple[tuple[ContinuationOutcomeV2, ...], Mapping[str, Any],
                      tuple[StateCandidateV2, ...], Mapping[str, Any]]) \
        -> tuple[Any, ...]:
    """Run target-free root construction and the production P0 evaluator."""
    roots = tuple(build_inference_root_v2(material) for material in materials)
    outcomes, required_slots, natural_population, mechanics = inputs
    result = evaluate_precision_label(
        outcomes, required_slots=required_slots,
        natural_fit_population=natural_population,
        tier=TIER_SPECS[0], mechanics_evidence=mechanics)
    validate_precision_label(result)
    return roots


def _fail(stage: str, exc: BaseException) -> FullDAGCapacityDependencyBlocked:
    bounded_stage = stage if stage in (*FULL_DAG_STAGES, "full-dag") else "full-dag"
    return FullDAGCapacityDependencyBlocked(
        f"full-DAG dependency failed at {stage}: {type(exc).__name__}: {exc}",
        stage=bounded_stage, reason_code="full-dag-dependency-failed")


def _build_control_training_population(
        name: str, block: int, examples: Sequence[Any],
        transform: Callable[[Sequence[Any]], tuple[Sequence[Any], Mapping[str, Any]]]
        ) -> tuple[Any, ...]:
    """Construct one control at its exact measured DAG boundary."""
    try:
        controlled, _evidence = transform(examples)
        return control_training_examples(controlled)
    except Exception as exc:
        raise _fail(f"block-{block}-{name}", exc) from exc


def _run_optimizer_canary(
        examples: Sequence[Any],
        training_cost: Callable[[Sequence[Any], int], Any]) -> None:
    """Select complete retained roots and run the real canary cost seam."""
    try:
        groups: dict[str, list[Any]] = {}
        for row in examples:
            groups.setdefault(row.root_key, []).append(row)
        if len(groups) < 16:
            raise FullDAGCapacityDependencyBlocked(
                "capacity canary requires 16 complete retained roots")
        selected_keys = sorted(groups)[:16]
        selected = tuple(row for key in selected_keys for row in groups[key])
        # Per-root candidate widths are protocol data.  The reviewed collator
        # validates each root's candidate/replica completeness below this seam.
        training_cost(selected, 500)
    except FullDAGCapacityDependencyBlocked as exc:
        raise _fail("optimizer-canary", exc) from exc
    except BaseException as exc:
        raise _fail("optimizer-canary", exc) from exc


def _build_capacity_label_population(
        work_root: Path, name: str, stage_materials: Sequence[Any], *,
        workers: int, deadline_perf_ns: int,
        progress: Callable[[dict[str, Any]], None] | None = None
        ) -> tuple[tuple[Any, ...], int, Path]:
    """Run and reopen one real, independently charged label-controller stage."""
    if name not in {"p0", "fit", "precision-select", "audit"}:
        raise FullDAGCapacityDependencyBlocked("capacity label stage drift")
    values = tuple(stage_materials)
    root = work_root / f"labels-{name}"
    if root.is_symlink():
        raise FullDAGCapacityDependencyBlocked(
            "capacity label namespace is a symlink")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    # The outer runner owns a perf-counter deadline; the production label
    # controller uses the monotonic clock. Preserve the exact remaining
    # duration without assuming that the clocks share an epoch.
    remaining_ns = max(0, deadline_perf_ns - time.perf_counter_ns())
    label_deadline_ns = time.monotonic_ns() + remaining_ns
    split = "audit" if name == "audit" else "fit-select"
    receipt = build_continuation_population_v2(
        root, values, split=split, workers=workers,
        deadline_monotonic_ns=label_deadline_ns,
        progress=(lambda row: progress({**row, "stage": name})
                  if progress is not None else None))
    reopened = reopen_continuation_manifest(root, values)
    bundles = tuple(
        reopen_continuation_bundle_v2(bundle, material)
        for material, bundle in zip(values, reopened, strict=True))
    if len(bundles) != len(values):
        raise FullDAGCapacityDependencyBlocked(
            f"capacity {name} label population incomplete")
    return bundles, receipt.artifact_bytes, root


def _capacity_stage_materials(materials: Sequence[Any]) -> tuple[
        tuple[Any, ...], tuple[Any, ...], tuple[Any, ...], tuple[Any, ...],
        tuple[Any, ...], tuple[Any, ...]]:
    """Return disjoint, protocol-faithful populations for each label stage."""
    ordered = tuple(sorted(
        materials, key=lambda material: material.state.deal_sha256))
    natural_fit = tuple(
        material for material in ordered
        if material.state.source == "natural" and material.state.split == "fit")
    epoch_select = tuple(
        material for material in ordered
        if material.state.split == "select"
        and material.state.select_subfold == "epoch-select")
    precision = tuple(
        material for material in ordered
        if material.state.split == "select"
        and material.state.select_subfold == "precision-select")
    audit = tuple(
        material for material in ordered if material.state.split == "audit")
    try:
        pair_counts = Counter(fit_pair_id_from_slot_sha256(
            material.state.slot_sha256) for material in natural_fit)
    except Exception as exc:
        raise FullDAGCapacityDependencyBlocked(
            "retained capacity pair population drift") from exc
    paired_roots = sum(count for count in pair_counts.values() if count == 2)
    if (len(natural_fit) != 17 or len({material.state.slot_sha256
                                      for material in natural_fit}) != 17
            or any(count not in (1, 2) for count in pair_counts.values())
            or paired_roots < 16
            or not epoch_select or not precision or not audit):
        raise FullDAGCapacityDependencyBlocked(
            "retained capacity sample lacks pair/fit/select/audit coverage")
    p0_count = min(16, len(natural_fit) - 1)
    p0 = natural_fit[:p0_count]
    fit_natural = natural_fit[p0_count:]
    fit_epoch_select = epoch_select[:max(1, len(epoch_select) // 2)]
    fit = fit_natural + fit_epoch_select
    return p0, fit, fit_natural, fit_epoch_select, precision, audit


def _validate_fit_slot_binding(material: PopulationMaterialV2) -> None:
    """Bind fit metadata to the canonical ledger before any measured work."""
    state = material.state
    if state.split != "fit":
        return
    try:
        slot = fit_slot_from_slot_sha256(state.slot_sha256)
    except Exception as exc:
        raise FullDAGCapacityDependencyBlocked(
            "capacity canonical fit slot binding drift") from exc
    if (state.source != slot.source or state.split != slot.split
            or state.trump_rank != slot.trump_rank
            or state.trump_mode != slot.trump_mode
            or (slot.source == "mechanics"
                and slot.mechanics_surface not in state.mechanics_surfaces)
            or (slot.source != "mechanics" and state.cell != slot.cell)):
        raise FullDAGCapacityDependencyBlocked(
            "capacity canonical fit slot binding drift")


def _capacity_training_pairs(
        p0_materials: Sequence[Any], p0_bundles: Sequence[Any],
        fit_materials: Sequence[Any], fit_bundles: Sequence[Any]
        ) -> tuple[tuple[Any, Any], ...]:
    """Reuse every natural-fit label while excluding epoch-select targets."""
    p0 = tuple(zip(p0_materials, p0_bundles, strict=True))
    later = tuple(zip(fit_materials, fit_bundles, strict=True))
    values = p0 + tuple(
        pair for pair in later if pair[0].state.split == "fit")
    if (not values or any(
            material.state.source != "natural" or material.state.split != "fit"
            for material, _bundle in values)
            or len({material.state.deal_sha256
                    for material, _bundle in values}) != len(values)):
        raise FullDAGCapacityDependencyBlocked(
            "capacity training population membership drift")
    try:
        pair_counts = Counter(fit_pair_id_from_slot_sha256(
            material.state.slot_sha256) for material, _bundle in values)
    except Exception as exc:
        raise FullDAGCapacityDependencyBlocked(
            "capacity training pair population drift") from exc
    if (len(values) != 17
            or sum(count for count in pair_counts.values() if count == 2) < 16
            or any(count not in (1, 2) for count in pair_counts.values())):
        raise FullDAGCapacityDependencyBlocked(
            "capacity training pair population drift")
    return values


def run_full_dag_supervisor(
        fixtures: Sequence[Any], *, backend: Any,
        progress: Callable[[dict[str, Any]], None] | None = None,
        deadline_ns: int | None = None,
        output_root: Path | None = None,
        member_workers: int | None = None,
        continuation_workers: int | None = None,
        torch_threads: int | None = None,
        inference_batch: int | None = None,
        reconstruction_workers: int | None = None,
        _provenance: object | None = None) -> FullDAGCapacityMeasurementV2:
    """Execute every representative stage over the retained 32 materials.

    ``backend`` is intentionally an internal runner seam.  Synthetic backends
    are refused here as well as by receipt construction; production supplies
    the real telemetry backend owned by the runner.
    """
    values = tuple(fixtures)
    if len(values) != 32 or len({item.fixture_sha256 for item in values}) != 32:
        raise FullDAGCapacityDependencyBlocked("full-DAG requires 32 unique fixtures")
    if getattr(backend, "synthetic", False):
        raise FullDAGCapacityDependencyBlocked("synthetic supervisor backend refused")
    materials: list[PopulationMaterialV2] = []
    for item in values:
        material = getattr(item, "material", None)
        if type(material) is not PopulationMaterialV2:
            raise FullDAGCapacityDependencyBlocked("fixture retained PopulationMaterialV2 is missing")
        try:
            material.validate()
        except Exception as exc:
            raise _fail("material", exc) from exc
        _validate_fit_slot_binding(material)
        materials.append(material)
    if (member_workers not in (1, 2, 4)
            or continuation_workers not in (1, 2, 4, 8, 12, 16, 32)
            or type(torch_threads) is not int
            or torch_threads != PINNED_TORCH_THREADS
            or inference_batch not in (32, 64, 128, 256)
            or reconstruction_workers not in (1, 4, 8, 16, 32)):
        raise FullDAGCapacityDependencyBlocked(
            "full-DAG resource layout missing")
    identity = _identity(values)
    if deadline_ns is None:
        deadline_ns = (time.perf_counter_ns()
                       + MAX_COMMAND_WALL_SECONDS * 1_000_000_000)
    walls: dict[str, int] = {}
    process_cpu: dict[str, int] = {}
    witnesses: list[str] = []
    artifact_count = 0
    immutable_shard_count = 0
    immutable_shard_bytes = 0
    examples: tuple[Any, ...] = ()
    training_pairs: tuple[tuple[Any, Any], ...] = ()
    roots: tuple[Any, ...] = ()
    cohort_builds: dict[tuple[str, int], Any] = {}
    predictions: dict[tuple[str, int], dict[str, Any]] = {}
    evaluations: dict[tuple[str, int], Any] = {}
    audit_predictions: dict[tuple[str, int], dict[str, Any]] = {}
    audit_evaluations: dict[tuple[str, int], Any] = {}
    audit_derivation_sha256: str | None = None
    capability_probes = {name: False for name in _RECOVERY_CAPABILITY_NAMES}
    progress_events: list[dict[str, Any]] = []
    training_invocations = 0
    audit_open_count = 0
    checkpoint_common_epochs: list[int] = []
    p0_inputs = _capacity_p0_inputs()

    started = time.perf_counter_ns()
    def measure(stage: str, operation: Callable[[], Any], workers: int = 1) -> Any:
        if deadline_ns is not None and time.perf_counter_ns() >= deadline_ns:
            raise FullDAGCapacityDependencyBlocked(
                f"full-DAG deadline exceeded before {stage}")
        try:
            raw = backend.measure(stage, workers, values[0], operation)
            validator = getattr(raw, "validate", None)
            if callable(validator):
                validator()
            if (isinstance(raw.elapsed_ns, bool)
                    or not isinstance(raw.elapsed_ns, int)
                    or isinstance(raw.process_cpu_ns, bool)
                    or not isinstance(raw.process_cpu_ns, int)):
                raise ValueError("stage timer type drift")
            elapsed = raw.elapsed_ns
            cpu_elapsed = raw.process_cpu_ns
            if elapsed < 1:
                raise ValueError("non-positive stage timer")
            if cpu_elapsed < 1:
                raise ValueError("non-positive stage CPU timer")
            # The receipt's progress/recovery capabilities are earned from
            # live measurements, not default values in a progress callback.
            for attribute in ("sample_utilization_ppm", "sample_memory_bytes",
                              "sample_task_counts", "sample_free_disk_bytes"):
                if not getattr(raw, attribute, ()):
                    raise ValueError(f"missing {attribute} telemetry")
            if getattr(raw, "byte_identity_sha256", identity) != identity:
                raise ValueError("byte-identical fixture identity drift")
            memory_samples = tuple(raw.sample_memory_bytes)
            task_samples = tuple(raw.sample_task_counts)
            def accumulate(name: str, value: bool) -> None:
                capability_probes[name] = value if not witnesses else (
                    capability_probes[name] and value)
            accumulate("reports_active_workers_and_cpu",
                workers > 0 and bool(raw.sample_utilization_ppm))
            accumulate("reports_current_peak_cgroup_memory",
                bool(memory_samples) and memory_samples[-1] >= 1
                and max(memory_samples) >= memory_samples[-1])
        except FullDAGCapacityDependencyBlocked:
            raise
        except BaseException as exc:
            raise _fail(stage, exc) from exc
        walls[stage] = elapsed
        process_cpu[stage] = cpu_elapsed
        witnesses.append(stage)
        elapsed_total = max(1, time.perf_counter_ns() - started)
        completed = len(witnesses)
        remaining = len(FULL_DAG_STAGES) - completed
        eta_seconds = ((elapsed_total * remaining + completed - 1)
                       // completed // 1_000_000_000)
        event = {
            "stage": stage, "completed_units": completed,
            "total_units": len(FULL_DAG_STAGES), "workers": workers,
            # Derive progress utilization from the measured nanoseconds.  A
            # backend-provided summary or a fabricated ``1`` is not an
            # admissible substitute for the exact stage counters.
            # Capacity telemetry is aggregate host utilization: normalize the
            # exact process/cgroup CPU interval by wall time and the pinned
            # 16 logical CPUs.  Never use a placeholder utilization value.
            "utilization_ppm": _exact_cpu_utilization_ppm(
                wall_ns=elapsed, process_cpu_ns=cpu_elapsed),
            "elapsed_seconds": max(1, elapsed_total // 1_000_000_000),
            "eta_seconds": eta_seconds,
            "headroom_seconds": max(0, MAX_COMMAND_WALL_SECONDS
                                     - elapsed_total // 1_000_000_000),
            "memory_bytes": memory_samples[-1],
            "peak_memory_bytes": max(memory_samples),
            "task_count": task_samples[-1] if task_samples else 1,
            "peak_task_count": max(task_samples) if task_samples else 1,
            "queue_depth": getattr(raw, "queue_depth", 0),
            "disk_free_bytes": (getattr(raw, "sample_free_disk_bytes", (1,))[-1]),
            "immutable_shards": immutable_shard_count,
            "immutable_shard_bytes": immutable_shard_bytes,
            "artifact_bytes": artifact_count,
            "checkpoint_count": len(cohort_builds) * 4}
        first_event = not progress_events
        progress_events.append(event)
        if progress is not None:
            progress(event)
        capability_probes["reports_stage_counts"] = (
            event["completed_units"] == len(witnesses)
            and event["total_units"] == len(FULL_DAG_STAGES)) if first_event else (
                capability_probes["reports_stage_counts"] and
                event["completed_units"] == len(witnesses)
                and event["total_units"] == len(FULL_DAG_STAGES))
        event_ok = (
            event["elapsed_seconds"] >= 1
            and event["headroom_seconds"] > 0
            and event["eta_seconds"] >= 0)
        capability_probes["reports_elapsed_eta_headroom"] = event_ok if first_event else (
            capability_probes["reports_elapsed_eta_headroom"] and event_ok)
        shard_ok = (
            event["immutable_shards"] == immutable_shard_count
            and event["immutable_shard_bytes"] == immutable_shard_bytes
            and event["artifact_bytes"] == artifact_count
            and event["checkpoint_count"] == len(cohort_builds) * 4)
        capability_probes["reports_immutable_shard_checkpoint_count"] = shard_ok if first_event else (
            capability_probes["reports_immutable_shard_checkpoint_count"] and shard_ok)
        return raw

    if output_root is None:
        # Direct unit callers retain an ephemeral seam. Production passes the
        # CLI work root. Interrupted attempts retain verified label shards for
        # diagnosis, but a capacity retry must use a fresh namespace so old
        # zero-time reopens cannot become performance evidence. Capacity-only
        # checkpoints remain ephemeral below.
        temp_context = tempfile.TemporaryDirectory(prefix="shengji-v2-full-dag-")
        artifact_root = Path(temp_context.name)
    else:
        temp_context = None
        artifact_root = Path(output_root).absolute()
        if artifact_root.exists() or artifact_root.is_symlink():
            raise FullDAGCapacityDependencyBlocked(
                "capacity work namespace is occupied or aliased")
        artifact_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not artifact_root.is_dir():
        raise FullDAGCapacityDependencyBlocked(
            "capacity work namespace was not created")
    else:
        ephemeral_context = tempfile.TemporaryDirectory(
            prefix="shengji-v2-capacity-ephemeral-")
        ephemeral_root = Path(ephemeral_context.name)

        def p0() -> str:
            nonlocal roots
            roots = _execute_capacity_p0(materials, p0_inputs)
            return identity

        # The retained sample is partitioned deterministically so the P0
        # representative is never rebuilt/counting again in later fit labels.
        # Precision and audit populations are separate staged callbacks; their
        # labels are generated only after their respective dependency fences.
        (p0_materials, fit_materials, fit_natural_materials,
         fit_epoch_select_materials, precision_materials,
         audit_materials) = _capacity_stage_materials(materials)
        p0_bundles: list[Any] = []
        fit_bundles: list[Any] = []
        precision_bundles: list[Any] = []
        audit_bundles: list[Any] = []
        label_roots: dict[str, Path] = {}

        def _label_population(name: str, stage_materials: Sequence[Any]) -> tuple[Any, ...]:
            nonlocal artifact_count, immutable_shard_count, immutable_shard_bytes
            stage_bundles, artifacts, root = _build_capacity_label_population(
                artifact_root, name, stage_materials,
                workers=continuation_workers, deadline_perf_ns=deadline_ns,
                progress=progress)
            label_roots[name] = root
            artifact_count += artifacts
            immutable_shard_count += len(stage_bundles)
            immutable_shard_bytes += sum(
                len(bundle.canonical_bytes) for bundle in stage_bundles)
            return stage_bundles

        def label_p0() -> str:
            nonlocal p0_bundles
            p0_bundles = list(_label_population("p0", p0_materials))
            return identity

        def label_precision_select() -> str:
            nonlocal precision_bundles
            precision_bundles = list(_label_population(
                "precision-select", precision_materials))
            return identity

        # Capacity uses deterministic in-memory categories to execute the real
        # P0 cross-fit/bootstrap/mechanics arithmetic.  It never mints a
        # scientific report or opens scientific continuation outcomes.
        measure("label-p0", label_p0, continuation_workers)
        measure("p0", p0)

        def build_examples(source: Sequence[Any]) -> tuple[Any, ...]:
            rows = []
            for material, bundle in source:
                rows.extend(build_training_examples_v2(material, bundle))
            return tuple(rows)

        examples = build_examples(tuple(zip(p0_materials, p0_bundles,
                                             strict=True)))

        config = WorldAfterstateV2TrainingConfig(
            learning_rate_ppb=10_000_000, weight_decay_ppb=0,
            gradient_norm_milli=1_000, max_epochs=1, sigma_pair_squared=1.0)
        fit_deals = {material.state.deal_sha256
                     for material in fit_natural_materials}
        epoch_select_deals = {material.state.deal_sha256
                              for material in fit_epoch_select_materials}
        precision_deals = {
            material.state.deal_sha256 for material in precision_materials}
        audit_deals = {material.state.deal_sha256 for material in audit_materials}
        select_roots = tuple(__import__("dataclasses").replace(
            root, split="select", select_subfold="epoch-select")
            for root in roots if root.deal_sha256 in epoch_select_deals)
        precision_roots = tuple(__import__("dataclasses").replace(
            root, split="select", select_subfold="epoch-select")
            for root in roots if root.deal_sha256 in precision_deals)
        audit_roots = tuple(__import__("dataclasses").replace(
            root, split="audit", select_subfold=None)
            for root in roots if root.deal_sha256 in audit_deals)
        select_outcomes: tuple[Any, ...] = ()
        selection: EpochSelectPopulationV2 | None = None

        def train(cohort: str, block: int, vals: Sequence[Any], natural: Sequence[Any] | None = None) -> str:
            nonlocal artifact_count, immutable_shard_count
            nonlocal immutable_shard_bytes, training_invocations
            # The natural block-1 build is a shared reviewed artifact.  It is
            # consumed by canary/nested/primary stages, never retrained.
            if (cohort, block) in cohort_builds:
                return identity
            persist_artifact = (cohort, block) not in cohort_builds
            build = train_named_cohort(
                cohort_name=cohort, values=vals,
                natural_values=natural, freeze_sha256=_sha(identity),
                config=config, selection_population=selection, seed_block=block,
                member_workers=member_workers, torch_threads=torch_threads,
                # Training batching is a frozen recipe constant.  The
                # independently measured inference arm affects only model
                # prediction below.
                batch_example_cap=TRAINING_BATCH_EXAMPLE_CAP,
                wall_budget_nanoseconds=2 * 60 * 60 * 1_000_000_000)
            training_invocations += 1
            manifest = getattr(build, "manifest", None)
            if (type(manifest) is not dict
                    or manifest.get("cohort_name") != cohort
                    or manifest.get("seed_block") != block):
                raise FullDAGCapacityDependencyBlocked(
                    f"full-DAG cohort block binding drift: {cohort}:{block}")
            cohort_builds[(cohort, block)] = build
            if persist_artifact:
                for member, raw in enumerate(build.selected_checkpoint_raws):
                    shard = publish_checkpoint_shard(
                        ephemeral_root, raw, cohort=cohort, seed_block=block,
                        member_index=member, epoch=1)
                    artifact_count += shard.byte_count
                    immutable_shard_count += 1
                    immutable_shard_bytes += shard.byte_count
                    _model, metadata = reopen_checkpoint_shard(
                        ephemeral_root, cohort, block, member, 1)
                    checkpoint_common_epochs.append(metadata["selected_epoch"])
            return identity

        def training_cost(rows: Sequence[Any], steps: int) -> None:
            nonlocal training_invocations
            if not rows:
                raise FullDAGCapacityDependencyBlocked("capacity training sample is empty")
            batch = collate_training_examples(tuple(rows))
            model = new_world_afterstate_v2_model(0)
            optimizer = new_optimizer(model, config)
            for _ in range(steps):
                train_epoch(model, optimizer, (batch,), epoch=1, config=config)
                training_invocations += 1

        def run_canary() -> str:
            # This is deliberately not produce_optimizer_canary_v2: that
            # producer emits scientific evidence and requires the full 128
            # natural-fit population.  Capacity measures the same 500 actual
            # optimizer steps over the 16 smallest complete retained roots.
            _run_optimizer_canary(examples, training_cost)
            return identity
        measure("optimizer-canary", run_canary, member_workers)

        def label_fit_and_prepare() -> str:
            nonlocal examples, training_pairs, select_outcomes, selection
            fit_bundles.extend(_label_population("fit", fit_materials))
            training_pairs = _capacity_training_pairs(
                p0_materials, p0_bundles, fit_materials, fit_bundles)
            examples = build_examples(training_pairs)
            select_outcomes = tuple(__import__("dataclasses").replace(
                row, split="select") for bundle in fit_bundles
                if bundle.deal_sha256 in epoch_select_deals
                for row in bundle.candidates)
            selection = EpochSelectPopulationV2(select_roots, select_outcomes)
            selection.validate()
            return identity

        # The remaining fit and epoch-select labels are opened only after the
        # P0 roots and optimizer-canary have completed.
        measure("label-fit", label_fit_and_prepare, continuation_workers)

        nested_builds: dict[str, Any] = {}

        def run_nested(stage: str, fraction: float) -> str:
            # Use the reviewed single-member controller, which performs the
            # real fit epoch(s) followed by sealed epoch-select scoring.  The
            # returned build remains in memory for this capacity witness only.
            nested_builds[stage] = train_named_member(
                values=examples, data_fraction=fraction, member_name=stage,
                freeze_sha256=_sha(identity), config=config,
                selection_population=selection, seed_block=1, member_index=0,
                cohort_name="natural", member_workers=1,
                torch_threads=torch_threads,
                batch_example_cap=TRAINING_BATCH_EXAMPLE_CAP,
                wall_budget_nanoseconds=2 * 60 * 60 * 1_000_000_000)
            model, manifest = reopen_member_build(nested_builds[stage])
            if model is None or manifest.get("member_index") != 0:
                raise FullDAGCapacityDependencyBlocked(
                    f"nested member build drift: {stage}")
            return identity

        for stage, fraction in (("nested-curve-25", 0.25),
                                ("nested-curve-50", 0.50)):
            measure(stage, lambda stage=stage, fraction=fraction:
                    run_nested(stage, fraction), 1)

        control_rows: dict[str, tuple[Any, ...]] = {}
        transforms = {
            CONTROL_NAMES[0]: action_association_permutation,
            CONTROL_NAMES[1]: label_permutation,
            CONTROL_NAMES[2]: complete_world_shuffle,
        }
        def control_train(name: str, block: int) -> str:
            if name not in control_rows:
                control_rows[name] = _build_control_training_population(
                    name, block, examples, transforms[name])
            return train(name, block, control_rows[name], examples)
        def natural_block1() -> str:
            # The natural block-1 artifact is built once and cached by
            # ``train``.  Nested cost uses the raw train_epoch primitive and
            # never invokes train_named_cohort a second time.
            return train("natural", 1, examples)
        measure("block-1-natural", natural_block1, member_workers)
        # Nested-100 is evaluation/reuse only: reopen block-1 member 0 and
        # score it on the sealed fit/select population.  It must never train.
        def run_nested_100() -> str:
            build = cohort_builds.get(("natural", 1))
            if build is None or selection is None:
                raise FullDAGCapacityDependencyBlocked(
                    "nested-100 natural member is missing")
            models, manifest = reopen_cohort_build(build)
            if len(models) != 4 or manifest.get("cohort_name") != "natural":
                raise FullDAGCapacityDependencyBlocked(
                    "nested-100 cohort reopen drift")
            selected_epoch = manifest["common_epoch"]["selected_epoch"]
            selection.score(
                models[0], epoch=selected_epoch, seed_block=1,
                member_index=0, control_name="natural",
                sigma_pair_squared=config.sigma_pair_squared)
            return identity

        measure("nested-curve-100", run_nested_100, 1)
        measure("block-1-action-association-permutation",
                lambda: control_train(CONTROL_NAMES[0], 1), member_workers)
        measure("block-1-label-permutation",
                lambda: control_train(CONTROL_NAMES[1], 1), member_workers)
        measure("block-1-complete-world-shuffle",
                lambda: control_train(CONTROL_NAMES[2], 1), member_workers)
        measure("block-2-natural", lambda: train("natural", 2, examples), member_workers)
        measure("block-2-complete-world-shuffle",
                lambda: control_train(CONTROL_NAMES[2], 2), member_workers)

        expected_cohorts = {
            ("natural", 1), ("natural", 2),
            (CONTROL_NAMES[0], 1), (CONTROL_NAMES[1], 1),
            (CONTROL_NAMES[2], 1), (CONTROL_NAMES[2], 2)}
        capability_probes["checkpoints_each_common_epoch"] = (
            set(cohort_builds) == expected_cohorts
            and len(checkpoint_common_epochs) == len(expected_cohorts) * 4
            and len(set(checkpoint_common_epochs)) == 1
            and checkpoint_common_epochs[0] >= 1)

        # Exercise the real training controller's deadline branch once.  A
        # normal completed cohort is not evidence that truncation preserves a
        # complete common epoch, and an asserted capability bit is not a
        # witness.  The clock below lets exactly one epoch finish, then expires
        # the budget before epoch two.  Reopening the returned build proves the
        # four selected checkpoints and their common-epoch chain remain usable
        # while the manifest is explicitly ineligible for audit.
        truncation_clock_calls = 0

        def truncation_clock() -> int:
            nonlocal truncation_clock_calls
            truncation_clock_calls += 1
            return 0 if truncation_clock_calls <= 3 else 1

        truncated_build = train_named_cohort(
            cohort_name="natural", values=examples,
            freeze_sha256=_sha(identity), config=__import__(
                "dataclasses").replace(config, max_epochs=2),
            selection_population=selection, seed_block=1,
            member_workers=member_workers, torch_threads=torch_threads,
            batch_example_cap=TRAINING_BATCH_EXAMPLE_CAP,
            wall_budget_nanoseconds=1, clock=truncation_clock)
        reopened_models, reopened_manifest = reopen_cohort_build(truncated_build)
        capability_probes["deadline_truncation_keeps_complete_epoch"] = (
            len(reopened_models) == 4
            and len(truncated_build.selected_checkpoint_raws) == 4
            and reopened_manifest["truncated_by_deadline"] is True
            and reopened_manifest["stop_reason"] == "deadline-truncation"
            and reopened_manifest["audit_eligible"] is False
            and reopened_manifest["common_epoch"]["selected_epoch"] >= 1
            and all(member["epoch_receipts"] for member in
                    reopened_manifest["members"]))

        def infer() -> str:
            # Import lazily so this capacity artifact can land before the
            # companion batched inference implementation.  Once present, a
            # root-by-root call is intentionally impossible here.
            try:
                from .world_afterstate_v2_inference import predict_roots_v2
            except ImportError as exc:
                raise FullDAGCapacityDependencyBlocked(
                    "batched predict_roots_v2 dependency is missing") from exc
            for (cohort, block), build in cohort_builds.items():
                select_rows = []
                audit_rows = []
                for member, raw in enumerate(build.selected_checkpoint_raws):
                    model, _ = __import__("shengji.rl.world_afterstate_v2_checkpoint", fromlist=["reopen_checkpoint"]).reopen_checkpoint(raw)
                    select_rows.extend(_predict_roots_batched(
                        predict_roots_v2, model, precision_roots,
                        seed_block=block, member_index=member,
                        control_name=cohort, inference_batch=inference_batch))
                    audit_rows.extend(_predict_roots_batched(
                        predict_roots_v2, model, audit_roots,
                        seed_block=block, member_index=member,
                        control_name=cohort, inference_batch=inference_batch))
                predictions[(cohort, block)] = prediction_population_manifest_v2(
                    precision_roots, tuple(select_rows), split="select", control_name=cohort,
                    seed_block=block)
                audit_predictions[(cohort, block)] = prediction_population_manifest_v2(
                    audit_roots, tuple(audit_rows), split="audit", control_name=cohort,
                    seed_block=block)
            return identity
        measure("precision-select-inference", infer, member_workers)
        prior = build_natural_fit_prior(examples)
        # Precision-select continuation labels are a distinct spend and are
        # opened only after all prediction manifests have sealed.
        measure("label-precision-select", label_precision_select,
                continuation_workers)
        precision_outcomes = tuple(__import__("dataclasses").replace(
            row, split="select") for bundle in precision_bundles
            for row in bundle.candidates)

        def precision_stage() -> str:
            evaluated = tuple(evaluate_v2(manifest, precision_outcomes, prior)
                              for manifest in predictions.values())
            for value in evaluated:
                evaluations[(value.control_name, value.seed_block)] = value
            if ("natural", 1) not in evaluations:
                raise FullDAGCapacityDependencyBlocked(
                    "capacity select evaluation population missing")
            return identity
        measure("precision-select", precision_stage, member_workers)

        def open_audit_labels() -> str:
            """Publish the attempt boundary, then measure the sole label open."""
            nonlocal audit_open_count
            capability_probes["audit_requires_complete_upstream"] = (
                set(cohort_builds) == expected_cohorts
                and set(predictions) == expected_cohorts
                and set(audit_predictions) == expected_cohorts)
            upstream_reopened = (
                artifact_count > 0
                and _verified_continuation_population(
                    label_roots["p0"], p0_materials, p0_bundles)
                and _verified_continuation_population(
                    label_roots["fit"], fit_materials, fit_bundles)
                and _verified_continuation_population(
                    label_roots["precision-select"], precision_materials,
                    precision_bundles))
            attempt_payload = canonical_json_bytes({
                "schema": "retained-32-capacity-audit-attempt-v1",
                "audit_population_sha256": _sha(
                    [root.root_sha256 for root in audit_roots]),
                "upstream_complete": capability_probes[
                    "audit_requires_complete_upstream"]})
            attempt_path = ephemeral_root / "audit-attempt.json"
            if attempt_path.exists() or attempt_path.is_symlink():
                if attempt_path.is_symlink():
                    raise FullDAGCapacityDependencyBlocked(
                        "capacity audit attempt marker is a symlink")
                with attempt_path.open("rb") as handle:
                    audit_open_count += 1
                    reopened_attempt = handle.read()
                if reopened_attempt != attempt_payload:
                    raise FullDAGCapacityDependencyBlocked(
                        "capacity audit attempt marker binding drift")
            else:
                with attempt_path.open("xb") as handle:
                    handle.write(attempt_payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                with attempt_path.open("rb") as handle:
                    audit_open_count += 1
                    reopened_attempt = handle.read()
            if reopened_attempt != attempt_payload:
                capability_probes["audit_attempt_fsynced_before_open"] = False
            try:
                with attempt_path.open("xb"):
                    pass
            except FileExistsError:
                pass
            else:
                capability_probes["one_audit_open"] = False
            directory_fd = os.open(ephemeral_root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            capability_probes["audit_attempt_fsynced_before_open"] = (
                upstream_reopened and reopened_attempt == attempt_payload)
            # The durable attempt marker and parent-directory fsync above are
            # the audit-label boundary.  Build continuations exactly once and
            # charge their wall/CPU to the explicit label-audit stage.
            # Audit has its own immutable manifest and independently charged
            # representative continuation spend.
            audit_bundles.extend(_label_population("audit", audit_materials))
            return identity

        measure("label-audit", open_audit_labels, continuation_workers)

        def derive_audit_clone() -> tuple[dict[tuple[str, int], Any], str]:
            # Evaluate the deterministic audit clone with the same pure
            # evaluation/control arithmetic.  This is timing-only: no P0,
            # AuditDerivationInputV2, or terminal scientific receipt is
            # constructed from the 32-deal sample.
            audit_outcomes = tuple(__import__("dataclasses").replace(
                row, split="audit") for bundle in audit_bundles
                for row in bundle.candidates)
            evaluated = tuple(evaluate_v2(manifest, audit_outcomes, prior)
                              for manifest in audit_predictions.values())
            by_cohort = {(value.control_name, value.seed_block): value
                         for value in evaluated}
            comparisons = []
            for name, block in ((CONTROL_NAMES[0], 1),
                                (CONTROL_NAMES[1], 1),
                                (CONTROL_NAMES[2], 1),
                                (CONTROL_NAMES[2], 2)):
                natural = by_cohort[("natural", block)]
                comparisons.append(evaluate_control_difference(
                    natural, by_cohort[(name, block)]))
            derivation_sha = _sha({
                "evaluations": [[name, block, value.sha256()]
                                for (name, block), value in sorted(
                                    by_cohort.items())],
                "control_comparisons": [value.sha256()
                                        for value in comparisons],
            })
            return by_cohort, derivation_sha

        def audit_cost() -> str:
            nonlocal audit_derivation_sha256
            by_cohort, audit_derivation_sha256 = derive_audit_clone()
            audit_evaluations.clear()
            audit_evaluations.update(by_cohort)
            return identity
        measure("audit", audit_cost, 1)

        def reconstruct() -> str:
            nonlocal capability_probes
            training_before = training_invocations
            reused = True
            replace_refused = True
            wrong_admission_refused = True
            populations = (
                ("p0", p0_materials, tuple(p0_bundles)),
                ("fit", fit_materials, tuple(fit_bundles)),
                ("precision-select", precision_materials,
                 tuple(precision_bundles)),
                ("audit", audit_materials, tuple(audit_bundles)),
            )
            for name, stage_materials, stage_bundles in populations:
                # This is the actual reconstruction workload: reopen the
                # sealed aggregate with the selected worker width, retaining
                # manifest order while the artifact boundary validates every
                # shard and parent-level population/hash contract.
                reopened_population = reopen_continuation_manifest(
                    label_roots[name], stage_materials,
                    workers=reconstruction_workers)
                reopened_by_deal = {
                    bundle.deal_sha256: bundle
                    for bundle in reopened_population}
                for index, (material, expected) in enumerate(zip(
                        stage_materials, stage_bundles, strict=True)):
                    reopened = reopened_by_deal.get(material.deal_sha256)
                    if reopened is None:
                        raise FullDAGCapacityDependencyBlocked(
                            "reconstruction continuation population drift")
                    reopened = reopen_continuation_bundle_v2(reopened, material)
                    reused = reused and (
                        reopened.bundle_sha256 == expected.bundle_sha256)
                    wrong_material = materials[
                        (materials.index(material) + 1) % len(materials)]
                    try:
                        reopen_continuation_bundle_v2(reopened, wrong_material)
                    except WorldAfterstateV2ContinuationError:
                        pass
                    else:
                        wrong_admission_refused = False
                    try:
                        publish_continuation_shard(
                            label_roots[name], material, reopened)
                    except WorldAfterstateV2ArtifactError:
                        pass
                    else:
                        replace_refused = False
            capability_probes["resumes_verified_shards_only"] = reused
            capability_probes["resume_same_admission"] = reused and wrong_admission_refused
            capability_probes["resume_cannot_regenerate_replace_select"] = replace_refused
            capability_probes["reconstruction_without_retraining"] = (
                training_invocations == training_before)
            capability_probes["reconstruction_reuses_immutable_continuations"] = reused
            # The scientific immediate verifier reopens the already-sealed
            # predictions/outcomes and repeats audit arithmetic. Charge that
            # work here without rebuilding any continuation.
            _, reconstructed_sha = derive_audit_clone()
            capability_probes["reconstruction_rederives_audit_arithmetic"] = (
                audit_derivation_sha256 is not None
                and reconstructed_sha == audit_derivation_sha256)
            return identity
        measure("reconstruction", reconstruct, reconstruction_workers)

    if temp_context is not None:
        temp_context.cleanup()
    ephemeral_context.cleanup()
    capability_probes["one_audit_open"] = audit_open_count == 1
    capability_probes["reports_stage_counts"] = (
        len(progress_events) == len(FULL_DAG_STAGES)
        and tuple(event["stage"] for event in progress_events) == FULL_DAG_STAGES)
    capability_probes["reports_elapsed_eta_headroom"] = (
        bool(progress_events)
        and all(event["elapsed_seconds"] >= 1
                and event["headroom_seconds"] >= 1
                for event in progress_events))
    training_material_count = len(training_pairs)
    result = FullDAGCapacityMeasurementV2(
        tuple((stage, walls[stage]) for stage in FULL_DAG_STAGES),
        max(1, artifact_count), tuple(witnesses), 0, True,
        dict(capability_probes), _provenance,
        tuple((stage, {
            "label-p0": len(p0_materials), "p0": P0_DEALS,
            "optimizer-canary": 16 * 500, "label-fit": len(fit_materials),
            "nested-curve-25": max(1, training_material_count * 25 // 100)
            + len(select_roots),
            "nested-curve-50": max(1, training_material_count * 50 // 100)
            + len(select_roots),
            "block-1-natural": training_material_count,
            "nested-curve-100": len(select_roots),
            "block-1-action-association-permutation": training_material_count,
            "block-1-label-permutation": training_material_count,
            "block-1-complete-world-shuffle": training_material_count,
            "block-2-natural": training_material_count,
            "block-2-complete-world-shuffle": training_material_count,
            "precision-select-inference": len(precision_materials),
            "label-precision-select": len(precision_materials),
            "precision-select": len(precision_materials),
            "audit": len(audit_materials),
            "label-audit": len(audit_materials),
            "reconstruction": len(materials),
        }[stage]) for stage in FULL_DAG_STAGES),
        tuple((stage, process_cpu[stage]) for stage in FULL_DAG_STAGES),
        member_workers, continuation_workers, torch_threads, inference_batch,
        reconstruction_workers)
    result.validate()
    return result


__all__ = ["FULL_DAG_MISSING_DEPENDENCY", "FULL_DAG_STAGES",
           "FullDAGCapacityDependencyBlocked",
           "FullDAGCapacityMeasurementV2", "FullDAGCapacitySupervisorV2",
           "run_full_dag_supervisor"]

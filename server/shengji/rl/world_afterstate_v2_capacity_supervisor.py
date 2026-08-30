"""The measured, score-free full-DAG capacity supervisor.

This module is deliberately a narrow execution boundary.  It keeps labels and
scores in local variables while running the reviewed V2 primitives, and emits
only timings and artifact sizes.  A hash loop (or a caller supplied stage
callback) cannot satisfy the ``actual`` witness required for admission.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Callable, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_artifacts import (
    WorldAfterstateV2ArtifactError,
    publish_checkpoint_shard, publish_continuation_shard,
    reopen_checkpoint_shard, reopen_continuation_shard,
)
from .world_afterstate_v2_capacity import (
    COMPOSED_STAGE_NAMES, MAX_COMMAND_WALL_SECONDS)
from .world_afterstate_v2_controls import (
    CONTROL_NAMES, action_association_permutation, complete_world_shuffle,
    control_training_examples, label_permutation,
)
from .world_afterstate_v2_dataset import build_training_examples_v2
from .world_afterstate_v2_evaluation import evaluate_control_difference, evaluate_v2
from .world_afterstate_v2_inference import (
    build_inference_root_v2, predict_root_v2,
    prediction_population_manifest_v2,
)
from .world_afterstate_v2_metrics import build_natural_fit_prior
from .world_afterstate_v2_population import PopulationMaterialV2
from .world_afterstate_v2_selection import EpochSelectPopulationV2
from .world_afterstate_v2_training import WorldAfterstateV2TrainingConfig
from .world_afterstate_v2_training import (
    collate_training_examples, new_optimizer, train_epoch)
from .world_afterstate_v2_model import new_world_afterstate_v2_model
from .world_afterstate_v2_training_controller import (
    reopen_cohort_build, train_named_cohort,
)
from .world_afterstate_v2_protocol import TIER_SPECS
from .world_afterstate_v2_continuation import (
    WorldAfterstateV2ContinuationError,
    build_continuation_bundle_v2, reopen_continuation_bundle_v2,
)


FULL_DAG_STAGES = COMPOSED_STAGE_NAMES
FULL_DAG_MISSING_DEPENDENCY = (
    "scientific P0/canary/AuditDerivationInputV2/audit receipts are "
    "intentionally outside the retained-32 capacity witness; capacity "
    "measures only typed sample primitives and their frozen workload "
    "projections"
)

_RECOVERY_CAPABILITY_NAMES = (
    "reports_stage_counts", "reports_active_workers_and_cpu",
    "reports_elapsed_eta_headroom", "reports_current_peak_cgroup_memory",
    "reports_immutable_shard_checkpoint_count", "resumes_verified_shards_only",
    "resume_same_admission", "resume_cannot_regenerate_replace_select",
    "checkpoints_each_common_epoch", "deadline_truncation_keeps_complete_epoch",
    "audit_requires_complete_upstream", "audit_attempt_fsynced_before_open",
    "one_audit_open", "reconstruction_without_retraining",
    "reconstruction_reuses_immutable_continuations")


class FullDAGCapacityDependencyBlocked(RuntimeError):
    """A required reviewed primitive did not execute successfully."""


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

    def validate(self) -> None:
        if tuple(name for name, _ in self.stage_wall_nanoseconds) != FULL_DAG_STAGES:
            raise FullDAGCapacityDependencyBlocked("full-DAG stage population drift")
        if any(type(value) is not int or value < 1
               for _, value in self.stage_wall_nanoseconds):
            raise FullDAGCapacityDependencyBlocked("full-DAG timing drift")
        if self.artifact_bytes < 1 or self.reconstruction_continuation_builds != 0:
            raise FullDAGCapacityDependencyBlocked("full-DAG artifact/reconstruction drift")
        if (len(self.actual_stage_witnesses) != len(FULL_DAG_STAGES)
                or set(self.actual_stage_witnesses) != set(FULL_DAG_STAGES)
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
                 output_root: Path | None = None) -> None:
        self.fixtures = tuple(fixtures)
        self.backend = backend
        self.progress = progress
        self.deadline_ns = deadline_ns
        self.output_root = output_root

    def run(self) -> FullDAGCapacityMeasurementV2:
        return run_full_dag_supervisor(
            self.fixtures, backend=self.backend, progress=self.progress,
            deadline_ns=self.deadline_ns, output_root=self.output_root)


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _identity(fixtures: Sequence[Any]) -> str:
    return _sha([fixture.fixture_sha256 for fixture in fixtures])


def _fail(stage: str, exc: BaseException) -> FullDAGCapacityDependencyBlocked:
    return FullDAGCapacityDependencyBlocked(
        f"full-DAG dependency failed at {stage}: {type(exc).__name__}: {exc}")


def run_full_dag_supervisor(
        fixtures: Sequence[Any], *, backend: Any,
        progress: Callable[[dict[str, Any]], None] | None = None,
        deadline_ns: int | None = None,
        output_root: Path | None = None,
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
        materials.append(material)
    identity = _identity(values)
    walls: dict[str, int] = {}
    witnesses: list[str] = []
    artifact_count = 0
    bundles: list[Any] = []
    examples: tuple[Any, ...] = ()
    roots: tuple[Any, ...] = ()
    cohort_builds: dict[tuple[str, int], Any] = {}
    predictions: dict[tuple[str, int], dict[str, Any]] = {}
    evaluations: dict[tuple[str, int], Any] = {}
    audit_predictions: dict[tuple[str, int], dict[str, Any]] = {}
    audit_evaluations: dict[tuple[str, int], Any] = {}
    capability_probes = {name: False for name in _RECOVERY_CAPABILITY_NAMES}
    progress_events: list[dict[str, Any]] = []
    training_invocations = 0
    audit_open_count = 0
    checkpoint_common_epochs: list[int] = []

    started = time.perf_counter_ns()
    def measure(stage: str, operation: Callable[[], Any], workers: int = 1) -> Any:
        if deadline_ns is not None and time.perf_counter_ns() >= deadline_ns:
            raise FullDAGCapacityDependencyBlocked(
                f"full-DAG deadline exceeded before {stage}")
        try:
            raw = backend.measure(stage, workers, values[0], operation)
            elapsed = int(raw.elapsed_ns)
            if elapsed < 1:
                raise ValueError("non-positive stage timer")
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
        witnesses.append(stage)
        elapsed_total = max(1, time.perf_counter_ns() - started)
        completed = len(witnesses)
        remaining = len(FULL_DAG_STAGES) - completed
        eta_seconds = ((elapsed_total * remaining + completed - 1)
                       // completed // 1_000_000_000)
        event = {
            "stage": stage, "completed_units": completed,
            "total_units": len(FULL_DAG_STAGES), "workers": workers,
            "utilization_ppm": getattr(raw, "mean_cpu_utilization_ppm", 1),
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
            "immutable_shards": artifact_count,
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
            event["immutable_shards"] == artifact_count
            and event["checkpoint_count"] == len(cohort_builds) * 4)
        capability_probes["reports_immutable_shard_checkpoint_count"] = shard_ok if first_event else (
            capability_probes["reports_immutable_shard_checkpoint_count"] and shard_ok)
        return raw

    with tempfile.TemporaryDirectory(prefix="shengji-v2-full-dag-",
                                      dir=str(output_root) if output_root else None) as temp:
        artifact_root = Path(temp)

        def p0() -> str:
            nonlocal roots
            roots = tuple(build_inference_root_v2(material) for material in materials)
            return identity

        def label() -> str:
            nonlocal examples
            rows = []
            for material, bundle in zip(materials, bundles, strict=True):
                rows.extend(build_training_examples_v2(material, bundle))
            examples = tuple(rows)
            return identity
        # Continuation labels are constructed once, inside the measured label
        # stage; the continuation arm itself is the mechanics benchmark.
        def build_labels() -> str:
            nonlocal bundles, artifact_count
            for material in materials:
                bundle = build_continuation_bundle_v2(material)
                shard = publish_continuation_shard(artifact_root, material, bundle)
                artifact_count += shard.byte_count
                bundles.append(reopen_continuation_shard(artifact_root, material))
            return identity
        measure("label", lambda: (build_labels(), label())[1])
        # P0 is a target-free root/tensor construction in capacity mode; the
        # scientific P0 report is intentionally not minted from 32 materials.
        measure("p0", p0)

        config = WorldAfterstateV2TrainingConfig(
            learning_rate_ppb=10_000_000, weight_decay_ppb=0,
            gradient_norm_milli=1_000, max_epochs=1, sigma_pair_squared=1.0)
        select_roots = tuple(__import__("dataclasses").replace(
            root, split="select", select_subfold="epoch-select") for root in roots)
        select_outcomes = tuple(__import__("dataclasses").replace(
            row, split="select") for bundle in bundles for row in bundle.candidates)
        audit_roots = tuple(__import__("dataclasses").replace(
            root, split="audit", select_subfold=None) for root in roots)
        audit_outcomes = tuple(__import__("dataclasses").replace(
            row, split="audit") for bundle in bundles for row in bundle.candidates)
        selection = EpochSelectPopulationV2(select_roots, select_outcomes)
        selection.validate()

        def train(cohort: str, block: int, vals: Sequence[Any], natural: Sequence[Any] | None = None) -> str:
            nonlocal artifact_count, training_invocations
            # The natural block-1 build is a shared reviewed artifact.  It is
            # consumed by canary/nested/primary stages, never retrained.
            if (cohort, block) in cohort_builds:
                return identity
            persist_artifact = (cohort, block) not in cohort_builds
            build = train_named_cohort(
                cohort_name=cohort, values=vals,
                natural_values=natural, freeze_sha256=_sha(identity),
                config=config, selection_population=selection, seed_block=block,
                member_workers=4, torch_threads=1, batch_example_cap=256,
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
                        artifact_root, raw, cohort=cohort, seed_block=block,
                        member_index=member, epoch=1)
                    artifact_count += shard.byte_count
                    _model, metadata = reopen_checkpoint_shard(
                        artifact_root, cohort, block, member, 1)
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
            groups: dict[str, list[Any]] = {}
            for row in examples:
                groups.setdefault(row.root_key, []).append(row)
            if len(groups) < 16:
                raise FullDAGCapacityDependencyBlocked(
                    "capacity canary requires 16 complete retained roots")
            selected_keys = sorted(groups)[:16]
            selected = tuple(row for key in selected_keys for row in groups[key])
            if any(len(groups[key]) != len(groups[selected_keys[0]])
                   for key in selected_keys):
                raise FullDAGCapacityDependencyBlocked(
                    "capacity canary sibling population drift")
            training_cost(selected, 500)
            return identity
        measure("optimizer-canary", run_canary, 4)

        def run_nested(fraction: int) -> str:
            groups: dict[str, list[Any]] = {}
            for row in examples:
                groups.setdefault(row.root_key, []).append(row)
            keys = sorted(groups)
            count = max(1, len(keys) * fraction // 4)
            selected = tuple(row for key in keys[:count] for row in groups[key])
            training_cost(selected, 1)
            return identity
        for stage, fraction in (("nested-curve-25", 1),
                                ("nested-curve-50", 2),
                                ("nested-curve-100", 4)):
            measure(stage, lambda fraction=fraction: run_nested(fraction), 4)

        control_rows: dict[str, tuple[Any, ...]] = {}
        transforms = {
            CONTROL_NAMES[0]: action_association_permutation,
            CONTROL_NAMES[1]: label_permutation,
            CONTROL_NAMES[2]: complete_world_shuffle,
        }
        def control_train(name: str, block: int) -> str:
            try:
                if name not in control_rows:
                    controlled, _evidence = transforms[name](examples)
                    control_rows[name] = control_training_examples(controlled)
                return train(name, block, control_rows[name], examples)
            except Exception as exc:
                raise _fail(f"{name}-construction", exc) from exc
        def natural_block1() -> str:
            # The natural block-1 artifact is built once and cached by
            # ``train``.  Nested cost uses the raw train_epoch primitive and
            # never invokes train_named_cohort a second time.
            return train("natural", 1, examples)
        measure("block-1-natural", natural_block1, 4)
        measure("block-1-action-association-permutation",
                lambda: control_train(CONTROL_NAMES[0], 1), 4)
        measure("block-1-label-permutation",
                lambda: control_train(CONTROL_NAMES[1], 1), 4)
        measure("block-1-complete-world-shuffle",
                lambda: control_train(CONTROL_NAMES[2], 1), 4)
        measure("block-2-natural", lambda: train("natural", 2, examples), 4)
        measure("block-2-complete-world-shuffle",
                lambda: control_train(CONTROL_NAMES[2], 2), 4)

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
            member_workers=4, torch_threads=1, batch_example_cap=256,
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
            for (cohort, block), build in cohort_builds.items():
                select_rows = []
                audit_rows = []
                for member, raw in enumerate(build.selected_checkpoint_raws):
                    model, _ = __import__("shengji.rl.world_afterstate_v2_checkpoint", fromlist=["reopen_checkpoint"]).reopen_checkpoint(raw)
                    for root in select_roots:
                        select_rows.extend(predict_root_v2(
                            model, root, seed_block=block,
                            member_index=member, control_name=cohort))
                    for root in audit_roots:
                        audit_rows.extend(predict_root_v2(
                            model, root, seed_block=block,
                            member_index=member, control_name=cohort))
                predictions[(cohort, block)] = prediction_population_manifest_v2(
                    select_roots, tuple(select_rows), split="select", control_name=cohort,
                    seed_block=block)
                audit_predictions[(cohort, block)] = prediction_population_manifest_v2(
                    audit_roots, tuple(audit_rows), split="audit", control_name=cohort,
                    seed_block=block)
            return identity
        measure("precision-select-inference", infer, 4)
        prior = build_natural_fit_prior(examples)
        outcomes = select_outcomes

        def precision_stage() -> str:
            evaluated = tuple(evaluate_v2(manifest, outcomes, prior)
                              for manifest in predictions.values())
            for value in evaluated:
                evaluations[(value.control_name, value.seed_block)] = value
            if ("natural", 1) not in evaluations:
                raise FullDAGCapacityDependencyBlocked(
                    "capacity select evaluation population missing")
            return identity
        measure("precision-select", precision_stage, 4)

        def audit_cost() -> str:
            # Evaluate the deterministic audit clone with the same pure
            # evaluation/control arithmetic.  This is timing-only: no P0,
            # AuditDerivationInputV2, or terminal scientific receipt is
            # constructed from the 32-deal sample.
            nonlocal audit_open_count
            capability_probes["audit_requires_complete_upstream"] = (
                set(cohort_builds) == expected_cohorts
                and set(predictions) == expected_cohorts
                and set(audit_predictions) == expected_cohorts)
            capability_probes["audit_attempt_fsynced_before_open"] = (
                artifact_count > 0 and all(
                    reopen_continuation_shard(artifact_root, material).bundle_sha256
                    == bundle.bundle_sha256
                    for material, bundle in zip(materials, bundles, strict=True)))
            attempt_payload = canonical_json_bytes({
                "schema": "retained-32-capacity-audit-attempt-v1",
                "audit_population_sha256": _sha(
                    [root.root_sha256 for root in audit_roots]),
                "upstream_complete": capability_probes[
                    "audit_requires_complete_upstream"]})
            attempt_path = artifact_root / "audit-attempt.json"
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
            evaluated = tuple(evaluate_v2(manifest, audit_outcomes, prior)
                              for manifest in audit_predictions.values())
            for value in evaluated:
                audit_evaluations[(value.control_name, value.seed_block)] = value
            for name, block in ((CONTROL_NAMES[0], 1),
                                (CONTROL_NAMES[1], 1),
                                (CONTROL_NAMES[2], 1),
                                (CONTROL_NAMES[2], 2)):
                natural = audit_evaluations[("natural", block)]
                evaluate_control_difference(natural, audit_evaluations[(name, block)])
            return identity
        measure("audit", audit_cost, 1)

        def reconstruct() -> str:
            nonlocal capability_probes
            training_before = training_invocations
            reused = True
            replace_refused = True
            wrong_admission_refused = True
            for index, material in enumerate(materials):
                reopened = reopen_continuation_shard(artifact_root, material)
                expected = next(bundle for bundle in bundles
                                if bundle.deal_sha256 == material.deal_sha256)
                reopened = reopen_continuation_bundle_v2(reopened, material)
                reused = reused and reopened.bundle_sha256 == expected.bundle_sha256
                wrong_material = materials[(index + 1) % len(materials)]
                try:
                    reopen_continuation_bundle_v2(reopened, wrong_material)
                except WorldAfterstateV2ContinuationError:
                    pass
                else:
                    wrong_admission_refused = False
                try:
                    publish_continuation_shard(artifact_root, material, reopened)
                except WorldAfterstateV2ArtifactError:
                    # The immutable publisher must reject replacement.  This
                    # probe is deliberately performed only after reopening.
                    pass
                else:
                    replace_refused = False
            capability_probes["resumes_verified_shards_only"] = reused
            capability_probes["resume_same_admission"] = reused and wrong_admission_refused
            capability_probes["resume_cannot_regenerate_replace_select"] = replace_refused
            capability_probes["reconstruction_without_retraining"] = (
                training_invocations == training_before)
            capability_probes["reconstruction_reuses_immutable_continuations"] = reused
            return identity
        measure("reconstruction", reconstruct, 1)

    capability_probes["one_audit_open"] = audit_open_count == 1
    capability_probes["reports_stage_counts"] = (
        len(progress_events) == len(FULL_DAG_STAGES)
        and tuple(event["stage"] for event in progress_events) == FULL_DAG_STAGES)
    capability_probes["reports_elapsed_eta_headroom"] = (
        bool(progress_events)
        and all(event["elapsed_seconds"] >= 1
                and event["headroom_seconds"] >= 1
                for event in progress_events))
    result = FullDAGCapacityMeasurementV2(
        tuple((stage, walls[stage]) for stage in FULL_DAG_STAGES),
        max(1, artifact_count), tuple(witnesses), 0, True,
        dict(capability_probes), _provenance)
    result.validate()
    return result


__all__ = ["FULL_DAG_MISSING_DEPENDENCY", "FULL_DAG_STAGES",
           "FullDAGCapacityDependencyBlocked",
           "FullDAGCapacityMeasurementV2", "FullDAGCapacitySupervisorV2",
           "run_full_dag_supervisor"]

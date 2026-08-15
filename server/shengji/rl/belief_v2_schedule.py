"""Exact realized cohort populations and round-grouped V2 schedules.

The pre-capture freeze names selection rules because exact decision identities
do not exist until capture.  This module applies those rules once: primary and
negative control share all synthetic work, the human arm replaces an equal
digest-selected synthetic count, and the scale arm consumes its frozen digest
prefix.  Complete selected round groups are never split between batches.

It has no corpus reader, model, optimizer, RNG, result access, or run authority.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .belief_b2_protocol import TRAIN_BATCH_DECISION_CAP
from .belief_contract import canonical_json_bytes
from .belief_v2_freeze import (
    ALL_HUMAN_TRAIN_DECISIONS,
    ALL_SYNTHETIC_TRAIN_DECISIONS,
    CONTROL_COHORT_ID,
    HUMAN_COHORT_ID,
    MAX_HUMAN_FRACTION_DENOMINATOR,
    MAX_HUMAN_FRACTION_NUMERATOR,
    MIXED_WORK_RULE,
    MIXED_SYNTHETIC_TRAIN_DECISIONS,
    NO_HUMAN_DECISIONS,
    PRIMARY_COHORT_ID,
    PRIMARY_WORK_RULE,
    SCALE_WORK_RULE,
    SCALE_SYNTHETIC_TRAIN_DECISIONS,
    V2CohortPlanV1,
)
from .belief_v2_training import V2TrainingExampleV1


ROW_SCHEMA = "belief-v1-v2-realized-training-row-v1"
REALIZATION_SCHEMA = "belief-v1-v2-cohort-realization-v1"
REALIZATION_SET_SCHEMA = "belief-v1-v2-cohort-realization-set-v1"
CALIBRATION_SCHEMA = "belief-v1-v2-common-calibration-schedule-v1"
SCHEDULE_NAMESPACE = "belief-v1-v2-realized-training-schedule-v1"


class BeliefV2ScheduleError(ValueError):
    """A realized population, selection, grouping, or work match drifted."""


def _is_sha256(value: Any) -> bool:
    return type(value) is str and len(value) == 64 \
        and all(char in "0123456789abcdef" for char in value)


def _sha(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _rank(label: str, key: str) -> bytes:
    return hashlib.sha256(
        f"{SCHEDULE_NAMESPACE}|{label}|{key}".encode("ascii")).digest()


@dataclass(frozen=True)
class V2TrainingRowV1:
    decision_key: str
    round_group_key: str
    source_kind: str
    active_label_count: int
    example_sha256: str
    schema: str = ROW_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "decision_key": self.decision_key,
            "round_group_key": self.round_group_key,
            "source_kind": self.source_kind,
            "active_label_count": self.active_label_count,
            "example_sha256": self.example_sha256,
        }


def _example_row(
        example: V2TrainingExampleV1, *, expected_split: str,
        expected_source: str | None = None) -> V2TrainingRowV1:
    if type(example) is not V2TrainingExampleV1 \
            or example.split != expected_split \
            or example.source_kind not in {"synthetic", "human"} \
            or (expected_source is not None
                and example.source_kind != expected_source) \
            or example.privileged_targets_consumed is not True \
            or example.source_identity_model_input is not False \
            or example.runtime_artifact is not False:
        raise BeliefV2ScheduleError("V2 schedule example drift")
    row = V2TrainingRowV1(
        decision_key=example.decision_key,
        round_group_key=example.round_group_key,
        source_kind=example.source_kind,
        active_label_count=int(example.active_mask.sum()),
        example_sha256=_sha({
            "schema": V2_TRAINING_EXAMPLE_IDENTITY_SCHEMA,
            "decision_key": example.decision_key,
            "round_group_key": example.round_group_key,
            "source_kind": example.source_kind,
            "source_actor_sha256": example.source_actor_sha256,
            "common_surface_sha256": example.common_surface_sha256,
            "privileged_target_sha256": example.privileged_target_sha256,
            "active_label_count": int(example.active_mask.sum()),
        }),
    )
    _validate_row(row)
    return row


def training_row(example: V2TrainingExampleV1) -> V2TrainingRowV1:
    return _example_row(example, expected_split="train")


def calibration_row(example: V2TrainingExampleV1) -> V2TrainingRowV1:
    """Bind one synthetic-only common-epoch calibration example."""
    return _example_row(
        example, expected_split="calibration",
        expected_source="synthetic")


V2_TRAINING_EXAMPLE_IDENTITY_SCHEMA = (
    "belief-v1-v2-training-example-identity-v1")


def _validate_row(row: V2TrainingRowV1) -> None:
    if type(row) is not V2TrainingRowV1 or row.schema != ROW_SCHEMA \
            or not _is_sha256(row.decision_key) \
            or not _is_sha256(row.round_group_key) \
            or row.source_kind not in {"synthetic", "human"} \
            or type(row.active_label_count) is not int \
            or row.active_label_count <= 0 \
            or not _is_sha256(row.example_sha256):
        raise BeliefV2ScheduleError("V2 realized training row drift")


def _row_population_sha256(rows: tuple[V2TrainingRowV1, ...]) -> str:
    return _sha({
        "schema": "belief-v1-v2-training-row-population-v1",
        "rows": [row.to_dict() for row in sorted(
            rows, key=lambda value: value.decision_key)],
    })


def _schedule_sha256(batches: tuple[tuple[str, ...], ...]) -> str:
    return _sha({
        "schema": "belief-v1-v2-training-batch-schedule-v1",
        "batch_decision_keys": [list(batch) for batch in batches],
    })


def _schedule(
        rows: tuple[V2TrainingRowV1, ...], *, family: str) \
        -> tuple[tuple[str, ...], ...]:
    groups: dict[str, list[V2TrainingRowV1]] = {}
    for row in rows:
        groups.setdefault(row.round_group_key, []).append(row)
    ordered_groups = sorted(groups.items(), key=lambda item: (
        _rank(f"{family}|round", item[0]), item[0]))
    batches: list[tuple[str, ...]] = []
    pending: list[str] = []
    for _, group_rows in ordered_groups:
        keys = sorted(row.decision_key for row in group_rows)
        if len(keys) > TRAIN_BATCH_DECISION_CAP:
            raise BeliefV2ScheduleError(
                "V2 selected round exceeds batch cap")
        if pending and len(pending) + len(keys) > TRAIN_BATCH_DECISION_CAP:
            batches.append(tuple(pending))
            pending = []
        pending.extend(keys)
    if pending:
        batches.append(tuple(pending))
    if not batches or any(not batch or len(batch) > TRAIN_BATCH_DECISION_CAP
                          for batch in batches):
        raise BeliefV2ScheduleError("V2 realized batch schedule drift")
    return tuple(batches)


@dataclass(frozen=True)
class V2CohortRealizationV1:
    cohort_id: str
    kind: str
    cohort_plan_sha256: str
    comparator_cohort_id: str | None
    rows: tuple[V2TrainingRowV1, ...]
    removed_synthetic_decision_keys: tuple[str, ...]
    batches: tuple[tuple[str, ...], ...]
    synthetic_decision_count: int
    human_decision_count: int
    active_label_count: int
    decision_population_sha256: str
    batch_schedule_sha256: str
    schema: str = REALIZATION_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "cohort_id": self.cohort_id,
            "kind": self.kind,
            "cohort_plan_sha256": self.cohort_plan_sha256,
            "comparator_cohort_id": self.comparator_cohort_id,
            "rows": [row.to_dict() for row in self.rows],
            "removed_synthetic_decision_keys": list(
                self.removed_synthetic_decision_keys),
            "batches": [list(batch) for batch in self.batches],
            "decision_count": len(self.rows),
            "synthetic_decision_count": self.synthetic_decision_count,
            "human_decision_count": self.human_decision_count,
            "active_label_count": self.active_label_count,
            "decision_population_sha256": self.decision_population_sha256,
            "batch_schedule_sha256": self.batch_schedule_sha256,
            "source_identity_model_input": False,
            "result_or_loss_used_for_selection": False,
            "training_authorized": False,
            "test_open_authorized": False,
            "strength_claim_authorized": False,
        }

    def canonical_bytes(self) -> bytes:
        _validate_realization(self)
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def _realization(
        plan: V2CohortPlanV1, rows: tuple[V2TrainingRowV1, ...], *,
        removed: tuple[str, ...], family: str) -> V2CohortRealizationV1:
    ordered = tuple(sorted(rows, key=lambda row: (
        _rank(f"{family}|decision", row.decision_key), row.decision_key)))
    batches = _schedule(ordered, family=family)
    result = V2CohortRealizationV1(
        cohort_id=plan.cohort_id, kind=plan.kind,
        cohort_plan_sha256=_sha(plan.to_dict()),
        comparator_cohort_id=plan.comparator_cohort_id,
        rows=ordered, removed_synthetic_decision_keys=removed,
        batches=batches,
        synthetic_decision_count=sum(
            row.source_kind == "synthetic" for row in ordered),
        human_decision_count=sum(
            row.source_kind == "human" for row in ordered),
        active_label_count=sum(row.active_label_count for row in ordered),
        decision_population_sha256=_row_population_sha256(ordered),
        batch_schedule_sha256=_schedule_sha256(batches),
    )
    _validate_realization(result)
    return result


def _validate_realization(value: V2CohortRealizationV1) -> None:
    flattened = tuple(key for batch in value.batches for key in batch) \
        if type(value) is V2CohortRealizationV1 \
        and type(value.batches) is tuple else ()
    if type(value) is not V2CohortRealizationV1 \
            or value.schema != REALIZATION_SCHEMA \
            or type(value.cohort_id) is not str or not value.cohort_id \
            or type(value.kind) is not str or not value.kind \
            or not _is_sha256(value.cohort_plan_sha256) \
            or not (value.comparator_cohort_id is None
                    or (type(value.comparator_cohort_id) is str
                        and bool(value.comparator_cohort_id))) \
            or type(value.rows) is not tuple or not value.rows \
            or any(_validate_row_return(row) is False for row in value.rows) \
            or len({row.decision_key for row in value.rows}) \
            != len(value.rows) \
            or type(value.removed_synthetic_decision_keys) is not tuple \
            or any(not _is_sha256(key)
                   for key in value.removed_synthetic_decision_keys) \
            or len(set(value.removed_synthetic_decision_keys)) \
            != len(value.removed_synthetic_decision_keys) \
            or type(value.batches) is not tuple or not value.batches \
            or len(flattened) != len(set(flattened)) \
            or set(flattened) \
            != {row.decision_key for row in value.rows} \
            or sum(len(batch) for batch in value.batches) != len(value.rows) \
            or any(type(batch) is not tuple or not batch
                   or len(batch) > TRAIN_BATCH_DECISION_CAP
                   for batch in value.batches) \
            or value.synthetic_decision_count \
            != sum(row.source_kind == "synthetic" for row in value.rows) \
            or value.human_decision_count \
            != sum(row.source_kind == "human" for row in value.rows) \
            or value.active_label_count \
            != sum(row.active_label_count for row in value.rows) \
            or value.decision_population_sha256 \
            != _row_population_sha256(value.rows) \
            or value.batch_schedule_sha256 != _schedule_sha256(value.batches):
        raise BeliefV2ScheduleError("V2 cohort realization drift")


def _validate_row_return(row: V2TrainingRowV1) -> bool:
    _validate_row(row)
    return True


@dataclass(frozen=True)
class V2CalibrationScheduleV1:
    rows: tuple[V2TrainingRowV1, ...]
    batches: tuple[tuple[str, ...], ...]
    decision_population_sha256: str
    batch_schedule_sha256: str
    schema: str = CALIBRATION_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "selection_role": "common-epoch-only",
            "source_kind": "synthetic",
            "rows": [row.to_dict() for row in self.rows],
            "batches": [list(batch) for batch in self.batches],
            "decision_count": len(self.rows),
            "decision_population_sha256": self.decision_population_sha256,
            "batch_schedule_sha256": self.batch_schedule_sha256,
            "human_calibration_consumed": False,
            "test_open_authorized": False,
            "strength_claim_authorized": False,
        }

    def canonical_bytes(self) -> bytes:
        _validate_calibration_schedule(self)
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def _validate_calibration_schedule(
        value: V2CalibrationScheduleV1) -> None:
    flattened = tuple(key for batch in value.batches for key in batch) \
        if type(value) is V2CalibrationScheduleV1 \
        and type(value.batches) is tuple else ()
    if type(value) is not V2CalibrationScheduleV1 \
            or value.schema != CALIBRATION_SCHEMA \
            or type(value.rows) is not tuple or not value.rows \
            or any(_validate_row_return(row) is False for row in value.rows) \
            or any(row.source_kind != "synthetic" for row in value.rows) \
            or len({row.decision_key for row in value.rows}) \
            != len(value.rows) \
            or type(value.batches) is not tuple or not value.batches \
            or any(type(batch) is not tuple or not batch
                   or len(batch) > TRAIN_BATCH_DECISION_CAP
                   for batch in value.batches) \
            or len(flattened) != len(set(flattened)) \
            or set(flattened) != {row.decision_key for row in value.rows} \
            or value.decision_population_sha256 \
            != _row_population_sha256(value.rows) \
            or value.batch_schedule_sha256 != _schedule_sha256(value.batches):
        raise BeliefV2ScheduleError(
            "V2 common calibration schedule drift")


def realize_v2_common_calibration(
        examples: tuple[V2TrainingExampleV1, ...]) \
        -> V2CalibrationScheduleV1:
    """Freeze one synthetic calibration schedule shared by every cohort."""
    if type(examples) is not tuple or not examples:
        raise BeliefV2ScheduleError(
            "V2 common calibration population is empty")
    rows = tuple(calibration_row(example) for example in examples)
    if len({row.decision_key for row in rows}) != len(rows):
        raise BeliefV2ScheduleError(
            "V2 common calibration decision duplicate")
    ordered = tuple(sorted(rows, key=lambda row: (
        _rank("common-synthetic-calibration|decision", row.decision_key),
        row.decision_key)))
    batches = _schedule(
        ordered, family="common-synthetic-calibration")
    result = V2CalibrationScheduleV1(
        rows=ordered, batches=batches,
        decision_population_sha256=_row_population_sha256(ordered),
        batch_schedule_sha256=_schedule_sha256(batches))
    _validate_calibration_schedule(result)
    return result


def validate_v2_common_calibration(
        examples: tuple[V2TrainingExampleV1, ...],
        candidate: V2CalibrationScheduleV1) -> None:
    expected = realize_v2_common_calibration(examples)
    try:
        candidate_raw = candidate.canonical_bytes()
    except (AttributeError, BeliefV2ScheduleError) as exc:
        raise BeliefV2ScheduleError(
            "V2 common calibration schedule reconstruction drift") from exc
    if type(candidate) is not V2CalibrationScheduleV1 \
            or candidate_raw != expected.canonical_bytes():
        raise BeliefV2ScheduleError(
            "V2 common calibration schedule reconstruction drift")


def realize_v2_cohorts(
        plans: tuple[V2CohortPlanV1, ...], *,
        synthetic_rows: tuple[V2TrainingRowV1, ...],
        human_rows: tuple[V2TrainingRowV1, ...]) \
        -> tuple[V2CohortRealizationV1, ...]:
    """Apply every frozen selection rule and cross-check exact work matching."""
    if type(plans) is not tuple or len(plans) < 4 \
            or any(type(plan) is not V2CohortPlanV1 for plan in plans) \
            or {plan.kind for plan in plans} != {
                "synthetic-primary", "hard-geometry-label-permutation",
                "human-mixture", "synthetic-scale"} \
            or sum(plan.kind == "synthetic-primary" for plan in plans) != 1 \
            or sum(plan.kind == "hard-geometry-label-permutation"
                   for plan in plans) != 1 \
            or sum(plan.kind == "human-mixture" for plan in plans) != 1 \
            or len({plan.cohort_id for plan in plans}) != len(plans):
        raise BeliefV2ScheduleError("V2 cohort plan population drift")
    if type(synthetic_rows) is not tuple or not synthetic_rows \
            or type(human_rows) is not tuple or not human_rows:
        raise BeliefV2ScheduleError("V2 source population is empty")
    for row in (*synthetic_rows, *human_rows):
        _validate_row(row)
    if any(row.source_kind != "synthetic" for row in synthetic_rows) \
            or any(row.source_kind != "human" for row in human_rows) \
            or len({row.decision_key
                    for row in (*synthetic_rows, *human_rows)}) \
            != len(synthetic_rows) + len(human_rows):
        raise BeliefV2ScheduleError("V2 source population identity drift")
    if len(human_rows) > len(synthetic_rows) \
            or len(human_rows) * MAX_HUMAN_FRACTION_DENOMINATOR \
            > len(synthetic_rows) * MAX_HUMAN_FRACTION_NUMERATOR:
        raise BeliefV2ScheduleError("V2 human mixture fraction exceeds cap")
    primary_plan = next(plan for plan in plans
                        if plan.kind == "synthetic-primary")
    control_plan = next(plan for plan in plans
                        if plan.kind == "hard-geometry-label-permutation")
    human_plan = next(plan for plan in plans
                      if plan.kind == "human-mixture")
    scale_plans = tuple(plan for plan in plans
                        if plan.kind == "synthetic-scale")
    if len({(plan.synthetic_fraction_numerator,
             plan.synthetic_fraction_denominator)
            for plan in scale_plans}) != len(scale_plans):
        raise BeliefV2ScheduleError("V2 scale fraction population drift")
    if primary_plan.cohort_id != PRIMARY_COHORT_ID \
            or control_plan.cohort_id != CONTROL_COHORT_ID \
            or human_plan.cohort_id != HUMAN_COHORT_ID \
            or primary_plan.synthetic_selection_rule \
            != ALL_SYNTHETIC_TRAIN_DECISIONS \
            or control_plan.synthetic_selection_rule \
            != ALL_SYNTHETIC_TRAIN_DECISIONS \
            or human_plan.synthetic_selection_rule \
            != MIXED_SYNTHETIC_TRAIN_DECISIONS \
            or primary_plan.human_selection_rule != NO_HUMAN_DECISIONS \
            or control_plan.human_selection_rule != NO_HUMAN_DECISIONS \
            or human_plan.human_selection_rule \
            != ALL_HUMAN_TRAIN_DECISIONS \
            or primary_plan.work_match_rule != PRIMARY_WORK_RULE \
            or control_plan.work_match_rule != PRIMARY_WORK_RULE \
            or human_plan.work_match_rule != MIXED_WORK_RULE \
            or primary_plan.comparator_cohort_id is not None \
            or control_plan.comparator_cohort_id != PRIMARY_COHORT_ID \
            or human_plan.comparator_cohort_id != PRIMARY_COHORT_ID \
            or any(scale.synthetic_selection_rule
                   != SCALE_SYNTHETIC_TRAIN_DECISIONS
                   or scale.human_selection_rule != NO_HUMAN_DECISIONS
                   or scale.work_match_rule != SCALE_WORK_RULE
                   or scale.comparator_cohort_id != PRIMARY_COHORT_ID
                   for scale in scale_plans):
        raise BeliefV2ScheduleError("V2 cohort selection rule drift")
    ranked_synthetic = tuple(sorted(
        synthetic_rows,
        key=lambda row: (_rank("mixed-removal", row.decision_key),
                         row.decision_key)))
    removed_rows = ranked_synthetic[:len(human_rows)]
    removed_keys = tuple(row.decision_key for row in removed_rows)
    removed_set = set(removed_keys)
    mixed_synthetic = tuple(
        row for row in synthetic_rows if row.decision_key not in removed_set)
    ranked_scale_rows = tuple(sorted(
        synthetic_rows,
        key=lambda row: (_rank("scale-prefix", row.decision_key),
                         row.decision_key)))
    primary = _realization(
        primary_plan, synthetic_rows, removed=(), family="primary")
    control = _realization(
        control_plan, synthetic_rows, removed=(), family="primary")
    mixed = _realization(
        human_plan, (*mixed_synthetic, *human_rows),
        removed=removed_keys, family="human-mixture")
    scales = tuple(_realization(
        scale, ranked_scale_rows[:(
            len(synthetic_rows) * scale.synthetic_fraction_numerator
            // scale.synthetic_fraction_denominator)],
        removed=(), family=f"synthetic-scale|{scale.cohort_id}")
                   for scale in scale_plans)
    if control.decision_population_sha256 \
            != primary.decision_population_sha256 \
            or control.batch_schedule_sha256 != primary.batch_schedule_sha256 \
            or len(mixed.rows) != len(primary.rows) \
            or mixed.human_decision_count != len(human_rows) \
            or mixed.synthetic_decision_count \
            != len(synthetic_rows) - len(human_rows) \
            or any(value.synthetic_decision_count != (
                len(synthetic_rows) * plan.synthetic_fraction_numerator
                // plan.synthetic_fraction_denominator)
                   or value.human_decision_count != 0
                   for plan, value in zip(scale_plans, scales, strict=True)):
        raise BeliefV2ScheduleError("V2 realized comparison/work drift")
    realized = (primary, control, mixed, *scales)
    return tuple(
        {value.cohort_id: value
         for value in realized}[plan.cohort_id]
        for plan in plans)


def validate_v2_cohort_realizations(
        plans: tuple[V2CohortPlanV1, ...], *,
        synthetic_rows: tuple[V2TrainingRowV1, ...],
        human_rows: tuple[V2TrainingRowV1, ...],
        candidates: tuple[V2CohortRealizationV1, ...]) -> None:
    """Independently rederive every population, removal, and batch byte."""
    if type(candidates) is not tuple or len(candidates) != len(plans) \
            or any(type(value) is not V2CohortRealizationV1
                   for value in candidates):
        raise BeliefV2ScheduleError(
            "V2 cohort realization population drift")
    expected = realize_v2_cohorts(
        plans, synthetic_rows=synthetic_rows, human_rows=human_rows)
    if tuple(value.canonical_bytes() for value in candidates) \
            != tuple(value.canonical_bytes() for value in expected):
        raise BeliefV2ScheduleError(
            "V2 cohort realization reconstruction drift")


def realization_set_sha256(
        candidates: tuple[V2CohortRealizationV1, ...]) -> str:
    if type(candidates) is not tuple or not candidates \
            or any(type(value) is not V2CohortRealizationV1
                   for value in candidates) \
            or len({value.cohort_id for value in candidates}) \
            != len(candidates):
        raise BeliefV2ScheduleError(
            "V2 cohort realization set drift")
    return _sha({
        "schema": REALIZATION_SET_SCHEMA,
        "cohorts": [
            {"cohort_id": value.cohort_id, "sha256": value.sha256()}
            for value in candidates
        ],
        "training_authorized": False,
        "test_open_authorized": False,
        "strength_claim_authorized": False,
    })

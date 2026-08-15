"""Closed split-safe training-input population for BELIEF-V1 V2.

This module is the one bridge from durable capture artifacts to realized
cohort schedules.  It opens synthetic and historical-human train targets,
opens only synthetic calibration targets for the common epoch rule, and
authenticates—but never reads—every test target file.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .belief_contract import canonical_json_bytes
from .belief_v2_controller import reopen_synthetic_training_lane_examples
from .belief_v2_freeze import (
    V2CohortPlanV1,
    V2ExecutionFreezeV1,
    V2PipelineAdmissionV1,
    validate_execution_freeze,
)
from .belief_v2_human_controller import (
    _bind_h0_receipts,
    reopen_human_group_manifest,
    reopen_human_training_group_examples,
)
from .belief_v2_protocol import V2_CAPTURE_LANES
from .belief_v2_schedule import (
    V2CalibrationScheduleV1,
    V2CohortRealizationV1,
    realization_set_sha256,
    realize_v2_cohorts,
    realize_v2_common_calibration,
    training_row,
)
from .belief_v2_training import V2TrainingExampleV1


TRAINING_INPUT_SCHEMA = "belief-v1-v2-training-input-population-v1"


class BeliefV2TrainingInputError(ValueError):
    """A split, source population, decision identity, or schedule drifted."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _example_population_sha256(
        examples: tuple[V2TrainingExampleV1, ...], *, label: str) -> str:
    rows = tuple(training_row(example) if example.split == "train"
                 else None for example in examples)
    if any(row is None for row in rows):
        # Calibration examples are bound by their common schedule instead.
        raise BeliefV2TrainingInputError(
            f"V2 {label} example population split drift")
    return _sha256(canonical_json_bytes({
        "schema": "belief-v1-v2-training-input-example-population-v1",
        "label": label,
        "rows": [row.to_dict() for row in sorted(
            rows, key=lambda value: value.decision_key)],
    }))


@dataclass(frozen=True)
class V2TrainingInputPopulationV1:
    synthetic_train_examples: tuple[V2TrainingExampleV1, ...]
    synthetic_calibration_examples: tuple[V2TrainingExampleV1, ...]
    human_train_examples: tuple[V2TrainingExampleV1, ...]
    cohort_plans: tuple[V2CohortPlanV1, ...]
    realizations: tuple[V2CohortRealizationV1, ...]
    common_calibration: V2CalibrationScheduleV1
    human_group_manifest_sha256s: tuple[str, ...]
    schema: str = TRAINING_INPUT_SCHEMA

    def manifest(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "synthetic_train_decision_count": len(
                self.synthetic_train_examples),
            "synthetic_train_population_sha256": (
                _example_population_sha256(
                    self.synthetic_train_examples,
                    label="synthetic-train")),
            "synthetic_calibration_decision_count": len(
                self.synthetic_calibration_examples),
            "common_calibration_sha256": self.common_calibration.sha256(),
            "human_train_decision_count": len(self.human_train_examples),
            "human_train_population_sha256": _example_population_sha256(
                self.human_train_examples, label="human-train"),
            "human_group_manifest_sha256s": list(
                self.human_group_manifest_sha256s),
            "cohort_plan_set_sha256": _sha256(canonical_json_bytes({
                "schema": "belief-v1-v2-cohort-plan-set-v1",
                "plans": [plan.to_dict() for plan in self.cohort_plans],
            })),
            "cohort_realization_set_sha256": realization_set_sha256(
                self.realizations),
            "cohorts": [{
                "cohort_id": realization.cohort_id,
                "kind": realization.kind,
                "realization_sha256": realization.sha256(),
                "decision_count": len(realization.rows),
                "synthetic_decision_count": (
                    realization.synthetic_decision_count),
                "human_decision_count": realization.human_decision_count,
            } for realization in self.realizations],
            "common_model_surface": True,
            "source_identity_model_input": False,
            "human_calibration_consumed_for_common_epoch": False,
            "synthetic_test_targets_opened": False,
            "human_test_targets_opened": False,
            "test_split_open_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        }

    def canonical_bytes(self) -> bytes:
        validate_v2_training_inputs(self)
        return canonical_json_bytes(self.manifest())

    def sha256(self) -> str:
        return _sha256(self.canonical_bytes())


def build_v2_training_inputs(
        freeze: V2ExecutionFreezeV1, *,
        synthetic_train_examples: tuple[V2TrainingExampleV1, ...],
        synthetic_calibration_examples: tuple[V2TrainingExampleV1, ...],
        human_train_examples: tuple[V2TrainingExampleV1, ...],
        human_group_manifest_sha256s: tuple[str, ...]) \
        -> V2TrainingInputPopulationV1:
    """Realize every frozen cohort from one exact source population."""
    try:
        validate_execution_freeze(freeze)
    except ValueError as exc:
        raise BeliefV2TrainingInputError(
            "V2 training input freeze refused") from exc
    if type(synthetic_train_examples) is not tuple \
            or not synthetic_train_examples \
            or type(synthetic_calibration_examples) is not tuple \
            or not synthetic_calibration_examples \
            or type(human_train_examples) is not tuple \
            or not human_train_examples \
            or any(type(example) is not V2TrainingExampleV1
                   or example.split != "train"
                   or example.source_kind != "synthetic"
                   for example in synthetic_train_examples) \
            or any(type(example) is not V2TrainingExampleV1
                   or example.split != "calibration"
                   or example.source_kind != "synthetic"
                   for example in synthetic_calibration_examples) \
            or any(type(example) is not V2TrainingExampleV1
                   or example.split != "train"
                   or example.source_kind != "human"
                   for example in human_train_examples) \
            or len(human_train_examples) \
            != freeze.human_train_eligible_decision_count \
            or type(human_group_manifest_sha256s) is not tuple \
            or len(human_group_manifest_sha256s) \
            != freeze.human_group_count \
            or len(set(human_group_manifest_sha256s)) \
            != len(human_group_manifest_sha256s) \
            or any(type(value) is not str or len(value) != 64
                   or any(char not in "0123456789abcdef" for char in value)
                   for value in human_group_manifest_sha256s):
        raise BeliefV2TrainingInputError(
            "V2 training source population drift")
    keys = tuple(example.decision_key for example in (
        *synthetic_train_examples, *synthetic_calibration_examples,
        *human_train_examples))
    if len(keys) != len(set(keys)):
        raise BeliefV2TrainingInputError(
            "V2 training/calibration decision population overlaps")
    try:
        realizations = realize_v2_cohorts(
            freeze.cohorts,
            synthetic_rows=tuple(training_row(example)
                                 for example in synthetic_train_examples),
            human_rows=tuple(training_row(example)
                             for example in human_train_examples))
        common = realize_v2_common_calibration(
            synthetic_calibration_examples)
    except ValueError as exc:
        raise BeliefV2TrainingInputError(
            "V2 training schedule realization refused") from exc
    result = V2TrainingInputPopulationV1(
        synthetic_train_examples=synthetic_train_examples,
        synthetic_calibration_examples=synthetic_calibration_examples,
        human_train_examples=human_train_examples,
        cohort_plans=freeze.cohorts,
        realizations=realizations, common_calibration=common,
        human_group_manifest_sha256s=tuple(sorted(
            human_group_manifest_sha256s)))
    validate_v2_training_inputs(result)
    return result


def validate_v2_training_inputs(value: V2TrainingInputPopulationV1) -> None:
    if type(value) is not V2TrainingInputPopulationV1 \
            or value.schema != TRAINING_INPUT_SCHEMA \
            or type(value.synthetic_train_examples) is not tuple \
            or not value.synthetic_train_examples \
            or any(type(example) is not V2TrainingExampleV1
                   or example.split != "train"
                   or example.source_kind != "synthetic"
                   for example in value.synthetic_train_examples) \
            or type(value.synthetic_calibration_examples) is not tuple \
            or not value.synthetic_calibration_examples \
            or any(type(example) is not V2TrainingExampleV1
                   or example.split != "calibration"
                   or example.source_kind != "synthetic"
                   for example in value.synthetic_calibration_examples) \
            or type(value.human_train_examples) is not tuple \
            or not value.human_train_examples \
            or any(type(example) is not V2TrainingExampleV1
                   or example.split != "train"
                   or example.source_kind != "human"
                   for example in value.human_train_examples) \
            or type(value.cohort_plans) is not tuple \
            or not value.cohort_plans \
            or any(type(plan) is not V2CohortPlanV1
                   for plan in value.cohort_plans) \
            or type(value.human_group_manifest_sha256s) is not tuple \
            or not value.human_group_manifest_sha256s \
            or tuple(sorted(value.human_group_manifest_sha256s)) \
            != value.human_group_manifest_sha256s \
            or len(set(value.human_group_manifest_sha256s)) \
            != len(value.human_group_manifest_sha256s):
        raise BeliefV2TrainingInputError(
            "V2 training input artifact identity drift")
    if any(type(digest) is not str or len(digest) != 64
           or any(char not in "0123456789abcdef" for char in digest)
           for digest in value.human_group_manifest_sha256s):
        raise BeliefV2TrainingInputError(
            "V2 training input artifact identity drift")
    keys = tuple(example.decision_key for example in (
        *value.synthetic_train_examples,
        *value.synthetic_calibration_examples,
        *value.human_train_examples))
    if len(keys) != len(set(keys)):
        raise BeliefV2TrainingInputError(
            "V2 training input decision population overlaps")
    try:
        expected_common = realize_v2_common_calibration(
            value.synthetic_calibration_examples)
        expected_realizations = realize_v2_cohorts(
            value.cohort_plans,
            synthetic_rows=tuple(training_row(example)
                                 for example
                                 in value.synthetic_train_examples),
            human_rows=tuple(training_row(example)
                             for example in value.human_train_examples))
    except ValueError as exc:
        raise BeliefV2TrainingInputError(
            "V2 training input schedule reconstruction refused") from exc
    if value.common_calibration.canonical_bytes() \
            != expected_common.canonical_bytes() \
            or type(value.realizations) is not tuple \
            or not value.realizations \
            or any(type(row) is not V2CohortRealizationV1
                   for row in value.realizations) \
            or len({row.cohort_id for row in value.realizations}) \
            != len(value.realizations) \
            or expected_realizations != value.realizations \
            or tuple(row.canonical_bytes() for row in expected_realizations) \
            != tuple(row.canonical_bytes() for row in value.realizations):
        raise BeliefV2TrainingInputError(
            "V2 training input artifact reconstruction drift")
    # Recompute every manifest field, including row and realization digests.
    payload = value.manifest()
    if payload["synthetic_train_decision_count"] <= 0 \
            or payload["synthetic_calibration_decision_count"] <= 0 \
            or payload["human_train_decision_count"] <= 0 \
            or any(payload[key] is not False for key in (
                "source_identity_model_input",
                "human_calibration_consumed_for_common_epoch",
                "synthetic_test_targets_opened", "human_test_targets_opened",
                "test_split_open_authorized", "strength_claim_authorized",
                "deployment_authorized")) \
            or payload["common_model_surface"] is not True:
        raise BeliefV2TrainingInputError(
            "V2 training input authority drift")


def reopen_v2_training_inputs(
        root: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        inventory: dict[str, Any], group_split: dict[str, Any]) \
        -> V2TrainingInputPopulationV1:
    """Reopen all non-test inputs while authenticating the full population."""
    if not isinstance(root, Path):
        raise BeliefV2TrainingInputError("V2 evidence root type drift")
    _bind_h0_receipts(freeze, inventory, group_split)
    capture = root / "capture"
    expected_lanes = {f"lane-{lane:02d}" for lane in range(V2_CAPTURE_LANES)}
    if root != Path(freeze.evidence_root) or root.is_symlink() \
            or not root.is_dir() or capture.is_symlink() \
            or not capture.is_dir() \
            or {path.name for path in capture.iterdir()} != expected_lanes:
        raise BeliefV2TrainingInputError(
            "V2 synthetic capture population drift")
    synthetic_train = []
    synthetic_calibration = []
    for lane in range(V2_CAPTURE_LANES):
        directory = capture / f"lane-{lane:02d}"
        synthetic_train.extend(reopen_synthetic_training_lane_examples(
            directory, freeze=freeze, admission=admission,
            lane=lane, split="train"))
        synthetic_calibration.extend(
            reopen_synthetic_training_lane_examples(
                directory, freeze=freeze, admission=admission,
                lane=lane, split="calibration"))

    human_root = root / "human-capture"
    expected_group_digests = {
        digest for row in group_split["splits"].values()
        for digest in row["group_digests"]}
    expected_groups = {f"group-{digest}" for digest in expected_group_digests}
    if human_root.is_symlink() or not human_root.is_dir() \
            or {path.name for path in human_root.iterdir()} != expected_groups:
        raise BeliefV2TrainingInputError(
            "V2 human capture group population drift")
    human_train = []
    group_manifest_hashes = []
    split_groups = {"train": 0, "calibration": 0, "test": 0}
    split_decisions = {"train": 0, "calibration": 0, "test": 0}
    for digest in sorted(expected_group_digests):
        directory = human_root / f"group-{digest}"
        manifest = reopen_human_group_manifest(
            directory, freeze=freeze, admission=admission)
        if manifest["group_digest"] != digest:
            raise BeliefV2TrainingInputError(
                "V2 human capture digest/directory drift")
        split = manifest["split"]
        if digest not in group_split["splits"][split]["group_digests"]:
            raise BeliefV2TrainingInputError(
                "V2 human capture split receipt drift")
        split_groups[split] += 1
        split_decisions[split] += manifest["human_decision_count"]
        group_manifest_hashes.append(_sha256(canonical_json_bytes(manifest)))
        if split == "train":
            human_train.extend(reopen_human_training_group_examples(
                directory, freeze=freeze, admission=admission,
                split="train"))
    if split_groups != {
            "train": freeze.human_train_group_count,
            "calibration": freeze.human_calibration_group_count,
            "test": freeze.human_test_group_count} \
            or split_decisions != {
                "train": freeze.human_train_eligible_decision_count,
                "calibration": freeze.human_calibration_eligible_decision_count,
                "test": freeze.human_test_eligible_decision_count}:
        raise BeliefV2TrainingInputError(
            "V2 human capture split accounting drift")
    return build_v2_training_inputs(
        freeze,
        synthetic_train_examples=tuple(synthetic_train),
        synthetic_calibration_examples=tuple(synthetic_calibration),
        human_train_examples=tuple(human_train),
        human_group_manifest_sha256s=tuple(group_manifest_hashes))

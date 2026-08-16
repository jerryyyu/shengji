"""Memory-bounded reconstruction of BELIEF-V1 V2 training identities.

The old V2 bridge retained every per-decision array and then every padded
Torch batch.  At the frozen 13,312-round scale that exceeds the target host's
physical memory.  This bridge scans one authenticated complete round at a time,
keeps only compact schedule rows and durable source locators, and supplies a
loader that reopens one named round group for the bounded batch iterator.

The scan opens train and calibration targets but authenticates test files by
shape/hash metadata only.  It grants no training, test, gameplay, or strength
authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .belief_artifacts import stable_read_bytes
from .belief_contract import canonical_json_bytes
from .belief_v2_controller import (
    _reopen_synthetic_training_round_examples,
    iter_synthetic_training_lane_round_examples,
    reopen_actor_capture_lane_manifest,
)
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
from .belief_v2_protocol import V2_CAPTURE_LANES, v2_lane_coordinates
from .belief_v2_schedule import (
    V2CalibrationScheduleV1,
    V2CohortRealizationV1,
    calibration_row,
    realize_v2_cohorts,
    realize_v2_common_calibration_rows,
    realization_set_sha256,
    training_row,
)
from .belief_v2_streaming_training import (
    V2StreamingSourceV1,
    V2StreamingTrainingIndexV1,
    validate_streaming_training_index,
)
from .belief_v2_training import (
    V2TrainingExampleV1,
    build_human_training_example,
    collate_v2_label_control_examples,
)


STREAMING_INPUT_SCHEMA = "belief-v1-v2-streaming-training-inputs-v1"
STREAMING_INPUT_ARTIFACT_SCHEMA = (
    "belief-v1-v2-streaming-training-input-artifact-v1")


class BeliefV2StreamingInputError(ValueError):
    """A compact population, locator, or reopened round drifted."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _rows_sha256(label: str, rows) -> str:
    return _sha256(canonical_json_bytes({
        "schema": "belief-v1-v2-streaming-row-population-v1",
        "label": label,
        "rows": [row.to_dict() for row in sorted(
            rows, key=lambda value: value.decision_key)],
    }))


def _sources_sha256(sources: tuple[V2StreamingSourceV1, ...]) -> str:
    return _sha256(canonical_json_bytes({
        "schema": "belief-v1-v2-streaming-source-population-v1",
        "sources": [{
            "round_group_key": row.round_group_key,
            "split": row.split,
            "source_kind": row.source_kind,
            "source_token": row.source_token,
        } for row in sorted(sources, key=lambda value: (
            value.round_group_key, value.source_token))],
    }))


@dataclass(frozen=True)
class V2StreamingTrainingInputsV1:
    index: V2StreamingTrainingIndexV1
    cohort_plans: tuple[V2CohortPlanV1, ...]
    realizations: tuple[V2CohortRealizationV1, ...]
    common_calibration: V2CalibrationScheduleV1
    human_group_manifest_sha256s: tuple[str, ...]
    schema: str = STREAMING_INPUT_SCHEMA

    def manifest(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "synthetic_train_decision_count": sum(
                row.source_kind == "synthetic"
                for row in self.index.train_rows),
            "synthetic_train_population_sha256": _rows_sha256(
                "synthetic-train", tuple(row for row in self.index.train_rows
                                         if row.source_kind == "synthetic")),
            "synthetic_calibration_decision_count": len(
                self.index.calibration_rows),
            "synthetic_calibration_population_sha256": _rows_sha256(
                "synthetic-calibration", self.index.calibration_rows),
            "human_train_decision_count": sum(
                row.source_kind == "human" for row in self.index.train_rows),
            "human_train_population_sha256": _rows_sha256(
                "human-train", tuple(row for row in self.index.train_rows
                                     if row.source_kind == "human")),
            "source_population_sha256": _sources_sha256(
                self.index.sources),
            "control_changed_cell_count": (
                self.index.control_changed_cell_count),
            "common_calibration_sha256": self.common_calibration.sha256(),
            "human_group_manifest_sha256s": list(
                self.human_group_manifest_sha256s),
            "cohort_plan_set_sha256": _sha256(canonical_json_bytes({
                "schema": "belief-v1-v2-cohort-plan-set-v1",
                "plans": [row.to_dict() for row in self.cohort_plans],
            })),
            "cohort_realization_set_sha256": realization_set_sha256(
                self.realizations),
            "cohorts": [{
                "cohort_id": row.cohort_id,
                "kind": row.kind,
                "realization_sha256": row.sha256(),
                "decision_count": len(row.rows),
                "active_label_count": row.active_label_count,
            } for row in self.realizations],
            "resident_model_array_bytes": 0,
            "one_batch_at_a_time": True,
            "synthetic_test_targets_opened": False,
            "human_test_targets_opened": False,
            "training_authorized_by_this_artifact": False,
            "test_split_open_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        }

    def canonical_bytes(self) -> bytes:
        validate_streaming_training_inputs(self)
        return canonical_json_bytes(self.manifest())

    def sha256(self) -> str:
        return _sha256(self.canonical_bytes())


def build_streaming_training_inputs(
        freeze: V2ExecutionFreezeV1, *,
        train_rows, calibration_rows,
        sources: tuple[V2StreamingSourceV1, ...],
        control_changed_cell_count: int,
        human_group_manifest_sha256s: tuple[str, ...]) \
        -> V2StreamingTrainingInputsV1:
    try:
        validate_execution_freeze(freeze)
        index = V2StreamingTrainingIndexV1(
            train_rows=tuple(train_rows),
            calibration_rows=tuple(calibration_rows), sources=sources,
            control_changed_cell_count=control_changed_cell_count)
        validate_streaming_training_index(index)
        synthetic = tuple(row for row in index.train_rows
                          if row.source_kind == "synthetic")
        human = tuple(row for row in index.train_rows
                      if row.source_kind == "human")
        realizations = realize_v2_cohorts(
            freeze.cohorts, synthetic_rows=synthetic, human_rows=human)
        common = realize_v2_common_calibration_rows(
            index.calibration_rows)
    except ValueError as exc:
        raise BeliefV2StreamingInputError(
            "V2 streaming input construction refused") from exc
    result = V2StreamingTrainingInputsV1(
        index=index, cohort_plans=freeze.cohorts,
        realizations=realizations, common_calibration=common,
        human_group_manifest_sha256s=tuple(sorted(
            human_group_manifest_sha256s)))
    validate_streaming_training_inputs(result)
    return result


def validate_streaming_training_inputs(
        value: V2StreamingTrainingInputsV1) -> None:
    if type(value) is not V2StreamingTrainingInputsV1 \
            or value.schema != STREAMING_INPUT_SCHEMA \
            or type(value.cohort_plans) is not tuple \
            or not value.cohort_plans \
            or type(value.realizations) is not tuple \
            or not value.realizations \
            or type(value.human_group_manifest_sha256s) is not tuple \
            or not value.human_group_manifest_sha256s \
            or tuple(sorted(value.human_group_manifest_sha256s)) \
            != value.human_group_manifest_sha256s \
            or len(set(value.human_group_manifest_sha256s)) \
            != len(value.human_group_manifest_sha256s):
        raise BeliefV2StreamingInputError(
            "V2 streaming input identity drift")
    try:
        validate_streaming_training_index(value.index)
        expected = realize_v2_cohorts(
            value.cohort_plans,
            synthetic_rows=tuple(
                row for row in value.index.train_rows
                if row.source_kind == "synthetic"),
            human_rows=tuple(
                row for row in value.index.train_rows
                if row.source_kind == "human"))
        expected_common = realize_v2_common_calibration_rows(
            value.index.calibration_rows)
    except ValueError as exc:
        raise BeliefV2StreamingInputError(
            "V2 streaming input reconstruction refused") from exc
    if expected != value.realizations \
            or expected_common.canonical_bytes() \
            != value.common_calibration.canonical_bytes() \
            or any(type(digest) is not str or len(digest) != 64
                   or any(char not in "0123456789abcdef" for char in digest)
                   for digest in value.human_group_manifest_sha256s):
        raise BeliefV2StreamingInputError(
            "V2 streaming input reconstruction drift")
    payload = value.manifest()
    if payload["resident_model_array_bytes"] != 0 \
            or payload["one_batch_at_a_time"] is not True \
            or any(payload[key] is not False for key in (
                "synthetic_test_targets_opened", "human_test_targets_opened",
                "training_authorized_by_this_artifact",
                "test_split_open_authorized", "strength_claim_authorized",
                "deployment_authorized")):
        raise BeliefV2StreamingInputError(
            "V2 streaming input authority drift")


def streaming_training_inputs_bytes(
        value: V2StreamingTrainingInputsV1,
        freeze: V2ExecutionFreezeV1) -> bytes:
    """Serialize the compact rows and locators, never model arrays."""
    validate_streaming_training_inputs(value)
    validate_execution_freeze(freeze)
    if value.cohort_plans != freeze.cohorts:
        raise BeliefV2StreamingInputError(
            "V2 streaming input/freeze cohort drift")
    return canonical_json_bytes({
        "schema": STREAMING_INPUT_ARTIFACT_SCHEMA,
        "freeze_sha256": freeze.sha256(),
        "train_rows": [row.to_dict() for row in value.index.train_rows],
        "calibration_rows": [
            row.to_dict() for row in value.index.calibration_rows],
        "sources": [{
            "round_group_key": row.round_group_key,
            "split": row.split,
            "source_kind": row.source_kind,
            "source_token": row.source_token,
        } for row in value.index.sources],
        "control_changed_cell_count": (
            value.index.control_changed_cell_count),
        "human_group_manifest_sha256s": list(
            value.human_group_manifest_sha256s),
        "derived_manifest": value.manifest(),
        "contains_model_arrays": False,
        "training_authorized_by_this_artifact": False,
        "test_split_open_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    })


def _training_row_from_dict(payload: Any):
    if type(payload) is not dict or set(payload) != {
            "schema", "decision_key", "round_group_key", "source_kind",
            "active_label_count", "example_sha256"}:
        raise BeliefV2StreamingInputError(
            "V2 streaming artifact row field drift")
    from .belief_v2_schedule import V2TrainingRowV1
    return V2TrainingRowV1(
        decision_key=payload["decision_key"],
        round_group_key=payload["round_group_key"],
        source_kind=payload["source_kind"],
        active_label_count=payload["active_label_count"],
        example_sha256=payload["example_sha256"],
        schema=payload["schema"])


def reopen_streaming_training_inputs_bytes(
        raw: bytes, *, freeze: V2ExecutionFreezeV1) \
        -> V2StreamingTrainingInputsV1:
    """Independently reconstruct every compact identity from canonical bytes."""
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2StreamingInputError(
            "V2 streaming input artifact is not JSON") from exc
    expected_keys = {
        "schema", "freeze_sha256", "train_rows", "calibration_rows",
        "sources", "control_changed_cell_count",
        "human_group_manifest_sha256s", "derived_manifest",
        "contains_model_arrays", "training_authorized_by_this_artifact",
        "test_split_open_authorized", "strength_claim_authorized",
        "deployment_authorized"}
    if type(payload) is not dict or set(payload) != expected_keys \
            or canonical_json_bytes(payload) != raw \
            or payload["schema"] != STREAMING_INPUT_ARTIFACT_SCHEMA \
            or payload["freeze_sha256"] != freeze.sha256() \
            or payload["contains_model_arrays"] is not False \
            or any(payload[key] is not False for key in (
                "training_authorized_by_this_artifact",
                "test_split_open_authorized", "strength_claim_authorized",
                "deployment_authorized")) \
            or type(payload["train_rows"]) is not list \
            or type(payload["calibration_rows"]) is not list \
            or type(payload["sources"]) is not list \
            or type(payload["human_group_manifest_sha256s"]) is not list:
        raise BeliefV2StreamingInputError(
            "V2 streaming input artifact identity/authority drift")
    try:
        sources = tuple(V2StreamingSourceV1(
            round_group_key=row["round_group_key"], split=row["split"],
            source_kind=row["source_kind"],
            source_token=row["source_token"])
                        for row in payload["sources"]
                        if type(row) is dict and set(row) == {
                            "round_group_key", "split", "source_kind",
                            "source_token"})
        if len(sources) != len(payload["sources"]):
            raise ValueError("source field population")
        value = build_streaming_training_inputs(
            freeze,
            train_rows=tuple(_training_row_from_dict(row)
                             for row in payload["train_rows"]),
            calibration_rows=tuple(_training_row_from_dict(row)
                                   for row in payload["calibration_rows"]),
            sources=sources,
            control_changed_cell_count=(
                payload["control_changed_cell_count"]),
            human_group_manifest_sha256s=tuple(
                payload["human_group_manifest_sha256s"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise BeliefV2StreamingInputError(
            "V2 streaming input artifact reconstruction refused") from exc
    if payload["derived_manifest"] != value.manifest() \
            or streaming_training_inputs_bytes(value, freeze) != raw:
        raise BeliefV2StreamingInputError(
            "V2 streaming input artifact reconstruction drift")
    return value


def _source(
        examples: tuple[V2TrainingExampleV1, ...], *, token: str) \
        -> V2StreamingSourceV1:
    if not examples or len({row.round_group_key for row in examples}) != 1 \
            or len({(row.split, row.source_kind) for row in examples}) != 1:
        raise BeliefV2StreamingInputError(
            "V2 streaming source example population drift")
    first = examples[0]
    return V2StreamingSourceV1(
        round_group_key=first.round_group_key, split=first.split,
        source_kind=first.source_kind, source_token=token)


def reopen_streaming_training_inputs(
        root: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        inventory: dict[str, Any], group_split: dict[str, Any],
        deadline_check: Callable[[str, int], None] | None = None) \
        -> V2StreamingTrainingInputsV1:
    """Scan train/calibration one complete round at a time into compact rows."""
    if not isinstance(root, Path) or root != Path(freeze.evidence_root) \
            or root.is_symlink() or not root.is_dir():
        raise BeliefV2StreamingInputError(
            "V2 streaming evidence root drift")
    _bind_h0_receipts(freeze, inventory, group_split)
    capture = root / "capture"
    expected_lanes = {f"lane-{lane:02d}" for lane in range(V2_CAPTURE_LANES)}
    if capture.is_symlink() or not capture.is_dir() \
            or {path.name for path in capture.iterdir()} != expected_lanes:
        raise BeliefV2StreamingInputError(
            "V2 streaming synthetic capture population drift")
    train_rows = []
    calibration_rows = []
    sources = []
    control_dose = 0
    unit = 0
    for lane in range(V2_CAPTURE_LANES):
        directory = capture / f"lane-{lane:02d}"
        for split in ("train", "calibration"):
            for coordinate_index, examples in \
                    iter_synthetic_training_lane_round_examples(
                        directory, freeze=freeze, admission=admission,
                        lane=lane, split=split,
                        deadline_check=deadline_check,
                        unit_index_start=unit):
                token = f"synthetic:{lane}:{coordinate_index}"
                sources.append(_source(examples, token=token))
                if split == "train":
                    train_rows.extend(training_row(row) for row in examples)
                    _, dose = collate_v2_label_control_examples(examples)
                    control_dose += dose
                else:
                    calibration_rows.extend(
                        calibration_row(row) for row in examples)
                unit += 1

    human_root = root / "human-capture"
    expected_group_digests = {
        digest for row in group_split["splits"].values()
        for digest in row["group_digests"]}
    expected_groups = {f"group-{digest}" for digest in expected_group_digests}
    if human_root.is_symlink() or not human_root.is_dir() \
            or {path.name for path in human_root.iterdir()} != expected_groups:
        raise BeliefV2StreamingInputError(
            "V2 streaming human capture population drift")
    group_hashes = []
    split_groups = {"train": 0, "calibration": 0, "test": 0}
    split_decisions = {"train": 0, "calibration": 0, "test": 0}
    for digest in sorted(expected_group_digests):
        if deadline_check is not None:
            deadline_check("before-unit", unit)
        directory = human_root / f"group-{digest}"
        manifest = reopen_human_group_manifest(
            directory, freeze=freeze, admission=admission)
        split = manifest["split"]
        if manifest["group_digest"] != digest \
                or digest not in group_split["splits"][split]["group_digests"]:
            raise BeliefV2StreamingInputError(
                "V2 streaming human group identity drift")
        split_groups[split] += 1
        split_decisions[split] += manifest["human_decision_count"]
        group_hashes.append(_sha256(canonical_json_bytes(manifest)))
        if split != "train":
            unit += 1
            if deadline_check is not None:
                deadline_check("after-unit", unit)
            continue
        examples = reopen_human_training_group_examples(
            directory, freeze=freeze, admission=admission, split="train")
        grouped: dict[str, list[V2TrainingExampleV1]] = {}
        for example in examples:
            grouped.setdefault(example.round_group_key, []).append(example)
            train_rows.append(training_row(example))
        for round_group, rows in sorted(grouped.items()):
            sources.append(_source(
                tuple(rows), token=f"human:{digest}:{round_group}"))
        unit += 1
        if deadline_check is not None:
            deadline_check("after-unit", unit)
    if split_groups != {
            "train": freeze.human_train_group_count,
            "calibration": freeze.human_calibration_group_count,
            "test": freeze.human_test_group_count} \
            or split_decisions != {
                "train": freeze.human_train_eligible_decision_count,
                "calibration": freeze.human_calibration_eligible_decision_count,
                "test": freeze.human_test_eligible_decision_count}:
        raise BeliefV2StreamingInputError(
            "V2 streaming human split accounting drift")
    if deadline_check is not None:
        deadline_check("before-seal", unit)
    return build_streaming_training_inputs(
        freeze, train_rows=tuple(train_rows),
        calibration_rows=tuple(calibration_rows), sources=tuple(sources),
        control_changed_cell_count=control_dose,
        human_group_manifest_sha256s=tuple(group_hashes))


class V2ArtifactRoundLoader:
    """Authenticate manifests once, then reopen one named group per call."""

    def __init__(self, root: Path, *, freeze: V2ExecutionFreezeV1,
                 admission: V2PipelineAdmissionV1,
                 index: V2StreamingTrainingIndexV1):
        validate_streaming_training_index(index)
        self._root = root
        self._freeze = freeze
        self._admission = admission
        self._sources = {row.round_group_key: row for row in index.sources}
        self._lane_manifests = {
            lane: reopen_actor_capture_lane_manifest(
                root / "capture" / f"lane-{lane:02d}", freeze=freeze,
                admission=admission, lane=lane)
            for lane in range(V2_CAPTURE_LANES)}
        human_digests = {
            source.source_token.split(":")[1]
            for source in index.sources
            if source.source_kind == "human"}
        self._human_manifests = {
            digest: reopen_human_group_manifest(
                root / "human-capture" / f"group-{digest}",
                freeze=freeze, admission=admission)
            for digest in human_digests}

    def __call__(
            self, source: V2StreamingSourceV1) \
            -> tuple[V2TrainingExampleV1, ...]:
        if self._sources.get(source.round_group_key) != source:
            raise BeliefV2StreamingInputError(
                "V2 streaming round loader source drift")
        fields = source.source_token.split(":")
        if fields[0] == "synthetic" and len(fields) == 3:
            try:
                lane, coordinate_index = map(int, fields[1:])
                coordinate = v2_lane_coordinates(lane)[coordinate_index]
                row = self._lane_manifests[lane]["rounds"][coordinate_index]
            except (ValueError, IndexError, KeyError) as exc:
                raise BeliefV2StreamingInputError(
                    "V2 streaming synthetic source token drift") from exc
            result = _reopen_synthetic_training_round_examples(
                self._root / "capture" / f"lane-{lane:02d}",
                coordinate=coordinate, row=row, split=source.split)
        elif fields[0] == "human" and len(fields) == 3:
            digest, round_group = fields[1:]
            if round_group != source.round_group_key:
                raise BeliefV2StreamingInputError(
                    "V2 streaming human source token drift")
            directory = self._root / "human-capture" / f"group-{digest}"
            manifest = self._human_manifests.get(digest)
            if manifest is None or manifest["split"] != source.split:
                raise BeliefV2StreamingInputError(
                    "V2 streaming human source manifest drift")
            examples = []
            for row in manifest["rows"]:
                if row["round_digest"] != round_group:
                    continue
                actor_raw = stable_read_bytes(
                    directory / "actor-only" / row["actor_filename"])
                target_raw = stable_read_bytes(
                    directory / "private-targets" /
                    row["target_filename"])
                if len(actor_raw) != row["actor_byte_count"] \
                        or _sha256(actor_raw) != row["actor_sha256"] \
                        or len(target_raw) != row["target_byte_count"] \
                        or _sha256(target_raw) != row["target_sha256"]:
                    raise BeliefV2StreamingInputError(
                        "V2 streaming human row byte binding drift")
                try:
                    example = build_human_training_example(
                        actor_raw, target_raw)
                except ValueError as exc:
                    raise BeliefV2StreamingInputError(
                        "V2 streaming human example refused") from exc
                if example.decision_key != row["decision_key"] \
                        or example.round_group_key != round_group \
                        or example.split != source.split:
                    raise BeliefV2StreamingInputError(
                        "V2 streaming human example identity drift")
                examples.append(example)
            result = tuple(examples)
        else:
            raise BeliefV2StreamingInputError(
                "V2 streaming source token kind drift")
        if not result or any(row.round_group_key != source.round_group_key
                             for row in result):
            raise BeliefV2StreamingInputError(
                "V2 streaming round loader population drift")
        return result

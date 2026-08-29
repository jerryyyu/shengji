"""Executable, dose-measured negative controls for Value V1.

The transforms operate only on already-validated natural pairs or target-free
inference batches.  They preserve the natural population identity separately
from the deliberately corrupted model inputs/labels, publish exact input and
output hashes, and refuse a named control whose required dose is absent.

They do not read artifacts, train a model, open audit/report outcomes, launch
gameplay, make a strength claim, merge, promote, deploy, retry, or run R5.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Sequence

import torch

from .belief_contract import canonical_json_bytes
from .world_afterstate import WorldAfterstateTensorsV0
from .world_afterstate_v1_dataset import JoinedAdvantageV1
from .world_afterstate_v1_evaluation import (
    AdvantageInferenceBatchV1, collate_inference_pairs)
from .world_afterstate_v1_model import (
    AdvantageBatchV1, collate_successor_tensors, successor_tensor_sha256)
from .world_afterstate_v1_training import AdvantageTrainingBatchV1


CONTROL_ROW_SCHEMA = "world-afterstate-advantage-control-row-v1"
CONTROL_EVIDENCE_SCHEMA = "world-afterstate-advantage-control-evidence-v1"
CONTROL_NAMES = (
    "identical-successor", "action-association-permutation",
    "label-permutation", "complete-world-shuffle",
)
MINIMUM_PERMUTATION_DOSE_PPM = 900_000
MINIMUM_LABEL_EFFECTIVE_DOSE_PPM = 400_000
AUTHORITY = {
    "dataset_opening_authorized": False,
    "training_execution_authorized": False,
    "audit_opening_authorized": False,
    "report_opening_authorized": False,
    "world_twin_generation_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
    "r5_authorized": False,
}


class WorldAfterstateV1ControlError(ValueError):
    """A control transform, donor, dose, or evidence binding drifted."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV1ControlError(f"{label} drift")
    return value


def _copy_tensors(value: WorldAfterstateTensorsV0) -> WorldAfterstateTensorsV0:
    if type(value) is not WorldAfterstateTensorsV0:
        raise WorldAfterstateV1ControlError("control tensor type drift")
    value.validate()
    result = WorldAfterstateTensorsV0(
        public=value.public.copy(), history=value.history.copy(),
        world=value.world.copy(), perspective=value.perspective.copy())
    result.validate()
    return result


def _natural_binding(value: JoinedAdvantageV1) -> dict[str, Any]:
    value.validate()
    return {
        "key": list(value.key()),
        "incumbent_row_sha256": value.incumbent_row_sha256,
        "candidate_row_sha256": value.candidate_row_sha256,
        "incumbent_tensor_sha256":
            successor_tensor_sha256(value.example.incumbent.tensors),
        "candidate_tensor_sha256":
            successor_tensor_sha256(value.example.candidate.tensors),
        "target_levels": value.pair.advantage_levels,
    }


@dataclass(frozen=True)
class ControlledAdvantageV1:
    natural: JoinedAdvantageV1
    control_name: str
    incumbent: WorldAfterstateTensorsV0
    candidate: WorldAfterstateTensorsV0
    target_levels: int
    incumbent_donor_key: str
    candidate_donor_key: str
    incumbent_tensor_sha256: str
    candidate_tensor_sha256: str
    schema: str = CONTROL_ROW_SCHEMA

    def validate(self) -> None:
        if self.schema != CONTROL_ROW_SCHEMA \
                or type(self.natural) is not JoinedAdvantageV1 \
                or self.control_name not in CONTROL_NAMES \
                or type(self.incumbent) is not WorldAfterstateTensorsV0 \
                or type(self.candidate) is not WorldAfterstateTensorsV0 \
                or any(type(value) is not str or not value or not value.isascii()
                       for value in (
                           self.incumbent_donor_key,
                           self.candidate_donor_key)) \
                or isinstance(self.target_levels, bool) \
                or not isinstance(self.target_levels, int) \
                or not -203 <= self.target_levels <= 203:
            raise WorldAfterstateV1ControlError("control row schema drift")
        self.natural.validate()
        self.incumbent.validate()
        self.candidate.validate()
        _digest(self.incumbent_tensor_sha256,
                "control incumbent tensor SHA-256")
        _digest(self.candidate_tensor_sha256,
                "control candidate tensor SHA-256")
        if self.incumbent_tensor_sha256 \
                != successor_tensor_sha256(self.incumbent) \
                or self.candidate_tensor_sha256 \
                != successor_tensor_sha256(self.candidate):
            raise WorldAfterstateV1ControlError(
                "control row tensor binding drift")

    def key(self) -> tuple[str, int, int]:
        self.validate()
        return self.natural.key()

    def binding(self) -> dict[str, Any]:
        self.validate()
        return {
            "key": list(self.key()),
            "control_name": self.control_name,
            "natural_incumbent_row_sha256":
                self.natural.incumbent_row_sha256,
            "natural_candidate_row_sha256":
                self.natural.candidate_row_sha256,
            "incumbent_donor_key": self.incumbent_donor_key,
            "candidate_donor_key": self.candidate_donor_key,
            "incumbent_tensor_sha256": self.incumbent_tensor_sha256,
            "candidate_tensor_sha256": self.candidate_tensor_sha256,
            "target_levels": self.target_levels,
        }


def _controlled(
        natural: JoinedAdvantageV1, *, name: str,
        incumbent: WorldAfterstateTensorsV0,
        candidate: WorldAfterstateTensorsV0, target_levels: int,
        incumbent_donor_key: str,
        candidate_donor_key: str) -> ControlledAdvantageV1:
    result = ControlledAdvantageV1(
        natural=natural, control_name=name,
        incumbent=_copy_tensors(incumbent),
        candidate=_copy_tensors(candidate), target_levels=target_levels,
        incumbent_donor_key=incumbent_donor_key,
        candidate_donor_key=candidate_donor_key,
        incumbent_tensor_sha256=successor_tensor_sha256(incumbent),
        candidate_tensor_sha256=successor_tensor_sha256(candidate))
    result.validate()
    return result


def _evidence(
        name: str, natural: Sequence[JoinedAdvantageV1],
        controlled: Sequence[ControlledAdvantageV1], *,
        changed_count: int, required_minimum_dose_ppm: int,
        effective_changed_count: int | None = None,
        required_minimum_effective_dose_ppm: int | None = None) \
        -> dict[str, Any]:
    if name not in CONTROL_NAMES or type(natural) not in (list, tuple) \
            or type(controlled) not in (list, tuple) or not natural \
            or len(natural) != len(controlled) \
            or isinstance(changed_count, bool) \
            or not isinstance(changed_count, int) \
            or not 0 <= changed_count <= len(natural) \
            or effective_changed_count is not None and (
                isinstance(effective_changed_count, bool)
                or not isinstance(effective_changed_count, int)
                or not 0 <= effective_changed_count <= len(natural)) \
            or isinstance(required_minimum_dose_ppm, bool) \
            or not isinstance(required_minimum_dose_ppm, int) \
            or not 0 <= required_minimum_dose_ppm <= 1_000_000 \
            or required_minimum_effective_dose_ppm is not None and (
                isinstance(required_minimum_effective_dose_ppm, bool)
                or not isinstance(
                    required_minimum_effective_dose_ppm, int)
                or not 0 <= required_minimum_effective_dose_ppm
                <= 1_000_000):
        raise WorldAfterstateV1ControlError("control evidence request drift")
    natural_rows = [_natural_binding(value) for value in natural]
    controlled_rows = [value.binding() for value in controlled]
    dose = changed_count * 1_000_000 // len(natural)
    effective = (changed_count if effective_changed_count is None
                 else effective_changed_count)
    effective_dose = effective * 1_000_000 // len(natural)
    required_effective = (
        required_minimum_dose_ppm
        if required_minimum_effective_dose_ppm is None
        else required_minimum_effective_dose_ppm)
    if dose < required_minimum_dose_ppm:
        raise WorldAfterstateV1ControlError(
            "control transform is below its minimum dose")
    if effective_dose < required_effective:
        raise WorldAfterstateV1ControlError(
            "control transform is below its minimum effective dose")
    body = {
        "schema": CONTROL_EVIDENCE_SCHEMA,
        "name": name,
        "row_count": len(natural),
        "changed_count": changed_count,
        "dose_ppm": dose,
        "effective_changed_count": effective,
        "effective_dose_ppm": effective_dose,
        "required_minimum_dose_ppm": required_minimum_dose_ppm,
        "required_minimum_effective_dose_ppm": required_effective,
        "input_population_sha256": _sha(natural_rows),
        "output_population_sha256": _sha(controlled_rows),
        "authority": dict(AUTHORITY),
    }
    if body["input_population_sha256"] == body["output_population_sha256"]:
        raise WorldAfterstateV1ControlError(
            "control transform did not change population bytes")
    return {**body, "evidence_sha256": _sha(body)}


def identical_successor_control(
        natural: Sequence[JoinedAdvantageV1]) \
        -> tuple[tuple[ControlledAdvantageV1, ...], dict[str, Any]]:
    if type(natural) not in (list, tuple) or not natural:
        raise WorldAfterstateV1ControlError(
            "identical-successor population drift")
    rows = []
    for value in natural:
        value.validate()
        key = value.key()
        donor = f"{key[0]}:0"
        rows.append(_controlled(
            value, name="identical-successor",
            incumbent=value.example.incumbent.tensors,
            candidate=value.example.incumbent.tensors,
            target_levels=value.pair.advantage_levels,
            incumbent_donor_key=donor, candidate_donor_key=donor))
    changed = sum(
        successor_tensor_sha256(row.candidate)
        != successor_tensor_sha256(value.example.candidate.tensors)
        for value, row in zip(natural, rows, strict=True))
    evidence = _evidence(
        "identical-successor", natural, rows, changed_count=changed,
        required_minimum_dose_ppm=1_000_000)
    return tuple(rows), evidence


def action_association_permutation(
        natural: Sequence[JoinedAdvantageV1]) \
        -> tuple[tuple[ControlledAdvantageV1, ...], dict[str, Any]]:
    """Rotate all action successors within each root; retain natural labels."""
    if type(natural) not in (list, tuple) or not natural:
        raise WorldAfterstateV1ControlError(
            "action-association population drift")
    states: dict[str, list[JoinedAdvantageV1]] = defaultdict(list)
    for value in natural:
        value.validate()
        states[value.pair.state_group_id].append(value)
    controls = []
    for state in sorted(states):
        values = sorted(states[state], key=lambda value: value.key())
        candidates = sorted({value.pair.candidate_index for value in values})
        if [(value.pair.candidate_index, value.pair.replicate)
                for value in values] != [
                    (candidate, replicate) for candidate in candidates
                    for replicate in (0, 1)]:
            raise WorldAfterstateV1ControlError(
                "action-association incomplete root")
        action_tensors = {0: values[0].example.incumbent.tensors}
        action_hashes = {0: successor_tensor_sha256(action_tensors[0])}
        for candidate in candidates:
            candidate_values = [value for value in values
                                if value.pair.candidate_index == candidate]
            hashes = {
                successor_tensor_sha256(value.example.candidate.tensors)
                for value in candidate_values
            }
            if len(hashes) != 1:
                raise WorldAfterstateV1ControlError(
                    "action-association replicate tensor drift")
            action_tensors[candidate] = candidate_values[0].example.candidate.tensors
            action_hashes[candidate] = next(iter(hashes))
        actions = [0, *candidates]
        if len(action_hashes) != len(actions):
            raise WorldAfterstateV1ControlError(
                "action-association action population drift")
        donor = {action: actions[(index + 1) % len(actions)]
                 for index, action in enumerate(actions)}
        for value in values:
            candidate = value.pair.candidate_index
            controls.append(_controlled(
                value, name="action-association-permutation",
                incumbent=action_tensors[donor[0]],
                candidate=action_tensors[donor[candidate]],
                target_levels=value.pair.advantage_levels,
                incumbent_donor_key=f"{state}:{donor[0]}",
                candidate_donor_key=f"{state}:{donor[candidate]}"))
    controls.sort(key=lambda value: value.key())
    ordered_natural = sorted(natural, key=lambda value: value.key())
    changed = sum(
        row.incumbent_tensor_sha256 \
        != successor_tensor_sha256(value.example.incumbent.tensors)
        or row.candidate_tensor_sha256 \
        != successor_tensor_sha256(value.example.candidate.tensors)
        for value, row in zip(ordered_natural, controls, strict=True))
    evidence = _evidence(
        "action-association-permutation", ordered_natural, controls,
        changed_count=changed,
        required_minimum_dose_ppm=MINIMUM_PERMUTATION_DOSE_PPM)
    return tuple(controls), evidence


def label_permutation(
        natural: Sequence[JoinedAdvantageV1]) \
        -> tuple[tuple[ControlledAdvantageV1, ...], dict[str, Any]]:
    """Rotate labels within populated outcome-blind geometry buckets.

    Candidate index is deliberately absent: it is an arbitrary ballot-order
    position, not a comparable action class across roots.  Exact trump, role,
    and point buckets made 2,158 of the frozen V0 train buckets singletons.
    Source, phase, lead/follow position, and replicate retain the important
    collection/noise geometry while keeping every frozen bucket populated.
    """
    if type(natural) not in (list, tuple) or not natural:
        raise WorldAfterstateV1ControlError("label control population drift")
    buckets: dict[tuple[Any, ...], list[JoinedAdvantageV1]] = defaultdict(list)
    for value in natural:
        value.validate()
        pair = value.pair
        bucket = (
            pair.source, pair.play_phase, pair.position, pair.replicate,
        )
        buckets[bucket].append(value)
    target_by_key = {}
    donor_by_key = {}
    for bucket in sorted(buckets, key=str):
        values = sorted(buckets[bucket], key=lambda value: hashlib.sha256(
            canonical_json_bytes({"namespace": "value-v1-label-control",
                                  "key": list(value.key())})).hexdigest())
        if len(values) < 2:
            raise WorldAfterstateV1ControlError(
                "label control geometry bucket is a singleton")
        for index, value in enumerate(values):
            donor = values[(index + 1) % len(values)]
            target_by_key[value.key()] = donor.pair.advantage_levels
            donor_by_key[value.key()] = ":".join(map(str, donor.key()))
    controls = []
    for value in sorted(natural, key=lambda value: value.key()):
        key = value.key()
        controls.append(_controlled(
            value, name="label-permutation",
            incumbent=value.example.incumbent.tensors,
            candidate=value.example.candidate.tensors,
            target_levels=target_by_key[key],
            incumbent_donor_key=f"{key[0]}:0",
            candidate_donor_key=donor_by_key[key]))
    ordered_natural = sorted(natural, key=lambda value: value.key())
    changed = sum(row.target_levels != value.pair.advantage_levels
                  for value, row in zip(
                      ordered_natural, controls, strict=True))
    evidence = _evidence(
        "label-permutation",
        ordered_natural, controls,
        changed_count=len(controls),
        effective_changed_count=changed,
        required_minimum_dose_ppm=MINIMUM_PERMUTATION_DOSE_PPM,
        required_minimum_effective_dose_ppm=
            MINIMUM_LABEL_EFFECTIVE_DOSE_PPM)
    return tuple(controls), evidence


def collate_control_training_pairs(
        values: Sequence[ControlledAdvantageV1], *,
        split: str) -> AdvantageTrainingBatchV1:
    """Bind one named control population to the real optimizer batch type."""
    if type(values) not in (list, tuple) or not values \
            or split not in ("fit", "select") \
            or any(type(value) is not ControlledAdvantageV1
                   for value in values):
        raise WorldAfterstateV1ControlError(
            "control training population drift")
    for value in values:
        value.validate()
    names = {value.control_name for value in values}
    if len(names) != 1 \
            or any(value.natural.pair.fold != "train" for value in values):
        raise WorldAfterstateV1ControlError(
            "control training cohort binding drift")
    tensors = AdvantageBatchV1(
        incumbent=collate_successor_tensors(
            [value.incumbent for value in values]),
        candidate=collate_successor_tensors(
            [value.candidate for value in values]),
        targets=torch.as_tensor(
            [value.target_levels for value in values], dtype=torch.float32))
    tensors.validate()
    keys = [value.key() for value in values]
    result = AdvantageTrainingBatchV1(
        pair_keys=tuple(f"{state}:{candidate}:{replicate}"
                        for state, candidate, replicate in keys),
        state_group_ids=tuple(state for state, _, _ in keys),
        candidate_indexes=tuple(candidate for _, candidate, _ in keys),
        replicates=tuple(replicate for _, _, replicate in keys),
        incumbent_row_sha256s=tuple(
            value.natural.incumbent_row_sha256 for value in values),
        candidate_row_sha256s=tuple(
            value.natural.candidate_row_sha256 for value in values),
        incumbent_tensor_sha256s=tuple(
            value.incumbent_tensor_sha256 for value in values),
        candidate_tensor_sha256s=tuple(
            value.candidate_tensor_sha256 for value in values),
        target_levels=tuple(value.target_levels for value in values),
        split=split, tensors=tensors)
    result.validate()
    return result


def _batch_tensor(batch, index: int) -> WorldAfterstateTensorsV0:
    length = int(batch.history_lengths[index])
    return WorldAfterstateTensorsV0(
        public=batch.public[index].detach().cpu().numpy().copy(),
        history=batch.history[index, :length].detach().cpu().numpy().copy(),
        world=batch.world[index].detach().cpu().numpy().copy(),
        perspective=batch.perspective[index].detach().cpu().numpy().copy())


def complete_world_shuffle(
        value: AdvantageInferenceBatchV1) \
        -> tuple[AdvantageInferenceBatchV1, dict[str, Any]]:
    """Rotate only complete-world tensors across unique action successors."""
    if type(value) is not AdvantageInferenceBatchV1:
        raise WorldAfterstateV1ControlError(
            "world-shuffle inference type drift")
    value.validate()
    unique: dict[str, WorldAfterstateTensorsV0] = {}
    keys_by_row = []
    for index, (state, candidate) in enumerate(zip(
            value.state_group_ids, value.candidate_indexes, strict=True)):
        incumbent_key = f"{state}:0"
        candidate_key = f"{state}:{candidate}"
        incumbent = _batch_tensor(value.incumbent, index)
        candidate_tensors = _batch_tensor(value.candidate, index)
        for key, tensors in ((incumbent_key, incumbent),
                             (candidate_key, candidate_tensors)):
            existing = unique.get(key)
            if existing is not None and successor_tensor_sha256(existing) \
                    != successor_tensor_sha256(tensors):
                raise WorldAfterstateV1ControlError(
                    "world-shuffle repeated successor drift")
            unique[key] = tensors
        keys_by_row.append((incumbent_key, candidate_key))
    ordered = sorted(unique, key=lambda key: (
        hashlib.sha256(canonical_json_bytes({
            "namespace": "value-v1-world-shuffle", "key": key,
        })).hexdigest(), key))
    if len(ordered) < 2:
        raise WorldAfterstateV1ControlError(
            "world-shuffle population is too small")
    donor = {key: ordered[(index + 1) % len(ordered)]
             for index, key in enumerate(ordered)}

    def replaced(key: str) -> WorldAfterstateTensorsV0:
        base = unique[key]
        source = unique[donor[key]]
        result = WorldAfterstateTensorsV0(
            public=base.public.copy(), history=base.history.copy(),
            world=source.world.copy(), perspective=base.perspective.copy())
        result.validate()
        return result

    incumbents = [replaced(left) for left, _ in keys_by_row]
    candidates = [replaced(right) for _, right in keys_by_row]
    output = collate_inference_pairs(
        state_group_ids=value.state_group_ids,
        candidate_indexes=value.candidate_indexes,
        incumbent_successor_sha256s=value.incumbent_successor_sha256s,
        candidate_successor_sha256s=value.candidate_successor_sha256s,
        incumbent_tensors=incumbents, candidate_tensors=candidates)
    input_bindings = [[key, successor_tensor_sha256(tensors)]
                      for key, tensors in sorted(unique.items())]
    output_bindings = [[key, successor_tensor_sha256(replaced(key))]
                       for key in sorted(unique)]
    changed = sum(left[1] != right[1] for left, right in zip(
        input_bindings, output_bindings, strict=True))
    dose = changed * 1_000_000 // len(unique)
    if changed == 0:
        raise WorldAfterstateV1ControlError("world-shuffle has zero dose")
    body = {
        "schema": CONTROL_EVIDENCE_SCHEMA,
        "name": "complete-world-shuffle",
        "row_count": len(unique), "changed_count": changed,
        "dose_ppm": dose, "effective_changed_count": changed,
        "effective_dose_ppm": dose, "required_minimum_dose_ppm": 1,
        "required_minimum_effective_dose_ppm": 1,
        "input_population_sha256": _sha(input_bindings),
        "output_population_sha256": _sha(output_bindings),
        "authority": dict(AUTHORITY),
    }
    return output, {**body, "evidence_sha256": _sha(body)}


def validate_control_evidence(value: object) -> None:
    required = {
        "schema", "name", "row_count", "changed_count", "dose_ppm",
        "effective_changed_count", "effective_dose_ppm",
        "required_minimum_dose_ppm",
        "required_minimum_effective_dose_ppm", "input_population_sha256",
        "output_population_sha256", "authority", "evidence_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != CONTROL_EVIDENCE_SCHEMA \
            or value.get("name") not in CONTROL_NAMES \
            or value.get("authority") != AUTHORITY:
        raise WorldAfterstateV1ControlError("control evidence schema drift")
    integers = (
        "row_count", "changed_count", "dose_ppm",
        "effective_changed_count", "effective_dose_ppm",
        "required_minimum_dose_ppm",
        "required_minimum_effective_dose_ppm",
    )
    if any(isinstance(value.get(key), bool)
           or not isinstance(value.get(key), int) for key in integers) \
            or value["row_count"] <= 0 \
            or not 0 <= value["changed_count"] <= value["row_count"] \
            or value["dose_ppm"] \
            != value["changed_count"] * 1_000_000 // value["row_count"] \
            or not 0 <= value["effective_changed_count"] \
            <= value["row_count"] \
            or value["effective_dose_ppm"] \
            != value["effective_changed_count"] * 1_000_000 \
            // value["row_count"] \
            or not 0 <= value["required_minimum_dose_ppm"] <= 1_000_000 \
            or not 0 <= value["required_minimum_effective_dose_ppm"] \
            <= 1_000_000 \
            or value["dose_ppm"] < value["required_minimum_dose_ppm"] \
            or value["effective_dose_ppm"] \
            < value["required_minimum_effective_dose_ppm"]:
        raise WorldAfterstateV1ControlError(
            "control evidence dose reconstruction drift")
    input_sha = _digest(
        value.get("input_population_sha256"),
        "control evidence input SHA-256")
    output_sha = _digest(
        value.get("output_population_sha256"),
        "control evidence output SHA-256")
    _digest(value.get("evidence_sha256"), "control evidence SHA-256")
    body = {key: item for key, item in value.items()
            if key != "evidence_sha256"}
    if input_sha == output_sha or value["evidence_sha256"] != _sha(body):
        raise WorldAfterstateV1ControlError(
            "control evidence byte reconstruction drift")


__all__ = [
    "AUTHORITY", "ControlledAdvantageV1", "WorldAfterstateV1ControlError",
    "action_association_permutation", "complete_world_shuffle",
    "collate_control_training_pairs", "identical_successor_control",
    "label_permutation",
    "validate_control_evidence",
]

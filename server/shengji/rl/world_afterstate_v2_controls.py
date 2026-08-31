"""Deterministic, in-memory negative controls for Value-Afterstate V2.

The controls in this module operate on complete fit roots.  A control row
keeps the natural row (and therefore its sealed identity) beside the altered
model tensor/label.  No control is an inference, gameplay, or execution
interface.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
from typing import Any, Mapping, Sequence

import numpy as np

from .belief_contract import canonical_json_bytes
from .world_afterstate import WorldAfterstateTensorsV0, OUTCOME_CLASSES
from .world_afterstate_v2_training import (
    REPLICATES, WorldAfterstateV2TrainingExample,
    WorldAfterstateV2TrainingError, collate_training_examples,
)


CONTROL_ROW_SCHEMA = "world-afterstate-v2-control-row-v1"
CONTROL_EVIDENCE_SCHEMA = "world-afterstate-v2-control-evidence-v1"
CONTROL_NAMES = (
    "action-association-permutation", "label-permutation",
    "complete-world-shuffle",
)
MINIMUM_PERMUTATION_DOSE_PPM = 900_000
MINIMUM_LABEL_EFFECTIVE_DOSE_PPM = 400_000
AUTHORITY = {
    "dataset_opening_authorized": False,
    "training_execution_authorized": False,
    "audit_opening_authorized": False,
    "world_twin_generation_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
}


class WorldAfterstateV2ControlError(ValueError):
    """A V2 control input, transform, or receipt violated its contract."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2ControlError(f"{label} drift")
    return value


def _seed(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 2**64:
        raise WorldAfterstateV2ControlError("control seed drift")
    return value


def _tensor_sha256(value: WorldAfterstateTensorsV0) -> str:
    if type(value) is not WorldAfterstateTensorsV0:
        raise WorldAfterstateV2ControlError("control tensor type drift")
    value.validate()
    return _sha({
        "public": hashlib.sha256(value.public.tobytes(order="C")).hexdigest(),
        "history": hashlib.sha256(value.history.tobytes(order="C")).hexdigest(),
        "world": hashlib.sha256(value.world.tobytes(order="C")).hexdigest(),
        "perspective": hashlib.sha256(
            value.perspective.tobytes(order="C")).hexdigest(),
    })


def _clone(value: WorldAfterstateTensorsV0) -> WorldAfterstateTensorsV0:
    value.validate()
    result = WorldAfterstateTensorsV0(
        public=value.public.copy(), history=value.history.copy(),
        world=value.world.copy(), perspective=value.perspective.copy())
    result.validate()
    return result


def _candidate_set(state: str, successors: Sequence[str]) -> str:
    _digest(state, "control state SHA-256")
    if type(successors) not in (list, tuple) or len(successors) < 2 \
            or len(set(successors)) != len(successors):
        raise WorldAfterstateV2ControlError("control successor population drift")
    for value in successors:
        _digest(value, "control successor SHA-256")
    return _sha({"schema": "world-afterstate-v2-candidate-set-v1",
                 "state_sha256": state,
                 "successor_sha256s": list(successors)})


def _roots(values: Sequence[WorldAfterstateV2TrainingExample]) \
        -> dict[str, list[WorldAfterstateV2TrainingExample]]:
    if type(values) not in (list, tuple) or not values:
        raise WorldAfterstateV2ControlError("control population is empty")
    result: dict[str, list[WorldAfterstateV2TrainingExample]] = defaultdict(list)
    for value in values:
        if type(value) is not WorldAfterstateV2TrainingExample:
            raise WorldAfterstateV2ControlError("control row type drift")
        try:
            value.validate()
        except WorldAfterstateV2TrainingError as exc:
            raise WorldAfterstateV2ControlError("control source row refused") from exc
        if value.split != "fit":
            raise WorldAfterstateV2ControlError("control only accepts fit rows")
        result[value.root_key].append(value)
    for root, rows in result.items():
        rows.sort(key=lambda row: (row.candidate_index, row.replica))
        pairs = [(row.candidate_index, row.replica) for row in rows]
        candidates = sorted({row.candidate_index for row in rows})
        if candidates != list(range(len(candidates))) or len(candidates) < 2 \
                or pairs != [(candidate, replica) for candidate in candidates
                             for replica in REPLICATES]:
            raise WorldAfterstateV2ControlError("control incomplete root")
        if len({row.successor_sha256 for row in rows}) != len(candidates):
            raise WorldAfterstateV2ControlError("control duplicate successor")
        try:
            collate_training_examples(
                rows, split=rows[0].split, cohort=rows[0].cohort).validate()
        except WorldAfterstateV2TrainingError as exc:
            raise WorldAfterstateV2ControlError(
                "control source root mechanics drift") from exc
        # This also detects a root whose nominal identity has been forged.
        first = rows[0]
        for row in rows[1:]:
            if (row.deal_sha256, row.slot_sha256, row.state_sha256,
                    row.candidate_set_sha256, row.source, row.split, row.role,
                    row.phase, row.position, row.trump_rank, row.trump_mode) != (
                    first.deal_sha256, first.slot_sha256, first.state_sha256,
                    first.candidate_set_sha256, first.source, first.split,
                    first.role, first.phase, first.position, first.trump_rank,
                    first.trump_mode) or row.points_bucket != first.points_bucket:
                raise WorldAfterstateV2ControlError("control root identity drift")
    return result


def _family_key(root: str, candidate: int) -> str:
    return f"{root}:{candidate}"


def _order(keys: Sequence[str], *, seed: int, namespace: str) -> list[str]:
    return sorted(keys, key=lambda key: (
        hashlib.sha256(canonical_json_bytes({
            "namespace": namespace, "seed": seed, "key": key,
        })).digest(), key))


def _stratum(row: WorldAfterstateV2TrainingExample, candidate_count: int) \
        -> tuple[str, str, str, str, str, str, str, int]:
    return (row.source, row.trump_rank, row.trump_mode, row.phase,
            row.position, row.role, row.points_bucket, candidate_count)


def _label_stratum(row: WorldAfterstateV2TrainingExample,
                   _candidate_count: int) -> tuple[str, str, str]:
    """Preserve collection/noise geometry without conditioning on outcomes.

    Exact trump, role, points, and ballot-width buckets can contain only one
    state whose candidate families all have the same numeric target.  In that
    geometry even an optimal family derangement cannot satisfy the frozen
    label-control dose.  Source, phase, and lead/follow position retain the
    outcome-blind acquisition geometry while allowing whole eight-replica
    families from distinct states to exchange targets.  Complete-world
    shuffle deliberately keeps using the stricter ``_stratum`` above.
    """
    return (row.source, row.phase, row.position)


@dataclass(frozen=True)
class ControlledWorldAfterstateV2Example:
    """One natural row and its deliberately altered training payload."""

    natural: WorldAfterstateV2TrainingExample
    control_name: str
    tensors: WorldAfterstateTensorsV0
    successor_sha256: str
    donor_successor_sha256: str
    target_category: int
    donor_key: str
    schema: str = CONTROL_ROW_SCHEMA

    @property
    def candidate_index(self) -> int:
        return self.natural.candidate_index

    @property
    def replica(self) -> int:
        return self.natural.replica

    @property
    def root_key(self) -> str:
        return self.natural.root_key

    @property
    def example_key(self) -> str:
        return self.natural.example_key

    @property
    def label(self) -> int:
        return self.target_category

    @property
    def signed_level_category(self) -> int:
        return self.target_category

    @property
    def protected_incumbent(self) -> bool:
        return self.natural.protected_incumbent

    @property
    def continuation_sha256(self) -> str:
        return self.natural.continuation_sha256

    @property
    def candidate_set_sha256(self) -> str:
        return self.natural.candidate_set_sha256

    def validate(self) -> None:
        if self.schema != CONTROL_ROW_SCHEMA or self.control_name not in CONTROL_NAMES \
                or type(self.natural) is not WorldAfterstateV2TrainingExample \
                or type(self.tensors) is not WorldAfterstateTensorsV0 \
                or type(self.donor_key) is not str or not self.donor_key \
                or isinstance(self.target_category, bool) \
                or not isinstance(self.target_category, int) \
                or not 0 <= self.target_category < OUTCOME_CLASSES:
            raise WorldAfterstateV2ControlError("control row schema drift")
        self.natural.validate()
        self.tensors.validate()
        _digest(self.successor_sha256, "control successor SHA-256")
        _digest(self.donor_successor_sha256,
                "control donor successor SHA-256")
        if self.natural.split != "fit":
            raise WorldAfterstateV2ControlError("control row split refused")
        if self.successor_sha256 != self.natural.successor_sha256:
            raise WorldAfterstateV2ControlError(
                "control changed protected successor identity")
        if self.control_name == "action-association-permutation" \
                and self.donor_successor_sha256 == self.successor_sha256:
            raise WorldAfterstateV2ControlError(
                "association donor was not deranged")
        if self.control_name != "action-association-permutation" \
                and self.donor_successor_sha256 != self.successor_sha256:
            raise WorldAfterstateV2ControlError(
                "non-association donor successor drift")

    def binding(self) -> dict[str, Any]:
        self.validate()
        return {
            "key": self.example_key, "root": self.root_key,
            "control_name": self.control_name,
            "candidate_index": self.candidate_index, "replica": self.replica,
            "successor_sha256": self.successor_sha256,
            "donor_successor_sha256": self.donor_successor_sha256,
            "tensor_sha256": _tensor_sha256(self.tensors),
            "target_category": self.target_category,
            "donor_key": self.donor_key,
            "natural_identity": {
                "deal_sha256": self.natural.deal_sha256,
                "slot_sha256": self.natural.slot_sha256,
                "state_sha256": self.natural.state_sha256,
                "candidate_set_sha256": self.natural.candidate_set_sha256,
                "candidate_index": self.natural.candidate_index,
                "protected_incumbent": self.natural.protected_incumbent,
                "continuation_sha256": self.natural.continuation_sha256,
                "replica": self.natural.replica,
                "source": self.natural.source,
                "split": self.natural.split,
                "role": self.natural.role,
                "phase": self.natural.phase,
                "position": self.natural.position,
                "trump_rank": self.natural.trump_rank,
                "trump_mode": self.natural.trump_mode,
                "points_bucket": self.natural.points_bucket,
                "target_category": self.natural.signed_level_category,
            },
        }

    @property
    def transformed_candidate_set_sha256(self) -> str:
        self.validate()
        root_rows = self.natural
        # A single-row view cannot derive the set; association callers use
        # ``transformed_candidate_set`` below when batching a root.
        return root_rows.candidate_set_sha256


def _row(natural: WorldAfterstateV2TrainingExample, name: str,
         tensors: WorldAfterstateTensorsV0, successor: str,
         donor_successor: str, target: int, donor: str) \
        -> ControlledWorldAfterstateV2Example:
    result = ControlledWorldAfterstateV2Example(
        natural=natural, control_name=name, tensors=_clone(tensors),
        successor_sha256=successor,
        donor_successor_sha256=donor_successor,
        target_category=target, donor_key=donor)
    result.validate()
    return result


def _population_binding(values: Sequence[WorldAfterstateV2TrainingExample]) -> list[dict[str, Any]]:
    roots = _roots(values)
    output = []
    for root in sorted(roots):
        for row in roots[root]:
            output.append({
                "key": row.example_key, "root": root,
                "candidate_index": row.candidate_index, "replica": row.replica,
                "deal_sha256": row.deal_sha256, "slot_sha256": row.slot_sha256,
                "state_sha256": row.state_sha256,
                "candidate_set_sha256": row.candidate_set_sha256,
                "successor_sha256": row.successor_sha256,
                "continuation_sha256": row.continuation_sha256,
                "source": row.source, "split": row.split, "role": row.role,
                "phase": row.phase, "position": row.position,
                "trump_rank": row.trump_rank, "trump_mode": row.trump_mode,
                "points_bucket": row.points_bucket,
                "tensor_sha256": _tensor_sha256(row.tensors),
                "target_category": row.signed_level_category,
            })
    return output


def _controlled_binding(values: Sequence[ControlledWorldAfterstateV2Example]) \
        -> list[dict[str, Any]]:
    return [row.binding() for row in sorted(
        values, key=lambda row: (row.root_key, row.candidate_index, row.replica))]


def _evidence(name: str, seed: int,
              natural: Sequence[WorldAfterstateV2TrainingExample],
              controlled: Sequence[ControlledWorldAfterstateV2Example], *,
              changed_rows: int, changed_cells: int,
              eligible_rows: int | None = None,
              eligible_cells: int | None = None) -> dict[str, Any]:
    if name not in CONTROL_NAMES or len(natural) != len(controlled) or not natural:
        raise WorldAfterstateV2ControlError("control evidence population drift")
    _seed(seed)
    for row in controlled:
        row.validate()
    row_count = len(natural)
    eligible_rows = row_count if eligible_rows is None else eligible_rows
    eligible_cells = row_count if eligible_cells is None else eligible_cells
    if not (0 <= changed_rows <= eligible_rows <= row_count and
            0 <= changed_cells <= eligible_cells <= row_count):
        raise WorldAfterstateV2ControlError("control evidence dose drift")
    row_dose = changed_rows * 1_000_000 // eligible_rows if eligible_rows else 0
    cell_dose = changed_cells * 1_000_000 // eligible_cells if eligible_cells else 0
    input_digest = _sha(_population_binding(natural))
    output_digest = _sha(_controlled_binding(controlled))
    if input_digest == output_digest or changed_rows == 0:
        raise WorldAfterstateV2ControlError("control has zero dose")
    body = {
        "schema": CONTROL_EVIDENCE_SCHEMA, "control_name": name,
        "name": name, "seed": seed, "row_count": row_count,
        "eligible_row_count": eligible_rows, "eligible_cell_count": eligible_cells,
        "changed_row_count": changed_rows, "changed_cell_count": changed_cells,
        "changed_count": changed_rows,
        "row_dose_ppm": row_dose, "cell_dose_ppm": cell_dose,
        "dose_ppm": row_dose, "effective_changed_count": changed_cells,
        "effective_dose_ppm": cell_dose,
        "required_minimum_dose_ppm": MINIMUM_PERMUTATION_DOSE_PPM,
        "required_minimum_effective_dose_ppm": (
            MINIMUM_LABEL_EFFECTIVE_DOSE_PPM if name == "label-permutation"
            else MINIMUM_PERMUTATION_DOSE_PPM),
        "root_count": len(_roots(natural)),
        "source_population_sha256": input_digest,
        "input_population_sha256": input_digest,
        "output_population_sha256": output_digest,
        "authority": dict(AUTHORITY),
    }
    if row_dose < body["required_minimum_dose_ppm"] \
            or cell_dose < body["required_minimum_effective_dose_ppm"]:
        raise WorldAfterstateV2ControlError("control transform is below minimum dose")
    return {**body, "evidence_sha256": _sha(body)}


def action_association_permutation(
        natural: Sequence[WorldAfterstateV2TrainingExample], *,
        seed: int = 0xA57E_0001) \
        -> tuple[tuple[ControlledWorldAfterstateV2Example, ...], dict[str, Any]]:
    """Derange every successor/tensor binding within each complete root."""
    roots = _roots(natural)
    _seed(seed)
    controls: list[ControlledWorldAfterstateV2Example] = []
    for root in sorted(roots):
        rows = roots[root]
        candidates = sorted({row.candidate_index for row in rows})
        by_candidate = {candidate: [row for row in rows
                                    if row.candidate_index == candidate]
                        for candidate in candidates}
        order = _order([str(candidate) for candidate in candidates], seed=seed,
                       namespace="world-afterstate-v2-association")
        donor = {int(order[index]): int(order[(index + 1) % len(order)])
                 for index in range(len(order))}
        representative = {candidate: by_candidate[candidate][0]
                          for candidate in candidates}
        for row in rows:
            source = representative[donor[row.candidate_index]]
            controls.append(_row(
                row, "action-association-permutation", source.tensors,
                row.successor_sha256, source.successor_sha256,
                row.signed_level_category,
                _family_key(root, donor[row.candidate_index])))
    controls.sort(key=lambda value: (value.root_key, value.candidate_index, value.replica))
    ordered = sorted(natural, key=lambda value: (value.root_key,
                                                  value.candidate_index,
                                                  value.replica))
    changed_bindings = sum(
        row.donor_successor_sha256 != natural_row.successor_sha256
        for row, natural_row in zip(controls, ordered, strict=True))
    changed_tensors = sum(
        _tensor_sha256(row.tensors) != _tensor_sha256(natural_row.tensors)
        for row, natural_row in zip(controls, ordered, strict=True))
    evidence = _evidence("action-association-permutation", seed, ordered, controls,
                         changed_rows=changed_bindings,
                         changed_cells=changed_tensors)
    return tuple(controls), evidence


def label_permutation(
        natural: Sequence[WorldAfterstateV2TrainingExample], *,
        seed: int = 0xA57E_0002) \
        -> tuple[tuple[ControlledWorldAfterstateV2Example, ...], dict[str, Any]]:
    """Rotate whole candidate×8 families within collection/noise strata."""
    roots = _roots(natural)
    _seed(seed)
    buckets: dict[tuple[Any, ...], list[tuple[str, int]]] = defaultdict(list)
    for root, rows in roots.items():
        count = len({row.candidate_index for row in rows})
        first = rows[0]
        buckets[_label_stratum(first, count)].extend(
            (root, candidate) for candidate in range(count))
    donors: dict[tuple[str, int], tuple[str, int]] = {}
    for bucket, families in sorted(buckets.items(), key=lambda item: str(item[0])):
        if len(families) < 2:
            raise WorldAfterstateV2ControlError("label geometry bucket is a singleton")
        keys = [_family_key(root, candidate) for root, candidate in families]
        ordered = _order(keys, seed=seed, namespace="world-afterstate-v2-label")
        lookup = {_family_key(root, candidate): (root, candidate)
                  for root, candidate in families}
        for index, key in enumerate(ordered):
            donors[lookup[key]] = lookup[ordered[(index + 1) % len(ordered)]]
    controls = []
    for root in sorted(roots):
        rows = roots[root]
        count = len({row.candidate_index for row in rows})
        by_family = {(root, candidate): [row for row in rows
                                        if row.candidate_index == candidate]
                     for candidate in range(count)}
        for row in rows:
            donor_root, donor_candidate = donors[(root, row.candidate_index)]
            donor_rows = by_family.get((donor_root, donor_candidate))
            if donor_rows is None:
                donor_rows = [item for item in roots[donor_root]
                              if item.candidate_index == donor_candidate]
            donor_by_replica = {item.replica: item for item in donor_rows}
            donor_row = donor_by_replica[row.replica]
            controls.append(_row(
                row, "label-permutation", row.tensors, row.successor_sha256,
                row.successor_sha256, donor_row.signed_level_category,
                _family_key(donor_root, donor_candidate)))
    controls.sort(key=lambda value: (value.root_key, value.candidate_index, value.replica))
    ordered = sorted(natural, key=lambda value: (value.root_key,
                                                  value.candidate_index,
                                                  value.replica))
    changed = sum(row.target_category != source.signed_level_category
                  for row, source in zip(controls, ordered, strict=True))
    if Counter(row.target_category for row in controls) != Counter(
            row.signed_level_category for row in ordered):
        raise WorldAfterstateV2ControlError("label histogram drift")
    # Every family receives a different donor binding; numeric target dose is
    # measured separately because equal labels can make individual cells byte
    # equal even though the donor family moved.
    evidence = _evidence("label-permutation", seed, ordered, controls,
                         changed_rows=len(ordered), changed_cells=changed,
                         eligible_rows=len(ordered), eligible_cells=len(ordered))
    return tuple(controls), evidence


def complete_world_shuffle(
        natural: Sequence[WorldAfterstateV2TrainingExample], *,
        seed: int = 0xA57E_0003) \
        -> tuple[tuple[ControlledWorldAfterstateV2Example, ...], dict[str, Any]]:
    """Derange complete-world channels across compatible distinct deals."""
    roots = _roots(natural)
    _seed(seed)
    strata: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    for root, rows in roots.items():
        count = len({row.candidate_index for row in rows})
        strata[_stratum(rows[0], count)].append(root)
    root_donor: dict[str, str] = {}
    eligible_roots: set[str] = set()
    for stratum, members in sorted(strata.items(), key=lambda item: str(item[0])):
        if len(members) < 2:
            continue
        ordered = _order(members, seed=seed, namespace="world-afterstate-v2-world")
        for index, root in enumerate(ordered):
            root_donor[root] = ordered[(index + 1) % len(ordered)]
            eligible_roots.add(root)
    if not eligible_roots:
        raise WorldAfterstateV2ControlError("world-shuffle has no compatible deal pair")
    controls = []
    for root in sorted(roots):
        by_candidate = {row.candidate_index: row for row in roots[root]}
        donor_root = root_donor.get(root)
        donor_by_candidate = ({row.candidate_index: row
                               for row in roots[donor_root]}
                              if donor_root is not None else {})
        for row in roots[root]:
            if donor_root is None:
                controls.append(_row(row, "complete-world-shuffle", row.tensors,
                                     row.successor_sha256, row.successor_sha256,
                                     row.signed_level_category,
                                     root))
                continue
            donor = donor_by_candidate[row.candidate_index]
            tensors = WorldAfterstateTensorsV0(
                public=row.tensors.public.copy(),
                history=row.tensors.history.copy(),
                world=donor.tensors.world.copy(),
                perspective=row.tensors.perspective.copy())
            tensors.validate()
            controls.append(_row(
                row, "complete-world-shuffle", tensors, row.successor_sha256,
                row.successor_sha256, row.signed_level_category, donor_root))
    controls.sort(key=lambda value: (value.root_key, value.candidate_index, value.replica))
    ordered = sorted(natural, key=lambda value: (value.root_key,
                                                  value.candidate_index,
                                                  value.replica))
    eligible_ordered = [row for row in ordered if row.root_key in eligible_roots]
    eligible_controls = [row for row in controls if row.root_key in eligible_roots]
    changed = sum(not np.array_equal(row.tensors.world, source.tensors.world)
                  for row, source in zip(eligible_controls,
                                         eligible_ordered, strict=True))
    # A world control with an accidental identical tensor is not informative.
    evidence = _evidence("complete-world-shuffle", seed, ordered, controls,
                         changed_rows=changed,
                         changed_cells=changed,
                         eligible_rows=len(eligible_ordered),
                         eligible_cells=len(eligible_ordered))
    return tuple(controls), evidence


def control_training_examples(
        values: Sequence[ControlledWorldAfterstateV2Example], *,
        split: str = "fit", cohort: str = "control") \
        -> tuple[WorldAfterstateV2TrainingExample, ...]:
    """Build transformed rows while preserving immutable natural root keys."""
    if type(values) not in (list, tuple) or not values or split != "fit":
        raise WorldAfterstateV2ControlError("control batch population drift")
    if any(type(value) is not ControlledWorldAfterstateV2Example for value in values):
        raise WorldAfterstateV2ControlError("control batch row type drift")
    names = {value.control_name for value in values}
    if len(names) != 1:
        raise WorldAfterstateV2ControlError("control mix is not homogeneous")
    by_root: dict[str, list[ControlledWorldAfterstateV2Example]] = defaultdict(list)
    for value in values:
        value.validate()
        by_root[value.root_key].append(value)
    rows: list[WorldAfterstateV2TrainingExample] = []
    for root in sorted(by_root):
        group = sorted(by_root[root], key=lambda value: (value.candidate_index,
                                                           value.replica))
        successors = [next(value.successor_sha256 for value in group
                           if value.candidate_index == candidate)
                      for candidate in sorted({value.candidate_index for value in group})]
        cset = _candidate_set(group[0].natural.state_sha256, successors)
        for value in group:
            source = value.natural
            rows.append(WorldAfterstateV2TrainingExample(
                deal_sha256=source.deal_sha256, slot_sha256=source.slot_sha256,
                state_sha256=source.state_sha256, candidate_set_sha256=cset,
                candidate_index=source.candidate_index,
                protected_incumbent=source.protected_incumbent,
                successor_sha256=value.successor_sha256,
                continuation_sha256=source.continuation_sha256,
                replica=source.replica, source=source.source, split=split,
                role=source.role, phase=source.phase, position=source.position,
                trump_rank=source.trump_rank, trump_mode=source.trump_mode,
                points_bucket=source.points_bucket,
                tensors=_clone(value.tensors),
                signed_level_category=value.target_category, cohort=cohort))
    result = tuple(rows)
    try:
        collate_training_examples(result, split=split, cohort=cohort).validate()
    except WorldAfterstateV2TrainingError as exc:
        raise WorldAfterstateV2ControlError("control batch binding drift") from exc
    return result


def collate_control_training_examples(
        values: Sequence[ControlledWorldAfterstateV2Example], *,
        split: str = "fit", cohort: str = "control"):
    """Bind one homogeneous control population to the normal training batch."""
    rows = control_training_examples(values, split=split, cohort=cohort)
    try:
        return collate_training_examples(rows, split=split, cohort=cohort)
    except WorldAfterstateV2TrainingError as exc:
        raise WorldAfterstateV2ControlError("control batch binding drift") from exc


def mix_control_populations(*populations: Sequence[ControlledWorldAfterstateV2Example]) \
        -> tuple[ControlledWorldAfterstateV2Example, ...]:
    """Reject mixed control names and duplicate natural rows."""
    if not populations or any(type(population) not in (list, tuple)
                              or not population for population in populations):
        raise WorldAfterstateV2ControlError("control mix population drift")
    rows = [row for population in populations for row in population]
    if any(type(row) is not ControlledWorldAfterstateV2Example for row in rows):
        raise WorldAfterstateV2ControlError("control mix row type drift")
    if len({row.control_name for row in rows}) != 1:
        raise WorldAfterstateV2ControlError("control mix contains multiple controls")
    keys = [row.example_key for row in rows]
    if len(set(keys)) != len(keys):
        raise WorldAfterstateV2ControlError("control mix duplicate row")
    for row in rows:
        row.validate()
    return tuple(sorted(rows, key=lambda row: (row.root_key, row.candidate_index,
                                               row.replica)))


def validate_control_evidence(value: Mapping[str, Any], *,
                              natural: Sequence[WorldAfterstateV2TrainingExample] | None = None,
                              controlled: Sequence[ControlledWorldAfterstateV2Example] | None = None) -> None:
    """Rebuild receipt hashes/doses; optionally rederive the named transform."""
    if type(value) is not dict or value.get("schema") != CONTROL_EVIDENCE_SCHEMA \
            or value.get("control_name") not in CONTROL_NAMES \
            or value.get("name") != value.get("control_name") \
            or value.get("authority") != AUTHORITY:
        raise WorldAfterstateV2ControlError("control evidence schema drift")
    required_ints = ("seed", "row_count", "eligible_row_count", "eligible_cell_count",
                     "changed_row_count", "changed_cell_count", "changed_count",
                     "row_dose_ppm", "cell_dose_ppm", "dose_ppm",
                     "effective_changed_count", "effective_dose_ppm",
                     "required_minimum_dose_ppm",
                     "required_minimum_effective_dose_ppm", "root_count")
    if any(isinstance(value.get(key), bool) or not isinstance(value.get(key), int)
           for key in required_ints):
        raise WorldAfterstateV2ControlError("control evidence integer drift")
    _seed(value["seed"])
    n = value["row_count"]
    er, ec = value["eligible_row_count"], value["eligible_cell_count"]
    cr, cc = value["changed_row_count"], value["changed_cell_count"]
    if n <= 0 or not (0 <= cr <= er <= n and 0 <= cc <= ec <= n) \
            or value["changed_count"] != cr \
            or value["effective_changed_count"] != cc \
            or value["row_dose_ppm"] != (cr * 1_000_000 // er if er else 0) \
            or value["cell_dose_ppm"] != (cc * 1_000_000 // ec if ec else 0) \
            or value["dose_ppm"] != value["row_dose_ppm"] \
            or value["effective_dose_ppm"] != value["cell_dose_ppm"] \
            or value["row_dose_ppm"] < value["required_minimum_dose_ppm"] \
            or value["cell_dose_ppm"] < value["required_minimum_effective_dose_ppm"]:
        raise WorldAfterstateV2ControlError("control evidence dose reconstruction drift")
    source_sha = _digest(value.get("source_population_sha256"), "control source SHA-256")
    if value.get("input_population_sha256") != source_sha:
        raise WorldAfterstateV2ControlError("control source digest alias drift")
    _digest(value.get("output_population_sha256"), "control output SHA-256")
    body = {key: item for key, item in value.items() if key != "evidence_sha256"}
    _digest(value.get("evidence_sha256"), "control evidence SHA-256")
    if value["evidence_sha256"] != _sha(body):
        raise WorldAfterstateV2ControlError("control evidence hash drift")
    if natural is not None or controlled is not None:
        if natural is None or controlled is None:
            raise WorldAfterstateV2ControlError("control evidence population pairing drift")
        if value["control_name"] == "action-association-permutation":
            expected, expected_receipt = action_association_permutation(
                natural, seed=value["seed"])
        elif value["control_name"] == "label-permutation":
            expected, expected_receipt = label_permutation(
                natural, seed=value["seed"])
        else:
            expected, expected_receipt = complete_world_shuffle(
                natural, seed=value["seed"])
        if _controlled_binding(expected) != _controlled_binding(controlled):
            raise WorldAfterstateV2ControlError("control transform reconstruction drift")
        if expected_receipt != dict(value):
            raise WorldAfterstateV2ControlError("control receipt reconstruction drift")


__all__ = [
    "AUTHORITY", "CONTROL_EVIDENCE_SCHEMA", "CONTROL_NAMES",
    "CONTROL_ROW_SCHEMA", "ControlledWorldAfterstateV2Example",
    "MINIMUM_LABEL_EFFECTIVE_DOSE_PPM", "MINIMUM_PERMUTATION_DOSE_PPM",
    "WorldAfterstateV2ControlError", "action_association_permutation",
    "complete_world_shuffle", "collate_control_training_examples",
    "control_training_examples",
    "label_permutation", "mix_control_populations", "validate_control_evidence",
]

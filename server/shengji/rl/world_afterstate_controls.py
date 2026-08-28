"""Executable E4 negative-control transformations.

These controls transform already-authenticated rows; they never generate a
label, choose a model, open a split, or decide a terminal result.  Every
transformation publishes its dose and exact input/output population hashes so
the scientific controller cannot replace a real ablation with a literal name.
"""

from __future__ import annotations

import copy
import hashlib
from collections import defaultdict
from dataclasses import replace
from typing import Any, Mapping, Sequence

import numpy as np

from .belief_contract import canonical_json_bytes
from .world_afterstate import (
    WorldAfterstateError, WorldAfterstateExampleV0, WorldAfterstateTensorsV0,
    bind_outcome_to_afterstate, build_outcome, reopen_afterstate_audit)
from .world_afterstate_dataset import (
    ReopenedDatasetRowV0, WorldAfterstateDatasetError,
    validate_dataset_row_static)
from .world_afterstate_evaluation import EvaluationOutcomeV0


TRANSFORM_SCHEMA = "world-afterstate-e4-control-transform-v0"
MUTATION_SCHEMA = "world-afterstate-e4-mutation-refusals-v0"
MUTATION_NAMES = (
    "transition", "ballot", "continuation", "perspective", "utility")
CONTROL_AUTHORITY = {
    "report_opening_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "deployment_authorized": False,
}


class WorldAfterstateControlError(ValueError):
    """A control input, dose, output, or evidence binding drifted."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateControlError(f"{label} drift")
    return value


def _outcome_binding(value: EvaluationOutcomeV0) -> dict[str, Any]:
    value.validate()
    return {
        "deal_group_sha256": value.deal_group_sha256,
        "state_group_id": value.state_group_id,
        "candidate_index": value.candidate_index,
        "replicate": value.replicate,
        "successor_sha256": value.successor_sha256,
        "stratum": list(value.stratum()),
        "signed_level_category": value.signed_level_category,
    }


def tensor_sha256(value: WorldAfterstateTensorsV0) -> str:
    value.validate()
    digest = hashlib.sha256(canonical_json_bytes({
        "schema": "world-afterstate-control-tensor-binding-v0",
        "arrays": ["public", "history", "world", "perspective"],
    }))
    for name in ("public", "history", "world", "perspective"):
        array = getattr(value, name).astype("<f4", copy=False)
        header = canonical_json_bytes({
            "name": name, "shape": list(array.shape),
            "dtype": "little-endian-float32", "byte_count": array.nbytes,
        })
        digest.update(len(header).to_bytes(8, "big"))
        digest.update(header)
        digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


def _evidence(
        *, name: str, row_count: int, changed_count: int,
        input_population_sha256: str,
        output_population_sha256: str) -> dict[str, Any]:
    if name not in (
            "geometry-preserving-label-permutation",
            "preaction-state-replacement",
            "complete-world-shuffle") \
            or isinstance(row_count, bool) or not isinstance(row_count, int) \
            or isinstance(changed_count, bool) \
            or not isinstance(changed_count, int) \
            or not 0 <= changed_count <= row_count:
        raise WorldAfterstateControlError("control transform dose drift")
    _digest(input_population_sha256, "control input population SHA-256")
    _digest(output_population_sha256, "control output population SHA-256")
    informative = changed_count > 0
    if (input_population_sha256 != output_population_sha256) \
            is not informative:
        raise WorldAfterstateControlError(
            "control transform dose/hash mismatch")
    body = {
        "schema": TRANSFORM_SCHEMA,
        "name": name,
        "row_count": row_count,
        "changed_count": changed_count,
        "informative": informative,
        "input_population_sha256": input_population_sha256,
        "output_population_sha256": output_population_sha256,
        "authority": dict(CONTROL_AUTHORITY),
    }
    return {**body, "transform_sha256": _sha(body)}


def validate_transform_evidence(value: Mapping[str, Any]) -> None:
    required = {
        "schema", "name", "row_count", "changed_count",
        "informative",
        "input_population_sha256", "output_population_sha256",
        "authority", "transform_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != TRANSFORM_SCHEMA \
            or value.get("authority") != CONTROL_AUTHORITY:
        raise WorldAfterstateControlError("control evidence schema drift")
    expected = _evidence(
        name=value["name"], row_count=value["row_count"],
        changed_count=value["changed_count"],
        input_population_sha256=value["input_population_sha256"],
        output_population_sha256=value["output_population_sha256"])
    if canonical_json_bytes(expected) != canonical_json_bytes(dict(value)):
        raise WorldAfterstateControlError(
            "control evidence reconstruction drift")


def geometry_preserving_label_permutation(
        outcomes: Sequence[EvaluationOutcomeV0]) \
        -> tuple[tuple[EvaluationOutcomeV0, ...], dict[str, Any]]:
    """Rotate raw labels within the exact public geometry stratum."""
    if type(outcomes) not in (list, tuple) or not outcomes:
        raise WorldAfterstateControlError(
            "label-permutation population drift")
    rows = list(outcomes)
    bindings = [_outcome_binding(row) for row in rows]
    keys = [(row.state_group_id, row.candidate_index, row.replicate)
            for row in rows]
    if len(keys) != len(set(keys)) or {row.fold for row in rows} != {"report"}:
        raise WorldAfterstateControlError(
            "label-permutation identity drift")
    buckets: dict[tuple[str, ...], list[EvaluationOutcomeV0]] = defaultdict(list)
    for row in rows:
        buckets[row.stratum()].append(row)
    replacements: dict[tuple[str, int, int], int] = {}
    for bucket_rows in buckets.values():
        ordered = sorted(bucket_rows, key=lambda row: (
            row.state_group_id, row.candidate_index, row.replicate))
        categories = [row.signed_level_category for row in ordered]
        rotated = categories[1:] + categories[:1]
        for row, category in zip(ordered, rotated, strict=True):
            replacements[row.key()] = category
    transformed = tuple(replace(
        row, signed_level_category=replacements[row.key()]) for row in rows)
    for row in transformed:
        row.validate()
    changed = sum(left.signed_level_category != right.signed_level_category
                  for left, right in zip(rows, transformed, strict=True))
    output_bindings = [_outcome_binding(row) for row in transformed]
    evidence = _evidence(
        name="geometry-preserving-label-permutation",
        row_count=len(rows), changed_count=changed,
        input_population_sha256=_sha(bindings),
        output_population_sha256=_sha(output_bindings))
    return transformed, evidence


def complete_world_shuffle(
        example_keys: Sequence[str],
        examples: Sequence[WorldAfterstateExampleV0]) \
        -> tuple[tuple[WorldAfterstateExampleV0, ...], dict[str, Any]]:
    """Deterministically rotate only complete-world tensors across rows."""
    if type(example_keys) not in (list, tuple) \
            or type(examples) not in (list, tuple) or len(examples) < 2 \
            or len(example_keys) != len(examples) \
            or any(type(key) is not str or not key or not key.isascii()
                   for key in example_keys) \
            or len(set(example_keys)) != len(example_keys) \
            or any(type(example) is not WorldAfterstateExampleV0
                   for example in examples):
        raise WorldAfterstateControlError("world-shuffle population drift")
    for example in examples:
        example.validate()
    order = sorted(range(len(examples)), key=lambda index: (
        hashlib.sha256(canonical_json_bytes({
            "namespace": "world-afterstate-complete-world-shuffle-v0",
            "example_key": example_keys[index],
        })).hexdigest(), example_keys[index]))
    donor_for = {
        order[index]: order[(index + 1) % len(order)]
        for index in range(len(order))
    }
    transformed = []
    for index, example in enumerate(examples):
        donor = examples[donor_for[index]]
        tensors = WorldAfterstateTensorsV0(
            public=example.tensors.public.copy(),
            history=example.tensors.history.copy(),
            world=donor.tensors.world.copy(),
            perspective=example.tensors.perspective.copy())
        value = WorldAfterstateExampleV0(
            tensors=tensors,
            signed_level_category=example.signed_level_category,
            successor_sha256=example.successor_sha256)
        value.validate()
        transformed.append(value)
    changed = sum(not np.array_equal(
        original.tensors.world, altered.tensors.world)
        for original, altered in zip(examples, transformed, strict=True))
    input_rows = [{"key": key,
                   "tensor_sha256": tensor_sha256(example.tensors)}
                  for key, example in zip(example_keys, examples, strict=True)]
    output_rows = [{"key": key,
                    "tensor_sha256": tensor_sha256(example.tensors)}
                   for key, example in zip(
                       example_keys, transformed, strict=True)]
    evidence = _evidence(
        name="complete-world-shuffle", row_count=len(examples),
        changed_count=changed, input_population_sha256=_sha(input_rows),
        output_population_sha256=_sha(output_rows))
    return tuple(transformed), evidence


def preaction_replacement_evidence(
        example_keys: Sequence[str],
        successor_examples: Sequence[WorldAfterstateExampleV0],
        preaction_examples: Sequence[WorldAfterstateExampleV0]) \
        -> dict[str, Any]:
    """Bind the actual pre-action inputs used by the action-ranking control."""
    if type(example_keys) not in (list, tuple) \
            or type(successor_examples) not in (list, tuple) \
            or type(preaction_examples) not in (list, tuple) \
            or not successor_examples \
            or len(example_keys) != len(successor_examples) \
            or len(example_keys) != len(preaction_examples) \
            or len(set(example_keys)) != len(example_keys) \
            or any(type(key) is not str or not key or not key.isascii()
                   for key in example_keys) \
            or any(type(example) is not WorldAfterstateExampleV0
                   for example in (*successor_examples, *preaction_examples)):
        raise WorldAfterstateControlError(
            "preaction-replacement population drift")
    for successor, preaction in zip(
            successor_examples, preaction_examples, strict=True):
        successor.validate()
        preaction.validate()
        if successor.successor_sha256 != preaction.successor_sha256 \
                or successor.signed_level_category \
                != preaction.signed_level_category:
            raise WorldAfterstateControlError(
                "preaction-replacement target binding drift")
    input_rows = [{"key": key,
                   "tensor_sha256": tensor_sha256(example.tensors)}
                  for key, example in zip(
                      example_keys, successor_examples, strict=True)]
    output_rows = [{"key": key,
                    "tensor_sha256": tensor_sha256(example.tensors)}
                   for key, example in zip(
                       example_keys, preaction_examples, strict=True)]
    changed = sum(left["tensor_sha256"] != right["tensor_sha256"]
                  for left, right in zip(input_rows, output_rows, strict=True))
    return _evidence(
        name="preaction-state-replacement", row_count=len(example_keys),
        changed_count=changed, input_population_sha256=_sha(input_rows),
        output_population_sha256=_sha(output_rows))


def build_mutation_refusal_evidence(
        rows: Sequence[ReopenedDatasetRowV0],
        groups: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Execute the five frozen corruptions against real reopened evidence."""
    if type(rows) not in (list, tuple) or not rows or type(groups) is not dict:
        raise WorldAfterstateControlError(
            "mutation refusal population drift")
    usable = []
    for reopened in rows:
        if type(reopened) is not ReopenedDatasetRowV0 \
                or type(reopened.row) is not dict:
            raise WorldAfterstateControlError(
                "mutation refusal row drift")
        group = groups.get(reopened.evaluation_outcome.state_group_id)
        if type(group) is not dict:
            raise WorldAfterstateControlError(
                "mutation refusal group drift")
        validate_dataset_row_static(reopened.row, group=group)
        usable.append((reopened, group))

    base, base_group = usable[0]
    sibling_pair = None
    by_state: dict[str, list[tuple[ReopenedDatasetRowV0,
                                  Mapping[str, Any]]]] = defaultdict(list)
    for item in usable:
        by_state[item[0].evaluation_outcome.state_group_id].append(item)
    for state_rows in by_state.values():
        by_candidate = {}
        for item in state_rows:
            by_candidate.setdefault(
                item[0].evaluation_outcome.candidate_index, item)
        if len(by_candidate) >= 2:
            ordered = [by_candidate[key] for key in sorted(by_candidate)[:2]]
            sibling_pair = (ordered[0], ordered[1])
            break
    if sibling_pair is None:
        raise WorldAfterstateControlError(
            "mutation refusal lacks sibling ballot")

    evidence_rows = []

    def refused(name: str, source: object, mutated: object,
                function, message: str) -> None:
        try:
            function()
        except (WorldAfterstateError, WorldAfterstateDatasetError) as exc:
            if message not in str(exc):
                raise WorldAfterstateControlError(
                    f"{name} mutation reached wrong refusal") from exc
            evidence_rows.append({
                "name": name,
                "input_sha256": _sha(source),
                "mutation_sha256": _sha(mutated),
                "refusal": message,
            })
        else:
            raise WorldAfterstateControlError(
                f"{name} mutation was not refused")

    # Transition: even a coordinated replacement of stored successor bytes
    # and their digest cannot replace the engine replay.
    transition = copy.deepcopy(base.row["audit"])
    transition["successor"]["public"]["attacker_points"] += 10
    transition["successor_sha256"] = _sha(transition["successor"])
    refused("transition", base.row["audit"], transition,
            lambda: reopen_afterstate_audit(transition),
            "successor reconstruction drift")

    # Ballot: a real sibling audit cannot be rebound to candidate zero.
    (ballot_base, ballot_group), (ballot_donor, _donor_group) = sibling_pair
    ballot = copy.deepcopy(ballot_base.row)
    ballot["audit"] = copy.deepcopy(ballot_donor.row["audit"])
    ballot["audit_sha256"] = hashlib.sha256(
        canonical_json_bytes(ballot["audit"])).hexdigest()
    refused("ballot", ballot_base.row, ballot,
            lambda: validate_dataset_row_static(ballot, group=ballot_group),
            "dataset row static byte binding drift")

    # Continuation: identity changes cannot be hidden by repairing the
    # embedded continuation digest.
    continuation = copy.deepcopy(base.row)
    continuation["continuation"]["continuation_identity"]["replicate"] += 1
    continuation["continuation_sha256"] = hashlib.sha256(
        canonical_json_bytes(continuation["continuation"])).hexdigest()
    refused("continuation", base.row, continuation,
            lambda: validate_dataset_row_static(
                continuation, group=base_group),
            "dataset row static continuation identity drift")

    outcome = base.row["continuation"]["outcome"]
    perspective = build_outcome(
        outcome["successor_sha256"], outcome["attacker_points"],
        not outcome["root_is_attacker"])
    refused("perspective", outcome, perspective,
            lambda: bind_outcome_to_afterstate(
                base.row["audit"], perspective),
            "outcome root perspective binding drift")

    utility = copy.deepcopy(outcome)
    utility["signed_level_utility"] += 1
    refused("utility", outcome, utility,
            lambda: bind_outcome_to_afterstate(base.row["audit"], utility),
            "afterstate outcome derivation drift")

    ordered = sorted(evidence_rows, key=lambda row: row["name"])
    if [row["name"] for row in ordered] != sorted(MUTATION_NAMES):
        raise WorldAfterstateControlError(
            "mutation refusal result population drift")
    body = {
        "schema": MUTATION_SCHEMA,
        "rows": ordered,
        "all_refused": True,
        "authority": dict(CONTROL_AUTHORITY),
    }
    return {**body, "mutation_evidence_sha256": _sha(body)}


def validate_mutation_refusal_evidence(value: Mapping[str, Any]) -> None:
    if type(value) is not dict or set(value) != {
            "schema", "rows", "all_refused", "authority",
            "mutation_evidence_sha256"} \
            or value.get("schema") != MUTATION_SCHEMA \
            or value.get("authority") != CONTROL_AUTHORITY \
            or value.get("all_refused") is not True \
            or type(value.get("rows")) is not list \
            or [row.get("name") for row in value["rows"]] \
            != sorted(MUTATION_NAMES):
        raise WorldAfterstateControlError(
            "mutation evidence schema drift")
    for row in value["rows"]:
        if type(row) is not dict or set(row) != {
                "name", "input_sha256", "mutation_sha256", "refusal"} \
                or type(row["refusal"]) is not str or not row["refusal"]:
            raise WorldAfterstateControlError(
                "mutation evidence row drift")
        _digest(row["input_sha256"], "mutation input SHA-256")
        _digest(row["mutation_sha256"], "mutation output SHA-256")
        if row["input_sha256"] == row["mutation_sha256"]:
            raise WorldAfterstateControlError(
                "mutation evidence has zero dose")
    body = {key: item for key, item in value.items()
            if key != "mutation_evidence_sha256"}
    if value.get("mutation_evidence_sha256") != _sha(body):
        raise WorldAfterstateControlError(
            "mutation evidence reconstruction drift")


__all__ = [
    "CONTROL_AUTHORITY", "MUTATION_NAMES", "MUTATION_SCHEMA",
    "TRANSFORM_SCHEMA", "WorldAfterstateControlError",
    "build_mutation_refusal_evidence",
    "complete_world_shuffle", "geometry_preserving_label_permutation",
    "preaction_replacement_evidence", "tensor_sha256",
    "validate_mutation_refusal_evidence", "validate_transform_evidence",
]

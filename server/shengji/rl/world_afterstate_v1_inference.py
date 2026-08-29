"""Outcome-blind calibration input construction for Value V1.

This module accepts only the frozen public population metadata and private
engine audit bytes.  It has no outcome, dataset-row, target, report, training,
gameplay, strength, merge, promotion, deployment, retry, or R5 input surface.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate import (
    actor_visible_root_identity, build_afterstate_tensors,
    replay_canonical_successor)
from .world_afterstate_population import (
    validate_population_audit_manifest, validate_population_manifest)
from .world_afterstate_v1_evaluation import (
    AdvantageInferenceBatchV1, collate_inference_pairs,
    inference_population_sha256)
from .world_afterstate_v1_model import successor_tensor_sha256


CALIBRATION_FOLD = "calibration"
MANIFEST_SCHEMA = "world-afterstate-v1-calibration-input-manifest-v1"
AUTHORITY = {
    "outcome_opening_authorized": False,
    "report_row_opening_authorized": False,
    "provider_audit_row_opening_authorized": False,
    "training_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
    "r5_authorized": False,
}
INFERENCE_INPUT_NAMES = ("natural", "identical-successor")
COHORT_INPUT_NAMES = {
    "natural": "natural",
    "identical-successor": "identical-successor",
    "action-association-permutation": "natural",
    "label-permutation": "natural",
}


class WorldAfterstateV1InferenceError(ValueError):
    """A target-free audit, ballot, tensor, or population binding drifted."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _strict_audit(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes:
        raise WorldAfterstateV1InferenceError(
            "calibration audit byte type drift")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateV1InferenceError(
            "calibration audit is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstateV1InferenceError(
            "calibration audit is not canonical JSON")
    return value


def build_calibration_inference_batch(
        population_manifest: Mapping[str, Any],
        audit_manifest: Mapping[str, Any],
        materials: Mapping[str, Sequence[bytes]]) \
        -> tuple[dict[str, AdvantageInferenceBatchV1], dict[str, Any]]:
    """Rebuild exact calibration successors without receiving any label.

    Candidate zero is the protected incumbent.  Every later candidate is
    paired with it after all actions have been independently reapplied through
    the engine by :func:`build_afterstate_tensors`.
    """
    try:
        validate_population_manifest(population_manifest)
        validate_population_audit_manifest(
            audit_manifest, population_manifest)
    except ValueError as exc:
        raise WorldAfterstateV1InferenceError(
            "calibration public manifest drift") from exc
    groups = sorted(
        (group for group in population_manifest["groups"]
         if group["fold"] == CALIBRATION_FOLD),
        key=lambda group: group["state_group_id"])
    expected_states = {group["state_group_id"] for group in groups}
    if type(materials) is not dict or not groups \
            or set(materials) != expected_states:
        raise WorldAfterstateV1InferenceError(
            "calibration audit population drift")

    state_ids: list[str] = []
    candidate_indexes: list[int] = []
    incumbent_successors: list[str] = []
    candidate_successors: list[str] = []
    incumbent_tensors = []
    candidate_tensors = []
    audit_bindings = []
    for group in groups:
        state = group["state_group_id"]
        raws = materials[state]
        if type(raws) is not tuple \
                or len(raws) != group["candidate_count"]:
            raise WorldAfterstateV1InferenceError(
                "calibration audit ballot population drift")
        audits = []
        tensors = []
        for index, (raw, candidate) in enumerate(zip(
                raws, group["candidates"], strict=True)):
            audit = _strict_audit(raw)
            if hashlib.sha256(raw).hexdigest() \
                    != candidate["audit_sha256"] \
                    or audit.get("successor_sha256") \
                    != candidate["successor_sha256"] \
                    or _sha(audit.get("attempted_action")) \
                    != candidate["action_sha256"]:
                raise WorldAfterstateV1InferenceError(
                    "calibration audit candidate binding drift")
            try:
                tensor = build_afterstate_tensors(audit)
            except ValueError as exc:
                raise WorldAfterstateV1InferenceError(
                    "calibration audit engine reconstruction drift") from exc
            audits.append(audit)
            tensors.append(tensor)
            audit_bindings.append({
                "state_group_id": state,
                "candidate_index": index,
                "audit_sha256": candidate["audit_sha256"],
                "successor_sha256": candidate["successor_sha256"],
            })

        prestate_raw = canonical_json_bytes(audits[0]["prestate"])
        if any(audit["prestate_sha256"] \
               != audits[0]["prestate_sha256"]
               or audit["root_seat"] != audits[0]["root_seat"]
               or canonical_json_bytes(audit["prestate"]) != prestate_raw
               for audit in audits[1:]):
            raise WorldAfterstateV1InferenceError(
                "calibration sibling root binding drift")
        try:
            root = replay_canonical_successor(audits[0]["prestate"])
            actor = actor_visible_root_identity(
                root, 0, [audit["attempted_action"] for audit in audits])
        except ValueError as exc:
            raise WorldAfterstateV1InferenceError(
                "calibration actor-visible reconstruction drift") from exc
        if actor["decision_sha256"] != group["decision_sha256"]:
            raise WorldAfterstateV1InferenceError(
                "calibration actor-visible binding drift")

        for index in range(1, group["candidate_count"]):
            state_ids.append(state)
            candidate_indexes.append(index)
            incumbent_successors.append(
                group["candidates"][0]["successor_sha256"])
            candidate_successors.append(
                group["candidates"][index]["successor_sha256"])
            incumbent_tensors.append(tensors[0])
            candidate_tensors.append(tensors[index])
    expected_pairs = sum(group["candidate_count"] - 1 for group in groups)
    if expected_pairs <= 0 or len(state_ids) != expected_pairs:
        raise WorldAfterstateV1InferenceError(
            "calibration inference pair population drift")
    try:
        natural_batch = collate_inference_pairs(
            state_group_ids=state_ids,
            candidate_indexes=candidate_indexes,
            incumbent_successor_sha256s=incumbent_successors,
            candidate_successor_sha256s=candidate_successors,
            incumbent_tensors=incumbent_tensors,
            candidate_tensors=candidate_tensors)
        identical_batch = collate_inference_pairs(
            state_group_ids=state_ids,
            candidate_indexes=candidate_indexes,
            incumbent_successor_sha256s=incumbent_successors,
            candidate_successor_sha256s=candidate_successors,
            incumbent_tensors=incumbent_tensors,
            candidate_tensors=incumbent_tensors)
    except ValueError as exc:
        raise WorldAfterstateV1InferenceError(
            "calibration inference collation drift") from exc
    changed_pairs = sum(
        successor_tensor_sha256(incumbent)
        != successor_tensor_sha256(candidate)
        for incumbent, candidate in zip(
            incumbent_tensors, candidate_tensors, strict=True))
    if changed_pairs != expected_pairs \
            or inference_population_sha256(natural_batch) \
            == inference_population_sha256(identical_batch):
        raise WorldAfterstateV1InferenceError(
            "calibration identical-successor control dose drift")
    batches = {
        "natural": natural_batch,
        "identical-successor": identical_batch,
    }
    body = {
        "schema": MANIFEST_SCHEMA,
        "population_manifest_sha256":
            population_manifest["manifest_sha256"],
        "audit_manifest_sha256": audit_manifest["manifest_sha256"],
        "fold": CALIBRATION_FOLD,
        "group_count": len(groups),
        "pair_count": expected_pairs,
        "audit_count": len(audit_bindings),
        "audit_population_sha256": _sha(audit_bindings),
        "inference_population_sha256s": {
            name: inference_population_sha256(batches[name])
            for name in INFERENCE_INPUT_NAMES
        },
        "cohort_input_names": dict(COHORT_INPUT_NAMES),
        "identical_successor_changed_pair_count": changed_pairs,
        "identical_successor_dose_ppm":
            changed_pairs * 1_000_000 // expected_pairs,
        "contains_outcome_labels": False,
        "report_rows_opened": False,
        "provider_audit_rows_opened": False,
        "authority": dict(AUTHORITY),
    }
    return batches, {**body, "manifest_sha256": _sha(body)}


def validate_calibration_inference_build(
        batches: Mapping[str, AdvantageInferenceBatchV1],
        manifest: Mapping[str, Any],
        population_manifest: Mapping[str, Any],
        audit_manifest: Mapping[str, Any],
        materials: Mapping[str, Sequence[bytes]]) -> None:
    """Independently reconstruct every input and the sealed manifest."""
    if type(batches) is not dict \
            or set(batches) != set(INFERENCE_INPUT_NAMES) \
            or any(type(batch) is not AdvantageInferenceBatchV1
                   for batch in batches.values()) \
            or type(manifest) is not dict:
        raise WorldAfterstateV1InferenceError(
            "calibration inference build identity drift")
    rebuilt_batches, rebuilt_manifest = build_calibration_inference_batch(
        population_manifest, audit_manifest, materials)
    if any(inference_population_sha256(batches[name])
           != inference_population_sha256(rebuilt_batches[name])
           for name in INFERENCE_INPUT_NAMES) \
            or canonical_json_bytes(dict(manifest)) \
            != canonical_json_bytes(rebuilt_manifest):
        raise WorldAfterstateV1InferenceError(
            "calibration inference build reconstruction drift")


def validate_calibration_inference_manifest(value: object) -> None:
    required = {
        "schema", "population_manifest_sha256", "audit_manifest_sha256",
        "fold", "group_count", "pair_count", "audit_count",
        "audit_population_sha256", "inference_population_sha256s",
        "cohort_input_names", "identical_successor_changed_pair_count",
        "identical_successor_dose_ppm",
        "contains_outcome_labels", "report_rows_opened",
        "provider_audit_rows_opened", "authority", "manifest_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != MANIFEST_SCHEMA \
            or value.get("fold") != CALIBRATION_FOLD \
            or value.get("contains_outcome_labels") is not False \
            or value.get("report_rows_opened") is not False \
            or value.get("provider_audit_rows_opened") is not False \
            or value.get("cohort_input_names") != COHORT_INPUT_NAMES \
            or value.get("authority") != AUTHORITY:
        raise WorldAfterstateV1InferenceError(
            "calibration inference manifest identity drift")
    for key in (
            "population_manifest_sha256", "audit_manifest_sha256",
            "audit_population_sha256", "manifest_sha256"):
        item = value.get(key)
        if type(item) is not str or len(item) != 64 \
                or any(char not in "0123456789abcdef" for char in item):
            raise WorldAfterstateV1InferenceError(
                "calibration inference manifest digest drift")
    input_shas = value.get("inference_population_sha256s")
    if type(input_shas) is not dict \
            or set(input_shas) != set(INFERENCE_INPUT_NAMES):
        raise WorldAfterstateV1InferenceError(
            "calibration inference manifest input population drift")
    for item in input_shas.values():
        if type(item) is not str or len(item) != 64 \
                or any(char not in "0123456789abcdef" for char in item):
            raise WorldAfterstateV1InferenceError(
                "calibration inference manifest digest drift")
    changed = value.get("identical_successor_changed_pair_count")
    dose = value.get("identical_successor_dose_ppm")
    if isinstance(changed, bool) or not isinstance(changed, int) \
            or changed != value.get("pair_count") \
            or isinstance(dose, bool) or not isinstance(dose, int) \
            or dose != 1_000_000 \
            or input_shas["natural"] == input_shas["identical-successor"]:
        raise WorldAfterstateV1InferenceError(
            "calibration inference manifest control dose drift")
    for key in ("group_count", "pair_count", "audit_count"):
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
            raise WorldAfterstateV1InferenceError(
                "calibration inference manifest population drift")
    if value["audit_count"] != value["group_count"] + value["pair_count"]:
        raise WorldAfterstateV1InferenceError(
            "calibration inference manifest population drift")
    body = {key: item for key, item in value.items()
            if key != "manifest_sha256"}
    if value["manifest_sha256"] != _sha(body):
        raise WorldAfterstateV1InferenceError(
            "calibration inference manifest reconstruction drift")


__all__ = [
    "AUTHORITY", "CALIBRATION_FOLD", "COHORT_INPUT_NAMES",
    "INFERENCE_INPUT_NAMES", "MANIFEST_SCHEMA",
    "WorldAfterstateV1InferenceError", "build_calibration_inference_batch",
    "validate_calibration_inference_build",
    "validate_calibration_inference_manifest",
]

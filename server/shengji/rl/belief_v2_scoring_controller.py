"""Split-safe artifact readers for BELIEF-V1 V2 calibration and test scoring.

The calibration reader authenticates the complete capture/reference directory
population but opens only the named calibration private/reference bytes.  The
same low-level reader can open test only when called by the future durable
single-test-attempt controller.

This module publishes nothing yet and grants no test-open, sampler, gameplay,
strength, or deployment authority.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path

from .belief_artifacts import (
    reopen_reference_external_actor_batch_bundle,
    reopen_capture_bundle,
    reopen_reference_round_bundle,
    stable_read_bytes,
)
from .belief_capture import reopen_captured_round_artifacts
from .belief_contract import canonical_json_bytes
from .belief_evaluation import reopen_score_pair
from .belief_v2_common_surface import build_common_surface_tensors
from .belief_v2_controller import (
    BeliefV2ControllerError,
    reopen_actor_capture_lane_manifest,
    reopen_reference_lane_manifest,
)
from .belief_v2_freeze import V2ExecutionFreezeV1, V2PipelineAdmissionV1
from .belief_v2_freeze import PRIMARY_COHORT_ID
from .belief_v2_human_corpus import UNIVERSAL_POLICY_IDS
from .belief_v2_human_corpus import validate_human_corpus_pair
from .belief_v2_human_controller import reopen_human_group_manifest
from .belief_v2_human_reference_controller import (
    reopen_human_reference_group,
)
from .belief_v2_protocol import V2RoundCoordinate, v2_policy_seeds
from .belief_v2_scoring import (
    V2CohortModelsV1,
    V2ScoringDecisionV1,
    cohort_models_from_trained,
    v2_scoring_actor,
)
from .belief_v2_training_controller import reopen_training_cohort
from .belief_v2_streaming_inputs import (
    V2StreamingTrainingInputsV1,
    validate_streaming_training_inputs,
)
from .belief_v2_tensor_cache_controller import (
    reopen_training_tensor_cache,
)
from .belief_v2_device_controller import reopen_device_qualification
from .belief_v2_device_qualification import (
    V2DeviceQualificationPlanV1,
    V2DeviceQualificationResultV1,
)


class BeliefV2ScoringControllerError(ValueError):
    """A selected scoring byte, actor, target, or REF-C binding drifted."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def synthetic_round_key(round_seed: int) -> str:
    if type(round_seed) is not int or round_seed < 0:
        raise BeliefV2ScoringControllerError(
            "V2 synthetic scoring round seed drift")
    return hashlib.sha256(
        f"belief-v1-v2-synthetic-round|{round_seed}".encode("ascii")
    ).hexdigest()


def reopen_trained_scoring_cohorts(
        root: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        training_inputs: V2StreamingTrainingInputsV1) \
        -> tuple[tuple[V2CohortModelsV1, ...],
                 V2DeviceQualificationPlanV1,
                 V2DeviceQualificationResultV1,
                 tuple[tuple[str, str], ...]]:
    """Reopen every selected portable checkpoint and its training receipt."""
    try:
        validate_streaming_training_inputs(training_inputs)
    except ValueError as exc:
        raise BeliefV2ScoringControllerError(
            "V2 scoring training input population refused") from exc
    primary_rows = [row for row in training_inputs.realizations
                    if row.cohort_id == PRIMARY_COHORT_ID]
    if len(primary_rows) != 1:
        raise BeliefV2ScoringControllerError(
            "V2 scoring primary realization drift")
    primary = primary_rows[0]
    try:
        _, qualification_plan, qualification_result = (
            reopen_device_qualification(
                root / "device-qualification" / "result",
                freeze=freeze, admission=admission, primary=primary))
    except ValueError as exc:
        raise BeliefV2ScoringControllerError(
            "V2 scoring device qualification refused") from exc
    try:
        _, _, calibration_factory, control_dose, cache_sha256 = (
            reopen_training_tensor_cache(
                root / "training-tensor-cache" / "result",
                freeze=freeze, admission=admission))
    except ValueError as exc:
        raise BeliefV2ScoringControllerError(
            "V2 scoring tensor cache refused") from exc

    def reopen_one(realization):
        try:
            manifest, trained = reopen_training_cohort(
                root / "training" / realization.cohort_id,
                freeze=freeze, admission=admission, primary=primary,
                realization=realization, training_examples=None,
                calibration=training_inputs.common_calibration,
                calibration_examples=None,
                qualification_plan=qualification_plan,
                qualification_result=qualification_result,
                compact_control_dose=(
                    control_dose if realization.kind
                    == "hard-geometry-label-permutation" else 0),
                calibration_batch_factory=calibration_factory,
                cache_manifest_sha256=cache_sha256)
            cohort = cohort_models_from_trained(trained)
        except ValueError as exc:
            raise BeliefV2ScoringControllerError(
                "V2 scoring trained cohort refused") from exc
        if cohort.cohort_id != realization.cohort_id:
            raise BeliefV2ScoringControllerError(
                "V2 scoring trained cohort order drift")
        return cohort, (
            realization.cohort_id,
            _sha256(canonical_json_bytes(manifest)))

    # Cohort artifacts and calibration factories are immutable and disjoint.
    # Reopening them in input order with one worker per cohort preserves the
    # exact returned population while avoiding a long single-core verification
    # tail before both calibration and terminal scoring.
    with ThreadPoolExecutor(
            max_workers=len(training_inputs.realizations)) as executor:
        reopened = tuple(executor.map(
            reopen_one, training_inputs.realizations))
    models = tuple(row[0] for row in reopened)
    manifest_hashes = tuple(row[1] for row in reopened)
    expected_ids = tuple(plan.cohort_id for plan in freeze.cohorts)
    if tuple(row.cohort_id for row in models) != expected_ids:
        raise BeliefV2ScoringControllerError(
            "V2 scoring cohort/freeze order drift")
    return (models, qualification_plan, qualification_result,
            manifest_hashes)


def reopen_synthetic_scoring_round(
        root: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        coordinate: V2RoundCoordinate, replicate: str,
        allowed_split: str) -> tuple[V2ScoringDecisionV1, ...]:
    """Open one exact allowed split after full manifest authentication."""
    if not isinstance(root, Path) or root != Path(freeze.evidence_root) \
            or type(coordinate) is not V2RoundCoordinate \
            or allowed_split not in {"calibration", "test"} \
            or coordinate.split != allowed_split \
            or (allowed_split == "calibration"
                and replicate not in {
                    "calibration-replicate-0",
                    "calibration-replicate-1"}) \
            or (allowed_split == "test" and replicate != "test-primary"):
        raise BeliefV2ScoringControllerError(
            "V2 scoring split/replicate admission drift")
    capture_directory = root / "capture" / f"lane-{coordinate.lane:02d}"
    reference_directory = (
        root / "reference" / f"lane-{coordinate.lane:02d}")
    try:
        capture_manifest = reopen_actor_capture_lane_manifest(
            capture_directory, freeze=freeze, admission=admission,
            lane=coordinate.lane)
        reference_manifest = reopen_reference_lane_manifest(
            reference_directory, capture_directory=capture_directory,
            freeze=freeze, admission=admission, lane=coordinate.lane)
    except BeliefV2ControllerError as exc:
        raise BeliefV2ScoringControllerError(
            "V2 scoring source manifest refused") from exc
    capture_rows = [row for row in capture_manifest["rounds"]
                    if row["round_seed"] == coordinate.round_seed]
    reference_rows = [row for row in reference_manifest["jobs"]
                      if row["round_seed"] == coordinate.round_seed
                      and row["replicate"] == replicate]
    if len(capture_rows) != 1 or len(reference_rows) != 1:
        raise BeliefV2ScoringControllerError(
            "V2 scoring round is absent or duplicated")
    capture_row = capture_rows[0]
    reference_row = reference_rows[0]
    private_raw = stable_read_bytes(
        capture_directory / "private" / capture_row["private_filename"])
    reference_raw = stable_read_bytes(
        reference_directory / reference_row["filename"])
    if len(private_raw) != capture_row["private_byte_count"] \
            or _sha256(private_raw) != capture_row["private_bundle_sha256"] \
            or len(reference_raw) != reference_row["byte_count"] \
            or _sha256(reference_raw) != reference_row["bundle_sha256"]:
        raise BeliefV2ScoringControllerError(
            "V2 scoring selected byte binding drift")
    try:
        captured = reopen_captured_round_artifacts(
            reopen_capture_bundle(private_raw))
        reference = reopen_reference_round_bundle(reference_raw)
    except ValueError as exc:
        raise BeliefV2ScoringControllerError(
            "V2 scoring selected typed artifact refused") from exc
    if captured.round_seed != coordinate.round_seed \
            or captured.policy_seeds != v2_policy_seeds(coordinate) \
            or reference.captured.round_seed != coordinate.round_seed \
            or reference.captured.policy_seeds != v2_policy_seeds(coordinate) \
            or reference.replicate != replicate \
            or len(captured.pairs) != len(reference.batches) \
            or tuple(pair.actor_bytes for pair in captured.pairs) \
            != reference.captured.actor_rows \
            or capture_row["decision_count"] != len(captured.pairs) \
            or reference_row["decision_count"] != len(reference.batches):
        raise BeliefV2ScoringControllerError(
            "V2 scoring capture/reference identity drift")
    decisions = []
    for pair, batch in zip(
            captured.pairs, reference.batches, strict=True):
        try:
            actor, target, metadata = reopen_score_pair(pair)
            common = build_common_surface_tensors(
                actor, behavior_policy_ids=UNIVERSAL_POLICY_IDS)
        except ValueError as exc:
            raise BeliefV2ScoringControllerError(
                "V2 scoring decision reconstruction refused") from exc
        if metadata["round_seed"] != coordinate.round_seed \
                or metadata["split"] != allowed_split \
                or actor.trump_rank != coordinate.trump_rank \
                or batch.actor.canonical_bytes() != actor.canonical_bytes():
            raise BeliefV2ScoringControllerError(
                "V2 scoring decision identity drift")
        decisions.append(V2ScoringDecisionV1(
            decision_key=metadata["decision_key"], source_actor=actor,
            target=target, common=common, reference=batch))
    if not decisions or len({row.decision_key for row in decisions}) \
            != len(decisions):
        raise BeliefV2ScoringControllerError(
            "V2 scoring decision population drift")
    return tuple(decisions)


def reopen_human_scoring_rounds(
        root: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        group_digest: str, replicate: str,
        allowed_split: str) \
        -> tuple[tuple[str, str, tuple[V2ScoringDecisionV1, ...]], ...]:
    """Open one allowed human group and return complete round units."""
    if not isinstance(root, Path) or root != Path(freeze.evidence_root) \
            or type(group_digest) is not str or len(group_digest) != 64 \
            or any(char not in "0123456789abcdef" for char in group_digest) \
            or allowed_split not in {"calibration", "test"} \
            or (allowed_split == "calibration"
                and replicate not in {
                    "calibration-replicate-0",
                    "calibration-replicate-1"}) \
            or (allowed_split == "test" and replicate != "test-primary"):
        raise BeliefV2ScoringControllerError(
            "V2 human scoring split/replicate admission drift")
    capture_directory = (
        root / "human-capture" / f"group-{group_digest}")
    reference_directory = (
        root / "human-reference" / f"group-{group_digest}" / replicate)
    try:
        capture = reopen_human_group_manifest(
            capture_directory, freeze=freeze, admission=admission)
        reference = reopen_human_reference_group(
            reference_directory, freeze=freeze, admission=admission)
    except ValueError as exc:
        raise BeliefV2ScoringControllerError(
            "V2 human scoring source manifest refused") from exc
    if capture["group_digest"] != group_digest \
            or capture["split"] != allowed_split \
            or reference["split"] != allowed_split \
            or reference["replicate"] != replicate \
            or len(capture["rows"]) != len(reference["rows"]):
        raise BeliefV2ScoringControllerError(
            "V2 human scoring source identity drift")
    grouped: dict[str, list[V2ScoringDecisionV1]] = {}
    ranks: dict[str, str] = {}
    for capture_row, reference_row in zip(
            capture["rows"], reference["rows"], strict=True):
        actor_raw = stable_read_bytes(
            capture_directory / "actor-only"
            / capture_row["actor_filename"])
        target_raw = stable_read_bytes(
            capture_directory / "private-targets"
            / capture_row["target_filename"])
        reference_raw = stable_read_bytes(
            reference_directory / reference_row["filename"])
        if len(actor_raw) != capture_row["actor_byte_count"] \
                or _sha256(actor_raw) != capture_row["actor_sha256"] \
                or len(target_raw) != capture_row["target_byte_count"] \
                or _sha256(target_raw) != capture_row["target_sha256"] \
                or len(reference_raw) != reference_row["byte_count"] \
                or _sha256(reference_raw) != reference_row["bundle_sha256"]:
            raise BeliefV2ScoringControllerError(
                "V2 human scoring selected byte binding drift")
        try:
            actor, target, common, metadata = validate_human_corpus_pair(
                actor_raw, target_raw)
            scoring_actor = v2_scoring_actor(actor)
            batch = reopen_reference_external_actor_batch_bundle(
                reference_raw, actor=scoring_actor)
        except ValueError as exc:
            raise BeliefV2ScoringControllerError(
                "V2 human scoring typed reconstruction refused") from exc
        if metadata["split"] != allowed_split \
                or metadata["decision_key"] != reference_row["decision_key"] \
                or metadata["round_digest"] \
                != reference_row["round_digest"] \
                or actor.trump_rank != reference_row["trump_rank"]:
            raise BeliefV2ScoringControllerError(
                "V2 human scoring decision identity drift")
        round_digest = metadata["round_digest"]
        if round_digest in ranks and ranks[round_digest] != actor.trump_rank:
            raise BeliefV2ScoringControllerError(
                "V2 human scoring round rank drift")
        ranks[round_digest] = actor.trump_rank
        grouped.setdefault(round_digest, []).append(V2ScoringDecisionV1(
            decision_key=metadata["decision_key"], source_actor=actor,
            target=target, common=common, reference=batch))
    if (not grouped and capture["human_decision_count"] != 0) \
            or sum(map(len, grouped.values())) \
            != capture["human_decision_count"]:
        raise BeliefV2ScoringControllerError(
            "V2 human scoring round population drift")
    return tuple((round_digest, ranks[round_digest], tuple(decisions))
                 for round_digest, decisions in sorted(grouped.items()))

import dataclasses
import hashlib

import numpy as np
import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.douzero_micro import HISTORY_EVENT_DIM
from shengji.rl.encode import N_CARDS
from shengji.rl.world_afterstate import (
    PERSPECTIVE_DIM, PUBLIC_DIM, WORLD_RECEIVERS, WorldAfterstateTensorsV0,
)
from shengji.rl.world_afterstate_v2_inference import (
    PROBABILITY_SCALE, ValueInferenceRootV2,
    expected_signed_microlevels, prediction_population_manifest_v2,
)
from shengji.rl.world_afterstate_v2_continuation import ContinuationOutcomeV2
from shengji.rl.world_afterstate_v2_evaluation import (
    WorldAfterstateV2EvaluationError, evaluate_control_difference, evaluate_v2,
)
from shengji.rl.world_afterstate_v2_inference import CandidatePredictionV2
from shengji.rl.world_afterstate_v2_metrics import build_natural_fit_prior
from shengji.rl.world_afterstate_v2_training import WorldAfterstateV2TrainingExample


def _sha(text):
    if isinstance(text, str):
        text = text.encode()
    else:
        text = canonical_json_bytes(text)
    return hashlib.sha256(text).hexdigest()


def _probability(category):
    row = [0] * 204
    row[category] = PROBABILITY_SCALE
    return tuple(row)


def _population(*, root="evaluation-root", categories=(100, 101),
                predicted_categories=None):
    predicted_categories = predicted_categories or categories
    deal, slot, state = (_sha(root + suffix) for suffix in (":deal", ":slot", ":state"))
    successors = (_sha(root + ":successor:0"), _sha(root + ":successor:1"))
    cset = _sha({"schema": "world-afterstate-v2-candidate-set-v1",
                 "state_sha256": state, "successor_sha256s": list(successors)})
    outcomes = []
    predictions = []
    tensor_rows = tuple(
        WorldAfterstateTensorsV0(
            np.zeros(PUBLIC_DIM, dtype=np.float32),
            np.zeros((0, HISTORY_EVENT_DIM), dtype=np.float32),
            np.zeros((WORLD_RECEIVERS, N_CARDS), dtype=np.float32),
            np.array([1.0, 0.0], dtype=np.float32))
        for _ in categories)
    from shengji.rl.world_afterstate_v2_model import (
        collate_world_afterstate_tensors)
    inference_root = ValueInferenceRootV2(
        deal_sha256=deal, slot_sha256=slot, state_sha256=state,
        candidate_set_sha256=cset, split="audit", source="natural",
        role="attacker", phase="early", position="lead",
        trump_rank="2", trump_mode="S", points_bucket="0-39",
        successor_sha256s=successors,
        tensor_sha256s=tuple(_sha(root + f":tensor:{candidate}")
                             for candidate in range(len(categories))),
        tensors=collate_world_afterstate_tensors(tensor_rows))
    inference_root.validate()
    for candidate, category in enumerate(categories):
        for replica in range(8):
            outcomes.append(ContinuationOutcomeV2(
                deal, slot, state, cset, "natural", "audit", "attacker",
                "early", "lead", "2", "S", "0-39", candidate,
                candidate == 0, successors[candidate], _sha(root + f":crn:{replica}"),
                replica, category))
        for member in range(4):
            probabilities = _probability(predicted_categories[candidate])
            predictions.append(CandidatePredictionV2(
                root_sha256=inference_root.root_sha256, deal_sha256=deal,
                slot_sha256=slot, state_sha256=state,
                candidate_set_sha256=cset, candidate_index=candidate,
                successor_sha256=successors[candidate],
                tensor_sha256=_sha(root + f":tensor:{candidate}"), seed_block=1,
                member_index=member, control_name="natural",
                model_state_sha256=_sha(f"model:{member}"),
                probability_ppb=probabilities,
                expected_signed_microlevels=expected_signed_microlevels(probabilities),
                consumer_eligible=True))
    training = WorldAfterstateV2TrainingExample(
        deal, slot, state, cset, 0, True, successors[0], _sha(root + ":crn:0"),
        0, "natural", "fit", "attacker", "early", "lead", "2", "S", "0-39",
        WorldAfterstateTensorsV0(
            np.zeros(PUBLIC_DIM, dtype=np.float32),
            np.zeros((0, HISTORY_EVENT_DIM), dtype=np.float32),
            np.zeros((WORLD_RECEIVERS, N_CARDS), dtype=np.float32),
            np.array([1.0, 0.0], dtype=np.float32)), 100)
    return (tuple(predictions), tuple(outcomes),
            build_natural_fit_prior((training,)), inference_root)


def _manifest(roots, predictions, *, control_name="natural", seed_block=1):
    return prediction_population_manifest_v2(
        roots, predictions, split="audit", control_name=control_name,
        seed_block=seed_block)


def test_evaluation_binds_populations_and_selects_nonincumbent():
    predictions, outcomes, prior, root = _population()
    result = evaluate_v2(_manifest((root,), predictions), outcomes, prior)
    result.validate()
    assert result.selected_action_utility.mean > 0
    assert result.nonincumbent_dose_ppm == 1_000_000
    assert result.positive_rps_member_count == 4
    assert result.payload()["authority"]["audit_opening_authorized"] is False


def test_evaluation_rejects_drop_duplicate_and_misbinding():
    predictions, outcomes, prior, root = _population()
    manifest = _manifest((root,), predictions)

    def rehash(value):
        return {**value, "manifest_sha256": _sha({
            key: item for key, item in value.items()
            if key != "manifest_sha256"})}

    dropped = {**manifest, "predictions": manifest["predictions"][:-1]}
    with pytest.raises(WorldAfterstateV2EvaluationError,
                       match="prediction manifest refused"):
        evaluate_v2(rehash(dropped), outcomes, prior)
    duplicated = {**manifest,
                  "predictions": [*manifest["predictions"],
                                  manifest["predictions"][0]]}
    with pytest.raises(WorldAfterstateV2EvaluationError,
                       match="prediction manifest refused"):
        evaluate_v2(rehash(duplicated), outcomes, prior)
    forged = {**manifest, "predictions": [dict(item)
                                           for item in manifest["predictions"]]}
    forged["predictions"][0]["successor_sha256"] = _sha("foreign")
    with pytest.raises(WorldAfterstateV2EvaluationError,
                       match="prediction manifest refused"):
        evaluate_v2(rehash(forged), outcomes, prior)


def test_tie_to_incumbent_and_control_block_separation():
    predictions, outcomes, prior, root = _population()
    result = evaluate_v2(_manifest((root,), predictions), outcomes, prior)
    assert result.selected_action_utility.mean >= 0
    control = tuple(dataclasses.replace(row, control_name="complete-world-shuffle",
                                        consumer_eligible=False)
                    for row in predictions)
    controlled = evaluate_v2(
        _manifest((root,), control,
                  control_name="complete-world-shuffle"),
        outcomes, prior)
    comparison = evaluate_control_difference(result, controlled)
    comparison.validate()


def test_bootstrap_preserves_each_deals_own_ensemble_metric():
    first_predictions, first_outcomes, prior, first_root = _population(root="deal-a")
    second_predictions, second_outcomes, _, second_root = _population(
        root="deal-b", categories=(140, 141), predicted_categories=(100, 100))
    result = evaluate_v2(
        _manifest((first_root, second_root),
                  first_predictions + second_predictions),
        first_outcomes + second_outcomes,
        prior,
    )
    deal_values = dict(result.deal_rps_improvement)
    assert len(deal_values) == 2
    assert len(set(deal_values.values())) == 2
    assert result.rps_improvement.mean == sum(deal_values.values()) // 2


def test_result_rejects_rehashed_gate_and_deal_mean_drift():
    predictions, outcomes, prior, root = _population()
    result = evaluate_v2(_manifest((root,), predictions), outcomes, prior)
    with pytest.raises(WorldAfterstateV2EvaluationError,
                       match="learning-gate derivation"):
        dataclasses.replace(
            result,
            learning_gates_1_to_4=tuple(
                not value for value in result.learning_gates_1_to_4),
        ).validate()


def test_action_gate_bootstraps_ensemble_choice_not_mean_member_choices():
    predictions, outcomes, prior, root = _population()
    heterogeneous = []
    for row in predictions:
        if row.member_index < 3:
            category = 101 if row.candidate_index == 0 else 100
        else:
            category = 0 if row.candidate_index == 0 else 203
        probability = _probability(category)
        heterogeneous.append(dataclasses.replace(
            row, probability_ppb=probability,
            expected_signed_microlevels=expected_signed_microlevels(
                probability)))
    result = evaluate_v2(
        _manifest((root,), tuple(heterogeneous)), outcomes, prior)
    assert result.selected_action_utility.mean == 1_000_000
    assert result.member_action_utility == (0, 0, 0, 1_000_000)
    assert sum(result.member_action_utility) // 4 != \
        result.selected_action_utility.mean
    with pytest.raises(WorldAfterstateV2EvaluationError,
                       match="deal/receipt mean binding"):
        dataclasses.replace(
            result,
            deal_rps_improvement=((result.deal_rps_improvement[0][0],
                                   result.deal_rps_improvement[0][1] + 1),),
        ).validate()

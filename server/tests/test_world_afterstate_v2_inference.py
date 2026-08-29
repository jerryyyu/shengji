from __future__ import annotations

import copy
import hashlib

import torch
import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.douzero_micro import HISTORY_EVENT_DIM
from shengji.rl.encode import N_CARDS
from shengji.rl.world_afterstate import (
    OUTCOME_CLASSES, PERSPECTIVE_DIM, PUBLIC_DIM, WORLD_RECEIVERS,
)
from shengji.rl.world_afterstate_v2_model import (
    WorldAfterstateV2Batch, new_world_afterstate_v2_model,
)
from shengji.rl import world_afterstate_v2_inference as inference


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _root() -> inference.ValueInferenceRootV2:
    successors = (_sha("successor-0"), _sha("successor-1"))
    state = _sha("state")
    batch = WorldAfterstateV2Batch(
        public=torch.zeros((2, PUBLIC_DIM), dtype=torch.float32),
        history=torch.zeros((2, 0, HISTORY_EVENT_DIM), dtype=torch.float32),
        history_lengths=torch.zeros(2, dtype=torch.long),
        world=torch.zeros((2, WORLD_RECEIVERS, N_CARDS), dtype=torch.float32),
        perspective=torch.tensor([[1.0, 0.0], [1.0, 0.0]],
                                 dtype=torch.float32),
    )
    return inference.ValueInferenceRootV2(
        deal_sha256=_sha("deal"), slot_sha256=_sha("slot"),
        state_sha256=state,
        candidate_set_sha256=_sha({
            "schema": "world-afterstate-v2-candidate-set-v1",
            "state_sha256": state,
            "successor_sha256s": list(successors),
        }),
        split="audit", source="natural", role="attacker", phase="early",
        position="lead", trump_rank="2", trump_mode="S",
        select_subfold=None, points_bucket="0-39",
        successor_sha256s=successors,
        tensor_sha256s=(_sha("tensor-0"), _sha("tensor-1")), tensors=batch)


def test_prediction_is_target_free_normalized_and_does_not_mutate_model():
    root = _root()
    root.validate()
    body = root.target_free_body()
    assert not {"outcome", "terminal_outcome", "signed_level_category"}.intersection(body)
    model = new_world_afterstate_v2_model(101)
    before = copy.deepcopy(model.state_dict())
    rows = inference.predict_root_v2(model, root, seed_block=1, member_index=0)
    assert len(rows) == 2
    assert all(sum(row.probability_ppb) == inference.PROBABILITY_SCALE
               for row in rows)
    assert all(row.consumer_eligible for row in rows)
    assert all(torch.equal(before[name], model.state_dict()[name]) for name in before)


def test_expected_signed_microlevels_is_exact_for_half_level_mixture():
    probabilities = [0] * OUTCOME_CLASSES
    probabilities[100] = inference.PROBABILITY_SCALE // 2
    probabilities[101] = inference.PROBABILITY_SCALE // 2
    assert inference.expected_signed_microlevels(tuple(probabilities)) == -1_000_000


def test_confirmatory_or_control_prediction_cannot_select_actions():
    root = _root()
    model = new_world_afterstate_v2_model(102)
    rows = inference.predict_root_v2(
        model, root, seed_block=2, member_index=0)
    assert all(not row.consumer_eligible for row in rows)
    with pytest.raises(inference.WorldAfterstateV2InferenceError,
                       match="manifest required"):
        inference.select_primary_actions_v2(rows)
    for control_name in inference.CONTROL_NAMES[1:]:
        controlled = inference.predict_root_v2(
            model, root, seed_block=1, member_index=0,
            control_name=control_name)
        assert all(not row.consumer_eligible for row in controlled)


def test_complete_prediction_population_reopens_and_drop_refuses():
    root = _root()
    rows = tuple(
        row
        for member in range(4)
        for row in inference.predict_root_v2(
            new_world_afterstate_v2_model(200 + member), root,
            seed_block=1, member_index=member)
    )
    manifest = inference.prediction_population_manifest_v2(
        [root], rows, split="audit", control_name="natural", seed_block=1)
    inference.validate_prediction_population_manifest_v2(manifest)
    assert inference.select_primary_actions_v2(manifest)[root.root_sha256] in (0, 1)
    with pytest.raises(inference.WorldAfterstateV2InferenceError, match="drop"):
        inference.prediction_population_manifest_v2(
            [root], rows[:-1], split="audit", control_name="natural",
            seed_block=1)
    forged = copy.deepcopy(manifest)
    forged["predictions"][0]["probability_ppb"][0] += 1
    with pytest.raises(inference.WorldAfterstateV2InferenceError):
        inference.validate_prediction_population_manifest_v2(forged)


def test_ensemble_tie_breaks_to_protected_incumbent():
    root = _root()
    probabilities = tuple(
        [inference.PROBABILITY_SCALE // OUTCOME_CLASSES]
        * (OUTCOME_CLASSES - 1)
        + [inference.PROBABILITY_SCALE
           - (inference.PROBABILITY_SCALE // OUTCOME_CLASSES)
           * (OUTCOME_CLASSES - 1)])
    expected = inference.expected_signed_microlevels(probabilities)
    rows = []
    for member in range(4):
        model_sha = _sha(("model", member))
        for candidate in range(2):
            rows.append(inference.CandidatePredictionV2(
                root_sha256=root.root_sha256, deal_sha256=root.deal_sha256,
                slot_sha256=root.slot_sha256, state_sha256=root.state_sha256,
                candidate_set_sha256=root.candidate_set_sha256,
                candidate_index=candidate,
                successor_sha256=root.successor_sha256s[candidate],
                tensor_sha256=root.tensor_sha256s[candidate], seed_block=1,
                member_index=member, control_name="natural",
                model_state_sha256=model_sha, probability_ppb=probabilities,
                expected_signed_microlevels=expected, consumer_eligible=True))
    manifest = inference.prediction_population_manifest_v2(
        [root], rows, split="audit", control_name="natural", seed_block=1)
    assert inference.select_primary_actions_v2(manifest)[root.root_sha256] == 0


def test_primary_selection_refuses_foreign_root_and_collapsed_models():
    root = _root()
    rows = tuple(
        row for member in range(4)
        for row in inference.predict_root_v2(
            new_world_afterstate_v2_model(400 + member), root,
            seed_block=1, member_index=member))
    manifest = inference.prediction_population_manifest_v2(
        [root], rows, split="audit", control_name="natural", seed_block=1)

    foreign = copy.deepcopy(manifest)
    foreign["predictions"][4]["state_sha256"] = _sha("foreign-state")
    body = {key: value for key, value in foreign.items()
            if key != "manifest_sha256"}
    foreign["manifest_sha256"] = _sha(body)
    with pytest.raises(inference.WorldAfterstateV2InferenceError):
        inference.select_primary_actions_v2(foreign)

    collapsed = copy.deepcopy(manifest)
    first_model = collapsed["predictions"][0]["model_state_sha256"]
    for row in collapsed["predictions"]:
        row["model_state_sha256"] = first_model
    body = {key: value for key, value in collapsed.items()
            if key != "manifest_sha256"}
    collapsed["manifest_sha256"] = _sha(body)
    with pytest.raises(inference.WorldAfterstateV2InferenceError):
        inference.select_primary_actions_v2(collapsed)

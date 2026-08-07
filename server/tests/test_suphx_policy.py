"""Falsification tests for the four-surface Suphx policy model."""
from __future__ import annotations

import copy
import random

import pytest


np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from shengji.ai.smart import SmartBot  # noqa: E402
from shengji.engine.game import Game  # noqa: E402
from shengji.rl.actions import enumerate_actions  # noqa: E402
from shengji.rl.douzero_micro import ROLE_ATTACKER, ROLE_DEFENDER  # noqa: E402
from shengji.rl.encode import ACT_DIM, encode_action  # noqa: E402
from shengji.rl.exact_resume import state_digest  # noqa: E402
from shengji.rl.suphx_micro import (  # noqa: E402
    FEATURE_SPEC_SHA256,
    PERFECT_DIM,
    apply_privilege_mask,
    encode_feature_partition,
)
from shengji.rl.suphx_policy import (  # noqa: E402
    INITIAL_ENTROPY_ALPHA,
    POLICY_SOURCE_SHA256S,
    POLICY_SPEC,
    POLICY_SPEC_SHA256,
    SURFACE_FOLLOW,
    SURFACE_LEAD,
    SuphxPolicyError,
    new_from_scratch_model,
    role_for,
    surface_for,
    surface_key,
)


def _play_state(seed: int = 9182):
    game = Game(random.Random(seed))
    rnd = game.start_round()
    while rnd.phase == "deal":
        rnd.deal_next()
    smart = SmartBot()
    for seat in range(4):
        declaration = smart.decide_declare(rnd, seat, final=True)
        if declaration:
            rnd.declare(seat, declaration)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, smart.decide_bury(rnd, rnd.banker))
    assert rnd.phase == "play"
    return rnd


def _policy_inputs(rnd, seat, *, perfect=True):
    partition = encode_feature_partition(rnd, seat)
    mask = np.ones(PERFECT_DIM, dtype=np.float32) if perfect \
        else np.zeros(PERFECT_DIM, dtype=np.float32)
    actions = enumerate_actions(
        rnd, seat, exhaustive_follows=False, include_throws=False)
    encoded = np.asarray(
        [encode_action(action, rnd) for action in actions],
        dtype=np.float32,
    ).reshape(-1, ACT_DIM)
    return {
        "role": role_for(rnd, seat),
        "surface": surface_for(rnd),
        "observation": partition["observation"],
        "legal_private": partition["legal_private"],
        "history": partition["public_history"],
        "masked_perfect": apply_privilege_mask(partition["perfect"], mask),
        "actions": encoded,
    }


def test_policy_contract_binds_feature_contract_and_four_surfaces():
    assert POLICY_SPEC_SHA256 == state_digest(POLICY_SPEC)
    assert POLICY_SPEC["feature_spec_sha256"] == FEATURE_SPEC_SHA256
    assert POLICY_SPEC["source_sha256s"] == POLICY_SOURCE_SHA256S
    assert POLICY_SPEC["surfaces"] == [
        "attacker_lead", "attacker_follow",
        "defender_lead", "defender_follow",
    ]
    assert POLICY_SPEC["independent_surface_parameters"] is True
    assert POLICY_SPEC["inputs"]["raw_perfect_input"] is False
    assert POLICY_SPEC["entropy_controller"]["initial_alpha"] == \
        INITIAL_ENTROPY_ALPHA


def test_named_initialization_preserves_global_rng_and_surface_parameters():
    before = torch.get_rng_state().clone()
    first = new_from_scratch_model(71)
    assert torch.equal(torch.get_rng_state(), before)
    torch.manual_seed(999)
    second = new_from_scratch_model(71)
    torch.set_rng_state(before)
    assert state_digest(first.state_dict()) == state_digest(second.state_dict())

    parameter_sets = [
        {id(value) for value in first.surfaces[key].parameters()}
        for key in POLICY_SPEC["surfaces"]
    ]
    for index, left in enumerate(parameter_sets):
        for right in parameter_sets[index + 1:]:
            assert left.isdisjoint(right)
    for head in first.surfaces.values():
        assert head.entropy_alpha.item() == pytest.approx(
            INITIAL_ENTROPY_ALPHA)


def test_public_endpoint_logits_and_value_ignore_hidden_world():
    rnd = _play_state()
    seat = (rnd.banker + 1) % 4
    first_inputs = _policy_inputs(rnd, seat, perfect=False)
    changed = copy.deepcopy(rnd)
    hidden_a = (seat + 1) % 4
    hidden_b = (seat + 2) % 4
    changed.hands[hidden_a], changed.hands[hidden_b] = (
        changed.hands[hidden_b], changed.hands[hidden_a])
    second_inputs = _policy_inputs(changed, seat, perfect=False)
    model = new_from_scratch_model(13)
    first_logits, first_value = model.score_candidates(**first_inputs)
    second_logits, second_value = model.score_candidates(**second_inputs)
    assert torch.equal(first_logits, second_logits)
    assert torch.equal(first_value, second_value)


def test_oracle_endpoint_uses_hidden_ownership():
    rnd = _play_state()
    seat = (rnd.banker + 1) % 4
    first_inputs = _policy_inputs(rnd, seat, perfect=True)
    changed = copy.deepcopy(rnd)
    hidden_a = (seat + 1) % 4
    hidden_b = (seat + 2) % 4
    changed.hands[hidden_a], changed.hands[hidden_b] = (
        changed.hands[hidden_b], changed.hands[hidden_a])
    second_inputs = _policy_inputs(changed, seat, perfect=True)
    model = new_from_scratch_model(17)
    first_logits, first_value = model.score_candidates(**first_inputs)
    second_logits, second_value = model.score_candidates(**second_inputs)
    assert not torch.equal(first_logits, second_logits)
    assert not torch.equal(first_value, second_value)


def test_role_and_surface_routing_select_independent_heads():
    rnd = _play_state()
    assert surface_for(rnd) == SURFACE_LEAD
    assert surface_key(ROLE_ATTACKER, SURFACE_LEAD) == "attacker_lead"
    assert surface_key(ROLE_DEFENDER, SURFACE_FOLLOW) == "defender_follow"
    rnd.play(rnd.turn, [rnd.hands[rnd.turn][0]])
    assert surface_for(rnd) == SURFACE_FOLLOW
    with pytest.raises(SuphxPolicyError, match="unsupported role"):
        surface_key(9, SURFACE_LEAD)
    with pytest.raises(SuphxPolicyError, match="unsupported surface"):
        surface_key(ROLE_ATTACKER, 9)
    with pytest.raises(SuphxPolicyError, match="valid seat"):
        role_for(rnd, True)


def test_candidate_scoring_is_action_conditioned_and_gradient_optional():
    rnd = _play_state(88)
    seat = rnd.turn
    inputs = _policy_inputs(rnd, seat, perfect=False)
    assert len(inputs["actions"]) >= 2
    model = new_from_scratch_model(19)
    logits, value = model.score_candidates(**inputs)
    assert logits.shape == (len(inputs["actions"]),)
    assert value.shape == ()
    assert not logits.requires_grad
    assert not torch.all(logits == logits[0])
    gradient_logits, gradient_value = model.score_candidates(
        **inputs, grad=True)
    assert gradient_logits.requires_grad
    assert gradient_value.requires_grad


def test_scoring_rejects_raw_shape_dtype_and_nonfinite_drift():
    rnd = _play_state(89)
    inputs = _policy_inputs(rnd, rnd.turn, perfect=False)
    model = new_from_scratch_model(23)
    changed = dict(inputs)
    changed["masked_perfect"] = np.zeros(PERFECT_DIM, dtype=np.float64)
    with pytest.raises(SuphxPolicyError, match="masked-perfect"):
        model.score_candidates(**changed)
    changed = dict(inputs)
    changed["actions"] = np.empty((0, ACT_DIM), dtype=np.float32)
    with pytest.raises(SuphxPolicyError, match="empty or malformed"):
        model.score_candidates(**changed)
    changed = dict(inputs)
    changed["observation"] = changed["observation"].copy()
    changed["observation"][0] = np.nan
    with pytest.raises(SuphxPolicyError, match="non-finite"):
        model.score_candidates(**changed)

"""Falsification tests for O0-v2 shared-public-key runner integration."""
from __future__ import annotations

import copy
import inspect
import random

import pytest


np = pytest.importorskip("numpy")
pytest.importorskip("torch")

from shengji.ai.smart import SmartBot  # noqa: E402
from shengji.engine.game import Game  # noqa: E402
from shengji.rl.exact_resume import state_digest  # noqa: E402
from shengji.rl import suphx_micro  # noqa: E402
from shengji.rl.suphx_micro import PERFECT_DIM  # noqa: E402
from shengji.rl.suphx_o0_v2_integration import (  # noqa: E402
    ARM_RECEIPT_SCHEMA,
    INTEGRATION_SPEC,
    INTEGRATION_SPEC_SHA256,
    MINIMUM_INITIAL_PUBLIC_KEY_COUPLING_RATE,
    SharedPublicDecisionCRN,
    SuphxO0V2IntegrationError,
    cross_arm_coupling_gate,
    project_public_decision,
)
from shengji.rl.suphx_o0_v2_mechanics import (  # noqa: E402
    MIN_INFERENCE_SEEDS,
    CrossedCRNSpec,
    CrossedCRNStreams,
)


def _spec():
    return CrossedCRNSpec(
        root_seed=20260808,
        training_seed_indices=tuple(range(MIN_INFERENCE_SEEDS)),
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
    assert rnd.phase == "play" and rnd.turn is not None
    return rnd


def _hidden_swap(rnd, seat):
    changed = copy.deepcopy(rnd)
    hidden = [other for other in range(4) if other != seat]
    changed.hands[hidden[0]], changed.hands[hidden[1]] = (
        changed.hands[hidden[1]], changed.hands[hidden[0]])
    return changed


def _all_receipts(*, mutate=None):
    spec = _spec()
    rnd = _play_state()
    receipts = []
    for index in spec.training_seed_indices:
        for iteration in range(spec.iterations_per_arm):
            for arm in ("oracle", "public"):
                trace = SharedPublicDecisionCRN(
                    CrossedCRNStreams(spec, index, iteration))
                trace.decision_draws(copy.deepcopy(rnd), rnd.turn)
                receipt = trace.receipt(arm=arm)
                if mutate is not None:
                    receipt = mutate(index, iteration, arm, receipt)
                receipts.append(receipt)
    return spec, receipts


def test_integration_spec_is_bounded_and_requires_measured_full_coupling():
    assert INTEGRATION_SPEC_SHA256 == state_digest(INTEGRATION_SPEC)
    assert INTEGRATION_SPEC["key_source"] == \
        "one round-derived public projection for both arms"
    assert INTEGRATION_SPEC["first_public_context_coupling_rate_floor"] == 1.0
    assert INTEGRATION_SPEC["later_aligned_position_rate"] == \
        "diagnostic_only_after_policy_fork"
    assert INTEGRATION_SPEC["experiment_launch_authorized"] is False
    assert INTEGRATION_SPEC["strength_claim"] is False
    assert INTEGRATION_SPEC["production_promotion"] is False


def test_runner_key_endpoint_cannot_accept_arm_or_privileged_model_inputs():
    for callable_ in (
            project_public_decision,
            SharedPublicDecisionCRN.decision_draws):
        parameters = inspect.signature(callable_).parameters
        for forbidden in (
                "arm", "model", "checkpoint", "logits", "mask", "perfect",
                "masked_perfect", "observation"):
            assert forbidden not in parameters


def test_public_projection_is_invariant_to_hidden_world_and_excludes_perfect(
        monkeypatch):
    rnd = _play_state()
    seat = rnd.turn
    changed = _hidden_swap(rnd, seat)
    # This goes red if the implementation takes the tempting route of calling
    # the full feature partition and merely promising to discard ``perfect``.
    monkeypatch.setattr(
        suphx_micro, "encode_perfect_features",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("privileged encoder was called")),
    )
    first = project_public_decision(rnd, seat, deal_seed=991)
    second = project_public_decision(changed, seat, deal_seed=991)
    assert first.public_key == second.public_key
    assert np.array_equal(first.observation, second.observation)
    assert np.array_equal(first.legal_private, second.legal_private)
    assert np.array_equal(first.history, second.history)
    assert first.candidate_cards == second.candidate_cards
    assert not hasattr(first, "perfect")
    assert not first.observation.flags.writeable
    assert not first.legal_private.flags.writeable
    assert not first.history.flags.writeable
    with pytest.raises(ValueError):
        first.observation[0] += 1.0
    assert project_public_decision(
        rnd, seat, deal_seed=992).public_key != first.public_key


def test_same_public_round_produces_identical_mask_action_draws_across_arms():
    spec = _spec()
    rnd = _play_state()
    oracle = SharedPublicDecisionCRN(CrossedCRNStreams(spec, 3, 11))
    public = SharedPublicDecisionCRN(CrossedCRNStreams(spec, 3, 11))
    left = oracle.decision_draws(copy.deepcopy(rnd), rnd.turn)
    right = public.decision_draws(copy.deepcopy(rnd), rnd.turn)
    assert left.projection.public_key == right.projection.public_key
    assert left.mask_uniforms == right.mask_uniforms
    assert len(left.mask_uniforms) == PERFECT_DIM
    assert left.action_uniform == right.action_uniform
    assert oracle.receipt(arm="oracle")["arm"] == "oracle"
    assert public.receipt(arm="public")["arm"] == "public"


def test_complete_crossed_grid_passes_exact_initial_context_coupling_gate():
    spec, receipts = _all_receipts()
    gate = cross_arm_coupling_gate(spec, receipts)
    assert gate["passed"] is True
    assert gate["problems"] == []
    assert gate["expected_pairs"] == MIN_INFERENCE_SEEDS * 64
    assert gate["paired_receipts"] == gate["expected_pairs"]
    assert gate["paired_deal_matches"] == gate["expected_pairs"]
    assert gate["initial_public_key_matches"] == gate["expected_pairs"]
    assert gate["initial_public_key_coupling_rate"] == 1.0
    assert gate["minimum_initial_public_key_coupling_rate"] == \
        MINIMUM_INITIAL_PUBLIC_KEY_COUPLING_RATE
    assert gate["minimum_shared_prefix_decisions"] == 1
    assert gate["later_alignment_is_gate"] is False
    assert gate["experiment_launch_authorized"] is False
    assert gate["strength_claim"] is False


def test_exact_oracle_specific_key_decoupling_bug_fails_the_rate_gate():
    def mutate(index, iteration, arm, receipt):
        if (index, iteration, arm) != (0, 0, "oracle"):
            return receipt
        changed = copy.deepcopy(receipt)
        # Model the exact integration bug: an oracle-only privileged plane was
        # included in the key.  Keep every receipt digest internally honest so
        # only the cross-arm coupling criterion can catch it.
        key = state_digest({"public_key": changed[
            "first_public_decision_key"], "oracle_plane": 1.0})
        mechanics = changed["mechanics_receipt"]
        mechanics["public_decision_keys"][0] = key
        mechanics["public_decision_keys_sha256"] = state_digest(
            mechanics["public_decision_keys"])
        changed["first_public_decision_key"] = key
        return changed

    spec, receipts = _all_receipts(mutate=mutate)
    gate = cross_arm_coupling_gate(spec, receipts)
    assert gate["passed"] is False
    assert gate["initial_public_key_matches"] == gate["expected_pairs"] - 1
    assert gate["initial_public_key_coupling_rate"] < 1.0
    assert "initial public-key coupling rate below floor" in gate["problems"]


def test_later_policy_fork_is_measured_but_does_not_false_fail_coupling():
    def mutate(index, iteration, arm, receipt):
        if (index, iteration) != (0, 0):
            return receipt
        changed = copy.deepcopy(receipt)
        mechanics = changed["mechanics_receipt"]
        mechanics["public_decision_keys"].append(state_digest({
            "legitimate_post_action_public_fork": arm,
        }))
        mechanics["public_decision_keys_sha256"] = state_digest(
            mechanics["public_decision_keys"])
        changed["decision_count"] = 2
        return changed

    spec, receipts = _all_receipts(mutate=mutate)
    gate = cross_arm_coupling_gate(spec, receipts)
    assert gate["passed"] is True
    assert gate["initial_public_key_coupling_rate"] == 1.0
    assert gate["minimum_shared_prefix_decisions"] == 1
    assert gate["aligned_position_key_coupling_rate_diagnostic"] < 1.0
    assert gate["later_alignment_is_gate"] is False


def test_missing_duplicate_or_outcome_shaped_receipts_refuse():
    spec, receipts = _all_receipts()
    missing = cross_arm_coupling_gate(spec, receipts[:-1])
    assert missing["passed"] is False
    assert any("lacks exact oracle/public" in problem
               for problem in missing["problems"])

    duplicate = cross_arm_coupling_gate(spec, [*receipts, receipts[0]])
    assert duplicate["passed"] is False
    assert any("duplicate" in problem for problem in duplicate["problems"])

    leaked = copy.deepcopy(receipts)
    leaked[0]["score"] = 999.0
    outcome = cross_arm_coupling_gate(spec, leaked)
    assert outcome["passed"] is False
    assert "receipt 0: arm key receipt fields mismatch" in outcome["problems"]


def test_receipt_publication_refuses_empty_or_unknown_endpoint():
    spec = _spec()
    trace = SharedPublicDecisionCRN(CrossedCRNStreams(spec, 0, 0))
    with pytest.raises(SuphxO0V2IntegrationError, match="empty"):
        trace.receipt(arm="oracle")
    rnd = _play_state()
    trace.decision_draws(rnd, rnd.turn)
    with pytest.raises(SuphxO0V2IntegrationError, match="unsupported"):
        trace.receipt(arm="future")
    assert trace.receipt(arm="oracle")["schema"] == ARM_RECEIPT_SCHEMA

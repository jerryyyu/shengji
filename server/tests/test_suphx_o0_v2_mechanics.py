"""Falsification tests for O0-v2 CRN and margin-only infrastructure."""
from __future__ import annotations

import inspect
import random

import pytest


np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from shengji.rl.exact_resume import state_digest  # noqa: E402
from shengji.rl.suphx_o0_v2_mechanics import (  # noqa: E402
    ARMS,
    MECHANICS_SPEC,
    MECHANICS_SPEC_SHA256,
    MIN_INFERENCE_SEEDS,
    CrossedCRNSpec,
    CrossedCRNStreams,
    LogitMarginSpec,
    SuphxO0V2MechanicsError,
    public_decision_key,
    two_sided_margin_loss,
)


def _spec():
    return CrossedCRNSpec(
        root_seed=20260808,
        training_seed_indices=tuple(range(MIN_INFERENCE_SEEDS)),
    )


def _key(*, observation_delta=0.0):
    observation = np.zeros(7, dtype=np.float32)
    observation[0] = observation_delta
    return public_decision_key(
        deal_seed=991,
        seat=2,
        role=1,
        surface=0,
        observation=observation,
        legal_private=np.ones(5, dtype=np.float32),
        history=np.zeros((3, 4), dtype=np.float32),
        candidate_cards=(("S2",), ("H3", "H3")),
    )


def test_mechanics_spec_is_bounded_and_keeps_factors_separate():
    assert MECHANICS_SPEC_SHA256 == state_digest(MECHANICS_SPEC)
    assert MECHANICS_SPEC["common_infrastructure"][
        "minimum_training_seeds"] == 8
    assert MECHANICS_SPEC["factorial_cells"] == [
        {"name": "crn_control", "crossed_crn": True,
         "margin_controller": False},
        {"name": "crn_plus_margin", "crossed_crn": True,
         "margin_controller": True},
    ]
    assert MECHANICS_SPEC["experiment_launch_authorized"] is False
    assert MECHANICS_SPEC["o1_authorized"] is False
    assert MECHANICS_SPEC["strength_claim"] is False
    assert MECHANICS_SPEC["production_promotion"] is False


def test_crn_api_has_no_arm_or_checkpoint_input():
    for method in (
            CrossedCRNStreams.deal_seed,
            CrossedCRNStreams.mask_uniforms,
            CrossedCRNStreams.action_uniform):
        parameters = inspect.signature(method).parameters
        assert "arm" not in parameters
        assert "model" not in parameters
        assert "checkpoint" not in parameters
    assert ARMS == ("oracle", "public")


def test_same_seed_iteration_and_public_context_reopens_same_draws():
    left = CrossedCRNStreams(_spec(), 3, 11)
    right = CrossedCRNStreams(_spec(), 3, 11)
    key = _key()
    assert left.deal_seed() == right.deal_seed()
    assert left.mask_uniforms(key, 9) == right.mask_uniforms(key, 9)
    assert left.action_uniform(key) == right.action_uniform(key)
    assert left.receipt([key]) == right.receipt([key])


def test_diverged_public_context_or_seed_gets_a_different_keyed_draw():
    base = CrossedCRNStreams(_spec(), 3, 11)
    other_seed = CrossedCRNStreams(_spec(), 4, 11)
    first = _key()
    changed = _key(observation_delta=1.0)
    assert first != changed
    assert base.action_uniform(first) != base.action_uniform(changed)
    assert base.action_uniform(first) != other_seed.action_uniform(first)
    assert base.deal_seed() != other_seed.deal_seed()


def test_crn_draws_are_order_independent_and_preserve_global_rng():
    streams = CrossedCRNStreams(_spec(), 0, 0)
    first, second = _key(), _key(observation_delta=2.0)
    before = random.getstate()
    left = [streams.action_uniform(first), streams.action_uniform(second)]
    right = [streams.action_uniform(second), streams.action_uniform(first)]
    assert left == list(reversed(right))
    assert random.getstate() == before


def test_mask_endpoints_consume_the_same_named_uniform_population():
    streams = CrossedCRNStreams(_spec(), 1, 2)
    draws = streams.mask_uniforms(_key(), 12)
    public = tuple(float(draw < 0.0) for draw in draws)
    oracle = tuple(float(draw < 1.0) for draw in draws)
    assert public == (0.0,) * 12
    assert oracle == (1.0,) * 12
    assert len(draws) == len(public) == len(oracle)


def test_malformed_public_keys_and_array_shapes_refuse():
    streams = CrossedCRNStreams(_spec(), 1, 2)
    with pytest.raises(SuphxO0V2MechanicsError, match="SHA-256"):
        streams.action_uniform("z" * 64)
    with pytest.raises(SuphxO0V2MechanicsError, match="ordinary-play shapes"):
        public_decision_key(
            deal_seed=991,
            seat=2,
            role=1,
            surface=0,
            observation=np.zeros((1, 2), dtype=np.float32),
            legal_private=np.ones(5, dtype=np.float32),
            history=np.zeros((3, 4), dtype=np.float32),
            candidate_cards=(("S2",), ("H3",)),
        )


@pytest.mark.parametrize("indices", [
    tuple(range(7)),
    (0, 1, 2, 3, 4, 5, 6, 6),
])
def test_crn_spec_requires_eight_unique_inference_seeds(indices):
    with pytest.raises(SuphxO0V2MechanicsError, match="eight unique"):
        CrossedCRNSpec(root_seed=1, training_seed_indices=indices)


def _updated_margin(values, spec, rate=0.1):
    logits = torch.tensor(values, dtype=torch.float32, requires_grad=True)
    before = float(torch.topk(logits.detach(), 2).values.diff().abs().item())
    loss, observed = two_sided_margin_loss(logits, spec)
    loss.backward()
    with torch.no_grad():
        after_logits = logits - rate * logits.grad
        after = float(torch.topk(after_logits, 2).values.diff().abs().item())
    return before, after, float(observed.item())


def test_two_sided_margin_loss_increases_a_below_target_gap():
    spec = LogitMarginSpec(target_margin=1.0, coefficient=1.0)
    before, after, observed = _updated_margin([0.2, 0.0, -1.0], spec)
    assert observed == pytest.approx(before)
    assert after > before


def test_two_sided_margin_loss_decreases_an_above_target_gap():
    spec = LogitMarginSpec(target_margin=1.0, coefficient=1.0)
    before, after, observed = _updated_margin([3.0, 0.0, -1.0], spec)
    assert observed == pytest.approx(before)
    assert after < before


def test_forced_action_margin_loss_is_exact_zero_with_zero_gradient():
    logits = torch.tensor([0.7], requires_grad=True)
    loss, margin = two_sided_margin_loss(
        logits, LogitMarginSpec(target_margin=1.0, coefficient=0.2))
    loss.backward()
    assert float(loss.item()) == 0.0
    assert float(margin.item()) == 0.0
    assert torch.equal(logits.grad, torch.zeros_like(logits))


def test_invalid_margin_and_nonfinite_logits_refuse():
    with pytest.raises(SuphxO0V2MechanicsError):
        LogitMarginSpec(target_margin=0.0, coefficient=1.0)
    with pytest.raises(SuphxO0V2MechanicsError, match="finite"):
        two_sided_margin_loss(
            torch.tensor([float("nan"), 0.0]),
            LogitMarginSpec(target_margin=1.0, coefficient=1.0),
        )
    with pytest.raises(SuphxO0V2MechanicsError, match="finite"):
        two_sided_margin_loss(
            torch.tensor([2, 1]),
            LogitMarginSpec(target_margin=1.0, coefficient=1.0),
        )

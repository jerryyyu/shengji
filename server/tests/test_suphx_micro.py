"""Falsification tests for the Suphx-style feature partition."""
from __future__ import annotations

import copy
import random

import pytest


np = pytest.importorskip("numpy")
pytest.importorskip("torch")

from shengji.ai.smart import SmartBot  # noqa: E402
from shengji.engine.game import Game  # noqa: E402
from shengji.rl.encode import CARD_INDEX, OBS_DIM  # noqa: E402
from shengji.rl.exact_resume import state_digest  # noqa: E402
from shengji.rl.suphx_micro import (  # noqa: E402
    FEATURE_SOURCE_SHA256S,
    FEATURE_SPEC,
    FEATURE_SPEC_SHA256,
    LEGAL_PRIVATE_DIM,
    MASK_SCHEMA,
    PERFECT_DIM,
    SuphxMicroError,
    apply_privilege_mask,
    draw_privilege_mask,
    encode_feature_partition,
    encode_legal_private,
    encode_perfect_features,
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


def _counts(cards):
    result = np.zeros(len(CARD_INDEX), dtype=np.float32)
    for card in cards:
        result[CARD_INDEX[card]] += 0.5
    return result


def test_feature_contract_binds_sources_and_information_semantics():
    assert FEATURE_SPEC_SHA256 == state_digest(FEATURE_SPEC)
    assert FEATURE_SPEC["source_sha256s"] == FEATURE_SOURCE_SHA256S
    assert set(FEATURE_SOURCE_SHA256S) == {
        "suphx_micro", "encode", "memory", "public_history", "cards", "round",
    }
    assert FEATURE_SPEC["normal"]["observation_dim"] == OBS_DIM
    assert FEATURE_SPEC["normal"]["legal_private_dim"] == LEGAL_PRIVATE_DIM
    assert FEATURE_SPEC["perfect"]["dimension"] == PERFECT_DIM
    assert FEATURE_SPEC["mask"]["schema"] == MASK_SCHEMA
    assert FEATURE_SPEC["mask"]["draws_per_decision"] == PERFECT_DIM
    assert FEATURE_SPEC["mask"]["endpoint_draws_are_consumed"] is True


def test_banker_burial_is_legal_private_not_oracle_only():
    rnd = _play_state()
    banker = rnd.banker
    legal = encode_legal_private(rnd, banker)
    perfect = encode_perfect_features(rnd, banker)
    assert np.array_equal(legal, _counts(rnd.buried))
    assert legal.sum() == 4.0  # eight physical cards at 0.5 per copy
    assert np.count_nonzero(legal) > 0
    assert np.array_equal(
        perfect[-len(CARD_INDEX):],
        np.zeros(len(CARD_INDEX), dtype=np.float32),
    )


def test_nonbanker_burial_is_perfect_and_not_legal_private():
    rnd = _play_state()
    seat = (rnd.banker + 1) % 4
    legal = encode_legal_private(rnd, seat)
    perfect = encode_perfect_features(rnd, seat)
    assert np.count_nonzero(legal) == 0
    assert np.array_equal(perfect[-len(CARD_INDEX):], _counts(rnd.buried))
    for relative in range(1, 4):
        start = (relative - 1) * len(CARD_INDEX)
        stop = relative * len(CARD_INDEX)
        assert np.array_equal(
            perfect[start:stop],
            _counts(rnd.hands[(seat + relative) % 4]),
        )


def test_public_endpoint_is_invariant_to_hidden_ownership_but_oracle_is_not():
    rnd = _play_state()
    seat = (rnd.banker + 1) % 4
    # At the first play every hidden hand has the same public card count, so
    # exchanging two exact hidden allocations produces another information-set
    # world without changing any observation available to ``seat``.
    first = encode_feature_partition(rnd, seat)
    changed = copy.deepcopy(rnd)
    hidden_a = (seat + 1) % 4
    hidden_b = (seat + 2) % 4
    changed.hands[hidden_a], changed.hands[hidden_b] = (
        changed.hands[hidden_b], changed.hands[hidden_a])
    second = encode_feature_partition(changed, seat)

    for key in ("observation", "public_history", "legal_private"):
        assert np.array_equal(first[key], second[key]), key
    assert not np.array_equal(first["perfect"], second["perfect"])
    zero = np.zeros(PERFECT_DIM, dtype=np.float32)
    assert np.array_equal(
        apply_privilege_mask(first["perfect"], zero),
        apply_privilege_mask(second["perfect"], zero),
    )


def test_endpoint_masks_consume_equal_named_rng_work():
    zero_rng = random.Random(73)
    one_rng = random.Random(73)
    zero = draw_privilege_mask(0.0, zero_rng)
    one = draw_privilege_mask(1.0, one_rng)
    assert np.count_nonzero(zero) == 0
    assert np.count_nonzero(one) == PERFECT_DIM
    # Both endpoints consumed exactly one draw per element.
    assert zero_rng.getstate() == one_rng.getstate()
    assert zero_rng.random() == one_rng.random()


def test_fractional_mask_is_replayable_and_binary():
    first_rng = random.Random(991)
    second_rng = random.Random(991)
    first = draw_privilege_mask(0.375, first_rng)
    second = draw_privilege_mask(0.375, second_rng)
    assert np.array_equal(first, second)
    assert set(np.unique(first)).issubset({0.0, 1.0})
    assert 0 < np.count_nonzero(first) < PERFECT_DIM


@pytest.mark.parametrize("probability", [-0.01, 1.01, float("nan"), True])
def test_mask_rejects_invalid_probability(probability):
    with pytest.raises(SuphxMicroError, match="probability"):
        draw_privilege_mask(probability, random.Random(1))


def test_mask_application_rejects_shape_dtype_and_nonbinary_drift():
    perfect = np.zeros(PERFECT_DIM, dtype=np.float32)
    mask = np.zeros(PERFECT_DIM, dtype=np.float32)
    assert apply_privilege_mask(perfect, mask).dtype == np.float32
    with pytest.raises(SuphxMicroError, match="perfect tensor"):
        apply_privilege_mask(perfect.astype(np.float64), mask)
    with pytest.raises(SuphxMicroError, match="mask shape"):
        apply_privilege_mask(perfect, mask[:-1])
    changed = mask.copy()
    changed[0] = 0.5
    with pytest.raises(SuphxMicroError, match="binary"):
        apply_privilege_mask(perfect, changed)


def test_feature_encoder_refuses_nonplay_state_and_invalid_seat():
    game = Game(random.Random(8))
    rnd = game.start_round()
    with pytest.raises(SuphxMicroError, match="ordinary-play"):
        encode_feature_partition(rnd, 0)
    play = _play_state(9)
    with pytest.raises(SuphxMicroError, match="range"):
        encode_feature_partition(play, 4)


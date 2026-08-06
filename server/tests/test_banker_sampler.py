"""Banker world-sampling regression (Codex audit, 2026-08-03).

BANKER_KITTY made Memory exclude the banker's own burial from `unseen`,
but the sampler kept subtracting that burial a second time. The pool ended
up 8 cards short of the seats it had to fill, EVERY determinization failed,
and `n_worlds == 0` silently returned candidate 0 — the banker ran with no
search at all while every duel still reported a plausible-looking number.
"""
from __future__ import annotations

import copy
import random
from collections import Counter

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.mcbot import MCBot
from shengji.ai.memory import Memory
from shengji.engine.game import Game


def _round_in_play(seed: int):
    game = Game(random.Random(seed))
    rnd = game.start_round()
    hb = HeuristicBot()
    while rnd.phase != "play":
        if rnd.phase == "deal":
            rnd.deal_next()
        elif rnd.phase == "declare":
            rnd.finalize_declare()
        elif rnd.phase == "bury":
            rnd.bury(rnd.banker, hb.decide_bury(rnd, rnd.banker))
    return rnd


@pytest.mark.parametrize("seed", [5, 7, 11, 13])
def test_banker_sampler_counts_kitty_once(seed):
    rnd = _round_in_play(seed)
    b = rnd.banker
    mem = Memory(rnd, b, own_kitty=True)
    assert mem.own_kitty_known

    need = sum(len(rnd.hands[s]) for s in range(4) if s != b)
    assert len(list(mem.unseen.elements())) == need, \
        "unseen must cover exactly the three opponents' remaining slots"
    # The burial is ours: it must not appear in the unseen pool at all.
    for code, n in Counter(rnd.buried).items():
        assert mem.unseen[code] + n <= 2

    bot = MCBot()
    for _ in range(10):
        sampled = bot._sample_hands(rnd, b, mem)
        assert sampled is not None, "banker sampling failed"
        hands, buried = sampled
        assert sorted(buried) == sorted(rnd.buried)
        # Conservation: sampled hands + burial + our hand = the full deal.
        total = Counter()
        for s, cards in hands.items():
            assert len(cards) == len(rnd.hands[s])
            total += Counter(cards)
        total += Counter(buried) + Counter(rnd.hands[b])
        played = Counter()
        for s in range(4):
            played += Counter(mem.played_by[s])
        assert total + played == Counter(rnd.deck)


@pytest.mark.parametrize("seed", [5, 11])
def test_banker_mc_evaluates_requested_worlds(seed):
    """A banker decision must run real worlds, not the candidate-0 fallback."""
    rnd = _round_in_play(seed)
    b = rnd.banker
    while rnd.turn != b and rnd.phase == "play":
        mv = HeuristicBot().decide_play(rnd, rnd.turn)
        rnd.play(rnd.turn, mv)
    assert rnd.phase == "play" and rnd.turn == b

    bot = MCBot()
    if len(bot._candidates(rnd, b)) <= 1:
        pytest.skip("forced move — no search to verify")
    bot.decide_play(rnd, b)
    assert bot.last_n_worlds == bot.N_DETERMINIZATIONS, \
        f"banker searched {bot.last_n_worlds} worlds, expected full sample"


def test_non_banker_sampling_unaffected():
    rnd = _round_in_play(5)
    other = next(s for s in range(4) if s != rnd.banker)
    mem = Memory(rnd, other, own_kitty=True)
    assert not mem.own_kitty_known
    sampled = MCBot()._sample_hands(rnd, other, mem)
    assert sampled is not None
    _, kitty = sampled
    assert len(kitty) == len(rnd.buried)


def test_encoder_kitty_contract_unchanged():
    """Bot memory may know the burial; the RL ENCODING must not drift.

    Changing what encode_obs() sees while ENC_VERSION stays 1 would make
    existing shards and checkpoints silently mismatched (Codex).
    """
    from shengji.rl.encode import (CARD_INDEX, ENCODER_IMPLEMENTATION_SHA256,
                                   ENCODER_SOURCE_SHA256S, ENC_VERSION,
                                   N_CARDS, OBS_DIM, OBS_SCHEMA, encode_obs)

    rnd = _round_in_play(5)
    b = rnd.banker
    assert ENC_VERSION == 1 and OBS_DIM == 531
    assert OBS_SCHEMA == "rl-observation-v1-public-no-private-kitty"
    assert len(ENCODER_IMPLEMENTATION_SHA256) == 64
    assert set(ENCODER_SOURCE_SHA256S) == {"encode", "memory"}
    vec = encode_obs(rnd, b)
    assert len(vec) == OBS_DIM

    # Change only information encoder-v1 deliberately does not expose: swap a
    # buried card with one hidden in an opponent's hand.  The previous test
    # rebuilt the identical deal and therefore passed even after Memory's new
    # own-kitty default silently changed the banker vector.
    altered = copy.copy(rnd)
    altered.hands = [list(hand) for hand in rnd.hands]
    altered.buried = list(rnd.buried)
    opponent = next(seat for seat in range(4) if seat != b)
    swap = next(
        (bury_i, hand_i)
        for bury_i, buried in enumerate(altered.buried)
        for hand_i, hidden in enumerate(altered.hands[opponent])
        if buried != hidden
    )
    bury_i, hand_i = swap
    altered.buried[bury_i], altered.hands[opponent][hand_i] = (
        altered.hands[opponent][hand_i], altered.buried[bury_i])
    assert altered.buried != rnd.buried
    assert altered.hands[b] == rnd.hands[b]
    assert encode_obs(altered, b) == vec

    unseen_offset = 8 * N_CARDS
    expected = [0.0] * N_CARDS
    for card, count in Memory(rnd, b, own_kitty=False).unseen.items():
        expected[CARD_INDEX[card]] = count * 0.5
    assert vec[unseen_offset:unseen_offset + N_CARDS] == expected
    # This is a real witness: the new bot-memory semantics do distinguish the
    # two legal private burials, so relying on Memory's default would fail the
    # encoder-v1 invariance above.
    assert (Memory(rnd, b, own_kitty=True).unseen !=
            Memory(altered, b, own_kitty=True).unseen)

"""Issue #339 layer 2, measurement half: the report fold records, per candidate,
how many of its report worlds a throw would FAIL validation in (the sampler's
own failure estimate).  No decision reads it; the realised 45% calibrates it."""
import random

from shengji.ai.memory import Memory
from shengji.ai.registry import make_bot
from shengji.engine.legal import uniform_suit, validate_lead
from tests.test_world_shortlist import play_state


def _lead_state():
    """A play state where it is the mover's lead and the hand holds a throw
    (a pair plus another card of the same effective suit)."""
    for seed in range(431, 600):
        rnd = play_state(seed)
        seat = rnd.turn
        if rnd.trick is not None and rnd.trick.plays:
            continue
        hand = rnd.hands[seat]
        by_suit = {}
        for c in hand:
            by_suit.setdefault(uniform_suit([c], rnd.ordering), []).append(c)
        for suit, cards in by_suit.items():
            pairs = [c for c in set(cards) if cards.count(c) == 2]
            singles = [c for c in set(cards) if cards.count(c) == 1]
            if pairs and singles:
                # a pair plus a single of the same suit is a two-component throw
                return rnd, seat, [pairs[0], pairs[0], singles[0]], [singles[0]]
    raise AssertionError("no lead state with a throw in 170 seeds")


def test_report_fold_counts_sampled_throw_failures_per_candidate():
    rnd, seat, throw, single = _lead_state()
    bot = make_bot("mc-s0-report-lcb")
    bot.rng = random.Random(5)
    mem = Memory(rnd, seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
    out = bot._report_fold_gap(rnd, seat, mem, rnd.is_attacker(seat), throw, single, 30, seed=7)
    assert out["complete"] and out["worlds"] == 30
    f = out["throw_fail_worlds"]
    assert 0 <= f["challenger"] <= 30 and f["incumbent"] == 0
    assert out["p_fail_sampled"]["challenger"] == f["challenger"] / 30
    assert out["p_fail_sampled"]["incumbent"] is None  # a single never fails
    # the count is the engine's own verdict on the same worlds, re-derived here
    # with the fold's own sampling loop (same seed, same attempt cap)
    bot.rng = random.Random(7)
    fails = used = attempts = 0
    while used < 30 and attempts < 30 * bot.SAMPLE_ATTEMPT_FACTOR:
        attempts += 1
        sampled = bot._sample_hands(rnd, seat, mem)
        if sampled is None:
            continue
        hands, _ = sampled
        _, msg = validate_lead(list(throw), rnd.hands[seat], [hands[s] for s in sorted(hands)], rnd.ordering)
        fails += msg is not None
        used += 1
    assert f["challenger"] == fails


def test_report_fold_without_a_throw_carries_no_failure_keys():
    rnd, seat, throw, single = _lead_state()
    bot = make_bot("mc-s0-report-lcb")
    mem = Memory(rnd, seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
    out = bot._report_fold_gap(rnd, seat, mem, rnd.is_attacker(seat), single, [rnd.hands[seat][0]], 5, seed=1)
    assert "p_fail_sampled" not in out and "throw_fail_worlds" not in out


def test_gap_and_se_are_unchanged_by_the_counting():
    """The counts are read-only on the world: same seed, same gap/se with and
    without a throw among the candidates' companions."""
    rnd, seat, throw, single = _lead_state()
    bot = make_bot("mc-s0-report-lcb")
    mem = Memory(rnd, seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
    a = bot._report_fold_gap(rnd, seat, mem, rnd.is_attacker(seat), throw, single, 20, seed=3)
    b = bot._report_fold_gap(rnd, seat, mem, rnd.is_attacker(seat), throw, single, 20, seed=3)
    assert (a["gap"], a["se"], a["worlds"]) == (b["gap"], b["se"], b["worlds"])

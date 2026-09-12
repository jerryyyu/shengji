"""Issue #339 layer 2, measurement half: the report fold records, per candidate,
how many of its report worlds a multi-component throw would FAIL validation in
(the sampler's own failure estimate).  No decision reads it; the realised 45%
calibrates it.  The counts must survive the harvest serializers."""
import json
import random

from shengji.ai.memory import Memory
from shengji.ai.registry import make_bot
from shengji.engine.legal import uniform_suit, validate_lead
from shengji.harvest import room_log, trajectory
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
                return rnd, seat, [pairs[0], pairs[0], singles[0]], [pairs[0], pairs[0]], [singles[0]]
    raise AssertionError("no lead state with a throw in 170 seeds")


def _bot(count=True):
    bot = make_bot("mc-s0-report-lcb")
    bot.REPORT_THROW_FAIL_COUNT = count
    return bot


def test_report_fold_counts_sampled_throw_failures_per_candidate():
    rnd, seat, throw, pair, single = _lead_state()
    bot = _bot()
    mem = Memory(rnd, seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
    out = bot._report_fold_gap(rnd, seat, mem, rnd.is_attacker(seat), throw, single, 30, seed=7)
    assert out["complete"] and out["worlds"] == 30
    f = out["throw_fail_worlds"]
    assert 0 <= f["challenger"] <= 30 and f["incumbent"] is None  # a single is not a throw
    assert out["p_fail_sampled"] == {"challenger": f["challenger"] / 30, "incumbent": None}
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


def test_pairs_and_singles_are_not_throws_so_no_keys_and_a_pair_incumbent_is_none():
    rnd, seat, throw, pair, single = _lead_state()
    bot = _bot()
    mem = Memory(rnd, seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
    out = bot._report_fold_gap(rnd, seat, mem, rnd.is_attacker(seat), pair, single, 5, seed=1)
    assert "p_fail_sampled" not in out and "throw_fail_worlds" not in out
    out = bot._report_fold_gap(rnd, seat, mem, rnd.is_attacker(seat), throw, pair, 5, seed=1)
    assert out["throw_fail_worlds"]["incumbent"] is None and out["p_fail_sampled"]["incumbent"] is None
    assert isinstance(out["throw_fail_worlds"]["challenger"], int)


def test_counting_disabled_versus_enabled_gives_identical_gap_se_and_deltas():
    """Old-vs-new parity on identical worlds: the control is the knob OFF."""
    rnd, seat, throw, pair, single = _lead_state()
    mem = Memory(rnd, seat, own_kitty=True)
    off = _bot(count=False)._report_fold_gap(rnd, seat, mem, rnd.is_attacker(seat), throw, single, 20,
                                             seed=3, keep_deltas=True)
    on = _bot(count=True)._report_fold_gap(rnd, seat, mem, rnd.is_attacker(seat), throw, single, 20,
                                           seed=3, keep_deltas=True)
    assert "p_fail_sampled" not in off and "p_fail_sampled" in on
    assert (off["gap"], off["se"], off["worlds"], off["attempts"]) == (on["gap"], on["se"], on["worlds"], on["attempts"])
    assert off["deltas"] == on["deltas"]


def _record(fold):
    return {"means": [1.0, 2.0], "paired_se": [0.1, 0.1], "eligible_indices": [0, 1],
            "raw_winner_index": 1, "report_fold": fold}


def test_harvest_serializers_keep_exact_counts_and_probabilities_through_json():
    fold = {"gap": 0.5, "se": 0.2, "worlds": 30, "attempts": 31, "rejected": 1, "complete": True,
            "rule": "lcb", "critical": 1.7, "statistic": 0.16, "min_gain": 0.0, "bound": "b",
            "throw_fail_worlds": {"challenger": 17, "incumbent": None},
            "p_fail_sampled": {"challenger": 17 / 30, "incumbent": None}}
    saved = json.loads(json.dumps(trajectory.action_values_from_record(_record(fold))))
    assert saved["report"]["throw_fail_worlds"] == {"challenger": 17, "incumbent": None}
    assert saved["report"]["p_fail_sampled"]["challenger"] == 17 / 30
    assert saved["report"]["p_fail_sampled"]["incumbent"] is None
    assert saved["report"]["gap"] == 0.5 and saved["report"]["worlds"] == 30
    logged = json.loads(json.dumps(room_log._allocation_from_decision({"report_fold": fold})))
    assert logged["report_fold"]["throw_fail_worlds"]["challenger"] == 17
    # an older record without the fields still serialises, with the keys absent-as-None
    old = trajectory.action_values_from_record(_record({k: v for k, v in fold.items() if not k.startswith(("throw", "p_fail"))}))
    assert old["report"]["throw_fail_worlds"] is None and old["report"]["p_fail_sampled"] is None

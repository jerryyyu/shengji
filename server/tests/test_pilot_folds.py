"""The fold machinery is the pilot's validity, so it gets real tests.

If proposal and report worlds overlap, a wider ballot wins the pilot for having
more draws to select a maximum from, not for proposing better actions — the
select-and-test-on-the-same-worlds defect that made the high-N corpus's `best`
and `gap` columns unusable. A wider-ballot arm is exactly the shape that would
exploit it, so "the streams differ, therefore the worlds differ" is not good
enough: different streams can and do produce the same world in constrained
late states.
"""
from __future__ import annotations

import random

import pytest

from shengji.ai.memory import Memory
from shengji.ai.registry import make_bot
from shengji.engine.game import Game
from shengji.pilot_folds import (FOLDS, FoldedWorlds, draw_folds, stream_seed,
                                 world_key)


def _state(seed=771000, min_tricks=2):
    game = Game(random.Random(seed))
    bots = [make_bot("smart") for _ in range(4)]
    rnd = game.start_round()
    while rnd.phase == "deal":
        s, _, _ = rnd.deal_next()
        cs = bots[s].decide_declare(rnd, s)
        if cs:
            rnd.declare(s, cs)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bots[rnd.banker].decide_bury(rnd, rnd.banker))
    while rnd.phase == "play" and len(rnd.history) < min_tricks:
        s = rnd.turn
        rnd.play(s, bots[s].decide_play(rnd, s))
    return rnd, rnd.turn


def test_streams_are_independent_across_folds_and_states():
    """Hash-derived, not base+offset: an additive scheme collides invisibly."""
    seeds = {(st, f): stream_seed("s", st, f)
             for st in ("a", "b", "c") for f in FOLDS}
    assert len(set(seeds.values())) == len(seeds), "stream seeds collided"
    # same inputs reproduce
    assert stream_seed("s", "a", "report") == stream_seed("s", "a", "report")
    # salt actually participates
    assert stream_seed("s", "a", "report") != stream_seed("t", "a", "report")


def test_unknown_fold_is_refused():
    with pytest.raises(ValueError):
        stream_seed("s", "k", "reportt")


def test_world_key_is_seat_aware():
    """Seats carry different voids; sorting hands together would call two
    genuinely different worlds equal — the bug that collapsed 90 assignments
    into 9 shapes in the action-semantics enumerator."""
    a = world_key({1: ["S3"], 2: ["S4"]}, [])
    b = world_key({1: ["S4"], 2: ["S3"]}, [])
    assert a != b


def test_every_successful_draw_is_kept():
    """Independence comes from the STREAMS, not from disjoint support.

    Rejecting a world because another fold drew it conditions this fold on
    that one. With P(A)=0.8/P(B)=0.2, dropping the proposal outcome from a
    two-world report fold makes report A appear only when proposal drew B —
    0.2 instead of 0.8 (Codex). The first version of this module did exactly
    that and called it disjointness.
    """
    rnd, seat = _state()
    bot = make_bot("mc", seed=5)
    mem = Memory(rnd, seat)
    counts = {"proposal": 6, "oracle": 6, "report": 6}
    drawn = draw_folds(bot, rnd, seat, mem, counts, salt="t", state_key="s1")
    for f in FOLDS:
        assert len(drawn.worlds[f]) == counts[f], \
            f"{f} came up short; draws must not be filtered"


def test_coincidences_are_counted_not_rejected():
    """Overlap is a diagnostic. A fold that reports it must not act on it."""
    shared = FoldedWorlds(state_key="x")
    w = ({1: ["S3"], 2: ["S4"], 3: ["S5"]}, [])
    shared.worlds = {"proposal": [w], "oracle": [w], "report": []}
    assert shared.shared_keys() == 1
    assert not hasattr(shared, "assert_disjoint"), \
        "disjointness must not be enforced; enforcing it is the bias"


def test_drawing_one_fold_cannot_shift_another():
    """Folds must not consume a shared generator.

    Drawing report first, then proposal, must give the same proposal worlds as
    drawing them in the declared order — otherwise one consumer silently moves
    another and reruns stop reproducing.
    """
    rnd, seat = _state()
    mem = Memory(rnd, seat)
    counts = {"proposal": 5, "oracle": 5, "report": 5}

    a = draw_folds(make_bot("mc", seed=1), rnd, seat, mem, counts,
                   salt="t", state_key="s2")
    # a different caller RNG state must not change the folds
    other = make_bot("mc", seed=999)
    for _ in range(37):
        other.rng.random()
    b = draw_folds(other, rnd, seat, mem, counts, salt="t", state_key="s2")
    for f in FOLDS:
        assert a.keys(f) == b.keys(f), \
            f"{f} fold depended on the caller's RNG state"


def test_same_state_reproduces_and_different_states_differ():
    rnd, seat = _state()
    mem = Memory(rnd, seat)
    counts = {"proposal": 4, "oracle": 4, "report": 4}
    a = draw_folds(make_bot("mc", seed=2), rnd, seat, mem, counts,
                   salt="t", state_key="k1")
    b = draw_folds(make_bot("mc", seed=2), rnd, seat, mem, counts,
                   salt="t", state_key="k1")
    c = draw_folds(make_bot("mc", seed=2), rnd, seat, mem, counts,
                   salt="t", state_key="k2")
    assert a.keys("report") == b.keys("report"), "same state must reproduce"
    assert a.keys("report") != c.keys("report"), "different states must differ"


def test_caller_rng_object_is_restored():
    """The original OBJECT, not an equivalent Random carrying its state.

    Anything holding a reference to `bot.rng` would otherwise keep the old
    object while the bot used a new one (Codex).
    """
    rnd, seat = _state()
    mem = Memory(rnd, seat)
    bot = make_bot("mc", seed=11)
    before_obj = bot.rng
    before = bot.rng.getstate()
    draw_folds(bot, rnd, seat, mem, {"proposal": 3, "oracle": 3, "report": 3},
               salt="t", state_key="s3")
    assert bot.rng is before_obj, "a NEW Random was installed, not the original"
    assert bot.rng.getstate() == before, "the bot's RNG state was not restored"


def test_fold_stats_name_every_requested_and_failed_draw(monkeypatch):
    rnd, seat = _state()
    mem = Memory(rnd, seat)
    bot = make_bot("mc", seed=11)
    real = bot._sample_hands
    calls = 0

    def reject_first(*args):
        nonlocal calls
        calls += 1
        return None if calls == 1 else real(*args)

    monkeypatch.setattr(bot, "_sample_hands", reject_first)
    counts = {"proposal": 2, "oracle": 2, "report": 2}
    drawn = draw_folds(bot, rnd, seat, mem, counts, salt="t", state_key="stats")
    stats = drawn.stats()
    assert set(stats) == set(FOLDS)
    assert stats["proposal"] == {
        "requested": 2, "accepted": 2, "attempts": 3, "rejected": 1,
        "short": 0, "collision_within": stats["proposal"]["collision_within"],
        "collision_cross": stats["proposal"]["collision_cross"],
    }
    assert all(stats[f]["requested"] == stats[f]["accepted"] == 2
               for f in FOLDS)

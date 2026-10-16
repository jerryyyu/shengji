"""Parity and guard gates for the opt-in native MC rollout loop.

``SHENGJI_MC_NATIVE_ROLLOUT=1`` routes every ``MCBot._rollout`` continuation
through ``_fast.rollout_play_loop``.  The contract is exact: the same
decision, the same decision record and the same RNG stream as the Python
loop, because the continuation draws no random numbers and the native loop
reaches the same routed sub-decisions.  In pure mode the flag is a no-op.
"""

from __future__ import annotations

import copy
import os
import random

import pytest

from shengji.ai import mcbot
from shengji.ai.heuristic import HeuristicBot
from shengji.ai.registry import make_bot
from shengji.engine import fast
from shengji.engine.game import Game
from shengji.engine.round import Round, Trick, TrickPlay

COMPILED = fast.HAVE_FAST and os.environ.get("SHENGJI_FAST") == "1"


def _state(rnd):
    return (
        rnd.phase, rnd.turn, rnd.attacker_points, rnd.kitty_bonus,
        rnd.last_trick_winner, rnd.message, [list(h) for h in rnd.hands],
        [(t.winner, t.points, [(p.seat, list(p.cards)) for p in t.plays])
         for t in rnd.history],
        None if rnd.trick is None else
        (rnd.trick.leader, [(p.seat, list(p.cards)) for p in rnd.trick.plays],
         rnd.trick.incumbent, rnd.trick.running_points),
    )


def _prepared_round(seed):
    game = Game(random.Random(seed))
    actors = [make_bot("smart") for _ in range(4)]
    rnd = game.start_round()
    while rnd.phase == "deal":
        s, _, _ = rnd.deal_next()
        c = actors[s].decide_declare(rnd, s)
        if c:
            rnd.declare(s, c)
    for s in range(4):
        c = actors[s].decide_declare(rnd, s, final=True)
        if c:
            rnd.declare(s, c)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, list(actors[rnd.banker].decide_bury(rnd, rnd.banker)))
    return rnd, actors


def _advance(rnd, actors, plays):
    for _ in range(plays):
        if rnd.phase != "play":
            break
        s = rnd.turn
        rnd.play(s, actors[s].decide_play(rnd, s))


def _clone_for_rollout(rnd, hands, buried, seat, candidate):
    """Exactly what ``MCBot._rollout`` builds before its play loop."""
    clone = copy.copy(rnd)
    clone.hands = [list(h) for h in hands]
    clone.buried = sorted(buried)
    clone.trick = Trick(
        leader=rnd.trick.leader,
        plays=[TrickPlay(p.seat, list(p.cards)) for p in rnd.trick.plays])
    clone.history = list(rnd.history)
    clone.last_trick = rnd.last_trick
    clone.message = None
    clone._trusted_rollout = True
    clone._determinized_world = True
    clone.play(seat, list(candidate))
    return clone


def _pure_loop(clone, policy):
    while clone.phase == "play":
        s = clone.turn
        clone.play(s, policy.decide_play(clone, s))
    return float(clone.attacker_points)


def _sampled_worlds(bot, rnd, seat, n):
    from shengji.ai.memory import Memory

    mem = Memory(rnd, seat, own_kitty=True)
    out = []
    while len(out) < n:
        got = bot._sample_hands(rnd, seat, mem)
        if got is not None:
            hands, buried = got
            out.append((bot._complete_determinized_hands(
                rnd, seat, hands, buried=buried), buried))
    return out


def test_flag_is_off_by_default_and_read_from_the_environment():
    assert mcbot.NATIVE_ROLLOUT is bool(os.environ.get("SHENGJI_MC_NATIVE_ROLLOUT"))
    assert (fast.rollout_play_loop is None) == (not fast.HAVE_FAST)


@pytest.mark.skipif(not COMPILED, reason="compiled engine routing required")
def test_native_loop_matches_pure_loop_state_for_state():
    assert fast.activate()
    bot = make_bot("mc")
    policy = HeuristicBot()
    checked = 0
    for seed, plays in ((7101, 0), (7102, 5), (7103, 17), (7104, 40), (7105, 61)):
        rnd, actors = _prepared_round(seed)
        _advance(rnd, actors, plays)
        if rnd.phase != "play":
            continue
        seat = rnd.turn
        cands = bot._candidates(rnd, seat)
        for hands, buried in _sampled_worlds(bot, rnd, seat, 3):
            for cand in cands[:3]:
                a = _clone_for_rollout(rnd, hands, buried, seat, cand)
                b = _clone_for_rollout(rnd, hands, buried, seat, cand)
                native = fast.rollout_play_loop(a, policy)
                assert native is not None, "guard missed on a trusted clone"
                pure = _pure_loop(b, policy)
                assert float(native) == pure
                assert _state(a) == _state(b)
                checked += 1
    assert checked >= 30


@pytest.mark.skipif(not COMPILED, reason="compiled engine routing required")
def test_native_loop_covers_refused_throw_leads():
    """A throw the world beats is downgraded by validate_lead with a message;
    the native lead branch must commit the forced play and the trick caches
    exactly as the pure method does.  A one-shot lead policy (decide_play
    inherited, so the loop admits it) throws the leader's whole longest plain
    suit once, then plays the heuristic."""
    assert fast.activate()

    class OneThrow(HeuristicBot):
        def __init__(self, throw):
            super().__init__()
            self.throw = list(throw)

        def _lead(self, rnd, seat):
            if self.throw:
                throw, self.throw = self.throw, []
                return throw
            return fast._fast.heuristic_lead(self, rnd, seat)

    refused = checked = 0
    for seed in range(7301, 7361):
        rnd, actors = _prepared_round(seed)
        rnd._trusted_rollout = True
        _advance(rnd, actors, 4 * (seed % 5))
        if rnd.phase != "play" or rnd.trick.plays:
            continue
        s = rnd.turn
        o = rnd.ordering
        suits = {}
        for c in rnd.hands[s]:
            if o.eff_suit(c) != "T":
                suits.setdefault(o.eff_suit(c), []).append(c)
        throw = max(suits.values(), key=len, default=None)
        if not throw or len(throw) < 3:
            continue
        a, b = copy.copy(rnd), copy.copy(rnd)
        for x in (a, b):
            x.hands = [list(h) for h in rnd.hands]
            x.trick = Trick(leader=rnd.trick.leader)
            x.history = list(rnd.history)
        native = fast.rollout_play_loop(a, OneThrow(throw))
        assert native is not None
        pure = _pure_loop(b, OneThrow(throw))
        assert float(native) == pure
        assert _state(a) == _state(b)
        checked += 1
        committed = a.history[len(rnd.history)].plays[0]
        assert committed.seat == s
        if len(committed.cards) < len(throw):
            refused += 1
    assert checked >= 10
    assert refused >= 3, refused


def test_decision_record_and_rng_stream_identical_flag_on_and_off(monkeypatch):
    """The flag changes neither the played cards nor any logged statistic nor
    the RNG position: a screen pairing against an archived control history
    reads the same decisions whichever loop ran."""
    if fast.HAVE_FAST and os.environ.get("SHENGJI_FAST") == "1":
        assert fast.activate()
    cls = type("MCTiny", (mcbot.MCBot,), {
        "N_DETERMINIZATIONS": 4, "REQUIRE_EXACT_WORK": True,
        "REPORT_FOLD_WORLDS": 30, "REPORT_RULE": "lcb", "REPORT_MIN_GAIN": 0.0})
    contested = 0
    for seed, plays in ((7201, 3), (7202, 22), (7203, 48)):
        results = []
        for flag in (False, True):
            monkeypatch.setattr(mcbot, "NATIVE_ROLLOUT", flag)
            rnd, actors = _prepared_round(seed)
            _advance(rnd, actors, plays)
            bot = cls(seed=99)
            seat = rnd.turn
            played = bot.decide_play(rnd, seat)
            rec = bot.last_decision_record
            results.append((
                played, bot.rng.getstate(),
                None if rec is None else (
                    rec["played"], rec["reason"], rec["means"], rec["paired_se"],
                    rec["report_seed"], rec.get("report_fold"),
                    rec["sampler_counters"]["delta"]),
                bot.rollouts, bot.sample_attempts))
            if rec is not None:
                contested += 1
        assert results[0] == results[1], seed
    assert contested >= 2


@pytest.mark.skipif(not COMPILED, reason="compiled engine routing required")
def test_guard_misses_return_none_before_any_mutation():
    assert fast.activate()
    rnd, actors = _prepared_round(7401)
    _advance(rnd, actors, 9)
    seat = rnd.turn
    policy = HeuristicBot()
    bot = make_bot("mc")
    (hands, buried), = _sampled_worlds(bot, rnd, seat, 1)
    cand = bot._candidates(rnd, seat)[0]

    untrusted = _clone_for_rollout(rnd, hands, buried, seat, cand)
    untrusted._trusted_rollout = False
    before = _state(untrusted)
    assert fast.rollout_play_loop(untrusted, policy) is None
    assert _state(untrusted) == before

    class Overriding(HeuristicBot):
        def decide_play(self, rnd, seat):  # a subclass keeps its own semantics
            return super().decide_play(rnd, seat)

    clone = _clone_for_rollout(rnd, hands, buried, seat, cand)
    before = _state(clone)
    assert fast.rollout_play_loop(clone, Overriding()) is None
    assert _state(clone) == before

    class NotARound(Round):
        pass

    foreign = NotARound.__new__(NotARound)
    foreign.__dict__.update(clone.__dict__)
    assert fast.rollout_play_loop(foreign, policy) is None

    # deactivated routing: the entry defers unconditionally
    fast.deactivate()
    try:
        assert fast.rollout_play_loop(clone, policy) is None
        assert _state(clone) == before
    finally:
        assert fast.activate()

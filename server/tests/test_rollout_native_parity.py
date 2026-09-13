"""Parity gate for the compiled rollout driver (``_fast.rollout_trusted``).

With the fast path active, MCBot drives trusted rollouts through one C loop
(``engine.fast.ROLLOUT``) instead of the Python ``while`` loop around
``HeuristicBot.decide_play`` and ``Round.play``.  The driver must leave the
clone in exactly the state the pure loop leaves it in, must refuse anything
outside the trusted HeuristicBot contract before touching the round, and must
actually be the path MCBot takes (a witness, so the gate cannot pass through
the pure fallback).  ``SHENGJI_FAST_ROLLOUT=0`` keeps the driver off.
"""

from __future__ import annotations

import copy
import random

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.mcbot import MCBot
from shengji.ai.registry import make_bot
from shengji.engine import fast
from shengji.engine.game import Game

if not fast.HAVE_FAST:
    pytest.skip("compiled engine required", allow_module_level=True)

assert fast.activate()
NATIVE = fast._fast.rollout_trusted


def _play_round(seed):
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


def _pure_loop(rnd, policy):
    """The driver MCBot used before: pure decide_play + Round.play per play."""
    while rnd.phase == "play":
        s = rnd.turn
        assert s is not None
        rnd.play(s, policy.decide_play(rnd, s))
    return float(rnd.attacker_points)


def _state(rnd):
    return (rnd.phase, rnd.turn, rnd.attacker_points, rnd.kitty_bonus,
            rnd.last_trick_winner, rnd.message, [list(h) for h in rnd.hands],
            [(t.leader, t.winner, t.points, [(p.seat, list(p.cards)) for p in t.plays])
             for t in rnd.history],
            None if rnd.trick is None else [(p.seat, list(p.cards)) for p in rnd.trick.plays])


@pytest.mark.parametrize("seed", [7101, 7102, 7103, 7104, 7105, 7106, 7107, 7108])
def test_native_driver_leaves_the_same_end_state_from_every_start(seed):
    """From the fresh round and from every fourth play of a reference game,
    the native driver and the pure loop end in the same state."""
    policy = HeuristicBot()
    rnd, actors = _play_round(seed)
    starts = 0
    ref = copy.deepcopy(rnd)
    k = 0
    while ref.phase == "play":
        if k % 4 == 0 or ref.trick.plays:  # trick boundaries AND mid-trick states
            a = copy.deepcopy(ref)
            b = copy.deepcopy(ref)
            a._trusted_rollout = True
            b._trusted_rollout = True
            pa = _pure_loop(a, policy)
            pb = float(NATIVE(b, policy))
            assert pa == pb, (seed, k, pa, pb)
            assert _state(a) == _state(b), (seed, k)
            assert a.phase == "round_end" and a.turn is None and a.trick is None
            starts += 1
        s = ref.turn
        ref.play(s, actors[s].decide_play(ref, s))
        k += 1
    assert starts >= 40


def test_native_driver_refuses_off_contract_states_before_mutating():
    policy = HeuristicBot()
    rnd, _ = _play_round(7201)
    before = _state(rnd)
    with pytest.raises(RuntimeError):  # not a trusted rollout clone
        NATIVE(rnd, policy)
    assert _state(rnd) == before
    rnd._trusted_rollout = True

    class Sub(HeuristicBot):  # a subclass could override decide_play
        pass

    with pytest.raises(RuntimeError):
        NATIVE(rnd, Sub())
    assert _state(rnd) == before
    # the trusted round + built-in policy contract is accepted and completes
    assert NATIVE(copy.deepcopy(rnd), policy) >= 0


def _first_play_state(seed):
    rnd, actors = _play_round(seed)
    for _ in range(9):  # into the third trick so both loops see follows and leads
        s = rnd.turn
        rnd.play(s, actors[s].decide_play(rnd, s))
    return rnd


def test_mcbot_takes_the_native_driver_and_decides_identically(monkeypatch):
    """Witness + decision parity: with ROLLOUT set MCBot's rollouts go through
    the kernel (counted), and the chosen play equals the pure loop's for the
    same seed.  Bury rollouts share the gate: witnessed through a bury."""
    calls = {"n": 0}

    def counting(rnd, policy):
        calls["n"] += 1
        return NATIVE(rnd, policy)

    for seed in (7301, 7302, 7303):
        rnd = _first_play_state(seed)
        s = rnd.turn
        monkeypatch.setattr(fast, "ROLLOUT", counting)
        native_pick = MCBot(seed=11).decide_play(copy.deepcopy(rnd), s)
        n_native = calls["n"]
        monkeypatch.setattr(fast, "ROLLOUT", None)
        pure_pick = MCBot(seed=11).decide_play(copy.deepcopy(rnd), s)
        assert calls["n"] == n_native  # the pure run never touched the kernel
        assert n_native > 0, seed
        assert native_pick == pure_pick, (seed, native_pick, pure_pick)


def test_bury_rollouts_take_the_native_driver(monkeypatch):
    calls = {"n": 0}

    def counting(rnd, policy):
        calls["n"] += 1
        return NATIVE(rnd, policy)

    game = Game(random.Random(7401))
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
    monkeypatch.setattr(fast, "ROLLOUT", counting)
    # the bury search is off by default and, without the structured candidate
    # source, usually has one candidate and never rolls out: turn both on
    bot = MCBot(seed=5)
    bot.MC_BURY = bot.STRUCTURED_BURY = True
    a = bot.decide_bury(copy.deepcopy(rnd), rnd.banker)
    n = calls["n"]
    monkeypatch.setattr(fast, "ROLLOUT", None)
    bot = MCBot(seed=5)
    bot.MC_BURY = bot.STRUCTURED_BURY = True
    b = bot.decide_bury(copy.deepcopy(rnd), rnd.banker)
    assert n > 0 and calls["n"] == n
    assert a == b


def test_exact_endgame_keeps_the_pure_loop(monkeypatch):
    """EXACT_ENDGAME interleaves an exact solve with every play; the driver
    cannot host that, so the gate must leave such bots on the Python loop."""
    calls = {"n": 0}

    def counting(rnd, policy):
        calls["n"] += 1
        return NATIVE(rnd, policy)

    monkeypatch.setattr(fast, "ROLLOUT", counting)
    rnd = _first_play_state(7501)
    bot = MCBot(seed=3)
    monkeypatch.setattr(bot, "EXACT_ENDGAME", True)
    bot.decide_play(copy.deepcopy(rnd), rnd.turn)
    assert calls["n"] == 0


def test_opt_out_env_keeps_the_driver_off(monkeypatch):
    monkeypatch.setenv("SHENGJI_FAST_ROLLOUT", "0")
    fast.deactivate()
    try:
        assert fast.activate() and fast.ROLLOUT is None
    finally:
        fast.deactivate()
        monkeypatch.delenv("SHENGJI_FAST_ROLLOUT")
        assert fast.activate() and fast.ROLLOUT is NATIVE

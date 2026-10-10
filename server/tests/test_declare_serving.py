"""Serving the value-guided declaration (``SHENGJI_PV_VALUE_DECLARE``) off the event loop.

`server.run_deal` used to call ``room.bot.decide_declare`` synchronously, under the
room lock, on the event loop.  For a value-declaring bot a GATED call
(`PVSearchBot.declare_gate`) now runs on isolated copies in a worker, under
``DECLARE_BUDGET_SECONDS``, and is committed only if the round is unchanged.

Witnesses: (a) flag off: `run_deal` takes the old synchronous path and never the
off-loop one, for the heuristic bot and for a flag-off pv-search bot; (b) the
gate is exactly the one `decide_declare` applies; (c) off-loop: the worker runs on
another thread while the loop keeps serving (a worker that waits for the loop
would deadlock if it ran on it); (d) expiry and error fall back to the heuristic
with a ``pv-declare-serving-fallback-v1`` record; (e) a human declaration or a
seat claim during the evaluation discards the result, and the grace-window pass
asks the seat again; (f) with no interference the off-loop deal reaches the same
declarations and trump as the synchronous path on the real pv-search bot.
"""
from __future__ import annotations

import asyncio
import logging
import random
import threading

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.api import server as srv
from shengji.engine.game import Game
from shengji.train import pv_search_policy as pv
from test_pv_value_declare import NTEvaluator, RaisingEvaluator, served

# Module-level so a deep-copied bot shares them (threading primitives do not copy).
RELEASE = threading.Event()
LOOP_TICKED = threading.Event()
CALLS: list[dict] = []


class GateBot(HeuristicBot):
    """A value-declaring stand-in: the heuristic gate, a scripted evaluation."""

    value_declare = True
    serving_budget_seconds = None
    policy_name = "gate-bot"
    last_declare_record = None

    def __init__(self, behavior: str = "strongest"):
        self.behavior = behavior

    def declare_gate(self, rnd, seat, final=False):
        heuristic = HeuristicBot.decide_declare(self, rnd, seat, final)
        return heuristic, bool(rnd.declare_options(seat) and (final or heuristic is not None))

    def decide_declare(self, rnd, seat, final=False):
        CALLS.append({"thread": threading.get_ident(), "seat": seat, "final": final,
                      "budget": self.serving_budget_seconds})
        if self.behavior == "wait-for-loop":
            assert LOOP_TICKED.wait(5.0), "the event loop never ran while the worker waited"
        elif self.behavior == "block":
            RELEASE.wait(10.0)
        elif self.behavior == "block-once":
            if sum(1 for c in CALLS if c["seat"] == seat) == 1:
                RELEASE.wait(10.0)
        elif self.behavior == "error":
            raise RuntimeError("value head exploded")
        options = rnd.declare_options(seat)
        self.last_declare_record = {"schema": "test-declare-v1", "seat": seat}
        return list(options[-1]) if options else None


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    RELEASE.clear()
    LOOP_TICKED.clear()
    CALLS.clear()
    monkeypatch.setattr(srv, "DEAL_DELAY", 0.0)
    monkeypatch.setattr(srv, "kick_bots", lambda room: None)
    yield
    RELEASE.set()          # never leave a worker thread blocked
    LOOP_TICKED.set()


def _room(bot, *, dealt: bool, seed: int = 5, humans=()) -> srv.Room:
    room = srv.Room(code="DECL", bot=bot)
    room.game = Game(random.Random(seed))
    rnd = room.game.start_round()
    if dealt:
        while rnd.phase == "deal":
            seat, idx, code = rnd.deal_next()
            room.ids[seat][idx] = code
    room.seats = [srv.Seat(name=f"S{s}", is_bot=s not in humans) for s in range(4)]
    room.events = []
    room.log_event = lambda kind, **data: room.events.append({"e": kind, **data})
    return room


def _events(room, kind):
    return [e for e in room.events if e["e"] == kind]


def _seat_with_options(seed_range=range(400)):
    """A dealt round in which seat 0 can declare a single and seat 1 a pair (so
    seat 1 can still overcall after seat 0's single)."""
    for seed in seed_range:
        room = _room(GateBot(), dealt=True, seed=seed)
        rnd = room.round
        if (any(len(o) == 1 for o in rnd.declare_options(0))
                and any(len(o) == 2 for o in rnd.declare_options(1))):
            return seed
    raise AssertionError("no seed with options at seats 0 and 1")


# ------------------------------------------------------------ (a) flag off

@pytest.mark.parametrize("make", [HeuristicBot, lambda: served(RaisingEvaluator())])
def test_flag_off_takes_the_synchronous_path(make, monkeypatch):
    bot = make()
    assert getattr(bot, "value_declare", False) is False
    room = _room(bot, dealt=False)
    assert srv._declare_offloop(room) is False
    sync_calls = []
    real = srv._bot_declares

    def spy(room_, seats, final=False):
        sync_calls.append((list(seats), final))
        return real(room_, seats, final)

    def forbidden(*args, **kwargs):
        raise AssertionError("the off-loop declare path ran with the flag off")

    monkeypatch.setattr(srv, "_bot_declares", spy)
    monkeypatch.setattr(srv, "_run_deal_offloop", forbidden)
    monkeypatch.setattr(srv, "_declare_step_locked", forbidden)
    monkeypatch.setattr(srv, "_offloop_declare", forbidden)
    monkeypatch.setattr(srv.asyncio, "to_thread", forbidden)
    asyncio.run(srv.run_deal(room))
    # one synchronous call per dealt card, then the final call for all four seats
    assert sync_calls[:100] == [([i % 4], False) for i in range(100)]
    assert sync_calls[100] == ([0, 1, 2, 3], True)
    assert room.round.phase == "bury"
    assert not _events(room, "bot_declare_timing")


# ------------------------------------------------------------ (b) the gate

@pytest.mark.parametrize("seed", range(6))
def test_gate_is_the_gate_decide_declare_applies(seed):
    bot = served(NTEvaluator(), value_declare=True)
    game = Game(random.Random(seed))
    rnd = game.start_round()

    def check(seat, final):
        heuristic, gated = bot.declare_gate(rnd, seat, final)
        assert heuristic == HeuristicBot().decide_declare(rnd, seat, final)
        choice = bot.decide_declare(rnd, seat, final=final)
        assert gated == (bot.last_declare_record is not None)
        if not gated:
            assert choice == heuristic
        if choice:
            rnd.declare(seat, choice)

    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        check(seat, False)
    for seat in range(4):
        check(seat, True)
    off = served(NTEvaluator())
    assert off.declare_gate(rnd, 0, True)[1] is False


# ------------------------------------------------------------ (c) off the loop

def test_gated_call_runs_off_the_loop_while_the_loop_serves(monkeypatch):
    monkeypatch.setattr(srv, "DECLARE_BUDGET_SECONDS", 8.0)
    room = _room(GateBot("wait-for-loop"), dealt=True, seed=_seat_with_options())
    loop_thread = threading.get_ident()

    async def scenario():
        async def ticker():
            for _ in range(5):
                await asyncio.sleep(0.01)
            LOOP_TICKED.set()
        tick = asyncio.create_task(ticker())
        assert await srv._declares_offloop(room, room.round, [0], True)
        await tick

    asyncio.run(scenario())
    assert CALLS and all(c["thread"] != loop_thread for c in CALLS)
    # the copy's own budget is lowered to the server budget; the room bot is untouched
    assert CALLS[0]["budget"] == 8.0 and room.bot.serving_budget_seconds is None
    timing, = _events(room, "bot_declare_timing")
    assert timing["status"] == "complete" and timing["acted"] is True
    assert timing["event_loop_offloaded"] is True and timing["stale_discarded"] is False
    assert timing["decision"] == {"schema": "test-declare-v1", "seat": 0}
    assert room.round.declaration["seat"] == 0
    assert _events(room, "declare")[0]["bot"] is True


# ------------------------------------------------------------ (d) fallbacks

def test_server_budget_expiry_falls_back_to_the_heuristic(monkeypatch):
    monkeypatch.setattr(srv, "DECLARE_BUDGET_SECONDS", 0.05)
    room = _room(GateBot("block"), dealt=True, seed=_seat_with_options())
    rnd = room.round
    heuristic = HeuristicBot().decide_declare(rnd, 0, True)
    started = asyncio.run(_timed(srv._declares_offloop(room, rnd, [0], True)))
    assert started < 2.0          # the wait was abandoned at the budget, not the worker
    timing, = _events(room, "bot_declare_timing")
    record = timing["decision"]
    assert timing["status"] == "fallback" and timing["fallback_reason"] == "server_budget"
    assert record["schema"] == srv.DECLARE_FALLBACK_SCHEMA
    assert record["reason"] == "server_budget" and record["work_complete"] is False
    assert record["played"] == heuristic and record["budget_seconds"] == 0.05
    if heuristic:
        assert rnd.declaration["cards"] == heuristic and timing["acted"] is True
    else:
        assert rnd.declaration is None and timing["acted"] is False


async def _timed(coro):
    t0 = asyncio.get_running_loop().time()
    await coro
    return asyncio.get_running_loop().time() - t0


def test_worker_error_falls_back_and_is_logged(monkeypatch, caplog):
    monkeypatch.setattr(srv, "DECLARE_BUDGET_SECONDS", 5.0)
    room = _room(GateBot("error"), dealt=True, seed=_seat_with_options())
    heuristic = HeuristicBot().decide_declare(room.round, 0, True)
    with caplog.at_level(logging.WARNING):
        asyncio.run(srv._declares_offloop(room, room.round, [0], True))
    timing, = _events(room, "bot_declare_timing")
    record = timing["decision"]
    assert timing["fallback_reason"] == "server-error"
    assert record["error_class"] == "RuntimeError"
    assert record["error_message"] == "value head exploded"
    assert record["played"] == heuristic
    assert "value declare failed" in caplog.text


def test_real_bot_evaluator_error_is_the_bots_own_fallback(monkeypatch):
    """An evaluator error inside `decide_declare` is the bot's OptionalStage
    fallback (record ``fallback_reason='error'``), not a server error."""
    monkeypatch.setattr(srv, "DECLARE_BUDGET_SECONDS", 30.0)
    room = _room(served(RaisingEvaluator(), value_declare=True), dealt=True,
                 seed=_seat_with_options())
    heuristic = HeuristicBot().decide_declare(room.round, 0, True)
    asyncio.run(srv._declares_offloop(room, room.round, [0], True))
    timing, = _events(room, "bot_declare_timing")
    assert timing["status"] == "complete"
    assert timing["decision"]["schema"] == pv.VALUE_DECLARE_RECORD_SCHEMA
    assert timing["decision"]["fallback_reason"] == "error"
    assert timing["decision"]["played"] == (pv.value_declare_model.PASS if heuristic is None
                                            else " ".join(heuristic))


# ------------------------------------------------------------ (e) staleness

@pytest.mark.parametrize("interference", ["human-declares", "seat-claimed"])
def test_a_change_during_evaluation_discards_the_result(monkeypatch, interference):
    monkeypatch.setattr(srv, "DECLARE_BUDGET_SECONDS", 8.0)
    seed = _seat_with_options()
    room = _room(GateBot("block-once"), dealt=True, seed=seed,
                 humans=(0,) if interference == "human-declares" else ())
    rnd = room.round
    human_option = next(o for o in rnd.declare_options(0) if len(o) == 1)

    async def scenario():
        work = asyncio.create_task(srv._declares_offloop(room, rnd, [1], True))
        while not CALLS:
            await asyncio.sleep(0.005)
        async with room.lock:          # the loop is free while the bot evaluates
            if interference == "human-declares":
                rnd.declare(0, human_option)
            else:
                room.seats[1].is_bot = False
        RELEASE.set()
        await work

    asyncio.run(scenario())
    timings = _events(room, "bot_declare_timing")
    assert timings[0]["stale_discarded"] is True and timings[0]["acted"] is False
    if interference == "human-declares":
        # the grace-window pass asks seat 1 again, on the human's declaration
        assert len(timings) == 2 and timings[1]["stale_discarded"] is False
        assert [c["seat"] for c in CALLS] == [1, 1]
        if timings[1]["acted"]:
            assert rnd.declaration["seat"] == 1
        else:
            assert rnd.declaration["seat"] == 0
    else:
        assert len(timings) == 1 and rnd.declaration is None
        assert not _events(room, "declare")


# ------------------------------------------------------------ (f) whole deal

def _declarations(room):
    return [(e["seat"], e["cards"]) for e in _events(room, "declare")]


@pytest.mark.parametrize("seed", [3, 22])
def test_offloop_deal_matches_the_synchronous_deal(monkeypatch, seed):
    """No interference: the off-loop deal declares exactly what the old
    synchronous path declares with the same value-declaring bot."""
    monkeypatch.setattr(srv, "DECLARE_BUDGET_SECONDS", 30.0)
    sync_room = _room(served(NTEvaluator(), value_declare=True), dealt=False, seed=seed)
    monkeypatch.setattr(srv, "_declare_offloop", lambda room: False)
    asyncio.run(srv.run_deal(sync_room))
    monkeypatch.undo()
    monkeypatch.setattr(srv, "DEAL_DELAY", 0.0)
    monkeypatch.setattr(srv, "kick_bots", lambda room: None)
    monkeypatch.setattr(srv, "DECLARE_BUDGET_SECONDS", 30.0)
    off_room = _room(served(NTEvaluator(), value_declare=True), dealt=False, seed=seed)
    assert srv._declare_offloop(off_room) is True
    asyncio.run(srv.run_deal(off_room))
    timings = _events(off_room, "bot_declare_timing")
    assert timings and all(t["status"] == "complete" and not t["stale_discarded"]
                           for t in timings)
    assert _declarations(off_room) == _declarations(sync_room)
    trump_sync, = _events(sync_room, "trump")
    trump_off, = _events(off_room, "trump")
    assert trump_off == trump_sync
    assert off_room.round.phase == sync_room.round.phase == "bury"
    assert off_room.round.hands == sync_room.round.hands


def test_declare_budget_env_is_validated(monkeypatch):
    for bad in ("0", "-1", "inf", "nan", "x"):
        monkeypatch.setenv("SHENGJI_PV_DECLARE_BUDGET_SECONDS", bad)
        with pytest.raises(ValueError, match="SHENGJI_PV_DECLARE_BUDGET_SECONDS"):
            srv._declare_budget_from_env()
    monkeypatch.setenv("SHENGJI_PV_DECLARE_BUDGET_SECONDS", "0.25")
    assert srv._declare_budget_from_env() == 0.25
    monkeypatch.delenv("SHENGJI_PV_DECLARE_BUDGET_SECONDS")
    assert srv._declare_budget_from_env() == 0.5

"""Concurrency, pacing, and stale-commit contracts for production bot turns."""
from __future__ import annotations

import asyncio
import copy
import random
import threading
from types import SimpleNamespace

import pytest

from shengji.api import server as srv
from shengji.ai.heuristic import HeuristicBot
from shengji.ai.registry import make_bot
from shengji.engine.game import Game


def _room() -> SimpleNamespace:
    return SimpleNamespace(
        code="TEST",
        lock=asyncio.Lock(),
        seats=[SimpleNamespace(is_bot=True)],
        round=SimpleNamespace(phase="play"),
        records=[],
        log_event=lambda kind, **data: None,
    )


def _snapshot(seat: int = 0) -> srv._BotTurnSnapshot:
    return srv._BotTurnSnapshot(
        game_token=SimpleNamespace(),
        round_token=SimpleNamespace(),
        round_copy=SimpleNamespace(),
        bot_copy=SimpleNamespace(policy_name="test-policy"),
        seat=seat,
        phase="play",
        mode="bot",
        owner_left_at=None,
    )


def _decision(snapshot: srv._BotTurnSnapshot) -> srv._BotTurnDecision:
    return srv._BotTurnDecision(snapshot=snapshot, cards=["SA"])


class _StatefulBot(HeuristicBot):
    policy_name = "stateful-scheduler-witness"

    def __init__(self):
        self.rng = random.Random(737_019)
        self.play_calls = 0

    def decide_play(self, rnd, seat):
        self.play_calls += 1
        self.rng.random()
        return super().decide_play(rnd, seat)


def _real_room(seed: int = 91) -> srv.Room:
    room = srv.Room(code="REAL")
    room.game = Game(random.Random(seed))
    rnd = room.game.start_round()
    helper = HeuristicBot()
    while rnd.phase != "play":
        if rnd.phase == "deal":
            rnd.deal_next()
        elif rnd.phase == "declare":
            rnd.finalize_declare()
        elif rnd.phase == "bury":
            rnd.bury(rnd.banker, helper.decide_bury(rnd, rnd.banker))
    room.seats = [srv.Seat(name=f"Bot {seat}", is_bot=True)
                  for seat in range(4)]
    room.bot = _StatefulBot()
    room.ids = [{index * 4 + seat: card
                 for index, card in enumerate(rnd.hands[seat])}
                for seat in range(4)]
    room._kitty_given = True
    room.log_event = lambda kind, **data: None
    return room


def _prepare_real(room: srv.Room, *, mode: str = "bot") \
        -> srv._PreparedBotTurn:
    seat = room.round.turn
    snapshot = srv._snapshot_bot_turn(room, seat, mode)
    assert snapshot is not None
    decision = srv._compute_bot_turn(snapshot)
    return srv._PreparedBotTurn(
        decision=decision,
        compute_seconds=0.1,
        pacing_seconds=0.6,
        turn_seconds=0.7,
    )


@pytest.mark.parametrize(
    ("policy_name", "bot_seed"),
    (("mc", 1), ("mc-s0-report-lcb", 3)),
)
def test_speculative_decision_matches_direct_path(policy_name, bot_seed):
    """Snapshot isolation must not change the policy's chosen action.

    Both named seeds are mutation witnesses: advancing only the snapshot RNG by
    one draw changes the selected play.  The test therefore fails if snapshot,
    compute, or future isolation code silently perturbs production RNG state.
    """
    room = _real_room()
    room.bot = make_bot(policy_name, seed=bot_seed)
    seat = room.round.turn
    direct_bot = copy.deepcopy(room.bot)
    direct_cards = list(
        direct_bot.decide_play(copy.deepcopy(room.round), seat))

    snapshot = srv._snapshot_bot_turn(room, seat, "bot")
    assert snapshot is not None
    speculative_cards = srv._compute_bot_turn(snapshot).cards

    assert speculative_cards == direct_cards

    perturbed = srv._snapshot_bot_turn(room, seat, "bot")
    assert perturbed is not None
    perturbed.bot_copy.rng.random()
    assert srv._compute_bot_turn(perturbed).cards != direct_cards


def test_bot_search_is_offloaded_and_event_loop_runs(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def blocking_search(snapshot):
        started.set()
        assert release.wait(timeout=2)
        return _decision(snapshot)

    monkeypatch.setattr(srv, "_compute_bot_turn", blocking_search)

    async def scenario():
        task = asyncio.create_task(
            srv._compute_bot_turn_off_loop(_snapshot()))
        while not started.is_set():
            await asyncio.sleep(0)

        # This coroutine running while the worker is blocked is the invariant;
        # no host-speed wall-clock threshold is involved.
        event_loop_progressed = False

        async def probe():
            nonlocal event_loop_progressed
            event_loop_progressed = True

        await probe()
        assert event_loop_progressed
        assert not task.done()
        release.set()
        assert (await task).cards == ["SA"]

    asyncio.run(scenario())


def test_cancelled_search_waits_for_bounded_worker(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def blocking_search(snapshot):
        started.set()
        assert release.wait(timeout=2)
        return _decision(snapshot)

    monkeypatch.setattr(srv, "_compute_bot_turn", blocking_search)

    async def scenario():
        task = asyncio.create_task(
            srv._compute_bot_turn_off_loop(_snapshot()))
        while not started.is_set():
            await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done(), "cancellation orphaned a CPU search"
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_compute_and_pacing_overlap_by_accounting(monkeypatch):
    clock = {"value": 100.0}
    slept = []
    snapshot = _snapshot()

    async def compute(_snapshot_):
        assert _snapshot_ is snapshot
        clock["value"] += 0.08
        return _decision(snapshot)

    async def sleep(seconds):
        slept.append(seconds)
        clock["value"] += seconds

    monkeypatch.setattr(srv, "_snapshot_bot_turn", lambda *_args: snapshot)
    monkeypatch.setattr(srv, "_compute_bot_turn_off_loop", compute)
    monkeypatch.setattr(srv.time, "perf_counter", lambda: clock["value"])
    monkeypatch.setattr(srv.asyncio, "sleep", sleep)

    prepared = asyncio.run(srv._paced_bot_step(
        _room(), 0, turn_started=100.0, minimum_turn_seconds=0.12))

    assert prepared is not None
    assert prepared.compute_seconds == pytest.approx(0.08)
    assert prepared.pacing_seconds == pytest.approx(0.04)
    assert prepared.turn_seconds == pytest.approx(0.12)
    assert slept == pytest.approx([0.04])


def test_slow_compute_adds_no_unconditional_delay(monkeypatch):
    clock = {"value": 200.0}
    slept = []
    snapshot = _snapshot()

    async def compute(_snapshot_):
        clock["value"] += 0.08
        return _decision(_snapshot_)

    async def sleep(seconds):
        slept.append(seconds)
        clock["value"] += seconds

    monkeypatch.setattr(srv, "_snapshot_bot_turn", lambda *_args: snapshot)
    monkeypatch.setattr(srv, "_compute_bot_turn_off_loop", compute)
    monkeypatch.setattr(srv.time, "perf_counter", lambda: clock["value"])
    monkeypatch.setattr(srv.asyncio, "sleep", sleep)

    prepared = asyncio.run(srv._paced_bot_step(
        _room(), 0, turn_started=200.0, minimum_turn_seconds=0.04))

    assert prepared is not None
    assert prepared.compute_seconds == pytest.approx(0.08)
    assert prepared.pacing_seconds == 0.0
    assert prepared.turn_seconds == pytest.approx(0.08)
    assert slept == []


def test_two_rooms_search_concurrently_without_timing_threshold(monkeypatch):
    both_workers = threading.Barrier(2)

    def rendezvous(snapshot):
        both_workers.wait(timeout=2)
        return _decision(snapshot)

    monkeypatch.setattr(srv, "_compute_bot_turn", rendezvous)

    async def scenario():
        return await asyncio.gather(
            srv._compute_bot_turn_off_loop(_snapshot(0)),
            srv._compute_bot_turn_off_loop(_snapshot(1)),
        )

    results = asyncio.run(scenario())
    assert [result.snapshot.seat for result in results] == [0, 1]


def test_timing_record_names_isolation_and_stale_discard():
    room = _room()
    records = []
    room.log_event = lambda kind, **data: records.append((kind, data))
    prepared = srv._PreparedBotTurn(
        decision=_decision(_snapshot()),
        compute_seconds=0.2,
        pacing_seconds=0.5,
        turn_seconds=0.7,
    )

    srv._log_bot_timing(room, prepared, acted=False)

    kind, record = records[-1]
    assert kind == "bot_timing"
    assert record["event_loop_offloaded"] is True
    assert record["snapshot_isolated"] is True
    assert record["acted"] is False
    assert record["stale_discarded"] is True


def test_unchanged_snapshot_commits_cloned_bot_and_action():
    room = _real_room()
    live_bot = room.bot
    live_rng = live_bot.rng.getstate()
    seat = room.round.turn
    before = len(room.round.hands[seat])
    prepared = _prepare_real(room)

    assert live_bot.play_calls == 0
    assert live_bot.rng.getstate() == live_rng
    assert srv._commit_bot_turn(room, prepared) is True
    assert room.bot is prepared.decision.snapshot.bot_copy
    assert room.bot is not live_bot
    assert room.bot.play_calls == 1
    assert len(room.round.hands[seat]) < before


def test_claimed_bot_seat_discards_action_rng_and_counters():
    room = _real_room()
    seat = room.round.turn
    live_bot = room.bot
    live_rng = live_bot.rng.getstate()
    hand = list(room.round.hands[seat])
    prepared = _prepare_real(room)

    room.seats[seat].is_bot = False
    room.seats[seat].connected = True

    assert srv._commit_bot_turn(room, prepared) is False
    assert room.bot is live_bot
    assert live_bot.play_calls == 0
    assert live_bot.rng.getstate() == live_rng
    assert room.round.turn == seat
    assert room.round.hands[seat] == hand


def test_reconnected_takeover_discards_speculative_action(monkeypatch):
    room = _real_room()
    seat = room.round.turn
    owner = room.seats[seat]
    owner.is_bot = False
    owner.connected = False
    owner.left_at = 100.0
    monkeypatch.setattr(srv, "now", lambda: 200.0)
    prepared = _prepare_real(room, mode="takeover")
    live_bot = room.bot
    hand = list(room.round.hands[seat])

    owner.connected = True
    owner.left_at = None

    assert srv._commit_bot_turn(room, prepared) is False
    assert room.bot is live_bot
    assert room.round.turn == seat
    assert room.round.hands[seat] == hand


@pytest.mark.parametrize("stale_change", ["turn", "round"])
def test_changed_turn_or_round_discards_snapshot(stale_change):
    room = _real_room()
    prepared = _prepare_real(room)
    live_bot = room.bot
    original_round = room.round

    if stale_change == "turn":
        room.round.turn = (room.round.turn + 1) % 4
    else:
        room.game.start_round()

    assert srv._commit_bot_turn(room, prepared) is False
    assert room.bot is live_bot
    if stale_change == "round":
        assert room.round is not original_round

"""Websocket-level tests for the multiplayer room protocol.

These drive the REAL socket via TestClient rather than calling handlers
directly: `peek_room` shipped completely unimplemented on the server while
the client sent it and the suite stayed green, because nothing here spoke
the wire protocol (2026-08-03).
"""
from __future__ import annotations

import os
import random
import threading
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("SHENGJI_BOT", "heuristic")  # fast; these tests are protocol-level


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_LOG_DIR", str(tmp_path / "logs"))
    from shengji.api import server as srv

    srv.LOG_DIR = tmp_path / "logs"
    # A real deal is ~22s of DEAL_DELAY; these tests care about the protocol,
    # not the pacing. BOT_DELAY is left alone — one test needs a bot turn to
    # still be PENDING when a human claims that seat.
    monkeypatch.setattr(srv, "DEAL_DELAY", 0.0)
    monkeypatch.setattr(srv, "DECLARE_GRACE", 0.05)
    monkeypatch.setattr(srv, "DECLARE_EXTEND", 0.05)
    srv.rooms.clear()
    # ONE event loop for the whole test: a bare TestClient gives each
    # websocket_connect its own portal, and a Room's asyncio.Lock binds to
    # whichever loop touches it first — so multi-socket tests died with
    # "bound to a different event loop".
    #
    # The reason the context manager was avoided is that its shutdown waits on
    # the per-room watchdog, which loops forever, hanging the suite. So the
    # watchdog is stubbed out here instead: every test that needs takeover
    # drives `watchdog_tick` directly with the injected clock, which is more
    # deterministic than waiting on a 5-second poll anyway.
    async def _no_watchdog(room):
        return

    monkeypatch.setattr(srv, "watchdog", _no_watchdog)
    monkeypatch.setattr(srv, "ROOM_TTL", 0.2)   # don't sleep 5 min on teardown

    with TestClient(srv.app) as c:
        yield c
        for room in list(srv.rooms.values()):
            for task in (room.cleanup_task, room.deal_task,
                         room.watchdog_task, room.bot_task):
                if task is not None:
                    task.cancel()
        srv.rooms.clear()
    srv.rooms.clear()


_READER = None  # lazily-built reader pool; a thread blocked on a dead socket
                # is abandoned rather than joined (joining it re-created the
                # hang the bounded read was meant to prevent)


def _drain(ws, want, tries=40, timeout=5.0):
    """Next message of type `want` (states/chat interleave freely).

    Each read is bounded: a bare receive_json() blocks forever when the server
    sends fewer messages than expected, which turned four behaviour changes
    into a HUNG suite instead of four failures (2026-08-04). A test that
    cannot fail fast is a test that hides its own breakage.
    """
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as _TO

    global _READER
    if _READER is None:
        _READER = ThreadPoolExecutor(max_workers=32,
                                     thread_name_prefix="ws-drain")
    seen = []
    for _ in range(tries):
        fut = _READER.submit(ws.receive_json)
        try:
            m = fut.result(timeout=timeout)
        except _TO:
            # Do NOT wait for the blocked reader: joining it is what turned a
            # bounded read back into a hang.
            raise AssertionError(
                f"no {want!r} within {timeout}s; saw {seen}; "
                f"server: {_server_snapshot()}") from None
        seen.append(m.get("type"))
        if m.get("type") == want:
            return m
    raise AssertionError(f"no {want!r} in {tries} messages; saw {seen}; "
                         f"server: {_server_snapshot()}")


def _task_state(task, recorded):
    """One word per task, so the timeout message reads at a glance."""
    if task is None:
        return "never"
    if not task.done():
        return "running"
    return recorded or ("cancelled" if task.cancelled() else "done-unrecorded")


def _server_snapshot():
    """Server-side state at the moment a read times out (#628): which room
    task or writer stopped producing frames, and how it ended. A timeout with
    every task running and every writer alive is a different bug from one
    whose deal task died on an exception, and the message must say which."""
    from shengji.api import server as srv

    rooms = []
    for code, room in list(srv.rooms.items()):
        rnd = room.round
        seats = []
        for seat in room.seats:
            seats.append(
                f"{seat.name}:{'bot' if seat.is_bot else 'human'}"
                f"{'/connected' if seat.connected else ''}"
                f"/writer={_task_state(seat.writer, seat.writer_exit)}"
                f"{'/' + seat.writer_error if seat.writer_error else ''}"
                f"/queued={seat.queue.qsize() if seat.queue is not None else '-'}")
        rooms.append(
            f"{code}: phase={getattr(rnd, 'phase', None)} "
            f"deal_task={_task_state(room.deal_task, room.task_exits.get('deal_task'))} "
            f"bot_task={_task_state(room.bot_task, room.task_exits.get('bot_task'))} "
            f"seats=[{', '.join(seats)}]")
    return "; ".join(rooms) or "no rooms"


def _room_with_bots(ws, name="jerry"):
    # Lobby broadcasts are "room"; only an in-game room sends "state".
    ws.send_json({"type": "create_room", "name": name})
    code = _drain(ws, "room")["room"]
    for _ in range(3):
        ws.send_json({"type": "add_bot"})
    return code


def test_peek_room_reports_seats_without_joining(client):
    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "peek_room", "room": code})
            m = _drain(b, "room_seats")

    assert m["room"] == code
    assert len(m["seats"]) == 4
    assert [s["team"] for s in m["seats"]] == [0, 1, 0, 1]
    assert m["seats"][0]["name"] == "jerry" and not m["seats"][0]["is_bot"]
    assert all(s["is_bot"] for s in m["seats"][1:])
    # Peeking must NOT seat the peeker.
    from shengji.api import server as srv
    assert len(srv.rooms[code].seats) == 4


def test_peek_unknown_room_errors(client):
    with client.websocket_connect("/ws") as a:
        a.send_json({"type": "peek_room", "room": "ZZZZ"})
        m = _drain(a, "error")
    assert m["code"] == "room_not_found"


def test_peek_then_join_chosen_seat(client):
    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "peek_room", "room": code})
            seats = _drain(b, "room_seats")["seats"]
            want = [s["seat"] for s in seats if s["is_bot"]][-1]
            b.send_json({"type": "join_room", "room": code,
                         "name": "james", "seat": want})
            st = _drain(b, "room")
            assert st["you"] == want
            mine = next(p for p in st["players"] if p["seat"] == want)
            assert mine["name"] == "james" and not mine["is_bot"]


def test_ready_ignores_disconnected_humans(client):
    """A player who drops at round end must stop being waited on."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "join_room", "room": code, "name": "james"})
            _drain(b, "room")
            room = srv.rooms[code]
            humans = [i for i, s in enumerate(room.seats) if not s.is_bot]
            assert len(humans) == 2
            room.ready.add(humans[0])
            assert srv.pending_ready(room) == {humans[1]}
            # Exercise _detach's explicit quorum cleanup, not merely the fact
            # that pending_ready ignores disconnected seats.
            room.ready.add(humans[1])
        # b's socket is closed here; the drop must clear it from the tally.
        room = srv.rooms[code]
        assert srv.pending_ready(room) == set()
        assert humans[1] not in room.ready


def test_state_carries_ready_tally(client):
    """In-game broadcasts must include `ready` — the client renders it."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        a.send_json({"type": "start_game"})
        st = _drain(a, "state", tries=60)
        assert "ready" in st, "round-end tally missing from in-game state"
        srv.rooms[code].ready.add(0)
        assert "ready" in srv.state_for(srv.rooms[code], 0)
        assert srv.state_for(srv.rooms[code], 0)["ready"] == [0]


def test_seat_claim_chat_names_the_bot(client):
    """"took Bot 1's seat" — which seat, not just "a bot's seat"."""
    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "peek_room", "room": code})
            seats = _drain(b, "room_seats")["seats"]
            want = [s["seat"] for s in seats if s["is_bot"]][-1]
            botname = next(s["name"] for s in seats if s["seat"] == want)
            b.send_json({"type": "join_room", "room": code,
                         "name": "jerry mbp", "seat": want})
            line = _drain(b, "chat")
    assert line["text"] == f"jerry mbp took {botname}'s seat"
    assert line["seat"] == -1


def test_chat_snapshot_rolls_over_after_more_than_fifty_messages(client):
    """A late/rejoining socket gets one bounded, contiguous snapshot.

    This crosses the real wire and the queue used by production.  A unit test
    of ``room.chat[-50:]`` would miss an attach path that sent stale history,
    duplicated the live boundary, or blocked after enough fan-out messages.
    """
    with client.websocket_connect("/ws") as host:
        host.send_json({"type": "create_room", "name": "host"})
        code = _drain(host, "room")["room"]
        for i in range(60):
            host.send_json({"type": "chat", "text": f"line-{i:02d}"})

        with client.websocket_connect("/ws") as late:
            late.send_json({"type": "join_room", "room": code,
                            "name": "late"})
            history = _drain(late, "chat_history")

    assert history["through_id"] == 60
    assert len(history["messages"]) == 50
    assert [m["id"] for m in history["messages"]] == list(range(11, 61))
    assert history["messages"][0]["text"] == "line-10"
    assert history["messages"][-1]["text"] == "line-59"


def test_two_clients_race_for_same_bot_seat(client):
    """The loser of a seat race must be refused, never silently reseated."""
    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        with client.websocket_connect("/ws") as b, \
                client.websocket_connect("/ws") as c:
            b.send_json({"type": "peek_room", "room": code})
            want = [s["seat"] for s in _drain(b, "room_seats")["seats"]
                    if s["is_bot"]][0]
            b.send_json({"type": "join_room", "room": code,
                         "name": "first", "seat": want})
            assert _drain(b, "room")["you"] == want
            c.send_json({"type": "join_room", "room": code,
                         "name": "second", "seat": want})
            err = _drain(c, "error")
    assert err["code"] == "seat_unavailable"
    from shengji.api import server as srv
    assert srv.rooms[code].seats[want].name == "first"
    assert not any(sd.name == "second" for sd in srv.rooms[code].seats)


def test_malformed_seat_falls_back_to_any_bot(client):
    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "join_room", "room": code,
                         "name": "odd", "seat": True})   # bool is not a seat
            st = _drain(b, "room")
    assert st["you"] in (1, 2, 3)


def _start_game(client, a, to_play=False):
    """Room with 3 bots, game running, returns (code, room).

    With to_play=True this drives the REAL deal path (the fixture zeroes
    DEAL_DELAY and shortens the declare window) rather than advancing the
    round in-process — an in-process loop races the server's own deal task
    and both end up calling deal_next on the same round.
    """
    from shengji.api import server as srv

    code = _room_with_bots(a)
    a.send_json({"type": "start_game"})
    st = _drain(a, "state", tries=60)
    if to_play:
        from shengji.engine.round import KITTY_SIZE
        bury_sent = False
        for _ in range(400):
            if st.get("phase") == "play":
                break
            if (st.get("phase") == "bury" and st.get("banker") == st.get("you")
                    and not bury_sent):
                # No declaration can leave the human at seat 0 as banker.
                # Drive that required action through the real socket too.
                ids = [card["id"] for card in st["hand"][:KITTY_SIZE]]
                assert len(ids) == KITTY_SIZE
                a.send_json({"type": "bury", "card_ids": ids})
                bury_sent = True
            st = _drain(a, "state", tries=400)
        assert st.get("phase") == "play", "round never reached the play phase"
    return code, srv.rooms[code]


def test_start_game_to_play_completes_human_banker_bury(client, monkeypatch):
    from shengji.ai.heuristic import HeuristicBot
    from shengji.engine.round import KITTY_SIZE

    # With no declarations the first round defaults to seat 0, the human.
    monkeypatch.setattr(HeuristicBot, "decide_declare", lambda *a, **kw: None)
    with client.websocket_connect("/ws") as a:
        _, room = _start_game(client, a, to_play=True)
        assert room.round.banker == 0
        assert room.round.phase == "play"
        assert len(room.round.buried) == KITTY_SIZE
        assert len(room.round.hands[0]) == 25


def test_claim_preserves_private_hand_and_ids(client):
    """The claimant gets that seat's REAL remaining cards; others see counts."""
    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a, to_play=True)
        want = next(i for i, sd in enumerate(room.seats) if sd.is_bot)
        before = sorted(room.round.hands[want])
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "join_room", "room": code,
                         "name": "late", "seat": want})
            st = _drain(b, "state", tries=60)
            assert st["you"] == want
            got = sorted(c["code"] for c in st["hand"])
            assert got == before, "claimant did not receive the seat's hand"
            assert len({c["id"] for c in st["hand"]}) == len(st["hand"]), \
                "duplicate card ids handed to the claimant"
            # Everyone else still sees only public counts for that seat.
            other = next(p for p in st["players"] if p["seat"] != want)
            assert "hand" not in other and "cards_left" in other
        # And the seat's hand was not mutated by the claim itself.
        assert sorted(room.round.hands[want]) == before


def test_claim_during_bot_delay_is_atomic(client, monkeypatch):
    """Claiming the seat whose bot turn is pending must cancel that bot move."""
    import asyncio

    from shengji.ai.heuristic import HeuristicBot
    from shengji.api import server as srv

    # No declaration deterministically makes the human seat 0 the banker.
    # Advance its lead over the socket; never substitute an off-turn bot.
    monkeypatch.setattr(HeuristicBot, "decide_declare",
                        lambda self, rnd, seat, final=False: None)
    monkeypatch.setattr(srv, "BOT_DELAY", 60.0)
    pending = threading.Event()
    release = threading.Event()
    committed = threading.Event()
    records = []
    real_sleep = asyncio.sleep

    async def controlled_sleep(delay, *args, **kwargs):
        # Only the deliberately long bot pacing sleep, not deal/cleanup.
        if delay > 30:
            pending.set()
            assert await asyncio.to_thread(release.wait, 10), "pacing never released"
        else:
            await real_sleep(delay, *args, **kwargs)

    monkeypatch.setattr(asyncio, "sleep", controlled_sleep)
    try:
        with client.websocket_connect("/ws") as a:
            code, room = _start_game(client, a, to_play=True)
            assert room.round.turn == 0 and not room.seats[0].is_bot
            original_log = room.log_event

            def capture_log(kind, **data):
                original_log(kind, **data)
                if kind == "bot_timing" and data.get("phase") == "play":
                    records.append(data)
                    committed.set()

            room.log_event = capture_log
            card = next(iter(room.ids[0]))
            a.send_json({"type": "play", "card_ids": [card]})
            assert pending.wait(timeout=5), "on-turn bot never reached pacing"
            turn = room.round.turn
            assert turn is not None and room.seats[turn].is_bot
            hand_before = list(room.round.hands[turn])
            with client.websocket_connect("/ws") as b:
                b.send_json({"type": "join_room", "room": code,
                             "name": "sniper", "seat": turn})
                state = _drain(b, "state", tries=60)
                assert state["you"] == turn and not release.is_set()
                assert not room.seats[turn].is_bot
                release.set()
                assert committed.wait(timeout=5), "pending move never reached commit guard"
                assert records[-1]["stale_discarded"] is True
                assert records[-1]["acted"] is False
                assert room.round.turn == turn, "bot moved for a claimed seat"
                assert list(room.round.hands[turn]) == hand_before
    finally:
        release.set()


def test_claim_during_blocked_search_is_prompt_and_discards_snapshot(
        client, monkeypatch):
    """A real socket claim wins while an on-turn bot search is still blocked.

    This is intentionally stronger than ``test_claim_during_bot_delay...``:
    the worker has already started and cannot finish until after the claimant
    receives its private state.  The stale result must discard both the move
    and the speculative bot's RNG/counter advance.
    """
    from shengji.ai.heuristic import HeuristicBot
    from shengji.api import server as srv

    started = threading.Event()
    release = threading.Event()
    timing_logged = threading.Event()
    blocked = {}
    timing_records = []
    real_compute = srv._compute_bot_turn

    class StatefulBot(HeuristicBot):
        policy_name = "stateful-claim-witness"

        def __init__(self):
            self.rng = random.Random(918_273)
            self.play_calls = 0

        def decide_declare(self, rnd, seat, final=False):
            # Force the first-round banker to be a bot, so the first playable
            # turn reaches the blocking worker without a human setup action.
            options = rnd.declare_options(seat)
            return list(options[-1]) if options else None

        def decide_play(self, rnd, seat):
            self.play_calls += 1
            self.rng.random()
            return super().decide_play(rnd, seat)

    def blocking_compute(snapshot):
        if snapshot.phase == "play" and not started.is_set():
            blocked["seat"] = snapshot.seat
            started.set()
            assert release.wait(timeout=10), "test never released bot search"
        return real_compute(snapshot)

    monkeypatch.setattr(srv, "_compute_bot_turn", blocking_compute)

    with client.websocket_connect("/ws") as host:
        code = _room_with_bots(host)
        room = srv.rooms[code]
        room.bot = StatefulBot()
        original_log = room.log_event

        def capture_log(kind, **data):
            original_log(kind, **data)
            if kind == "bot_timing" and data.get("phase") == "play":
                timing_records.append(data)
                timing_logged.set()

        room.log_event = capture_log
        host.send_json({"type": "start_game"})
        state = _drain(host, "state", tries=500)
        while state.get("phase") != "play":
            state = _drain(host, "state", tries=500)
        assert started.wait(timeout=5), "on-turn bot search never started"
        seat = blocked["seat"]
        assert room.round.turn == seat and room.seats[seat].is_bot
        live_bot = room.bot
        live_rng = live_bot.rng.getstate()
        hand_before = list(room.round.hands[seat])

        try:
            with client.websocket_connect("/ws") as claimant:
                claimant.send_json({"type": "join_room", "room": code,
                                    "name": "claimant", "seat": seat})
                claimed = _drain(claimant, "state", tries=60)
                # Receiving this before releasing the worker proves that the
                # search neither holds the room lock nor starves WebSockets.
                assert not release.is_set()
                assert claimed["you"] == seat
                assert not room.seats[seat].is_bot
                assert room.round.turn == seat
                assert list(room.round.hands[seat]) == hand_before

                release.set()
                assert timing_logged.wait(timeout=5), \
                    "stale search never reached its guarded commit"
                assert timing_records[-1]["stale_discarded"] is True
                assert timing_records[-1]["acted"] is False
                assert room.round.turn == seat
                assert list(room.round.hands[seat]) == hand_before
                assert room.bot is live_bot
                assert live_bot.play_calls == 0
                assert live_bot.rng.getstate() == live_rng
        finally:
            release.set()


def test_disconnect_takeover_and_reconnect_resets_each_absence(client):
    """bot_announced must reset per absence, not latch after the first."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a)
        seat0 = room.seats[0]
        for absence in (1, 2):
            seat0.connected = False
            seat0.bot_announced = True          # as the watchdog would set it
            with client.websocket_connect("/ws") as b:
                b.send_json({"type": "join_room", "room": code, "name": "jerry"})
                _drain(b, "state", tries=60)
                me = srv.rooms[code].seats[0]
                assert me is seat0, "reconnect must reuse the SAME Seat object"
                assert not me.is_bot and me.connected
                assert not me.bot_announced, \
                    f"bot_announced still set after absence {absence}"
                assert me.name == "jerry"
        # Reclaiming must not have spawned extra seats.
        assert len(srv.rooms[code].seats) == 4


def test_reconnect_cancels_room_cleanup(client):
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, _ = _start_game(client, a)
    room = srv.rooms.get(code)
    assert room is not None, "room deleted immediately instead of after TTL"
    assert room.cleanup_task is not None
    with client.websocket_connect("/ws") as b:
        b.send_json({"type": "join_room", "room": code, "name": "jerry"})
        _drain(b, "state", tries=60)
        assert room.cleanup_task is None or room.cleanup_task.cancelled()


def test_claim_state_does_not_leak_across_rooms_on_one_socket(client):
    """Claiming a bot seat in room A must not label a later join of room B."""
    with client.websocket_connect("/ws") as a, \
            client.websocket_connect("/ws") as host_b:
        code_a, room_a = _start_game(client, a)
        # Room B has SPACE (one bot, two free seats), so a join there is an
        # ordinary lobby join — any "took ...'s seat" line is leaked state.
        host_b.send_json({"type": "create_room", "name": "hostb"})
        code_b = _drain(host_b, "room")["room"]
        host_b.send_json({"type": "add_bot"})
        with client.websocket_connect("/ws") as mover:
            want = next(i for i, sd in enumerate(room_a.seats) if sd.is_bot)
            mover.send_json({"type": "join_room", "room": code_a,
                             "name": "wanderer", "seat": want})
            first = _drain(mover, "chat")
            assert "took" in first["text"]
            mover.send_json({"type": "leave_room"})
            mover.send_json({"type": "join_room", "room": code_b,
                             "name": "wanderer"})
            lines = []
            for _ in range(30):
                m = mover.receive_json()
                if m.get("type") == "chat":
                    lines.append(m["text"])
                if m.get("type") in ("room", "state") and lines:
                    break
    joined = [t for t in lines if "wanderer" in t]
    assert joined and all("took" not in t for t in joined), \
        f"stale claim state leaked into the next room: {joined}"


def test_state_reports_takeover_countdown(client):
    """A disconnected human's seat carries seconds-until-bot; others None."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a, to_play=True)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "join_room", "room": code, "name": "james"})
            _drain(b, "state", tries=60)
            seat_b = next(i for i, sd in enumerate(room.seats)
                          if sd.name == "james")
        # b's socket closed: the watchdog has not fired yet, so a countdown
        # must be visible to everyone still at the table.
        st = srv.state_for(room, 0)
        me = next(p for p in st["players"] if p["seat"] == seat_b)
        assert me["takeover_in"] is not None
        assert 0 < me["takeover_in"] <= srv.TAKEOVER_AFTER
        assert all(p["takeover_in"] is None
                   for p in st["players"] if p["seat"] != seat_b)
        # Once the bot has taken over, the countdown stops being reported.
        room.seats[seat_b].bot_announced = True
        st2 = srv.state_for(room, 0)
        assert next(p for p in st2["players"]
                    if p["seat"] == seat_b)["takeover_in"] is None


def _four_humans(client, a, sockets: ExitStack):
    """Room of 4 HUMANS mid-game — no bot seat anywhere."""
    from shengji.api import server as srv

    a.send_json({"type": "create_room", "name": "jerry"})
    code = _drain(a, "room")["room"]
    peers, peer_stacks = [], []
    for n in ("amy", "bo", "cy"):
        peer_stack = ExitStack()
        sockets.callback(peer_stack.close)
        w = peer_stack.enter_context(client.websocket_connect("/ws"))
        w.send_json({"type": "join_room", "room": code, "name": n})
        _drain(w, "room")
        peers.append(w)
        peer_stacks.append(peer_stack)
    a.send_json({"type": "start_game"})
    _drain(a, "state", tries=60)
    return code, srv.rooms[code], peers, peer_stacks


def test_dropped_seat_is_reserved_during_grace_then_claimable(client, clock):
    """A blip must not cost you your seat; a real departure must not lock it.

    Both halves matter: the seat was previously claimable the INSTANT someone
    dropped (so a momentary disconnect could lose it), and before that it was
    never claimable at all (so a four-human game with one player gone was
    unjoinable). One window, TAKEOVER_AFTER long, settles both.
    """
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        with ExitStack() as sockets:
            code, room, socks, peer_stacks = _four_humans(
                client, a, sockets)
            peer_stacks[0].close()                     # amy drops

            # --- inside the grace window: reserved for amy ---
            with client.websocket_connect("/ws") as p:
                p.send_json({"type": "peek_room", "room": code})
                seats = _drain(p, "room_seats")["seats"]
            assert not seats[1]["claimable"], \
                "seat claimable during its grace window"
            assert seats[1]["reserved_secs"] is not None
            with client.websocket_connect("/ws") as q:
                q.send_json({"type": "join_room", "room": code,
                             "name": "vulture"})
                assert _drain(q, "error")["code"] == "seat_reserved"
            # amy herself can still return.
            with client.websocket_connect("/ws") as amy:
                amy.send_json({"type": "join_room", "room": code,
                               "name": "amy"})
                assert _drain(amy, "state", tries=60)["you"] == 1

            # --- after it expires: anyone may take over ---
            clock["v"] += srv.TAKEOVER_AFTER + 1
            with client.websocket_connect("/ws") as p2:
                p2.send_json({"type": "peek_room", "room": code})
                seats2 = _drain(p2, "room_seats")["seats"]
            assert seats2[1]["claimable"], \
                "seat still locked after the grace window"
            with client.websocket_connect("/ws") as r:
                r.send_json({"type": "join_room", "room": code,
                             "name": "newbie", "seat": 1})
                st = _drain(r, "state", tries=60)
                assert st["you"] == 1 and len(st["hand"]) > 0


def test_reclaim_is_case_and_space_insensitive(client):
    """Coming back as 'Amy ' must reclaim the seat left by 'amy'."""
    with client.websocket_connect("/ws") as a:
        with ExitStack() as sockets:
            code, room, socks, peer_stacks = _four_humans(
                client, a, sockets)
            peer_stacks[0].close()
            with client.websocket_connect("/ws") as back:
                back.send_json({"type": "join_room", "room": code,
                                "name": " Amy "})
                st = _drain(back, "state", tries=60)
                assert st["you"] == 1, "did not reclaim the original seat"
                assert room.seats[1].connected


def test_takeover_of_dropped_human_is_announced_as_such(client, clock):
    with client.websocket_connect("/ws") as a:
        with ExitStack() as sockets:
            code, room, socks, peer_stacks = _four_humans(
                client, a, sockets)
            peer_stacks[0].close()
            from shengji.api import server as srv
            clock["v"] += srv.TAKEOVER_AFTER + 1      # past the reservation
            with client.websocket_connect("/ws") as r:
                r.send_json({"type": "join_room", "room": code,
                             "name": "newbie", "seat": 1})
                line = _drain(r, "chat")
            assert "took over for amy" in line["text"], line


# ---------------------------------------------------------------- ship gate
def test_stale_socket_cannot_detach_a_newer_connection(client):
    """P0-1: an old socket's teardown must only detach the generation it owns.

    A dropped TCP connection's `finally` can run long after a newer socket has
    resumed the seat. Without generation scoping it detaches the LIVE
    connection and strands the player.
    """
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a, to_play=True)
        seat0 = room.seats[0]
        old_gen = seat0.gen
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "join_room", "room": code,
                         "name": "jerry", "token": seat0.token})
            _drain(b, "state", tries=60)
            assert seat0.gen > old_gen, "attach did not bump the generation"
            assert seat0.connected
            # The stale socket's teardown arrives late, for the OLD generation.
            srv._detach(seat0, room, old_gen)
            assert seat0.connected, "stale teardown detached the live socket"
            # The generation it does own still detaches normally.
            srv._detach(seat0, room, seat0.gen)
            assert not seat0.connected


def test_resume_token_resumes_the_exact_seat(client):
    """The token is identity: it resumes that seat regardless of the name."""
    with client.websocket_connect("/ws") as a:
        with ExitStack() as sockets:
            code, room, socks, peer_stacks = _four_humans(
                client, a, sockets)
            tok = room.seats[1].token          # amy's seat
            peer_stacks[0].close()
            with client.websocket_connect("/ws") as real:
                real.send_json({"type": "join_room", "room": code,
                                "name": "totally-different-name",
                                "token": tok})
                st = _drain(real, "state", tries=60)
                assert st["you"] == 1


def test_name_reentry_is_allowed_but_does_not_inherit_the_token(client):
    """The house trust model, asserted honestly rather than wished away.

    Typing a dropped player's name DOES re-enter their seat — the same
    permission the seat picker already grants deliberately, so the name path
    is not a privilege escalation. What it must NOT do is hand over that
    seat's existing token, or an impersonator could later displace the real
    owner. An earlier version of this test claimed the opposite of what it
    asserted (Codex, 2026-08-04).
    """
    with client.websocket_connect("/ws") as a:
        with ExitStack() as sockets:
            code, room, socks, peer_stacks = _four_humans(
                client, a, sockets)
            original = room.seats[1].token
            peer_stacks[0].close()
            with client.websocket_connect("/ws") as other:
                other.send_json({"type": "join_room", "room": code,
                                 "name": "AMY ", "token": "not-the-token"})
                st = _drain(other, "state", tries=60)
                assert st["you"] == 1, \
                    "name re-entry should reach the dropped seat"
                assert room.seats[1].token != original, \
                    "name re-entry inherited the original owner's token"


def test_state_exposes_controller_not_inference(client):
    """P0-2: permanent bot, bot covering a human, and human are distinct."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a, to_play=True)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "join_room", "room": code, "name": "james"})
            _drain(b, "state", tries=60)
            seat_b = next(i for i, sd in enumerate(room.seats)
                          if sd.name == "james")
        st = srv.state_for(room, 0)
        by = {p["seat"]: p for p in st["players"]}
        assert by[0]["controller"] == "human"
        assert by[seat_b]["controller"] == "bot_cover"
        assert by[seat_b]["reserved_for"] == "james"
        botseat = next(i for i, sd in enumerate(room.seats) if sd.is_bot)
        assert by[botseat]["controller"] == "bot"
        assert by[botseat]["reserved_for"] is None


def test_pregame_full_lobby_with_a_drop_is_claimable(client, clock):
    """P0-4: a full PRE-GAME lobby with one dropped player must not deadlock."""
    with client.websocket_connect("/ws") as h:
        h.send_json({"type": "create_room", "name": "host"})
        code = _drain(h, "room")["room"]
        with ExitStack() as sockets:
            peers, peer_stacks = [], []
            for n in ("p2", "p3", "p4"):
                peer_stack = ExitStack()
                sockets.callback(peer_stack.close)
                w = peer_stack.enter_context(client.websocket_connect("/ws"))
                w.send_json({"type": "join_room", "room": code, "name": n})
                _drain(w, "room")
                peers.append(w)
                peer_stacks.append(peer_stack)
            peer_stacks[0].close()                  # drop BEFORE start_game
            from shengji.api import server as srv
            clock["v"] += srv.TAKEOVER_AFTER + 1    # past the reservation
            with client.websocket_connect("/ws") as p:
                p.send_json({"type": "peek_room", "room": code})
                pk = _drain(p, "room_seats")
                assert pk["in_game"] is False
                claim = [s for s in pk["seats"] if s["claimable"]]
                assert (len(claim) == 1
                        and claim[0]["controller"] == "bot_cover"), \
                    "a dropped pre-game seat must be visibly claimable"
            with client.websocket_connect("/ws") as q:
                q.send_json({"type": "join_room", "room": code,
                             "name": "newbie", "seat": claim[0]["seat"]})
                st = _drain(q, "room", tries=60)
                assert st["you"] == claim[0]["seat"]


def test_explicit_leave_at_round_end_advances_the_round(client):
    """P0-4: leaving must release the quorum exactly like dropping does."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a, to_play=True)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "join_room", "room": code, "name": "james"})
            _drain(b, "state", tries=60)
            seat_b = next(i for i, sd in enumerate(room.seats)
                          if sd.name == "james")
            # Pretend the round ended with only `a` ready.
            room.ready.add(0)
            assert srv.pending_ready(room) == {seat_b}
            b.send_json({"type": "leave_room"})
            _drain(b, "left", tries=40)
        assert srv.pending_ready(room) == set(), \
            "the leaver is still being waited on"


# ------------------------------------------------- P0-3: no double-play ever
@pytest.fixture()
def clock(monkeypatch):
    """Injected clock: advance time instead of sleeping through TAKEOVER_AFTER."""
    from shengji.api import server as srv

    t = {"v": 1000.0}
    monkeypatch.setattr(srv, "now", lambda: t["v"])
    return t


def _plays_by(room, seat):
    """How many TIMES this seat has played — not how many cards, since one
    legal play can be a pair, a tractor, or a throw."""
    rnd = room.round
    n = sum(1 for t in rnd.history for p in t.plays if p.seat == seat)
    if rnd.trick is not None:
        n += sum(1 for p in rnd.trick.plays if p.seat == seat)
    return n


def _turn_owner_drops(client, a, code, room):
    """Make the seat on turn a disconnected human. Returns (seat, socket)."""
    turn = room.round.turn
    if room.seats[turn].is_bot:
        # Put a human on the seat that is about to act.
        with client.websocket_connect("/ws") as w:
            w.send_json({"type": "join_room", "room": code,
                         "name": "onturn", "seat": turn})
            _drain(w, "state", tries=60)
    return turn


def test_bot_does_not_act_before_the_grace_period(client, clock):
    """Inside the grace window the absent player's seat must not be played."""
    import asyncio as aio

    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a, to_play=True)
        seat = _turn_owner_drops(client, a, code, room)
        if room.seats[seat].connected or room.seats[seat].is_bot:
            pytest.skip("could not place a disconnected human on turn")
        before = list(room.round.hands[seat])
        clock["v"] += srv.TAKEOVER_AFTER - 1          # still inside the grace
        loop = aio.new_event_loop()
        try:
            acted = loop.run_until_complete(srv.watchdog_tick(room))
        finally:
            loop.close()
        assert not acted, "bot acted before the grace period expired"
        assert list(room.round.hands[seat]) == before
        assert room.round.turn == seat, "turn advanced without a play"


def test_takeover_plays_exactly_once_then_stops(client, clock):
    """Advance past grace: one bot action, and not a second for the same turn."""
    import asyncio as aio

    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a, to_play=True)
        seat = _turn_owner_drops(client, a, code, room)
        if room.seats[seat].connected or room.seats[seat].is_bot:
            pytest.skip("could not place a disconnected human on turn")
        plays_before = _plays_by(room, seat)
        clock["v"] += srv.TAKEOVER_AFTER + 1
        loop = aio.new_event_loop()
        try:
            acted = loop.run_until_complete(srv.watchdog_tick(room))
            assert acted, "bot never covered the absent player"
            assert _plays_by(room, seat) == plays_before + 1, \
                "the covered seat played more than once for one turn"
            # Ticking again must not play a second time for the same turn.
            if room.round.turn != seat:
                loop.run_until_complete(srv.watchdog_tick(room))
                assert _plays_by(room, seat) == plays_before + 1
        finally:
            loop.close()


def test_reconnect_after_takeover_sees_the_bot_s_hand(client, clock):
    import asyncio as aio

    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a, to_play=True)
        seat = _turn_owner_drops(client, a, code, room)
        if room.seats[seat].connected or room.seats[seat].is_bot:
            pytest.skip("could not place a disconnected human on turn")
        tok = room.seats[seat].token
        clock["v"] += srv.TAKEOVER_AFTER + 1
        loop = aio.new_event_loop()
        try:
            loop.run_until_complete(srv.watchdog_tick(room))
        finally:
            loop.close()
        expect = sorted(room.round.hands[seat])
        with client.websocket_connect("/ws") as back:
            back.send_json({"type": "join_room", "room": code,
                            "name": "onturn", "token": tok})
            st = _drain(back, "state", tries=60)
            assert st["you"] == seat
            assert sorted(c["code"] for c in st["hand"]) == expect, \
                "reconnecting player did not see the hand the bot left"
            assert room.seats[seat].bot_announced is False


def test_overlapping_resume_race_is_stable(client):
    """P0-1: repeat the overlap race; the newest socket must always own it."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a, to_play=True)
        seat0 = room.seats[0]
        tok = seat0.token
        for i in range(25):
            gen_before = seat0.gen
            with client.websocket_connect("/ws") as w:
                w.send_json({"type": "join_room", "room": code,
                             "name": "jerry", "token": tok})
                _drain(w, "state", tries=60)
                assert seat0.gen > gen_before, \
                    f"iteration {i}: generation stalled"
                assert seat0.connected
                srv._detach(seat0, room, gen_before)  # stale teardown, late
                assert seat0.connected, \
                    f"iteration {i}: stale teardown won"


# ------------------------------- Codex re-audit 2026-08-04: public-path bugs
def test_create_room_issues_a_resume_token(client):
    """create_room bypassed _attach: no token, no generation, no identity."""
    with client.websocket_connect("/ws") as a:
        a.send_json({"type": "create_room", "name": "jerry"})
        res = _drain(a, "resume")
        assert res["token"] and res["gen"] >= 1


def test_creator_refresh_does_not_duplicate_the_seat(client):
    """The exact client path: create, take the wire token, refresh over it."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        a.send_json({"type": "create_room", "name": "jerry"})
        tok = _drain(a, "resume")["token"]
        code = _drain(a, "room")["room"]
        with client.websocket_connect("/ws") as a2:
            a2.send_json({"type": "join_room", "room": code,
                          "name": "jerry", "token": tok})
            st = _drain(a2, "room")
            assert st["you"] == 0, "refresh landed on a different seat"
            assert len(srv.rooms[code].seats) == 1, \
                "refresh appended a second seat for the same person"


def test_displaced_socket_cannot_act(client):
    """A socket replaced by a newer one owns nothing — not even leave_room."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as h:
        h.send_json({"type": "create_room", "name": "host"})
        code = _drain(h, "room")["room"]
        with ExitStack() as sockets:
            old = sockets.enter_context(client.websocket_connect("/ws"))
            old.send_json({"type": "join_room", "room": code, "name": "bob"})
            tok = _drain(old, "resume")["token"]
            _drain(old, "room")
            new = sockets.enter_context(client.websocket_connect("/ws"))
            new.send_json({"type": "join_room", "room": code,
                           "name": "bob", "token": tok})
            _drain(new, "room")
            room = srv.rooms[code]
            assert room.seats[1].connected

            old.send_json({"type": "leave_room"})  # displaced socket acts
            err = _drain(old, "error")
            assert err["code"] == "stale_connection"
            assert code in srv.rooms, "stale leave deleted the room"
            assert len(room.seats) == 2, "stale leave removed the live seat"
            assert room.seats[1].connected, \
                "stale leave detached the live socket"


def test_claiming_a_seat_rotates_its_token(client, clock):
    """The previous owner must not be able to displace the new one later."""
    with client.websocket_connect("/ws") as a:
        with ExitStack() as sockets:
            code, room, socks, peer_stacks = _four_humans(
                client, a, sockets)
            old_tok = room.seats[1].token
            # A prior bot-cover announcement belongs to the previous owner.
            # If seat claim does not clear it, the next disconnect silently
            # suppresses the new owner's takeover announcement.
            room.seats[1].bot_announced = True
            peer_stacks[0].close()                    # amy drops
            from shengji.api import server as srv
            clock["v"] += srv.TAKEOVER_AFTER + 1      # past the reservation
            with client.websocket_connect("/ws") as taker:
                taker.send_json({"type": "join_room", "room": code,
                                 "name": "newbie", "seat": 1})
                _drain(taker, "state", tries=60)
                assert room.seats[1].token != old_tok, \
                    "token survived the transfer"
                assert room.seats[1].bot_announced is False, \
                    "claimed seat inherited the prior owner's bot announcement"
                # The old token must no longer resume that seat.
                with client.websocket_connect("/ws") as amy:
                    amy.send_json({"type": "join_room", "room": code,
                                   "name": "amy", "token": old_tok})
                    m = None
                    for _ in range(40):
                        m = amy.receive_json()
                        if m.get("type") in ("room", "state", "error"):
                            break
                    seat = (m.get("you") if m.get("type") in ("room", "state")
                            else None)
                    assert seat != 1, "stale token displaced the new owner"


def test_play_shape_distinguishes_tractor_from_two_pair_throw():
    """A two-PAIR throw is not a tractor — the audio called it 拖拉机."""
    import random

    from shengji.ai.heuristic import HeuristicBot
    from shengji.api.server import play_shape
    from shengji.engine.game import Game

    g = Game(random.Random(5))
    r = g.start_round()
    hb = HeuristicBot()
    while r.phase != "play":
        if r.phase == "deal":
            r.deal_next()
        elif r.phase == "declare":
            r.finalize_declare()
        elif r.phase == "bury":
            r.bury(r.banker, hb.decide_bury(r, r.banker))
    o = r.ordering
    assert play_shape(["S5"], o) == "single"
    assert play_shape(["S5", "S5"], o) == "pair"
    assert play_shape(["S5", "S5", "S6", "S6"], o) == "tractor"
    # The reported bug: two pairs that are NOT consecutive.
    assert play_shape(["S5", "S5", "S9", "S9"], o) == "throw"
    # Two pairs in different suits are a throw too.
    assert play_shape(["S5", "S5", "H9", "H9"], o) == "throw"
    # Three consecutive pairs remain a tractor.
    assert play_shape(["S5", "S5", "S6", "S6", "S7", "S7"], o) == "tractor"


# ------------------------------------------- starting level (create_room)
def test_room_defaults_to_level_two(client):
    with client.websocket_connect("/ws") as a:
        a.send_json({"type": "create_room", "name": "jerry"})
        m = _drain(a, "room")
        assert m["start_level"] == "2"


def test_create_room_honours_the_chosen_start_level(client):
    """End to end: the picked level must reach the DEALT round, not just the
    room record."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        a.send_json({"type": "create_room", "name": "jerry", "start_level": "10"})
        m = _drain(a, "room")
        assert m["start_level"] == "10"
        code = m["room"]
        for _ in range(3):
            a.send_json({"type": "add_bot"})
            _drain(a, "room")
        a.send_json({"type": "start_game"})
        _drain(a, "state")
        game = srv.rooms[code].game
        assert game is not None
        assert game.levels == ("10", "10")
        assert game.round is not None
        assert game.round.trump_rank == "10", "dealt at a different rank"


def test_unknown_start_level_is_refused_and_creates_no_room(client):
    """Coercing to 2 would hand the player a game their own UI misdescribes."""
    from shengji.api import server as srv

    before = set(srv.rooms)
    with client.websocket_connect("/ws") as a:
        a.send_json({"type": "create_room", "name": "jerry", "start_level": "1"})
        m = _drain(a, "error")
        assert m["code"] == "bad_start_level"
    assert set(srv.rooms) == before, "a refused create still left a room behind"


def test_refused_start_level_leaves_the_socket_usable(client):
    """The handler `continue`s; the same connection must still be able to
    create a room afterwards."""
    with client.websocket_connect("/ws") as a:
        a.send_json({"type": "create_room", "name": "jerry", "start_level": "Z"})
        assert _drain(a, "error")["code"] == "bad_start_level"
        a.send_json({"type": "create_room", "name": "jerry"})
        assert _drain(a, "room")["start_level"] == "2"


@pytest.mark.parametrize("bad", [1, 8, None, ["8"], {"r": "8"}, True])
def test_non_string_start_levels_are_refused(client, bad):
    """`None` is the one value that means "unspecified" -- everything else
    that is not a known rank is an error, including a bare int 8."""
    with client.websocket_connect("/ws") as a:
        a.send_json({"type": "create_room", "name": "jerry", "start_level": bad})
        m = _drain(a, "room" if bad is None else "error")
        if bad is None:
            assert m["start_level"] == "2"
        else:
            assert m["code"] == "bad_start_level"


def test_web_and_engine_rank_lists_agree():
    """protocol.ts hand-mirrors RANKS. Drift would let the lobby offer a level
    the server refuses (or hide one it accepts)."""
    import json
    import pathlib
    import re

    from shengji.engine.cards import RANKS

    src = (pathlib.Path(__file__).resolve().parents[2]
           / "web" / "src" / "protocol.ts").read_text()
    match = re.search(r"export const RANKS = \[(.*?)\] as const;", src, re.S)
    assert match, "RANKS literal not found in protocol.ts"
    web_ranks = json.loads("[" + match.group(1).replace("\n", " ") + "]")
    assert web_ranks == RANKS, f"web {web_ranks} != engine {RANKS}"


# ------------------------------------------- writer observability (#628)
def test_a_dead_writer_leaves_every_other_signal_saying_healthy(client):
    """The #628 signature, reproduced: kill ONLY the writer and the reader sees
    exactly `saw []` while the seat still reports connected and the queue grows.

    This is what makes the failure mode so hard to see, and it is the reason
    the writer must not exit silently."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        a.send_json({"type": "create_room", "name": "jerry"})
        _drain(a, "room")
        code = list(srv.rooms)[0]
        seat = srv.rooms[code].seats[0]
        for _ in range(3):
            a.send_json({"type": "add_bot"})
            _drain(a, "room")

        seat.writer.cancel()                 # nothing else changes
        assert seat.connected, "seat still reports connected"

        a.send_json({"type": "start_game"})
        with pytest.raises(AssertionError) as caught:
            _drain(a, "state", tries=2, timeout=1.0)
        assert "saw []" in str(caught.value), str(caught.value)
        assert seat.queue.qsize() > 0, "frames were produced but never written"


def test_one_send_failure_is_recorded_and_logged_not_swallowed(client, caplog):
    """A single raise from send_json ends the writer. That is unchanged. What
    must NOT happen is it ending with no trace at all."""
    import logging as _logging
    from shengji.api import server as srv

    calls = {"n": 0}
    real_writer_body = srv._writer

    async def flaky(ws, queue, seat=None):
        class OneShotFlaky:
            async def send_json(self, payload):
                calls["n"] += 1
                if calls["n"] == 2:
                    raise RuntimeError("transient send failure")
                return await ws.send_json(payload)
        return await real_writer_body(OneShotFlaky(), queue, seat)

    monkeypatched = srv._writer
    srv._writer = flaky
    try:
        with caplog.at_level(_logging.WARNING):
            with client.websocket_connect("/ws") as a:
                a.send_json({"type": "create_room", "name": "jerry"})
                _drain(a, "resume", tries=2, timeout=1.0)
                code = list(srv.rooms)[0]
                seat = srv.rooms[code].seats[0]
                with pytest.raises(AssertionError):
                    _drain(a, "room", tries=2, timeout=1.0)

                assert seat.writer.done(), "writer exited (unchanged behaviour)"
                assert seat.connected, "seat still reports connected"
                # The point of the change:
                assert seat.writer_error is not None, \
                    "writer died with NO record -- this is the #628 blind spot"
                assert "transient send failure" in seat.writer_error
                assert any("websocket writer stopped" in r.message
                           for r in caplog.records), \
                    "writer death was not logged"
    finally:
        srv._writer = monkeypatched


def test_ordinary_cancellation_is_not_recorded_as_an_error(client):
    """Displacement and detach cancel the writer as a matter of course. That is
    not an error and must not be reported as one, or the new signal is noise."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        a.send_json({"type": "create_room", "name": "jerry"})
        _drain(a, "room")
        code = list(srv.rooms)[0]
        seat = srv.rooms[code].seats[0]
        seat.writer.cancel()
        import time as _t
        _t.sleep(0.2)
        assert seat.writer_error is None, \
            f"cancellation recorded as an error: {seat.writer_error!r}"


def test_reattaching_clears_a_stale_writer_error(client):
    """A previous socket's failure must not haunt the next one."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        a.send_json({"type": "create_room", "name": "jerry"})
        tok = _drain(a, "resume")["token"]
        code = list(srv.rooms)[0]
        seat = srv.rooms[code].seats[0]
        _drain(a, "room")
        seat.writer_error = "stale: from an earlier socket"
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "join_room", "room": code,
                         "name": "jerry", "token": tok})
            _drain(b, "room")
            assert seat.writer_error is None, "stale error survived a reattach"


# ------------------------------- writer exit reason (#628 follow-up)
def _cancel_scenario(pre_step: bool):
    """Drive a writer to cancellation ENTIRELY inside one event loop.

    These assertions are about cancellation timing, so they must not cancel
    across threads: TestClient runs the server loop in another thread, and
    asyncio.Task.cancel() is not thread-safe. Doing it that way made this test
    pass, fail, pass on three identical runs -- a flake of exactly the kind
    #628 is about, which is not something to add to this suite.
    """
    import asyncio as _asyncio
    from shengji.api import server as srv

    async def scenario():
        seat = srv.Seat(name="jerry")
        seat.queue = _asyncio.Queue()

        class Idle:
            async def send_json(self, payload):
                await _asyncio.sleep(3600)

        task = srv._start_writer(seat, Idle())
        if pre_step:
            await _asyncio.sleep(0)       # let the body reach its first await
        task.cancel()
        try:
            await task
        except _asyncio.CancelledError:
            pass
        await _asyncio.sleep(0)           # let the done-callback run
        return seat, task

    return _asyncio.run(scenario())


def test_cancellation_is_recorded_but_not_an_error():
    """Cancellation must be DISTINGUISHABLE from 'never exited', while still
    not being reported as an error."""
    seat, _ = _cancel_scenario(pre_step=True)
    assert seat.writer_exit == "cancelled", seat.writer_exit
    assert seat.writer_error is None, \
        "cancellation must not be recorded as an error"


def test_cancellation_still_propagates():
    """Recording must not swallow CancelledError: the task must still end up
    cancelled, or every caller awaiting it hangs."""
    _, task = _cancel_scenario(pre_step=True)
    assert task.cancelled(), \
        "CancelledError was swallowed; the task did not end up cancelled"


def test_a_live_writer_reads_as_none():
    """The property that makes the instrument two-sided, at the unit level."""
    import asyncio as _asyncio
    from shengji.api import server as srv

    async def scenario():
        seat = srv.Seat(name="jerry")
        seat.queue = _asyncio.Queue()

        class Idle:
            async def send_json(self, payload):
                await _asyncio.sleep(3600)

        task = srv._start_writer(seat, Idle())
        await _asyncio.sleep(0)
        live = (seat.writer_exit, seat.writer_error, task.done())
        task.cancel()
        try:
            await task
        except _asyncio.CancelledError:
            pass
        return live

    exit_reason, error, done = scenario_result = _asyncio.run(scenario())
    assert exit_reason is None and error is None and not done, scenario_result


def test_an_exception_exit_is_distinguishable_from_cancellation(client):
    from shengji.api import server as srv

    calls = {"n": 0}
    real = srv._writer

    async def flaky(ws, queue, seat=None):
        class OneShot:
            async def send_json(self, payload):
                calls["n"] += 1
                if calls["n"] == 2:
                    raise RuntimeError("transient send failure")
                return await ws.send_json(payload)
        return await real(OneShot(), queue, seat)

    keep = srv._writer
    srv._writer = flaky
    try:
        with client.websocket_connect("/ws") as a:
            a.send_json({"type": "create_room", "name": "jerry"})
            _drain(a, "resume", tries=2, timeout=1.0)
            seat = srv.rooms[list(srv.rooms)[0]].seats[0]
            with pytest.raises(AssertionError):
                _drain(a, "room", tries=2, timeout=1.0)
            assert seat.writer_exit == "error", seat.writer_exit
            assert "transient send failure" in (seat.writer_error or "")
    finally:
        srv._writer = keep


def test_none_now_means_still_running(client):
    """The property that makes the instrument two-sided: with a healthy
    socket, BOTH fields stay None, so None is evidence rather than ambiguity."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        a.send_json({"type": "create_room", "name": "jerry"})
        _drain(a, "room")
        seat = srv.rooms[list(srv.rooms)[0]].seats[0]
        for _ in range(3):
            a.send_json({"type": "add_bot"})
            _drain(a, "room")
        assert seat.writer_exit is None
        assert seat.writer_error is None
        assert not seat.writer.done(), "writer still running"


def test_reattach_clears_the_exit_reason(client):
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        a.send_json({"type": "create_room", "name": "jerry"})
        tok = _drain(a, "resume")["token"]
        code = list(srv.rooms)[0]
        seat = srv.rooms[code].seats[0]
        _drain(a, "room")
        seat.writer_exit = "cancelled"
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "join_room", "room": code,
                         "name": "jerry", "token": tok})
            _drain(b, "room")
            assert seat.writer_exit is None, "stale exit reason survived reattach"


def test_cancel_before_the_first_step_is_still_recorded():
    """Codex's P2 on #641: a task cancelled before its coroutine takes its
    first step never runs the body, so no except clause fires. The task is
    done() and cancelled() while an in-body record would say nothing.

    This is the case that would have made `writer_exit is None` a LIE -- it
    would have read 'still running' for a writer that was already dead.
    """
    import asyncio as _asyncio
    from shengji.api import server as srv

    async def scenario():
        seat = srv.Seat(name="jerry")
        seat.queue = _asyncio.Queue()

        class NeverSends:
            async def send_json(self, payload):   # never reached
                raise AssertionError("body should not have run")

        task = srv._start_writer(seat, NeverSends())
        task.cancel()                    # BEFORE the coroutine ever steps
        try:
            await task
        except _asyncio.CancelledError:
            pass
        await _asyncio.sleep(0)          # let the done-callback run
        return seat, task

    seat, task = _asyncio.run(scenario())
    assert task.done() and task.cancelled(), "precondition: cancelled before first step"
    assert seat.writer_exit == "cancelled", (
        "a writer that died before its first step read as %r -- "
        "'still running' for a dead writer" % (seat.writer_exit,))


def test_a_displaced_writer_does_not_stamp_the_new_socket():
    """The old writer must not record onto a seat the NEW socket owns.

    The assertion has to land WHILE the new writer is still live. Asserting
    only at the end cannot detect the bug: the new writer's own cancellation
    also writes "cancelled", so a displaced writer that wrongly stamped would
    produce an identical final value (Codex, nonblocking on #641).

    Callback dispatch is asynchronous, so this also witnesses that the old
    task genuinely COMPLETED -- its callback has had its chance to run -- and
    only then checks that the field is still untouched.
    """
    import asyncio as _asyncio
    from shengji.api import server as srv

    async def scenario():
        seat = srv.Seat(name="jerry")
        seat.queue = _asyncio.Queue()

        class Idle:
            async def send_json(self, payload):
                await _asyncio.sleep(3600)

        old = srv._start_writer(seat, Idle())
        await _asyncio.sleep(0)
        new = srv._start_writer(seat, Idle())   # displaces: seat.writer is `new`
        assert seat.writer is new

        old.cancel()
        try:
            await old
        except _asyncio.CancelledError:
            pass
        for _ in range(5):                      # let callbacks actually dispatch
            await _asyncio.sleep(0)

        # The witness, taken while `new` is still LIVE.
        witness = {
            "old_done": old.done(),
            "old_cancelled": old.cancelled(),
            "new_done": new.done(),
            "writer_exit": seat.writer_exit,
            "writer_error": seat.writer_error,
        }

        new.cancel()
        try:
            await new
        except _asyncio.CancelledError:
            pass
        for _ in range(5):
            await _asyncio.sleep(0)
        return witness, seat

    witness, seat = _asyncio.run(scenario())

    # The old task really finished, so its callback ran and declined to record.
    assert witness["old_done"] and witness["old_cancelled"], witness
    assert not witness["new_done"], witness
    assert witness["writer_exit"] is None, (
        "a DISPLACED writer stamped the seat the new socket owns: %r" % (witness,))
    assert witness["writer_error"] is None, witness

    # And once the owner itself is cancelled, the record appears normally.
    assert seat.writer_exit == "cancelled"


# --------------------------------- disconnect vs a real RuntimeError (#639)
def _starlette_socket_after_a_failed_send():
    """Drive a REAL starlette WebSocket into the state #639 happens in.

    A send that fails with OSError sets application_state = DISCONNECTED and
    raises WebSocketDisconnect, but leaves client_state at CONNECTED. The next
    receive_json then raises the exact #639 RuntimeError. This is the
    transition, not a mock of it (Codex, P2 on #643)."""
    import asyncio as _asyncio
    from starlette.websockets import WebSocket, WebSocketState

    async def scenario():
        async def receive():
            return {"type": "websocket.connect"}

        async def send(message):
            if message["type"] == "websocket.send":
                raise OSError("broken pipe")

        ws = WebSocket({"type": "websocket", "path": "/ws", "headers": []},
                       receive, send)
        await ws.accept()
        assert ws.application_state is WebSocketState.CONNECTED
        try:
            await ws.send_json({"hello": 1})
        except Exception:
            pass
        return ws

    return _asyncio.run(scenario())


def test_a_failed_send_leaves_client_state_lying_about_the_connection():
    """The trap: after a failed send the socket is NOT receivable, yet
    client_state still says CONNECTED. Anything keying off client_state reports
    healthy for exactly the socket that is about to raise."""
    from starlette.websockets import WebSocketState

    ws = _starlette_socket_after_a_failed_send()
    assert ws.application_state is WebSocketState.DISCONNECTED
    assert ws.client_state is WebSocketState.CONNECTED, \
        "if starlette ever fixes this, the helper choice should be revisited"


def test_the_helper_reads_the_state_that_actually_gates_receive():
    """Regression for the P2: _receive_is_legal must be False here. Reading
    client_state returns True and the #639 traceback escapes anyway."""
    from shengji.api import server as srv

    ws = _starlette_socket_after_a_failed_send()
    assert srv._receive_is_legal(ws) is False


def test_that_state_really_does_raise_the_639_runtimeerror():
    """Ties the helper to the actual failure: a receive in this state raises
    the exact error #639 is about."""
    import asyncio as _asyncio

    ws = _starlette_socket_after_a_failed_send()
    with pytest.raises(RuntimeError, match="not connected"):
        _asyncio.run(ws.receive_json())


class _FakeSocket:
    """Minimal websocket that raises RuntimeError on the first receive."""

    def __init__(self, state, message='WebSocket is not connected. Need to call "accept" first.'):
        from starlette.websockets import WebSocketState
        # application_state is the field that gates receive, so it is the one
        # under test; client_state is pinned CONNECTED precisely because that
        # is the misleading combination a failed send produces.
        self.application_state = state
        self.client_state = WebSocketState.CONNECTED
        self._message = message
        self.accepted = False
        self.query_params = {}

    async def accept(self):
        self.accepted = True

    async def receive_json(self):
        raise RuntimeError(self._message)

    async def send_json(self, payload):
        return None

    async def close(self, code=1000):
        return None


def test_a_runtimeerror_from_a_gone_peer_is_treated_as_a_disconnect():
    """#639: starlette raises RuntimeError, not WebSocketDisconnect, when the
    peer is already gone. That escaped as an ASGI traceback for what is an
    ordinary disconnect."""
    import asyncio as _asyncio
    from starlette.websockets import WebSocketState
    from shengji.api import server as srv

    sock = _FakeSocket(WebSocketState.DISCONNECTED)
    _asyncio.run(srv.ws_endpoint(sock))      # must NOT raise
    assert sock.accepted


def test_a_runtimeerror_while_still_connected_keeps_propagating():
    """The narrowing must not swallow a genuine bug of ours. A RuntimeError
    raised while the socket is still CONNECTED is not a disconnect."""
    import asyncio as _asyncio
    import pytest as _pytest
    from starlette.websockets import WebSocketState
    from shengji.api import server as srv

    sock = _FakeSocket(WebSocketState.CONNECTED, message="genuine bug in our code")
    with _pytest.raises(RuntimeError, match="genuine bug"):
        _asyncio.run(srv.ws_endpoint(sock))


def test_the_discriminator_is_state_not_message_text():
    """Matching the message string would break silently the day starlette
    rewords it, and would swallow same-worded bugs."""
    from starlette.websockets import WebSocketState
    from shengji.api import server as srv

    assert srv._receive_is_legal(_FakeSocket(WebSocketState.CONNECTED)) is True
    for state in (WebSocketState.DISCONNECTED, WebSocketState.CONNECTING):
        sock = _FakeSocket(state)
        assert sock.client_state is WebSocketState.CONNECTED, "the misleading combination"
        assert srv._receive_is_legal(sock) is False


def test_a_room_plays_on_past_ace_and_keeps_score(client):
    """A table must not end at A: it scores a game and restarts. Rooms pass
    games_to_win=None, unlike the engine default that evaluation relies on."""
    from shengji.api import server as srv
    from shengji.engine.game import A_INDEX

    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        a.send_json({"type": "start_game"})
        _drain(a, "state")
        game = srv.rooms[code].game
        assert game.games_to_win is None, "a room must not end at one game"

        game.level_idx = [A_INDEX, A_INDEX]
        rnd = game.round
        rnd.phase = "round_end"
        rnd.banker = 0
        rnd.attacker_points = 0          # banker team holds A
        result = game.finish_round()

        assert result.point_scored and result.games_won == (1, 0)
        assert not result.game_over and not game.game_over
        assert game.levels == ("2", "2"), "levels restart for the next game"


def test_the_state_payload_carries_games_won(client):
    with client.websocket_connect("/ws") as a:
        _room_with_bots(a)
        a.send_json({"type": "start_game"})
        st = _drain(a, "state")
        assert st["games_won"] == [0, 0], st.get("games_won")


def test_round_result_payload_carries_the_scoring_fields(client):
    """Codex P2 on #644: the modal reads round_result, so omitting the new
    fields there left the UI saying '+levels' on a game win and reset."""
    from shengji.api import server as srv
    from shengji.engine.game import A_INDEX

    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        a.send_json({"type": "start_game"})
        _drain(a, "state")
        room = srv.rooms[code]
        game = room.game
        game.level_idx = [A_INDEX, A_INDEX]
        rnd = game.round
        rnd.phase = "round_end"
        rnd.banker = 0
        rnd.attacker_points = 0
        game.finish_round()

        payload = srv.state_for(room, 0)["round_result"]
        assert payload["point_scored"] is True
        assert payload["games_won"] == [1, 0]
        assert payload["new_levels"] == ["2", "2"], payload["new_levels"]
        assert payload["game_over"] is False


# ------------------------------ the host sets the level in the ROOM (Jerry 09-26)
def test_host_sets_the_start_level_in_the_room_and_everyone_sees_it(client):
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as host:
        host.send_json({"type": "create_room", "name": "jerry"})
        code = _drain(host, "room")["room"]
        with client.websocket_connect("/ws") as guest:
            guest.send_json({"type": "join_room", "room": code, "name": "robin"})
            _drain(guest, "room")
            _drain(host, "room")                      # the join broadcast
            host.send_json({"type": "set_start_level", "start_level": "9"})
            assert _drain(host, "room")["start_level"] == "9"
            assert _drain(guest, "room")["start_level"] == "9", \
                "a joiner must see the level the host picked"
            assert srv.rooms[code].start_level == "9"


def test_only_the_host_can_set_the_start_level(client):
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as host:
        host.send_json({"type": "create_room", "name": "jerry"})
        code = _drain(host, "room")["room"]
        with client.websocket_connect("/ws") as guest:
            guest.send_json({"type": "join_room", "room": code, "name": "robin"})
            _drain(guest, "room")
            guest.send_json({"type": "set_start_level", "start_level": "9"})
            assert "host" in _drain(guest, "error")["message"].lower()
            assert srv.rooms[code].start_level == "2", "a guest changed the level"


def test_the_start_level_is_fixed_once_the_game_starts(client):
    """Game() reads the level exactly once at start_game; a later change would
    make the HUD lie for the rest of the session."""
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        for _ in range(3):
            _drain(a, "room")
        a.send_json({"type": "start_game"})
        _drain(a, "state")
        a.send_json({"type": "set_start_level", "start_level": "K"})
        # The refusal shares the seat's FIFO queue with the card-by-card deal
        # broadcasts (one state per DEAL_DELAY, ~108 for a full deal). On a
        # loaded CI runner the handler ran behind 40+ of them and the default
        # 40-message window read "no error" (2026-09-26); the window must
        # cover the whole deal, not the runner's idea of prompt.
        assert "fixed" in _drain(a, "error", tries=400)["message"].lower()
        assert srv.rooms[code].start_level == "2"
        assert srv.rooms[code].game.levels == ("2", "2")


def test_an_unknown_room_level_is_refused_not_coerced(client):
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as a:
        a.send_json({"type": "create_room", "name": "jerry"})
        code = _drain(a, "room")["room"]
        a.send_json({"type": "set_start_level", "start_level": "1"})
        assert "unknown" in _drain(a, "error")["message"].lower()
        assert srv.rooms[code].start_level == "2"


# ------------------------------------------------------------------ Ranked switch
# A created room starts unranked; its host may switch Ranked on or off in the
# lobby (``set_ranked``), and every seat sees the mode in the room frame.
def test_the_host_switches_ranked_and_every_seat_sees_it(client):
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as host:
        host.send_json({"type": "create_room", "name": "jerry"})
        first = _drain(host, "room")
        code = first["room"]
        assert "ranked" not in first and srv.rooms[code].ranked is False
        with client.websocket_connect("/ws") as guest:
            guest.send_json({"type": "join_room", "room": code, "name": "robin"})
            _drain(guest, "room")
            _drain(host, "room")
            host.send_json({"type": "set_ranked", "on": True})
            assert _drain(host, "room")["ranked"] is True
            assert _drain(guest, "room")["ranked"] is True
            assert srv.rooms[code].ranked is True
            host.send_json({"type": "set_ranked", "on": False})
            assert "ranked" not in _drain(guest, "room")
            assert srv.rooms[code].ranked is False


def test_only_the_host_can_switch_ranked(client):
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as host:
        host.send_json({"type": "create_room", "name": "jerry"})
        code = _drain(host, "room")["room"]
        with client.websocket_connect("/ws") as guest:
            guest.send_json({"type": "join_room", "room": code, "name": "robin"})
            _drain(guest, "room")
            guest.send_json({"type": "set_ranked", "on": True})
            assert "host" in _drain(guest, "error")["message"].lower()
            assert srv.rooms[code].ranked is False


def test_ranked_is_fixed_once_the_game_starts(client):
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        for _ in range(3):
            _drain(a, "room")
        a.send_json({"type": "set_ranked", "on": True})
        _drain(a, "room")
        a.send_json({"type": "start_game"})
        assert _drain(a, "state")["ranked"] is True
        a.send_json({"type": "set_ranked", "on": False})
        # the refusal queues behind the deal's broadcasts, as for the level
        assert "fixed" in _drain(a, "error", tries=400)["message"].lower()
        assert srv.rooms[code].ranked is True


def test_a_guest_joins_a_ranked_created_room_by_code(client):
    """A created ranked room keeps the open join: the queue-only refusals
    belong to queue-matched rooms."""
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as host:
        host.send_json({"type": "create_room", "name": "jerry"})
        code = _drain(host, "room")["room"]
        host.send_json({"type": "set_ranked", "on": True})
        _drain(host, "room")
        with client.websocket_connect("/ws") as guest:
            guest.send_json({"type": "peek_room", "room": code})
            assert "ranked" not in _drain(guest, "room_seats")
            guest.send_json({"type": "join_room", "room": code, "name": "robin"})
            joined = _drain(guest, "room")
            assert joined["you"] == 1 and joined["ranked"] is True
            assert [s.name for s in srv.rooms[code].seats] == ["jerry", "robin"]


def test_the_room_level_reaches_the_dealt_round(client):
    """End to end: the level set in the room must be what round 1 is DEALT at."""
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        for _ in range(3):
            _drain(a, "room")
        a.send_json({"type": "set_start_level", "start_level": "J"})
        _drain(a, "room")
        a.send_json({"type": "start_game"})
        _drain(a, "state")
        game = srv.rooms[code].game
        assert game.levels == ("J", "J")
        assert game.round.trump_rank == "J", "dealt at a different rank than shown"


# ------------------------------------------------------------------ #628 room tasks
def test_a_deal_task_that_dies_is_recorded_and_named_in_the_timeout(client, caplog):
    """The real start_game path spawns the deal task. If it raises, the seat's
    reader sees exactly the #628 signature (no state within 5 s, saw []) --
    and the message now says WHY, and a warning is logged."""
    import logging as _logging
    from shengji.api import server as srv

    async def doomed(room):
        raise RuntimeError("deal exploded")
    real = srv.run_deal
    srv.run_deal = doomed
    try:
        with caplog.at_level(_logging.WARNING):
            with client.websocket_connect("/ws") as a:
                code = _room_with_bots(a)
                a.send_json({"type": "start_game"})
                # The start handler broadcasts once itself; every frame after
                # that is the deal task's. This is the CI failure's shape: a
                # first state, then nothing (test_server_ws.py:271, #628).
                _drain(a, "state", tries=60)
                with pytest.raises(AssertionError) as info:
                    _drain(a, "state", tries=400, timeout=1.0)
                msg = str(info.value)
                assert "within 1.0s" in msg                 # timed out, not exhausted
                assert f"{code}: phase=deal" in msg
                assert "deal_task=error: RuntimeError: deal exploded" in msg
                assert "bot_task=never" in msg
                assert "writer=running" in msg
                room = srv.rooms[code]
                assert room.task_exits["deal_task"] == "error: RuntimeError: deal exploded"
                assert any("deal_task failed: RuntimeError: deal exploded" in r.message
                           for r in caplog.records), "deal task death was not logged"
    finally:
        srv.run_deal = real


def test_a_cancelled_deal_task_is_recorded_without_a_warning(client, caplog):
    import logging as _logging
    import time as _t
    from shengji.api import server as srv

    with caplog.at_level(_logging.WARNING):
        with client.websocket_connect("/ws") as a:
            code = _room_with_bots(a)
            a.send_json({"type": "start_game"})
            _drain(a, "state", tries=60)
            room = srv.rooms[code]
            room.deal_task.cancel()
            _t.sleep(0.3)
            assert room.task_exits.get("deal_task") == "cancelled"
            assert not any("deal_task" in r.message for r in caplog.records)
            # Frames already queued before the cancel still drain; read past
            # that backlog to the read that times out, which is the one that
            # carries the snapshot.
            message = None
            for _ in range(400):
                try:
                    _drain(a, "state", tries=1, timeout=1.0)
                except AssertionError as failure:
                    message = str(failure)
                    break
            assert message is not None, "frames kept arriving after the deal task was cancelled"
            assert "within 1.0s" in message
            assert "deal_task=cancelled" in message


def test_a_finished_game_start_records_the_deal_and_bot_tasks(client):
    """The real path, unmodified: once play begins, the deal task has RETURNED
    and the bot task exists, both recorded by the same callback."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a, to_play=True)
        assert room.deal_task.done()
        assert room.task_exits.get("deal_task") == "returned"
        assert room.bot_task is not None
        assert srv.rooms[code] is room


def test_negotiated_heartbeat_before_and_after_room_attach(client):
    from shengji.api import server as srv

    with client.websocket_connect("/ws?heartbeat=1") as ws:
        assert _drain(ws, "heartbeat_ready") == {"type": "heartbeat_ready"}
        ws.send_json({"type": "ping", "nonce": 1})
        assert _drain(ws, "pong") == {"type": "pong", "nonce": 1}
        assert not srv.rooms
        code = _room_with_bots(ws)
        ws.send_json({"type": "ping", "nonce": 2})
        assert _drain(ws, "pong") == {"type": "pong", "nonce": 2}
        seats = tuple(srv.rooms[code].seats)
        assert len(seats) == 4
        ws.send_json({"type": "ping", "nonce": 3})
        assert _drain(ws, "pong") == {"type": "pong", "nonce": 3}
        assert tuple(srv.rooms[code].seats) == seats
        assert srv.rooms[code].round is None


def test_heartbeat_ignores_invalid_nonce_without_breaking_next_request(client):
    with client.websocket_connect("/ws?heartbeat=1") as ws:
        _drain(ws, "heartbeat_ready")
        for nonce in (None, True, -1, "large", 9007199254740992):
            ws.send_json({"type": "ping", "nonce": nonce})
        ws.send_json({"type": "ping", "nonce": 7})
        assert _drain(ws, "pong") == {"type": "pong", "nonce": 7}


def _host_and_guest(client, a, b):
    """Host `jerry` at seat 0, guest `james` at seat 1, both in the lobby."""
    a.send_json({"type": "create_room", "name": "jerry"})
    code = _drain(a, "room")["room"]
    b.send_json({"type": "join_room", "room": code, "name": "james"})
    assert _drain(b, "room")["you"] == 1
    return code


def test_host_swaps_a_person_with_a_bot(client):
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        code = _host_and_guest(client, a, b)
        room = srv.rooms[code]
        a.send_json({"type": "add_bot"})
        _drain(b, "room")
        token = room.seats[1].token
        a.send_json({"type": "swap_seats", "a": 1, "b": 2})
        st = _drain(b, "room")
        while st["you"] != 2:
            st = _drain(b, "room")
        players = {p["seat"]: p for p in st["players"]}
        assert players[2]["name"] == "james" and not players[2]["is_bot"]
        assert players[1]["is_bot"]
        assert st["host"] == 0
        # The person moved, not just the label: the resume token and the
        # socket binding follow, so the guest now acts from seat 2.
        assert room.seats[2].token == token and room.seats[2].connected
        b.send_json({"type": "chat", "text": "hi"})
        msg = _drain(b, "chat")
        while msg.get("text") != "hi":
            msg = _drain(b, "chat")
        assert msg["seat"] == 2


def test_swap_moves_both_clients_and_the_host(client):
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        code = _host_and_guest(client, a, b)
        a.send_json({"type": "swap_seats", "a": 0, "b": 1})
        sa = _drain(a, "room")
        while sa["you"] != 1:
            sa = _drain(a, "room")
        sb = _drain(b, "room")
        while sb["you"] != 0:
            sb = _drain(b, "room")
        assert sa["host"] == 1 and sb["host"] == 1
        assert srv.rooms[code].host == 1
        # The host is still the host from its new seat.
        a.send_json({"type": "add_bot"})
        st = _drain(a, "room")
        while len(st["players"]) != 3:
            st = _drain(a, "room")
        b.send_json({"type": "add_bot"})
        assert _drain(b, "error")["message"] == "Cannot add a bot now."
        assert len(srv.rooms[code].seats) == 3


def _names(room):
    return [s.name if s is not None else None for s in room.seats]


def _room_until(ws, pred):
    st = _drain(ws, "room")
    while not pred(st):
        st = _drain(ws, "room")
    return st


def test_two_players_move_the_second_into_the_partner_seat(client):
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        code = _host_and_guest(client, a, b)
        a.send_json({"type": "swap_seats", "a": 1, "b": 2})
        st = _room_until(b, lambda m: m["you"] == 2)
        assert [p["seat"] for p in st["players"]] == [0, 2]
        assert _names(srv.rooms[code]) == ["jerry", None, "james"]
        # and back out to an end seat: the list keeps no trailing empties
        a.send_json({"type": "swap_seats", "a": 2, "b": 3})
        _room_until(b, lambda m: m["you"] == 3)
        assert _names(srv.rooms[code]) == ["jerry", None, None, "james"]
        a.send_json({"type": "swap_seats", "a": 3, "b": 1})
        _room_until(b, lambda m: m["you"] == 1)
        assert _names(srv.rooms[code]) == ["jerry", "james"]


def test_swapping_two_empty_seats_is_refused(client):
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        _host_and_guest(client, a, b)
        a.send_json({"type": "swap_seats", "a": 2, "b": 3})
        assert _drain(a, "error")["message"] == "Both seats are empty."


def test_join_fills_the_lowest_empty_seat(client):
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        code = _host_and_guest(client, a, b)
        a.send_json({"type": "swap_seats", "a": 1, "b": 3})
        _room_until(b, lambda m: m["you"] == 3)
        with client.websocket_connect("/ws") as c:
            c.send_json({"type": "join_room", "room": code, "name": "amy"})
            assert _drain(c, "room")["you"] == 1
            with client.websocket_connect("/ws") as d:
                d.send_json({"type": "join_room", "room": code, "name": "ben"})
                assert _drain(d, "room")["you"] == 2
        assert _names(srv.rooms[code])[:2] == ["jerry", "amy"]


def test_start_fills_gaps_with_bots_in_those_seats(client):
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        code = _host_and_guest(client, a, b)
        a.send_json({"type": "swap_seats", "a": 1, "b": 2})
        _room_until(b, lambda m: m["you"] == 2)
        a.send_json({"type": "start_game"})
        st = _drain(b, "state", tries=60)
        assert st["you"] == 2
        room = srv.rooms[code]
        assert len(room.seats) == 4 and all(s is not None for s in room.seats)
        assert [s.is_bot for s in room.seats] == [False, True, False, True]
        assert [s.name for s in room.seats] == ["jerry", "Bot 1", "james", "Bot 3"]


def test_resume_after_a_move_keeps_the_moved_seat(client):
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as a:
        with client.websocket_connect("/ws") as b:
            code = _host_and_guest(client, a, b)
            a.send_json({"type": "swap_seats", "a": 1, "b": 2})
            _room_until(b, lambda m: m["you"] == 2)
            token = srv.rooms[code].seats[2].token
        with client.websocket_connect("/ws") as again:
            again.send_json({"type": "join_room", "room": code, "name": "whoever", "token": token})
            assert _drain(again, "room")["you"] == 2
        assert _names(srv.rooms[code]) == ["jerry", None, "james"]


def test_a_room_with_a_gap_keeps_the_existing_payloads(client):
    """Clients that predate empty seats read players and room_seats by each
    entry's seat number; a gap is simply a seat with no entry, as an unfilled
    seat at the end always was."""
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        code = _host_and_guest(client, a, b)
        a.send_json({"type": "swap_seats", "a": 1, "b": 2})
        st = _room_until(a, lambda m: [p["seat"] for p in m["players"]] == [0, 2])
        assert set(st) >= {"type", "room", "you", "host", "start_level", "ready", "players"}
        assert all(set(p) == {"seat", "name", "is_bot", "connected"} for p in st["players"])
        with client.websocket_connect("/ws") as c:
            c.send_json({"type": "peek_room", "room": code})
            seats = _drain(c, "room_seats")["seats"]
        assert [(x["seat"], x["name"], x["team"]) for x in seats] == [(0, "jerry", 0), (2, "james", 0)]


def test_non_host_cannot_swap(client):
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        code = _host_and_guest(client, a, b)
        b.send_json({"type": "swap_seats", "a": 0, "b": 1})
        assert "host" in _drain(b, "error")["message"]
        assert [s.name for s in srv.rooms[code].seats] == ["jerry", "james"]


@pytest.mark.parametrize("bad", [{"a": 1, "b": 1}, {"a": 0, "b": 4},
                                 {"a": "0", "b": 1}, {"a": True, "b": 1}, {}])
def test_malformed_swap_is_refused(client, bad):
    with client.websocket_connect("/ws") as a:
        _room_with_bots(a)
        a.send_json({"type": "swap_seats", **bad})
        assert _drain(a, "error")["message"] == "Invalid seats."


def test_swap_after_start_is_refused(client):
    with client.websocket_connect("/ws") as a:
        _code, room = _start_game(client, a)
        names = [s.name for s in room.seats]
        a.send_json({"type": "swap_seats", "a": 0, "b": 1})
        assert "started" in _drain(a, "error", tries=200)["message"]
        assert [s.name for s in room.seats] == names


def _host_guest_and_third(client, a, b, c):
    """Host at seat 0, `james` at 1, `amy` at 2, all in the lobby."""
    code = _host_and_guest(client, a, b)
    c.send_json({"type": "join_room", "room": code, "name": "amy"})
    assert _drain(c, "room")["you"] == 2
    return code


def test_host_removes_a_guest(client):
    from shengji.api import server as srv
    with (client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b,
          client.websocket_connect("/ws") as c):
        code = _host_guest_and_third(client, a, b, c)
        room = srv.rooms[code]
        token = room.seats[1].token
        a.send_json({"type": "remove_player", "seat": 1})
        left = _drain(b, "left")
        assert left["reason"] == "removed" and "removed" in left["message"]
        # the middle seat empties; amy does not shift
        assert _names(room) == ["jerry", None, "amy"]
        assert room.host == 0
        st = _room_until(c, lambda m: len(m["players"]) == 2)
        assert st["you"] == 2
        # The removed socket is back in the lobby: a room action is refused
        # as from a lobby socket, not applied to the room.
        b.send_json({"type": "add_bot"})
        assert _drain(b, "error")["message"] == "Join a room first."
        assert _names(room) == ["jerry", None, "amy"]
        # Its old token reclaims nothing: a join with it is a new arrival.
        with client.websocket_connect("/ws") as again:
            again.send_json({"type": "join_room", "room": code, "name": "james", "token": token})
            st = _drain(again, "room")
            assert st["you"] == 1
            assert room.seats[1].token != token
        assert all(s.token != token for s in room.seats)


def test_host_removes_a_signed_in_player(client):
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        code = _host_and_guest(client, a, b)
        room = srv.rooms[code]
        room.seats[1].user_id = 4242
        a.send_json({"type": "remove_player", "seat": 1})
        assert _drain(b, "left")["reason"] == "removed"
        assert [s.user_id if s else "empty" for s in room.seats] == [None]


def test_removing_a_seat_beside_the_host_keeps_the_host(client):
    from shengji.api import server as srv
    with (client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b,
          client.websocket_connect("/ws") as c):
        code = _host_guest_and_third(client, a, b, c)
        room = srv.rooms[code]
        a.send_json({"type": "swap_seats", "a": 0, "b": 2})
        st = _drain(a, "room")
        while st["you"] != 2:
            st = _drain(a, "room")
        a.send_json({"type": "remove_player", "seat": 1})
        _drain(b, "left")
        st = _room_until(a, lambda m: len(m["players"]) == 2)
        assert st["you"] == st["host"] == 2
        assert _names(room) == ["amy", None, "jerry"]


def test_non_host_cannot_remove(client):
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        code = _host_and_guest(client, a, b)
        b.send_json({"type": "remove_player", "seat": 0})
        assert "host" in _drain(b, "error")["message"]
        assert [s.name for s in srv.rooms[code].seats] == ["jerry", "james"]


@pytest.mark.parametrize("bad", [0, 2, -1, "1", True, None])
def test_bad_remove_is_refused(client, bad):
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        code = _host_and_guest(client, a, b)
        a.send_json({"type": "remove_player", "seat": bad})
        _drain(a, "error")
        assert [s.name for s in srv.rooms[code].seats] == ["jerry", "james"]


def test_remove_after_start_is_refused(client):
    with client.websocket_connect("/ws") as a:
        _code, room = _start_game(client, a)
        names = [s.name for s in room.seats]
        a.send_json({"type": "remove_player", "seat": 1})
        assert "started" in _drain(a, "error", tries=200)["message"]
        assert [s.name for s in room.seats] == names


def test_start_fills_empty_seats_with_bots(client):
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        code = _host_and_guest(client, a, b)
        a.send_json({"type": "start_game"})
        st = _drain(b, "state", tries=60)
        assert st["you"] == 1
        room = srv.rooms[code]
        assert [s.is_bot for s in room.seats] == [False, False, True, True]
        assert room.game is not None


def test_a_lobby_leave_empties_the_seat_without_shifting(client):
    from shengji.api import server as srv
    with (client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b,
          client.websocket_connect("/ws") as c):
        code = _host_guest_and_third(client, a, b, c)
        room = srv.rooms[code]
        b.send_json({"type": "leave_room"})
        _drain(b, "left")
        st = _room_until(c, lambda m: len(m["players"]) == 2)
        assert st["you"] == 2 and st["host"] == 0
        assert _names(room) == ["jerry", None, "amy"]
        # the host leaving hands the room to the first person left
        a.send_json({"type": "leave_room"})
        _drain(a, "left")
        st = _room_until(c, lambda m: len(m["players"]) == 1)
        assert st["you"] == st["host"] == 2
        assert _names(room) == [None, None, "amy"]
        c.send_json({"type": "add_bot"})
        st = _room_until(c, lambda m: len(m["players"]) == 2)
        assert [p["seat"] for p in st["players"]] == [0, 2]


def _who(seat):
    return {"name": seat.name, "is_bot": seat.is_bot}


def test_remove_with_the_expected_occupant_applies(client):
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        code = _host_and_guest(client, a, b)
        room = srv.rooms[code]
        a.send_json({"type": "remove_player", "seat": 1, "expect": _who(room.seats[1])})
        assert _drain(b, "left")["reason"] == "removed"
        assert _names(room) == ["jerry"]


def test_remove_of_a_replaced_occupant_is_refused(client):
    """The host's menu was opened on james; james left and amy sat down in
    the same seat before the Remove arrived. Amy stays."""
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as a:
        with client.websocket_connect("/ws") as b:
            code = _host_and_guest(client, a, b)
            room = srv.rooms[code]
            meant = _who(room.seats[1])
            b.send_json({"type": "leave_room"})
            _drain(b, "left")
        with client.websocket_connect("/ws") as c:
            c.send_json({"type": "join_room", "room": code, "name": "amy"})
            assert _drain(c, "room")["you"] == 1
            a.send_json({"type": "remove_player", "seat": 1, "expect": meant})
            err = _drain(a, "error")
            assert err["code"] == "seat_changed"
            assert _names(room) == ["jerry", "amy"]


def test_remove_of_a_seat_that_emptied_is_refused(client):
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as a:
        with client.websocket_connect("/ws") as b:
            code = _host_and_guest(client, a, b)
            meant = _who(srv.rooms[code].seats[1])
            b.send_json({"type": "leave_room"})
            _drain(b, "left")
        a.send_json({"type": "remove_player", "seat": 1, "expect": meant})
        assert _drain(a, "error")["message"] == "Invalid seat."
        assert _names(srv.rooms[code]) == ["jerry"]


def test_swap_with_the_expected_occupants_applies(client):
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        code = _host_and_guest(client, a, b)
        room = srv.rooms[code]
        a.send_json({"type": "swap_seats", "a": 1, "b": 2,
                     "expect": [_who(room.seats[1]), None]})
        _room_until(b, lambda m: m["you"] == 2)
        assert _names(room) == ["jerry", None, "james"]


@pytest.mark.parametrize("stale", ["occupant", "empty", "malformed"])
def test_swap_against_a_changed_seat_is_refused(client, stale):
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        code = _host_and_guest(client, a, b)
        room = srv.rooms[code]
        if stale == "occupant":
            expect, target = [{"name": "amy", "is_bot": False}, None], 2
        elif stale == "empty":
            expect, target = [_who(room.seats[1]), None], 0   # seat 0 was believed empty
        else:
            expect, target = "james", 2
        a.send_json({"type": "swap_seats", "a": 1, "b": target, "expect": expect})
        err = _drain(a, "error")
        assert err.get("code") == ("seat_changed" if stale != "malformed" else None)
        assert _names(room) == ["jerry", "james"]


# ------------------------------------------------------------- move timer
# A room with ``move_timer`` on (ranked rooms) gives a present player
# MOVE_TIMER seconds per decision; ticks run on the server's own loop through
# the TestClient portal so the bot pump it kicks keeps playing.
def _wait_for(pred, timeout=15.0):
    import time

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return
        time.sleep(0.01)
    raise AssertionError(f"condition never held; server: {_server_snapshot()}")


def _timer_game(client, a, monkeypatch, on=True):
    """Seat 0 human, three bots, in the play phase, waiting on seat 0."""
    from shengji.api import server as srv

    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    code, room = _start_game(client, a, to_play=True)
    room.move_timer = on
    _wait_for(lambda: _my_turn(room))
    # The turn passes to seat 0 inside the pump's commit; the pump is idle
    # only once its task ends, and a test may then set seat state directly.
    _wait_for(lambda: room.bot_task is None or room.bot_task.done())

    # A real room has the flag from creation; here it was set mid-round, so
    # send one state that reflects it (the pump's last one may predate it).
    async def _broadcast():
        async with room.lock:
            await srv.broadcast(room)

    client.portal.call(_broadcast)
    return code, room


def _state_until(ws, pred, tries=400):
    """The first state frame that satisfies ``pred`` (older frames queue up)."""
    for _ in range(tries):
        state = _drain(ws, "state", tries=400)
        if pred(state):
            return state
    raise AssertionError(f"no matching state; server: {_server_snapshot()}")


def _my_turn(room, seat=0):
    rnd = room.round
    return rnd is not None and rnd.phase == "play" and rnd.turn == seat


def _tick(client, room):
    from shengji.api import server as srv

    return client.portal.call(srv.move_timer_tick, room)


def _real_play(client, a, room, seat=0):
    """Send a legal play for ``seat`` through the socket, as the player would,
    and return once the server has finished handling it."""
    import copy

    codes = copy.deepcopy(room.bot).decide_play(copy.deepcopy(room.round), seat)
    before = _plays_by(room, seat)
    a.send_json({"type": "play", "card_ids": room.ids_for_codes(seat, codes)})
    _wait_for(lambda: _plays_by(room, seat) == before + 1)
    # The card lands mid-handler; the handler's bookkeeping after it (such as
    # clearing away) is done once it releases the room lock.
    _settled(client, room)


def _settled(client, room):
    async def _acquire():
        async with room.lock:
            pass

    client.portal.call(_acquire)


def _time_out_once(client, room, clock, seat=0):
    from shengji.api import server as srv

    before = _plays_by(room, seat)
    clock["v"] += srv.MOVE_TIMER + 1
    assert _tick(client, room)
    assert _plays_by(room, seat) == before + 1


def test_move_timer_bot_plays_one_move_at_zero(client, clock, monkeypatch):
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        _, room = _timer_game(client, a, monkeypatch)
        before = _plays_by(room, 0)
        assert _tick(client, room) is False          # starts the clock
        clock["v"] += srv.MOVE_TIMER - 1
        assert _tick(client, room) is False
        assert _plays_by(room, 0) == before and room.round.turn == 0
        state = _state_until(a, lambda m: m["players"][0].get("turn_deadline") is not None)
        assert state["players"][0]["away"] is False
        assert all(p["turn_deadline"] is None for p in state["players"][1:])
        clock["v"] += 2
        assert _tick(client, room) is True
        assert _plays_by(room, 0) == before + 1
        seat = room.seats[0]
        assert (seat.timeouts_in_row, seat.timeouts_in_round, seat.away) == (1, 1, False)
        # the bot decided once: seat 0 waits again on its next turn
        _wait_for(lambda: _my_turn(room))
        assert _plays_by(room, 0) == before + 1


def test_two_timeouts_in_a_row_mark_the_seat_away(client, clock, monkeypatch):
    with client.websocket_connect("/ws") as a:
        _, room = _timer_game(client, a, monkeypatch)
        _tick(client, room)
        _time_out_once(client, room, clock)
        _wait_for(lambda: _my_turn(room))
        _tick(client, room)
        _time_out_once(client, room, clock)
        assert room.seats[0].away
        # away: the bot plays seat 0's next turn with no clock running out
        before = _plays_by(room, 0)
        _wait_for(lambda: _plays_by(room, 0) > before)
        state = _state_until(a, lambda m: m["players"][0].get("away"))
        assert state["players"][0]["turn_deadline"] is None


def test_three_timeouts_in_one_round_mark_the_seat_away(client, clock, monkeypatch):
    with client.websocket_connect("/ws") as a:
        _, room = _timer_game(client, a, monkeypatch)
        for n in range(3):
            _tick(client, room)
            _time_out_once(client, room, clock)
            if n < 2:
                assert not room.seats[0].away
                _wait_for(lambda: _my_turn(room))
                _real_play(client, a, room)                   # breaks the run
                assert room.seats[0].timeouts_in_row == 0
                _wait_for(lambda: _my_turn(room))
        assert room.seats[0].timeouts_in_round == 3
        assert room.seats[0].away


def test_im_back_and_a_real_move_clear_away(client, clock, monkeypatch):
    with client.websocket_connect("/ws") as a:
        _, room = _timer_game(client, a, monkeypatch)
        seat = room.seats[0]
        # on seat 0's turn with the pump idle: away takes effect from here
        seat.away, seat.timeouts_in_row = True, 2
        a.send_json({"type": "im_back"})
        _wait_for(lambda: not seat.away)
        assert seat.timeouts_in_row == 0
        state = _state_until(a, lambda m: m["players"][0].get("turn_deadline") is not None)
        assert state["players"][0]["away"] is False
        seat.away, seat.timeouts_in_row = True, 2
        _real_play(client, a, room)
        assert not seat.away and seat.timeouts_in_row == 0


def test_round_end_next_is_readied_after_the_move_timer(client, clock, monkeypatch):
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        _, room = _timer_game(client, a, monkeypatch)
        round_no = room.game.round_no
        # let the bot play seat 0 out to the round end
        room.seats[0].away = True
        client.portal.call(srv.kick_bots, room)
        _wait_for(lambda: room.round.phase == "round_end")
        a.send_json({"type": "im_back"})
        _wait_for(lambda: not room.seats[0].away)
        assert _tick(client, room) is False
        clock["v"] += srv.MOVE_TIMER - 1
        assert _tick(client, room) is False
        assert room.game.round_no == round_no
        clock["v"] += 2
        assert _tick(client, room) is True
        assert room.game.round_no == round_no + 1, "Next was never auto-readied"
        assert room.seats[0].timeouts_in_row == 1
        assert room.seats[0].timeouts_in_round == 0      # a new round began


def test_an_away_seat_is_readied_at_round_end_without_waiting(client, clock, monkeypatch):
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        _, room = _timer_game(client, a, monkeypatch)
        round_no = room.game.round_no
        room.seats[0].away = True
        client.portal.call(srv.kick_bots, room)
        _wait_for(lambda: room.round.phase == "round_end")
        assert _tick(client, room) is True
        assert room.game.round_no == round_no + 1
        assert room.seats[0].away


def test_a_casual_room_has_no_move_timer(client, clock, monkeypatch):
    with client.websocket_connect("/ws") as a:
        _, room = _timer_game(client, a, monkeypatch, on=False)
        before = _plays_by(room, 0)
        _tick(client, room)
        clock["v"] += 600
        assert _tick(client, room) is False
        assert _plays_by(room, 0) == before and room.round.turn == 0
        state = _drain(a, "state", tries=200)
        assert all("turn_deadline" not in p and "away" not in p
                   for p in state["players"])
        assert room.seats[0].turn_started is None


def test_a_disconnected_turn_uses_takeover_and_is_not_a_timeout(client, clock, monkeypatch):
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as b:
        with client.websocket_connect("/ws") as a:
            code, room = _timer_game(client, a, monkeypatch)
            _tick(client, room)
            # a second human keeps the room alive once seat 0 drops
            b.send_json({"type": "join_room", "room": code, "name": "bee", "seat": 1})
            _drain(b, "state", tries=200)
        _wait_for(lambda: not room.seats[0].connected)
        before = _plays_by(room, 0)
        clock["v"] += srv.MOVE_TIMER + 1
        assert _tick(client, room) is False, "the move timer acted for a disconnected seat"
        assert client.portal.call(srv.watchdog_tick, room) is True
        assert _plays_by(room, 0) == before + 1
        seat = room.seats[0]
        assert (seat.timeouts_in_row, seat.timeouts_in_round, seat.away) == (0, 0, False)


def test_review_final_timeout_marks_away_before_rating_capture(client, clock, monkeypatch):
    from shengji.api import server as srv
    captured = []
    monkeypatch.setattr(srv.ratings, 'round_ended', lambda room, result: captured.append([s.away for s in room.seats]))
    with client.websocket_connect('/ws') as a:
        _, room = _timer_game(client, a, monkeypatch)
        async def prepare():
            async with room.lock:
                for _ in range(200):
                    if sum(len(h) for h in room.round.hands) == 1:
                        break
                    assert srv.bot_step(room, room.round.turn)
                assert sum(len(h) for h in room.round.hands) == 1
                actor = room.round.turn
                seat = room.seats[actor]
                seat.is_bot = False
                seat.connected = True
                seat.timeouts_in_row = 1
                seat.timeouts_in_round = 1
                srv._sync_move_timer(room)
                return actor
        actor = client.portal.call(prepare)
        clock['v'] += srv.MOVE_TIMER + 1
        assert _tick(client, room)
        assert room.seats[actor].away
        assert captured[-1][actor], 'rating captured before final timeout marked away'


# ------------------------------------------------- a room every human has left
def _room_tasks_done(room):
    return all(task is None or task.done()
               for task in (room.bot_task, room.deal_task,
                            room.watchdog_task, room.cleanup_task))


def _banker_leads(client, a, monkeypatch, bot_delay):
    """Seat 0 human banker (nobody declares), on lead in the play phase."""
    from shengji.ai.heuristic import HeuristicBot
    from shengji.api import server as srv

    monkeypatch.setattr(HeuristicBot, "decide_declare", lambda *a, **kw: None)
    monkeypatch.setattr(srv, "BOT_DELAY", bot_delay)
    code, room = _start_game(client, a, to_play=True)
    _wait_for(lambda: _my_turn(room))
    return code, room


def _play_times(room):
    """Wall-clock time of every committed play from now on."""
    import time

    times = []
    original = room.log_event

    def log_event(kind, **data):
        if kind == "play":
            times.append(time.monotonic())
        return original(kind, **data)

    room.log_event = log_event
    return times


def test_the_last_humans_leaving_mid_game_close_the_room_at_once(client):
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a, to_play=True)
        with client.websocket_connect("/ws") as b:
            want = next(i for i, sd in enumerate(room.seats) if sd.is_bot)
            b.send_json({"type": "join_room", "room": code, "name": "james", "seat": want})
            _drain(b, "state", tries=60)
            b.send_json({"type": "leave_room"})
            _drain(b, "left", tries=200)
            assert srv.rooms.get(code) is room, "one human is still playing"
            a.send_json({"type": "leave_room"})
            _drain(a, "left", tries=200)
            assert code not in srv.rooms
            assert not room.closing           # nothing rated: no round to finish
            _wait_for(lambda: _room_tasks_done(room))


def test_an_empty_room_plays_slowly_through_the_grace_then_closes(client, monkeypatch):
    import time

    from shengji.api import server as srv

    monkeypatch.setattr(srv, "EMPTY_ROOM_BOT_DELAY", 0.6)
    monkeypatch.setattr(srv, "EMPTY_ROOM_POLL", 0.05)
    monkeypatch.setattr(srv, "ROOM_TTL", 2.5)
    a = client.websocket_connect("/ws").__enter__()
    try:
        code, room = _banker_leads(client, a, monkeypatch, bot_delay=0.3)
        times = _play_times(room)
        _real_play(client, a, room)
    finally:
        a.__exit__(None, None, None)
    gone = time.monotonic()
    _wait_for(lambda: not room.seats[0].connected)
    _wait_for(lambda: code not in srv.rooms, timeout=10)
    later = [t for t in times[1:] if t > gone]
    assert len(later) >= 2, "the bots stopped instead of playing slowly"
    steps = [b - a for a, b in zip(later, later[1:])]
    assert min(steps) >= 0.6 * 0.95, f"a bot moved faster than the empty-room pace: {steps}"
    assert len(later) <= 2.5 / 0.6 + 1
    _wait_for(lambda: _room_tasks_done(room))


def test_a_human_back_in_the_grace_restores_the_normal_pace(client, monkeypatch):
    import time

    from shengji.api import server as srv

    monkeypatch.setattr(srv, "EMPTY_ROOM_BOT_DELAY", 5.0)
    monkeypatch.setattr(srv, "EMPTY_ROOM_POLL", 0.05)
    monkeypatch.setattr(srv, "ROOM_TTL", 30.0)
    a = client.websocket_connect("/ws").__enter__()
    try:
        code, room = _banker_leads(client, a, monkeypatch, bot_delay=0.1)
        _real_play(client, a, room)
    finally:
        a.__exit__(None, None, None)
    _wait_for(lambda: not room.seats[0].connected)
    time.sleep(0.6)
    assert len(room.round.trick.plays) == 1, "a bot moved at the normal pace in an empty room"
    with client.websocket_connect("/ws") as back:
        back.send_json({"type": "join_room", "room": code, "name": "jerry"})
        _drain(back, "state", tries=60)
        assert room.seats[0].connected and srv.rooms.get(code) is room
        started = time.monotonic()
        _wait_for(lambda: len(room.round.history) >= 1, timeout=4.0)
        assert time.monotonic() - started < 4.0
        assert room.cleanup_task is None or room.cleanup_task.cancelled()


def test_one_of_two_humans_leaving_leaves_the_game_running(client):
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a, to_play=True)
        with client.websocket_connect("/ws") as b:
            want = next(i for i, sd in enumerate(room.seats) if sd.is_bot)
            b.send_json({"type": "join_room", "room": code, "name": "james", "seat": want})
            _drain(b, "state", tries=60)
            b.send_json({"type": "leave_room"})
            _drain(b, "left", tries=200)
        assert srv.rooms.get(code) is room and not room.closing
        assert room.cleanup_task is None
        left = room.seats[want]
        assert not left.is_bot and not left.connected and left.name == "james"
        assert not srv._unwatched(room)
        assert srv._auto_mode(room, want) is None   # the takeover covers it


def test_only_the_served_pace_slows_an_empty_room(monkeypatch):
    """A caller's explicit minimum (tests and harnesses pass 0) is never
    stretched by the empty-room wait; only the served default is."""
    import asyncio
    import time
    from types import SimpleNamespace

    from shengji.api import server as srv

    async def compute(snapshot):
        return "decision"

    monkeypatch.setattr(srv, "_snapshot_bot_turn",
                        lambda room, seat, mode: SimpleNamespace(bot_copy=None, phase="play"))
    monkeypatch.setattr(srv, "_compute_bot_turn_off_loop", compute)
    monkeypatch.setattr(srv, "_unwatched", lambda room: True)
    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    monkeypatch.setattr(srv, "EMPTY_ROOM_POLL", 0.02)

    async def step(**kw):
        room = SimpleNamespace(lock=asyncio.Lock())
        started = time.perf_counter()
        prepared = await srv._paced_bot_step(room, 1, **kw)
        return prepared, time.perf_counter() - started

    monkeypatch.setattr(srv, "EMPTY_ROOM_BOT_DELAY", 30.0)
    prepared, took = asyncio.run(step(minimum_turn_seconds=0))
    assert prepared.decision == "decision" and took < 1.0
    monkeypatch.setattr(srv, "EMPTY_ROOM_BOT_DELAY", 0.3)
    prepared, took = asyncio.run(step())
    assert took >= 0.3 * 0.95 and prepared.pacing_seconds > 0


def test_a_covered_seat_moves_at_the_bot_pace_without_the_watchdog(client, monkeypatch):
    """One connected human and one absent human the bot already covers: the
    covered seat is driven by the bot pump, not the watchdog's 5 s tick (the
    fixture stubs the watchdog, so only the pump can move it)."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _banker_leads(client, a, monkeypatch, bot_delay=0.05)
        _wait_for(lambda: room.bot_task is None or room.bot_task.done())

        async def cover_seat_1():
            async with room.lock:
                sd = room.seats[1]
                sd.is_bot, sd.name, sd.connected = False, "james", False
                sd.left_at = srv.now() - srv.TAKEOVER_AFTER - 1
                sd.bot_announced = True

        client.portal.call(cover_seat_1)
        _real_play(client, a, room)
        _wait_for(lambda: _plays_by(room, 1) == 1, timeout=3.0)
        _wait_for(lambda: _my_turn(room) or room.round.phase != "play", timeout=3.0)
        assert srv.rooms.get(code) is room and not room.closing


def test_an_absence_inside_the_takeover_window_is_not_covered_by_the_pump(client, monkeypatch):
    import time

    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        _, room = _banker_leads(client, a, monkeypatch, bot_delay=0.05)
        _wait_for(lambda: room.bot_task is None or room.bot_task.done())

        async def drop_seat_1():
            async with room.lock:
                sd = room.seats[1]
                sd.is_bot, sd.name, sd.connected = False, "james", False
                sd.left_at = srv.now()
                sd.bot_announced = True     # even so, the 30 s window holds

        client.portal.call(drop_seat_1)
        _real_play(client, a, room)
        _wait_for(lambda: _my_turn(room, 1))
        time.sleep(0.3)
        assert _plays_by(room, 1) == 0 and srv._auto_mode(room, 1) is None


def test_ranked_switches_the_move_timer_on_and_back(client):
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        room = srv.rooms[code]
        _drain(a, "room", tries=60)
        assert room.move_timer is False
        a.send_json({"type": "set_ranked", "on": True})
        _wait_for(lambda: room.ranked)
        assert room.move_timer is True
        a.send_json({"type": "set_ranked", "on": True})     # a repeat keeps the saved setting
        a.send_json({"type": "set_ranked", "on": False})
        _wait_for(lambda: not room.ranked)
        assert room.move_timer is False
        room.move_timer = True                              # a room whose own setting is on
        a.send_json({"type": "set_ranked", "on": True})
        _wait_for(lambda: room.ranked)
        a.send_json({"type": "set_ranked", "on": False})
        _wait_for(lambda: not room.ranked)
        assert room.move_timer is True
        a.send_json({"type": "set_ranked", "on": True})
        _wait_for(lambda: room.ranked)
        a.send_json({"type": "start_game"})
        _drain(a, "state", tries=60)
        assert room.move_timer is True and room.watchdog_task is not None


def test_a_refused_human_play_is_logged_with_its_cards(client, monkeypatch):
    import json

    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _banker_leads(client, a, monkeypatch, bot_delay=0.05)
        _wait_for(lambda: room.bot_task is None or room.bot_task.done())
        a.send_json({"type": "next_round"})                  # not a play: not logged
        _drain(a, "error", tries=60)
        _real_play(client, a, room)                          # seat 0 led; now off turn
        ids = sorted(room.ids[0])[:1]
        codes = [room.ids[0][i] for i in ids]
        a.send_json({"type": "play", "card_ids": ids})
        error = _drain(a, "error", tries=200)
        records = [json.loads(line) for line in
                   (srv.LOG_DIR / f"{code}.jsonl").read_text().splitlines()]
        refused = [r for r in records if r["e"] == "play_refused"]
        assert len(refused) == 1
        [rec] = refused
        assert rec["seat"] == 0 and rec["attempted_cards"] == codes
        assert rec["reason"] == error["message"] and rec["code"] == "IllegalPlay"
        assert rec["phase"] == "play" and rec["round"] == 1


def test_seat_presence_and_ranked_are_in_the_room_log(client):
    import json

    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a)
        want = next(i for i, sd in enumerate(room.seats) if sd.is_bot)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "join_room", "room": code, "name": "james", "seat": want})
            _drain(b, "state", tries=60)
        _wait_for(lambda: not room.seats[want].connected)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "join_room", "room": code, "name": "james"})
            _drain(b, "state", tries=60)
            assert room.seats[want].connected
            b.send_json({"type": "leave_room"})
            _drain(b, "left", tries=200)
        records = [json.loads(line) for line in
                   (srv.LOG_DIR / f"{code}.jsonl").read_text().splitlines()]
        [start] = [r for r in records if r["e"] == "round_start"]
        assert start["ranked"] is False
        seat_events = [(r["e"], r["seat"], r["reason"]) for r in records
                       if r["e"].startswith("seat_") and r["e"] != "seat_claimed"]
        assert seat_events == [("seat_disconnected", want, "socket_closed"),
                               ("seat_reconnected", want, "name"),
                               ("seat_left", want, "leave")]
        assert all(r["round"] == 1 for r in records if r["e"].startswith("seat_"))


def test_a_displaced_socket_closing_logs_no_disconnect(client):
    """A second tab resuming the seat is a reconnect; the first tab's socket
    then closing is not a disconnect of the seat, which is still connected."""
    import json
    import time

    from shengji.api import server as srv

    a = client.websocket_connect("/ws").__enter__()
    try:
        code, room = _start_game(client, a)
        token = room.seats[0].token
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "join_room", "room": code, "name": "jerry", "token": token})
            _drain(b, "state", tries=60)
            a.__exit__(None, None, None)
            a = None
            time.sleep(0.3)                 # the server handles the close
            _settled(client, room)
            assert room.seats[0].connected
            records = [json.loads(line) for line in
                       (srv.LOG_DIR / f"{code}.jsonl").read_text().splitlines()]
            assert [(r["e"], r["reason"]) for r in records
                    if r["e"] in ("seat_disconnected", "seat_reconnected")] == [
                ("seat_reconnected", "token")]
        _wait_for(lambda: not room.seats[0].connected)
        records = [json.loads(line) for line in
                   (srv.LOG_DIR / f"{code}.jsonl").read_text().splitlines()]
        assert [r["e"] for r in records if r["e"] == "seat_disconnected"] == ["seat_disconnected"]
    finally:
        if a is not None:
            a.__exit__(None, None, None)

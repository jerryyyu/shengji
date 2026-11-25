"""Websocket-level tests for the multiplayer room protocol.

These drive the REAL socket via TestClient rather than calling handlers
directly: `peek_room` shipped completely unimplemented on the server while
the client sent it and the suite stayed green, because nothing here spoke
the wire protocol (2026-08-03).
"""
from __future__ import annotations

import json
import os
import random
import threading
from contextlib import ExitStack
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("SHENGJI_BOT", "heuristic")  # fast; these tests are protocol-level


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_LOG_DIR", str(tmp_path / "logs"))
    from shengji.api import server as srv

    srv.LOG_DIR = tmp_path / "logs"
    # A real deal is ~20s of DEAL_DELAY; these tests care about the protocol,
    # not the pacing. BOT_DELAY is left alone — one test needs a bot turn to
    # still be PENDING when a human claims that seat.
    monkeypatch.setattr(srv, "DEAL_DELAY", 0.0)
    monkeypatch.setattr(srv, "DECLARE_GRACE", 0.05)
    monkeypatch.setattr(srv, "DECLARE_EXTEND", 0.05)
    srv.rooms.clear()
    # peeks draw on the process-wide code-read limit; each test starts fresh
    srv.MATCHMAKER.lookup_limiter.reset()
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


# How long a read waits for the frame it wants. Bounded by time only: a deal
# streams one state frame per dealt card, so a frame count is no bound on how
# far away the wanted frame is.
DRAIN_TIMEOUT = 20.0


def _reader():
    from concurrent.futures import ThreadPoolExecutor

    global _READER
    if _READER is None:
        _READER = ThreadPoolExecutor(max_workers=32,
                                     thread_name_prefix="ws-drain")
    return _READER


def _recv(ws, timeout=DRAIN_TIMEOUT):
    """The next frame, or None when none arrives within ``timeout`` seconds.

    Each read is bounded: a bare receive_json() blocks forever when the server
    sends fewer messages than expected, which turns a behaviour change into a
    hung suite instead of a failure."""
    from concurrent.futures import TimeoutError as _TO

    fut = _reader().submit(ws.receive_json)
    try:
        return fut.result(timeout=max(timeout, 0.0))
    except _TO:
        # Do NOT wait for the blocked reader: joining it is what turned a
        # bounded read back into a hang.
        return None


def _frames_until(ws, stop, what, timeout=DRAIN_TIMEOUT):
    """Frames up to and including the first for which ``stop(frame)`` holds,
    read until ``timeout`` seconds have passed."""
    import time as _time

    deadline = _time.monotonic() + timeout
    seen = []
    while True:
        m = _recv(ws, deadline - _time.monotonic())
        if m is None:
            raise AssertionError(
                f"no {what} within {timeout}s; saw {[f.get('type') for f in seen]}; "
                f"server: {_server_snapshot()}")
        seen.append(m)
        if stop(m):
            return seen


def _drain(ws, want, timeout=DRAIN_TIMEOUT):
    """Next message of type `want` (states/chat interleave freely)."""
    return _frames_until(ws, lambda m: m.get("type") == want, repr(want), timeout)[-1]


def _next(ws, want, timeout=5.0):
    """The very next message, which must be of type ``want``."""
    m = _recv(ws, timeout)
    if m is None:
        raise AssertionError(f"no frame within {timeout}s; wanted {want!r}; "
                             f"server: {_server_snapshot()}")
    assert m.get("type") == want, f"next frame is {m.get('type')!r}, not {want!r}: {m}"
    return m


def _next_where(ws, kind, pred, timeout=DRAIN_TIMEOUT):
    """The first message of ``kind`` that satisfies ``pred``."""
    return _frames_until(ws, lambda m: m.get("type") == kind and pred(m),
                         f"matching {kind!r}", timeout)[-1]


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


def _created_room(ws, name="jerry", **fields):
    """``create_room``, which starts the game at once with a bot in each
    other seat: the one room frame, then the game's first state frame."""
    ws.send_json({"type": "create_room", "name": name, **fields})
    room = _drain(ws, "room")
    return room, _drain(ws, "state")


def _room_with_bots(ws, name="jerry"):
    """A created room's code, its game running with bots in seats 1-3."""
    return _created_room(ws, name)[0]["room"]


def test_peek_room_reports_seats_without_joining(client):
    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "table_peek", "code": code})
            m = _drain(b, "room_seats")

    assert m["room"] == code
    assert len(m["seats"]) == 4
    assert [s["team"] for s in m["seats"]] == [0, 1, 0, 1]
    assert m["seats"][0]["name"] == "jerry" and not m["seats"][0]["is_bot"]
    assert all(s["is_bot"] for s in m["seats"][1:])
    # Peeking must NOT seat the peeker.
    from shengji.api import server as srv
    assert len(srv.rooms[code].seats) == 4


def test_a_room_peek_frame_is_unchanged_in_play(client):
    """The exact bytes of a room code's ``room_seats`` while its game runs: a
    table code's peek adds fields only to its own frame."""
    import json

    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        code = _room_with_bots(a)
        b.send_json({"type": "table_peek", "code": code.lower()})
        play = json.dumps(_drain(b, "room_seats"))

    def seat(i, name, bot):
        return {"seat": i, "name": name, "is_bot": bot, "connected": not bot, "team": i % 2,
                "claimable": bot, "reserved_secs": None,
                "controller": "bot" if bot else "human"}
    assert play == json.dumps({"type": "room_seats", "room": code, "in_game": True,
                               "seats": [seat(0, "jerry", False), seat(1, "Bot 1", True),
                                         seat(2, "Bot 2", True), seat(3, "Bot 3", True)]})


def test_peek_unknown_room_errors(client):
    with client.websocket_connect("/ws") as a:
        a.send_json({"type": "table_peek", "code": "ZZZZ"})
        m = _drain(a, "error")
    assert m["code"] == "room_not_found"


def test_peek_then_join_chosen_seat(client):
    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "table_peek", "code": code})
            seats = _drain(b, "room_seats")["seats"]
            want = [s["seat"] for s in seats if s["is_bot"]][-1]
            b.send_json({"type": "table_join", "expect": "room", "code": code,
                         "name": "james", "seat": want})
            st = _drain(b, "state")
            assert st["you"] == want
            mine = next(p for p in st["players"] if p["seat"] == want)
            assert mine["name"] == "james" and not mine["is_bot"]


def test_ready_ignores_disconnected_humans(client):
    """A player who drops at round end must stop being waited on."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "james"})
            _drain(b, "state")
            room = srv.rooms[code]
            humans = [i for i, s in enumerate(room.seats) if not s.is_bot]
            assert len(humans) == 2
            room.ready.add(humans[0])
            assert srv.pending_ready(room) == {humans[1]}
            room.ready.add(humans[1])
        # b's socket is closed here: it is no longer waited on, and its own
        # confirmation is kept for a return within READY_KEEP_SECONDS.
        room = srv.rooms[code]
        _wait_for(lambda: not room.seats[humans[1]].connected)
        assert srv.pending_ready(room) == set()
        assert humans[1] in room.ready


def test_state_carries_ready_tally(client):
    """In-game broadcasts must include `ready` — the client renders it."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        room_frame, st = _created_room(a)
        code = room_frame["room"]
        assert "ready" in st, "round-end tally missing from in-game state"
        srv.rooms[code].ready.add(0)
        assert "ready" in srv.state_for(srv.rooms[code], 0)
        assert srv.state_for(srv.rooms[code], 0)["ready"] == [0]


def test_seat_claim_chat_names_the_bot(client):
    """"took Bot 1's seat" — which seat, not just "a bot's seat"."""
    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "table_peek", "code": code})
            seats = _drain(b, "room_seats")["seats"]
            want = [s["seat"] for s in seats if s["is_bot"]][-1]
            botname = next(s["name"] for s in seats if s["seat"] == want)
            b.send_json({"type": "table_join", "expect": "room", "code": code,
                         "name": "jerry mbp", "seat": want})
            line = _drain(b, "chat")
    assert line["text"] == f"jerry mbp took {botname}'s seat"
    assert line["seat"] == -1
    # the line's participants, as names: the newcomer, and the bot it replaced
    assert (line["event"], line["actor"], line["target"], line["target_is_bot"]) == (
        "took_seat", "jerry mbp", botname, True)


def test_system_lines_carry_their_kind_and_actor(client):
    """Each system line names its kind and its person as fields, so a client
    words it without reading the name out of the English text."""
    from shengji.api import server as srv

    def fields(room, kind):
        line = next(m for m in reversed(room.chat) if m.get("event") == kind)
        return line["text"], line["actor"], "target" in line

    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        room = srv.rooms[code]
        with ExitStack() as sockets:
            first = ExitStack()
            sockets.callback(first.close)
            b = first.enter_context(client.websocket_connect("/ws"))
            b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "bob", "seat": 2})
            tok = _drain(b, "resume")["token"]
            _drain(b, "state")
            first.close()
            _wait_for(lambda: any(m.get("event") == "disconnected" for m in room.chat))
            assert fields(room, "disconnected") == ("bob disconnected", "bob", False)
            back = sockets.enter_context(client.websocket_connect("/ws"))
            back.send_json({"type": "table_join", "expect": "room", "code": code,
                            "name": "bob", "token": tok})
            _drain(back, "state")
            _wait_for(lambda: any(m.get("event") == "reconnected" for m in room.chat))
            assert fields(room, "reconnected") == ("bob reconnected", "bob", False)
            back.send_json({"type": "table_leave"})
            _drain(back, "left")
            _wait_for(lambda: any(m.get("event") == "left" for m in room.chat))
            assert fields(room, "left") == ("bob left", "bob", False)


def test_chat_snapshot_rolls_over_after_more_than_fifty_messages(client):
    """A late/rejoining socket gets one bounded, contiguous snapshot.

    This crosses the real wire and the queue used by production.  A unit test
    of ``room.chat[-50:]`` would miss an attach path that sent stale history,
    duplicated the live boundary, or blocked after enough fan-out messages.
    """
    with client.websocket_connect("/ws") as host:
        code = _room_with_bots(host, "host")
        for i in range(60):
            host.send_json({"type": "table_chat", "text": f"line-{i:02d}"})

        with client.websocket_connect("/ws") as late:
            late.send_json({"type": "table_join", "expect": "room", "code": code,
                            "name": "late"})
            history = _drain(late, "chat_history")

    assert history["through_id"] == 60
    assert len(history["messages"]) == 50
    assert [m["id"] for m in history["messages"]] == list(range(11, 61))
    assert history["messages"][0]["text"] == "line-10"
    assert history["messages"][-1]["text"] == "line-59"


def test_room_chat_and_a_guests_name_are_masked_where_the_server_takes_them(client):
    """The chat filter runs where a room chat line is accepted, so the echo,
    the scrollback and the round log all hold the masked line; a guest's
    typed name is masked where its seat takes it."""
    import json

    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        room_frame, _ = _created_room(a, "shithead")
        code = room_frame["room"]
        room = srv.rooms[code]
        assert room.seats[0].name == "********"
        a.send_json({"type": "table_chat", "text": "well fuck, a class play"})
        echo = _drain(a, "chat")
        while echo.get("seat") != 0:
            echo = _drain(a, "chat")
        assert echo["text"] == "well ****, a class play"
    assert [m["text"] for m in room.chat if m["seat"] == 0] == ["well ****, a class play"]
    records = [json.loads(line)
               for line in (room.log_dir / f"{code}.jsonl").read_text().splitlines()]
    assert [r["text"] for r in records if r["e"] == "chat"] == ["well ****, a class play"]
    assert not any("fuck" in line or "shithead" in line
                   for line in (room.log_dir / f"{code}.jsonl").read_text().splitlines())


def test_room_chat_is_logged_and_reaches_the_scrollback(client):
    """A room's chat is always a game's chat, so every line is logged."""
    import json

    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a, "host")
        room = srv.rooms[code]
        a.send_json({"type": "table_chat", "text": "in-game-line"})
        # the deal streams a state frame per card, so the echo can come late
        echo = _drain(a, "chat")
        while echo.get("text") != "in-game-line":
            echo = _drain(a, "chat")

        bot_seat = next(i for i, sd in enumerate(room.seats) if sd.is_bot)
        with client.websocket_connect("/ws") as c:
            c.send_json({"type": "table_join", "expect": "room", "code": code, "name": "late",
                         "seat": bot_seat})
            history = _drain(c, "chat_history")
    assert "in-game-line" in [m["text"] for m in history["messages"]]

    records = [json.loads(line)
               for line in (room.log_dir / f"{code}.jsonl").read_text().splitlines()]
    chats = [r for r in records if r["e"] == "chat"]
    assert len(chats) == 1
    assert {k: chats[0][k] for k in ("e", "seat", "text", "bot", "room")} == {
        "e": "chat", "seat": 0, "text": "in-game-line", "bot": False, "room": code}
    assert chats[0]["round"] == room.game.round_no


def test_two_clients_race_for_same_bot_seat(client):
    """The loser of a seat race must be refused, never silently reseated."""
    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        with client.websocket_connect("/ws") as b, \
                client.websocket_connect("/ws") as c:
            b.send_json({"type": "table_peek", "code": code})
            want = [s["seat"] for s in _drain(b, "room_seats")["seats"]
                    if s["is_bot"]][0]
            b.send_json({"type": "table_join", "expect": "room", "code": code,
                         "name": "first", "seat": want})
            assert _drain(b, "state")["you"] == want
            c.send_json({"type": "table_join", "expect": "room", "code": code,
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
            b.send_json({"type": "table_join", "expect": "room", "code": code,
                         "name": "odd", "seat": True})   # bool is not a seat
            st = _drain(b, "state")
    assert st["you"] in (1, 2, 3)


def _start_game(client, a, to_play=False):
    """A created room with 3 bots, its game running; returns (code, room).

    With to_play=True this drives the REAL deal path (the fixture zeroes
    DEAL_DELAY and shortens the declare window) rather than advancing the
    round in-process — an in-process loop races the server's own deal task
    and both end up calling deal_next on the same round.
    """
    from shengji.api import server as srv

    room_frame, st = _created_room(a)
    code = room_frame["room"]
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
            st = _drain(a, "state")
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


def test_the_deal_paces_a_card_every_0_2_s_and_keeps_the_declare_windows():
    from shengji.api import server as srv
    from shengji.engine.round import HAND_SIZE

    assert srv.DEAL_DELAY == 0.2
    assert 4 * HAND_SIZE * srv.DEAL_DELAY == pytest.approx(20.0)
    # the window after the last card is the deal-speed-independent part
    assert srv.DECLARE_GRACE == 5.0 and srv.DECLARE_EXTEND == 3.0


def test_a_human_declaration_during_the_deal_is_accepted(client, monkeypatch):
    from shengji.ai.heuristic import HeuristicBot
    from shengji.api import server as srv

    from shengji.engine.cards import card_rank
    from shengji.engine.round import Round

    monkeypatch.setattr(HeuristicBot, "decide_declare", lambda *a, **kw: None)
    # Slow enough that a socket round trip lands mid-deal, at the real pace's order.
    monkeypatch.setattr(srv, "DEAL_DELAY", 0.05)
    real_init = Round.__init__

    def init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        # seat 0's first card is a trump-rank card, so it can declare at once
        i = next(i for i, c in enumerate(self.deck) if card_rank(c) == self.trump_rank)
        self.deck[0], self.deck[i] = self.deck[i], self.deck[0]

    monkeypatch.setattr(Round, "__init__", init)
    with client.websocket_connect("/ws") as a:
        room_frame, st = _created_room(a)
        room = srv.rooms[room_frame["room"]]
        while not st["declare_options"]:
            assert st["phase"] == "deal", "the deal ended before seat 0 could declare"
            st = _drain(a, "state")
        option = st["declare_options"][0]
        a.send_json({"type": "declare", "card_ids": option})
        for _ in range(200):
            st = _drain(a, "state")
            if st["current_declaration"] is not None:
                break
        assert st["current_declaration"]["seat"] == 0
        assert st["phase"] == "deal"                 # taken while cards were still coming
        assert room.round.declaration is not None and room.round.declaration["seat"] == 0


def test_claim_preserves_private_hand_and_ids(client):
    """The claimant gets that seat's REAL remaining cards; others see counts."""
    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a, to_play=True)
        want = next(i for i, sd in enumerate(room.seats) if sd.is_bot)
        before = sorted(room.round.hands[want])
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "table_join", "expect": "room", "code": code,
                         "name": "late", "seat": want})
            st = _drain(b, "state")
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
                b.send_json({"type": "table_join", "expect": "room", "code": code,
                             "name": "sniper", "seat": turn})
                state = _drain(b, "state")
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
    # the room's bot is built at create_room, which also starts the game
    monkeypatch.setattr(srv, "make_bot", lambda *args, **kwargs: StatefulBot())

    with client.websocket_connect("/ws") as host:
        room_frame, state = _created_room(host)
        code = room_frame["room"]
        room = srv.rooms[code]
        assert isinstance(room.bot, StatefulBot)
        original_log = room.log_event

        def capture_log(kind, **data):
            original_log(kind, **data)
            if kind == "bot_timing" and data.get("phase") == "play":
                timing_records.append(data)
                timing_logged.set()

        # the first play-phase search blocks until release, so its commit
        # is logged through this capture
        room.log_event = capture_log
        while state.get("phase") != "play":
            state = _drain(host, "state")
        assert started.wait(timeout=5), "on-turn bot search never started"
        seat = blocked["seat"]
        assert room.round.turn == seat and room.seats[seat].is_bot
        live_bot = room.bot
        live_rng = live_bot.rng.getstate()
        hand_before = list(room.round.hands[seat])

        try:
            with client.websocket_connect("/ws") as claimant:
                claimant.send_json({"type": "table_join", "expect": "room", "code": code,
                                    "name": "claimant", "seat": seat})
                claimed = _drain(claimant, "state")
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
                b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "jerry",
                             "token": seat0.token})
                _drain(b, "state")
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
        b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "jerry",
                     "token": room.seats[0].token})
        _drain(b, "state")
        assert room.cleanup_task is None or room.cleanup_task.cancelled()


def test_claim_state_does_not_leak_across_rooms_on_one_socket(client):
    """Claiming a bot seat in room A must not label a later join of room B."""
    with client.websocket_connect("/ws") as a, \
            client.websocket_connect("/ws") as host_b:
        code_a, room_a = _start_game(client, a)
        # Room B's join takes a different bot's seat, so a line naming room
        # A's bot, or a human, is leaked state.
        code_b = _room_with_bots(host_b, "hostb")
        with client.websocket_connect("/ws") as mover:
            mover.send_json({"type": "table_join", "expect": "room", "code": code_a,
                             "name": "wanderer", "seat": 3})
            first = _drain(mover, "chat")
            assert first["text"] == "wanderer took Bot 3's seat"
            mover.send_json({"type": "table_leave"})
            _drain(mover, "left")
            mover.send_json({"type": "table_join", "expect": "room", "code": code_b,
                             "name": "wanderer", "seat": 1})
            line = _drain(mover, "chat")
            while "wanderer" not in line["text"]:
                line = _drain(mover, "chat")
    assert line["text"] == "wanderer took Bot 1's seat", \
        f"stale claim state leaked into the next room: {line['text']}"


def test_state_reports_takeover_countdown(client):
    """A disconnected human's seat carries seconds-until-bot; others None."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a, to_play=True)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "james"})
            _drain(b, "state")
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
    """Room of 4 HUMANS mid-game — no bot seat anywhere: jerry, amy, bo and
    cy in seats 0-3, each joiner taking a bot's seat of the running game;
    their sockets and stacks are returned in the order amy, bo, cy."""
    from shengji.api import server as srv

    code = _room_with_bots(a)
    peers, peer_stacks = [], []
    for seat, n in enumerate(("amy", "bo", "cy"), start=1):
        peer_stack = ExitStack()
        sockets.callback(peer_stack.close)
        w = peer_stack.enter_context(client.websocket_connect("/ws"))
        w.send_json({"type": "table_join", "expect": "room", "code": code, "name": n, "seat": seat})
        assert _drain(w, "state")["you"] == seat
        peers.append(w)
        peer_stacks.append(peer_stack)
    assert [s.name for s in srv.rooms[code].seats] == ["jerry", "amy", "bo", "cy"]
    assert not any(s.is_bot for s in srv.rooms[code].seats)
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
            amy_token = room.seats[1].token
            peer_stacks[0].close()                     # amy drops

            # --- inside the grace window: reserved for amy ---
            with client.websocket_connect("/ws") as p:
                p.send_json({"type": "table_peek", "code": code})
                seats = _drain(p, "room_seats")["seats"]
            assert not seats[1]["claimable"], \
                "seat claimable during its grace window"
            assert seats[1]["reserved_secs"] is not None
            with client.websocket_connect("/ws") as q:
                q.send_json({"type": "table_join", "expect": "room", "code": code,
                             "name": "vulture"})
                assert _drain(q, "error")["code"] == "seat_reserved"
            # nor by her name alone
            with client.websocket_connect("/ws") as q:
                q.send_json({"type": "table_join", "expect": "room", "code": code,
                             "name": "amy"})
                assert _drain(q, "error")["code"] == "seat_reserved"
            # amy herself, by her seat's token, can still return.
            with client.websocket_connect("/ws") as amy:
                amy.send_json({"type": "table_join", "expect": "room", "code": code,
                               "name": "amy", "token": amy_token})
                assert _drain(amy, "state")["you"] == 1

            # --- after it expires: anyone may take over ---
            clock["v"] += srv.TAKEOVER_AFTER + 1
            with client.websocket_connect("/ws") as p2:
                p2.send_json({"type": "table_peek", "code": code})
                seats2 = _drain(p2, "room_seats")["seats"]
            assert seats2[1]["claimable"], \
                "seat still locked after the grace window"
            with client.websocket_connect("/ws") as r:
                r.send_json({"type": "table_join", "expect": "room", "code": code,
                             "name": "newbie", "seat": 1})
                st = _drain(r, "state")
                assert st["you"] == 1 and len(st["hand"]) > 0


def test_reclaim_is_case_and_space_insensitive(client, clock):
    """Coming back as 'Amy ' after the hold must reclaim the seat left by 'amy'."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        with ExitStack() as sockets:
            code, room, socks, peer_stacks = _four_humans(
                client, a, sockets)
            peer_stacks[0].close()
            clock["v"] += srv.TAKEOVER_AFTER + 1
            with client.websocket_connect("/ws") as back:
                back.send_json({"type": "table_join", "expect": "room", "code": code,
                                "name": " Amy "})
                st = _drain(back, "state")
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
                r.send_json({"type": "table_join", "expect": "room", "code": code,
                             "name": "newbie", "seat": 1})
                line = _drain(r, "chat")
            assert "took over for amy" in line["text"], line
            # amy is a person the newcomer took over for
            assert (line["event"], line["actor"], line["target"], line["target_is_bot"]) == (
                "took_over", "newbie", "amy", False), line


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
            b.send_json({"type": "table_join", "expect": "room", "code": code,
                         "name": "jerry", "token": seat0.token})
            _drain(b, "state")
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
                real.send_json({"type": "table_join", "expect": "room", "code": code,
                                "name": "totally-different-name",
                                "token": tok})
                st = _drain(real, "state")
                assert st["you"] == 1


def test_name_reentry_is_allowed_but_does_not_inherit_the_token(client, clock):
    """The house trust model, asserted honestly rather than wished away.

    After the hold window, typing a dropped player's name DOES re-enter
    their seat — the same permission the seat picker then grants, so the
    name path is not a privilege escalation. What it must NOT do is hand over that
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
            from shengji.api import server as srv
            clock["v"] += srv.TAKEOVER_AFTER + 1
            with client.websocket_connect("/ws") as other:
                other.send_json({"type": "table_join", "expect": "room", "code": code,
                                 "name": "AMY ", "token": "not-the-token"})
                st = _drain(other, "state")
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
            b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "james"})
            _drain(b, "state")
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


def _two_humans_at_round_end(client, a, monkeypatch):
    """Seat 0 (``a``) and a second human on seat 1 at a round end, neither
    confirmed; returns (code, room, round_no, b's ExitStack, b, b's token)."""
    from shengji.api import server as srv

    code, room = _timer_game(client, a, monkeypatch, on=True)
    round_no = room.game.round_no
    room.seats[0].away = True              # the bot plays seat 0 to the round end
    client.portal.call(srv.kick_bots, room)
    _wait_for(lambda: room.round.phase == "round_end")
    a.send_json({"type": "im_back"})
    _wait_for(lambda: not room.seats[0].away)
    stack = ExitStack()
    b = stack.enter_context(client.websocket_connect("/ws"))
    b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "bee", "seat": 1})
    token = _drain(b, "resume")["token"]
    _drain(b, "state")
    _settled(client, room)
    assert room.ready == set() and srv.pending_ready(room) == {0, 1}
    return code, room, round_no, stack, b, token


def _ready_and_drop(client, room, stack, b):
    b.send_json({"type": "next_round"})
    _wait_for(lambda: 1 in room.ready)
    stack.close()
    _wait_for(lambda: not room.seats[1].connected)
    _settled(client, room)


def _resume(client, sockets, code, room, token):
    b = sockets.enter_context(client.websocket_connect("/ws"))
    b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "bee", "token": token})
    _drain(b, "state")
    _settled(client, room)
    assert room.seats[1].connected
    return b


def test_a_short_blip_keeps_the_round_end_ready(client, clock, monkeypatch):
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room, round_no, stack, b, token = _two_humans_at_round_end(client, a, monkeypatch)
        _ready_and_drop(client, room, stack, b)
        assert room.game.round_no == round_no and 1 in room.ready
        clock["v"] += srv.READY_KEEP_SECONDS - 1
        with ExitStack() as sockets:
            _resume(client, sockets, code, room, token)
            assert 1 in room.ready, "a short drop undid the confirmation"
            a.send_json({"type": "next_round"})
            _wait_for(lambda: room.game.round_no == round_no + 1)


def test_a_long_absence_drops_the_round_end_ready_on_return(client, clock, monkeypatch):
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room, round_no, stack, b, token = _two_humans_at_round_end(client, a, monkeypatch)
        _ready_and_drop(client, room, stack, b)
        clock["v"] += srv.READY_KEEP_SECONDS + 1
        with ExitStack() as sockets:
            _resume(client, sockets, code, room, token)
            assert 1 not in room.ready
            a.send_json({"type": "next_round"})
            _wait_for(lambda: 0 in room.ready)
            _settled(client, room)
            assert room.game.round_no == round_no
            assert srv.pending_ready(room) == {1}


def test_a_kept_ready_of_a_dropped_seat_alone_starts_no_round(client, clock, monkeypatch):
    """A lone player who confirmed and then dropped: nobody connected is at
    the table, so the next round does not start."""
    from shengji.api import server as srv

    a = client.websocket_connect("/ws").__enter__()
    try:
        _, room = _timer_game(client, a, monkeypatch, on=True)
        round_no = room.game.round_no
        room.seats[0].away = True
        client.portal.call(srv.kick_bots, room)
        _wait_for(lambda: room.round.phase == "round_end")
        room.ready.add(0)
        a.__exit__(None, None, None)
        a = None
        _wait_for(lambda: not room.seats[0].connected)
        assert 0 in room.ready and srv.pending_ready(room) == set()

        async def _advance():
            async with room.lock:
                return await srv.advance_if_all_ready(room)

        assert client.portal.call(_advance) is False
        assert room.game.round_no == round_no
    finally:
        if a is not None:
            a.__exit__(None, None, None)


def test_a_leave_at_round_end_drops_the_leavers_ready(client, clock, monkeypatch):
    with client.websocket_connect("/ws") as a:
        code, room, round_no, stack, b, token = _two_humans_at_round_end(client, a, monkeypatch)
        with stack:
            b.send_json({"type": "next_round"})
            _wait_for(lambda: 1 in room.ready)
            b.send_json({"type": "table_leave"})
            _drain(b, "left")
        _settled(client, room)
        assert 1 not in room.ready
        assert room.game.round_no == round_no


def test_explicit_leave_at_round_end_advances_the_round(client):
    """P0-4: leaving must release the quorum exactly like dropping does."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a, to_play=True)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "james"})
            _drain(b, "state")
            seat_b = next(i for i, sd in enumerate(room.seats)
                          if sd.name == "james")
            # Pretend the round ended with only `a` ready.
            room.ready.add(0)
            assert srv.pending_ready(room) == {seat_b}
            b.send_json({"type": "table_leave"})
            _drain(b, "left")
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
            w.send_json({"type": "table_join", "expect": "room", "code": code,
                         "name": "onturn", "seat": turn})
            _drain(w, "state")
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


def test_the_hold_is_thirty_seconds_and_the_away_pause_twenty():
    """A dropped seat is held 30 s in every room; its move clock stands still
    for at most 20 s of that, shorter than both the hold and the clock."""
    from shengji.api import server as srv

    assert srv.MOVE_TIMER == 60.0
    assert srv.TAKEOVER_AFTER == 30.0
    assert srv.AWAY_PAUSE_MAX == 20.0


def _run_once(coro):
    import asyncio as aio

    loop = aio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.mark.parametrize("timed", [False, True], ids=["casual", "move-timer"])
def test_a_dropped_seat_is_held_for_thirty_seconds_then_covered(client, clock, timed):
    """Disconnect at t=0: at 29 s the seat is still reserved, the countdown
    reads 1 s and no bot has played; at 30 s the bot plays the turn. The
    same in a casual room and in one with the move timer."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a, to_play=True)
        room.move_timer = timed
        seat = _turn_owner_drops(client, a, code, room)
        if room.seats[seat].connected or room.seats[seat].is_bot:
            pytest.skip("could not place a disconnected human on turn")
        assert room.seats[seat].left_at == clock["v"]
        plays_before = _plays_by(room, seat)
        clock["v"] += 29.0
        assert srv._reserved(room, seat)
        assert srv._takeover_in(room, seat) == 1.0
        assert not _run_once(srv.watchdog_tick(room))
        if timed:
            assert not _run_once(srv.move_timer_tick(room))
        assert _plays_by(room, seat) == plays_before
        assert room.round.turn == seat
        clock["v"] += 1.0
        assert not srv._reserved(room, seat)
        assert srv._takeover_in(room, seat) == 0.0
        assert _run_once(srv.watchdog_tick(room)), "bot never covered the dropped seat"
        assert _plays_by(room, seat) == plays_before + 1


def test_a_leave_press_is_covered_at_once_not_after_the_window(clock, monkeypatch):
    """Leave does not wait for the takeover window; a plain drop does."""
    from shengji.api import server as srv

    monkeypatch.setattr(srv, "current_actor", lambda room: 0)

    def room_with(left_by_choice):
        seat = srv.Seat(name="james", connected=False, left_at=clock["v"],
                        left_by_choice=left_by_choice)
        return srv.Room(code="ZZZZ", seats=[seat])

    left = room_with(True)
    dropped = room_with(False)
    assert srv._turn_eligible(left, 0, "takeover")
    assert not srv._turn_eligible(dropped, 0, "takeover")
    clock["v"] += srv.TAKEOVER_AFTER - 1
    assert not srv._turn_eligible(dropped, 0, "takeover")
    clock["v"] += 1
    assert srv._turn_eligible(dropped, 0, "takeover")


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
            back.send_json({"type": "table_join", "expect": "room", "code": code,
                            "name": "onturn", "token": tok})
            st = _drain(back, "state")
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
                w.send_json({"type": "table_join", "expect": "room", "code": code,
                             "name": "jerry", "token": tok})
                _drain(w, "state")
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
            a2.send_json({"type": "table_join", "expect": "room", "code": code,
                          "name": "jerry", "token": tok})
            st = _drain(a2, "state")
            assert st["you"] == 0, "refresh landed on a different seat"
            assert [s.name for s in srv.rooms[code].seats] == [
                "jerry", "Bot 1", "Bot 2", "Bot 3"], \
                "refresh took a second seat for the same person"


def test_displaced_socket_cannot_act(client):
    """A socket replaced by a newer one owns nothing — not even leave_room."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as h:
        code = _room_with_bots(h, "host")
        with ExitStack() as sockets:
            old = sockets.enter_context(client.websocket_connect("/ws"))
            old.send_json({"type": "table_join", "expect": "room", "code": code, "name": "bob", "seat": 2})
            tok = _drain(old, "resume")["token"]
            _drain(old, "state")
            new = sockets.enter_context(client.websocket_connect("/ws"))
            new.send_json({"type": "table_join", "expect": "room", "code": code,
                           "name": "bob", "token": tok})
            _drain(new, "state")
            room = srv.rooms[code]
            assert room.seats[2].connected

            old.send_json({"type": "table_leave"})  # displaced socket acts
            err = _drain(old, "error")
            assert err["code"] == "stale_connection"
            assert code in srv.rooms, "stale leave deleted the room"
            assert room.seats[2].name == "bob" and not room.seats[2].is_bot, \
                "stale leave gave up the live seat"
            assert room.seats[2].connected, \
                "stale leave detached the live socket"


def test_a_displaced_socket_closing_posts_no_disconnect_chat(client):
    """The seat is still held, by the socket that replaced this one."""
    import time

    from shengji.api import server as srv

    with client.websocket_connect("/ws") as h:
        code = _room_with_bots(h, "host")
        room = srv.rooms[code]
        with ExitStack() as sockets:
            old_stack = ExitStack()
            sockets.callback(old_stack.close)
            old = old_stack.enter_context(client.websocket_connect("/ws"))
            old.send_json({"type": "table_join", "expect": "room", "code": code, "name": "bob", "seat": 2})
            tok = _drain(old, "resume")["token"]
            _drain(old, "state")
            new = sockets.enter_context(client.websocket_connect("/ws"))
            new.send_json({"type": "table_join", "expect": "room", "code": code,
                           "name": "bob", "token": tok})
            _drain(new, "state")
            old_stack.close()
            time.sleep(0.3)                 # the server handles the close
            _settled(client, room)
            assert room.seats[2].connected
            assert not any(m["text"] == "bob disconnected" for m in room.chat)
            h.send_json({"type": "table_chat", "text": "marker"})
            seen = _frames_until(new, lambda m: m.get("type") == "chat"
                                 and m.get("text") == "marker", "the marker line")
            assert not any(m.get("type") == "chat" and "disconnected" in m.get("text", "")
                           for m in seen)


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
                taker.send_json({"type": "table_join", "expect": "room", "code": code,
                                 "name": "newbie", "seat": 1})
                _drain(taker, "state")
                assert room.seats[1].token != old_tok, \
                    "token survived the transfer"
                assert room.seats[1].bot_announced is False, \
                    "claimed seat inherited the prior owner's bot announcement"
                # The old token must no longer resume that seat.
                with client.websocket_connect("/ws") as amy:
                    amy.send_json({"type": "table_join", "expect": "room", "code": code,
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
        m, _ = _created_room(a, start_level="10")
        assert m["start_level"] == "10"
        code = m["room"]
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
        code = _room_with_bots(a)
        seat = srv.rooms[code].seats[0]

        seat.writer.cancel()                 # nothing else changes
        assert seat.connected, "seat still reports connected"
        # read past the frames the writer sent before it stopped
        with pytest.raises(AssertionError) as caught:
            _drain(a, "never-sent", timeout=1.0)
        assert "within 1.0s" in str(caught.value), str(caught.value)

        a.send_json({"type": "table_chat", "text": "after the writer stopped"})
        with pytest.raises(AssertionError) as caught:
            _drain(a, "chat", timeout=1.0)
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
                _drain(a, "resume", timeout=1.0)
                code = list(srv.rooms)[0]
                seat = srv.rooms[code].seats[0]
                with pytest.raises(AssertionError):
                    _drain(a, "room", timeout=1.0)

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
            b.send_json({"type": "table_join", "expect": "room", "code": code,
                         "name": "jerry", "token": tok})
            _drain(b, "state")
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
            _drain(a, "resume", timeout=1.0)
            seat = srv.rooms[list(srv.rooms)[0]].seats[0]
            with pytest.raises(AssertionError):
                _drain(a, "room", timeout=1.0)
            assert seat.writer_exit == "error", seat.writer_exit
            assert "transient send failure" in (seat.writer_error or "")
    finally:
        srv._writer = keep


def test_none_now_means_still_running(client):
    """The property that makes the instrument two-sided: with a healthy
    socket, BOTH fields stay None, so None is evidence rather than ambiguity."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        seat = srv.rooms[code].seats[0]
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
            b.send_json({"type": "table_join", "expect": "room", "code": code,
                         "name": "jerry", "token": tok})
            _drain(b, "state")
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
        _, st = _created_room(a)
        assert st["games_won"] == [0, 0], st.get("games_won")


def test_round_result_payload_carries_the_scoring_fields(client):
    """Codex P2 on #644: the modal reads round_result, so omitting the new
    fields there left the UI saying '+levels' on a game win and reset."""
    from shengji.api import server as srv
    from shengji.engine.game import A_INDEX

    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
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
        # scored outside _finish_round, the result has no recorded levels to send
        assert "old_levels" not in payload


def _finished_payload(client, levels, banker, attacker_points):
    """The round_result a seat receives for a round played at `levels`."""
    from shengji.api import server as srv
    from shengji.engine.cards import RANKS

    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        room = srv.rooms[code]
        game = room.game
        game.level_idx = [RANKS.index(levels[0]), RANKS.index(levels[1])]
        rnd = game.round
        rnd.phase = "round_end"
        rnd.banker = banker
        rnd.attacker_points = attacker_points
        srv._finish_round(room)
        return srv.state_for(room, 0)["round_result"]


def test_round_result_carries_the_levels_before_a_normal_round(client):
    # we bank at J and hold them to 40: we go up one, to Q; they stay at 9
    payload = _finished_payload(client, ("J", "9"), banker=0, attacker_points=40)
    assert payload["old_levels"] == ["J", "9"]
    assert payload["new_levels"] == ["Q", "9"]


def test_round_result_carries_the_levels_before_a_takeover(client):
    # they attack at K and take 125: they take the deal and go up one, to A. The climb
    # ran into A, so only old_levels says they started at K.
    payload = _finished_payload(client, ("5", "K"), banker=0, attacker_points=125)
    assert payload["winner_team"] == 1 and payload["next_banker"] == 1
    assert payload["old_levels"] == ["5", "K"]
    assert payload["new_levels"] == ["5", "A"]
    # a capped climb: from Q, 165 points would be two levels, and lands on A too
    capped = _finished_payload(client, ("5", "Q"), banker=0, attacker_points=165)
    assert capped["old_levels"] == ["5", "Q"] and capped["new_levels"] == ["5", "A"]


ROUND_END_FIXTURE = (Path(__file__).resolve().parents[2] / "web" / "src" / "components"
                     / "round-end-levels.fixture.json")


def test_the_client_s_round_end_fixture_is_what_state_for_sends(client):
    """web/src/components/round-end-levels.fixture.json holds the state_for
    frames the round-end card is tested on, so the card reads what the server
    really sends. The deal's random kitty is cleared; the rest is verbatim.
    SHENGJI_REGEN_FIXTURES=1 rewrites it."""
    from shengji.api import server as srv
    from shengji.engine.cards import RANKS

    cases = {}
    for name, levels, attacker_points in (("round", ("J", "9"), 40), ("takeover", ("5", "K"), 125),
                                          ("won_game", ("A", "Q"), 35)):
        with client.websocket_connect("/ws") as a:
            code = _room_with_bots(a)
            room = srv.rooms[code]
            game = room.game
            game.level_idx = [RANKS.index(levels[0]), RANKS.index(levels[1])]
            rnd = game.round
            rnd.phase = "round_end"
            rnd.banker = 0
            rnd.attacker_points = attacker_points
            rnd.kitty_bonus = 0
            rnd.buried = []
            srv._finish_round(room)
            st = srv.state_for(room, 0)
            cases[name] = {key: st[key] for key in ("you", "banker", "levels", "games_won", "round_result")}
    text = json.dumps(cases, indent=2, sort_keys=True) + "\n"
    if os.environ.get("SHENGJI_REGEN_FIXTURES") == "1":
        ROUND_END_FIXTURE.write_text(text)
    assert ROUND_END_FIXTURE.read_text() == text


def test_round_result_carries_the_levels_before_a_won_game_s_restart(client):
    # we defend at A and hold them to 35: a game won, both teams restart at 2
    payload = _finished_payload(client, ("A", "Q"), banker=0, attacker_points=35)
    assert payload["point_scored"] is True
    assert payload["old_levels"] == ["A", "Q"]
    assert payload["new_levels"] == ["2", "2"]


def test_the_start_level_is_fixed_once_the_game_starts(client):
    """Game() reads the level exactly once at the start; a later change would
    make the HUD lie for the rest of the session."""
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        a.send_json({"type": "table_start_level", "start_level": "K"})
        # the refusal queues behind the deal's state frames, one per card
        assert _drain(a, "error")["message"] == "Game already started."
        assert srv.rooms[code].start_level == "2"
        assert srv.rooms[code].game.levels == ("2", "2")


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
                # The start broadcasts once itself and every later frame is
                # the deal task's, so a dead deal task reads as one state
                # frame, then nothing.
                code = _room_with_bots(a)
                with pytest.raises(AssertionError) as info:
                    _drain(a, "state", timeout=1.0)
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
                    _drain(a, "state", timeout=1.0)
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


def test_negotiated_heartbeat_before_and_after_room_attach(client, monkeypatch):
    from shengji.api import server as srv

    monkeypatch.setattr(srv, "WEB_BUILD", None)
    with client.websocket_connect("/ws?heartbeat=1") as ws:
        assert _drain(ws, "heartbeat_ready") == {"type": "heartbeat_ready"}
        ws.send_json({"type": "ping", "nonce": 1})
        assert _drain(ws, "pong") == {"type": "pong", "nonce": 1}
        assert not srv.rooms
        code = _room_with_bots(ws)
        ws.send_json({"type": "ping", "nonce": 2})
        # the deal streams a state frame per card ahead of the pong
        assert _drain(ws, "pong") == {"type": "pong", "nonce": 2}
        seats = tuple(srv.rooms[code].seats)
        assert len(seats) == 4
        ws.send_json({"type": "ping", "nonce": 3})
        assert _drain(ws, "pong") == {"type": "pong", "nonce": 3}
        assert tuple(srv.rooms[code].seats) == seats
        assert srv.rooms[code].game.round_no == 1


def test_heartbeat_ready_carries_the_served_page_build(client, monkeypatch):
    from shengji.api import server as srv

    monkeypatch.setattr(srv, "WEB_BUILD", "a1b2c3d4e5f6")
    with client.websocket_connect("/ws?heartbeat=1") as ws:
        assert _drain(ws, "heartbeat_ready") == {"type": "heartbeat_ready", "build": "a1b2c3d4e5f6"}
    assert client.get("/healthz").json()["web_build"] == "a1b2c3d4e5f6"


def test_web_build_reads_the_meta_tag_of_the_built_page(tmp_path):
    from shengji.api import server as srv

    assert srv.web_build(tmp_path) is None
    (tmp_path / "index.html").write_text("<head><title>x</title></head>", encoding="utf-8")
    assert srv.web_build(tmp_path) is None
    (tmp_path / "index.html").write_text(
        '<head><meta name="shengji-build" content="0f9e8d7c6b5a"></head>', encoding="utf-8")
    assert srv.web_build(tmp_path) == "0f9e8d7c6b5a"
    (tmp_path / "index.html").write_text(
        '<head><meta name="shengji-build" content="bad id!"></head>', encoding="utf-8")
    assert srv.web_build(tmp_path) is None


def test_heartbeat_ignores_invalid_nonce_without_breaking_next_request(client):
    with client.websocket_connect("/ws?heartbeat=1") as ws:
        _drain(ws, "heartbeat_ready")
        for nonce in (None, True, -1, "large", 9007199254740992):
            ws.send_json({"type": "ping", "nonce": nonce})
        ws.send_json({"type": "ping", "nonce": 7})
        assert _drain(ws, "pong") == {"type": "pong", "nonce": 7}


@pytest.mark.parametrize("bad", [{"a": 1, "b": 1}, {"a": 0, "b": 4},
                                 {"a": "0", "b": 1}, {"a": True, "b": 1}, {}])
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
    """Seat 0 human, three bots, in the play phase, waiting on seat 0. The
    clock runs as if a second human were seated: these tests are about the
    clock itself, and the one-human rule has its own (``test_matchmaking``)."""
    from shengji.api import server as srv

    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    monkeypatch.setattr(srv, "_timer_live", lambda room: room.move_timer)
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


def _state_until(ws, pred, timeout=60.0):
    """The first state frame that satisfies ``pred`` (older frames queue up)."""
    return _next_where(ws, "state", pred, timeout)


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

    async def _timeout_and_count():
        before = _plays_by(room, seat)
        clock["v"] += srv.MOVE_TIMER + 1
        acted = await srv.move_timer_tick(room)
        # Capture the commit before the newly kicked away-seat pump can run.
        return acted, before, _plays_by(room, seat)

    acted, before, after = client.portal.call(_timeout_and_count)
    assert acted
    assert after == before + 1


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
        state = _drain(a, "state")
        assert all(p["turn_deadline"] is None and p["away"] is False
                   for p in state["players"])
        assert room.seats[0].turn_started is None


def test_a_disconnected_turn_uses_takeover_and_is_not_a_timeout(client, clock, monkeypatch):
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as b:
        with client.websocket_connect("/ws") as a:
            code, room = _timer_game(client, a, monkeypatch)
            _tick(client, room)
            # a second human keeps the room alive once seat 0 drops
            b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "bee", "seat": 1})
            _drain(b, "state")
        _wait_for(lambda: not room.seats[0].connected)
        before = _plays_by(room, 0)
        clock["v"] += srv.MOVE_TIMER + 1
        assert _tick(client, room) is False, "the move timer acted for a disconnected seat"
        assert client.portal.call(srv.watchdog_tick, room) is True
        assert _plays_by(room, 0) == before + 1
        seat = room.seats[0]
        assert (seat.timeouts_in_row, seat.timeouts_in_round, seat.away) == (0, 0, False)


def _drop_and_return(client, a_ctx, b, code, room, clock, drop_at, back_at):
    """Seat 0 owes a play with its clock started at the current time; its
    socket closes ``drop_at`` seconds in and a new socket takes the seat back
    by token ``back_at`` seconds in. Returns the new socket's context."""
    seat = room.seats[0]
    started = seat.turn_started
    assert started is not None
    clock["v"] = started + drop_at
    a_ctx.__exit__(None, None, None)
    _wait_for(lambda: not seat.connected)
    clock["v"] = started + back_at
    back = client.websocket_connect("/ws")
    ws = back.__enter__()
    ws.send_json({"type": "table_join", "expect": "room", "code": code,
                  "name": "jerry", "token": seat.token})
    _drain(ws, "state")
    _wait_for(lambda: seat.connected)
    return back, ws


@pytest.mark.parametrize("drop_at,back_at,left", [
    (5.0, 24.0, 55.0),      # the clock stood still while away
    (50.0, 55.0, 15.0),     # nearly run out at the drop: RETURN_MIN
    (50.0, 70.0, 15.0),     # back at the end of the pause: RETURN_MIN
    (0.0, 20.0, 60.0),
], ids=["early-drop", "late-drop", "late-drop-back-at-20s", "drop-at-once"])
def test_a_returning_seat_resumes_its_clock_with_at_least_return_min(
        client, clock, monkeypatch, drop_at, back_at, left):
    """Back within AWAY_PAUSE_MAX, the move clock takes up where it stood at
    the drop, with at least RETURN_MIN left: no strike comes of the time
    away."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as b:
        a_ctx = client.websocket_connect("/ws")
        a = a_ctx.__enter__()
        code, room = _timer_game(client, a, monkeypatch)
        b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "bee", "seat": 1})
        _drain(b, "state")
        assert _tick(client, room) is False          # starts the clock
        back, ws = _drop_and_return(client, a_ctx, b, code, room, clock, drop_at, back_at)
        try:
            seat = room.seats[0]
            before = _plays_by(room, 0)
            assert _my_turn(room)
            assert srv._turn_deadline(room, 0) == left
            clock["v"] += left - 1
            assert _tick(client, room) is False, "struck for time spent away"
            assert _plays_by(room, 0) == before
            assert (seat.timeouts_in_row, seat.timeouts_in_round) == (0, 0)
            clock["v"] += 2
            assert _tick(client, room) is True       # the resumed clock still runs out
            assert (seat.timeouts_in_row, seat.timeouts_in_round) == (1, 1)
        finally:
            back.__exit__(None, None, None)
    assert srv.RETURN_MIN == 15.0


@pytest.mark.parametrize("drop_at,back_at,left", [
    (50.0, 75.0, 5.0),      # 10 s left at the drop, back 25 s later
    (5.0, 30.0, 50.0),      # 55 s left at the drop, back 25 s later
    (55.0, 79.0, 1.0),      # 5 s left, back 24 s later: no RETURN_MIN floor
], ids=["ten-left-back-after-25s", "early-drop-back-after-25s", "five-left-back-after-24s"])
def test_a_seat_back_after_the_away_pause_finds_its_clock_run_down(
        client, clock, monkeypatch, drop_at, back_at, left):
    """Away longer than AWAY_PAUSE_MAX, the clock ran on from where it stood
    once the pause was over: the seat is back with that much less, and the
    decision ends by the move clock as for any present player."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as b:
        a_ctx = client.websocket_connect("/ws")
        a = a_ctx.__enter__()
        code, room = _timer_game(client, a, monkeypatch)
        b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "bee", "seat": 1})
        _drain(b, "state")
        assert _tick(client, room) is False          # starts the clock
        back, ws = _drop_and_return(client, a_ctx, b, code, room, clock, drop_at, back_at)
        try:
            seat = room.seats[0]
            before = _plays_by(room, 0)
            assert _my_turn(room)
            assert srv._turn_deadline(room, 0) == left
            clock["v"] += left - 0.5
            assert _tick(client, room) is False
            assert _plays_by(room, 0) == before
            clock["v"] += 1.0
            assert _tick(client, room) is True       # the run-down clock runs out
            assert _plays_by(room, 0) == before + 1
            assert (seat.timeouts_in_row, seat.timeouts_in_round) == (1, 1)
        finally:
            back.__exit__(None, None, None)


def test_a_dropped_seat_whose_clock_runs_out_inside_the_hold_is_played_for(
        client, clock, monkeypatch):
    """5 s left at the drop: the clock stands still 20 s, runs on for 5 s,
    and at 25 s away (inside the 30 s hold) the bot makes that decision.
    No strike and no takeover announcement: the seat is still held."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as b:
        a_ctx = client.websocket_connect("/ws")
        a = a_ctx.__enter__()
        code, room = _timer_game(client, a, monkeypatch)
        b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "bee", "seat": 1})
        _drain(b, "state")
        _tick(client, room)
        seat = room.seats[0]
        started = seat.turn_started
        clock["v"] = started + 55.0
        a_ctx.__exit__(None, None, None)
        _wait_for(lambda: not seat.connected)
        before = _plays_by(room, 0)
        clock["v"] = started + 55.0 + srv.AWAY_PAUSE_MAX + 4.5
        assert _tick(client, room) is False
        assert client.portal.call(srv.watchdog_tick, room) is False
        assert _plays_by(room, 0) == before
        clock["v"] += 1.0                            # 25.5 s away: clock out
        assert client.portal.call(srv.watchdog_tick, room) is False
        assert _tick(client, room) is True
        assert _plays_by(room, 0) == before + 1
        assert (seat.timeouts_in_row, seat.timeouts_in_round, seat.away) == (0, 0, False)
        assert seat.bot_announced is False
        assert srv._reserved(room, 0)


def _rejoin(client, code, seat):
    back = client.websocket_connect("/ws")
    ws = back.__enter__()
    ws.send_json({"type": "table_join", "expect": "room", "code": code,
                  "name": "jerry", "token": seat.token})
    _drain(ws, "state")
    _wait_for(lambda: seat.connected)
    return back


def test_a_clock_run_out_while_away_is_no_strike_when_the_return_beats_the_poll(
        client, clock, monkeypatch):
    """5 s left at the drop (t=55), the clock out while away (t=80), back by
    token at t=80.25 before any poll: the bot's move for that decision is no
    strike, though the seat is connected when it commits."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as b:
        a_ctx = client.websocket_connect("/ws")
        a = a_ctx.__enter__()
        code, room = _timer_game(client, a, monkeypatch)
        b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "bee", "seat": 1})
        _drain(b, "state")
        assert _tick(client, room) is False          # starts the clock
        back, ws = _drop_and_return(client, a_ctx, b, code, room, clock, 55.0, 80.25)
        try:
            seat = room.seats[0]
            before = _plays_by(room, 0)
            assert srv._turn_deadline(room, 0) == 0.0
            assert _tick(client, room) is True
            assert _plays_by(room, 0) == before + 1
            assert (seat.timeouts_in_row, seat.timeouts_in_round, seat.away) == (0, 0, False)
        finally:
            back.__exit__(None, None, None)


def test_a_clock_run_out_while_away_is_no_strike_when_the_return_beats_the_commit(
        client, clock, monkeypatch):
    """The same run-out, with the bot's move snapshotted while the seat is
    away (t=80) and the return by token (t=80.25) landing before its commit."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as b:
        a_ctx = client.websocket_connect("/ws")
        a = a_ctx.__enter__()
        code, room = _timer_game(client, a, monkeypatch)
        b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "bee", "seat": 1})
        _drain(b, "state")
        assert _tick(client, room) is False          # starts the clock
        seat = room.seats[0]
        started = seat.turn_started
        clock["v"] = started + 55.0
        a_ctx.__exit__(None, None, None)
        _wait_for(lambda: not seat.connected)
        clock["v"] = started + 80.0
        before = _plays_by(room, 0)

        async def snapshot():
            async with room.lock:
                return srv._snapshot_bot_turn(room, 0, "timeout")

        snap = client.portal.call(snapshot)
        assert snap is not None, "the run-out clock did not make the turn the bot's"
        prepared = srv._PreparedBotTurn(srv._compute_bot_turn(snap), 0.0, 0.0, 0.0)
        clock["v"] = started + 80.25
        back = _rejoin(client, code, seat)
        try:
            async def commit():
                async with room.lock:
                    return srv._commit_bot_turn(room, prepared)

            assert client.portal.call(commit) is True
            assert _plays_by(room, 0) == before + 1
            assert (seat.timeouts_in_row, seat.timeouts_in_round, seat.away) == (0, 0, False)
        finally:
            back.__exit__(None, None, None)


def test_a_drop_past_the_hold_window_is_covered_then_a_return_gets_a_fresh_clock(
        client, clock, monkeypatch):
    """Past TAKEOVER_AFTER the bot plays the dropped seat's turn as before,
    with no strike; a later return finds a new decision and a whole clock."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as b:
        a_ctx = client.websocket_connect("/ws")
        a = a_ctx.__enter__()
        code, room = _timer_game(client, a, monkeypatch)
        b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "bee", "seat": 1})
        _drain(b, "state")
        _tick(client, room)
        seat = room.seats[0]
        started = seat.turn_started
        clock["v"] = started + 5.0
        a_ctx.__exit__(None, None, None)
        _wait_for(lambda: not seat.connected)
        before = _plays_by(room, 0)
        clock["v"] = started + 5.0 + srv.TAKEOVER_AFTER + 1
        assert _tick(client, room) is False
        assert client.portal.call(srv.watchdog_tick, room) is True
        assert _plays_by(room, 0) == before + 1
        assert (seat.timeouts_in_row, seat.timeouts_in_round, seat.away) == (0, 0, False)


def test_a_returning_seat_in_a_casual_room_has_no_clock(client, clock, monkeypatch):
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as b:
        a_ctx = client.websocket_connect("/ws")
        a = a_ctx.__enter__()
        code, room = _timer_game(client, a, monkeypatch, on=False)
        b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "bee", "seat": 1})
        _drain(b, "state")
        _tick(client, room)
        seat = room.seats[0]
        assert seat.turn_started is None
        seat.turn_started = clock["v"]       # the helper's anchor; no clock reads it
        back, ws = _drop_and_return(client, a_ctx, b, code, room, clock, 5.0, 58.0)
        try:
            before = _plays_by(room, 0)
            assert srv._turn_deadline(room, 0) is None
            clock["v"] += 600
            assert _tick(client, room) is False
            assert _plays_by(room, 0) == before
            assert (seat.timeouts_in_row, seat.timeouts_in_round) == (0, 0)
        finally:
            back.__exit__(None, None, None)


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
            b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "james", "seat": want})
            _drain(b, "state")
            b.send_json({"type": "table_leave"})
            _drain(b, "left")
            assert srv.rooms.get(code) is room, "one human is still playing"
            a.send_json({"type": "table_leave"})
            _drain(a, "left")
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
        # the frame carries the round's resolved tricks, the client's trick count
        assert srv.state_for(room, 0)["tricks_done"] == len(room.round.history)
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
    # the close is in the room log, so the bots' last move reads as a close, not a stall
    events = [json.loads(line) for line in (room.log_dir / f"{code}.jsonl").read_text().splitlines()]
    closed = [e for e in events if e["e"] == "room_closed"]
    assert len(closed) == 1 and events[-1] is closed[0]
    assert closed[0]["reason"] == "empty_ttl" and closed[0]["phase"] == "play"
    assert closed[0]["tricks_played"] == len(room.round.history)
    assert set(closed[0]) == {"t", "room", "round", "e", "reason", "phase", "tricks_played"}


def test_the_last_human_leaving_logs_the_close_once(client):
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a, to_play=True)
        a.send_json({"type": "table_leave"})
        _drain(a, "left")
    _wait_for(lambda: code not in srv.rooms)
    _wait_for(lambda: _room_tasks_done(room))
    events = [json.loads(line) for line in (room.log_dir / f"{code}.jsonl").read_text().splitlines()]
    closed = [e for e in events if e["e"] == "room_closed"]
    assert len(closed) == 1
    assert closed[0]["reason"] in ("other", "round_finished", "empty_ttl", "aborted")
    assert closed[0]["phase"] in ("lobby", "declaring", "bury", "play", "round_end")
    assert 0 <= closed[0]["tricks_played"] <= 25


def test_a_failing_close_record_never_stops_the_close(client, monkeypatch):
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a, to_play=True)

        def broken(kind, **data):
            if kind == "room_closed":
                raise RuntimeError("disk gone")
            return None
        monkeypatch.setattr(room, "log_event", broken)
        a.send_json({"type": "table_leave"})
        _drain(a, "left")
    _wait_for(lambda: code not in srv.rooms)
    _wait_for(lambda: _room_tasks_done(room))


def test_close_phase_words():
    from types import SimpleNamespace

    from shengji.api import server as srv

    def room(phase):
        return SimpleNamespace(round=None if phase is None else SimpleNamespace(phase=phase))

    assert srv._close_phase(room(None)) == "lobby"
    assert srv._close_phase(room("deal")) == "declaring"
    assert srv._close_phase(room("declare")) == "declaring"
    for ph in ("bury", "play", "round_end"):
        assert srv._close_phase(room(ph)) == ph


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
        back.send_json({"type": "table_join", "expect": "room", "code": code, "name": "jerry",
                        "token": room.seats[0].token})
        _drain(back, "state")
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
            b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "james", "seat": want})
            _drain(b, "state")
            b.send_json({"type": "table_leave"})
            _drain(b, "left")
        assert srv.rooms.get(code) is room and not room.closing
        assert room.cleanup_task is None
        left = room.seats[want]
        assert not left.is_bot and not left.connected and left.name == "james"
        assert not srv._unwatched(room)
        # a deliberate Leave: the bot covers the seat at once, and the
        # table names it as left rather than counting down
        assert left.left_by_choice
        st = srv.state_for(room, 0)
        seat = next(p for p in st["players"] if p["seat"] == want)
        assert seat["left"] is True and seat["takeover_in"] is None
        assert seat["controller"] == "bot_cover" and seat["reserved_for"] == "james"
        # the owner's reservation of the seat is unchanged
        assert seat["reserved_secs"] is not None and srv._reserved(room, want)


def test_a_leaver_back_by_code_under_a_new_name_takes_their_own_seat(client):
    """After a Leave the device holds no seat token: the seat it left is
    found by the device key, renamed to the name brought back, and no bot
    seat on the other team is taken. Another device bringing the same new
    name gets a bot's seat, and the left seat stays the leaver's."""
    from shengji.api import server as srv

    dev_b = "b" * 24
    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a, to_play=True)
        want = next(i for i, sd in enumerate(room.seats) if sd.is_bot)
        with client.websocket_connect(f"/ws?device={dev_b}") as b:
            b.send_json({"type": "table_join", "expect": "room", "code": code,
                         "name": "james", "seat": want})
            _drain(b, "state")
            b.send_json({"type": "table_leave"})
            _drain(b, "left")
        assert room.seats[want].left_by_choice and room.seats[want].name == "james"
        bots_before = [i for i, sd in enumerate(room.seats) if sd.is_bot]

        with client.websocket_connect("/ws?device=" + "c" * 24) as other:
            other.send_json({"type": "table_join", "expect": "room", "code": code,
                             "name": "james two"})
            _drain(other, "state")
            assert room.seats[want].name == "james" and not room.seats[want].connected
            taken = next(i for i, sd in enumerate(room.seats)
                         if sd.connected and sd.name == "james two")
            assert taken in bots_before

            with client.websocket_connect(f"/ws?device={dev_b}") as back:
                back.send_json({"type": "table_join", "expect": "room", "code": code,
                                "name": "james two"})
                st = _drain(back, "state")
                assert st["you"] == want
                seat = room.seats[want]
                assert seat.connected and not seat.left_by_choice and seat.name == "james two"
                assert [p["name"] for p in st["players"] if p["seat"] == want] == ["james two"]
                assert srv.rooms.get(code) is room


def test_a_left_seat_is_found_by_its_device_or_its_account_only_while_it_is_left():
    from shengji.api import server as srv

    room = srv.Room(code="LEFT")
    left = srv.Seat(name="james", is_bot=False, connected=False, left_by_choice=True,
                    device="d" * 24, user_id=7)
    room.seats = [srv.Seat(name="jerry", is_bot=False, connected=True), left,
                  srv.Seat(name="Bot 2", is_bot=True), srv.Seat(name="Bot 3", is_bot=True)]
    assert srv._left_seat_of(room, "d" * 24, None) is left
    assert srv._left_seat_of(room, None, 7) is left
    assert srv._left_seat_of(room, "e" * 24, 8) is None
    assert srv._left_seat_of(room, None, None) is None
    # a dropped seat (no Leave) is its token's, and a taken one is not left
    left.left_by_choice = False
    assert srv._left_seat_of(room, "d" * 24, 7) is None
    left.left_by_choice, left.connected = True, True
    assert srv._left_seat_of(room, "d" * 24, 7) is None


def test_allow_joiners_in_game_is_the_openers_and_passes_when_the_opener_leaves(client):
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a, to_play=True)
        opener = room.host
        assert room.seats[opener].name and not room.seats[opener].is_bot
        with client.websocket_connect("/ws") as b:
            want = next(i for i, sd in enumerate(room.seats) if sd.is_bot)
            b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "james", "seat": want})
            st = _drain(b, "state")
            # every seat's state names the opener's seat
            assert st["opener"] == opener and srv.state_for(room, opener)["opener"] == opener
            # a person who is not the opener is refused, and nothing changes
            b.send_json({"type": "table_allow_joiners", "on": False})
            err = _drain(b, "error")
            assert err["code"] == "not_opener"
            assert room.allow_joiners is True
            # the opener's switch works
            a.send_json({"type": "table_allow_joiners", "on": False})
            _wait_for(lambda: room.allow_joiners is False)
            # the opener leaves mid-game: the controls pass to the next person
            a.send_json({"type": "table_leave"})
            _drain(a, "left")
            _wait_for(lambda: room.host == want)
            assert srv.state_for(room, want)["opener"] == want
            b.send_json({"type": "table_allow_joiners", "on": True})
            _wait_for(lambda: room.allow_joiners is True)


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
                sd.bot_announced = True     # even so, the reservation holds

        client.portal.call(drop_seat_1)
        _real_play(client, a, room)
        _wait_for(lambda: _my_turn(room, 1))
        time.sleep(0.3)
        assert _plays_by(room, 1) == 0 and srv._auto_mode(room, 1) is None


def test_a_refused_human_play_is_logged_with_its_cards(client, monkeypatch):
    import json

    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _banker_leads(client, a, monkeypatch, bot_delay=0.05)
        _wait_for(lambda: room.bot_task is None or room.bot_task.done())
        a.send_json({"type": "next_round"})                  # not a play: not logged
        _drain(a, "error")
        _real_play(client, a, room)                          # seat 0 led; now off turn
        ids = sorted(room.ids[0])[:1]
        codes = [room.ids[0][i] for i in ids]
        a.send_json({"type": "play", "card_ids": ids})
        error = _drain(a, "error")
        records = [json.loads(line) for line in
                   (srv.LOG_DIR / f"{code}.jsonl").read_text().splitlines()]
        refused = [r for r in records if r["e"] == "play_refused"]
        assert len(refused) == 1
        [rec] = refused
        assert rec["seat"] == 0 and rec["attempted_cards"] == codes
        assert rec["reason"] == error["message"] and rec["code"] == "IllegalPlay"
        assert rec["phase"] == "play" and rec["round"] == 1


def test_seat_presence_and_ranked_are_in_the_room_log(client, clock):
    import json

    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a)
        want = next(i for i, sd in enumerate(room.seats) if sd.is_bot)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "james", "seat": want})
            _drain(b, "state")
        _wait_for(lambda: not room.seats[want].connected)
        clock["v"] += srv.TAKEOVER_AFTER + 1        # past the hold: a name takes it back
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "james"})
            _drain(b, "state")
            assert room.seats[want].connected
            b.send_json({"type": "table_leave"})
            _drain(b, "left")
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


def test_seat_disconnected_records_the_close_code_and_socket_timing(client, clock):
    import json

    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a)
        want = next(i for i, sd in enumerate(room.seats) if sd.is_bot)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "james", "seat": want})
            _drain(b, "state")
            clock["v"] += 3.04
            b.send_json({"type": "no_such_action"})
            _drain(b, "error")
            clock["v"] += 2.0
        _wait_for(lambda: not room.seats[want].connected)
        records = [json.loads(line) for line in
                   (srv.LOG_DIR / f"{code}.jsonl").read_text().splitlines()]
        [rec] = [r for r in records if r["e"] == "seat_disconnected"]
        assert set(rec) == {"t", "room", "round", "e", "seat", "reason",
                            "close_code", "socket_age_s", "since_last_frame_s"}
        assert (rec["seat"], rec["reason"]) == (want, "socket_closed")
        assert rec["close_code"] == 1000
        assert (rec["socket_age_s"], rec["since_last_frame_s"]) == (5.0, 2.0)


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
            b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "jerry", "token": token})
            _drain(b, "state")
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


def test_a_created_room_allows_joiners_by_default_and_casual_rooms_take_the_switch(client):
    from shengji.api import server as srv
    with client.websocket_connect("/ws") as host:
        first, _ = _created_room(host)
        code = first["room"]
        assert srv.rooms[code].allow_joiners is True and first["allow_joiners"] is True
        host.send_json({"type": "table_allow_joiners", "on": False})
        assert _state_until(host, lambda m: m["allow_joiners"] is False)["you"] == 0
        assert srv.rooms[code].allow_joiners is False


def test_a_deliberate_leave_is_covered_by_the_pump_at_once(client, monkeypatch):
    """A seat whose owner pressed Leave moves at the bot pace inside what
    would be a disconnect's takeover window; a reconnect clears the mark."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        _, room = _banker_leads(client, a, monkeypatch, bot_delay=0.05)
        _wait_for(lambda: room.bot_task is None or room.bot_task.done())

        async def leave_seat_1():
            async with room.lock:
                sd = room.seats[1]
                sd.is_bot, sd.name, sd.connected = False, "james", False
                sd.left_at = srv.now()
                sd.left_by_choice = True

        client.portal.call(leave_seat_1)
        _real_play(client, a, room)
        _wait_for(lambda: _plays_by(room, 1) == 1, timeout=3.0)
        seat = srv.state_for(room, 0)["players"][1]
        assert seat["left"] is True and seat["takeover_in"] is None


def test_attach_clears_a_deliberate_leave():
    from shengji.api import server as srv

    seat = srv.Seat(name="james", left_by_choice=True)
    room = srv.Room(code="ZZZZ", seats=[seat])

    class _Ws:
        async def send_json(self, payload):
            return None

    import asyncio

    async def attach():
        srv._attach(room, seat, _Ws())
        if seat.writer is not None:
            seat.writer.cancel()

    asyncio.run(attach())
    assert seat.connected and not seat.left_by_choice


def test_frames_count_down_the_declare_window(client, monkeypatch):
    from shengji.ai.heuristic import HeuristicBot
    from shengji.api import server as srv

    monkeypatch.setattr(HeuristicBot, "decide_declare", lambda *a, **kw: None)
    monkeypatch.setattr(srv, "DEAL_DELAY", 0.0)
    with client.websocket_connect("/ws") as a:
        room_frame, st = _created_room(a)
        code = room_frame["room"]
        seen = []
        for _ in range(400):
            seen.append((st["phase"], st["declare_deadline"]))
            if st["phase"] not in ("deal", "declare"):
                break
            st = _drain(a, "state")
        declaring = [d for ph, d in seen if ph == "declare"]
        assert declaring, "no frame in the declare window"
        assert all(d is not None and 0 <= d <= srv.DECLARE_GRACE for d in declaring), [x for x in seen if x[0] != "deal"]
        assert all(d is None for ph, d in seen if ph != "declare")
        assert srv.rooms[code].declare_until is None


# A Duo is a table: its opener's own Play table with the partner seat held
# for the first single who joins by the table's code.
@pytest.fixture()
def duo_queue(client, tmp_path, monkeypatch):
    """Three signed-in players and the server's matchmaker on a still
    clock, driven by explicit ticks."""
    from shengji.api import accounts
    from shengji.api import server as srv
    from tests.test_accounts import _claims

    store = accounts.Store(tmp_path / "accounts" / "duo.sqlite3")
    monkeypatch.setattr(accounts, "STORE", store)
    users = []
    for sub, name in (("duo-ann", "Ann"), ("duo-bo", "Bo"), ("duo-cy", "Cy"), ("duo-di", "Di")):
        user = store.upsert_user(_claims(sub=sub, email=f"{sub}@example.com",
                                         name=name, given_name=name))
        users.append((user["id"], {"cookie": f"sj_session={store.create_session(user['id'])}"}))
    mmk = srv.MATCHMAKER
    mmk.reset()
    saved = (mmk.clock, mmk.autorun)
    now = [10_000.0]
    mmk.clock, mmk.autorun = (lambda: now[0]), False
    try:
        yield srv, users
    finally:
        mmk.reset()
        mmk.clock, mmk.autorun = saved


def test_ws_a_duo_table_seats_its_code_joiner_in_the_held_seat_and_starts_a_rated_room(
        client, duo_queue):
    srv, ((ann, ha), (bo, hb), (cy, hc), _) = duo_queue
    with client.websocket_connect("/ws", headers=ha) as a, \
            client.websocket_connect("/ws", headers=hb) as b, \
            client.websocket_connect("/ws", headers=hc) as c:
        a.send_json({"type": "queue_join", "mode": "ranked", "duo": True})
        own = _next_where(a, "queue_state", lambda m: m.get("queued"))
        assert own["duo"] is True and own["held_seat"] == 2 and own["table"] is None
        code = own["code"]
        c.send_json({"type": "queue_join", "mode": "ranked"})       # a stranger on Play
        table = _next_where(c, "queue_state", lambda m: m.get("table"))["table"]
        assert table["you"] == 1 and table["held_seat"] == 2 and table["code"] == code
        b.send_json({"type": "table_peek", "code": code})
        assert _drain(b, "room_seats")["table"] is True
        b.send_json({"type": "table_join", "code": code})            # the friend's link
        mine = _next_where(b, "queue_state", lambda m: m.get("table"))
        assert mine["table"]["you"] == 2 and mine["held_seat"] is None and mine["duo"] is True
        assert _drain(b, "party")["table"] is True
        b.send_json({"type": "table_allow_joiners", "on": False})
        assert _drain(b, "error")["code"] == "not_opener"
        # each Duo player taps Start; the pair is ready once both have
        b.send_json({"type": "table_start"})
        seen = _next_where(a, "queue_state", lambda m: m["table"]["ready"] == 1)["table"]
        assert seen["seats"][2]["ready"] and not seen["you_ready"]
        c.send_json({"type": "table_start"})
        _next_where(a, "queue_state", lambda m: m["table"]["ready"] == 2)
        assert srv.MATCHMAKER.tables                       # the pair is not ready yet
        a.send_json({"type": "table_start"})
        started = [_drain(ws, "match_started") for ws in (a, b, c)]
        assert len({s["room"] for s in started}) == 1 and all(s["rated"] for s in started)
        assert started[0]["room"] == code                  # the invite link leads here
        _drain(a, "state")
        room = srv.rooms[code]
        assert [s.user_id for s in room.seats] == [ann, cy, bo, None]
        assert room.ratings is not None and room.ratings.present == {0: ann, 1: cy, 2: bo}
        assert srv.MATCHMAKER.entries == {} and srv.MATCHMAKER.tables == {}


def test_ws_a_duo_that_starts_without_its_friend_keeps_the_held_seat_for_the_friends_join(
        client, duo_queue):
    srv, ((ann, ha), (bo, hb), (cy, hc), _) = duo_queue
    with client.websocket_connect("/ws", headers=ha) as a:
        a.send_json({"type": "queue_join", "mode": "casual", "duo": True})
        code = _next_where(a, "queue_state", lambda m: m.get("queued"))["code"]
        a.send_json({"type": "table_start_bots"})
        assert _drain(a, "match_started")["room"] == code
        _drain(a, "state")
        room = srv.rooms[code]
        assert room.friend_seat == 2 and room.seats[2].is_bot
        with client.websocket_connect("/ws", headers=hb) as b:
            b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "Bo"})
            assert _drain(b, "state")["you"] == 2      # the late friend
            assert room.seats[2].user_id == bo
            with client.websocket_connect("/ws", headers=hc) as c:
                c.send_json({"type": "table_join", "expect": "room", "code": code, "name": "Cy"})
                assert _drain(c, "state")["you"] == 1  # the usual first bot seat


def test_ws_a_duo_split_at_a_strangers_table_stays_seated_and_the_room_promises_no_seat(
        client, duo_queue):
    srv, ((ann, ha), (bo, hb), (cy, hc), (di, hd)) = duo_queue
    with client.websocket_connect("/ws", headers=ha) as a, \
            client.websocket_connect("/ws", headers=hb) as b, \
            client.websocket_connect("/ws", headers=hc) as c, \
            client.websocket_connect("/ws", headers=hd) as d:
        c.send_json({"type": "queue_join", "allow_joiners": False})   # first in line, private
        cy_code = _next_where(c, "queue_state", lambda m: m.get("queued"))["code"]
        a.send_json({"type": "queue_join", "duo": True})
        code = _next_where(a, "queue_state", lambda m: m.get("queued"))["code"]
        b.send_json({"type": "table_join", "code": code})
        _next_where(b, "queue_state", lambda m: m.get("duo"))
        c.send_json({"type": "table_allow_joiners", "on": True})     # the pair sits at Cy's table
        at_cy = _next_where(a, "queue_state", lambda m: m.get("table") and m["table"]["code"] == cy_code)
        b.send_json({"type": "table_leave"})
        mine = _next_where(a, "queue_state", lambda m: m.get("table") and not m.get("duo"))
        assert mine["table"]["id"] == at_cy["table"]["id"]            # Ann stays where she is
        assert mine["held_seat"] is None and mine["table"]["held_seat"] is None
        assert mine["table"]["you"] == at_cy["table"]["you"]
        d.send_json({"type": "queue_join"})
        _next_where(d, "queue_state", lambda m: m.get("table"))
        for ws in (a, c, d):
            ws.send_json({"type": "table_start"})
        started = _drain(a, "match_started")
        assert started["room"] == cy_code                  # the opener's code is the room's
        _drain(a, "state")
        room = srv.rooms[cy_code]
        assert room.friend_seat is None
        (open_seat,) = [i for i, sd in enumerate(room.seats) if sd.is_bot]
        # Ann's own code ended with the table; Bo joins the room the usual way
        b.send_json({"type": "table_peek", "code": code})
        assert _drain(b, "error")["peek"] == code
        b.send_json({"type": "table_join", "expect": "room", "code": cy_code, "name": "Bo"})
        for _ in range(80):
            pj = room.pending_joins.get(open_seat)
            if (pj is not None and pj.uid == bo) or room.seats[open_seat].user_id == bo:
                break
            _drain(a, "state")
        else:
            raise AssertionError("Bo did not take the open seat")


@pytest.mark.parametrize("start", ["absent", False, "true", 1, None])
def test_create_room_seats_bots_and_starts_at_once(client, start):
    """Every create_room starts its game: the creator gets the room frame
    the client saves the room from, with only them in it, then the game."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "create_room", "name": "P",
                      **({} if start == "absent" else {"start": start})})
        assert _next(ws, "resume")["token"]
        assert _next(ws, "chat_history")["messages"] == []
        room_msg = _next(ws, "room")
        assert [p["name"] for p in room_msg["players"]] == ["P"]
        assert "ready" not in room_msg and "start_now_in" not in room_msg
        state = _next(ws, "state")
        assert state["you"] == 0
        room = srv.rooms[room_msg["room"]]
        assert [sd.name for sd in room.seats] == ["P", "Bot 1", "Bot 2", "Bot 3"]
        assert [sd.is_bot for sd in room.seats] == [False, True, True, True]
        assert room.host == 0 and room.game is not None


def _refuse_the_first_start(monkeypatch, error):
    """``_start_game`` refuses the first room it is asked to start with
    ``error`` and starts every later one; returns the refused room codes."""
    from shengji.api import server as srv

    real = srv._start_game
    refused = []

    def start(room):
        if not refused:
            refused.append(room.code)
            raise error
        return real(room)

    monkeypatch.setattr(srv, "_start_game", start)
    return refused


@pytest.mark.parametrize("kind", ["illegal", "same_device"])
def test_a_refused_created_start_discards_the_room(client, monkeypatch, kind):
    from shengji.api import server as srv

    error = (srv.IllegalPlay("Refused for the test.") if kind == "illegal"
             else srv.SameDevice("Refused for the test."))
    refused = _refuse_the_first_start(monkeypatch, error)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "create_room", "name": "P"})
        code = _drain(ws, "room")["room"]
        err = _next(ws, "error")
        assert err["message"] == "Refused for the test."
        assert err.get("code") == (None if kind == "illegal" else "same_device")
        assert _next(ws, "left") == {"type": "left"}
        assert refused == [code] and code not in srv.rooms
        # the socket is back in the lobby and can create a room of its own
        ws.send_json({"type": "create_room", "name": "P"})
        again = _drain(ws, "room")["room"]
        assert _drain(ws, "state")["you"] == 0
        assert again != code and srv.rooms[again].game is not None


def test_create_room_start_true_seats_bots_and_starts(client):
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "create_room", "name": "P", "start": True,
                      "start_level": "5"})
        room_msg = _drain(ws, "room")
        assert [p["name"] for p in room_msg["players"]] == ["P"]
        state = _drain(ws, "state")
        assert state["you"] == 0 and state["levels"] == ["5", "5"]
        room = srv.rooms[room_msg["room"]]
        assert [sd.name for sd in room.seats] == ["P", "Bot 1", "Bot 2", "Bot 3"]
        assert [sd.is_bot for sd in room.seats] == [False, True, True, True]
        assert room.host == 0 and room.game is not None
        ws.send_json({"type": "table_start_now"})
        # the deal streams a state frame per card ahead of the refusal
        assert _drain(ws, "error")["message"] == "Game already started."


@pytest.mark.parametrize("kind", ["add_bot", "remove_bot", "remove_player", "set_ranked"])
def test_a_retired_lobby_control_is_refused_and_still_counted(client, monkeypatch, kind):
    """An out-of-date page that still sends one is told to reload, outside a
    room and from a seat alike, and the health counters still see it."""
    from shengji.api import server as srv

    monkeypatch.setattr(srv, "ACTIVITY", srv.Activity())
    retired = {"type": "error", "code": "retired",
               "message": "This page is out of date. Reload to play."}
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": kind, "seat": 1, "on": True})
        assert _drain(ws, "error") == retired
        code = _room_with_bots(ws)
        seats = [(sd.name, sd.is_bot) for sd in srv.rooms[code].seats]
        ws.send_json({"type": kind, "seat": 1, "on": True})
        assert _drain(ws, "error") == retired
        assert [(sd.name, sd.is_bot) for sd in srv.rooms[code].seats] == seats
    assert srv.ACTIVITY.legacy_messages[kind] == 2


@pytest.mark.parametrize("msg", [
    {"type": "table_move", "seat": 1},
    {"type": "table_start"},
    {"type": "table_start_now"},
    {"type": "table_start_bots"},
    {"type": "table_start_level", "start_level": "5"},
], ids=lambda m: m["type"])
def test_a_lobby_control_in_a_running_room_is_refused(client, msg):
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as ws:
        code = _room_with_bots(ws)
        room = srv.rooms[code]
        seats = [(sd.name, sd.is_bot) for sd in room.seats]
        ws.send_json(msg)
        err = _drain(ws, "error")
        assert err == {"type": "error", "message": "Game already started."}
        assert [(sd.name, sd.is_bot) for sd in room.seats] == seats
        assert room.start_level == "2" and room.game.levels == ("2", "2")


def test_a_room_whose_game_has_not_started_cannot_be_joined(client):
    from shengji.api import server as srv

    srv.rooms["WAIT"] = srv.Room(code="WAIT")
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "table_join", "expect": "room", "code": "WAIT", "name": "james"})
        assert _drain(ws, "error")["code"] == "room_not_found"
    assert srv.rooms["WAIT"].seats == []


def test_a_seat_taken_mid_game_by_code_comes_back_by_its_token_and_plays_on(client, monkeypatch):
    """A friend who takes a bot's seat in a game already on is sent no
    ``room`` frame: its first state (which names the room) and its ``resume``
    token are what a reconnect asks with. A move from a socket holding no
    seat is refused with ``no_room``, which the page answers by asking for
    the seat back."""
    with client.websocket_connect("/ws") as a:
        code, room = _banker_leads(client, a, monkeypatch, bot_delay=0.0)
        with client.websocket_connect("/ws") as c:
            c.send_json({"type": "table_join", "expect": "room", "code": code,
                         "name": "Cee", "seat": 2})
            seen = _frames_until(c, lambda m: m.get("type") == "state" and m.get("you") == 2
                                 and not m.get("joining_you"), "C's seat", DRAIN_TIMEOUT)
            kinds = [m.get("type") for m in seen]
            assert "room" not in kinds
            assert seen[-1]["room"] == code
            token = next(m for m in seen if m.get("type") == "resume")["token"]
            assert not room.seats[2].is_bot and room.seats[2].name == "Cee"
        _wait_for(lambda: not room.seats[2].connected)
        with client.websocket_connect("/ws") as c2:
            c2.send_json({"type": "play", "card_ids": []})
            refused = _drain(c2, "error")
            assert refused["code"] == "no_room" and refused["message"] == "Join a room first."
            c2.send_json({"type": "table_join", "expect": "room", "code": code,
                          "name": "Cee", "token": token})
            assert _next_where(c2, "state", lambda m: m["you"] == 2)["room"] == code
            assert room.seats[2].connected and room.seats[2].name == "Cee"
            _real_play(client, a, room, seat=0)
            _wait_for(lambda: _my_turn(room, 2))
            _real_play(client, c2, room, seat=2)


def test_a_held_seat_is_not_taken_back_by_its_name_alone(client, clock):
    """During the hold window a dropped seat (and its hand) is its owner's:
    typing the owner's name is refused; the owner's token still resumes it,
    and after the window the name path is the seat picker's permission."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a)
        want = next(i for i, sd in enumerate(room.seats) if sd.is_bot)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "table_join", "expect": "room", "code": code,
                         "name": "james", "seat": want})
            _drain(b, "state")
            token = room.seats[want].token
        _wait_for(lambda: not room.seats[want].connected)
        with client.websocket_connect("/ws") as x:
            x.send_json({"type": "table_join", "expect": "room", "code": code, "name": "James "})
            assert _drain(x, "error")["code"] == "seat_reserved"
        assert not room.seats[want].connected and room.seats[want].token == token
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "table_join", "expect": "room", "code": code,
                         "name": "james", "token": token})
            assert _drain(b, "state")["you"] == want
            assert room.seats[want].connected and room.seats[want].token == token
        _wait_for(lambda: not room.seats[want].connected)
        clock["v"] += srv.TAKEOVER_AFTER + 1
        with client.websocket_connect("/ws") as x:
            x.send_json({"type": "table_join", "expect": "room", "code": code, "name": "james"})
            assert _drain(x, "state")["you"] == want
            assert room.seats[want].token != token



def test_a_seat_left_by_choice_is_taken_back_by_its_name(client, clock):
    """Leave ends the hold at once (the bot covers the seat with no grace),
    and a Leave clears the saved token: the leaver coming back by the code
    under the same name, inside 60 s, sits in that seat again. A seat that
    only dropped stays held against its name alone."""
    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "james"})
            _drain(b, "state")
            a.send_json({"type": "table_leave"})
            _drain(a, "left")
            assert room.seats[0].left_by_choice and not room.seats[0].connected
            with client.websocket_connect("/ws") as back:
                back.send_json({"type": "table_join", "expect": "room", "code": code,
                                "name": "Jerry ", "seat": 0})
                st = _drain(back, "state")
                assert st["you"] == 0 and len(st["hand"]) > 0
                assert room.seats[0].connected and not room.seats[0].left_by_choice


def test_a_ranked_table_counts_an_accounts_seat_by_the_account(client):
    """One seat per account at a ranked table: a seat the account holds
    counts as held whatever queue id the seat carries, so neither an
    invite link nor an open-table confirm gives it a second hand."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a)
        room.matched = True
        mine = room.seats[0]
        mine.user_id, mine.queue_id = 41, None
        assert srv._holds_seat(room, 41)
        assert not srv._holds_seat(room, 42)
        assert not srv._holds_seat(room, -41)            # a guest id is not the account

        class _Conn:
            device = None
        room.allow_joiners = True
        out = client.portal.call(srv.join_by_invite, room, None, 41, "Again", _Conn())
        assert out == "table_full"
        assert sum(1 for sd in room.seats if not sd.is_bot and sd.user_id == 41) == 1


def test_http_responses_carry_the_security_headers_and_the_api_schema_is_off(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.headers["strict-transport-security"].startswith("max-age=")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path


def test_a_live_table_deals_and_names_itself_from_the_os_generator(client):
    import random
    import secrets as _secrets

    from shengji.api import server as srv

    assert isinstance(srv._ROOM_CODE_RNG, _secrets.SystemRandom)
    with client.websocket_connect("/ws") as a:
        _, room = _start_game(client, a)
        assert isinstance(room.game.rng, random.SystemRandom)


# ------------------------------------------------- per-address limits
@pytest.fixture()
def limit_clock(monkeypatch):
    """The limits' clock, advanced by hand."""
    from shengji.api import limits

    t = {"v": 5000.0}
    monkeypatch.setattr(limits, "clock", lambda: t["v"])
    return t


def test_sockets_per_address_are_capped_and_freed_on_close(client, monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    from shengji.api import limits

    monkeypatch.setattr(limits, "SOCKETS_PER_IP", 2)
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws"):
        with pytest.raises(WebSocketDisconnect) as refused:
            with client.websocket_connect("/ws"):
                pass
        assert refused.value.code == 1013
        assert limits.SOCKETS.open == {"testclient": 2}
        a.send_json({"type": "ping", "nonce": 1})
        assert _drain(a, "pong")["nonce"] == 1
    assert limits.SOCKETS.open == {}
    with client.websocket_connect("/ws") as c:
        c.send_json({"type": "ping", "nonce": 2})
        assert _drain(c, "pong")["nonce"] == 2


def test_live_rooms_per_address_and_in_total_are_capped(client, monkeypatch):
    from shengji.api import limits

    monkeypatch.setattr(limits, "ROOMS_PER_IP", 2)
    with ExitStack() as stack:
        for n in range(2):
            ws = stack.enter_context(client.websocket_connect("/ws"))
            _created_room(ws, name=f"p{n}")
        extra = stack.enter_context(client.websocket_connect("/ws"))
        extra.send_json({"type": "create_room", "name": "p2"})
        assert _drain(extra, "error")["code"] == "rate_limited"
        monkeypatch.setattr(limits, "ROOMS_PER_IP", 10)
        monkeypatch.setattr(limits, "MAX_ROOMS", 2)
        extra.send_json({"type": "create_room", "name": "p2"})
        assert _drain(extra, "error")["code"] == "server_busy"
        monkeypatch.setattr(limits, "MAX_ROOMS", 3)
        extra.send_json({"type": "create_room", "name": "p2"})
        assert _drain(extra, "room")["room"]


def test_room_creates_per_address_are_rate_limited(client, monkeypatch, limit_clock):
    from shengji.api import limits

    monkeypatch.setattr(limits.CREATES, "limit", 1)
    with client.websocket_connect("/ws") as a:
        _created_room(a)
        a.send_json({"type": "table_leave"})
        _drain(a, "left")
        a.send_json({"type": "create_room", "name": "again"})
        assert _drain(a, "error")["code"] == "rate_limited"
        limit_clock["v"] += limits.CREATES.window + 1
        a.send_json({"type": "create_room", "name": "again"})
        assert _drain(a, "room")["room"]


def test_code_lookups_that_name_nothing_are_bounded_per_address(client, monkeypatch, limit_clock):
    """A sweep of the code space is bounded per address, not per socket:
    past its misses an address learns nothing, even about a live code."""
    from shengji.api import limits

    monkeypatch.setattr(limits.MISSES, "limit", 3)
    with client.websocket_connect("/ws") as host:
        code = _room_with_bots(host)
        for n in range(3):
            with client.websocket_connect("/ws") as s:      # a fresh socket each time
                s.send_json({"type": "table_peek", "code": f"ZZZ{n}"})
                err = _drain(s, "error")
                assert err["code"] == "room_not_found" and err["peek"] == f"ZZZ{n}"
        with client.websocket_connect("/ws") as s:
            s.send_json({"type": "table_peek", "code": code})
            err = _drain(s, "error")
            assert err["code"] == "room_not_found" and err["peek"] == code
            s.send_json({"type": "table_join", "expect": "room", "code": code, "name": "x"})
            assert _drain(s, "error")["code"] == "rate_limited"
        limit_clock["v"] += limits.MISSES.window + 1
        with client.websocket_connect("/ws") as s:
            s.send_json({"type": "table_peek", "code": code})
            assert _drain(s, "room_seats")["room"] == code


def test_code_lookups_per_address_are_rate_limited(client, monkeypatch, limit_clock):
    from shengji.api import limits

    monkeypatch.setattr(limits.LOOKUPS, "limit", 2)
    with client.websocket_connect("/ws") as host:
        code = _room_with_bots(host)
        with client.websocket_connect("/ws") as s:
            for _ in range(2):
                s.send_json({"type": "table_peek", "code": code})
                _drain(s, "room_seats")
            s.send_json({"type": "table_peek", "code": code})
            assert _drain(s, "error")["code"] == "room_not_found"
            limit_clock["v"] += limits.LOOKUPS.window + 1
            s.send_json({"type": "table_peek", "code": code})
            _drain(s, "room_seats")


def test_queue_starts_per_address_are_rate_limited(client, monkeypatch, limit_clock):
    from shengji.api import limits

    monkeypatch.setattr(limits.QUEUE_STARTS, "limit", 0)
    with client.websocket_connect("/ws?device=" + "q" * 22) as a:
        a.send_json({"type": "queue_join"})
        assert _drain(a, "error")["code"] == "rate_limited"


def test_the_server_reads_websocket_messages_of_at_most_64_kib(monkeypatch):
    import uvicorn

    from shengji.api import server as srv

    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: seen.update(kw))
    srv.main()
    assert seen["ws_max_size"] == 64 * 1024


def test_guest_ids_are_bounded_and_never_reused(monkeypatch):
    from shengji.api import limits

    monkeypatch.setattr(limits, "MAX_GUEST_IDS", 2)
    ids = limits.GuestIds()
    a, b = ids.id_for("a" * 22), ids.id_for("b" * 22)
    assert (a, b) == (-1, -2)
    assert ids.id_for("a" * 22) == -1          # seen again: now the newest
    c = ids.id_for("c" * 22)
    assert c == -3 and len(ids) == 2
    assert "b" * 22 not in ids and ids.get("a" * 22) == -1
    assert ids.id_for("b" * 22) == -4          # forgotten, so a new id


def test_a_queue_start_at_the_room_cap_keeps_its_place_until_a_room_closes(client, monkeypatch):
    """The whole-server room cap holds for rooms the queue opens too: at the
    cap a start with bots is refused ``server_busy`` and the entry stays
    queued at its own table, no socket bound to any room; once a room
    closes the same start opens one."""
    from shengji.api import limits
    from shengji.api import server as srv

    monkeypatch.setattr(limits, "MAX_ROOMS", 1)
    mmk = srv.MATCHMAKER
    with client.websocket_connect("/ws") as host:
        _created_room(host)
        with client.websocket_connect("/ws?device=" + "Z" * 22) as newcomer:
            newcomer.send_json({"type": "queue_join", "name": "Guest"})
            _next_where(newcomer, "queue_state", lambda m: m.get("queued"))
            conn = next(c for c in mmk.conns.values() if c.device == "Z" * 22)
            entry = mmk._entry(conn.queue_id)
            table_id = entry.table.id
            newcomer.send_json({"type": "table_start_bots"})
            refused = _drain(newcomer, "error")
            assert refused["code"] == "server_busy" and refused["message"] == limits.BUSY_MESSAGE
            assert len(srv.rooms) == 1
            assert mmk._entry(conn.queue_id) is entry and entry.table.id == table_id
            assert conn.adopted is None and not conn.in_room
            assert not any(s.queue_id == conn.queue_id for r in srv.rooms.values()
                           for s in r.seats if s is not None)
            host.send_json({"type": "table_leave"})
            _drain(host, "left")
            assert not srv.rooms
            newcomer.send_json({"type": "table_start_bots"})
            _drain(newcomer, "match_started")
            assert _drain(newcomer, "state")["you"] == 0
            assert len(srv.rooms) == 1 and mmk._entry(conn.queue_id) is None


def test_competing_room_opens_at_one_below_the_cap_admit_exactly_one(client, monkeypatch):
    """Two queue starts and a ``create_room`` sent together with one room
    left under the cap: exactly one opens a room, the others are told
    ``server_busy`` and the two queued players who lost stay queued."""
    from shengji.api import limits
    from shengji.api import server as srv

    monkeypatch.setattr(limits, "MAX_ROOMS", 2)
    mmk = srv.MATCHMAKER
    with ExitStack() as stack:
        host = stack.enter_context(client.websocket_connect("/ws"))
        _created_room(host)
        queued = []
        for d, mode in (("X", "ranked"), ("Y", "casual")):   # two tables, not one
            ws = stack.enter_context(client.websocket_connect("/ws?device=" + d * 22))
            ws.send_json({"type": "queue_join", "name": d, "mode": mode})
            _next_where(ws, "queue_state", lambda m: m.get("queued"))
            queued.append(ws)
        creator = stack.enter_context(client.websocket_connect("/ws"))
        for ws in queued:
            ws.send_json({"type": "table_start_bots"})
        creator.send_json({"type": "create_room", "name": "c"})
        outcomes = [_frames_until(ws, lambda m: m.get("type") == "state"
                                  or (m.get("type") == "error" and m.get("code") == "server_busy"),
                                  "a state or server_busy")[-1]
                    for ws in (*queued, creator)]
        won = [m["type"] == "state" for m in outcomes]
        assert sum(won) == 1, outcomes
        assert len(srv.rooms) == 2
        still = [c for c in mmk.conns.values()
                 if c.device in ("X" * 22, "Y" * 22) and not c.in_room]
        assert len(still) == 2 - sum(won[:2])
        assert all(mmk._entry(c.queue_id) is not None and c.adopted is None for c in still)


def test_the_matched_room_factory_keeps_the_room_cap_whoever_calls_it(client, monkeypatch):
    """With the queue's own check bypassed, ``start_matched_room`` still
    refuses at the cap before building anything: no room, no seat bound."""
    from shengji.api import limits
    from shengji.api import server as srv

    monkeypatch.setattr(limits, "MAX_ROOMS", 1)
    monkeypatch.setattr(srv.MATCHMAKER, "room_capacity", lambda: True)
    with client.websocket_connect("/ws") as host:
        _created_room(host)
        with client.websocket_connect("/ws?device=" + "W" * 22) as newcomer:
            newcomer.send_json({"type": "queue_join", "name": "Guest"})
            _next_where(newcomer, "queue_state", lambda m: m.get("queued"))
            conn = next(c for c in srv.MATCHMAKER.conns.values() if c.device == "W" * 22)
            newcomer.send_json({"type": "table_start_bots"})
            assert _drain(newcomer, "error")["code"] == "start_failed"
            assert len(srv.rooms) == 1
            assert conn.adopted is None and not conn.in_room


def _queue_stale_frame_behind_a_resume(client, frame):
    """A replacement's resume and then the old socket's ``frame`` both wait on the room lock while the old
    socket still owns the seat; releasing the lock lets the replacement attach first."""
    import asyncio
    from contextlib import ExitStack
    from shengji.api import server as srv
    stack = ExitStack()
    host = stack.enter_context(client.websocket_connect("/ws"))
    code = _room_with_bots(host, "host")
    old = stack.enter_context(client.websocket_connect("/ws"))
    old.send_json({"type": "table_join", "expect": "room", "code": code, "name": "bob", "seat": 2})
    token = _drain(old, "resume")["token"]
    _drain(old, "state")
    room = srv.rooms[code]
    new = stack.enter_context(client.websocket_connect("/ws"))
    client.portal.call(room.lock.acquire)
    try:
        new.send_json({"type": "table_join", "expect": "room", "code": code, "name": "bob", "token": token})
        _wait_for(lambda: room.lock._waiters and len(room.lock._waiters) == 1)
        old.send_json(frame)
        _wait_for(lambda: len(room.lock._waiters) == 2)
    finally:
        client.portal.call(room.lock.release)
    _drain(new, "state")
    _wait_for(lambda: not room.lock._waiters)
    client.portal.call(asyncio.sleep, 0.01)
    return stack, room, old, new


def test_a_play_queued_before_a_resume_is_refused_once_the_resume_attaches(client, monkeypatch):
    """The ownership check runs again under the room lock, so a play the replaced socket sent while the
    resume was queued never reaches the action handler."""
    from shengji.api import server as srv
    reached = []
    original = srv.handle_action

    async def observed(room_arg, seat, msg):
        if msg.get("marker"):
            reached.append(room_arg.seats[seat].gen)
        return await original(room_arg, seat, msg)

    monkeypatch.setattr(srv, "handle_action", observed)
    stack, room, old, new = _queue_stale_frame_behind_a_resume(client, {"type": "play", "card_ids": [], "marker": True})
    with stack:
        assert not reached
        assert _drain(old, "error")["code"] == "stale_connection"


def test_a_leave_queued_before_a_resume_does_not_leave_the_resumed_seat(client):
    """A Leave the replaced socket sent while the resume was queued is refused under the lock: the seat
    stays with the new socket, connected and not left by choice."""
    stack, room, old, new = _queue_stale_frame_behind_a_resume(client, {"type": "table_leave"})
    with stack:
        assert _drain(old, "error")["code"] == "stale_connection"
        seat = room.seats[2]
        assert seat.connected and not getattr(seat, "left_by_choice", False)
        assert not any("bob left" in (m.get("text") or "") for m in getattr(room, "chat", []) if isinstance(m, dict))


def test_a_leave_owed_across_a_drop_resumes_by_token_and_is_covered_at_once(client, monkeypatch):
    """The page's owed Leave (ws.ts): a seat whose socket died is taken back
    by its token on a fresh socket and left in the next frame, without
    waiting for the resume's state. The seat is left by choice, so the bot
    covers it at once instead of after the dropped seat's hold, and the
    leave reaches the ratings as a Leave."""
    from shengji.api import server as srv

    told = []
    real = srv.ratings.seat_left
    monkeypatch.setattr(srv.ratings, "seat_left", lambda room, seat: (told.append(seat), real(room, seat)))

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a, to_play=True)
        want = next(i for i, sd in enumerate(room.seats) if sd.is_bot)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "james", "seat": want})
            _drain(b, "state")
        dropped = room.seats[want]
        assert not dropped.connected and not dropped.left_by_choice
        assert srv._reserved(room, want) and told == []
        with client.websocket_connect("/ws") as back:
            back.send_json({"type": "table_join", "expect": "room", "code": code, "name": "james",
                            "token": dropped.token})
            back.send_json({"type": "table_leave"})
            _drain(back, "left")
        left = room.seats[want]
        assert left is dropped and not left.connected and left.left_by_choice
        assert told == [want]
        st = srv.state_for(room, 0)
        seat = next(p for p in st["players"] if p["seat"] == want)
        assert seat["left"] is True and seat["takeover_in"] is None

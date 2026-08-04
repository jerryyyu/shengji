"""Websocket-level tests for the multiplayer room protocol.

These drive the REAL socket via TestClient rather than calling handlers
directly: `peek_room` shipped completely unimplemented on the server while
the client sent it and the suite stayed green, because nothing here spoke
the wire protocol (2026-08-03).
"""
from __future__ import annotations

import os

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
    with TestClient(srv.app) as c:
        yield c
    # Rooms outlive a test's event loop; their asyncio.Lock binds to whichever
    # loop touches it first, so a leftover room makes the NEXT test fail with
    # "attached to a different loop". Tear down explicitly.
    for room in list(srv.rooms.values()):
        for task in (room.cleanup_task, room.deal_task,
                     getattr(room, "watchdog_task", None)):
            if task is not None:
                task.cancel()
    srv.rooms.clear()


def _drain(ws, want, tries=40):
    """Next message of type `want` (states/chat interleave freely)."""
    for _ in range(tries):
        m = ws.receive_json()
        if m.get("type") == want:
            return m
    raise AssertionError(f"no {want!r} message arrived")


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
        for _ in range(400):
            if st.get("phase") == "play":
                break
            st = _drain(a, "state", tries=400)
        assert st.get("phase") == "play", "round never reached the play phase"
    return code, srv.rooms[code]


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


def test_claim_during_bot_delay_is_atomic(client):
    """Claiming the seat whose bot turn is pending must cancel that bot move."""
    import asyncio

    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a, to_play=True)
        turn = room.round.turn
        assert turn is not None and room.round.phase == "play"
        if not room.seats[turn].is_bot:      # seat 0 (human) leads
            turn = next(i for i, sd in enumerate(room.seats) if sd.is_bot)
        hand_before = list(room.round.hands[turn])
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "join_room", "room": code,
                         "name": "sniper", "seat": turn})
            _drain(b, "state", tries=60)
            # pump_bots re-checks is_bot after sleeping; the seat is human now.
            assert not room.seats[turn].is_bot
            assert room.round.turn == turn, "bot moved for a claimed seat"
            assert list(room.round.hands[turn]) == hand_before
    del asyncio, srv


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


def _four_humans(client, a):
    """Room of 4 HUMANS mid-game — no bot seat anywhere."""
    from shengji.api import server as srv

    a.send_json({"type": "create_room", "name": "jerry"})
    code = _drain(a, "room")["room"]
    socks = []
    for n in ("amy", "bo", "cy"):
        w = client.websocket_connect("/ws").__enter__()
        w.send_json({"type": "join_room", "room": code, "name": n})
        _drain(w, "room")
        socks.append(w)
    a.send_json({"type": "start_game"})
    _drain(a, "state", tries=60)
    return code, srv.rooms[code], socks


def test_dropped_human_seat_is_claimable_not_locked(client):
    """A disconnected player's seat must never become unreachable."""
    with client.websocket_connect("/ws") as a:
        code, room, socks = _four_humans(client, a)
        socks[0].__exit__(None, None, None)          # amy drops
        assert not room.seats[1].connected and not room.seats[1].is_bot

        # Peek must advertise the seat as claimable.
        with client.websocket_connect("/ws") as p:
            p.send_json({"type": "peek_room", "room": code})
            seats = _drain(p, "room_seats")["seats"]
        assert seats[1]["claimable"] and not seats[1]["is_bot"]
        assert not seats[1]["connected"]

        # A blind join is told to choose rather than being refused outright.
        with client.websocket_connect("/ws") as q:
            q.send_json({"type": "join_room", "room": code, "name": "newbie"})
            err = _drain(q, "error")
            assert err["code"] == "choose_seat"

        # An explicit choice takes the seat over.
        with client.websocket_connect("/ws") as r:
            r.send_json({"type": "join_room", "room": code,
                         "name": "newbie", "seat": 1})
            st = _drain(r, "state", tries=60)
            assert st["you"] == 1
            assert len(st["hand"]) > 0, "took over a seat but got no hand"
        for w in socks[1:]:
            w.__exit__(None, None, None)


def test_reclaim_is_case_and_space_insensitive(client):
    """Coming back as 'Amy ' must reclaim the seat left by 'amy'."""
    with client.websocket_connect("/ws") as a:
        code, room, socks = _four_humans(client, a)
        socks[0].__exit__(None, None, None)
        with client.websocket_connect("/ws") as back:
            back.send_json({"type": "join_room", "room": code, "name": " Amy "})
            st = _drain(back, "state", tries=60)
            assert st["you"] == 1, "did not reclaim the original seat"
            assert room.seats[1].connected
        for w in socks[1:]:
            w.__exit__(None, None, None)


def test_takeover_of_dropped_human_is_announced_as_such(client):
    with client.websocket_connect("/ws") as a:
        code, room, socks = _four_humans(client, a)
        socks[0].__exit__(None, None, None)
        with client.websocket_connect("/ws") as r:
            r.send_json({"type": "join_room", "room": code,
                         "name": "newbie", "seat": 1})
            texts = []
            for _ in range(40):
                m = r.receive_json()
                if m.get("type") == "chat":
                    texts.append(m["text"])
                elif m.get("type") == "state" and texts:
                    break
        assert any("took over for amy" in t for t in texts), texts
        for w in socks[1:]:
            w.__exit__(None, None, None)


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
        code, room, socks = _four_humans(client, a)
        tok = room.seats[1].token          # amy's seat
        socks[0].__exit__(None, None, None)
        with client.websocket_connect("/ws") as real:
            real.send_json({"type": "join_room", "room": code,
                            "name": "totally-different-name", "token": tok})
            st = _drain(real, "state", tries=60)
            assert st["you"] == 1
        for w in socks[1:]:
            w.__exit__(None, None, None)


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
        code, room, socks = _four_humans(client, a)
        original = room.seats[1].token
        socks[0].__exit__(None, None, None)
        with client.websocket_connect("/ws") as other:
            other.send_json({"type": "join_room", "room": code,
                             "name": "AMY ", "token": "not-the-token"})
            st = _drain(other, "state", tries=60)
            assert st["you"] == 1, "name re-entry should reach the dropped seat"
            assert room.seats[1].token != original, \
                "name re-entry inherited the original owner's token"
        for w in socks[1:]:
            w.__exit__(None, None, None)


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


def test_pregame_full_lobby_with_a_drop_is_claimable(client):
    """P0-4: a full PRE-GAME lobby with one dropped player must not deadlock."""
    with client.websocket_connect("/ws") as h:
        h.send_json({"type": "create_room", "name": "host"})
        code = _drain(h, "room")["room"]
        socks = []
        for n in ("p2", "p3", "p4"):
            w = client.websocket_connect("/ws").__enter__()
            w.send_json({"type": "join_room", "room": code, "name": n})
            _drain(w, "room")
            socks.append(w)
        socks[0].__exit__(None, None, None)          # drop BEFORE start_game
        with client.websocket_connect("/ws") as p:
            p.send_json({"type": "peek_room", "room": code})
            pk = _drain(p, "room_seats")
            assert pk["in_game"] is False
            claim = [s for s in pk["seats"] if s["claimable"]]
            assert len(claim) == 1 and claim[0]["controller"] == "bot_cover", \
                "a dropped pre-game seat must be visibly claimable"
        with client.websocket_connect("/ws") as q:
            q.send_json({"type": "join_room", "room": code,
                         "name": "newbie", "seat": claim[0]["seat"]})
            st = _drain(q, "room", tries=60)
            assert st["you"] == claim[0]["seat"]
        for w in socks[1:]:
            w.__exit__(None, None, None)


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
        w = client.websocket_connect("/ws").__enter__()
        w.send_json({"type": "join_room", "room": code, "name": "onturn",
                     "seat": turn})
        _drain(w, "state", tries=60)
        w.__exit__(None, None, None)
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
            w = client.websocket_connect("/ws").__enter__()
            w.send_json({"type": "join_room", "room": code,
                         "name": "jerry", "token": tok})
            _drain(w, "state", tries=60)
            assert seat0.gen > gen_before, f"iteration {i}: generation stalled"
            assert seat0.connected
            srv._detach(seat0, room, gen_before)     # stale teardown, late
            assert seat0.connected, f"iteration {i}: stale teardown won"
            w.__exit__(None, None, None)


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
        old = client.websocket_connect("/ws").__enter__()
        old.send_json({"type": "join_room", "room": code, "name": "bob"})
        tok = _drain(old, "resume")["token"]
        _drain(old, "room")
        new = client.websocket_connect("/ws").__enter__()
        new.send_json({"type": "join_room", "room": code,
                       "name": "bob", "token": tok})
        _drain(new, "room")
        room = srv.rooms[code]
        assert room.seats[1].connected

        old.send_json({"type": "leave_room"})     # the DISPLACED socket acts
        err = _drain(old, "error")
        assert err["code"] == "stale_connection"
        assert code in srv.rooms, "stale leave deleted the room"
        assert len(room.seats) == 2, "stale leave removed the live seat"
        assert room.seats[1].connected, "stale leave detached the live socket"
        for w in (old, new):
            try:
                w.__exit__(None, None, None)
            except Exception:
                pass


def test_claiming_a_seat_rotates_its_token(client):
    """The previous owner must not be able to displace the new one later."""
    with client.websocket_connect("/ws") as a:
        code, room, socks = _four_humans(client, a)
        old_tok = room.seats[1].token
        socks[0].__exit__(None, None, None)          # amy drops
        with client.websocket_connect("/ws") as taker:
            taker.send_json({"type": "join_room", "room": code,
                             "name": "newbie", "seat": 1})
            _drain(taker, "state", tries=60)
            assert room.seats[1].token != old_tok, "token survived the transfer"
            # The old token must no longer resume that seat.
            with client.websocket_connect("/ws") as amy:
                amy.send_json({"type": "join_room", "room": code,
                               "name": "amy", "token": old_tok})
                m = None
                for _ in range(40):
                    m = amy.receive_json()
                    if m.get("type") in ("room", "state", "error"):
                        break
                seat = m.get("you") if m.get("type") in ("room", "state") else None
                assert seat != 1, "stale token displaced the new owner"
        for w in socks[1:]:
            w.__exit__(None, None, None)

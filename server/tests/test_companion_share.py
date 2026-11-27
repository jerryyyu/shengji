"""A seated person's companion moves shared with the table (``companion``):
its special and where it was parked, relayed to everyone else at the table
and to a Join waiting for its handover, rate limited per seat, refused from
anyone but the seat's own person, and the parked spot kept in the frames a
rejoin reads until the seat changes hands."""
from __future__ import annotations

from contextlib import ExitStack

from tests.test_server_ws import _drain, _next_where, _room_with_bots, _wait_for, client  # noqa: F401


def _two(client, stack):
    """jerry on seat 0 and bee on seat 1 of a running game (bots on 2 and 3)."""
    from shengji.api import server as srv

    a = stack.enter_context(client.websocket_connect("/ws"))
    code = _room_with_bots(a)
    b = stack.enter_context(client.websocket_connect("/ws"))
    b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "bee", "seat": 1})
    token = _drain(b, "resume")["token"]
    assert _drain(b, "state")["you"] == 1
    return a, b, srv.rooms[code], code, token


def _sent(monkeypatch):
    from shengji.api import server as srv

    out: list[tuple[str, dict]] = []
    monkeypatch.setattr(srv, "enqueue", lambda sd, payload: out.append((sd.name, payload)))
    return out


def test_a_shared_move_reaches_the_others_and_a_parked_spot_survives_a_rejoin(client):
    with ExitStack() as stack:
        a, b, room, code, token = _two(client, stack)
        a.send_json({"type": "companion", "act": "home", "x": 0.25, "y": 0.6})
        got = _next_where(b, "companion", lambda m: m.get("act") == "home")
        assert got == {"type": "companion", "seat": 0, "act": "home", "x": 0.25, "y": 0.6}
        a.send_json({"type": "companion", "act": "special"})
        assert _next_where(b, "companion", lambda m: m.get("act") == "special") == {
            "type": "companion", "seat": 0, "act": "special"}
        _wait_for(lambda: room.companion_homes.get(0) == (0.25, 0.6))
        # bee comes back by token: the frame it reads has jerry's companion where it was parked
        b.close()
        _wait_for(lambda: not room.seats[1].connected)
        back = stack.enter_context(client.websocket_connect("/ws"))
        back.send_json({"type": "table_join", "expect": "room", "code": code, "name": "bee", "token": token})
        players = {p["seat"]: p for p in _drain(back, "state")["players"]}
        assert players[0]["home"] == [0.25, 0.6]
        assert "home" not in players[1] and "home" not in players[2]


def test_the_sender_is_not_told_and_the_limits_drop_the_excess(client, monkeypatch):
    from shengji.api import server as srv

    with ExitStack() as stack:
        _a, _b, room, _code, _token = _two(client, stack)
        sent = _sent(monkeypatch)
        jerry = room.seats[0]
        special, home = {"act": "special"}, {"act": "home", "x": 0.5, "y": 0.5}
        assert srv.companion_message(room, jerry, special, now=100.0)
        assert [name for name, _ in sent] == ["bee"]               # not jerry, not the bots
        assert not srv.companion_message(room, jerry, special, now=104.9)   # within 5 s
        assert srv.companion_message(room, jerry, special, now=105.0)
        assert srv.companion_message(room, jerry, home, now=105.0)    # its own clock
        assert not srv.companion_message(room, jerry, {**home, "x": 0.4}, now=105.9)
        assert srv.companion_message(room, jerry, {**home, "x": 0.4}, now=106.0)
        assert room.companion_homes[0] == (0.4, 0.5)
        # each seat keeps its own clock
        assert srv.companion_message(room, room.seats[1], special, now=105.1)
        assert sent[-1] == ("jerry", {"type": "companion", "seat": 1, "act": "special"})


def test_refused_from_a_bot_a_seat_left_by_choice_a_stale_socket_and_a_bad_move(client, monkeypatch):
    from shengji.api import server as srv

    with ExitStack() as stack:
        _a, _b, room, _code, _token = _two(client, stack)
        sent = _sent(monkeypatch)
        assert not srv.companion_message(room, room.seats[2], {"act": "special"}, now=1.0)   # a bot
        outsider = srv.Seat(name="watcher")
        assert not srv.companion_message(room, outsider, {"act": "special"}, now=1.0)      # holds no seat
        for bad in ({"act": "dance"}, {"act": "home", "x": 1.5, "y": 0.2}, {"act": "home", "x": "0.1", "y": 0.2},
                    {"act": "home", "x": True, "y": 0.2}, {"act": "home"}):
            assert not srv.companion_message(room, room.seats[0], bad, now=1.0)
        room.seats[1].left_by_choice = True                                              # the bot plays it now
        assert not srv.companion_message(room, room.seats[1], {"act": "special"}, now=1.0)
        room.seats[1].left_by_choice = False
        room.seats[1].connected = False
        assert not srv.companion_message(room, room.seats[1], {"act": "special"}, now=1.0)
        assert sent == [] and room.companion_homes == {}


def test_a_join_waiting_for_its_handover_sees_it_and_a_new_holder_starts_with_no_home(client, monkeypatch):
    from shengji.api import server as srv

    with ExitStack() as stack:
        _a, _b, room, _code, _token = _two(client, stack)
        _sent(monkeypatch)
        pushed = []

        class Waiting:
            def push(self, m):
                pushed.append(m)
        monkeypatch.setitem(room.pending_joins, 3, type("PJ", (), {"conn": Waiting()})())
        assert srv.companion_message(room, room.seats[1], {"act": "home", "x": 0.1, "y": 0.9}, now=1.0)
        assert pushed == [{"type": "companion", "seat": 1, "act": "home", "x": 0.1, "y": 0.9}]
        room.pending_joins.clear()
        assert room.companion_homes == {1: (0.1, 0.9)}
        assert srv.state_for(room, 0)["players"][1]["home"] == [0.1, 0.9]
        srv._revert_to_bot(room, 1)                    # the seat is a bot's again
        assert 1 not in room.companion_homes
        assert "home" not in srv.state_for(room, 0)["players"][1]

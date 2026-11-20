"""The canonical ``table_*`` messages (``shengji.api.tables``) over the real
socket.

Every canonical name is a rewrite into a message a backend already handles,
so the main test here is a differential: each scenario runs twice on a fresh
server, once sent with the old name and once with the canonical one, and
everything a person or a record could see must be the same, frame for
frame on every socket, line for line in the room log, and the same
saved-game link and rating snapshot.
"""
from __future__ import annotations

import json
import re
from contextlib import ExitStack

import pytest

from shengji.api import tables

from tests.test_accounts import accounts_on, keypair  # noqa: F401
from tests.test_matchmaking import DEVICE_A, DEVICE_B, _account_match, wsenv  # noqa: F401
from tests.test_ratings import _user
from tests.test_server_ws import _drain, _frames_until, _next_where, client  # noqa: F401

DEVICE_C = "CCCCCCCCCCCCCCCCCCCCCC"


# ------------------------------------------------------------ normalizing
CODE = re.compile(r"^[A-Z2-9]{4}$")
HEX_ID = re.compile(r"^[0-9a-f]{8,}$")
# Values that differ between two runs of one scenario by construction:
# clocks, random tokens and generations.
VOLATILE = {"t", "token", "since", "start_now_in", "start_now_at", "expires_at",
            "cooldown_until", "gen", "sit", "deadline", "turn_started"}


def _norm(v):
    if isinstance(v, dict):
        if v.get("type") == "state":
            # a deal is random: the frame's identity is whose view it is
            return {"type": "state", "you": v.get("you")}
        return {k: None if k in VOLATILE else _norm(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_norm(x) for x in v]
    if isinstance(v, str) and CODE.match(v):
        return "<CODE>"
    if isinstance(v, str) and HEX_ID.match(v):
        return "<ID>"
    return v


def _frames(seen: list[dict]) -> list[str]:
    """One socket's frames, normalized. A room frame and a queue frame
    travel on two writers, so their interleaving is not part of the
    comparison: the frames are compared as a sorted list, and a started
    game's stream of state frames counts once."""
    out = {json.dumps(_norm(m), sort_keys=True) for m in seen if m.get("type") == "state"}
    return sorted([json.dumps(_norm(m), sort_keys=True) for m in seen
                   if m.get("type") != "state"] + list(out))


def _until_text(ws, text):
    """Frames up to and including the chat line ``text`` (room or table
    chat) or an error, whichever comes first."""
    def stop(m):
        return ((m.get("type") in ("chat", "table_chat") and m.get("text") == text)
                or (m.get("type") == "error" and m.get("code") == "not_seated"))
    return _frames_until(ws, stop, repr(text))


def _until(ws, kind):
    return _frames_until(ws, lambda m: m.get("type") == kind, repr(kind))


def _reset(srv):
    for room in list(srv.rooms.values()):
        for task in (room.cleanup_task, room.deal_task, room.watchdog_task, room.bot_task):
            if task is not None:
                task.cancel()
    srv.rooms.clear()
    srv.MATCHMAKER.reset()
    srv.GUEST_IDS.clear()


# ------------------------------------------------------------ room scenarios
def _log_lines(srv, code):
    path = srv.LOG_DIR / f"{code}.jsonl"
    if not path.exists():
        return None
    keep = []
    for line in path.read_text().splitlines():
        rec = json.loads(line)
        if rec["e"] in ("chat", "seat_left", "seat_claimed", "seat_reconnected",
                        "seat_disconnected", "seat_joined"):
            keep.append(_norm(rec))
    return keep


def _records(room):
    link = room.saved_game
    return {
        "saved_game": None if link is None else {
            "open": dict(link.open), "stored": link.stored,
            "last_round": link.last_round, "incomplete": link.incomplete},
        "ratings": None if room.ratings is None else dict(room.ratings.present),
        "matched": room.matched, "start_level": room.start_level,
        "seats": [None if sd is None else (sd.name, sd.is_bot, sd.user_id)
                  for sd in room.seats],
        "host": room.host, "allow_joiners": room.allow_joiners,
        "started": room.game is not None,
    }


def _run_room(env, case: dict, msg: dict, ends: str | None) -> dict:
    """A room in play, its host at 0 with ``case``'s humans in bot seats,
    then ``msg`` sent by ``case``'s actor, whose frames end at ``ends`` (or
    at the end marker); returns everything visible afterwards."""
    srv, store, client, _ = env
    _reset(srv)
    out: dict = {}
    with ExitStack() as stack:
        socks: dict[str, object] = {}
        _, host_headers = _user(store, "host", "Host")
        h = stack.enter_context(client.websocket_connect("/ws", headers=host_headers))
        h.send_json({"type": "create_room", "name": "Host", "start": True})
        code = _drain(h, "room")["room"]
        socks["Host"] = h
        for name, seat in case.get("humans", (("Bo", 2),)):
            w = stack.enter_context(client.websocket_connect("/ws"))
            w.send_json({"type": "table_join", "code": code, "name": name, "seat": seat})
            _drain(w, "state")
            socks[name] = w
        room = srv.rooms[code]
        seated = list(socks)
        for name in seated:                       # everything so far is setup
            socks[name].send_json({"type": "table_chat", "text": f"zz-setup-{name}"})
            for other in seated:
                _until_text(socks[other], f"zz-setup-{name}")
        if "outsider" in case:
            socks["Cy"] = stack.enter_context(client.websocket_connect("/ws"))
        actor = socks[case["actor"]]
        msg = dict(msg)
        for key in ("room", "code"):
            if msg.get(key) == "<CODE>":
                msg[key] = code
        actor.send_json(msg)
        if ends is not None:
            out[case["actor"]] = _frames(_until(actor, ends))
        end_from = case.get("end_from", "Host")
        stay = [n for n in socks if n not in out]
        socks[end_from].send_json({"type": "table_chat", "text": "zz-end"})
        for name in stay:
            out[name] = _frames(_until_text(socks[name], "zz-end"))
        out["log"] = _log_lines(srv, code)
        out["records"] = _records(room)
        out["room_alive"] = code in srv.rooms
    return out


RETIRED_FRAME = json.dumps({"type": "error", "code": "retired",
                            "message": tables.RETIRED_MESSAGE}, sort_keys=True)
# A message that changes nothing anyone else sees, answered to its sender alone.
PING = {"type": "ping", "nonce": 1}
PONG_FRAME = json.dumps({"type": "pong", "nonce": 1}, sort_keys=True)


def _without(frames: list[str], frame: str) -> list[str]:
    assert frame in frames, frames
    rest = list(frames)
    rest.remove(frame)
    return rest


# The host sits at 0 and Bo, the host's partner, at 2; bots play 1 and 3.
# Each case: the actor, its canonical message and the old name it replaced.
ROOM_CASES = {
    "Start now in play": dict(actor="Host", old={"type": "start_game"},
                              new={"type": "table_start_now"}, actor_ends="error"),
    "a Start in play": dict(actor="Bo", old={"type": "lobby_ready"},
                            new={"type": "table_start"}, actor_ends="error"),
    "Allow joiners by a guest": dict(actor="Bo", old={"type": "allow_joiners", "on": False},
                                     new={"type": "table_allow_joiners", "on": False}),
    "Allow joiners in play": dict(actor="Host", old={"type": "allow_joiners", "on": False},
                                  new={"type": "table_allow_joiners", "on": False}),
    "chat in play": dict(actor="Bo", old={"type": "chat", "text": "gl"},
                         new={"type": "table_chat", "text": "gl"}),
    "a Leave in play": dict(actor="Bo", actor_ends="left",
                            old={"type": "leave_room"}, new={"type": "table_leave"}),
    "a Join into a bot's seat in play": dict(
        actor="Cy", outsider=True, actor_ends="state",
        old={"type": "join_room", "room": "<CODE>", "name": "Cy", "seat": 3},
        new={"type": "table_join", "code": "<CODE>", "name": "Cy", "seat": 3}),
    "a Join into a taken seat in play": dict(
        actor="Cy", outsider=True, actor_ends="error",
        old={"type": "join_room", "room": "<CODE>", "name": "Cy", "seat": 2},
        new={"type": "table_join", "code": "<CODE>", "name": "Cy", "seat": 2}),
    "a Join of an unknown code, as a room": dict(
        actor="Cy", outsider=True, actor_ends="error",
        old={"type": "join_room", "room": "ZZZZ", "name": "Cy"},
        new={"type": "table_join", "code": "zzzz", "name": "Cy", "expect": "room"}),
    "a peek": dict(actor="Cy", outsider=True, actor_ends="room_seats",
                   old={"type": "peek_room", "room": "<CODE>"},
                   new={"type": "table_peek", "code": "<CODE>"}),
    "a peek at an unknown code": dict(actor="Cy", outsider=True, actor_ends="error",
                                      old={"type": "peek_room", "room": "ZZZZ"},
                                      new={"type": "table_peek", "code": "ZZZZ"}),
}


# What the actor's frames must show for the canonical name.
ROOM_SEES = {
    "Start now in play": "Game already started.", "a Start in play": "Game already started.",
    "Allow joiners by a guest": '"not_opener"', "Allow joiners in play": '"type": "state"',
    "chat in play": '"text": "gl"', "a Leave in play": '"left"',
    "a Join into a bot's seat in play": "Cy took Bot 3's seat",
    "a Join into a taken seat in play": "seat_unavailable", "a peek": '"room_seats"',
    "a Join of an unknown code, as a room": '"room_not_found"',
    "a peek at an unknown code": "room_not_found",
}


@pytest.mark.parametrize("name", list(ROOM_CASES))
def test_a_room_answers_the_canonical_name(wsenv, name):  # noqa: F811
    case = ROOM_CASES[name]
    new = _run_room(wsenv, case, case["new"], case.get("actor_ends"))
    assert ROOM_SEES[name] in " ".join(new[case["actor"]])


@pytest.mark.parametrize("name", list(ROOM_CASES))
def test_a_room_refuses_the_old_name_and_changes_nothing(wsenv, name):  # noqa: F811
    """The old name is refused as ``retired`` to its sender alone: everything
    else visible is what a ping (which changes nothing) leaves."""
    case = ROOM_CASES[name]
    outsider = "outsider" in case
    old = _run_room(wsenv, case, case["old"], "error" if outsider else None)
    base = _run_room(wsenv, case, PING, "pong" if outsider else None)
    actor = case["actor"]
    assert _without(old.pop(actor), RETIRED_FRAME) == _without(base.pop(actor), PONG_FRAME)
    assert old == base


# ----------------------------------------------------------- queue scenarios
GUESTS = {"Ann": DEVICE_A, "Bo": DEVICE_B, "Cy": DEVICE_C}


def _run_queue(env, case: dict, msg: dict) -> dict:
    """Guests on their own devices: ``queued`` search Casual (the first
    two meet at a table), ``ready`` tap Start, then ``actor`` sends
    ``msg``; returns every socket's frames afterwards."""
    srv, _, client, _ = env
    _reset(srv)
    out: dict = {}
    with ExitStack() as stack:
        socks = {name: stack.enter_context(client.websocket_connect(f"/ws?device={device}"))
                 for name, device in GUESTS.items()}
        codes = {}
        for name in case.get("queued", ()):
            socks[name].send_json({"type": "queue_join", "mode": "casual", "bot_level": "advanced", "name": name})
            codes[name] = _until(socks[name], "queue_state")[-1].get("code")
        for name in case.get("ready", ()):
            socks[name].send_json({"type": "table_start"})
        for name, ws in socks.items():           # everything so far is setup
            ws.send_json({"type": "table_chat", "text": f"zz-setup-{name}"})
            _until_text(ws, f"zz-setup-{name}")
        msg = dict(msg)
        if msg.get("code") == "<ANN>":
            msg["code"] = codes["Ann"]
        socks[case["actor"]].send_json(msg)
        for name, ws in socks.items():
            # Outside any table the end marker is a not_seated refusal, which
            # the action may also have been; a second marker reads past it.
            seen = []
            for mark in ("zz-end", "zz-end-2"):
                ws.send_json({"type": "table_chat", "text": f"{mark}-{name}"})
                seen += _until_text(ws, f"{mark}-{name}")
            out[name] = _frames(seen)
        out["entries"] = sorted(
            (sorted(srv.MATCHMAKER._name(u) for u in e.members), e.mode)
            for e in srv.MATCHMAKER.entries.values())
        out["tables"] = sorted(
            sorted(srv.MATCHMAKER._name(u) if u is not None else "" for u in t.seats)
            for t in srv.MATCHMAKER.tables.values())
        out["rooms"] = sorted(repr(_records(room)) for room in srv.rooms.values())
    return out


QUEUE_CASES = {
    "a Start taken back": dict(actor="Ann", queued=("Ann", "Bo"), ready=("Ann",),
                               old={"type": "table_unready"},
                               new={"type": "table_start", "on": False}),
    "a Start taken back with nothing to take back": dict(
        actor="Cy", old={"type": "table_unready"}, new={"type": "table_start", "on": False}),
    "Play bots alone": dict(actor="Ann", queued=("Ann",), old={"type": "queue_start_bots"},
                            new={"type": "table_start_bots"}),
    "Play bots at a table": dict(actor="Ann", queued=("Ann", "Bo"),
                                 old={"type": "queue_start_bots"},
                                 new={"type": "table_start_bots"}),
    "Play bots against a changed panel": dict(
        actor="Ann", queued=("Ann",), old={"type": "queue_start_bots", "panel_seq": 999},
        new={"type": "table_start_bots", "panel_seq": 999}),
    "a Leave alone": dict(actor="Ann", queued=("Ann",), old={"type": "queue_leave"},
                          new={"type": "table_leave"}),
    "a Leave at a table": dict(actor="Bo", queued=("Ann", "Bo"), old={"type": "queue_leave"},
                               new={"type": "table_leave"}),
    "a Join by a table's code": dict(actor="Cy", queued=("Ann",),
                                     old={"type": "queue_join", "code": "<ANN>", "name": "Cy"},
                                     new={"type": "table_join", "code": "<ANN>", "name": "Cy"}),
    "a Join by a table's code, as a room": dict(
        actor="Cy", queued=("Ann",),
        old={"type": "join_room", "room": "<ANN>", "name": "Cy"},
        new={"type": "table_join", "code": "<ANN>", "name": "Cy", "expect": "room"}),
    "a Join with an unknown code": dict(actor="Cy", queued=("Ann",),
                                        old={"type": "queue_join", "code": "ZZZZ", "name": "Cy"},
                                        new={"type": "table_join", "code": "zzzz ", "name": "Cy"}),
}


QUEUE_SEES = {
    "a Start taken back": '"ready": 0',
    "a Start taken back with nothing to take back": '"not_seated"',
    "Play bots alone": '"match_started"', "Play bots at a table": '"ready": 1',
    "Play bots against a changed panel": '"panel_changed"',
    "a Leave alone": '"queued": false', "a Leave at a table": '"queued": false',
    "a Join by a table's code": '"table_chat_history"',
    "a Join by a table's code, as a room": '"table_chat_history"',
    "a Join with an unknown code": '"table_not_found"',
}


@pytest.mark.parametrize("name", list(QUEUE_CASES))
def test_the_queue_answers_the_canonical_name(wsenv, name):  # noqa: F811
    case = QUEUE_CASES[name]
    new = _run_queue(wsenv, case, case["new"])
    assert QUEUE_SEES[name] in " ".join(new[case["actor"]])


@pytest.mark.parametrize("name", list(QUEUE_CASES))
def test_the_queue_refuses_the_old_name_and_changes_nothing(wsenv, name):  # noqa: F811
    case = QUEUE_CASES[name]
    old = _run_queue(wsenv, case, case["old"])
    base = _run_queue(wsenv, case, PING)
    actor = case["actor"]
    assert _without(old.pop(actor), RETIRED_FRAME) == _without(base.pop(actor), PONG_FRAME)
    assert old == base


# --------------------------------------------------- what a Join's code names
def test_a_join_of_a_table_that_just_became_a_room_joins_the_room_by_its_name(wsenv):  # noqa: F811
    """The Join panel read a Play table, which then started: the same
    ``table_join`` sits in the room it became, under the name sent."""
    srv, _, client, _ = wsenv
    _reset(srv)
    with client.websocket_connect(f"/ws?device={DEVICE_A}") as a, \
            client.websocket_connect(f"/ws?device={DEVICE_B}") as c:
        a.send_json({"type": "queue_join", "mode": "casual", "name": "Ann"})
        code = _until(a, "queue_state")[-1]["code"]
        a.send_json({"type": "table_start_bots"})
        assert _until(a, "match_started")[-1]["room"] == code
        c.send_json({"type": "table_join", "code": code, "name": "Cy"})
        _drain(c, "state")
        assert [sd.name for sd in srv.rooms[code].seats if not sd.is_bot] == ["Ann", "Cy"]


@pytest.mark.parametrize("expect, refused", [("room", "room_not_found"),
                                             (None, "table_not_found")])
def test_a_join_of_a_room_that_closed_is_refused_where_the_client_expected(
        wsenv, expect, refused):  # noqa: F811
    """A resume, or a Join panel left open on a room, after the room is
    gone: ``room_not_found``, which ends the dead room on the page; a
    table's Join gets the queue's ``table_not_found``."""
    srv, _, client, _ = wsenv
    _reset(srv)
    with client.websocket_connect("/ws") as h:
        h.send_json({"type": "create_room", "name": "Host", "start": True})
        seen = _until(h, "room")
        code = seen[-1]["room"]
        token = next(m for m in seen if m["type"] == "resume")["token"]
    _reset(srv)                                   # the room has closed
    with client.websocket_connect(f"/ws?device={DEVICE_A}") as w:
        w.send_json({"type": "table_join", "code": code, "name": "Host", "token": token,
                     **({"expect": expect} if expect else {})})
        assert _drain(w, "error")["code"] == refused


# ------------------------------------------ a table_* message reaches the room
def test_table_messages_from_a_room_socket_reach_the_room_not_the_queue(client):  # noqa: F811
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as h, client.websocket_connect("/ws") as b:
        h.send_json({"type": "create_room", "name": "Host", "start": True})
        code = _drain(h, "room")["room"]
        b.send_json({"type": "table_join", "code": code, "name": "Bo", "seat": 2})
        _drain(b, "state")
        b.send_json({"type": "table_chat", "text": "hello"})
        assert _next_where(h, "chat", lambda m: m["seat"] == 2)["text"] == "hello"
        # a pre-game control is the room's refusal, not the queue's not_seated
        b.send_json({"type": "table_move", "seat": 3})
        assert _drain(b, "error") == {"type": "error",
                                                 "message": "Game already started."}
        h.send_json({"type": "table_allow_joiners", "on": False})
        h.send_json({"type": "table_chat", "text": "after"})   # handled in order
        _next_where(h, "chat", lambda m: m["text"] == "after")
        assert srv.rooms[code].allow_joiners is False
        b.send_json({"type": "table_leave"})
        assert _drain(b, "left") == {"type": "left"}
        # in play the seat stays, the bot covering it
        assert srv.rooms[code].seats[2].left_by_choice


@pytest.mark.parametrize("kind", sorted(tables.LOBBY))
def test_a_running_rooms_pre_game_controls_are_refused(client, kind):  # noqa: F811
    """A room exists only once its game has started, so each pre-game
    control is refused there."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as h:
        h.send_json({"type": "create_room", "name": "Host", "start": True})
        code = _drain(h, "room")["room"]
        _drain(h, "state")
        before = (srv.rooms[code].host, srv.rooms[code].start_level,
                  [(sd.name, sd.is_bot) for sd in srv.rooms[code].seats])
        h.send_json({"type": kind, "seat": 1, "a": 0, "b": 1, "start_level": "5"})
        assert _drain(h, "error") == {"type": "error",
                                                 "message": "Game already started."}
        assert (srv.rooms[code].host, srv.rooms[code].start_level,
                [(sd.name, sd.is_bot) for sd in srv.rooms[code].seats]) == before


# ------------------------------------------------------- the retired names
def _legacy(client):
    return client.get("/healthz").json()["legacy_messages"]


def _retired_forms():
    """Each retired name as a client frame: ``queue_join`` with a code."""
    return [{"type": t, **({"code": "ABCD"} if t == "queue_join" else {})}
            for t in sorted(tables.RETIRED)]


@pytest.mark.parametrize("seated", [False, True])
def test_every_retired_name_is_refused_and_counted(client, monkeypatch, seated):  # noqa: F811
    from shengji.api import server as srv

    monkeypatch.setattr(srv, "ACTIVITY", srv.Activity())
    zero = dict.fromkeys(sorted(tables.LEGACY), 0)
    assert _legacy(client) == zero
    with client.websocket_connect("/ws") as h:
        if seated:
            h.send_json({"type": "create_room", "name": "Host", "start": True})
            code = _drain(h, "room")["room"]
            _drain(h, "state")
            before = _records(srv.rooms[code])
        for msg in _retired_forms():
            h.send_json({**msg, "on": False, "text": "x", "room": "ABCD", "seat": 1})
            assert _drain(h, "error") == {
                "type": "error", "code": "retired", "message": tables.RETIRED_MESSAGE}, msg
        if seated:
            # nothing reached the room: no chat, no switch, no leave
            assert _records(srv.rooms[code]) == before
    assert _legacy(client) == {**zero, **dict.fromkeys(tables.RETIRED, 1)}
    # every value is a plain count: no codes, ids or text
    assert all(type(v) is int for v in _legacy(client).values())
    assert set(client.get("/healthz").json()["activity"]) == set(srv.Activity().health())


def test_a_create_without_start_is_counted_and_still_starts(client, monkeypatch):  # noqa: F811
    from shengji.api import server as srv

    monkeypatch.setattr(srv, "ACTIVITY", srv.Activity())
    with client.websocket_connect("/ws") as h:
        h.send_json({"type": "create_room", "name": "Host"})
        _drain(h, "state")
    assert {k: v for k, v in _legacy(client).items() if v} == {"create_room": 1}


def test_internal_starts_and_canonical_names_are_not_counted(wsenv, monkeypatch):  # noqa: F811
    srv, _, client, _ = wsenv
    monkeypatch.setattr(srv, "ACTIVITY", srv.Activity())
    with client.websocket_connect("/ws") as h:
        h.send_json({"type": "create_room", "name": "Host", "start": True})
        _drain(h, "state")
        h.send_json({"type": "table_chat", "text": "one"})
        _drain(h, "chat")
    with client.websocket_connect(f"/ws?device={DEVICE_A}") as a:
        a.send_json({"type": "queue_join", "mode": "casual", "name": "Ann"})
        _drain(a, "queue_state")
        a.send_json({"type": "table_join", "code": "ZZZZ"})
        _drain(a, "error")
        # the queue's own start of the room calls _start_game, never start_game
        a.send_json({"type": "table_start_bots"})
        _drain(a, "match_started")
    assert srv.ACTIVITY.games_started == 2
    assert _legacy(client) == dict.fromkeys(sorted(tables.LEGACY), 0)


# ---------------------------------------------------------- guard parity
@pytest.mark.parametrize("msg", [{"type": "table_start_bots"},
                                 {"type": "table_join", "code": "ABCD"}])
def test_a_signed_out_guest_is_refused_the_canonical_starts(wsenv, monkeypatch, msg):  # noqa: F811
    srv, store, client, _ = wsenv
    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    _account_match(srv, store, client)
    with client.websocket_connect(f"/ws?device={DEVICE_A}") as g:
        g.send_json({**msg, "name": "Lea"})
        assert _drain(g, "error") == {"type": "error", "code": "account_in_game",
                                      "message": "Sign in again to return to your game."}
    assert srv.MATCHMAKER.entry_of == {}


def test_every_canonical_queue_start_is_guarded_as_the_backend_name_is():
    from shengji.api import server as srv

    for kind, backend in (("table_start_bots", "queue_start_bots"),
                          ("table_join", "queue_join"), ("table_start", "table_start"),
                          ("table_leave", "queue_leave"), ("table_peek", "peek_room")):
        new = tables.for_queue({"type": kind, "code": "ABCD"}, joining=False,
                               room_codes={"ROOM"}, table_codes={"ABCD"})["type"]
        assert new == backend
        assert (new in srv.QUEUE_STARTS) == (backend in srv.QUEUE_STARTS)


# ------------------------------------------------------------ the rewrites
def test_the_queue_rewrites():
    def q(msg, joining=False):
        return tables.for_queue(msg, joining=joining, room_codes={"ROOM"},
                                table_codes={"TABL"})

    assert q({"type": "table_start", "panel_seq": 3}) == {"type": "table_start", "panel_seq": 3}
    assert q({"type": "table_start", "on": False})["type"] == "table_unready"
    assert q({"type": "table_start", "on": True})["type"] == "table_start"
    assert q({"type": "table_start_bots", "panel_seq": 3}) == {"type": "queue_start_bots",
                                                               "panel_seq": 3}
    assert q({"type": "table_leave"})["type"] == "queue_leave"
    assert q({"type": "table_leave"}, joining=True)["type"] == "leave_room"
    peek = {"type": "table_peek", "code": "room"}
    assert q(peek) == {**peek, "room": "ROOM"} | {"type": "peek_room"}
    for same in ("table_move", "table_start_now", "table_chat", "table_allow_joiners",
                 "table_start_level"):
        assert q({"type": same, "x": 1}) == {"type": same, "x": 1}


@pytest.mark.parametrize("code, expect, backend", [
    # a live room's code joins the room, whatever the client expected
    (" room", None, ("join_room", "room", "ROOM")),
    ("ROOM", "room", ("join_room", "room", "ROOM")),
    # a queued table's code joins the table, whatever the client expected
    ("tabl", None, ("queue_join", "code", "TABL")),
    ("TABL", "room", ("queue_join", "code", "TABL")),
    # a code that names nothing: refused where the client expected
    ("zzzz", "room", ("join_room", "room", "ZZZZ")),
    ("zzzz", None, ("queue_join", "code", "ZZZZ")),
    ("zzzz", "table", ("queue_join", "code", "ZZZZ")),
    # no code at all is the room's refusal, never a search
    (None, None, ("join_room", "room", "")),
    ("", "room", ("join_room", "room", "")),
])
def test_a_join_goes_where_its_code_names(code, expect, backend):
    msg = {"type": "table_join", "name": "Cy", "seat": 2, "token": "t", "panel_seq": 4,
           **({"code": code} if code is not None else {}),
           **({"expect": expect} if expect is not None else {})}
    out = tables.for_queue(msg, joining=False, room_codes={"ROOM"}, table_codes={"TABL"})
    kind, field, value = backend
    # every field the client sent goes through
    assert out == {**msg, "type": kind, field: value}


def test_the_room_rewrites():
    r = tables.for_room

    assert r({"type": "table_allow_joiners", "on": True}) == {"type": "allow_joiners", "on": True}
    assert r({"type": "table_chat", "text": "hi"}) == {"type": "chat", "text": "hi"}
    assert r({"type": "table_leave"}) == {"type": "leave_room"}
    assert r({"type": "table_join", "code": "ROOM"}) == {"type": "join_room", "code": "ROOM",
                                                         "room": "ROOM"}
    assert r({"type": "table_peek", "code": "ROOM"}) == {"type": "peek_room", "code": "ROOM",
                                                         "room": "ROOM"}
    # a pre-game control stays as it is, for the room to refuse
    for kind in tables.LOBBY:
        assert r({"type": kind, "seat": 3}) == {"type": kind, "seat": 3}


def test_legacy_names():
    assert tables.legacy_name({"type": "queue_join"}) is None
    assert not tables.retired({"type": "queue_join", "mode": "casual"})
    assert tables.legacy_name({"type": "queue_join", "code": "ABCD"}) == "queue_join"
    assert tables.legacy_name({"type": "create_room"}) == "create_room"
    assert not tables.retired({"type": "create_room"})
    assert tables.legacy_name({"type": "create_room", "start": True}) is None
    assert all(tables.legacy_name({"type": t}) is None for t in tables.CANONICAL)
    assert tables.legacy_name({"type": "play"}) is None
    assert tables.legacy_name({"type": ["chat"]}) is None
    assert not tables.CANONICAL & tables.LEGACY
    assert not tables.LOBBY & tables.RETIRED
    assert all(tables.retired(m) and tables.legacy_name(m) == m["type"]
               for m in _retired_forms())
    # every name a rewrite produces is a backend name a client may not send
    produced = {tables.for_queue({"type": t, "code": c, "on": False}, joining=j,
                                 room_codes={"ROOM"}, table_codes={"TABL"})["type"]
                for t in tables.CANONICAL for c in ("ROOM", "TABL", "ZZZZ")
                for j in (False, True)}
    produced |= {tables.for_room({"type": t})["type"] for t in tables.CANONICAL}
    assert produced - tables.CANONICAL <= tables.RETIRED

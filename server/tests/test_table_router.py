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
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import ExitStack

import pytest

from shengji.api import tables

from tests.test_accounts import accounts_on, keypair  # noqa: F401
from tests.test_matchmaking import DEVICE_A, DEVICE_B, _account_match, wsenv  # noqa: F401
from tests.test_ratings import _user
from tests.test_server_ws import _drain, _next_where, client  # noqa: F401

DEVICE_C = "CCCCCCCCCCCCCCCCCCCCCC"
_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="router-read")


def _recv(ws, timeout=5.0):
    fut = _POOL.submit(ws.receive_json)
    try:
        return fut.result(timeout=timeout)
    except FutureTimeout:
        raise AssertionError("no frame within the timeout") from None


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


def _until_text(ws, text, tries=600):
    """Frames up to and including the chat line ``text`` (room or table
    chat) or an error, whichever comes first."""
    seen = []
    for _ in range(tries):
        m = _recv(ws)
        seen.append(m)
        if m.get("type") in ("chat", "table_chat") and m.get("text") == text:
            return seen
        if m.get("type") == "error" and m.get("code") == "not_seated":
            return seen
    raise AssertionError(f"no {text!r} in {[m.get('type') for m in seen]}")


def _until(ws, kind, tries=600):
    seen = []
    for _ in range(tries):
        m = _recv(ws)
        seen.append(m)
        if m.get("type") == kind:
            return seen
    raise AssertionError(f"no {kind} in {[m.get('type') for m in seen]}")


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


def _run_room(env, case: dict, which: str) -> dict:
    """A room in play, its host at 0 with ``case``'s humans in bot seats,
    then its action sent as ``case[which]``; returns everything visible
    afterwards."""
    srv, store, client, _ = env
    _reset(srv)
    out: dict = {}
    with ExitStack() as stack:
        socks: dict[str, object] = {}
        _, host_headers = _user(store, "host", "Host")
        h = stack.enter_context(client.websocket_connect("/ws", headers=host_headers))
        h.send_json({"type": "create_room", "name": "Host"})
        code = _drain(h, "room")["room"]
        socks["Host"] = h
        for name, seat in case.get("humans", (("Bo", 2),)):
            w = stack.enter_context(client.websocket_connect("/ws"))
            w.send_json({"type": "join_room", "room": code, "name": name, "seat": seat})
            _drain(w, "state", tries=400)
            socks[name] = w
        room = srv.rooms[code]
        seated = list(socks)
        for name in seated:                       # everything so far is setup
            socks[name].send_json({"type": "chat", "text": f"zz-setup-{name}"})
            for other in seated:
                _until_text(socks[other], f"zz-setup-{name}")
        if "outsider" in case:
            socks["Cy"] = stack.enter_context(client.websocket_connect("/ws"))
        actor = socks[case["actor"]]
        msg = dict(case[which])
        for key in ("room", "code"):
            if msg.get(key) == "<CODE>":
                msg[key] = code
        actor.send_json(msg)
        if case.get("actor_ends") == "left":
            out[case["actor"]] = _frames(_until(actor, "left"))
        elif case.get("actor_ends"):
            out[case["actor"]] = _frames(_until(actor, case["actor_ends"]))
        end_from = case.get("end_from", "Host")
        stay = [n for n in socks if n not in out]
        socks[end_from].send_json({"type": "chat", "text": "zz-end"})
        for name in stay:
            out[name] = _frames(_until_text(socks[name], "zz-end"))
        out["log"] = _log_lines(srv, code)
        out["records"] = _records(room)
        out["room_alive"] = code in srv.rooms
    return out


# The host sits at 0 and Bo, the host's partner, at 2; bots play 1 and 3.
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
    "a peek": dict(actor="Cy", outsider=True, actor_ends="room_seats",
                   old={"type": "peek_room", "room": "<CODE>"},
                   new={"type": "table_peek", "code": "<CODE>"}),
    "a peek at an unknown code": dict(actor="Cy", outsider=True, actor_ends="error",
                                      old={"type": "peek_room", "room": "ZZZZ"},
                                      new={"type": "table_peek", "code": "ZZZZ"}),
}


# What the actor's frames must show, so that two runs agreeing on nothing
# happening cannot pass.
ROOM_SEES = {
    "Start now in play": "Game already started.", "a Start in play": "Game already started.",
    "Allow joiners by a guest": '"not_opener"', "Allow joiners in play": '"type": "state"',
    "chat in play": '"text": "gl"', "a Leave in play": '"left"',
    "a Join into a bot's seat in play": "Cy took Bot 3's seat",
    "a Join into a taken seat in play": "seat_unavailable", "a peek": '"room_seats"',
    "a peek at an unknown code": "room_not_found",
}


@pytest.mark.parametrize("name", list(ROOM_CASES))
def test_a_room_hears_the_old_name_and_the_canonical_one_alike(wsenv, name):  # noqa: F811
    case = ROOM_CASES[name]
    old = _run_room(wsenv, case, "old")
    new = _run_room(wsenv, case, "new")
    assert ROOM_SEES[name] in " ".join(old[case["actor"]])
    assert new == old


# ----------------------------------------------------------- queue scenarios
GUESTS = {"Ann": DEVICE_A, "Bo": DEVICE_B, "Cy": DEVICE_C}


def _run_queue(env, case: dict, which: str) -> dict:
    """Guests on their own devices: ``queued`` search Casual (the first
    two meet at a table), ``ready`` tap Start, then ``actor`` sends
    ``case[which]``; returns every socket's frames afterwards."""
    srv, _, client, _ = env
    _reset(srv)
    out: dict = {}
    with ExitStack() as stack:
        socks = {name: stack.enter_context(client.websocket_connect(f"/ws?device={device}"))
                 for name, device in GUESTS.items()}
        codes = {}
        for name in case.get("queued", ()):
            socks[name].send_json({"type": "queue_join", "mode": "casual", "name": name})
            codes[name] = _until(socks[name], "queue_state")[-1].get("code")
        for name in case.get("ready", ()):
            socks[name].send_json({"type": "table_start"})
        for name, ws in socks.items():           # everything so far is setup
            ws.send_json({"type": "table_chat", "text": f"zz-setup-{name}"})
            _until_text(ws, f"zz-setup-{name}")
        msg = dict(case[which])
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
    "a Join with an unknown code": '"table_not_found"',
}


@pytest.mark.parametrize("name", list(QUEUE_CASES))
def test_the_queue_hears_the_old_name_and_the_canonical_one_alike(wsenv, name):  # noqa: F811
    case = QUEUE_CASES[name]
    old = _run_queue(wsenv, case, "old")
    new = _run_queue(wsenv, case, "new")
    assert QUEUE_SEES[name] in " ".join(old[case["actor"]])
    assert new == old


# ------------------------------------------ a table_* message reaches the room
def test_table_messages_from_a_room_socket_reach_the_room_not_the_queue(client):  # noqa: F811
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as h, client.websocket_connect("/ws") as b:
        h.send_json({"type": "create_room", "name": "Host"})
        code = _drain(h, "room")["room"]
        b.send_json({"type": "join_room", "room": code, "name": "Bo", "seat": 2})
        _drain(b, "state", tries=400)
        b.send_json({"type": "table_chat", "text": "hello"})
        assert _next_where(h, "chat", lambda m: m["seat"] == 2,
                           tries=400)["text"] == "hello"
        # a pre-game control is the room's refusal, not the queue's not_seated
        b.send_json({"type": "table_move", "seat": 3})
        assert _drain(b, "error", tries=400) == {"type": "error",
                                                 "message": "Game already started."}
        h.send_json({"type": "table_allow_joiners", "on": False})
        h.send_json({"type": "table_chat", "text": "after"})   # handled in order
        _next_where(h, "chat", lambda m: m["text"] == "after", tries=400)
        assert srv.rooms[code].allow_joiners is False
        b.send_json({"type": "table_leave"})
        assert _drain(b, "left", tries=400) == {"type": "left"}
        # in play the seat stays, the bot covering it
        assert srv.rooms[code].seats[2].left_by_choice


@pytest.mark.parametrize("kind", sorted(tables.LOBBY))
def test_a_running_rooms_pre_game_controls_are_refused(client, kind):  # noqa: F811
    """A room exists only once its game has started, so each pre-game
    control, by its old name or its canonical one, is refused there."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as h:
        h.send_json({"type": "create_room", "name": "Host"})
        code = _drain(h, "room")["room"]
        _drain(h, "state", tries=400)
        before = (srv.rooms[code].host, srv.rooms[code].start_level,
                  [(sd.name, sd.is_bot) for sd in srv.rooms[code].seats])
        h.send_json({"type": kind, "seat": 1, "a": 0, "b": 1, "start_level": "5"})
        assert _drain(h, "error", tries=400) == {"type": "error",
                                                 "message": "Game already started."}
        assert (srv.rooms[code].host, srv.rooms[code].start_level,
                [(sd.name, sd.is_bot) for sd in srv.rooms[code].seats]) == before


# ------------------------------------------------------- the legacy counters
def _legacy(client):
    return client.get("/healthz").json()["legacy_messages"]


def test_old_names_count_at_the_socket_and_canonical_names_do_not(client, monkeypatch):  # noqa: F811
    from shengji.api import server as srv

    monkeypatch.setattr(srv, "ACTIVITY", srv.Activity())
    zero = dict.fromkeys(sorted(tables.LEGACY), 0)
    assert _legacy(client) == zero
    with client.websocket_connect("/ws") as h, client.websocket_connect("/ws") as b:
        h.send_json({"type": "create_room", "name": "Host"})
        code = _drain(h, "room")["room"]
        b.send_json({"type": "table_join", "code": code, "name": "Bo"})
        _drain(b, "state", tries=400)
        b.send_json({"type": "table_chat", "text": "one"})
        _drain(h, "chat", tries=400)
        b.send_json({"type": "chat", "text": "two"})
        _drain(h, "chat", tries=400)
        # a retired control is counted and refused
        h.send_json({"type": "add_bot"})
        assert _drain(h, "error", tries=400) == {"type": "error", "code": "retired",
                                                 "message": tables.RETIRED_MESSAGE}
        # an old pre-game name is counted, a canonical one is not; both refused
        b.send_json({"type": "lobby_ready"})
        assert _drain(b, "error", tries=400)["message"] == "Game already started."
        b.send_json({"type": "table_start", "on": False})
        assert _drain(b, "error", tries=400)["message"] == "Game already started."
        h.send_json({"type": "start_game"})
        assert _drain(h, "error", tries=400)["message"] == "Game already started."
    assert _legacy(client) == {**zero, "create_room": 1, "chat": 1, "add_bot": 1,
                               "lobby_ready": 1, "start_game": 1}
    # every value is a plain count: no codes, ids or text
    assert all(type(v) is int for v in _legacy(client).values())
    assert set(client.get("/healthz").json()["activity"]) == set(srv.Activity().health())


def test_internal_starts_and_new_forms_of_old_names_are_not_counted(wsenv, monkeypatch):  # noqa: F811
    srv, _, client, _ = wsenv
    monkeypatch.setattr(srv, "ACTIVITY", srv.Activity())
    with client.websocket_connect("/ws") as h:
        h.send_json({"type": "create_room", "name": "Host", "start": True})
        _drain(h, "state", tries=400)
    with client.websocket_connect(f"/ws?device={DEVICE_A}") as a:
        a.send_json({"type": "queue_join", "mode": "casual", "name": "Ann"})
        _drain(a, "queue_state")
        # the queue's own start of the room calls _start_game, never start_game
        a.send_json({"type": "table_start_bots"})
        _drain(a, "match_started", tries=400)
    assert srv.ACTIVITY.games_started == 2
    assert _legacy(client) == dict.fromkeys(sorted(tables.LEGACY), 0)
    with client.websocket_connect(f"/ws?device={DEVICE_B}") as b:
        b.send_json({"type": "queue_join", "mode": "casual", "name": "Bo"})
        _drain(b, "queue_state")
        b.send_json({"type": "queue_join", "code": "ZZZZ"})
        _drain(b, "error")
        b.send_json({"type": "queue_start_bots"})
        _drain(b, "match_started", tries=400)
    assert {k: v for k, v in _legacy(client).items() if v} == {"queue_join": 1,
                                                                "queue_start_bots": 1}


# ---------------------------------------------------------- guard parity
@pytest.mark.parametrize("msg", [
    {"type": "queue_start_bots"}, {"type": "table_start_bots"},
    {"type": "queue_join", "code": "ABCD"}, {"type": "table_join", "code": "ABCD"},
])
def test_a_signed_out_guest_is_refused_the_canonical_starts_as_the_old_ones(
        wsenv, monkeypatch, msg):  # noqa: F811
    srv, store, client, _ = wsenv
    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    _account_match(srv, store, client)
    with client.websocket_connect(f"/ws?device={DEVICE_A}") as g:
        g.send_json({**msg, "name": "Lea"})
        assert _drain(g, "error") == {"type": "error", "code": "account_in_game",
                                      "message": "Sign in again to return to your game."}
    assert srv.MATCHMAKER.entry_of == {}


def test_every_canonical_queue_start_is_guarded_as_its_old_name_is():
    from shengji.api import server as srv

    rooms = {"ROOM"}
    for kind, old in (("table_start_bots", "queue_start_bots"),
                      ("table_join", "queue_join"), ("table_start", "table_start"),
                      ("table_leave", "queue_leave"), ("table_peek", "peek_room")):
        new = tables.for_queue({"type": kind, "code": "ABCD"}, joining=False,
                               room_codes=rooms)["type"]
        assert new == old
        assert (new in srv.QUEUE_STARTS) == (old in srv.QUEUE_STARTS)


# ------------------------------------------------------------ the rewrites
def test_the_queue_rewrites():
    def q(msg, joining=False):
        return tables.for_queue(msg, joining=joining, room_codes={"ROOM"})

    assert q({"type": "table_start", "panel_seq": 3}) == {"type": "table_start", "panel_seq": 3}
    assert q({"type": "table_start", "on": False})["type"] == "table_unready"
    assert q({"type": "table_start", "on": True})["type"] == "table_start"
    assert q({"type": "table_start_bots", "panel_seq": 3}) == {"type": "queue_start_bots",
                                                               "panel_seq": 3}
    assert q({"type": "table_leave"})["type"] == "queue_leave"
    assert q({"type": "table_leave"}, joining=True)["type"] == "leave_room"
    assert q({"type": "table_join", "code": " room", "seat": 2, "token": "t"}) == {
        "type": "join_room", "code": " room", "room": "ROOM", "seat": 2, "token": "t"}
    assert q({"type": "table_join", "code": "abcd"}) == {"type": "queue_join", "code": "ABCD"}
    # no code is the room's not-found refusal, never a search
    assert q({"type": "table_join"}) == {"type": "join_room", "room": ""}
    assert q({"type": "table_peek", "code": "room"}) == {"type": "peek_room", "code": "room",
                                                         "room": "ROOM"}
    for same in ("table_move", "table_start_now", "table_chat", "table_allow_joiners",
                 "table_start_level"):
        assert q({"type": same, "x": 1}) == {"type": same, "x": 1}


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
    assert tables.legacy_name({"type": "queue_join", "code": "ABCD"}) == "queue_join"
    assert tables.legacy_name({"type": "create_room"}) == "create_room"
    assert tables.legacy_name({"type": "create_room", "start": True}) is None
    assert all(tables.legacy_name({"type": t}) is None for t in tables.CANONICAL)
    assert tables.legacy_name({"type": "play"}) is None
    assert tables.legacy_name({"type": ["chat"]}) is None
    assert not tables.CANONICAL & tables.LEGACY
    assert all(tables.legacy_name({"type": t}) == t for t in tables.RETIRED)

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

import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import ExitStack

import pytest

from shengji.api import tables

from tests.test_accounts import accounts_on, keypair  # noqa: F401
from tests.test_matchmaking import DEVICE_A, DEVICE_B, Env, _account_match, wsenv  # noqa: F401
from tests.test_ratings import _user
from tests.test_server_ws import _drain, _next_where, client, clock  # noqa: F401

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
        "ranked": room.ranked, "start_level": room.start_level,
        "seats": [None if sd is None else (sd.name, sd.is_bot, sd.user_id)
                  for sd in room.seats],
        "host": room.host, "allow_joiners": room.allow_joiners,
        "started": room.game is not None,
    }


def _run_room(env, clock, case: dict, which: str) -> dict:
    """``case`` set up with the old names, then its action sent as
    ``case[which]``; returns everything visible afterwards."""
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
        for name in case.get("humans", ("Bo",)):
            w = stack.enter_context(client.websocket_connect("/ws"))
            w.send_json({"type": "join_room", "room": code, "name": name})
            _drain(w, "room")
            socks[name] = w
        for _ in range(case.get("bots", 0)):
            h.send_json({"type": "add_bot"})
        for name in case.get("ready", ()):
            socks[name].send_json({"type": "lobby_ready"})
        if case.get("started"):
            h.send_json({"type": "start_game"})
        clock["v"] += case.get("wait", 0.0)
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


BO = {"name": "Bo", "is_bot": False}
ZED = {"name": "Zed", "is_bot": False}
# The host sits at 0 and Bo, the host's partner, at 2.
ROOM_CASES = {
    "a self move": dict(actor="Bo", old={"type": "swap_seats", "a": 2, "b": 3},
                        new={"type": "table_move", "seat": 3}),
    "the host's self move": dict(actor="Host", old={"type": "swap_seats", "a": 0, "b": 1},
                                 new={"type": "table_move", "seat": 1}),
    "a self move onto a taken seat": dict(actor="Bo", old={"type": "swap_seats", "a": 2, "b": 0},
                                          new={"type": "table_move", "seat": 0}),
    "the host moves another": dict(
        actor="Host", old={"type": "swap_seats", "a": 2, "b": 1, "expect": [BO, None]},
        new={"type": "table_move", "from": 2, "seat": 1, "expect": [BO, None]}),
    "the host move of a changed seat": dict(
        actor="Host", old={"type": "swap_seats", "a": 2, "b": 1, "expect": [ZED, None]},
        new={"type": "table_move", "from": 2, "seat": 1, "expect": [ZED, None]}),
    "a guest moving the host": dict(actor="Bo", old={"type": "swap_seats", "a": 0, "b": 1},
                                    new={"type": "table_move", "from": 0, "seat": 1}),
    "a move after Start": dict(actor="Bo", ready=("Bo",), old={"type": "swap_seats", "a": 2, "b": 3},
                               new={"type": "table_move", "seat": 3}),
    "a Start": dict(actor="Bo", old={"type": "lobby_ready"}, new={"type": "table_start"}),
    "a Start taken back": dict(actor="Bo", ready=("Bo",), old={"type": "lobby_ready", "on": False},
                               new={"type": "table_start", "on": False}),
    "the last Start starts": dict(actor="Host", ready=("Bo",), old={"type": "lobby_ready"},
                                  new={"type": "table_start"}),
    "Start now alone with bots": dict(actor="Host", humans=(), bots=3,
                                      old={"type": "start_game"}, new={"type": "table_start_now"}),
    "Start now once its wait is over": dict(actor="Host", wait=31.0, old={"type": "start_game"},
                                            new={"type": "table_start_now"}),
    "Start now by a guest": dict(actor="Bo", wait=31.0, old={"type": "start_game"},
                                 new={"type": "table_start_now"}),
    "Start now in play": dict(actor="Host", started=True, old={"type": "start_game"},
                              new={"type": "table_start_now"}, actor_ends="error"),
    "a Start in play": dict(actor="Bo", started=True, old={"type": "lobby_ready"},
                            new={"type": "table_start"}, actor_ends="error"),
    "Allow joiners off": dict(actor="Host", old={"type": "allow_joiners", "on": False},
                              new={"type": "table_allow_joiners", "on": False}),
    "Allow joiners by a guest": dict(actor="Bo", old={"type": "allow_joiners", "on": False},
                                     new={"type": "table_allow_joiners", "on": False}),
    "Allow joiners in play": dict(actor="Host", started=True,
                                  old={"type": "allow_joiners", "on": False},
                                  new={"type": "table_allow_joiners", "on": False}),
    "a starting level": dict(actor="Host", ready=("Bo",),
                             old={"type": "set_start_level", "start_level": "5"},
                             new={"type": "table_start_level", "start_level": "5"}),
    "a starting level by a guest": dict(actor="Bo",
                                        old={"type": "set_start_level", "start_level": "5"},
                                        new={"type": "table_start_level", "start_level": "5"}),
    "lobby chat": dict(actor="Bo", old={"type": "chat", "text": " hi all "},
                       new={"type": "table_chat", "text": " hi all "}),
    "chat in play": dict(actor="Bo", started=True, old={"type": "chat", "text": "gl"},
                         new={"type": "table_chat", "text": "gl"}),
    "a lobby Leave": dict(actor="Bo", actor_ends="left", old={"type": "leave_room"},
                          new={"type": "table_leave"}),
    "the host's lobby Leave": dict(actor="Host", end_from="Bo", actor_ends="left",
                                   old={"type": "leave_room"}, new={"type": "table_leave"}),
    "a Leave in play": dict(actor="Bo", started=True, actor_ends="left",
                            old={"type": "leave_room"}, new={"type": "table_leave"}),
    "a Join": dict(actor="Cy", outsider=True, actor_ends="room",
                   old={"type": "join_room", "room": "<CODE>", "name": "Cy"},
                   new={"type": "table_join", "code": "<CODE>", "name": "Cy"}),
    "a Join into a bot's seat in play": dict(
        actor="Cy", outsider=True, started=True, actor_ends="state",
        old={"type": "join_room", "room": "<CODE>", "name": "Cy", "seat": 3},
        new={"type": "table_join", "code": "<CODE>", "name": "Cy", "seat": 3}),
    "a Join into a taken seat in play": dict(
        actor="Cy", outsider=True, started=True, actor_ends="error",
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
    "a self move": '"seat": 3', "the host's self move": '"seat": 1',
    "a self move onto a taken seat": "Pick an empty seat.",
    "the host moves another": '"name": "Bo", "seat": 1',
    "the host move of a changed seat": '"seat_changed"',
    "a guest moving the host": "Only the host can move other players.",
    "a move after Start": "You tapped Start, so your seat is set.",
    "a Start": '"ready": [2]', "a Start taken back": '"ready": []',
    "the last Start starts": '"type": "state"', "Start now alone with bots": '"type": "state"',
    "Start now once its wait is over": '"type": "state"',
    "Start now by a guest": "Only the host can start.",
    "Start now in play": "Game already started.", "a Start in play": "Game already started.",
    "Allow joiners off": '"allow_joiners": false',
    "Allow joiners by a guest": '"not_opener"', "Allow joiners in play": '"type": "state"',
    "a starting level": '"start_level": "5"',
    "a starting level by a guest": "Only the host can set the starting level.",
    "lobby chat": '"text": "hi all"', "chat in play": '"text": "gl"',
    "a lobby Leave": '"left"', "the host's lobby Leave": '"left"', "a Leave in play": '"left"',
    "a Join": "Cy joined", "a Join into a bot's seat in play": "Cy took Bot 3's seat",
    "a Join into a taken seat in play": "seat_unavailable", "a peek": '"room_seats"',
    "a peek at an unknown code": "room_not_found",
}


@pytest.mark.parametrize("name", list(ROOM_CASES))
def test_a_room_hears_the_old_name_and_the_canonical_one_alike(wsenv, clock, name):  # noqa: F811
    case = ROOM_CASES[name]
    old = _run_room(wsenv, clock, case, "old")
    new = _run_room(wsenv, clock, case, "new")
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


# ---------------------------------------------- Start now waits in a room too
def test_a_rooms_table_start_now_waits_30_s_after_the_last_arrival_and_start_game_does_not(
        client, clock):  # noqa: F811
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as h, client.websocket_connect("/ws") as b, \
            client.websocket_connect("/ws") as c:
        h.send_json({"type": "create_room", "name": "Host"})
        code = _drain(h, "room")["room"]
        clock["v"] += 100.0                      # the host alone has no wait
        b.send_json({"type": "join_room", "room": code, "name": "Bo"})
        _drain(b, "room")
        h.send_json({"type": "table_start_now"})
        assert _drain(h, "error") == {"type": "error", "code": "too_soon",
                                      "message": tables.TOO_SOON}
        clock["v"] += 20.0
        c.send_json({"type": "join_room", "room": code, "name": "Cy"})
        _drain(c, "room")
        clock["v"] += 15.0                       # 35 s after Bo, 15 s after Cy
        h.send_json({"type": "table_start_now"})
        assert _drain(h, "error")["code"] == "too_soon"
        assert srv.rooms[code].game is None
        clock["v"] += 15.0
        h.send_json({"type": "table_start_now"})
        assert _drain(h, "state", tries=400)["you"] == 0
        assert srv.rooms[code].game is not None


def test_a_rooms_start_game_still_starts_at_once(client, clock):  # noqa: F811
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as h, client.websocket_connect("/ws") as b:
        h.send_json({"type": "create_room", "name": "Host"})
        code = _drain(h, "room")["room"]
        b.send_json({"type": "join_room", "room": code, "name": "Bo"})
        assert _drain(h, "room")["start_now_in"] == 30.0
        h.send_json({"type": "start_game"})
        assert _drain(h, "state", tries=400)["you"] == 0
        assert srv.rooms[code].game is not None


def test_the_rooms_too_soon_is_the_queues_refusal_word_for_word():
    async def go():
        env = Env()
        for uid in (1, 2):
            await env.join(uid)
            await env.send(uid, "queue_wait_players")
        await env.send(1, "table_start_now")
        return env.conns[1].last("error")

    assert asyncio.run(go()) == {"type": "error", "code": "too_soon", "message": tables.TOO_SOON}


# ------------------------------------------ a table_* message reaches the room
def test_table_messages_from_a_room_socket_reach_the_room_not_the_queue(client):  # noqa: F811
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as h, client.websocket_connect("/ws") as b:
        h.send_json({"type": "create_room", "name": "Host"})
        code = _drain(h, "room")["room"]
        b.send_json({"type": "join_room", "room": code, "name": "Bo"})
        _drain(b, "room")
        b.send_json({"type": "table_chat", "text": "hello"})
        assert _next_where(h, "chat", lambda m: m["seat"] == 2)["text"] == "hello"
        b.send_json({"type": "table_move", "seat": 3})
        _next_where(h, "room", lambda m: [p["seat"] for p in m["players"]] == [0, 3])
        b.send_json({"type": "table_start"})
        _next_where(h, "room", lambda m: m["ready"] == [3])
        h.send_json({"type": "table_start_level", "start_level": "4"})
        _next_where(b, "room", lambda m: m["start_level"] == "4")
        h.send_json({"type": "table_allow_joiners", "on": False})
        _next_where(b, "room", lambda m: m["allow_joiners"] is False)
        b.send_json({"type": "table_leave"})
        assert _drain(b, "left") == {"type": "left"}
        assert [sd.name for sd in srv.rooms[code].seats if sd is not None] == ["Host"]


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
        _drain(b, "room")
        b.send_json({"type": "table_chat", "text": "one"})
        _drain(h, "chat")
        b.send_json({"type": "chat", "text": "two"})
        _drain(h, "chat")
        h.send_json({"type": "add_bot"})
        _drain(h, "room")
        b.send_json({"type": "lobby_ready"})
        _drain(h, "room")
        b.send_json({"type": "table_start", "on": False})
        _drain(h, "room")
        h.send_json({"type": "start_game"})
        _drain(h, "state", tries=400)
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
    def r(msg, seat=2):
        return tables.for_room(msg, seat)

    assert r({"type": "table_move", "seat": 3}) == {"type": "swap_seats", "seat": 3,
                                                    "a": 2, "b": 3}
    assert r({"type": "table_move", "seat": 3, "from": 1, "expect": [None, None]}) == {
        "type": "swap_seats", "seat": 3, "from": 1, "expect": [None, None], "a": 1, "b": 3}
    assert r({"type": "table_start"}) == {"type": "lobby_ready"}
    assert r({"type": "table_start", "on": False}) == {"type": "lobby_ready", "on": False}
    assert r({"type": "table_start_bots", "on": False}) == {"type": "lobby_ready", "on": True}
    assert r({"type": "table_start_now"}) == {"type": "start_game"}
    assert r({"type": "table_allow_joiners", "on": True}) == {"type": "allow_joiners", "on": True}
    assert r({"type": "table_start_level", "start_level": "3"}) == {
        "type": "set_start_level", "start_level": "3"}
    assert r({"type": "table_chat", "text": "hi"}) == {"type": "chat", "text": "hi"}
    assert r({"type": "table_leave"}) == {"type": "leave_room"}
    assert r({"type": "table_join", "code": "ROOM"})["type"] == "join_room"
    assert r({"type": "table_peek", "code": "ROOM"})["type"] == "peek_room"


def test_legacy_names():
    assert tables.legacy_name({"type": "queue_join"}) is None
    assert tables.legacy_name({"type": "queue_join", "code": "ABCD"}) == "queue_join"
    assert tables.legacy_name({"type": "create_room"}) == "create_room"
    assert tables.legacy_name({"type": "create_room", "start": True}) is None
    assert all(tables.legacy_name({"type": t}) is None for t in tables.CANONICAL)
    assert tables.legacy_name({"type": "play"}) is None
    assert tables.legacy_name({"type": ["chat"]}) is None
    assert not tables.CANONICAL & tables.LEGACY

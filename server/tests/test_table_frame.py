"""The ``table`` frame (PROTOCOL.md "The table frame"): one description of a
table, from a queue ``Table`` (``Matchmaker.table_frame``) or a ``Room`` in
play (``server.room_table_frame``), sent next to the frames it will replace.

Every matchmaking golden scenario is replayed: each ``queue_state`` that holds
the entry is followed by exactly one ``table`` frame, and that frame says
what the ``queue_state`` says (``from_queue_state`` maps old to new). The
room side is checked against ``room``, ``state`` and ``room_seats``."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests import test_matchmaking_golden as golden
from tests.test_server_ws import _drain, client  # noqa: F401

FRAME_KEYS = {"type", "code", "phase", "mode", "you", "opener", "seats", "settings",
              "timers", "your_ready", "waiting_for", "chat_log"}
SEAT_KEYS = {"seat", "team", "state", "name", "you", "ready", "reconnecting", "since",
             "sit", "pair", "leader", "left"}
# a seat's fields from queue_state.table that the table frame carries as is
QUEUE_SEAT_FIELDS = ("name", "you", "ready", "reconnecting", "since", "sit", "pair", "leader")


def _shape(frame: dict) -> None:
    """The frame's keys are exactly the documented ones: no account id,
    rating, resume token or device key can ride along."""
    assert set(frame) == FRAME_KEYS, sorted(frame)
    assert [s["seat"] for s in frame["seats"]] == [0, 1, 2, 3]
    for s in frame["seats"]:
        assert set(s) == SEAT_KEYS, sorted(s)
        assert s["team"] == s["seat"] % 2
        assert s["state"] in ("taken", "open", "held", "bot")
        if s["state"] in ("open", "held"):
            assert s["name"] is None
    assert set(frame["settings"]) == {"allow_joiners", "start_level"}
    assert set(frame["timers"]) == {"bots", "start_now_at"}


def from_queue_state(qs: dict) -> dict:
    """What a ``queue_state`` that holds the entry says about its table, in
    the table frame's terms. A waiting table (``qs.table``) fills every
    field; alone, ``qs.table`` is null and only the table-wide fields and
    your own Start are said."""
    out: dict = {"type": "table", "phase": "open", "code": qs["code"], "mode": qs["mode"],
                 "settings": {"allow_joiners": qs["allow_joiners"],
                              "start_level": qs["start_level"]},
                 "your_ready": qs["you_ready"]}
    t = qs["table"]
    if t is None:
        out["chat_log"] = None
        return out
    seats = []
    for i, s in enumerate(t["seats"]):
        if s is None:
            seats.append({"seat": i, "state": "held" if i in t["held_seats"] else "open",
                          "name": None})
        else:
            seats.append({"seat": i, "state": "taken", **{k: s[k] for k in QUEUE_SEAT_FIELDS}})
    out.update(code=t["code"], you=t["you"], opener=t["opener"], seats=seats,
               timers={"bots": t["timer"], "start_now_at": t["start_now_at"]},
               your_ready=t["you_ready"], waiting_for=t["waiting_for"], chat_log=t["id"])
    return out


def _agrees(frame: dict, qs: dict) -> None:
    _shape(frame)
    want = from_queue_state(qs)
    for k, v in want.items():
        if k == "seats":
            for got, w in zip(frame["seats"], v):
                assert {f: got[f] for f in w} == w, (got, w)
        else:
            assert frame[k] == v, (k, frame[k], v)
    # the rest of queue_state's table fields follow from the frame's seats
    taken = [s for s in frame["seats"] if s["state"] == "taken"]
    if qs["table"] is not None:
        assert qs["table"]["ready"] == sum(s["ready"] for s in taken)
        assert qs["table"]["of"] == len(taken)
        assert qs["table"]["held_seat"] == next(
            (s["seat"] for s in frame["seats"] if s["state"] == "held"), None)
    else:
        assert frame["timers"]["start_now_at"] is None
        assert frame["timers"]["bots"] == (None if qs["bots_at"] is None else
                                           {**frame["timers"]["bots"], "at": qs["bots_at"]})
    if qs["held_seat"] is not None:
        assert frame["seats"][qs["held_seat"]]["state"] == "held"
    if qs["duo_ready"] is not None:
        mine = frame["seats"][frame["you"]]["team"]
        assert qs["duo_ready"] == sum(s["ready"] for s in taken if s["pair"] and s["team"] == mine)
    assert qs["opener"] == (frame["opener"] == frame["you"])
    assert frame["seats"][frame["you"]]["you"]
    # the client's panel kind (web/src/queue/tableText.ts panelKind) reads
    # the frame alone: shared iff someone other than you and your Duo
    # partner sits there
    assert shared(frame) == (qs["table"] is not None)


def shared(frame: dict) -> bool:
    """Someone else sits at the table: a taken seat that is neither you nor
    your Duo partner (across from you, both seats ``pair``)."""
    you = frame["you"]
    mine = frame["seats"][you]
    partner = (you + 2) % 4 if mine["pair"] else None
    return any(s["state"] == "taken" and not s["you"]
               and not (s["seat"] == partner and s["pair"]) for s in frame["seats"])


@pytest.mark.parametrize("name", sorted(golden.SCENARIOS))
def test_every_held_queue_state_is_followed_by_its_table_frame(name):
    env = golden.run_env(golden.SCENARIOS[name])
    pairs = 0
    for conn in env.all_conns:
        sent = conn.sent
        for i, m in enumerate(sent):
            holds = (m["type"] == "queue_state" and m.get("queued")
                     and not m.get("elsewhere"))
            if m["type"] == "table":
                prev = sent[i - 1] if i else {}
                assert prev.get("type") == "queue_state" and prev.get("queued") \
                    and not prev.get("elsewhere"), (conn.label, i, prev)
            if holds:
                nxt = sent[i + 1] if i + 1 < len(sent) else None
                assert nxt is not None and nxt["type"] == "table", (conn.label, i)
                _agrees(nxt, m)
                pairs += 1
    assert pairs, "the scenario never held an entry"


# The client's port of ``from_queue_state`` (web/src/queue/testFrames.ts)
# is checked against these pairs: one per kind of held queue_state.
WEB_FIXTURE = (Path(__file__).resolve().parents[2] / "web" / "src" / "queue" / "fixtures"
               / "table_frames.json")


def _kind(qs: dict, frame: dict) -> tuple:
    return (qs["table"] is not None, qs["duo"], qs["duo_ready"] is not None, qs["leader"],
            qs["opener"], qs["held_seat"] is not None, qs["you_ready"])


def web_pairs() -> list[dict]:
    """``(party, queue_state, table)`` for the first held queue_state of each
    kind over the golden scenarios, normalized as the goldens are. ``party``
    names a pair's partner: the socket's pair frame of that ``party_id``
    (the server may send it just after the queue_state), else null."""
    out, seen = [], set()
    for name in sorted(golden.SCENARIOS):
        env = golden.run_env(golden.SCENARIOS[name])
        for conn in env.all_conns:
            for i, m in enumerate(conn.sent):
                holds = (m["type"] == "queue_state" and m.get("queued")
                         and not m.get("elsewhere"))
                if not holds:
                    continue
                pid = m.get("party_id")
                near = sorted((abs(j - i), j) for j, p in enumerate(conn.sent)
                              if pid and p["type"] == "party" and p["party_id"] == pid)
                party = conn.sent[near[0][1]] if near else None
                k = _kind(m, conn.sent[i + 1])
                if k in seen:
                    continue
                seen.add(k)
                ev = golden.normalize([["pair", party, m, conn.sent[i + 1]]])[0]
                out.append({"scenario": name, "party": ev[1], "queue_state": ev[2], "table": ev[3]})
    return out


def _web_fixture_text() -> str:
    rows = [json.dumps(p, sort_keys=True, separators=(",", ":")) for p in web_pairs()]
    return "[\n" + ",\n".join(rows) + "\n]\n"


def test_the_web_frame_fixture_is_current():
    """Regenerate with ``python -m tests.test_table_frame --write`` (from
    ``server/``)."""
    assert WEB_FIXTURE.read_text() == _web_fixture_text()


def test_the_golden_log_never_holds_the_table_frame():
    """The goldens of the old frames stay byte for byte: the harness keeps
    the additive frame out of the log."""
    for name, fn in golden.SCENARIOS.items():
        env = golden.run_env(fn)
        assert any(m["type"] == "table" for c in env.all_conns for m in c.sent), name
        assert not any(ev[0] == "frame" and ev[2]["type"] == "table" for ev in env.log), name


# ------------------------------------------------------------------ rooms
def _next(ws, timeout: float = 5.0) -> dict:
    import tests.test_server_ws as sw
    m = sw._recv(ws, timeout)
    if m is None:
        raise AssertionError(f"no frame within {timeout}s")
    return m


def _until(ws, kind: str) -> list[dict]:
    import tests.test_server_ws as sw
    return sw._frames_until(ws, lambda m: m["type"] == kind, repr(kind))


def _agrees_with_room(frame: dict, room: dict, state: dict | None) -> None:
    _shape(frame)
    assert frame["phase"] == "playing" and frame["code"] == room["room"]
    assert frame["you"] == room["you"] and frame["opener"] == room["opener"] == room["host"]
    assert frame["settings"] == {"allow_joiners": room.get("allow_joiners"),
                                 "start_level": room["start_level"]}
    assert frame["chat_log"] == room["room"]
    assert frame["timers"] == {"bots": None, "start_now_at": None}
    assert frame["your_ready"] is None and frame["waiting_for"] is None
    by_seat = {p["seat"]: p for p in (state or room)["players"]}
    for s in frame["seats"]:
        p = by_seat[s["seat"]]
        assert s["name"] == p["name"] and s["you"] == (s["seat"] == frame["you"])
        assert (s["state"] == "bot") == (p["is_bot"] or bool(p.get("left")))
        assert s["reconnecting"] == (s["state"] == "taken" and not p["connected"])
        assert s["ready"] is None and s["sit"] is None and s["since"] is None


def test_a_created_room_sends_its_table_frame_once_with_its_room_frame(client):
    with client.websocket_connect("/ws") as a:
        a.send_json({"type": "create_room", "name": "amy"})
        first = _until(a, "table")
        kinds = [m["type"] for m in first]
        # the room frame, then the game's first state and right after it the
        # table frame
        assert kinds.index("room") < kinds.index("state") == kinds.index("table") - 1
        room, frame, state = first[kinds.index("room")], first[-1], first[-2]
        _agrees_with_room(frame, room, state)
        assert frame["mode"] == "casual"
        assert [s["state"] for s in frame["seats"]] == ["taken", "bot", "bot", "bot"]
        # the deal's many state frames change nothing at the table: no resend
        more = [_next(a) for _ in range(30)]
        assert sum(m["type"] == "state" for m in more) >= 20
        assert not any(m["type"] == "table" for m in more)


def test_a_join_resends_the_table_frame_to_everyone_and_the_joiner_gets_it(client):
    with client.websocket_connect("/ws") as a:
        a.send_json({"type": "create_room", "name": "amy"})
        room = _drain(a, "room")
        code = room["room"]
        _drain(a, "state")
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "bea", "seat": 2})
            got = _until(b, "table")
            mine = [m for m in got if m["type"] == "table"]
            assert len(mine) == 1 and got[-2]["type"] == "state"
            _agrees_with_room(mine[0], {**room, "you": 2}, got[-2])
            assert mine[0]["seats"][2]["state"] == "taken" and mine[0]["seats"][2]["you"]
            # amy's next table frame shows bea at seat 2
            for _ in range(400):
                m = _next(a)
                if m["type"] == "table" and m["seats"][2]["name"] == "bea":
                    break
            else:
                raise AssertionError("amy never saw bea's seat")
            assert m["you"] == 0 and m["seats"][2]["state"] == "taken"
        # bea's socket is gone: amy sees the seat reconnecting
        for _ in range(400):
            m = _next(a)
            if m["type"] == "table" and m["seats"][2]["reconnecting"]:
                break
        else:
            raise AssertionError("amy never saw bea reconnecting")
        assert m["seats"][2]["state"] == "taken" and m["seats"][2]["name"] == "bea"


def test_a_room_table_frame_names_its_seats_as_a_peek_does(client):
    """A room's ``room_seats`` and its table frame agree on every seat's
    name, team and bot."""
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        a.send_json({"type": "create_room", "name": "amy"})
        frame = _until(a, "table")[-1]
        b.send_json({"type": "table_peek", "code": frame["code"]})
        peek = _drain(b, "room_seats")
    for s, p in zip(frame["seats"], peek["seats"]):
        assert (s["name"], s["team"], s["state"] == "bot") == (p["name"], p["team"], p["is_bot"])


if __name__ == "__main__":
    if sys.argv[1:] != ["--write"]:
        print("usage: python -m tests.test_table_frame --write", file=sys.stderr)
        raise SystemExit(2)
    WEB_FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    WEB_FIXTURE.write_text(_web_fixture_text())
    print(f"wrote {WEB_FIXTURE}")

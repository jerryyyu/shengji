"""A held ``queue_state`` read together with the ``table`` frame sent right
after it, in the terms the queue tests assert: ``seen["table"]`` is the
waiting table (null alone), and ``code``, ``allow_joiners``, ``start_level``,
``opener``, ``held_seat``, ``you_ready`` and, alone, ``bots_at`` describe your
table. Every value is read off the frame; the server sends none of these
names (PROTOCOL.md "The table frame")."""
from __future__ import annotations

from typing import Any


def shared(frame: dict) -> bool:
    """Someone else sits at the table: a taken seat that is neither you nor
    your Duo partner (across from you, both seats ``pair``)."""
    you = frame["you"]
    mine = frame["seats"][you]
    partner = (you + 2) % 4 if mine["pair"] else None
    return any(s["state"] == "taken" and not s["you"]
               and not (s["seat"] == partner and s["pair"]) for s in frame["seats"])


SEAT_FIELDS = ("name", "you", "ready", "reconnecting", "since", "sit", "pair", "leader")


def waiting_table(frame: dict) -> dict | None:
    """The waiting table the frame describes; None while you are alone (or
    only with your Duo partner). Seats are taken ones, else None."""
    if not shared(frame):
        return None
    seats = [{k: s[k] for k in SEAT_FIELDS} if s["state"] == "taken" else None
             for s in frame["seats"]]
    taken = [s for s in seats if s is not None]
    held = [s["seat"] for s in frame["seats"] if s["state"] == "held"]
    return {"id": frame["chat_log"], "code": frame["code"], "seats": seats,
            "opener": frame["opener"], "you": frame["you"],
            "held_seat": held[0] if held else None, "held_seats": held,
            "start_now_at": frame["timers"]["start_now_at"], "timer": frame["timers"]["bots"],
            "ready": sum(s["ready"] for s in taken), "of": len(taken),
            "you_ready": frame["your_ready"], "waiting_for": frame["waiting_for"]}


def holds(m: dict | None) -> bool:
    """A queue_state that holds the entry on this socket, so its frame follows."""
    return bool(m) and m["type"] == "queue_state" and m.get("queued") and not m.get("elsewhere")


def read(qs: dict, frame: dict | None) -> dict:
    """``qs`` with its table frame's fields, as the tests name them."""
    if not holds(qs):
        return qs
    assert frame is not None and frame["type"] == "table" and frame["phase"] == "open", frame
    held = [s["seat"] for s in frame["seats"] if s["state"] == "held"]
    t = waiting_table(frame)
    bots = frame["timers"]["bots"]
    out: dict[str, Any] = {
        **qs, "table": t, "code": frame["code"], "opener": frame["opener"] == frame["you"],
        "allow_joiners": frame["settings"]["allow_joiners"],
        "start_level": frame["settings"]["start_level"],
        "held_seat": held[0] if held else None, "you_ready": frame["your_ready"]}
    if t is None:
        out["bots_at"] = bots["at"] if bots is not None else None
    return out


def seen(conn) -> dict | None:
    """A test socket's last queue_state, read with the frame after it."""
    sent = conn.sent
    i = next((i for i in range(len(sent) - 1, -1, -1) if sent[i]["type"] == "queue_state"), None)
    if i is None:
        return None
    return read(sent[i], sent[i + 1] if i + 1 < len(sent) else None)


def seen_all(conn) -> list[dict]:
    """Every queue_state a test socket was sent, each read with its frame."""
    sent = conn.sent
    return [read(m, sent[i + 1] if i + 1 < len(sent) else None)
            for i, m in enumerate(sent) if m["type"] == "queue_state"]


def _drain_seen(ws) -> dict:
    """A socket's next queue_state, read with the table frame after it."""
    from tests.test_server_ws import _drain, _next
    qs = _drain(ws, "queue_state")
    return read(qs, _next(ws, "table") if holds(qs) else None)


def _next_seen_where(ws, pred) -> dict:
    """A socket's next queue_state, read with its table frame, for which
    ``pred`` holds; earlier ones are skipped."""
    while True:
        m = _drain_seen(ws)
        if pred(m):
            return m

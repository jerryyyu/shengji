"""One message family for a table, wherever the socket sits.

A table is open in the queue (a waiting ``Table``, or a lone entry) and
plays in a ``Room``, which exists only once its game has started. The
canonical ``table_*`` names below mean the same thing in each place; this
module rewrites a canonical message into the message the socket's backend
already handles, so every guard, rate limit and refusal of that backend
applies to it unchanged. Those backend names are the server's own: a client
frame that carries one (``RETIRED``) is refused before any rewrite, and
``legacy_name`` names it for the ``/healthz`` counts of stale pages.

The rewrite keeps every field the client sent (``panel_seq``, ``expect``,
``name`` and the rest) and changes only ``type`` and the fields the target
names differently.
"""
from __future__ import annotations

from collections.abc import Container
from typing import Any

from .matchmaking import normalize_code

CANONICAL = frozenset({
    "table_move", "table_start", "table_start_now", "table_start_bots",
    "table_allow_joiners", "table_start_level", "table_relaxed_bots", "table_chat",
    "table_leave", "table_join", "table_peek",
})

# The names a canonical name replaced, the created room's old lobby
# controls, which no table has any more, ``code_lookup``, whose question
# ``table_peek`` answers with the seats, the Duo made by its own code (a
# Duo is made at a table: ``queue_join {duo}`` and its code's joiner) and
# the ready check's answers (the waiting table is the accept). A client
# frame with one is refused with the code ``retired`` (``RETIRED_MESSAGE``)
# and counted. ``queue_join`` is one only with a ``code`` (a join); without
# one it is the search, which has no other name.
RETIRED = frozenset({
    "swap_seats", "lobby_ready", "table_unready", "start_game", "queue_start_bots",
    "allow_joiners", "set_start_level", "chat", "leave_room", "queue_leave",
    "join_room", "queue_join", "peek_room", "code_lookup",
    "add_bot", "remove_bot", "remove_player", "set_ranked",
    "party_create", "party_invite", "party_join", "match_accept", "match_decline",
})
RETIRED_MESSAGE = "This page is out of date. Reload to play."
# ``create_room`` counts only without ``start: true``; it starts the game at
# once either way, so it is counted and still answered.
LEGACY = RETIRED | {"create_room"}

# What sets up a table before its game: a room's game has always started, so
# in a room each is refused.
LOBBY = frozenset({"table_move", "table_start", "table_start_now", "table_start_bots",
                   "table_start_level", "table_relaxed_bots"})


def legacy_name(msg: dict) -> str | None:
    """The old name ``msg`` uses, or None for a canonical or other message."""
    t = msg.get("type")
    if not isinstance(t, str) or t not in LEGACY:
        return None
    if t == "queue_join" and msg.get("code") is None:
        return None
    if t == "create_room" and msg.get("start") is True:
        return None
    return t


def retired(msg: dict) -> bool:
    """Whether a client frame ``msg`` uses a retired name, refused unread."""
    return legacy_name(msg) in RETIRED


def _as(msg: dict, kind: str, **fields: Any) -> dict:
    return {**msg, "type": kind, **fields}


def for_queue(msg: dict, *, joining: bool, room_codes: Container[str],
              table_codes: Container[str]) -> dict:
    """``msg`` (a canonical name) as a socket outside any room sends it.

    ``joining``: the socket has an invite Join waiting for its handover,
    which a Leave ends as ``leave_room`` does. ``room_codes``: the live
    rooms, and ``table_codes`` the queue's tables, since a code names
    either.

    A ``table_join`` goes to the room its code names, else to the queue
    table it names. A code that names neither is refused by the place the
    client expected: ``expect: "room"`` (a resume, a room link, a peek that
    showed a room) gets the room's ``room_not_found``, which ends a dead
    room on the page; anything else the queue's ``table_not_found``. No
    code at all is the room's refusal, never a search.
    """
    t = msg["type"]
    if t == "table_start":
        return _as(msg, "table_unready") if msg.get("on") is False else msg
    if t == "table_start_bots":
        return _as(msg, "queue_start_bots")
    if t == "table_leave":
        return _as(msg, "leave_room" if joining else "queue_leave")
    if t == "table_join":
        code = normalize_code(msg.get("code"))
        if code and code not in room_codes and (
                code in table_codes or msg.get("expect") != "room"):
            return _as(msg, "queue_join", code=code)
        return _as(msg, "join_room", room=code)
    if t == "table_peek":
        return _as(msg, "peek_room", room=normalize_code(msg.get("code")))
    return msg


def for_room(msg: dict) -> dict:
    """``msg`` (a canonical name) as a person seated in a room's game sends
    it. The names that set a table up before its game (``LOBBY``) stay as
    they are, for the room to refuse."""
    t = msg["type"]
    if t == "table_allow_joiners":
        return _as(msg, "allow_joiners")
    if t == "table_chat":
        return _as(msg, "chat")
    if t == "table_leave":
        return _as(msg, "leave_room")
    if t == "table_join":
        return _as(msg, "join_room", room=msg.get("code", ""))
    if t == "table_peek":
        return _as(msg, "peek_room", room=msg.get("code", ""))
    return msg

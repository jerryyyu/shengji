"""One message family for a table, wherever the socket sits.

A table is open in the queue (a waiting ``Table``, or a lone entry) and
plays in a ``Room``, which exists only once its game has started. The
canonical ``table_*`` names below mean the same thing in each place; this
module rewrites a canonical message into the message the socket's backend
already handles, so every guard, rate limit and refusal of that backend
applies to it unchanged. The older names stay accepted as aliases, and
``legacy_name`` names the ones an old page still sends, for the ``/healthz``
counts that say when an alias can retire.

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
    "table_allow_joiners", "table_start_level", "table_chat", "table_leave",
    "table_join", "table_peek",
})

# Old names that a canonical name replaces. ``queue_join`` counts only with
# a ``code`` (a join); without one it is the search, which has no other name.
ALIASES = frozenset({
    "swap_seats", "lobby_ready", "table_unready", "start_game", "queue_start_bots",
    "allow_joiners", "set_start_level", "chat", "leave_room", "queue_leave",
    "join_room", "queue_join", "peek_room",
})
# The created room's old lobby controls, which no table has any more: each is
# refused with the code ``retired`` (``RETIRED_MESSAGE``), and still counted.
RETIRED = frozenset({"add_bot", "remove_bot", "remove_player", "set_ranked"})
RETIRED_MESSAGE = "This page is out of date. Reload to play."
# ``create_room`` counts only without ``start: true``; it starts the game at
# once either way.
LEGACY = ALIASES | RETIRED | {"create_room"}

# What sets up a table before its game, old and canonical names alike: a
# room's game has always started, so in a room each is refused.
LOBBY = frozenset({"swap_seats", "lobby_ready", "set_start_level", "table_move",
                   "table_start", "table_start_now", "table_start_bots",
                   "table_start_level"})


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


def _as(msg: dict, kind: str, **fields: Any) -> dict:
    return {**msg, "type": kind, **fields}


def for_queue(msg: dict, *, joining: bool, room_codes: Container[str]) -> dict:
    """``msg`` (a canonical name) as a socket outside any room sends it.

    ``joining``: the socket has an invite Join waiting for its handover,
    which a Leave ends as ``leave_room`` does. ``room_codes``: the live
    rooms, since a code names either a room or a queue table.
    """
    t = msg["type"]
    if t == "table_start":
        return _as(msg, "table_unready") if msg.get("on") is False else msg
    if t == "table_start_bots":
        return _as(msg, "queue_start_bots")
    if t == "table_leave":
        return _as(msg, "leave_room" if joining else "queue_leave")
    if t == "table_join":
        # a code that names nothing is the room's refusal, never a search
        code = normalize_code(msg.get("code"))
        if not code or code in room_codes:
            return _as(msg, "join_room", room=code)
        return _as(msg, "queue_join", code=code)
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

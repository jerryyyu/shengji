"""Player reports from the table (the ``report_player`` socket message).

A report appends one JSON line to ``player_reports.jsonl`` in
``accounts.data_dir()``, beside the support messages: the room, the round,
both seats' names and accounts, the reason and the room's last
``CHAT_LINES`` chat lines as the reporter saw them. Nothing stored is sent
back; the reporter gets a confirmation or a refusal with a short code.

Only a signed-in player may report, and only another seat held by a
signed-in player: a bot says nothing of its own and a guest has no account
to act on. Reports are limited per reporting account.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from . import accounts

FILE_NAME = "player_reports.jsonl"
REASONS = frozenset({"abuse", "spam", "cheating", "other"})
CHAT_LINES = 20
# Five reports an hour per account: enough to report each other seat at a
# table and then some, too few to flood the file.
RATE_LIMIT = 5
RATE_WINDOW = 3600.0

LIMITER = accounts.RateLimiter(limit=RATE_LIMIT, window=RATE_WINDOW)
_write_lock = threading.Lock()


class ReportRefused(Exception):
    """A report that is not stored; ``code`` is the short reason the client sees."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def reports_path() -> Path:
    return accounts.data_dir() / FILE_NAME


def build(room: Any, reporter_seat: int, reporter_account: int | None, msg: dict,
          now: float | None = None) -> dict:
    """The record to store for ``msg`` from ``reporter_seat``, or
    ``ReportRefused``. The caller holds the room lock, so seats and chat are
    read in one consistent moment. A refused report spends no rate budget."""
    if reporter_account is None:
        raise ReportRefused("report_sign_in", "Sign in to report a player.")
    target = msg.get("seat")
    if type(target) is not int or not 0 <= target < len(room.seats):
        raise ReportRefused("report_bad_seat", "That seat cannot be reported.")
    if target == reporter_seat:
        raise ReportRefused("report_bad_seat", "You cannot report yourself.")
    reason = msg.get("reason")
    if reason not in REASONS:
        raise ReportRefused("report_bad_reason", "Choose a reason for the report.")
    seat = room.seats[target]
    if seat.is_bot:
        raise ReportRefused("report_bot", "Bots cannot be reported.")
    if seat.user_id is None:
        raise ReportRefused("report_guest", "Only signed-in players can be reported.")
    if not LIMITER.allow(str(reporter_account), now):
        raise ReportRefused("report_rate_limited", "Too many reports. Try again later.")
    game = getattr(room, "game", None)
    return {
        "ts": round(now if now is not None else time.time(), 3),
        "room": room.code,
        "round": game.round_no if game is not None else 0,
        "matched": bool(getattr(room, "matched", False)),
        "reason": reason,
        "reporter": {"seat": reporter_seat, "name": room.seats[reporter_seat].name,
                     "account_id": int(reporter_account)},
        "reported": {"seat": target, "name": seat.name, "account_id": int(seat.user_id)},
        "chat": [{"seat": line.get("seat"), "name": line.get("name"), "text": line.get("text"),
                  "t": line.get("t")}
                 for line in list(room.chat)[-CHAT_LINES:]],
    }


def _account_name(user_id: int) -> str | None:
    try:
        user = accounts.STORE.user(user_id)
    except Exception:               # noqa: BLE001 - a report over an identity
        return None
    return accounts.effective_name(user) if user else None


def store(record: dict) -> None:
    """Append ``record`` with both accounts' current names; blocking, so the
    socket loop runs it off the event loop. Raises ``OSError`` if not stored."""
    for side in ("reporter", "reported"):
        record[side]["account_name"] = _account_name(record[side]["account_id"])
    line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    path = reports_path()
    with _write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "ab") as f:
            f.write(line)

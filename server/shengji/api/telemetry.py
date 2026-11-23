"""UI telemetry: allow-listed client flow events in their own sink.

The client batches ``{"type": "client_event", "v": 1, "form": …,
"platform": …, "first_visit": …, "events": [{"e": …, "t": …, …}]}``. Every event is
checked against ``SCHEMA``: an unknown event name, an unknown field, or a
value outside its enum or integer bound drops that field or event. Nothing
free-form survives: no names, chat, room codes or card codes.

Each socket gets a random ``sid`` minted here and kept only on the socket
object, so no table maps it to an account, device or address. The server
stamps ``sid``, ``who``, ``form``, ``platform``, ``build`` and
``first_visit`` onto each kept event. ``who`` is the socket's own kind as
the server read it at the handshake: ``guest``, ``device`` (an account with
no Google or Apple identity, the iOS app's own) or ``linked`` (an account
with one); never the account itself.

A successful sign-in is also counted server-side (``signin_count``): its
provider and whether it made the account, with no ``sid`` and no ``ts``, so
it joins no socket's events.

Records go to ``$SHENGJI_TELEMETRY_DIR/ui-YYYYMMDD.jsonl`` (UTC date). The
sink is off when the variable is unset, and refuses any directory inside
the game-log directory (``SHENGJI_LOG_DIR``, ``/data/logs``): that tree is
the human-play training corpus and UI events must never be mined as play.

Files expire after ``RETENTION_DAYS``: the first write of each UTC day (so
also the first after a restart) deletes day files whose whole day is older
than that, at most ``MAX_PRUNE_PER_PASS`` per pass, and logs only the count.
A pass that hits the cap leaves the day unmarked so the next write goes on.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_EVENTS_PER_MESSAGE = 50
MAX_EVENTS_PER_HOUR = 600
MAX_MESSAGE_BYTES = 2048
HOUR = 3600.0
MAX_MS = 24 * 3600 * 1000
DAY = 86400.0
RETENTION_DAYS = 90
MAX_PRUNE_PER_PASS = 64
_DAY_FILE = re.compile(r"ui-(\d{8})\.jsonl")

log = logging.getLogger(__name__)
# (directory, UTC day) of the last pass that finished; one pass a day per sink.
_pruned: tuple[Path, str] | None = None

SCREENS = frozenset({
    "play", "howto", "name_sheet", "duo_sheet", "room", "waiting_table",
    "offer", "table", "round_end", "leaderboard", "me", "games", "game",
})
TAPS = frozenset({
    "play", "play_bots", "create_room", "duo", "join_code", "start_with_bots",
    "leave_queue", "wait_people_on", "wait_people_off", "table_start",
    "offer_join", "offer_wait", "offer_chip", "next_round", "round_end_leave",
    "menu_leave", "chip_leave", "leave_confirm", "leave_keep", "howto_open",
    "signin_open", "coach_on", "coach_off", "invite_share", "copy_code",
})
# Server error codes the client may echo, plus the client's own notice ids.
NOTICE_CODES = frozenset({
    "bad_party", "bad_seat", "bad_start_level", "choose_seat", "cooldown",
    "in_party", "in_queue", "in_room", "no_match", "no_offer", "not_in_party",
    "not_leader", "not_queued", "not_seated", "partner_unavailable",
    "party_busy", "party_changed", "party_full", "party_incomplete",
    "party_not_found", "ranked_queue_only", "rate_limited",
    "report_not_stored", "resume_unavailable", "room_full", "room_not_found",
    "same_device", "seat_changed", "seat_reserved", "seat_taken",
    "seat_unavailable", "signed_in_only", "stale_connection", "start_failed",
    "table_closed", "pair_seats_fixed", "already_ready",
    "panel_changed", "account_in_game",
    "illegal_play", "follow_hint", "lead_hint", "disconnected", "reconnecting",
    "reconnected", "error_other",
})
WHERE = SCREENS | {"toast", "other"}
# What ended an open socket, as the page saw it (web/src/link.ts): the
# transport closed it, a ping went unanswered, or the page replaced it on
# purpose (a sign-in or sign-out, or Retry).
DISCONNECT_CAUSES = frozenset({"closed", "no_pong", "replaced"})
FORMS = frozenset({"phone", "phone-land", "wide"})
# The iOS app, an installed home-screen web app, or a browser tab.
PLATFORMS = frozenset({"ios_app", "pwa", "web"})
WHO = frozenset({"guest", "device", "linked"})
PROVIDERS = frozenset({"google", "apple"})
# Where the identity sheet was opened: the Play tab's guest line, the chip,
# Me's name row, the Leaderboard's Sign in row, a round end's rating line,
# the saved games' signed-out prompt, or a player's Report row.
SIGNIN_FROM = frozenset({"play_line", "chip", "me_row", "leaderboard_row", "round_end",
                         "lapsed", "report"})
# A provider sign-in: its button tapped (the app's native buttons; the
# website's Google button is Google's own frame), the account confirmed, a
# refusal, or the provider's sheet dismissed.
SIGNIN_STEPS = frozenset({"provider_tap", "done", "error", "closed"})
# The iOS app's own account: made, signed in again from the Keychain, the
# device left a guest (device accounts off, a refused or unreadable secret,
# no connection), a provider identity linked onto it, the "Switch to …?"
# confirm shown, or the device's account given way to the identity's.
DEVICE_STEPS = frozenset({"created", "restored", "fell_back_guest", "linked",
                          "conflict_shown", "switched"})
QUEUE_EVENTS = frozenset({"join", "leave", "start", "start_failed"})


def _enum(values: frozenset[str]):
    return lambda v: v if isinstance(v, str) and v in values else None


def _int(lo: int, hi: int):
    # bool is an int subclass; a true/false is no count
    return lambda v: v if type(v) is int and lo <= v <= hi else None


def _bool(v: Any) -> bool | None:
    return v if type(v) is bool else None


SCHEMA: dict[str, dict[str, Any]] = {
    "screen": {"name": _enum(SCREENS), "prev": _enum(SCREENS),
               "ms_on_prev": _int(0, MAX_MS)},
    "turn_done": {"phase": _enum(frozenset({"play", "bury"})),
                  "lead": _enum(frozenset({"single", "pair", "tractor", "throw"})),
                  "need": _int(0, 60),
                  "ms_to_first_tap": _int(0, MAX_MS), "ms_total": _int(0, MAX_MS),
                  "sel_changes": _int(0, 1000), "disabled_play_taps": _int(0, 1000),
                  "refused": _int(0, 100), "coach": _bool, "nth_turn": _int(1, 30),
                  "by": _enum(frozenset({"you", "timer", "bot"}))},
    "tap": {"id": _enum(TAPS), "from": _enum(SIGNIN_FROM)},
    "signin": {"step": _enum(SIGNIN_STEPS), "provider": _enum(PROVIDERS)},
    "device_account": {"step": _enum(DEVICE_STEPS)},
    "notice": {"code": _enum(NOTICE_CODES), "where": _enum(WHERE),
               # the connection notices: why the page dropped its socket, and
               # for how long it had none
               "cause": _enum(DISCONNECT_CAUSES), "ms": _int(0, MAX_MS)},
}
# The field without which an event says nothing; missing or invalid drops it.
REQUIRED = {"screen": "name", "turn_done": "phase", "tap": "id", "notice": "code",
            "signin": "step", "device_account": "step"}

# Server-side queue events (``queue_event``): field -> check.
QUEUE_FIELDS: dict[str, Any] = {
    "who": _enum(frozenset({"guest", "account"})), "size": _int(1, 4),
    "wait": lambda v: round(float(v), 1) if type(v) in (int, float) and 0 <= v <= 86400 else None,
    "table": _bool, "humans": _int(0, 4), "queued": _int(0, 100000),
    "reason": lambda v: v if isinstance(v, str) and re.fullmatch(r"[a-z_]{1,24}", v) else None,
    "max_wait": lambda v: round(float(v), 1) if type(v) in (int, float) and 0 <= v <= 86400 else None,
}


def _repo_logs_local() -> Path:
    return Path(__file__).resolve().parents[3] / "logs" / "local"


def game_log_dir() -> Path:
    """The game-log directory exactly as server.py resolves it."""
    return Path(os.environ.get("SHENGJI_LOG_DIR", _repo_logs_local()))


def telemetry_dir() -> Path | None:
    """The sink directory, or None when telemetry is off or the configured
    directory would sit inside the game logs."""
    raw = os.environ.get("SHENGJI_TELEMETRY_DIR", "").strip()
    if not raw:
        return None
    path = Path(raw).resolve()
    for logs in (game_log_dir().resolve(), Path("/data/logs")):
        if path == logs or logs in path.parents:
            return None
    return path


def build_id() -> str:
    """The deployed build: ``SHENGJI_BUILD``, else the tag of Fly's image ref."""
    raw = os.environ.get("SHENGJI_BUILD") or os.environ.get("FLY_IMAGE_REF", "").rsplit(":", 1)[-1]
    clean = re.sub(r"[^A-Za-z0-9._-]", "", raw)[:40]
    return clean or "dev"


class SocketTelemetry:
    """Per-socket state: the random sid and the hourly event budget."""

    __slots__ = ("sid", "window_start", "count")

    def __init__(self) -> None:
        self.sid = secrets.token_hex(8)
        self.window_start = time.monotonic()
        self.count = 0

    def take(self, n: int, now: float | None = None) -> int:
        """How many of ``n`` events this socket may still log this hour."""
        now = time.monotonic() if now is None else now
        if now - self.window_start >= HOUR:
            self.window_start, self.count = now, 0
        allowed = max(0, min(n, MAX_EVENTS_PER_HOUR - self.count))
        self.count += allowed
        return allowed


def state_for(conn: Any) -> SocketTelemetry:
    """The socket's telemetry state, created on first use and held only on
    the socket object (it dies with the socket)."""
    st = getattr(conn, "telemetry", None)
    if not isinstance(st, SocketTelemetry):
        st = SocketTelemetry()
        try:
            conn.telemetry = st
        except Exception:      # noqa: BLE001 - a socket object without attributes
            pass
    return st


def clean_event(raw: Any) -> dict[str, Any] | None:
    """The allow-listed projection of one client event, or None to drop it."""
    if not isinstance(raw, dict):
        return None
    name = raw.get("e")
    schema = SCHEMA.get(name) if isinstance(name, str) else None
    if schema is None:
        return None
    out: dict[str, Any] = {"e": name}
    t = _int(0, MAX_MS)(raw.get("t"))
    if t is not None:
        out["t"] = t
    for field, check in schema.items():
        if field in raw:
            value = check(raw[field])
            if value is not None:
                out[field] = value
    if REQUIRED[name] not in out:
        return None
    return out


def clean_message(msg: Any, raw_bytes: int | None = None) -> tuple[list[dict], dict[str, Any]]:
    """The kept events of one ``client_event`` message and its stamps
    (``form``, ``platform``, ``first_visit``); nothing for a malformed or oversize one."""
    if not isinstance(msg, dict) or msg.get("v") != 1:
        return [], {}
    size = raw_bytes if raw_bytes is not None else len(
        json.dumps(msg, separators=(",", ":"), ensure_ascii=False).encode())
    if size > MAX_MESSAGE_BYTES:
        return [], {}
    events = msg.get("events")
    if not isinstance(events, list):
        return [], {}
    kept = [ev for ev in (clean_event(e) for e in events[:MAX_EVENTS_PER_MESSAGE]) if ev is not None]
    stamps: dict[str, Any] = {}
    form = _enum(FORMS)(msg.get("form"))
    if form is not None:
        stamps["form"] = form
    platform = _enum(PLATFORMS)(msg.get("platform"))
    if platform is not None:
        stamps["platform"] = platform
    first = _bool(msg.get("first_visit"))
    if first is not None:
        stamps["first_visit"] = first
    return kept, stamps


def prune(directory: Path, now: float | None = None,
          limit: int | None = None) -> tuple[int, bool]:
    """Delete up to ``limit`` day files in ``directory`` whose day ended more
    than ``RETENTION_DAYS`` before ``now``; returns (deleted, more remain)."""
    now = time.time() if now is None else now
    limit = MAX_PRUNE_PER_PASS if limit is None else limit
    cutoff = now - RETENTION_DAYS * DAY
    deleted, more = 0, False
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return 0, False
    for name in names:
        m = _DAY_FILE.fullmatch(name)
        if m is None:
            continue
        try:
            start = datetime.strptime(m.group(1), "%Y%m%d").replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
        if start + DAY > cutoff:
            continue
        if deleted >= limit:
            more = True
            break
        try:
            (directory / name).unlink()
            deleted += 1
        except FileNotFoundError:
            pass
        except OSError:
            more = True
    return deleted, more


def _prune_once_a_day(directory: Path, now: float, day: str) -> None:
    global _pruned
    if _pruned == (directory, day):
        return
    deleted, more = prune(directory, now)
    if deleted:
        log.info("telemetry retention removed %d day files", deleted)
    if not more:
        _pruned = (directory, day)


def write(records: list[dict[str, Any]], now: float | None = None) -> bool:
    """Append records to today's file; False when the sink is off or the
    write failed. Telemetry never breaks the game."""
    if not records:
        return False
    directory = telemetry_dir()
    if directory is None:
        return False
    now = time.time() if now is None else now
    day = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y%m%d")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        _prune_once_a_day(directory, now, day)
        with open(directory / f"ui-{day}.jsonl", "a", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, separators=(",", ":"), sort_keys=True) + "\n")
        return True
    except Exception:          # noqa: BLE001
        return False


def receive(conn: Any, msg: Any, kind: str) -> int:
    """Handle one ``client_event`` message from ``conn``; ``kind`` is the
    socket's ``who`` (anything else reads as guest). Returns how many events
    were written."""
    try:
        kind = kind if kind in WHO else "guest"
        events, stamps = clean_message(msg)
        if not events:
            return 0
        st = state_for(conn)
        events = events[:st.take(len(events))]
        ts = round(time.time())
        records = [{**ev, **stamps, "sid": st.sid,
                    "who": kind,
                    "build": build_id(), "ts": ts} for ev in events]
        return len(records) if write(records) else 0
    except Exception:          # noqa: BLE001
        return 0


def queue_event(conn: Any, event: str, **fields: Any) -> bool:
    """One queue event (``join``, ``leave``, ``start``, ``start_failed``)
    under the same ``sid`` as the socket's UI events; ``conn`` may be None
    (a start with no single socket), which logs it without a sid."""
    try:
        if event not in QUEUE_EVENTS:
            return False
        rec: dict[str, Any] = {"e": "queue", "q": event}
        for field, value in fields.items():
            check = QUEUE_FIELDS.get(field)
            if check is not None:
                kept = check(value)
                if kept is not None:
                    rec[field] = kept
        if conn is not None:
            st = state_for(conn)
            if not st.take(1):
                return False
            rec["sid"] = st.sid
        rec["build"] = build_id()
        rec["ts"] = round(time.time())
        return write([rec])
    except Exception:          # noqa: BLE001
        return False


def signin_count(provider: str, new: bool) -> bool:
    """One successful provider sign-in: the provider and whether it made the
    account. Written with no ``sid`` and no ``ts`` (the day file is its
    time), so neither a socket's events nor an account's last sign-in time
    can be joined to it."""
    try:
        provider = _enum(PROVIDERS)(provider)
        if provider is None or type(new) is not bool:
            return False
        return write([{"e": "signin_count", "provider": provider, "new": new, "build": build_id()}])
    except Exception:          # noqa: BLE001
        return False

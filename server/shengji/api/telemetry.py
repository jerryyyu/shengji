"""UI telemetry: allow-listed client flow events in their own sink.

The client batches ``{"type": "client_event", "v": 1, "form": …,
"platform": …, "first_visit": …, "days_since_first": …, "session_n": …,
"lang": …, "events": [{"e": …, "t": …, …}]}``. The three later stamps are
buckets the page computes from a first-seen date and a session counter it
keeps on the device (``0|1|2-7|8-30|31+`` days, ``1|2|3-5|6+`` sessions,
``en|zh``); a batch without them is still kept. Every event is
checked against ``SCHEMA``: an unknown event name, an unknown field, or a
value outside its enum or integer bound drops that field or event. Nothing
free-form survives: no names, chat, room codes or card codes.

An ``invite`` event (``created``, ``opened``, ``seated``) may carry ``h``,
the random token the sender's device puts on the links it shares
(``/?code=CODE&h=TOKEN``, minted once and kept in that origin's storage).
Only ``h``'s salted hash, eight hex, is written: it groups one sender's
links with the opens and seats they led to, and it is derived from neither
an account nor the room code. It is stable for that device's origin, so a
sender's ``created`` rows of different sockets share it.

Each socket gets a random ``sid`` minted here and kept only on the socket
object, so no table maps it to an account, device or address. The server
stamps ``sid``, ``who``, ``form``, ``platform``, ``build``, ``first_visit``,
the three bucket stamps and ``app_version`` onto each kept event. ``who`` is the socket's own kind as
the server read it at the handshake: ``guest``, ``device`` (an account with
no Google or Apple identity, the iOS app's own) or ``linked`` (an account
with one); never the account itself.

``app_version`` is the iOS app's own version, from the ``ShengjiApp/<version>``
token its WebView appends to the handshake's User-Agent (``appendUserAgent``
in web/capacitor.config.ts). The app loads the live site, so the page cannot
know which shell runs it. Only a bare ``1.2`` or ``1.2.3`` (at most four
digits a part) is kept; any other token, and the rest of the User-Agent, is
dropped, and the socket's ``app_version`` and queue events carry the same
value. Apps up to 1.0.1 send no token: a ``platform`` ``ios_app`` row with no
``app_version`` is from 1.0.1 or earlier.

What the page keeps to compute its stamps and round events lives in that
page's own origin storage (web/src/telemetryStamps.ts, roundTelemetry.ts):
the first-seen date, the session counter and the played-a-round flag in
local storage, an open online round in the tab's session storage. Two
origins never share them: a browser's site, and in the iOS app the hosted
site and the bundled offline page, each count on their own. So
``device_account.first_round_before`` says only whether this origin saw a
round, never a round played on the app's other origin, and a device's
``days_since_first`` restarts on cleared site data. Only the offline digest's
counts are shared across the app's two origins (its native store). The
digest's counts are read and written only under the origin's Web Lock, or
on a page that is alone with its store (the iOS app); a browser without Web
Locks counts no device rounds and sends no digest.

``round_finish.tricks_played`` is the server's own ``tricks_done`` count; a
round whose page saw any state without it sends no count. ``by: closed`` is
said at a pagehide, or on the same tab's next load when the page went
without one; a session that ended with the page (an app killed in the
background) leaves no such record.

A batch holding any event sent at a sign-in or identity change
(``signin``, ``device_account`` or the ``signin_open`` tap) is an identity
batch: every row of it keeps ``ts`` only to the hour and drops ``t``, and it
goes to its own day file, ``ui-id-YYYYMMDD.jsonl``, whose rows all carry
hours (its modification time is set back to the hour too). Neither a
neighbouring row's exact second nor a row's place among exact-second rows
can then date the sign-in to an account's last sign-in.

A successful sign-in is also counted server-side (``signin_count``): its
provider and whether it made the account, with no ``sid`` and no ``ts``, in
the identity file, so it joins no socket's events.

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

import hashlib
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
_DAY_FILE = re.compile(r"ui-(?:id-)?(\d{8})\.jsonl")

log = logging.getLogger(__name__)
# (directory, UTC day) of the last pass that finished; one pass a day per sink.
_pruned: tuple[Path, str] | None = None

SCREENS = frozenset({
    "play", "howto", "name_sheet", "duo_sheet", "room", "waiting_table",
    "offer", "table", "round_end", "leaderboard", "me", "games", "game",
    "collection",
})
TAPS = frozenset({
    "play", "play_bots", "create_room", "duo", "join_code", "start_with_bots",
    "leave_queue", "wait_people_on", "wait_people_off", "table_start",
    "offer_join", "offer_wait", "offer_chip", "next_round", "round_end_leave",
    "menu_leave", "chip_leave", "leave_confirm", "leave_keep", "howto_open",
    "signin_open", "coach_on", "coach_off", "invite_share", "copy_code",
    "app_store_badge", "hint_preselect", "rejoin_duo",
    # Show companions at the table switched on or off; a look put in use; a
    # Collection tile selected into the stage; Try on your table turned on
    "companions_on", "companions_off", "look_use", "collection_tile", "try_on",
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
# Me's name row, Me's Sign in row (the app's own account), the Leaderboard's
# Sign in row, a round end's rating line, the saved games' signed-out prompt,
# a player's Report row, the app's one ask after its move to its own domain
# left it signed out (web/src/originMove.ts), the Shop's Sign in to buy and
# Restore purchases for a device account, or a guest's Sign in to use in the
# Collection.
SIGNIN_FROM = frozenset({"play_line", "chip", "me_row", "me_signin", "leaderboard_row",
                         "round_end", "lapsed", "report", "moved", "shop", "collection"})
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
# The iOS app asked for Apple's rating sheet: at the 2nd ranked or the 5th
# casual round win (web/src/reviewPrompt.ts).
REVIEW_TRIGGERS = frozenset({"ranked2", "casual5"})
QUEUE_EVENTS = frozenset({"join", "leave", "start", "start_failed"})
QUEUE_MODES = frozenset({"ranked", "casual"})
# The client's view of a round: a ranked (matched) table, a casual queue
# table, a friends' table (a code, a Duo or a saved game's Continue), a
# tutorial, or the device's own server (offline, nearby). Offline and nearby
# rounds reach the server only as the counts of an ``offline_digest``.
ROUND_MODES = frozenset({"ranked", "casual", "friend", "tutorial", "offline", "nearby"})
# What ended a round as the page saw it: its round end, your Leave, or the
# page closing mid-round (said on the next load).
ROUND_BY = frozenset({"end", "left", "closed"})
# Batch stamps, all buckets: days since the device was first seen, the
# device's session (a new one after 30 idle minutes) and the page's language.
DAYS_BUCKETS = frozenset({"0", "1", "2-7", "8-30", "31+"})
SESSION_BUCKETS = frozenset({"1", "2", "3-5", "6+"})
LANGS = frozenset({"en", "zh"})
# The companion kinds (``accounts.LOOKS``; a test holds the two equal): the
# kind of the look a ``companions`` event's viewer wears, never its colour.
COMPANION_KINDS = frozenset({"tractor", "bun", "chick", "sparrow", "lamb", "panda"})
COMPANION_SETTINGS = frozenset({"on", "off"})
MAX_COMPANION_TAPS = 500  # each companion_round count
MAX_ROUNDS = 50          # nth_round_this_load
MAX_DIGEST = 99          # each offline_digest count
MAX_SOCKET_MS = 120_000  # app_open ms_to_socket
MAX_HOWTO_STEP = 20
APP_UA_TOKEN = re.compile(r"(?:^|\s)ShengjiApp/(\S{1,32})(?=\s|$)")
APP_VERSION = re.compile(r"\d{1,4}\.\d{1,4}(?:\.\d{1,4})?")
MAX_USER_AGENT = 512
# An invite's funnel: the link sent (by the share sheet or a copy), a page
# loaded from it, and that page's visitor seated by its Join.
INVITE_STEPS = frozenset({"created", "opened", "seated"})
# Watching a table (web/src/watch/usage.ts): a live table or a replay; how
# the watch began (the Play tab's presence link, Forward onto its history
# entry, or the screen moving to another table); what ended it (its Leave,
# back, Escape, Next table, a failed read, a seat taken, the table gone, or
# the round watched ended and the feed moved on to another table).
WATCH_KINDS = frozenset({"live", "replay"})
WATCH_FROM = frozenset({"presence", "history", "next"})
WATCH_BY = frozenset({"close", "back", "escape", "next", "error", "seat", "gone", "ended"})
MAX_WATCH_SECS = 86_400
INVITE_VIA = frozenset({"share", "copy"})
# The sender's random link token (web/src/codes.ts hostToken); only its hash is kept.
HOST_TOKEN = re.compile(r"[0-9a-f]{12}")
HOST_HASH_SALT = b"shengji-invite-host:"


def _enum(values: frozenset[str]):
    return lambda v: v if isinstance(v, str) and v in values else None


def _int(lo: int, hi: int):
    # bool is an int subclass; a true/false is no count
    return lambda v: v if type(v) is int and lo <= v <= hi else None


def _bool(v: Any) -> bool | None:
    return v if type(v) is bool else None


def _version(v: Any) -> str | None:
    return v if isinstance(v, str) and APP_VERSION.fullmatch(v) else None


def _host_hash(v: Any) -> str | None:
    """Eight hex of the salted SHA-256 of a well-formed link token: the same
    token always gives the same group, and the kept value is never the token
    a link carries."""
    if not isinstance(v, str) or HOST_TOKEN.fullmatch(v) is None:
        return None
    return hashlib.sha256(HOST_HASH_SALT + v.encode()).hexdigest()[:8]


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
    "device_account": {"step": _enum(DEVICE_STEPS), "first_round_before": _bool},
    "app_open": {"cold": _bool, "ms_to_socket": _int(0, MAX_SOCKET_MS)},
    "round_start": {"mode": _enum(ROUND_MODES), "bots": _int(0, 3),
                    "nth_round_this_load": _int(1, MAX_ROUNDS)},
    "round_finish": {"mode": _enum(ROUND_MODES), "won": _bool, "by": _enum(ROUND_BY),
                     "tricks_played": _int(0, 25)},
    "offline_digest": {"rounds_started": _int(0, MAX_DIGEST), "rounds_finished": _int(0, MAX_DIGEST),
                       "nearby_rounds": _int(0, MAX_DIGEST)},
    "howto_step": {"step": _int(1, MAX_HOWTO_STEP), "done": _bool},
    "notice": {"code": _enum(NOTICE_CODES), "where": _enum(WHERE),
               # the connection notices: why the page dropped its socket, and
               # for how long it had none
               "cause": _enum(DISCONNECT_CAUSES), "ms": _int(0, MAX_MS)},
    # the app version asked for, as the page read it from its User-Agent
    "review_prompt": {"trigger": _enum(REVIEW_TRIGGERS), "version": _version},
    # ``h`` arrives as the link's raw token and is kept only as its hash
    "invite": {"step": _enum(INVITE_STEPS), "via": _enum(INVITE_VIA), "h": _host_hash},
    # once per table, for a viewer shown the Collection: whether the table
    # draws companions, the viewer's Show companions at the table switch, the
    # kind of the viewer's look and how many figures are drawn
    "companions": {"shown": _bool, "setting": _enum(COMPANION_SETTINGS),
                   "kind": _enum(COMPANION_KINDS), "figures": _int(0, 4)},
    # at each round end of a table drawing companions: felt taps that walked
    # yours, taps on yours that played its special, and taps on it while the
    # special cooled down
    "companion_round": {"walk_taps": _int(0, MAX_COMPANION_TAPS), "specials": _int(0, MAX_COMPANION_TAPS),
                        "nudges": _int(0, MAX_COMPANION_TAPS)},
    # a watched table first drawn; a watch ended, with the seconds it lasted;
    # an online round begun within half an hour of a watch ending
    "watch_open": {"kind": _enum(WATCH_KINDS), "from": _enum(WATCH_FROM)},
    "watch_leave": {"by": _enum(WATCH_BY), "secs": _int(0, MAX_WATCH_SECS), "kind": _enum(WATCH_KINDS)},
    "watch_to_play": {"secs": _int(0, MAX_WATCH_SECS), "by": _enum(WATCH_BY)},
}
# The field without which an event says nothing; missing or invalid drops it.
REQUIRED = {"screen": "name", "turn_done": "phase", "tap": "id", "notice": "code",
            "signin": "step", "device_account": "step", "review_prompt": "trigger",
            "app_open": "cold", "round_start": "mode", "round_finish": "by",
            "offline_digest": "rounds_started", "howto_step": "step", "invite": "step",
            "companions": "shown", "companion_round": "walk_taps",
            "watch_open": "kind", "watch_leave": "by", "watch_to_play": "secs"}

# Server-side queue events (``queue_event``): field -> check.
QUEUE_FIELDS: dict[str, Any] = {
    "who": _enum(frozenset({"guest", "account"})), "size": _int(1, 4),
    "wait": lambda v: round(float(v), 1) if type(v) in (int, float) and 0 <= v <= 86400 else None,
    "table": _bool, "humans": _int(0, 4), "queued": _int(0, 100000),
    "reason": lambda v: v if isinstance(v, str) and re.fullmatch(r"[a-z_]{1,24}", v) else None,
    "max_wait": lambda v: round(float(v), 1) if type(v) in (int, float) and 0 <= v <= 86400 else None,
    "mode": _enum(QUEUE_MODES),
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


def app_version(user_agent: Any) -> str | None:
    """The iOS app's version from a User-Agent's ``ShengjiApp/<version>``
    token, or None when there is none or it is not a bare version."""
    if not isinstance(user_agent, str) or len(user_agent) > MAX_USER_AGENT:
        return None
    m = APP_UA_TOKEN.search(user_agent)
    if m is None or not APP_VERSION.fullmatch(m.group(1)):
        return None
    return m.group(1)


class SocketTelemetry:
    """Per-socket state: the random sid, the hourly event budget and the
    app version read at the handshake."""

    __slots__ = ("sid", "window_start", "count", "app_version")

    def __init__(self) -> None:
        self.sid = secrets.token_hex(8)
        self.app_version: str | None = None
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


def handshake(conn: Any, user_agent: Any) -> None:
    """Record the socket's app version from its handshake User-Agent."""
    try:
        state_for(conn).app_version = app_version(user_agent)
    except Exception:          # noqa: BLE001
        pass


def _app_stamp(st: SocketTelemetry) -> dict[str, str]:
    return {"app_version": st.app_version} if st.app_version is not None else {}


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
    (``form``, ``platform``, ``first_visit``, ``days_since_first``, ``session_n``,
    ``lang``); nothing for a malformed or oversize one."""
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
    for field, values in (("days_since_first", DAYS_BUCKETS), ("session_n", SESSION_BUCKETS),
                          ("lang", LANGS)):
        value = _enum(values)(msg.get(field))
        if value is not None:
            stamps[field] = value
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


def write(records: list[dict[str, Any]], now: float | None = None,
          identity: bool = False) -> bool:
    """Append records to today's file (the identity file with ``identity``);
    False when the sink is off or the write failed. Telemetry never breaks
    the game."""
    if not records:
        return False
    sink = telemetry_dir()
    if sink is None:
        return False
    now = time.time() if now is None else now
    day = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y%m%d")
    try:
        sink.mkdir(parents=True, exist_ok=True)
        _prune_once_a_day(sink, now, day)
        path = sink / (f"ui-id-{day}.jsonl" if identity else f"ui-{day}.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, separators=(",", ":"), sort_keys=True) + "\n")
        if identity:
            hour = int(now) - int(now) % 3600
            os.utime(path, (hour, hour))
        return True
    except Exception:          # noqa: BLE001
        return False


def _identity_moment(ev: dict[str, Any]) -> bool:
    """An event sent at a sign-in or an identity change: its time could be
    matched to an account's last sign-in."""
    return ev["e"] in ("signin", "device_account") or (ev["e"] == "tap" and ev.get("id") == "signin_open")


def _stamped(ev: dict[str, Any], ts: int, identity: bool) -> dict[str, Any]:
    """The event with its ``ts``. In an identity batch every row gets the
    hour and loses ``t``: the batch shares one receipt second, so any exact
    row, or any offset, would date the sign-in beside it."""
    if not identity:
        return {**ev, "ts": ts}
    return {**{k: v for k, v in ev.items() if k != "t"}, "ts": ts - ts % 3600}


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
        # classified before the quota cut: a dropped identity event still
        # marks the rows kept with it, so they cannot date the sign-in
        identity = any(_identity_moment(ev) for ev in events)
        events = events[:st.take(len(events))]
        ts = round(time.time())
        records = [{**_stamped(ev, ts, identity), **stamps, **_app_stamp(st), "sid": st.sid,
                    "who": kind, "build": build_id()} for ev in events]
        return len(records) if write(records, identity=identity) else 0
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
            rec.update(_app_stamp(st))
        rec["build"] = build_id()
        rec["ts"] = round(time.time())
        return write([rec])
    except Exception:          # noqa: BLE001
        return False


def signin_count(provider: str, new: bool) -> bool:
    """One successful provider sign-in: the provider and whether it made the
    account. Written with no ``sid`` and no ``ts`` (the day file is its
    time) to the identity file, among rows kept to the hour, so neither a
    socket's events nor an account's last sign-in time can be joined to it."""
    try:
        provider = _enum(PROVIDERS)(provider)
        if provider is None or type(new) is not bool:
            return False
        return write([{"e": "signin_count", "provider": provider, "new": new, "build": build_id()}],
                     identity=True)
    except Exception:          # noqa: BLE001
        return False

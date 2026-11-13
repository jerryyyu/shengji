"""Ratings for signed-in players: one Elo-style number per account, the
leaderboard and the My stats page.

Only rounds in a ranked room are rated (``ranked``): a room from the queue
(``matched``) always is, and a room a player created is ranked only when its
host switched Ranked on (``set_ranked``) before the game started; the mode is
then fixed for that game. Every other room, Play bots included, is unranked
and writes no rating at all.

Only signed-in human seats are rated. Bots never move: every bot seat counts
as ``BOT_RATING``, the anchor of the served release, and in a ranked room a
player created a guest seat counts the same, so solo games against bots,
games with a partner and mixed tables share one scale. A queue-matched room
is for signed-in players only: a round that starts with a guest in one of its
seats is not rated for anyone. Nothing here reads or changes a game decision;
the hooks only observe the room at a round's start, at an explicit leave and
at the round's end.

Every seat's rating and kind (account, bot, guest) is read when the round
starts, and the round is rated from that record: a seat that changes hands
mid-round changes nobody's result, and the newcomer is rated from the next
round.

One rated round, for each rated account on team ``t``:

* team strength ``R_t`` is the mean of the two seats' ratings (a bot or guest
  seat is ``BOT_RATING``), plus ``BANKER_ADVANTAGE`` for the banker's team;
* expected score ``E = 1 / (1 + 10 ** ((R_opp - R_t) / 400))``;
* actual score ``S`` from the round's level change (``round_score``): the
  winner of ``n`` levels scores ``0.5 + min(n, 3) / 6`` (1 level 0.667,
  2 levels 0.833, 3 or more 1.0) and the loser ``1 - S``; attackers who take
  the deal without going up a level (80 to 115 points) score
  ``TAKEOVER_WIN_SCORE`` and the bankers ``1 - TAKEOVER_WIN_SCORE``;
* ``delta = K * (S - E)`` with ``K = K_PROVISIONAL`` for an account's first
  ``PROVISIONAL_ROUNDS`` rated rounds and ``K_ESTABLISHED`` after; an
  established account's ``K`` is halved when another rated player in the
  round was still provisional at its start,
  so a stranger's uncalibrated number moves an established one less.

Partners share ``R_t``, ``E`` and ``S``, so two established partners move by
the same amount; only a provisional partner's larger ``K`` (and the halving it
causes for the other) makes them differ.

Abandoning: a signed-in player who leaves a round in play (``leave_room``),
or whose seat the bot takes over after a disconnect and who has not
returned by the round's end, is rated on that round's real result (a bot
finished their hand) with the score capped at ``LEAVER_SCORE_CAP``: a loss
counts as it happened, a win counts no better than a draw. Leaving can then
never earn more than playing on, and costs no more than the real result.
Later rounds they are absent from are not rated at all.

A newcomer who takes a seat at an open table mid-round and leaves (or
abandons) that round, in which they were not rated, carries the cap instead:
their next rated round, anywhere, scores at most ``LEAVER_SCORE_CAP``
(``carry_leaver_cap``; kept in memory, so a restart forgets it).

Writes run on one worker thread in a single transaction per round; a
storage failure is logged and never reaches the game. Once a round's update
is stored, the room is broadcast again so each rated seat's round-end
screen gains its own rating line (``round_payload``).
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from . import accounts

log = logging.getLogger(__name__)

START_RATING = accounts.START_RATING
# The served release's fixed rating. Every bot seat is rated this, so a
# stronger release gets a higher constant from its measured duel margin.
BOT_RATING = 1000.0
# A guest has no rating; in a created ranked room their seat counts like a bot's.
GUEST_RATING = BOT_RATING
# Holding the deal (the kitty, the first lead and the defence threshold of
# 80) is worth this much team strength; the value is a starting estimate to
# be calibrated from the round logs' banker win rate.
BANKER_ADVANTAGE = 40.0
PROVISIONAL_ROUNDS = 20
K_PROVISIONAL = 40.0
K_ESTABLISHED = 20.0
# Attackers who reach 80 to 115 points take the deal but gain no level.
TAKEOVER_WIN_SCORE = 0.6
LEAVER_SCORE_CAP = 0.5
MAX_SCORED_LEVELS = 3

# What a seat held when the round started: a connected signed-in account, a
# bot, a guest (a person with no account), or an account not at the table.
ACCOUNT, BOT, GUEST, ABSENT = "account", "bot", "guest", "absent"

WEEK_SECONDS = 7 * 86400
LEADERBOARD_SIZE = 20
HISTORY_POINTS = 60
RECENT_GAMES = 10
BOT_ANCHOR_NAME = "Sheng Ji bot"

# Accounts whose next rated round is capped as a leave (``carry_leaver_cap``).
CARRIED_CAPS: set[int] = set()

_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ratings")
# Broadcast tasks are kept until done; the loop holds only weak references.
_TASKS: set[asyncio.Task] = set()


# ------------------------------------------------------------------- maths
def expected_score(team: float, opponents: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((opponents - team) / 400.0))


def round_score(won: bool, level_change: int) -> float:
    """The actual score of one team for a round it won or lost by
    ``level_change`` levels (the engine's ``RoundResult.level_change``)."""
    if level_change <= 0:
        winner = TAKEOVER_WIN_SCORE
    else:
        winner = 0.5 + min(level_change, MAX_SCORED_LEVELS) / (2 * MAX_SCORED_LEVELS)
    return winner if won else 1.0 - winner


def is_provisional(rated_rounds: int) -> bool:
    return rated_rounds < PROVISIONAL_ROUNDS


def k_factor(rated_rounds: int, provisional_opponent: bool = False) -> float:
    """``provisional_opponent``: another rated player in the round, partner
    or opponent, was provisional when it started. Only an established
    account's ``K`` is halved for it; a provisional account keeps the full
    ``K_PROVISIONAL`` so it calibrates at the intended pace."""
    if is_provisional(rated_rounds):
        return K_PROVISIONAL
    return K_ESTABLISHED / 2 if provisional_opponent else K_ESTABLISHED


def team_strengths(seat_ratings: list[float], banker_team: int) -> tuple[float, float]:
    """Mean seat rating per team (seats 0 and 2 are team 0), with the
    banker's team raised by ``BANKER_ADVANTAGE``."""
    strengths = [(seat_ratings[t] + seat_ratings[t + 2]) / 2.0 for t in (0, 1)]
    strengths[banker_team] += BANKER_ADVANTAGE
    return strengths[0], strengths[1]


# ------------------------------------------------------------------- store
@dataclass
class Participant:
    user_id: int
    seat: int
    abandoned: bool = False
    # Scored at most LEAVER_SCORE_CAP for a leave carried from a round in
    # which they were not rated; recorded as a played round.
    capped: bool = False


@dataclass
class RoundRecord:
    """What one finished round contributes, captured on the event loop."""
    game_id: str
    round_no: int
    banker_team: int
    winner_team: int
    level_change: int
    point_scored: bool
    # seat -> the account connected there when the round started
    start_accounts: dict[int, int]
    seat_names: list[str]
    seat_bots: list[bool]
    participants: list[Participant]
    # {account: (rating, rated_rounds)} read when the round started
    # (``read_standing``); a missing or failed read falls back to the
    # accounts' stored numbers at write time
    standing: Future | Mapping[int, tuple[float, int]] | None = None


def read_standing(store: accounts.Store, user_ids: list[int]) -> dict[int, tuple[float, int]]:
    """Each existing account's ``(rating, rated_rounds)``."""
    out: dict[int, tuple[float, int]] = {}
    with closing(store._open()) as conn:
        for uid in user_ids:
            row = conn.execute("SELECT rating, rated_rounds FROM users WHERE id = ?",
                               (uid,)).fetchone()
            if row is not None:
                out[uid] = (float(row["rating"]), int(row["rated_rounds"]))
    return out


def _frozen(standing: Any) -> Mapping[int, tuple[float, int]]:
    if standing is None:
        return {}
    if not isinstance(standing, Future):
        return standing
    # The read was queued on the ratings worker before this round's write,
    # so on that worker it is always done; never wait on it there.
    if not standing.done() or standing.cancelled() or standing.exception() is not None:
        log.warning("round-start rating read unavailable; using stored ratings")
        return {}
    return standing.result()


def apply_round(store: accounts.Store, rec: RoundRecord,
                now: float | None = None) -> dict[int, dict]:
    """Rate one round in one transaction; returns ``{user_id: {rating,
    delta}}`` for the accounts rated. A round already stored for an account
    is skipped, so a retried write cannot rate it twice; an account that no
    longer exists is skipped too.

    Team strengths and the provisional test use each participant's numbers
    from the round's start; a seat whose start account is not rated in this
    round counts ``GUEST_RATING``, as a bot or guest seat does."""
    t = int(now if now is not None else time.time())
    frozen = _frozen(rec.standing)
    with closing(store._open()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            ids = {p.user_id for p in rec.participants}
            users: dict[int, Mapping[str, Any]] = {}
            for uid in ids:
                row = conn.execute("SELECT id, rating, rated_rounds FROM users WHERE id = ?",
                                   (uid,)).fetchone()
                if row is not None:
                    users[uid] = row
            at_start = {uid: frozen.get(uid, (float(row["rating"]), int(row["rated_rounds"])))
                        for uid, row in users.items()}
            seat_ratings = [at_start[u][0] if u in at_start else GUEST_RATING
                            for u in (rec.start_accounts.get(s) for s in range(4))]
            strengths = team_strengths(seat_ratings, rec.banker_team)
            provisional = {uid for uid, (_, n) in at_start.items() if is_provisional(n)}
            out: dict[int, dict] = {}
            for p in rec.participants:
                row = users.get(p.user_id)
                if row is None:
                    continue
                if conn.execute(
                        "SELECT 1 FROM rating_events WHERE game_id = ? AND round_no = ? AND user_id = ?",
                        (rec.game_id, rec.round_no, p.user_id)).fetchone():
                    continue
                team = p.seat % 2
                won = rec.winner_team == team
                exp = expected_score(strengths[team], strengths[1 - team])
                actual = round_score(won, rec.level_change)
                if p.abandoned or p.capped:
                    actual = min(actual, LEAVER_SCORE_CAP)
                k = k_factor(int(row["rated_rounds"]), bool(provisional - {p.user_id}))
                before = float(row["rating"])
                delta = k * (actual - exp)
                after = before + delta
                partner = (p.seat + 2) % 4
                opponents = ((p.seat + 1) % 4, (p.seat + 3) % 4)
                conn.execute(
                    """INSERT INTO rating_events(game_id, round_no, user_id, created_at, team,
                           banker_team, won, levels, game_won, abandoned, expected, actual, k,
                           rating_before, rating_after, delta, partner, partner_bot,
                           opponents_bots)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (rec.game_id, rec.round_no, p.user_id, t, team,
                     1 if team == rec.banker_team else 0,
                     1 if won and not p.abandoned else 0,
                     rec.level_change if won else -rec.level_change,
                     1 if won and rec.point_scored and not p.abandoned else 0,
                     1 if p.abandoned else 0, exp, actual, k, before, after, delta,
                     rec.seat_names[partner], 1 if rec.seat_bots[partner] else 0,
                     sum(1 for s in opponents if rec.seat_bots[s])))
                conn.execute(
                    "UPDATE users SET rating = ?, rated_rounds = rated_rounds + 1 WHERE id = ?",
                    (after, p.user_id))
                out[p.user_id] = {"rating": after, "delta": delta}
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return out


def current_rating(store: accounts.Store, user_id: int) -> float | None:
    """An account's stored rating, or None when the account does not exist."""
    with closing(store._open()) as conn:
        row = conn.execute("SELECT rating FROM users WHERE id = ?", (user_id,)).fetchone()
    return float(row["rating"]) if row is not None else None


def set_visible(store: accounts.Store, user_id: int, visible: bool) -> bool:
    with closing(store._open()) as conn:
        return conn.execute("UPDATE users SET leaderboard_visible = ? WHERE id = ?",
                            (1 if visible else 0, user_id)).rowcount > 0


def _player_rows(conn, since: int) -> list[dict]:
    rows = conn.execute(
        """SELECT u.id, u.name, u.display_name, u.rating, u.rated_rounds,
                  u.leaderboard_visible,
                  COALESCE(SUM(CASE WHEN e.created_at >= ? THEN e.delta END), 0) AS week_delta,
                  COUNT(CASE WHEN e.created_at >= ? THEN 1 END) AS week_rounds,
                  AVG(e.levels) AS levels_per_round
           FROM users u JOIN rating_events e ON e.user_id = u.id
           GROUP BY u.id""", (since, since)).fetchall()
    players = [dict(r) for r in rows]
    players.sort(key=lambda r: (-r["rating"], -r["rated_rounds"], r["id"]))
    return players


def _public_row(row: Mapping[str, Any], rank: int | None, you: bool) -> dict:
    """One leaderboard row: the display name and numbers only, never the
    account id or email."""
    return {
        "rank": rank,
        "name": accounts.effective_name(row) or "Player",
        "rating": int(round(row["rating"])),
        "rounds": int(row["rated_rounds"]),
        "levels_per_round": round(float(row["levels_per_round"] or 0.0), 2),
        "week_delta": int(round(row["week_delta"] or 0.0)),
        "provisional": int(row["rated_rounds"]) < PROVISIONAL_ROUNDS,
        "you": you,
    }


def _rank_of(population: list[dict], user_id: int) -> int | None:
    """1 + the visible players ahead of ``user_id`` (``population`` is sorted);
    an opted-out viewer still learns where they would stand."""
    ahead = 0
    for row in population:
        if row["id"] == user_id:
            return ahead + 1
        if row["leaderboard_visible"]:
            ahead += 1
    return None


def leaderboard(store: accounts.Store, period: str, viewer: int | None,
                now: float | None = None) -> dict:
    """The top ``LEADERBOARD_SIZE`` visible players by current rating, among
    everyone with a rated round ("all") or a rated round in the last seven
    days ("week"), plus the viewer's own row wherever it ranks."""
    t = int(now if now is not None else time.time())
    with closing(store._open()) as conn:
        players = _player_rows(conn, t - WEEK_SECONDS)
    if period == "week":
        players = [r for r in players if r["week_rounds"] > 0]
    visible = [r for r in players if r["leaderboard_visible"]]
    top = [_public_row(r, i + 1, r["id"] == viewer)
           for i, r in enumerate(visible[:LEADERBOARD_SIZE])]
    me = None
    if viewer is not None:
        mine = next((r for r in players if r["id"] == viewer), None)
        if mine is not None:
            me = _public_row(mine, _rank_of(players, viewer), True)
            me["visible"] = bool(mine["leaderboard_visible"])
    return {"period": period, "players": top, "me": me,
            "anchor": {"name": BOT_ANCHOR_NAME, "rating": int(BOT_RATING)}}


def _pct(wins: int, n: int) -> float | None:
    return round(100.0 * wins / n, 1) if n else None


def stats(store: accounts.Store, user_id: int, now: float | None = None) -> dict | None:
    """The My stats payload for one account, or None for an unknown one."""
    t = int(now if now is not None else time.time())
    with closing(store._open()) as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return None
        user = dict(row)
        events = [dict(r) for r in conn.execute(
            "SELECT * FROM rating_events WHERE user_id = ? ORDER BY created_at, id", (user_id,))]
        players = _player_rows(conn, t - WEEK_SECONDS)
    n = len(events)
    wins = sum(e["won"] for e in events)
    defending = [e for e in events if e["banker_team"]]
    attacking = [e for e in events if not e["banker_team"]]
    streak = best = 0
    for e in events:
        streak = streak + 1 if e["won"] else 0
        best = max(best, streak)
    history: list[int] = []
    if events:
        tail = events[-HISTORY_POINTS:]
        history = [int(round(tail[0]["rating_before"]))]
        history += [int(round(e["rating_after"])) for e in tail]
    games: dict[str, dict] = {}
    for e in events:
        g = games.setdefault(e["game_id"], {"started_at": e["created_at"], "rounds": 0,
                                            "delta": 0.0, "games_won": 0})
        g["ended_at"] = e["created_at"]
        g["_last_event"] = e["id"]
        g["rounds"] += 1
        g["delta"] += e["delta"]
        g["games_won"] += e["game_won"]
        g["partner"] = None if e["partner_bot"] else e["partner"]
        g["partner_bot"] = bool(e["partner_bot"])
        g["opponents_bots"] = e["opponents_bots"]
    # Events share a whole-second timestamp, so the last event's id breaks ties:
    # within a second, the game that ended later still lists first.
    recent = sorted(games.values(), key=lambda g: (g["ended_at"], g["_last_event"]),
                    reverse=True)[:RECENT_GAMES]
    for g in games.values():
        del g["_last_event"]
    for g in recent:
        g["delta"] = int(round(g["delta"]))
    week_delta = sum(e["delta"] for e in events if e["created_at"] >= t - WEEK_SECONDS)
    return {
        "name": accounts.effective_name(user) or "Player",
        "rating": int(round(user["rating"])),
        "rank": _rank_of(players, user_id) if n else None,
        "rounds": n,
        "provisional": n < PROVISIONAL_ROUNDS,
        "levels_per_round": round(sum(e["levels"] for e in events) / n, 2) if n else None,
        "won_pct": _pct(wins, n),
        "defender_won_pct": _pct(sum(e["won"] for e in defending), len(defending)),
        "attacker_won_pct": _pct(sum(e["won"] for e in attacking), len(attacking)),
        "best_streak": best,
        "games_won": sum(e["game_won"] for e in events),
        "week_delta": int(round(week_delta)),
        "history": history,
        "recent_games": recent,
        "visible": bool(user["leaderboard_visible"]),
    }


# -------------------------------------------------------------- room hooks
@dataclass
class RoomRatings:
    """Server-only rating state of one room's game; it enters no log record,
    and a state frame carries only the receiving seat's own line."""
    game_id: str
    round_no: int = 0
    # games completed at this table; a rated round's game id is the table id
    # plus this count, so each game to a held Ace is its own Recent games row
    game_no: int = 0
    # seat -> account connected there when the round started
    present: dict[int, int] = field(default_factory=dict)
    # seat -> ACCOUNT, BOT, GUEST or ABSENT when the round started
    kinds: list[str] = field(default_factory=list)
    # the present accounts' (rating, rated_rounds) as the round started,
    # read on the ratings worker behind the previous round's write
    standing: Future | None = None
    # account -> seat it left from while the round was in play
    left: dict[int, int] = field(default_factory=dict)
    # account -> {"round", "rating", "delta", "game_delta"} of its latest rated round
    last: dict[int, dict] = field(default_factory=dict)
    # account -> rating change since the current game (to a held Ace) began
    game_delta: dict[int, float] = field(default_factory=dict)


def eligible(room: Any) -> bool:
    """Ordinary rooms only: an experimental policy or a human evaluation is
    not the served bot, so its rounds are not rated."""
    return room.experimental_policy is None and room.evaluation is None


def _guarded(fn):
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except Exception:           # noqa: BLE001 - ratings never break a game
            log.exception("rating hook %s failed; gameplay continues", fn.__name__)
            return None
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def _signed_in(seat: Any) -> int | None:
    uid = seat.user_id
    if seat.is_bot or uid is None or accounts.is_deleted(uid):
        return None
    return uid


def ranked(room: Any) -> bool:
    """Whether the room's rounds are rated: a queue-matched room, or a created
    room whose host switched Ranked on; never a room that is not ``eligible``."""
    return eligible(room) and bool(getattr(room, "matched", False)
                                   or getattr(room, "ranked", False))


@_guarded
def start(room: Any) -> None:
    """At ``start_game``, after the saved-game link (whose id it reuses). An
    unranked room gets no rating state, so none of its rounds is rated."""
    room.ratings = None
    if not ranked(room):
        return
    link = getattr(room, "saved_game", None)
    room.ratings = RoomRatings(game_id=link.id if link is not None else secrets.token_hex(16))
    round_started(room)


@_guarded
def round_started(room: Any) -> None:
    tracker: RoomRatings | None = getattr(room, "ratings", None)
    if tracker is None or room.game is None:
        return
    tracker.round_no = room.game.round_no
    tracker.left = {}
    tracker.present = {}
    tracker.kinds = []
    tracker.standing = None
    for s, seat in enumerate(room.seats):
        uid = _signed_in(seat)
        if uid is not None and seat.connected:
            tracker.present[s] = uid
            tracker.kinds.append(ACCOUNT)
        elif seat.is_bot:
            tracker.kinds.append(BOT)
        elif seat.user_id is None:
            tracker.kinds.append(GUEST)
        else:
            tracker.kinds.append(ABSENT)
    store = accounts.STORE
    if tracker.present and store is not None:
        tracker.standing = _EXECUTOR.submit(read_standing, store,
                                            sorted(set(tracker.present.values())))


@_guarded
def seat_left(room: Any, seat: int) -> None:
    """A player pressed Leave mid-game: while a round is in play, that round
    counts as abandoned unless they are back in the seat when it ends."""
    tracker: RoomRatings | None = getattr(room, "ratings", None)
    if tracker is None or room.game is None or room.game.game_over:
        return
    rnd = room.round
    if rnd is None or rnd.phase == "round_end":
        return
    uid = _signed_in(room.seats[seat])
    if uid is not None:
        tracker.left[uid] = seat


def participants(room: Any, tracker: RoomRatings) -> list[Participant]:
    """Who is rated for the round that just ended, and who abandoned it."""
    found: dict[int, Participant] = {}
    for s, seat in enumerate(room.seats):
        uid = _signed_in(seat)
        if uid is None or uid in found:
            continue
        if tracker.left.get(uid) == s and seat.connected:
            del tracker.left[uid]           # left and came back before the end
        if uid in tracker.left:
            continue
        if tracker.present.get(s) != uid:
            continue                        # sat down mid-round: rated from the next round
        if seat.connected:
            # Away at the end (the move timer handed every decision to the
            # bot) counts as leaving; back before the end does not.
            found[uid] = Participant(uid, s, abandoned=bool(getattr(seat, "away", False)))
        else:
            # Disconnected at the end: a blip inside the takeover window is
            # still their round; a bot playing on for them is an abandon.
            found[uid] = Participant(
                uid, s, abandoned=bool(seat.bot_announced or getattr(seat, "away", False)))
    for uid, s in tracker.left.items():
        if (uid not in found and tracker.present.get(s) == uid
                and not accounts.is_deleted(uid)):
            found[uid] = Participant(uid, s, abandoned=True)
    for s, uid in tracker.present.items():
        if uid not in found and not accounts.is_deleted(uid) and _signed_in(room.seats[s]) != uid:
            found[uid] = Participant(uid, s, abandoned=True)   # someone else holds the seat now
    # One account seated on both teams cannot be rated against itself.
    teams: dict[int, set[int]] = {}
    for s, seat in enumerate(room.seats):
        uid = _signed_in(seat)
        if uid is not None:
            teams.setdefault(uid, set()).add(s % 2)
    return [p for p in found.values() if len(teams.get(p.user_id, {p.seat % 2})) == 1]


def ranked_round_voided(room: Any, tracker: RoomRatings) -> bool:
    """A ranked (queue-matched) room rates signed-in players only: a guest
    seated when the round started leaves the round unrated for everyone."""
    return bool(getattr(room, "matched", False)) and GUEST in tracker.kinds


def build_record(room: Any, tracker: RoomRatings, result: Any) -> RoundRecord | None:
    rnd = room.round
    if rnd is None or rnd.banker is None or room.game is None:
        return None
    if ranked_round_voided(room, tracker):
        return None
    parts = participants(room, tracker)
    if not parts:
        return None
    for p in parts:
        if p.user_id in CARRIED_CAPS:
            CARRIED_CAPS.discard(p.user_id)
            p.capped = not p.abandoned
    rated = {p.user_id for p in parts}
    return RoundRecord(
        game_id=f"{tracker.game_id}/{tracker.game_no}", round_no=room.game.round_no,
        banker_team=rnd.banker % 2, winner_team=int(result.winner_team),
        level_change=int(result.level_change), point_scored=bool(result.point_scored),
        start_accounts={s: uid for s, uid in tracker.present.items() if uid in rated},
        seat_names=[seat.name for seat in room.seats],
        seat_bots=[bool(seat.is_bot) for seat in room.seats],
        participants=parts, standing=tracker.standing)


def _record_outcome(room: Any, tracker: RoomRatings, rec: RoundRecord,
                    out: dict[int, dict], game_over: bool) -> None:
    for uid, res in out.items():
        total = tracker.game_delta.get(uid, 0.0) + res["delta"]
        tracker.last[uid] = {"round": rec.round_no, "rating": res["rating"],
                             "delta": res["delta"], "game_delta": total}
        tracker.game_delta[uid] = total
    if rec.point_scored or game_over:
        tracker.game_delta = {}


async def _rebroadcast(room: Any, round_no: int) -> None:
    from . import server            # the room broadcast lives with the rooms
    async with room.lock:
        if (room.game is not None and room.game.round_no == round_no
                and room.round is not None and room.round.phase == "round_end"):
            await server.broadcast(room)


@_guarded
def round_ended(room: Any, result: Any) -> None:
    tracker: RoomRatings | None = getattr(room, "ratings", None)
    if tracker is None:
        return
    rec = build_record(room, tracker, result)
    game_over = bool(result.game_over)
    if result.point_scored or game_over:
        tracker.game_no += 1            # the same boundary that resets game_delta
    if rec is None:
        return
    store = accounts.STORE
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:                # off the loop (scripts, unit tests): inline
        flush()                     # the round-start read first, as on the worker
        _record_outcome(room, tracker, rec, apply_round(store, rec), game_over)
        return

    def done(fut: "asyncio.Future[dict[int, dict]]") -> None:
        if fut.cancelled() or fut.exception() is not None:
            log.warning("rating write failed (%s); gameplay continues",
                        "cancelled" if fut.cancelled() else type(fut.exception()).__name__)
            return
        _record_outcome(room, tracker, rec, fut.result(), game_over)
        task = loop.create_task(_rebroadcast(room, rec.round_no))
        _TASKS.add(task)
        task.add_done_callback(_TASKS.discard)

    loop.run_in_executor(_EXECUTOR, apply_round, store, rec).add_done_callback(done)


def carry_leaver_cap(user_id: int) -> None:
    """Cap ``user_id``'s next rated round as a leave: they left (or
    abandoned) a round they joined mid-way and so were not rated in."""
    CARRIED_CAPS.add(user_id)


def flush(timeout: float = 10.0) -> None:
    """Block until every queued rating write has run (tests, shutdown)."""
    _EXECUTOR.submit(lambda: None).result(timeout=timeout)


def round_payload(room: Any, seat: int) -> dict:
    """The ``rating`` entry of one seat's ``round_result``: that seat's own
    account only, and nothing for a guest, a bot or a round not yet rated."""
    try:
        tracker: RoomRatings | None = getattr(room, "ratings", None)
        game = room.game
        if tracker is None or game is None or game.result is None:
            return {}
        uid = _signed_in(room.seats[seat])
        info = tracker.last.get(uid) if uid is not None else None
        if info is None or info["round"] != game.round_no:
            return {}
        line = {"rating": int(round(info["rating"])), "delta": int(round(info["delta"]))}
        if game.result.point_scored or game.result.game_over:
            line["game_delta"] = int(round(info["game_delta"]))
        return {"rating": line}
    except Exception:               # noqa: BLE001 - a state frame never fails on this
        log.exception("rating payload failed")
        return {}


# --------------------------------------------------------------------- API
router = APIRouter(prefix="/api")
LIMITER = accounts.RateLimiter(limit=120, window=60.0)


class Visibility(BaseModel):
    visible: bool


async def _viewer(request: Request) -> dict | None:
    if not LIMITER.allow(accounts.client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many requests; try again in a minute.")
    store = accounts.STORE
    user = await store.run(store.session_user, request.cookies.get(accounts.COOKIE))
    if user is not None and accounts.is_deleted(int(user["id"])):
        return None
    return user


async def _required(request: Request) -> dict:
    user = await _viewer(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in.")
    return user


@router.get("/leaderboard")
async def get_leaderboard(request: Request, period: str = "week") -> dict:
    if period not in ("week", "all"):
        raise HTTPException(status_code=400, detail="period must be week or all.")
    user = await _viewer(request)
    store = accounts.STORE
    return await store.run(leaderboard, store, period, int(user["id"]) if user else None)


@router.get("/me/stats")
async def get_stats(request: Request) -> dict:
    user = await _required(request)
    store = accounts.STORE
    body = await store.run(stats, store, int(user["id"]))
    if body is None:
        raise HTTPException(status_code=401, detail="Not signed in.")
    return body


@router.post("/me/leaderboard-visibility")
async def post_visibility(body: Visibility, request: Request) -> dict:
    user = await _required(request)
    store = accounts.STORE
    await store.run(set_visible, store, int(user["id"]), body.visible)
    return {"visible": body.visible}


def register_ratings(app) -> None:
    app.include_router(router)

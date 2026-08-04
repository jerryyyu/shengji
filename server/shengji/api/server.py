"""FastAPI WebSocket server: rooms, seats, humans + bots, per-seat state."""

from __future__ import annotations

import asyncio
import json
import random
import string
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

import os
import secrets

from ..ai.heuristic import HeuristicBot
from ..ai.registry import make_bot
from ..engine.game import Game
from ..engine.legal import IllegalPlay
from ..engine.round import Round, actual_play_after

BOT_DELAY = 0.7
CHAT_KEEP = 50        # scrollback kept per room (in memory, like game state)
CHAT_MAX_LEN = 300    # per-message cap
DEAL_DELAY = 0.22          # seconds between dealt cards (~22s full deal)
DECLARE_GRACE = 5.0        # window after the deal; extended on new declarations
DECLARE_EXTEND = 3.0
ROOM_TTL = 300.0           # grace before deleting a room with no humans connected
TAKEOVER_AFTER = 30.0      # bot plays for a disconnected human after this long
# Game logs (full hands!). Prod sets SHENGJI_LOG_DIR=/data/logs and those
# files are fetched into logs/ as the HUMAN CORPUS, so a dev server must not
# write there: local multiplayer testing would otherwise be mined as real
# human play (Jerry's VKHW/DPMV test games, 2026-08-03).
LOG_DIR = Path(os.environ.get(
    "SHENGJI_LOG_DIR",
    Path(__file__).resolve().parents[3] / "logs" / "local"))
app = FastAPI(title="shengji")

rooms: dict[str, "Room"] = {}


@dataclass
class Seat:
    name: str
    is_bot: bool = False
    bot_announced: bool = False
    # Monotonic stamp of the disconnect, independent of the event loop, so the
    # takeover countdown can be computed anywhere (loop.time() is only
    # meaningful inside a running loop).
    left_at: float | None = None  # bot-takeover announced for this absence
    ws: WebSocket | None = None
    connected: bool = False
    queue: asyncio.Queue | None = None   # outbound messages; writer task drains
    writer: asyncio.Task | None = None
    last_seen: float = 0.0               # loop time of last disconnect
    # Connection GENERATION. A dropped socket's `finally` can run long after a
    # newer socket has resumed the seat; without this the old cleanup detaches
    # the LIVE connection and strands the player (Codex ship gate P0-1).
    # Every attach bumps it; a detach only applies to the generation it owns.
    gen: int = 0
    # Opaque resume token: names are not identity. Two people called "jerry",
    # or one person on two devices, must not be able to seize each other's
    # seat, and a returning player must be able to resume even while their
    # stale socket is still open.
    token: str = field(default_factory=lambda: secrets.token_urlsafe(12))


@dataclass
class Room:
    code: str
    seats: list[Seat] = field(default_factory=list)
    host: int = 0
    game: Game | None = None
    ready: set[int] = field(default_factory=set)  # seats confirming round end
    chat: list[dict] = field(default_factory=list)  # last CHAT_KEEP messages
    ids: list[dict[int, str]] = field(default_factory=lambda: [{} for _ in range(4)])
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    bot: HeuristicBot = field(
        default_factory=lambda: make_bot(os.environ.get("SHENGJI_BOT", "mc")))
    bot_task: asyncio.Task | None = None
    deal_task: asyncio.Task | None = None
    watchdog_task: asyncio.Task | None = None
    cleanup_task: asyncio.Task | None = None

    @property
    def round(self) -> Round | None:
        return self.game.round if self.game else None

    def log_event(self, kind: str, **data) -> None:
        """Append one JSONL record to this room's game log. Best-effort —
        logging must never break the game."""
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            rec = {"t": round(time.time(), 3), "room": self.code,
                   "round": self.game.round_no if self.game else 0,
                   "e": kind, **data}
            with open(LOG_DIR / f"{self.code}.jsonl", "a") as f:
                f.write(json.dumps(rec) + "\n")
        except OSError:
            pass

    # ------------------------------------------------------------- id mapping
    def index_round(self) -> None:
        rnd = self.round
        assert rnd is not None
        self.ids = [{} for _ in range(4)]  # filled card-by-card as the deal runs
        self._kitty_ids = {100 + i: rnd.deck[100 + i] for i in range(8)}
        self._kitty_given = False

    def mint_card_id(self, seat: int, code: str) -> int:
        """Fresh id for a card the id map is missing (desync recovery)."""
        nid = max([*self.ids[seat], 199]) + 1
        self.ids[seat][nid] = code
        return nid

    def sync_kitty(self) -> None:
        rnd = self.round
        if rnd and rnd.phase in ("bury", "play", "round_end") and not self._kitty_given:
            assert rnd.banker is not None
            self.ids[rnd.banker].update(self._kitty_ids)
            self._kitty_given = True

    def codes_for(self, seat: int, card_ids: list[int]) -> list[str]:
        try:
            return [self.ids[seat][i] for i in card_ids]
        except KeyError:
            raise IllegalPlay("Unknown card id.")

    def remove_ids(self, seat: int, card_ids: list[int]) -> None:
        for i in card_ids:
            self.ids[seat].pop(i, None)

    def remove_codes(self, seat: int, codes: list[str]) -> None:
        pool = dict(self.ids[seat])
        for code in codes:
            cid = next(i for i, c in pool.items() if c == code)
            del pool[cid]
            del self.ids[seat][cid]

    def ids_for_codes(self, seat: int, codes: list[str]) -> list[int]:
        pool = dict(self.ids[seat])
        out = []
        for code in codes:
            cid = next(i for i, c in pool.items() if c == code)
            out.append(cid)
            del pool[cid]
        return out


# --------------------------------------------------------------------- state
def trick_json(t) -> dict | None:
    if t is None:
        return None
    d = {"leader": t.leader,
         "plays": [{"seat": p.seat, "cards": p.cards} for p in t.plays]}
    if t.winner is not None:
        d["winner"] = t.winner
        d["points"] = t.points
    return d


def _controller(room: Room, seat: int) -> str:
    sd = room.seats[seat]
    if sd.is_bot:
        return "bot"
    return "human" if sd.connected else "bot_cover"


def _takeover_in(room: Room, seat: int) -> float | None:
    """Seconds before the bot plays for a disconnected human (None if N/A)."""
    sd = room.seats[seat]
    if sd.is_bot or sd.connected or sd.bot_announced:
        return None
    if sd.left_at is None:
        return None
    return round(max(0.0, TAKEOVER_AFTER - (time.monotonic() - sd.left_at)), 1)


def state_for(room: Room, seat: int) -> dict[str, Any]:
    game = room.game
    rnd = room.round
    assert game is not None and rnd is not None
    room.sync_kitty()
    phase = rnd.phase if not game.game_over else "game_over"
    banker = rnd.banker
    hand_codes = rnd.sorted_hand(seat)
    id_pool = dict(room.ids[seat])
    hand = []
    for code in hand_codes:
        # Total by construction: a bare next() here raises StopIteration
        # INSIDE a coroutine, which Python turns into RuntimeError and which
        # killed every subsequent broadcast to the room, not just this seat.
        # If the id map ever disagrees with the hand, mint a fresh handle and
        # carry on — ids are per-round client handles, and an unknown id sent
        # back is already rejected by codes_for().
        cid = next((i for i, c in id_pool.items() if c == code), None)
        if cid is None:
            cid = room.mint_card_id(seat, code)
        else:
            del id_pool[cid]
        hand.append({"id": cid, "code": code})

    trump = None
    if rnd.ordering is not None:
        trump = {"suit": "NT" if rnd.trump_is_nt else rnd.trump_suit,
                 "rank": rnd.trump_rank,
                 "declarer": rnd.declaration["seat"] if rnd.declaration else None}

    declare_options = [room.ids_for_codes(seat, opt)
                       for opt in rnd.declare_options(seat)]

    result = game.result
    return {
        "type": "state",
        "room": room.code,
        "you": seat,
        # The round-end tally lives here too: in-game broadcasts send ONLY
        # state_for, so without this the client's ready count was always
        # 0/N and "Next round" never disabled (2026-08-03).
        "ready": sorted(room.ready),
        "phase": phase,
        "players": [{
            "seat": s, "name": room.seats[s].name, "is_bot": room.seats[s].is_bot,
            "connected": room.seats[s].connected or room.seats[s].is_bot,
            "team": s % 2, "cards_left": len(rnd.hands[s]),
            "is_banker": banker == s,
            # Seconds until the bot covers this seat, so the table can show a
            # countdown instead of a bare "offline" (Jerry, 2026-08-03).
            # Clients tick it down locally: broadcasts are event-driven, not
            # per-second, and an absolute time would need clock agreement.
            "takeover_in": _takeover_in(room, s),
            # Explicit three-way state instead of inferring it from is_bot:
            #   "human"     — a connected person is playing
            #   "bot"       — a permanent bot seat
            #   "bot_cover" — a bot covering a human who dropped
            "controller": _controller(room, s),
            # Seconds the absent owner keeps the right to reclaim. After it
            # expires anyone may claim the seat.
            "reserved_for": (room.seats[s].name
                             if _controller(room, s) == "bot_cover" else None),
        } for s in range(4)],
        "hand": hand,
        "levels": list(game.levels),
        "banker": banker,
        "trump": trump,
        "turn": rnd.turn,
        "declare_options": declare_options,
        "passed": sorted(rnd.passed),
        "current_declaration": (
            {"seat": rnd.declaration["seat"], "cards": rnd.declaration["cards"]}
            if rnd.declaration else None),
        "trick": trick_json(rnd.trick),
        "last_trick": trick_json(rnd.last_trick),
        "attacker_points": rnd.attacker_points,
        "kitty_count": 8,
        "round_result": ({
            "attacker_points": result.attacker_points,
            "kitty_points": result.kitty_points,
            "kitty_cards": result.kitty_cards,
            "winner_team": result.winner_team,
            "level_change": result.level_change,
            "next_banker": result.next_banker,
            "new_levels": list(result.new_levels),
            "game_over": result.game_over,
        } if result else None),
        "message": rnd.message,
    }


def room_json(room: Room, seat: int) -> dict:
    return {
        "type": "room", "room": room.code, "you": seat, "host": room.host,
        "ready": sorted(room.ready),
        "players": [{"seat": i, "name": s.name, "is_bot": s.is_bot,
                     "connected": s.connected or s.is_bot}
                    for i, s in enumerate(room.seats)],
    }


async def send(ws: WebSocket, payload: dict) -> None:
    """Direct send; only for sockets not yet bound to a seat."""
    try:
        await ws.send_json(payload)
    except Exception:
        pass


def chat_system(room: Room, text: str) -> None:
    """Post a system line into the room chat (joins, leaves, seat claims).

    Uses seat -1 so clients can style it apart from player messages; kept
    in the same scrollback so late joiners see who arrived before them.
    """
    entry = {"seat": -1, "name": "", "text": text, "t": time.time()}
    room.chat.append(entry)
    del room.chat[:-CHAT_KEEP]
    for sd in room.seats:
        enqueue(sd, {"type": "chat", **entry})


def enqueue(seat: Seat, payload: dict) -> None:
    """Non-blocking send via the seat's writer task. A slow client fills its
    own queue (old snapshots are dropped) without stalling the room."""
    if seat.queue is None:
        return
    try:
        seat.queue.put_nowait(payload)
    except asyncio.QueueFull:
        try:
            seat.queue.get_nowait()  # drop oldest, keep newest
            seat.queue.put_nowait(payload)
        except asyncio.QueueEmpty:
            pass


async def _writer(ws: WebSocket, queue: asyncio.Queue) -> None:
    try:
        while True:
            await ws.send_json(await queue.get())
    except Exception:
        pass


async def broadcast(room: Room) -> None:
    for i, seat in enumerate(room.seats):
        if seat.connected and not seat.is_bot:
            if room.game and room.round:
                enqueue(seat, state_for(room, i))
            else:
                enqueue(seat, room_json(room, i))


# ----------------------------------------------------------------- bot pump
def current_actor(room: Room) -> int | None:
    rnd = room.round
    if rnd is None or rnd.turn is None or rnd.phase == "round_end":
        return None
    return rnd.turn


def _log_play(room: Room, seat: int, cards: list[str], bot: bool,
              prev_last) -> None:
    room.log_event("play", seat=seat, cards=cards, bot=bot)
    rnd = room.round
    if rnd and rnd.last_trick is not None and rnd.last_trick is not prev_last:
        lt = rnd.last_trick
        room.log_event("trick", winner=lt.winner, points=lt.points,
                       plays=[{"seat": p.seat, "cards": p.cards}
                              for p in lt.plays])



def pending_ready(room: Room) -> set[int]:
    """Connected humans who have not yet confirmed the round end."""
    return {i for i, sd in enumerate(room.seats)
            if not sd.is_bot and sd.connected} - room.ready


async def advance_if_all_ready(room: Room) -> bool:
    """Start the next round once every CONNECTED human has confirmed.

    Called both when someone clicks and when someone drops: a player who
    leaves during the round-end screen must stop being counted, or the
    remaining players wait forever on a browser that is never coming back
    (Jerry, 2026-08-03).
    """
    rnd, game = room.round, room.game
    if game is None or rnd is None or rnd.phase != "round_end" or game.game_over:
        return False
    if pending_ready(room) or not room.ready:
        return False
    room.ready.clear()
    game.start_round()
    room.index_round()
    _log_round_start(room)
    room.deal_task = asyncio.create_task(run_deal(room))
    return True


def _log_round_start(room: Room) -> None:
    rnd, game = room.round, room.game
    assert rnd is not None and game is not None
    room.log_event("round_start", deck=rnd.deck, banker=rnd.banker,
                   trump_rank=rnd.trump_rank, levels=list(game.levels),
                   players=[{"seat": i, "name": s.name, "is_bot": s.is_bot}
                            for i, s in enumerate(room.seats)])


def _log_round_end(room: Room) -> None:
    r = room.game.result if room.game else None
    if r is None:
        return
    room.log_event("round_end", attacker_points=r.attacker_points,
                   kitty=r.kitty_cards, kitty_points=r.kitty_points,
                   winner_team=r.winner_team, level_change=r.level_change,
                   new_levels=list(r.new_levels), next_banker=r.next_banker,
                   game_over=r.game_over)


def bot_step(room: Room, seat: int) -> bool:
    """One bot decision for ``seat`` (caller holds the lock). True if acted."""
    game, rnd = room.game, room.round
    if game is None or rnd is None or game.game_over:
        return False
    try:
        if rnd.phase == "bury":
            cards = room.bot.decide_bury(rnd, seat)
            room.sync_kitty()
            rnd.bury(seat, cards)
            room.remove_codes(seat, cards)
            room.log_event("bury", seat=seat, cards=cards, bot=True)
        elif rnd.phase == "play":
            prev_last = rnd.last_trick
            cards = room.bot.decide_play(rnd, seat)
            rnd.play(seat, cards)
            # a failed throw plays fewer cards than attempted — mirror what
            # the ENGINE recorded, not what the bot asked for
            played = actual_play_after(rnd, seat, prev_last)
            room.remove_codes(seat, played)
            _log_play(room, seat, played, True, prev_last)
        else:
            return False
        if rnd.phase == "round_end" and game.result is None:
            game.finish_round()
            _log_round_end(room)
        return True
    except IllegalPlay as e:  # bot bug — shouldn't happen; skip safely
        rnd.message = f"Bot error at seat {seat}: {e}"
        return False


async def pump_bots(room: Room) -> None:
    while True:
        await asyncio.sleep(BOT_DELAY)
        async with room.lock:
            seat = current_actor(room)
            if seat is None or not room.seats[seat].is_bot:
                return
            if not bot_step(room, seat):
                return
            await broadcast(room)


async def watchdog(room: Room) -> None:
    """If the turn-holder is a disconnected human for TAKEOVER_AFTER seconds,
    the bot plays their turn so the game can't stall forever."""
    loop = asyncio.get_event_loop()
    while True:
        await asyncio.sleep(5.0)
        async with room.lock:
            if rooms.get(room.code) is not room:
                return
            seat = current_actor(room)
            if seat is None:
                continue
            s = room.seats[seat]
            if s.is_bot or s.connected:
                continue
            if loop.time() - s.last_seen >= TAKEOVER_AFTER:
                if bot_step(room, seat):
                    # Say so in chat: otherwise a card appears from an
                    # "offline" seat and the table cannot tell whether the
                    # player came back (Jerry, 2026-08-03). Announce once
                    # per absence, not once per trick.
                    if not s.bot_announced:
                        s.bot_announced = True
                        chat_system(room, f"bot is playing for {s.name} "
                                          f"(disconnected)")
                    await broadcast(room)
                    kick_bots(room)


async def cleanup_room(room: Room) -> None:
    """Delete the room only after ROOM_TTL with no humans connected, so a
    refresh or network blip can reclaim the seat and resume the game."""
    await asyncio.sleep(ROOM_TTL)
    async with room.lock:
        if any(s.connected for s in room.seats if not s.is_bot):
            return
        rooms.pop(room.code, None)
        for task in (room.bot_task, room.deal_task, room.watchdog_task):
            if task is not None:
                task.cancel()


def kick_bots(room: Room) -> None:
    seat = current_actor(room)
    if seat is not None and room.seats[seat].is_bot:
        if room.bot_task is None or room.bot_task.done():
            room.bot_task = asyncio.create_task(pump_bots(room))


# ---------------------------------------------------------------- deal task
def _bot_declares(room: Room, seats: list[int], final: bool = False) -> None:
    rnd = room.round
    assert rnd is not None
    for s in seats:
        if room.seats[s].is_bot:
            cards = room.bot.decide_declare(rnd, s, final=final)
            if cards:
                try:
                    rnd.declare(s, cards)
                    room.log_event("declare", seat=s, cards=cards, bot=True)
                except IllegalPlay:
                    pass


async def run_deal(room: Room) -> None:
    """Stream the deal card by card, then run the declare grace window."""
    rnd = room.round
    assert rnd is not None
    while True:
        async with room.lock:
            if room.round is not rnd:
                return
            if rnd.phase != "deal":
                break
            seat, idx, code = rnd.deal_next()
            room.ids[seat][idx] = code
            _bot_declares(room, [seat])
            await broadcast(room)
        await asyncio.sleep(DEAL_DELAY)

    loop = asyncio.get_event_loop()
    async with room.lock:
        _bot_declares(room, list(range(4)), final=True)
        for s in range(4):
            if room.seats[s].is_bot:
                rnd.passed.add(s)
        await broadcast(room)
    deadline = loop.time() + DECLARE_GRACE
    last_declaration = rnd.declaration
    while True:
        await asyncio.sleep(0.25)
        async with room.lock:
            if room.round is not rnd or rnd.phase != "declare":
                return
            if rnd.declaration is not last_declaration:
                last_declaration = rnd.declaration
                deadline = max(deadline, loop.time() + DECLARE_EXTEND)
                _bot_declares(room, list(range(4)), final=True)
                for s in range(4):
                    if room.seats[s].is_bot:
                        rnd.passed.add(s)
            humans = [i for i, s in enumerate(room.seats)
                      if not s.is_bot and s.connected]
            if all(i in rnd.passed for i in humans) or loop.time() >= deadline:
                rnd.finalize_declare()
                room.log_event("trump", suit=rnd.trump_suit or "NT",
                               rank=rnd.trump_rank, banker=rnd.banker,
                               declared=rnd.declaration is not None)
                await broadcast(room)
                kick_bots(room)
                return


# ------------------------------------------------------------------ actions
def new_code() -> str:
    while True:
        code = "".join(random.choices(string.ascii_uppercase, k=4))
        if code not in rooms:
            return code


def _card_ids(msg: dict) -> list[int]:
    ids = msg.get("card_ids")
    if (not isinstance(ids, list) or not ids
            or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids)
            or len(set(ids)) != len(ids)):
        raise IllegalPlay("Invalid card selection.")
    return ids


async def handle_action(room: Room, seat: int, msg: dict) -> None:
    """Caller holds room.lock. Raises IllegalPlay on bad input."""
    t = msg.get("type")
    game, rnd = room.game, room.round

    if t == "chat":
        text = str(msg.get("text", "")).strip()[:CHAT_MAX_LEN]
        if not text:
            return
        entry = {"seat": seat, "name": room.seats[seat].name, "text": text,
                 "t": time.time()}
        room.chat.append(entry)
        del room.chat[:-CHAT_KEEP]
        room.log_event("chat", seat=seat, text=text, bot=False)
        for sd in room.seats:          # push to everyone, including the sender
            enqueue(sd, {"type": "chat", **entry})
        return

    if t == "add_bot":
        if seat != room.host or len(room.seats) >= 4:
            raise IllegalPlay("Cannot add a bot now.")
        room.seats.append(Seat(name=f"Bot {len(room.seats)}", is_bot=True))
    elif t == "remove_bot":
        if seat != room.host or not room.seats or not room.seats[-1].is_bot:
            raise IllegalPlay("No bot to remove.")
        if room.game:
            raise IllegalPlay("Game already started.")
        room.seats.pop()
    elif t == "start_game":
        if seat != room.host:
            raise IllegalPlay("Only the host can start.")
        if len(room.seats) != 4:
            raise IllegalPlay("Need exactly 4 players.")
        if room.game:
            raise IllegalPlay("Game already started.")
        room.game = Game()
        room.game.start_round()
        room.index_round()
        _log_round_start(room)
        room.deal_task = asyncio.create_task(run_deal(room))
        if room.watchdog_task is None or room.watchdog_task.done():
            room.watchdog_task = asyncio.create_task(watchdog(room))
    elif game is None or rnd is None:
        raise IllegalPlay("Game not started.")
    elif t == "declare":
        codes = room.codes_for(seat, _card_ids(msg))
        rnd.declare(seat, codes)
        room.log_event("declare", seat=seat, cards=codes, bot=False)
    elif t == "pass_declare":
        rnd.pass_declare(seat)
    elif t == "bury":
        room.sync_kitty()
        ids = _card_ids(msg)
        codes = room.codes_for(seat, ids)
        rnd.bury(seat, codes)
        room.remove_ids(seat, ids)
        room.log_event("bury", seat=seat, cards=codes, bot=False)
    elif t == "play":
        ids = _card_ids(msg)
        codes = room.codes_for(seat, ids)
        prev_last = rnd.last_trick
        rnd.play(seat, codes)
        # a failed throw may have played different (fewer) cards than sent;
        # the play landed either in the open trick or the just-closed one
        if rnd.trick and rnd.trick.plays:
            played = rnd.trick.plays[-1].cards
        else:
            assert rnd.last_trick is not None
            played = next(p.cards for p in rnd.last_trick.plays if p.seat == seat)
        if sorted(played) == sorted(codes):
            room.remove_ids(seat, ids)
        else:
            room.remove_codes(seat, played)
        _log_play(room, seat, played, False, prev_last)
    elif t == "next_round":
        if rnd.phase != "round_end":
            raise IllegalPlay("Round not finished.")
        if game.game_over:
            raise IllegalPlay("Game is over.")
        # Wait for EVERY connected human to confirm, so nobody's review of
        # the round gets cut short by a faster clicker (Jerry, 2026-08-03).
        room.ready.add(seat)
        if not await advance_if_all_ready(room):
            await broadcast(room)
    else:
        raise IllegalPlay(f"Unknown action: {t}")

    rnd = room.round
    if rnd and rnd.phase == "round_end" and room.game and room.game.result is None:
        room.game.finish_round()
        _log_round_end(room)


# --------------------------------------------------------------- websocket
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    room: Room | None = None
    me: Seat | None = None  # seat OBJECT — indexes shift when lobby seats leave
    my_gen = 0              # connection generation this socket owns
    try:
        while True:
            msg = await ws.receive_json()
            if not isinstance(msg, dict):
                continue
            t = msg.get("type")
            if room is None or me is None:
                if t == "create_room":
                    room = Room(code=new_code())
                    rooms[room.code] = room
                    me = Seat(name=str(msg.get("name") or "Player"),
                              ws=ws, connected=True)
                    me.queue = asyncio.Queue(maxsize=128)
                    me.writer = asyncio.create_task(_writer(ws, me.queue))
                    room.seats.append(me)
                    await broadcast(room)
                elif t == "peek_room":
                    # Who is sitting where, WITHOUT joining — the lobby uses
                    # this to offer a seat picker for a game in progress.
                    target = rooms.get(str(msg.get("room", "")).upper())
                    if target is None:
                        await send(ws, {"type": "error", "code": "room_not_found",
                                        "message": "Room not found."})
                        continue
                    await send(ws, {
                        "type": "room_seats",
                        "room": target.code,
                        "in_game": target.game is not None,
                        "seats": [{"seat": i, "name": sd.name,
                                   "is_bot": sd.is_bot,
                                   "connected": sd.connected,
                                   "team": i % 2,
                                   # What the lobby actually needs to know:
                                   # a dropped human's seat can be taken too.
                                   "claimable": sd.is_bot or not sd.connected,
                                   "controller": ("bot" if sd.is_bot else
                                                  "human" if sd.connected
                                                  else "bot_cover")}
                                  for i, sd in enumerate(target.seats)],
                    })
                elif t == "join_room":
                    # Per-JOIN, not per-socket: these were read back via
                    # locals(), so a player who claimed a bot seat in one room
                    # kept claimed_from_bot/took_from set and the NEXT room
                    # announced a stale bot's name (Codex case 8).
                    claimed_from_bot = False
                    took_from = ""
                    took_over_human = False
                    code = str(msg.get("room", "")).upper()
                    target = rooms.get(code)
                    if target is None:
                        await send(ws, {"type": "error", "code": "room_not_found",
                                        "message": "Room not found."})
                        continue
                    async with target.lock:
                        name = str(msg.get("name") or "Player")
                        # Match on a normalised name: an exact-only match
                        # locked people out of their own seat whenever they
                        # came back on another device or retyped their name
                        # with different capitalisation (Jerry, 2026-08-03).
                        # Identity order: TOKEN first (the only real identity;
                        # it also lets a player resume while their stale socket
                        # is still open — the newest connection wins), then a
                        # normalised name among DISCONNECTED seats.
                        tok = msg.get("token")
                        reclaim = None
                        if isinstance(tok, str) and tok:
                            reclaim = next(
                                (s for s in target.seats
                                 if not s.is_bot and secrets.compare_digest(
                                     s.token, tok)), None)
                        if reclaim is None:
                            key = name.strip().casefold()
                            reclaim = next(
                                (s for s in target.seats
                                 if not s.is_bot and not s.connected
                                 and s.name.strip().casefold() == key),
                                None)
                        if reclaim is not None:
                            me = reclaim
                        elif len(target.seats) < 4 and target.game is None:
                            me = Seat(name=name)
                            target.seats.append(me)
                        else:
                            # Take over a BOT's seat, mid-game if need be —
                            # the hand already exists, so a late arrival can
                            # sit down without restarting (Jerry, 2026-08-03).
                            # Safe under the room lock: pump_bots re-checks
                            # is_bot after every BOT_DELAY and exits cleanly
                            # when a seat stops being a bot.
                            want = msg.get("seat")
                            # Claimable = bot seats, plus seats whose human has
                            # dropped (a bot is covering those anyway). Without
                            # the second group a 4-human game with one player
                            # offline reported "room full" and NOBODY could
                            # take the seat — not even that player under a
                            # different name (Jerry, 2026-08-03).
                            botseats = [i for i, sd in enumerate(target.seats)
                                        if sd.is_bot]
                            dropped = [i for i, sd in enumerate(target.seats)
                                       if not sd.is_bot and not sd.connected]
                            claimable = botseats + dropped
                            if isinstance(want, bool) or not (
                                    want is None or isinstance(want, int)):
                                want = None          # malformed: treat as "any"
                            if want is not None and want not in claimable:
                                # Two people can pick the same seat between the
                                # peek and the join. Silently seating the loser
                                # somewhere else puts them on a team they did
                                # not choose — refuse and let them re-pick.
                                await send(ws, {
                                    "type": "error", "code": "seat_unavailable",
                                    "message": "That seat was just taken — "
                                               "pick another."})
                                continue
                            pick = want if want is not None else (
                                botseats[0] if botseats else None)
                            if pick is None:
                                if dropped:
                                    # Seats exist, but each belongs to someone
                                    # who may be reconnecting: make the caller
                                    # choose one deliberately.
                                    await send(ws, {
                                        "type": "error", "code": "choose_seat",
                                        "message": "Every seat is taken, but "
                                                   "a player is offline — pick "
                                                   "their seat to take over."})
                                else:
                                    await send(ws, {
                                        "type": "error", "code": "room_full",
                                        "message": "Room is full — every seat "
                                                   "is taken by a human."})
                                continue
                            me = target.seats[pick]
                            # Name whoever they replaced: "took Bot 1's seat"
                            # says WHICH seat far better than "a bot's seat".
                            took_from = me.name
                            took_over_human = not me.is_bot
                            me.bot_announced = False
                            me.is_bot = False
                            me.name = name
                            target.log_event("seat_claimed", seat=pick,
                                             name=name, bot=False)
                            claimed_from_bot = True
                        room = target
                        my_gen = _attach(room, me, ws)
                        if reclaim is not None:
                            chat_system(
                                room,
                                f"{name} reconnected"
                                + (" — taking over from the bot"
                                   if me.bot_announced else ""))
                            me.bot_announced = False
                        elif claimed_from_bot:
                            chat_system(
                                room,
                                f"{name} took over for {took_from} (offline)"
                                if took_over_human
                                else f"{name} took {took_from}'s seat")
                        else:
                            chat_system(room, f"{name} joined")
                        kick_bots(room)      # remaining bot seats keep playing
                        await broadcast(room)
                else:
                    await send(ws, {"type": "error", "message": "Join a room first."})
                continue

            if t == "leave_room":
                async with room.lock:
                    chat_system(room, f"{me.name} left")
                    _detach(me, room)
                    if room.game is None:
                        # lobby: free the seat entirely
                        if me in room.seats:
                            room.seats.remove(me)
                        humans = [i for i, x in enumerate(room.seats)
                                  if not x.is_bot]
                        if not humans:
                            rooms.pop(room.code, None)
                        else:
                            room.host = humans[0]
                            await broadcast(room)
                    else:
                        # mid-game: seat stays (reclaimable); bots cover it
                        if not any(x.connected for x in room.seats
                                   if not x.is_bot):
                            if room.cleanup_task is None or room.cleanup_task.done():
                                room.cleanup_task = asyncio.create_task(
                                    cleanup_room(room))
                        # Explicit leave must re-check the round-end quorum
                        # exactly like an abrupt disconnect: the last unready
                        # player LEAVING used to deadlock everyone else while
                        # the same player DROPPING advanced the round
                        # (Codex ship gate P0-4).
                        elif not await advance_if_all_ready(room):
                            await broadcast(room)
                await send(ws, {"type": "left"})
                room, me = None, None
                continue
            async with room.lock:
                try:
                    seat_idx = room.seats.index(me)
                except ValueError:  # seat vanished — shouldn't happen mid-game
                    room, me = None, None
                    await send(ws, {"type": "error", "code": "room_not_found",
                                    "message": "Seat no longer exists."})
                    continue
                try:
                    await handle_action(room, seat_idx, msg)
                    await broadcast(room)
                    kick_bots(room)
                except IllegalPlay as e:
                    enqueue(me, {"type": "error", "message": str(e)})
                except Exception:  # malformed input must not kill the socket
                    enqueue(me, {"type": "error", "message": "Invalid request."})
    except WebSocketDisconnect:
        pass
    finally:
        if room is not None and me is not None:
            async with room.lock:
                if not me.is_bot and me.connected:
                    chat_system(room, f"{me.name} disconnected")
                _detach(me, room, my_gen)
                if not any(x.connected for x in room.seats if not x.is_bot):
                    if room.cleanup_task is None or room.cleanup_task.done():
                        room.cleanup_task = asyncio.create_task(cleanup_room(room))
                else:
                    if not await advance_if_all_ready(room):
                        await broadcast(room)



def _attach(room: Room, seat: Seat, ws: WebSocket) -> int:
    """Bind a socket to a seat as ONE transition (caller holds the room lock).

    Membership used to be updated inline at each call site — connected flag,
    queue, writer, cleanup task, scrollback — and the paths drifted apart.
    That is how a dropped player's seat became unreachable while still looking
    occupied (Jerry, 2026-08-03) and why Codex asked for a single owner of the
    transition.
    """
    if room.cleanup_task is not None:
        room.cleanup_task.cancel()
        room.cleanup_task = None
    if seat.writer is not None:      # displace any older live socket
        seat.writer.cancel()
    seat.gen += 1
    seat.ws, seat.connected = ws, True
    seat.left_at = None
    seat.queue = asyncio.Queue(maxsize=128)
    seat.writer = asyncio.create_task(_writer(ws, seat.queue))
    enqueue(seat, {"type": "resume", "token": seat.token, "gen": seat.gen})
    for entry in room.chat:            # scrollback, before the first state
        enqueue(seat, {"type": "chat", **entry})
    return seat.gen


def _detach(seat: Seat, room: Room | None = None,
            gen: int | None = None) -> None:
    """Unbind a websocket from a seat (caller holds the room lock).

    Also drops the seat from the round-end quorum: a player who leaves must
    stop being waited on, or everyone else sits on a browser that is never
    coming back.
    """
    if gen is not None and gen != seat.gen:
        return                       # a newer socket owns this seat now
    if room is not None and seat in room.seats:
        room.ready.discard(room.seats.index(seat))
    seat.ws, seat.connected = None, False
    seat.left_at = time.monotonic()
    if seat.writer is not None:
        seat.writer.cancel()
    seat.writer, seat.queue = None, None
    try:                     # watchdog clock; unavailable off-loop (tests)
        seat.last_seen = asyncio.get_event_loop().time()
    except RuntimeError:
        pass


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "rooms": len(rooms),
            "bot": os.environ.get("SHENGJI_BOT", "mc")}


from .debug import register_debug  # noqa: E402

register_debug(app, rooms)

# ------------------------------------------------------------------ static
dist = Path(__file__).resolve().parents[3] / "web" / "dist"
if dist.is_dir():
    app.mount("/", StaticFiles(directory=dist, html=True), name="web")


def main() -> None:
    import uvicorn
    uvicorn.run("shengji.api.server:app", host="0.0.0.0", port=8000)

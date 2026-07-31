"""FastAPI WebSocket server: rooms, seats, humans + bots, per-seat state."""

from __future__ import annotations

import asyncio
import random
import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from ..ai.smart import SmartBot
from ..engine.game import Game
from ..engine.legal import IllegalPlay
from ..engine.round import Round

BOT_DELAY = 0.7
DEAL_DELAY = 0.09          # seconds between dealt cards (~9s full deal)
DECLARE_GRACE = 5.0        # window after the deal; extended on new declarations
DECLARE_EXTEND = 3.0
app = FastAPI(title="shengji")

rooms: dict[str, "Room"] = {}


@dataclass
class Seat:
    name: str
    is_bot: bool = False
    ws: WebSocket | None = None
    connected: bool = False


@dataclass
class Room:
    code: str
    seats: list[Seat] = field(default_factory=list)
    host: int = 0
    game: Game | None = None
    ids: list[dict[int, str]] = field(default_factory=lambda: [{} for _ in range(4)])
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    bot: SmartBot = field(default_factory=SmartBot)
    bot_task: asyncio.Task | None = None
    deal_task: asyncio.Task | None = None

    @property
    def round(self) -> Round | None:
        return self.game.round if self.game else None

    # ------------------------------------------------------------- id mapping
    def index_round(self) -> None:
        rnd = self.round
        assert rnd is not None
        self.ids = [{} for _ in range(4)]  # filled card-by-card as the deal runs
        self._kitty_ids = {100 + i: rnd.deck[100 + i] for i in range(8)}
        self._kitty_given = False

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
        cid = next(i for i, c in id_pool.items() if c == code)
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
        "phase": phase,
        "players": [{
            "seat": s, "name": room.seats[s].name, "is_bot": room.seats[s].is_bot,
            "connected": room.seats[s].connected or room.seats[s].is_bot,
            "team": s % 2, "cards_left": len(rnd.hands[s]),
            "is_banker": banker == s,
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
        "players": [{"seat": i, "name": s.name, "is_bot": s.is_bot,
                     "connected": s.connected or s.is_bot}
                    for i, s in enumerate(room.seats)],
    }


async def send(ws: WebSocket, payload: dict) -> None:
    try:
        await ws.send_json(payload)
    except Exception:
        pass


async def broadcast(room: Room) -> None:
    for i, seat in enumerate(room.seats):
        if seat.ws is not None and seat.connected:
            if room.game and room.round:
                await send(seat.ws, state_for(room, i))
            else:
                await send(seat.ws, room_json(room, i))


# ----------------------------------------------------------------- bot pump
def current_actor(room: Room) -> int | None:
    rnd = room.round
    if rnd is None or rnd.turn is None or rnd.phase == "round_end":
        return None
    return rnd.turn


async def pump_bots(room: Room) -> None:
    while True:
        await asyncio.sleep(BOT_DELAY)
        async with room.lock:
            game, rnd = room.game, room.round
            if game is None or rnd is None or game.game_over:
                return
            seat = current_actor(room)
            if seat is None or not room.seats[seat].is_bot:
                return
            try:
                if rnd.phase == "bury":
                    cards = room.bot.decide_bury(rnd, seat)
                    room.sync_kitty()
                    rnd.bury(seat, cards)
                    room.remove_codes(seat, cards)
                elif rnd.phase == "play":
                    cards = room.bot.decide_play(rnd, seat)
                    rnd.play(seat, cards)
                    room.remove_codes(seat, cards)
                if rnd.phase == "round_end" and game.result is None:
                    game.finish_round()
            except IllegalPlay as e:  # bot bug — shouldn't happen; skip safely
                rnd.message = f"Bot error at seat {seat}: {e}"
                return
            await broadcast(room)


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
                await broadcast(room)
                kick_bots(room)
                return


# ------------------------------------------------------------------ actions
def new_code() -> str:
    while True:
        code = "".join(random.choices(string.ascii_uppercase, k=4))
        if code not in rooms:
            return code


async def handle_action(room: Room, seat: int, msg: dict) -> None:
    """Caller holds room.lock. Raises IllegalPlay on bad input."""
    t = msg.get("type")
    game, rnd = room.game, room.round

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
        room.deal_task = asyncio.create_task(run_deal(room))
    elif game is None or rnd is None:
        raise IllegalPlay("Game not started.")
    elif t == "declare":
        codes = room.codes_for(seat, msg.get("card_ids", []))
        rnd.declare(seat, codes)
    elif t == "pass_declare":
        rnd.pass_declare(seat)
    elif t == "bury":
        room.sync_kitty()
        codes = room.codes_for(seat, msg.get("card_ids", []))
        rnd.bury(seat, codes)
        room.remove_ids(seat, msg.get("card_ids", []))
    elif t == "play":
        ids = msg.get("card_ids", [])
        codes = room.codes_for(seat, ids)
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
    elif t == "next_round":
        if rnd.phase != "round_end":
            raise IllegalPlay("Round not finished.")
        if game.game_over:
            raise IllegalPlay("Game is over.")
        game.start_round()
        room.index_round()
        room.deal_task = asyncio.create_task(run_deal(room))
    else:
        raise IllegalPlay(f"Unknown action: {t}")

    rnd = room.round
    if rnd and rnd.phase == "round_end" and room.game and room.game.result is None:
        room.game.finish_round()


# --------------------------------------------------------------- websocket
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    room: Room | None = None
    seat: int | None = None
    try:
        while True:
            msg = await ws.receive_json()
            t = msg.get("type")
            if room is None:
                if t == "create_room":
                    room = Room(code=new_code())
                    rooms[room.code] = room
                    room.seats.append(Seat(name=str(msg.get("name") or "Player"),
                                           ws=ws, connected=True))
                    seat = 0
                    await broadcast(room)
                elif t == "join_room":
                    code = str(msg.get("room", "")).upper()
                    target = rooms.get(code)
                    if target is None:
                        await send(ws, {"type": "error", "message": "Room not found."})
                        continue
                    async with target.lock:
                        name = str(msg.get("name") or "Player")
                        reclaim = next(
                            (i for i, s in enumerate(target.seats)
                             if not s.is_bot and not s.connected and s.name == name),
                            None)
                        if reclaim is not None:
                            seat = reclaim
                        elif len(target.seats) < 4 and target.game is None:
                            target.seats.append(Seat(name=name))
                            seat = len(target.seats) - 1
                        else:
                            await send(ws, {"type": "error", "message": "Room is full."})
                            continue
                        room = target
                        room.seats[seat].ws = ws
                        room.seats[seat].connected = True
                        await broadcast(room)
                else:
                    await send(ws, {"type": "error", "message": "Join a room first."})
                continue

            assert seat is not None
            async with room.lock:
                try:
                    await handle_action(room, seat, msg)
                    await broadcast(room)
                    kick_bots(room)
                except IllegalPlay as e:
                    await send(ws, {"type": "error", "message": str(e)})
    except WebSocketDisconnect:
        pass
    finally:
        if room is not None and seat is not None:
            async with room.lock:
                room.seats[seat].ws = None
                room.seats[seat].connected = False
                if not any(s.connected for s in room.seats if not s.is_bot):
                    rooms.pop(room.code, None)
                else:
                    await broadcast(room)


# ------------------------------------------------------------------ static
dist = Path(__file__).resolve().parents[3] / "web" / "dist"
if dist.is_dir():
    app.mount("/", StaticFiles(directory=dist, html=True), name="web")


def main() -> None:
    import uvicorn
    uvicorn.run("shengji.api.server:app", host="0.0.0.0", port=8000)

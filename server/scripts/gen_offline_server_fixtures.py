#!/usr/bin/env python3
"""Fixtures that hold the offline local game server to ``shengji.api.server``.

The offline mode of the web client (``web/src/offline/server/``) answers the
same client messages the game server does and must send the same frames.  This
script runs seeded solo games through the real ``ws_endpoint``: one fake
WebSocket for the human at seat 0, three server bots, and a human driver that
plays seat 0 with SmartBot through ordinary client messages.  It records every
frame the human's socket receives, normalised for the fields that are
environmental (see ``normalize``), and writes one line per game to
``server_sessions.jsonl.gz``: the seed, how many rounds were played, the frame
count and a short digest of each frame.  The vitest suite drives the
TypeScript server with the same seeds and the same human driver and compares
digests frame by frame.

Determinism:
- the event loop runs on virtual time: when nothing is ready it jumps to the
  next timer, so the deal pacing, the declare window and the bot pacing keep
  their order and their relative timing but take no wall time;
- bot search runs inline instead of in a worker thread (the same
  ``_compute_bot_turn`` on the same snapshot);
- the deck order comes from a small seeded shuffle (``DeckRng``) that the
  TypeScript server reproduces exactly; ``Game`` receives it as its ``rng``.
The room bot is SmartBot (``SHENGJI_BOT=smart``), the offline bot.

Usage::

    python scripts/gen_offline_server_fixtures.py --games 200 --rounds 2 \\
        --out ../web/src/offline/fixtures
    python scripts/gen_offline_server_fixtures.py --dump 7 --rounds 2   # one game's frames
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
for _p in (SERVER_DIR, SCRIPTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Read by the server at import (log root) and at room creation (bot policy).
os.environ["SHENGJI_BOT"] = "smart"
os.environ.setdefault("SHENGJI_LOG_DIR", tempfile.mkdtemp(prefix="offline-server-fixtures-"))

from gen_offline_engine_fixtures import _dumps, _gzip_bytes  # noqa: E402
from starlette.websockets import WebSocketDisconnect, WebSocketState  # noqa: E402

import shengji.api.server as server  # noqa: E402
from shengji.ai.smart import SmartBot  # noqa: E402
from shengji.engine.combos import decompose  # noqa: E402
from shengji.engine.game import Game  # noqa: E402

FORMAT = 1
HUMAN_NAME = "You"
HUMAN_SEAT = 0
M32 = 0xFFFFFFFF
# A session that has not ended after this many frames is a driver bug.
MAX_FRAMES = 20_000
PLAIN_SUITS = "SHDC"


def game_config(g: int) -> dict:
    """Driver variations, cycled by game index so every one is covered:
    every fourth game starts at A (a defended A scores a game point and the
    levels restart), and every third game's human leads attempted throws."""
    return {"startLevel": "A" if g % 4 == 3 else None, "throws": g % 3 == 1}


class DeckRng:
    """mulberry32 plus a Fisher-Yates shuffle: small enough to port exactly
    (``web/src/offline/server/rng.ts``) so both servers deal the same decks."""

    def __init__(self, seed: int):
        self.state = seed & M32

    def next_u32(self) -> int:
        self.state = (self.state + 0x6D2B79F5) & M32
        t = self.state
        t = ((t ^ (t >> 15)) * (t | 1)) & M32
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & M32)) & M32
        return (t ^ (t >> 14)) & M32

    def shuffle(self, items: list) -> None:
        for i in range(len(items) - 1, 0, -1):
            j = self.next_u32() % (i + 1)
            items[i], items[j] = items[j], items[i]


class VirtualTimeLoop(asyncio.SelectorEventLoop):
    """An event loop whose clock jumps to the next timer when nothing is ready."""

    def __init__(self):
        super().__init__()
        self._virtual_now = 0.0

    def time(self) -> float:
        return self._virtual_now

    def _run_once(self) -> None:
        if not self._ready and self._scheduled:
            when = self._scheduled[0]._when
            if when > self._virtual_now:
                self._virtual_now = when
        super()._run_once()


class FakeWebSocket:
    """What ``ws_endpoint`` uses of a starlette WebSocket. ``None`` in the
    inbox is a disconnect."""

    cookies: dict = {}

    def __init__(self):
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.outbox: asyncio.Queue = asyncio.Queue()
        self.application_state = WebSocketState.CONNECTED

    async def accept(self) -> None:
        return None

    async def receive_json(self):
        msg = await self.inbox.get()
        if msg is None:
            self.application_state = WebSocketState.DISCONNECTED
            raise WebSocketDisconnect()
        return msg

    async def send_json(self, payload) -> None:
        # what the wire carries: tuples become lists, keys become strings
        self.outbox.put_nowait(json.loads(json.dumps(payload)))


# ------------------------------------------------------------- normalisation

NORMALIZED_FIELDS = {
    "room": "room code (random per room)",
    "token": "resume token (random per seat)",
    "t": "chat timestamp (wall clock)",
}


def normalize(msg: dict) -> dict:
    """Replace the environmental fields listed in NORMALIZED_FIELDS."""
    out = dict(msg)
    if "room" in out:
        out["room"] = "ROOM"
    if out.get("type") == "resume":
        out["token"] = "TOKEN"
    if out.get("type") == "chat":
        out["t"] = 0
    if out.get("type") == "chat_history":
        out["messages"] = [{**m, "room": "ROOM", "t": 0} for m in out["messages"]]
    return out


def canonical(msg: dict) -> str:
    return json.dumps(msg, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(msg: dict) -> str:
    return hashlib.sha256(canonical(msg).encode("ascii")).hexdigest()[:8]


# ------------------------------------------------------------------- driver

def _ids_for(hand: list[dict], codes: list[str]) -> list[int]:
    """The ids a player picks for ``codes``: per code, the first unused card
    with that code in the hand as the state lists it."""
    pool = list(hand)
    out = []
    for code in codes:
        k = next(i for i, c in enumerate(pool) if c["code"] == code)
        out.append(pool.pop(k)["id"])
    return out


class HumanDriver:
    """Seat 0 as a client: App's Play-vs-bots chain, then SmartBot decisions
    sent as ordinary messages.  Mirrored in web/src/offline/server/driver.ts.

    A decision is made only on a frame that matches the live round (``fresh``):
    a frame read after the room already moved on is not acted on.
    """

    def __init__(self, rounds: int, live_round, throws: bool = False):
        self.rounds = rounds
        self.throws = throws
        self.live_round = live_round      # () -> the room's current Round, or None
        self.bot = SmartBot()
        self.rounds_done = 0
        self.leaving = False
        self.acted: set = set()

    def _fresh(self, msg: dict, rnd) -> bool:
        decl = rnd.declaration
        live_decl = {"seat": decl["seat"], "cards": decl["cards"]} if decl else None
        trick = rnd.trick
        return (msg["phase"] == rnd.phase
                and len(msg["hand"]) == len(rnd.hands[HUMAN_SEAT])
                and msg["turn"] == rnd.turn
                and msg["current_declaration"] == live_decl
                and msg["passed"] == sorted(rnd.passed)
                and len(msg["trick"]["plays"] if msg["trick"] else []) ==
                    len(trick.plays if trick else [])
                and (msg["last_trick"] is None) == (rnd.last_trick is None))

    def react(self, msg: dict) -> list[dict]:
        t = msg["type"]
        if t == "room":
            if msg["you"] != msg["host"]:
                return []
            if len(msg["players"]) < 4:
                return [{"type": "add_bot"}]
            return [{"type": "start_game"}]
        if t != "state" or self.leaving:
            return []
        phase = msg["phase"]
        if phase == "round_end":
            if HUMAN_SEAT in msg["ready"]:
                return []
            self.rounds_done += 1
            if self.rounds_done >= self.rounds:
                self.leaving = True
                return [{"type": "leave_room"}]
            return [{"type": "next_round"}]
        rnd = self.live_round()
        if rnd is None or not self._fresh(msg, rnd):
            return []
        hand = msg["hand"]
        if phase in ("deal", "declare"):
            if phase == "declare" and HUMAN_SEAT in msg["passed"]:
                return []
            final = phase == "declare"
            cards = None
            if msg["declare_options"]:
                cards = self.bot.decide_declare(rnd, HUMAN_SEAT, final=final)
            if cards:
                by_id = {c["id"]: c["code"] for c in hand}
                ids = next(o for o in msg["declare_options"]
                           if sorted(by_id[i] for i in o) == sorted(cards))
                return [{"type": "declare", "card_ids": ids}]
            return [{"type": "pass_declare"}] if final else []
        if msg["turn"] != HUMAN_SEAT:
            return []
        key = (self.rounds_done, phase, len(rnd.history),
               len(rnd.trick.plays) if rnd.trick else -1)
        if key in self.acted:
            return []
        self.acted.add(key)
        if phase == "bury":
            cards = self.bot.decide_bury(rnd, HUMAN_SEAT)
            return [{"type": "bury", "card_ids": _ids_for(hand, list(cards))}]
        if phase == "play":
            cards = self._throw(rnd) if self.throws else None
            if cards is None:
                cards = self.bot.decide_play(rnd, HUMAN_SEAT)
            return [{"type": "play", "card_ids": _ids_for(hand, list(cards))}]
        return []


    @staticmethod
    def _throw(rnd):
        """On a lead: every card of the first plain suit (S H D C) that holds
        more than one component, which the engine often refuses as a throw."""
        if rnd.trick.plays:
            return None
        o = rnd.ordering
        for suit in PLAIN_SUITS:
            cards = [c for c in rnd.hands[HUMAN_SEAT] if o.eff_suit(c) == suit]
            if len(decompose(cards, o).components) > 1:
                return cards
        return None


async def _inline_bot_turn(snapshot):
    return server._compute_bot_turn(snapshot)


async def _session(seed: int, rounds: int, config: dict) -> list[dict]:
    ws = FakeWebSocket()
    endpoint = asyncio.ensure_future(server.ws_endpoint(ws))

    def live_round():
        room = next(iter(server.rooms.values()), None)
        return room.round if room is not None else None

    human = HumanDriver(rounds, live_round, throws=config["throws"])
    create = {"type": "create_room", "name": HUMAN_NAME}
    if config["startLevel"] is not None:
        create["start_level"] = config["startLevel"]
    ws.inbox.put_nowait(create)
    frames = []
    while True:
        msg = await ws.outbox.get()
        frames.append(normalize(msg))
        if msg["type"] == "error":
            raise RuntimeError(f"seed {seed}: server refused the driver: {msg}")
        if msg["type"] == "left":
            break
        if len(frames) > MAX_FRAMES:
            raise RuntimeError(f"seed {seed}: no end after {MAX_FRAMES} frames")
        for action in human.react(msg):
            ws.inbox.put_nowait(action)
    ws.inbox.put_nowait(None)
    await endpoint
    return frames


def play_session(seed: int, rounds: int, config: dict) -> list[dict]:
    """Every frame seat 0 receives in one seeded solo game of ``rounds`` rounds."""
    saved = (server.Game, server._compute_bot_turn_off_loop)
    server.Game = functools.partial(Game, DeckRng(seed))
    server._compute_bot_turn_off_loop = _inline_bot_turn
    loop = VirtualTimeLoop()
    try:
        return loop.run_until_complete(_session(seed, rounds, config))
    finally:
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()
        server.rooms.clear()
        server.Game, server._compute_bot_turn_off_loop = saved


def game_seed(base: int, g: int) -> int:
    return (base * 1_000_003 + g) & M32


def session_record(seed: int, rounds: int, config: dict, stats: Counter) -> dict:
    frames = play_session(seed, rounds, config)
    kinds = Counter(f["type"] for f in frames)
    for k, v in kinds.items():
        stats[f"frames_{k}"] += v
    stats["frames"] += len(frames)
    stats["games"] += 1
    for f in frames:
        if f["type"] == "state":
            if f.get("notice") is not None:
                stats["notice_frames"] += 1
            if f["phase"] == "round_end":
                stats["round_end_frames"] += 1
                if f["round_result"]["point_scored"]:
                    stats["point_scored_rounds"] += 1
            if f["phase"] == "bury" and f["turn"] == HUMAN_SEAT:
                stats["human_bury_frames"] += 1
            decl = f["current_declaration"]
            if f["phase"] in ("deal", "declare") and decl and decl["seat"] == HUMAN_SEAT:
                stats["human_declared_frames"] += 1
    return {"seed": seed, "rounds": rounds, "config": config, "frames": len(frames),
            "digests": "".join(digest(f) for f in frames)}


def sessions_text(n_games: int, rounds: int, base_seed: int, stats=None) -> str:
    stats = Counter() if stats is None else stats
    lines = [_dumps(session_record(game_seed(base_seed, g), rounds, game_config(g), stats))
             for g in range(n_games)]
    deck = list(__import__("shengji.engine.cards", fromlist=["make_deck"]).make_deck())
    DeckRng(game_seed(base_seed, 0)).shuffle(deck)
    header = {"format": FORMAT, "games": n_games, "rounds": rounds, "seed": base_seed,
              "human": HUMAN_NAME, "firstDeck": deck,
              "normalized": NORMALIZED_FIELDS, "stats": dict(sorted(stats.items()))}
    return "\n".join([_dumps(header)] + lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--dump", type=int, metavar="GAME",
                    help="print game GAME's normalised frames as JSON lines")
    args = ap.parse_args(argv)
    if args.dump is not None:
        for f in play_session(game_seed(args.seed, args.dump), args.rounds,
                              game_config(args.dump)):
            print(canonical(f))
        return 0
    if args.out is None:
        ap.error("--out is required unless --dump is given")
    stats: Counter = Counter()
    text = sessions_text(args.games, args.rounds, args.seed, stats)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "server_sessions.jsonl.gz").write_bytes(_gzip_bytes(text))
    print(json.dumps(dict(sorted(stats.items()))))
    return 0


if __name__ == "__main__":
    sys.exit(main())

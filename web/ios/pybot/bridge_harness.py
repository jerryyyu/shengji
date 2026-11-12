"""The game server's bot decisions, recorded as offline decision requests.

Runs seeded solo games through the real ``shengji.api.server.ws_endpoint``
(the driver of ``server/scripts/gen_offline_server_fixtures.py``: one human
seat played by SmartBot through client messages, three server bot seats) and
records, for every decision the room bot makes, the request the offline page
would send for it (``offline_bot`` module docstring) together with the cards
the server's bot chose.  Feeding the requests, in order, to a fresh
``offline_bot`` session seeded like the room bot must reproduce every choice.

How a request is read off the server:

* the live round of each ``Game.start_round`` carries an action log that the
  engine's own methods extend (deal, declare, pass, finalize, bury, play), and
  a deep copy of the round keeps the log as it was at copy time, so the
  server's turn snapshot (a copy) holds exactly the actions committed before
  the decision;
* the room bot's class is wrapped so each top-level ``decide_*`` call records
  the request built from the round it is handed and the cards it returns.

Bot search runs inline (no worker threads), as in the fixture generator, so the
event loop's virtual clock never advances during a search.
"""
from __future__ import annotations

import asyncio
import copy
import functools
import importlib
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SERVER = REPO / "server"
for _p in (SERVER, SERVER / "scripts", Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import offline_bot  # noqa: E402


class _PassSet(set):
    """``Round.passed`` of a live round: a new member is logged as a pass."""

    def add(self, seat):
        rnd = self._round
        if seat not in self and rnd is not None and _is_live(rnd):
            rnd._actlog.append(["pass", seat])
        super().add(seat)

    def __deepcopy__(self, memo):
        out = set(self)
        return out


def _is_live(rnd) -> bool:
    return getattr(rnd, "_actlog_owner", None) == id(rnd)


def request_for(rnd, kind: str, seat: int, final: bool = False) -> dict:
    """The offline page's request for this decision on ``rnd``."""
    req = {"v": 1, "kind": kind, "seat": seat, "deck": list(rnd.deck),
           "trump_rank": rnd.trump_rank,
           "banker": None if rnd.first_round else rnd.banker,
           "log": copy.deepcopy(rnd._actlog)}
    if kind == "declare":
        req["final"] = bool(final)
    return req


class _Patches:
    """Engine and server hooks, installed for one recording and then removed."""

    def __init__(self):
        self.saved = []

    def set(self, obj, name, value):
        self.saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, value in reversed(self.saved):
            setattr(obj, name, value)
        self.saved.clear()


def _install_round_log(p: _Patches) -> None:
    from shengji.engine.game import Game
    from shengji.engine.round import Round

    start_round = Game.start_round

    def logged_start_round(self):
        rnd = start_round(self)
        rnd._actlog = []
        rnd._actlog_owner = id(rnd)
        passed = _PassSet(rnd.passed)
        passed._round = rnd
        rnd.passed = passed
        return rnd

    p.set(Game, "start_round", logged_start_round)

    deal_next = Round.deal_next

    def logged_deal_next(self):
        out = deal_next(self)
        if _is_live(self):
            log = self._actlog
            if log and log[-1][0] == "deal":
                log[-1][1] = self._deal_pos
            else:
                log.append(["deal", self._deal_pos])
        return out

    p.set(Round, "deal_next", logged_deal_next)

    def wrap(name, entry):
        orig = getattr(Round, name)

        @functools.wraps(orig)
        def logged(self, *args):
            out = orig(self, *args)
            if _is_live(self):
                self._actlog.append(entry(*args))
            return out

        p.set(Round, name, logged)

    wrap("declare", lambda seat, cards: ["declare", seat, list(cards)])
    wrap("finalize_declare", lambda: ["finalize"])
    wrap("bury", lambda seat, cards: ["bury", seat, list(cards)])
    wrap("play", lambda seat, cards: ["play", seat, list(cards)])


def recording_bot(bot, records: list):
    """``bot`` with its class wrapped: every top-level decision is recorded."""
    base = type(bot)

    def _record(self, kind, rnd, seat, final, fn):
        depth = getattr(self, "_rec_depth", 0)
        req = request_for(rnd, kind, seat, final) if depth == 0 and hasattr(rnd, "_actlog") else None
        self._rec_depth = depth + 1
        try:
            out = fn()
        finally:
            self._rec_depth = depth
        if req is not None:
            records.append({"request": req, "cards": list(out) if out else None,
                            "clock": offline_bot.clock_flags(self, kind)})
        return out

    def decide_declare(self, rnd, seat, final=False, **kw):
        return _record(self, "declare", rnd, seat, final,
                       lambda: base.decide_declare(self, rnd, seat, final=final, **kw))

    def decide_bury(self, rnd, seat):
        return _record(self, "bury", rnd, seat, False, lambda: base.decide_bury(self, rnd, seat))

    def decide_play(self, rnd, seat):
        return _record(self, "play", rnd, seat, False, lambda: base.decide_play(self, rnd, seat))

    bot.__class__ = type("Recording" + base.__name__, (base,), {
        "decide_declare": decide_declare, "decide_bury": decide_bury,
        "decide_play": decide_play})
    bot._rec_depth = 0
    return bot


async def _inline_to_thread(fn, /, *args, **kwargs):
    return fn(*args, **kwargs)


def record_session(seed: int, rounds: int, config: dict, make_room_bot) -> tuple[list, list]:
    """``(records, frames)`` of one seeded solo game whose room bot is
    ``make_room_bot()``."""
    gen = importlib.import_module("gen_offline_server_fixtures")
    server = gen.server
    records: list = []
    p = _Patches()
    try:
        _install_round_log(p)
        p.set(server, "make_bot", lambda name, **kw: recording_bot(make_room_bot(), records))
        p.set(asyncio, "to_thread", _inline_to_thread)
        frames = gen.play_session(seed, rounds, config)
    finally:
        p.undo()
    return records, frames


def served_bot_factory(payload_dir: str, out_dir: str, seed: int, overrides: dict | None = None):
    """A factory for the served bot built from the payload's fly.toml, with
    that environment installed in this process (as ``offline_bot.init`` does).
    ``overrides`` (a value of "" removes the key) changes the environment and
    the bot's registry name with it."""
    from shengji.eval import served_config
    fly, env = offline_bot.served_env(payload_dir, out_dir)
    os.makedirs(env["SHENGJI_LOG_DIR"], exist_ok=True)
    offline_bot.verify_weights(env)
    for key, value in (overrides or {}).items():
        if value == "":
            env.pop(key, None)
            os.environ.pop(key, None)
        else:
            env[key] = value
    if overrides:
        env["SHENGJI_BOT"] = served_config.registry_name(env)
    os.environ.update(env)
    name = env["SHENGJI_BOT"]

    def make():
        return served_config.build_served_bot(env, seed=seed, expected_name=name)[1]

    make.bot_name = name
    return make

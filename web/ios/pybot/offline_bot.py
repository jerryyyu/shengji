"""The app's offline bot: the served pv-search bot, deciding for the offline game.

The iOS app bundles this module with the unmodified ``shengji`` package, the
``fly.toml`` the release was cut from and its four weight files.  The offline
game itself runs in the web page (``web/src/offline/server``); for a bot seat's
turn the page sends a decision request through the native ``ShengjiBot``
plugin, and this module answers it with the served bot.

A request carries what the game server holds for the round, so the bot is
handed the same ``Round`` the server hands it:

* ``deck``: the 108 card codes in deal order (the TypeScript and Python
  engines share card codes and deal order: ``Round`` deals ``deck[i]`` to seat
  ``i % 4`` and the last eight are the kitty);
* ``trump_rank`` and ``banker`` (``None`` on a game's first round), the
  arguments ``Game.start_round`` gives ``Round``;
* ``log``: every committed action of the round, in order: ``["deal", n]``
  (deal until ``n`` cards are out), ``["declare", seat, cards]``,
  ``["pass", seat]``, ``["finalize"]``, ``["bury", seat, cards]`` and
  ``["play", seat, cards]`` with the cards as submitted (the engine records a
  failed throw's forced part itself);
* ``kind`` (``declare``, ``bury`` or ``play``), ``seat`` and, for a declare,
  ``final``.

The bot object lives for the whole session, as the server's room bot lives for
the room: its RNG and its public-notice ledger carry over between decisions and
rounds.  As on the server, every committed play is shown to it
(``observe_public``), a bury or play is searched on a copy of the bot and the
round that then becomes the bot, and a declare runs on the bot inline unless
the bot's own declare gate sends it to a copied search.  The round is rebuilt
by replaying the log, and replay is incremental: a request whose log extends
the previous one applies only the new actions.

Calls from the native plugin (JSON strings in and out): ``call(name, args)``
with ``init(payload_dir, out_dir, seed)`` and ``decide(request_json)``.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import time
import tomllib

MODEL_PREFIX = "/data/models/"
NATIVE_MODULES = ("shengji.engine._fast", "shengji.ai._cwv_math",
                  "shengji.ai._endgame_fast", "shengji.train._pv_fast")
LOG_KINDS = ("deal", "declare", "pass", "finalize", "bury", "play")

_STATE: dict = {}


class RequestError(ValueError):
    """A request that does not describe a live decision for its seat."""


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def served_env(payload_dir: str, out_dir: str) -> tuple[dict, dict]:
    """``(fly, env)``: fly.toml's ``[env]`` as written, and the same with every
    ``/data/models/<file>`` mapped to the bundled copy and the write paths
    under ``out_dir``.  Nothing else differs from the served environment."""
    with open(os.path.join(payload_dir, "fly.toml"), "rb") as f:
        fly = {str(k): str(v) for k, v in tomllib.load(f)["env"].items()}
    models = os.path.join(payload_dir, "models")
    env = {k: (os.path.join(models, v[len(MODEL_PREFIX):]) if v.startswith(MODEL_PREFIX) else v)
           for k, v in fly.items()}
    env["SHENGJI_LOG_DIR"] = os.path.join(out_dir, "logs")
    env["SHENGJI_DATA_DIR"] = out_dir
    return fly, env


def verify_weights(env: dict) -> dict:
    """Every bundled weight file must hash to the sha256 fly.toml pins for it."""
    pins = {}
    for key, value in env.items():
        if key.endswith("_CKPT") and value.endswith(".npz"):
            got = _sha256(value)
            pins[os.path.basename(value)] = got
            want = env.get(key[:-len("_CKPT")] + "_SHA256")
            if want and want != got:
                raise RuntimeError(f"{key}: {value} sha256 {got} != {want}")
            # the shortlist checkpoint has no pin of its own: it is the CWV prior file
            if key == "SHENGJI_CWV_SHORTLIST_CKPT" and got != env["SHENGJI_CWV_PRIOR_SHA256"]:
                raise RuntimeError("shortlist checkpoint is not the pinned CWV prior file")
    return pins


def init(payload_dir: str, out_dir: str, seed: int = 13) -> str:
    """Build the served bot from the bundled fly.toml; returns its identity."""
    t0 = time.perf_counter()
    os.makedirs(out_dir, exist_ok=True)
    fly, env = served_env(payload_dir, out_dir)
    os.makedirs(env["SHENGJI_LOG_DIR"], exist_ok=True)
    pins = verify_weights(env)
    t_hash = time.perf_counter()
    # The server process runs with fly.toml's [env] in its environment; so does this one.
    os.environ.update(env)
    import numpy
    from shengji.eval import served_config
    from shengji.engine import fast as engine_fast
    t_import = time.perf_counter()
    name, bot = served_config.build_served_bot(env, seed=int(seed), expected_name=fly["SHENGJI_BOT"])
    t_build = time.perf_counter()
    if "torch" in sys.modules:
        raise RuntimeError("torch was imported on the served bot path")
    start_session(bot)
    ident = {
        "bot": name,
        "matches_fly_toml": name == fly["SHENGJI_BOT"],
        "seed": int(seed),
        "worlds": int(env["SHENGJI_PV_WORLDS"]),
        "fast_engine": engine_fast.HAVE_FAST,
        "native_loaded": sorted(m for m in NATIVE_MODULES if m in sys.modules),
        "weights_sha256": pins,
        "python": sys.version.split()[0],
        "numpy": numpy.__version__,
        "seconds": {"hash_weights": round(t_hash - t0, 3),
                    "import": round(t_import - t_hash, 3),
                    "build_bot": round(t_build - t_import, 3),
                    "total": round(t_build - t0, 3)},
    }
    print(f"[pybot] init {json.dumps(ident)}", flush=True)
    return json.dumps(ident)


def start_session(bot) -> None:
    """Make ``bot`` the session's bot (``init`` does this; tests pass their own)."""
    _STATE.clear()
    _STATE["bot"] = bot
    _STATE["decisions"] = 0


def clock_flags(bot, kind: str) -> dict:
    """What the wall clock did to the bot's last ``kind`` decision: ``fallback``
    (the serving budget expired or the search failed, and the heuristic move
    was played), ``exact_lead`` (the exact-lead stage's status when it did not
    complete) and ``leaf_deadline`` (the greedy-finish deadline fired).  Empty
    for a decision the clock did not touch."""
    attr = {"bury": "last_bury_record", "play": "last_decision_record"}.get(kind)
    record = getattr(bot, attr, None) if attr else None
    if not isinstance(record, dict):
        return {}
    flags = {}
    if record.get("work_complete") is False or str(record.get("schema", "")).endswith("fallback-v1"):
        flags["fallback"] = record.get("reason") or "fallback"
    status = record.get("exact_lead_status")
    if status not in (None, "ineligible", "complete", "single"):
        flags["exact_lead"] = status
    if record.get("leaf_greedy_deadline_fired_any", record.get("leaf_greedy_deadline_fired")):
        flags["leaf_deadline"] = True
    return flags


# Replay

class _DeckOrder:
    """The ``rng`` argument of ``Round``: its one shuffle lays out ``deck``."""

    def __init__(self, deck: list[str]):
        self.deck = deck

    def shuffle(self, items: list) -> None:
        if sorted(items) != sorted(self.deck):
            raise RequestError("deck is not a permutation of the 108-card deck")
        items[:] = self.deck


def _cards(value) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(c, str) for c in value):
        raise RequestError(f"cards must be a list of card codes, got {value!r}")
    return list(value)


def _seat(value) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < 4:
        raise RequestError(f"bad seat {value!r}")
    return value


def _apply(rnd, entry, bot) -> None:
    """One committed action, applied as the server applies it."""
    if not isinstance(entry, list) or not entry or entry[0] not in LOG_KINDS:
        raise RequestError(f"bad log entry {entry!r}")
    kind = entry[0]
    if kind == "deal":
        n = entry[1]
        if not isinstance(n, int) or n < rnd._deal_pos or n > 100:
            raise RequestError(f"bad deal position {n!r}")
        while rnd._deal_pos < n:
            rnd.deal_next()
    elif kind == "declare":
        rnd.declare(_seat(entry[1]), _cards(entry[2]))
    elif kind == "pass":
        seat = _seat(entry[1])
        if rnd.phase == "declare":
            rnd.passed.add(seat)
        else:
            raise RequestError("a pass outside the declare window")
    elif kind == "finalize":
        rnd.finalize_declare()
    elif kind == "bury":
        rnd.bury(_seat(entry[1]), _cards(entry[2]))
    else:
        rnd.play(_seat(entry[1]), _cards(entry[2]))
        # the server shows the committed bot every committed play's public notice
        observe = getattr(bot, "observe_public", None)
        if observe is not None:
            observe(rnd)


def _round_for(req: dict, bot):
    """The live round the request describes, reusing the cached replay when the
    request's log extends it."""
    from shengji.engine.round import Round
    deck = _cards(req.get("deck"))
    if len(deck) != 108:
        raise RequestError("deck must hold 108 cards")
    trump_rank, banker = req.get("trump_rank"), req.get("banker")
    if banker is not None:
        banker = _seat(banker)
    log = req.get("log")
    if not isinstance(log, list):
        raise RequestError("log must be a list")
    key = (tuple(deck), trump_rank, banker)
    rnd, start = None, 0
    cached = _STATE.get("replay")
    if cached is not None and cached["key"] == key:
        done = cached["log"]
        k = len(done)
        if log[:k] == done:
            rnd, start = cached["round"], k
        elif (k and done[-1][0] == "deal" and log[:k - 1] == done[:-1] and len(log) >= k
              and isinstance(log[k - 1], list) and log[k - 1][:1] == ["deal"]):
            # the last deal entry grew: dealing on to its new position is the same replay
            rnd, start = cached["round"], k - 1
    if rnd is None:
        rnd = Round(trump_rank, banker, _DeckOrder(deck))
    try:
        for entry in log[start:]:
            _apply(rnd, entry, bot)
    except Exception:
        _STATE.pop("replay", None)
        raise
    _STATE["replay"] = {"key": key, "round": rnd, "log": copy.deepcopy(log)}
    return rnd


def decide(request_json: str) -> str:
    """The bot's action for the request's seat: ``{"cards": [...] | null, "seconds": s}``."""
    req = json.loads(request_json)
    bot = _STATE.get("bot")
    if bot is None:
        raise RuntimeError("the bot is not built yet")
    kind, seat = req.get("kind"), _seat(req.get("seat"))
    t0 = time.perf_counter()
    rnd = _round_for(req, bot)
    t_replay = time.perf_counter()
    if kind == "declare":
        if rnd.phase not in ("deal", "declare"):
            raise RequestError(f"declare asked during {rnd.phase}")
        final = bool(req.get("final", False))
        value_declare = getattr(bot, "value_declare", False)
        gate = getattr(bot, "declare_gate", None)
        gated = value_declare and (not callable(gate) or gate(rnd, seat, final)[1])
        if gated:
            # the server searches a gated declare on copies, then keeps the copied bot
            bot_copy = copy.deepcopy(bot)
            cards = bot_copy.decide_declare(copy.deepcopy(rnd), seat, final=final)
            _STATE["bot"] = bot_copy
        else:
            cards = bot.decide_declare(rnd, seat, final=final)
        cards = list(cards) if cards else None
    elif kind in ("bury", "play"):
        if rnd.phase != kind or rnd.turn != seat:
            raise RequestError(f"{kind} asked for seat {seat} during {rnd.phase}, turn {rnd.turn}")
        # the server's turn snapshot: the search runs on copies and the copied bot is kept
        bot_copy, round_copy = copy.deepcopy(bot), copy.deepcopy(rnd)
        if kind == "bury":
            cards = list(bot_copy.decide_bury(round_copy, seat))
        else:
            cards = list(bot_copy.decide_play(round_copy, seat))
        _STATE["bot"] = bot_copy
    else:
        raise RequestError(f"unknown decision kind {kind!r}")
    t_end = time.perf_counter()
    _STATE["decisions"] += 1
    out = {"cards": cards, "seconds": round(t_end - t0, 4),
           "replay_seconds": round(t_replay - t0, 4), "n": _STATE["decisions"]}
    out.update(clock_flags(_STATE["bot"], kind))
    return json.dumps(out)


def call(name: str, args_json: str) -> str:
    """The native bridge's single entry: ``name(*json.loads(args_json))``."""
    if name not in ("init", "decide"):
        raise ValueError(f"unknown pybot call {name!r}")
    return globals()[name](*json.loads(args_json))

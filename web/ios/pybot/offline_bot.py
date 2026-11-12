"""On-device entry point for the served pv-search bot (iOS spike).

The app bundle carries ``payload/``: the unmodified ``shengji`` package, the
``fly.toml`` it was cut from and the four release weight files under
``models/``.  The bot is built exactly as ``shengji.eval.served_config`` builds
the served bot from ``fly.toml``: every ``/data/models/<file>`` value is mapped
to the bundled copy, and the write paths point into the app's Documents.

API (the Swift plugin calls these with JSON strings):

* ``init(payload_dir, out_dir, worlds=None, fast=False)`` -> identity JSON;
* ``decide(request_json)`` -> response JSON (Python-owned offline session:
  ``new_round``, ``state``, ``act`` for a human move, ``bot_step``);
* ``bench(rounds, seed)`` -> timing JSON: N full rounds, all four seats this
  bot, every decision timed by phase.
"""
from __future__ import annotations

import gc
import hashlib
import json
import os
import platform
import random
import resource
import statistics
import sys
import time
import tomllib

_STATE: dict = {}

MODEL_PREFIX = "/data/models/"


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _peak_rss_mb() -> float:
    # ru_maxrss is bytes on Darwin (macOS and iOS)
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1 << 20)


def _log(msg: str) -> None:
    line = f"[pybot {time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    out = _STATE.get("out_dir")
    if out:
        with open(os.path.join(out, "pybot_log.txt"), "a") as f:
            f.write(line + "\n")


def build_env(payload_dir: str, out_dir: str, worlds: int | None, fast: bool) -> dict:
    """fly.toml's [env], volume paths mapped into the bundle; worlds and the
    compiled engine switch are the spike's only overrides."""
    with open(os.path.join(payload_dir, "fly.toml"), "rb") as f:
        fly = {str(k): str(v) for k, v in tomllib.load(f)["env"].items()}
    models = os.path.join(payload_dir, "models")
    env = {}
    for k, v in fly.items():
        if v.startswith(MODEL_PREFIX):
            v = os.path.join(models, v[len(MODEL_PREFIX):])
        env[k] = v
    env["SHENGJI_LOG_DIR"] = os.path.join(out_dir, "logs")
    env["SHENGJI_DATA_DIR"] = out_dir
    if not fast:
        env.pop("SHENGJI_FAST", None)
    if worlds is not None:
        env["SHENGJI_PV_WORLDS"] = str(worlds)
    return fly, env


NATIVE_MODULES = ("shengji.engine._fast", "shengji.ai._cwv_math",
                  "shengji.ai._endgame_fast", "shengji.train._pv_fast")


class _NoNative:
    """Pure mode: the compiled extensions are used whenever importable, so the
    pure-Python engine is measured by refusing their import."""
    def find_spec(self, name, path=None, target=None):
        if name in NATIVE_MODULES:
            raise ImportError(f"{name} blocked (pure-Python mode)")
        return None


def _block_native():
    if any(name in sys.modules for name in NATIVE_MODULES):
        raise RuntimeError("a native module is already loaded; restart for pure mode")
    if not any(isinstance(f, _NoNative) for f in sys.meta_path):
        sys.meta_path.insert(0, _NoNative())


def init(payload_dir: str, out_dir: str, worlds=None, fast=False) -> str:
    t0 = time.perf_counter()
    os.makedirs(out_dir, exist_ok=True)
    _STATE["out_dir"] = out_dir
    worlds = int(worlds) if worlds not in (None, "", 0) else None
    fly, env = build_env(payload_dir, out_dir, worlds, bool(fast))
    os.makedirs(env["SHENGJI_LOG_DIR"], exist_ok=True)
    if fast:
        os.environ["SHENGJI_FAST"] = "1"
    else:
        os.environ.pop("SHENGJI_FAST", None)
        _block_native()

    # pins: every bundled weight file must match the sha256 fly.toml names for it
    pins = {}
    for key, value in env.items():
        if key.endswith("_CKPT") and value.endswith(".npz"):
            sha_key = key[:-len("_CKPT")] + "_SHA256"
            got = _sha256(value)
            pins[os.path.basename(value)] = got
            want = env.get(sha_key)
            if want and want != got:
                raise RuntimeError(f"{key}: {value} sha256 {got} != {want}")
            # the shortlist checkpoint has no own pin; it is the CWV prior file
            if key == "SHENGJI_CWV_SHORTLIST_CKPT" and got != env["SHENGJI_CWV_PRIOR_SHA256"]:
                raise RuntimeError("shortlist checkpoint is not the pinned CWV prior file")
    t_hash = time.perf_counter()

    import numpy
    import shengji  # noqa: F401  (activates the compiled engine when SHENGJI_FAST=1)
    from shengji.eval import served_config
    t_import = time.perf_counter()

    if worlds is not None:
        env["SHENGJI_BOT"] = served_config.registry_name(env)
    name, bot = served_config.build_served_bot(env, seed=13)
    t_build = time.perf_counter()

    from shengji.engine import fast as engine_fast
    ident = {
        "bot": name,
        "fly_toml_bot": fly["SHENGJI_BOT"],
        "matches_fly_toml": name == fly["SHENGJI_BOT"],
        "worlds": int(env["SHENGJI_PV_WORLDS"]),
        "fast_engine_active": bool(fast) and engine_fast.HAVE_FAST,
        "have_fast_ext": engine_fast.HAVE_FAST,
        "native_loaded": sorted(m for m in NATIVE_MODULES if m in sys.modules),
        "weights_sha256": pins,
        "python": sys.version,
        "numpy": numpy.__version__,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "torch_imported": "torch" in sys.modules,
        "seconds": {"hash_weights": round(t_hash - t0, 3),
                    "import_shengji": round(t_import - t_hash, 3),
                    "build_bot": round(t_build - t_import, 3),
                    "total_init": round(t_build - t0, 3)},
        "peak_rss_mb_after_init": round(_peak_rss_mb(), 1),
    }
    if ident["torch_imported"]:
        raise RuntimeError("torch was imported on the served bot path")
    _STATE.update(bot=bot, ident=ident, env=env)
    _log(f"init {json.dumps(ident)}")
    return json.dumps(ident)


# Session API

def _public_state(rnd, seat=None) -> dict:
    d = {"phase": rnd.phase, "turn": getattr(rnd, "turn", None), "banker": rnd.banker,
         "trump_rank": rnd.trump_rank, "trump_suit": getattr(rnd, "trump_suit", None),
         "attacker_points": getattr(rnd, "attacker_points", 0)}
    if seat is not None:
        d["hand"] = sorted(rnd.hands[seat])
    return d


def decide(request_json: str) -> str:
    """A Python-owned offline round: the engine here is authoritative, the
    caller sends the human seat's moves and asks for bot moves."""
    req = json.loads(request_json)
    op = req.get("op")
    bot = _STATE["bot"]
    if op == "new_round":
        from shengji.engine.game import Game
        game = Game(random.Random(int(req.get("seed", 0))))
        rnd = game.start_round()
        while rnd.phase == "deal":
            seat, _, _ = rnd.deal_next()
            cards = bot.decide_declare(rnd, seat)
            if cards:
                rnd.declare(seat, cards)
        rnd.finalize_declare()
        _STATE["game"] = game
        human = int(req.get("human_seat", 0))
        _STATE["human"] = human
        if rnd.banker != human:
            rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
        return json.dumps(_public_state(rnd, human))
    rnd = _STATE["game"].round
    human = _STATE["human"]
    if op == "state":
        return json.dumps(_public_state(rnd, human))
    if op == "act":
        cards = list(req["cards"])
        if rnd.phase == "bury":
            rnd.bury(human, cards)
        else:
            rnd.play(human, cards)
        return json.dumps(_public_state(rnd, human))
    if op == "bot_step":
        seat = rnd.turn
        t = time.perf_counter()
        cards = bot.decide_play(rnd, seat)
        dt = time.perf_counter() - t
        rnd.play(seat, cards)
        return json.dumps({"seat": seat, "cards": cards, "seconds": round(dt, 3),
                           **_public_state(rnd, human)})
    raise ValueError(f"unknown op {op!r}")


# Benchmark

def _summary(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    s = sorted(xs)
    def q(p):
        return s[min(len(s) - 1, int(round(p * (len(s) - 1))))]
    return {"n": len(s), "mean": round(statistics.fmean(s), 4), "p50": round(q(0.5), 4),
            "p95": round(q(0.95), 4), "max": round(s[-1], 4), "total": round(sum(s), 2)}


def bench(rounds: int = 3, seed: int = 20261112, tag: str = "") -> str:
    from shengji.engine.game import Game
    from shengji.ai.env import observe_committed_play
    bot = _STATE["bot"]
    policies = [bot] * 4
    times = {"declare": [], "declare_final": [], "bury": [], "play": []}
    per_round = []
    from collections import Counter
    fallbacks = Counter()
    deadlines = Counter()
    import copy
    copy_s = []
    t_all = time.perf_counter()
    for r in range(int(rounds)):
        game = Game(random.Random(int(seed) + r))
        rnd = game.start_round()
        tr = time.perf_counter()
        dec = []
        while rnd.phase == "deal":
            seat, _, _ = rnd.deal_next()
            t = time.perf_counter()
            cards = policies[seat].decide_declare(rnd, seat)
            dec.append(time.perf_counter() - t)
            if cards:
                rnd.declare(seat, cards)
        times["declare"].extend(dec)
        for seat in range(4):
            t = time.perf_counter()
            cards = policies[seat].decide_declare(rnd, seat, final=True)
            times["declare_final"].append(time.perf_counter() - t)
            if cards:
                rnd.declare(seat, cards)
        rnd.finalize_declare()
        t = time.perf_counter()
        buried = policies[rnd.banker].decide_bury(rnd, rnd.banker)
        tb = time.perf_counter() - t
        rec = getattr(bot, "last_bury_record", None)
        if isinstance(rec, dict) and rec.get("work_complete") is False:
            fallbacks["bury_" + str(rec.get("reason"))] += 1
        times["bury"].append(tb)
        rnd.bury(rnd.banker, buried)
        plays = []
        while rnd.phase == "play":
            seat = rnd.turn
            t = time.perf_counter()
            cards = policies[seat].decide_play(rnd, seat)
            plays.append(time.perf_counter() - t)
            rec = getattr(bot, "last_decision_record", None)
            if isinstance(rec, dict) and rec.get("work_complete") is False:
                fallbacks["play_" + str(rec.get("reason"))] += 1
            if isinstance(rec, dict):
                # served-search internal deadlines (fire on Fly too; counted to compare rates)
                if rec.get("leaf_greedy_deadline_fired_any", rec.get("leaf_greedy_deadline_fired")):
                    deadlines["leaf_greedy_deadline_fired"] += 1
                status = rec.get("exact_lead_status")
                if status not in (None, "ineligible"):
                    deadlines["exact_lead_" + str(status)] += 1
            rnd.play(seat, cards)
            observe_committed_play(rnd, policies)
        times["play"].extend(plays)
        # the server deep-copies the room bot and the round for every bot turn
        t = time.perf_counter()
        copy.deepcopy(bot)
        copy.deepcopy(rnd)
        copy_s.append(time.perf_counter() - t)
        row = {"round": r, "seed": int(seed) + r, "declare_calls": len(dec),
               "declare_total_s": round(sum(dec), 2), "declare_max_s": round(max(dec), 3),
               "bury_s": round(tb, 3), "plays": len(plays),
               "play_mean_s": round(statistics.fmean(plays), 3),
               "play_max_s": round(max(plays), 3),
               "round_wall_s": round(time.perf_counter() - tr, 1),
               "attacker_points": rnd.attacker_points,
               "fallbacks_so_far": dict(fallbacks),
               "deadlines_so_far": dict(deadlines),
               "peak_rss_mb": round(_peak_rss_mb(), 1)}
        per_round.append(row)
        _log(f"bench{tag} round {json.dumps(row)}")
        gc.collect()
    out = {"tag": tag, "ident": _STATE["ident"], "rounds": per_round,
           "phases": {k: _summary(v) for k, v in times.items()},
           "declare_per_round_total": _summary([r["declare_total_s"] for r in per_round]),
           "fallbacks": dict(fallbacks),
           "deadlines": dict(deadlines),
           "native_loaded_after": sorted(m for m in NATIVE_MODULES if m in sys.modules),
           "server_turn_deepcopy_s": _summary(copy_s),
           "wall_s": round(time.perf_counter() - t_all, 1),
           "peak_rss_mb": round(_peak_rss_mb(), 1)}
    path = os.path.join(_STATE["out_dir"], f"bench{tag}.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
    _log(f"bench{tag} done -> {path}")
    return json.dumps(out)


if __name__ == "__main__":  # host check: python offline_bot.py PAYLOAD OUT [worlds] [rounds] [fast]
    a = sys.argv[1:]
    print(init(a[0], a[1], int(a[2]) if len(a) > 2 and a[2] != "0" else None,
               len(a) > 4 and a[4] == "1"))
    print(json.dumps(json.loads(bench(int(a[3]) if len(a) > 3 else 1,
                                      tag=f"-host-w{a[2] if len(a) > 2 else 64}"))["phases"], indent=1))


def call(name: str, args_json: str) -> str:
    """The native bridge's single entry: ``name(*json.loads(args_json))``."""
    if name not in ("init", "decide", "bench"):
        raise ValueError(f"unknown pybot call {name!r}")
    return globals()[name](*json.loads(args_json))

#!/usr/bin/env python3
"""Parity of the served unified registry entry (`shengji.train.unified_serving`) against the duel
adapter that played the unified-model screens (``ut_adapter.py``, run unchanged from its kit
directory on the tree it ran on), and flag-off identity of the served bot across trees.

    unified_adapter_parity.py package --b1a B1A.npz --out DIR      # stand-in pair, trunk = B1a perturbed
    unified_adapter_parity.py states  --server TREE/server --rounds N --seed0 S --out states.pkl
    unified_adapter_parity.py decide  --side adapter|registry|served --server TREE/server \
        --states states.pkl --unified U.npz --belief UB.npz --out side.jsonl [--limit K]
    unified_adapter_parity.py compare A.jsonl B.jsonl

Every subcommand takes ``--pkg-dir`` (the local copies of fly.toml's ``/data/models`` packages) and
``decide --side adapter`` takes ``--kit`` (the directory holding ``ut_adapter.py``,
``x1a_adapter.py`` and ``exploit_duel_s61.py``).  Each process imports ``shengji`` from ``--server``
only, so the adapter can run on the tree it duelled on and the registry on this one.

``states`` plays N full rounds with release 52 as served (fly.toml, one bot per seat) and keeps a
copy of every play-decision state.  ``decide`` builds, for each state, a fresh bot with seed
``1000003 * i + 7`` and records ``r50_flag_positions.decision`` (cards, world digest, record less
the run's measurements) plus the slot counters.  ``adapter`` builds that bot with the DEV adapter's
own ``variant_factory`` over the screen recipe's ALLS exploiter words (local paths substituted);
``registry`` builds it with ``registry.make_bot`` on the name the environment registers.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import pickle
import sys
from pathlib import Path

#: fly.toml's /data/models packages, mapped to ``--pkg-dir`` by `set_pkg_dir`
VOLUME_PACKAGES = ("g3a-e04-f4f4127e.npz", "p0-ft1-1fa201b2.npz", "b1a-028131a0.npz", "js-m1-0d17fd03.npz",
                   "smv3out-491ee4bf.npz", "s58-e6-42444515.npz", "s17long-e2-763b5e05.npz")
PKG = Path(".")
MAP: dict = {}
HERE = Path(__file__).resolve()
COUNTERS = ("unified_prior_calls", "unified_shared_hits", "unified_shared_misses", "unified_value_rows",
            "unified_value_other", "unified_reply_rows", "unified_reply_served", "unified_trunk_forwards",
            "unified_trunk_shared")


def set_pkg_dir(path):
    global PKG
    PKG = Path(path).resolve()
    MAP.clear()
    MAP.update({f"/data/models/{n}": str(PKG / n) for n in VOLUME_PACKAGES})


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def use_tree(server):
    server = str(Path(server).resolve())
    sys.path[:0] = [server, server + "/tests"]
    if os.environ.get("SHENGJI_FAST") == "1":
        from shengji.engine import fast
        assert fast.activate(), "compiled engine missing"
    import shengji
    assert str(Path(shengji.__file__).resolve()).startswith(server), shengji.__file__


def cmd_package(a):
    sys.path[:0] = [str(HERE.parents[1]), str(HERE.parent)]
    import numpy as np
    from shengji.ai import belief_numpy as bn
    from shengji.ai import unified_numpy as un
    from shengji.ai import unified_readout_numpy as rn
    from unified_serving_check import STAND_IN_HEADS, STAND_IN_READOUT

    belief = bn.load_belief_numpy(a.b1a)
    config = {"trunk": dict(belief.config), "heads": dict(STAND_IN_HEADS), "readout": dict(STAND_IN_READOUT)}
    rng = np.random.default_rng(20261117)
    trunk = {k: (v * (1.0 + 0.05 * rng.standard_normal(v.shape))).astype(np.float32) for k, v in belief.w.items()}

    def weights(shapes):
        out = {}
        for key, shape in shapes.items():
            if len(shape) == 1:
                out[key] = np.full(shape, 0.0 if key.endswith("bias") else 1.0, np.float32)
            else:
                out[key] = (rng.standard_normal(shape) / np.sqrt(shape[-1])).astype(np.float32)
        return out
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    heads, readout = weights(un.head_shapes(config)), weights(rn.readout_shapes(config))
    u_sha = rn.save_package(out / "ut-standin.npz", config, trunk, heads, readout,
                            {"temperature": belief.temperature, "stand_in_from": belief.package_sha256})
    b_sha = rn.belief_package(rn.load_unified_readout_numpy(out / "ut-standin.npz", u_sha), out / "ut-standin-belief.npz")
    n = lambda d: int(sum(np.prod(v.shape) for v in d.values()))
    print(json.dumps({"unified": str(out / "ut-standin.npz"), "unified_sha256": u_sha,
                      "belief": str(out / "ut-standin-belief.npz"), "belief_sha256": b_sha,
                      "params": {"trunk": n(trunk), "heads": n(heads), "readout": n(readout)}}, indent=1))


def served_env_for(server):
    from shengji.eval import served_config
    env = served_config.served_env(fly_toml=str(Path(server).parent / "fly.toml"), mappings=MAP)
    for key in (*served_config.WRITE_KEYS, "SHENGJI_FAST"):
        env.pop(key, None)
    return env


def cmd_states(a):
    use_tree(a.server)
    import random
    from shengji.ai import registry
    from shengji.ai.env import observe_committed_play, prepare_round
    from shengji.engine.game import Game
    from shengji.eval import served_config
    env = served_env_for(a.server)
    with served_config.process_env(env):
        registry._register_pv_search_from_env()
        bots = [registry.make_bot(env["SHENGJI_BOT"], seed=a.seed0 * 10 + s) for s in range(4)]
    states = []
    for r in range(a.rounds):
        game = Game(random.Random(a.seed0 + r))
        rnd = prepare_round(game, bots)
        while rnd.phase == "play":
            states.append((a.seed0 + r, copy.deepcopy(rnd)))
            cards = bots[rnd.turn].decide_play(rnd, rnd.turn)
            rnd.play(rnd.turn, cards)
            observe_committed_play(rnd, bots)
        game.finish_round()
        print("round", a.seed0 + r, "states", len(states), flush=True)
    with open(a.out, "xb") as fh:
        pickle.dump({"name": env["SHENGJI_BOT"], "states": states}, fh)


def cmd_decide(a):
    use_tree(a.server)
    u_sha, b_sha = sha(a.unified), sha(a.belief)
    if a.side == "adapter":
        os.environ.update({"FIND_GAPS_SERVER": str(Path(a.server).resolve()), "FIND_GAPS_PKG": str(PKG / "g3a-e04-f4f4127e.npz"),
                           "FIND_GAPS_PATH_MAP": ";".join(f"{k}={v}" for k, v in MAP.items()),
                           "UT_PKG": a.unified, "UT_SHA256": u_sha})
        import importlib.util
        spec = importlib.util.spec_from_file_location("ut_adapter", Path(a.kit) / "ut_adapter.py")
        UA = importlib.util.module_from_spec(spec)
        sys.modules["ut_adapter"] = UA
        spec.loader.exec_module(UA)
        words = (("SHENGJI_PV_CKPT", MAP["/data/models/g3a-e04-f4f4127e.npz"]),
                 ("SHENGJI_PV_SHA256", "f4f4127ec0c8821b4aa07f7d651a4258c696f97a874707da2c78ad26c0c9b9fd"),
                 ("SHENGJI_PV_PRIOR_CKPT", MAP["/data/models/p0-ft1-1fa201b2.npz"]),
                 ("SHENGJI_PV_PRIOR_SHA256", "1fa201b288e78b3072979f55030aae44711ee214b50a14e155d0bbe11b6bb1bf"),
                 ("SHENGJI_PV_BELIEF_CKPT", a.belief), ("SHENGJI_PV_BELIEF_SHA256", b_sha),
                 ("SHENGJI_PV_BURY_BELIEF_WORLDS", "1"), ("SHENGJI_PV_LEAD_CONFIRM", "0"),
                 ("UT_PRIOR", "shared"), ("UT_VALUE", "readout"), ("UT_REPLY", "readout"))
        name, make = UA.variant_factory(words)
        build = lambda seed: make(seed)
        binding = {"ut_adapter.py": sha(Path(a.kit) / "ut_adapter.py"), "x1a_adapter.py": sha(Path(a.kit) / "x1a_adapter.py"),
                   "exploit_duel_s61.py": sha(Path(a.kit) / "exploit_duel_s61.py")}
    elif a.side == "served":
        from shengji.ai import registry
        from shengji.eval import served_config
        env = served_env_for(a.server)
        name = env["SHENGJI_BOT"]
        ctx = served_config.process_env(env)
        ctx.__enter__()
        registry._register_pv_search_from_env()
        build = lambda seed: registry.make_bot(name, seed=seed)
        binding = {"unified_modules": []}
    else:
        from shengji.ai import registry
        from shengji.eval import served_config
        env = {**served_env_for(a.server), "SHENGJI_PV_BELIEF_CKPT": a.belief, "SHENGJI_PV_BELIEF_SHA256": b_sha,
               "SHENGJI_PV_UNIFIED_CKPT": a.unified, "SHENGJI_PV_UNIFIED_SHA256": u_sha}
        env["SHENGJI_BOT"] = name = served_config.registry_name(env)
        ctx = served_config.process_env(env)
        ctx.__enter__()
        registry._register_pv_search_from_env()
        build = lambda seed: registry.make_bot(name, seed=seed)
        binding = {}
    import r50_flag_positions as P
    with open(a.states, "rb") as fh:
        states = pickle.load(fh)["states"]
    if a.limit:
        states = states[:a.limit]
    with open(a.out, "x") as out:
        out.write(json.dumps({"kind": "header", "side": a.side, "name": name, "unified_sha256": u_sha,
                              "belief_sha256": b_sha, "server": str(Path(a.server).resolve()), "binding": binding,
                              "engine": "compiled" if os.environ.get("SHENGJI_FAST") == "1" else "pure",
                              "states": len(states)}, sort_keys=True) + "\n")
        for i, (deal, rnd) in enumerate(states):
            bot = build(1000003 * i + 7)
            before = [getattr(bot, c, 0) for c in COUNTERS]
            got = P.decision(P.lift(bot), copy.deepcopy(rnd))
            got["counters"] = [getattr(bot, c, 0) - b for c, b in zip(COUNTERS, before)]
            account = got["record"].pop("unified", None)
            if a.side == "registry":
                assert account is not None and account["shared"] == got["counters"][1], account
            out.write(json.dumps({"kind": "decision", "i": i, "deal": deal, "trick": len(rnd.history) + 1,
                                  **got}, sort_keys=True, default=list) + "\n")
            out.flush()
        if a.side == "served":
            loaded = [m for m in sys.modules if m.startswith("shengji.") and "unified" in m]
            out.write(json.dumps({"kind": "footer", "unified_modules_loaded": loaded}) + "\n")


def cmd_compare(a):
    rows = []
    for path in (a.a, a.b):
        lines = [json.loads(x) for x in open(path)]
        rows.append((lines[0], {r["i"]: r for r in lines[1:] if r["kind"] == "decision"}))
    (ha, ra), (hb, rb) = rows
    assert ha["name"] == hb["name"], (ha["name"], hb["name"])
    common = sorted(set(ra) & set(rb))
    diff = [i for i in common if ra[i] != rb[i]]
    tot = [sum(ra[i]["counters"][k] for i in common) for k in range(len(COUNTERS))]
    print(json.dumps({"name": ha["name"], "engines": [ha["engine"], hb["engine"]], "compared": len(common),
                      "mismatches": len(diff), "first_mismatches": diff[:10],
                      "rounds": len({ra[i]["deal"] for i in common}), "counters": dict(zip(COUNTERS, tot)),
                      "files": {p: sha(p) for p in (a.a, a.b)}}, indent=1))
    return 1 if diff or not common else 0


def main():
    p = argparse.ArgumentParser()
    s = p.add_subparsers(dest="cmd", required=True)
    x = s.add_parser("package"); x.add_argument("--b1a", required=True); x.add_argument("--out", required=True)
    x = s.add_parser("states"); x.add_argument("--server", required=True); x.add_argument("--rounds", type=int, default=8)
    x.add_argument("--seed0", type=int, default=7700); x.add_argument("--out", required=True)
    x = s.add_parser("decide"); x.add_argument("--side", choices=("adapter", "registry", "served"), required=True)
    for k in ("--server", "--states", "--unified", "--belief", "--out"):
        x.add_argument(k, required=True)
    x.add_argument("--limit", type=int, default=0)
    x.add_argument("--kit", help="the duel kit directory (required for --side adapter)")
    x = s.add_parser("compare"); x.add_argument("a"); x.add_argument("b")
    for sub in s.choices.values():
        sub.add_argument("--pkg-dir", default=".", help="local copies of fly.toml's /data/models packages")
    a = p.parse_args()
    set_pkg_dir(a.pkg_dir)
    if a.cmd == "decide" and a.side == "adapter" and not a.kit:
        p.error("--side adapter needs --kit")
    return {"package": cmd_package, "states": cmd_states, "decide": cmd_decide, "compare": cmd_compare}[a.cmd](a) or 0


if __name__ == "__main__":
    raise SystemExit(main())

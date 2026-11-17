"""RD1 step 0: is there a readable tie-break channel in release 52's near-ties?

Release 52 self-play (fly.toml's served recipe, every seat deciding on its own scrambled view, as the
defender study's run_sp.py), round plan r2.  At every play decision in tricks 1-6 whose record has >= 2
admitted candidates with finite value means within EPS of the best, every candidate a of that near set
(plus the play actually made, c*) is committed to a copy of the TRUE round and the served belief model
(B1a) is read from each other seat.  NLL_o(a) = -sum over the actor's remaining hidden, unpinned copies
of log p_o[card, receiver(actor)].  The row keeps the per-candidate NLLs; rd1_read.py forms
Delta(a) = [NLL_p(c*) - NLL_p(a)] - mean_opp[NLL_opp(c*) - NLL_opp(a)].

Usage: python rd1_probe.py <out.jsonl> <status> <seed0> <first_index> <n> [<plan_seed0>]
  deal seeds [seed0 + first_index, seed0 + first_index + n); plan index = seed - plan_seed0 (default seed0).
DIAGNOSTIC ONLY: reads true hands to score candidates; nothing here is a policy.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import sys
import time
from pathlib import Path

CODE = Path(__file__).resolve().parents[3]          # the worktree root (holds fly.toml and server/)
PKG = Path("/Users/jerryyu/.claude/jobs/d0498cda/tmp/r50pkg")
JSM1 = Path("/Users/jerryyu/perf-archive/root/models/js-m1-0d17fd03.npz")
LOCAL = {
    "/data/models/g3a-e04-f4f4127e.npz": PKG / "g3a-e04-f4f4127e.npz",
    "/data/models/p0-ft1-1fa201b2.npz": PKG / "p0-ft1-1fa201b2.npz",
    "/data/models/b1a-028131a0.npz": PKG / "b1a-028131a0.npz",
    "/data/models/js-m1-0d17fd03.npz": JSM1,
}
SHA = {"g3a-e04-f4f4127e.npz": "f4f4127ec0c8821b4aa07f7d651a4258c696f97a874707da2c78ad26c0c9b9fd",
       "p0-ft1-1fa201b2.npz": "1fa201b288e78b3072979f55030aae44711ee214b50a14e155d0bbe11b6bb1bf",
       "b1a-028131a0.npz": "028131a03de0c69b5164cdd0f65369950340f58fe226f75d6d877aeda2ca8fc8",
       "js-m1-0d17fd03.npz": "0d17fd03aee759cc8de50083c062e8b11a85bdd8cf2bdda95213b73f431fd747"}
EXPECTED_NAME = ("pv-search-f4f4127e-prior-1fa201b2-w64-k8-div-rc-rcec-whl-whd-wht-bw-tb-ele-elt-elm"
                 "-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-els1600-xf7-xfcompactlevel-r12e81e0c"
                 "-bury-hybrid-bwv-bbw-7a9a430fe690-sc8")
LOG_DIR = Path(os.environ.get("RD1_LOG_DIR", "/Users/jerryyu/.claude/jobs/d0498cda/tmp/rd1av1/rd1/enginelogs"))
EPS = 0.02          # the served tie tolerance (TIEBREAK_DEFAULTS["tiebreak_epsilon"], signed levels)
MAX_TRICK = 6       # tricks 1-6
FIRST_INDICES = (0, 3, 5, 8)


def _mapped_env() -> dict:
    import tomllib
    for p in LOCAL.values():
        got = hashlib.sha256(p.read_bytes()).hexdigest()
        assert got == SHA[p.name], f"{p} hash {got[:12]} != pinned"
    env = {str(k): str(v) for k, v in tomllib.loads((CODE / "fly.toml").read_text())["env"].items()}
    m = {k: str(v) for k, v in LOCAL.items()}
    env = {k: m.get(v, v) for k, v in env.items()}
    env["SHENGJI_LOG_DIR"] = str(LOG_DIR)
    env["SHENGJI_DATA_DIR"] = str(LOG_DIR)
    return env


def build_bot(seed: int = 17):
    env = _mapped_env()
    for k in list(os.environ):
        if k.startswith("SHENGJI_"):
            del os.environ[k]
    os.environ.update(env)
    sys.path.insert(0, str(CODE / "server"))
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    import shengji
    assert shengji.__file__.startswith(str(CODE)), shengji.__file__
    from shengji.engine import fast
    assert fast.HAVE_FAST, "compiled engine required"
    from shengji.eval import served_config
    maps = {k: str(v) for k, v in LOCAL.items()}
    diff = served_config.unexplained_diff(env, mappings=maps)
    assert diff == [], diff
    assert served_config.registry_name(env) == env["SHENGJI_BOT"] == EXPECTED_NAME
    name, bot = served_config.build_served_bot(env, seed=seed, expected_name=EXPECTED_NAME)
    os.environ.update(env)
    return name, bot


NAME, BOT = build_bot()

import numpy as np  # noqa: E402

from shengji.ai.belief_numpy import decision_inputs, load_belief_numpy  # noqa: E402
from shengji.ai.endgame import _clone_for_play  # noqa: E402
from shengji.ai.env import observe_committed_play  # noqa: E402
from shengji.engine.cards import RANKS  # noqa: E402
from shengji.engine.round import Round  # noqa: E402
from shengji.rl.encode import CARD_INDEX  # noqa: E402
from shengji.train.belief_labels import actor_memory, belief_labels  # noqa: E402

BELIEF = load_belief_numpy(LOCAL["/data/models/b1a-028131a0.npz"], SHA["b1a-028131a0.npz"])


def mix(*xs):
    h = 1469598103934665603
    for x in xs:
        h = ((h ^ (x & 0xFFFFFFFFFFFFFFFF)) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return h & 0x7FFFFFFF


def round_plan(index: int):
    if index % 10 in FIRST_INDICES:
        return "first", "2", None
    return "fixed_banker", RANKS[index % 13], index % 4


def view_round(rnd, seat, rng):
    v = _clone_for_play(rnd)
    others = [s for s in range(4) if s != seat]
    pool = [c for s in others for c in v.hands[s]]
    own_kitty = seat == v.banker
    if not own_kitty:
        pool += list(v.buried)
    rng.shuffle(pool)
    for s in others:
        n = len(v.hands[s])
        v.hands[s], pool = pool[:n], pool[n:]
    if not own_kitty:
        v.buried = pool
        v.kitty = list(pool)
    return v


def actor_nll(rnd_after, actor: int, observer: int) -> float:
    """-sum log p_observer(card -> actor) over the actor's hidden copies that the observer has not pinned."""
    mem = actor_memory(rnd_after, observer, ())
    inp = decision_inputs(rnd_after, observer, (), mem=mem)
    p = BELIEF.marginals(inp)
    y = belief_labels(rnd_after, observer, mem).astype(np.int64)
    r = (actor - observer) % 4 - 1
    free = y[:, r] - inp["K"][:, r]
    assert (free >= 0).all()
    idx = np.nonzero(free)[0]
    return float(-(free[idx] * np.log(np.clip(p[idx, r], 1e-9, 1.0))).sum())


def score_candidate(rnd, actor, cards):
    r2 = _clone_for_play(rnd)
    r2.play(actor, list(cards))
    return {o: actor_nll(r2, actor, o) for o in range(4) if o != actor}


def near_set(rec):
    adm = rec.get("admitted") or []
    vm = rec.get("value_means") or []
    pairs = [(sorted(a), float(v)) for a, v in zip(adm, vm) if v is not None and math.isfinite(float(v))]
    if len(pairs) < 2:
        return [], None
    best = max(v for _, v in pairs)
    return [(a, v) for a, v in pairs if v >= best - EPS], best


def decide(rnd, seat, deal_seed, d):
    s = mix(deal_seed, d)
    BOT.sampler.rng.seed(s)
    v = view_round(rnd, seat, random.Random(s ^ 0x5A5A))
    cards = list(BOT.decide_play(v, seat))
    return cards, (BOT.last_decision_record or {})


def play_deal(deal_seed, index):
    t0 = time.time()
    kind, rank, banker = round_plan(index)
    rnd = Round(rank, banker, random.Random(mix(deal_seed, 1)))
    BOT.sampler.rng.seed(mix(deal_seed, 2))
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        c = BOT.decide_declare(rnd, seat)
        if c:
            rnd.declare(seat, c)
    for seat in range(4):
        c = BOT.decide_declare(rnd, seat, final=True)
        if c:
            rnd.declare(seat, c)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, BOT.decide_bury(rnd, rnd.banker))
    from shengji.ai.refusal import RefusalLedger
    BOT._refusals = RefusalLedger()
    d, decisions, probe_secs = 0, [], 0.0
    while rnd.phase == "play":
        s = rnd.turn
        trick = len(rnd.history)
        lead = rnd.trick is None or not rnd.trick.plays
        cards, rec = decide(rnd, s, deal_seed, d)
        if trick < MAX_TRICK:
            ns, best = near_set(rec)
            entry = {"d": d, "seat": s, "trick": trick, "lead": bool(lead), "team_banker": s % 2 == rnd.banker % 2,
                     "n_admitted": len(rec.get("admitted") or []), "near": len(ns), "chosen": sorted(cards)}
            if len(ns) >= 2:
                tp = time.time()
                cands = [a for a, _ in ns]
                if sorted(cards) not in cands:
                    cands.append(sorted(cards))
                entry["cands"] = [{"cards": a, "v": next((v for b, v in ns if b == a), None),
                                   "nll": {str(o): x for o, x in score_candidate(rnd, s, a).items()}}
                                  for a in cands]
                entry["best_v"] = best
                probe_secs += time.time() - tp
            decisions.append(entry)
        rnd.play(s, list(cards))
        observe_committed_play(rnd, [BOT])
        d += 1
    return dict(deal_seed=deal_seed, index=index, kind=kind, rank=rank, banker=rnd.banker,
                trump=rnd.trump_suit, final_pts=rnd.attacker_points, decisions=decisions,
                gen_secs=time.time() - t0, probe_secs=probe_secs)


def main():
    out, status, seed0, first, n = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
    plan0 = int(sys.argv[6]) if len(sys.argv) > 6 else seed0
    done = set()
    if os.path.exists(out):
        for line in open(out):
            try:
                done.add(json.loads(line)["deal_seed"])
            except Exception:  # noqa: BLE001
                pass
    t0 = time.time()
    with open(status, "a") as st:
        st.write(f"START {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} bot={NAME[:40]}.. "
                 f"seeds [{seed0 + first},{seed0 + first + n}) resume_done={len(done)}\n")
        st.flush()
        for ds in range(seed0 + first, seed0 + first + n):
            if ds in done:
                continue
            try:
                row = play_deal(ds, ds - plan0)
            except Exception as e:  # noqa: BLE001
                import traceback
                row = dict(deal_seed=ds, error=repr(e)[:300], tb=traceback.format_exc()[-1500:])
            with open(out, "a") as f:
                f.write(json.dumps(row) + "\n")
            st.write(f"PROGRESS {time.strftime('%H:%M:%SZ', time.gmtime())} seed {ds} err {'error' in row} "
                     f"secs {row.get('gen_secs', 0):.1f} probe {row.get('probe_secs', 0):.1f} "
                     f"elapsed {time.time() - t0:.0f}s\n")
            st.flush()
        st.write(f"DONE {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} elapsed {time.time() - t0:.0f}s\n")


if __name__ == "__main__":
    main()

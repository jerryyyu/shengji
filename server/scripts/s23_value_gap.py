#!/usr/bin/env python3
"""S23 DEV: the early-trick value gap of each world model against the true deal.

The D6 training audit (M8) found the served value head right on the TRUE deal
(release 45, banker tricks 0-4: +0.98 predicted, +0.89 realised) and about one
level low on the served search's SAMPLED worlds.  This script measures, per
decision, the served leaf's value (the acting seat's chosen play, trick finished
by the served finisher, scored by the served package's value head) on

* ``true``: the true deal, and
* each arm's 64 worlds, drawn by the served ``PVSearchBot._worlds`` of a bot
  built from the served recipe plus the arm's rules:
  ``P`` release 45 (production sampler), ``WU`` uniform (S30), ``KB`` uniform +
  bury-rule kitty (S31), ``S17`` the S17 belief proposal (``bw``, a numpy
  belief package), and ``torch:NAME=CKPT`` arms -- the S17 proposal with its
  marginals from a ``belief_seq`` checkpoint (with ``belief_declare`` inputs when
  the checkpoint reads them).

``gap = mean over worlds - true`` per decision; summaries by role (banker,
banker's partner, defender; banker team = banker + partner, the S30 table's
"banker") and trick bucket, with the realised outcome where the record has one
(the M8 decomposition's columns), the arm's card agreement over the hidden
copies (v83 definition, public pins excluded) and its distinct worlds per 64
(an unweighted proposal's ESS is its world count).

Populations:

``heldout``  the #1023 S22 collections' states (S17 held-out test deals of the
             17 PV stores), the record's played action;
``w2b``      the serving audit's W2b heuristic self-play roots exactly as
             ``s30_uniform_worlds_eval.py values`` draws them (deals from
             1010000, three stops per deal), so P / WU / KB reproduce its table.

Every number is a world-model measurement, not playing strength.  Needs a tree
with the S17 served hook (#1030), the S30 sampler (#1036) and this branch's
``belief_declare`` (for declaration-input torch arms).  Usage (cwd server/,
compiled engine)::

    SHENGJI_FAST=1 python scripts/s23_value_gap.py heldout --collections C1 C2 \
        --stores-root /root/traj-out --arms P,WU,KB,S17 --shard 0/2 --out OUT.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

PKG = os.environ.get("S23_PKG", os.path.expanduser("~/Projects/shengji-wt/pkg/smv3out-491ee4bf.npz"))
PKG_SHA = "491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670"
BELIEF_PKG = os.environ.get("S23_BELIEF_PKG", os.path.expanduser("~/s17s/models/s17_full_h.npz"))
BELIEF_SHA = "cb02e1b67ecd6910d44a5928bf626f54fbe22606a3f04404332c738246f33acb"
SERVED_ENV = {
    "SHENGJI_PV_ADMISSION_DIVERSITY": "1", "SHENGJI_PV_REFUSAL_CONSTRAINTS": "1",
    "SHENGJI_PV_TIEBREAK_POINTS": "1", "SHENGJI_PV_LEAD_ANCHOR": "1",
    "SHENGJI_PV_DOOMED_THROW_RESELECT": "1", "SHENGJI_PV_VALUE_DECLARE": "1",
    "SHENGJI_PV_CKPT": PKG, "SHENGJI_PV_SHA256": PKG_SHA, "SHENGJI_PV_WORLDS": "64",
    "SHENGJI_PV_CANDIDATES": "8", "SHENGJI_PV_CAP": "4000", "SHENGJI_PV_BATCH_SIZE": "128",
    "SHENGJI_PV_SERVING_BUDGET_SECONDS": "3", "SHENGJI_PV_BURY_ARM": "hybrid",
    "SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS": "2", "SHENGJI_PV_BURY_WIDE_VALUE": "1",
    "SHENGJI_PV_BURY_WIDE_K": "64",
}
HL = dict(world_history_legal=True, world_history_draw=True)
ARMS = {
    "P": {},
    "WU": dict(HL, world_uniform=True),
    "KB": dict(HL, world_uniform=True, kitty_bury_rule=True),
    "S17": dict(HL, belief_worlds=True),
}
TRICK_BUCKETS = (("0-4", 0, 4), ("5-9", 5, 9), ("10-14", 10, 14), ("15+", 15, 99))
ROLES = ("banker", "partner", "defender")


# ------------------------------------------------------------------ bots

def served_bot(seed, **rules):
    from shengji.train import pv_search_policy as pv
    recipe = pv.pv_env_recipe(dict(SERVED_ENV))
    recipe.update(rules)
    if recipe.get("belief_worlds"):
        recipe.update(belief_checkpoint=BELIEF_PKG, belief_sha256=BELIEF_SHA)
    (name, factory), = pv.pv_registry_entries(**recipe).items()
    bot = factory(seed=seed)
    bot.serving_budget_seconds = None
    return name, bot


class TorchBelief:
    """A ``belief_seq`` checkpoint behind ``ai.belief_numpy.BeliefNumpy``'s
    ``marginals(inp)`` interface, so the served ``BeliefProposal`` draws from it
    unchanged.  A checkpoint that reads declaration inputs takes them from
    ``inp["decl_row"]`` / ``inp["decl_card"]`` (added by ``with_declare_inputs``)."""

    def __init__(self, path: str, temperature: float = 1.0):
        import torch
        from shengji.train import belief_seq as bs
        torch.set_num_threads(1)
        self.model, saved = bs.load_trained(path)
        self.decl = int(saved["config"].get("decl_row", 0)) > 0
        self.temperature = float(temperature)
        self.path = path
        self.sha256 = hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def __deepcopy__(self, memo):
        return self

    def marginals(self, inp):
        import torch
        T = len(inp["tok_int"])
        pad = max(T, 1)

        def tok(key, width, dtype):
            a = np.zeros((1, pad, width), dtype)
            if T:
                a[0, :T] = inp[key]
            return torch.from_numpy(a)
        b = {"tok_int": tok("tok_int", 4, np.int64), "tok_f": tok("tok_f", inp["tok_f"].shape[-1], np.float32),
             "tok_cards": tok("tok_cards", 54, np.float32), "tok_att": tok("tok_att", 54, np.float32),
             "card_feat": torch.from_numpy(np.asarray(inp["card_feat"], np.float32)[None]),
             "banker": torch.tensor([int(inp["banker"])]),
             "X": torch.from_numpy(np.asarray(inp["X"], np.float32)[None]),
             "row_card": torch.from_numpy(np.asarray(inp["row_card"], np.float32)[None]),
             "M": torch.from_numpy(np.asarray(inp["M"], bool)[None]),
             "rr": torch.tensor([0]), "seat": torch.tensor([int(inp["seat"])]),
             "ply": torch.tensor([T])}
        if self.decl:
            b["decl_row"] = torch.from_numpy(np.asarray(inp["decl_row"], np.float32)[None])
            b["decl_card"] = torch.from_numpy(np.asarray(inp["decl_card"], np.float32)[None])
        with torch.no_grad():
            z = self.model(b).numpy()[0].astype(np.float64) / self.temperature
        M = np.asarray(inp["M"], bool)
        z = np.where(M, z, -np.inf)
        top = z.max(-1, keepdims=True)
        top = np.where(np.isfinite(top), top, 0.0)
        e = np.where(M, np.exp(z - top), 0.0)
        s = e.sum(-1, keepdims=True)
        return np.where(s > 0, e / np.where(s > 0, s, 1.0), 0.0)


def with_declare_inputs():
    """Wrap ``ai.belief_numpy.decision_inputs`` so every live decision also
    carries the ``belief_declare`` inputs (from ``rnd.declaration_log``, the
    round's declaration sequence; the harness sets it from the record)."""
    from shengji.ai import belief_numpy
    from shengji.train.belief_declare import decision_declare_inputs
    base = belief_numpy.decision_inputs
    if getattr(base, "_s23_declare", False):
        return

    def wrapped(rnd, seat, refusals=(), mem=None):
        inp = base(rnd, seat, refusals, mem=mem)
        row, card = decision_declare_inputs(rnd, seat, getattr(rnd, "declaration_log", None))
        inp["decl_row"], inp["decl_card"] = row, card
        return inp
    wrapped._s23_declare = True
    wrapped.__wrapped_base__ = base
    belief_numpy.decision_inputs = wrapped


def build_arms(names, torch_arms, seed):
    bots = {}
    for k in names:
        bots[k] = served_bot(seed, **ARMS[k])[1]
    for spec in torch_arms:
        name, rest = spec.split("=", 1)
        path, _, temp = rest.partition(":")
        bot = served_bot(seed, **ARMS["S17"])[1]
        bot.belief_model = TorchBelief(path, float(temp) if temp else 1.0)
        if bot.belief_model.decl:
            with_declare_inputs()
        bots[name] = bot
    return bots


# ------------------------------------------------------------------ one decision

def leaf_values(ev, rnd, seat, action, worlds):
    from shengji.ai.cwv_policy import afterstate
    leaves = [afterstate(rnd, seat, hands, buried, action, finish_trick=True)
              for hands, buried in worlds]
    return np.asarray(ev.score(leaves, seat), np.float64)


def role_of(rnd, seat):
    if seat == rnd.banker:
        return "banker"
    return "partner" if (seat - rnd.banker) % 2 == 0 else "defender"


def residual_truth(rnd, seat, refusals):
    """``(K, Y)``: public pins and the true holders of every hidden copy (54 x 4,
    receivers next / partner / previous / kitty), as ``belief_numpy`` sees them."""
    from shengji.ai import belief_numpy
    from shengji.train.belief_labels import actor_memory, belief_labels
    fn = belief_numpy.decision_inputs
    inp = getattr(fn, "__wrapped_base__", fn)(rnd, seat, refusals)
    Y = belief_labels(rnd, seat, actor_memory(rnd, seat, refusals)).astype(np.int64)
    return inp["K"].astype(np.int64), Y


def world_matrix(worlds, rnd, seat):
    from shengji.rl.encode import CARD_INDEX
    kitty_hidden = seat != rnd.banker
    out = np.zeros((len(worlds), 54, 4), np.int64)
    for w, (hands, buried) in enumerate(worlds):
        for rel in (1, 2, 3):
            for c in hands[(seat + rel) % 4]:
                out[w, CARD_INDEX[c], rel - 1] += 1
        if kitty_hidden:
            for c in buried:
                out[w, CARD_INDEX[c], 3] += 1
    return out


def measure(rnd, seat, action, refusals, bots, ev, key):
    from shengji.engine.cards import TRUMP
    truth = ([list(h) for h in rnd.hands], list(rnd.buried))
    row = {"key": key, "trick": len(rnd.history), "role": role_of(rnd, seat),
           "lead": not rnd.trick.plays,
           "v_true": float(leaf_values(ev, rnd, seat, action, [truth])[0])}
    K, Y = residual_truth(rnd, seat, refusals if refusals is not None else ())
    Yr = np.maximum(Y - K, 0)
    hidden = max(int(Yr.sum()), 1)
    o = rnd.ordering
    for name, bot in bots.items():
        if refusals is not None:          # the decision's own refusal ledger
            bot._refusals.key = tuple(rnd.deck)
            bot._refusals.refusals = list(refusals)
        t0 = time.perf_counter()
        worlds, _ = bot._worlds(rnd, seat)
        secs = time.perf_counter() - t0
        stats = dict(bot._last_sampling)
        v = leaf_values(ev, rnd, seat, action, worlds)
        C = np.maximum(world_matrix(worlds, rnd, seat) - K[None], 0)
        agree = np.minimum(C, Yr[None]).sum((1, 2)) / hidden
        kit = [sum(o.eff_suit(c) == TRUMP for c in b) for _, b in worlds]
        row.update({f"v_{name}": float(v.mean()), f"sd_{name}": float(v.std()),
                    f"agree_{name}": float(agree.mean()),
                    f"distinct_{name}": len({repr((sorted(map(sorted, h.values())) if isinstance(h, dict)
                                                   else [sorted(x) for x in h], sorted(b)))
                                             for h, b in worlds}),
                    f"kit_{name}": float(np.mean(kit)), f"secs_{name}": secs,
                    f"fallback_{name}": stats.get("belief_fallback")})
    row["kit_true"] = sum(o.eff_suit(c) == TRUMP for c in rnd.buried)
    return row


# ------------------------------------------------------------------ populations

def heldout_rows(args, bots, ev):
    from shengji.train.world_weighting import iter_collected_states, load
    from shengji.train.cwv_data import bridge_record, TrainDataError
    from shengji.rl.value_afterstate import category_signed_level
    data = load(args.collections)
    stores = [str(Path(args.stores_root) / Path(s).name) for s in data["manifest"][0]["stores"]]
    meta = data["meta"]
    if args.max_trick is not None:
        meta = meta[meta[:, 5] <= args.max_trick + 1]       # meta trick is 1-based
    groups = sorted({(int(r[1]), int(r[2])) for r in meta})
    i, n = map(int, args.shard.split("/"))
    mine = set(groups[i::n])
    meta = np.asarray([r for r in meta if (int(r[1]), int(r[2])) in mine])
    rows = []
    t0 = time.time()
    for sid, view in iter_collected_states(stores, meta):
        d = view.decision
        rnd, seat, rec = d.rnd, d.seat, d.record
        rnd.declaration_log = list(view.setup.get("declarations") or [])
        action = list(rec.get("engine_play") or rec["action"])
        row = measure(rnd, seat, action, list(d.refusals), bots, ev, int(sid))
        row["n_decl"] = len(rnd.declaration_log)
        try:
            br = bridge_record(rec, version=2)
            row["realised"] = float(category_signed_level(br.target))
        except (TrainDataError, KeyError, ValueError):
            row["realised"] = None
        rows.append(row)
        if len(rows) % 25 == 0:
            print(f"states {len(rows)}/{len(meta)} {time.time() - t0:.0f}s", flush=True)
            _dump(args, rows)
    return rows


def testdeal_rows(args, bots, ev):
    """Early decisions of the S17 TEST deals (``belief_labels.split_of`` with the
    extract's salt and fractions; registered non-trajectory seed windows
    excluded): every ``--cluster-stride``-th cluster per store from
    ``--cluster-offset``, each decision at trick <= ``--max-trick`` kept with
    probability ``--rate`` (seeded by deal key, round and decision)."""
    from shengji.harvest.rebuild import RebuildError  # noqa: F401  (import check)
    from shengji.train.belief_labels import (_read_records, cluster_paths, excluded_windows,
                                             seed_excluded, split_of)
    from shengji.train.cwv_data import bridge_record, TrainDataError
    from shengji.train.data import deal_key
    from shengji.train.world_weighting import iter_states
    from shengji.rl.value_afterstate import category_signed_level
    windows = excluded_windows()
    max_trick = 4 if args.max_trick is None else args.max_trick
    i, n = map(int, args.shard.split("/"))
    rows = []
    t0 = time.time()
    for si, store in enumerate(args.stores):
        paths = cluster_paths(Path(args.stores_root) / store)
        picked = [p for ci, p in enumerate(paths) if ci % args.cluster_stride == args.cluster_offset]
        picked = picked[: args.clusters_per_store][i::n]
        for path in picked:
            plays = [r for r in _read_records(path) if r.get("decision_kind") == "play"]
            if not plays or any(seed_excluded(r.get("round_seed"), windows) for r in plays[:1]):
                continue
            key = deal_key(list(plays[0]["deck"]))
            if split_of(key, 0.06, 0.12) != "test":
                continue

            def want(d, key=key):
                if len(d.rnd.history) > max_trick:
                    return False
                h = hashlib.sha256(f"{key}|{d.round_index}|{d.decision_index}|s23".encode()).hexdigest()
                return int(h[:12], 16) / 16 ** 12 < args.rate
            for view in iter_states(plays, want=want):
                d = view.decision
                rnd, seat, rec = d.rnd, d.seat, d.record
                rnd.declaration_log = list(view.setup.get("declarations") or [])
                action = list(rec.get("engine_play") or rec["action"])
                row = measure(rnd, seat, action, list(d.refusals), bots, ev,
                              f"{store}:{path.name}:{d.round_index}:{d.decision_index}")
                row["n_decl"] = len(rnd.declaration_log)
                try:
                    row["realised"] = float(category_signed_level(bridge_record(rec, version=2).target))
                except (TrainDataError, KeyError, ValueError):
                    row["realised"] = None
                rows.append(row)
                if len(rows) % 50 == 0:
                    print(f"states {len(rows)} {time.time() - t0:.0f}s", flush=True)
                    _dump(args, rows)
    return rows


def _declared_with_log(seed):
    from shengji.ai.heuristic import HeuristicBot
    from shengji.engine.game import Game
    rnd = Game(random.Random(seed)).start_round()
    h = HeuristicBot()
    log = []
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = h.decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
            log.append({"seat": seat, "cards": list(cards)})
    for seat in range(4):
        cards = h.decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
            log.append({"seat": seat, "cards": list(cards)})
    rnd.finalize_declare()
    rnd.bury(rnd.banker, HeuristicBot().decide_bury(rnd, rnd.banker))
    rnd.declaration_log = log
    return rnd


def w2b_rows(args, bots, ev):
    """``s30_uniform_worlds_eval.cmd_values``'s roots, in its order."""
    from shengji.ai.heuristic import HeuristicBot
    h = HeuristicBot()
    rng = random.Random(8)
    rows, deal = [], 1010000
    while len(rows) < args.n:
        rnd = _declared_with_log(deal)
        deal += 1
        stops = set(rng.sample(range(60), 3))
        ply = 0
        while rnd.phase == "play" and ply < 60 and len(rows) < args.n:
            seat = rnd.turn
            action = h.decide_play(rnd, seat)
            if ply in stops:
                rows.append(measure(rnd, seat, action, None, bots, ev, f"{deal - 1}:{ply}"))
                rows[-1]["n_decl"] = len(rnd.declaration_log)
                if len(rows) % 25 == 0:
                    print("roots", len(rows), flush=True)
                    _dump(args, rows)
            rnd.play(seat, action)
            ply += 1
    return rows


# ------------------------------------------------------------------ summary

def bootstrap(x, reps=4000, seed=1):
    a = np.asarray(x, float)
    rng = np.random.default_rng(seed)
    m = a[rng.integers(0, len(a), size=(reps, len(a)))].mean(1)
    return [float(a.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def summarize(rows, arms):
    out = {"n": len(rows), "groups": {}}
    groups = {}
    for lab, lo, hi in TRICK_BUCKETS:
        for role in ROLES + ("banker_team",):
            def f(r, lo=lo, hi=hi, role=role):
                ok = lo <= r["trick"] <= hi
                return ok and (r["role"] in ("banker", "partner") if role == "banker_team"
                               else r["role"] == role)
            groups[f"{role} {lab}"] = f
    for g, f in groups.items():
        sel = [r for r in rows if f(r)]
        if not sel:
            continue
        e = {"n": len(sel), "v_true": float(np.mean([r["v_true"] for r in sel]))}
        real = [r["realised"] for r in sel if r.get("realised") is not None]
        if real:
            e["realised"] = float(np.mean(real))
        for a in arms:
            d = np.array([r[f"v_{a}"] - r["v_true"] for r in sel])
            e[f"{a}-true"] = [float(d.mean()), float(d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 1 else 0.0]
            e[f"{a}-true_ci"] = bootstrap(d)
            e[f"agree_{a}"] = float(np.mean([r[f"agree_{a}"] for r in sel]))
            e[f"distinct_{a}"] = float(np.mean([r[f"distinct_{a}"] for r in sel]))
        out["groups"][g] = e
    for a in arms:
        s = np.array([r[f"secs_{a}"] for r in rows])
        out.setdefault("seconds", {})[a] = {q: float(np.percentile(s, q)) for q in (50, 90, 99)}
        fb = [r[f"fallback_{a}"] for r in rows if r.get(f"fallback_{a}") is not None]
        if fb:
            out.setdefault("belief_fallback", {})[a] = float(np.mean(fb))
    return out


def _dump(args, rows, summary=None):
    tmp = args.out + ".tmp"
    with open(tmp, "w") as fh:
        json.dump({"args": vars(args), "summary": summary, "rows": rows}, fh)
    os.replace(tmp, args.out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("population", choices=("heldout", "testdeals", "w2b", "summarize"))
    ap.add_argument("--collections", nargs="*", default=[])
    ap.add_argument("--stores-root", default="/root/traj-out")
    ap.add_argument("--stores", nargs="*", default=[], help="testdeals: store names")
    ap.add_argument("--cluster-stride", type=int, default=2)
    ap.add_argument("--cluster-offset", type=int, default=1)
    ap.add_argument("--clusters-per-store", type=int, default=400)
    ap.add_argument("--rate", type=float, default=0.25)
    ap.add_argument("--prep-seconds", type=float, default=5.0,
                    help="belief preparation limit (served 0.25 s; raised so a cold first "
                         "call or a torch forward never falls back in a measurement)")
    ap.add_argument("--max-trick", type=int, default=None, help="0-based; keep tricks <= this")
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--n", type=int, default=600)
    ap.add_argument("--arms", default="P,WU,KB,S17")
    ap.add_argument("--torch-arm", action="append", default=[], help="NAME=CKPT[:T]")
    ap.add_argument("--seed", type=int, default=51)
    ap.add_argument("--inputs", nargs="*", default=[], help="summarize: row files to pool")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.population == "summarize":
        rows, arms = [], None
        for p in args.inputs:
            d = json.load(open(p))
            rows += d["rows"]
            a = [k for k in d["args"]["arms"].split(",") if k] + [s.split("=")[0] for s in d["args"]["torch_arm"]]
            arms = a if arms is None else [x for x in arms if x in a]
        s = summarize(rows, arms)
        Path(args.out).write_text(json.dumps(s, indent=1))
        print(json.dumps(s, indent=1))
        return 0
    import torch
    from shengji.ai import belief_numpy
    torch.set_num_threads(1)
    belief_numpy.PREP_SECONDS = args.prep_seconds
    arms = [a for a in args.arms.split(",") if a]
    bots = build_arms(arms, args.torch_arm, args.seed)
    ev = served_bot(args.seed)[1].evaluator
    t0 = time.time()
    rows = {"heldout": heldout_rows, "testdeals": testdeal_rows,
            "w2b": w2b_rows}[args.population](args, bots, ev)
    s = summarize(rows, list(bots))
    s["wall_seconds"] = time.time() - t0
    _dump(args, rows, s)
    print(json.dumps(s, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

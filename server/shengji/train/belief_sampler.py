"""S17 belief worlds offline: export, parity, latency and the proposal test.

DIAGNOSTIC ONLY (tier-i DEV), never served.  Steps:

* ``export`` -- a ``belief_seq`` checkpoint to the NumPy package
  (``ai.belief_numpy``), with its calibration temperature;
* ``parity`` -- torch vs NumPy logits on held-out extract rows;
* ``featurizer-parity`` -- the live featurizer (``ai.belief_numpy.decision_inputs``)
  vs the extract's rows and history tokens, by replaying the extract's clusters;
* ``latency`` -- per decision on held-out store decisions: featurize, forward,
  and draw ``W`` worlds, single thread;
* ``collect`` -- on the states of a ``world_weighting`` collection (the #1023
  held-out states), draw ``W`` worlds FROM the S17 marginals (receiver sizes,
  voids and public pins honoured by ``belief_seq.sample_worlds``) and score them
  exactly as the production collection was scored (``world_weighting.collect_state``
  with this proposal as ``draw``), optionally with the S22 likelihood pass; per
  state it also stores the S17 marginals and, per world, whether an earlier
  foreign follow is illegal for the hand the world gives that player then;
* ``analyze`` -- the production collection and the S17 collection on the same
  states: agreement, ESS, legality filter, S22 and S23 weights, by trick and role.

Offline card agreement is not playing strength.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ..ai.belief_numpy import (BeliefNumpy, decision_inputs, load_belief_numpy, save_package)
from ..rl.encode import CARD_INDEX, N_CARDS

KITTY = 3
_CODES = sorted(CARD_INDEX, key=CARD_INDEX.get)


# ------------------------------------------------------------------ export

def export(checkpoint: str, out: str, *, temperature: float, note: str = "") -> dict:
    import torch
    raw = Path(checkpoint).read_bytes()
    saved = torch.load(checkpoint, weights_only=False, map_location="cpu")
    weights = {k: v.detach().cpu().numpy() for k, v in saved["model"].items()}
    meta = {"source_checkpoint_sha256": hashlib.sha256(raw).hexdigest(),
            "source_checkpoint": str(checkpoint), "temperature": float(temperature),
            "epoch": saved.get("epoch"), "calib_ll": saved.get("calib_ll"),
            "no_history": bool(saved["args"].get("no_history")), "note": note}
    if meta["no_history"]:
        raise ValueError("a --no-history checkpoint is not the history model")
    sha = save_package(out, saved["config"], weights, meta)
    return {"package": out, "sha256": sha, **meta}


# ------------------------------------------------------------------ parity

def row_inputs(batch: Mapping[str, np.ndarray], j: int) -> dict:
    """One row of a ``belief_seq.make_batch`` batch as NumPy runtime inputs."""
    r = int(batch["rr"][j])
    ply = int(batch["ply"][j])
    return {"tok_int": batch["tok_int"][r, :ply], "tok_f": batch["tok_f"][r, :ply],
            "tok_cards": batch["tok_cards"][r, :ply], "tok_att": batch["tok_att"][r, :ply],
            "card_feat": batch["card_feat"][r], "banker": int(batch["banker"][r]),
            "seat": int(batch["seat"][j]), "X": batch["X"][j], "row_card": batch["row_card"][j],
            "M": batch["M"][j]}


def parity(data: Sequence[str], package: str, checkpoint: str, *, n: int, seed: int) -> dict:
    """Max |torch - NumPy| over ``n`` held-out rows, for both compute dtypes:
    logits on feasible receivers and calibrated marginals."""
    import torch
    from . import belief_seq as bs
    torch.set_num_threads(1)
    models = {"float64": load_belief_numpy(package, dtype=np.float64),
              "float32": load_belief_numpy(package, dtype=np.float32)}
    tmodel, _ = bs.load_trained(checkpoint)
    test = bs.load_eval(data, "test", bs._Verified(), max_rows=max(n * 4, 2000), seed=seed)
    rng = np.random.default_rng(seed)
    rows = rng.choice(len(test["X"]), size=min(n, len(test["X"])), replace=False)
    worst = {k: {"logit": 0.0, "prob": 0.0} for k in models}
    plies = []
    for i in rows:
        b = bs.make_batch(test, np.asarray([test["row_round"][i]]), np.asarray([i]))
        with torch.no_grad():
            ref = tmodel(bs.to_torch(b)).numpy()[0].astype(np.float64)
        inp = row_inputs(b, 0)
        M = inp["M"]
        for k, model in models.items():
            got = model.logits(inp).astype(np.float64)
            if M.any():
                worst[k]["logit"] = max(worst[k]["logit"], float(np.abs(got - ref)[M].max()))
            pr = bs.masked_softmax(ref[None], M[None], model.temperature)[0]
            worst[k]["prob"] = max(worst[k]["prob"], float(np.abs(model.marginals(inp) - pr).max()))
        plies.append(int(b["ply"][0]))
    return {"rows": int(len(rows)), "max_abs_diff": worst, "ply_min": int(min(plies)),
            "ply_max": int(max(plies)), "package_sha256": models["float32"].package_sha256}


def featurizer_parity(data: Sequence[str], stores_root: str, *, chunks: int, seed: int) -> dict:
    """Replay extract chunks' clusters and compare the live featurizer's inputs
    to the extract rows (float16 X, residual mask and sizes) and history tokens."""
    import io
    from . import belief_seq as bs
    from .belief_labels import cluster_paths, iter_decisions, _read_records
    entries = bs.extract_entries(data, "test")
    rng = np.random.default_rng(seed)
    pick = [entries[i] for i in rng.permutation(len(entries))[:chunks]]
    ver = bs._Verified()
    checked = 0
    bad: Counter = Counter()
    for e in pick:
        part = bs.load_part(e, bs.EVAL_KEYS, ver)
        man = json.loads((Path(e["dir"]) / "manifest.json").read_text())
        shards = cluster_paths(Path(stores_root) / Path(man["stores"][0]).name)
        R = part["_rounds"]
        for c in np.unique(part["cluster"]):
            rows = np.flatnonzero(part["cluster"] == c)
            by_dec = {int(part["decision"][i]): int(i) for i in rows}
            recs = [r for r in _read_records(shards[int(c)]) if r.get("decision_kind") == "play"]
            for d in iter_decisions(recs):
                i = by_dec.get(d.decision_index)
                if i is None:
                    continue
                inp = decision_inputs(d.rnd, d.seat, d.refusals)
                b = bs.make_batch(part, np.asarray([part["row_round"][i]]), np.asarray([i]))
                ref = row_inputs(b, 0)
                for k in ("X", "row_card", "M", "card_feat", "tok_int", "tok_f", "tok_cards",
                          "tok_att"):
                    a, r_ = np.asarray(inp[k]), np.asarray(ref[k])
                    if a.shape != r_.shape or not np.array_equal(a.astype(np.float64),
                                                                 r_.astype(np.float64)):
                        bad[k] += 1
                if not np.array_equal(inp["sizes"], part["sizes"][i]):
                    bad["sizes"] += 1
                if int(inp["banker"]) != int(ref["banker"]) or int(inp["seat"]) != int(ref["seat"]):
                    bad["seat/banker"] += 1
                checked += 1
    return {"rows_checked": checked, "mismatches": dict(bad), "chunks": len(pick)}


# ------------------------------------------------------------------ worlds from the marginals

def assemble_worlds(W: np.ndarray, inp: Mapping[str, Any], rnd, seat: int, kitty_hidden: bool):
    """``(hands, buried)`` per sampled world: unknown copies from ``W`` (54, 4)
    counts, the pinned copies with their holders, the actor's own hand, and the
    actor's own burial when it is known."""
    K = inp["K"]
    out = []
    for w in W:
        hands: list[list[str]] = [[], [], [], []]
        hands[seat] = list(rnd.hands[seat])
        for rel in (1, 2, 3):
            cnt = w[:, rel - 1].astype(np.int64) + K[:, rel - 1]
            hands[(seat + rel) % 4] = [_CODES[c] for c in np.repeat(np.arange(N_CARDS), cnt)]
        buried = ([_CODES[c] for c in np.repeat(np.arange(N_CARDS), w[:, KITTY].astype(np.int64))]
                  if kitty_hidden else list(rnd.buried))
        out.append((hands, buried))
    return out


def s17_draw(model: BeliefNumpy, *, project: bool = True, keep: dict | None = None):
    """A ``world_weighting.collect_state`` proposal: ``n`` worlds drawn from the
    S17 marginals.  ``keep`` (when given) receives the state's inputs and marginals."""
    from ..ai.mcbot import MCBot
    from ..ai.memory import Memory
    from .belief_seq import project_sizes, sample_worlds

    def draw(rnd, seat, refusals, n, seed):
        from ..ai.refusal import pin_unplayed_attempt
        sampler = MCBot(seed=seed)
        mem = Memory(rnd, seat, own_kitty=getattr(sampler, "BANKER_KITTY", True))
        # the refused throws' pins, as release 45's refusal-aware draw writes
        # them into its memory: the agreement layout then excludes those
        # copies for every arm alike (they are public, never a sampling gain)
        for refusal in refusals:
            pin_unplayed_attempt(mem, rnd, refusal, seat)
        t0 = time.perf_counter()
        inp = decision_inputs(rnd, seat, refusals)
        P = model.marginals(inp)
        t1 = time.perf_counter()
        n_c, sizes, M = inp["n_c"], inp["sizes"], inp["M"]
        Q = project_sizes(P, n_c, sizes, M) if project else P
        W = sample_worlds(Q, n_c, M, sizes, n, np.random.default_rng(seed))
        kitty_hidden = not mem.own_kitty_known
        if not kitty_hidden and W[:, :, KITTY].any():
            raise ValueError("a known kitty received a copy")
        worlds = assemble_worlds(W, inp, rnd, seat, kitty_hidden)
        for (hands, buried) in worlds:
            for s in range(4):
                if len(hands[s]) != len(rnd.hands[s]):
                    raise ValueError("a sampled hand has the wrong size")
            if len(buried) != len(rnd.buried):
                raise ValueError("a sampled kitty has the wrong size")
        if keep is not None:
            keep.update({"P": P.astype(np.float32), "Q": Q.astype(np.float32),
                         "ms_model": 1e3 * (t1 - t0), "ms_draw": 1e3 * (time.perf_counter() - t1),
                         "worlds": worlds})
        return sampler, mem, worlds, {"attempts": n}
    return draw


def production_draw(*, keep: dict):
    """Release 45's own draw (``world_weighting.served_worlds``), keeping the
    worlds for the follow check: the comparator arm at the same W."""
    from .world_weighting import served_worlds

    def draw(rnd, seat, refusals, n, seed):
        t0 = time.perf_counter()
        sampler, mem, worlds, stats = served_worlds(rnd, seat, refusals, n, seed)
        keep.update({"P": np.zeros((N_CARDS, 4), np.float32), "Q": np.zeros((N_CARDS, 4), np.float32),
                     "ms_model": 0.0, "ms_draw": 1e3 * (time.perf_counter() - t0), "worlds": worlds})
        return sampler, mem, worlds, stats
    return draw


def distinct_worlds(worlds) -> int:
    return len({tuple(tuple(sorted(h)) for h in hands) + (tuple(sorted(b)),)
                for hands, b in worlds})


def follow_illegal(view, worlds) -> np.ndarray:
    """``(W,)`` bool: an earlier FOLLOW by another seat is illegal for the hand
    the world gives that player at that play (that hand = the world's current
    hand plus what the player has played since).  The same question
    ``world_weighting.event_log_probs`` answers through the legal-set
    enumeration, asked of the engine's follow validator directly."""
    from ..engine.legal import validate_follow
    from .world_weighting import played_since
    seat = view.decision.seat
    out = np.zeros(len(worlds), bool)
    events = [(i, ev) for i, ev in enumerate(view.events) if ev.seat != seat and ev.snap.trick.plays]
    if not events:
        return out
    since = {i: played_since(view.events, i) for i, _ in events}
    for w, (hands, _) in enumerate(worlds):
        for i, ev in events:
            hand = list(hands[ev.seat]) + list(since[i][ev.seat].elements())
            try:
                validate_follow(list(ev.played), hand, ev.snap.trick.plays[0].cards,
                                ev.snap.ordering)
            except Exception:
                out[w] = True
                break
    return out


def _collect_task(args: tuple) -> dict:
    (collection, stores, state_ids, out_dir, name, package, sha256, worlds, project, events,
     prior_package, prior_sha256, proposal) = args
    from . import world_weighting as ww
    # offline: float64 (the served default is float32; marginals agree to ~1e-6)
    model = load_belief_numpy(package, sha256, dtype=np.float64)
    predict = version = None
    if events:
        from .pv_search_policy import NumpyPriorPredict
        predict = NumpyPriorPredict(prior_package, prior_sha256)
        version = int(predict.version)
    data = ww.load(collection)
    meta = data["meta"][np.isin(data["meta"][:, 0], np.asarray(state_ids, np.int64))]
    row_of = {int(r[0]): r for r in meta}
    c = ww.Collected()
    timings, failed = [], []
    extras: dict[str, list] = {k: [] for k in ("state", "P", "Q", "illegal", "ms_model",
                                                "ms_draw", "ms_legal", "distinct")}
    t0 = time.time()
    keep: dict = {}
    draw = (s17_draw(model, project=project, keep=keep) if proposal == "s17"
            else production_draw(keep=keep))
    for sid, view in ww.iter_collected_states(stores, meta):
        row = row_of[sid]
        n_before = len(c.meta)
        try:
            key = ww.deal_key(list(view.decision.record["deck"]))
            # same key, round and decision as the production collection: same per-state seed
            t = ww.collect_state(view, predict, version or 0, worlds=worlds, cap=ww.SERVED_CAP,
                                 key=key, out=c, state_id=sid, store_index=int(row[1]),
                                 cluster_index=int(row[2]), events=events, draw=draw)
            tl = time.perf_counter()
            illegal = follow_illegal(view, keep["worlds"])
            extras["ms_legal"].append(1e3 * (time.perf_counter() - tl))
        except Exception as exc:          # one state's defect never sinks the chunk
            if len(c.meta) != n_before:
                raise
            failed.append({"state": int(sid), "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
            continue
        timings.append((t["t_sample"], t["t_lik"], t["events"]))
        extras["state"].append(sid)
        extras["P"].append(keep["P"])
        extras["Q"].append(keep["Q"])
        extras["illegal"].append(illegal)
        extras["ms_model"].append(keep["ms_model"])
        extras["ms_draw"].append(keep["ms_draw"])
        extras["distinct"].append(distinct_worlds(keep["worlds"]))
    out = Path(out_dir)
    res = ww._save(out / f"{name}.npz", c, timings) if c.meta else {"file": None, "states": 0}
    if extras["state"]:
        ex_path = out / f"{name}.s17.npz"
        np.savez_compressed(ex_path, **{k: np.asarray(v) for k, v in extras.items()})
        res["extras"] = {"file": ex_path.name,
                         "sha256": hashlib.sha256(ex_path.read_bytes()).hexdigest()}
    return dict(res, failed=failed, seconds=time.time() - t0, chunk=name)


def collect(collection: str, out: str, *, package: str, sha256: str, worlds: int, project: bool,
            events: bool, workers: int, states_per_task: int, prior_package: str | None,
            prior_sha256: str | None, max_states: int | None = None, seed: int = 0,
            proposal: str = "s17", log=print) -> dict:
    """The S17 proposal on every state of one production collection."""
    from concurrent.futures import ProcessPoolExecutor
    from . import world_weighting as ww
    src = json.loads((Path(collection) / "manifest.json").read_text())
    data = ww.load(collection)
    ids = data["meta"][:, 0].astype(np.int64)
    if max_states is not None and max_states < len(ids):
        ids = np.sort(np.random.default_rng(seed).choice(ids, size=max_states, replace=False))
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    # tasks group states of the same cluster (one replay per cluster)
    order = np.lexsort((data["meta"][:, 2], data["meta"][:, 1]))
    wanted = set(ids.tolist())
    ordered = [int(s) for s in data["meta"][order, 0] if int(s) in wanted]
    tasks = []
    for t in range(0, len(ordered), states_per_task):
        name = f"t{t // states_per_task:04d}"
        if (out_dir / f"{name}.npz").exists():
            continue
        tasks.append((collection, src["stores"], ordered[t:t + states_per_task], str(out_dir), name,
                      package, sha256, worlds, project, events, prior_package, prior_sha256,
                      proposal))
    manifest_path = out_dir / "manifest.json"
    manifest = (json.loads(manifest_path.read_text()) if manifest_path.exists() else
                {"schema": ww.SCHEMA, "proposal": proposal, "source_collection": str(collection),
                 "source_manifest_sha256": hashlib.sha256(
                     (Path(collection) / "manifest.json").read_bytes()).hexdigest(),
                 "stores": src["stores"], "package": package, "sha256": sha256, "worlds": worlds,
                 "project": project, "events": events, "prior_package": prior_package,
                 "prior_sha256": prior_sha256, "cap": ww.SERVED_CAP,
                 "meta_cols": ww.META_COLS, "ev_cols": ww.EV_COLS, "readings": ww.READINGS,
                 "chunks": []})
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, res in enumerate(pool.map(_collect_task, tasks)):
            manifest["chunks"].append(res)
            manifest_path.write_text(json.dumps(manifest, indent=1))
            log(f"[s17-collect] {i + 1}/{len(tasks)} {res['chunk']} states={res['states']} "
                f"failed={len(res['failed'])} {res['seconds']:.0f}s total {time.time() - t0:.0f}s",
                flush=True)
    return manifest


# ------------------------------------------------------------------ analysis

def load_extras(outs: Sequence[str]) -> dict:
    """The S17 per-state extras of one or more S17 collections, keyed like
    ``world_weighting.load`` (collection ``n`` offsets ids by ``n * 1e12``)."""
    parts = []
    for n, out in enumerate(outs):
        man = json.loads((Path(out) / "manifest.json").read_text())
        for ch in man["chunks"]:
            ex = ch.get("extras")
            if not ex:
                continue
            p = Path(out) / ex["file"]
            if hashlib.sha256(p.read_bytes()).hexdigest() != ex["sha256"]:
                raise ValueError(f"{p}: sha256 mismatch")
            with np.load(p) as z:
                part = {k: z[k] for k in z.files}
            part["state"] = part["state"] + n * 10 ** 12
            parts.append(part)
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}


def align(data: dict, ids: np.ndarray) -> dict:
    """Restrict a ``world_weighting.load`` dict to ``ids`` in that order."""
    row = {int(s): i for i, s in enumerate(data["meta"][:, 0])}
    keep = np.asarray([row[int(s)] for s in ids])
    out = {k: data[k][keep] for k in ("meta", "agreement", "counts", "truth", "kitty_x")}
    ev_keep = np.isin(data["ev_row"], keep)
    new_row = {int(o): i for i, o in enumerate(keep)}
    for k in ("ev_state", "ev_meta", "ev_seconds", "ev_listwise", "ev_bernoulli"):
        out[k] = data[k][ev_keep]
    out["ev_row"] = np.asarray([new_row[int(r)] for r in data["ev_row"][ev_keep]], np.int64)
    t = data["timings"]
    out["timings"] = t[keep] if len(t) == len(data["meta"]) else t
    return out


def kitty_replace_log_weights(head: str, data: Mapping[str, np.ndarray],
                              Q: np.ndarray) -> np.ndarray:
    """S23 in place of S17 for the kitty: per world, the sum over its kitty
    copies of ``log p_S23(card) - log q(card, kitty)`` with ``q`` the S17
    proposal marginal (projected) the worlds were drawn from."""
    from . import kitty_inference
    from .world_weighting import META_COLS
    model = kitty_inference.load_head(head)
    p = kitty_inference.predict(model, data["kitty_x"].astype(np.float32))[:, 0, :]
    kitty = data["counts"][:, :, KITTY, :].astype(np.float64)
    ratio = np.log(np.clip(p, 1e-6, 1.0)) - np.log(np.clip(Q[:, :, KITTY], 1e-6, 1.0))
    lw = np.einsum("swc,sc->sw", kitty, ratio)
    hidden = data["meta"][:, META_COLS.index("kitty_hidden")] == 1
    return np.where(hidden[:, None], lw, 0.0)


def analyze(prod_outs: Sequence[str], s17_outs: Sequence[str], *, kitty_head: str | None,
            s17_events: bool) -> dict:
    from . import world_weighting as ww
    prod = ww.load(prod_outs)
    s17 = ww.load(s17_outs)
    ex = load_extras(s17_outs)
    # state ids: both collections index by (collection position, original id)
    have = set(prod["meta"][:, 0].tolist())
    ids = np.asarray([s for s in s17["meta"][:, 0] if int(s) in have], np.int64)
    P = align(prod, ids)
    S = align(s17, ids)
    xrow = {int(s): i for i, s in enumerate(ex["state"])}
    xi = np.asarray([xrow[int(s)] for s in ids])
    illegal = ex["illegal"][xi].astype(bool)
    Q = ex["Q"][xi].astype(np.float64)
    if not np.array_equal(P["truth"], S["truth"]):
        raise ValueError("the two collections disagree on the true deal of a state")
    n, W = S["agreement"].shape
    zero = np.zeros((n, W))
    ill_lw = np.where(illegal & ~illegal.all(1, keepdims=True), -np.inf, 0.0)
    rep: dict[str, Any] = {"states": int(n), "worlds": int(W)}
    arms = {"production": (P, zero), "s17": (S, zero), "s17_legal": (S, ill_lw)}
    pv = {v.name: v for v in ww.DEFAULT_VARIANTS}
    if len(P["ev_state"]):
        arms["production_legal_only"] = (P, ww.variant_log_weights(P, pv["legal_only"]))
        arms["production_s22_b05"] = (P, ww.variant_log_weights(P, pv["lw_b05_e02"]))
        arms["production_s22_b05_zi"] = (P, ww.variant_log_weights(P, pv["lw_b05_e02_zi"]))
        arms["production_s22_b1"] = (P, ww.variant_log_weights(P, pv["lw_b1_e02"]))
        # production worlds reweighted toward the S17 marginals (no redraw)
        arms["production_x_s17"] = (P, np.stack([
            ww.marginal_log_weights(P["counts"][i], ex["P"][xi[i]]) for i in range(n)]))
    if s17_events and len(S["ev_state"]):
        arms["s17_legal_only_enum"] = (S, ww.variant_log_weights(S, pv["legal_only"]))
        arms["s17_s22_b05"] = (S, ww.variant_log_weights(S, pv["lw_b05_e02"]))
        arms["s17_s22_b05_zi"] = (S, ww.variant_log_weights(S, pv["lw_b05_e02_zi"]))
        arms["s17_s22_b1"] = (S, ww.variant_log_weights(S, pv["lw_b1_e02"]))
    if kitty_head:
        from . import kitty_inference
        k_prod = kitty_inference.world_log_weights(kitty_head, P)
        k_rep = kitty_replace_log_weights(kitty_head, S, Q)
        k_naive = kitty_inference.world_log_weights(kitty_head, S)
        arms["production_s23"] = (P, k_prod)
        arms["s17_s23_replace"] = (S, k_rep)
        arms["s17_s23_product"] = (S, k_naive)
        arms["s17_legal_s23_replace"] = (S, ill_lw + k_rep)
        if s17_events and len(S["ev_state"]):
            arms["s17_s22_b05_zi_s23_replace"] = (S, ww.variant_log_weights(S, pv["lw_b05_e02_zi"])
                                                  + k_rep)
    for name, (d, lw) in arms.items():
        rep[name] = ww.score(d, lw)
    # the S17 follow check vs the #1023 enumeration detector (same worlds)
    if s17_events and len(S["ev_state"]):
        enum = np.isneginf(ww.variant_log_weights(S, ww.Variant("x", legality_only=True)))
        raw = np.zeros((n, W), bool)
        lp = S["ev_listwise"].astype(np.float64)
        for e in range(len(lp)):
            raw[S["ev_row"][e]] |= lp[e] <= ww.ILLEGAL / 2
        rep["detector_agreement"] = {"follow_check_rate": float(illegal.mean()),
                                     "enumeration_rate": float(raw.mean()),
                                     "same": float((illegal == raw).mean())}
    rep["illegal"] = {"world_rate": float(illegal.mean()),
                      "states_with_any": float(illegal.any(1).mean()),
                      "states_all_illegal": int(illegal.all(1).sum())}
    rep["timing_ms"] = {k: {"p50": float(np.median(ex[k][xi])), "p95": float(np.percentile(ex[k][xi], 95))}
                        for k in ("ms_model", "ms_draw", "ms_legal")}
    return rep


def compare_arms(arms: Mapping[str, Sequence[str]], *, ref: str) -> dict:
    """Same-W arms on the same states (each arm: the dirs of one ``collect``,
    in the same collection order): per arm, card agreement (all worlds and with
    the follow-illegal worlds dropped), distinct worlds per state, the share of
    illegal worlds, by trick bucket and role, and the paired per-state gain over
    ``ref``."""
    from . import world_weighting as ww
    loaded = {}
    for name, outs in arms.items():
        d = ww.load(outs)
        ex = load_extras(outs)
        xrow = {int(s): i for i, s in enumerate(ex["state"])}
        loaded[name] = (d, ex, xrow)
    common = set.intersection(*[set(int(s) for s in d["meta"][:, 0]) for d, _, _ in loaded.values()])
    ids = np.asarray(sorted(common), np.int64)
    out: dict[str, Any] = {"states": int(len(ids)), "ref": ref, "arms": {}}
    per_state: dict[str, dict[str, np.ndarray]] = {}
    meta = None
    for name, (d, ex, xrow) in loaded.items():
        row = {int(s): i for i, s in enumerate(d["meta"][:, 0])}
        r = np.asarray([row[int(s)] for s in ids])
        x = np.asarray([xrow[int(s)] for s in ids])
        a = d["agreement"][r].astype(np.float64)
        ill = ex["illegal"][x].astype(bool)
        keep = ~ill
        keep[~keep.any(1)] = True              # all illegal: keep them all
        per_state[name] = {"agree": a.mean(1), "legal": (a * keep).sum(1) / keep.sum(1),
                           "illegal": ill.mean(1), "distinct": ex["distinct"][x].astype(np.float64)}
        if meta is None:
            meta = d["meta"][r]
        elif not np.array_equal(meta[:, 3:6], d["meta"][r][:, 3:6]):
            raise ValueError("arms disagree on a state's round/decision/trick")
        out["arms"][name] = {"worlds": int(a.shape[1]),
                             "ms_draw_p50": float(np.median(ex["ms_draw"][x])),
                             "ms_draw_p95": float(np.percentile(ex["ms_draw"][x], 95))}
    trick = meta[:, ww.META_COLS.index("trick")]
    role = meta[:, ww.META_COLS.index("role")]
    groups = {"overall": np.ones(len(ids), bool)}
    groups.update({f"trick {lo}-{hi}": (trick >= lo) & (trick <= hi) for lo, hi in ww.TRICK_BUCKETS})
    groups.update({n: role == i for i, n in enumerate(("banker", "banker_partner", "defender"))})
    for name, ps in per_state.items():
        tab = {}
        for g, m in groups.items():
            gain = ps["agree"][m] - per_state[ref]["agree"][m]
            tab[g] = {"states": int(m.sum()), "agree": float(ps["agree"][m].mean()),
                      "agree_legal": float(ps["legal"][m].mean()),
                      "illegal_share": float(ps["illegal"][m].mean()),
                      "distinct": float(ps["distinct"][m].mean()),
                      "gain_vs_ref": float(gain.mean()),
                      "gain_se": (float(gain.std(ddof=1) / math.sqrt(len(gain)))
                                  if len(gain) > 1 else None)}
        out["arms"][name]["table"] = tab
    return out


# ------------------------------------------------------------------ latency

def latency(stores: Sequence[str], package: str, *, n: int, worlds: int, seed: int,
            project: bool) -> dict:
    """Per decision, single thread: featurize, forward, and draw ``worlds`` worlds,
    on held-out (test-split) store decisions."""
    from .belief_labels import cluster_paths, iter_decisions, split_of, _read_records
    from .belief_seq import project_sizes, sample_worlds
    from .data import deal_key
    from .world_weighting import CALIB, TEST
    model = load_belief_numpy(package)
    rng = np.random.default_rng(seed)
    t_feat, t_fwd, t_enc, t_draw, plies = [], [], [], [], []
    for store in stores:
        paths = cluster_paths(store)
        for k in rng.permutation(len(paths)):
            if len(t_fwd) >= n:
                break
            recs = [r for r in _read_records(paths[k]) if r.get("decision_kind") == "play"]
            if not recs or split_of(deal_key(list(recs[0]["deck"])), CALIB, TEST) != "test":
                continue
            for d in iter_decisions(recs):
                if rng.random() > 0.1:
                    continue
                t0 = time.perf_counter()
                inp = decision_inputs(d.rnd, d.seat, d.refusals)
                t1 = time.perf_counter()
                P = model.marginals(inp)
                t2 = time.perf_counter()
                model.encode_history(inp)
                te = time.perf_counter() - t2
                t2 = time.perf_counter()
                if worlds:
                    Q = project_sizes(P, inp["n_c"], inp["sizes"], inp["M"]) if project else P
                    sample_worlds(Q, inp["n_c"], inp["M"], inp["sizes"], worlds,
                                  np.random.default_rng(int(t0 * 1e6) % 2 ** 32))
                t3 = time.perf_counter()
                t_feat.append(1e3 * (t1 - t0))
                t_fwd.append(1e3 * (t2 - t1 - te))
                t_enc.append(1e3 * te)
                t_draw.append(1e3 * (t3 - t2))
                plies.append(len(inp["tok_int"]))
        if len(t_fwd) >= n:
            break

    def q(x):
        x = np.asarray(x[5:])
        return {"p50": float(np.median(x)), "p95": float(np.percentile(x, 95)),
                "p99": float(np.percentile(x, 99)), "mean": float(x.mean())}
    tot = np.asarray(t_feat) + np.asarray(t_fwd)
    # a served bot that keeps the encoder states of earlier plays (the encoder is
    # causal) pays the forward without the history encoder, plus one token
    cached = np.asarray(t_fwd) - np.asarray(t_enc) * (1 - 1 / np.maximum(np.asarray(plies), 1))
    return {"n": len(t_fwd) - 5, "featurize_ms": q(t_feat), "forward_ms": q(t_fwd),
            "encoder_ms": q(t_enc), "forward_cached_encoder_ms": q(cached),
            "featurize_plus_cached_forward_ms": q(np.asarray(t_feat) + cached),
            "featurize_plus_forward_ms": q(tot), f"draw{worlds}_ms": q(t_draw),
            "ply_mean": float(np.mean(plies)), "engine": os.environ.get("SHENGJI_FAST", "0"),
            "threads": os.environ.get("OMP_NUM_THREADS")}


# ------------------------------------------------------------------ CLI

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="belief_sampler", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    e = sub.add_parser("export")
    e.add_argument("--checkpoint", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--temperature", type=float, required=True)
    e.add_argument("--note", default="")
    p = sub.add_parser("parity")
    p.add_argument("--data", nargs="+", required=True)
    p.add_argument("--package", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--n", type=int, default=500)
    p.add_argument("--seed", type=int, default=0)
    f = sub.add_parser("featurizer-parity")
    f.add_argument("--data", nargs="+", required=True)
    f.add_argument("--stores-root", required=True)
    f.add_argument("--chunks", type=int, default=4)
    f.add_argument("--seed", type=int, default=0)
    la = sub.add_parser("latency")
    la.add_argument("--store", action="append", required=True)
    la.add_argument("--package", required=True)
    la.add_argument("--n", type=int, default=400)
    la.add_argument("--worlds", type=int, default=512)
    la.add_argument("--no-project", action="store_true")
    la.add_argument("--seed", type=int, default=0)
    c = sub.add_parser("collect")
    c.add_argument("--collection", required=True, help="a world_weighting collection dir")
    c.add_argument("--out", required=True)
    c.add_argument("--package", required=True)
    c.add_argument("--sha256", required=True)
    c.add_argument("--worlds", type=int, default=512)
    c.add_argument("--no-project", action="store_true")
    c.add_argument("--events", action="store_true", help="also the S22 likelihood pass")
    c.add_argument("--prior-package", default=None)
    c.add_argument("--prior-sha256", default=None)
    c.add_argument("--workers", type=int, default=2)
    c.add_argument("--states-per-task", type=int, default=25)
    c.add_argument("--max-states", type=int, default=None)
    c.add_argument("--seed", type=int, default=0)
    c.add_argument("--proposal", choices=("s17", "production"), default="s17",
                   help="production: release 45's own draw at the same W (the comparator)")
    cmp_ = sub.add_parser("compare", help="same-W arms on the same states")
    cmp_.add_argument("--arm", action="append", required=True,
                      help="name=dir[,dir...] (one collect per collection, same order per arm)")
    cmp_.add_argument("--ref", required=True)
    cmp_.add_argument("--report", required=True)
    a = sub.add_parser("analyze")
    a.add_argument("--prod", action="append", required=True)
    a.add_argument("--s17", action="append", required=True)
    a.add_argument("--kitty-head", default=None)
    a.add_argument("--events", action="store_true")
    a.add_argument("--report", required=True)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "export":
        res = export(args.checkpoint, args.out, temperature=args.temperature, note=args.note)
    elif args.command == "parity":
        res = parity(args.data, args.package, args.checkpoint, n=args.n, seed=args.seed)
    elif args.command == "featurizer-parity":
        res = featurizer_parity(args.data, args.stores_root, chunks=args.chunks, seed=args.seed)
    elif args.command == "latency":
        res = latency(args.store, args.package, n=args.n, worlds=args.worlds, seed=args.seed,
                      project=not args.no_project)
    elif args.command == "collect":
        if args.events and not (args.prior_package and args.prior_sha256):
            raise SystemExit("--events needs --prior-package and --prior-sha256")
        m = collect(args.collection, args.out, package=args.package, sha256=args.sha256,
                    worlds=args.worlds, project=not args.no_project, events=args.events,
                    workers=args.workers, states_per_task=args.states_per_task,
                    prior_package=args.prior_package, prior_sha256=args.prior_sha256,
                    max_states=args.max_states, seed=args.seed, proposal=args.proposal)
        res = {"chunks": len(m["chunks"]), "states": sum(c.get("states", 0) for c in m["chunks"])}
    elif args.command == "compare":
        arms = {a.split("=", 1)[0]: a.split("=", 1)[1].split(",") for a in args.arm}
        res = compare_arms(arms, ref=args.ref)
        Path(args.report).write_text(json.dumps(res, indent=1))
    else:
        res = analyze(args.prod, args.s17, kitty_head=args.kitty_head, s17_events=args.events)
        Path(args.report).write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())

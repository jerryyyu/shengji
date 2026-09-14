"""Root-state factorised policy prior (issue #419, plan #421).

A small net reads the ROOT state (the position before the acting seat plays; the
same v2 tensors the value net reads, built here for the root rather than the
afterstate) and emits one logit per card: the log-odds that the card is part of
the action the search played.  Any candidate action's prior score is the sum of
its cards' log-odds, so scoring every legal action costs arithmetic over the
action list, not a net call per afterstate -- which is what lets a shortlist
prune the wide tail (#396) BEFORE enumerating afterstates.

Targets, from trajectory records:
  * multi-hot of the played action's cards (binary cross-entropy per card);
  * listwise: softmax over the record's ballot candidates' factorised scores with
    the played candidate as the class (the search's own ordering, weighted by
    ``listwise_weight``).
Metrics on held-out deals: recall of the played action inside the prior's
top-N over the record's legal actions, per legal-count bucket; and whether the
whole ballot survives a top-N cut.  Rows with more than ``MAX_LEGAL`` stored
legal actions are ranked within a sample that always contains the played action
and the ballot (optimistic for the prior; the count is reported).

CLI: ``extract`` / ``train`` / ``eval``; see ``build_parser``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ..engine.cards import make_deck
from ..harvest.rebuild import state_for_record
from ..rl.douzero_micro import HISTORY_EVENT_DIM
from ..rl.encode import CARD_INDEX, N_CARDS, encode_obs
from ..rl.value_afterstate import (WORLD_RECEIVERS, ValueAfterstateError,
                                   ValueAfterstateTensors)
from ..rl.value_afterstate_v2 import widen_to
from .cwv_data import deal_key, tensors_at
from .data import ShardRef, discover_store, iter_records

SCHEMA = "shengji-policy-prior-v1"
ENC_VERSION = 2
INPUT_DIM = 561 + WORLD_RECEIVERS * N_CARDS + 2      # v2 public + world + perspective = 833
MAX_LEGAL = 4000
BUCKETS = ((0, 20), (21, 100), (101, 1000), (1001, 10000), (10001, 10 ** 9))
TOP_NS = (1, 5, 8, 32, 64, 256)


class PolicyPriorError(ValueError):
    """A record, tensor or checkpoint the prior refuses."""


# ----------------------------------------------------------------- root tensors

def root_tensors(rnd, seat: int) -> ValueAfterstateTensors:
    """v2 tensors of a ROOT state.  The frozen afterstate builder refuses an empty
    history (the opening lead), so that case is built by hand with a one-event
    placeholder history and widened to v2; every other root goes through the
    builder unchanged."""
    try:
        return tensors_at(rnd, seat, version=ENC_VERSION)
    except ValueAfterstateError:
        public = np.asarray([*encode_obs(rnd, seat), float(rnd.phase == "round_end")], dtype=np.float32)
        world = np.zeros((WORLD_RECEIVERS, N_CARDS), dtype=np.float32)
        for rel in range(4):
            for card in rnd.hands[(seat + rel) % 4]:
                world[rel, CARD_INDEX[card]] += 0.5
        for card in rnd.buried:
            world[4, CARD_INDEX[card]] += 0.5
        attacker = rnd.is_attacker(seat)
        v1 = ValueAfterstateTensors(public, np.zeros((1, HISTORY_EVENT_DIM), np.float32), world,
                                    np.asarray([float(attacker), float(not attacker)], np.float32))
        return widen_to(v1, rnd, seat, ENC_VERSION)


def flat_input(t: ValueAfterstateTensors) -> np.ndarray:
    x = np.concatenate([t.public.ravel(), t.world.ravel(), t.perspective.ravel()]).astype(np.float32)
    if x.shape != (INPUT_DIM,):
        raise PolicyPriorError(f"root input width {x.shape[0]} != {INPUT_DIM}")
    return x


def cards_to_idx(cards: Sequence[str]) -> list[int]:
    return [CARD_INDEX[c] for c in cards]


def deal_fraction(rnd) -> float:
    """The split hash of ``cwv_data.split_deals`` (seed 1) as a fraction in [0, 1)."""
    return int(hashlib.sha256(f"1|{deal_key(list(rnd.deck))}".encode()).hexdigest(), 16) / 16 ** 64


# ----------------------------------------------------------------- extraction

def _shard_rows(args: tuple) -> list[tuple]:
    path, lo, hi, thin, seed = args
    rng = random.Random(f"{seed}|{path}")
    rows: list[tuple] = []
    first = True
    for rec in iter_records(ShardRef(path=path, label="", sha256="", records=None, cluster=None, store="")):
        if rec.get("decision_kind") != "play":
            continue
        if not first and rng.random() > thin:
            continue
        try:
            root = state_for_record(rec)
        except Exception:
            continue
        frac = deal_fraction(root)
        if not (lo <= frac < hi):
            if first:
                return []            # a shard is one deal: the whole shard is out of the split
            continue
        first = False
        seat = int(rec["seat"])
        if root.phase != "play" or root.turn != seat:
            continue
        x = flat_input(root_tensors(root, seat))
        y = np.zeros(N_CARDS, np.float32)
        for c in rec["action"]:
            y[CARD_INDEX[c]] = 1.0
        legal = rec.get("legal_actions") or []
        n_legal = int(rec.get("legal_actions_count") or len(legal))
        if len(legal) > MAX_LEGAL:
            keep = [a for a in legal if sorted(a) == sorted(rec["action"])] + [a for a in rec.get("ballot", [])]
            keep += rng.sample(legal, MAX_LEGAL - len(keep))
            legal = keep
        rows.append((x, y, n_legal, [cards_to_idx(a) for a in legal],
                     [cards_to_idx(a) for a in rec.get("ballot", [])], cards_to_idx(rec["action"]),
                     bool(rec.get("legal_actions_complete", True))))
    return rows


def extract(out: str | Path, corpora: Sequence[str], *, lo: float, hi: float, thin: float,
            max_rows: int, workers: int, seed: int = 1) -> dict:
    """Write ``<out>.npz`` (X, Y) and ``<out>.meta.jsonl`` (one record per row)."""
    if not 0 < thin <= 1 or not 0 <= lo < hi <= 1.01:
        raise PolicyPriorError("thin must be in (0, 1] and 0 <= lo < hi")
    rng = random.Random(seed)
    paths: list[str] = []
    for root in corpora:
        paths.extend(sh.path for sh in discover_store(root).shards)
    rng.shuffle(paths)
    X, Y, meta = [], [], []
    with ProcessPoolExecutor(workers) as ex:
        for got in ex.map(_shard_rows, [(p, lo, hi, thin, seed) for p in paths], chunksize=4):
            for x, y, n, legal, ballot, taken, complete in got:
                X.append(x); Y.append(y)
                meta.append({"n_legal": n, "legal": legal, "ballot": ballot, "taken": taken, "complete": complete})
            if len(X) >= max_rows:
                ex.shutdown(cancel_futures=True)
                break
    if not X:
        raise PolicyPriorError("no rows extracted")
    Xa = np.stack(X[:max_rows]); Ya = np.stack(Y[:max_rows]); meta = meta[:max_rows]
    out = Path(out)
    np.savez_compressed(str(out) + ".npz", X=Xa, Y=Ya)
    with open(str(out) + ".meta.jsonl", "w") as fh:
        for m in meta:
            fh.write(json.dumps(m) + "\n")
    summary = {"rows": int(len(Xa)), "mean_legal": float(np.mean([m["n_legal"] for m in meta])),
               "max_legal": int(max(m["n_legal"] for m in meta)),
               "sampled_rows": int(sum(m["n_legal"] > MAX_LEGAL for m in meta)),
               "incomplete_rows": int(sum(not m["complete"] for m in meta))}
    with open(str(out) + ".summary.json", "w") as fh:
        json.dump(summary, fh, indent=1)
    return summary


# ----------------------------------------------------------------- model + scoring

def build_model(hidden: Sequence[int] = (512, 256)):
    import torch
    layers: list = []
    din = INPUT_DIM
    for h in hidden:
        layers += [torch.nn.Linear(din, int(h)), torch.nn.GELU()]
        din = int(h)
    layers.append(torch.nn.Linear(din, N_CARDS))
    return torch.nn.Sequential(*layers)


def card_log_odds(logits):
    """log p - log (1 - p) per card, from the head's logits (that IS the logit)."""
    return logits


def score_candidates(log_odds: np.ndarray, candidates: Sequence[Sequence[int]]) -> np.ndarray:
    """Factorised prior score of each candidate: the sum of its cards' log-odds,
    with multiplicity (a pair counts its card twice).  Order-invariant."""
    return np.asarray([sum(float(log_odds[c]) for c in cand) for cand in candidates], dtype=np.float64)


def ballot_tensors(meta: Sequence[Mapping[str, Any]]):
    """Padded ballot card indices (int8, -1 = none), a slot mask, and the played slot
    (-1 if the played action is not in the ballot).  Padding is DYNAMIC: every slot
    and every card of every candidate is kept, so the training score of a candidate
    is exactly its inference score (``score_candidates``), whatever its length."""
    import torch
    n = len(meta)
    ballots = [[tuple(sorted(a)) for a in m["ballot"] if a] for m in meta]
    b_max = max((len(b) for b in ballots), default=1) or 1
    c_max = max((len(c) for b in ballots for c in b), default=1) or 1
    ball = np.full((n, b_max, c_max), -1, np.int8)
    mask = np.zeros((n, b_max), bool)
    tgt = np.full(n, -1, np.int64)
    for i, (m, cands) in enumerate(zip(meta, ballots)):
        taken = tuple(sorted(m["taken"]))
        for j, c in enumerate(cands):
            ball[i, j, :len(c)] = c
            mask[i, j] = True
            if c == taken:
                tgt[i] = j
    return torch.from_numpy(ball), torch.from_numpy(mask), torch.from_numpy(tgt)


def listwise_loss(logits, ball, mask, tgt):
    """Cross-entropy over the ballot's factorised scores, rows whose played action is
    in the ballot only.  ``logits`` (b, 54); ``ball`` (b, B, C) card indices or -1."""
    import torch
    ok = tgt >= 0
    if not bool(ok.any()):
        return logits.sum() * 0.0
    lo = logits[ok]                                                    # (n, 54) log-odds
    b = ball[ok].long()
    gathered = lo.gather(1, b.clamp(min=0).reshape(b.shape[0], -1)).reshape(b.shape)
    gathered = gathered * (b >= 0)
    scores = gathered.sum(2).masked_fill(~mask[ok], -1e9)
    return torch.nn.functional.cross_entropy(scores, tgt[ok])


# ----------------------------------------------------------------- train / eval

def train(data: str | Path, out: str | Path, *, test: str | Path | None = None, epochs: int = 10,
          listwise_weight: float = 1.0, lr: float = 1e-3, weight_decay: float = 1e-4,
          batch_size: int = 512, seed: int = 1, threads: int = 4, log=print) -> dict:
    import torch
    torch.manual_seed(seed); torch.set_num_threads(threads)
    d = np.load(str(data) + ".npz")
    X = torch.from_numpy(d["X"]); Y = torch.from_numpy(d["Y"])
    if X.shape[1] != INPUT_DIM or Y.shape[1] != N_CARDS:
        raise PolicyPriorError("training arrays have the wrong width")
    meta = [json.loads(l) for l in open(str(data) + ".meta.jsonl")]
    mu, sd = X.mean(0), X.std(0) + 1e-6
    net = build_model()
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=weight_decay)
    ball = mask = tgt = None
    if listwise_weight > 0:
        ball, mask, tgt = ballot_tensors(meta)
    n = len(X); t0 = time.time(); history = []
    for ep in range(epochs):
        perm = torch.randperm(n); tot = 0.0; steps = 0
        for i in range(0, n, batch_size):
            idx = perm[i:i + batch_size]
            logits = net((X[idx] - mu) / sd)
            loss = torch.nn.functional.binary_cross_entropy_with_logits(logits, Y[idx])
            if listwise_weight > 0:
                loss = loss + listwise_weight * listwise_loss(logits, ball[idx], mask[idx], tgt[idx])
            opt.zero_grad(); loss.backward(); opt.step()
            tot += float(loss); steps += 1
        history.append({"epoch": ep + 1, "train_loss": tot / max(steps, 1), "secs": round(time.time() - t0)})
        if log:
            log(f"epoch {ep + 1}/{epochs} loss {tot / max(steps, 1):.4f} ({time.time() - t0:.0f}s)")
    payload = {"schema": SCHEMA, "state": net.state_dict(), "mu": mu, "sd": sd, "hidden": [512, 256],
               "enc_version": ENC_VERSION, "input_dim": INPUT_DIM, "epochs": epochs,
               "listwise_weight": listwise_weight, "train_rows": int(n), "history": history,
               "data_sha256": hashlib.sha256(open(str(data) + ".npz", "rb").read()).hexdigest()}
    torch.save(payload, str(out))
    result = {"out": str(out), "train_rows": int(n), "history": history}
    if test is not None:
        result["eval"] = evaluate(out, test, log=log)
    return result


def load_prior(path: str | Path):
    import torch
    payload = torch.load(str(path), map_location="cpu", weights_only=False)
    if payload.get("schema") != SCHEMA or payload.get("input_dim") != INPUT_DIM:
        raise PolicyPriorError(f"{path}: not a policy-prior checkpoint")
    net = build_model(payload["hidden"]); net.load_state_dict(payload["state"]); net.eval()
    return net, payload


def predict_log_odds(net, payload, X: np.ndarray) -> np.ndarray:
    import torch
    with torch.no_grad():
        return net((torch.from_numpy(X) - payload["mu"]) / payload["sd"]).numpy()


def evaluate(checkpoint: str | Path, test: str | Path, *, log=print) -> dict:
    """Recall of the played action and survival of the whole ballot inside the
    prior's top-N over the STORED legal list, per legal-count bucket, reported in
    two strata: ``exhaustive`` (the record's legal list is complete and was not
    sampled) and ``partial`` (incomplete or sampled to ``MAX_LEGAL``).  Rows whose
    played action is not in the stored list are COUNTED (``missing_target``) and
    excluded from recall.  The random baseline is computed on the same ranked
    universe (the stored list); the full-universe reference (the record's true
    legal count) is reported separately and labelled."""
    net, payload = load_prior(checkpoint)
    d = np.load(str(test) + ".npz"); X = d["X"]
    meta = [json.loads(l) for l in open(str(test) + ".meta.jsonl")]
    lo = predict_log_odds(net, payload, X)
    strata = {"exhaustive": {}, "partial": {}}
    counters = {"rows": len(meta), "no_legal_list": 0, "missing_target": {"exhaustive": 0, "partial": 0},
                "ranked": {"exhaustive": 0, "partial": 0}}
    def bucket_stats():
        return {"n": 0, "taken": {N: 0 for N in TOP_NS}, "ballot_rows": 0, "ballot": {N: 0 for N in TOP_NS},
                "rand_same": {N: 0.0 for N in TOP_NS}, "rand_full": {N: 0.0 for N in TOP_NS}}
    for i, m in enumerate(meta):
        legal = m["legal"]
        if not legal:
            counters["no_legal_list"] += 1
            continue
        nL = int(m["n_legal"])
        stratum = "exhaustive" if (m.get("complete", True) and nL <= MAX_LEGAL and len(legal) >= nL) else "partial"
        sc = score_candidates(lo[i], legal)
        order = np.argsort(-sc, kind="stable")
        keys = [tuple(sorted(legal[j])) for j in order]
        try:
            r_taken = keys.index(tuple(sorted(m["taken"])))
        except ValueError:
            counters["missing_target"][stratum] += 1
            continue
        counters["ranked"][stratum] += 1
        b = next(bb for bb in BUCKETS if bb[0] <= nL <= bb[1])
        s = strata[stratum].setdefault(b, bucket_stats()); s["n"] += 1
        universe = len(keys)
        for N in TOP_NS:
            s["taken"][N] += r_taken < N
            s["rand_same"][N] += min(1.0, N / universe)
            s["rand_full"][N] += min(1.0, N / max(nL, 1))
        bal = [tuple(sorted(a)) for a in m["ballot"] if a]
        if bal:
            s["ballot_rows"] += 1
            for N in TOP_NS:
                top = set(keys[:N]); s["ballot"][N] += all(k in top for k in bal)
    report = {"counters": counters, "strata": {}}
    lines = [f"rows {counters['rows']} · no legal list {counters['no_legal_list']} · ranked exhaustive {counters['ranked']['exhaustive']} / partial {counters['ranked']['partial']} · missing target exhaustive {counters['missing_target']['exhaustive']} / partial {counters['missing_target']['partial']}"]
    for name in ("exhaustive", "partial"):
        recs = []
        lines.append(f"\n[{name}] legal-count bucket   rows  " + " ".join(f"top{N:<4d}" for N in TOP_NS) + " | rand64 same-universe | rand64 full (ref) | ballot in top256")
        for b in BUCKETS:
            s = strata[name].get(b)
            if not s:
                continue
            rec = {"bucket": list(b), "rows": s["n"], "taken_recall": {str(N): s["taken"][N] / s["n"] for N in TOP_NS},
                   "ballot_survival": {str(N): (s["ballot"][N] / s["ballot_rows"] if s["ballot_rows"] else None) for N in TOP_NS},
                   "random_same_universe": {str(N): s["rand_same"][N] / s["n"] for N in TOP_NS},
                   "random_full_universe_reference": {str(N): s["rand_full"][N] / s["n"] for N in TOP_NS}}
            recs.append(rec)
            bs = (s["ballot"][256] / s["ballot_rows"]) if s["ballot_rows"] else float("nan")
            lines.append(f"{b[0]:>6}-{min(b[1], 10**6):<7} {s['n']:6d}  " + " ".join(f"{s['taken'][N] / s['n']:7.3f}" for N in TOP_NS)
                         + f" | {s['rand_same'][64] / s['n']:6.3f} | {s['rand_full'][64] / s['n']:6.3f} | {bs:.3f}")
        report["strata"][name] = recs
    report["text"] = "\n".join(lines)
    if log:
        log(report["text"])
    return report


# ----------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="policy_prior")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract"); e.add_argument("--out", required=True); e.add_argument("--data", action="append", required=True)
    e.add_argument("--lo", type=float, default=0.0); e.add_argument("--hi", type=float, default=0.8)
    e.add_argument("--thin", type=float, default=0.1); e.add_argument("--max-rows", type=int, default=1_000_000)
    e.add_argument("--workers", type=int, default=8); e.add_argument("--seed", type=int, default=1)
    t = sub.add_parser("train"); t.add_argument("--data", required=True); t.add_argument("--out", required=True)
    t.add_argument("--test"); t.add_argument("--epochs", type=int, default=10); t.add_argument("--listwise-weight", type=float, default=1.0)
    t.add_argument("--lr", type=float, default=1e-3); t.add_argument("--threads", type=int, default=4); t.add_argument("--seed", type=int, default=1)
    v = sub.add_parser("eval"); v.add_argument("--checkpoint", required=True); v.add_argument("--test", required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    if a.cmd == "extract":
        print(json.dumps(extract(a.out, a.data, lo=a.lo, hi=a.hi, thin=a.thin, max_rows=a.max_rows, workers=a.workers, seed=a.seed)))
    elif a.cmd == "train":
        r = train(a.data, a.out, test=a.test, epochs=a.epochs, listwise_weight=a.listwise_weight, lr=a.lr, threads=a.threads, seed=a.seed)
        print(json.dumps({k: v for k, v in r.items() if k != "eval"}))
    else:
        evaluate(a.checkpoint, a.test)
    return 0


if __name__ == "__main__":
    sys.exit(main())

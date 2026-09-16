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
from ..rl.public_history import HISTORY_EVENT_DIM      # torch-free (douzero_micro imports torch)
from ..rl.encode import CARD_INDEX, N_CARDS, encode_obs
from ..rl.value_afterstate import (WORLD_RECEIVERS, ValueAfterstateError,
                                   ValueAfterstateTensors)
from ..rl.value_afterstate_v2 import widen_to
# torch-free sources: cwv_data imports rl.douzero_micro (torch) at module level, and the
# served admission reaches this module through _prior_scores (Codex HOLD on #442).
from ..rl.value_afterstate_v2 import tensors_from_round as tensors_at
from .data import deal_key
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


def root_flat_input(rnd, seat: int) -> np.ndarray:
    """Flat prior input without constructing history that this model discards.

    Keep the original root builder as the authority for empty-history opening
    states and static-builder refusals. Sequential/value tensor callers still
    use ``root_tensors`` unchanged.
    """
    from ..ai.cwv_static_encoding import tensors_from_round_static

    if not rnd.history:
        return flat_input(root_tensors(rnd, seat))
    try:
        tensors = tensors_from_round_static(rnd, seat, version=ENC_VERSION)
    except ValueAfterstateError:
        return flat_input(root_tensors(rnd, seat))
    return flat_input(tensors)


def cards_to_idx(cards: Sequence[str]) -> list[int]:
    return [CARD_INDEX[c] for c in cards]


def deal_id(rnd) -> str:
    """A stable 16-hex id of the deal (the deck), written into every row's
    metadata so evaluation can resample whole deals (Codex on #425: decisions of
    one game are correlated; a row bootstrap understates the uncertainty)."""
    return hashlib.sha256(deal_key(list(rnd.deck)).encode()).hexdigest()[:16]


def deal_fraction(rnd) -> float:
    """The split hash of ``cwv_data.split_deals`` (seed 1) as a fraction in [0, 1)."""
    return int(hashlib.sha256(f"1|{deal_key(list(rnd.deck))}".encode()).hexdigest(), 16) / 16 ** 64


# ----------------------------------------------------------------- extraction

def _shard_rows(args: tuple) -> list[tuple]:
    path, lo, hi, thin, seed = args
    rng = random.Random(f"{seed}|{path}")
    rows: list[tuple] = []
    first = True
    deal = ""
    key = ""
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
        if first:
            deal = deal_id(root)
            key = deal_key(list(root.deck))       # the exposure system's identity (#428)
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
                     bool(rec.get("legal_actions_complete", True)), deal, key))
    return rows


CHUNK_SCHEMA = "shengji-policy-rows-chunked-v1"


def _write_chunk(out_dir: Path, index: int, X, Y, meta) -> dict:
    """One training chunk: rows as float16, the ballots padded once, the deal
    keys alongside; no legal lists (training never reads them)."""
    ball, mask, tgt = ballot_tensors(meta)
    path = out_dir / f"chunk-{index:05d}.npz"
    np.savez_compressed(path, X=np.stack(X).astype(np.float16), Y=np.stack(Y).astype(np.uint8),
                        ball=ball.numpy(), mask=mask.numpy(), tgt=tgt.numpy(),
                        deal_key=np.asarray([m["deal_key"] for m in meta]))
    with open(path, "rb") as fh:
        sha = hashlib.file_digest(fh, "sha256").hexdigest()
    return {"file": path.name, "rows": len(X), "deals": len({m["deal_key"] for m in meta}),
            "rows_with_ballot_target": int((tgt >= 0).sum()), "sha256": sha}


def extract(out: str | Path, corpora: Sequence[str], *, lo: float, hi: float, thin: float,
            max_rows: int, workers: int, seed: int = 1, chunk_rows: int | None = None) -> dict:
    """Write ``<out>.npz`` (X, Y) and ``<out>.meta.jsonl`` (one record per row);
    with ``chunk_rows`` write a DIRECTORY ``<out>/`` of training chunks
    (``chunk-NNNNN.npz`` with X float16, Y, padded ballots, deal keys) plus
    ``manifest.json`` so a trainer can stream every root row instead of holding
    them in memory (#425: the policy head on all ~20M root decisions)."""
    if not 0 < thin <= 1 or not 0 <= lo < hi <= 1.01:
        raise PolicyPriorError("thin must be in (0, 1] and 0 <= lo < hi")
    if chunk_rows is not None and (type(chunk_rows) is not int or chunk_rows < 1):
        raise PolicyPriorError("chunk_rows must be a positive integer")
    rng = random.Random(seed)
    paths: list[str] = []
    for root in corpora:
        paths.extend(sh.path for sh in discover_store(root).shards)
    rng.shuffle(paths)
    X, Y, meta = [], [], []
    chunks: list[dict] = []
    total = 0
    out_dir = Path(out) if chunk_rows else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        if any(out_dir.glob("chunk-*.npz")):
            raise PolicyPriorError(f"{out_dir}: chunks already present; refusing to mix extractions")
    with ProcessPoolExecutor(workers) as ex:
        for got in ex.map(_shard_rows, [(p, lo, hi, thin, seed) for p in paths], chunksize=4):
            for x, y, n, legal, ballot, taken, complete, deal, key in got:
                X.append(x); Y.append(y)
                meta.append({"n_legal": n, "legal": legal, "ballot": ballot, "taken": taken, "complete": complete,
                             "deal": deal, "deal_key": key})
            if out_dir is not None:
                # Flush full chunks as they fill; the LAST chunk may be partial so the
                # limit is met the moment total + buffered reaches it (bounded memory:
                # never more than chunk_rows + one shard's rows are held).
                while len(X) >= chunk_rows and total + chunk_rows <= max_rows:
                    chunks.append(_write_chunk(out_dir, len(chunks), X[:chunk_rows], Y[:chunk_rows], meta[:chunk_rows]))
                    total += chunk_rows
                    X, Y, meta = X[chunk_rows:], Y[chunk_rows:], meta[chunk_rows:]
                if total + len(X) >= max_rows:
                    keep = max_rows - total
                    if keep > 0:
                        chunks.append(_write_chunk(out_dir, len(chunks), X[:keep], Y[:keep], meta[:keep]))
                        total += keep
                    X, Y, meta = [], [], []
                    ex.shutdown(cancel_futures=True)
                    break
            elif len(X) >= max_rows:
                ex.shutdown(cancel_futures=True)
                break
    if out_dir is not None:
        keep = min(len(X), max_rows - total)
        if keep > 0:
            chunks.append(_write_chunk(out_dir, len(chunks), X[:keep], Y[:keep], meta[:keep]))
            total += keep
        if not chunks:
            raise PolicyPriorError("no rows extracted")
        manifest = {"schema": CHUNK_SCHEMA, "input_dim": INPUT_DIM, "rows": total, "chunks": chunks,
                    "deals": sum(c["deals"] for c in chunks),
                    "split": {"lo": lo, "hi": hi, "thin": thin, "seed": seed, "max_rows": max_rows},
                    "corpora": [str(Path(c).resolve()) for c in corpora],
                    "deal_key_schema": "shengji-value-deal-key-v1"}
        with open(out_dir / "manifest.json", "w") as fh:
            json.dump(manifest, fh, indent=1)
        return {"rows": total, "chunks": len(chunks), "dir": str(out_dir)}
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
               "incomplete_rows": int(sum(not m["complete"] for m in meta)),
               "deals": len({m["deal"] for m in meta})}
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
    return _report(_rank_rows(lo, meta), len(meta), log)


def _rank_rows(lo: np.ndarray, meta: Sequence[Mapping[str, Any]]) -> list[dict]:
    """One record per ranked row: stratum, bucket, deal id, the played action's
    rank, the ranked universe size, the true legal count and the ballot's worst
    rank; plus the counter rows (no legal list / missing target) flagged."""
    out = []
    for i, m in enumerate(meta):
        legal = m["legal"]
        if not legal:
            out.append({"skip": "no_legal_list"})
            continue
        nL = int(m["n_legal"])
        stratum = "exhaustive" if (m.get("complete", True) and nL <= MAX_LEGAL and len(legal) >= nL) else "partial"
        sc = score_candidates(lo[i], legal)
        order = np.argsort(-sc, kind="stable")
        keys = [tuple(sorted(legal[j])) for j in order]
        try:
            r_taken = keys.index(tuple(sorted(m["taken"])))
        except ValueError:
            out.append({"skip": "missing_target", "stratum": stratum})
            continue
        bal = [tuple(sorted(a)) for a in m["ballot"] if a]
        pos: dict[tuple, int] = {}
        for r, k in enumerate(keys):
            pos.setdefault(k, r)          # FIRST rank per action: the stored list may hold duplicates
        out.append({"stratum": stratum, "bucket": next(bb for bb in BUCKETS if bb[0] <= nL <= bb[1]),
                    "deal": m.get("deal", ""), "r_taken": r_taken, "universe": len(keys), "n_legal": nL,
                    "ballot_worst": (max(pos.get(k, 10 ** 9) for k in bal) if bal else None)})
    return out


def _report(rows: list[dict], n_rows: int, log) -> dict:
    strata = {"exhaustive": {}, "partial": {}}
    counters = {"rows": n_rows, "no_legal_list": 0, "missing_target": {"exhaustive": 0, "partial": 0},
                "ranked": {"exhaustive": 0, "partial": 0}}
    def bucket_stats():
        return {"n": 0, "deals": set(), "taken": {N: 0 for N in TOP_NS}, "ballot_rows": 0, "ballot": {N: 0 for N in TOP_NS},
                "rand_same": {N: 0.0 for N in TOP_NS}, "rand_full": {N: 0.0 for N in TOP_NS}}
    for r in rows:
        if r.get("skip") == "no_legal_list":
            counters["no_legal_list"] += 1
            continue
        if r.get("skip") == "missing_target":
            counters["missing_target"][r["stratum"]] += 1
            continue
        counters["ranked"][r["stratum"]] += 1
        s = strata[r["stratum"]].setdefault(r["bucket"], bucket_stats()); s["n"] += 1; s["deals"].add(r["deal"])
        for N in TOP_NS:
            s["taken"][N] += r["r_taken"] < N
            s["rand_same"][N] += min(1.0, N / r["universe"])
            s["rand_full"][N] += min(1.0, N / max(r["n_legal"], 1))
        if r["ballot_worst"] is not None:
            s["ballot_rows"] += 1
            for N in TOP_NS:
                s["ballot"][N] += r["ballot_worst"] < N
    report = {"counters": counters, "strata": {}}
    lines = [f"rows {counters['rows']} · no legal list {counters['no_legal_list']} · ranked exhaustive {counters['ranked']['exhaustive']} / partial {counters['ranked']['partial']} · missing target exhaustive {counters['missing_target']['exhaustive']} / partial {counters['missing_target']['partial']}"]
    for name in ("exhaustive", "partial"):
        recs = []
        lines.append(f"\n[{name}] legal-count bucket   rows  deals " + " ".join(f"top{N:<4d}" for N in TOP_NS) + " | rand64 same-universe | rand64 full (ref) | ballot in top256")
        for b in BUCKETS:
            s = strata[name].get(b)
            if not s:
                continue
            rec = {"bucket": list(b), "rows": s["n"], "deals": len(s["deals"]), "taken_recall": {str(N): s["taken"][N] / s["n"] for N in TOP_NS},
                   "ballot_survival": {str(N): (s["ballot"][N] / s["ballot_rows"] if s["ballot_rows"] else None) for N in TOP_NS},
                   "random_same_universe": {str(N): s["rand_same"][N] / s["n"] for N in TOP_NS},
                   "random_full_universe_reference": {str(N): s["rand_full"][N] / s["n"] for N in TOP_NS}}
            recs.append(rec)
            bs = (s["ballot"][256] / s["ballot_rows"]) if s["ballot_rows"] else float("nan")
            lines.append(f"{b[0]:>6}-{min(b[1], 10**6):<7} {s['n']:6d} {len(s['deals']):5d} " + " ".join(f"{s['taken'][N] / s['n']:7.3f}" for N in TOP_NS)
                         + f" | {s['rand_same'][64] / s['n']:6.3f} | {s['rand_full'][64] / s['n']:6.3f} | {bs:.3f}")
        report["strata"][name] = recs
    report["text"] = "\n".join(lines)
    if log:
        log(report["text"])
    return report


def compare(baseline: str | Path, candidate: str | Path, test: str | Path, *, top: int = 64,
            margin: float = -0.02, n_boot: int = 1000, seed: int = 1, log=print) -> dict:
    """Paired non-inferiority read of ``candidate`` against ``baseline`` on the
    same rows: per stratum and bucket, the difference in top-``top`` recall of the
    played action, with a percentile interval from resampling whole DEALS (never
    rows: the decisions of one game are correlated).  ``pass`` = the interval's
    lower bound is above ``margin``.  Refuses metadata without deal ids."""
    d = np.load(str(test) + ".npz"); X = d["X"]
    meta = [json.loads(l) for l in open(str(test) + ".meta.jsonl")]
    if any(not m.get("deal") for m in meta):
        raise PolicyPriorError("compare needs deal ids in the metadata (re-extract with this module)")
    ranked = []
    for ck in (baseline, candidate):
        net, payload = load_prior(ck)
        ranked.append(_rank_rows(predict_log_odds(net, payload, X), meta))
    cells: dict[tuple, dict] = {}
    for ra, rb in zip(*ranked):
        if ra.get("skip") or rb.get("skip"):
            continue
        assert ra["deal"] == rb["deal"] and ra["stratum"] == rb["stratum"]
        c = cells.setdefault((ra["stratum"], ra["bucket"]), {})
        hit = c.setdefault(ra["deal"], [0, 0, 0])      # rows, base hits, cand hits
        hit[0] += 1; hit[1] += ra["r_taken"] < top; hit[2] += rb["r_taken"] < top
    rng = np.random.default_rng(seed)
    report = {"top": top, "margin": margin, "n_boot": n_boot, "cells": []}
    lines = [f"paired deal bootstrap · top{top} recall · candidate − baseline · margin {margin:+.3f} · {n_boot} resamples",
             f"{'stratum':>10} {'bucket':>14} {'rows':>6} {'deals':>6} {'base':>7} {'cand':>7} {'diff':>8} {'lo':>8} {'hi':>8}  verdict"]
    for (stratum, b), deals in sorted(cells.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        arr = np.array(list(deals.values()), dtype=np.float64)        # deals × (rows, base, cand)
        n_rows = arr[:, 0].sum(); base = arr[:, 1].sum() / n_rows; cand = arr[:, 2].sum() / n_rows
        diffs = []
        for _ in range(n_boot):
            pick = arr[rng.integers(0, len(arr), len(arr))]
            diffs.append((pick[:, 2].sum() - pick[:, 1].sum()) / pick[:, 0].sum())
        lo_, hi_ = (float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))) if len(arr) > 1 else (float("nan"), float("nan"))
        ok = bool(lo_ > margin) if len(arr) > 1 else False
        cell = {"stratum": stratum, "bucket": list(b), "rows": int(n_rows), "deals": len(arr), "baseline": base,
                "candidate": cand, "diff": cand - base, "lo": lo_, "hi": hi_, "pass": ok}
        report["cells"].append(cell)
        lines.append(f"{stratum:>10} {b[0]:>6}-{min(b[1], 10**6):<7} {int(n_rows):6d} {len(arr):6d} {base:7.3f} {cand:7.3f} "
                     f"{cand - base:+8.4f} {lo_:+8.4f} {hi_:+8.4f}  {'PASS' if ok else 'not shown'}"
                     + ("" if len(arr) > 1 else " (one deal: no interval)"))
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
    e.add_argument("--chunk-rows", type=int, default=None,
                   help="write a streamable directory of chunks (this many rows each) instead of one npz")
    t = sub.add_parser("train"); t.add_argument("--data", required=True); t.add_argument("--out", required=True)
    t.add_argument("--test"); t.add_argument("--epochs", type=int, default=10); t.add_argument("--listwise-weight", type=float, default=1.0)
    t.add_argument("--lr", type=float, default=1e-3); t.add_argument("--threads", type=int, default=4); t.add_argument("--seed", type=int, default=1)
    v = sub.add_parser("eval"); v.add_argument("--checkpoint", required=True); v.add_argument("--test", required=True)
    c = sub.add_parser("compare"); c.add_argument("--baseline", required=True); c.add_argument("--candidate", required=True)
    c.add_argument("--test", required=True); c.add_argument("--top", type=int, default=64); c.add_argument("--margin", type=float, default=-0.02)
    c.add_argument("--n-boot", type=int, default=1000); c.add_argument("--seed", type=int, default=1)
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    if a.cmd == "extract":
        print(json.dumps(extract(a.out, a.data, lo=a.lo, hi=a.hi, thin=a.thin, max_rows=a.max_rows, workers=a.workers,
                                 seed=a.seed, chunk_rows=a.chunk_rows)))
    elif a.cmd == "train":
        r = train(a.data, a.out, test=a.test, epochs=a.epochs, listwise_weight=a.listwise_weight, lr=a.lr, threads=a.threads, seed=a.seed)
        print(json.dumps({k: v for k, v in r.items() if k != "eval"}))
    elif a.cmd == "eval":
        evaluate(a.checkpoint, a.test)
    else:
        compare(a.baseline, a.candidate, a.test, top=a.top, margin=a.margin, n_boot=a.n_boot, seed=a.seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())

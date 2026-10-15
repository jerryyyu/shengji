"""Human-seat model, offline: self-play policy vs a human-imitation head on human plays.

Question: how much better does a small human-imitation head predict held-out
human plays than the self-play policy head as served?  If production world
weighting (policy-likelihood inference) reads human seats with the self-play
head, its NLL on human actions is the cost of that mis-model.

Data: the production room logs (``rl.replay_log.group_rounds``), every human
play decision (``bot`` false, test-script seats excluded) of a round that
replays to its logged end; rounds tagged as evaluation-only
(``rl.human_shards._refuse_evaluation_round``) are skipped and counted.

Per decision (``extract``):

* the legal set: ``harvest.legal.enumerate_legal`` (serving's cap) with the
  human action and the heuristic anchor forced in;
* the SERVED policy preference of every legal action: the package's policy
  log-odds summed over the action's cards, mean over the served sampler's 64
  worlds (``PVSearchBot._worlds`` and ``PVSearchBot.scores``, the admission's
  own ranking);
* actor-view inputs (``infoset_q.actor_inputs``) and per-action features
  (card counts, ``infoset_q.candidate_features``, heuristic-anchor flag, the
  served preference's rank and mean card level).

Models (``fit``), compared by NLL of the human action under a softmax over the
legal set, cross-validated by ROOM (every round of a room in one fold):

* ``served`` -- softmax of the served preference (temperature 1);
* ``served_t`` -- the same with one temperature fitted on the training folds;
* ``human_lin`` / ``human_mlp`` -- ``t * served + g(state, action)``, a linear or
  small two-layer correction trained on the training folds (early stopping on
  a held-out slice of the training rooms).

Breakdown: ``partner_of_bot`` (the human's partner seat is a bot, which reads the
human as a partner) and ``opponent_of_bot`` (a bot sits next to the human).
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import os
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from ..rl.encode import N_CARDS
from .infoset_q import CAND_DIM, IN_DIM, actor_inputs, candidate_features, card_counts

SCHEMA = "shengji-human-seat-v1"
EXTRA_FEATURES = ("is_anchor", "pref_rank", "mean_level", "pref_centered")
ACT_DIM = N_CARDS + CAND_DIM + len(EXTRA_FEATURES)


class HumanSeatError(ValueError):
    """A log, round or decision this module refuses."""


# ------------------------------------------------------------------ extraction

_BOT = None


def _bot(package: str, sha256: str, seed: int):
    global _BOT
    if _BOT is None:
        from .pv_search_policy import make_pv_search_bot
        _BOT = make_pv_search_bot(package, sha256=sha256, seed=seed,
                                  serving_budget_seconds=None, threads=1)
    return _BOT


def _room_rounds(path: str):
    from ..rl.human_shards import HumanCorpusError, _refuse_evaluation_round
    from ..rl.replay_log import group_rounds
    for round_no, events in sorted(group_rounds(path).items()):
        ref = f"{Path(path).name}:round-{round_no}"
        try:
            _refuse_evaluation_round(events, ref)
        except HumanCorpusError:
            yield round_no, None, "evaluation_round"
            continue
        yield round_no, events, None


def extract_room(path: str, package: str, sha256: str) -> dict:
    """Every accepted human play decision of one room log."""
    from ..ai.heuristic import HeuristicBot
    from ..harvest.legal import enumerate_legal
    from ..rl.replay_log import EXCLUDE_PLAYERS, rebuild_round
    room = Path(path).name
    seed = int(hashlib.sha256(room.encode()).hexdigest()[:8], 16)
    bot = _bot(package, sha256, seed)
    stats = Counter()
    rows = []
    for round_no, events, skip in _room_rounds(path):
        stats["rounds_seen"] += 1
        if skip:
            stats[skip] += 1
            continue
        start = next((e for e in events if e.get("e") == "round_start"), None)
        end = next((e for e in events if e.get("e") == "round_end"), None)
        if start is None or end is None or len(start.get("players") or []) != 4:
            stats["round_incomplete"] += 1
            continue
        players = {int(p["seat"]): p for p in start["players"]}
        is_bot = {s: bool(players[s].get("is_bot")) for s in range(4)}
        excluded = {s for s, p in players.items() if str(p.get("name")) in EXCLUDE_PLAYERS}
        try:
            rnd = rebuild_round(events)
        except Exception:
            stats["round_setup_replay"] += 1
            continue
        if rnd is None:
            stats["round_missing_setup"] += 1
            continue
        pending = []
        failed = False
        for event in events:
            if event.get("e") != "play" or rnd.phase != "play":
                continue
            seat, cards = event.get("seat"), event.get("cards")
            if event.get("bot") is False and seat not in excluded and rnd.turn == seat \
                    and isinstance(cards, list):
                try:
                    pending.append(_decision(bot, rnd, seat, cards, is_bot, room, round_no,
                                             HeuristicBot, enumerate_legal))
                except Exception as exc:
                    stats[f"decision_error:{type(exc).__name__}"] += 1
            try:
                rnd.play(seat, cards)
            except Exception:
                failed = True
                break
        if failed or rnd.phase != "round_end" \
                or rnd.attacker_points != end.get("attacker_points"):
            stats["round_replay_mismatch"] += 1
            continue
        stats["rounds_accepted"] += 1
        stats["decisions"] += len(pending)
        rows.extend(pending)
    return {"room": room, "rows": rows, "stats": dict(stats)}


def _decision(bot, rnd, seat, cards, is_bot, room, round_no, HeuristicBot, enumerate_legal):
    anchor = HeuristicBot.decide_play(bot, rnd, seat)
    legal = enumerate_legal(rnd, seat, cap=bot.cap, must_include=[list(cards), list(anchor)])
    actions = [list(a) for a in legal.actions]
    keys = [tuple(sorted(a)) for a in actions]
    chosen = keys.index(tuple(sorted(cards)))
    anchor_i = keys.index(tuple(sorted(anchor)))
    worlds, _ = bot._worlds(rnd, seat)
    pref = np.asarray(bot.scores(rnd, seat, actions, worlds).mean(axis=0), np.float32)
    order = np.argsort(-pref, kind="stable")
    rank = np.empty(len(pref), np.float32)
    rank[order] = np.arange(len(pref))
    o = rnd.ordering
    feats = np.zeros((len(actions), ACT_DIM), np.float32)
    for j, a in enumerate(actions):
        feats[j, :N_CARDS] = card_counts(a)
        feats[j, N_CARDS:N_CARDS + CAND_DIM] = candidate_features(rnd, seat, a)
        feats[j, N_CARDS + CAND_DIM:] = (
            float(j == anchor_i), math.log1p(rank[j]) / 5.0,
            float(np.mean([o.level(c) for c in a])) / 16.0, 0.0)
    feats[:, -1] = (pref - pref.mean()) / 5.0
    return {
        "room": room, "round": int(round_no), "seat": int(seat),
        "x": actor_inputs(rnd, seat).astype(np.float16), "act": feats, "pref": pref,
        "chosen": int(chosen), "anchor": int(anchor_i),
        "partner_of_bot": bool(is_bot[(seat + 2) % 4]),
        "opponent_of_bot": bool(is_bot[(seat + 1) % 4] or is_bot[(seat + 3) % 4]),
        "leading": bool(not rnd.trick.plays), "trick": len(rnd.history) + 1,
        "legal_count": len(actions), "legal_complete": bool(legal.complete),
    }


def _room_task(args):
    path, package, sha256 = args
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    return extract_room(path, package, sha256)


def extract(logs: Sequence[str], manifest: str | None, out: str, *, package: str, sha256: str,
            workers: int, log=print) -> dict:
    actual = hashlib.sha256(Path(package).read_bytes()).hexdigest()
    if actual != sha256:
        raise HumanSeatError(f"package sha256 {actual} != {sha256}")
    paths = sorted({p for pattern in logs for p in glob.glob(pattern)})
    members = None
    if manifest:
        members = {}
        for line in Path(manifest).read_text().splitlines():
            if line.strip():
                digest, name = line.split()
                members[name] = digest
        paths = [p for p in paths if Path(p).name in members]
        for p in paths:
            if hashlib.sha256(Path(p).read_bytes()).hexdigest() != members[Path(p).name]:
                raise HumanSeatError(f"{p} differs from the snapshot manifest")
    rows, stats = [], Counter()
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for res in pool.map(_room_task, [(p, package, sha256) for p in paths]):
            rows.extend(res["rows"])
            stats.update(res["stats"])
            log(f"[extract] {res['room']} {res['stats'].get('decisions', 0)} "
                f"({time.time() - t0:.0f}s)", flush=True)
    if not rows:
        raise HumanSeatError("no human decisions")
    lens = np.asarray([len(r["pref"]) for r in rows])
    offsets = np.concatenate([[0], np.cumsum(lens)])
    arrays = {
        "X": np.stack([r["x"] for r in rows]),
        "act": np.concatenate([r["act"] for r in rows]).astype(np.float16),
        "pref": np.concatenate([r["pref"] for r in rows]),
        "offsets": offsets.astype(np.int64),
        "chosen": np.asarray([r["chosen"] for r in rows], np.int32),
        "anchor": np.asarray([r["anchor"] for r in rows], np.int32),
        "room": np.asarray([r["room"] for r in rows]),
        "round": np.asarray([r["round"] for r in rows], np.int32),
        "seat": np.asarray([r["seat"] for r in rows], np.int8),
        "partner_of_bot": np.asarray([r["partner_of_bot"] for r in rows]),
        "opponent_of_bot": np.asarray([r["opponent_of_bot"] for r in rows]),
        "leading": np.asarray([r["leading"] for r in rows]),
        "trick": np.asarray([r["trick"] for r in rows], np.int16),
        "legal_complete": np.asarray([r["legal_complete"] for r in rows]),
    }
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, **arrays)
    info = {"schema": SCHEMA, "rows": len(rows), "rooms": int(len(set(arrays["room"]))),
            "stats": dict(stats), "package_sha256": sha256, "manifest": manifest,
            "files": len(paths), "seconds": time.time() - t0,
            "sha256": hashlib.sha256(Path(out).read_bytes()).hexdigest()}
    Path(str(out) + ".json").write_text(json.dumps(info, indent=1))
    return info


# ------------------------------------------------------------------ models

def _segments(offsets: np.ndarray, idx: np.ndarray):
    """Flat action indices and segment ids for the decisions ``idx``."""
    starts, ends = offsets[idx], offsets[idx + 1]
    flat = np.concatenate([np.arange(s, e) for s, e in zip(starts, ends)])
    seg = np.repeat(np.arange(len(idx)), ends - starts)
    return flat, seg, starts


def _local(seg: np.ndarray, chosen: np.ndarray) -> np.ndarray:
    """Positions of the chosen actions inside a flat segment layout."""
    return np.searchsorted(seg, np.arange(len(chosen))) + chosen


def nll_from_logits(logits: np.ndarray, seg: np.ndarray, n: int, chosen_flat: np.ndarray
                    ) -> np.ndarray:
    m = np.full(n, -np.inf)
    np.maximum.at(m, seg, logits)
    z = np.zeros(n)
    np.add.at(z, seg, np.exp(logits - m[seg]))
    return -(logits[chosen_flat] - m - np.log(z))


def fit_temperature(pref, seg, n, chosen_flat) -> float:
    best = (None, 1.0)
    for t in np.exp(np.linspace(np.log(0.05), np.log(5.0), 121)):
        v = nll_from_logits(pref * t, seg, n, chosen_flat).mean()
        if best[0] is None or v < best[0]:
            best = (v, float(t))
    return best[1]


def train_head(data, train_idx, val_idx, *, kind: str, t0: float, epochs: int, lr: float,
               wd: float, seed: int):
    import torch
    torch.manual_seed(seed)
    X = data["X"].astype(np.float32)
    mu = X[train_idx].mean(0)
    sd = X[train_idx].std(0) + 1e-3
    act = data["act"].astype(np.float32)
    pref = data["pref"].astype(np.float32)
    offsets = data["offsets"]
    chosen = data["chosen"]
    nn = torch.nn

    class Head(nn.Module):
        def __init__(self):
            super().__init__()
            self.t = nn.Parameter(torch.tensor(float(t0)))
            if kind == "lin":
                self.g = nn.Linear(ACT_DIM, 1)
                self.s = None
            else:
                self.s = nn.Sequential(nn.Linear(IN_DIM, 64), nn.ReLU())
                self.g = nn.Sequential(nn.Linear(ACT_DIM + 64, 64), nn.ReLU(), nn.Linear(64, 1))
            nn.init.zeros_(self.g[-1].weight if kind != "lin" else self.g.weight)

        def forward(self, xs, a, p, seg):
            if self.s is None:
                h = a
            else:
                h = torch.cat([a, self.s(xs)[seg]], dim=1)
            return self.t * p + self.g(h).squeeze(-1)

    def batch(idx):
        flat, seg, starts = _segments(offsets, idx)
        xs = torch.from_numpy((X[idx] - mu) / sd)
        return (xs, torch.from_numpy(act[flat]), torch.from_numpy(pref[flat]),
                torch.from_numpy(seg),
                torch.from_numpy(np.searchsorted(seg, np.arange(len(idx))) + chosen[idx]),
                len(idx))

    def loss_of(model, b):
        xs, a, p, seg, ch, n = b
        logits = model(xs, a, p, seg)
        m = torch.full((n,), -1e30).scatter_reduce(0, seg, logits, reduce="amax")
        z = torch.zeros(n).index_add(0, seg, torch.exp(logits - m[seg]))
        return -(logits[ch] - m - torch.log(z)), logits

    model = Head()
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=wd)
    rng = np.random.default_rng(seed)
    vb = batch(val_idx)
    best = (math.inf, None, -1)
    for ep in range(epochs):
        perm = rng.permutation(train_idx)
        for s in range(0, len(perm), 128):
            nll, _ = loss_of(model, batch(perm[s:s + 128]))
            opt.zero_grad()
            nll.mean().backward()
            opt.step()
        with torch.no_grad():
            v = float(loss_of(model, vb)[0].mean())
        if v < best[0]:
            best = (v, {k: t.clone() for k, t in model.state_dict().items()}, ep)
    model.load_state_dict(best[1])

    def predict(idx):
        with torch.no_grad():
            nll, _ = loss_of(model, batch(idx))
        return nll.numpy()

    return predict, best[2]


def fit(path: str, out: str, *, folds: int, epochs: int, seed: int, log=print) -> dict:
    import torch
    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "4")))
    z = np.load(path)
    data = {k: z[k] for k in z.files}
    n = len(data["chosen"])
    rooms = data["room"]
    uniq = sorted(set(rooms))
    fold_of_room = {r: int(hashlib.sha256(f"s25|{r}".encode()).hexdigest(), 16) % folds
                    for r in uniq}
    fold = np.asarray([fold_of_room[r] for r in rooms])
    offsets = data["offsets"]
    all_idx = np.arange(n)
    flat, seg, starts = _segments(offsets, all_idx)
    chosen_flat = starts + data["chosen"]
    pref = data["pref"].astype(np.float64)
    nll = {"served": nll_from_logits(pref[flat], seg, n, chosen_flat),
           "uniform": np.log(np.diff(offsets).astype(np.float64)),
           "served_t": np.zeros(n), "human_lin": np.zeros(n), "human_mlp": np.zeros(n)}
    details = []
    for f in range(folds):
        test = all_idx[fold == f]
        train_rooms = [r for r in uniq if fold_of_room[r] != f]
        rng = np.random.default_rng(seed + f)
        val_rooms = set(rng.choice(train_rooms, max(1, len(train_rooms) // 6), replace=False))
        tr = all_idx[(fold != f) & ~np.isin(rooms, list(val_rooms))]
        va = all_idx[(fold != f) & np.isin(rooms, list(val_rooms))]
        trf, trs, trst = _segments(offsets, all_idx[fold != f])
        t = fit_temperature(pref[trf], trs, int((fold != f).sum()),
                            _local(trs, data["chosen"][fold != f]))
        tf, ts, tst = _segments(offsets, test)
        nll["served_t"][test] = nll_from_logits(pref[tf] * t, ts, len(test),
                                                _local(ts, data["chosen"][test]))
        rec = {"fold": f, "test_rows": int(len(test)), "train_rows": int(len(tr)),
               "val_rows": int(len(va)), "temperature": t}
        for kind in ("lin", "mlp"):
            predict, ep = train_head(data, tr, va, kind=kind, t0=t,
                                     epochs=epochs * (4 if kind == "lin" else 1),
                                     lr=3e-3 if kind == "lin" else 1e-3,
                                     wd=1e-3 if kind == "lin" else 1e-2, seed=seed + f)
            nll[f"human_{kind}"][test] = predict(test)
            rec[f"{kind}_best_epoch"] = ep
        details.append(rec)
        log(f"[fit] {json.dumps(rec)} served={nll['served'][test].mean():.4f} "
            f"served_t={nll['served_t'][test].mean():.4f} "
            f"lin={nll['human_lin'][test].mean():.4f} mlp={nll['human_mlp'][test].mean():.4f}",
            flush=True)

    def room_boot(a, b, r, n_boot=2000):
        """Relative NLL gain of ``b`` over ``a`` (1 - b/a), 95% interval by room
        (``r``: each row's room)."""
        names = sorted(set(r))
        sa = np.asarray([a[r == name].sum() for name in names])
        sb = np.asarray([b[r == name].sum() for name in names])
        g = np.random.default_rng(seed)
        vals = []
        for _ in range(n_boot):
            p = g.integers(0, len(names), len(names))
            vals.append(1 - sb[p].sum() / sa[p].sum())
        lo, hi = np.percentile(vals, [2.5, 97.5])
        return float(1 - b.sum() / a.sum()), float(lo), float(hi)

    slices = {"all": np.ones(n, bool), "partner_of_bot": data["partner_of_bot"],
              "opponent_of_bot": data["opponent_of_bot"],
              "partner_bot_only": data["partner_of_bot"] & ~data["opponent_of_bot"],
              "opponent_bot_only": data["opponent_of_bot"] & ~data["partner_of_bot"],
              "lead": data["leading"], "follow": ~data["leading"],
              "nontrivial": np.diff(offsets) > 1}
    table = {}
    for name, sel in slices.items():
        if not sel.any():
            continue
        row = {"n": int(sel.sum()), "rooms": int(len(set(rooms[sel])))}
        for k, v in nll.items():
            row[f"nll_{k}"] = float(v[sel].mean())
        for base in ("served", "served_t"):
            for k in ("human_lin", "human_mlp"):
                row[f"gain_{k}_vs_{base}"] = room_boot(nll[base][sel], nll[k][sel], rooms[sel]) \
                    if len(set(rooms[sel])) > 2 else None
        table[name] = row
    top1 = {}
    flat_pref = pref[flat]
    m = np.full(n, -np.inf)
    np.maximum.at(m, seg, flat_pref)
    top1["served_argmax_hit"] = float(np.mean(flat_pref[chosen_flat] >= m))
    top1["anchor_hit"] = float(np.mean(data["anchor"] == data["chosen"]))
    res = {"schema": SCHEMA + "-fit", "rows": int(n), "rooms": len(uniq), "folds": folds,
           "mean_legal": float(np.diff(offsets).mean()), "details": details, "table": table,
           "top1": top1, "data": path}
    Path(out).write_text(json.dumps(res, indent=1))
    log(json.dumps(table["all"], indent=1))
    return res


def build_parser():
    ap = argparse.ArgumentParser(prog="human_seat", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("extract")
    ex.add_argument("--logs", nargs="+", required=True)
    ex.add_argument("--manifest", default=None)
    ex.add_argument("--out", required=True)
    ex.add_argument("--package", required=True)
    ex.add_argument("--package-sha256", required=True)
    ex.add_argument("--workers", type=int, default=4)
    fi = sub.add_parser("fit")
    fi.add_argument("--data", required=True)
    fi.add_argument("--out", required=True)
    fi.add_argument("--folds", type=int, default=5)
    fi.add_argument("--epochs", type=int, default=30)
    fi.add_argument("--seed", type=int, default=0)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "extract":
        info = extract(args.logs, args.manifest, args.out, package=args.package,
                       sha256=args.package_sha256, workers=args.workers)
        print(json.dumps({k: v for k, v in info.items() if k != "stats"}))
        print(json.dumps(info["stats"]))
        return 0
    if args.command == "fit":
        fit(args.data, args.out, folds=args.folds, epochs=args.epochs, seed=args.seed)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

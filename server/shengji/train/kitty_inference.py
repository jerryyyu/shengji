"""Declaration and kitty inference: per-card marginals from the pre-play actions.

DIAGNOSTIC ONLY, never served.  A small head reads what a non-banker seat knows
when play starts -- its own hand, every declaration in order (who showed what),
the seats that passed, who is banker, the trump suit and rank -- and predicts,
for each card code, the probability that one hidden copy of it is

* in the kitty (``kitty``: the banker's burial, which only the banker saw), and
* in the banker's hand (``banker``: after the kitty pickup and the burial).

Labels are the round's sealed setup (``setup.buried`` and the rebuilt hands).
The loss is the per-copy binomial log-loss over the observer's hidden copies:
``k log p + (h - k) log (1 - p)`` per code, ``h`` the hidden copies and ``k``
those with the receiver.  Two baselines share it: ``uniform`` (every hidden copy
equally likely, ``8 / H`` for the kitty) and ``sampler`` (the served sampler's
play-start marginal: copies `Memory.known` pins to the declarer stay with it,
the rest are uniform over the remaining slots).

Splits are `belief_labels`'s salted deal split, so the test deals are the same
held-out deals `world_weighting` scores.  One round (the cluster's first record)
per deal.

CLI: ``extract`` / ``train`` / ``eval``; ``world_log_weights`` turns a trained
head into per-world log weights for `world_weighting.analyze`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ..ai.memory import Memory
from ..engine.cards import RANKS, SUITS
from ..rl.encode import CARD_INDEX, N_CARDS
from .belief_labels import cluster_paths, excluded_windows, seed_excluded, split_of
from .data import deal_key

SCHEMA = "shengji-kitty-inference-v1"
CALIB, TEST = 0.06, 0.12
KITTY_SIZE = 8
#: (name, width) of the input row
FEATURE_BLOCKS: tuple[tuple[str, int], ...] = (
    ("own_hand", N_CARDS),
    ("hidden", N_CARDS),
    ("declared_rel", 4 * N_CARDS),
    ("declarations_rel", 4),
    ("first_declarer_rel", 4),
    ("final_declarer_rel", 4),
    ("n_declarations", 1),
    ("passed_rel", 4),
    ("banker_rel", 4),
    ("trump_suit", len(SUITS) + 1),
    ("trump_rank", len(RANKS)),
)
FEATURE_DIM = sum(w for _, w in FEATURE_BLOCKS)
HEADS = ("kitty", "banker")


class KittyInferenceError(ValueError):
    pass


def _counts(cards) -> np.ndarray:
    out = np.zeros(N_CARDS, np.float32)
    for card in cards:
        out[CARD_INDEX[card]] += 1.0
    return out


def features(start, seat: int, setup: Mapping[str, Any]) -> np.ndarray:
    """The observer's pre-play row (``FEATURE_BLOCKS`` order).  ``start`` is the
    round at its first play; only public facts and ``seat``'s own hand are read."""
    mem = Memory(start, seat, own_kitty=True)
    hidden = np.zeros(N_CARDS, np.float32)
    for code, n in mem.unseen.items():
        hidden[CARD_INDEX[code]] = n
    declared = np.zeros((4, N_CARDS), np.float32)
    per_seat = np.zeros(4, np.float32)
    first = np.zeros(4, np.float32)
    final = np.zeros(4, np.float32)
    decls = list(setup.get("declarations") or [])
    for i, d in enumerate(decls):
        rel = (int(d["seat"]) - seat) % 4
        declared[rel] = np.maximum(declared[rel], _counts(d["cards"]))
        per_seat[rel] += 1
        if i == 0:
            first[rel] = 1
    if decls:
        final[(int(decls[-1]["seat"]) - seat) % 4] = 1
    passed = np.zeros(4, np.float32)
    for s in setup.get("passed") or []:
        passed[(int(s) - seat) % 4] = 1
    banker = np.zeros(4, np.float32)
    banker[(int(start.banker) - seat) % 4] = 1
    suit = np.zeros(len(SUITS) + 1, np.float32)
    if start.trump_is_nt or start.trump_suit is None:
        suit[-1] = 1
    else:
        suit[SUITS.index(start.trump_suit)] = 1
    rank = np.zeros(len(RANKS), np.float32)
    rank[RANKS.index(str(start.trump_rank))] = 1
    x = np.concatenate([_counts(start.hands[seat]) / 2, hidden / 2, declared.ravel() / 2,
                        np.minimum(per_seat, 4) / 4, first, final,
                        [min(len(decls), 8) / 8], passed, banker, suit, rank]).astype(np.float32)
    if x.shape != (FEATURE_DIM,):
        raise KittyInferenceError(f"feature width {x.shape[0]} != {FEATURE_DIM}")
    return x


def labels(start, seat: int) -> dict[str, np.ndarray]:
    """``hidden``, ``kitty`` and ``banker`` copy counts per code (int8), and the
    sampler's play-start marginals ``p_sampler_kitty`` / ``p_sampler_banker``."""
    mem = Memory(start, seat, own_kitty=True)
    hidden = np.zeros(N_CARDS, np.int8)
    for code, n in mem.unseen.items():
        hidden[CARD_INDEX[code]] = n
    kitty = _counts(start.buried).astype(np.int8)
    banker = _counts(start.hands[start.banker]).astype(np.int8)
    if np.any(kitty > hidden) or np.any(banker > hidden):
        raise KittyInferenceError("a label copy is not hidden")
    pinned = {s: np.zeros(N_CARDS) for s in range(4)}
    for code, (holder, copies) in mem.known.items():
        if holder != seat:
            pinned[holder][CARD_INDEX[code]] += copies
    pin_total = sum(p for p in pinned.values())
    free = hidden - pin_total
    slots_kitty = KITTY_SIZE
    slots_banker = len(start.hands[start.banker]) - pinned[start.banker].sum()
    free_total = max(1.0, free.sum())
    with np.errstate(invalid="ignore", divide="ignore"):
        pk = np.where(hidden > 0, free * slots_kitty / free_total / np.maximum(hidden, 1), 0.0)
        pb = np.where(hidden > 0, (free * slots_banker / free_total + pinned[start.banker])
                      / np.maximum(hidden, 1), 0.0)
    return {"hidden": hidden, "kitty": kitty, "banker": banker,
            "p_sampler_kitty": pk.astype(np.float32), "p_sampler_banker": pb.astype(np.float32)}


# ------------------------------------------------------------------ extraction

def _first_record(path: Path) -> dict | None:
    with open(path) as fh:
        line = fh.readline()
    return json.loads(line) if line.strip() else None


def _extract_task(args: tuple) -> dict:
    from ..harvest.rebuild import round_from_setup
    paths, out_dir, name, windows = args
    rows: dict[str, dict[str, list]] = {s: {} for s in ("train", "calib", "test")}
    failed = 0
    for path in paths:
        try:
            rec = _first_record(Path(path))
            if rec is None or seed_excluded(rec.get("round_seed"), windows):
                continue
            deck = list(rec["deck"])
            setup = rec["setup"]
            split = split_of(deal_key(deck), CALIB, TEST)
            start = round_from_setup(deck, setup)
            for seat in range(4):
                if seat == start.banker:
                    continue
                lab = labels(start, seat)
                bucket = rows[split]
                for k, v in (("X", features(start, seat, setup)), ("role", np.int8((start.banker - seat) % 2 == 0)),
                             *lab.items()):
                    bucket.setdefault(k, []).append(v)
        except Exception:                      # counted; one bad record never stops a chunk
            failed += 1
    files = {}
    for split, bucket in rows.items():
        if not bucket:
            continue
        arrays = {k: np.stack(v) for k, v in bucket.items()}
        file = Path(out_dir) / f"{split}-{name}.npz"
        np.savez_compressed(file, **arrays)
        files[split] = {"file": file.name, "rows": int(arrays["X"].shape[0]),
                        "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
    return {"chunk": name, "files": files, "failed": failed}


def extract(stores: Sequence[str], out: str, *, stride: int, workers: int, task_clusters: int = 2000,
            log=print) -> dict:
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=False)
    windows = excluded_windows()
    tasks = []
    for si, store in enumerate(stores):
        paths = cluster_paths(store)[::stride]
        for start in range(0, len(paths), task_clusters):
            tasks.append(([str(p) for p in paths[start:start + task_clusters]], str(out_dir),
                          f"s{si:02d}-{start // task_clusters:04d}", windows))
    manifest: dict[str, Any] = {"schema": SCHEMA, "stores": list(stores), "stride": stride,
                                "feature_dim": FEATURE_DIM, "feature_blocks": FEATURE_BLOCKS,
                                "split": {"calib": CALIB, "test": TEST}, "chunks": []}
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, res in enumerate(pool.map(_extract_task, tasks)):
            manifest["chunks"].append(res)
            if (i + 1) % 10 == 0 or i + 1 == len(tasks):
                log(f"[extract] {i + 1}/{len(tasks)} {time.time() - t0:.0f}s", flush=True)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1, default=list))
    return manifest


def load_split(out: str, split: str) -> dict[str, np.ndarray]:
    out_dir = Path(out)
    manifest = json.loads((out_dir / "manifest.json").read_text())
    parts = []
    for chunk in manifest["chunks"]:
        entry = chunk["files"].get(split)
        if not entry:
            continue
        path = out_dir / entry["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise KittyInferenceError(f"{path}: sha256 mismatch")
        with np.load(path) as z:
            parts.append({k: z[k] for k in z.files})
    if not parts:
        raise KittyInferenceError(f"split {split} is empty")
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}


# ------------------------------------------------------------------ loss

def copy_log_loss(p: np.ndarray, k: np.ndarray, h: np.ndarray, floor: float = 1e-6) -> np.ndarray:
    """Per-row binomial log-loss per hidden copy (nats)."""
    p = np.clip(np.asarray(p, np.float64), floor, 1 - floor)
    k = k.astype(np.float64)
    h = h.astype(np.float64)
    ll = k * np.log(p) + (h - k) * np.log1p(-p)
    return -ll.sum(axis=1) / np.maximum(h.sum(axis=1), 1)


def in_receiver_log_loss(p: np.ndarray, k: np.ndarray, floor: float = 1e-6) -> np.ndarray:
    """Per-row mean ``-log p`` over the copies that ARE with the receiver."""
    p = np.clip(np.asarray(p, np.float64), floor, 1.0)
    k = k.astype(np.float64)
    return -(k * np.log(p)).sum(axis=1) / np.maximum(k.sum(axis=1), 1)


def uniform_p(h: np.ndarray, slots: np.ndarray) -> np.ndarray:
    tot = np.maximum(h.sum(axis=1, keepdims=True), 1)
    return np.where(h > 0, slots[:, None] / tot, 0.0)


# ------------------------------------------------------------------ model

def build_model(hidden: Sequence[int] = (256, 256)):
    import torch
    layers: list = []
    din = FEATURE_DIM
    for h in hidden:
        layers += [torch.nn.Linear(din, int(h)), torch.nn.GELU()]
        din = int(h)
    layers.append(torch.nn.Linear(din, len(HEADS) * N_CARDS))
    return torch.nn.Sequential(*layers)


def _torch_loss(logits, k, h):
    import torch
    lp = torch.nn.functional.logsigmoid(logits)
    lq = torch.nn.functional.logsigmoid(-logits)
    ll = k * lp + (h - k) * lq
    return -(ll.sum(1) / h.sum(1).clamp(min=1)).mean()


def predict(model, X: np.ndarray, batch: int = 8192) -> np.ndarray:
    """``(n, 2, 54)`` per-copy probabilities (kitty, banker)."""
    import torch
    out = []
    model.eval()
    with torch.no_grad():
        for i in range(0, len(X), batch):
            z = model(torch.as_tensor(X[i:i + batch], dtype=torch.float32))
            out.append(torch.sigmoid(z).numpy().reshape(-1, len(HEADS), N_CARDS))
    return np.concatenate(out).astype(np.float64)


def evaluate_split(model, d: Mapping[str, np.ndarray]) -> dict:
    p = predict(model, d["X"])
    h = d["hidden"]
    report: dict[str, Any] = {"rows": int(len(h))}
    slots = {"kitty": np.full(len(h), float(KITTY_SIZE)),
             "banker": d["banker"].sum(axis=1).astype(np.float64)}
    for j, head in enumerate(HEADS):
        k = d[head]
        arms = {"uniform": uniform_p(h, slots[head]), "sampler": d[f"p_sampler_{head}"],
                "head": np.where(h > 0, p[:, j], 0.0)}
        block: dict[str, Any] = {}
        for name, pa in arms.items():
            block[name] = {"copy_log_loss": float(copy_log_loss(pa, k, h).mean()),
                           "in_receiver_log_loss": float(in_receiver_log_loss(pa, k).mean())}
        for base in ("uniform", "sampler"):
            b = block[base]["copy_log_loss"]
            block[f"gain_vs_{base}"] = (b - block["head"]["copy_log_loss"]) / b
            bi = block[base]["in_receiver_log_loss"]
            block[f"in_receiver_gain_vs_{base}"] = (bi - block["head"]["in_receiver_log_loss"]) / bi
        for r, name in ((0, "defender"), (1, "banker_partner")):
            m = d["role"] == r
            if m.any():
                bu = copy_log_loss(arms["uniform"][m], k[m], h[m]).mean()
                bh = copy_log_loss(arms["head"][m], k[m], h[m]).mean()
                block[f"gain_vs_uniform_{name}"] = float((bu - bh) / bu)
        report[head] = block
    return report


def train(data: str, out: str, *, epochs: int = 8, batch: int = 512, lr: float = 1e-3,
          threads: int = 4, seed: int = 0, log=print) -> dict:
    import torch
    torch.set_num_threads(threads)
    torch.manual_seed(seed)
    tr = load_split(data, "train")
    ca = load_split(data, "calib")
    X = torch.as_tensor(tr["X"], dtype=torch.float32)
    K = torch.as_tensor(np.concatenate([tr["kitty"], tr["banker"]], 1), dtype=torch.float32)
    H = torch.as_tensor(np.concatenate([tr["hidden"], tr["hidden"]], 1), dtype=torch.float32)
    model = build_model()
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    best, best_state, history = math.inf, None, []
    n = len(X)
    for epoch in range(epochs):
        model.train()
        perm = torch.randperm(n)
        tot = 0.0
        for i in range(0, n, batch):
            idx = perm[i:i + batch]
            loss = _torch_loss(model(X[idx]), K[idx], H[idx])
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += float(loss) * len(idx)
        cal = evaluate_split(model, ca)
        val = cal["kitty"]["head"]["copy_log_loss"] + cal["banker"]["head"]["copy_log_loss"]
        history.append({"epoch": epoch, "train_loss": tot / n, "calib_kitty": cal["kitty"]["head"],
                        "calib_banker": cal["banker"]["head"], "calib_sum": val})
        log(json.dumps(history[-1]), flush=True)
        if val < best:
            best = val
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    payload = {"schema": SCHEMA, "feature_dim": FEATURE_DIM, "hidden": [256, 256],
               "history": history, "train_rows": n, "data": str(data)}
    torch.save({"state_dict": model.state_dict(), "payload": payload}, out)
    return payload


def load_head(path: str):
    import torch
    blob = torch.load(path, map_location="cpu", weights_only=False)
    model = build_model(blob["payload"]["hidden"])
    model.load_state_dict(blob["state_dict"])
    model.eval()
    return model


def world_log_weights(checkpoint: str, data: Mapping[str, np.ndarray]) -> np.ndarray:
    """``(S, W)`` log weights of a `world_weighting` collection under the kitty
    head: ``sum over the world's kitty copies of log p_kitty(card)`` for states
    whose kitty is hidden, zero elsewhere.  The uniform proposal's per-copy
    probability is the same for every unpinned copy and every world holds eight,
    so it cancels in the normalised weights."""
    model = load_head(checkpoint)
    p = predict(model, data["kitty_x"].astype(np.float32))[:, 0, :]
    kitty = data["counts"][:, :, 3, :].astype(np.float64)
    lw = np.einsum("swc,sc->sw", kitty, np.log(np.clip(p, 1e-6, 1.0)))
    from .world_weighting import META_COLS
    hidden = data["meta"][:, META_COLS.index("kitty_hidden")] == 1
    return np.where(hidden[:, None], lw, 0.0)


# ------------------------------------------------------------------ CLI

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="kitty_inference", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("extract")
    ex.add_argument("--store", action="append", required=True)
    ex.add_argument("--out", required=True)
    ex.add_argument("--stride", type=int, default=1)
    ex.add_argument("--workers", type=int, default=4)
    tr = sub.add_parser("train")
    tr.add_argument("--data", required=True)
    tr.add_argument("--out", required=True)
    tr.add_argument("--epochs", type=int, default=8)
    tr.add_argument("--threads", type=int, default=4)
    ev = sub.add_parser("eval")
    ev.add_argument("--data", required=True)
    ev.add_argument("--checkpoint", required=True)
    ev.add_argument("--split", default="test")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "extract":
        m = extract(args.store, args.out, stride=args.stride, workers=args.workers)
        rows = {s: sum(c["files"].get(s, {}).get("rows", 0) for c in m["chunks"])
                for s in ("train", "calib", "test")}
        print(json.dumps({"rows": rows, "failed": sum(c["failed"] for c in m["chunks"])}))
        return 0
    if args.command == "train":
        payload = train(args.data, args.out, epochs=args.epochs, threads=args.threads)
        print(json.dumps(payload["history"][-1]))
        return 0
    if args.command == "eval":
        rep = evaluate_split(load_head(args.checkpoint), load_split(args.data, args.split))
        print(json.dumps(rep, indent=1))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

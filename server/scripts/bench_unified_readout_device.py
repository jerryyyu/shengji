#!/usr/bin/env python3
"""Throughput of `train.unified_readout` on a device: the trainer's own step (``train``) or the polish step
(``polish``), timed in parts so a GPU run shows whether the loader feeds it.

``train`` runs the trainer's step (the same model, optimizer groups, losses and clipping as
``unified_readout train``) on the trainer's ``Stream``; per step it records the wait for the next batch
(loader), the leaf build (``leaf_batch``, main thread), the host-to-device copy, and forward + backward +
optimizer step (synchronised).  ``polish`` does the same for the polish step on a cache shard; a step that
loads a shard is charged the load, and the reported wall interval starts before it.  The polish step is the
default recipe (``POLISH_RECIPE``), so a polish timing speaks for that recipe only.  Nothing is written but
``--out`` (one JSON object per run); no checkpoint, no lock.

    python scripts/bench_unified_readout_device.py train --data DIR... --init-readout-ckpt CKPT \\
        --device mps --threads 4 --rounds-per-batch 16 --steps 20
    python scripts/bench_unified_readout_device.py polish --ckpt CKPT --cache CACHE_DIR --device mps --batch 4096
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shengji.train import belief_seq as bs  # noqa: E402
from shengji.train import unified_readout as ur  # noqa: E402
from shengji.train import unified_seq as us  # noqa: E402


#: the polish step the bench times: ``unified_readout polish``'s defaults at a fixed learning rate (no cosine
#: schedule).  A timing holds for this recipe; another ``--lr``, weight decay or reply weight is not measured.
POLISH_RECIPE = {"lr": 1e-3, "weight_decay": 0.01, "reply_weight": 0.2, "clip": 1.0}


def _sync(device):
    import torch
    if device.type == "mps":
        torch.mps.synchronize()


def _model(args):
    import torch
    if args.init_readout_ckpt:
        model, _ = ur.load_checkpoint(args.init_readout_ckpt)
        model.train()
        return model, "readout-ckpt:" + args.init_readout_ckpt
    arch = dict(bs.DEFAULT_ARCH)
    for item in (args.scratch_arch or "").split(","):
        if item:
            k, v = item.split("=")
            arch[k] = type(arch[k])(int(v))
    torch.manual_seed(args.seed)
    return ur.build(arch), "scratch:" + json.dumps(arch, sort_keys=True)


def _summary(rec, n_items, label, wall):
    import torch
    mem = {"mps_driver_gib": round(torch.mps.driver_allocated_memory() / 2**30, 2)} if torch.backends.mps.is_available() else {}
    parts = {k: float(np.sum(v)) for k, v in rec.items()}
    total = sum(parts.values())
    return {"steps": len(rec["compute"]), label: int(n_items), f"{label}_per_s": n_items / wall, "wall_s": wall,
            "step_s_median": float(np.median(np.sum([rec[k] for k in rec], 0))),
            "step_s_p90": float(np.percentile(np.sum([rec[k] for k in rec], 0), 90)),
            "share": {k: round(v / total, 4) for k, v in parts.items()}, **mem}


def bench_train(args) -> dict:
    import torch
    torch.set_num_threads(args.threads)
    device = ur._device(args.device)
    model, init = _model(args)
    if device.type != "cpu":
        model.to(device)
    groups = [{"params": list(model.trunk.parameters()), "lr": args.lr},
              {"params": list(model.q_head.parameters()) + list(model.p_head.parameters()), "lr": args.head_lr},
              {"params": list(model.readout.parameters()), "lr": args.readout_lr}]
    opt = torch.optim.AdamW(groups, weight_decay=0.01)
    index = us.OutcomeIndex(us.parse_store_map(args.store_map))
    entries = us.entries_for(args.data, "train", exclude_seed_windows=args.exclude_seed_window)
    if args.max_chunks:
        entries = entries[:args.max_chunks]
    stream = us.Stream(entries, index=index, suit_aug=False, verified=bs._Verified(), threads=args.loader_threads,
                       buffer_chunks=args.buffer_chunks, rounds_per_batch=args.rounds_per_batch, row_frac=1.0)
    rec = {k: [] for k in ("loader_wait", "leaf_batch", "to_device", "compute")}
    rows = leaves = 0
    it = stream.batches(args.seed, 0, 0)
    step = 0
    t_start = None
    while step < args.warmup + args.steps:
        t0 = time.perf_counter()
        try:
            _, b = next(it)
        except StopIteration:
            step = -1 if step < args.warmup + 1 else step
            break
        t1 = time.perf_counter()
        for k, v in ur.leaf_batch(b).items():
            b["leaf_" + k] = v
        t2 = time.perf_counter()
        tb = us.to_device(b, device)
        _sync(device)
        t3 = time.perf_counter()
        L = ur.losses(model, tb)
        m = ur.means([L[k] for k in ur.SUM_KEYS])
        opt.zero_grad()
        (m["belief"] + m["q"] + 0.2 * m["policy"] + m["leaf_value"] + 0.2 * m["reply"]).backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        sums = [float(L[k].detach()) for k in ur.SUM_KEYS]          # the trainer's per-step read (a sync)
        t4 = time.perf_counter()
        if not all(np.isfinite(sums)):
            raise SystemExit(f"non-finite loss at step {step}: {sums}")
        if step == args.warmup:
            t_start = t0
        if step >= args.warmup:
            for k, v in zip(rec, (t1 - t0, t2 - t1, t3 - t2, t4 - t3)):
                rec[k].append(v)
            rows += len(b["X"])
            leaves += len(b["leaf_row"])
        step += 1
    if step < 0 or not rec["compute"]:
        raise SystemExit("the data ran out before the timed steps: add data or lower --warmup/--steps")
    wall = time.perf_counter() - t_start
    out = _summary(rec, rows, "rows", wall)
    out.update({"mode": "train", "device": args.device, "threads": args.threads, "loader_threads": args.loader_threads,
                "rounds_per_batch": args.rounds_per_batch, "buffer_chunks": args.buffer_chunks, "leaves": int(leaves),
                "rows_per_step": rows / len(rec["compute"]), "init": init,
                "params": sum(p.numel() for p in model.parameters())})
    return out


def bench_polish(args) -> dict:
    import torch
    torch.set_num_threads(args.threads)
    device = ur._device(args.device)
    model, _ = ur.load_checkpoint(args.ckpt)
    if device.type != "cpu":
        model.to(device)
    readout = model.readout
    readout.train()
    body = [p for n, p in readout.named_parameters() if n.startswith(ur.BODY_PREFIXES)]
    opt = torch.optim.AdamW(body, lr=POLISH_RECIPE["lr"], weight_decay=POLISH_RECIPE["weight_decay"])
    shards = sorted(Path(args.cache).glob("train-*.npz"))
    if not shards:
        raise SystemExit(f"no train-*.npz shards in {args.cache}")
    rng = np.random.default_rng(args.seed)
    rec = {k: [] for k in ("shard_load", "gather_to_device", "compute")}
    n_leaves, step, t_start = 0, 0, None
    while step < args.warmup + args.steps:
        pass_start = step
        for si in rng.permutation(len(shards)):
            t0 = time.perf_counter()
            z = np.load(shards[si])
            z = {k: z[k] for k in z.files}
            order = rng.permutation(len(z["leaf_row"]))
            load = time.perf_counter() - t0
            for i in range(0, len(order), args.batch):
                t1 = time.perf_counter()
                step_start = t1 - load            # a step's interval includes the shard load it is charged
                t = ur._polish_tensors(z, np.sort(order[i:i + args.batch]), device)
                _sync(device)
                t2 = time.perf_counter()
                v, r, end, has = ur.polish_losses(readout, t)
                loss = v.mean() + POLISH_RECIPE["reply_weight"] * r.sum() / has.float().sum().clamp_min(1.0)
                opt.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(body, POLISH_RECIPE["clip"])
                opt.step()
                vals = [float(v.sum().detach()), float(r.sum().detach())]       # the polish's per-step read
                t3 = time.perf_counter()
                if not all(np.isfinite(vals)):
                    raise SystemExit(f"non-finite loss at step {step}")
                if step == args.warmup:
                    t_start = step_start
                if step >= args.warmup:
                    rec["shard_load"].append(load)
                    rec["gather_to_device"].append(t2 - t1)
                    rec["compute"].append(t3 - t2)
                    n_leaves += len(v)
                load = 0.0
                step += 1
                if step >= args.warmup + args.steps:
                    break
            if step >= args.warmup + args.steps:
                break
        if step == pass_start:
            raise SystemExit(f"a pass over the {len(shards)} shards of {args.cache} yielded no batch: every shard is empty")
    wall = time.perf_counter() - t_start
    out = _summary(rec, n_leaves, "leaves", wall)
    out.update({"mode": "polish", "device": args.device, "threads": args.threads, "batch": args.batch,
                "body_params": sum(p.numel() for p in body), "recipe": POLISH_RECIPE})
    return out


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="bench_unified_readout_device")
    sub = ap.add_subparsers(dest="mode", required=True)
    t = sub.add_parser("train")
    t.add_argument("--data", nargs="+", required=True)
    t.add_argument("--init-readout-ckpt", default=None)
    t.add_argument("--scratch-arch", default=None)
    t.add_argument("--store-map", action="append", default=[])
    t.add_argument("--exclude-seed-window", type=bs.seed_window, action="append", default=[])
    t.add_argument("--max-chunks", type=int, default=None)
    t.add_argument("--rounds-per-batch", type=int, default=16)
    t.add_argument("--buffer-chunks", type=int, default=24)
    t.add_argument("--loader-threads", type=int, default=4)
    t.add_argument("--lr", type=float, default=3e-5)
    t.add_argument("--head-lr", type=float, default=9e-5)
    t.add_argument("--readout-lr", type=float, default=1e-3)
    p = sub.add_parser("polish")
    p.add_argument("--ckpt", required=True)
    p.add_argument("--cache", required=True)
    p.add_argument("--batch", type=int, default=4096)
    for x in (t, p):
        x.add_argument("--device", choices=("cpu", "mps"), default="cpu")
        x.add_argument("--threads", type=int, default=4)
        x.add_argument("--steps", type=int, default=20)
        x.add_argument("--warmup", type=int, default=3)
        x.add_argument("--seed", type=int, default=1)
        x.add_argument("--out", default=None, help="append the result (one JSON line) here")
    return ap


def _check_counts(ap, args) -> None:
    if args.steps < 1:
        ap.error(f"--steps {args.steps}: must be positive")
    if args.warmup < 0:
        ap.error(f"--warmup {args.warmup}: must not be negative")
    if getattr(args, "batch", 1) < 1:
        ap.error(f"--batch {args.batch}: must be positive")
    if getattr(args, "rounds_per_batch", 1) < 1:
        ap.error(f"--rounds-per-batch {args.rounds_per_batch}: must be positive")


def main(argv=None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    _check_counts(ap, args)
    res = (bench_train if args.mode == "train" else bench_polish)(args)
    line = json.dumps(res)
    print(line, flush=True)
    if args.out:
        with open(args.out, "a") as fh:
            fh.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

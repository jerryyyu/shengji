#!/usr/bin/env python3
"""Train-step time of ``belief_seq`` per speed mode on one fixed synthetic batch.

The batch has the S46 bench shape (R rounds, T plies, B rows; default 16, 86,
545) and the model the S46 config (d192, 4 encoder + 4 cross-attention layers).
Each mode builds the same seeded model, runs ``--warmup`` steps (compile happens
there), then times ``--steps`` full AdamW steps.  ``loss0`` is the first step's
loss: every mode starts from the same weights, so its relative difference to
``base`` is the fixed-batch numerics witness (fp32 modes ~1e-6, bf16 ~1e-3).

usage: python scripts/bench_belief_seq_step.py --threads 16 --steps 40 [--src SERVER_DIR]
       [--modes base,grouped,grouped+bf16,grouped+compile,grouped+bf16+compile] [--out-json F]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

MODES = ("base", "grouped", "bf16", "grouped+bf16", "compile", "grouped+compile",
         "grouped+bf16+compile")


def synthetic_batch(bs, R: int, T: int, B: int):
    import numpy as np
    from shengji.train.belief_history import N_CARD_FEATURES, N_TOKEN_FLOAT
    from shengji.train.belief_labels import FEATURE_DIM, N_RECV
    rng = np.random.default_rng(0)
    b = {"tok_int": np.stack([rng.integers(0, 4, (R, T)), rng.integers(0, 4, (R, T)),
                              rng.integers(0, 25, (R, T)), rng.integers(0, 5, (R, T))], -1),
         "tok_f": rng.random((R, T, N_TOKEN_FLOAT), dtype=np.float32),
         "tok_cards": (rng.random((R, T, 54)) < 0.03).astype(np.float32),
         "tok_att": (rng.random((R, T, 54)) < 0.03).astype(np.float32),
         "card_feat": rng.random((R, 54, N_CARD_FEATURES), dtype=np.float32),
         "banker": rng.integers(0, 4, R),
         "X": rng.random((B, FEATURE_DIM + 4), dtype=np.float32),
         "row_card": rng.random((B, 54, bs.N_ROW_CARD), dtype=np.float32),
         "M": rng.random((B, 54, N_RECV)) < 0.6,
         "rr": np.sort(rng.integers(0, R, B)), "seat": rng.integers(0, 4, B),
         "ply": rng.integers(0, T, B)}
    b["M"][..., 0] = True
    b["Y"] = (b["M"] & (rng.random((B, 54, N_RECV)) < 0.2)).astype(np.float32)
    return bs.to_torch(b)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", default=str(Path(__file__).resolve().parents[1]),
                    help="the server/ dir whose shengji.train.belief_seq is timed")
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--steps", type=int, default=5)
    ap.add_argument("--warmup", type=int, default=2)
    ap.add_argument("--modes", default="base,grouped,grouped+bf16,grouped+compile,grouped+bf16+compile")
    ap.add_argument("--shape", default="16,86,545", help="R,T,B")
    ap.add_argument("--model", default="192,4,4,4,256", help="d,heads,enc_layers,xattn_layers,x_hidden")
    ap.add_argument("--out-json", default=None)
    a = ap.parse_args(argv)
    sys.path.insert(0, a.src)
    import torch
    from shengji.train import belief_seq as bs
    torch.set_num_threads(a.threads)
    R, T, B = (int(x) for x in a.shape.split(","))
    d, heads, enc, xl, xh = (int(x) for x in a.model.split(","))
    tb = synthetic_batch(bs, R, T, B)
    modes = a.modes.split(",")
    for m in modes:
        if m not in MODES:
            raise SystemExit(f"unknown mode {m}; one of {MODES}")
    res = {"src": a.src, "belief_seq": bs.__file__, "torch": torch.__version__,
           "cpu_capability": torch.backends.cpu.get_cpu_capability(), "threads": a.threads,
           "steps": a.steps, "warmup": a.warmup, "shape": [R, T, B], "model": [d, heads, enc, xl, xh],
           "modes": {}}
    for mode in modes:
        parts = set(mode.split("+"))
        torch.manual_seed(0)
        model = bs.build_model(d=d, heads=heads, enc_layers=enc, xattn_layers=xl, x_hidden=xh,
                               card_self_attn=True)
        model.train()
        flags = argparse.Namespace(grouped_xattn="grouped" in parts, bf16="bf16" in parts,
                                   compile="compile" in parts)
        fwd, bf16 = bs.apply_speed_flags(model, flags)
        opt = torch.optim.AdamW(model.parameters(), lr=5e-4, weight_decay=0.01)

        def step():
            loss, n = bs.batch_loss(fwd, tb, bf16=bf16)
            opt.zero_grad()
            (loss / n.clamp_min(1.0)).backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            return float(loss.detach() / n)

        t0 = time.perf_counter()
        loss0 = step()
        for _ in range(a.warmup - 1):
            step()
        warm_s = time.perf_counter() - t0
        times = []
        for _ in range(a.steps):
            t1 = time.perf_counter()
            step()
            times.append(time.perf_counter() - t1)
        times.sort()
        r = {"step_s_mean": sum(times) / len(times), "step_s_median": times[len(times) // 2],
             "warmup_s": warm_s, "loss0": loss0, "rows_per_s": B * len(times) / sum(times)}
        res["modes"][mode] = r
        print(f"{mode:24s} step {r['step_s_mean']:.4f} s (median {r['step_s_median']:.4f}) "
              f"warmup {warm_s:.1f} s loss0 {loss0:.6f}", flush=True)
    if "base" in res["modes"]:
        b0 = res["modes"]["base"]
        for mode, r in res["modes"].items():
            r["speedup_vs_base"] = b0["step_s_mean"] / r["step_s_mean"]
            r["loss0_rel_vs_base"] = abs(r["loss0"] - b0["loss0"]) / abs(b0["loss0"])
        print("\n| mode | step s | speedup vs base | loss0 rel diff |\n|---|---:|---:|---:|")
        for mode, r in res["modes"].items():
            print(f"| {mode} | {r['step_s_mean']:.4f} | {r['speedup_vs_base']:.3f}x | "
                  f"{r['loss0_rel_vs_base']:.1e} |")
    if a.out_json:
        Path(a.out_json).write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

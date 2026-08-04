"""Train an absolute action-value output on the provisional high-N labels.

An earlier selected, non-strict prototype suggested that mc(N=10) forfeited
about 2.8 raw points per consequential decision against its 240-world labels.
That is a label-quality hypothesis, not a measured global ceiling.

The target is the ABSOLUTE 240-world mean — the expected outcome of playing a
candidate when the heuristic finishes the round, from the acting team's
perspective. It is `Q^H(s,a)` in raw points: deliberately not `max_a Q`, but
also not signed level utility or a generic state value.

Why absolute scale matters, concretely: v11pair learned only WITHIN-decision
differences, so adding any per-state constant left its loss unchanged. Its
cross-state scale was never identified, which is why using it as a leaf
evaluator was invalid. These labels identify a scale only on their own state,
ballot, perspective, and continuation-policy distribution; they do not by
themselves make a valid leaf evaluator.

Warm-started from a checkpoint whose value output is already absolute-scaled
(v7w). Despite the historical description “fit the head,” the optimizer below
updates the shared trunk and value head; only the unused policy head receives
no gradient.

Rows are weighted by inverse variance, so states the reference resolved
sharply count for more than noisy ones.

    uv run python scripts/highn_train.py OUT_CKPT [epochs] [--init CKPT]
"""
from __future__ import annotations

import glob
import os
import sys
import time

import numpy as np

sys.path.insert(0, ".")

DATA = "rl_data/highn_enc"
VAL_SHARDS = 2          # held out; never trained on


def load(paths):
    obs, acts, offs, val, wt = [], [], [], [], []
    base = 0
    for p in paths:
        d = np.load(p)
        obs.append(d["obs"])
        acts.append(d["actions"])
        offs.append(d["offsets"][:-1] + base)
        base += len(d["value"])
        val.append(d["value"])
        wt.append(d["weight"])
    starts = np.concatenate(offs)
    return (np.concatenate(obs), np.concatenate(acts), starts,
            np.concatenate(val), np.concatenate(wt))


def main() -> None:
    import torch

    from shengji.rl.model import load_any_net

    out = sys.argv[1] if len(sys.argv) > 1 else "ckpt_v13abs.pt"
    epochs = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 6
    init = "snapshots_v7w/ep02.pt"
    if "--init" in sys.argv:
        init = sys.argv[sys.argv.index("--init") + 1]

    shards = sorted(glob.glob(f"{DATA}/*.npz"))
    val_paths = shards[::max(len(shards) // VAL_SHARDS, 1)][:VAL_SHARDS]
    trn_paths = [p for p in shards if p not in val_paths]
    print(f"{len(trn_paths)} train / {len(val_paths)} val shards", flush=True)

    o_tr, a_tr, s_tr, v_tr, w_tr = load(trn_paths)
    o_va, a_va, s_va, v_va, w_va = load(val_paths)
    print(f"train rows {len(v_tr):,}   val rows {len(v_va):,}", flush=True)

    net = load_any_net(init)
    torch_net = getattr(net, "net", net)
    opt = torch.optim.Adam(torch_net.parameters(), lr=3e-4)

    def batches(o, a, starts, v, w, size=256):
        """Yield decision-aligned batches: a row's obs is its decision's obs."""
        n_dec = len(o)
        idx = np.arange(n_dec)
        np.random.shuffle(idx)
        ends = np.append(starts[1:], len(v))
        for k in range(0, n_dec, size):
            sel = idx[k:k + size]
            rows = np.concatenate([np.arange(starts[i], ends[i]) for i in sel])
            rep = np.concatenate([np.full(ends[i] - starts[i], j)
                                  for j, i in enumerate(sel)])
            yield (torch.as_tensor(o[sel]), torch.as_tensor(a[rows]),
                   torch.as_tensor(rep, dtype=torch.long),
                   torch.as_tensor(v[rows]), torch.as_tensor(w[rows]))

    def evaluate():
        torch_net.eval()
        se = wsum = 0.0
        with torch.no_grad():
            for ob, ac, seg, tv, tw in batches(o_va, a_va, s_va, v_va, w_va, 512):
                q, _ = torch_net.heads_grouped(ob, ac, seg)
                se += float((tw * (q - tv) ** 2).sum())
                wsum += float(tw.sum())
        torch_net.train()
        return (se / max(wsum, 1e-9)) ** 0.5

    print(f"epoch 0 (before training): weighted val RMSE {evaluate():.4f}",
          flush=True)
    for ep in range(epochs):
        t0 = time.time()
        tot = n = 0.0, 0
        run = 0.0
        nb = 0
        for ob, ac, seg, tv, tw in batches(o_tr, a_tr, s_tr, v_tr, w_tr):
            q, _ = torch_net.heads_grouped(ob, ac, seg)
            loss = (tw * (q - tv) ** 2).sum() / tw.sum()
            opt.zero_grad()
            loss.backward()
            opt.step()
            run += float(loss)
            nb += 1
        print(f"epoch {ep+1}: train wMSE {run/max(nb,1):.4f}  "
              f"val wRMSE {evaluate():.4f}  ({time.time()-t0:.0f}s)", flush=True)
        torch.save(torch_net.state_dict(), out)
        stamp_ballot(out, shards)
        del tot, n
    print(f"saved {out}")


def stamp_ballot(ckpt_path, shards):
    """Record the ballot these labels covered, next to the weights.

    Without this the contract is only half-built: a checkpoint that cannot say
    which action set it was trained against is one that `require_ballot()` must
    refuse at load, so saving an unstamped file is saving a dud. The labelled
    ballot is read from the corpus manifest rather than from live code — the
    point is what the DATA covered, which live flags cannot tell us.
    """
    import glob as _glob
    import json as _json

    from shengji.engine.ballot import BallotSpec
    from shengji.rl.provenance import record_ballot

    mans = sorted(_glob.glob("rl_data/*.manifest.*.json"))
    if not mans:
        print("REFUSING to stamp: no corpus manifest found, so the labelled "
              "ballot is unknown. This checkpoint will be rejected at load "
              "until its provenance can be established.", flush=True)
        return
    with open(mans[0]) as fh:
        m = _json.load(fh)
    if "ballot_config" not in m:
        print(f"REFUSING to stamp: {mans[0]} predates ballot provenance.",
              flush=True)
        return
    spec = BallotSpec(
        name="mc_candidates", version=1, source="MCBot._candidates",
        config=tuple(tuple(kv) for kv in m["ballot_config"]),
        source_digest=m.get("ballot_source_digest", ""),
        note=f"labels from {os.path.basename(mans[0])}")
    path = record_ballot(ckpt_path, spec, corpus_manifest=mans[0],
                         n_shards=len(shards))
    print(f"  stamped {path} -> {spec}", flush=True)


if __name__ == "__main__":
    main()

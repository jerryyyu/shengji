"""Train a DIRECT-V head on high-N labels — the label-ceiling attack.

The obstacle, measured: mc(N=10) forfeits ~2.8 points per consequential
decision against a 240-world reference, so a student distilled from mc's own
N=10/N=30 preferences inherits that forfeit and caps at mc. Beating mc needs
labels stronger than mc, which is what this corpus is.

The target is the ABSOLUTE 240-world mean — the expected outcome of playing a
candidate when the heuristic finishes the round. Codex's spec, and deliberately
not `max_a Q` (selection optimism) nor the per-decision argmax (which improved
offline regret and then REVERSED online to 47%, RL_PLAN 1n).

Why absolute matters, concretely: v11pair's head learned only WITHIN-decision
differences, so adding any per-state constant left its loss unchanged. Its
cross-state scale was never identified, which is why using it as a leaf
evaluator was INVALID rather than merely unsuccessful. A head fit here has the
anchor that one lacked, so it is also the first honest test of a learned leaf.

Warm-started from a checkpoint whose value head is already absolute-scaled
(v7w), because 161k rows is far too little to learn a 531-dim encoder from
scratch — this fits the head, it does not rebuild the net.

Rows are weighted by inverse variance, so states the reference resolved
sharply count for more than noisy ones.

    uv run python scripts/highn_train.py OUT_CKPT [epochs] [--init CKPT]
"""
from __future__ import annotations

import glob
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
        del tot, n
    print(f"saved {out}")


if __name__ == "__main__":
    main()

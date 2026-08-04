"""Diagnostic ladder rung 2 (Codex): optimizer/capacity sanity.

Can the current model drive decision regret near ZERO on a small, clean,
high-margin set? If not, the trainer/model is binding and no amount of
data or LR sweeping matters. Run this BEFORE another full-data sweep.

Selects high-confidence rows (teacher's best beats candidate 0 by a wide
margin, so the label is not noise), then overfits them.
"""
import sys

import numpy as np

sys.path.insert(0, ".")
import glob  # noqa: E402

import torch  # noqa: E402
from shengji.rl.model import PolicyValueNet  # noqa: E402

MARGIN = 8.0          # points: only rows where the teacher was confident
TARGET = int(sys.argv[1]) if len(sys.argv) > 1 else 6000

rows = []
for f in sorted(glob.glob("rl_data/gen_v4_all/*.npz"))[:40]:
    z = np.load(f)
    offs, ch, vals, hv = z["offsets"], z["chosen"], z["action_values"], z["has_values"].astype(bool)
    obs, acts = z["obs"], z["actions"]
    idx = np.flatnonzero(hv & (np.diff(offs) > 1))
    for i in idx:
        a, b = offs[i], offs[i + 1]
        v = vals[a:b]
        if len(v) < 2:
            continue
        srt = np.sort(v)[::-1]
        if srt[0] - srt[1] >= MARGIN:      # unambiguous label
            rows.append((obs[i], acts[a:b], int(np.argmax(v))))
    if len(rows) >= TARGET:
        break
rows = rows[:TARGET]
print(f"selected {len(rows)} unambiguous rows (top-vs-second >= {MARGIN} pts)", flush=True)

dev = "mps" if torch.backends.mps.is_available() else "cpu"
net = PolicyValueNet().to(dev)
opt = torch.optim.Adam(net.parameters(), lr=1e-3)
for ep in range(60):
    correct = tot = 0
    losses = []
    for s in range(0, len(rows), 256):
        batch = rows[s:s + 256]
        o = torch.as_tensor(np.stack([r[0] for r in batch]), device=dev)
        ar = torch.as_tensor(np.concatenate([r[1] for r in batch]), device=dev)
        seg = torch.as_tensor(np.concatenate(
            [np.full(len(r[1]), i) for i, r in enumerate(batch)]),
            dtype=torch.long, device=dev)
        base = np.cumsum([0] + [len(r[1]) for r in batch])[:-1]
        chr_ = torch.as_tensor(base + np.array([r[2] for r in batch]),
                               dtype=torch.long, device=dev)
        _, ql = net.heads_grouped(o, ar, seg)
        xmax = torch.full((len(batch),), -1e9, device=dev).scatter_reduce(0, seg, ql, reduce="amax")
        ex = torch.exp(ql - xmax[seg])
        den = torch.zeros(len(batch), device=dev).index_add_(0, seg, ex)
        logp = (ql - xmax[seg]) - torch.log(den[seg] + 1e-9)
        loss = -logp[chr_].mean()
        opt.zero_grad(); loss.backward(); opt.step()
        losses.append(loss.item())
        with torch.no_grad():
            best = ql >= (xmax[seg] - 1e-6)
            correct += int(best[chr_].sum().item()); tot += len(batch)
    if ep % 10 == 0 or ep == 59:
        print(f"  epoch {ep:2d}: CE {np.mean(losses):.4f}  train-set accuracy {100*correct/tot:.1f}%", flush=True)
print(f"\nRESULT capacity sanity: final train accuracy {100*correct/tot:.1f}% on "
      f"{len(rows)} unambiguous rows.")
print("  >=95% => model/optimizer can fit clean labels; the bottleneck is elsewhere.")
print("  <80%  => trainer/architecture is BINDING; fix that before more data.")

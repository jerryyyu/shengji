"""Search distillation trainer (RL_PLAN Step 1).

Trains QNetDueling on MCBot's per-candidate values: MSE over ALL candidates
(dense targets) plus a cross-entropy term on the search's chosen action.
Vectorized over ragged candidate sets via segment indices.

Usage:
  uv run python -m shengji.rl.distill_train rl_data/distill ckpt_distill.pt [epochs]
Requires: uv sync --group rl
"""

from __future__ import annotations

import sys
from pathlib import Path

CE_WEIGHT = 1.0
BATCH_DECISIONS = 512
VALUE_SCALE = 100.0  # MC values are in points (±100+); normalize so the
#                      MSE term is O(1) and balances the CE term
SOFT_T = 0.05  # soft-target temperature (5 points at VALUE_SCALE): the
#                policy trains toward softmax(teacher values / T) — the AGZ
#                visit-distribution analog. Hard choice labels are partly
#                STOCHASTIC (10-world sampling noise decides near-ties;
#                measured: unconstrained CE stalled at 57% agreement, gates
#                32/24) — soft targets average out the teacher's RNG.


def main() -> None:
    import numpy as np
    import torch
    from .model import PolicyValueNet

    data_dir, ckpt_out = sys.argv[1], sys.argv[2]
    epochs = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    net = PolicyValueNet().to(dev)
    opt = torch.optim.Adam(net.parameters(), lr=1e-3)

    shards = sorted(Path(data_dir).glob("shard_*.npz"))
    assert shards, f"no shards in {data_dir}"
    val_shards = shards[:: max(len(shards) // 3, 1)][:2] if len(shards) > 2 else []
    train_shards = [s for s in shards if s not in val_shards]
    print(f"{len(train_shards)} train / {len(val_shards)} val shards, "
          f"device={dev}", flush=True)

    def run_shard(shard, training: bool):
        nonlocal tot_val, tot_ce, n_batches, correct, total
        import numpy as _np
        z = _np.load(shard)
        obs, acts = z["obs"], z["actions"]
        offs, chosen = z["offsets"], z["chosen"]
        values, hasv = z["action_values"], z["has_values"]
        idx_all = _np.flatnonzero(hasv & (_np.diff(offs) > 1))
        if training:
            _np.random.shuffle(idx_all)
        for bstart in range(0, len(idx_all), BATCH_DECISIONS):
            dec = idx_all[bstart:bstart + BATCH_DECISIONS]
            seg_list, rows, tgts, ch_row = [], [], [], []
            base = 0
            for di, i in enumerate(dec):
                a, b = offs[i], offs[i + 1]
                rows.append(acts[a:b])
                tgts.append(values[a:b])
                seg_list.append(_np.full(b - a, di))
                ch_row.append(base + chosen[i])
                base += b - a
            o = torch.as_tensor(obs[dec], device=dev)
            ar = torch.as_tensor(_np.concatenate(rows), device=dev)
            seg = torch.as_tensor(_np.concatenate(seg_list),
                                  dtype=torch.long, device=dev)
            tg = torch.as_tensor(_np.concatenate(tgts), device=dev) / VALUE_SCALE
            chr_ = torch.as_tensor(_np.array(ch_row), dtype=torch.long,
                                   device=dev)
            with torch.set_grad_enabled(training):
                q, ql = net.heads_grouped(o, ar, seg)  # value head, policy logits
                loss_val = torch.nn.functional.mse_loss(q, tg)

                def seg_logsoftmax(x):
                    xmax = torch.full((len(dec),), -1e9, device=dev)
                    xmax = xmax.scatter_reduce(0, seg, x, reduce="amax")
                    ex = torch.exp(x - xmax[seg])
                    den = torch.zeros(len(dec), device=dev).index_add_(0, seg, ex)
                    return (x - xmax[seg]) - torch.log(den[seg] + 1e-9), xmax

                logp, qmax = seg_logsoftmax(ql)
                with torch.no_grad():
                    soft, _ = seg_logsoftmax(tg / SOFT_T)
                    soft = torch.exp(soft)  # teacher preference distribution
                per_row = -(soft * logp)
                per_dec = torch.zeros(len(dec), device=dev).index_add_(
                    0, seg, per_row)
                loss_ce = per_dec.mean()
                if training:
                    loss = loss_val + CE_WEIGHT * loss_ce
                    opt.zero_grad()
                    loss.backward()
                    opt.step()
            tot_val += loss_val.item()
            tot_ce += loss_ce.item()
            n_batches += 1
            with torch.no_grad():
                is_best = ql >= (qmax[seg] - 1e-6)
                correct += int(is_best[chr_].sum().item())
                total += len(dec)

    for epoch in range(epochs):
        tot_val = tot_ce = 0.0
        n_batches = correct = total = 0
        for shard in train_shards:
            run_shard(shard, training=True)
        train_msg = (f"train mse {tot_val/n_batches:.3f} ce {tot_ce/n_batches:.3f} "
                     f"agree {correct/max(total,1):.1%}")
        tot_val = tot_ce = 0.0
        n_batches = correct = total = 0
        for shard in val_shards:
            run_shard(shard, training=False)
        val_msg = (f"VAL mse {tot_val/max(n_batches,1):.3f} "
                   f"ce {tot_ce/max(n_batches,1):.3f} "
                   f"agree {correct/max(total,1):.1%}") if val_shards else "no val"
        torch.save(net.state_dict(), ckpt_out)
        print(f"epoch {epoch}: {train_msg} | {val_msg}", flush=True)
    print(f"saved {ckpt_out}")


if __name__ == "__main__":
    main()

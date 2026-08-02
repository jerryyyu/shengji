"""Ragged-batch utilities for (obs, candidate-set) training.

One home for the segment math previously copied across distill_train,
dmc2, and the overnight inline scripts: collate variable-size candidate
sets into flat tensors + segment indices, and compute per-segment
softmax/extrema with scatter ops.
"""

from __future__ import annotations

import numpy as np
import torch


def collate(decisions, device):
    """decisions: iterable of (obs_vec, action_rows, chosen_idx).
    Returns (obs (D,O), rows (R,A), seg (R,), chosen_rows (D,), n_dec)."""
    obs_l, rows_l, seg_l, chosen_l = [], [], [], []
    base = 0
    for di, (obs, actions, chosen) in enumerate(decisions):
        obs_l.append(obs)
        rows_l.append(np.asarray(actions, dtype=np.float32))
        k = len(actions)
        seg_l.append(np.full(k, di))
        chosen_l.append(base + chosen)
        base += k
    n = len(obs_l)
    return (torch.as_tensor(np.asarray(obs_l, dtype=np.float32), device=device),
            torch.as_tensor(np.concatenate(rows_l), device=device),
            torch.as_tensor(np.concatenate(seg_l), dtype=torch.long,
                            device=device),
            torch.as_tensor(np.asarray(chosen_l), dtype=torch.long,
                            device=device),
            n)


def collate_shard(z, dec_idx, device, values_key: str | None = None):
    """Collate from an .npz shard for decision indices ``dec_idx``.
    Returns (obs, rows, seg, chosen_rows, n[, targets])."""
    offs, chosen = z["offsets"], z["chosen"]
    obs_l, rows_l, seg_l, chosen_l, tgt_l = [], [], [], [], []
    base = 0
    for di, i in enumerate(dec_idx):
        a, b = offs[i], offs[i + 1]
        rows_l.append(z["actions"][a:b])
        if values_key:
            tgt_l.append(z[values_key][a:b])
        seg_l.append(np.full(b - a, di))
        chosen_l.append(base + int(chosen[i]))
        base += b - a
    out = [torch.as_tensor(z["obs"][dec_idx], device=device),
           torch.as_tensor(np.concatenate(rows_l), device=device),
           torch.as_tensor(np.concatenate(seg_l), dtype=torch.long,
                           device=device),
           torch.as_tensor(np.asarray(chosen_l), dtype=torch.long,
                           device=device),
           len(dec_idx)]
    if values_key:
        out.append(torch.as_tensor(np.concatenate(tgt_l), device=device))
    return tuple(out)


def seg_logsoftmax(x, seg, n_dec, device):
    """Log-softmax within each segment. Returns (logp rows, seg maxes)."""
    xm = torch.full((n_dec,), -1e9, device=device)
    xm = xm.scatter_reduce(0, seg, x, reduce="amax")
    ex = torch.exp(x - xm[seg])
    dn = torch.zeros(n_dec, device=device).index_add_(0, seg, ex)
    return (x - xm[seg]) - torch.log(dn[seg] + 1e-9), xm


def seg_softmax(x, seg, n_dec, device):
    logp, _ = seg_logsoftmax(x, seg, n_dec, device)
    return torch.exp(logp)


def seg_spread(x, seg, n_dec, device):
    """Mean (max - min) per segment — the collapse-alarm statistic."""
    xmax = torch.full((n_dec,), -1e9, device=device)
    xmax = xmax.scatter_reduce(0, seg, x, reduce="amax")
    xmin = torch.full((n_dec,), 1e9, device=device)
    xmin = xmin.scatter_reduce(0, seg, x, reduce="amin")
    return (xmax - xmin).mean()


def seg_kl(x_ref, x_stu, seg, n_dec, device):
    """Mean KL(softmax(x_ref) || softmax(x_stu)) over segments."""
    lp_ref, _ = seg_logsoftmax(x_ref, seg, n_dec, device)
    lp_stu, _ = seg_logsoftmax(x_stu, seg, n_dec, device)
    p_ref = torch.exp(lp_ref)
    per_row = p_ref * (lp_ref - lp_stu)
    tot = torch.zeros(n_dec, device=device).index_add_(0, seg, per_row)
    return tot.mean()

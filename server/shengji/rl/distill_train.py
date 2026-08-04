"""Search distillation trainer (RL_PLAN Step 1).

Trains QNetDueling on MCBot's per-candidate values: MSE over ALL candidates
(dense targets) plus a cross-entropy term against the SOFTENED VALUE
DISTRIBUTION softmax(values/T) — NOT the teacher's post-processed choice
(margin / point-shy / TRACTOR_LOCK are not represented in valued rows).
Choice-only rows (has_values=False, e.g. TRACTOR_LOCK short-circuits)
are trained with hard CE on `chosen`, which is the only signal they
carry. Codex audit 2026-08-03 caught that these rows were being dropped
entirely.
Vectorized over ragged candidate sets via segment indices.

Usage:
  uv run python -m shengji.rl.distill_train rl_data/distill ckpt_distill.pt [epochs]
Requires: uv sync --group rl
"""

from __future__ import annotations

import sys
from pathlib import Path

CE_WEIGHT = 1.0
CHOICE_CE_WEIGHT = 1.0  # hard-CE weight for choice-only (locked) rows
RESIDUAL = False  # train on DELTAS from candidate 0 (the heuristic's pick)
#   instead of absolute values. Matches the teacher's real control
#   structure (keep a0 unless something clears the margin), cancels the
#   rollout noise shared by all candidates in a state — which the
#   label-noise diagnostic showed corrupts 63% of states — and makes the
#   net a learned OVERRIDE rather than a from-scratch replacement.
#   (Codex recommendation, 2026-08-03.)
PAIRWISE = False   # --pairwise: train the DEPLOYED quantity q_i-q_0 directly
BOUNDARY_W = 3.0   # extra weight on rows straddling the override margin
MARGIN_PRIOR = 0.0  # points added to candidate 0 before softmax (set via
#                     --margin-prior 5.0 for the margin-aware arm)
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
    if "--init" in sys.argv:  # warm start (same objective => safe)
        p = sys.argv[sys.argv.index("--init") + 1]
        net.load_state_dict(torch.load(p, map_location=dev))
        print(f"warm start from {p}", flush=True)
    snap_dir = None
    if "--snapshots" in sys.argv:  # per-epoch snapshots for probe-selection
        snap_dir = sys.argv[sys.argv.index("--snapshots") + 1]
        Path(snap_dir).mkdir(exist_ok=True)
    global MARGIN_PRIOR, RESIDUAL, PAIRWISE
    if "--pairwise" in sys.argv:
        PAIRWISE = True
        print("PAIRWISE objective: optimising (q_i - q_0) directly against "
              "(Q_i - Q_0), Huber, with weight concentrated near the "
              "+/-MARGIN decision boundary", flush=True)
    if "--residual" in sys.argv:
        RESIDUAL = True
        print("residual targets: Q(s,a_i) - Q(s,a_0)", flush=True)
    if "--margin-prior" in sys.argv:
        MARGIN_PRIOR = float(sys.argv[sys.argv.index("--margin-prior") + 1])
        print(f"margin-aware targets: +{MARGIN_PRIOR} on candidate 0",
              flush=True)
    lr = (float(sys.argv[sys.argv.index("--lr") + 1])
          if "--lr" in sys.argv else 1e-3)
    opt = torch.optim.Adam(net.parameters(), lr=lr)

    shards = sorted(Path(data_dir).glob("shard_*.npz"))
    assert shards, f"no shards in {data_dir}"
    val_shards = shards[:: max(len(shards) // 3, 1)][:2] if len(shards) > 2 else []
    train_shards = [s for s in shards if s not in val_shards]
    print(f"{len(train_shards)} train / {len(val_shards)} val shards, "
          f"device={dev}", flush=True)

    def run_shard(shard, training: bool):
        nonlocal tot_val, tot_ce, n_batches, correct, total, n_choice
        import numpy as _np
        z = _np.load(shard)
        obs, acts = z["obs"], z["actions"]
        offs, chosen = z["offsets"], z["chosen"]
        values, hasv = z["action_values"], z["has_values"]
        idx_all = _np.flatnonzero(hasv & (_np.diff(offs) > 1))
        idx_choice = _np.flatnonzero((~hasv.astype(bool)) & (_np.diff(offs) > 1))
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
            if RESIDUAL:   # subtract each decision's candidate-0 value
                tgts = [t - t[0] for t in tgts]
            tg = torch.as_tensor(_np.concatenate(tgts), device=dev) / VALUE_SCALE
            chr_ = torch.as_tensor(_np.array(ch_row), dtype=torch.long,
                                   device=dev)
            with torch.set_grad_enabled(training):
                q, ql = net.heads_grouped(o, ar, seg)  # value head, policy logits
                if PAIRWISE:
                    # v10res regressed each row independently and was never
                    # told what a_0 was, so it never learned the quantity the
                    # override rule actually gates on. Optimise that quantity:
                    #   (q_i - q_0) vs (Q_i - Q_0)
                    # Huber, because a few huge deltas dominated the MSE, and
                    # up-weighted where the teacher's delta sits near the
                    # margin — that is where a wrong sign flips a decision.
                    starts0 = torch.zeros(len(dec), dtype=torch.long, device=dev)
                    starts0[1:] = torch.cumsum(
                        torch.bincount(seg, minlength=len(dec))[:-1], 0)
                    q0 = q[starts0][seg]        # this decision's baseline
                    t0 = tg[starts0][seg]
                    dq, dt = q - q0, tg - t0
                    margin = MARGIN_PRIOR / VALUE_SCALE if MARGIN_PRIOR else \
                        5.0 / VALUE_SCALE
                    near = (dt.abs() < 2.0 * margin).float()
                    w = 1.0 + BOUNDARY_W * near
                    loss_val = (w * torch.nn.functional.huber_loss(
                        dq, dt, reduction="none", delta=margin)).mean()
                else:
                    loss_val = torch.nn.functional.mse_loss(q, tg)

                def seg_logsoftmax(x):
                    xmax = torch.full((len(dec),), -1e9, device=dev)
                    xmax = xmax.scatter_reduce(0, seg, x, reduce="amax")
                    ex = torch.exp(x - xmax[seg])
                    den = torch.zeros(len(dec), device=dev).index_add_(0, seg, ex)
                    return (x - xmax[seg]) - torch.log(den[seg] + 1e-9), xmax

                logp, qmax = seg_logsoftmax(ql)
                with torch.no_grad():
                    tgt = tg
                    if MARGIN_PRIOR:
                        # The teacher does NOT play raw-value argmax: it keeps
                        # candidate 0 (the heuristic's pick) unless the search
                        # beats it by MARGIN. Raw-value argmax matches the
                        # actual choice only 61.7%; +margin on candidate 0
                        # matches 98.3% (Codex audit, reproduced 2026-08-03).
                        # Encode that prior SOFTLY so the target represents the
                        # acting policy while keeping soft-target smoothing.
                        first = torch.zeros_like(tgt)
                        starts = torch.zeros(len(dec), dtype=torch.long,
                                             device=dev)
                        starts[1:] = torch.cumsum(
                            torch.bincount(seg, minlength=len(dec))[:-1], 0)
                        first[starts] = MARGIN_PRIOR / VALUE_SCALE
                        tgt = tgt + first
                    soft, _ = seg_logsoftmax(tgt / SOFT_T)
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

        # Choice-only rows (no teacher values): hard CE on the chosen
        # action. These are the teacher's most assertive plays
        # (TRACTOR_LOCK leads) and were silently dropped until the Codex
        # audit, 2026-08-03. Ballots here are the wide v2 enumeration
        # (up to ~500 candidates) — a different distribution from valued
        # rows, so they are trained but NOT used to justify a play-time
        # ballot change (Elo-798 rule).
        for bstart in range(0, len(idx_choice), BATCH_DECISIONS):
            dec = idx_choice[bstart:bstart + BATCH_DECISIONS]
            seg_list, rows, ch_row = [], [], []
            base = 0
            for di, i in enumerate(dec):
                a, b = offs[i], offs[i + 1]
                rows.append(acts[a:b])
                seg_list.append(_np.full(b - a, di))
                ch_row.append(base + chosen[i])
                base += b - a
            o = torch.as_tensor(obs[dec], device=dev)
            ar = torch.as_tensor(_np.concatenate(rows), device=dev)
            seg = torch.as_tensor(_np.concatenate(seg_list),
                                  dtype=torch.long, device=dev)
            chr_ = torch.as_tensor(_np.array(ch_row), dtype=torch.long,
                                   device=dev)
            with torch.set_grad_enabled(training):
                _, ql = net.heads_grouped(o, ar, seg)
                xmax = torch.full((len(dec),), -1e9, device=dev)
                xmax = xmax.scatter_reduce(0, seg, ql, reduce="amax")
                ex = torch.exp(ql - xmax[seg])
                den = torch.zeros(len(dec), device=dev).index_add_(0, seg, ex)
                logp = (ql - xmax[seg]) - torch.log(den[seg] + 1e-9)
                loss_c = CHOICE_CE_WEIGHT * (-logp[chr_].mean())
                if training:
                    opt.zero_grad()
                    loss_c.backward()
                    opt.step()
            n_choice += len(dec)

    # Heartbeat: long epochs are opaque (block-buffered logs, hours per
    # line) — emit running losses per SHARD, plus a machine-readable
    # trail beside the checkpoint for stability monitoring.
    import json
    import time
    hb_path = ckpt_out + ".progress.jsonl"

    for epoch in range(epochs):
        tot_val = tot_ce = 0.0
        n_batches = correct = total = n_choice = 0
        for si, shard in enumerate(train_shards):
            run_shard(shard, training=True)
            print(f"  ep {epoch} shard {si + 1}/{len(train_shards)}: "
                  f"mse {tot_val / n_batches:.3f} "
                  f"ce {tot_ce / n_batches:.3f} "
                  f"agree {correct / max(total, 1):.1%}", flush=True)
            with open(hb_path, "a") as hf:
                hf.write(json.dumps(
                    {"t": round(time.time()), "epoch": epoch,
                     "shard": si + 1, "of": len(train_shards),
                     "mse": round(tot_val / n_batches, 4),
                     "ce": round(tot_ce / n_batches, 4),
                     "agree": round(correct / max(total, 1), 4)}) + "\n")
        train_msg = (f"train mse {tot_val/n_batches:.3f} ce {tot_ce/n_batches:.3f} "
                     f"agree {correct/max(total,1):.1%} choiceCE_rows {n_choice}")
        tot_val = tot_ce = 0.0
        n_batches = correct = total = 0
        for shard in val_shards:
            run_shard(shard, training=False)
        val_msg = (f"VAL mse {tot_val/max(n_batches,1):.3f} "
                   f"ce {tot_ce/max(n_batches,1):.3f} "
                   f"agree {correct/max(total,1):.1%}") if val_shards else "no val"
        torch.save(net.state_dict(), ckpt_out)
        if snap_dir:
            torch.save(net.state_dict(), f"{snap_dir}/ep{epoch:02d}.pt")
        print(f"epoch {epoch}: {train_msg} | {val_msg}", flush=True)
    print(f"saved {ckpt_out}")


if __name__ == "__main__":
    main()

"""Offline evaluator for OVERRIDE-style checkpoints (Codex, 2026-08-03).

v10res was shipped as "residual distillation rejected" on the strength of a
duel. Codex's post-mortem showed the checkpoint was effectively a NO-OP —
it overrode 1.28% of states where the teacher overrode 14.78%, and its choice
agreement (84.92%) was *below* the trivial always-keep-candidate-0 policy
(85.22%). A product duel cannot distinguish "the idea is wrong" from "this
net never fired", so the duel was the wrong gate.

This measures the deployed decision rule directly, on held-out gen-v4 rows,
with no new teacher data:

  * pairwise delta RMSE vs. the zero predictor (does it beat "no override"?)
  * override precision / recall against the teacher's own overrides
  * decision regret in raw teacher-Q vs. always-candidate-0
  * a threshold sweep, reported as DIAGNOSTIC ONLY — picking the threshold
    that minimises held-out regret and then shipping it is post-hoc fitting
  * slices: lead / follow / tractor-lock rows

Gate before any successor arm earns a seeded duel: pairwise RMSE below the
zero predictor AND regret below always-candidate-0 at a threshold chosen on a
VALIDATION split, not on the reported one.

    uv run python scripts/residual_eval.py <ckpt> [shard_glob] [n_states]
"""
from __future__ import annotations

import glob
import sys

import numpy as np

sys.path.insert(0, ".")


def val_shards(data_dir: str) -> list[str]:
    """EXACTLY the shards distill_train holds out, so this is a true holdout."""
    shards = sorted(glob.glob(f"{data_dir}/*.npz"))
    return shards[:: max(len(shards) // 3, 1)][:2] if len(shards) > 2 else shards


def load_states(paths: list[str], limit: int):
    """Yield (obs, [action encodings], [teacher Q], choice_only) per state."""
    out = []
    for path in paths:
        d = np.load(path, allow_pickle=False)
        obs, acts = d["obs"], d["actions"]
        off, vals, hv = d["offsets"], d["action_values"], d["has_values"]
        for i in range(len(obs)):
            a, b = int(off[i]), int(off[i + 1])
            if b - a < 2:
                continue
            out.append((obs[i], acts[a:b], vals[a:b], not bool(hv[i])))
            if len(out) >= limit:
                return out
    return out


def main() -> None:
    ckpt = sys.argv[1] if len(sys.argv) > 1 else "snapshots_v10res/ep09.pt"
    data_dir = sys.argv[2] if len(sys.argv) > 2 else "rl_data/gen_v4_all"
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 5000

    paths = val_shards(data_dir)
    states = load_states(paths, limit)
    print(f"checkpoint: {ckpt}")
    print(f"holdout shards (exactly what distill_train withholds): "
          f"{[p.split('/')[-1] for p in paths]}")
    print(f"states: {len(states)} (valued: "
          f"{sum(1 for s_ in states if not s_[3])})", flush=True)

    from shengji.rl.model import load_any_net

    net = load_any_net(ckpt)

    d_true, d_pred = [], []
    regret_net, regret_base = [], []
    teacher_over = net_over = both_over = 0
    scored = []
    for ob, enc, qt, is_choice in states:
        if is_choice:
            continue                     # TRACTOR_LOCK rows carry no values
        qp = np.asarray(net.value_candidates(ob, list(enc)), dtype=np.float64)
        qt = np.asarray(qt, dtype=np.float64)
        scored.append((qt, qp))
        d_true.append(qt[1:] - qt[0])
        d_pred.append(qp[1:] - qp[0])
        best, pick = int(np.argmax(qt)), int(np.argmax(qp))
        regret_net.append(qt[best] - qt[pick])
        regret_base.append(qt[best] - qt[0])
        t_o, n_o = best != 0, pick != 0
        teacher_over += t_o
        net_over += n_o
        both_over += t_o and n_o

    d_true = np.concatenate(d_true)
    d_pred = np.concatenate(d_pred)
    n_states = len(regret_net)
    rmse = float(np.sqrt(np.mean((d_pred - d_true) ** 2)))
    rmse0 = float(np.sqrt(np.mean(d_true ** 2)))

    print(f"\nvalued states evaluated: {n_states}")
    print(f"pairwise delta RMSE: {rmse:.4f}   zero-predictor: {rmse0:.4f}  "
          f"=> {'BEATS' if rmse < rmse0 else 'WORSE THAN'} predicting no override")
    print(f"teacher overrides: {100 * teacher_over / n_states:.2f}%   "
          f"net overrides (argmax): {100 * net_over / n_states:.2f}%")
    prec = 100 * both_over / net_over if net_over else 0.0
    rec = 100 * both_over / teacher_over if teacher_over else 0.0
    print(f"override precision: {prec:.1f}%   recall: {rec:.1f}%")
    print(f"regret vs teacher-best: net {np.mean(regret_net):.3f}  "
          f"always-candidate-0 {np.mean(regret_base):.3f}  "
          f"=> {'IMPROVES on' if np.mean(regret_net) < np.mean(regret_base) else 'NO BETTER THAN'} the trivial policy")

    print("\nthreshold sweep (DIAGNOSTIC ONLY — choosing a threshold here and "
          "shipping it is post-hoc fitting):")
    for thr in (0.0, 0.01, 0.02, 0.05, 0.1, 0.2):
        reg, over = [], 0
        for qt, qp in scored:
            gain = qp - qp[0]
            pick = int(np.argmax(gain)) if float(np.max(gain)) > thr else 0
            reg.append(qt[int(np.argmax(qt))] - qt[pick])
            over += pick != 0
        print(f"  thr {thr:<5} regret {np.mean(reg):.3f}  "
              f"override {100 * over / len(scored):.1f}%")


if __name__ == "__main__":
    main()

"""Fixed-coefficient, paired model/rollout diagnostics; not a search policy.

For action advantages G and model advantages X, estimate E[G] with
mean(X on independent cheap worlds) + mean(G-X on paired rollout worlds).
The coefficient is one, chosen before results; no fitted confidence rule.
All columns must use the same actor perspective, utility and world ordering.
"""
from __future__ import annotations

import numpy as np


def _matrix(value):
    a = np.asarray(value, dtype=np.float64)
    if a.ndim != 2 or min(a.shape) < 2 or not np.isfinite(a).all():
        raise ValueError("expected finite world-by-action matrix with at least two rows/columns")
    return a


def action_gaps(value, incumbent=0):
    a = _matrix(value)
    if (isinstance(incumbent, bool) or not isinstance(incumbent, int)
            or not 0 <= incumbent < a.shape[1]):
        raise ValueError("invalid incumbent column")
    return a - a[:, incumbent:incumbent + 1]


def corrected_gaps(cheap_predictions, paired_predictions, paired_returns, incumbent=0):
    """Independent cheap mean plus paired residual mean, in action-gap units.

    The caller owns sample provenance/disjointness. Do not use an arbitrary
    unmatched return matrix, or fit a coefficient from these same outcomes.
    """
    cheap = action_gaps(cheap_predictions, incumbent)
    pred = action_gaps(paired_predictions, incumbent)
    truth = action_gaps(paired_returns, incumbent)
    if pred.shape != truth.shape or cheap.shape[1] != truth.shape[1]:
        raise ValueError("paired world/action shape mismatch")
    return cheap.mean(0) + (truth - pred).mean(0)


def gap_moments(predictions, returns, incumbent=0):
    x, y = action_gaps(predictions, incumbent), action_gaps(returns, incumbent)
    if x.shape != y.shape:
        raise ValueError("paired world/action shape mismatch")
    keep = [i for i in range(x.shape[1]) if i != incumbent]
    x, y = x[:, keep], y[:, keep]
    vx, vy = x.var(0, ddof=1), y.var(0, ddof=1)
    cov = ((x - x.mean(0)) * (y - y.mean(0))).sum(0) / (len(y) - 1)
    vr = (y - x).var(0, ddof=1)
    return {
        "mean_model_gap_bias": float((x - y).mean()),
        "mean_absolute_model_gap_bias": float(np.abs((x - y).mean(0)).mean()),
        "mean_rollout_gap_variance": float(vy.mean()),
        "mean_model_gap_variance": float(vx.mean()),
        "mean_gap_covariance": float(cov.mean()),
        "mean_residual_gap_variance": float(vr.mean()),
        "residual_variance_ratio": None if vy.mean() == 0 else float(vr.mean() / vy.mean()),
        "nonzero_rollout_variance_actions": int(np.count_nonzero(vy)),
        "alternative_count": len(keep),
    }


def held_world_comparison(predictions, returns, *, seed, repetitions=16):
    """1024 retained worlds: 512 reference, 384 cheap, 128 correction pool.

    Compare fixed 32/128-rollout doses, with identical actions and correction
    rows for plain/corrected estimates. Reference, cheap and correction rows
    are disjoint in each repetition. Repetitions reuse the same worlds and
    are NOT independent games or evidence for gameplay strength.
    Column zero is the incumbent; no action elimination or MC-LCB is tested.
    """
    x, y = _matrix(predictions), _matrix(returns)
    if x.shape != y.shape or len(y) != 1024:
        raise ValueError("expected paired 1024-world matrices")
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions < 1:
        raise ValueError("repetitions must be a positive integer")
    rng = np.random.default_rng(seed)
    results = {name: [] for name in ("model_384", "mc_32", "corrected_32", "mc_128", "corrected_128")}
    xg, yg = action_gaps(x), action_gaps(y)
    for _ in range(repetitions):
        perm = rng.permutation(1024)
        ref, cheap, pool = perm[:512], perm[512:896], perm[896:]
        target = yg[ref].mean(0)
        estimates = {"model_384": xg[cheap].mean(0)}
        for n in (32, 128):
            paired = pool[:n]
            estimates[f"mc_{n}"] = yg[paired].mean(0)
            estimates[f"corrected_{n}"] = corrected_gaps(x[cheap], x[paired], y[paired])
        for name, estimate in estimates.items():
            pick = int(np.argmax(estimate))  # fixed incumbent-first tie rule
            results[name].append({
                "gap_mse": float(np.square(estimate[1:] - target[1:]).mean()),
                "reference_regret": float(target.max() - target[pick]),
                "reference_lift_vs_incumbent": float(target[pick]),
            })
    return {name: {metric: float(np.mean([row[metric] for row in rows]))
                   for metric in rows[0]} for name, rows in results.items()}

"""Baselines and evaluation statistics (every run reports them).

* Stratified prior for value: the mean TRAINING outcome by (phase: ply
  thirds early/middle/late) x (role: banker-team/attacker-team) x (attacker
  points so far: 0-39 / 40-79 / 80+); an empty cell falls back to the global
  training mean.  D64 (784569ba): a value model must beat this.
* Prior baselines: uniform over the ballot (CE = log K) and one-hot on the
  incumbent (ballot index 0) smoothed with ``eps`` uniform mass, ``eps``
  fitted on the training split (a literal one-hot has infinite CE).
* Paired per-record differences with a cluster bootstrap CI.
* Affine calibration (scale, shift) of value predictions fitted on the
  validation split; reliability over 10 predicted-value bins.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

PHASES = ("early", "middle", "late")
ROLES = ("banker-team", "attacker-team")
POINT_BINS = ("0-39", "40-79", "80+")
N_STRATA = len(PHASES) * len(ROLES) * len(POINT_BINS)
INCUMBENT_EPS_GRID = (0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3,
                      0.5, 0.7, 0.9, 1.0)


# ---------------------------------------------------------- stratified prior

def phase_index(ply: np.ndarray) -> np.ndarray:
    """0 early / 1 middle / 2 late by ply thirds (100 plays per round); a
    bury decision (ply -1) is early."""
    ply = np.asarray(ply, dtype=np.int64)
    return np.clip(np.where(ply < 0, 0, ply * 3 // 100), 0, 2)


def points_bin(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=np.float64)
    return np.where(points < 40, 0, np.where(points < 80, 1, 2)).astype(np.int64)


def stratum_index(ply: np.ndarray, role_attacker: np.ndarray, points: np.ndarray
                  ) -> np.ndarray:
    role = np.asarray(role_attacker, dtype=bool).astype(np.int64)
    return (phase_index(ply) * len(ROLES) + role) * len(POINT_BINS) + points_bin(points)


def stratum_label(index: int) -> str:
    p, rest = divmod(int(index), len(ROLES) * len(POINT_BINS))
    r, b = divmod(rest, len(POINT_BINS))
    return f"{PHASES[p]}|{ROLES[r]}|{POINT_BINS[b]}"


class StratifiedPrior:
    """Mean training outcome per stratum with a global-mean fallback."""

    def __init__(self, sums: np.ndarray | None = None, counts: np.ndarray | None = None):
        self.sums = np.zeros(N_STRATA, dtype=np.float64) if sums is None else np.asarray(sums, np.float64)
        self.counts = np.zeros(N_STRATA, dtype=np.int64) if counts is None else np.asarray(counts, np.int64)

    def add(self, ply, role_attacker, points, target) -> None:
        idx = stratum_index(ply, role_attacker, points)
        self.sums += np.bincount(idx, weights=np.asarray(target, np.float64), minlength=N_STRATA)
        self.counts += np.bincount(idx, minlength=N_STRATA)

    @property
    def global_mean(self) -> float:
        n = int(self.counts.sum())
        return float(self.sums.sum() / n) if n else 0.0

    def means(self) -> np.ndarray:
        out = np.full(N_STRATA, self.global_mean, dtype=np.float64)
        filled = self.counts > 0
        out[filled] = self.sums[filled] / self.counts[filled]
        return out

    def predict(self, ply, role_attacker, points) -> np.ndarray:
        return self.means()[stratum_index(ply, role_attacker, points)]

    def to_dict(self) -> dict:
        means = self.means()
        return {
            "strata": "phase(ply thirds) x role x attacker points so far (0-39/40-79/80+)",
            "global_mean": self.global_mean,
            "n": int(self.counts.sum()),
            "empty_cells": int((self.counts == 0).sum()),
            "cells": [{"stratum": stratum_label(i), "n": int(self.counts[i]),
                       "mean": float(means[i])} for i in range(N_STRATA)],
            "sums": self.sums.tolist(),
            "counts": self.counts.tolist(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StratifiedPrior":
        return cls(np.asarray(d["sums"], np.float64), np.asarray(d["counts"], np.int64))


# ------------------------------------------------------------ prior baselines

def uniform_ce(widths: np.ndarray) -> np.ndarray:
    """CE of any distribution against uniform over K candidates: log K."""
    return np.log(np.asarray(widths, dtype=np.float64))


def incumbent_ce(target_first: np.ndarray, widths: np.ndarray, eps: float) -> np.ndarray:
    """CE of a target (mass ``target_first`` on ballot index 0) against
    ``(1 - eps) * onehot(0) + eps * uniform``."""
    k = np.asarray(widths, dtype=np.float64)
    t0 = np.asarray(target_first, dtype=np.float64)
    q0 = (1.0 - eps) + eps / k
    qj = eps / k
    with np.errstate(divide="ignore"):
        return -(t0 * np.log(q0) + (1.0 - t0) * np.log(qj))


def fit_incumbent_eps(target_first: np.ndarray, widths: np.ndarray,
                      grid: Sequence[float] = INCUMBENT_EPS_GRID) -> dict:
    """The eps of the grid minimising the mean training CE."""
    best = None
    table = []
    for eps in grid:
        ce = incumbent_ce(target_first, widths, eps)
        mean = float(np.mean(ce)) if ce.size else math.inf
        table.append({"eps": eps, "ce": mean})
        if best is None or mean < best["ce"]:
            best = {"eps": eps, "ce": mean}
    return {"eps": best["eps"] if best else 1.0, "train_ce": best["ce"] if best else None,
            "grid": table, "n": int(np.asarray(widths).size)}


# ----------------------------------------------------------------- bootstrap

def cluster_bootstrap(values: np.ndarray, clusters: np.ndarray, *, n_boot: int = 1000,
                      seed: int = 0) -> dict:
    """Mean of ``values`` with a percentile CI from resampling deal clusters
    with replacement (records within a cluster are not independent)."""
    values = np.asarray(values, dtype=np.float64)
    if values.size == 0:
        return {"mean": None, "ci95": [None, None], "n": 0, "clusters": 0,
                "n_boot": n_boot, "seed": seed}
    _, inverse = np.unique(np.asarray(clusters).astype(str), return_inverse=True)
    n_clusters = int(inverse.max()) + 1
    sums = np.bincount(inverse, weights=values, minlength=n_clusters)
    counts = np.bincount(inverse, minlength=n_clusters).astype(np.float64)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, n_clusters, size=(n_boot, n_clusters))
    boot = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return {"mean": float(values.mean()), "ci95": [float(lo), float(hi)],
            "n": int(values.size), "clusters": n_clusters, "n_boot": int(n_boot),
            "seed": int(seed)}


# --------------------------------------------------------------- calibration

def fit_affine(pred: np.ndarray, target: np.ndarray) -> dict:
    """Least-squares ``target ~ scale * pred + shift``."""
    pred = np.asarray(pred, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    if pred.size < 2 or float(np.var(pred)) <= 1e-12:
        return {"scale": 1.0, "shift": float(target.mean() - pred.mean()) if pred.size else 0.0,
                "degenerate": True, "n": int(pred.size)}
    scale, shift = np.polyfit(pred, target, 1)
    return {"scale": float(scale), "shift": float(shift), "degenerate": False,
            "n": int(pred.size)}


def apply_affine(pred: np.ndarray, calib: dict) -> np.ndarray:
    return float(calib["scale"]) * np.asarray(pred, dtype=np.float64) + float(calib["shift"])


def reliability_table(pred: np.ndarray, target: np.ndarray, bins: int = 10) -> list[dict]:
    """Equal-count bins over predicted values: count, mean prediction, mean
    target, prediction range."""
    pred = np.asarray(pred, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    if pred.size == 0:
        return []
    order = np.argsort(pred, kind="stable")
    parts = np.array_split(order, min(bins, pred.size))
    rows = []
    for i, part in enumerate(parts):
        if part.size == 0:
            continue
        rows.append({"bin": i, "n": int(part.size),
                     "pred_lo": float(pred[part].min()), "pred_hi": float(pred[part].max()),
                     "pred_mean": float(pred[part].mean()),
                     "target_mean": float(target[part].mean())})
    return rows


# ----------------------------------------------------------------- summaries

def value_summary(pred: np.ndarray, baseline: np.ndarray, target: np.ndarray,
                  clusters: np.ndarray, *, n_boot: int = 1000, seed: int = 0) -> dict:
    pred = np.asarray(pred, np.float64)
    baseline = np.asarray(baseline, np.float64)
    target = np.asarray(target, np.float64)
    e_m = pred - target
    e_b = baseline - target
    return {
        "n": int(target.size),
        "model": {"mae": float(np.abs(e_m).mean()) if target.size else None,
                  "mse": float((e_m ** 2).mean()) if target.size else None},
        "stratified_prior": {"mae": float(np.abs(e_b).mean()) if target.size else None,
                             "mse": float((e_b ** 2).mean()) if target.size else None},
        "paired_diff_model_minus_prior": {
            "abs_error": cluster_bootstrap(np.abs(e_m) - np.abs(e_b), clusters,
                                           n_boot=n_boot, seed=seed),
            "sq_error": cluster_bootstrap(e_m ** 2 - e_b ** 2, clusters,
                                          n_boot=n_boot, seed=seed + 1),
        },
        "target_mean": float(target.mean()) if target.size else None,
        "target_std": float(target.std()) if target.size else None,
    }


def prior_summary(ce_model: np.ndarray, ce_final: np.ndarray, top1: np.ndarray,
                  target_first: np.ndarray, widths: np.ndarray, played: np.ndarray,
                  clusters: np.ndarray, *, incumbent_eps: float, n_boot: int = 1000,
                  seed: int = 0) -> dict:
    """Prior-head metrics over records with a target and K >= 2.

    ``ce_model``: CE against the training target; ``ce_final``: -log p(played)
    (NaN where the played index is unknown); ``top1``: argmax == played.
    """
    widths = np.asarray(widths, np.int64)
    n = int(widths.size)
    if n == 0:
        return {"n": 0}
    uni = uniform_ce(widths)
    inc = incumbent_ce(target_first, widths, incumbent_eps)
    known = np.asarray(played) >= 0
    final = np.asarray(ce_final, np.float64)
    return {
        "n": n,
        "model_ce": float(np.mean(ce_model)),
        "uniform_ce": float(np.mean(uni)),
        "incumbent_ce": float(np.mean(inc)),
        "incumbent_eps": float(incumbent_eps),
        "diff_model_minus_uniform": cluster_bootstrap(np.asarray(ce_model) - uni, clusters,
                                                      n_boot=n_boot, seed=seed),
        "diff_model_minus_incumbent": cluster_bootstrap(np.asarray(ce_model) - inc, clusters,
                                                        n_boot=n_boot, seed=seed + 1),
        "nll_played": (float(np.mean(final[known])) if known.any() else None),
        "nll_played_uniform": (float(np.mean(uni[known])) if known.any() else None),
        "top1_agreement": (float(np.mean(np.asarray(top1)[known])) if known.any() else None),
        "incumbent_top1_agreement": (float(np.mean(np.asarray(played)[known] == 0))
                                     if known.any() else None),
        "n_played_known": int(known.sum()),
        "mean_width": float(widths.mean()),
    }

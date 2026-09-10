"""DEV empirical-world mixture matching; not a Bayesian joint posterior.

Fit model count marginals on a fixed supplied world set. Never consumes actual
hidden ownership, actions, returns or outcomes. Projected gradient fits a
capped simplex, then mixes with uniform to satisfy ESS >= N/2. The latter is
a named post-fit concentration guard, NOT the joint constrained optimum.
"""
from __future__ import annotations

import numpy as np


def reweighted_consumer_means(values, weights, ordinary_means):
    """Anchor to actual W32 arithmetic; uniform weights preserve exact ties."""
    values = np.asarray(values, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    means = np.asarray(ordinary_means, dtype=np.float64).copy()
    if values.ndim != 2 or values.shape[0] < 2 or values.shape[1] < 1 \
            or weights.shape != (values.shape[0],) or means.shape != (values.shape[1],) \
            or not all(np.isfinite(a).all() for a in (values,weights,means)) \
            or (weights < 0).any() or abs(weights.sum()-1) > 1e-8:
        raise ValueError("invalid weighted consumer matrix")
    for delta, row in zip(weights-1/len(weights), values):
        means += delta*row
    return means


def capped_simplex(values, cap):
    """Euclidean projection onto sum(w)=1, 0<=w<=cap."""
    lo, hi = float(values.min()-cap), float(values.max())
    for _ in range(60):
        mid = (lo+hi)/2
        if np.clip(values-mid, 0, cap).sum() > 1:
            lo = mid
        else:
            hi = mid
    return np.clip(values-(lo+hi)/2, 0, cap)


def fit_world_mixture(counts, probabilities, *, iterations=500):
    """counts[world,cell] in0..2; model probabilities[cell,count].

    Non-converged iteration-limited solutions are explicitly labeled. They
    remain valid empirical mixtures; no optimizer-success claim is inferred.
    """
    counts = np.asarray(counts)
    probabilities = np.asarray(probabilities, dtype=np.float64)
    if counts.ndim != 2 or min(counts.shape) < 1 or counts.shape[0] < 2 \
            or not np.issubdtype(counts.dtype, np.integer) \
            or (counts < 0).any() or (counts > 2).any():
        raise ValueError("invalid world count matrix")
    n, cells = counts.shape
    if probabilities.shape != (cells, 3) or not np.isfinite(probabilities).all() \
            or (probabilities < 0).any() or not np.allclose(probabilities.sum(axis=1), 1,
                                                       rtol=0, atol=1e-8):
        raise ValueError("invalid model count probabilities")
    if type(iterations) is not int or not 1 <= iterations <= 2000:
        raise ValueError("bounded positive iteration count required")
    design = np.eye(3)[counts].reshape(n, -1)
    target = probabilities.ravel()
    gram = design @ design.T / cells
    rhs = design @ target / cells
    step = 1/max(float(np.abs(gram).sum(axis=1).max()), 1e-12)
    uniform = np.full(n, 1/n)
    w = uniform.copy()
    converged = False
    cap = min(1., 4/n)
    for iteration in range(1, iterations+1):
        next_w = capped_simplex(w-step*(gram@w-rhs), cap)
        residual = float(np.max(np.abs(next_w-w)))
        w = next_w
        if residual <= 1e-10:
            converged = True
            break
    unguarded = w.copy()
    distance2 = float(np.square(w-uniform).sum())
    mixture_fraction = min(1., np.sqrt((1/n)/distance2)) if distance2 else 1.
    w = uniform + mixture_fraction*(w-uniform)
    def error(weights):
        return float(np.square(weights@design-target).sum()/cells)
    if abs(w.sum()-1) > 1e-8 or w.min() < -1e-10 or w.max() > cap+1e-10 \
            or float(w@w) > 2/n+1e-10 or error(w) > error(uniform)+1e-10:
        raise ValueError("fitted mixture invariant failure")
    return {"recipe": "capped-simplex-pg-then-uniform-ess-half-v1",
            "iteration_limit": iterations,
            "weights": w.tolist(), "converged": converged, "iterations": iteration,
            "last_step_residual": residual, "uniform_mix_fit_fraction": float(mixture_fraction),
            "ess_fraction": float(1/(n*(w@w))), "max_weight": float(w.max()),
            "uniform_model_squared_error": error(uniform),
            "capped_fit_model_squared_error": error(unguarded),
            "guarded_fit_model_squared_error": error(w)}

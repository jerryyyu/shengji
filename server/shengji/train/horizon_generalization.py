"""Held-out-world ranking contrast for serialized paired-horizon captures.

This measures generalization across sampled worlds under the same evaluator,
not actual-game utility. Worlds may be correlated; folds are not independent
trials and their dispersion is not a gameplay confidence interval.
"""

from __future__ import annotations

import numpy as np


def held_out_horizon(record):
    """Select each horizon's move on one parity, evaluate on the other.

    World indices are fixed before inspecting values. Both arms use the same
    split and first-argmax tie rule. Every world is evaluated exactly once,
    without contributing to selection of the moves evaluated on that world.
    Incomplete captures are not silently turned into smaller experiments.
    """
    horizon = record.get("paired_horizon")
    if not isinstance(horizon, dict) or horizon.get("status") != "complete":
        raise ValueError("requires a complete paired-horizon capture")
    decision = record.get("decision")
    if not isinstance(decision, dict):
        replay = record.get("replay")
        decision = replay.get("decision") if isinstance(replay, dict) else None
    actions = horizon.get("actions")
    if (not isinstance(actions, list) or not actions or not isinstance(decision, dict)
            or actions != decision.get("admitted")):
        raise ValueError("capture ballot differs from decision")
    worlds = horizon.get("worlds")
    if type(worlds) is not int or worlds < 4:
        raise ValueError("requires at least four sampled worlds")
    arms = horizon.get("arms")
    if not isinstance(arms, dict):
        raise ValueError("missing horizon arms")
    matrices = {}
    for name in ("trick", "policy"):
        arm = arms.get(name)
        if not isinstance(arm, dict):
            raise ValueError("missing horizon arm")
        matrix = np.asarray(arm.get("values"), dtype=np.float64)
        if matrix.shape != (worlds, len(actions)) or not np.isfinite(matrix).all():
            raise ValueError("horizon matrix must be finite and match world/ballot shape")
        matrices[name] = matrix
    indices = np.arange(worlds)
    gaps = np.empty(worlds, dtype=np.float64)
    folds = []
    for parity in (0, 1):
        train = indices % 2 == parity
        test = ~train
        winners = {name: int(np.argmax(matrix[train].mean(axis=0)))
                   for name, matrix in matrices.items()}
        gap = (matrices["policy"][test, winners["policy"]]
               - matrices["policy"][test, winners["trick"]])
        gaps[test] = gap
        folds.append(dict(selection_parity=parity, selection_worlds=int(train.sum()),
                          evaluation_worlds=int(test.sum()),
                          trick_index=winners["trick"], policy_index=winners["policy"],
                          winner_flip=winners["trick"] != winners["policy"],
                          held_out_gap_mean=float(gap.mean())))
    return dict(schema="paired-horizon-held-out-v1", worlds=worlds, folds=folds,
                held_out_gap_mean=float(gaps.mean()),
                claim="Evaluator-relative sampled-world generalization, not gameplay strength; "
                      "no independence or confidence-interval claim.")

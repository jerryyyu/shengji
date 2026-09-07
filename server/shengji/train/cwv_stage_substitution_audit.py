"""Cross-fitted, finite-reference substitutions for a fixed shortlist union.

Not an oracle or a playable policy: reference ranking and direct selection
consume many heuristic-continuation returns. Disjoint rows judge each fold's
choices. Reusing previously inspected FIT worlds does not create a holdout.
"""
from __future__ import annotations

import numpy as np


def fold_plan(levels, ballots, incumbent: int, *, k: int = 5):
    """Use even/odd WORLD rows jointly across columns; reverse, then average.

    Column order is canonical action order. Reference ranking breaks ties by
    column index. Direct choice breaks ties by ballot order (incumbent first).
    Neither choice function sees that fold's evaluation mean.
    """
    values = np.asarray(levels, dtype=float)
    if values.ndim != 2 or values.shape[0] < 2 or values.shape[0] % 2 or not np.isfinite(values).all():
        raise ValueError('reference must be a finite even-row matrix')
    n = values.shape[1]
    if type(incumbent) is not int or not 0 <= incumbent < n or type(k) is not int or k < 1:
        raise ValueError('invalid incumbent or cardinality')
    if not ballots:
        raise ValueError('no model ballots')
    for ballot in ballots.values():
        if (len(ballot) != min(k, n) or len(set(ballot)) != len(ballot)
                or ballot[0] != incumbent
                or any(type(i) is not int or not 0 <= i < n for i in ballot)):
            raise ValueError('ballot population or incumbent mismatch')
    if set().union(*(set(b) for b in ballots.values())) != set(range(n)):
        raise ValueError('matrix must cover exactly the frozen model-ballot union')
    folds = []
    for parity in (0, 1):
        fit = list(range(parity, len(values), 2))
        judge = list(range(1 - parity, len(values), 2))
        fit_mean = values[fit].mean(0)
        ranked = sorted((i for i in range(n) if i != incumbent), key=lambda i: (-fit_mean[i], i))
        reference_ballot = [incumbent] + ranked[:k - 1]
        folds.append({'selection_rows': fit, 'evaluation_rows': judge,
                      'reference_ballot': reference_ballot,
                      'reference_pick': max(reference_ballot, key=lambda i: fit_mean[i]),
                      'model_reference_picks': {
                          name: max(ballot, key=lambda i: fit_mean[i]) for name, ballot in ballots.items()},
                      'evaluation_means': values[judge].mean(0).tolist()})
    return folds

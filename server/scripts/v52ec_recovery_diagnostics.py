"""Direction-suppressed S8 recovery diagnostics; no file access or estimator.

Inputs are validated mirror-summed utilities and the pinned primary's SE.
This module alone is NOT a qualified reader or authority to reread the lane.
"""
import math


def numeric_diagnostics(candidate, comparator, *, bootstrap_se, clusters=520):
    """Return only r5's counts/flags, never outcomes or their direction.

    A nonfinite population leaves outcome-dependent counts undefined rather
    than accidentally counting NaN != 0 as an observed nonzero difference.
    SE zero is observed from the pinned bootstrap, not inferred from a tie.
    Structural failures use fixed messages without interpolating utilities.
    """
    if type(clusters) is not int or clusters < 2:
        raise ValueError('invalid expected population')
    if set(candidate) != set(comparator) or len(candidate) != clusters:
        raise ValueError('paired population mismatch')
    values = list(candidate.values()) + list(comparator.values())
    if any(type(v) not in (int, float) for v in values):
        raise ValueError('invalid utility type')
    if type(bootstrap_se) not in (int, float):
        raise ValueError('invalid bootstrap SE type')
    finite = {
        'candidate': all(math.isfinite(v) for v in candidate.values()),
        'comparator': all(math.isfinite(v) for v in comparator.values()),
    }
    deltas = [(candidate[k] - comparator[k]) / 2 for k in candidate]
    finite_deltas = all(math.isfinite(d) for d in deltas)
    finite_se = math.isfinite(bootstrap_se)
    observed = all(finite.values()) and finite_deltas
    return {
        'cluster_count': {'candidate': len(candidate), 'comparator': len(comparator)},
        'all_finite': finite,
        'paired_deltas_finite': finite_deltas,
        'bootstrap_se_finite': finite_se,
        'bootstrap_se_nonnegative': bootstrap_se >= 0 if finite_se else None,
        'n_nonzero_delta': sum(d != 0 for d in deltas) if observed else None,
        'se_zero': bootstrap_se == 0 if finite_se else None,
        'constant_nonzero': (
            deltas[0] != 0 and all(d == deltas[0] for d in deltas)
        ) if observed else None,
        'exact_committed_play_equality': {
            'status': 'UNIDENTIFIABLE', 'count': None,
            'reason': 'Only attempted-action traces and a 64-bit history digest persist; '
                      'the committed transcript is absent.',
        },
    }

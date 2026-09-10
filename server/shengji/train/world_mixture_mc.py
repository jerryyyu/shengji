"""DEV reduction of saved MC folds with fitted empirical-world mixtures.

No sampling, inference or true-state access here. The weighted paired bound is
exploratory, not a calibrated confidence interval for a learned posterior.
"""
from __future__ import annotations

import math
import numpy as np

from .r4_w32_mc import BASE, finalize, moments, nominate
from .world_mixture_fit import reweighted_consumer_means


def _weights(weights, n):
    if weights is None:
        return None
    w = np.asarray(weights, dtype=np.float64)
    if w.shape != (n,) or not np.isfinite(w).all() or (w < 0).any() \
            or abs(float(w.sum())-1) > 1e-8:
        raise ValueError("invalid MC mixture weights")
    if np.array_equal(w, np.full(n, 1/n)):
        return None  # Preserve ordinary MC's exact arithmetic and tie behavior.
    if float(w@w) >= 1:
        raise ValueError("insufficient MC mixture effective population")
    return w


def mixture_decision(actions, admitted, selection, report, sw=None, rw=None):
    """Use production nomination/tie rules and paired report threshold."""
    if not admitted or len(set(admitted)) != len(admitted):
        raise ValueError("nonempty distinct admitted indices required")
    for matrix in (selection, report):
        if len(matrix) < 2 or any(len(row) != len(actions) for row in matrix) \
                or not np.isfinite(np.asarray(matrix)).all():
            raise ValueError("invalid MC rollout matrix")
    if any(type(i) is not int or not 0 <= i < len(actions) for i in admitted):
        raise ValueError("admitted index outside action matrix")
    sw, rw = _weights(sw, len(selection)), _weights(rw, len(report))
    if sw is None:
        raw, challenger, values = nominate(actions, admitted, selection)
    else:
        ordinary = [moments([row[i] for row in selection])[0] for i in admitted]
        values = reweighted_consumer_means(
            [[row[i] for i in admitted] for row in selection], sw, ordinary).tolist()
        bot = BASE(seed=0)
        ordered = [actions[i] for i in admitted]
        raw = admitted[bot._pick_index(ordered, values, range(len(admitted)))]
        challenger = None if len(admitted) == 1 else admitted[
            bot._pick_index(ordered, values, range(1, len(admitted)))]
    if rw is None or challenger is None:
        final = finalize(admitted[0], challenger, report)
    else:
        gaps = [row[challenger]-row[admitted[0]] for row in report]
        ordinary_gap = moments(gaps)[0]
        gap = float(reweighted_consumer_means([[v] for v in gaps], rw, [ordinary_gap])[0])
        variance = math.fsum(float(w*w)*(v-gap)**2 for w, v in zip(rw, gaps))/(1-float(rw@rw))
        se = math.sqrt(max(0, variance))
        bot = BASE(seed=0)
        critical = bot._report_critical(len(report))
        statistic = gap-critical*se
        override = statistic >= bot.REPORT_MIN_GAIN
        final = {"played": challenger if override else admitted[0], "gap": gap,
                 "se": se, "statistic": statistic, "critical": critical,
                 "threshold": bot.REPORT_MIN_GAIN,
                 "reason": "report_lcb_override" if override else "report_lcb_below_min_gain"}
    return {**final, "raw_winner": raw, "challenger": challenger,
            "selection_means": values, "admitted": admitted}


def reduce_mixture_arms(actions, baseline, ranked, selection, report, fold_weights):
    """Ordinary, rank-only, MC-only and combined; shared tensors across arms."""
    if set(ranked) != set(fold_weights["selection"]) or set(ranked) != set(fold_weights["report"]):
        raise ValueError("MC mixture arm population differs")
    if any(not indices or indices[0] != baseline[0] for indices in ranked.values()):
        raise ValueError("mixture ranking changed incumbent")
    results = {"ordinary": mixture_decision(actions, baseline, selection, report)}
    for name, indices in ranked.items():
        sw, rw = (fold_weights[f][name] for f in ("selection", "report"))
        results[name+":rank-only"] = mixture_decision(actions, indices, selection, report)
        results[name+":mc-only"] = mixture_decision(actions, baseline, selection, report, sw, rw)
        results[name+":rank+mc"] = mixture_decision(actions, indices, selection, report, sw, rw)
    return results

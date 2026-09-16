"""Small shared-world leaf diagnostic, NOT a gameplay strength screen.

Full heuristic continuation is a named comparator, not optimal-play truth.
Keep each root's world/action matrix intact: action ordering is measured after
averaging identical worlds, never by counting correlated rows as games.
"""
from dataclasses import asdict
import time

import numpy as np

from ..ai.cwv_policy import afterstate, sample_worlds
from ..ai.cwv_puct import leaf_copy
from .cwv_truncated_value import continuation_values


class LeafRecorder:
    """Diagnostic evaluator wrapper: keep a bounded prefix of ACTUAL net leaves.

    Returns the wrapped scores unchanged. No rollout/comparator work occurs
    inside search. Prefix selection is explicit, outcome-blind and potentially
    unrepresentative; captures are correlated, not independent game samples.
    """
    def __init__(self, evaluator, limit=32):
        if type(limit) is not int or limit < 1:
            raise ValueError('positive capture limit required')
        self.evaluator, self.limit = evaluator, limit
        self.rows = []

    def score_many(self, states, seats):
        scores = self.evaluator.score_many(states, seats)
        for state, seat, score in zip(states, seats, scores, strict=True):
            if len(self.rows) == self.limit:
                break
            self.rows.append((leaf_copy(state), seat, float(score)))
        return scores

    def compare_full(self, batch_size=128):
        if not self.rows:
            raise ValueError('no model leaves captured')
        states, seats, predictions = zip(*self.rows)
        out = continuation_values(states, seats, [len(s.history) for s in states],
            evaluator=None, tricks=None, batch_size=batch_size)
        error = np.asarray(predictions) - out.values
        return dict(schema='cwv-actual-leaf-probe-v1', captured=len(states),
            capture_limit=self.limit, selection='prefix-of-actual-model-leaves',
            comparator='full-heuristic-not-optimal-policy-truth',
            units='root-team-final-signed-levels', predictions=list(predictions),
            full_heuristic_values=out.values.tolist(), perspectives=list(seats),
            trick_plays=[len(s.trick.plays) if s.trick else 0 for s in states],
            mean_bias=float(error.mean()), rmse=float(np.sqrt(np.mean(error**2))),
            heuristic_plies=out.heuristic_plies)

    def compare_evaluators(self, evaluators, batch_size=128):
        """Rescore identical captured leaves; run the named comparator once.

        Selection remains conditioned on the model that generated this search.
        This is neither a gameplay comparison nor independent calibration data.
        """
        if not evaluators:
            raise ValueError('at least one evaluator required')
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError('positive batch size required')
        report = self.compare_full(batch_size=batch_size)
        states, seats, _ = zip(*self.rows)
        reference = np.asarray(report['full_heuristic_values'])
        rescored = {}
        for name, evaluator in evaluators.items():
            values = []
            for start in range(0, len(states), batch_size):
                stop = start + batch_size
                chunk = np.asarray(evaluator.score_many(
                    [leaf_copy(s) for s in states[start:stop]], seats[start:stop]), float)
                if chunk.shape != (len(states[start:stop]),) or not np.isfinite(chunk).all():
                    raise ValueError('finite one-score-per-leaf vector required')
                values.extend(chunk.tolist())
            error = np.asarray(values) - reference
            rescored[name] = dict(predictions=values, mean_bias=float(error.mean()),
                rmse=float(np.sqrt(np.mean(error**2))))
        report['rescored'] = rescored
        report['selection_caveat'] = 'conditioned-on-capture-model-search-not-independent-games'
        return report


def compare_values(predicted, reference):
    predicted, reference = np.asarray(predicted, float), np.asarray(reference, float)
    if (predicted.ndim != 2 or predicted.shape != reference.shape
            or not all(predicted.shape) or not np.isfinite(predicted).all()
            or not np.isfinite(reference).all()):
        raise ValueError('finite matching nonempty world-by-action matrices required')
    p, r = predicted.mean(0), reference.mean(0)
    selected = int(np.argmax(p))
    # Only strict comparator preferences enter pairwise ordering accuracy.
    gaps, inferred = [], []
    for a in range(len(r)):
        for b in range(a):
            if r[a] != r[b]:
                gaps.append(r[a] - r[b])
                inferred.append(p[a] - p[b])
    return dict(worlds=len(predicted), actions=len(p), selected_index=selected,
                reference_best_index=int(np.argmax(r)),
                comparator_regret=float(r.max() - r[selected]),
                mean_bias=float((predicted-reference).mean()),
                rmse=float(np.sqrt(np.mean((predicted-reference)**2))),
                action_gap_rmse=float(np.sqrt(np.mean(((p-p[0])-(r-r[0]))**2))),
                strict_pairs=len(gaps),
                pairwise_accuracy=(float(np.mean(np.sign(gaps) == np.sign(inferred)))
                                   if gaps else None),
                predicted_action_means=p.tolist(), reference_action_means=r.tolist())


def probe_root(rnd, seat, actions, *, sampler, evaluator, worlds=4, batch_size=128):
    if type(worlds) is not int or worlds < 1 or not actions:
        raise ValueError('positive world count and nonempty actions required')
    sampled, attempts = sample_worlds(sampler, rnd, seat, worlds)
    if len(sampled) != worlds:
        raise ValueError('leaf diagnostic world pool underfilled')
    # Same accepted worlds in the same order for every horizon and action.
    leaves = [afterstate(rnd, seat, hands, buried, action)
              for hands, buried in sampled for action in actions]
    values, work = {}, {}
    for horizon in (None, 0, 1, 2):
        key = 'full' if horizon is None else str(horizon)
        started = time.perf_counter()
        result = continuation_values(leaves, [seat]*len(leaves),
            [len(rnd.history)]*len(leaves), evaluator=evaluator,
            tricks=horizon, batch_size=batch_size)
        values[key] = result.values.reshape(worlds, len(actions))
        work[key] = {k: v for k, v in asdict(result).items() if k != 'values'}
        work[key]['wall_seconds'] = time.perf_counter() - started
    return dict(schema='cwv-leaf-probe-v1', seat=seat, trick=len(rnd.history),
        cards_remaining=[len(hand) for hand in rnd.hands], actions=actions,
        sampled_worlds=[dict(hands=hands, buried=buried) for hands, buried in sampled],
        attempts=attempts, units='root-team-final-signed-levels',
        comparator='full-heuristic-not-optimal-policy-truth',
        values={k: v.tolist() for k, v in values.items()}, work=work,
        comparisons={k: compare_values(v, values['full']) for k, v in values.items() if k != 'full'})

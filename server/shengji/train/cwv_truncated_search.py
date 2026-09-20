"""DEV W32 admission with value-truncated selection AND independent report.

All search scores use acting-team signed levels, including the full-heuristic
control (tricks=None). The inherited MC ``LEVEL_OBJECTIVE`` is NOT this scale.
The report SE measures sampled-world dispersion, not learned-model uncertainty.
No registry/default change. Admission and world sampling remain inherited.
"""
import random

import numpy as np

from ..ai.cwv_policy import afterstate
from .cwv_shortlist import CWVShortlistBot
from .cwv_prior_admission import CWVPriorAdmissionBot
from .cwv_truncated_value import continuation_values


class TruncatedSearchMixin:
    POINT_SHY_EPS = 0.0

    def _pick_index(self, candidates, means, indices):
        indices = list(indices)
        if indices and all(value == float('-inf') for value in means):
            return indices[0]
        return super()._pick_index(candidates, means, indices)

    def __init__(self, *args, continuation_tricks=1, **kwargs):
        if continuation_tricks is not None and (
                type(continuation_tricks) is not int or continuation_tricks < 0):
            raise ValueError('invalid continuation horizon')
        super().__init__(*args, **kwargs)
        self.continuation_tricks = continuation_tricks
        self.continuation_counts = {}
        self.continuation_totals = dict.fromkeys(
            ('model_rows', 'model_batches', 'terminal_rows', 'heuristic_plies', 'worlds'), 0)

    def decide_play(self, rnd, seat):
        if (self.ADAPTIVE_ALLOCATION or self.EXTRA_SELECTION_WORK or self.LEVEL_OBJECTIVE
                or not self.REPORT_FOLD_WORLDS or self.REPORT_MIN_GAIN != 0):
            raise ValueError('truncated search requires uniform selection and zero-gain report')
        self.continuation_counts = dict.fromkeys(
            ('model_rows', 'model_batches', 'terminal_rows', 'heuristic_plies'), 0)
        result = super().decide_play(rnd, seat)
        if self.last_decision_record is not None:
            self.last_decision_record['value_continuation'] = {
                'schema': 'value-continuation-v1', 'tricks': self.continuation_tricks,
                'units': 'acting-team-final-signed-levels',
                'exact_endgame': False, **self.continuation_counts,
                # Parent's historical rollout counters count candidate-world
                # evaluations here, not necessarily completed playouts.
                'legacy_rollout_counter_units': 'candidate-world-evaluations',
                'report_uncertainty': 'sampled-world-only-not-model-error',
            }
        return result

    def _continuation_matrix(self, rnd, seat, candidates, mem, n):
        values = []
        attempts = 0
        pending, locations = [], []
        batch = self.shortlist_config.batch_size

        def flush():
            if not pending:
                return
            out = continuation_values(pending, [seat] * len(pending),
                                      [len(rnd.history)] * len(pending),
                                      evaluator=self.evaluator, tricks=self.continuation_tricks,
                                      batch_size=batch, policy=self.rollout_policy)
            for (wi, ci), value in zip(locations, out.values, strict=True):
                values[wi][ci] = value
            for key in self.continuation_counts:
                self.continuation_counts[key] += getattr(out, key)
                self.continuation_totals[key] += getattr(out, key)
            pending.clear()
            locations.clear()

        while len(values) < n and attempts < n * self.SAMPLE_ATTEMPT_FACTOR:
            attempts += 1
            world = self._sample_hands(rnd, seat, mem)
            if world is None:
                continue
            opponents, buried = world
            hands = self._complete_determinized_hands(rnd, seat, opponents, buried=buried)
            buried = sorted(buried)
            wi = len(values)
            values.append([0.] * len(candidates))
            for ci, action in enumerate(candidates):
                pending.append(afterstate(rnd, seat, hands, buried, action))
                locations.append((wi, ci))
                if len(pending) == batch:
                    flush()
        flush()
        self.continuation_totals['worlds'] += len(values)
        return np.asarray(values, dtype=np.float64).reshape(-1, len(candidates)), attempts

    def _selection_override(self, rnd, seat, candidates, mem, i_attack, *, allocation_rng):
        n = self.N_DETERMINIZATIONS
        vals, attempts = self._continuation_matrix(rnd, seat, candidates, mem, n)
        used, k = vals.shape
        differences = vals - vals[:, :1]
        self.last_alloc = {
            'mode': 'uniform-value-continuation', 'attempts': attempts,
            'attempt_cap': n * self.SAMPLE_ATTEMPT_FACTOR,
            'attempt_cap_hit': used < n, 'worlds': used, 'rollouts': used * k,
            'decision_rollouts': used * k, 'dummy_rollouts': 0, 'budget': n * k,
            'short': used < n, 'survivors': k, 'survivor_indices': list(range(k)),
            'n_by_candidate': [used] * k,
        }
        return (vals.sum(0).tolist(), differences.sum(0).tolist(),
                (differences ** 2).sum(0).tolist(), [used] * k, used)

    def _report_fold_gap(self, rnd, seat, mem, i_attack, cand_a, cand_b, n,
                         *, seed, keep_deltas=False):
        original_rng = self.rng
        try:
            self.rng = random.Random(seed)
            vals, attempts = self._continuation_matrix(rnd, seat, [cand_a, cand_b], mem, n)
        finally:
            self.rng = original_rng
        deltas = vals[:, 0] - vals[:, 1]
        used = len(deltas)
        result = dict(gap=float(deltas.mean()) if used else 0.,
                      se=self._paired_se(float(deltas.sum()), float((deltas ** 2).sum()), used),
                      worlds=used, attempts=attempts, rejected=attempts-used,
                      complete=used == n, seed=seed)
        if keep_deltas:
            result['deltas'] = deltas.tolist()
        return result


class CWVTruncatedSearchBot(TruncatedSearchMixin, CWVShortlistBot):
    pass


class CWVPriorTruncatedSearchBot(TruncatedSearchMixin, CWVPriorAdmissionBot):
    pass

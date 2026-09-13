"""Opt-in DEV control-variate selection, with unchanged point-based MC report.

Admission is the existing independent W32 ballot. Draw N new common worlds,
uniformly select m of them BEFORE scoring, and nominate a challenger using
mean_N(V) + mean_m(R-V). R and V are acting-team signed levels. The levels
control uses mean_m(R) on the identical subset, isolating the correction from
the points-to-levels objective change. Neither branch changes the report fold.
"""
from __future__ import annotations

import numpy as np

from ..ai.cwv_policy import afterstate
from ..rl.value_afterstate import category_signed_level, signed_level_category
from .cwv_bury_policy import CWVBuryBot
from .cwv_residual_diagnostic import corrected_estimate
from .cwv_shortlist import CWVShortlistBot


class CWVCorrectedRolloutBot(CWVShortlistBot):
    # Production's 2-point indifference band is not a 2-level band. For both
    # experimental selectors only exact ties use the inherited point-shy rule.
    POINT_SHY_EPS = 0.0
    def __init__(self, evaluator, *, correction_mode='corrected',
                 correction_worlds=64, residual_worlds=16, **kwargs):
        if correction_mode not in ('corrected', 'levels'):
            raise ValueError('unknown correction mode')
        if (type(correction_worlds) is not int or type(residual_worlds) is not int
                or not 1 <= residual_worlds <= correction_worlds):
            raise ValueError('require 1 <= residual worlds <= correction worlds')
        super().__init__(evaluator, **kwargs)
        if self.shortlist_config.uniform:
            raise ValueError('corrected selector requires learned admission')
        self.correction_mode = correction_mode
        self.correction_worlds = correction_worlds
        self.residual_worlds = residual_worlds
        self.corrected_rollout_counts = dict.fromkeys(
            ('decisions', 'model_evaluations', 'model_batches', 'sampled_worlds',
             'residual_worlds', 'rollouts', 'underfilled'), 0)

    def _pick_index(self, candidates, means, indices):
        indices = list(indices)
        if indices and all(value == float('-inf') for value in means):
            # Underfilled selection has no estimate. Parent records the refusal
            # and retains incumbent; avoid (-inf)-(-inf) in point-shy logic.
            return indices[0]
        return super()._pick_index(candidates, means, indices)

    def _selection_override(self, rnd, seat, candidates, mem, i_attack,
                            *, allocation_rng):
        # This implementation nominates only. Do not accidentally use its
        # unknown SE in an override rule or silently change the report units.
        if (self.ADAPTIVE_ALLOCATION or self.EXTRA_SELECTION_WORK
                or self.LEVEL_OBJECTIVE or self.REPORT_RULE != 'lcb'
                or self.REPORT_FOLD_WORLDS < 30):
            raise ValueError('corrected selector requires unchanged point-based LCB report')
        n, m, k = self.correction_worlds, self.residual_worlds, len(candidates)
        ids = allocation_rng.sample(range(n), m)
        worlds = []
        attempts = 0
        cap = n * self.SAMPLE_ATTEMPT_FACTOR
        while len(worlds) < n and attempts < cap:
            attempts += 1
            sampled = self._sample_hands(rnd, seat, mem)
            if sampled is not None:
                worlds.append(sampled)
        counts = self.corrected_rollout_counts
        counts['decisions'] += 1
        counts['sampled_worlds'] += len(worlds)
        complete = len(worlds) == n
        self.last_alloc = {
            'mode': 'model-corrected-rollout-v1', 'correction_mode': self.correction_mode,
            'selection_units': 'acting-team-signed-level', 'report_units': 'attacker-points',
            'selection_point_shy_eps': self.POINT_SHY_EPS,
            'attempts': attempts, 'attempt_cap': cap,
            'attempt_cap_hit': not complete and attempts >= cap,
            'worlds': len(worlds), 'model_worlds_requested': n,
            'residual_worlds_requested': m, 'residual_indices': ids,
            'rollouts': 0, 'decision_rollouts': 0, 'dummy_rollouts': 0,
            'budget': m * k, 'short': not complete, 'survivors': k,
            'survivor_indices': list(range(k)), 'n_by_candidate': [0] * k,
            'paired_se_available': False, 'model_evaluations': 0,
        }
        if not complete:
            counts['underfilled'] += 1
            return [0.] * k, [0.] * k, [0.] * k, [0] * k, len(worlds)

        # Keep only a small N*K scalar matrix; bound live afterstates by batch.
        v = np.empty((n, k), dtype=np.float64)
        pending, locations = [], []

        def flush():
            if not pending:
                return
            values = np.asarray(self.evaluator.score(pending, seat), dtype=np.float64)
            if values.shape != (len(pending),) or not np.isfinite(values).all():
                raise ValueError('expected one finite acting-team model value per leaf')
            for location, value in zip(locations, values, strict=True):
                v[location] = value
            counts['model_evaluations'] += len(pending)
            counts['model_batches'] += 1
            self.last_alloc['model_evaluations'] += len(pending)
            pending.clear()
            locations.clear()

        if self.correction_mode == 'corrected':
            for wi, (opponents, buried) in enumerate(worlds):
                hands = [list(rnd.hands[seat]) if s == seat else list(opponents[s])
                         for s in range(4)]
                for ci, action in enumerate(candidates):
                    pending.append(afterstate(rnd, seat, hands, buried, action,
                                              finish_trick=True))
                    locations.append((wi, ci))
                    if len(pending) >= self.shortlist_config.batch_size:
                        flush()
            flush()
        r = np.empty((m, k), dtype=np.float64)
        for ri, wi in enumerate(ids):
            opponents, buried = worlds[wi]
            session = self._new_exact_world_session(rnd, buried)
            for ci, action in enumerate(candidates):
                points = self._rollout(rnd, seat, opponents, buried, action,
                                       exact_session=session)
                if not np.isfinite(points) or float(points) != int(points):
                    raise ValueError('expected integral terminal attacker points')
                r[ri, ci] = category_signed_level(signed_level_category(int(points), i_attack))
        means = (corrected_estimate(v, r, ids) if self.correction_mode == 'corrected'
                 else r.mean(axis=0))
        counts['residual_worlds'] += m
        counts['rollouts'] += m * k
        self.last_alloc.update(rollouts=m * k, decision_rollouts=m * k,
                               n_by_candidate=[m] * k)
        # Parent divides by n_by; no fictitious confidence estimates are used.
        return (means * m).tolist(), [0.] * k, [0.] * k, [m] * k, n


class CWVCorrectedRolloutBuryBot(CWVCorrectedRolloutBot, CWVBuryBot):
    """Experimental play selector plus unchanged full-completion hybrid bury."""

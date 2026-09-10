"""Unregistered DEV ranking-only mixture around unchanged W32/hybrid bury.

MC-only/combined runtime paths are deliberately not silently approximated by
resampling. This first adapter changes only rank means; MC is inherited.
"""
from __future__ import annotations

import time
import numpy as np

from .cwv_bury_policy import CWVBuryBot
from .r4_runtime_client import actor_for_round
from .r4_w32_capture import RecordingEvaluator
from .r4_w32_weight_diagnostic import cell_count
from .world_mixture_fit import fit_world_mixture, reweighted_consumer_means


class R4MixtureRankBot(CWVBuryBot):
    def __init__(self, evaluator, *, client, model_arm, seed=0):
        if model_arm not in ('ordinary', 'synthetic-primary', 'hard-geometry-label-permutation'):
            raise ValueError('unknown R4 mixture arm')
        super().__init__(evaluator, seed=seed, arm='hybrid', reuse_successors=True)
        self.client = client
        self.model_arm = model_arm
        self.last_mixture = None

    def _means(self, rnd, seat, actions, worlds):
        self.last_mixture = None
        if self.model_arm == 'ordinary':
            return super()._means(rnd, seat, actions, worlds)
        started = time.monotonic()
        actor = actor_for_round(rnd, seat, self.client.archive_server)
        prediction = self.client.predict(actor)
        cells = prediction['arms'][self.model_arm]['ownership']['count_probabilities']
        counts = np.array([[cell_count(w, seat, c['card'], c['receiver']) for c in cells] for w in worlds])
        probabilities = np.array([c['count_probability_ppb'] for c in cells])/1e9
        fitted = fit_world_mixture(counts, probabilities)
        fitted_at = time.monotonic()
        delegate = self.evaluator
        recorder = RecordingEvaluator(delegate)
        try:
            self.evaluator = recorder
            ordinary = super()._means(rnd, seat, actions, worlds)
        finally:
            self.evaluator = delegate
        values = np.asarray(recorder.values).reshape(len(worlds), len(actions))
        result = reweighted_consumer_means(values, fitted['weights'], ordinary)
        self.last_mixture = {'actor_sha256': actor.sha256(), 'model_arm': self.model_arm,
                             'fit': fitted, 'inference_wall_s': prediction['inference_wall_s'],
                             'inference_and_fit_wall_s': fitted_at-started,
                             'ordinary_means': ordinary.tolist(), 'weighted_means': result.tolist(),
                             'mc_weighted': False, 'joint_posterior': False}
        return result

    def decide_play(self, rnd, seat):
        self.last_mixture = None
        action = super().decide_play(rnd, seat)
        if self.last_decision_record is not None and self.last_mixture is not None:
            self.last_decision_record['r4_mixture'] = self.last_mixture
        return action

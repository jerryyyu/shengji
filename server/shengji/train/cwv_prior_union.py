"""DEV-only union of the exhaustive CWV value shortlist and a public prior."""
from __future__ import annotations

import time

import numpy as np

from .cwv_shortlist import CWVShortlistBot, CWVShortlistConfig


class CWVPriorUnionBot(CWVShortlistBot):
    """Keep value finalists, then add distinct public-prior finalists."""

    def __init__(self, evaluator, prior_head, *, seed=0, config=None,
                 reuse_successors=False, prior_alternatives=2):
        if type(prior_alternatives) is not int or prior_alternatives < 1:
            raise ValueError("prior_count must be a positive integer")
        if prior_head is None:
            raise ValueError("prior union requires a public prior head")
        config = config or CWVShortlistConfig()
        if config.uniform:
            raise ValueError("prior union refuses a uniform shortlist")
        super().__init__(evaluator, seed=seed, config=config,
                         reuse_successors=reuse_successors)
        self.prior_head = prior_head
        self.prior_alternatives = prior_alternatives
        self._prior_union_detail = None

    def _choose_alternatives(self, rnd, seat, actions, means, base):
        value = super()._choose_alternatives(rnd, seat, actions, means, base)
        started = time.perf_counter()
        try:
            probabilities = self.prior_head.probabilities(rnd, seat, actions)
            probabilities = np.asarray(probabilities, dtype=np.float64)
        except AttributeError as exc:
            raise ValueError("CWV prior union requires public prior probabilities") from exc
        elapsed = time.perf_counter() - started
        if (probabilities.shape != (len(actions),)
                or not np.isfinite(probabilities).all()
                or (probabilities < 0).any()
                or not np.isclose(float(probabilities.sum()), 1.0,
                                  rtol=0.0, atol=1e-5)):
            raise ValueError(
                "CWV prior union requires finite nonnegative probabilities "
                "with one entry per legal action summing to one")

        selected = [base, *value]
        selected_keys = {tuple(sorted(actions[i])) for i in selected}
        ranked = sorted(
            range(len(actions)),
            key=lambda i: (-float(probabilities[i]), tuple(sorted(actions[i]))))
        added = []
        for index in ranked:
            key = tuple(sorted(actions[index]))
            if key in selected_keys:
                continue
            selected_keys.add(key)
            added.append(index)
            if len(added) == self.prior_alternatives:
                break
        self._prior_union_detail = {
            "value_alternatives": len(value),
            "requested_prior_count": self.prior_alternatives,
            "added_prior_count": len(added),
            "added_prior_indices": list(added),
            "prior_checkpoint_sha256": getattr(
                self.prior_head, "checkpoint_sha256", None),
            "prior_wall_secs": elapsed,
        }
        return [*value, *added]

    def _candidates(self, rnd, seat):
        # Direct callers can invoke _candidates without decide_play's reset;
        # never let a prior receipt leak into a forced singleton or refusal.
        self.last_shortlist = None
        self._prior_union_detail = None
        selected = super()._candidates(rnd, seat)
        if self._prior_union_detail is not None and self.last_shortlist is not None:
            self.last_shortlist["prior_union"] = dict(self._prior_union_detail)
        return selected

    def decide_play(self, rnd, seat):
        # MCBot's tractor-lock return happens before _candidates; clear the
        # hook state there as well as for ordinary and forced ballots.
        self._prior_union_detail = None
        return super().decide_play(rnd, seat)

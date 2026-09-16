"""Opt-in capture of actual search prior requests; never a gameplay metric.

Capture is an outcome-blind request prefix, conditioned on the generating
search. Priors express action preference, not terminal win probabilities.
No comparator work or additional model calls occur inside search.
"""
from dataclasses import dataclass

import numpy as np

from ..ai.cwv_puct import leaf_copy


@dataclass
class PriorRequest:
    state: object
    seat: int
    ballot: tuple
    observation: np.ndarray
    candidates: np.ndarray
    probabilities: np.ndarray | None = None


class PriorRecorder:
    """Wrap the encode/batch_from_encoded interface used by PUCT.

    Retain at most ``limit`` states. Request identity, not equal feature bytes,
    associates probabilities with the exact state/ballot that generated them.
    Unserved captured requests remain explicitly incomplete. This wrapper is
    diagnostic-only: copying states adds overhead, so its timing is not a
    performance comparison against an unwrapped search.
    """
    def __init__(self, prior, limit=16):
        if type(limit) is not int or limit < 1:
            raise ValueError("positive integer capture limit required")
        self.prior, self.limit = prior, limit
        self.rows = []
        self._pending = {}

    def __getattr__(self, name):
        return getattr(self.prior, name)

    def encode(self, state, seat, ballot):
        encoded = self.prior.encode(state, seat, ballot)
        if len(self.rows) < self.limit:
            row = PriorRequest(leaf_copy(state), seat,
                               tuple(tuple(play) for play in ballot),
                               np.array(encoded[0], copy=True),
                               np.array(encoded[1], copy=True))
            self.rows.append(row)
            # Retaining the encoded object prevents id reuse before dispatch.
            self._pending[id(encoded)] = (encoded, row)
        return encoded

    def batch_from_encoded(self, encoded_rows):
        output = self.prior.batch_from_encoded(encoded_rows)
        if len(output) != len(encoded_rows):
            raise ValueError("one prior vector per request required")
        for encoded, probabilities in zip(encoded_rows, output, strict=True):
            pending = self._pending.get(id(encoded))
            if pending is None:
                continue
            original, row = pending
            if original is not encoded:
                raise RuntimeError("prior request identity mismatch")
            p = np.asarray(probabilities)
            if (p.shape != (len(row.ballot),) or not np.isfinite(p).all()
                    or np.any(p < 0) or not np.isclose(p.sum(), 1.0, atol=1e-5, rtol=0)):
                raise ValueError("finite normalized ballot probability vector required")
            row.probabilities = p.copy()
            del self._pending[id(encoded)]
        return output

    def batch_probabilities(self, requests):
        return self.batch_from_encoded([self.encode(*request) for request in requests])

    def probabilities(self, state, seat, ballot):
        return self.batch_probabilities([(state, seat, ballot)])[0]


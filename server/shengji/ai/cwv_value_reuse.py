"""Bounded score reuse for immutable successor objects within ONE decision.

This is not a cache for live/mutable rounds. The owner must be the shortlist
successor sweep: its leaves are immutable after publication and the evaluator
and weights must remain fixed. Allocate a new instance for every sweep.
Deduplication changes inference batch shapes; numerical qualification is
required and this helper is not enabled by production defaults.
"""
from collections import OrderedDict

import numpy as np


class SuccessorValueCache:
    def __init__(self, evaluator, *, max_entries=128):
        if type(max_entries) is not int or max_entries < 1:
            raise ValueError("max_entries must be a positive integer")
        self._score = evaluator.score
        self.max_entries = max_entries
        self._entries = OrderedDict()
        self.rows = self.forwarded_rows = self.peak_entries = 0

    def score(self, positions, seat, *, tensor_cache=None):
        """Preserve row order/multiplicity while forwarding unique cache misses.

        Retained strong references prevent recycled object IDs from aliasing.
        Perspective is part of the key. Never cache partial/non-finite output.
        Temporary maps are bounded by the caller's inference batch, while
        persistent retained objects are bounded by ``max_entries``.
        """
        if type(seat) is not int or not 0 <= seat < 4:
            raise ValueError("seat must be an integer in [0,4)")
        if not positions:
            return np.empty(0, dtype=np.float64)
        keys = [(seat, id(state)) for state in positions]
        resolved, missing = {}, OrderedDict()
        for key, state in zip(keys, positions):
            hit = self._entries.get(key)
            if hit is not None and hit[0] is state:
                resolved[key] = hit[1]
                self._entries.move_to_end(key)
            else:
                missing[key] = state
        if missing:
            options = {} if tensor_cache is None else {"tensor_cache": tensor_cache}
            values = np.asarray(self._score(list(missing.values()), seat, **options),
                                dtype=np.float64)
            if values.shape != (len(missing),) or not np.isfinite(values).all():
                raise ValueError("value reuse requires one finite scalar per miss")
            for (key, state), value in zip(missing.items(), values):
                resolved[key] = value
                self._entries[key] = (state, value)
                self._entries.move_to_end(key)
                if len(self._entries) > self.max_entries:
                    self._entries.popitem(last=False)
        self.rows += len(positions)
        self.forwarded_rows += len(missing)
        self.peak_entries = max(self.peak_entries, len(self._entries))
        return np.asarray([resolved[key] for key in keys], dtype=np.float64)

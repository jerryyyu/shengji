"""Diagnostic-only same-leaf value/point capture on a caller-owned world tape.

No sampling, admission, model loading, artifact access or launch is performed.
Use only a dedicated, exclusively owned PVSearchBot with reviewed runtime pins.
The caller still establishes tape, root, model and complete legal-pool provenance.
"""
from __future__ import annotations

import numpy as np

from .ballot_matrix import _canonical_collection


class _PointCapture:
    def __init__(self, evaluator, root, seat, expected):
        self.evaluator = evaluator
        self.root = root
        self.seat = seat
        self.expected = expected
        self.points = []

    def score(self, leaves, seat):
        if seat != self.seat or len(self.points) + len(leaves) > self.expected:
            raise ValueError("unexpected capture seat or leaf count")
        points = []
        for leaf in leaves:
            trick = leaf.last_trick
            if (len(leaf.history) != len(self.root.history) + 1 or trick is None
                    or trick.winner is None):
                raise ValueError("capture leaf must resolve exactly the current trick")
            value = trick.points
            if type(value) is not int or value < 0:
                raise ValueError("resolved trick points must be a nonnegative integer")
            ours = self.root.is_attacker(trick.winner) == self.root.is_attacker(seat)
            points.append(value if ours else -value)
        # Delegate with the original leaves/order/seat, exactly once. Capture
        # before delegation so an evaluator cannot silently replace the leaf.
        scores = self.evaluator.score(leaves, seat)
        self.points.extend(points)
        return scores


def capture_fixed_tape(bot, root, seat, actions, worlds, *, check_budget=None):
    """Capture all action/world scores and signed points in one served loop.

    ``worlds`` must already be the complete frozen tape; nothing resamples it.
    Column order is the supplied order, NOT a newly sorted canonical ballot.
    The temporary evaluator decoration is restored even on an exception; callers
    must never share this bot concurrently. Any incomplete/failed work raises and
    returns no scientific result. This is not a packet/reader acceptance gate.
    """
    from ..train.pv_search_policy import PVSearchBot

    if not isinstance(bot, PVSearchBot):
        raise ValueError("a dedicated PVSearchBot is required")
    # Batch offsets only identify world/action cells under this exact traversal.
    # Refuse subclass/instance overrides rather than silently trusting order.
    if getattr(bot._score_leaves, "__func__", None) is not PVSearchBot._score_leaves:
        raise ValueError("canonical world-major scoring loop is required")
    _canonical_collection(actions, "actions")
    if type(worlds) is not list or not worlds:
        raise ValueError("a nonempty frozen world list is required")
    if type(seat) is not int or seat not in range(4) or root.turn != seat:
        raise ValueError("seat must be the root's current player")
    if any(not isinstance(world, (tuple, list)) or len(world) != 2 for world in worlds):
        raise ValueError("worlds must contain (hands, buried) pairs")
    original = bot.evaluator
    if isinstance(original, _PointCapture):
        raise ValueError("nested capture is forbidden")
    capture = _PointCapture(original, root, seat, len(worlds) * len(actions))
    bot.evaluator = capture
    try:
        # Invoke the canonical implementation, never a subclass's value_matrix.
        matrix, sums, batches = PVSearchBot.value_matrix(
            bot, root, seat, actions, worlds, check_budget=check_budget)
        if len(capture.points) != capture.expected:
            raise ValueError("incomplete same-leaf point capture")
        means = sums / len(worlds)
        if not np.isfinite(means).all():
            raise ValueError("nonfinite serving means")
        return {
            "schema": "fixed-tape-same-leaf-capture-v1",
            "actions": [list(action) for action in actions],
            "world_count": len(worlds),
            "value_matrix": matrix.tolist(),
            "serving_value_means": means.tolist(),
            "signed_trick_points": np.asarray(capture.points).reshape(
                len(worlds), len(actions)).tolist(),
            "batches": batches,
            "provenance_verified": False,
        }
    finally:
        bot.evaluator = original

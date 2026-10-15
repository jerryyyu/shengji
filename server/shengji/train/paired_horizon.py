"""DEV-only paired horizon measurement on an existing diagnostic tree bot.

No sampling, admission, selection or serving integration happens here. The
caller supplies one frozen ballot and world list to both arms. Continuations
are determinized policy-head replies (single-component next leads), not a
served information-set policy. Values are evaluator-relative, not strength.
"""
from __future__ import annotations

import copy
from dataclasses import replace
import time

import numpy as np


def _plays(rnd):
    tricks = [t.plays for t in rnd.history]
    if rnd.phase == "play":
        tricks.append(rnd.trick.plays)
    return tuple((p.seat, tuple(sorted(p.cards))) for plays in tricks for p in plays)


class _Leaves:
    def __init__(self, evaluator, root, horizon):
        self.evaluator = evaluator
        self.root_tricks = len(root.history)
        self.root_plies = len(_plays(root))
        self.horizon = horizon
        self.rows = []

    def score(self, leaves, seat):
        for leaf in leaves:
            tricks = len(leaf.history) - self.root_tricks
            terminal = leaf.phase == "round_end"
            if not terminal and (tricks != self.horizon or leaf.trick.plays):
                raise ValueError("horizon leaf is not at its requested trick boundary")
            if not 0 <= tricks <= self.horizon:
                raise ValueError("horizon leaf passed its requested boundary")
            sequence = _plays(leaf)[self.root_plies:]
            self.rows.append({"completed_tricks": tricks, "action_plies": len(sequence),
                              "terminal": terminal, "plays": sequence})
        return self.evaluator.score(leaves, seat)


def paired_horizon(bot, rnd, seat, actions, worlds, *, gate=None):
    """Measure current vs next completed trick, returning only a complete pair.

    Use a dedicated diagnostic bot: its predictor/evaluator are shared with
    shallow arm copies, but its config, sampler and game are not modified.
    ``gate`` is the caller's single deadline and exceptions propagate. A gate
    failure, continuation refusal or prefix mismatch publishes no partial arm.
    Matrix and leaf-row order is world-major, then ballot index in both arms.
    Action plies INCLUDE the submitted root action; terminal leaves may stop
    before the requested boundary. Timings include diagnostic instrumentation,
    not admission or the rest of the served decision.
    """
    if not actions or not worlds:
        raise ValueError("paired horizon requires a nonempty ballot and worlds")
    if rnd.phase != "play" or rnd.turn != seat:
        raise ValueError("paired horizon requires the acting play seat")
    actions = copy.deepcopy(list(actions))
    worlds = copy.deepcopy(list(worlds))
    root = copy.deepcopy(rnd)
    expected = (len(worlds), len(actions))
    result = {}
    for cont, horizon in (("trick", 1), ("policy", 2)):
        if gate is not None:
            gate()
        arm = copy.copy(bot)
        config = replace(bot.tree_config, cont=cont)
        arm.config = replace(bot.config, tree=config)
        # The audit's DiagBot borrows lookahead methods, but keeps its tree
        # config as an ordinary attribute; production tree bots use a property.
        if not isinstance(getattr(type(bot), "tree_config", None), property):
            arm.tree_config = config
        capture = _Leaves(bot.evaluator, root, horizon)
        arm.evaluator = capture
        start = time.perf_counter()
        values, stats = arm._tree_lookahead(root, seat, actions, worlds, gate=gate)
        elapsed = time.perf_counter() - start
        if gate is not None:
            gate()
        values = np.asarray(values, dtype=np.float64)
        if (values.shape != expected or not np.isfinite(values).all()
                or len(capture.rows) != expected[0] * expected[1]):
            raise ValueError("incomplete paired horizon matrix or leaves")
        result[cont] = {"values": values.copy(), "leaves": capture.rows,
                        "stats": stats, "seconds": elapsed}
    for shallow, deep in zip(result["trick"]["leaves"], result["policy"]["leaves"]):
        prefix = shallow["plays"]
        if deep["plays"][:len(prefix)] != prefix:
            raise ValueError("paired horizon arms disagree before the first boundary")
        if shallow["terminal"] and deep["plays"] != prefix:
            raise ValueError("paired horizon continued a terminal leaf")
    if gate is not None:
        gate()
    return result

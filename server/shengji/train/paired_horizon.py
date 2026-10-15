"""DEV-only paired horizon measurement on an existing diagnostic tree bot.

No sampling, admission, selection or serving integration happens here. The
caller supplies one frozen ballot and world list to both arms. Continuations
are determinized policy-head replies (single-component next leads), not a
served information-set policy. Values are evaluator-relative, not strength.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from dataclasses import replace
import time

import numpy as np


@contextmanager
def capture_horizon_inputs(bot):
    """Observe the final selection call without redrawing worlds or candidates."""
    captured = {}
    original = bot._select
    had_own = "_select" in vars(bot)
    own = vars(bot).get("_select")

    def observe(rnd, seat, admitted, means, *args, **kwargs):
        selected = original(rnd, seat, admitted, means, *args, **kwargs)
        worlds = kwargs.get("worlds", args[0] if args else None)
        captured.clear()
        if worlds is not None:
            captured.update(root=copy.deepcopy(rnd), seat=seat,
                            actions=copy.deepcopy(admitted), worlds=copy.deepcopy(worlds))
        return selected

    bot._select = observe
    try:
        yield captured
    finally:
        if had_own:
            bot._select = own
        else:
            del bot._select


def measure_captured_horizon(bot, captured, record, *, gate):
    """Collector consumer; skips fallback/stale ballots rather than mispairing.

    Only invoke after preserving the actual served decision. Uses borrowed
    lookahead methods on a diagnostic copy, never on the playing bot.
    """
    from .pv_tree_config import PVTreeConfig
    from .pv_tree_search import PVTreeMixin
    if not record or record.get("work_complete") is not True or not captured:
        return {"status": "skipped", "reason": "incomplete_served_capture"}
    if record.get("admitted") != captured["actions"]:
        return {"status": "skipped", "reason": "final_ballot_mismatch"}
    diagnostic = copy.copy(bot)
    if not isinstance(bot, PVTreeMixin):
        diagnostic.__class__ = type("HorizonDiagnostic", (PVTreeMixin, type(bot)), {})
    diagnostic.config = replace(bot.config, tree=PVTreeConfig(sims=64))
    pair = paired_horizon(diagnostic, captured["root"], captured["seat"],
                          captured["actions"], captured["worlds"], gate=gate)
    return {"status": "complete", "actions": captured["actions"],
            "worlds": len(captured["worlds"]),
            "arms": {name: {**arm, "values": arm["values"].tolist()}
                     for name, arm in pair.items()}}


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

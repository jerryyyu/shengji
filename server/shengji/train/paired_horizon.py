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


def _horizon_record_parts(record, decision):
    if not isinstance(record, dict):
        raise ValueError("horizon record must be an object")
    if decision is None:
        if "paired_horizon" in record:
            horizon = record["paired_horizon"]
            replay = record.get("replay")
            decision = (record.get("decision") if isinstance(record.get("decision"), dict)
                        else replay.get("decision") if isinstance(replay, dict) else record)
        else:
            horizon, decision = record, record
    else:
        horizon = record
    if not isinstance(horizon, dict):
        raise ValueError("paired_horizon must be an object")
    return horizon, decision


def _leaf_summary(arm, name, expected_count):
    leaves = arm.get("leaves")
    if leaves is None:
        return None
    if not isinstance(leaves, list) or len(leaves) != expected_count:
        raise ValueError(f"{name}.leaves must contain {expected_count} rows")
    plies, tricks, terminals = [], [], 0
    for index, leaf in enumerate(leaves):
        if not isinstance(leaf, dict):
            raise ValueError(f"{name}.leaves[{index}] must be an object")
        action_plies = leaf.get("action_plies")
        completed_tricks = leaf.get("completed_tricks")
        terminal = leaf.get("terminal")
        if (type(action_plies) is not int or action_plies < 0
                or type(completed_tricks) is not int or completed_tricks < 0
                or type(terminal) is not bool):
            raise ValueError(f"{name}.leaves[{index}] has invalid depth metadata")
        plies.append(action_plies)
        tricks.append(completed_tricks)
        terminals += int(terminal)
    return {
        "action_plies_min": min(plies), "action_plies_max": max(plies),
        "completed_tricks_min": min(tricks), "completed_tricks_max": max(tricks),
        "terminal_count": terminals,
    }


def summarize_captured_horizon(record, decision=None):
    """Summarize one completed paired horizon without claiming true strength.

    ``record`` may be a collector row containing ``paired_horizon`` and a
    replay decision, or a serialized paired-horizon object when ``decision``
    is supplied explicitly.  The two winners are deterministic first-argmax
    value-head means with the policy replies held fixed under the same worlds
    and ballot.  The deep-arm gap is conditional on those selected winners;
    its SE describes paired world variation, and does not quantify selection
    bias or an unbiased benefit estimate.
    """
    horizon, decision = _horizon_record_parts(record, decision)
    status = horizon.get("status")
    if status in ("skipped", "abandoned"):
        result = {"status": status}
        if "reason" in horizon:
            result["reason"] = horizon["reason"]
        return result
    if status != "complete":
        raise ValueError("paired_horizon status must be complete, skipped, or abandoned")
    if not isinstance(decision, dict):
        raise ValueError("complete horizon requires a decision object")
    actions = horizon.get("actions")
    admitted = decision.get("admitted")
    if not isinstance(actions, list) or not actions:
        raise ValueError("complete horizon actions must be a nonempty list")
    if not isinstance(admitted, list) or actions != admitted:
        raise ValueError("complete horizon actions do not match admitted ballot")
    worlds = horizon.get("worlds")
    if type(worlds) is not int or worlds <= 0:
        raise ValueError("complete horizon worlds must be a positive integer")
    arms = horizon.get("arms")
    if not isinstance(arms, dict):
        raise ValueError("complete horizon arms must be an object")
    matrices = {}
    for name in ("trick", "policy"):
        arm = arms.get(name)
        if not isinstance(arm, dict):
            raise ValueError(f"complete horizon missing {name} arm")
        try:
            matrix = np.asarray(arm.get("values"), dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} values must be a numeric matrix") from exc
        expected = (worlds, len(actions))
        if matrix.shape != expected or not np.isfinite(matrix).all():
            raise ValueError(f"{name} values must be finite with shape {expected}")
        matrices[name] = matrix

    shallow_means = matrices["trick"].mean(axis=0)
    deep_means = matrices["policy"].mean(axis=0)
    shallow_index = int(np.argmax(shallow_means))
    deep_index = int(np.argmax(deep_means))
    paired_gap = matrices["policy"][:, deep_index] - matrices["policy"][:, shallow_index]
    result = {
        "status": "complete",
        "claim": ("Evaluator-relative, in-sample selected-winner contrast; conditional SE "
                   "excludes selection bias and is not gameplay strength."),
        "trick_mean_argmax_index": shallow_index,
        "trick_mean_argmax_action": copy.deepcopy(actions[shallow_index]),
        "trick_mean_argmax_value": float(shallow_means[shallow_index]),
        "policy_mean_argmax_index": deep_index,
        "policy_mean_argmax_action": copy.deepcopy(actions[deep_index]),
        "policy_mean_argmax_value": float(deep_means[deep_index]),
        "winner_flip": shallow_index != deep_index,
        "policy_winner_minus_trick_winner_mean": float(paired_gap.mean()),
        "policy_winner_minus_trick_winner_se": (
            float(np.std(paired_gap, ddof=1) / np.sqrt(worlds)) if worlds > 1 else None
        ),
    }
    actual = {}
    for name in ("trick", "policy"):
        leaf_summary = _leaf_summary(arms[name], name, worlds * len(actions))
        if leaf_summary is not None:
            actual[name] = leaf_summary
    if actual:
        result["actual"] = actual
    return result


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
    # The real evaluator keeps scalar work/timing counters on the instance.
    # Share its immutable model weights, not the playing bot's accounting.
    diagnostic.evaluator = copy.copy(bot.evaluator)
    if not isinstance(bot, PVTreeMixin):
        diagnostic.__class__ = type("HorizonDiagnostic", (PVTreeMixin, type(bot)), {})
    diagnostic.config = replace(bot.config, tree=PVTreeConfig(sims=64))
    pair = paired_horizon(diagnostic, captured["root"], captured["seat"],
                          captured["actions"], captured["worlds"], gate=gate)
    result = {"status": "complete", "actions": captured["actions"],
              "worlds": len(captured["worlds"]),
              "arms": {name: {**arm, "values": arm["values"].tolist()}
                       for name, arm in pair.items()}}
    result["summary"] = summarize_captured_horizon(result, record)
    if gate is not None:
        gate()
    return result


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

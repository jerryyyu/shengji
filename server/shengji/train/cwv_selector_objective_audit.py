"""Replay the production MC-LCB selector under alternate point objectives.

This is an audit/research helper.  It supplies saved attacker-point values to
the actual production decision consumer, so its selection pairing, report
confidence bound, tie-break, and record remain authoritative.  No rollout or
policy registration occurs here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from ..ai.registry import REGISTRY
from ..teacher_v1 import attacker_level_utility
from .cwv_horizon_audit import _actions


def _points(values: Any, name: str, *, columns: int, min_rows: int = 1) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != columns or array.shape[0] < min_rows:
        raise ValueError(f"{name} must have shape (N, {columns}) with enough rows")
    if not np.isfinite(array).all() or np.any(array < 0) or np.any(array > 4_120):
        raise ValueError(f"{name} must contain finite engine-bounded points")
    if not np.equal(array, np.floor(array)).all():
        raise ValueError(f"{name} must contain integral engine points")
    return np.array(array, dtype=np.float64, copy=True)


def _seed_ok(seed: object) -> None:
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise ValueError("seed must be an integer or None")


def replay_selector(rnd, seat: int, ballot: Sequence[Sequence[str]],
                    selection_points: Any, report_points: Any, *, seed: int,
                    objective: str = "points") -> dict[str, Any]:
    """Replay native MC-LCB with saved point matrices and one chosen objective."""
    if isinstance(seat, bool) or not isinstance(seat, int) or not 0 <= seat < 4:
        raise ValueError("seat must be an integer in [0, 3]")
    _seed_ok(seed)
    if objective not in {"points", "levels"}:
        raise ValueError("objective must be 'points' or 'levels'")
    actions = _actions(ballot)
    selection = _points(selection_points, "selection_points",
                        columns=len(actions))
    report = _points(report_points, "report_points", columns=len(actions), min_rows=30)

    production = REGISTRY["mc-s0-report-lcb"]

    class ReplayWorld:
        __slots__ = ("fold", "row")

        def __init__(self, fold: str, row: int):
            self.fold = fold
            self.row = row

    def fixed_candidates(self, _rnd, _seat):
        return [list(action) for action in self._replay_ballot]

    def replay_sample(self, _rnd, _seat, _mem):
        if self.rng is self._selection_rng:
            row = self._selection_next
            if row >= self._selection_values.shape[0]:
                raise ValueError("selection replay consumed more rows than supplied")
            self._selection_next += 1
            fold = "selection"
        else:
            row = self._report_next
            if row >= self._report_values.shape[0]:
                raise ValueError("report replay consumed more rows than supplied")
            self._report_next += 1
            fold = "report"
        self.sample_attempts += 1
        self.accepted_worlds += 1
        return ReplayWorld(fold, row), []

    def replay_rollout(self, _rnd, _seat, sampled, _buried, candidate, **_kwargs):
        if not isinstance(sampled, ReplayWorld):
            raise ValueError("replay received an unexpected sampled-world marker")
        key = tuple(sorted(candidate))
        try:
            column = self._replay_action_indices[key]
        except KeyError:
            raise ValueError("replay received an action outside the fixed ballot") from None
        values = (self._selection_values if sampled.fold == "selection"
                  else self._report_values)
        return float(values[sampled.row, column])

    attrs = {
        "N_DETERMINIZATIONS": int(selection.shape[0]),
        "REPORT_FOLD_WORLDS": int(report.shape[0]),
        "TRACTOR_LOCK": False,
        "_candidates": fixed_candidates,
        "_sample_hands": replay_sample,
        "_rollout": replay_rollout,
    }
    if objective == "levels":
        def level_score(self, points):
            return 40.0 * attacker_level_utility(int(points))
        attrs["_score"] = level_score
    replay_type = type("CWVSelectorObjectiveReplay", (production,), attrs)
    bot = replay_type(seed)
    bot._replay_ballot = tuple(tuple(action) for action in actions)
    bot._replay_action_indices = {
        tuple(sorted(action)): index for index, action in enumerate(actions)
    }
    bot._selection_values = selection
    bot._report_values = report
    bot._selection_rng = bot.rng
    bot._selection_next = 0
    bot._report_next = 0

    played = bot.decide_play(rnd, seat)
    if len(actions) > 1:
        if bot._selection_next != selection.shape[0]:
            raise ValueError("selection replay did not consume every supplied row")
        if bot._report_next != report.shape[0]:
            raise ValueError("report replay did not consume every supplied row")
    elif bot._selection_next != 0 or bot._report_next != 0:
        raise ValueError("single-candidate replay unexpectedly consumed saved values")
    record = bot.last_decision_record
    if record is not None:
        record["replay"] = {
            "mode": "saved_attacker_points",
            "objective": objective,
            "selection_values": int(selection.size),
            "report_values": int(report.size) if len(actions) > 1 else 0,
            "fresh_rollouts": 0,
            "cpu_work": "replayed_values",
        }
    return {"played": played, "record": record}


__all__ = ["replay_selector"]

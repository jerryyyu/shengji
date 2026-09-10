"""Bounded counterfactual completion for declaration decisions.

The sampler is deliberately kept in :mod:`declare_completion`.  This module
only completes one already-sampled prefix and compares legal declarations (or
waiting) on exact deep copies of that prefix.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
import math
from typing import Any

from ..ai.smart import SmartBot
from .declare_completion import baseline_action, build_sampled_prefix


def _normal_action(action: Sequence[str] | None) -> tuple[str, ...] | None:
    if action is None:
        return None
    if isinstance(action, (str, bytes)):
        raise ValueError("declaration action must be a sequence of cards")
    try:
        return tuple(action)
    except TypeError as exc:
        raise ValueError("declaration action must be a sequence of cards") from exc


def finish_declarations(rnd: Any, observation: Any,
                        action: Sequence[str] | None) -> Any:
    """Apply callbacks through declaration finalization, stopping at bury.

    ``None`` means that the focal player waits at this callback.  It is not a
    pass: all players are passed only after the remaining declaration callbacks
    have run.
    """
    current = _normal_action(action)
    legal = {tuple(option) for option in observation.options}
    if current is not None:
        if current not in legal:
            raise ValueError("action is not legal for this declaration callback")
        rnd.declare(observation.seat, list(current))

    bot = SmartBot()
    if not observation.final:
        while rnd.phase == "deal":
            seat, _, _ = rnd.deal_next()
            next_action = bot.decide_declare(rnd, seat, final=False)
            if next_action is not None:
                rnd.declare(seat, next_action)
        final_seats = range(4)
    else:
        final_seats = range(observation.seat + 1, 4)

    for seat in final_seats:
        next_action = bot.decide_declare(rnd, seat, final=True)
        if next_action is not None:
            rnd.declare(seat, next_action)

    # Passing is intentionally deferred until every future callback has had a
    # chance to declare.  In particular, focal ``action=None`` is only a wait.
    for seat in range(4):
        rnd.pass_declare(seat)
    rnd.finalize_declare()
    return rnd


def _candidate_actions(observation: Any) -> list[tuple[str, ...] | None]:
    baseline = baseline_action(observation)
    legal = {tuple(option) for option in observation.options}
    candidates: list[tuple[str, ...] | None] = []
    seen: set[tuple[str, ...] | None] = set()

    def add(action: tuple[str, ...] | None) -> None:
        if action not in seen:
            seen.add(action)
            candidates.append(action)

    if baseline is not None:
        add(baseline)
    add(None)
    for action in sorted(legal):
        add(action)
    return candidates


def evaluate_actions(observation: Any, *, seeds: tuple[int, ...],
                     evaluator: Callable[..., Mapping[str, Any]]) -> dict[str, Any]:
    """Evaluate every legal declaration and waiting on common sampled worlds."""
    if not isinstance(seeds, tuple) or not seeds:
        raise ValueError("seeds must be a non-empty tuple")
    if len(set(seeds)) != len(seeds):
        raise ValueError("seeds must not contain duplicates")

    candidates = _candidate_actions(observation)
    rows_by_action: dict[tuple[str, ...] | None, list[dict[str, Any]]] = {
        action: [] for action in candidates
    }
    for seed in seeds:
        # Sampling is independent of action outcomes.  Every candidate gets a
        # fresh copy of exactly this one sampled prefix.
        prefix = build_sampled_prefix(observation, seed)
        for action in candidates:
            completed = finish_declarations(copy.deepcopy(prefix), observation,
                                             action)
            metrics = evaluator(completed,
                                focal_team=observation.seat % 2,
                                seed=seed)
            if not isinstance(metrics, Mapping):
                raise TypeError("evaluator must return a metrics mapping")
            if "focal_signed_levels" not in metrics:
                raise KeyError("evaluator metrics lack focal_signed_levels")
            try:
                signed_levels = float(metrics["focal_signed_levels"])
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(
                    "focal_signed_levels must be a finite number") from exc
            if not math.isfinite(signed_levels):
                raise ValueError("focal_signed_levels must be a finite number")
            rows_by_action[action].append({"seed": seed,
                                           "metrics": dict(metrics)})

    output_actions: list[dict[str, Any]] = []
    for action in candidates:
        rows = rows_by_action[action]
        mean = (sum(float(row["metrics"]["focal_signed_levels"])
                    for row in rows) / len(rows))
        output_actions.append({
            "action": None if action is None else list(action),
            "rows": rows,
            "mean_signed_levels": mean,
        })

    selected = candidates[0]
    best_mean = output_actions[0]["mean_signed_levels"]
    for action, result in zip(candidates[1:], output_actions[1:]):
        if result["mean_signed_levels"] > best_mean:
            selected, best_mean = action, result["mean_signed_levels"]
    return {"actions": output_actions,
            "selected_action": None if selected is None else list(selected)}

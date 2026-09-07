"""Small, bounded diagnostics for comparing CWV afterstate horizons.

This module is deliberately an audit surface: it does not register a policy,
change production defaults, or select a training population.  The matrix
helper keeps the sampled worlds and candidate order supplied by its caller and
scores world-major rows in bounded batches.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from ..ai.cwv_policy import afterstate
from ..ai.cwv_successor_reuse import TensorInputCache, WorldSuccessorCache
from ..ai.registry import REGISTRY
from ..rl.value_afterstate import category_signed_level, signed_level_category


def _positive_int(value: object, name: str, *, zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < (0 if zero else 1):
        bound = "non-negative" if zero else "positive"
        raise ValueError(f"{name} must be {bound}")
    return value


def _actions(actions: Sequence[Sequence[str]]) -> list[list[str]]:
    if isinstance(actions, (str, bytes)):
        raise ValueError("actions must be a non-empty sequence of card sequences")
    out = list(actions)
    if not out:
        raise ValueError("actions must be non-empty")
    keys: set[tuple[str, ...]] = set()
    for action in out:
        if isinstance(action, (str, bytes)):
            raise ValueError("each action must be a non-empty card sequence")
        cards = list(action)
        if not cards or any(not isinstance(card, str) for card in cards):
            raise ValueError("each action must be a non-empty card sequence")
        key = tuple(sorted(cards))
        if key in keys:
            raise ValueError("actions must be unique by sorted card tuple")
        keys.add(key)
    return out


def _validator():
    # The production determinization validator is the one place that knows
    # the current deck, played-card accounting, and hidden-seat contract.
    return REGISTRY["mc-s0-report-lcb"](seed=0)


def _world_parts(world: object) -> tuple[object, object]:
    if isinstance(world, (str, bytes)) or not isinstance(world, Sequence):
        raise ValueError("each world must be a (hands, buried) pair")
    if len(world) != 2:
        raise ValueError("each world must be a (hands, buried) pair")
    return world[0], world[1]


def _canonical_worlds(rnd, seat: int, worlds: Sequence[Any]):
    if isinstance(worlds, (str, bytes)):
        raise ValueError("worlds must be a non-empty sequence")
    supplied = list(worlds)
    if not supplied:
        raise ValueError("worlds must be non-empty")
    checker = _validator()
    canonical: list[tuple[list[list[str]], list[str]]] = []
    for world in supplied:
        hands_obj, buried_obj = _world_parts(world)
        if isinstance(buried_obj, (str, bytes)):
            raise ValueError("buried must be a card sequence")
        buried = list(buried_obj)
        if any(not isinstance(card, str) for card in buried):
            raise ValueError("buried must contain card strings")
        if isinstance(hands_obj, Mapping):
            sampled = {key: list(value) for key, value in hands_obj.items()}
        else:
            if isinstance(hands_obj, (str, bytes)) or not isinstance(hands_obj, Sequence):
                raise ValueError("hands must be complete hands or hidden-seat mapping")
            full = list(hands_obj)
            if len(full) != 4:
                raise ValueError("complete hands must contain four seats")
            sampled = {other: list(full[other]) for other in range(4) if other != seat}
        try:
            full_hands = checker._complete_determinized_hands(
                rnd, seat, sampled, buried=buried)
        except Exception:
            # Keep engine contract errors (including their useful messages),
            # while refusing malformed audit inputs before any scoring work.
            raise
        # Repeated complete worlds are legitimate draws with replacement and
        # must remain separate rows in the requested posterior/sample dose.
        canonical.append(([list(hand) for hand in full_hands], sorted(buried)))
    return canonical


def _score_support(evaluator: object, leaves: list[Any], seat: int,
                   tensor_cache: TensorInputCache):
    score = getattr(evaluator, "score", None)
    if not callable(score):
        raise TypeError("each evaluator must provide score(positions, seat)")
    # Tiny test evaluators and diagnostic doubles commonly implement the
    # historical two-argument method.  CompleteWorldEvaluator additionally
    # accepts tensor_cache; use it whenever the callable advertises support.
    try:
        params = inspect.signature(score).parameters.values()
        supports_cache = ("tensor_cache" in inspect.signature(score).parameters or
                          any(p.kind is p.VAR_KEYWORD for p in params))
    except (TypeError, ValueError):
        supports_cache = True
    values = (score(leaves, seat, tensor_cache=tensor_cache)
              if supports_cache else score(leaves, seat))
    values = np.asarray(values, dtype=np.float64)
    if values.shape != (len(leaves),) or not np.isfinite(values).all():
        raise ValueError("evaluator must return one finite value per afterstate")
    return values


def score_horizon_matrix(rnd, seat: int, actions: Sequence[Sequence[str]],
                         worlds: Sequence[Any], evaluators: Mapping[str, object], *,
                         finish_trick: bool, batch_size: int = 128
                         ) -> dict[str, np.ndarray]:
    """Return ``{evaluator: (world, action) signed-level matrix}``.

    Leaves are emitted WORLD-MAJOR, exactly as ``CWVShortlistBot._means``.
    Every evaluator sees the same leaf objects in each bounded batch, while
    each evaluator owns an independent bounded tensor cache.
    """
    if isinstance(seat, bool) or not isinstance(seat, int) or not 0 <= seat < 4:
        raise ValueError("seat must be an integer in [0, 3]")
    if type(finish_trick) is not bool:
        raise ValueError("finish_trick must be boolean")
    batch_size = _positive_int(batch_size, "batch_size")
    acts = _actions(actions)
    canonical = _canonical_worlds(rnd, seat, worlds)
    if not isinstance(evaluators, Mapping) or not evaluators:
        raise ValueError("evaluators must be a non-empty mapping")
    if any(not isinstance(name, str) or not name for name in evaluators):
        raise ValueError("evaluator names must be non-empty strings")
    names = list(evaluators)
    matrices = {name: np.empty((len(canonical), len(acts)), dtype=np.float64)
                for name in names}
    caches = {name: TensorInputCache(max_entries=batch_size) for name in names}
    pending: list[Any] = []
    pending_indices: list[tuple[int, int]] = []

    def flush() -> None:
        if not pending:
            return
        for name in names:
            values = _score_support(evaluators[name], pending, seat, caches[name])
            for value, (world_index, action_index) in zip(values, pending_indices):
                matrices[name][world_index, action_index] = value
        pending.clear()
        pending_indices.clear()

    for world_index, (hands, buried) in enumerate(canonical):
        successor = (WorldSuccessorCache(rnd, seat, hands, buried)
                     if finish_trick else None)
        for action_index, action in enumerate(acts):
            leaf = (successor.leaf(action) if successor is not None else
                    afterstate(rnd, seat, hands, buried, action,
                               finish_trick=False))
            pending.append(leaf)
            pending_indices.append((world_index, action_index))
            if len(pending) == batch_size:
                flush()
    flush()
    return matrices


def topk_with_incumbent(actions: Sequence[Sequence[str]], means: Any,
                        incumbent: Sequence[str], alternatives: int = 4) -> list[int]:
    """Return incumbent first, then the best sorted-card-tuple alternatives."""
    acts = _actions(actions)
    alternatives = _positive_int(alternatives, "alternatives", zero=True)
    values = np.asarray(means, dtype=np.float64)
    if values.ndim == 2:
        if values.shape[1] != len(acts) or values.shape[0] < 1:
            raise ValueError("means must have one column per action")
        values = values.mean(axis=0)
    if values.shape != (len(acts),) or not np.isfinite(values).all():
        raise ValueError("means must be one finite value per action")
    incumbent_key = tuple(sorted(list(incumbent)))
    keys = [tuple(sorted(action)) for action in acts]
    if incumbent_key not in keys:
        raise ValueError("incumbent must be one of actions")
    incumbent_index = keys.index(incumbent_key)
    ranked = sorted((index for index in range(len(acts)) if index != incumbent_index),
                    key=lambda index: (-float(values[index]), keys[index]))
    return [incumbent_index, *ranked[:alternatives]]


def reference_returns(rnd, seat: int, actions: Sequence[Sequence[str]],
                      worlds: Sequence[Any]) -> dict[str, np.ndarray]:
    """Run production's native heuristic continuation on each fixed world."""
    acts = _actions(actions)
    canonical = _canonical_worlds(rnd, seat, worlds)
    bot = REGISTRY["mc-s0-report-lcb"](seed=0)
    points = np.empty((len(canonical), len(acts)), dtype=np.float64)
    levels = np.empty_like(points)
    root_is_attacker = bool(rnd.is_attacker(seat))
    for world_index, (hands, buried) in enumerate(canonical):
        for action_index, action in enumerate(acts):
            sampled = {other: list(hands[other]) for other in range(4) if other != seat}
            value = bot._rollout(rnd, seat, sampled, list(buried), list(action))
            value_float = float(value)
            if not np.isfinite(value_float) or not value_float.is_integer():
                raise ValueError("production rollout must return an integral finite score")
            attacker_points = int(value_float)
            points[world_index, action_index] = value_float
            category = signed_level_category(attacker_points, root_is_attacker)
            levels[world_index, action_index] = category_signed_level(category)
    return {"points": points, "levels": levels}


def run_fixed_ballot(rnd, seat: int, ballot: Sequence[Sequence[str]], *,
                     seed: int | None = 0, selection_worlds: int = 30,
                     report_worlds: int = 300) -> dict[str, Any]:
    """Run the real S0 report-LCB selector with a caller-supplied ballot."""
    selection_worlds = _positive_int(selection_worlds, "selection_worlds")
    report_worlds = _positive_int(report_worlds, "report_worlds")
    acts = _actions(ballot)
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise ValueError("seed must be an integer or None")
    production = REGISTRY["mc-s0-report-lcb"]

    def fixed_candidates(self, _rnd, _seat):
        return [list(action) for action in self._fixed_ballot]

    fixed_type = type("CWVFixedBallotReportLCB", (production,), {
        "N_DETERMINIZATIONS": selection_worlds,
        "REPORT_FOLD_WORLDS": report_worlds,
        "TRACTOR_LOCK": False,
        "_candidates": fixed_candidates,
    })
    bot = fixed_type(seed)
    bot._fixed_ballot = tuple(tuple(action) for action in acts)
    played = bot.decide_play(rnd, seat)
    return {"played": played, "record": bot.last_decision_record}


__all__ = [
    "reference_returns",
    "run_fixed_ballot",
    "score_horizon_matrix",
    "topk_with_incumbent",
]

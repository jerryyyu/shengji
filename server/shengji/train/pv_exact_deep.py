"""Exact lead values for deeper endgames (OFF BY DEFAULT).

The served exact lead (`pv_exact_endgame.exact_lead_means`) scores lead
candidates with every hand at most four cards.  This module serves the
opt-in ``exact_deep_cards`` rule of `pv_search_policy` (module docstring):

* hands may hold up to ``max_hand_cards`` cards (at most eight, the compiled
  solver's slot capacity);
* with ``level=True`` each world runs a level-mode session
  (`endgame_compact.CompactWorldSession.solve_level`): the minimax value is
  resolved only up to the steps of the signed-level objective, which is all
  the means use, so the means equal those of a full minimax while the search
  visits far fewer nodes.

The contract is ``exact_lead_means``'s: already-determinized worlds only, one
session per world shared by its candidates, no partial matrix (any invalid
world, failed leaf, cancellation or node-cap refusal raises).

Completed-worlds mode (OFF unless ``min_worlds`` is given)
---------------------------------------------------------
With ``min_worlds=m`` and ``stop_at`` (a time on ``clock``), the pass stops
starting worlds once ``clock() >= stop_at`` and abandons a world still being
solved at that time; the means are taken over the worlds completed before it,
provided at least ``m`` completed (otherwise it raises, as a refused pass
does).  The worlds are the sampler's draws in their drawn order, so the
completed ones are a prefix of an i.i.d. sample -- an unbiased but noisier
estimate, except that the last world's inclusion depends on its own cost.
This is a different estimator from the all-worlds pass; callers name it
separately (``pv_search_policy``: ``exact_deep_min_worlds``).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence

import numpy as np

from ..ai.endgame import ExactEndgameRefusal
from ..ai.endgame_compact import CompactWorldSession
from ..engine.round import Round
from ..rl.value_afterstate import category_signed_level, signed_level_category
from .cwv_prior_admission import root_clone

#: the compiled solver's per-seat slot capacity
MAX_DEEP_CARDS = 8


def _refuse(message: str) -> None:
    raise ExactEndgameRefusal(message)


def _validate_world(rnd: Round, world, world_index: int, max_hand_cards: int):
    if type(world) not in (tuple, list) or len(world) != 2:
        _refuse(f"world {world_index} must be (hands, buried)")
    hands, buried = world
    if type(hands) is not list or len(hands) != 4:
        _refuse(f"world {world_index} must carry four hands")
    if type(buried) is not list:
        _refuse(f"world {world_index} buried cards must be a list")
    if len(buried) != len(rnd.buried):
        _refuse(f"world {world_index} buried-card count differs from root")
    copied = [list(hand) if type(hand) is list else _refuse(
        f"world {world_index} hand {seat} must be a list") for seat, hand in enumerate(hands)]
    if any(len(hand) > max_hand_cards for hand in copied):
        _refuse(f"exact endgame requires every world hand to hold at most {max_hand_cards} cards")
    if any(len(hand) != len(root_hand) for hand, root_hand in zip(copied, rnd.hands)):
        _refuse(f"world {world_index} hand sizes differ from public root")
    if Counter(copied[rnd.turn]) != Counter(rnd.hands[rnd.turn]):
        _refuse("world root hand differs from the live root hand")
    return copied, list(buried)


class WorldsTimeout(Exception):
    """A completed-worlds pass reached its ``stop_at`` inside a world."""


def world_guard(check_budget, stop_at, clock):
    """``check_budget`` plus the completed-worlds stop (module docstring)."""
    def guard():
        if clock() >= stop_at:
            raise WorldsTimeout()
        if check_budget is not None:
            check_budget()
    return guard


def check_min_worlds(min_worlds, stop_at, clock, total):
    if min_worlds is None:
        if stop_at is not None:
            _refuse("stop_at needs min_worlds")
        return
    if isinstance(min_worlds, bool) or type(min_worlds) is not int \
            or not 1 <= min_worlds <= total:
        _refuse("min_worlds must be an int in [1, number of worlds]")
    if stop_at is None or not callable(clock):
        _refuse("min_worlds needs stop_at and a clock")


def exact_root_means(
        rnd: Round, seat: int, actions: Sequence[Sequence[str]], worlds,
        leaf_fn: Callable, check_budget: Callable | None, *,
        max_hand_cards: int, max_nodes: int, level: bool = True,
        min_worlds: int | None = None, stop_at: float | None = None,
        clock: Callable | None = None) -> tuple[np.ndarray, dict]:
    """Exact root-team level means for every candidate over the worlds.

    ``leaf_fn(world_root, seat, hands, buried, action, world_index)`` returns
    the Round after the candidate and the rest of its trick (as
    ``exact_lead_means``).  ``max_nodes`` bounds each world's session.
    """
    if type(rnd) is not Round or rnd.phase != "play" or rnd.turn != seat:
        _refuse("exact values require an active root play decision")
    if rnd.trick is None or rnd.trick.plays:
        _refuse("exact lead values require a lead root")
    if isinstance(seat, bool) or type(seat) is not int or not 0 <= seat < 4:
        _refuse("seat must be an engine seat")
    if (isinstance(max_hand_cards, bool) or type(max_hand_cards) is not int
            or not 1 <= max_hand_cards <= MAX_DEEP_CARDS):
        _refuse(f"max_hand_cards must be an integer in [1, {MAX_DEEP_CARDS}]")
    if any(len(hand) > max_hand_cards for hand in rnd.hands):
        _refuse(f"exact endgame requires every live root hand to hold at most "
                f"{max_hand_cards} cards")
    if not callable(leaf_fn):
        _refuse("leaf_fn must be callable")
    if check_budget is not None and not callable(check_budget):
        _refuse("check_budget must be callable or None")
    if isinstance(max_nodes, bool) or type(max_nodes) is not int or max_nodes < 1:
        _refuse("max_nodes must be a positive integer")
    if type(actions) not in (list, tuple) or not actions:
        _refuse("actions must be a non-empty sequence")
    candidate_actions = []
    for index, action in enumerate(actions):
        if type(action) not in (list, tuple) or not action:
            _refuse(f"action {index} must be a non-empty sequence")
        candidate_actions.append(list(action))
    if type(worlds) not in (list, tuple) or not worlds:
        _refuse("worlds must be a non-empty sequence")
    validated = [_validate_world(rnd, world, index, max_hand_cards)
                 for index, world in enumerate(worlds)]
    check_min_worlds(min_worlds, stop_at, clock, len(validated))
    partial = min_worlds is not None
    guard = world_guard(check_budget, stop_at, clock) if partial else check_budget
    means = np.zeros(len(candidate_actions), dtype=np.float64)
    node_total = cache_total = completed = 0
    for world_index, (hands, buried) in enumerate(validated):
        if partial and clock() >= stop_at:
            break
        try:
            row, nodes, hits = _world_row(rnd, seat, candidate_actions, hands, buried,
                                          world_index, leaf_fn, guard, max_hand_cards,
                                          max_nodes, level)
        except WorldsTimeout:
            if not partial:
                raise
            break
        means += row
        completed += 1
        node_total += nodes
        cache_total += hits
    if completed < len(validated):
        if completed < (min_worlds or len(validated)):
            raise ExactEndgameRefusal(
                f"completed-worlds pass finished {completed} worlds; needs {min_worlds}")
    means /= completed
    return means, {"worlds_completed": completed, "nodes": node_total,
                   "cache_hits": cache_total}


def _world_row(rnd, seat, candidate_actions, hands, buried, world_index, leaf_fn,
               check_budget, max_hand_cards, max_nodes, level):
    """One world's candidate levels, its session's nodes and cache hits."""
    row = np.zeros(len(candidate_actions), dtype=np.float64)
    world_root = root_clone(rnd, hands, buried)
    session = CompactWorldSession(
        world_root, max_hand_cards=max_hand_cards, max_nodes=max_nodes,
        check_budget=check_budget, alpha_beta=True, level=level)
    for action_index, action in enumerate(candidate_actions):
        leaf = leaf_fn(world_root, seat, hands, buried, action, world_index)
        if type(leaf) is not Round:
            _refuse("leaf_fn must return a Round")
        if check_budget is not None:
            check_budget()
        if leaf.phase == 'round_end':
            points = leaf.attacker_points
        elif level:
            points = session.solve_level(leaf)
        else:
            points = session.solve(leaf).attacker_points
        row[action_index] = category_signed_level(
            signed_level_category(points, leaf.is_attacker(seat)))
    return row, session.nodes, session.cache_hits


__all__ = ["MAX_DEEP_CARDS", "WorldsTimeout", "check_min_worlds", "exact_root_means",
           "world_guard"]

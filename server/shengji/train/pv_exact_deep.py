"""Exact candidate values for deeper endgames and for follows (OFF BY DEFAULT).

The served exact lead (`pv_exact_endgame.exact_lead_means`) scores lead
candidates only, with every hand at most four cards.  This module is its
generalisation for two opt-in rules of `pv_search_policy` (module docstring:
``exact_deep_cards`` and ``exact_follows``):

* the root may be a lead OR a follow (an open trick the root seat joins);
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


def exact_root_means(
        rnd: Round, seat: int, actions: Sequence[Sequence[str]], worlds,
        leaf_fn: Callable, check_budget: Callable | None, *,
        max_hand_cards: int, max_nodes: int, level: bool = True) -> tuple[np.ndarray, dict]:
    """Exact root-team level means for every candidate over the worlds.

    ``leaf_fn(world_root, seat, hands, buried, action, world_index)`` returns
    the Round after the candidate and the rest of its trick (as
    ``exact_lead_means``).  ``max_nodes`` bounds each world's session.
    """
    if type(rnd) is not Round or rnd.phase != "play" or rnd.turn != seat:
        _refuse("exact values require an active root play decision")
    if rnd.trick is None:
        _refuse("exact values require an active trick")
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
    means = np.zeros(len(candidate_actions), dtype=np.float64)
    node_total = cache_total = completed = 0
    for world_index, (hands, buried) in enumerate(validated):
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
            means[action_index] += category_signed_level(
                signed_level_category(points, leaf.is_attacker(seat)))
        completed += 1
        node_total += session.nodes
        cache_total += session.cache_hits
    means /= len(validated)
    return means, {"worlds_completed": completed, "nodes": node_total,
                   "cache_hits": cache_total}


__all__ = ["MAX_DEEP_CARDS", "exact_root_means"]

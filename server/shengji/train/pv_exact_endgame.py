"""Model-free exact values for a bounded set of lead candidates.

This is an opt-in diagnostic seam.  It accepts only already-determinized
worlds; it never completes a missing hand from the live round and never calls
an evaluator.  One exact session is shared by all candidates in one world,
while the transposition table is deliberately not shared between worlds.  The
session is :class:`~shengji.ai.endgame_compact.CompactWorldSession`, the
compact-state twin of :class:`~shengji.ai.endgame.ExactWorldSession` (same
values, node and cache-hit counts; compiled when the engine is).
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


def _refuse(message: str) -> None:
    raise ExactEndgameRefusal(message)


def _validate_world(rnd: Round, world, world_index: int) -> tuple[list[list[str]], list[str]]:
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
    if any(len(hand) > 4 for hand in copied):
        _refuse("exact lead endgame requires every world hand to contain at most four cards")
    if any(len(hand) > 4 for hand in rnd.hands):
        _refuse("exact lead endgame requires every live root hand to contain at most four cards")
    if any(len(hand) != len(root_hand)
           for hand, root_hand in zip(copied, rnd.hands)):
        _refuse(f"world {world_index} hand sizes differ from public root")
    if Counter(copied[rnd.turn]) != Counter(rnd.hands[rnd.turn]):
        _refuse("world root hand differs from the live root hand")
    return copied, list(buried)


def exact_lead_means(
        rnd: Round, seat: int, actions: Sequence[Sequence[str]], worlds,
        leaf_fn: Callable, check_budget: Callable | None, *,
        max_nodes: int = 10_000) -> tuple[np.ndarray, dict]:
    """Return exact root-team level means for every candidate and world.

    ``leaf_fn`` is the existing candidate-to-leaf producer.  It receives the
    world-substituted root, seat, that world's hands and kitty, the submitted
    action, and its world index; it must return a Round reached through the
    real engine transition.  The function intentionally publishes no partial
    matrix: any invalid world, failed leaf, cancellation, or node-cap refusal
    raises before returning.
    """
    if type(rnd) is not Round or rnd.phase != "play" or rnd.turn != seat:
        _refuse("exact lead values require an active root play decision")
    if rnd.trick is None or rnd.trick.plays:
        _refuse("exact lead values require a lead root")
    if isinstance(seat, bool) or type(seat) is not int or not 0 <= seat < 4:
        _refuse("seat must be an engine seat")
    if not callable(leaf_fn):
        _refuse("leaf_fn must be callable")
    if check_budget is not None and not callable(check_budget):
        _refuse("check_budget must be callable or None")
    if isinstance(max_nodes, bool) or type(max_nodes) is not int or max_nodes < 1:
        _refuse("max_nodes must be a positive integer")
    if type(actions) not in (list, tuple) or not actions:
        _refuse("actions must be a non-empty sequence")
    candidate_actions: list[list[str]] = []
    for index, action in enumerate(actions):
        if type(action) not in (list, tuple) or not action:
            _refuse(f"action {index} must be a non-empty sequence")
        candidate_actions.append(list(action))
    if type(worlds) not in (list, tuple) or not worlds:
        _refuse("worlds must be a non-empty sequence")

    validated_worlds = [
        _validate_world(rnd, world, index)
        for index, world in enumerate(worlds)
    ]
    means = np.zeros(len(candidate_actions), dtype=np.float64)
    node_total = 0
    cache_total = 0
    completed = 0

    for world_index, (hands, buried) in enumerate(validated_worlds):
        world_root = root_clone(rnd, hands, buried)
        session = CompactWorldSession(
            world_root, max_hand_cards=4, max_nodes=max_nodes,
            check_budget=check_budget, alpha_beta=True)
        for action_index, action in enumerate(candidate_actions):
            leaf = leaf_fn(world_root, seat, hands, buried, action, world_index)
            if type(leaf) is not Round:
                _refuse("leaf_fn must return a Round")
            if check_budget is not None:
                check_budget()
            points = (leaf.attacker_points if leaf.phase == 'round_end'
                      else session.solve(leaf).attacker_points)
            means[action_index] += category_signed_level(
                signed_level_category(points,
                                      leaf.is_attacker(seat)))
        completed += 1
        node_total += session.nodes
        cache_total += session.cache_hits

    means /= len(validated_worlds)
    return means, {"worlds_completed": completed,
                   "nodes": node_total, "cache_hits": cache_total}


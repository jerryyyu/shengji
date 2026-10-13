"""Model-free exact values for bounded lead candidates."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence

import numpy as np

from ..ai.endgame import ExactEndgameRefusal, ExactWorldSession
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
    if type(buried) is not list or len(buried) != len(rnd.buried):
        _refuse(f"world {world_index} buried-card count differs from root")
    copied = [list(hand) if type(hand) is list else _refuse(
        f"world {world_index} hand {seat} must be a list")
              for seat, hand in enumerate(hands)]
    if any(len(hand) > 4 for hand in copied + rnd.hands):
        _refuse("exact lead endgame requires every hand to contain at most four cards")
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
    """Evaluate produced candidate leaves exactly, preserving old behavior."""
    if type(rnd) is not Round or rnd.phase != "play" or rnd.turn != seat:
        _refuse("exact lead values require an active root play decision")
    if rnd.trick is None or rnd.trick.plays:
        _refuse("exact lead values require a lead root")
    if not callable(leaf_fn):
        _refuse("leaf_fn must be callable")
    if isinstance(max_nodes, bool) or type(max_nodes) is not int or max_nodes < 1:
        _refuse("max_nodes must be a positive integer")
    if type(actions) not in (list, tuple) or not actions:
        _refuse("actions must be a non-empty sequence")
    candidate_actions = [list(action) for action in actions]
    if type(worlds) not in (list, tuple) or not worlds:
        _refuse("worlds must be a non-empty sequence")
    validated = [_validate_world(rnd, world, index)
                 for index, world in enumerate(worlds)]
    means = np.zeros(len(candidate_actions), dtype=np.float64)
    stats = {"worlds_completed": 0, "nodes": 0, "cache_hits": 0}
    for world_index, (hands, buried) in enumerate(validated):
        root = root_clone(rnd, hands, buried)
        session = ExactWorldSession(root, max_hand_cards=4,
                                    max_nodes=max_nodes,
                                    check_budget=check_budget)
        for action_index, action in enumerate(candidate_actions):
            if check_budget is not None:
                check_budget()
            leaf = leaf_fn(root, seat, hands, buried, action, world_index)
            if type(leaf) is not Round:
                _refuse("leaf_fn must return a Round")
            points = (leaf.attacker_points if leaf.phase == "round_end"
                      else session.solve(leaf).attacker_points)
            means[action_index] += category_signed_level(
                signed_level_category(points, leaf.is_attacker(seat)))
        stats["worlds_completed"] += 1
        stats["nodes"] += session.nodes
        stats["cache_hits"] += session.cache_hits
    return means / len(validated), stats


def exact_first_trick_means(rnd, seat, actions, worlds, check_budget=None, *,
                            max_nodes=10_000):
    """Evaluate fixed leads by engine application then exact continuation."""
    from ..ai.endgame import exact_first_trick_means as _means
    return _means(rnd, seat, actions, worlds, check_budget,
                  max_nodes=max_nodes)


"""Bounded DEV exact reranking for policy-value follow roots.

The stage is deliberately independent of the serving factory.  It consumes the
already sampled worlds and admitted ballot, applies each submitted follow
through the real engine, and solves the remaining game exactly.  A stage is
published only after every candidate in every world completed.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections import Counter

from ..ai.endgame import ExactEndgameRefusal, ExactWorldSession
from ..ai.endgame_compact import CompactWorldSession
from .pv_exact_deep import WorldsTimeout, check_min_worlds, world_guard
from ..rl.value_afterstate import category_signed_level, signed_level_category
from .cwv_prior_admission import root_clone


#: ``reference``: ``ExactWorldSession`` (full minimax); ``compact-level``: the
#: compiled level-mode ``CompactWorldSession`` (alpha-beta, values resolved to
#: the signed-level steps, which is all the scores use, so the scores are equal)
SOLVERS = ("reference", "compact-level")


class ExactFollowRefusal(RuntimeError):
    """The root or one of its worlds is outside the exact follow boundary."""


@dataclass(frozen=True)
class ExactFollowResult:
    winner: int
    scores: tuple[float, ...]
    worlds: int
    nodes: int


def rerank_follow(rnd, seat: int, admitted, worlds, *, baseline_index: int = 0,
                  max_hand_cards: int = 4, max_nodes: int = 250_000,
                  check_budget=None, solver: str = "reference",
                  min_worlds: int | None = None, stop_at: float | None = None,
                  clock=None) -> ExactFollowResult:
    """Return a complete exact reranking, or raise without a partial result.

    Scores are the value head's signed-level category utility from the acting
    seat's team's perspective; conversion is performed separately per world.

    ``min_worlds`` / ``stop_at`` / ``clock`` select the completed-worlds
    estimator of `pv_exact_deep` (its module docstring): the scores are means
    over the worlds completed before ``stop_at``, at least ``min_worlds``.
    Unset, every world must complete.
    """
    if getattr(rnd, "phase", None) != "play" or rnd.trick is None \
            or not rnd.trick.plays:
        raise ExactFollowRefusal("exact follow requires a follow root")
    if rnd.turn != seat:
        raise ExactFollowRefusal("exact follow root is not the acting seat")
    if not admitted or not worlds:
        raise ExactFollowRefusal("exact follow requires a non-empty ballot")
    if any(len(hand) > max_hand_cards for hand in rnd.hands):
        raise ExactFollowRefusal("a world exceeds the exact hand-card boundary")
    if solver not in SOLVERS:
        raise ExactFollowRefusal(f"unknown exact follow solver {solver!r}")
    if not 0 <= baseline_index < len(admitted):
        raise ExactFollowRefusal("baseline index is outside the ballot")
    try:
        check_min_worlds(min_worlds, stop_at, clock, len(worlds))
    except ExactEndgameRefusal as exc:
        raise ExactFollowRefusal(str(exc)) from exc
    partial = min_worlds is not None
    if partial:
        check_budget = world_guard(check_budget, stop_at, clock)
    scores = [0.0] * len(admitted)
    nodes = 0
    completed = 0
    root_attacker = bool(rnd.is_attacker(seat))
    for world in worlds:
        if partial and clock() >= stop_at:
            break
        try:
            row, solved = _world_scores(rnd, seat, admitted, world, max_hand_cards,
                                        max_nodes, check_budget, solver, root_attacker)
        except WorldsTimeout:
            if not partial:
                raise
            break
        for index, value in enumerate(row):
            scores[index] += value
        nodes += solved
        completed += 1
    if completed < len(worlds) and completed < (min_worlds or len(worlds)):
        raise ExactFollowRefusal(
            f"completed-worlds pass finished {completed} worlds; needs {min_worlds}")
    means = tuple(score / completed for score in scores)
    baseline = means[baseline_index]
    winner = max(range(len(means)), key=lambda i: (means[i], -i))
    if means[winner] <= baseline:
        winner = baseline_index
    return ExactFollowResult(winner=winner, scores=means, worlds=completed, nodes=nodes)


def _world_scores(rnd, seat, admitted, world, max_hand_cards, max_nodes, check_budget,
                  solver, root_attacker):
    """One world's signed-level scores per candidate and its solver nodes."""
    scores = [0.0] * len(admitted)
    nodes = 0
    if check_budget is not None:
        check_budget()
    hands, buried = world
    if len(hands) != 4 or len(buried) != len(rnd.buried) \
            or [len(hand) for hand in hands] != [len(hand) for hand in rnd.hands]:
        raise ExactFollowRefusal("sampled world changes public hand or kitty sizes")
    if Counter(hands[seat]) != Counter(rnd.hands[seat]):
        raise ExactFollowRefusal("sampled world changes the acting hand")
    if any(len(hand) > max_hand_cards for hand in hands):
        raise ExactFollowRefusal("a sampled world exceeds the exact hand-card boundary")
    world_root = root_clone(rnd, hands, buried)
    if solver == "reference":
        session = ExactWorldSession(world_root, max_hand_cards=max_hand_cards,
                                    max_nodes=max_nodes, check_budget=check_budget)
    else:
        session = CompactWorldSession(world_root, max_hand_cards=max_hand_cards,
                                      max_nodes=max_nodes, check_budget=check_budget,
                                      alpha_beta=True, level=True)
    keys = {}
    for index, action in enumerate(admitted):
        if check_budget is not None:
            check_budget()
        if solver != "reference":
            # interchangeable plays have equal values (`CompactWorldSession.play_key`)
            key = session.play_key(world_root, action)
            if key is not None and key in keys:
                scores[index] = scores[keys[key]]
                continue
            if key is not None:
                keys[key] = index
        child = root_clone(rnd, hands, buried)
        try:
            child.play(seat, list(action))
            if child.phase == "round_end":
                points = child.attacker_points
                signed = category_signed_level(
                    signed_level_category(points, root_attacker))
                scores[index] += float(signed)
                continue
            if solver == "reference":
                result = session.solve(child)
                points, solved = result.attacker_points, result.nodes
            else:
                before = session.nodes
                points = session.solve_level(child)
                solved = session.nodes - before
        except ExactEndgameRefusal as exc:
            raise ExactFollowRefusal(str(exc)) from exc
        # Convert the terminal attacker score into the value head's closed
        # category support; points are not linear signed-level utility.
        signed = category_signed_level(
            signed_level_category(points, root_attacker))
        scores[index] += float(signed)
        nodes += solved
    if check_budget is not None:
        check_budget()
    return scores, nodes

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
    # Per-world level scores are retained only for the optional points tie-break.
    # They make the secondary pass auditable: a points solve may not silently
    # change the primary level ordering.
    world_scores: tuple[tuple[float, ...], ...] | None = None


@dataclass(frozen=True)
class PointsTieBreakResult:
    winner: int
    point_scores: tuple[float | None, ...]
    nodes: int


def rerank_follow(rnd, seat: int, admitted, worlds, *, baseline_index: int = 0,
                  max_hand_cards: int = 4, max_nodes: int = 250_000,
                  check_budget=None, solver: str = "reference",
                  retain_world_scores: bool = False) -> ExactFollowResult:
    """Return a complete exact reranking, or raise without a partial result.

    Scores are the value head's signed-level category utility from the acting
    seat's team's perspective; conversion is performed separately per world.
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
    scores = [0.0] * len(admitted)
    nodes = 0
    root_attacker = bool(rnd.is_attacker(seat))
    world_rows = []
    for world in worlds:
        row, solved = _world_scores(
            rnd, seat, admitted, world, max_hand_cards, max_nodes,
            check_budget, solver, root_attacker)
        for index, value in enumerate(row):
            scores[index] += value
        if retain_world_scores:
            world_rows.append(tuple(row))
        nodes += solved
    means = tuple(score / len(worlds) for score in scores)
    baseline = means[baseline_index]
    winner = max(range(len(means)), key=lambda i: (means[i], -i))
    if means[winner] <= baseline:
        winner = baseline_index
    return ExactFollowResult(winner=winner, scores=means, worlds=len(worlds), nodes=nodes,
                             world_scores=(tuple(world_rows) if retain_world_scores else None))


def rerank_follow_points(primary: ExactFollowResult, rnd, seat: int, admitted,
                         worlds, *, baseline_index: int = 0, max_hand_cards: int = 4,
                         max_nodes: int = 250_000, check_budget=None,
                         solver: str = "reference") -> PointsTieBreakResult:
    """Tie-break only maximal primary level candidates by exact points.

    This is a separate, optional stage.  It never returns a partial ranking:
    any refusal or deadline is raised to the caller, which keeps ``primary``
    as the selected result.  Every secondary points value is checked against
    the retained per-world level value before it can influence selection.
    """
    if primary.world_scores is None or len(primary.world_scores) != len(worlds):
        raise ExactFollowRefusal("primary per-world level scores are unavailable")
    best = max(primary.scores)
    tied = [i for i, value in enumerate(primary.scores)
            if value == best]
    if len(tied) < 2:
        return PointsTieBreakResult(winner=primary.winner,
                                    point_scores=(None,) * len(admitted), nodes=0)
    if not 0 <= baseline_index < len(admitted):
        raise ExactFollowRefusal("baseline index is outside the ballot")
    root_attacker = bool(rnd.is_attacker(seat))
    point_sums = {i: 0.0 for i in tied}
    nodes = 0
    for wi, world in enumerate(worlds):
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
        elif solver == "compact-level":
            session = CompactWorldSession(world_root, max_hand_cards=max_hand_cards,
                                          max_nodes=max_nodes, check_budget=check_budget,
                                          alpha_beta=True, level=True)
        else:
            raise ExactFollowRefusal(f"unknown exact follow solver {solver!r}")
        for index in tied:
            if check_budget is not None:
                check_budget()
            child = root_clone(rnd, hands, buried)
            child._trusted_rollout = False
            try:
                child.play(seat, list(admitted[index]))
                if child.phase == "round_end":
                    points = child.attacker_points
                    solved = 0
                elif solver == "reference":
                    result = session.solve(child)
                    points, solved = result.attacker_points, result.nodes
                else:
                    before = session.nodes
                    points = session.solve_points(child)
                    solved = session.nodes - before
            except ExactEndgameRefusal as exc:
                raise ExactFollowRefusal(str(exc)) from exc
            level = float(category_signed_level(
                signed_level_category(points, root_attacker)))
            expected = primary.world_scores[wi][index]
            if level != expected:
                raise ExactFollowRefusal("points solve disagrees with primary level score")
            point_sums[index] += float(points)
            nodes += solved
    if check_budget is not None:
        check_budget()
    means = [None] * len(admitted)
    n = len(worlds)
    for index in tied:
        means[index] = point_sums[index] / n
    sign = 1 if root_attacker else -1
    top = max(sign * point_sums[index] for index in tied)
    candidates = [index for index in tied if sign * point_sums[index] == top]
    winner = baseline_index if baseline_index in candidates else min(candidates)
    return PointsTieBreakResult(winner=winner, point_scores=tuple(means), nodes=nodes)


def _world_scores(rnd, seat, admitted, world, max_hand_cards, max_nodes,
                  check_budget, solver, root_attacker):
    """Score every admitted play in one world, reusing equivalent children."""
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
        # Validate every submitted action through the real engine before key
        # reuse, so a malformed action cannot inherit a valid candidate's score.
        child = root_clone(rnd, hands, buried)
        child._trusted_rollout = False
        try:
            child.play(seat, list(action))
            if child.phase == "round_end":
                points = child.attacker_points
                signed = category_signed_level(
                    signed_level_category(points, root_attacker))
                scores[index] = float(signed)
                continue
            if solver != "reference":
                key = session.play_key(world_root, action)
                if key is not None and key in keys:
                    scores[index] = scores[keys[key]]
                    continue
                if key is not None:
                    keys[key] = index
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
        scores[index] = float(signed)
        nodes += solved
    if check_budget is not None:
        check_budget()
    return scores, nodes

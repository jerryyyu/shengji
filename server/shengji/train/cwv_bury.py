"""Bounded, development-only value scoring for banker bury candidates.

This module deliberately stops at producing aligned candidate values.  It does
not sample worlds, choose a bury, or register a policy.  World sampling stays
with :mod:`shengji.ai.cwv_policy`, which is also the source of the complete
world evaluator used here.
"""

from __future__ import annotations

import copy
from collections import Counter
from typing import Any, Sequence

import numpy as np

from ..ai.bury import DEFAULT_MAX_CANDIDATES, structured_bury_ballot
from ..ai.cwv_policy import sample_worlds  # re-export the canonical source
from ..ai.mcbot import MCBot
from ..engine.round import Round
from ..rl.value_afterstate import category_signed_level, signed_level_category


class BuryValueError(ValueError):
    """The bounded bury-value contract was supplied an invalid input."""


def _require_bury_round(rnd: Round) -> int:
    """Validate the one live state this development surface accepts."""
    if type(rnd) is not Round:
        raise BuryValueError("rnd must be an exact Round")
    if rnd.phase != "bury":
        raise BuryValueError("rnd must be in bury phase")
    if rnd.banker is None or rnd.turn != rnd.banker:
        raise BuryValueError("rnd must have the banker to act in bury phase")
    if rnd.ordering is None:
        raise BuryValueError("bury round is missing ordering")
    return int(rnd.banker)


def bury_candidates(rnd: Round, bot: Any) -> list[list[str]]:
    """Return the bounded structured ballot, with the literal incumbent first.

    Candidate sourcing is intentionally independent of MC bury search.  A bot
    with ``MC_BURY`` enabled is refused so calling this helper cannot recurse
    into sampling or accidentally use production's bury chooser.
    """
    banker = _require_bury_round(rnd)
    if getattr(bot, "MC_BURY", False):
        raise BuryValueError("bury_candidates requires bot.MC_BURY == False")

    incumbent = list(bot.decide_bury(rnd, banker))
    cap = getattr(bot, "BURY_MAX_CANDIDATES", DEFAULT_MAX_CANDIDATES)
    ballot = structured_bury_ballot(
        rnd.hands[banker], rnd.ordering, incumbent, max_candidates=int(cap))

    # structured_bury_ballot canonicalises candidate keys for deduplication.
    # The control action is nevertheless the exact list returned by the bot;
    # preserving that literal is part of the DEV comparison contract.
    candidates = [list(candidate.cards) for candidate in ballot.candidates]
    if not candidates:
        raise BuryValueError("structured bury ballot returned no candidates")
    candidates[0] = list(incumbent)
    return candidates


def _validated_world_hands(rnd: Round, hands: Sequence[Sequence[str]], banker: int
                           ) -> list[list[str]]:
    """Validate and canonicalise one complete pre-bury hand assignment."""
    try:
        if len(hands) != 4:
            raise BuryValueError("world must contain four hands")
        supplied_banker = hands[banker]
        if Counter(supplied_banker) != Counter(rnd.hands[banker]):
            raise BuryValueError("world banker hand differs from the real banker hand")
        sampled = {seat: hands[seat] for seat in range(4) if seat != banker}
    except (IndexError, TypeError) as exc:
        raise BuryValueError("world hands must be four card sequences") from exc

    # _complete_determinized_hands is the production conservation and hidden
    # information boundary.  It returns fresh, sorted hand lists.
    validator = object.__new__(MCBot)
    try:
        return MCBot._complete_determinized_hands(
            validator, rnd, banker, sampled, buried=[])
    except Exception as exc:
        # Preserve the useful public error type while retaining the production
        # validator's message (including card-conservation diagnostics).
        if isinstance(exc, BuryValueError):
            raise
        raise BuryValueError(f"invalid complete bury world: {exc}") from exc


def post_bury_world(rnd: Round, hands: Sequence[Sequence[str]],
                    candidate: Sequence[str]) -> Round:
    """Apply one candidate to a validated, complete pre-bury world.

    The caller's round, hand lists, candidate and world remain untouched.  The
    returned clone is an actual engine post-bury state, suitable for the same
    afterstate encoder used by the complete-world evaluator.
    """
    banker = _require_bury_round(rnd)
    canonical_hands = _validated_world_hands(rnd, hands, banker)
    return _post_bury_validated(rnd, banker, canonical_hands, candidate)


def _post_bury_validated(rnd, banker, canonical_hands, candidate):
    """Private batch helper; callers first validate this world's full population.

    Copy every hand before the engine removes cards, including the banker hand.
    Neither an earlier candidate nor an evaluator can mutate the template.
    """
    clone: Round = copy.copy(rnd)
    clone.hands = [list(hand) for hand in canonical_hands]
    clone.buried = []
    clone.trick = None
    clone.last_trick = None
    clone.history = []
    clone.message = None
    clone.bury(banker, list(candidate))
    clone._determinized_world = True
    return clone


def _world_parts(world: Any) -> tuple[Sequence[Sequence[str]], Sequence[str]]:
    try:
        hands, buried = world
    except (TypeError, ValueError) as exc:
        raise BuryValueError("worlds must contain (hands, buried) tuples") from exc
    if buried is None or len(buried) != 0:
        raise BuryValueError("bury-value worlds must have an empty buried kitty")
    return hands, buried


def _checked_batch_size(evaluator: Any) -> int:
    try:
        batch = int(evaluator.max_batch)
    except (AttributeError, TypeError, ValueError) as exc:
        raise BuryValueError("evaluator.max_batch must be a positive integer") from exc
    if batch < 1:
        raise BuryValueError("evaluator.max_batch must be a positive integer")
    return batch


def score_bury_candidates(rnd: Round, candidates: Sequence[Sequence[str]],
                          worlds: Sequence[Any], evaluator: Any, *,
                          first_trick_policy=None, check_budget=None) -> np.ndarray:
    """Score every world/candidate post-bury position in bounded chunks.

    Rows are WORLD-MAJOR: ``values[w, c]`` is world ``w`` with candidate
    ``c``.  Only one evaluator batch, bounded by ``evaluator.max_batch``, is
    resident at a time.
    """
    banker = _require_bury_round(rnd)
    candidates = tuple(tuple(candidate) for candidate in candidates)
    worlds = tuple(_world_parts(world) for world in worlds)
    if not candidates or not worlds:
        raise BuryValueError("bury scoring needs at least one candidate and world")
    max_batch = _checked_batch_size(evaluator)
    values = np.empty((len(worlds), len(candidates)), dtype=np.float64)
    positions: list[Round] = []
    slots: list[tuple[int, int]] = []

    def flush() -> None:
        if not positions:
            return
        if check_budget is not None:
            check_budget()
        # Pass a stable batch object: clearing our work buffer after the call
        # must not retroactively empty a recorder's reference to the batch.
        scored = np.asarray(evaluator.score(list(positions), banker), dtype=np.float64)
        if check_budget is not None:
            check_budget()
        if scored.shape != (len(positions),):
            raise BuryValueError(
                f"evaluator returned {scored.shape}, expected ({len(positions)},)")
        for (world_index, candidate_index), value in zip(slots, scored):
            values[world_index, candidate_index] = value
        positions.clear()
        slots.clear()

    for world_index, world in enumerate(worlds):
        hands, _buried = world
        if check_budget is not None:
            check_budget()
        canonical = tuple(tuple(hand) for hand in
                          _validated_world_hands(rnd, hands, banker))
        for candidate_index, candidate in enumerate(candidates):
            if check_budget is not None:
                check_budget()
            position = _post_bury_validated(rnd, banker, canonical, candidate)
            if first_trick_policy is not None:
                # The frozen afterstate encoder requires at least one play.
                # Complete exactly the first trick with the existing rollout
                # policy; do not insert synthetic history or alter the encoder.
                for _ in range(4):
                    seat = position.turn
                    position.play(seat, first_trick_policy.decide_play(position, seat))
            positions.append(position)
            slots.append((world_index, candidate_index))
            if len(positions) == max_batch:
                flush()
    flush()
    return values


def rollout_bury_values(rnd: Round, candidates: Sequence[Sequence[str]],
                        worlds: Sequence[Any], bot: Any, *, check_budget=None
                        ) -> tuple[np.ndarray, np.ndarray]:
    """Roll every world/candidate pair and return model units plus raw points.

    Rollout points are attacker points.  The returned value matrix is mapped
    to the banker/defender team's signed-level support so it can be compared
    directly with complete-world model predictions.
    """
    banker = _require_bury_round(rnd)
    candidates = tuple(tuple(candidate) for candidate in candidates)
    worlds = tuple(_world_parts(world) for world in worlds)
    if not candidates or not worlds:
        raise BuryValueError("bury rollouts need at least one candidate and world")
    values = np.empty((len(worlds), len(candidates)), dtype=np.float64)
    points = np.empty((len(worlds), len(candidates)), dtype=np.int64)
    for world_index, world in enumerate(worlds):
        hands, _buried = world
        # Validate once per world; the rollout itself repeats the native
        # validation and receives only opponent hands, exactly as production.
        _validated_world_hands(rnd, hands, banker)
        sampled = {seat: list(hands[seat]) for seat in range(4) if seat != banker}
        for candidate_index, candidate in enumerate(candidates):
            if check_budget is not None:
                check_budget()
            raw = float(bot._rollout_from_bury(rnd, banker, sampled, list(candidate)))
            if check_budget is not None:
                check_budget()
            if not np.isfinite(raw) or not raw.is_integer():
                raise BuryValueError("bury rollout must return integral attacker points")
            attacker_points = int(raw)
            points[world_index, candidate_index] = attacker_points
            values[world_index, candidate_index] = category_signed_level(
                signed_level_category(attacker_points, False))
    return values, points


__all__ = [
    "BuryValueError", "bury_candidates", "post_bury_world",
    "score_bury_candidates", "rollout_bury_values", "sample_worlds",
]

"""Offline replies scored on paired belief worlds conditioned on the acting seat."""
from collections import Counter
from collections.abc import Callable, Sequence

import numpy as np

from ..ai.belief_numpy import BeliefNumpy, BeliefProposal
from ..ai.cwv_policy import afterstate
from ..ai.history_legality import (HISTORY_ATTEMPT_FACTOR, draw_constraints,
                                   first_throw_violation, first_violation,
                                   follow_events, throw_events)
from ..ai.mcbot import MCBot
from ..ai.refusal import Refusal, observe_refusal, on_record, refusal_consistent
from ..engine.legal import validate_follow
from ..engine.round import Round, actual_play_after
from .pv_tree_search import value_batches


def draw_depth_worlds(
    child: Round,
    *,
    belief: BeliefNumpy,
    refusals: Sequence[Refusal],
    seed: int,
    worlds: int,
) -> list[tuple[list[list[str]], list[str]]]:
    """Draw strictly history-legal worlds from the next actor's information.

    The caller supplies the public refusal ledger and a seed paired across
    branches. Each returned hand and kitty is available to every candidate.
    """
    seat = child.turn
    if child.phase != "play" or seat is None or child.trick is None:
        raise ValueError("depth redraw requires a live play child")
    if worlds < 1 or seed < 0:
        raise ValueError("positive world count and nonnegative seed required")
    ledger = tuple(refusals)
    notice = observe_refusal(child)
    if (len(set(ledger)) != len(ledger)
            or any(r.trick_index < 0 or not on_record(child, r) for r in ledger)
            or (notice is not None and notice not in ledger)):
        raise ValueError("depth refusal ledger disagrees with the public record")
    follows = follow_events(child, seat)
    throws = throw_events(child)
    proposal = BeliefProposal(belief, child, seat, ledger, seed=seed, batch=worlds,
                              forbidden=draw_constraints(child, seat, follows))
    sampler = MCBot(seed=seed)
    accepted = []
    for _ in range(worlds * HISTORY_ATTEMPT_FACTOR):
        hidden, buried = proposal(child, seat, None)
        hands = sampler._complete_determinized_hands(child, seat, hidden, buried=buried)
        if (first_violation(follows, hands, child.ordering) is not None
                or first_throw_violation(throws, hands, child.ordering) is not None
                or not all(refusal_consistent(child, hands, r) for r in ledger)):
            continue
        accepted.append((hands, buried))
        if len(accepted) == worlds:
            break
    if len(accepted) != worlds:
        raise ValueError(f"depth draw supplied {len(accepted)} of {worlds} history-legal worlds")

    return accepted


def paired_reply_values(
    child: Round,
    replies: Sequence[Sequence[str]],
    sampled_worlds: Sequence[tuple[Sequence[Sequence[str]], Sequence[str]]],
    *,
    batch_size: int,
    score: Callable[[Sequence[Round], int], np.ndarray],
    value_seat: int | None = None,
) -> np.ndarray:
    """Score every reply in every supplied world, defaulting to the actor's team."""
    seat = child.turn
    if child.phase != "play" or seat is None or child.trick is None:
        raise ValueError("depth reply values require a live play child")
    if value_seat is None:
        value_seat = seat
    if value_seat not in range(4):
        raise ValueError("depth value perspective must name a seat")
    actions = [list(reply) for reply in replies]
    if not actions or any(not action for action in actions) or not sampled_worlds or batch_size < 1:
        raise ValueError("nonempty replies and worlds, and positive batch size required")
    if len({tuple(sorted(action)) for action in actions}) != len(actions):
        raise ValueError("duplicate depth replies")
    if child.trick.plays:
        lead = child.trick.plays[0].cards
        for action in actions:
            # The fast afterstate path trusts a follower's play.
            validate_follow(action, child.hands[seat], lead, child.ordering)

    actor_hand = Counter(child.hands[seat])
    kitty = Counter(child.buried) if seat == child.banker else None
    sizes = [len(hand) for hand in child.hands]
    leaves = []
    for hands, buried in sampled_worlds:
        if [len(hand) for hand in hands] != sizes or len(buried) != len(child.buried):
            raise ValueError("incomplete depth world")
        if Counter(hands[seat]) != actor_hand or (kitty is not None and Counter(buried) != kitty):
            raise ValueError("depth world changed information known to the actor")
        for action in actions:
            leaf = afterstate(child, seat, hands, buried, action)
            if Counter(actual_play_after(leaf, seat, child.last_trick)) != Counter(action):
                raise ValueError("engine substituted a depth reply")
            leaves.append(leaf)
    values, _ = value_batches(leaves, value_seat, batch_size, None, score)
    return values.reshape(len(sampled_worlds), len(actions))

"""Research-only effective-action diversity diagnostics for CWV shortlists.

An action's effective identity is the vector of engine-accepted cards over the
ordered sampled worlds.  This is an empirical W-world ablation, not an
all-world equivalence optimization and is intentionally not registered as a
policy.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..ai.cwv_policy import afterstate
from ..engine.legal import PreparedLeadValidation
from ..engine.round import actual_play_after
from .cwv_horizon_audit import _actions, _canonical_worlds, topk_with_incumbent


def _signature_key(signature: object) -> tuple[tuple[str, ...], ...]:
    if isinstance(signature, (str, bytes)) or not isinstance(signature, Sequence):
        raise ValueError("signatures must contain one accepted-action vector per world")
    worlds = []
    for accepted in signature:
        if isinstance(accepted, (str, bytes)) or not isinstance(accepted, Sequence):
            raise ValueError("each accepted action must be a card sequence")
        cards = list(accepted)
        if not cards or any(not isinstance(card, str) for card in cards):
            raise ValueError("each accepted action must be a non-empty card sequence")
        worlds.append(tuple(sorted(cards)))
    if not worlds:
        raise ValueError("each action signature must contain at least one world")
    return tuple(worlds)


def accepted_action_signatures(rnd, seat: int, actions: Sequence[Sequence[str]],
                              worlds: Sequence[Any]):
    """Return each action's ordered vector of engine-accepted card tuples."""
    acts = _actions(actions)
    canonical = _canonical_worlds(rnd, seat, worlds)
    signatures = [[] for _ in acts]
    for hands, buried in canonical:
        prepared = None
        if (rnd.trick is not None and not rnd.trick.plays and
                rnd.ordering is not None):
            prepared = PreparedLeadValidation(
                hands[seat], [hands[s] for s in range(4) if s != seat],
                rnd.ordering)
        for index, action in enumerate(acts):
            leaf = afterstate(
                rnd, seat, hands, buried, action, finish_trick=False,
                _lead_validation=prepared)
            accepted = tuple(sorted(actual_play_after(
                leaf, seat, rnd.last_trick)))
            if not accepted:
                raise ValueError("engine returned no accepted cards for an action")
            signatures[index].append(accepted)
    # Immutable vectors make accidental cross-root mutation impossible while
    # retaining repeated worlds and their exact input order.
    return tuple(tuple(per_world) for per_world in signatures)


def diverse_topk_with_incumbent(actions: Sequence[Sequence[str]], means: Any,
                                incumbent: Sequence[str], signatures: Sequence[Any],
                                alternatives: int = 4) -> list[int]:
    """Select baseline-ranked actions, preferring distinct empirical signatures.

    Distinct classes are discovered in baseline score order, then duplicate
    classes backfill only when the requested cardinality cannot be met.  The
    returned non-incumbents are finally restored to baseline ranking order.
    """
    acts = _actions(actions)
    if isinstance(signatures, (str, bytes)) or not isinstance(signatures, Sequence):
        raise ValueError("signatures must contain one entry per action")
    if len(signatures) != len(acts):
        raise ValueError("signatures must contain one entry per action")
    signature_keys = [_signature_key(signature) for signature in signatures]
    world_counts = {len(signature) for signature in signature_keys}
    if len(world_counts) != 1:
        raise ValueError("signatures must share one sampled-world population")
    # The ordinary selector is the cardinality and tie-order authority.  A
    # full ranking lets diversity discover a distinct class below the cutoff.
    baseline = topk_with_incumbent(acts, means, incumbent, alternatives)
    full_rank = topk_with_incumbent(acts, means, incumbent,
                                    len(acts) - 1)
    target = len(baseline)
    incumbent_index = baseline[0]
    chosen = [incumbent_index]
    classes = {signature_keys[incumbent_index]}
    for index in full_rank[1:]:
        if len(chosen) >= target:
            break
        if signature_keys[index] not in classes:
            chosen.append(index)
            classes.add(signature_keys[index])
    if len(chosen) < target:
        for index in full_rank[1:]:
            if len(chosen) >= target:
                break
            if index not in chosen:
                chosen.append(index)
    rank_position = {index: position for position, index in enumerate(full_rank)}
    chosen_nonincumbents = sorted(chosen[1:], key=rank_position.__getitem__)
    return [incumbent_index, *chosen_nonincumbents]


__all__ = ["accepted_action_signatures", "diverse_topk_with_incumbent"]

"""Offline within-cell ballot repair prototype (S11a).

This helper consumes a caller-supplied legal action pool, a strict total policy
ordering, and the baseline ballot that was supplied by the caller.  It does
not run a model, sample worlds, inspect values, or establish serving
provenance.  The intended baseline is the externally supplied r38 served
ballot; this synthetic API cannot prove that provenance.

An action's cell is ``(structure_key, held_pair_remainder_signature)``.  If a
cell has at least two baseline representatives and at least one excluded
action, the worst-ranked non-anchor baseline representative in that cell is
replaced by the best-ranked excluded representative in the same cell.  At
most one replacement is made, and it must improve policy rank. Rank-worsening
exploration belongs to S11b. If the selected slot cannot improve, return a
no-op without trying another slot.
"""

from __future__ import annotations

from collections import Counter

from ..train.policy_value_search import structure_key
from .ballot_matrix import _canonical_action
from .pair_resource_admission import _pair_inputs


def _validate_pool(actions, ranked, baseline):
    """Validate index vectors and return canonical action identities.

    Canonical identities are card multisets, so both action ordering and pool
    ordering are irrelevant to duplicate detection.  The original action
    objects remain untouched and are passed to ``_pair_inputs`` below.
    """
    if type(actions) is not list or not actions:
        raise ValueError("actions must be a nonempty list")
    if type(ranked) is not list or len(ranked) != len(actions):
        raise ValueError("ranked must be a complete permutation")
    if (any(type(index) is not int for index in ranked)
            or sorted(ranked) != list(range(len(actions)))):
        raise ValueError("ranked must be a strict total index permutation")
    if type(baseline) is not list or not baseline:
        raise ValueError("baseline must be a nonempty index list")
    if (any(type(index) is not int for index in baseline)
            or len(set(baseline)) != len(baseline)
            or any(not 0 <= index < len(actions) for index in baseline)):
        raise ValueError("baseline must be a unique legal index subset")

    canonical = []
    for position, action in enumerate(actions):
        try:
            identity = _canonical_action(action, f"actions[{position}]")
        except (TypeError, KeyError) as exc:
            raise ValueError("actions must contain legal card lists") from exc
        canonical.append(identity)
    if len(set(canonical)) != len(canonical):
        raise ValueError("actions contains duplicate card multisets")
    return canonical


def _audit_entry(index, canonical, rank, cell):
    """Build a detached, provenance-neutral action audit entry."""
    return {
        "index": index,
        "action": canonical[index],
        "policy_rank": rank[index] + 1,
        "cell": cell,
    }


def within_cell_rank_repair(rnd, seat, actions, ranked, baseline):
    """Apply one deterministic S11a same-cell replacement.

    ``ranked`` is a caller-owned strict total permutation of action indices;
    its position is the policy rank.  ``baseline[0]`` is the anchor and is
    never removed.  The returned ``chosen`` ballot has the same size, anchor,
    and exact cell multiplicities as ``baseline``.  ``audit`` is ``None`` for
    a no-op, otherwise it records the removed and added action identities,
    their one-based policy ranks, and their common cell.

    Inputs are read-only; no serving or collection integration is performed.
    """
    canonical = _validate_pool(actions, ranked, baseline)

    # _pair_inputs owns the actor-hand subset and exact pair-remainder checks.
    # Calling it here keeps this prototype aligned with the pair-resource
    # admission's input contract; the caller remains responsible for the
    # legal-play semantics of its supplied pool.
    _, signatures = _pair_inputs(
        rnd, seat, actions, ranked, baseline[0], len(baseline), 1
    )
    structures = [structure_key(rnd, action) for action in actions]
    cells = [(structures[index], signatures[index]) for index in range(len(actions))]

    rank = {index: position for position, index in enumerate(ranked)}
    baseline_counts = Counter(cells[index] for index in baseline)
    excluded_by_cell = {}
    baseline_set = set(baseline)
    for index in ranked:
        if index not in baseline_set:
            excluded_by_cell.setdefault(cells[index], []).append(index)

    eligible = [
        index for index in baseline[1:]
        if baseline_counts[cells[index]] >= 2 and excluded_by_cell.get(cells[index])
    ]
    if not eligible:
        return {"chosen": list(baseline), "audit": None}

    # Strict ranks make both choices unambiguous. Keep the selected-slot rule;
    # do not search another cell when this slot cannot improve.
    removed = max(eligible, key=rank.__getitem__)
    candidate = min(excluded_by_cell[cells[removed]], key=rank.__getitem__)
    if rank[candidate] >= rank[removed]:
        return {"chosen": list(baseline), "audit": None}
    chosen = list(baseline)
    chosen[chosen.index(removed)] = candidate
    audit = {
        "removed": _audit_entry(removed, canonical, rank, cells[removed]),
        "added": _audit_entry(candidate, canonical, rank, cells[candidate]),
    }
    return {"chosen": chosen, "audit": audit}


__all__ = ["within_cell_rank_repair"]

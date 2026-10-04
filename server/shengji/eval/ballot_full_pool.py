"""Descriptive full-pool analysis for a shared world-by-action matrix.

The caller supplies the complete action pool, two ordered ballots, and values
paired by world.  This module does not establish legality, provenance, model
quality, causal mechanism, or a production selection rule.  In particular,
ties are reported descriptively rather than resolved for serving.
"""

from __future__ import annotations

from .ballot_matrix import (
    CARD_INDEX,
    _canonical_collection,
    _column_means,
    _finite_result,
    summarize_ballot_matrix,
)


SCHEMA = "full-pool-ballot-matrix-summary-v1"


def _ordered_actions(actions: set[tuple[str, ...]]) -> list[tuple[str, ...]]:
    return sorted(actions, key=lambda action: tuple(CARD_INDEX[c] for c in action))


def _maximizers(candidates: set[tuple[str, ...]],
                means: dict[tuple[str, ...], float]) -> tuple[float, list[tuple[str, ...]]]:
    ordered = _ordered_actions(candidates)
    best = max(means[action] for action in ordered)
    return best, [action for action in ordered if means[action] == best]


def _ballot_summary(ballot: set[tuple[str, ...]],
                    means: dict[tuple[str, ...], float],
                    full_best: float,
                    full_maximizers: set[tuple[str, ...]]) -> dict:
    raw_best, raw_maximizers = _maximizers(ballot, means)
    try:
        gap = full_best - raw_best
    except (OverflowError, ValueError) as exc:
        raise ValueError("overflow computing gap to full maximum") from exc
    gap = _finite_result(gap, "gap to full maximum")
    return {
        # This representative is canonical/descriptive only.  It is not a
        # serving choice; raw_best_actions retains every exact raw tie.
        "raw_best_action": list(raw_maximizers[0]),
        "raw_best_actions": [list(action) for action in raw_maximizers],
        "raw_best_predicted_value": raw_best,
        "predicted_value_gap_to_full_maximum": gap,
        "any_maximum_available": bool(full_maximizers & ballot),
        "all_maximum_available": full_maximizers <= ballot,
    }


def summarize_full_pool_matrix(actions, control_ballot, treatment_ballot,
                               world_values) -> dict:
    """Summarize a complete supplied action pool and two restricted ballots.

    ``actions`` may contain legal candidates absent from both ballots.  Every
    ballot member must occur in ``actions``; duplicate canonical actions are
    refused while card multiplicity inside an action is retained.  The union
    field is the existing fixed-ballot summary over only the restricted union
    columns, so it is intentionally not a summary of the complete pool.
    """
    action_list = _canonical_collection(actions, "actions")
    control_list = _canonical_collection(control_ballot, "control_ballot")
    treatment_list = _canonical_collection(treatment_ballot, "treatment_ballot")
    action_set = set(action_list)
    control_set = set(control_list)
    treatment_set = set(treatment_list)
    if not control_set <= action_set or not treatment_set <= action_set:
        raise ValueError("ballots must contain only actions from actions")
    if not isinstance(world_values, list) or not world_values:
        raise ValueError("world_values must be a nonempty rectangular list")

    input_means = _column_means(world_values, len(action_list))
    means = {action: input_means[i] for i, action in enumerate(action_list)}
    full_best, full_maximizer_list = _maximizers(action_set, means)
    full_maximizers = set(full_maximizer_list)

    control = _ballot_summary(control_set, means, full_best, full_maximizers)
    treatment = _ballot_summary(treatment_set, means, full_best, full_maximizers)

    # The existing fixed-ballot helper requires its actions to be exactly the
    # union of the two ballots.  Restrict both action columns and means to that
    # union while preserving the caller's column correspondence.
    restricted_set = control_set | treatment_set
    restricted_actions = [action for action in action_list if action in restricted_set]
    restricted_indices = [action_list.index(action) for action in restricted_actions]
    restricted_world_values = [
        [row[column] for column in restricted_indices] for row in world_values
    ]
    restricted = summarize_ballot_matrix(
        [list(action) for action in restricted_actions],
        [list(action) for action in control_list],
        [list(action) for action in treatment_list],
        restricted_world_values,
    )

    return {
        "schema": SCHEMA,
        "world_count": len(world_values),
        "action_count": len(action_list),
        "actions": [list(action) for action in _ordered_actions(action_set)],
        "action_means": [means[action] for action in _ordered_actions(action_set)],
        "full_pool": {
            "best_predicted_value": full_best,
            "exact_maximizers": [list(action) for action in full_maximizer_list],
        },
        "control": control,
        "treatment": treatment,
        "union": restricted["union"],
        "union_summary": restricted,
        "strategic_quality_assessed": False,
        "causal_mechanism_assessed": False,
    }


__all__ = ["summarize_full_pool_matrix"]

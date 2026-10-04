"""Descriptive scoring for a caller-supplied shared-world ballot matrix.

This module only summarizes numbers that the caller has already paired by
world.  The caller owns root/model/tape provenance and all scientific
judgments; this helper cannot establish shared-world collection, engine
legality, strategic quality, or a serving tie-break rule.  In particular, the
selected-action paired mean and SE are descriptive post-selection quantities,
not calibrated confidence or tactical-correctness measures.
"""

from __future__ import annotations

import math

from ..engine.cards import JOKERS, RANKS, SUITS


SCHEMA = "fixed-ballot-matrix-summary-v1"

# Keep this order in lockstep with the engine's canonical card primitives,
# without importing the much heavier encoder module.
_CANONICAL_CARDS = [suit + rank for suit in SUITS for rank in RANKS]
_CANONICAL_CARDS += list(JOKERS)
CARD_INDEX = {code: index for index, code in enumerate(_CANONICAL_CARDS)}


def _canonical_action(action, label: str) -> tuple[str, ...]:
    if type(action) is not list or not action:
        raise ValueError(f"{label} must be a nonempty list")
    result = []
    for card in action:
        if type(card) is not str or card not in CARD_INDEX:
            raise ValueError(f"{label} contains unknown card code {card!r}")
        result.append(card)
    return tuple(sorted(result, key=CARD_INDEX.__getitem__))


def _canonical_collection(value, label: str) -> list[tuple[str, ...]]:
    if type(value) is not list or not value:
        raise ValueError(f"{label} must be a nonempty list")
    result = [_canonical_action(action, f"{label}[{i}]")
              for i, action in enumerate(value)]
    if len(set(result)) != len(result):
        raise ValueError(f"{label} contains duplicate canonical actions")
    return result


def _finite_number(value, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be an int or float (not bool)")
    try:
        finite = math.isfinite(value)
    except (OverflowError, TypeError):
        finite = False
    if not finite:
        raise ValueError(f"{label} must be finite")


def _finite_result(value, label: str):
    try:
        finite = math.isfinite(value)
    except (OverflowError, TypeError):
        finite = False
    if not finite:
        raise ValueError(f"nonfinite or overflowing derived {label}")
    return value


def _column_means(world_values: list[list[float]], action_count: int) -> list[float]:
    world_count = len(world_values)
    columns = [[] for _ in range(action_count)]
    for row_index, row in enumerate(world_values):
        if type(row) is not list or len(row) != action_count:
            raise ValueError("world_values must be a nonempty rectangular list")
        for column, value in enumerate(row):
            _finite_number(value, f"world_values[{row_index}][{column}]")
            columns[column].append(value)
    means = []
    for column, values in enumerate(columns):
        try:
            total = math.fsum(values)
            mean = total / world_count
        except (OverflowError, ValueError, ZeroDivisionError) as exc:
            raise ValueError(f"overflow computing mean for column {column}") from exc
        means.append(_finite_result(mean, f"mean for column {column}"))
    return means


def _selection(candidates: set[tuple[str, ...]], means: dict[tuple[str, ...], float]):
    ordered = sorted(candidates, key=lambda action: tuple(CARD_INDEX[c] for c in action))
    best_mean = max(means[action] for action in ordered)
    tied = [action for action in ordered if means[action] == best_mean]
    selected = tied[0]  # canonical winner makes exact ties input-order invariant
    if len(ordered) == 1:
        gap = None
    else:
        runner_up = max(means[action] for action in ordered if action != selected)
        try:
            gap = best_mean - runner_up
        except (OverflowError, ValueError) as exc:
            raise ValueError("overflow computing gap to runner-up") from exc
        gap = _finite_result(gap, "gap to runner-up")
    return {
        "selected_action": list(selected),
        "selected_mean": best_mean,
        "gap_to_runner_up": gap,
        "tied_best_count": len(tied),
    }


def summarize_ballot_matrix(actions, control_ballot, treatment_ballot,
                            world_values) -> dict:
    """Summarize restrictive choices from one shared world-by-action matrix.

    ``world_values[row][column]`` is supplied by the caller; no values are
    imputed.  Ballot/action order and row order do not affect the result.
    Card multiplicity inside an action is retained, while duplicate canonical
    actions in any collection are refused.  The paired SE is the sample
    standard error of treatment-minus-control differences on these same rows;
    it is ``None`` for fewer than two worlds.  No provenance, legality, causal
    mechanism, or strategy claim is inferred here.
    """
    action_list = _canonical_collection(actions, "actions")
    control_list = _canonical_collection(control_ballot, "control_ballot")
    treatment_list = _canonical_collection(treatment_ballot, "treatment_ballot")
    action_set = set(action_list)
    control_set = set(control_list)
    treatment_set = set(treatment_list)
    if control_set | treatment_set != action_set:
        raise ValueError("actions must be exactly the union of both ballots")
    if not isinstance(world_values, list) or not world_values:
        raise ValueError("world_values must be a nonempty rectangular list")

    # Input columns follow the caller's action order; output columns are
    # canonical.  This makes corresponding action/column permutations benign.
    input_means = _column_means(world_values, len(action_list))
    means = {action: input_means[i] for i, action in enumerate(action_list)}
    ordered_actions = sorted(action_set,
                             key=lambda action: tuple(CARD_INDEX[c] for c in action))
    ordered_means = [means[action] for action in ordered_actions]
    summaries = {
        "control": _selection(control_set, means),
        "treatment": _selection(treatment_set, means),
        "union": _selection(action_set, means),
    }

    # Re-read only validated rows and locate the selected columns without
    # mutating caller-owned data.  A difference is formed before aggregation,
    # preserving the common-world pairing and allowing common large effects to
    # cancel exactly when the input values represent them exactly.
    control_action = tuple(summaries["control"]["selected_action"])
    treatment_action = tuple(summaries["treatment"]["selected_action"])
    control_column = action_list.index(control_action)
    treatment_column = action_list.index(treatment_action)
    deltas = [row[treatment_column] - row[control_column] for row in world_values]
    for i, delta in enumerate(deltas):
        _finite_result(delta, f"paired difference at world {i}")
    try:
        difference_mean = math.fsum(deltas) / len(deltas)
    except (OverflowError, ValueError) as exc:
        raise ValueError("overflow computing paired difference mean") from exc
    difference_mean = _finite_result(difference_mean, "paired difference mean")
    if len(deltas) < 2:
        difference_se = None
    else:
        try:
            squared = math.fsum((delta - difference_mean) ** 2 for delta in deltas)
            variance = squared / (len(deltas) - 1)
            difference_se = math.sqrt(variance / len(deltas))
        except (OverflowError, ValueError, ZeroDivisionError) as exc:
            raise ValueError("overflow computing paired difference SE") from exc
        difference_se = _finite_result(difference_se, "paired difference SE")

    union_winner = tuple(summaries["union"]["selected_action"])
    return {
        "schema": SCHEMA,
        "world_count": len(world_values),
        "action_count": len(ordered_actions),
        "actions": [list(action) for action in ordered_actions],
        "action_means": ordered_means,
        "control": summaries["control"],
        "treatment": summaries["treatment"],
        "union": summaries["union"],
        "paired_selected_action_difference": {
            "mean": difference_mean,
            "se": difference_se,
        },
        "union_best_available_in_control": union_winner in control_set,
        "union_best_available_in_treatment": union_winner in treatment_set,
        "strategic_quality_assessed": False,
        "causal_mechanism_assessed": False,
    }

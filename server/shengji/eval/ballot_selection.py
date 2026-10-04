"""Descriptive joins for already-validated observation telemetry.

No artifact reader or scientific acceptance gate. Ranks describe an admitted
ballot, not the full legal pool or ground-truth move quality. Across arms the
sampled worlds can differ, so score changes do not isolate a causal mechanism.
"""
import math
from types import SimpleNamespace

from .tactical import _validate_observation_telemetry


def _action(cards):
    return tuple(sorted(cards))


def _arm(record, action):
    _validate_observation_telemetry(SimpleNamespace(record=record, action=action))
    actions = [_action(cards) for cards in record["admitted"]]
    if len(set(actions)) != len(actions):
        raise ValueError("duplicate admitted action makes ranks ambiguous")
    position = record["admitted_indices"].index(record["selected_index"])
    summary = {"selected_action": list(actions[position]),
               "selected_position": position,
               "selected_index": record["selected_index"],
               "admitted_count": len(actions)}
    for name, field in (("value", "value_means"), ("prior", "policy_log_odds_admitted")):
        scores = record[field]
        selected = scores[position]
        gap = max(scores) - selected
        if not math.isfinite(gap):
            raise ValueError("nonfinite derived score gap")
        summary[name] = {
            "selected_score": selected,
            # Competition ranking: all exact maxima have rank 1.
            "selected_rank": 1 + sum(score > selected for score in scores),
            "selected_ties": sum(score == selected for score in scores),
            "gap_to_max": gap,
        }
    return summary, set(actions)


def compare_ballot_selection(control_record, control_action,
                             treatment_record, treatment_action):
    """Describe two caller-paired decisions without inferring move quality.

    Caller must establish matching public root, package, seed, complete sealed
    outputs and reader ownership first. This helper neither reads artifacts nor
    establishes any of those prerequisites. Missing telemetry refuses; an absent
    action has no imputed score. Card permutations are equal; card multiplicities
    and original-pool indices are preserved.
    """
    control, control_set = _arm(control_record, control_action)
    treatment, treatment_set = _arm(treatment_record, treatment_action)
    return {
        "schema": "observation-ballot-selection-description-v1",
        "control": control, "treatment": treatment,
        "selection_changed": _action(control_action) != _action(treatment_action),
        "common_admitted": len(control_set & treatment_set),
        "control_only_admitted": len(control_set - treatment_set),
        "treatment_only_admitted": len(treatment_set - control_set),
        "control_selection_available_in_treatment": _action(control_action) in treatment_set,
        "treatment_selection_available_in_control": _action(treatment_action) in control_set,
        "strategic_quality_assessed": False,
        "causal_mechanism_assessed": False,
    }

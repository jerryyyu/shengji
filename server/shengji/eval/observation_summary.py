"""Selection-only summary for an already-authenticated M9 report.

The external reader owns artifact reading, reader ownership, model/fixture
seals, and provenance. This module is not a scientific acceptance gate.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from .ballot_selection import compare_ballot_selection

MODEL_SHA256 = "491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670"
NORMALIZED_FIXTURE_SHA256 = "f3d0c48ab6a077fdec6c83ebdd30550a801048edb1617b0037456a30e423e5e6"
COMPARISON = "r36-smv3-vs-div+rc+tb+la"
CHANGED_FLAGS = {
    "SHENGJI_PV_ADMISSION_DIVERSITY", "SHENGJI_PV_REFUSAL_CONSTRAINTS",
    "SHENGJI_PV_TIEBREAK_POINTS", "SHENGJI_PV_LEAD_ANCHOR",
}
FIXTURE_IDS = frozenset({
    "pvr8-c1-m0-p23-pair-preservation", "pvr8-c2-m0-p62-joker-control",
    "pvr8-c3-m0-p47-ace-control", "pvr8-c2-m0-p43-partner-overtake-control",
})
_SEEDS = (0, 1, 2)
_DECISION_KEYS = frozenset({
    "work_complete", "admitted", "admitted_indices", "value_means",
    "policy_log_odds_admitted", "selected_index", "seconds",
})


def _obj(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _arm(value: Any, label: str) -> tuple[list[str], Mapping[str, Any]]:
    arm = _obj(value, label)
    if arm.get("status") != "observed" or arm.get("error") is not None:
        raise ValueError(f"{label} must be observed with no error")
    action = arm.get("action")
    if (not isinstance(action, list) or not action
            or any(type(card) is not str for card in action)):
        raise ValueError(f"{label}.action must be a nonempty card list")
    decision = _obj(arm.get("decision"), f"{label}.decision")
    if set(decision) != _DECISION_KEYS:
        raise ValueError(f"{label}.decision fields mismatch")
    seconds = decision["seconds"]
    if (type(seconds) not in (int, float)
            or not math.isfinite(seconds) or seconds < 0):
        raise ValueError(f"{label}.decision.seconds must be finite and nonnegative")
    return action, decision


def summarize_observation_comparison(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Join twelve repeated root/seed observations descriptively.

    These are four public roots repeated at three seeds, not twelve independent
    gameplay cases. The adapter makes no legal-pool, quality, causality, or
    scientific-completeness claim; the external reader verifies those inputs,
    seals, and the actual bot names.
    """
    p = _obj(payload, "comparison payload")
    if p.get("comparison") != COMPARISON or p.get("comparison_complete") is not True:
        raise ValueError("complete reviewed comparison required")
    if p.get("checkpoint_sha256") != MODEL_SHA256:
        raise ValueError("checkpoint SHA mismatch")
    if p.get("normalized_fixture_sha256") != NORMALIZED_FIXTURE_SHA256:
        raise ValueError("normalized fixture SHA mismatch")
    seeds = p.get("seeds")
    if (not isinstance(seeds, list) or seeds != list(_SEEDS)
            or any(type(seed) is not int for seed in seeds)):
        raise ValueError("seeds must be exactly [0, 1, 2]")
    if type(p.get("fill_seed")) is not int or p["fill_seed"] != 0:
        raise ValueError("fill_seed must be strict integer 0")
    flags = p.get("changed_flags")
    if (not isinstance(flags, list) or len(flags) != 4
            or any(type(flag) is not str for flag in flags)
            or set(flags) != CHANGED_FLAGS or len(set(flags)) != 4):
        raise ValueError("changed_flags must be exactly the four reviewed flags")
    bots = _obj(p.get("bots"), "bots")
    if set(bots) != {"r36-smv3", "div+rc+tb+la"}:
        raise ValueError("comparison bot labels missing")
    labels = list(bots.values())
    if (any(type(label) is not str or not label.strip() for label in labels)
            or len(set(labels)) != 2):
        raise ValueError("comparison bot labels must be distinct nonempty strings")

    results = p.get("results")
    if not isinstance(results, list) or len(results) != 12:
        raise ValueError("comparison must contain exactly 12 rows")
    expected = {(fixture, seed) for fixture in FIXTURE_IDS for seed in _SEEDS}
    seen: set[tuple[str, int]] = set()
    rows, changed = [], 0
    for index, raw in enumerate(results):
        row = _obj(raw, f"results[{index}]")
        fixture, seed, fill = row.get("id"), row.get("seed"), row.get("fill_seed")
        if (type(fixture) is not str or fixture not in FIXTURE_IDS
                or type(seed) is not int or seed not in _SEEDS
                or type(fill) is not int or fill != 0):
            raise ValueError(f"results[{index}] root/seed/fill binding invalid")
        pair = (fixture, seed)
        if pair in seen:
            raise ValueError("duplicate fixture/seed row")
        seen.add(pair)
        control_action, control = _arm(row.get("control"), f"results[{index}].control")
        treatment_action, treatment = _arm(row.get("treatment"), f"results[{index}].treatment")
        description = compare_ballot_selection(control, control_action, treatment, treatment_action)
        changed += int(description["selection_changed"])
        rows.append({"id": fixture, "seed": seed, "fill_seed": 0,
                     "description": description})
    if seen != expected:
        raise ValueError("comparison rows must cover every required fixture and seed")
    summary = {"schema": "m9-observation-summary-v1", "bots": dict(bots),
               "rows": rows, "selection_changed_count": changed,
               "selection_count": 12, "strategic_quality_assessed": False,
               "causal_mechanism_assessed": False}
    for key in ("source", "source_metadata"):
        if key in p:
            summary[key] = p[key]
    return summary


__all__ = ["summarize_observation_comparison"]

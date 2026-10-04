"""Pure deterministic job planning for the fixed M9 panel.

The planner validates an already-read scientific analysis and emits detached
job descriptions.  It does not read files, import bots, collect worlds, or
provide launch authority.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any

from .ballot_matrix import _canonical_collection


SCHEMA = "m9-scientific-readout-v1"
CHECKPOINT_SHA256 = "491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670"
SEEDS = (0, 1, 2)
PRIMARY_ROOT = "pvr8-c1-m0-p23-pair-preservation"
SECONDARY_ROOTS = (
    "pvr8-c2-m0-p43-partner-overtake-control",
    "pvr8-c2-m0-p62-joker-control",
    "pvr8-c3-m0-p47-ace-control",
)
ROOTS = (PRIMARY_ROOT, *SECONDARY_ROOTS)
EXPECTED_LEGAL_COUNTS = {
    PRIMARY_ROOT: 712,
    SECONDARY_ROOTS[0]: 4,
    SECONDARY_ROOTS[1]: 3,
    SECONDARY_ROOTS[2]: 3,
}
EXPECTED_ACTION_COUNTS = {
    PRIMARY_ROOT: 8,
    SECONDARY_ROOTS[0]: 4,
    SECONDARY_ROOTS[1]: 3,
    SECONDARY_ROOTS[2]: 3,
}


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _strict_int(value: Any, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{label} must be a strict integer")
    return value


def _finite_means(value: Any, label: str, count: int) -> list[int | float]:
    if not isinstance(value, list) or len(value) != count:
        raise ValueError(f"{label} must have exactly {count} values")
    for index, number in enumerate(value):
        try:
            finite = math.isfinite(number)
        except (OverflowError, TypeError):
            finite = False
        if type(number) not in (int, float) or not finite:
            raise ValueError(f"{label}[{index}] must be a finite plain number")
    return value


def _validated_ballot(decision: Mapping[str, Any], label: str,
                      expected_count: int) -> list[list[str]]:
    if decision.get("work_complete") is not True:
        raise ValueError(f"{label}.work_complete must be true")
    admitted = decision.get("admitted")
    canonical = _canonical_collection(admitted, f"{label}.admitted")
    if len(canonical) != expected_count:
        raise ValueError(f"{label}.admitted has unexpected action count")
    _finite_means(decision.get("value_means"), f"{label}.value_means",
                  expected_count)
    # Copy the supplied representation, retaining action and card ordering;
    # canonicalization above is validation only.
    return copy.deepcopy(admitted)


def _validate_analysis(analysis: Any) -> dict[str, dict[int, dict[str, list[list[str]]]]]:
    payload = _object(analysis, "saved_analysis")
    if payload.get("schema") != SCHEMA:
        raise ValueError("saved analysis schema mismatch")
    seeds = payload.get("seeds")
    if (not isinstance(seeds, list) or seeds != list(SEEDS)
            or any(type(seed) is not int for seed in seeds)):
        raise ValueError("analysis.seeds must be exactly [0, 1, 2]")
    if _strict_int(payload.get("fill_seed"), "analysis.fill_seed") != 0:
        raise ValueError("analysis.fill_seed must be 0")
    if payload.get("checkpoint_sha256") != CHECKPOINT_SHA256:
        raise ValueError("analysis checkpoint declaration mismatch")

    roots = payload.get("roots")
    if not isinstance(roots, list) or len(roots) != len(ROOTS):
        raise ValueError("analysis must contain exactly four roots")
    by_root: dict[str, dict[int, dict[str, list[list[str]]]]] = {}
    for root_index, raw_root in enumerate(roots):
        root = _object(raw_root, f"analysis.roots[{root_index}]")
        root_id = root.get("id")
        if root_id not in ROOTS or root_id in by_root:
            raise ValueError("analysis roots must be the four unique expected IDs")
        seed_rows = root.get("seeds")
        if not isinstance(seed_rows, list) or len(seed_rows) != len(SEEDS):
            raise ValueError(f"{root_id}.seeds must contain exactly three rows")
        by_seed: dict[int, dict[str, list[list[str]]]] = {}
        for seed_index, raw_seed in enumerate(seed_rows):
            seed_row = _object(raw_seed, f"{root_id}.seeds[{seed_index}]")
            seed = _strict_int(seed_row.get("seed"), f"{root_id}.seed")
            if seed not in SEEDS or seed in by_seed:
                raise ValueError(f"{root_id} seeds must be unique [0, 1, 2]")
            if _strict_int(seed_row.get("fill_seed"),
                           f"{root_id}.fill_seed") != 0:
                raise ValueError(f"{root_id}.fill_seed must be 0")
            expected_count = EXPECTED_ACTION_COUNTS[root_id]
            arms: dict[str, list[list[str]]] = {}
            for arm in ("control", "treatment"):
                arm_obj = _object(seed_row.get(arm), f"{root_id}.{arm}")
                decision = _object(arm_obj.get("decision"),
                                   f"{root_id}.{arm}.decision")
                arms[arm] = _validated_ballot(
                    decision, f"{root_id}.{arm}.decision", expected_count)
            by_seed[seed] = arms
        if set(by_seed) != set(SEEDS):
            raise ValueError(f"{root_id} seeds must contain exactly [0, 1, 2]")
        by_root[root_id] = by_seed
    if set(by_root) != set(ROOTS):
        raise ValueError("analysis roots contain an extra or missing root")
    return by_root


def _job(root_id: str, mode: str, seed: int,
         ballots: dict[str, list[list[str]]]) -> dict[str, Any]:
    primary = mode == "fresh-root"
    legal_count = EXPECTED_LEGAL_COUNTS[root_id]
    capture_count = 3 if mode == "fresh-root" else 1
    return {
        "fixture_id": root_id,
        "mode": mode,
        "seed": seed,
        "fill_seed": 0,
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "control_ballot": copy.deepcopy(ballots["control"]),
        "treatment_ballot": copy.deepcopy(ballots["treatment"]),
        "role": "primary" if primary else "secondary",
        "capture_count": capture_count,
        "require_m9_replay_match": primary,
        "expected_legal_count": legal_count,
        "world_count": 64,
        "expected_leaf_evaluations": 64 * (
            legal_count + (8 if primary else 0) + (8 if primary else 0)),
    }


def build_m9_panel_plan(saved_analysis: Any) -> list[dict[str, Any]]:
    """Return the deterministic 15-job M9 panel plan.

    The checkpoint hash is a declared recipe pin, not an authentication
    result.  The returned dictionaries are detached from the input and from
    one another; this function has no collection or launch authority.
    """
    data = _validate_analysis(saved_analysis)
    jobs = []
    for seed in SEEDS:
        jobs.append(_job(PRIMARY_ROOT, "fresh-root", seed,
                         data[PRIMARY_ROOT][seed]))
    for root_id in ROOTS:
        for seed in SEEDS:
            jobs.append(_job(root_id, "history-primed", seed,
                             data[root_id][seed]))
    return jobs


__all__ = ["build_m9_panel_plan"]

"""Narrow consistency check for one public-fixture replay.

This module compares already-materialized panel and scientific-readout values;
it does not read artifacts, replay a tape, or establish tape, model, or
provenance identity.  In particular, a successful receipt is not a scientific
result acceptance gate.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

from .ballot_matrix import _canonical_collection


ROOT_ID = "pvr8-c1-m0-p23-pair-preservation"
_SEEDS = (0, 1, 2)
_CAPTURE_SCHEMA = "fixed-tape-same-leaf-capture-v1"
_COLLECTION_SCHEMA = "fixed-tape-three-pass-panel-v1"
_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
_ARMS = ("control", "treatment")


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _strict_int(value: Any, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{label} must be a strict integer")
    return value


def _checkpoint(value: Any, label: str) -> str:
    if type(value) is not str or _HASH_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 hex string")
    return value


def _means(value: Any, label: str) -> list[int | float]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a nonempty numeric list")
    for index, number in enumerate(value):
        try:
            finite = math.isfinite(number)
        except (OverflowError, TypeError):
            finite = False
        if type(number) not in (int, float) or not finite:
            raise ValueError(f"{label}[{index}] must be a finite plain number")
    return value


def _actions(value: Any, label: str) -> tuple[tuple[str, ...], ...]:
    # Besides validating cards, this rejects canonical duplicates while
    # retaining the caller's action order for the exact equality check.
    return tuple(_canonical_collection(value, label))


def _panel(panel: Any) -> tuple[Mapping[str, Any], int, str, Mapping[str, Any]]:
    p = _object(panel, "panel")
    if p.get("schema") != "public-fixture-panel-v1":
        raise ValueError("panel schema mismatch")
    if p.get("mode") != "fresh-root":
        raise ValueError("replay binding requires a fresh-root panel")
    if p.get("fixture_id") != ROOT_ID:
        raise ValueError("panel root mismatch")
    seed = _strict_int(p.get("seed"), "panel.seed")
    if seed not in _SEEDS:
        raise ValueError("panel.seed must be one of [0, 1, 2]")
    fill_seed = _strict_int(p.get("fill_seed"), "panel.fill_seed")
    if fill_seed != 0:
        raise ValueError("panel.fill_seed must be 0")
    checkpoint = _checkpoint(p.get("checkpoint_sha256"),
                             "panel.checkpoint_sha256")
    tape_receipt = _object(p.get("tape_receipt"), "panel.tape_receipt")
    if tape_receipt.get("schema") != "public-refusal-tape-v1":
        raise ValueError("panel tape receipt schema mismatch")
    if tape_receipt.get("mode") != "fresh-root":
        raise ValueError("panel tape receipt mode mismatch")
    if _strict_int(tape_receipt.get("seed"), "panel.tape_receipt.seed") != seed:
        raise ValueError("panel tape receipt seed mismatch")
    if _strict_int(tape_receipt.get("fill_seed"),
                   "panel.tape_receipt.fill_seed") != 0:
        raise ValueError("panel tape receipt fill_seed mismatch")
    if _strict_int(tape_receipt.get("world_count"),
                   "panel.tape_receipt.world_count") != 64:
        raise ValueError("panel tape receipt world_count mismatch")
    if _checkpoint(tape_receipt.get("checkpoint_sha256"),
                   "panel.tape_receipt.checkpoint_sha256") != checkpoint:
        raise ValueError("panel tape receipt checkpoint mismatch")
    ledger_receipt = tape_receipt.get("ledger_receipt")
    if isinstance(ledger_receipt, Mapping) and ledger_receipt.get("mode") != "fresh-root":
        raise ValueError("panel ledger receipt mode mismatch")
    collection = _object(p.get("collection"), "panel.collection")
    if collection.get("schema") != _COLLECTION_SCHEMA:
        raise ValueError("history-primed or unknown collection schema")
    captures = _object(collection.get("captures"), "panel.collection.captures")
    return p, seed, checkpoint, captures


def _analysis_seed_row(analysis: Mapping[str, Any], panel_seed: int) -> Mapping[str, Any]:
    roots = analysis.get("roots")
    if not isinstance(roots, list):
        raise ValueError("analysis.roots must be a list")
    matching_roots = [(_object(root, f"analysis.roots[{index}]"), index)
                      for index, root in enumerate(roots)
                      if isinstance(root, Mapping) and root.get("id") == ROOT_ID]
    if len(matching_roots) != 1:
        raise ValueError("analysis must contain exactly one matching root")
    root, root_index = matching_roots[0]
    seed_rows = root.get("seeds")
    if not isinstance(seed_rows, list) or len(seed_rows) != len(_SEEDS):
        raise ValueError(f"analysis.roots[{root_index}].seeds must contain 0, 1, 2")
    checked_seed_rows = []
    for index, seed_row in enumerate(seed_rows):
        seed_obj = _object(seed_row,
                           f"analysis.roots[{root_index}].seeds[{index}]")
        seed_value = _strict_int(seed_obj.get("seed"),
                                 f"analysis seed[{index}].seed")
        if seed_value not in _SEEDS:
            raise ValueError("analysis seed rows must use seeds 0, 1, 2")
        if _strict_int(seed_obj.get("fill_seed"),
                       f"analysis seed[{index}].fill_seed") != 0:
            raise ValueError("analysis seed.fill_seed must be 0")
        checked_seed_rows.append((seed_obj, seed_value))
    if {seed for _, seed in checked_seed_rows} != set(_SEEDS):
        raise ValueError("analysis seed rows must contain each seed exactly once")
    matching_seeds = [(seed_obj, index)
                      for index, (seed_obj, seed_value) in enumerate(checked_seed_rows)
                      if seed_value == panel_seed]
    if len(matching_seeds) != 1:
        raise ValueError("analysis must contain exactly one matching seed row")
    seed_row, _ = matching_seeds[0]
    return seed_row


def _validate_analysis(analysis: Any) -> tuple[Mapping[str, Any], str]:
    a = _object(analysis, "saved_analysis")
    if a.get("schema") != "m9-scientific-readout-v1":
        raise ValueError("saved analysis schema mismatch")
    seeds = a.get("seeds")
    if (not isinstance(seeds, list) or seeds != list(_SEEDS)
            or any(type(seed) is not int for seed in seeds)):
        raise ValueError("analysis.seeds must be exactly [0, 1, 2]")
    fill_seed = _strict_int(a.get("fill_seed"), "analysis.fill_seed")
    if fill_seed != 0:
        raise ValueError("analysis.fill_seed must be 0")
    checkpoint = _checkpoint(a.get("checkpoint_sha256"),
                             "analysis.checkpoint_sha256")
    return a, checkpoint


def _validate_arm(capture: Mapping[str, Any], decision: Any,
                  arm: str) -> int:
    if capture.get("schema") != _CAPTURE_SCHEMA:
        raise ValueError(f"{arm} capture schema mismatch")
    world_count = capture.get("world_count")
    if type(world_count) is not int or world_count != 64:
        raise ValueError(f"{arm} capture world_count must be strict 64")
    capture_actions = capture.get("actions")
    admitted = decision.get("admitted") if isinstance(decision, Mapping) else None
    # This comparison intentionally precedes canonicalization.  Card order and
    # action order are part of the replay binding, even when cards are a valid
    # canonical set in either order.
    if admitted != capture_actions:
        raise ValueError(f"{arm} admitted action order differs from capture")
    admitted_canonical = _actions(admitted, f"{arm}.decision.admitted")
    _actions(capture_actions, f"{arm}.capture.actions")
    decision_means = _means(decision.get("value_means"),
                            f"{arm}.decision.value_means")
    capture_means = _means(capture.get("serving_value_means"),
                           f"{arm}.capture.serving_value_means")
    if len(decision_means) != len(capture_means):
        raise ValueError(f"{arm} mean list lengths differ")
    if decision_means != capture_means:
        raise ValueError(f"{arm} decision and capture means differ")
    if len(decision_means) != len(admitted_canonical):
        raise ValueError(f"{arm} means must match admitted action count")
    return len(admitted_canonical)


def validate_m9_replay(panel: Any, saved_analysis: Any) -> dict[str, Any]:
    """Validate one declared fresh-root panel against a saved readout.

    The returned receipt records only exact field consistency.  It does not
    infer that the panel's tape is the historical tape, that a model is
    authenticated, or that any strategy or causal claim is correct.
    """
    _, panel_seed, panel_checkpoint, captures = _panel(panel)
    analysis, analysis_checkpoint = _validate_analysis(saved_analysis)
    if panel_checkpoint != analysis_checkpoint:
        raise ValueError("panel and analysis checkpoint hashes differ")

    row = _analysis_seed_row(analysis, panel_seed)

    arm_receipts: dict[str, dict[str, Any]] = {}
    for arm in _ARMS:
        saved_arm = _object(row.get(arm), f"analysis seed row {arm}")
        decision = _object(saved_arm.get("decision"), f"{arm}.decision")
        if decision.get("work_complete") is not True:
            raise ValueError(f"{arm} decision is not complete")
        capture = _object(captures.get(arm), f"panel.collection.captures.{arm}")
        count = _validate_arm(capture, decision, arm)
        arm_receipts[arm] = {"action_count": count,
                             "exact_means_match": True}

    return {
        "schema": "m9-replay-consistency-v1",
        "fixture_id": ROOT_ID,
        "seed": panel_seed,
        "fill_seed": 0,
        "checkpoint_sha256": panel_checkpoint,
        "control": arm_receipts["control"],
        "treatment": arm_receipts["treatment"],
        "tape_identity_verified": False,
        "provenance_verified": False,
        "strategic_quality_assessed": False,
    }


__all__ = ["validate_m9_replay"]

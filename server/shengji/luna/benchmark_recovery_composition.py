"""Compose one authenticated historical source with one recovery source.

This is an audit-only boundary.  It authenticates the historical retention
plan and the single recovery report through their existing loaders, then
selects one effective row per scheduled slot.  It does not create runner
input, classify failures, approve a retry, or write either source.

Historical retention may normalize an explicitly reviewed legacy C7 failure.
For an inherited slot the effective row is therefore the authenticated
normalized row, while both raw sidecar records remain visible in the result.
The inherited equality claim is canonical row equality after that approved
normalization; it is not a claim that the two sidecar byte streams are
identical.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Mapping

from .benchmark_recovery_source import load_recovery_source
from .benchmark_retention import RetentionRefusal, _row_cost, load_retained_attempts


SCHEMA = "benchmark-recovery-composition-v1"


def _reject_prior_attempt(row: Any, *, key: str, label: str) -> None:
    """Reject an unbounded per-row continuation before selecting its cost."""
    if type(row) is not dict:
        raise RetentionRefusal(f"{label} row {key} is malformed")
    if "prior_attempt" in row:
        raise RetentionRefusal(f"{label} row {key} carries prior_attempt")


def _same_directory(left: str, right: str) -> bool:
    """Detect equal directories even if callers spell an alias path."""
    left_path = Path(left)
    right_path = Path(right)
    try:
        return os.path.samefile(left_path, right_path)
    except OSError as exc:
        raise RetentionRefusal("cannot compare original and recovery directories") from exc


def compose_recovery_sources(
        plan_path: str | os.PathLike,
        plan_sha256: str,
        recovery_directory: str | os.PathLike,
        recovery_sha256: str,
        *,
        expected_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Authenticate and compose exactly one original plus one recovery.

    The recovery loader verifies the exact forty-slot schedule, inherited
    lineage, source recipe/roots, sidecars, and recorded cost audit.  No
    caller-supplied authenticated dictionaries are accepted here.
    """
    original = load_retained_attempts(
        plan_path, plan_sha256, expected_config=expected_config)

    # A retained plan names an absolute, loader-consumed source directory.
    # Reject an alias before authenticating a second report from that same
    # directory; composition is deliberately exactly two source generations.
    recovery_path = Path(recovery_directory)
    if _same_directory(original["path"], str(recovery_path)):
        raise RetentionRefusal("original and recovery directories must differ")

    recovery = load_recovery_source(
        recovery_directory, recovery_sha256,
        expected_config=expected_config,
        authenticated_retention=original,
    )
    if _same_directory(original["path"], recovery["path"]):
        raise RetentionRefusal("original and recovery directories must differ")

    original_rows = original["rows"]
    original_source_rows = original["source_rows"]
    recovery_source_rows = recovery["source_rows"]
    if (set(original_rows) != set(original_source_rows)
            or set(original_rows) != set(recovery_source_rows)
            or len(original_rows) != 40):
        raise RetentionRefusal("composition does not cover the exact schedule")

    slots: dict[str, dict[str, Any]] = {}
    selected_tokens = 0
    for key, normalized_original in original_rows.items():
        original_source = original_source_rows[key]
        recovery_source = recovery_source_rows[key]
        _reject_prior_attempt(normalized_original, key=key, label="original")
        _reject_prior_attempt(original_source["row"], key=key,
                             label="original source")
        _reject_prior_attempt(recovery_source["row"], key=key,
                             label="recovery source")

        recovered_row = recovery_source["row"]
        inherited = "lineage" in recovered_row
        if inherited:
            origin = "original"
            effective = normalized_original
        else:
            origin = "recovery"
            effective = recovered_row
        recorded_tokens = _row_cost(effective)
        selected_tokens += recorded_tokens
        slots[key] = {
            "origin": origin,
            "row": copy.deepcopy(effective),
            "original": copy.deepcopy(original_source),
            "recovery": copy.deepcopy(recovery_source),
            "recorded_tokens": recorded_tokens,
        }

    costs = copy.deepcopy(recovery["costs"])
    combined_tokens = costs.get("combined_tokens")
    if type(combined_tokens) is not int or isinstance(combined_tokens, bool):
        raise RetentionRefusal("recovery cost audit has invalid combined tokens")
    if selected_tokens != combined_tokens:
        raise RetentionRefusal("composed slot costs disagree with recovery audit")

    return {
        "schema": SCHEMA,
        "original": {
            "path": original["path"],
            "result_sha256": original["result_sha256"],
            "plan": str(Path(plan_path).resolve()),
            "plan_sha256": original["plan_sha256"],
        },
        "recovery": {
            "path": recovery["path"],
            "result_sha256": recovery["result_sha256"],
        },
        "slots": slots,
        "costs": costs,
    }


__all__ = ["compose_recovery_sources"]

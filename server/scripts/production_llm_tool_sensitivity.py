"""In-memory sensitivity readout for the proposed tool-illegal scenario.

This module is deliberately a reader-side PREP.  It does not admit a runner,
change the benchmark failure classifier, or approve the proposed amendment.
Rows are copied only for local classification; the caller's rows and evidence
are never rewritten.  A structured rollout rejection is accepted only after
the existing evidence proof rechecks the recorded request and engine context.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from scripts.production_llm_panel_readout import (
    BOOTSTRAP_SEED, INFORMATION, POLICIES, _contrast, analyze_panel_reports,
)
from shengji.luna.benchmark_failure_protocol import (
    PRESERVE_ILLEGAL,
    attempt_disposition,
)
from shengji.luna.benchmark_rollout_proof import verify_rollout_rejection


PROPOSED_AMENDMENT = "tool-illegal-forfeit-proposal-v1"
FAILURE_LIMIT = 8
MODES = ("actor-only", "perfect")
FLIPS = (0, 1)
SENSITIVITY_DISCLOSURE = (
    "Outcome-informed proposed scenario disclosed after r3; not predeclared "
    "or adopted."
)
TIER_DISCLOSURE = "tier comparison unavailable; no ranking claim"


class ToolSensitivityError(ValueError):
    """The supplied rows/evidence are not an admitted in-memory schedule."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ToolSensitivityError(message)


def _finite_number(value: Any, label: str) -> float:
    # Converting a very large integer can raise OverflowError; that is malformed
    # input, rather than a reason to let an implementation exception escape.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolSensitivityError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ToolSensitivityError(f"{label} must be a finite number") from exc
    if not math.isfinite(result):
        raise ToolSensitivityError(f"{label} must be a finite number")
    return result


def _identity(row: Mapping[str, Any]) -> tuple[str, int, int]:
    mode, seed, flip = row.get("information"), row.get("seed"), row.get("flip")
    _require(mode in MODES, "row information must be actor-only or perfect")
    _require(type(seed) is int, "row seed must be an integer")
    _require(type(flip) is int and flip in FLIPS, "row flip must be 0 or 1")
    return mode, seed, flip


def _check_schedule(rows: Sequence[Mapping[str, Any]]) -> tuple[list[tuple[str, int, int]], list[int]]:
    _require(type(rows) is list, "rows must be a list")
    _require(len(rows) == 40, "schedule must contain exactly 40 rows")
    identities: list[tuple[str, int, int]] = []
    seen: set[tuple[str, int, int]] = set()
    by_mode: dict[str, set[int]] = {mode: set() for mode in MODES}
    for row in rows:
        _require(isinstance(row, Mapping), "each row must be an object")
        identity = _identity(row)
        _require(identity not in seen, "duplicate scheduled mirror")
        seen.add(identity)
        identities.append(identity)
        by_mode[identity[0]].add(identity[1])
    _require(set(by_mode) == set(MODES), "schedule must contain both information modes")
    _require(all(len(seeds) == 10 for seeds in by_mode.values()),
             "each information mode must contain ten unique seeds")
    seeds = sorted(by_mode[MODES[0]])
    _require(by_mode[MODES[1]] == set(seeds),
             "information modes must use identical ten seeds")
    expected = {(mode, seed, flip) for mode in MODES for seed in seeds for flip in FLIPS}
    _require(seen == expected, "schedule must contain both flips for every mode and seed")
    return identities, seeds


def _check_evidence(evidence: Mapping[Any, Any], required: set[tuple[str, int, int]]) -> None:
    _require(isinstance(evidence, Mapping), "evidence must be a mapping")
    for key in evidence:
        _require(type(key) is tuple and len(key) == 3,
                 "evidence key is malformed")
        _identity({"information": key[0], "seed": key[1], "flip": key[2]})
    # Exact coverage prevents bytes for a different row from being silently
    # ignored and makes an empty no-tool schedule explicit.
    _require(set(evidence) == required,
             "evidence must exactly cover otherwise-unknown tool failures")
    for key in required:
        _require(type(key) is tuple and len(key) == 3, "evidence key is malformed")
        value = evidence[key]
        _require(isinstance(value, Mapping) and set(value) == {"packet_bytes", "final_bytes"},
                 "evidence value must contain exactly packet_bytes and final_bytes")
        _require(type(value["packet_bytes"]) is bytes and type(value["final_bytes"]) is bytes,
                 "evidence bytes must be exact bytes")


def _has_tool_fields(row: Mapping[str, Any]) -> bool:
    return "rollout_diagnostic" in row or "rollout_request_binding" in row


def _classify(row: Mapping[str, Any], identity: tuple[str, int, int], evidence: Mapping[Any, Any]) -> str:
    """Return complete/final-action-illegal/tool-request-illegal/pending."""
    # A diagnostic is an explicit claim that this is the structured tool path.
    # Do this before attempt_disposition: its not_run shortcut must not hide a
    # malformed diagnostic, and a final-action failure must not bypass proof.
    if _has_tool_fields(row):
        _require(row.get("status") is None,
                 "tool rejection proof cannot be accepted on a row with status")
        _require(row.get("complete") is False,
                 "tool rejection proof requires an incomplete row")
        _require("failure" not in row and "signed_levels" not in row,
                 "tool rejection row cannot also be a classified failure or score")
        proof_input = evidence[identity]
        try:
            verify_rollout_rejection(
                dict(row), packet_bytes=proof_input["packet_bytes"],
                final_bytes=proof_input["final_bytes"])
        except (ValueError, TypeError, KeyError) as exc:
            raise ToolSensitivityError("structured tool failure lacks valid rollout proof") from exc
        _require("signed_levels" not in row, "tool failure cannot contain signed_levels")
        return "tool_request_illegal"

    try:
        disposition = attempt_disposition(dict(row), protocol=PRESERVE_ILLEGAL)
    except (ValueError, TypeError) as exc:
        raise ToolSensitivityError("row failure disposition is invalid") from exc
    if disposition == "complete":
        _require("signed_levels" in row, "complete row requires signed_levels")
        _finite_number(row["signed_levels"], "signed_levels")
        return "complete"
    if disposition == "retained-model-failure":
        _require("signed_levels" not in row, "final-action failure cannot contain signed_levels")
        return "final_action_illegal"
    if disposition == "unattempted":
        _require("signed_levels" not in row, "pending row cannot contain signed_levels")
        _require(type(row.get("calls")) is list and not row["calls"],
                 "pending row calls must be empty")
        _require(type(row.get("events")) is list and not row["events"],
                 "pending row events must be empty")
        return "pending"
    raise ToolSensitivityError("unknown failure requires a valid structured tool proof")


def _sign_change(left: float | None, right: float | None) -> bool | None:
    if left is None or right is None:
        return None
    def sign(value: float) -> int:
        return (value > 0) - (value < 0)
    return sign(left) != sign(right)


def _mode_result(rows: Sequence[Mapping[str, Any]], mode: str,
                 classifications: Mapping[tuple[str, int, int], str], *,
                 bootstrap_seed: int) -> dict[str, Any]:
    selected = [
        (row, (mode, row["seed"], row["flip"]))
        for row in rows if row.get("information") == mode
    ]
    counts = {name: 0 for name in
              ("complete", "final_action_illegal", "tool_request_illegal", "pending")}
    by_seed: dict[int, dict[int, tuple[Mapping[str, Any], str, float | None]]] = {}
    for row, identity in selected:
        classification = classifications[identity]
        counts[classification] += 1
        value: float | None
        if classification == "complete":
            value = -_finite_number(row["signed_levels"], "signed_levels")
        elif classification in ("final_action_illegal", "tool_request_illegal"):
            value = 1.0
        else:
            value = None
        by_seed.setdefault(identity[1], {})[identity[2]] = (row, classification, value)

    primary_values: list[float] = []
    primary_seeds: list[int] = []
    sensitivity_values: list[float] = []
    sensitivity_seeds: list[int] = []
    tool_mirrors: list[dict[str, Any]] = []
    dropped_pair_mirrors: list[dict[str, Any]] = []
    affected_pair_seeds: list[int] = []
    for seed in sorted(by_seed):
        pair = by_seed[seed]
        _require(set(pair) == set(FLIPS), "schedule pair is missing a flip")
        if all(pair[flip][2] is not None for flip in FLIPS):
            primary_values.append((pair[0][2] + pair[1][2]) / 2.0)
            primary_seeds.append(seed)
        has_tool = any(pair[flip][1] == "tool_request_illegal" for flip in FLIPS)
        if has_tool:
            affected_pair_seeds.append(seed)
            for flip in FLIPS:
                row, classification, _ = pair[flip]
                identity = {"information": mode, "seed": seed, "flip": flip}
                dropped_pair_mirrors.append(identity)
                if classification == "tool_request_illegal":
                    tool_mirrors.append(identity)
        elif all(pair[flip][2] is not None for flip in FLIPS):
            sensitivity_values.append((pair[0][2] + pair[1][2]) / 2.0)
            sensitivity_seeds.append(seed)

    primary = _contrast(primary_values, seed=bootstrap_seed)
    sensitivity = _contrast(sensitivity_values, seed=bootstrap_seed)
    dropped_pair_mirrors.sort(key=lambda item: (item["seed"], item["flip"]))
    tool_mirrors.sort(key=lambda item: (item["seed"], item["flip"]))
    return {
        "information": mode,
        "counts": counts,
        "forfeit_signed_levels_model_perspective": -1,
        "forfeit_signed_levels_policy_perspective": 1,
        "primary": primary,
        "sensitivity": sensitivity,
        "mean_sign_change": _sign_change(primary["mean"], sensitivity["mean"]),
        "primary_paired_seeds": primary_seeds,
        "dropped_tool_mirror_identities": tool_mirrors,
        "dropped_pair_mirror_identities": dropped_pair_mirrors,
        "dropped_pair_seeds": affected_pair_seeds,
        "retained_paired_seeds": sensitivity_seeds,
        "dropped_tool_mirror_count": len(tool_mirrors),
        "dropped_pair_mirror_count": len(dropped_pair_mirrors),
        "dropped_pair_count": len(affected_pair_seeds),
        "retained_paired_count": len(sensitivity_seeds),
    }


def analyze_tool_sensitivity(
    rows: list[Mapping[str, Any]], *, evidence: Mapping[Any, Any],
    amendment: str, bootstrap_seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Analyze one exact 40-mirror schedule under the proposed scenario.

    The version selects a hypothetical scenario, not approval. The caller
    must authenticate rows and evidence externally. The proof verifier only
    checks their internal bindings and rechecks recorded engine legality.
    This is not terminal admission or a nine-policy ranking: pending slots
    may remain and the shared failure count does not prove dispatch order.
    """
    _require(amendment == PROPOSED_AMENDMENT,
             f"amendment must equal {PROPOSED_AMENDMENT!r}")
    identities, seeds = _check_schedule(rows)
    classifications: dict[tuple[str, int, int], str] = {}
    tool_required: set[tuple[str, int, int]] = set()
    for row, identity in zip(rows, identities):
        if _has_tool_fields(row):
            tool_required.add(identity)
    _check_evidence(evidence, tool_required)
    for row, identity in zip(rows, identities):
        classifications[identity] = _classify(row, identity, evidence)

    failed = sum(classification in ("final_action_illegal", "tool_request_illegal")
                 for classification in classifications.values())
    _require(failed <= FAILURE_LIMIT,
             f"shared failure limit exceeded: {failed} > {FAILURE_LIMIT}")
    modes = {
        mode: _mode_result(rows, mode, classifications, bootstrap_seed=bootstrap_seed)
        for mode in MODES
    }
    return {
        "schema": "production-llm-tool-sensitivity-v1",
        "schedule": {"scheduled": len(rows), "seeds": seeds, "modes": list(MODES),
                      "flips": list(FLIPS)},
        "amendment": amendment,
        "amendment_status": "proposed-scenario-only-not-approved",
        "scenario_disclosure": SENSITIVITY_DISCLOSURE,
        "evidence_disclosure": (
            "Caller must authenticate every row and packet_bytes/final_bytes "
            "externally; the verifier rechecks internal bindings and legality."
        ),
        "tier_comparison": TIER_DISCLOSURE,
        "final_action_protocol": PRESERVE_ILLEGAL,
        "failure_limit": FAILURE_LIMIT,
        "failed": failed,
        "stop_required": failed == FAILURE_LIMIT,
        "status": "partial" if any(
            mode["counts"]["pending"] for mode in modes.values()
        ) else "scored-scenario",
        "modes": modes,
    }


def analyze_panel_tool_sensitivity(
    report_data, campaign_contexts, *, evidence, amendment,
    bootstrap_seed=BOOTSTRAP_SEED,
):
    """Compare all nine policies on aligned pairs under the proposed rule.

    The canonical reader validates recipe/root/schedule joins and remains in
    ``baseline`` without modification. No report is rewritten to pretend it
    ran under the proposal. Caller authentication and terminal admission are
    still required externally. This only supplies the hypothetical analysis;
    it neither adopts the amendment nor defines new ranking/tier thresholds.
    """
    _require(type(evidence) is dict and set(evidence) == set(POLICIES),
             "evidence must name exactly the nine policies")
    _require(amendment == PROPOSED_AMENDMENT, "unknown proposed amendment")
    baseline = analyze_panel_reports(
        report_data, campaign_contexts, bootstrap_seed=bootstrap_seed)
    policies = {
        policy: analyze_tool_sensitivity(
            report_data[policy]["mirrors"], evidence=evidence[policy],
            amendment=amendment, bootstrap_seed=bootstrap_seed)
        for policy in POLICIES
    }
    # Cache only values already admitted by the proof-bound per-row analysis.
    # Each comparison below aligns by seed, never by row or list position.
    values = {
        policy: {
            mode: dict(zip(
                policies[policy]["modes"][information]["primary_paired_seeds"],
                policies[policy]["modes"][information]["primary"]["values"],
                strict=True))
            for mode, information in INFORMATION.items()
        }
        for policy in POLICIES
    }
    differences = []
    for index, left in enumerate(POLICIES):
        for right in POLICIES[index + 1:]:
            comparison = {"left": left, "right": right}
            for mode, information in INFORMATION.items():
                a, b = values[left][mode], values[right][mode]
                common = sorted(set(a) & set(b))
                excluded = sorted(
                    set(policies[left]["modes"][information]["dropped_pair_seeds"])
                    | set(policies[right]["modes"][information]["dropped_pair_seeds"]))
                kept = sorted(set(common) - set(excluded))
                primary = _contrast([a[seed] - b[seed] for seed in common],
                                    seed=bootstrap_seed)
                sensitivity = _contrast([a[seed] - b[seed] for seed in kept],
                                        seed=bootstrap_seed)
                comparison[mode] = {
                    "primary": primary, "sensitivity": sensitivity,
                    "primary_paired_seeds": common,
                    "sensitivity_paired_seeds": kept,
                    "excluded_tool_pair_seeds": excluded,
                    "removed_scored_pair_seeds": sorted(set(common) & set(excluded)),
                    "mean_sign_change": _sign_change(primary["mean"], sensitivity["mean"]),
                }
            differences.append(comparison)
    return {
        "schema": "production-llm-panel-tool-sensitivity-v1",
        "amendment": amendment,
        "amendment_status": "proposed-scenario-only-not-approved",
        "scenario_disclosure": SENSITIVITY_DISCLOSURE,
        "tier_comparison": TIER_DISCLOSURE,
        "baseline": baseline, "policies": policies,
        "row_differences": differences,
        "definition": "left policy minus right policy on matching scored deal pairs; "
                      "sensitivity excludes pairs with a tool failure in either policy",
    }

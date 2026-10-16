"""Quality gate for the validated hybrid paired-duel readout.

``qualify_duel`` consumes the mapping returned by the hybrid duel reader.  Its
caller is responsible for seals and identity; this module only checks the
telemetry and the already-read score fields.  It does not read files, replay
games, or authorize deployment.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


COUNTERS = (
    "play_decisions",
    "pv_fallback_budget",
    "pv_fallback_search_error",
    "pv_fallback_other",
    "pv_record_missing",
    "hybrid_attempted",
    "hybrid_applied",
    "hybrid_changed",
    "hybrid_expired",
    "hybrid_invalid",
)
HYBRID_COUNTERS = COUNTERS[5:]
FALLBACK_COUNTERS = COUNTERS[1:5]
ARMS = ("candidate", "baseline")


def _empty_totals() -> dict[str, dict[str, int]]:
    return {arm: {counter: 0 for counter in COUNTERS} for arm in ARMS}


def _finite_number(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, ValueError):
        return False


def qualify_duel(result: Mapping) -> dict:
    """Qualify a mapping already returned by ``hybrid_search_duel.read_duel``.

    The caller must provide the mapping returned by the validated reader.  The
    reader has validated row ordering and paired-score reconstruction, while
    the caller owns seal and identity checks; this function intentionally does
    not repeat those checks and never performs file or gameplay I/O.
    ``PARTIAL`` results can qualify for the same exploratory bar as
    ``COMPLETE`` results, but the caller must retain the partial label and must
    not present it as a fixed-population claim.
    """
    reasons: list[str] = []
    totals = _empty_totals()

    if not isinstance(result, Mapping):
        return {
            "quality_ok": False,
            "promotion_eligible": False,
            "status": None,
            "completed_pairs": None,
            "partial": False,
            "reasons": ["result is not a mapping"],
            "per_arm_totals": totals,
        }

    status = result.get("status")
    partial = status == "PARTIAL"
    status_ok = status == "COMPLETE" or status == "PARTIAL"
    if not status_ok:
        reasons.append(
            "status must be COMPLETE or PARTIAL"
            if status != "FAILED" else "FAILED result is not promotable")

    completed_pairs = result.get("deals")
    completed_ok = type(completed_pairs) is int and completed_pairs >= 0
    if not completed_ok:
        reasons.append("completed pair count is missing or invalid")

    rows = result.get("rows")
    rows_ok = isinstance(rows, Sequence) and not isinstance(rows, (str, bytes, bytearray))
    if not rows_ok:
        reasons.append("rows are missing or not a sequence")
    else:
        for row_index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                reasons.append(f"round {row_index} is not a mapping")
                continue
            telemetry = row.get("telemetry")
            if not isinstance(telemetry, Mapping):
                reasons.append(f"round {row_index} is missing telemetry")
                continue
            for arm in ARMS:
                bots = telemetry.get(arm)
                bots_ok = (isinstance(bots, Sequence)
                           and not isinstance(bots, (str, bytes, bytearray))
                           and len(bots) == 2)
                if not bots_ok:
                    reasons.append(f"round {row_index} {arm} must contain two bots")
                    continue
                for bot_index, bot in enumerate(bots):
                    if not isinstance(bot, Mapping):
                        reasons.append(
                            f"round {row_index} {arm} bot {bot_index} is not a mapping")
                        continue
                    values: dict[str, int] = {}
                    for counter in COUNTERS:
                        value = bot.get(counter)
                        if type(value) is not int or value < 0:
                            reasons.append(
                                f"round {row_index} {arm} bot {bot_index} "
                                f"has invalid {counter}")
                            continue
                        values[counter] = value
                        totals[arm][counter] += value
                    if len(values) != len(COUNTERS):
                        continue
                    attempted = values["hybrid_attempted"]
                    applied = values["hybrid_applied"]
                    changed = values["hybrid_changed"]
                    expired = values["hybrid_expired"]
                    invalid = values["hybrid_invalid"]
                    play_decisions = values["play_decisions"]
                    if not changed <= applied <= attempted <= play_decisions:
                        reasons.append(
                            f"round {row_index} {arm} bot {bot_index} "
                            "has impossible hybrid activation ordering")
                    if expired + invalid > attempted:
                        reasons.append(
                            f"round {row_index} {arm} bot {bot_index} "
                            "has too many expiry or invalid decisions")
                    if applied + expired + invalid > attempted:
                        reasons.append(
                            f"round {row_index} {arm} bot {bot_index} "
                            "has impossible hybrid decision accounting")

    candidate = totals["candidate"]
    baseline = totals["baseline"]
    if candidate["play_decisions"] <= 0:
        reasons.append("candidate has no play decisions")
    if baseline["play_decisions"] <= 0:
        reasons.append("baseline has no play decisions")
    if any(candidate[counter] != 0 for counter in FALLBACK_COUNTERS):
        reasons.append("candidate has a PV fallback or missing decision record")
    if any(baseline[counter] != 0 for counter in FALLBACK_COUNTERS):
        reasons.append("baseline has a PV fallback or missing decision record")
    if any(baseline[counter] != 0 for counter in HYBRID_COUNTERS):
        reasons.append("baseline has hybrid activity")
    if candidate["hybrid_attempted"] <= 0:
        reasons.append("candidate has no hybrid attempts")
    if candidate["hybrid_applied"] <= 0:
        reasons.append("candidate has no applied hybrid decisions")
    if candidate["hybrid_expired"] != 0:
        reasons.append("candidate has expired hybrid decisions")
    if candidate["hybrid_invalid"] != 0:
        reasons.append("candidate has invalid hybrid decisions")

    telemetry_ok = not reasons

    score_ready = False
    lower_bound = None
    if status_ok:
        if completed_ok and completed_pairs < 2:
            reasons.append("at least two completed pairs are required for CI eligibility")
        mean = result.get("paired_utility_mean")
        ci = result.get("paired_utility_ci")
        ci_ok = (isinstance(ci, Sequence)
                 and not isinstance(ci, (str, bytes, bytearray))
                 and len(ci) == 2
                 and all(_finite_number(bound) for bound in ci)
                 and float(ci[0]) <= float(ci[1]))
        mean_ok = _finite_number(mean)
        if not mean_ok:
            reasons.append("paired utility mean is missing or non-finite")
        if not ci_ok:
            reasons.append("paired utility CI must have two finite ordered bounds")
        score_ready = completed_ok and completed_pairs >= 2 and mean_ok and ci_ok

    quality_ok = status_ok and telemetry_ok and score_ready
    if quality_ok:
        lower_bound = float(result["paired_utility_ci"][0])
    promotion_eligible = quality_ok and lower_bound is not None and lower_bound > 0
    if quality_ok and not promotion_eligible:
        reasons.append("paired utility CI lower bound is not positive")

    return {
        "quality_ok": quality_ok,
        "promotion_eligible": promotion_eligible,
        "status": status,
        "completed_pairs": completed_pairs,
        "partial": partial,
        "reasons": reasons,
        "per_arm_totals": totals,
    }


__all__ = ["COUNTERS", "qualify_duel"]

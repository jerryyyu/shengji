"""Descriptive summaries of the existing, pinned refusal-sampler census.

Consumes saved census dictionaries, never raw shards. These rates neither
select games nor establish a treatment effect: arms can follow different
trajectories. Missing telemetry is not a zero observation.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping


def summarize_refusal_observations(censuses: Iterable[Mapping]) -> dict:
    """Pool counts before division; denominator is complete valid tuples.

The historical census only sums observations when ALL four sampler fields
are valid nonnegative integers. Retain that denominator, including valid
fallback records, rather than silently switching to completed PV turns.
    """
    keys = ("decisions", "valid_records", "missing_records", "partial_records",
            "invalid_records", "refusal_observations",
            "observations_positive_decisions")
    total = dict.fromkeys(keys, 0)
    for census in censuses:
        if (census.get("schema") != "pv-refusal-sampler-census-v1"
                or census.get("denominator") != "validrecords"
                or census.get("outcome_filter_applied") is not False):
            raise ValueError("incompatible refusal census")
        if any(type(census.get(k)) is not int or census[k] < 0 for k in keys):
            raise ValueError("census counts must be nonnegative integers")
        valid = census["valid_records"]
        positive = census["observations_positive_decisions"]
        observations = census["refusal_observations"]
        if census["decisions"] != sum(census[k] for k in
                ("valid_records", "missing_records", "partial_records", "invalid_records")):
            raise ValueError("census population accounting mismatch")
        if not 0 <= positive <= valid or observations < positive or (positive == 0 and observations != 0):
            raise ValueError("inconsistent observation totals")
        for key in keys:
            total[key] += census[key]
    valid = total["valid_records"]
    return {
        "counts": total,
        "denominator": "valid_records (all four refusal fields valid)",
        "mean_observations": total["refusal_observations"] / valid if valid else None,
        "share_with_observations": total["observations_positive_decisions"] / valid if valid else None,
        "valid_record_share": valid / total["decisions"] if total["decisions"] else None,
        "status": "observed" if valid else "no valid telemetry",
        "event_complete_activation": None,
        "observe_public_calls": None,
        "note": "Descriptive only; no cross-arm monotonicity or causal claim. "
                "Event-complete activation and observe_public call counters are not emitted.",
    }


def five_window_extension(point: float, ci95: tuple[float, float]) -> str:
    """v52ec proposal rule, not permission to launch additional windows.

Touching zero remains INCONCLUSIVE, as in the pinned classifier. A positive
interval never needs the inconclusive-result extension, regardless of point.
    """
    values = (point, *ci95)
    if len(values) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError("point and two CI endpoints must be finite numbers")
    low, high = ci95
    if not low <= point <= high:
        raise ValueError("unordered CI or point outside interval")
    if point > 0.015 and low <= 0 <= high:
        return "new predeclared confirmation may be proposed; no launch authority"
    return "no extension under the predeclared rule"

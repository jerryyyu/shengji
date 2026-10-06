"""Bounded S11 joined projections and descriptive root summaries.

This module joins the already existing release-38 admission boundary with the
two model-free rank-repair projections.  It does not score, sample, load a
model, establish provenance, or make a gameplay/strength claim.
"""

from __future__ import annotations

import math
import random
from .ballot_matrix import _canonical_collection, _finite_number, _finite_result
from .fixed_tape_policy import release38_admission
from .pair_resource_admission import project_rank_repair


ROOT_SCHEMA = "s11-joined-root-v1"
SUMMARY_SCHEMA = "s11-joined-summary-v1"
VALUE_SCOPE = "model-relative saved-value coverage; not realised strength"


def _root_id(value, label="root_id") -> str:
    if type(value) is not str or not value:
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _check(check_budget) -> None:
    if check_budget is not None:
        check_budget()


def project_s11(root_id, root, seat, capture, value_actions, value_means, *,
                check_budget=None) -> dict:
    """Produce one joined S11 root from one shared rank capture.

    The release-38 adapter is called exactly once.  Both projections consume
    its same returned baseline; a failure at any point propagates without a
    partial report.
    """
    _root_id(root_id)
    _check(check_budget)
    baseline = release38_admission(root, seat, capture,
                                   check_budget=check_budget)
    _check(check_budget)
    control = project_rank_repair(
        root, seat, capture, baseline["baseline_actions"], value_actions,
        value_means, signature_overlap_veto=True)
    _check(check_budget)
    treatment = project_rank_repair(
        root, seat, capture, baseline["baseline_actions"], value_actions,
        value_means, signature_overlap_veto=False)
    _check(check_budget)
    return {
        "schema": ROOT_SCHEMA,
        "status": "valid",
        "root_id": root_id,
        "baseline": baseline,
        "control": control,
        "treatment": treatment,
        "provenance_verified": False,
        "value_scope": VALUE_SCOPE,
    }


def _finite(value, label: str) -> None:
    _finite_number(value, label)


def _action_set(value, label: str) -> set[tuple[str, ...]]:
    return set(_canonical_collection(value, label))


def _projection(report, arm: str) -> dict:
    projection = report.get(arm)
    if not isinstance(projection, dict):
        raise ValueError(f"{arm} projection must be a mapping")
    if projection.get("schema") != "pair-resource-rank-repair-projection-v1":
        raise ValueError(f"{arm} projection schema mismatch")
    if type(projection.get("signature_overlap_veto")) is not bool:
        raise ValueError(f"{arm} signature_overlap_veto must be a bool")
    expected = arm == "control"
    if projection["signature_overlap_veto"] is not expected:
        raise ValueError(f"{arm} signature_overlap_veto mismatch")
    for side in ("baseline", "repaired"):
        value = projection.get(side)
        if not isinstance(value, dict):
            raise ValueError(f"{arm} {side} view must be a mapping")
        _canonical_collection(value.get("actions"), f"{arm}.{side}.actions")
        _finite(value.get("raw_value_max"), f"{arm}.{side}.raw_value_max")
    return projection


def _validate_displacement(projection, arm: str, baseline_max: float,
                           adapter_actions: list[tuple[str, ...]],
                           adapter_chosen: set[int]) -> tuple[bool, dict | None]:
    base = _action_set(projection["baseline"]["actions"], f"{arm}.baseline.actions")
    repaired = _action_set(projection["repaired"]["actions"], f"{arm}.repaired.actions")
    changed = base != repaired
    swap = projection.get("swap")
    audit = projection.get("displacement_audit")
    if (swap is None) != (not changed):
        raise ValueError(f"{arm} swap/ballot changed mismatch")
    if (audit is None) != (swap is None):
        raise ValueError(f"{arm} displacement audit mismatch")
    if swap is None:
        return changed, None
    if not isinstance(swap, dict):
        raise ValueError(f"{arm} swap must be a mapping")
    removed = swap.get("removed")
    added = swap.get("added")
    if type(removed) is not int or type(added) is not int:
        raise ValueError(f"{arm} swap indices must be integers")
    if not (0 <= removed < len(adapter_actions)
            and 0 <= added < len(adapter_actions)):
        raise ValueError(f"{arm} swap index outside baseline adapter pool")
    if removed not in adapter_chosen or added in adapter_chosen:
        raise ValueError(f"{arm} swap indices do not match baseline membership")
    if not isinstance(audit, dict):
        raise ValueError(f"{arm} displacement audit must be a mapping")
    removed_view = audit.get("removed")
    added_view = audit.get("added")
    if not isinstance(removed_view, dict) or not isinstance(added_view, dict):
        raise ValueError(f"{arm} displacement endpoints required")
    if (removed_view.get("pool_index") != removed
            or added_view.get("pool_index") != added):
        raise ValueError(f"{arm} displacement pool indices do not match swap")
    if (_canonical_collection([removed_view.get("action")], "removed action")[0]
            != adapter_actions[removed]
            or _canonical_collection([added_view.get("action")], "added action")[0]
            != adapter_actions[added]):
        raise ValueError(f"{arm} displacement action/index mismatch")
    removed_actions = _action_set([removed_view.get("action")],
                                  f"{arm}.displacement_audit.removed.action")
    added_actions = _action_set([added_view.get("action")],
                                f"{arm}.displacement_audit.added.action")
    if removed_actions != base - repaired or added_actions != repaired - base:
        raise ValueError(f"{arm} displacement actions do not describe the swap")
    if len(base - repaired) != 1 or len(repaired - base) != 1:
        raise ValueError(f"{arm} displacement must replace exactly one action")
    _finite(removed_view.get("saved_value_mean"),
            f"{arm}.displacement_audit.removed.saved_value_mean")
    _finite(added_view.get("saved_value_mean"),
            f"{arm}.displacement_audit.added.saved_value_mean")
    if (removed_view["saved_value_mean"] > baseline_max
            or added_view["saved_value_mean"] > projection["repaired"]["raw_value_max"]):
        raise ValueError(f"{arm} displacement endpoint exceeds its saved maximum")
    tie_count = audit.get("baseline_max_tie_count")
    if type(tie_count) is not int or not 1 <= tie_count <= len(base):
        raise ValueError(f"{arm} baseline_max_tie_count must be positive int")
    for key in ("removed_was_baseline_max", "removed_was_unique_baseline_max",
                "repaired_max_below_baseline"):
        if type(audit.get(key)) is not bool:
            raise ValueError(f"{arm} audit {key} must be a bool")
    removed_max = removed_view["saved_value_mean"] == baseline_max
    unique_max = removed_max and tie_count == 1
    repaired_below = projection["repaired"]["raw_value_max"] < baseline_max
    if (audit["removed_was_baseline_max"] != removed_max
            or audit["removed_was_unique_baseline_max"] != unique_max
            or audit["repaired_max_below_baseline"] != repaired_below):
        raise ValueError(f"{arm} displacement audit is incoherent")
    if not unique_max:
        expected_new_max = max(baseline_max, added_view["saved_value_mean"])
        if projection["repaired"]["raw_value_max"] != expected_new_max:
            raise ValueError(f"{arm} nonmaximum removal changed the wrong maximum")
    elif projection["repaired"]["raw_value_max"] > max(
            baseline_max, added_view["saved_value_mean"]):
        raise ValueError(f"{arm} unique maximum repair exceeds available endpoint values")
    if len(base) == 1 and unique_max:
        if projection["repaired"]["raw_value_max"] != added_view["saved_value_mean"]:
            raise ValueError(f"{arm} singleton repair maximum mismatch")
    return changed, audit


def _adapter_baseline(report) -> tuple[set, list[tuple[str, ...]], set[int], dict]:
    baseline = report.get("baseline")
    if not isinstance(baseline, dict):
        raise ValueError("baseline adapter must be a mapping")
    if baseline.get("schema") != "release38-admission-boundary-v1":
        raise ValueError("baseline adapter schema mismatch")
    actions = _action_set(baseline.get("baseline_actions"),
                          "baseline.baseline_actions")
    adapter_actions = _canonical_collection(baseline.get("actions"),
                                             "baseline.actions")
    chosen = baseline.get("chosen_indices")
    if (type(chosen) is not list or any(type(i) is not int for i in chosen)
            or len(set(chosen)) != len(chosen)
            or any(not 0 <= i < len(adapter_actions) for i in chosen)):
        raise ValueError("baseline chosen_indices must be integer list")
    chosen_actions = {adapter_actions[i] for i in chosen}
    if chosen_actions != actions or len(chosen_actions) != len(chosen):
        raise ValueError("baseline actions do not match chosen indices")
    return actions, adapter_actions, set(chosen), baseline


def _percentile(sorted_values: list[float], fraction: float) -> float:
    # Match the project's established nearest-rank indexing convention while
    # keeping the result wholly local and deterministic.
    index = int(fraction * (len(sorted_values) - 1))
    return _finite_result(sorted_values[index], "bootstrap percentile")


def _bootstrap(values: list[float], seed: int, samples: int) -> list[float]:
    rng = random.Random(seed)
    n = len(values)
    draws = []
    for _ in range(samples):
        try:
            draw = math.fsum(values[rng.randrange(n)] for _ in range(n)) / n
        except (OverflowError, ValueError, ZeroDivisionError) as exc:
            raise ValueError("overflow computing bootstrap mean") from exc
        draws.append(_finite_result(draw, "bootstrap mean"))
    draws.sort()
    return draws


def _validate_bootstrap(seed, samples) -> None:
    if type(seed) is not int or seed < 0:
        raise ValueError("bootstrap_seed must be a nonnegative integer")
    if type(samples) is not int or not 1 <= samples <= 100000:
        raise ValueError("bootstrap_samples must be an integer in [1, 100000]")


def summarize_s11(reports, scheduled_root_ids, *, bootstrap_seed=0,
                  bootstrap_samples=2000) -> dict:
    """Summarize one valid/failed/refused record per scheduled root.

    Valid roots are equally weighted independent units.  Failed and refused
    records are retained as coverage counts; missing roots are not silently
    converted into valid no-ops.
    """
    _validate_bootstrap(bootstrap_seed, bootstrap_samples)
    if not isinstance(reports, list):
        raise ValueError("reports must be a list")
    if not isinstance(scheduled_root_ids, list):
        raise ValueError("scheduled_root_ids must be a list")
    scheduled = [_root_id(root_id, "scheduled root_id")
                 for root_id in scheduled_root_ids]
    if len(set(scheduled)) != len(scheduled):
        raise ValueError("scheduled_root_ids must be unique")
    scheduled_set = set(scheduled)
    seen = set()
    valid_rows = []
    failures = []
    failed = refused = 0
    for report in reports:
        if not isinstance(report, dict):
            raise ValueError("each report must be a mapping")
        root_id = _root_id(report.get("root_id"))
        if root_id not in scheduled_set:
            raise ValueError("report root_id is outside the schedule")
        if root_id in seen:
            raise ValueError("duplicate report root_id")
        seen.add(root_id)
        status = report.get("status")
        if status in ("failed", "refused"):
            if set(report) != {"root_id", "status", "reason"}:
                raise ValueError("failed/refused records require root_id/status/reason")
            if type(report["reason"]) is not str or not report["reason"].strip():
                raise ValueError("failed/refused reason must be a nonempty string")
            failures.append(dict(report))
            if status == "failed":
                failed += 1
            else:
                refused += 1
            continue
        if status != "valid" or report.get("schema") != ROOT_SCHEMA:
            raise ValueError("malformed valid S11 report")
        if report.get("provenance_verified") is not False:
            raise ValueError("S11 provenance must remain false")
        baseline_actions, adapter_actions, adapter_chosen, _adapter = _adapter_baseline(report)
        control = _projection(report, "control")
        treatment = _projection(report, "treatment")
        control_base = _action_set(control["baseline"]["actions"],
                                   "control.baseline.actions")
        treatment_base = _action_set(treatment["baseline"]["actions"],
                                     "treatment.baseline.actions")
        if control_base != treatment_base or control_base != baseline_actions:
            raise ValueError("baseline action identities disagree")
        control_max = control["baseline"]["raw_value_max"]
        treatment_max = treatment["baseline"]["raw_value_max"]
        if control_max != treatment_max:
            raise ValueError("baseline maxima disagree")
        control_changed, control_audit = _validate_displacement(
            control, "control", control_max,
            adapter_actions, adapter_chosen)
        treatment_changed, treatment_audit = _validate_displacement(
            treatment, "treatment", control_max,
            adapter_actions, adapter_chosen)
        control_repaired = control["repaired"]["raw_value_max"]
        treatment_repaired = treatment["repaired"]["raw_value_max"]
        control_repaired_actions = _action_set(
            control["repaired"]["actions"], "control.repaired.actions")
        treatment_repaired_actions = _action_set(
            treatment["repaired"]["actions"], "treatment.repaired.actions")
        if control_repaired_actions == baseline_actions and control_repaired != control_max:
            raise ValueError("control unchanged ballot has a changed maximum")
        if treatment_repaired_actions == baseline_actions and treatment_repaired != control_max:
            raise ValueError("treatment unchanged ballot has a changed maximum")
        if (control_repaired_actions == treatment_repaired_actions
                and control_repaired != treatment_repaired):
            raise ValueError("identical repaired ballots have different maxima")
        try:
            primary = _finite_result(treatment_repaired - control_repaired,
                                     "T-C max delta")
            cb = _finite_result(control_repaired - control_max,
                                "C-B max delta")
            tb = _finite_result(treatment_repaired - control_max,
                                "T-B max delta")
        except (OverflowError, ValueError) as exc:
            raise ValueError("overflow computing S11 diagnostics") from exc
        valid_rows.append({
            "root_id": root_id, "primary": primary, "cb": cb, "tb": tb,
            "control_changed": control_changed,
            "treatment_changed": treatment_changed,
            "arms_changed": control_repaired_actions != treatment_repaired_actions,
            "control_audit": control_audit,
            "treatment_audit": treatment_audit,
        })

    valid_rows.sort(key=lambda row: row["root_id"])
    n = len(valid_rows)
    missing = len(scheduled) - len(seen)
    primary_values = [row["primary"] for row in valid_rows]
    cb_values = [row["cb"] for row in valid_rows]
    tb_values = [row["tb"] for row in valid_rows]

    def mean(values, label):
        if not values:
            return None
        try:
            result = math.fsum(values) / len(values)
        except (OverflowError, ValueError, ZeroDivisionError) as exc:
            raise ValueError(f"overflow computing {label} mean") from exc
        return _finite_result(result, f"{label} mean")

    mean_primary = mean(primary_values, "T-C")
    interval = None
    if n >= 2:
        boot = _bootstrap(primary_values, bootstrap_seed, bootstrap_samples)
        interval = [_percentile(boot, .025), _percentile(boot, .975)]

    def fraction(count, denominator):
        return {"numerator": count,
                "all_valid_denominator": denominator}

    equal_arms = sum(not row["arms_changed"] for row in valid_rows)
    no_op = sum(not row["control_changed"] and not row["treatment_changed"]
                for row in valid_rows)
    changes = {
        "control_vs_baseline": fraction(
            sum(row["control_changed"] for row in valid_rows), n),
        "treatment_vs_baseline": fraction(
            sum(row["treatment_changed"] for row in valid_rows), n),
        "treatment_vs_control": fraction(
            sum(row["arms_changed"] for row in valid_rows), n),
    }

    displacement = {}
    for arm in ("control", "treatment"):
        key = f"{arm}_audit"
        arm_changed = sum(row[f"{arm}_changed"] for row in valid_rows)
        displacement[arm] = {}
        for field in ("removed_was_baseline_max",
                      "removed_was_unique_baseline_max",
                      "repaired_max_below_baseline"):
            numerator = sum(bool(row[key] and row[key][field])
                            for row in valid_rows)
            displacement[arm][field] = {
                "numerator": numerator,
                "all_valid_denominator": n,
                "arm_changed_denominator": arm_changed,
            }

    result = {
        "schema": SUMMARY_SCHEMA,
        "status": "valid" if n else "UNAVAILABLE",
        "provenance_verified": False,
        "value_scope": VALUE_SCOPE,
        "scheduled_root_ids": sorted(scheduled),
        "scheduled_count": len(scheduled),
        "valid_count": n,
        "failed_count": failed,
        "refused_count": refused,
        "missing_count": missing,
        "coverage_complete": n == len(scheduled),
        "failures": sorted(failures, key=lambda row: row["root_id"]),
        "no_op_count": no_op,
        "treatment_equals_control_count": equal_arms,
        "primary": {
            "estimand": "T-C max_saved",
            "denominator": "all_valid_roots",
            "mean": mean_primary,
            "interval95": interval,
            "positive_root_count": sum(value > 0 for value in primary_values),
            "negative_root_count": sum(value < 0 for value in primary_values),
            "zero_root_count": sum(value == 0 for value in primary_values),
            "bootstrap": {"seed": bootstrap_seed,
                          "percentile_method": "sorted replicate index floor(p * (N - 1))",
                          "samples": bootstrap_samples,
                          "replicates": bootstrap_samples if n >= 2 else 0},
        },
        "diagnostics": {
            "primary": False,
            "control_minus_baseline_mean": mean(cb_values, "C-B"),
            "treatment_minus_baseline_mean": mean(tb_values, "T-B"),
            "change_counts": changes,
            "displacement": displacement,
        },
    }
    return result


__all__ = ["project_s11", "summarize_s11"]

import copy
import math
import random

import pytest

from shengji.eval.s11_report import summarize_s11


def _projection(veto, baseline, repaired, baseline_max, repaired_max,
                *, pool_index=None, removed_value=None, added_value=None):
    changed = baseline != repaired
    if not changed:
        swap = audit = None
    else:
        removed = pool_index[0]
        added = pool_index[1]
        swap = {"removed": removed, "added": added}
        removed_max = removed_value == baseline_max
        tie_count = 1
        audit = {
            "removed": {"pool_index": removed, "action": baseline[0],
                        "policy_rank_1based": 1,
                        "cell": {"structure": [], "held_pair_remainders": []},
                        "saved_value_mean": removed_value},
            "added": {"pool_index": added, "action": repaired[0],
                      "policy_rank_1based": 2,
                      "cell": {"structure": [], "held_pair_remainders": []},
                      "saved_value_mean": added_value},
            "removed_was_baseline_max": removed_max,
            "baseline_max_tie_count": tie_count,
            "removed_was_unique_baseline_max": removed_max and tie_count == 1,
            "repaired_max_below_baseline": repaired_max < baseline_max,
        }
    return {
        "schema": "pair-resource-rank-repair-projection-v1",
        "signature_overlap_veto": veto,
        "displacement_audit": audit,
        "baseline": {"actions": copy.deepcopy(baseline),
                      "raw_value_max": baseline_max, "gap_to_full_pool": 0},
        "repaired": {"actions": copy.deepcopy(repaired),
                      "raw_value_max": repaired_max, "gap_to_full_pool": 0},
        "swap": swap,
        "raw_value_max_delta": repaired_max - baseline_max,
        "value_scope": "test",
        "provenance_verified": False,
        "strategic_quality_assessed": False,
        "serving_choice_assessed": False,
    }


def report(root_id, control_value, treatment_value, *, changed=True):
    baseline = [["S2"]]
    if changed:
        control_actions, treatment_actions = [["S3"]], [["S4"]]
        control = _projection(True, baseline, control_actions, 1, control_value,
                              pool_index=(0, 1), removed_value=1,
                              added_value=control_value)
        treatment = _projection(False, baseline, treatment_actions, 1,
                                treatment_value, pool_index=(0, 2),
                                removed_value=1, added_value=treatment_value)
    else:
        control = _projection(True, baseline, baseline, 1, 1)
        treatment = _projection(False, baseline, baseline, 1, 1)
    return {
        "schema": "s11-joined-root-v1", "status": "valid", "root_id": root_id,
        "baseline": {"schema": "release38-admission-boundary-v1",
                      "actions": [["S2"], ["S3"], ["S4"]],
                      "chosen_indices": [0], "baseline_actions": [["S2"]]},
        "control": control, "treatment": treatment,
        "provenance_verified": False,
    }


def test_sign_reversal_and_all_noop_denominators():
    result = summarize_s11([report("r1", 4, 2)], ["r1"], bootstrap_samples=3)
    assert result["primary"]["mean"] == -2
    assert result["primary"]["positive_root_count"] == 0
    assert result["diagnostics"]["control_minus_baseline_mean"] == 3
    assert result["diagnostics"]["treatment_minus_baseline_mean"] == 1

    no_op = summarize_s11([report("r1", 0, 0, changed=False)], ["r1"])
    assert no_op["primary"]["mean"] == 0
    assert no_op["no_op_count"] == 1
    assert no_op["diagnostics"]["change_counts"]["treatment_vs_control"] == {
        "numerator": 0, "all_valid_denominator": 1}


def test_multiple_roots_are_sorted_and_bootstrap_does_not_touch_global_rng():
    rows = [report("b", 4, 2), report("a", 2, 4), report("c", 1, 1)]
    before = random.getstate()
    first = summarize_s11(rows, ["c", "a", "b"], bootstrap_seed=9,
                          bootstrap_samples=20)
    after = random.getstate()
    second = summarize_s11(list(reversed(rows)), ["b", "c", "a"],
                           bootstrap_seed=9, bootstrap_samples=20)
    assert before == after
    assert first == second
    assert first["primary"]["mean"] == 0
    assert first["primary"]["positive_root_count"] == 1
    assert first["primary"]["negative_root_count"] == 1
    assert first["primary"]["zero_root_count"] == 1
    # Seed 9 draws from root-ID order [2, -2, 0]; sorted replicate
    # means at floor(.025*19)=0 and floor(.975*19)=18 are -4/3,+4/3.
    assert first["primary"]["interval95"] == [-4 / 3, 4 / 3]
    assert first["primary"]["bootstrap"] == {
        "seed": 9, "samples": 20, "replicates": 20}


def test_mixed_noop_keeps_all_valid_denominators_and_null_audits():
    result = summarize_s11([report("changed", 4, 2),
                            report("noop", 0, 0, changed=False)],
                           ["noop", "changed"])
    assert result["no_op_count"] == 1
    assert result["diagnostics"]["change_counts"]["control_vs_baseline"] == {
        "numerator": 1, "all_valid_denominator": 2}
    assert result["diagnostics"]["displacement"]["control"][
        "removed_was_baseline_max"] == {
            "numerator": 1, "all_valid_denominator": 2,
            "arm_changed_denominator": 1}
    assert result["diagnostics"]["displacement"]["treatment"][
        "removed_was_unique_baseline_max"]["numerator"] == 1


def test_noop_maximum_and_displacement_index_must_be_coherent():
    mismatch = report("r", 0, 0, changed=False)
    mismatch["control"]["repaired"]["raw_value_max"] = 2
    with pytest.raises(ValueError):
        summarize_s11([mismatch], ["r"])

    mismatch = report("r", 4, 2)
    mismatch["control"]["displacement_audit"]["removed"]["pool_index"] = 2
    with pytest.raises(ValueError):
        summarize_s11([mismatch], ["r"])

    tied = report("r", 1, 1)
    tied["baseline"]["baseline_actions"] = [["S2"], ["S3"]]
    tied["baseline"]["chosen_indices"] = [0, 1]
    for arm in ("control", "treatment"):
        projection = tied[arm]
        projection["baseline"]["actions"] = [["S2"], ["S3"]]
        projection["repaired"]["actions"] = [["S3"], ["S4"]]
        projection["baseline"]["raw_value_max"] = 1
        projection["repaired"]["raw_value_max"] = 1
        projection["swap"] = {"removed": 0, "added": 2}
        audit = projection["displacement_audit"]
        audit["removed"]["pool_index"] = 0
        audit["removed"]["action"] = ["S2"]
        audit["added"]["pool_index"] = 2
        audit["added"]["action"] = ["S4"]
        audit["added"]["saved_value_mean"] = 1
        audit["baseline_max_tie_count"] = 2
        audit["removed_was_unique_baseline_max"] = False
        audit["repaired_max_below_baseline"] = False
    tied_summary = summarize_s11([tied], ["r"])
    assert tied_summary["diagnostics"]["displacement"]["control"][
        "removed_was_unique_baseline_max"]["numerator"] == 0


def test_derived_difference_overflow_is_rejected():
    huge = report("r", 1e308, -1e308)
    with pytest.raises(ValueError):
        summarize_s11([huge], ["r"])


def test_failures_refusals_missing_and_single_root_have_no_ci():
    result = summarize_s11([report("ok", 4, 2),
                            {"root_id": "bad", "status": "failed"},
                            {"root_id": "ref", "status": "refused"}],
                           ["ok", "bad", "ref", "missing"])
    assert (result["valid_count"], result["failed_count"],
            result["refused_count"], result["missing_count"]) == (1, 1, 1, 1)
    assert result["primary"]["interval95"] is None

    empty = summarize_s11([], ["missing"])
    assert empty["status"] == "UNAVAILABLE"
    assert empty["primary"]["mean"] is None
    assert empty["primary"]["interval95"] is None


def test_duplicate_outside_schedule_and_malformed_are_rejected():
    row = report("r", 4, 2)
    with pytest.raises(ValueError):
        summarize_s11([row, copy.deepcopy(row)], ["r"])
    with pytest.raises(ValueError):
        summarize_s11([row], ["other"])

    malformed = copy.deepcopy(row)
    malformed["control"]["baseline"]["raw_value_max"] = math.inf
    with pytest.raises(ValueError):
        summarize_s11([malformed], ["r"])


@pytest.mark.parametrize("seed,samples", [(True, 2), (-1, 2), (0, True), (0, 0),
                                           (0, 100001)])
def test_bootstrap_bounds_reject_bool_or_out_of_range(seed, samples):
    with pytest.raises(ValueError):
        summarize_s11([report("r", 4, 2), report("s", 2, 4)], ["r", "s"],
                      bootstrap_seed=seed, bootstrap_samples=samples)

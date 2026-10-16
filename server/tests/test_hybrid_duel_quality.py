from copy import deepcopy

import pytest

from shengji.train.hybrid_duel_quality import COUNTERS, qualify_duel


def _bot(*, candidate=False):
    values = {counter: 0 for counter in COUNTERS}
    values["play_decisions"] = 1
    if candidate:
        values.update(hybrid_attempted=1, hybrid_applied=1, hybrid_changed=1)
    return values


def _result(*, status="COMPLETE", rows=4, lower=0.25):
    return {
        "status": status,
        "deals": 2,
        "paired_utility_mean": 0.5,
        "paired_utility_ci": [lower, 0.75],
        "rows": [
            {"telemetry": {"candidate": [_bot(candidate=True), _bot(candidate=True)],
                            "baseline": [_bot(), _bot()]}}
            for _ in range(rows)
        ],
    }


def test_positive_complete_result_is_eligible_with_arm_totals():
    quality = qualify_duel(_result())

    assert quality["quality_ok"] is True
    assert quality["promotion_eligible"] is True
    assert quality["status"] == "COMPLETE"
    assert quality["completed_pairs"] == 2
    assert quality["partial"] is False
    assert quality["reasons"] == []
    assert quality["per_arm_totals"]["candidate"]["play_decisions"] == 8
    assert quality["per_arm_totals"]["candidate"]["hybrid_applied"] == 8
    assert quality["per_arm_totals"]["baseline"]["hybrid_attempted"] == 0


def test_nonpositive_ci_is_quality_but_not_promotion():
    quality = qualify_duel(_result(lower=0.0))

    assert quality["quality_ok"] is True
    assert quality["promotion_eligible"] is False
    assert any("lower bound" in reason for reason in quality["reasons"])


def test_partial_result_keeps_partial_label_and_can_pass_exploratory_bar():
    quality = qualify_duel(_result(status="PARTIAL", rows=5))

    assert quality["quality_ok"] is True
    assert quality["promotion_eligible"] is True
    assert quality["status"] == "PARTIAL"
    assert quality["partial"] is True


def test_failed_result_is_not_a_score_claim():
    failed = _result(status="FAILED")
    failed.pop("paired_utility_mean")
    failed.pop("paired_utility_ci")

    quality = qualify_duel(failed)

    assert quality["quality_ok"] is False
    assert quality["promotion_eligible"] is False
    assert quality["status"] == "FAILED"
    assert any("FAILED" in reason for reason in quality["reasons"])


def test_dangling_partial_mirror_telemetry_is_counted():
    result = _result(status="PARTIAL", rows=5)
    result["rows"][-1]["telemetry"]["candidate"][0]["pv_fallback_budget"] = 1

    quality = qualify_duel(result)

    assert quality["quality_ok"] is False
    assert quality["promotion_eligible"] is False
    assert quality["per_arm_totals"]["candidate"]["pv_fallback_budget"] == 1


@pytest.mark.parametrize("counter", COUNTERS[5:])
def test_baseline_hybrid_activity_is_a_zero_gate(counter):
    result = _result()
    result["rows"][0]["telemetry"]["baseline"][0][counter] = 1

    quality = qualify_duel(result)

    assert quality["quality_ok"] is False
    assert quality["promotion_eligible"] is False
    assert quality["per_arm_totals"]["baseline"][counter] == 1


@pytest.mark.parametrize("arm", ["candidate", "baseline"])
@pytest.mark.parametrize("counter", COUNTERS[1:5])
def test_any_fallback_or_missing_record_is_a_both_arm_zero_gate(arm, counter):
    result = _result()
    result["rows"][0]["telemetry"][arm][0][counter] = 1

    quality = qualify_duel(result)

    assert quality["quality_ok"] is False
    assert quality["promotion_eligible"] is False
    assert quality["per_arm_totals"][arm][counter] == 1


@pytest.mark.parametrize("mutation", [
    lambda bot: bot.pop("play_decisions"),
    lambda bot: bot.update(play_decisions=True),
    lambda bot: bot.update(hybrid_attempted=-1),
    lambda bot: bot.update(hybrid_applied=2),
    lambda bot: bot.update(hybrid_changed=2),
    lambda bot: bot.update(hybrid_expired=2),
])
def test_malformed_or_impossible_counters_fail_quality(mutation):
    result = _result()
    mutation(result["rows"][0]["telemetry"]["candidate"][0])

    quality = qualify_duel(result)

    assert quality["quality_ok"] is False
    assert quality["promotion_eligible"] is False
    assert quality["reasons"]


@pytest.mark.parametrize("field,value", [
    ("paired_utility_mean", float("nan")),
    ("paired_utility_mean", float("inf")),
    ("paired_utility_ci", [float("nan"), 1.0]),
    ("paired_utility_ci", [1.0, float("inf")]),
    ("paired_utility_ci", [1.0]),
    ("paired_utility_ci", [2.0, 1.0]),
])
def test_invalid_or_nonfinite_score_is_not_quality(field, value):
    result = _result()
    result[field] = value

    quality = qualify_duel(result)

    assert quality["quality_ok"] is False
    assert quality["promotion_eligible"] is False


def test_missing_bots_and_zero_activation_are_rejected():
    missing = _result()
    del missing["rows"][0]["telemetry"]["candidate"]
    zero = _result()
    for row in zero["rows"]:
        row["telemetry"]["candidate"] = [_bot(), _bot()]

    missing_quality = qualify_duel(missing)
    zero_quality = qualify_duel(zero)

    assert missing_quality["quality_ok"] is False
    assert zero_quality["quality_ok"] is False
    assert zero_quality["promotion_eligible"] is False


def test_fewer_than_two_pairs_cannot_claim_ci_eligibility():
    result = _result()
    result["deals"] = 1
    result["paired_utility_ci"] = None

    quality = qualify_duel(result)

    assert quality["quality_ok"] is False
    assert quality["promotion_eligible"] is False


def test_invalid_status_is_nonpromotable_without_hashing_assumptions():
    result = _result()
    result["status"] = ["COMPLETE"]

    quality = qualify_duel(result)

    assert quality["quality_ok"] is False
    assert quality["promotion_eligible"] is False


def test_input_is_not_mutated():
    result = _result()
    original = deepcopy(result)

    qualify_duel(result)

    assert result == original

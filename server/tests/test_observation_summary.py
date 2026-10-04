from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from shengji.eval import tactical as T
from shengji.eval.observation_summary import (
    COMPARISON,
    FIXTURE_IDS,
    MODEL_SHA256,
    NORMALIZED_FIXTURE_SHA256,
    summarize_observation_comparison,
)


def _decision(action, selected, seconds=0.25):
    admitted = [["S6", "S6"], ["S7", "S8"]]
    record = {
        "work_complete": True,
        "admitted": admitted,
        "admitted_indices": [10, 20],
        "selected_index": [10, 20][selected],
        "value_means": [0.2, 0.1],
        "policy_log_odds_admitted": [-1.0, -2.0],
    }
    assert action == admitted[selected]
    return T.observation_decision_metadata(
        SimpleNamespace(record=record, seconds=seconds))


def _arm(action, selected, seconds=0.25):
    return {"status": "observed", "action": action, "detail": "observed",
            "error": None, "decision": _decision(action, selected, seconds)}


def _payload():
    rows = []
    for fixture_id in sorted(FIXTURE_IDS):
        for seed in (0, 1, 2):
            changed = seed == 0
            rows.append({
                "id": fixture_id, "seed": seed, "fill_seed": 0,
                "control": _arm(["S6", "S6"], 0),
                "treatment": _arm(["S7", "S8"] if changed else ["S6", "S6"],
                                   1 if changed else 0),
            })
    return {
        "comparison": COMPARISON, "comparison_complete": True,
        "checkpoint": "/external/pinned/model.npz", "checkpoint_sha256": MODEL_SHA256,
        "normalized_fixture_sha256": NORMALIZED_FIXTURE_SHA256,
        "seeds": [0, 1, 2], "fill_seed": 0,
        "changed_flags": ["SHENGJI_PV_ADMISSION_DIVERSITY",
                          "SHENGJI_PV_REFUSAL_CONSTRAINTS",
                          "SHENGJI_PV_TIEBREAK_POINTS", "SHENGJI_PV_LEAD_ANCHOR"],
        "bots": {"r36-smv3": "external-control", "div+rc+tb+la": "external-treatment"},
        "source_metadata": {"reader": "external", "sealed": True},
        "results": rows,
    }


def test_summary_joins_all_four_roots_and_three_seeds_descriptively():
    summary = summarize_observation_comparison(_payload())

    assert summary["schema"] == "m9-observation-summary-v1"
    assert len(summary["rows"]) == 12
    assert {(row["id"], row["seed"]) for row in summary["rows"]} == {
        (fixture_id, seed) for fixture_id in FIXTURE_IDS for seed in (0, 1, 2)
    }
    assert summary["selection_changed_count"] == 4
    assert all("description" in row for row in summary["rows"])
    assert summary["source_metadata"] == {"reader": "external", "sealed": True}
    assert not summary["strategic_quality_assessed"]
    assert not summary["causal_mechanism_assessed"]


@pytest.mark.parametrize("mutation", ["partial", "duplicate", "missing", "model", "fixture", "boolseed", "timing"])
def test_summary_rejects_incomplete_or_unpinned_payloads(mutation):
    payload = _payload()
    if mutation == "partial":
        payload["comparison_complete"] = False
    elif mutation == "duplicate":
        payload["results"][-1] = copy.deepcopy(payload["results"][0])
    elif mutation == "missing":
        payload["results"].pop()
    elif mutation == "model":
        payload["checkpoint_sha256"] = "0" * 64
    elif mutation == "fixture":
        payload["normalized_fixture_sha256"] = "0" * 64
    elif mutation == "boolseed":
        payload["seeds"] = [True, 1, 2]
    else:
        payload["results"][0]["control"]["decision"]["seconds"] = -1.0

    with pytest.raises(ValueError):
        summarize_observation_comparison(payload)


def test_summary_rejects_per_row_boolean_seed():
    payload = _payload()
    payload["results"][0]["seed"] = True
    with pytest.raises(ValueError):
        summarize_observation_comparison(payload)


@pytest.mark.parametrize("seconds", [float("nan"), float("inf"), True])
def test_summary_rejects_nonfinite_or_boolean_timing(seconds):
    payload = _payload()
    payload["results"][0]["control"]["decision"]["seconds"] = seconds
    with pytest.raises(ValueError):
        summarize_observation_comparison(payload)


def test_summary_rejects_malformed_changed_flag_types_before_set_operations():
    payload = _payload()
    payload["changed_flags"] = [{"not": "a flag"}, *payload["changed_flags"][1:]]
    with pytest.raises(ValueError):
        summarize_observation_comparison(payload)

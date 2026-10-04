from __future__ import annotations

import copy
import math

import pytest

from shengji.eval.m9_panel_plan import (
    CHECKPOINT_SHA256,
    PRIMARY_ROOT,
    ROOTS,
    build_m9_panel_plan,
)


def _decision(actions):
    return {"work_complete": True, "admitted": copy.deepcopy(actions),
            "value_means": [float(index) for index in range(len(actions))],
            "ignored_matrix_means": [math.inf]}


def _actions(count, prefix):
    cards = ["D6", "D7", "D8", "D9", "D10", "DJ", "DQ", "DK",
             "H6", "H7", "H8", "H9", "H10", "HJ", "HQ", "HK"]
    offset = 0 if prefix == "control" else 8
    return [[card] for card in cards[offset:offset + count]]


def _analysis():
    roots = []
    counts = {ROOTS[0]: 8, ROOTS[1]: 4, ROOTS[2]: 3, ROOTS[3]: 3}
    for root_id in ROOTS:
        seeds = []
        for seed in (0, 1, 2):
            control = _actions(counts[root_id], "control")
            treatment = _actions(counts[root_id], "treatment")
            seeds.append({"seed": seed, "fill_seed": 0,
                          "control": {"decision": _decision(control)},
                          "treatment": {"decision": _decision(treatment)}})
        roots.append({"id": root_id, "seeds": seeds})
    return {"schema": "m9-scientific-readout-v1", "seeds": [0, 1, 2],
            "fill_seed": 0, "checkpoint_sha256": CHECKPOINT_SHA256,
            "roots": roots}


def test_plan_has_deterministic_population_and_leaf_accounting():
    plan = build_m9_panel_plan(_analysis())
    assert len(plan) == 15
    assert [job["role"] for job in plan[:3]] == ["primary"] * 3
    assert [job["seed"] for job in plan[:3]] == [0, 1, 2]
    assert all(job["fixture_id"] == PRIMARY_ROOT
               and job["mode"] == "fresh-root"
               and job["capture_count"] == 3
               and job["require_m9_replay_match"] is True
               for job in plan[:3])
    assert all(job["mode"] == "history-primed"
               and job["capture_count"] == 1
               and job["require_m9_replay_match"] is False
               for job in plan[3:])
    assert sum(job["capture_count"] for job in plan) == 21
    assert sum(job["expected_leaf_evaluations"] for job in plan) == 278400
    assert sum(job["require_m9_replay_match"] for job in plan) == 3


def test_plan_preserves_ballot_order_and_is_detached():
    analysis = _analysis()
    analysis["roots"][0]["seeds"][0]["control"]["decision"]["admitted"][0] = ["HK", "D6"]
    original = copy.deepcopy(analysis)
    first = build_m9_panel_plan(analysis)
    second = build_m9_panel_plan(analysis)
    assert first == second
    first[0]["control_ballot"][0][0] = "D10"
    first[0]["control_ballot"].append(["CJ"])
    assert analysis == original
    assert second[0]["control_ballot"] == original["roots"][0]["seeds"][0]["control"]["decision"]["admitted"]
    assert first[1]["control_ballot"] != first[0]["control_ballot"]
    assert first[3]["control_ballot"] == second[0]["control_ballot"]
    assert second[0]["control_ballot"][0] == ["HK", "D6"]


def test_root_and_seed_input_permutations_do_not_change_plan():
    analysis = _analysis()
    permuted = copy.deepcopy(analysis)
    permuted["roots"].reverse()
    for root in permuted["roots"]:
        root["seeds"].reverse()
    assert build_m9_panel_plan(analysis) == build_m9_panel_plan(permuted)


@pytest.mark.parametrize("mutation", ["schema", "seeds", "fill", "hash"])
def test_analysis_header_is_strict(mutation):
    analysis = _analysis()
    if mutation == "schema":
        analysis["schema"] = "other"
    elif mutation == "seeds":
        analysis["seeds"] = [0, True, 2]
    elif mutation == "fill":
        analysis["fill_seed"] = True
    else:
        analysis["checkpoint_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        build_m9_panel_plan(analysis)


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate"])
def test_root_population_is_exact(mutation):
    analysis = _analysis()
    if mutation == "missing":
        analysis["roots"].pop()
    elif mutation == "extra":
        analysis["roots"].append({"id": "unexpected", "seeds": []})
    else:
        analysis["roots"][1]["id"] = PRIMARY_ROOT
    with pytest.raises(ValueError):
        build_m9_panel_plan(analysis)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "bool", "fill"])
def test_seed_population_is_exact(mutation):
    analysis = _analysis()
    rows = analysis["roots"][0]["seeds"]
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows[1]["seed"] = 0
    elif mutation == "bool":
        rows[1]["seed"] = True
    else:
        rows[1]["fill_seed"] = 1
    with pytest.raises(ValueError):
        build_m9_panel_plan(analysis)


@pytest.mark.parametrize("mutation", ["incomplete", "short", "nan", "bool", "duplicate"])
def test_decision_and_ballot_validation(mutation):
    analysis = _analysis()
    decision = analysis["roots"][0]["seeds"][0]["control"]["decision"]
    if mutation == "incomplete":
        decision["work_complete"] = False
    elif mutation == "short":
        decision["value_means"] = [1.0]
    elif mutation == "nan":
        decision["value_means"][0] = float("nan")
    elif mutation == "bool":
        decision["value_means"][0] = True
    else:
        decision["admitted"][1] = copy.deepcopy(decision["admitted"][0])
    with pytest.raises(ValueError):
        build_m9_panel_plan(analysis)

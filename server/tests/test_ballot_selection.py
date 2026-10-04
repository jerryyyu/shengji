import copy

import pytest

from shengji.eval.ballot_selection import compare_ballot_selection


def record():
    return {"work_complete": True, "admitted": [["S6", "S6"], ["S5", "S7"]],
            "admitted_indices": [7, 19], "selected_index": 19,
            "value_means": [0.4, 0.39], "policy_log_odds_admitted": [-2.0, -1.0]}


def test_noncontiguous_indices_and_nonmax_selection_are_descriptive():
    c, t = record(), record()
    original = copy.deepcopy((c, t))
    t["selected_index"] = 7
    result = compare_ballot_selection(c, ["S7", "S5"], t, ["S6", "S6"])
    assert result["control"]["selected_position"] == 1
    assert result["control"]["value"]["selected_rank"] == 2
    assert result["control"]["value"]["gap_to_max"] == pytest.approx(0.01)
    assert result["control"]["prior"]["selected_rank"] == 1
    assert result["selection_changed"] and result["common_admitted"] == 2
    assert result["treatment_selection_available_in_control"]
    assert not result["strategic_quality_assessed"]
    assert not result["causal_mechanism_assessed"]
    assert c == original[0]  # no sorting/mutation of supplied records


def test_ties_and_reordered_actions_are_not_a_change():
    c = record()
    c["value_means"] = [0.4, 0.4]
    result = compare_ballot_selection(c, ["S5", "S7"], c, ["S7", "S5"])
    assert not result["selection_changed"]
    assert result["control"]["value"]["selected_rank"] == 1
    assert result["control"]["value"]["selected_ties"] == 2


def test_new_action_has_membership_not_an_imputed_control_value():
    c, t = record(), record()
    t["admitted"][1] = ["H5", "H7"]
    result = compare_ballot_selection(c, ["S5", "S7"], t, ["H5", "H7"])
    assert result["common_admitted"] == 1
    assert result["treatment_only_admitted"] == 1
    assert not result["treatment_selection_available_in_control"]


def test_finite_inputs_must_not_produce_infinite_score_gap():
    c = record()
    c["policy_log_odds_admitted"] = [1e308, -1e308]
    with pytest.raises(ValueError, match="derived score gap"):
        compare_ballot_selection(c, ["S5", "S7"], record(), ["S5", "S7"])


@pytest.mark.parametrize("bad", ["incomplete", "missing", "nan", "index", "duplicate"])
def test_unusable_telemetry_refuses(bad):
    c = record()
    if bad == "incomplete": c["work_complete"] = False
    if bad == "missing": c.pop("policy_log_odds_admitted")
    if bad == "nan": c["value_means"][0] = float("nan")
    if bad == "index": c["selected_index"] = 1
    if bad == "duplicate": c["admitted"][0] = ["S7", "S5"]
    with pytest.raises(ValueError):
        compare_ballot_selection(c, ["S5", "S7"], record(), ["S5", "S7"])

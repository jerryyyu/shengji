from __future__ import annotations

import copy

import pytest

from shengji.eval.m9_replay_binding import ROOT_ID, validate_m9_replay


HASH = "a" * 64
CONTROL = [["D6"], ["D7"]]
TREATMENT = [["H6"], ["H7"]]


def _capture(actions, means):
    return {
        "schema": "fixed-tape-same-leaf-capture-v1",
        "actions": copy.deepcopy(actions),
        "world_count": 64,
        "value_matrix": [[900, -900] for _ in range(64)],
        "serving_value_means": list(means),
    }


def _decision(actions, means):
    return {"work_complete": True, "admitted": copy.deepcopy(actions),
            "value_means": list(means)}


def _inputs():
    captures = {
        "control": _capture(CONTROL, [1.25, 2.5]),
        "treatment": _capture(TREATMENT, [-3.0, 4.0]),
    }
    panel = {
        "schema": "public-fixture-panel-v1", "fixture_id": ROOT_ID,
        "mode": "fresh-root", "seed": 1, "fill_seed": 0,
        "checkpoint_sha256": HASH,
        "tape_receipt": {"schema": "public-refusal-tape-v1",
                         "mode": "fresh-root", "seed": 1, "fill_seed": 0,
                         "world_count": 64, "checkpoint_sha256": HASH,
                         "ledger_receipt": {"mode": "fresh-root"}},
        "actions": [["D6"], ["D7"], ["H6"], ["H7"]],
        "collection": {"schema": "fixed-tape-three-pass-panel-v1",
                       "captures": captures,
                       # The full-pool matrix is deliberately irrelevant.
                       "shared_matrix_summary": {"action_means": [999]},},
    }
    row = {
        "seed": 1, "fill_seed": 0,
        "control": {"decision": _decision(CONTROL, [1.25, 2.5])},
        "treatment": {"decision": _decision(TREATMENT, [-3.0, 4.0])},
    }
    seed_rows = [{"seed": seed, "fill_seed": 0,
                  "control": copy.deepcopy(row["control"]),
                  "treatment": copy.deepcopy(row["treatment"])}
                 for seed in (0, 1, 2)]
    analysis = {"schema": "m9-scientific-readout-v1",
                "checkpoint_sha256": HASH, "seeds": [0, 1, 2],
                "fill_seed": 0,
                "roots": [{"id": ROOT_ID, "seeds": seed_rows}]}
    return panel, analysis


def test_matching_receipt_ignores_full_pool_matrix_and_preserves_inputs():
    panel, analysis = _inputs()
    original = copy.deepcopy((panel, analysis))
    receipt = validate_m9_replay(panel, analysis)
    assert receipt == {
        "schema": "m9-replay-consistency-v1", "fixture_id": ROOT_ID,
        "seed": 1, "fill_seed": 0, "checkpoint_sha256": HASH,
        "control": {"action_count": 2, "exact_means_match": True},
        "treatment": {"action_count": 2, "exact_means_match": True},
        "tape_identity_verified": False, "provenance_verified": False,
        "strategic_quality_assessed": False,
    }
    assert (panel, analysis) == original


@pytest.mark.parametrize("arm", ["control", "treatment"])
def test_each_arm_mean_drift_is_rejected(arm):
    panel, analysis = _inputs()
    analysis["roots"][0]["seeds"][1][arm]["decision"]["value_means"][0] += 1
    with pytest.raises(ValueError, match="means differ"):
        validate_m9_replay(panel, analysis)


@pytest.mark.parametrize("arm", ["control", "treatment"])
def test_action_or_card_order_drift_is_rejected(arm):
    panel, analysis = _inputs()
    actions = panel["collection"]["captures"][arm]["actions"]
    actions.reverse()
    with pytest.raises(ValueError, match="action order"):
        validate_m9_replay(panel, analysis)

    panel, analysis = _inputs()
    panel["collection"]["captures"][arm]["actions"][0] = ["D7", "D6"]
    # The otherwise equivalent card ordering is not the exact ordered replay.
    with pytest.raises(ValueError, match="action order"):
        validate_m9_replay(panel, analysis)


@pytest.mark.parametrize("field,value", [
    ("fixture_id", "wrong-root"), ("seed", 0), ("fill_seed", 1),
    ("checkpoint_sha256", "b" * 64),
])
def test_panel_binding_fields_are_strict(field, value):
    panel, analysis = _inputs()
    panel[field] = value
    with pytest.raises(ValueError):
        validate_m9_replay(panel, analysis)


@pytest.mark.parametrize("field,value", [
    ("checkpoint_sha256", "b" * 64), ("schema", "other"),
    ("fill_seed", 1), ("seeds", [0, 1, 2, 3]),
])
def test_analysis_binding_fields_are_strict(field, value):
    panel, analysis = _inputs()
    analysis[field] = value
    with pytest.raises(ValueError):
        validate_m9_replay(panel, analysis)


def test_duplicate_matching_root_and_seed_is_rejected():
    panel, analysis = _inputs()
    analysis["roots"].append(copy.deepcopy(analysis["roots"][0]))
    with pytest.raises(ValueError, match="exactly one"):
        validate_m9_replay(panel, analysis)

    panel, analysis = _inputs()
    analysis["roots"][0]["seeds"].append(
        copy.deepcopy(analysis["roots"][0]["seeds"][1]))
    analysis["roots"][0]["seeds"][-1]["fill_seed"] = 9
    with pytest.raises(ValueError):
        validate_m9_replay(panel, analysis)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True,
                                  pytest.param(10 ** 10000, id="huge-int")])
def test_nonfinite_or_boolean_means_are_rejected(bad):
    panel, analysis = _inputs()
    analysis["roots"][0]["seeds"][1]["control"]["decision"]["value_means"][0] = bad
    with pytest.raises(ValueError):
        validate_m9_replay(panel, analysis)


@pytest.mark.parametrize("bad_seed", [True, 1.0, 0])
def test_invalid_or_duplicate_selected_root_seed_refused(bad_seed):
    panel, analysis = _inputs()
    analysis["roots"][0]["seeds"][1]["seed"] = bad_seed
    with pytest.raises(ValueError):
        validate_m9_replay(panel, analysis)


def test_equal_short_mean_lists_are_rejected_against_action_count():
    panel, analysis = _inputs()
    for arm in ("control", "treatment"):
        analysis["roots"][0]["seeds"][1][arm]["decision"]["value_means"] = [1.0]
        panel["collection"]["captures"][arm]["serving_value_means"] = [1.0]
    with pytest.raises(ValueError, match="action count"):
        validate_m9_replay(panel, analysis)


@pytest.mark.parametrize("bad", [True, 63, 65])
def test_world_count_must_be_strict_64(bad):
    panel, analysis = _inputs()
    panel["collection"]["captures"]["control"]["world_count"] = bad
    with pytest.raises(ValueError, match="world_count"):
        validate_m9_replay(panel, analysis)


def test_history_primed_and_unknown_collection_are_rejected():
    panel, analysis = _inputs()
    panel["mode"] = "history-primed"
    with pytest.raises(ValueError):
        validate_m9_replay(panel, analysis)


@pytest.mark.parametrize("field,value", [
    ("mode", "history-primed"), ("seed", 0), ("fill_seed", 1),
    ("world_count", True), ("checkpoint_sha256", "b" * 64),
])
def test_tape_receipt_must_bind_to_panel_declaration(field, value):
    panel, analysis = _inputs()
    panel["tape_receipt"][field] = value
    with pytest.raises(ValueError):
        validate_m9_replay(panel, analysis)
    panel, analysis = _inputs()
    panel["collection"]["schema"] = "fixed-tape-history-primed-panel-v1"
    with pytest.raises(ValueError):
        validate_m9_replay(panel, analysis)


def test_incomplete_decision_and_duplicate_actions_are_rejected():
    panel, analysis = _inputs()
    analysis["roots"][0]["seeds"][1]["control"]["decision"]["work_complete"] = False
    with pytest.raises(ValueError):
        validate_m9_replay(panel, analysis)
    panel, analysis = _inputs()
    panel["collection"]["captures"]["control"]["actions"] = [["D6"], ["D6"]]
    analysis["roots"][0]["seeds"][1]["control"]["decision"]["admitted"] = [["D6"], ["D6"]]
    with pytest.raises(ValueError):
        validate_m9_replay(panel, analysis)

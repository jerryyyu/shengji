from __future__ import annotations

import copy
import itertools
import json
import math

import pytest

from shengji.eval.ballot_full_pool import summarize_full_pool_matrix
from shengji.eval.ballot_matrix import CARD_INDEX
from shengji.eval.ballot_points_selection import summarize_points_selection
from shengji.eval.m9_panel_plan import (
    CHECKPOINT_SHA256,
    EXPECTED_ACTION_COUNTS,
    PRIMARY_ROOT,
    ROOTS,
    build_m9_panel_plan,
)
from shengji.eval.m9_panel_readout import _choice_view, _diagnostic_views, summarize_m9_panels
from shengji.eval.m9_replay_binding import validate_m9_replay
from test_m9_panel_plan import _analysis


CARDS = list(CARD_INDEX)
CONTROL = [["D6"], ["D7"], ["D8"], ["D9"], ["D10"], ["DJ"], ["DQ"], ["DK"]]
TREATMENT = [["H6"], ["H7"], ["H8"], ["H9"], ["H10"], ["HJ"], ["HQ"], ["HK"]]


def _full_actions():
    actions = copy.deepcopy(CONTROL + TREATMENT)
    for left, right in itertools.combinations(CARDS, 2):
        action = [left, right]
        if action not in actions:
            actions.append(action)
        if len(actions) == 712:
            return actions
    raise AssertionError("not enough synthetic legal actions")


def _canonical_key(action):
    return tuple(sorted(action, key=CARD_INDEX.__getitem__))


def _analysis_and_actions(*, multi=False):
    analysis = _analysis()
    actions = _full_actions()
    values = {_canonical_key(action): float(index)
              for index, action in enumerate(actions)}
    for root in analysis["roots"]:
        count = EXPECTED_ACTION_COUNTS[root["id"]]
        control = copy.deepcopy(CONTROL[:count])
        treatment = (copy.deepcopy(TREATMENT[:count]) if root["id"] == PRIMARY_ROOT
                     else copy.deepcopy(control))
        if multi and root["id"] == PRIMARY_ROOT:
            control[0] = [CARDS[1], CARDS[0]]
        for row in root["seeds"]:
            for arm, ballot in (("control", control), ("treatment", treatment)):
                decision = row[arm]["decision"]
                # The plan-only fixture carries an unrelated Infinity sentinel;
                # retained records must instead be strict JSON serializable.
                decision.pop("ignored_matrix_means")
                decision["admitted"] = copy.deepcopy(ballot)
                decision["admitted_indices"] = list(range(100, 100 + len(ballot)))
                decision["selected_index"] = 100 + len(ballot) - 1
                decision["value_means"] = [values[_canonical_key(action)]
                                            for action in ballot]
    return analysis, actions, values


def _capture(actions, values, *, points=True, drift=False):
    matrix = [[values[_canonical_key(action)] for action in actions]
              for _ in range(64)]
    means = [sum(row[column] for row in matrix) / 64
             for column in range(len(actions))]
    if drift:
        means[0] += 1
    point_values = {_canonical_key(action): index % 7
                    for index, action in enumerate(_full_actions())}
    points = [[point_values[_canonical_key(action)] for action in actions]
              for _ in range(64)]
    return {
        "schema": "fixed-tape-same-leaf-capture-v1",
        "actions": copy.deepcopy(actions), "world_count": 64,
        "value_matrix": matrix,
        "signed_trick_points": points if points else [[0] * len(actions) for _ in range(64)],
        "serving_value_means": means,
        "batches": (64 * len(actions) + 127) // 128,
    }


def _records(*, matrix_bad=None, drift=False, points_bad=False,
             cached_bad=False, order_bad=False, multi=False):
    analysis, actions, values = _analysis_and_actions(multi=multi)
    plan = build_m9_panel_plan(analysis)
    records = []
    for index, job in enumerate(plan):
        if order_bad and index == 1:
            job = copy.deepcopy(plan[0])
        panel_actions = (copy.deepcopy(actions) if job["fixture_id"] == PRIMARY_ROOT
                         else copy.deepcopy(job["control_ballot"]))
        full = _capture(panel_actions, values,
                        drift=drift and index == 0,
                        points=not points_bad)
        if matrix_bad and index == 0:
            full["value_matrix"] = matrix_bad
        captures = {"full_pool": full}
        for arm in ("control", "treatment"):
            ballot = job[f"{arm}_ballot"]
            captures[arm] = _capture(ballot, values, points=not points_bad)
        shared = summarize_full_pool_matrix(
            panel_actions, job["control_ballot"], job["treatment_ballot"],
            full["value_matrix"])
        if cached_bad and index == 0:
            shared = copy.deepcopy(shared)
            shared["action_count"] += 1
        if job["mode"] == "fresh-root":
            collection = {"schema": "fixed-tape-three-pass-panel-v1",
                           "captures": captures,
                           "shared_matrix_summary": shared}
            indices = {_canonical_key(action): i
                       for i, action in enumerate(panel_actions)}
            replays, shared_replays, deltas = {}, {}, {}
            for arm in ("control", "treatment"):
                ballot = job[f"{arm}_ballot"]
                capture = captures[arm]
                columns = [indices[_canonical_key(action)] for action in ballot]
                shared_means = [full["serving_value_means"][i] for i in columns]
                replays[arm] = summarize_points_selection(
                    ballot, capture["serving_value_means"], capture["signed_trick_points"])
                shared_replays[arm] = summarize_points_selection(
                    ballot, shared_means,
                    [[row[i] for i in columns] for row in full["signed_trick_points"]])
                deltas[arm] = [value - common for value, common in
                              zip(capture["serving_value_means"], shared_means)]
            collection.update(
                ballot_schedule_points_replay=replays,
                shared_matrix_points_replay=shared_replays,
                ballot_minus_full_schedule_value_deltas=deltas)
        else:
            collection = {
                "schema": "fixed-tape-history-primed-panel-v1",
                "full_pool_capture": full,
                "shared_matrix_summary": shared,
                "union_is_projection": True,
                "saved_ballots_generated_under_this_sampler": False,
            }
        panel = {
            "schema": "public-fixture-panel-v1",
            "fixture_id": job["fixture_id"], "mode": job["mode"],
            "seed": job["seed"], "fill_seed": 0,
            "checkpoint_sha256": CHECKPOINT_SHA256,
            "effective": {"worlds": 64, "batch_size": 128},
            "legal_count": 712 if job["fixture_id"] == PRIMARY_ROOT else job["expected_legal_count"],
            "actions": panel_actions, "worlds": [[[[], [], [], []], []] for _ in range(64)],
            "collection": collection,
        }
        panel["tape_receipt"] = {
            "schema": "public-refusal-tape-v1", "mode": job["mode"],
            "seed": job["seed"], "fill_seed": 0, "world_count": 64,
            "checkpoint_sha256": CHECKPOINT_SHA256,
            "ledger_receipt": {"mode": job["mode"]},
        }
        replay = validate_m9_replay(panel, analysis) if job["mode"] == "fresh-root" else None
        records.append({"job": copy.deepcopy(job), "panel": panel,
                        "replay_consistency": replay,
                        "validation_status": "passed", "replay_failure": None,
                        "ledger_cadence": ("fresh-root" if job["mode"] == "fresh-root"
                                           else "single-seat-actor-turns")})
    return analysis, records


def test_good_fifteen_panel_readout_and_input_immutability():
    analysis, records = _records()
    original = copy.deepcopy((analysis, records))
    report = summarize_m9_panels(analysis, records)
    assert report["schema"] == "m9-panel-readout-v1"
    assert report["panel_count"] == 15
    assert len(report["rows"]) == 15
    assert report["rows"][0]["mode"] == "fresh-root"
    assert report["rows"][3]["mode"] == "history-primed"
    assert report["rows"][0]["ballot_minus_full_schedule_value_deltas"] is not None
    assert report["rows"][3]["ballot_minus_full_schedule_value_deltas"] is None
    assert report["rows"][0]["replay_consistency"]["schema"] == "m9-replay-consistency-v1"
    assert report["rows"][3]["replay_consistency"] is None
    assert report["provenance_verified"] is False
    assert report["strategic_quality_assessed"] is False
    assert report["causal_mechanism_assessed"] is False
    assert (analysis, records) == original


def test_multi_card_membership_uses_canonical_cards_but_preserves_capture_order():
    analysis, records = _records(multi=True)
    report = summarize_m9_panels(analysis, records)
    assert report["panel_count"] == 15


@pytest.mark.parametrize("field", [
    "ballot_schedule_points_replay", "shared_matrix_points_replay",
    "ballot_minus_full_schedule_value_deltas",
])
@pytest.mark.parametrize("mutation", ["missing", "garbage", "nested_bool"])
def test_cached_fresh_derivatives_are_recomputed(field, mutation):
    analysis, records = _records()
    # Exercise the persisted JSON representation, not Python-only tuple shapes.
    analysis, records = json.loads(json.dumps([analysis, records], allow_nan=False))
    collection = records[0]["panel"]["collection"]
    if mutation == "missing":
        del collection[field]
    elif mutation == "garbage":
        collection[field] = "garbage"
    elif field == "ballot_minus_full_schedule_value_deltas":
        assert collection[field]["control"][0] == 0.0
        collection[field]["control"][0] = False
    else:
        assert collection[field]["control"]["near_count"] == 1
        collection[field]["control"]["near_count"] = True
    with pytest.raises(ValueError, match=f"cached {field} differs"):
        summarize_m9_panels(analysis, records)


def test_good_json_roundtrip_and_explicit_replay_failure_key():
    analysis, records = _records(multi=True)
    expected = summarize_m9_panels(analysis, records)
    analysis, records = json.loads(json.dumps([analysis, records], allow_nan=False))
    assert summarize_m9_panels(analysis, records) == expected
    del records[0]["replay_failure"]
    with pytest.raises(ValueError, match="explicitly contain replay_failure"):
        summarize_m9_panels(analysis, records)


def test_views_map_saved_legal_indices_and_label_schedules():
    analysis, records = _records()
    report = summarize_m9_panels(analysis, records)
    fresh = report["rows"][0]["diagnostic_views"]
    assert fresh["saved_fresh_choices"]["control"] == ["DK"]
    assert fresh["saved_control_choice_absent_from_treatment_ballot"] is True
    assert fresh["replayed_control_choice_absent_from_treatment_ballot"] is True
    assert fresh["own_ballot_schedule"]["control"]["raw_argmax_action"] == ["DK"]
    assert fresh["own_ballot_schedule"]["control"]["near_actions"] == [["DK"]]
    assert fresh["own_ballot_schedule"]["control"]["near_point_sums"] == [0]
    assert fresh["tie_break_alone_explains_choice_change"] is None
    small = report["rows"][6]["diagnostic_views"]
    assert small["small_root_comparison"]["raw_argmax_action"] == ["D9"]
    assert small["raw_argmax_matches_saved_fresh_choice"] == dict(control=True, treatment=True)
    assert report["rows"][6]["shared_summary_reduction"] == "math.fsum"
    assert "post-selection" in report["rows"][6]["shared_summary_selected_difference_se_scope"]


@pytest.mark.parametrize("points,unresolved", [([4, 4, 9], True), ([4, 8, 9], False)])
def test_primed_any_near_points_tie_is_unresolved_even_below_winner(points, unresolved):
    view = _choice_view([["D6"], ["D7"], ["D8"]], [0.0, 0.01, 0.02],
                        [points] * 64, ordered_ballot=False)
    assert view["near_actions"] == [["D6"], ["D7"], ["D8"]]
    assert view["near_point_sums"] == [p * 64 for p in points]
    assert view["order_dependent"] is unresolved
    assert view["points_choice_action"] == (None if unresolved else ["D8"])
    assert view["points_replay"] is None


def test_ordered_ballot_can_resolve_points_tie_but_primed_cannot():
    actions, means, points = [["D6"], ["D7"]], [0.0, 0.0], [[5, 5]] * 64
    own = _choice_view(actions, means, points, ordered_ballot=True)
    primed = _choice_view(actions, means, points, ordered_ballot=False)
    assert own["points_choice_action"] == ["D6"]
    assert own["points_replay"]["selected_index"] == 0
    assert primed["points_choice_action"] is None
    assert primed["raw_argmax_actions"] == actions


def test_view_builder_does_not_substitute_full_schedule_for_own_schedule():
    analysis, records = _records()
    record = records[0]
    # Isolate view wiring: capture consistency is tested separately above.
    capture = record["panel"]["collection"]["captures"]["control"]
    capture["serving_value_means"][0] = 1000.0
    view = _diagnostic_views(analysis, record["job"], record["panel"])
    assert view["own_ballot_schedule"]["control"]["raw_argmax_action"] == ["D6"]
    assert view["full_pool_schedule_ballot_projection"]["control"]["raw_argmax_action"] == ["DK"]


def test_primed_report_preserves_unresolved_choice_comparison():
    analysis, records = _records()
    record = records[6]  # first partner root, four-action primed full pool
    panel = record["panel"]
    collection = panel["collection"]
    capture = collection["full_pool_capture"]
    capture["value_matrix"] = [[0.0] * 4 for _ in range(64)]
    capture["serving_value_means"] = [0.0] * 4
    capture["signed_trick_points"] = [[5] * 4 for _ in range(64)]
    collection["shared_matrix_summary"] = summarize_full_pool_matrix(
        panel["actions"], record["job"]["control_ballot"],
        record["job"]["treatment_ballot"], capture["value_matrix"])
    view = summarize_m9_panels(analysis, records)["rows"][6]["diagnostic_views"]
    assert view["small_root_comparison"]["order_dependent"] is True
    assert view["small_root_comparison"]["points_choice_action"] is None
    assert view["points_choice_matches_saved_fresh_choice"] == dict(control=None, treatment=None)
    assert view["raw_argmax_matches_saved_fresh_choice"] == dict(control=False, treatment=False)
    assert view["small_root_comparison"]["raw_argmax_actions"] == panel["actions"]


@pytest.mark.parametrize("mutation", ["missing", "bool", "duplicate", "out_of_ballot"])
def test_saved_choice_join_refuses_invalid_indices(mutation):
    analysis, records = _records()
    decision = analysis["roots"][0]["seeds"][0]["control"]["decision"]
    if mutation == "missing":
        del decision["admitted_indices"]
    elif mutation == "bool":
        decision["selected_index"] = True
    elif mutation == "duplicate":
        decision["admitted_indices"][0] = decision["admitted_indices"][1]
    else:
        decision["selected_index"] = 0
    with pytest.raises(ValueError, match="saved control choice/index mapping invalid"):
        summarize_m9_panels(analysis, records)


def test_primed_tape_receipt_is_also_bound():
    analysis, records = _records()
    records[3]["panel"]["tape_receipt"]["mode"] = "fresh-root"
    with pytest.raises(ValueError, match="tape receipt mode"):
        summarize_m9_panels(analysis, records)


def test_malformed_world_structure_is_rejected_without_reconstructing_it():
    analysis, records = _records()
    records[3]["panel"]["worlds"][0] = None
    with pytest.raises(ValueError, match="world must contain"):
        summarize_m9_panels(analysis, records)


@pytest.mark.parametrize("mutation", ["missing", "reordered", "duplicate", "rejected"])
def test_record_population_and_status_are_strict(mutation):
    analysis, records = _records()
    if mutation == "missing":
        records.pop()
    elif mutation == "reordered":
        records[0], records[1] = records[1], records[0]
    elif mutation == "duplicate":
        records[1] = copy.deepcopy(records[0])
    else:
        records[0]["validation_status"] = "failed"
    pattern = {"missing": "exactly 15", "reordered": "job differs",
               "duplicate": "job differs", "rejected": "passed validation"}[mutation]
    with pytest.raises(ValueError, match=pattern):
        summarize_m9_panels(analysis, records)


@pytest.mark.parametrize("field,value", [("worlds", True), ("batch_size", True)])
def test_boolean_panel_counts_are_rejected(field, value):
    analysis, records = _records()
    records[0]["panel"]["effective"][field] = value
    with pytest.raises(ValueError, match="worlds|batch_size"):
        summarize_m9_panels(analysis, records)


@pytest.mark.parametrize("bad", ["shape", "nonfinite"])
def test_matrix_shape_and_finiteness_are_rejected(bad):
    analysis, records = _records()
    if bad == "shape":
        records[0]["panel"]["collection"]["captures"]["full_pool"]["value_matrix"] = [[0.0]]
    else:
        records[0]["panel"]["collection"]["captures"]["full_pool"]["value_matrix"][0][0] = float("nan")
    with pytest.raises(ValueError, match="64 rows|finite plain number"):
        summarize_m9_panels(analysis, records)


def test_serving_means_cached_summary_replay_and_points_are_checked():
    analysis, records = _records(drift=True)
    with pytest.raises(ValueError, match="means differ|drifted"):
        summarize_m9_panels(analysis, records)
    analysis, records = _records(cached_bad=True)
    with pytest.raises(ValueError, match="cached"):
        summarize_m9_panels(analysis, records)
    analysis, records = _records(points_bad=True)
    records[0]["panel"]["collection"]["captures"]["control"]["signed_trick_points"][0][0] += 1
    with pytest.raises(ValueError, match="signed trick points"):
        summarize_m9_panels(analysis, records)

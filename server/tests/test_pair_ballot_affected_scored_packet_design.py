from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pair_ballot_affected_scored_packet_design as DESIGN  # noqa: E402


AUTHENTICATE_REVIEW_CHAIN = DESIGN._authenticate_review_chain
AUTHENTICATE_PROSE_CONTEXT = DESIGN._authenticate_capacity_prose_context

EXPECTED_LANES = (
    (0, 51, 24, 27, 44, 6, 1, 149_940,
     "e6757756498b8ade7e35d66c55a7974a4ce83073f75e3cb1246fdb39cc0547a8"),
    (1, 59, 35, 24, 51, 7, 1, 173_460,
     "a191b5e861d6a6a492a15c51878cffa46121bc9d24a268f2cc4ecafdc3148cc9"),
    (2, 60, 23, 37, 53, 3, 4, 176_400,
     "9c8c8944f112fbe723ff4d92227f8527a419094a61103215a8ad575a0893cb0e"),
    (3, 84, 39, 45, 75, 9, 0, 246_960,
     "9aa037a427f56e1de8305be92a6d4ef74d567d476d77a0e81b9c04c13164d025"),
    (4, 58, 35, 23, 52, 4, 2, 170_520,
     "9cbdff9be1368ba92c94b77418808539ef0a6dadfd6072e6a5f68f9d35ac0d05"),
    (5, 74, 28, 46, 67, 3, 4, 217_560,
     "88437b2f8b972a9f83c6abdf7890aed9547219e1e335a844e7fefb2d7a344873"),
    (6, 61, 32, 29, 50, 8, 3, 179_340,
     "622e7365db88665eee36707866d8c4c60efa8eb915ae8eb857d4c0e4293bf57b"),
    (7, 47, 23, 24, 36, 8, 3, 138_180,
     "c256606d12d047c07dffd8dd2170649477eda60b99d27997970b4f5b2112290d"),
    (8, 56, 28, 28, 48, 6, 2, 164_640,
     "761fd15afe9b37198eabd7c0252e5749f4d8350b93e618bae4841b67b6bdaf97"),
    (9, 50, 24, 26, 44, 2, 4, 147_000,
     "510f74ca90c1b630b5e98f4ef13c08fad5f0f80bb7dde01a4c6d9549d7cd3a2b"),
    (10, 71, 36, 35, 64, 5, 2, 208_740,
     "ebfccf9fa0d84a75090474e9e25793343c5d62064fb52638bd7d9f3a7ad6494f"),
    (11, 80, 41, 39, 69, 9, 2, 235_200,
     "32dec86631f71d60fa08549a3b9bade2a5ce8ddced55859057371ccf42e34558"),
    (12, 77, 45, 32, 69, 6, 2, 226_380,
     "d9cbfbf46604faed5cbcf8e84b60e61fae392721350c00f4dde2664fa39d08d6"),
    (13, 60, 30, 30, 51, 9, 0, 176_400,
     "41d2ea14918e3c6072ea012bf45bab7b6b5994cb0a3b210ca59f7a47188695b8"),
    (14, 68, 31, 37, 60, 7, 1, 199_920,
     "2fa70c0b8a068b05b804eaa93e7c6e08fe2d9b2b291b0e1ab981c55f968de570"),
    (15, 68, 38, 30, 63, 4, 1, 199_920,
     "e4c6f6eb8f8ee1d21f967eaa8143b2a3734f88b17e2f8de88b32016866c722fa"),
)
EXPECTED_LANE_MANIFEST_SHA256 = (
    "75e1ca0fd756083179b3e1943b528063ce53a2ddaab8a44568b498ccf48a6b37")


@pytest.fixture(scope="module")
def canonical_review_chain() -> dict:
    return AUTHENTICATE_REVIEW_CHAIN()


@pytest.fixture(scope="module")
def canonical_prose_context() -> dict:
    return AUTHENTICATE_PROSE_CONTEXT()


@pytest.fixture(autouse=True)
def stable_review_chain(
        monkeypatch, canonical_review_chain, canonical_prose_context):
    monkeypatch.setattr(
        DESIGN, "_authenticate_review_chain",
        lambda: copy.deepcopy(canonical_review_chain))
    monkeypatch.setattr(
        DESIGN, "_authenticate_capacity_prose_context",
        lambda: copy.deepcopy(canonical_prose_context))


@pytest.fixture
def design() -> dict:
    return DESIGN.build_design()


def _rehash(value: dict) -> None:
    body = dict(value)
    body.pop("design_sha256", None)
    value["design_sha256"] = DESIGN._sha256_bytes(DESIGN._canonical(body))


def test_exact_raw_review_chain_is_authenticated_once(canonical_review_chain):
    assert set(canonical_review_chain) == {
        "source_population", "artifact_evaluator", "capacity_design",
        "capacity_packet", "capacity_result",
    }
    assert canonical_review_chain["source_population"]["commit"] \
        == DESIGN.SOURCE_POPULATION_REVIEW_COMMIT
    assert canonical_review_chain["artifact_evaluator"]["commit"] \
        == DESIGN.ARTIFACT_EVALUATOR_REVIEW_COMMIT
    assert canonical_review_chain["capacity_design"]["commit"] \
        == DESIGN.CAPACITY_DESIGN_REVIEW_COMMIT
    assert canonical_review_chain["capacity_packet"]["commit"] \
        == DESIGN.CAPACITY_PACKET_REVIEW_COMMIT
    result = canonical_review_chain["capacity_result"]
    assert result["commit"] == DESIGN.CAPACITY_RESULT_REVIEW_COMMIT
    assert result["parent_commit"] == DESIGN.CAPACITY_RESULT_REVIEW_PARENT
    assert result["claim"] == DESIGN._capacity_result_claim()
    assert result["claim"]["scored_packet_design_authorized"] is True
    assert result["claim"]["scored_packet_freeze_authorized"] is False
    assert result["claim"]["scored_packet_run_authorized"] is False


def test_capacity_numbers_bind_non_authority_prose_context(
        canonical_prose_context):
    assert canonical_prose_context == {
        "commit": DESIGN.CAPACITY_PROSE_REVIEW_COMMIT,
        "parent_commit": DESIGN.CAPACITY_PROSE_REVIEW_PARENT,
        "canonical_ref": DESIGN.CANONICAL_REVIEW_REF,
        "ledger_blob_sha256":
            canonical_prose_context["ledger_blob_sha256"],
        "authority": False,
        "use": "public independently reproduced capacity numbers only",
    }
    assert DESIGN._is_hex(
        canonical_prose_context["ledger_blob_sha256"], 64)


def test_review_marker_claim_substitution_refuses(monkeypatch):
    original = DESIGN._capacity_result_claim

    def changed_claim():
        claim = original()
        claim["scored_packet_run_authorized"] = True
        return claim

    monkeypatch.setattr(DESIGN, "_capacity_result_claim", changed_claim)
    with pytest.raises(
            DESIGN.ScoredPacketDesignRefused,
            match="marker is not exactly once"):
        AUTHENTICATE_REVIEW_CHAIN()


def test_review_commit_must_be_ancestor_of_canonical_ref():
    canonical_ref = DESIGN.CAPACITY_RESULT_REVIEW_PARENT
    ancestor = DESIGN.subprocess.run(
        [
            "git", "merge-base", "--is-ancestor",
            DESIGN.CAPACITY_RESULT_REVIEW_COMMIT, canonical_ref,
        ],
        cwd=DESIGN.REPO, capture_output=True,
    )
    assert ancestor.returncode != 0

    with pytest.raises(
            DESIGN.ScoredPacketDesignRefused,
            match=(
                rf"review {DESIGN.CAPACITY_RESULT_REVIEW_COMMIT[:8]} "
                r"is not on canonical main")):
        DESIGN._canonical_review_record(
            commit=DESIGN.CAPACITY_RESULT_REVIEW_COMMIT,
            parent=DESIGN.CAPACITY_RESULT_REVIEW_PARENT,
            prefix=DESIGN.CAPACITY_RESULT_REVIEW_PREFIX,
            expected=DESIGN._capacity_result_claim(),
            canonical_ref=canonical_ref)


def test_later_duplicate_column_one_marker_refuses(monkeypatch):
    original = DESIGN._git_bytes
    marker = (DESIGN.CAPACITY_RESULT_REVIEW_PREFIX.encode()
              + DESIGN._canonical(DESIGN._capacity_result_claim()))

    def duplicated(*args):
        value = original(*args)
        if args == (
                "show",
                f"{DESIGN.CANONICAL_REVIEW_REF}:{DESIGN.REVIEW_LEDGER}"):
            return value + marker
        return value

    monkeypatch.setattr(DESIGN, "_git_bytes", duplicated)
    with pytest.raises(
            DESIGN.ScoredPacketDesignRefused,
            match="marker is not exactly once"):
        DESIGN._canonical_review_record(
            commit=DESIGN.CAPACITY_RESULT_REVIEW_COMMIT,
            parent=DESIGN.CAPACITY_RESULT_REVIEW_PARENT,
            prefix=DESIGN.CAPACITY_RESULT_REVIEW_PREFIX,
            expected=DESIGN._capacity_result_claim())


@pytest.mark.parametrize("mutation", ("delete", "rewrite"))
def test_review_commit_must_preserve_parent_ledger_bytes(
        monkeypatch, mutation):
    original = DESIGN._git_bytes
    parent_args = (
        "show",
        f"{DESIGN.CAPACITY_RESULT_REVIEW_PARENT}:{DESIGN.REVIEW_LEDGER}")
    commit_args = (
        "show",
        f"{DESIGN.CAPACITY_RESULT_REVIEW_COMMIT}:{DESIGN.REVIEW_LEDGER}")
    parent = original(*parent_args)

    def drifted(*args):
        value = original(*args)
        if args == commit_args:
            if mutation == "delete":
                return value[:100] + value[101:]
            replacement = b"X" if value[100:101] != b"X" else b"Y"
            return value[:100] + replacement + value[101:]
        return value

    assert len(parent) > 101
    monkeypatch.setattr(DESIGN, "_git_bytes", drifted)
    with pytest.raises(
            DESIGN.ScoredPacketDesignRefused, match="not append-only"):
        DESIGN._canonical_review_record(
            commit=DESIGN.CAPACITY_RESULT_REVIEW_COMMIT,
            parent=DESIGN.CAPACITY_RESULT_REVIEW_PARENT,
            prefix=DESIGN.CAPACITY_RESULT_REVIEW_PREFIX,
            expected=DESIGN._capacity_result_claim())


def test_canonical_tip_must_preserve_review_commit_ledger_bytes(monkeypatch):
    original = DESIGN._git_bytes
    canonical_args = (
        "show", f"{DESIGN.CANONICAL_REVIEW_REF}:{DESIGN.REVIEW_LEDGER}")

    def rewritten(*args):
        value = original(*args)
        if args == canonical_args:
            replacement = b"X" if value[100:101] != b"X" else b"Y"
            return value[:100] + replacement + value[101:]
        return value

    monkeypatch.setattr(DESIGN, "_git_bytes", rewritten)
    with pytest.raises(
            DESIGN.ScoredPacketDesignRefused, match="not append-only"):
        DESIGN._canonical_review_record(
            commit=DESIGN.CAPACITY_RESULT_REVIEW_COMMIT,
            parent=DESIGN.CAPACITY_RESULT_REVIEW_PARENT,
            prefix=DESIGN.CAPACITY_RESULT_REVIEW_PREFIX,
            expected=DESIGN._capacity_result_claim())


def test_later_different_marker_with_same_authority_name_refuses(monkeypatch):
    original = DESIGN._git_bytes
    claim = DESIGN._capacity_result_claim()
    claim["verdict"] = "HOLD"
    later = DESIGN.CAPACITY_RESULT_REVIEW_PREFIX.encode() \
        + DESIGN._canonical(claim)

    def appended(*args):
        value = original(*args)
        if args == (
                "show",
                f"{DESIGN.CANONICAL_REVIEW_REF}:{DESIGN.REVIEW_LEDGER}"):
            return value + later
        return value

    monkeypatch.setattr(DESIGN, "_git_bytes", appended)
    with pytest.raises(
            DESIGN.ScoredPacketDesignRefused,
            match="marker is not exactly once"):
        DESIGN._canonical_review_record(
            commit=DESIGN.CAPACITY_RESULT_REVIEW_COMMIT,
            parent=DESIGN.CAPACITY_RESULT_REVIEW_PARENT,
            prefix=DESIGN.CAPACITY_RESULT_REVIEW_PREFIX,
            expected=DESIGN._capacity_result_claim())


@pytest.mark.parametrize(("target", "error"), (
    ("actor", "actor drift"),
    ("session", "session provenance missing"),
    ("files", "changed files beyond the ledger"),
))
def test_review_actor_session_and_file_scope_drift_refuse(
        monkeypatch, target, error):
    original = DESIGN._git

    def drifted(*args):
        if (target == "actor" and args == (
                "show", "-s", "--format=%an",
                DESIGN.CAPACITY_RESULT_REVIEW_COMMIT)):
            return "not-Claude"
        if (target == "session" and args == (
                "show", "-s", "--format=%B",
                DESIGN.CAPACITY_RESULT_REVIEW_COMMIT)):
            return "review without session provenance"
        if target == "files" and args == (
                "diff-tree", "--no-commit-id", "--name-only", "-r",
                DESIGN.CAPACITY_RESULT_REVIEW_COMMIT):
            return f"{DESIGN.REVIEW_LEDGER}\nother.txt"
        return original(*args)

    monkeypatch.setattr(DESIGN, "_git", drifted)
    with pytest.raises(DESIGN.ScoredPacketDesignRefused, match=error):
        DESIGN._canonical_review_record(
            commit=DESIGN.CAPACITY_RESULT_REVIEW_COMMIT,
            parent=DESIGN.CAPACITY_RESULT_REVIEW_PARENT,
            prefix=DESIGN.CAPACITY_RESULT_REVIEW_PREFIX,
            expected=DESIGN._capacity_result_claim())


def test_reviewed_source_bytes_and_chain_cross_bind(design):
    sources = design["review_chain"]["reviewed_sources"]
    records = design["review_chain"]["records"]
    assert sources == DESIGN.SOURCE_SHA256S
    result = records["capacity_result"]["claim"]
    expected_dependencies = dict(DESIGN.SOURCE_SHA256S)
    expected_dependencies.pop(
        "pair_ballot_affected_capacity_result_review.py")
    assert result["reviewer_dependency_sha256s"] == expected_dependencies
    assert result["result_reviewer_script_sha256"] \
        == sources["pair_ballot_affected_capacity_result_review.py"]
    assert design["frozen_inputs"]["population"]["file_sha256"] \
        == records["source_population"]["claim"][
            "scratch_population_sha256"]
    assert design["frozen_inputs"]["population"]["artifact_sha256"] \
        == records["artifact_evaluator"]["claim"][
            "formal_artifact_sha256"]
    assert design["frozen_inputs"]["capacity_design"]["file_sha256"] \
        == records["capacity_design"]["claim"]["design_file_sha256"]
    assert design["frozen_inputs"]["capacity_design"]["internal_sha256"] \
        == records["capacity_design"]["claim"]["design_internal_sha256"]
    assert design["frozen_inputs"]["capacity_evidence"] == {
        "implementation_git": DESIGN.CAPACITY_IMPLEMENTATION_GIT,
        "packet_sha256": DESIGN.CAPACITY_PACKET_SHA256,
        "packet_internal_sha256": DESIGN.CAPACITY_PACKET_INTERNAL_SHA256,
        "admission_sha256": DESIGN.CAPACITY_ADMISSION_SHA256,
        "result_sha256": DESIGN.CAPACITY_RESULT_SHA256,
        "result_internal_sha256": DESIGN.CAPACITY_RESULT_INTERNAL_SHA256,
        "result_review_commit": DESIGN.CAPACITY_RESULT_REVIEW_COMMIT,
        "score_free_capacity_pass": True,
    }


def test_full_dev_calib_selection_and_every_lane_are_fixed(design):
    assert design["selection"] == {
        "rule": "all frozen DEV and CALIB rows; no outcome filtering",
        "splits": ["dev", "calib"],
        "report_permitted": False,
        "states": 1_024,
        "states_by_split": {"calib": 512, "dev": 512},
        "states_by_band": {"early": 896, "late": 32, "mid": 96},
        "states_by_role": {"attacker": 1, "defender": 1_023},
        "unique_deal_clusters": 991,
        "identity_membership_sha256": DESIGN.IDENTITY_MEMBERSHIP_SHA256,
        "selection_sha256": DESIGN.SELECTION_SHA256,
        "no_replacement_retry_or_extension": True,
    }
    schedule = design["schedule"]
    assert schedule["logical_lanes"] == 16
    observed_lanes = tuple((
        lane["lane_index"], lane["state_count"],
        lane["states_by_split"]["calib"],
        lane["states_by_split"]["dev"],
        lane["states_by_band"]["early"],
        lane["states_by_band"]["mid"],
        lane["states_by_band"].get("late", 0),
        lane["max_candidate_world_rollouts"], lane["selection_sha256"],
    ) for lane in schedule["lanes"])
    assert observed_lanes == EXPECTED_LANES
    assert schedule["lane_manifest_sha256"] \
        == EXPECTED_LANE_MANIFEST_SHA256
    assert schedule["lane_manifest_provenance"] \
        == "exact reviewed capacity design file be21b547...f439"
    assert [lane["lane_index"] for lane in schedule["lanes"]] \
        == list(range(16))
    assert [lane["state_count"] for lane in schedule["lanes"]] == [
        51, 59, 60, 84, 58, 74, 61, 47,
        56, 50, 71, 80, 77, 60, 68, 68,
    ]
    assert sum(lane["state_count"] for lane in schedule["lanes"]) == 1_024
    assert sum(lane["max_candidate_world_rollouts"]
               for lane in schedule["lanes"]) == 3_010_560
    assert schedule["minimum_states_in_lane"] == 47
    assert schedule["maximum_states_in_lane"] == 84
    assert schedule["scored_shard_outputs"] == 32
    assert schedule[
        "lane_manifest_bound_to_exact_reviewed_capacity_design"] is True


def test_lane_arithmetic_refuses_rehashed_global_or_per_lane_drift(
        monkeypatch):
    original_lanes = copy.deepcopy(DESIGN.LANES)
    lanes = copy.deepcopy(original_lanes)
    lanes[0]["states_by_split"] = {"calib": 25, "dev": 26}
    monkeypatch.setattr(DESIGN, "LANES", tuple(lanes))
    monkeypatch.setattr(
        DESIGN, "LANE_MANIFEST_SHA256",
        DESIGN._sha256_bytes(DESIGN._canonical(list(lanes))))
    with pytest.raises(
            DESIGN.ScoredPacketDesignRefused,
            match="fixed design arithmetic drift"):
        DESIGN.build_design()

    lanes = copy.deepcopy(original_lanes)
    lanes[0]["max_candidate_world_rollouts"] += 1
    lanes[1]["max_candidate_world_rollouts"] -= 1
    monkeypatch.setattr(DESIGN, "LANES", tuple(lanes))
    monkeypatch.setattr(
        DESIGN, "LANE_MANIFEST_SHA256",
        DESIGN._sha256_bytes(DESIGN._canonical(list(lanes))))
    with pytest.raises(
            DESIGN.ScoredPacketDesignRefused,
            match="fixed design arithmetic drift"):
        DESIGN.build_design()


def test_exact_n30_r300_work_and_common_world_semantics(design):
    work = design["scored_work"]
    assert work["ballot_width"] == 14
    assert work["selection_worlds_per_candidate"] == 30
    assert work["policy_report_lcb_worlds"] == 300
    assert work["external_common_worlds"] == 300
    assert work["complete_policy_rollouts_per_arm"] == 1_020
    assert work["max_candidate_world_rollouts_per_state"] == 2_940
    assert work["max_candidate_world_rollouts_total"] == 3_010_560
    assert work["same_policy_root_seed_for_current_and_retained"] is True
    assert work[
        "fresh_common_external_world_draw_for_all_distinct_actions"] is True
    assert work["paired_external_action_utilities"] is True
    assert work[
        "policy_report_lcb_is_not_source_REPORT_split_access"] is True


def test_primary_is_combined_defender_only_and_split_results_are_diagnostics(
        design):
    estimands = design["estimands"]
    assert estimands["primary"] \
        == "defender_retained_policy_minus_current"
    assert estimands["secondary"] \
        == "defender_best_inserted_pair_minus_current"
    assert estimands["primary_population"] \
        == "combined DEV+CALIB defender rows"
    assert estimands["primary_row_filter"] == "role == defender"
    assert estimands["defender_rows"] == 1_023
    assert estimands["defender_deal_clusters"] == 990
    assert estimands["attacker_rows"] == 1
    assert estimands["attacker_use"] == "descriptive case study only"
    assert estimands["combined_dev_calib_primary"] is True
    assert estimands["split_results_are_diagnostics"] is True
    assert estimands["band_weights"] == DESIGN.BAND_WEIGHTS
    assert estimands["exact_natural_decision_estimand"] is False
    assert estimands["exact_whole_round_estimand"] is False
    assert estimands["confirmatory_claim"] is False


def test_source_headroom_is_not_conflated_with_selector_exploitation(design):
    estimands = design["estimands"]
    routing = design["routing"]
    assert estimands[
        "policy_selection_neutral_does_not_imply_source_failure"] is True
    assert "selector not exploiting" in routing[
        "source_positive_policy_nonpositive"]
    assert "audit evictions" in routing[
        "policy_positive_source_nonpositive"]
    assert "contextual pair source" in routing["both_nonpositive"]
    assert routing["route_is_exploration_only"] is True
    assert routing["route_cannot_authorize_more_scored_work"] is True


def test_smartbot_dose_is_not_relabelled_live_champion_or_whole_game(design):
    dose = design["natural_dose_boundary"]
    assert dose["source_trajectory_policy"] == "smart"
    assert dose["capture_deals"] == 12_000_000
    assert dose["search_eligible_omission_events"] == 146_112
    assert dose["events_per_captured_smartbot_deal"] == 0.012176
    assert dose["is_live_champion_dose"] is False
    assert dose["selected_role_mix_is_natural_dose"] is False
    assert dose["live_champion_role_specific_dose_available"] is False
    census = dose["future_champion_trajectory_census"]
    assert census[
        "required_before_whole_game_or_value_for_compute_claim"] is True
    assert census["exact_policy_identity_required"] == "mc-s0-report-lcb"
    assert census["counts_required_by_role"] == ["attacker", "defender"]
    assert census["counts_required_by_band"] == ["early", "mid", "late"]
    assert census["included_in_this_scored_packet"] is False
    assert census["implementation_authorized"] is False
    assert census["execution_authorized"] is False


def test_capacity_values_are_runtime_specific_not_economic_utility(design):
    capacity = design["capacity_and_economics"]
    assert capacity["projected_fleet_hours"] \
        == 1.0498934074073278
    assert capacity["max_fleet_hours"] == 64.0
    assert capacity["projected_worst_lane_hours"] \
        == 0.0877279930623274
    assert capacity[
        "reviewed_worst_lane_is_max_of_16_lane_projections"] is True
    assert capacity["average_lane_projection_permitted"] is False
    assert capacity["max_lane_wall_hours"] == 4.0
    assert capacity["capacity_is_not_current_constraint"] is True
    assert capacity["exact_runtime_and_result_specific"] is True
    assert capacity["numeric_summary_provenance_commit"] \
        == DESIGN.CAPACITY_PROSE_REVIEW_COMMIT
    assert capacity[
        "numeric_summary_is_prose_context_not_execution_authority"] is True
    assert capacity[
        "projected_fleet_hours_are_not_billed_host_hours"] is True
    assert capacity["currency_or_host_price_claim"] is False
    assert capacity["utility_per_compute_claim"] is False
    assert capacity["whole_game_economics_claim"] is False
    assert capacity[
        "natural_dose_required_before_value_for_compute_claim"] is True


def test_future_controller_is_only_a_freeze_specification(design):
    future = design["future_controller_freeze"]
    assert future["status"] \
        == "specification only; controller not implemented"
    assert future["run_id"] == DESIGN.FUTURE_RUN_ID
    assert future["packet_schema"] == DESIGN.FUTURE_PACKET_SCHEMA
    assert future["independent_design_source_review_required"] is True
    assert future[
        "packet_must_bind_reviewed_design_source_git_and_sha256"] is True
    assert future[
        "packet_must_reconstruct_population_design_and_all_16_lanes"] is True
    assert future[
        "packet_must_bind_reviewed_per_lane_projection_vector"] is True
    assert future["average_lane_projection_permitted"] is False
    assert future[
        "dependency_source_bytes_authenticated_before_import"] is True
    assert future["preloaded_pair_dependency_names_refuse"] is True
    assert future[
        "evidence_reads_require_regular_unlinked_no_partial_single_inode"] \
        is True
    assert future["evidence_bytes_unchanged_across_reconstruction"] is True
    assert future["packet_must_keep_report_split_absent"] is True
    assert future["packet_must_keep_scored_outputs_sealed"] is True
    assert future["independent_packet_review_required"] is True
    assert future["packet_cannot_self_authorize"] is True
    assert future["packet_write_must_be_exclusive_and_after_review"] is True
    assert future["implementation_authorized_now"] is False
    assert future["freeze_authorized_now"] is False
    assert future["run_authorized_now"] is False


def test_terminal_sequence_keeps_scored_outputs_sealed(design):
    terminal = design["terminal_sequence"]
    assert terminal[
        "scored_shards_remain_sealed_until_supervisor_final_review"] is True
    assert terminal["score_free_supervisor_final_review_required"] is True
    assert terminal["aggregation_requires_separate_explicit_marker"] is True
    assert terminal[
        "aggregate_reconstruction_requires_all_32_exact_shards"] is True
    assert terminal[
        "result_review_required_before_opening_diagnostic_values"] is True
    assert terminal[
        "positive_diagnostic_opens_only_fresh_next_design_review"] is True
    assert terminal["no_automatic_retry_extension_or_larger_look"] is True


def test_all_execution_and_downstream_authority_remains_closed(design):
    assert design["authority"] == {
        "scored_packet_design_only": True,
        "controller_freeze_specification_only": True,
        "population_open_authorized_now": False,
        "capacity_result_open_authorized_now": False,
        "controller_implementation_authorized": False,
        "scored_packet_implementation_authorized": False,
        "scored_packet_freeze_authorized": False,
        "scored_packet_run_authorized": False,
        "scored_evaluation_authorized": False,
        "scored_output_access_authorized": False,
        "aggregation_authorized": False,
        "report_access_authorized": False,
        "champion_dose_census_implementation_authorized": False,
        "champion_dose_census_execution_authorized": False,
        "whole_game_execution_authorized": False,
        "retry_authorized": False,
        "extension_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
    }


@pytest.mark.parametrize(("section", "field", "value"), (
    ("selection", "report_permitted", True),
    ("selection", "splits", ["dev", "calib", "report"]),
    ("selection", "states", 1_023),
    ("selection", "no_replacement_retry_or_extension", False),
    ("schedule", "logical_lanes", 15),
    ("schedule", "scored_shard_outputs", 16),
    ("scored_work", "selection_worlds_per_candidate", 29),
    ("scored_work", "external_common_worlds", 299),
    ("estimands", "primary_row_filter", "all roles"),
    ("estimands", "combined_dev_calib_primary", False),
    ("estimands", "exact_whole_round_estimand", True),
    ("estimands", "policy_selection_neutral_does_not_imply_source_failure",
     False),
    ("natural_dose_boundary", "is_live_champion_dose", True),
    ("capacity_and_economics", "currency_or_host_price_claim", True),
    ("capacity_and_economics", "projected_fleet_hours", 0.1),
    ("future_controller_freeze", "freeze_authorized_now", True),
))
def test_rehashed_science_or_scope_mutation_refuses(
        design, section, field, value):
    design[section][field] = value
    _rehash(design)
    with pytest.raises(
            DESIGN.ScoredPacketDesignRefused,
            match="differs from reconstruction"):
        DESIGN.validate_design(design)


@pytest.mark.parametrize("field", (
    "controller_implementation_authorized",
    "scored_packet_implementation_authorized",
    "scored_packet_freeze_authorized",
    "scored_packet_run_authorized",
    "scored_evaluation_authorized",
    "scored_output_access_authorized",
    "aggregation_authorized",
    "report_access_authorized",
    "champion_dose_census_implementation_authorized",
    "champion_dose_census_execution_authorized",
    "whole_game_execution_authorized",
    "retry_authorized",
    "extension_authorized",
    "strength_claim",
    "training_authorized",
    "production_promotion",
    "production_deployment",
))
def test_rehashed_authority_escalation_refuses(design, field):
    design["authority"][field] = True
    _rehash(design)
    with pytest.raises(
            DESIGN.ScoredPacketDesignRefused,
            match="differs from reconstruction"):
        DESIGN.validate_design(design)


def test_rehashed_band_weights_or_membership_substitution_refuses(design):
    design["estimands"]["band_weights"] = {
        "early": 0.5, "mid": 0.25, "late": 0.25,
    }
    design["estimands"]["defender_membership_sha256"] = "0" * 64
    _rehash(design)
    with pytest.raises(
            DESIGN.ScoredPacketDesignRefused,
            match="differs from reconstruction"):
        DESIGN.validate_design(design)


def test_every_hash_binding_is_nonempty_exact_lower_hex(design):
    hashes = [
        design["design_sha256"],
        design["schedule"]["lane_manifest_sha256"],
        design["selection"]["identity_membership_sha256"],
        design["selection"]["selection_sha256"],
        design["estimands"]["defender_membership_sha256"],
        design["frozen_inputs"]["population"]["file_sha256"],
        design["frozen_inputs"]["population"]["artifact_sha256"],
        design["frozen_inputs"]["population"]["shard_manifest_sha256"],
        design["frozen_inputs"]["capacity_design"]["file_sha256"],
        design["frozen_inputs"]["capacity_design"]["internal_sha256"],
        design["frozen_inputs"]["capacity_evidence"]["packet_sha256"],
        design["frozen_inputs"]["capacity_evidence"][
            "packet_internal_sha256"],
        design["frozen_inputs"]["capacity_evidence"]["admission_sha256"],
        design["frozen_inputs"]["capacity_evidence"]["result_sha256"],
        design["frozen_inputs"]["capacity_evidence"][
            "result_internal_sha256"],
        *design["review_chain"]["reviewed_sources"].values(),
        *(lane["selection_sha256"] for lane in design["schedule"]["lanes"]),
    ]
    assert hashes
    assert all(DESIGN._is_hex(value, 64) for value in hashes)


@pytest.mark.parametrize("bad_hash", (
    None,
    "",
    "0" * 63,
    "0" * 65,
    "G" * 64,
))
def test_none_empty_or_non_64_hex_hash_binding_refuses(design, bad_hash):
    design["frozen_inputs"]["capacity_evidence"]["result_sha256"] \
        = bad_hash
    _rehash(design)
    with pytest.raises(
            DESIGN.ScoredPacketDesignRefused,
            match="differs from reconstruction"):
        DESIGN.validate_design(design)


@pytest.mark.parametrize(("path", "value"), (
    (("selection", "states"), 1_024.0),
    (("estimands", "attacker_rows"), True),
    (("schedule", "lanes", 0, "lane_index"), False),
    (("schedule", "lanes", 1, "lane_index"), True),
    (("schedule", "lanes", 0, "state_count"), 51.0),
    (("schedule", "lanes", 3, "max_candidate_world_rollouts"),
     246_960.0),
))
def test_bool_or_float_substitution_for_integer_contract_refuses(
        design, path, value):
    target = design
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    _rehash(design)
    with pytest.raises(
            DESIGN.ScoredPacketDesignRefused,
            match="differs from reconstruction"):
        DESIGN.validate_design(design)


def test_reviewed_source_substitution_refuses(monkeypatch):
    changed = dict(DESIGN.SOURCE_SHA256S)
    changed["pair_ballot_affected_eval.py"] = "0" * 64
    monkeypatch.setattr(DESIGN, "SOURCE_SHA256S", changed)
    with pytest.raises(
            DESIGN.ScoredPacketDesignRefused,
            match="reviewed Pair source digest drift"):
        DESIGN.build_design()


def test_digest_only_edit_and_foreign_field_refuse(design):
    design["authority"]["scored_packet_run_authorized"] = True
    with pytest.raises(
            DESIGN.ScoredPacketDesignRefused, match="design digest drift"):
        DESIGN.validate_design(design)

    design = DESIGN.build_design()
    design["launcher"] = {"enabled": False}
    _rehash(design)
    with pytest.raises(
            DESIGN.ScoredPacketDesignRefused,
            match="differs from reconstruction"):
        DESIGN.validate_design(design)


def test_verify_design_file_is_strict_and_source_reconstructing(
        design, tmp_path):
    path = tmp_path / "design.json"
    path.write_bytes(DESIGN._canonical(design))
    assert DESIGN.verify_design_file(path) == design

    raw = DESIGN._canonical(design).decode()
    duplicate = raw.replace(
        '"schema":"pair-ballot-affected-scored-packet-design-v1",',
        '"schema":"pair-ballot-affected-scored-packet-design-v1",'
        '"schema":"pair-ballot-affected-scored-packet-design-v1",', 1)
    path.write_text(duplicate)
    with pytest.raises(
            DESIGN.ScoredPacketDesignRefused, match="unreadable"):
        DESIGN.verify_design_file(path)

    path.write_text(json.dumps(design, indent=2) + "\n")
    with pytest.raises(
            DESIGN.ScoredPacketDesignRefused, match="not canonical JSON"):
        DESIGN.verify_design_file(path)

    path.write_text('{"value":NaN}\n')
    with pytest.raises(
            DESIGN.ScoredPacketDesignRefused, match="unreadable"):
        DESIGN.verify_design_file(path)


def test_verify_refuses_symlink_hardlink_and_partial(design, tmp_path):
    source = tmp_path / "source.json"
    source.write_bytes(DESIGN._canonical(design))

    symlink = tmp_path / "symlink.json"
    symlink.symlink_to(source)
    with pytest.raises(
            DESIGN.ScoredPacketDesignRefused, match="linked"):
        DESIGN.verify_design_file(symlink)

    hardlink = tmp_path / "hardlink.json"
    os.link(source, hardlink)
    with pytest.raises(
            DESIGN.ScoredPacketDesignRefused, match="linked"):
        DESIGN.verify_design_file(hardlink)
    hardlink.unlink()

    partial = Path(str(source) + ".partial")
    partial.write_text("incomplete")
    with pytest.raises(
            DESIGN.ScoredPacketDesignRefused, match="partial"):
        DESIGN.verify_design_file(source)


def test_module_has_no_writer_gameplay_or_imported_evaluator_surface():
    source = Path(DESIGN.__file__).read_text()
    assert "import pair_ballot_affected_" not in source
    assert "from shengji" not in source
    assert "make_bot(" not in source
    assert "evaluate_state(" not in source
    assert "run_shard(" not in source
    assert "aggregate(" not in source
    assert "_write_exclusive" not in source
    assert "Popen(" not in source
    assert "packet_path.write" not in source
    assert "admission_path.write" not in source
    assert "result_path.write" not in source

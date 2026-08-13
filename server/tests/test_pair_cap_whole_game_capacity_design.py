from __future__ import annotations

import ast
import copy
import json
import os
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pair_cap_whole_game_capacity_design as DESIGN  # noqa: E402


def _rehash(design: dict) -> None:
    body = dict(design)
    body.pop("design_sha256", None)
    design["design_sha256"] = DESIGN._stable_digest(body)


def _root_work(*, searches: int = 1, rollouts: int = 660) -> dict:
    value = {field: 0 for field in DESIGN.ROOT_WORK_FIELDS}
    value.update({
        "rollouts": rollouts,
        "searches": searches,
        "search_secs": 0.25,
        "sample_attempts": searches * DESIGN.ACCEPTED_WORLDS_PER_SEARCH,
        "accepted_worlds": searches * DESIGN.ACCEPTED_WORLDS_PER_SEARCH,
    })
    return value


def _pair_aware(*, lead_calls: int, triggers: int) -> dict:
    value = {field: 0 for field in DESIGN.PAIR_AWARE_COUNTER_FIELDS}
    value["lead_calls"] = lead_calls
    if triggers:
        value.update({
            "single_baseline_leads": triggers,
            "pair_candidates_checked": triggers,
            "promoted_boss_pairs": triggers,
            "ruff_safe_promoted_pairs": triggers,
            "opportunities": triggers,
            "triggers": triggers,
            "changes": triggers,
            "attacker_triggers": triggers,
        })
    return value


def _pair_cap(*, triggers: int) -> dict:
    value = {field: 0 for field in DESIGN.PAIR_CAP_COUNTER_FIELDS}
    if triggers:
        value.update({
            "candidates_checked": triggers,
            "opponent_pair_cap_proofs": triggers,
            "ruff_safe_proofs": triggers,
            "opportunities": triggers,
            "triggers": triggers,
            "changes": triggers,
            "attacker_triggers": triggers,
        })
    return value


def _incremental(mode: str, *, triggers: int = 1) -> dict:
    outer = {
        field: 0 for field in DESIGN.PAIR_CAP_INCREMENTAL_COUNTER_FIELDS
    }
    outer["lead_calls"] = 1
    if triggers:
        outer.update({
            "v1_v3_action_differences": triggers,
            "opportunities": triggers,
            "triggers": triggers,
            "attacker_triggers": triggers,
            ("changes" if mode == "treatment"
             else "matched_parent_noops"): triggers,
        })
    return {
        "schema": "pair-cap-attacker-incremental-telemetry-v1",
        "mode": mode,
        "deterministic": True,
        "public_information_only": True,
        "exact_component_work": True,
        "components_are_counterfactual_analyses": True,
        "counters": {
            "outer": outer,
            "v1_pair_aware": _pair_aware(lead_calls=1, triggers=0),
            "v3_pair_aware": _pair_aware(
                lead_calls=1, triggers=triggers),
            "v3_pair_cap": _pair_cap(triggers=triggers),
        },
    }


def _record(design: dict, label: str, *, index: int = 0,
            flip: int = 0) -> dict:
    return {
        "schema": DESIGN.CAPACITY_RECORD_SCHEMA,
        "design_sha256": design["design_sha256"],
        "cluster_index": index,
        "deal_seed": DESIGN.CAPACITY_SEED0 + DESIGN.STREAM_STRIDE * index,
        "flip": flip,
        "label": label,
        "policy": design["arms"]["contracts"][label]["policy"],
        "opponent": design["arms"]["opponent_for_every_arm"],
        "elapsed_seconds": 1.0,
        "arm_root_work": _root_work(),
        "opponent_root_work": _root_work(),
        "root_roles": {"attacker_searches": 1, "defender_searches": 0},
        "incremental": (
            None if label == "literal_champion"
            else _incremental(label)),
        "natural_dose": ({
            "shared_prefix_root_decisions": 3,
            "root_action_changed": True,
            "change_phase": "early",
            "change_role": "attacker",
        } if label == "treatment" else None),
    }


def _keys(value: object) -> set[str]:
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            found.add(str(key).lower())
            found.update(_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_keys(item))
    return found


def test_design_freezes_three_arm_common_population_and_no_execution():
    design = DESIGN.build_design()
    DESIGN.validate_design(design)
    assert design["reviewed_source"] == {
        "pr_number": 69,
        "git": DESIGN.REVIEWED_GIT,
        "parent_pr_number": 62,
        "parent_git": DESIGN.REVIEWED_PARENT_GIT,
        "review_schema": DESIGN.REVIEW_SCHEMA,
        "review_verdict": "PASS",
        "review_authority": "capacity/packet design only",
        "review_claim": {
            "component_work_identical": True,
            "parent_v1_preserved": True,
            "attacker_only_incremental_dose": True,
            "root_ballot_unchanged": True,
            "literal_champion_separate_arm_required": True,
            "public_information_only": True,
            "capacity_packet_design_authorized": True,
            "whole_game_execution_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
        "source_sha256s": dict(sorted(DESIGN.SOURCE_SHA256S.items())),
        "sealed_outcomes_opened": False,
    }
    assert design["population"]["capacity"] == {
        "seed0": 620_000_000_000,
        "clusters": 8,
        "seed_hi": 620_021_000_119,
        "stream_stride": 3_000_017,
        "flips": [0, 1],
        "labels": ["treatment", "matched_parent", "literal_champion"],
        "policy_seed_offsets": [0, 500_000],
        "opponent_seed_offsets": [1_000_000, 1_500_000],
        "manifest_sha256": (
            "b5beaa5daede0e57d6782ae98dda6d221a24b796acea8abba50c962319d3930c"),
    }
    assert design["population"]["evaluation"]["clusters"] == 4_608
    assert design["population"]["evaluation"]["manifest_sha256"] == (
        "ea8662c64e240e8e8eb074e74e282d070d99106f3ee0d43e2ceda0a4691b58f3")
    assert design["population"]["capacity_evaluation_disjoint"] is True
    assert design["population"]["same_deal_for_all_arms"] is True
    assert design["population"][
        "same_policy_and_opponent_rng_offsets_for_all_arms"] is True
    assert design["authority"] == {
        "design_only": True,
        "score_free": True,
        "design_review_authorized": True,
        "capacity_implementation_authorized": False,
        "capacity_execution_authorized": False,
        "scored_controller_implementation_authorized": False,
        "scored_packet_review_authorized": False,
        "whole_game_execution_authorized": False,
        "sealed_outcome_access_authorized": False,
        "launcher_present": False,
        "resource_binding_authorized": False,
        "retry_or_extension_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    assert not ({"host", "ip", "address"} & _keys(design))


def test_policy_contract_is_parent_matched_and_champion_literal():
    design = DESIGN.build_design()
    contracts = design["arms"]["contracts"]
    treatment = contracts["treatment"]
    parent = contracts["matched_parent"]
    champion = contracts["literal_champion"]
    common = (
        "root_base_class", "root_ballot_digest", "uppercase_contract_sha256",
        "rng_probe_seed", "rng_state_sha256", "root_selection_worlds",
        "root_report_worlds", "lead_candidate_cap", "follow_candidate_cap",
        "require_exact_root_work",
    )
    assert all(treatment[field] == parent[field] == champion[field]
               for field in common)
    assert treatment["component_recipe"] == parent["component_recipe"] == [
        "v1_pair_aware", "v3_attacker_gate"]
    assert treatment["class"] == parent["class"] \
        == "PairCapAttackerIncrementalMCS0ReportLCB"
    assert champion["class"] == champion["root_base_class"] \
        == "MCS0ReportLCB"
    assert parent["returned_component"] == "v1"
    assert champion["policy"] == "mc-s0-report-lcb"
    assert champion["component_recipe"] == []
    assert design["arms"]["treatment_parent_component_work_identical"] \
        is True
    assert design["arms"]["component_work_identity_unit"] \
        == "each visited rollout lead"
    assert design["arms"]["post_divergence_total_lead_counts_may_differ"] \
        is True
    assert design["arms"]["champion_internal_component_work_identical"] \
        is False
    assert design["arms"]["champion_budget_comparability_unit"].startswith(
        "root Monte Carlo budget")


def test_two_required_contrasts_have_predeclared_joint_power_and_work_caps():
    design = DESIGN.build_design()
    assert design["estimands"]["primary"].endswith(
        "treatment minus matched_parent")
    assert design["estimands"]["absolute_guardrail"].endswith(
        "treatment minus literal_champion")
    assert "both treatment minus matched_parent" in \
        design["estimands"]["decision_rule"]
    assert design["power"]["clusters_required_for_target_marginal_power_each"] \
        == 4_475
    assert design["power"]["mde_at_80pct_marginal_power"] == pytest.approx(
        0.05860677450422228)
    assert design["power"]["marginal_power_at_target_effect"] == \
        pytest.approx(0.9074135709493715)
    assert design["power"]["joint_power_union_bound_floor_at_target_effect"] \
        == pytest.approx(0.814827141898743)
    assert design["power"]["sensitivity_by_effect"]["0.05"] == {
        "marginal_power_each": pytest.approx(0.6831290430800078),
        "joint_power_union_bound_floor": pytest.approx(0.36625808616001554),
    }
    assert design["power"]["adequately_powered"] is True
    assert design["estimands"]["stage"] \
        == "economical first-look screen; not confirmation"
    assert design["estimands"]["nonpass_route"] \
        == "SELECT_NONE; no automatic continuation"
    assert design["work_ceiling"]["capacity"]["arm_rounds"] == 48
    assert design["work_ceiling"]["capacity"]["root_search_scope"] == \
        "arm team plus literal champion opponent"
    assert design["work_ceiling"]["evaluation"]["arm_rounds"] == 27_648
    assert design["work_ceiling"]["evaluation"][
        "max_candidate_world_rollouts"] == 2_820_096_000
    assert design["work_ceiling"]["logical_lanes"] == 16
    assert design["work_ceiling"]["evaluation_clusters_per_lane"] == 288
    assert design["work_ceiling"]["max_projected_compute_hours"] == 768.0
    assert design["work_ceiling"]["max_projected_lane_hours"] == 48.0
    assert design["work_ceiling"]["resource_or_machine_binding"] is False


@pytest.mark.parametrize("mutate", (
    lambda value: value["population"]["capacity"].__setitem__("seed0", 1),
    lambda value: value["population"]["capacity"].__setitem__("flips", [0]),
    lambda value: value["population"]["evaluation"].__setitem__(
        "clusters", 8_192),
    lambda value: value["arms"].__setitem__(
        "order", ["treatment", "literal_champion"]),
    lambda value: value["arms"]["contracts"]["matched_parent"].__setitem__(
        "policy", "mc-s0-report-lcb"),
    lambda value: value["arms"]["contracts"]["matched_parent"].__setitem__(
        "component_recipe", ["v1_pair_aware"]),
    lambda value: value["arms"]["contracts"]["literal_champion"].__setitem__(
        "component_recipe", ["v3_attacker_gate"]),
    lambda value: value["estimands"].__setitem__(
        "absolute_guardrail", "none"),
    lambda value: value["power"].__setitem__(
        "planning_cluster_sd", 0.1),
    lambda value: value["work_ceiling"].__setitem__(
        "max_projected_compute_hours", 10_000.0),
    lambda value: value["role_dose_scope"].__setitem__(
        "v3_pair_cap_defender_triggers_required", 1),
    lambda value: value["authority"].__setitem__(
        "capacity_execution_authorized", True),
))
def test_rehashed_semantic_mutations_refuse(mutate):
    design = DESIGN.build_design()
    mutate(design)
    _rehash(design)
    with pytest.raises(
            DESIGN.CapacityDesignRefused,
            match="differs from reconstruction"):
        DESIGN.validate_design(design)


def test_source_hash_and_policy_factory_substitutions_refuse(monkeypatch):
    original_sha = DESIGN._sha256_path

    def drifted_sha(path):
        if Path(path) == DESIGN.SOURCE_PATHS["incremental_policy"]:
            return "0" * 64
        return original_sha(path)

    monkeypatch.setattr(DESIGN, "_sha256_path", drifted_sha)
    with pytest.raises(
            DESIGN.CapacityDesignRefused, match="source digest drift"):
        DESIGN.build_design()

    monkeypatch.setattr(DESIGN, "_sha256_path", original_sha)
    monkeypatch.setattr(
        DESIGN, "make_pair_cap_incremental_bot",
        lambda **kwargs: DESIGN.make_bot("mc-s0-report-lcb", seed=7))
    with pytest.raises(
            DESIGN.CapacityDesignRefused, match="rollout seam identity drift"):
        DESIGN.build_design()


@pytest.mark.parametrize(
    "label", ("treatment", "matched_parent", "literal_champion"))
def test_score_free_capacity_record_accepts_exact_three_arm_contract(label):
    design = DESIGN.build_design()
    assert DESIGN.capacity_record_problems(_record(design, label), design) == []


def test_recursive_score_or_outcome_fields_refuse_before_extra_fields():
    design = DESIGN.build_design()
    record = _record(design, "treatment")
    record["incremental"]["counters"]["outer"]["points"] = 0
    problems = DESIGN.capacity_record_problems(record, design)
    assert problems == [
        "forbidden telemetry field: $.incremental.counters.outer.points"]

    record = _record(design, "literal_champion")
    record["arm_root_work"]["nested"] = {"winner_team": 0}
    problems = DESIGN.capacity_record_problems(record, design)
    assert problems == [
        "forbidden telemetry field: $.arm_root_work.nested.winner_team"]


def test_parent_champion_substitution_and_champion_hook_refuse():
    design = DESIGN.build_design()
    parent = _record(design, "matched_parent")
    parent["policy"] = "mc-s0-report-lcb"
    assert "capacity record policy identity" in \
        DESIGN.capacity_record_problems(parent, design)

    champion = _record(design, "literal_champion")
    champion["incremental"] = _incremental("treatment")
    assert "literal champion gained incremental telemetry" in \
        DESIGN.capacity_record_problems(champion, design)


def test_skipped_component_and_removed_attacker_gate_refuse():
    design = DESIGN.build_design()
    parent = _record(design, "matched_parent")
    parent["incremental"]["counters"]["v3_pair_aware"] = _pair_aware(
        lead_calls=0, triggers=0)
    assert "incremental component lead work" in \
        DESIGN.capacity_record_problems(parent, design)

    treatment = _record(design, "treatment")
    cap = treatment["incremental"]["counters"]["v3_pair_cap"]
    cap["attacker_triggers"] = 0
    cap["defender_triggers"] = 1
    problems = DESIGN.capacity_record_problems(treatment, design)
    assert "v3 pair-cap defender trigger" in problems


def test_rng_population_and_exact_root_work_drift_refuse():
    design = DESIGN.build_design()
    record = _record(design, "treatment")
    record["deal_seed"] += 1
    assert DESIGN.capacity_record_problems(record, design) == [
        "capacity record identity"]

    record = _record(design, "treatment")
    record["arm_root_work"]["accepted_worlds"] -= 1
    record["arm_root_work"]["sample_attempts"] -= 1
    assert "arm root work accepted-world dose" in \
        DESIGN.capacity_record_problems(record, design)

    record = _record(design, "treatment")
    record["arm_root_work"]["short_searches"] = 1
    assert "arm root work forbidden short_searches" in \
        DESIGN.capacity_record_problems(record, design)


def test_zero_change_dose_is_explicit_hold_without_extension():
    design = DESIGN.build_design()
    assert design["role_dose_scope"][
        "natural_treatment_parent_root_changes_required_for_capacity_pass"] == 1
    assert design["refusal"]["zero_natural_incremental_root_change"] \
        == "HOLD; no extension"
    assert design["authority"]["retry_or_extension_authorized"] is False


def test_design_module_has_no_gameplay_launcher_or_machine_binding_imports():
    source = Path(DESIGN.__file__).read_text()
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert "subprocess" not in imported
    assert "shengji.ai.env" not in imported
    assert "shengji.engine.game" not in imported
    assert not any(isinstance(node, ast.Name) and node.id == "play_round"
                   for node in ast.walk(tree))
    assert not any(isinstance(node, ast.FunctionDef) and node.name == "main"
                   for node in ast.walk(tree))


def test_verify_design_file_refuses_symlink_and_partial(tmp_path: Path):
    design = DESIGN.build_design()
    source = tmp_path / "design.json"
    source.write_text(json.dumps(design))
    assert DESIGN.verify_design_file(source) == design

    link = tmp_path / "link.json"
    link.symlink_to(source)
    with pytest.raises(
            DESIGN.CapacityDesignRefused, match="linked, nonregular"):
        DESIGN.verify_design_file(link)

    partial = Path(str(source) + ".partial")
    partial.write_text("incomplete")
    with pytest.raises(
            DESIGN.CapacityDesignRefused, match="linked, nonregular"):
        DESIGN.verify_design_file(source)

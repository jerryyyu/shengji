from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pair_ballot_affected_capacity_design as DESIGN  # noqa: E402


def _cards(prefix: str) -> list[list[str]]:
    return [[f"{prefix}{index}"] for index in range(DESIGN.BALLOT_WIDTH)]


@pytest.fixture
def population_payload() -> dict:
    states = []
    for split_index, split in enumerate((*DESIGN.SPLITS, "report")):
        offset = split_index * 100_000
        row_index = 0
        for band, count in DESIGN.BAND_ROWS_PER_SPLIT.items():
            for band_index in range(count):
                seed = offset + row_index
                # Mirror the reviewed population's deal clustering: 16 DEV
                # and 17 CALIB defender deals contribute both early and mid
                # rows.  The lone CALIB attacker remains its own deal.
                overlap = 16 if split == "dev" else 17
                if band == "mid" and band_index < overlap:
                    early_index = band_index
                    if split == "calib" and band_index == 0:
                        early_index = 32
                    seed = offset + early_index
                current = _cards("c")
                retained = copy.deepcopy(current)
                retained[-1] = [f"p{row_index}", f"p{row_index}"]
                states.append({
                    "state_id": f"{seed}:{row_index % 20}:0",
                    "state_sha256": f"{row_index + split_index:064x}"[-64:],
                    "deal_seed": seed,
                    "split": split,
                    "band": band,
                    "trick": row_index % 20,
                    "seat": 0,
                    "role": ("attacker" if split == "calib" and row_index == 0
                             else "defender"),
                    "search_eligible": True,
                    "current_ballot": current,
                    "retained_ballot": retained,
                })
                row_index += 1
    return {
        "artifact_sha256": DESIGN.POPULATION_ARTIFACT_SHA256,
        "source_sha256s": {"producer": DESIGN.CAPTURE_SHA256},
        "states": states,
        "search_eligible_weights": {
            "early": 0.9686815593517302,
            "mid": 0.03081197985107315,
            "late": 0.000506460797196671,
        },
        "search_eligible_denominator": 146_112,
        "max_deals": 12_000_000,
        "source_policy": DESIGN.SOURCE_TRAJECTORY_POLICY,
    }


@pytest.fixture
def population_path(tmp_path: Path) -> Path:
    path = tmp_path / "population.json"
    path.write_text("reviewed-population-placeholder")
    return path


@pytest.fixture
def pinned_sources(monkeypatch, population_payload, population_path):
    def fake_sha(path):
        path = Path(path)
        if path == population_path:
            return DESIGN.POPULATION_FILE_SHA256
        if path == Path(DESIGN.EVAL.__file__):
            return DESIGN.EVALUATOR_SHA256
        if path == Path(DESIGN.AGG.__file__):
            return DESIGN.AGGREGATE_SHA256
        raise AssertionError(f"unexpected source hash: {path}")

    monkeypatch.setattr(DESIGN.STATES, "sha256_file", fake_sha)
    monkeypatch.setattr(
        DESIGN.EVAL, "load_population", lambda path: population_payload)
    selected = sorted(
        (row for row in population_payload["states"]
         if row["split"] in DESIGN.SPLITS),
        key=lambda row: (
            DESIGN.SPLITS.index(row["split"]), row["deal_seed"],
            row["trick"], row["seat"]),
    )
    defenders = [row for row in selected if row["role"] == "defender"]
    monkeypatch.setattr(
        DESIGN, "REVIEWED_IDENTITY_MEMBERSHIP_SHA256",
        DESIGN._membership_sha256(selected))
    monkeypatch.setattr(
        DESIGN, "REVIEWED_DEFENDER_MEMBERSHIP_SHA256",
        DESIGN._membership_sha256(defenders))
    monkeypatch.setattr(
        DESIGN, "REVIEWED_SELECTION_SHA256",
        DESIGN._sha256(DESIGN._canonical(
            [DESIGN._manifest_row(row) for row in selected])))


def _rehash(design: dict) -> None:
    body = dict(design)
    body.pop("design_sha256", None)
    design["design_sha256"] = DESIGN._sha256(DESIGN._canonical(body))


def test_full_dev_calib_schedule_is_fixed_and_adequately_powered(
        pinned_sources, population_path):
    design = DESIGN.build_design(population_path)
    assert design["selection"]["states"] == 1_024
    assert design["selection"]["states_by_split"] == {
        "calib": 512, "dev": 512,
    }
    assert design["selection"]["states_by_band"] == {
        "early": 896, "late": 32, "mid": 96,
    }
    assert design["selection"]["states_by_role"] == {
        "attacker": 1, "defender": 1_023,
    }
    assert design["selection"]["unique_deal_clusters"] == 991
    assert design["selection"]["identity_membership_sha256"] \
        == DESIGN.REVIEWED_IDENTITY_MEMBERSHIP_SHA256
    assert design["selection"]["defender_membership_sha256"] \
        == DESIGN.REVIEWED_DEFENDER_MEMBERSHIP_SHA256
    assert design["schedule"]["logical_lanes"] == 16
    assert design["schedule"]["outputs"] == 32
    assert len(design["schedule"]["lanes"]) == 16
    assert all(lane["states_by_split"] == {"calib": 32, "dev": 32}
               for lane in design["schedule"]["lanes"])
    assert design["work"]["max_candidate_world_rollouts_per_state"] == 2_940
    assert design["work"]["max_candidate_world_rollouts_total"] == 3_010_560
    assert design["power"]["mde_at_target_power"] \
        == 0.040889289223836306
    assert design["power"]["state_rows"] == 1_023
    assert design["power"]["independent_deal_clusters"] == 990
    assert design["power"]["effective_clusters_under_band_weights"] \
        == 924.8524611365071
    assert design["power"]["planning_se"] == 0.016441209981438
    assert design["power"]["power_at_worthwhile_effect"] \
        == 0.9186636345219327
    assert design["power"]["adequately_powered_at_worthwhile_effect"] is True
    assert design["scope"] == {
        "defender_states": 1_023,
        "attacker_states": 1,
        "primary_role_inference": "defender-selected-state population",
        "attacker_effect_estimable": False,
        "attacker_row_use": "descriptive case study only",
        "all_role_generalization_authorized": False,
        "role_stratified_reporting_required": True,
        "selected_role_mix_is_natural_dose": False,
        "role_specific_natural_dose_available": False,
        "role_conditional_band_weights_available": False,
        "all_role_smartbot_band_weights_used_for_exploration": True,
        "role_specific_capture_census_required_before_whole_round_claim": True,
        "late_band_use": "diagnostic slice; natural weight is below 0.001",
    }
    assert design["estimands"]["primary"] \
        == "defender_retained_policy_minus_current"
    assert design["estimands"]["combined_dev_calib_primary"] is True
    assert design["routing"]["decision_statistic"] \
        == "combined DEV+CALIB defender summary"
    assert design["dose"] == {
        "source_trajectory_policy": "smart",
        "search_eligible_omission_events": 146_112,
        "capture_deals": 12_000_000,
        "events_per_captured_smartbot_deal": 146_112 / 12_000_000,
        "is_live_champion_dose": False,
        "live_champion_role_specific_dose_available": False,
        "translation_to_whole_round_is_approximate": True,
    }


def test_combined_summary_is_defender_only_and_routes_on_both_splits(
        pinned_sources, population_payload, population_path):
    design = DESIGN.build_design(population_path)
    rows = [copy.deepcopy(row) for row in population_payload["states"]
            if row["split"] in DESIGN.SPLITS]
    for row in rows:
        if row["role"] == "attacker":
            policy_value, source_value = -1000.0, -2000.0
        elif row["split"] == "dev":
            policy_value, source_value = -0.2, -0.3
        else:
            policy_value, source_value = 0.4, 0.5
        row["estimands"] = {
            "retained_policy_minus_current": policy_value,
            "best_inserted_pair_minus_current": source_value,
        }
    summary = DESIGN.defender_combined_summary(rows, design)
    assert summary["schema"] == DESIGN.SUMMARY_SCHEMA
    assert summary["primary_population"] == "combined DEV+CALIB defender rows"
    assert summary["rows"] == 1_023
    assert summary["deal_clusters"] == 990
    assert summary["attacker_case_study_rows_excluded"] == 1
    assert summary["routing_basis"] == "combined_defender_dev_calib"
    assert summary["diagnostic_route"] \
        == "POLICY_AND_SOURCE_PROMISING_MEASURE_LIVE_CHAMPION_DOSE"
    assert set(summary["split_diagnostics"]) == {"dev", "calib"}
    policy = summary["metrics"]["retained_policy_minus_current"][
        "capture_event_band_weighted_mean"]
    source = summary["metrics"]["best_inserted_pair_minus_current"][
        "capture_event_band_weighted_mean"]
    dev_policy = summary["split_diagnostics"]["dev"][
        "retained_policy_minus_current"]["capture_event_band_weighted_mean"]
    calib_policy = summary["split_diagnostics"]["calib"][
        "retained_policy_minus_current"]["capture_event_band_weighted_mean"]
    assert dev_policy == pytest.approx(-0.2)
    assert calib_policy == pytest.approx(0.4)
    assert dev_policy < policy < calib_policy
    assert policy > 0
    assert source > 0
    assert summary["selected_role_mix_is_natural_dose"] is False
    assert summary["strength_claim"] is False


def test_combined_summary_refuses_role_or_cluster_drift(
        pinned_sources, population_payload, population_path):
    design = DESIGN.build_design(population_path)
    rows = [copy.deepcopy(row) for row in population_payload["states"]
            if row["split"] in DESIGN.SPLITS]
    for row in rows:
        row["estimands"] = {metric: 0.0 for metric in DESIGN.AGG.METRICS}
    next(row for row in rows if row["role"] == "defender")["role"] = "attacker"
    with pytest.raises(
            DESIGN.CapacityDesignRefused, match="role membership drift"):
        DESIGN.defender_combined_summary(rows, design)


def test_coordinated_same_cell_role_swap_cannot_change_primary_membership(
        pinned_sources, population_payload, population_path):
    design = DESIGN.build_design(population_path)
    rows = [copy.deepcopy(row) for row in population_payload["states"]
            if row["split"] in DESIGN.SPLITS]
    for row in rows:
        row["estimands"] = {metric: 0.0 for metric in DESIGN.AGG.METRICS}
    attacker = next(row for row in rows
                    if row["role"] == "attacker"
                    and row["split"] == "calib" and row["band"] == "early")
    defender_deal_counts = {
        row["deal_seed"]: sum(other["deal_seed"] == row["deal_seed"]
                              and other["role"] == "defender"
                              for other in rows)
        for row in rows if row["role"] == "defender"
    }
    defender = next(row for row in rows
                    if row["role"] == "defender"
                    and row["split"] == "calib" and row["band"] == "early"
                    and defender_deal_counts[row["deal_seed"]] == 1)
    attacker["role"], defender["role"] = "defender", "attacker"
    # The old gate saw exactly the same aggregate cells and cluster count.
    swapped_defenders = [row for row in rows if row["role"] == "defender"]
    assert len(swapped_defenders) == DESIGN.DEFENDER_ROWS
    assert len({row["deal_seed"] for row in swapped_defenders}) \
        == DESIGN.DEFENDER_DEAL_CLUSTERS
    with pytest.raises(
            DESIGN.CapacityDesignRefused, match="membership drift"):
        DESIGN.defender_combined_summary(rows, design)


def test_coordinated_same_cell_split_swap_cannot_change_primary_membership(
        pinned_sources, population_payload, population_path):
    design = DESIGN.build_design(population_path)
    rows = [copy.deepcopy(row) for row in population_payload["states"]
            if row["split"] in DESIGN.SPLITS]
    for row in rows:
        row["estimands"] = {metric: 0.0 for metric in DESIGN.AGG.METRICS}
    dev = next(row for row in rows
               if row["split"] == "dev" and row["band"] == "early"
               and row["role"] == "defender")
    calib = next(row for row in rows
                 if row["split"] == "calib" and row["band"] == "early"
                 and row["role"] == "defender")
    dev["split"], calib["split"] = calib["split"], dev["split"]
    assert sum(row["split"] == "dev" for row in rows) == 512
    assert sum(row["split"] == "calib" for row in rows) == 512
    with pytest.raises(
            DESIGN.CapacityDesignRefused,
            match="identity/role membership drift"):
        DESIGN.defender_combined_summary(rows, design)


def test_report_row_cannot_replace_dev_row_with_marginals_preserved(
        pinned_sources, population_payload, population_path):
    dev = next(row for row in population_payload["states"]
               if row["split"] == "dev" and row["band"] == "early"
               and row["role"] == "defender")
    report = next(row for row in population_payload["states"]
                  if row["split"] == "report" and row["band"] == "early"
                  and row["role"] == "defender")
    dev["split"], report["split"] = report["split"], dev["split"]
    selected = [row for row in population_payload["states"]
                if row["split"] in DESIGN.SPLITS]
    assert len(selected) == 1_024
    assert sum(row["split"] == "dev" for row in selected) == 512
    assert sum(row["split"] == "calib" for row in selected) == 512
    assert sum(row["band"] == "early" for row in selected) == 896
    with pytest.raises(
            DESIGN.CapacityDesignRefused,
            match="identity/role membership drift"):
        DESIGN.build_design(population_path)


def test_attacker_estimand_cannot_change_primary_metrics_or_route(
        pinned_sources, population_payload, population_path):
    design = DESIGN.build_design(population_path)
    rows = [copy.deepcopy(row) for row in population_payload["states"]
            if row["split"] in DESIGN.SPLITS]
    for row in rows:
        row["estimands"] = {
            "retained_policy_minus_current": (
                0.0 if row["role"] == "attacker" else 0.1),
            "best_inserted_pair_minus_current": (
                0.0 if row["role"] == "attacker" else 0.2),
        }
    before = DESIGN.defender_combined_summary(rows, design)
    attacker = next(row for row in rows if row["role"] == "attacker")
    attacker["estimands"] = {
        "retained_policy_minus_current": -1_000_000.0,
        "best_inserted_pair_minus_current": 1_000_000.0,
    }
    after = DESIGN.defender_combined_summary(rows, design)
    assert DESIGN._canonical(before["metrics"]) \
        == DESIGN._canonical(after["metrics"])
    assert DESIGN._canonical(before["split_diagnostics"]) \
        == DESIGN._canonical(after["split_diagnostics"])
    assert DESIGN._canonical({"route": before["diagnostic_route"]}) \
        == DESIGN._canonical({"route": after["diagnostic_route"]})


def test_selected_role_mix_cannot_be_relabelled_natural_dose(
        pinned_sources, population_path):
    design = DESIGN.build_design(population_path)
    design["scope"]["selected_role_mix_is_natural_dose"] = True
    _rehash(design)
    with pytest.raises(
            DESIGN.CapacityDesignRefused, match="scope drift"):
        DESIGN.validate_design(design, population=population_path)


def test_source_trajectory_cannot_be_relabelled_champion(
        pinned_sources, population_payload, population_path):
    population_payload["source_policy"] = "mc-s0-report-lcb"
    with pytest.raises(
            DESIGN.CapacityDesignRefused, match="trajectory policy drift"):
        DESIGN.build_design(population_path)


def test_rehashed_primary_estimator_or_power_cluster_drift_refuses(
        pinned_sources, population_path):
    design = DESIGN.build_design(population_path)
    design["estimands"]["primary_row_filter"] = "all roles"
    _rehash(design)
    with pytest.raises(
            DESIGN.CapacityDesignRefused, match="estimand drift"):
        DESIGN.validate_design(design, population=population_path)

    design = DESIGN.build_design(population_path)
    design["power"]["independent_deal_clusters"] = 1_023
    _rehash(design)
    with pytest.raises(
            DESIGN.CapacityDesignRefused, match="power drift"):
        DESIGN.validate_design(design, population=population_path)


@pytest.mark.parametrize(("section", "field", "value"), (
    ("estimands", "primary_splits", ["dev"]),
    ("estimands", "cluster_unit", "state_id"),
    ("power", "alpha", 0.5),
    ("scope", "attacker_effect_estimable", True),
    ("estimands", "exact_whole_round_estimand", True),
    ("estimands", "band_weight_unit",
     "live-champion search-reachable omission events"),
))
def test_rehashed_semantic_drifts_refuse_source_bound_validation(
        pinned_sources, population_path, section, field, value):
    design = DESIGN.build_design(population_path)
    design[section][field] = value
    _rehash(design)
    with pytest.raises(DESIGN.CapacityDesignRefused, match="drift"):
        DESIGN.validate_design(design, population=population_path)


def test_rehashed_arbitrary_normalized_band_weights_refuse(
        pinned_sources, population_path):
    design = DESIGN.build_design(population_path)
    design["estimands"]["band_weights"] = {
        "early": 0.5, "mid": 0.25, "late": 0.25,
    }
    _rehash(design)
    with pytest.raises(
            DESIGN.CapacityDesignRefused, match="estimand drift"):
        DESIGN.validate_design(design, population=population_path)


def test_foreign_authority_field_and_unbound_validation_refuse(
        pinned_sources, population_path):
    design = DESIGN.build_design(population_path)
    with pytest.raises(
            DESIGN.CapacityDesignRefused, match="source reconstruction"):
        DESIGN.validate_design(design)

    design["authority"]["launcher_authorized"] = True
    _rehash(design)
    with pytest.raises(
            DESIGN.CapacityDesignRefused, match="authority field drift"):
        DESIGN.validate_design(design, population=population_path)


def test_report_is_present_in_source_but_absent_from_design(
        pinned_sources, population_path):
    design = DESIGN.build_design(population_path)
    assert design["selection"]["splits"] == ["dev", "calib"]
    assert design["selection"]["report_permitted"] is False
    assert all("report" not in lane["states_by_split"]
               for lane in design["schedule"]["lanes"])
    assert design["authority"]["report_access_authorized"] is False


def test_design_is_capacity_only_and_requires_later_host_gate(
        pinned_sources, population_path):
    design = DESIGN.build_design(population_path)
    assert design["capacity"] == {
        "preferred_future_host_class": "cpx62-x86-16-vcpu-32gb",
        "preferred_host_is_runtime_qualified": False,
        "fallback_host_alias": "shengji-cloud",
        "fallback_currently_available": False,
        "public_address_recorded": False,
        "host_qualification_required": True,
        "measured_projection_available": False,
        "preflight_required_before_scored_execution": True,
        "max_fleet_hours": 64.0,
        "max_lane_wall_hours": 4.0,
        "cap_is_fail_closed_not_a_throughput_claim": True,
    }
    assert design["authority"] == {
        "capacity_design_only": True,
        "population_opened_for_design_only": True,
        "runtime_qualification_authorized": False,
        "capacity_preflight_authorized": False,
        "scored_evaluation_authorized": False,
        "report_access_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }


def test_changed_ballot_width_refuses_before_design(
        pinned_sources, population_payload, population_path):
    row = next(row for row in population_payload["states"]
               if row["split"] == "dev")
    row["current_ballot"].pop()
    with pytest.raises(
            DESIGN.CapacityDesignRefused, match="work geometry drift"):
        DESIGN.build_design(population_path)


def test_missing_split_row_refuses_instead_of_silently_shrinking(
        pinned_sources, population_payload, population_path):
    row = next(row for row in population_payload["states"]
               if row["split"] == "calib")
    row["split"] = "report"
    with pytest.raises(
            DESIGN.CapacityDesignRefused, match="state population drift"):
        DESIGN.build_design(population_path)


def test_rehashed_authority_escalation_refuses(
        pinned_sources, population_path):
    design = DESIGN.build_design(population_path)
    design["authority"]["scored_evaluation_authorized"] = True
    _rehash(design)
    with pytest.raises(
            DESIGN.CapacityDesignRefused, match="authority escalation"):
        DESIGN.validate_design(design, population=population_path)


def test_rehashed_report_admission_refuses(
        pinned_sources, population_path):
    design = DESIGN.build_design(population_path)
    design["selection"]["report_permitted"] = True
    _rehash(design)
    with pytest.raises(
            DESIGN.CapacityDesignRefused, match="selection drift"):
        DESIGN.validate_design(design, population=population_path)


def test_verify_reconstructs_every_field(
        pinned_sources, population_path, tmp_path):
    design = DESIGN.build_design(population_path)
    design_path = tmp_path / "design.json"
    design_path.write_bytes(DESIGN._canonical(design))
    assert DESIGN.verify_design(population_path, design_path) == design

    changed = copy.deepcopy(design)
    changed["capacity"]["max_fleet_hours"] = 65.0
    _rehash(changed)
    design_path.write_bytes(DESIGN._canonical(changed))
    with pytest.raises(
            DESIGN.CapacityDesignRefused, match="capacity drift"):
        DESIGN.verify_design(population_path, design_path)


def test_module_has_no_launcher_surface():
    source = Path(DESIGN.__file__).read_text()
    assert "import subprocess" not in source
    assert "Popen(" not in source
    assert "run_shard(" not in source
    assert "evaluate_state(" not in source

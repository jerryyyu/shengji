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
            for _ in range(count):
                seed = offset + row_index
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
    assert design["schedule"]["logical_lanes"] == 16
    assert design["schedule"]["outputs"] == 32
    assert len(design["schedule"]["lanes"]) == 16
    assert all(lane["states_by_split"] == {"calib": 32, "dev": 32}
               for lane in design["schedule"]["lanes"])
    assert design["work"]["max_candidate_world_rollouts_per_state"] == 2_940
    assert design["work"]["max_candidate_world_rollouts_total"] == 3_010_560
    assert design["power"]["mde_at_target_power"] == pytest.approx(
        0.04043108370862586)
    assert design["power"]["power_at_worthwhile_effect"] > 0.9
    assert design["power"]["adequately_powered_at_worthwhile_effect"] is True
    assert design["scope"] == {
        "defender_states": 1_023,
        "attacker_states": 1,
        "primary_role_inference": "defender",
        "attacker_effect_estimable": False,
        "attacker_row_use": "descriptive case study only",
        "all_role_generalization_authorized": False,
        "role_stratified_reporting_required": True,
        "late_band_use": "diagnostic slice; natural weight is below 0.001",
    }


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
        DESIGN.validate_design(design)


def test_rehashed_report_admission_refuses(
        pinned_sources, population_path):
    design = DESIGN.build_design(population_path)
    design["selection"]["report_permitted"] = True
    _rehash(design)
    with pytest.raises(
            DESIGN.CapacityDesignRefused, match="boundary drift"):
        DESIGN.validate_design(design)


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
            DESIGN.CapacityDesignRefused, match="differs from reconstruction"):
        DESIGN.verify_design(population_path, design_path)


def test_module_has_no_launcher_surface():
    source = Path(DESIGN.__file__).read_text()
    assert "import subprocess" not in source
    assert "Popen(" not in source
    assert "run_shard(" not in source
    assert "evaluate_state(" not in source

"""Falsification tests for the fresh-seed S4 C2 replacement design."""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import s4_point_banking_future_cloud_c2_reseed_design as D  # noqa: E402


def test_reseed_keeps_science_work_and_automatic_transition_exact():
    assert D.design_problems() == []
    record = D.design_record()
    assert [look["clusters"] for look in record["looks"]] == [8_192, 16_384]
    assert [look["alpha"] for look in record["looks"]] == [0.025, 0.025]
    assert record["design"]["shard_count"] == 16
    assert record["design"]["cloud_cores"] == 16
    assert record["look_1_transition"][
        "efficacy_nonpass_and_integrity_pass"] == "CONTINUE_AUTOMATICALLY"
    assert record["historical_outcomes_used_for_claim"] is False
    assert record["sequential_execution_authorized"] is False


def test_complete_300b_interval_is_retired_and_360b_is_disjoint():
    retired = D.retired_population()
    primary = D.primary_population()
    assert retired.seed0 == 300_000_000_000
    assert retired.clusters == 16_384
    assert primary.seed0 == 360_000_000_000
    assert all(not D.C2.overlap(primary, old)
               for old in D.reserved_populations())
    assert D.C2.overlap(
        D.primary_population(replace(D.Design(), seed0=retired.seed0)),
        retired,
    )


def test_old_or_arbitrary_seed_cannot_publish():
    for seed0 in (300_000_000_000, 361_000_000_000):
        changed = replace(D.Design(), seed0=seed0)
        assert "fresh population seed drift" in D.design_problems(changed)
        with pytest.raises(ValueError):
            D.design_record(changed)


def test_incident_retirement_is_explicit_and_non_authorizing():
    incident = D.incident_record()
    assert incident == {
        "schema": "s4-point-banking-future-c2-reviewer-gameplay-incident-v1",
        "retired_run_id": "s4-point-banking-future-c2-300b-recovery-v2",
        "retired_git": "2649b514380e7a2e2ef40c96e8cf5b15f0da6e31",
        "retired_packet_sha256":
            "65c3cf8a3488cacc230a6f9cca2c1a2fd30bf8006f97833b67eda7d1e75916e8",
        "retired_seed0": 300_000_000_000,
        "retired_clusters": 16_384,
        "reviewer_workers_started": 16,
        "completed_shard_results": 0,
        "aggregates_published": 0,
        "finals_published": 0,
        "formal_admission_consumed": False,
        "outcomes_observed": False,
        "entire_population_retired": True,
        "old_packet_launch_authorized": False,
    }
    record = D.design_record()
    assert record["reviewer_incident"] == incident
    assert record["packet_implementation_authorized"] is False
    assert record["production_promotion"] is False
    assert record["production_deployment"] is False


def test_retired_population_is_rendered_in_exclusion_set():
    record = D.design_record()
    matches = [value for value in record["excluded_populations"]
               if value["seed0"] == 300_000_000_000]
    assert len(matches) == 1
    assert matches[0]["clusters"] == 16_384
    assert matches[0]["name"].endswith("retired-after-reviewer-gameplay")


def test_measured_capacity_still_fits_unchanged_envelope():
    projection = D.adjusted_projection()
    assert projection["fleet_hours"] == pytest.approx(869.2951536658958)
    assert projection["max_shard_hours"] == pytest.approx(
        54.330947104118486)
    assert projection["fleet_hours"] < D.MAX_PROJECTED_FLEET_HOURS
    assert projection["max_shard_hours"] < D.MAX_PROJECTED_SHARD_HOURS


def test_design_record_round_trips_and_all_authority_is_false():
    record = D.design_record()
    rendered = json.dumps(record, sort_keys=True, separators=(",", ":"))
    assert json.loads(rendered) == record
    assert record["run_id"] == "s4-point-banking-future-c2-360b-v1"
    assert record["primary_population"]["seed0"] == 360_000_000_000
    assert record["score_free_capacity_only"] is True
    assert record["packet_implementation_authorized"] is False
    assert record["sequential_execution_authorized"] is False
    assert record["strength_claim"] is False

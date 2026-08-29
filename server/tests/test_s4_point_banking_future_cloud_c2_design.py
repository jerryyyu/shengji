"""Falsification tests for the 16-shard S4 Cloud capacity successor."""
from __future__ import annotations

import copy
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import s4_point_banking_future_cloud_c2_design as D  # noqa: E402


def test_c2_keeps_scientific_target_and_uses_all_cloud_cores():
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


def test_measured_projection_fits_declared_c2_envelope():
    projection = D.adjusted_projection()
    assert projection["fleet_hours"] == pytest.approx(869.2951536658958)
    assert projection["max_shard_hours"] == pytest.approx(54.330947104118486)
    assert projection["look_1_max_shard_hours"] == pytest.approx(
        27.165473552059243)
    assert projection["fleet_hours"] < D.MAX_PROJECTED_FLEET_HOURS
    assert projection["max_shard_hours"] < D.MAX_PROJECTED_SHARD_HOURS


def test_capacity_artifact_is_exact_score_free_hold():
    assert D.sha256(D.CAPACITY_RESULT) == D.CAPACITY_RESULT_SHA256
    result = D.capacity_result()
    assert D.capacity_problems(result) == []
    assert result["status"] == "HOLD"
    assert result["score_free"] is True
    assert result["outcomes_published"] is False
    assert result["criteria"]["records_valid"] is True


@pytest.mark.parametrize(("mutation", "needle"), [
    (lambda value: value["criteria"].__setitem__(
        "records_valid", False), "criteria"),
    (lambda value: value.__setitem__(
        "sequential_launch_authorized", True), "authority"),
    (lambda value: value.__setitem__("status", "PASS"), "identity/status"),
])
def test_capacity_mutations_refuse(mutation, needle):
    value = copy.deepcopy(D.capacity_result())
    mutation(value)
    assert any(needle in problem for problem in D.capacity_problems(value))


def test_eight_shards_or_smaller_envelope_cannot_publish():
    old_geometry = replace(D.Design(), shard_count=8)
    small_fleet_cap = replace(D.Design(), max_projected_fleet_hours=768.0)
    small_shard_cap = replace(D.Design(), max_projected_shard_hours=48.0)
    assert "16-core shard geometry drift" in D.design_problems(old_geometry)
    assert "capacity envelope drift" in D.design_problems(small_fleet_cap)
    assert "capacity envelope drift" in D.design_problems(small_shard_cap)
    with pytest.raises(ValueError):
        D.design_record(old_geometry)


def test_fresh_population_excludes_c1_reservations():
    candidate = D.primary_population()
    assert all(not D.overlap(candidate, old)
               for old in D.c1_reserved_populations())
    overlap = replace(D.Design(), seed0=240_000_000_000)
    assert "fresh population seed drift" in D.design_problems(overlap)
    assert "fresh population overlaps prior reservation" in \
        D.design_problems(overlap)


def test_display_record_is_stable_and_non_authorizing():
    record = D.design_record()
    rendered = json.dumps(record, sort_keys=True, separators=(",", ":"))
    assert json.loads(rendered) == record
    assert all(isinstance(look["critical_decimal"], str)
               for look in record["looks"])
    assert record["packet_implementation_authorized"] is False
    assert record["production_deployment"] is False

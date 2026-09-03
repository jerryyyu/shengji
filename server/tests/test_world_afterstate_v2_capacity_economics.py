from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v2_capacity_economics import (
    ALLOWED_CARRY_FORWARD_PATHS, AMENDMENT_SCHEMA, CapacityEconomicsError,
    POPULATION_WALL_SECONDS_MAX,
    REPAIRED_D256_COMPLETE_DAG_WALL_SECONDS,
    RETAINED_D256_POST_POPULATION_WALL_SECONDS,
    SourceDiffV2,
    build_capacity_economics_amendment_v2,
    reopen_capacity_economics_amendment_v2_bytes,
    reopen_capacity_evidence_v2_bytes,
)
from shengji.rl.world_afterstate_v2_freeze_inputs import capacity_context


FIXTURE = Path(__file__).parent / "fixtures" / (
    "world_afterstate_v2_capacity_census11_failure.json")


def _diff() -> tuple[SourceDiffV2, ...]:
    added = {
        "server/scripts/world_afterstate_v2_capacity_economics.py",
        "server/shengji/rl/world_afterstate_v2_capacity_economics.py",
        "server/tests/fixtures/world_afterstate_v2_capacity_census11_failure.json",
        "server/tests/test_world_afterstate_v2_capacity_economics.py",
    }
    return tuple(SourceDiffV2(
        path=path, status="A" if path in added else "M",
        base_sha256=None if path in added else "d" * 64,
        current_sha256="a" * 64)
        for path in sorted(ALLOWED_CARRY_FORWARD_PATHS))


def _receipt():
    return build_capacity_economics_amendment_v2(
        base_failure_raw=FIXTURE.read_bytes(), execution_git="b" * 40,
        source_sha256="c" * 64, source_diff=_diff())


def _reseal(payload: dict[str, object]) -> bytes:
    body = {key: value for key, value in payload.items()
            if key != "capacity_economics_sha256"}
    payload["capacity_economics_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()
    return canonical_json_bytes(payload)


def test_exact_census11_failure_rederives_one_d256_amendment() -> None:
    receipt = _receipt()
    raw = canonical_json_bytes(receipt.payload())
    reopened = reopen_capacity_economics_amendment_v2_bytes(raw)

    assert reopened == receipt
    assert reopen_capacity_evidence_v2_bytes(raw) == receipt
    assert reopened.choose_tier().name == "D256"
    assert RETAINED_D256_POST_POPULATION_WALL_SECONDS == 23_065
    assert reopened.population_wall_seconds_max == 7_200
    assert POPULATION_WALL_SECONDS_MAX == 7_200
    assert reopened.tiers[0].complete_dag_wall_seconds == 30_265
    assert reopened.tiers[0].complete_dag_wall_seconds \
        == REPAIRED_D256_COMPLETE_DAG_WALL_SECONDS
    assert reopened.tiers[0].service_wall_seconds == 64_800
    assert reopened.tiers[0].eligible is True
    assert reopened.member_workers == 2
    assert reopened.continuation_workers == 16
    assert reopened.inference_batch == 256
    assert reopened.reconstruction_workers == 4


def test_freeze_context_accepts_amendment_without_widening_d256() -> None:
    raw = canonical_json_bytes(_receipt().payload())
    receipt, tier, population_workers, label_workers = capacity_context(raw)
    assert receipt.schema == AMENDMENT_SCHEMA
    assert (tier, population_workers, label_workers) == ("D256", 1, 16)


def test_changed_retained_failure_bytes_refuse_before_rederivation() -> None:
    forged = FIXTURE.read_bytes().replace(
        b'"cohort_workers":2', b'"cohort_workers":4')
    with pytest.raises(CapacityEconomicsError,
                       match="base capacity failure bytes drift"):
        build_capacity_economics_amendment_v2(
            base_failure_raw=forged, execution_git="b" * 40,
            source_sha256="c" * 64, source_diff=_diff())


def test_only_two_inherited_wall_violations_are_admissible() -> None:
    payload = _receipt().payload()
    payload["inherited_violations"] = ["complete-dag-wall"]
    with pytest.raises(CapacityEconomicsError,
                       match="capacity economics identity drift"):
        reopen_capacity_economics_amendment_v2_bytes(_reseal(payload))


def test_amended_caps_are_exact_and_cannot_drift_in_resealed_bytes() -> None:
    payload = _receipt().payload()
    payload["amended_scientific_service_seconds"] = 64_801
    with pytest.raises(CapacityEconomicsError,
                       match="capacity economics schema drift"):
        reopen_capacity_economics_amendment_v2_bytes(_reseal(payload))


def test_population_allowance_is_separate_and_load_bearing() -> None:
    payload = _receipt().payload()
    payload["population_wall_seconds_max"] -= 1
    with pytest.raises(CapacityEconomicsError,
                       match="capacity economics D256 drift"):
        reopen_capacity_economics_amendment_v2_bytes(_reseal(payload))

    payload = _receipt().payload()
    payload["tiers"][0]["complete_dag_wall_seconds"] = 23_065
    with pytest.raises(CapacityEconomicsError,
                       match="capacity economics D256 drift"):
        reopen_capacity_economics_amendment_v2_bytes(_reseal(payload))


def test_performance_affecting_source_path_is_not_allowlisted() -> None:
    assert {
        "server/shengji/rl/world_afterstate_v2_population_controller.py",
        "server/tests/test_world_afterstate_v2_population_controller.py",
    } <= ALLOWED_CARRY_FORWARD_PATHS
    with pytest.raises(CapacityEconomicsError,
                       match="carry-forward source diff drift"):
        SourceDiffV2(
            path="server/shengji/rl/world_afterstate_v2_model.py",
            status="M", base_sha256="d" * 64,
            current_sha256="e" * 64).validate()


def test_reopened_amendment_requires_the_complete_reviewed_diff() -> None:
    payload = _receipt().payload()
    payload["source_diff"] = payload["source_diff"][:-1]
    with pytest.raises(CapacityEconomicsError,
                       match="carry-forward source diff population drift"):
        reopen_capacity_economics_amendment_v2_bytes(_reseal(payload))

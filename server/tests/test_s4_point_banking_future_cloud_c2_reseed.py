"""Fail-closed checks for the fresh-360B S4 C2 runtime/controller."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import s4_point_banking_future_c2 as RETIRED  # noqa: E402

RETIRED_RUN_ID = RETIRED.RUN_ID

import s4_point_banking_future_c2_reseed as CORE  # noqa: E402
import s4_point_banking_future_cloud_c2_reseed as CTRL  # noqa: E402
import s4_point_banking_future_cloud_c2_reseed_design as DESIGN  # noqa: E402


def _config() -> CTRL.Config:
    return CTRL.Config(
        expected_git="a" * 40,
        expected_runner_sha256="b" * 64,
        expected_controller_sha256="c" * 64,
        heartbeat_seconds=30.0,
    )


def _raw(marker: str, value: dict) -> bytes:
    return (marker + json.dumps(
        value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def test_import_does_not_mutate_retired_c2_protocol():
    assert RETIRED.RUN_ID == RETIRED_RUN_ID
    assert RETIRED.RUN_ID.endswith("300b-recovery-v2")
    assert CORE.RUN_ID == "s4-point-banking-future-c2-360b-v1"
    assert CORE.RUN_ID != RETIRED.RUN_ID


def test_schedule_uses_only_fresh_360b_population():
    schedule = CORE.schedule()
    assert schedule["seed0"] == 360_000_000_000
    assert schedule["looks"] == [8_192, 16_384]
    assert schedule["shard_count"] == 16
    assert schedule["tranche_clusters_per_shard"] == 512
    indexes = [CORE.shard_indexes(index, tranche=1)
               for index in range(16)]
    assert sorted(value for values in indexes for value in values) == list(
        range(8_192))


def test_commands_name_only_reseed_runner_and_namespace():
    command = CORE.command_template(2, 15)
    assert command[1] == "server/scripts/s4_point_banking_future_c2_reseed.py"
    assert command[command.index("--shard-index") + 1] == "15"
    assert str(CORE.NAMESPACE) in command[-1]
    validation = CORE.runtime_validation_template()
    assert validation[1] == (
        "server/scripts/s4_point_banking_future_c2_reseed.py")
    assert str(CORE.NAMESPACE / "receipt.json") in validation


def test_retirement_record_excludes_complete_old_interval():
    record = CORE.retired_population_record()
    assert record["reviewer_incident"] == DESIGN.incident_record()
    assert record["population"]["seed0"] == 300_000_000_000
    assert record["population"]["clusters"] == 16_384
    assert record["population"]["high"] < DESIGN.primary_population().low
    assert record["entire_interval_excluded"] is True
    assert record["outcomes_used_for_claim"] is False


def test_design_review_claim_byte_matches_signed_authority():
    assert CTRL.design_review_claim() == {
        "capacity_result_sha256": DESIGN.C2.CAPACITY_RESULT_SHA256,
        "design_sha256": hashlib.sha256(
            Path(DESIGN.__file__).read_bytes()).hexdigest(),
        "git": "8c262f77c97c33b68bdda8a37b71236f3a92b246",
        "implementation_authorized": True,
        "look_alphas": [0.025, 0.025],
        "look_clusters": [8_192, 16_384],
        "new_preflight_authorized": False,
        "primary_seed0": 360_000_000_000,
        "production_deployment": False,
        "production_promotion": False,
        "retired_packet_sha256": DESIGN.RETIRED_PACKET_SHA256,
        "retired_seed0": 300_000_000_000,
        "schema": "s4-point-banking-future-c2-reseed-design-review-v1",
        "scored_execution_authorized": False,
        "shard_count": 16,
        "strength_claim": False,
        "verdict": "PASS_TO_IMPLEMENT",
    }


def test_review_markers_are_exact_raw_singletons(tmp_path):
    config = _config()
    design = CTRL.design_review_claim()
    controller = CTRL.controller_review_claim(config)
    combined = (
        _raw(CTRL.DESIGN_REVIEW_MARKER, design)
        + _raw(CTRL.CONTROLLER_REVIEW_MARKER, controller))
    path = tmp_path / "review.md"
    path.write_bytes(combined)
    assert CTRL.design_review_evidence(path)["verdict"] == "PASS_TO_IMPLEMENT"
    assert CTRL.controller_review_evidence(combined, config) == controller
    with pytest.raises(CTRL.SupervisorRefused, match="exactly one"):
        CTRL.controller_review_evidence(
            combined + _raw(CTRL.CONTROLLER_REVIEW_MARKER, controller),
            config)
    with pytest.raises(CTRL.SupervisorRefused, match="exactly one"):
        CTRL.controller_review_evidence(
            b"    " + _raw(CTRL.CONTROLLER_REVIEW_MARKER, controller),
            config)


def test_controller_claim_allows_freeze_but_not_execution():
    claim = CTRL.controller_review_claim(_config())
    assert claim["packet_freeze_authorized"] is True
    assert claim["new_preflight_authorized"] is False
    assert claim["sequential_execution_authorized"] is False
    assert claim["strength_claim"] is False
    assert claim["expected_host"] == "ubuntu-32gb-hel1-1"
    assert claim["expected_python"] == "3.14.4"
    assert claim["retired_population"] == CORE.retired_population_record()
    assert claim["fresh_namespace"] == CORE.RUN_ID


def test_mutated_controller_authority_refuses():
    config = _config()
    claim = CTRL.controller_review_claim(config)
    claim["sequential_execution_authorized"] = True
    with pytest.raises(CTRL.SupervisorRefused, match="wrong authority"):
        CTRL.controller_review_evidence(
            _raw(CTRL.CONTROLLER_REVIEW_MARKER, claim), config)


def test_capacity_reuse_is_score_free_and_inside_16_core_envelope():
    evidence = CTRL.capacity_evidence()
    assert evidence["sha256"] == DESIGN.C2.CAPACITY_RESULT_SHA256
    assert evidence["score_free"] is True
    assert evidence["outcomes_published"] is False
    assert evidence["old_shard_count"] == 8
    assert evidence["new_shard_count"] == 16
    assert evidence["new_preflight_run"] is False
    assert evidence["preflight_retry_authorized"] is False
    assert evidence["criteria"]["all"] is True
    assert evidence["projection"]["fleet_hours"] < 1_024
    assert evidence["projection"]["max_shard_hours"] < 64


def test_packet_contract_binds_controller_and_retirement():
    config = _config()
    paths = CTRL.paths_for()
    controller = CTRL.controller_review_claim(config)
    packet = CTRL.packet_contract(
        config, paths,
        parent={"champion": "report-lcb"},
        runtime={"host": CTRL.EXPECTED_HOST},
        preflight=CTRL.capacity_evidence(),
        design_review={"sha256": "d" * 64},
        controller_review=controller,
        retired_population=CORE.retired_population_record(),
    )
    assert packet["schema"] == CORE.PACKET_SCHEMA
    assert packet["schedule"]["seed0"] == 360_000_000_000
    assert packet["controller_implementation_review"] == controller
    assert packet["retired_population"] == CORE.retired_population_record()
    assert packet["new_preflight_run"] is False
    assert packet["sequential_launch_authorized"] is False
    with pytest.raises(CTRL.SupervisorRefused, match="retired-population"):
        CTRL.packet_contract(
            config, paths, parent={}, runtime={},
            preflight=CTRL.capacity_evidence(), design_review={},
            controller_review=controller, retired_population={})


def test_child_packet_profile_reopens_all_added_fields():
    config = CTRL.Config(
        expected_git="a" * 40,
        expected_runner_sha256=CTRL.sha256_file(CORE.SCRIPT),
        expected_controller_sha256="c" * 64,
        heartbeat_seconds=30.0,
    )
    claim = CTRL.controller_review_claim(config)
    runtime = {
        "host": claim["expected_host"],
        "python": claim["expected_python"],
        "fast_binary_sha256": claim["expected_fast_binary_sha256"],
    }
    packet = {
        "implementation_sources": {
            "base_runner_sha256": CTRL.sha256_file(CORE.BASE_RUNNER),
            "base_controller_sha256": CTRL.sha256_file(CTRL.BASE_CONTROLLER),
        },
        "controller_implementation_review": claim,
        "new_preflight_run": False,
        "retired_population": CORE.retired_population_record(),
    }
    receipt = {"controller_sha256": config.expected_controller_sha256}
    assert CORE.packet_profile_problems(
        packet, expected_git=config.expected_git, receipt=receipt,
        current_runtime=runtime) == []
    for field in ("implementation_sources",
                  "controller_implementation_review",
                  "new_preflight_run", "retired_population"):
        mutated = copy.deepcopy(packet)
        mutated[field] = True
        assert CORE.packet_profile_problems(
            mutated, expected_git=config.expected_git, receipt=receipt,
            current_runtime=runtime)


def test_preflight_retry_is_unreachable():
    with pytest.raises(CTRL.SupervisorRefused, match="forbids"):
        CTRL.run_score_free_preflight()
    with pytest.raises(SystemExit):
        CTRL.main([
            "run-preflight",
            "--expected-git", "a" * 40,
            "--expected-runner-sha256", "b" * 64,
            "--expected-controller-sha256", "c" * 64,
        ])


def test_freeze_validates_runtime_before_first_namespace_write(
        tmp_path, monkeypatch):
    config = _config()
    review = tmp_path / "combined-review.md"
    review.write_bytes(
        _raw(CTRL.DESIGN_REVIEW_MARKER, CTRL.design_review_claim())
        + _raw(CTRL.CONTROLLER_REVIEW_MARKER,
               CTRL.controller_review_claim(config)))
    namespace = tmp_path / "fresh-360b"
    paths = replace(
        CTRL.paths_for(), namespace=namespace,
        design_review_copy=namespace / "design-review-record.txt",
        packet=namespace / "launch_packet.json")
    monkeypatch.setattr(CTRL._CTRL, "paths_for", lambda: paths)

    def refuse_runtime(_config, _paths):
        raise CTRL.SupervisorRefused("runtime refused before write")

    monkeypatch.setattr(CTRL, "_identity_context", refuse_runtime)
    with pytest.raises(CTRL.SupervisorRefused, match="before write"):
        CTRL.freeze_packet(
            config, review, hashlib.sha256(review.read_bytes()).hexdigest())
    assert not namespace.exists()


def test_runtime_profile_design_and_claim_are_exact():
    assert CORE.DESIGN_RECORD == DESIGN.design_record()
    assert CORE.DESIGN_RECORD["historical_outcomes_used_for_claim"] is False
    assert CORE.DESIGN_RECORD["sequential_execution_authorized"] is False
    assert "complete 300B interval is retired" in CORE.CLAIM_BOUNDARY
    assert CORE.PACKET_EXTRA_FIELDS == frozenset({
        "controller_implementation_review", "implementation_sources",
        "new_preflight_run", "retired_population"})

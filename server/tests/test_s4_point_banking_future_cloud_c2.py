"""Fail-closed checks for the compact 16-shard S4 C2 profile."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import s4_point_banking_future as C1  # noqa: E402

C1_RUN_ID = C1.RUN_ID
C1_SHARDS = C1.SHARD_COUNT

import s4_point_banking_future_c2 as CORE  # noqa: E402
import s4_point_banking_future_cloud_c2 as CTRL  # noqa: E402
import s4_point_banking_future_cloud_c2_design as DESIGN  # noqa: E402


def _config() -> CTRL.Config:
    return CTRL.Config(
        expected_git="a" * 40,
        expected_runner_sha256="b" * 64,
        expected_controller_sha256="c" * 64,
        heartbeat_seconds=30.0)


def _raw(marker: str, value: dict) -> bytes:
    return (marker + json.dumps(
        value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def test_import_does_not_mutate_closed_c1_protocol():
    assert C1.RUN_ID == C1_RUN_ID
    assert C1.SHARD_COUNT == C1_SHARDS == 8
    assert CORE.RUN_ID == DESIGN.RUN_ID
    assert CORE.SHARD_COUNT == 16


def test_c2_schedule_is_exactly_two_fresh_sixteen_shard_tranches():
    schedule = CORE.schedule()
    assert schedule["seed0"] == 300_000_000_000
    assert schedule["looks"] == [8_192, 16_384]
    assert schedule["shard_count"] == 16
    assert schedule["tranche_clusters_per_shard"] == 512
    assert len(CORE.SHARD_NAMES) == 32
    for tranche in (1, 2):
        indexes = [CORE.shard_indexes(i, tranche=tranche)
                   for i in range(16)]
        assert all(len(values) == 512 for values in indexes)
        assert sorted(value for values in indexes for value in values) == (
            list(range(0, 8_192)) if tranche == 1
            else list(range(8_192, 16_384)))


def test_commands_name_only_the_c2_runner_and_namespace():
    command = CORE.command_template(2, 15)
    assert command[1] == "server/scripts/s4_point_banking_future_c2.py"
    assert "--shard-index" in command
    assert command[command.index("--shard-index") + 1] == "15"
    assert str(CORE.NAMESPACE) in command[-1]


def test_capacity_reuse_is_score_free_and_passes_only_adjusted_envelope():
    evidence = CTRL.capacity_evidence()
    assert evidence["sha256"] == DESIGN.CAPACITY_RESULT_SHA256
    assert evidence["score_free"] is True
    assert evidence["outcomes_published"] is False
    assert evidence["source_status"] == "HOLD"
    assert evidence["source_admission"]["sha256"] == (
        DESIGN.CAPACITY_ADMISSION_SHA256)
    assert evidence["status"] == "AUTHORIZE_SEQUENTIAL_PACKET_REVIEW"
    assert evidence["old_shard_count"] == 8
    assert evidence["new_shard_count"] == 16
    assert evidence["new_preflight_run"] is False
    assert evidence["preflight_retry_authorized"] is False
    assert evidence["criteria"]["all"] is True


def test_controller_claim_authorizes_freeze_but_no_run():
    claim = CTRL.controller_review_claim(_config())
    assert claim["packet_freeze_authorized"] is True
    assert claim["new_preflight_authorized"] is False
    assert claim["sequential_execution_authorized"] is False
    assert claim["strength_claim"] is False
    assert claim["expected_host"] == "ubuntu-32gb-hel1-1"
    assert claim["expected_python"] == "3.14.4"
    assert claim["expected_fast_binary_sha256"] == CTRL.EXPECTED_FAST_SHA256


def test_review_markers_are_exact_raw_singletons():
    config = _config()
    design = CTRL.design_review_claim()
    controller = CTRL.controller_review_claim(config)
    combined = (
        _raw(CTRL.DESIGN_REVIEW_MARKER, design)
        + _raw(CTRL.CONTROLLER_REVIEW_MARKER, controller))
    assert CTRL.controller_review_evidence(combined, config) == controller
    with pytest.raises(CTRL.SupervisorRefused, match="exactly one"):
        CTRL.controller_review_evidence(
            combined + _raw(CTRL.CONTROLLER_REVIEW_MARKER, controller),
            config)
    indented = b"    " + _raw(CTRL.CONTROLLER_REVIEW_MARKER, controller)
    with pytest.raises(CTRL.SupervisorRefused, match="exactly one"):
        CTRL.controller_review_evidence(indented, config)
    mutated = copy.deepcopy(controller)
    mutated["sequential_execution_authorized"] = True
    with pytest.raises(CTRL.SupervisorRefused, match="wrong authority"):
        CTRL.controller_review_evidence(
            _raw(CTRL.CONTROLLER_REVIEW_MARKER, mutated), config)


def test_design_review_claim_binds_reviewed_source_bytes(tmp_path):
    claim = CTRL.design_review_claim()
    assert claim["design_sha256"] == hashlib.sha256(
        Path(DESIGN.__file__).read_bytes()).hexdigest()
    path = tmp_path / "review.md"
    path.write_bytes(_raw(CTRL.DESIGN_REVIEW_MARKER, claim))
    evidence = CTRL.design_review_evidence(path)
    assert evidence["git"] == CORE.DESIGN_REVIEW_GIT
    claim["preflight_retry_authorized"] = True
    path.write_bytes(_raw(CTRL.DESIGN_REVIEW_MARKER, claim))
    with pytest.raises(CTRL.SupervisorRefused, match="authority drift"):
        CTRL.design_review_evidence(path)


def test_packet_contract_binds_reused_sources_and_review():
    config = _config()
    paths = CTRL.paths_for()
    controller = CTRL.controller_review_claim(config)
    packet = CTRL.packet_contract(
        config, paths,
        parent={"champion": "report-lcb"},
        runtime={"host": CTRL.EXPECTED_HOST},
        preflight=CTRL.capacity_evidence(),
        design_review={"sha256": "d" * 64},
        controller_review=controller)
    assert packet["schema"] == CORE.PACKET_SCHEMA
    assert packet["schedule"]["shard_count"] == 16
    assert packet["controller_implementation_review"] == controller
    assert packet["new_preflight_run"] is False
    assert packet["sequential_launch_authorized"] is False
    assert packet["implementation_sources"] == {
        "base_runner_sha256": CTRL.sha256_file(CORE.BASE_RUNNER),
        "base_controller_sha256": CTRL.sha256_file(CTRL.BASE_CONTROLLER),
    }
    with pytest.raises(CTRL.SupervisorRefused, match="did not authorize"):
        CTRL.packet_contract(
            config, paths, parent={}, runtime={},
            preflight=CTRL.capacity_evidence(), design_review={},
            controller_review=None)


def test_preflight_retry_is_not_reachable():
    with pytest.raises(CTRL.SupervisorRefused, match="forbids"):
        CTRL.run_score_free_preflight()
    with pytest.raises(SystemExit):
        CTRL.main([
            "run-preflight",
            "--expected-git", "a" * 40,
            "--expected-runner-sha256", "b" * 64,
            "--expected-controller-sha256", "c" * 64,
        ])


def test_review_claim_pins_reused_implementation_sources():
    claim = CTRL.controller_review_claim(_config())
    assert claim["base_runner_sha256"] == CTRL.sha256_file(CORE.BASE_RUNNER)
    assert claim["base_controller_sha256"] == CTRL.sha256_file(
        CTRL.BASE_CONTROLLER)
    assert len(claim["runner_sha256"]) == 64
    assert len(claim["controller_sha256"]) == 64

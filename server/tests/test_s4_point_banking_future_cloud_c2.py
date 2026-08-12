"""Fail-closed checks for the compact 16-shard S4 C2 profile."""
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
    assert CORE.FAILED_RUN_ID == DESIGN.RUN_ID
    assert CORE.FAILED_FREEZE_RUN_ID.endswith("-recovery-v1")
    assert CORE.RUN_ID.endswith("-recovery-v2")
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
    validation = CORE.runtime_validation_template()
    assert validation[1] == "server/scripts/s4_point_banking_future_c2.py"
    assert validation[2] == "validate-runtime"
    assert str(CORE.NAMESPACE / "receipt.json") in validation


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
    assert claim["failed_launch"] == CORE.recovery_source_record()
    assert claim["failed_freeze"] == CORE.failed_freeze_record()
    assert claim["fresh_recovery_namespace"] == CORE.RUN_ID
    assert claim["child_boundary_validation_required"] is True
    assert claim["runtime_validation_before_first_write"] is True


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


def test_literal_signed_design_review_marker_is_consumable(tmp_path):
    raw = (
        b'S4_POINT_BANKING_FUTURE_C2_DESIGN_V1_REVIEW '
        b'{"capacity_result_sha256":"70a15405c7edb94ecfdd89fb8c86d158ba64d8161eeba82c57851b67d513413e",'
        b'"design_sha256":"303f1642a8d5754f3243afc576163c8ea4d0ab744487c4af9aee92864f7f76b0",'
        b'"git":"f0c2a6de07b828535d17350c1c3206942175ad45",'
        b'"implementation_authorized":true,"look_clusters":[8192,16384],'
        b'"preflight_retry_authorized":false,"production_deployment":false,'
        b'"production_promotion":false,'
        b'"schema":"s4-point-banking-future-c2-design-review-v1",'
        b'"scored_execution_authorized":false,"shard_count":16,'
        b'"strength_claim":false,"verdict":"PASS_TO_IMPLEMENT"}\n'
    )
    path = tmp_path / "literal-signed-design-review.md"
    path.write_bytes(raw)
    assert CTRL.design_review_evidence(path)["verdict"] == (
        "PASS_TO_IMPLEMENT")


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
        controller_review=controller,
        recovery_source=CORE.recovery_source_record(),
        failed_freeze_source=CORE.failed_freeze_record())
    assert packet["schema"] == CORE.PACKET_SCHEMA
    assert packet["schedule"]["shard_count"] == 16
    assert packet["controller_implementation_review"] == controller
    assert packet["new_preflight_run"] is False
    assert packet["recovery_source"] == CORE.recovery_source_record()
    assert packet["failed_freeze_source"] == CORE.failed_freeze_record()
    assert packet["sequential_launch_authorized"] is False
    assert packet["implementation_sources"] == {
        "base_runner_sha256": CTRL.sha256_file(CORE.BASE_RUNNER),
        "base_controller_sha256": CTRL.sha256_file(CTRL.BASE_CONTROLLER),
    }
    with pytest.raises(CTRL.SupervisorRefused, match="did not authorize"):
        CTRL.packet_contract(
            config, paths, parent={}, runtime={},
            preflight=CTRL.capacity_evidence(), design_review={},
            controller_review=None,
            recovery_source=CORE.recovery_source_record(),
            failed_freeze_source=CORE.failed_freeze_record())


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


def test_freeze_validates_runtime_before_first_namespace_write(
        tmp_path, monkeypatch):
    config = _config()
    review = tmp_path / "combined-review.md"
    review.write_bytes(
        _raw(CTRL.DESIGN_REVIEW_MARKER, CTRL.design_review_claim())
        + _raw(CTRL.CONTROLLER_REVIEW_MARKER,
               CTRL.controller_review_claim(config)))
    namespace = tmp_path / "fresh-recovery"
    paths = replace(
        CTRL.paths_for(),
        namespace=namespace,
        design_review_copy=namespace / "design-review-record.txt",
        packet=namespace / "launch_packet.json",
    )
    monkeypatch.setattr(CTRL._CTRL, "paths_for", lambda: paths)

    def refuse_runtime(_config, _paths):
        raise CTRL.SupervisorRefused("runtime refused before write")

    monkeypatch.setattr(CTRL, "_identity_context", refuse_runtime)
    with pytest.raises(CTRL.SupervisorRefused, match="before write"):
        CTRL.freeze_packet(
            config, review, hashlib.sha256(review.read_bytes()).hexdigest())
    assert not namespace.exists()


def test_failed_freeze_evidence_requires_exactly_the_review_snapshot(
        tmp_path, monkeypatch):
    raw = b"immutable review snapshot\n"
    digest = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(CORE, "FAILED_FREEZE_REVIEW_SHA256", digest)
    monkeypatch.setattr(CTRL._CTRL, "ROOT", tmp_path)
    namespace = (
        tmp_path / "server/runs/logs" / CORE.FAILED_FREEZE_RUN_ID)
    namespace.mkdir(parents=True)
    (namespace / "design-review-record.txt").write_bytes(raw)
    assert CTRL.failed_freeze_evidence() == CORE.failed_freeze_record()
    (namespace / "launch_packet.json").write_text("{}", encoding="utf-8")
    with pytest.raises(CTRL.SupervisorRefused, match="exactly one file"):
        CTRL.failed_freeze_evidence()


def test_child_receipt_reopens_the_exact_c2_packet(tmp_path, monkeypatch):
    """Exercise the child-only gate that controller verification cannot see."""
    runner_sha = hashlib.sha256(Path(CORE.__file__).read_bytes()).hexdigest()
    controller_sha = hashlib.sha256(
        Path(CTRL.__file__).read_bytes()).hexdigest()
    config = CTRL.Config(
        expected_git="a" * 40,
        expected_runner_sha256=runner_sha,
        expected_controller_sha256=controller_sha,
        heartbeat_seconds=30.0,
    )
    parent = {"policy": "literal-live-report-lcb"}
    runtime = {
        "host": CTRL.EXPECTED_HOST,
        "python": CTRL.EXPECTED_PYTHON,
        "fast_binary_sha256": CTRL.EXPECTED_FAST_SHA256,
    }
    namespace = tmp_path / CORE.NAMESPACE
    namespace.mkdir(parents=True)

    design_review_raw = b"reviewed C2 design and controller\n"
    design_review_sha = hashlib.sha256(design_review_raw).hexdigest()
    design_review = {
        "path": str(CORE.NAMESPACE / "design-review-record.txt"),
        "sha256": design_review_sha,
        "git": CORE.DESIGN_REVIEW_GIT,
        "verdict": "PASS_TO_IMPLEMENT",
        "implementation_authorized": True,
    }
    packet = CTRL.packet_contract(
        config, CTRL.paths_for(), parent=parent, runtime=runtime,
        preflight=CTRL.capacity_evidence(),
        design_review=design_review,
        controller_review=CTRL.controller_review_claim(config),
        recovery_source=CORE.recovery_source_record(),
        failed_freeze_source=CORE.failed_freeze_record(),
    )
    packet_path = namespace / "launch_packet.json"
    packet_path.write_text(json.dumps(packet, sort_keys=True), encoding="utf-8")
    packet_sha = hashlib.sha256(packet_path.read_bytes()).hexdigest()

    review_claim = CORE.expected_review_claim(
        expected_git=config.expected_git,
        packet_sha256=packet_sha,
        preflight_sha256=DESIGN.CAPACITY_RESULT_SHA256,
        design_review_sha256=design_review_sha,
    )
    review_raw = _raw(CORE.PACKET_REVIEW_MARKER, review_claim)
    review_path = namespace / "review_record.txt"
    review_path.write_bytes(review_raw)
    review_sha = hashlib.sha256(review_raw).hexdigest()
    admission = {
        "schema": CORE.ADMISSION_SCHEMA,
        "run_id": CORE.RUN_ID,
        "packet": {"path": str(CORE.NAMESPACE / "launch_packet.json"),
                   "sha256": packet_sha},
        "review": {"path": str(CORE.NAMESPACE / "review_record.txt"),
                   "sha256": review_sha},
        "review_claim": review_claim,
        "operator_asserted_independent_review": True,
        "sequential_launch_authorized": True,
        "tranche_2_pre_authorized": True,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
    }
    admission_path = namespace / "review_admission.json"
    admission_path.write_text(
        json.dumps(admission, sort_keys=True), encoding="utf-8")
    admission_sha = hashlib.sha256(admission_path.read_bytes()).hexdigest()

    (namespace / "design-review-record.txt").write_bytes(design_review_raw)
    capacity_path = tmp_path / CORE._CORE.PREFLIGHT_RESULT_PATH
    capacity_path.parent.mkdir(parents=True, exist_ok=True)
    capacity_path.write_bytes(DESIGN.CAPACITY_RESULT.read_bytes())
    controller_path = tmp_path / CORE._CORE.CONTROLLER_PATH
    controller_path.parent.mkdir(parents=True, exist_ok=True)
    controller_path.write_bytes(Path(CTRL.__file__).read_bytes())

    receipt = {
        "schema": CORE.RECEIPT_SCHEMA,
        "run_id": CORE.RUN_ID,
        "complete": True,
        "git": config.expected_git,
        "runner_sha256": runner_sha,
        "controller_sha256": controller_sha,
        "design_sha256": hashlib.sha256(
            Path(DESIGN.__file__).read_bytes()).hexdigest(),
        "created_time_ns": 1,
        "nonce": "0" * 64,
        "packet_sha256": packet_sha,
        "admission_sha256": admission_sha,
        "preflight_sha256": DESIGN.CAPACITY_RESULT_SHA256,
        "design_review_sha256": design_review_sha,
        "sequential_launch_authorized": True,
        "tranche_2_pre_authorized": True,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "retry_or_extension_authorized": False,
    }
    receipt_path = namespace / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
    receipt_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()

    monkeypatch.setattr(CORE._CORE, "REPO", tmp_path)
    monkeypatch.setattr(
        CORE._CORE, "require_runtime",
        lambda expected_git: (parent, runtime),
    )
    assert CORE.require_receipt(
        receipt_path, receipt_sha,
        expected_git=config.expected_git) == {
            "path": str(CORE.NAMESPACE / "receipt.json"),
            "sha256": receipt_sha,
        }
    monkeypatch.chdir(tmp_path)
    assert CORE.require_receipt(
        CORE.NAMESPACE / "receipt.json", receipt_sha,
        expected_git=config.expected_git) == {
            "path": str(CORE.NAMESPACE / "receipt.json"),
            "sha256": receipt_sha,
        }

    capacity_path.unlink()
    with pytest.raises(CORE.ProtocolRefused, match="preflight is missing"):
        CORE.require_receipt(
            receipt_path, receipt_sha,
            expected_git=config.expected_git)

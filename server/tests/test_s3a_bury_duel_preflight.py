"""Falsification tests for the one-shot S3a duel sizing controller."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import s3a_bury_duel_preflight as SUP  # noqa: E402


def _config(**changes) -> SUP.Config:
    values = {
        "expected_git": "a" * 40,
        "expected_runner_sha256": "b" * 64,
        "expected_controller_sha256": "c" * 64,
        "expected_host": "Jerrys-Mac-mini.local",
        "screen_fleet_hours": 1_000.0,
        "screen_max_shard_hours": 1_000.0,
        "confirm_fleet_hours": 1_000.0,
        "confirm_max_shard_hours": 1_000.0,
        "heartbeat_seconds": 30.0,
    }
    values.update(changes)
    return SUP.Config(**values)


def _paths(tmp_path: Path) -> SUP.Paths:
    namespace = tmp_path / SUP.RUN_ID
    return SUP.Paths(
        namespace=namespace,
        runner=tmp_path / "runner.py",
        controller=tmp_path / "controller.py",
        receipt=namespace / SUP.RECEIPT_NAME,
        preflight=namespace / SUP.PREFLIGHT_NAME,
        log_partial=namespace / f"{SUP.LOG_NAME}.partial",
        log_final=namespace / SUP.LOG_NAME,
        exit_final=namespace / SUP.EXIT_NAME,
        progress_partial=namespace / f"{SUP.PROGRESS_NAME}.partial",
        progress_final=namespace / SUP.PROGRESS_NAME,
        final=namespace / SUP.FINAL_NAME,
    )


def _parent() -> dict:
    return {"champion_policy": SUP.DUEL.CHAMPION}


def _runtime() -> dict:
    return {
        "git": "a" * 40,
        "tree_dirty": False,
        "host": "Jerrys-Mac-mini.local",
        "python": SUP.EXPECTED_PYTHON,
        "fast_engine": True,
        "require_voids": True,
        "experimental_flags": [],
        "source_sha256s": {"runner": "d" * 64},
        "fast_binary_sha256": "e" * 64,
        "policy_contract_sha256s": {"policy": "f" * 64},
        "stream_digests": {
            "preflight": "1" * 64,
            "screen": "2" * 64,
            "confirm": "3" * 64,
        },
    }


def _zero_telemetry() -> dict:
    return {
        name: 0 for name in SUP.DUEL.STRUCTURED_BURY_TELEMETRY_FIELDS}


def _structured_telemetry() -> dict:
    value = _zero_telemetry()
    value.update({
        "opportunities": 1,
        "triggers": 1,
        "overrides": 1,
        "candidate_count_sum": 2,
        "searches": 1,
        "complete_searches": 1,
        "worlds_requested": 8,
        "worlds_used": 8,
        "candidate_world_budget": 16,
        "candidate_rollouts": 16,
        "sample_attempts": 8,
        "accepted_worlds": 8,
    })
    return value


def _payload(config: SUP.Config | None = None) -> dict:
    config = config or _config()
    seconds = 10.0
    projections = {
        phase: {
            "fleet_hours": (
                seconds * spec["clusters"] *
                SUP.DUEL.THROUGHPUT_SAFETY_FACTOR / 3_600),
            "max_shard_hours": (
                seconds * spec["clusters_per_shard"] *
                SUP.DUEL.THROUGHPUT_SAFETY_FACTOR / 3_600),
        }
        for phase, spec in SUP.DUEL.PHASES.items()
    }
    counter_fields = set(SUP.DUEL.counters([])) - {"search_secs"}
    counters = {
        label: {name: 0 for name in counter_fields}
        for label in SUP.DUEL.LABEL_ORDER
    }
    counters["structured"].update({
        "searches": 1,
        "rollouts": 16,
        "sample_attempts": 8,
        "accepted_worlds": 8,
    })
    return {
        "schema": SUP.DUEL.PREFLIGHT_SCHEMA,
        "complete": True,
        "score_free": True,
        "clusters": SUP.DUEL.PREFLIGHT_CLUSTERS,
        "run_id": SUP.RUN_ID,
        "seed0": SUP.DUEL.PREFLIGHT_SEED0,
        "stream_stride": SUP.DUEL.STREAM_STRIDE,
        "parent": _parent(),
        "runtime": _runtime(),
        "elapsed_seconds": seconds * SUP.DUEL.PREFLIGHT_CLUSTERS,
        "seconds_per_cluster": seconds,
        "integer_counters": counters,
        "structured_bury_telemetry": {
            "structured": _structured_telemetry(),
            "champion": _zero_telemetry(),
            "null": _zero_telemetry(),
        },
        "projections": projections,
        "throughput_safety_factor": SUP.DUEL.THROUGHPUT_SAFETY_FACTOR,
        "problems": [],
        "budgets": config.budgets,
        "capacity_pass": True,
        "strength_launch_authorized": False,
        "production_promotion": False,
    }


def _keys(value) -> set[str]:
    keys = set()
    if isinstance(value, dict):
        keys.update(value)
        for item in value.values():
            keys.update(_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(_keys(item))
    return keys


def test_packet_freezes_score_free_geometry_command_and_authority(tmp_path):
    config = _config()
    paths = _paths(tmp_path)
    contract = SUP.packet_contract(
        config, paths, parent=_parent(), runtime=_runtime())
    assert contract["run_id"] == SUP.DUEL.PREFLIGHT_RUN_ID
    assert contract["host"] == "Jerrys-Mac-mini.local"
    assert contract["python_version"] == "3.14.3"
    assert contract["runtime"]["python"] == "3.14.3"
    assert contract["population"]["clusters"] == 4
    assert contract["population"]["global_stream_separation"] is True
    assert contract["capacity"]["screen"]["clusters"] == 2_048
    assert contract["capacity"]["confirm"]["clusters"] == 8_192
    assert contract["teacher_release"] == {
        "required_before_namespace_creation": True,
        "supervisor_final": str(SUP.TEACHER_PROGRESS_FINAL),
        "supervisor_partial": str(SUP.TEACHER_PROGRESS_PARTIAL),
        "terminal_regular_final_required": True,
        "partial_absent_required": True,
        "live_supervisor_and_workers_absent_required": True,
    }
    assert contract["command"] == list(
        SUP.preflight_argv(config, paths.preflight))
    assert contract["gate"]["strength_launch_authorized"] is False
    assert contract["gate"]["production_promotion"] is False
    assert not (_keys(contract) & SUP.FORBIDDEN_OUTCOME_KEYS)


def test_teacher_exclusivity_requires_terminal_final_and_no_live_process(
        tmp_path, monkeypatch):
    final = tmp_path / "champion_audit_supervisor_v2.jsonl"
    partial = Path(str(final) + ".partial")
    monkeypatch.setattr(SUP, "TEACHER_PROGRESS_FINAL", final)
    monkeypatch.setattr(SUP, "TEACHER_PROGRESS_PARTIAL", partial)
    monkeypatch.setattr(SUP, "TEACHER_AUDIT_ROOT", tmp_path)
    monkeypatch.setattr(SUP, "_process_table", lambda: "")

    assert SUP.teacher_exclusivity_problems() == [
        "Teacher supervisor final is not terminal/regular"]

    final.write_text("terminal\n")
    partial.write_text("partial\n")
    assert SUP.teacher_exclusivity_problems() == [
        "Teacher supervisor partial still exists"]

    partial.unlink()
    monkeypatch.setattr(
        SUP, "_process_table",
        lambda: (
            f"123 /opt/python {tmp_path}/scripts/"
            "teacher_v1_champion_audit.py label --receipt evidence\n"
            f"124 /opt/python {tmp_path}/scripts/"
            "teacher_champion_audit_supervisor.py --audit-root "
            f"{tmp_path}\n"
            "125 /opt/python unrelated.py\n"),
    )
    assert SUP.teacher_exclusivity_problems() == [
        "live Teacher supervisor/worker processes remain: 123,124"]

    monkeypatch.setattr(SUP, "_process_table", lambda: "125 unrelated.py\n")
    assert SUP.teacher_exclusivity_problems() == []


def test_teacher_exclusivity_fails_closed_when_process_table_unavailable(
        tmp_path, monkeypatch):
    final = tmp_path / "champion_audit_supervisor_v2.jsonl"
    final.write_text("terminal\n")
    monkeypatch.setattr(SUP, "TEACHER_PROGRESS_FINAL", final)
    monkeypatch.setattr(
        SUP, "TEACHER_PROGRESS_PARTIAL", Path(str(final) + ".partial"))

    def fail():
        raise OSError("ps unavailable")

    monkeypatch.setattr(SUP, "_process_table", fail)
    assert SUP.teacher_exclusivity_problems() == [
        "cannot prove Teacher process absence"]


def test_config_refuses_malformed_host_hash_budget_and_heartbeat():
    assert SUP._config_problems(_config()) == []
    cases = (
        (_config(expected_host="Jerrys-MacBook-Air.local"), "host"),
        (_config(expected_host="somewhere"), "host"),
        (_config(expected_runner_sha256="bad"), "runner"),
        (_config(screen_fleet_hours=float("nan")), "budget"),
        (_config(heartbeat_seconds=0), "heartbeat"),
    )
    for config, fragment in cases:
        assert any(fragment in problem
                   for problem in SUP._config_problems(config))


def test_identity_refuses_homebrew_python_on_registered_mini(
        tmp_path, monkeypatch):
    assert SUP.EXPECTED_PYTHON == "3.14.3"
    monkeypatch.setattr(
        SUP.os, "uname",
        lambda: SimpleNamespace(nodename="Jerrys-Mac-mini.local"))
    monkeypatch.setattr(SUP.platform, "python_version", lambda: "3.14.6")
    with pytest.raises(SUP.ControllerRefusal,
                       match="preflight requires Python 3.14.3"):
        SUP._identity_context(_config(), _paths(tmp_path))


def test_preflight_artifact_recomputes_capacity_and_rejects_scores():
    config = _config()
    payload = _payload(config)
    assert SUP.preflight_artifact_problems(
        payload, config=config, parent=_parent(), runtime=_runtime()) == []

    changed = copy.deepcopy(payload)
    changed["outcome"] = {"winner": "structured"}
    assert "preflight leaked outcome fields" in SUP.preflight_artifact_problems(
        changed, config=config, parent=_parent(), runtime=_runtime())

    changed = copy.deepcopy(payload)
    changed["projections"]["screen"]["fleet_hours"] += 1
    assert "preflight projection screen" in SUP.preflight_artifact_problems(
        changed, config=config, parent=_parent(), runtime=_runtime())

    changed = copy.deepcopy(payload)
    changed["capacity_pass"] = False
    assert "preflight capacity verdict drift" in \
        SUP.preflight_artifact_problems(
            changed, config=config, parent=_parent(), runtime=_runtime())

    changed = copy.deepcopy(payload)
    changed["integer_counters"]["structured"]["rollouts"] = 0
    assert any("exceeds general counter rollouts" in problem for problem in
               SUP.preflight_artifact_problems(
                   changed, config=config, parent=_parent(),
                   runtime=_runtime()))


def test_preflight_artifact_rejects_control_activation_and_run_mixing():
    config = _config()
    payload = _payload(config)
    payload["structured_bury_telemetry"]["champion"] = \
        _structured_telemetry()
    assert any("control structured telemetry" in problem for problem in
               SUP.preflight_artifact_problems(
                   payload, config=config, parent=_parent(), runtime=_runtime()))

    payload = _payload(config)
    payload["run_id"] = SUP.DUEL.PHASES["screen"]["run_id"]
    assert "preflight identity/provenance/authority" in \
        SUP.preflight_artifact_problems(
            payload, config=config, parent=_parent(), runtime=_runtime())

    payload = _payload(config)
    payload["structured_bury_telemetry"]["structured"] = _zero_telemetry()
    assert "preflight recorded problems omit derived failures" in \
        SUP.preflight_artifact_problems(
            payload, config=config, parent=_parent(), runtime=_runtime())


def test_preflight_hold_is_valid_but_cannot_authorize_screen():
    config = _config(screen_fleet_hours=0.001)
    payload = _payload(config)
    payload["capacity_pass"] = False
    assert SUP.preflight_artifact_problems(
        payload, config=config, parent=_parent(), runtime=_runtime()) == []
    evidence = {
        "output": {"path": "preflight.json", "sha256": "1" * 64},
        "log": {"path": "preflight.log", "sha256": "2" * 64},
        "exit": {"path": "preflight.exit.json", "sha256": "3" * 64},
    }
    final = SUP.expected_final(
        contract={}, receipt_sha256="4" * 64,
        progress_sha256="5" * 64, preflight=payload,
        job_evidence=evidence)
    assert final["status"] == "TERMINAL_CAPACITY_HOLD"
    assert final["screen_packet_review_authorized"] is False
    assert final["strength_launch_authorized"] is False

    payload["problems"] = [
        "score-free preflight did not exercise structured bury"]
    final = SUP.expected_final(
        contract={}, receipt_sha256="4" * 64,
        progress_sha256="5" * 64, preflight=payload,
        job_evidence=evidence)
    assert final["status"] == "TERMINAL_PROTOCOL_HOLD"


def test_receipt_and_final_are_full_recomputations(tmp_path):
    config = _config()
    paths = _paths(tmp_path)
    contract = SUP.packet_contract(
        config, paths, parent=_parent(), runtime=_runtime())
    receipt = {
        "schema": SUP.RECEIPT_SCHEMA,
        "run_id": SUP.RUN_ID,
        "complete": True,
        "created_time_ns": 1,
        "nonce": "6" * 64,
        "contract": contract,
        "contract_sha256": SUP.stable_digest(contract),
    }
    assert SUP.receipt_problems(receipt, contract) == []
    changed = copy.deepcopy(receipt)
    changed["contract"]["capacity"]["budgets"]["screen_fleet_hours"] = 2
    changed["contract_sha256"] = SUP.stable_digest(changed["contract"])
    assert "receipt contract drift" in SUP.receipt_problems(changed, contract)

    payload = _payload(config)
    evidence = {
        "output": {"path": "preflight.json", "sha256": "1" * 64},
        "log": {"path": "preflight.log", "sha256": "2" * 64},
        "exit": {"path": "preflight.exit.json", "sha256": "3" * 64},
    }
    final = SUP.expected_final(
        contract=contract, receipt_sha256="4" * 64,
        progress_sha256="5" * 64, preflight=payload,
        job_evidence=evidence)
    assert final["status"] == "AUTHORIZE_SCREEN_PACKET_REVIEW"
    assert final["screen_packet_review_authorized"] is True
    assert final["strength_launch_authorized"] is False
    assert final["production_promotion"] is False


def test_job_evidence_recomputes_command_output_log_and_exit(tmp_path):
    config = _config()
    paths = _paths(tmp_path)
    paths.namespace.mkdir(parents=True)
    paths.preflight.write_text("{}\n")
    paths.log_final.write_text("log\n")
    paths.exit_final.write_text(json.dumps({
        "schema": SUP.EXIT_SCHEMA,
        "run_id": SUP.RUN_ID,
        "argv": list(SUP.preflight_argv(config, paths.preflight)),
        "returncode": 0,
        "output": str(paths.preflight),
        "output_regular_unlinked": True,
        "output_sha256": SUP.sha256_file(paths.preflight),
        "log": str(paths.log_final),
        "log_sha256": SUP.sha256_file(paths.log_final),
    }))
    evidence, problems = SUP.job_evidence_problems(paths, config)
    assert problems == []
    assert evidence["output"]["sha256"] == SUP.sha256_file(paths.preflight)
    paths.log_final.write_text("mutated\n")
    _, problems = SUP.job_evidence_problems(paths, config)
    assert problems == ["preflight exit receipt full recomputation drift"]


def test_progress_recomputes_order_bindings_and_score_free_boundary(tmp_path):
    path = tmp_path / "progress.jsonl"
    events = [
        {
            "schema": SUP.SCHEMA,
            "time_ns": 1,
            "phase": "preflight",
            "status": "receipt-published",
            "receipt_sha256": "1" * 64,
            "contract_sha256": "2" * 64,
        },
        {
            "schema": SUP.SCHEMA,
            "time_ns": 2,
            "phase": "preflight",
            "status": "started",
            "pid": 123,
        },
        {
            "schema": SUP.SCHEMA,
            "time_ns": 3,
            "phase": "preflight",
            "status": "running",
            "pid": 123,
        },
        {
            "schema": SUP.SCHEMA,
            "time_ns": 4,
            "phase": "preflight",
            "status": "complete",
            "capacity_pass": True,
            "preflight_sha256": "3" * 64,
        },
    ]
    path.write_text("".join(json.dumps(event) + "\n" for event in events))
    kwargs = {
        "receipt_sha256": "1" * 64,
        "contract_sha256": "2" * 64,
        "preflight_sha256": "3" * 64,
        "capacity_pass": True,
    }
    assert SUP.progress_problems(path, **kwargs) == []
    events[2]["won"] = 1
    path.write_text("".join(json.dumps(event) + "\n" for event in events))
    assert "progress leaked outcome fields" in SUP.progress_problems(
        path, **kwargs)


def test_namespace_is_one_shot_and_unknown_bytes_refuse(tmp_path, monkeypatch):
    config = _config()
    paths = _paths(tmp_path)
    monkeypatch.setattr(
        SUP, "_identity_context", lambda *_args: (_parent(), _runtime()))
    contract, _, _ = SUP.launch_preflight(config, paths)
    assert contract["retry_or_resume_authorized"] is False
    paths.namespace.mkdir(parents=True)
    (paths.namespace / "surprise.bin").write_bytes(b"x")
    with pytest.raises(SUP.ControllerRefusal, match="unknown bytes"):
        SUP.launch_preflight(config, paths)


def test_launch_pipeline_publishes_one_terminal_review_only_final(
        tmp_path, monkeypatch):
    config = _config()
    paths = _paths(tmp_path)
    contract = SUP.packet_contract(
        config, paths, parent=_parent(), runtime=_runtime())
    monkeypatch.setattr(SUP, "paths_for", lambda: paths)
    monkeypatch.setattr(
        SUP, "launch_preflight",
        lambda *_args: (contract, _parent(), _runtime()))
    fake_job = SimpleNamespace(
        process=SimpleNamespace(pid=123), finished=False)
    monkeypatch.setattr(SUP, "_start_job", lambda *_args: fake_job)

    def fake_wait(job, progress, _heartbeat):
        payload = _payload(config)
        paths.preflight.write_text(json.dumps(payload) + "\n")
        paths.log_final.write_text("fake score-free child\n")
        paths.exit_final.write_text(json.dumps({
            "schema": SUP.EXIT_SCHEMA,
            "run_id": SUP.RUN_ID,
            "argv": list(SUP.preflight_argv(config, paths.preflight)),
            "returncode": 0,
            "output": str(paths.preflight),
            "output_regular_unlinked": True,
            "output_sha256": SUP.sha256_file(paths.preflight),
            "log": str(paths.log_final),
            "log_sha256": SUP.sha256_file(paths.log_final),
        }))
        progress.event("running", pid=job.process.pid)
        job.finished = True
        return 0

    monkeypatch.setattr(SUP, "_wait", fake_wait)
    SUP.launch(config)
    final = json.loads(paths.final.read_text())
    assert final["status"] == "AUTHORIZE_SCREEN_PACKET_REVIEW"
    assert final["screen_packet_review_authorized"] is True
    assert final["strength_launch_authorized"] is False
    assert final["production_promotion"] is False
    assert not (_keys(final) & SUP.FORBIDDEN_OUTCOME_KEYS)
    monkeypatch.setattr(
        SUP, "_identity_context", lambda *_args: (_parent(), _runtime()))
    SUP.verify(config)
    final["strength_launch_authorized"] = True
    paths.final.write_text(json.dumps(final) + "\n")
    with pytest.raises(SUP.ControllerRefusal, match="final full recomputation"):
        SUP.verify(config)


def test_regular_unlinked_rejects_symlink_and_hardlink(tmp_path):
    original = tmp_path / "artifact.json"
    original.write_text("{}\n")
    assert SUP.is_regular_unlinked(original)
    symlink = tmp_path / "alias.json"
    symlink.symlink_to(original)
    assert not SUP.is_regular_unlinked(symlink)
    hardlink = tmp_path / "hard.json"
    hardlink.hardlink_to(original)
    assert not SUP.is_regular_unlinked(original)


def test_cli_refuses_invalid_values_before_launch():
    common = [
        "launch", "--expected-git", "a" * 40,
        "--expected-runner-sha256", "b" * 64,
        "--expected-controller-sha256", "c" * 64,
        "--expected-host", "Jerrys-Mac-mini.local",
        "--screen-fleet-hours", "1",
        "--screen-max-shard-hours", "1",
        "--confirm-fleet-hours", "1",
        "--confirm-max-shard-hours", "1",
    ]
    with pytest.raises(SUP.ControllerRefusal, match="heartbeat"):
        SUP.main([*common, "--heartbeat-seconds", "0"])

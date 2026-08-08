"""Fail-closed boundaries for the one-shot S3a Mini screen supervisor."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import s3a_bury_screen_supervisor as SUP  # noqa: E402


def _config() -> SUP.Config:
    return SUP.Config(
        expected_git="a" * 40,
        expected_runner_sha256="b" * 64,
        expected_controller_sha256="c" * 64,
        heartbeat_seconds=30.0,
    )


def _paths(tmp_path: Path) -> SUP.Paths:
    namespace = tmp_path / SUP.RUN_ID
    shards = tuple(namespace / name for name in SUP.SHARD_NAMES)
    shard_logs = tuple(namespace / f"shard-{index:02d}.log"
                       for index in range(SUP.SHARD_COUNT))
    shard_exits = tuple(namespace / f"exit-shard-{index:02d}.json"
                       for index in range(SUP.SHARD_COUNT))
    return SUP.Paths(
        namespace=namespace,
        runner=tmp_path / "runner.py",
        controller=tmp_path / "controller.py",
        receipt=namespace / SUP.RECEIPT_NAME,
        progress_partial=namespace / f"{SUP.PROGRESS_NAME}.partial",
        progress_final=namespace / SUP.PROGRESS_NAME,
        final=namespace / SUP.FINAL_NAME,
        shards=shards,
        shard_logs=shard_logs,
        shard_exits=shard_exits,
        aggregate=namespace / SUP.AGGREGATE_NAME,
        aggregate_log=namespace / "aggregate.log",
        aggregate_exit=namespace / "aggregate.exit.json",
    )


def _parent() -> dict:
    return SUP.S3A.LIVE_PARENT.expected_parent()


def _runtime() -> dict:
    return {
        "host": SUP.EXPECTED_HOST,
        "python": "3.14.6",
        "fast_engine": True,
        "require_voids": True,
        "experimental_sampler_ballot_flags": [],
        "digests": {"fast_binary": "d" * 64},
    }


def _contract(tmp_path: Path) -> tuple[SUP.Paths, dict]:
    paths = _paths(tmp_path)
    return paths, SUP.packet_contract(
        _config(), paths, parent=_parent(), runtime=_runtime())


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


def test_packet_freezes_exact_geometry_commands_gate_and_no_outcomes(tmp_path):
    paths, contract = _contract(tmp_path)
    assert contract["run_id"] == "s3a-bury-v2-screen-136m-v1"
    assert contract["host"] == "Jerrys-Mac-mini.local"
    assert contract["mechanism"]["total_states"] == 512
    assert contract["mechanism"]["shard_count"] == 8
    assert contract["mechanism"]["seed0"] == 136_000_000
    assert contract["mechanism"]["seed_hi"] == 136_000_511
    assert contract["mechanism"]["report_worlds"] == 120
    assert len(contract["commands"]["shards"]) == 8
    for index, argv in enumerate(contract["commands"]["shards"]):
        assert argv == list(SUP.shard_argv(index, paths.shards[index]))
        assert argv[0] == sys.executable
        assert "--smoke" not in argv
    assert contract["commands"]["aggregate"] == list(
        SUP.aggregate_argv(paths))
    assert not any(
        path.match("shard-*.json") for path in paths.shard_exits)
    assert sorted(paths.namespace.glob("shard-*.json")) == []
    assert contract["gate"]["production_promotion"] is False
    assert contract["gate"]["duel_reference_frozen"] is False
    assert contract["retry_or_resume_authorized"] is False
    assert not (_keys(contract) & {
        "stats", "criteria", "mean", "lcb_95", "winner", "outcome",
        "played", "selected_index", "duel_result",
    })


def test_preflight_refuses_any_known_or_unknown_namespace_byte(
        tmp_path, monkeypatch):
    paths, contract = _contract(tmp_path)
    monkeypatch.setattr(
        SUP, "_identity_context", lambda *_args: (_parent(), _runtime()))
    got, parent, runtime = SUP.launch_preflight(_config(), paths)
    assert got == contract and parent == _parent() and runtime == _runtime()

    paths.namespace.mkdir(parents=True)
    unknown = paths.namespace / "surprise.bin"
    unknown.write_bytes(b"x")
    with pytest.raises(SUP.SupervisorRefusal, match="unknown bytes"):
        SUP.launch_preflight(_config(), paths)
    unknown.unlink()

    paths.receipt.write_text("occupied")
    with pytest.raises(SUP.SupervisorRefusal, match="collision"):
        SUP.launch_preflight(_config(), paths)


def test_receipt_is_exact_contract_bound_and_mutation_falsifiable(tmp_path):
    _, contract = _contract(tmp_path)
    receipt = {
        "schema": SUP.RECEIPT_SCHEMA,
        "run_id": SUP.RUN_ID,
        "complete": True,
        "created_time_ns": 1,
        "nonce": "e" * 64,
        "contract": contract,
        "contract_sha256": SUP.stable_digest(contract),
    }
    assert SUP.receipt_problems(receipt, contract) == []

    changed = copy.deepcopy(receipt)
    changed["contract"]["mechanism"]["report_worlds"] = 119
    changed["contract_sha256"] = SUP.stable_digest(changed["contract"])
    assert "receipt contract drift" in SUP.receipt_problems(changed, contract)

    changed = copy.deepcopy(receipt)
    changed["outcome"] = {"winner": "structured"}
    assert "receipt field population" in SUP.receipt_problems(changed, contract)


def test_terminal_final_recomputes_every_hash_status_and_authority(tmp_path):
    _, contract = _contract(tmp_path)
    shard_sha256s = [f"{index:064x}" for index in range(8)]
    aggregate = {
        "status": "HOLD",
        "duel_design_authorized": False,
        "production_promotion": False,
    }
    job_evidence = [
        {
            "job": f"job-{index}",
            "output": {"path": f"output-{index}", "sha256": "4" * 64},
            "log": {"path": f"log-{index}", "sha256": "5" * 64},
            "exit": {"path": f"exit-{index}", "sha256": "6" * 64},
        }
        for index in range(9)
    ]
    final = {
        "schema": SUP.FINAL_SCHEMA,
        "run_id": SUP.RUN_ID,
        "complete": True,
        "contract_sha256": SUP.stable_digest(contract),
        "receipt_sha256": "1" * 64,
        "progress_sha256": "2" * 64,
        "jobs": job_evidence,
        "shards": [
            {"path": contract["outputs"]["shards"][index],
             "sha256": shard_sha256s[index], "shard_index": index}
            for index in range(8)
        ],
        "aggregate": {
            "path": contract["outputs"]["aggregate"],
            "sha256": "3" * 64,
            "status": "HOLD",
        },
        "duel_design_authorized": False,
        "production_promotion": False,
        "retry_or_resume_authorized": False,
    }
    kwargs = {
        "contract": contract,
        "receipt_sha256": "1" * 64,
        "progress_sha256": "2" * 64,
        "shard_sha256s": shard_sha256s,
        "aggregate_sha256": "3" * 64,
        "aggregate": aggregate,
        "job_evidence": job_evidence,
    }
    assert SUP.final_problems(final, **kwargs) == []

    for mutation in (
        lambda row: row["shards"][0].update(sha256="f" * 64),
        lambda row: row["aggregate"].update(status="AUTHORIZE_DUEL_DESIGN"),
        lambda row: row["jobs"][0]["exit"].update(sha256="0" * 64),
        lambda row: row.update(production_promotion=True),
        lambda row: row.update(retry_or_resume_authorized=True),
        lambda row: row.update(extra={"outcome": 1}),
    ):
        changed = copy.deepcopy(final)
        mutation(changed)
        assert SUP.final_problems(changed, **kwargs) == [
            "supervisor final full recomputation drift"]


def test_terminal_job_evidence_binds_commands_outputs_logs_and_exits(tmp_path):
    paths = _paths(tmp_path)
    paths.namespace.mkdir(parents=True)
    for name, argv, output, log, exit_path in SUP._job_specs(paths):
        output.write_text(f"{name} output\n")
        log.write_text(f"{name} log\n")
        exit_path.write_text(json.dumps({
            "schema": SUP.EXIT_SCHEMA,
            "run_id": SUP.RUN_ID,
            "job": name,
            "argv": list(argv),
            "returncode": 0,
            "output": str(output),
            "output_regular_unlinked": True,
            "output_sha256": SUP.sha256_file(output),
            "log": str(log),
            "log_sha256": SUP.sha256_file(log),
        }))
    evidence, problems = SUP.terminal_job_evidence(paths)
    assert problems == []
    assert len(evidence) == 9

    paths.shard_logs[0].write_text("mutated log\n")
    _, problems = SUP.terminal_job_evidence(paths)
    assert problems == [
        "shard-00 exit receipt full recomputation drift",
        "terminal child evidence population",
    ]


def test_regular_unlinked_rejects_symlink_and_extra_hardlink(tmp_path):
    original = tmp_path / "artifact.json"
    original.write_text("{}\n")
    assert SUP.is_regular_unlinked(original)
    symlink = tmp_path / "artifact-symlink.json"
    symlink.symlink_to(original)
    assert not SUP.is_regular_unlinked(symlink)
    hardlink = tmp_path / "artifact-hardlink.json"
    hardlink.hardlink_to(original)
    assert not SUP.is_regular_unlinked(original)
    assert not SUP.is_regular_unlinked(hardlink)


def test_source_hash_and_host_predeclarations_are_strict(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    paths.runner.write_text("runner")
    paths.controller.write_text("controller")
    config = SUP.Config(
        expected_git="a" * 40,
        expected_runner_sha256=SUP.sha256_file(paths.runner),
        expected_controller_sha256=SUP.sha256_file(paths.controller),
        heartbeat_seconds=30.0,
    )
    monkeypatch.setattr(SUP.os, "uname", lambda: type(
        "Uname", (), {"nodename": "wrong-host"})())
    with pytest.raises(SUP.SupervisorRefusal, match="pinned to"):
        SUP._identity_context(config, paths)

    bad = copy.copy(config)
    object.__setattr__(bad, "expected_runner_sha256", "not-a-sha")
    with pytest.raises(SUP.SupervisorRefusal, match="malformed"):
        SUP._identity_context(bad, paths)


def test_heartbeat_bounds_refuse_invalid_cli_values():
    common = [
        "launch", "--expected-git", "a" * 40,
        "--expected-runner-sha256", "b" * 64,
        "--expected-controller-sha256", "c" * 64,
    ]
    with pytest.raises(SUP.SupervisorRefusal, match="heartbeat"):
        SUP.main([*common, "--heartbeat-seconds", "0"])
    with pytest.raises(SUP.SupervisorRefusal, match="heartbeat"):
        SUP.main([*common, "--heartbeat-seconds", "61"])

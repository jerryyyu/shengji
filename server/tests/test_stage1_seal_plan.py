from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from scripts import prepare_stage1_seal_plan as builder
from scripts import sealed_production_llm_panel_readout as sealed
from shengji.luna.benchmark_failure_protocol import PRESERVE_ILLEGAL
from test_production_llm_panel_readout import _stage1_reports


ROWS = ("smv3-pv", "m1-prior")


def _write(path: Path, value) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, sort_keys=True).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _fixture(tmp_path: Path):
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    reports, _ = _stage1_reports(tmp_path / "reports")
    output = tmp_path / "campaign"
    roots = tmp_path / "roots"
    roots_sha = _write(roots / "result.json", {"roots": {str(i): f"{i:064x}" for i in range(10)}})
    config = {
        "schema": "sol-feedback-on-stage1-v1", "rows": list(ROWS),
        "output": str(output), "seeds": list(range(10)),
        "prepared_roots": str(roots), "prepared_roots_sha256": roots_sha,
        "recovery_controls": {"capacity_retries": True,
                               "accept_recovered_reconnects": False,
                               "invalid_action_feedback": True,
                               "classify_final_action_failures": True},
        "provider_capacity_retry_delays": [15, 30, 60],
        "row_wall_seconds": 43200, "row_soft_tokens": 45000000,
        "provider_call_seconds": 300, "failure_protocol": PRESERVE_ILLEGAL,
        "illegal_failure_limit": 8,
    }
    config_path = tmp_path / "config.json"
    config_sha = _write(config_path, config)
    _write(output / "config.json", config)
    exits = []
    accounting = {"status": "scheduled-terminal", "completed": 40,
                  "failed": 0, "unattempted": 0, "scheduled": 40}
    for row in ROWS:
        report = reports[row]
        report["config"]["prepared_roots_from"] = {
            "result_sha256": roots_sha, "root_hashes": {str(i): f"{i:064x}" for i in range(10)}}
        report["prepared_roots"] = report["config"]["prepared_roots_from"]
        _write(output / row / "result.json", report)
        exit_record = {"row": row, "status": "exited", "returncode": 0}
        _write(output / f"{row}.terminal.json", exit_record)
        _write(output / f"{row}.accounting.json", accounting)
        exits.append(exit_record)
    _write(output / "terminal.json", {"status": "scheduled-terminal",
                                       "config_sha256": config_sha, "rows": exits})
    _write(output / "stage1-summary.json", {
        "schema": "sol-feedback-on-stage1-summary-v1", "config_sha256": config_sha,
        "status": "scheduled-terminal", "required_prior_rows": [],
        "rows": {row: accounting for row in ROWS},
    })
    return config_path, config_sha, output


def _plan(tmp_path: Path):
    config_path, config_sha, campaign = _fixture(tmp_path)
    plan_dir = tmp_path / "seal-plan"
    plan = builder.prepare_stage1_seal_plan(config_path, config_sha, plan_dir)
    plan_path = plan_dir / "result.json"
    plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    return plan, plan_path, plan_sha, campaign


def test_builder_admits_metadata_hashes_results_once_and_reader_accepts(tmp_path, monkeypatch):
    hashed = []
    real_hash = builder._hash_result_once
    def record(path, label):
        hashed.append(path)
        return real_hash(path, label)
    monkeypatch.setattr(builder, '_hash_result_once', record)
    plan, plan_path, plan_sha, _ = _plan(tmp_path)
    assert hashed == [Path(plan['rows'][row]['result']['path']) for row in ROWS]
    assert all(ref["sha256"] != builder.ZERO_SHA256
               for refs in plan["rows"].values() for ref in [refs["result"]])
    result = sealed.read_sealed_stage1(plan_path, plan_sha)
    assert result["panel_size"] == 2
    assert json.loads((plan_path.parent / "receipt.json").read_text())["status"] == "complete"


@pytest.mark.parametrize("mutation", ["terminal", "accounting", "config", "incomplete"])
def test_builder_refuses_before_result_hashing_and_leaves_partial_claim(tmp_path, mutation, monkeypatch):
    config_path, config_sha, output = _fixture(tmp_path)
    if mutation == "terminal":
        path = output / "smv3-pv.terminal.json"
        value = json.loads(path.read_text()); value["returncode"] = 1
        _write(path, value)
    elif mutation == "accounting":
        path = output / "m1-prior.accounting.json"
        value = json.loads(path.read_text()); value["completed"] = 39
        _write(path, value)
    elif mutation == "config":
        path = output / "config.json"
        value = json.loads(path.read_text()); value["row_soft_tokens"] = 1
        _write(path, value)
    else:
        path = output / "m1-prior.terminal.json"
        value = json.loads(path.read_text()); value["status"] = "deadline"
        _write(path, value)
    plan_dir = tmp_path / "seal-plan"
    monkeypatch.setattr(builder, '_hash_result_once',
                        lambda *_: pytest.fail('result opened before metadata admission'))
    with pytest.raises(ValueError):
        builder.prepare_stage1_seal_plan(config_path, config_sha, plan_dir)
    assert (plan_dir / "claim.json").is_file()
    assert not (plan_dir / "receipt.json").exists()
    assert not (plan_dir / 'result.json').exists()
    with pytest.raises(FileExistsError):
        builder.prepare_stage1_seal_plan(config_path, config_sha, plan_dir)


@pytest.mark.parametrize('special', ['symlink', 'fifo', 'oversize'])
def test_builder_rejects_special_result_and_repeat_claim(tmp_path, special, monkeypatch):
    config_path, config_sha, output = _fixture(tmp_path)
    result = output / "m1-prior" / "result.json"
    result.unlink()
    if special == 'symlink':
        result.symlink_to(output / "smv3-pv" / "result.json")
    elif special == 'fifo':
        os.mkfifo(result)
    else:
        result.write_bytes(b'x' * 33)
        monkeypatch.setattr(builder, 'RESULT_LIMIT', 32)
    with pytest.raises(ValueError):
        builder.prepare_stage1_seal_plan(config_path, config_sha, tmp_path / "special")


def test_successful_claim_never_hashes_again(tmp_path, monkeypatch):
    _, plan_path, _, _ = _plan(tmp_path)
    monkeypatch.setattr(builder, '_read_metadata', lambda *_: pytest.fail('repeated input read'))
    with pytest.raises(FileExistsError):
        builder.prepare_stage1_seal_plan(tmp_path / 'config.json', 'a' * 64, plan_path.parent)


def test_wrong_config_digest_refuses_before_results(tmp_path, monkeypatch):
    config, _, _ = _fixture(tmp_path)
    monkeypatch.setattr(builder, '_hash_result_once', lambda *_: pytest.fail('result read'))
    with pytest.raises(ValueError, match='SHA mismatch'):
        builder.prepare_stage1_seal_plan(config, 'a' * 64, tmp_path / 'plan')


@pytest.mark.parametrize('when', ['admission', 'hashing'])
def test_metadata_mutation_refuses_publication(tmp_path, monkeypatch, when):
    config, pin, output = _fixture(tmp_path)
    metadata = output / 'config.json'
    if when == 'admission':
        original = builder.admit_stage1_metadata
        def mutate(plan):
            admitted = original(plan)
            metadata.write_bytes(metadata.read_bytes() + b' ')
            return admitted
        monkeypatch.setattr(builder, 'admit_stage1_metadata', mutate)
        monkeypatch.setattr(builder, '_hash_result_once', lambda *_: pytest.fail('result read'))
    else:
        original = builder._hash_result_once
        def mutate(path, label):
            hashed = original(path, label)
            metadata.write_bytes(metadata.read_bytes() + b' ')
            return hashed
        monkeypatch.setattr(builder, '_hash_result_once', mutate)
    destination = tmp_path / 'plan'
    with pytest.raises(ValueError, match='metadata changed'):
        builder.prepare_stage1_seal_plan(config, pin, destination)
    assert not (destination / 'result.json').exists()
    assert (destination / 'refusal.json').exists()


def test_first_result_mutation_while_hashing_second_refuses(tmp_path, monkeypatch):
    config, pin, output = _fixture(tmp_path)
    original = builder._hash_result_once
    def mutate(path, label):
        hashed = original(path, label)
        if path.parent.name == 'm1-prior':
            first = output / 'smv3-pv/result.json'
            first.write_bytes(first.read_bytes() + b' ')
        return hashed
    monkeypatch.setattr(builder, '_hash_result_once', mutate)
    with pytest.raises(ValueError, match='result changed after hashing'):
        builder.prepare_stage1_seal_plan(config, pin, tmp_path / 'plan')


def test_cli_requires_execute_without_reading_inputs(tmp_path):
    with pytest.raises(SystemExit):
        builder.main(["--config", str(tmp_path / "missing"), "--config-sha256", "a" * 64,
                      "--output-dir", str(tmp_path / "plan")])
    assert not (tmp_path / "plan").exists()

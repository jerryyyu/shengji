"""Population production-adapter binding and immutable-input tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import shengji.rl.world_afterstate_v2_stage_adapters as adapters
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v2_population_controller import WORKER_ARMS


FREEZE = "a" * 64
ADMISSION = "b" * 64


class Freeze:
    deadline_seconds = 300

    def __init__(self, path: str, digest: str):
        self.artifact_bindings = (("population", path, digest),)

    def sha256(self) -> str:
        return FREEZE


class Admission:
    def sha256(self) -> str:
        return ADMISSION


class Supervisor:
    def __init__(self, root: Path):
        self.root = root
        self.admission = Admission()
        self.progress = []

    def emit_progress(self, **value):
        self.progress.append(value)


def _input(**overrides) -> dict:
    value = {
        "schema": adapters.INPUT_SCHEMA,
        "population_namespace_sha256": "c" * 64,
        "max_attempts_per_slot": 2,
        "workers": 2,
        "deadline_seconds": 120,
        "heartbeat_seconds": 30,
    }
    value.update(overrides)
    return value


def _fixture(tmp_path: Path, **overrides):
    repo = tmp_path / "repo"
    repo.mkdir()
    path = repo / "population-input.json"
    raw = canonical_json_bytes(_input(**overrides))
    path.write_bytes(raw)
    path.chmod(0o400)
    return repo, Freeze("population-input.json", hashlib.sha256(raw).hexdigest())


def test_factory_binds_real_collect_producer_and_exact_input_fields(tmp_path: Path):
    repo, freeze = _fixture(tmp_path)
    adapter = adapters.population_collection_adapter(freeze=freeze, repo=repo)
    assert adapter.__world_afterstate_v2_stage_adapter__ == adapters.ABI
    assert adapter.producer is adapters.collect_population_v2


@pytest.mark.parametrize("overrides", [
    {"workers": 3}, {"workers": 0}, {"max_attempts_per_slot": 0},
    {"deadline_seconds": 0}, {"deadline_seconds": 301},
    {"heartbeat_seconds": 0}, {"heartbeat_seconds": 61},
])
def test_invalid_frozen_population_values_refuse(tmp_path: Path, overrides):
    repo, freeze = _fixture(tmp_path, **overrides)
    with pytest.raises(adapters.StageAdapterUnavailable):
        adapters.population_collection_adapter(freeze=freeze, repo=repo)


@pytest.mark.parametrize("mutation", ["missing", "extra", "tamper"])
def test_missing_extra_or_tampered_bound_artifact_refuses(tmp_path: Path, mutation: str):
    repo, freeze = _fixture(tmp_path)
    path = repo / "population-input.json"
    if mutation == "missing":
        path.unlink()
    elif mutation == "extra":
        value = _input(extra=True)
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes(value))
        path.chmod(0o400)
    else:
        path.chmod(0o600)
        path.write_bytes(path.read_bytes() + b"tamper")
        path.chmod(0o400)
    with pytest.raises(adapters.StageAdapterUnavailable, match="artifact|schema"):
        adapters.population_collection_adapter(freeze=freeze, repo=repo)


def test_frozen_values_reach_real_producer_and_progress_is_bridged(
        tmp_path: Path, monkeypatch):
    repo, freeze = _fixture(tmp_path)
    observed = []

    def fake(root, **kwargs):
        observed.append((root, kwargs))
        kwargs["progress_callback"]({
            "stage": "population", "substage": "slot-1",
            "completed_slots": 1, "total_slots": 256,
            "active_workers": 2, "immutable_shards": 1,
        })
        return "receipt"

    monkeypatch.setattr(adapters, "collect_population_v2", fake)
    adapter = adapters.population_collection_adapter(freeze=freeze, repo=repo)
    supervisor = Supervisor(tmp_path / "evidence")
    supervisor.root.mkdir()
    assert adapter(supervisor, ()) == "receipt"
    root, kwargs = observed[0]
    assert root == supervisor.root
    assert kwargs["freeze_sha256"] == FREEZE
    assert kwargs["admission_sha256"] == ADMISSION
    assert kwargs["population_namespace_sha256"] == "c" * 64
    assert kwargs["max_attempts_per_slot"] == 2
    assert kwargs["workers"] in WORKER_ARMS
    assert kwargs["deadline_seconds"] == 120
    assert kwargs["heartbeat_seconds"] == 30
    assert supervisor.progress == [{
        "stage": "population", "substage": "slot-1", "completed": 1,
        "total": 256, "active_workers": 2, "sealed_shards": 1,
    }]
    with pytest.raises(TypeError):
        adapter(supervisor, (), workers=16)


def test_caller_cannot_inject_driver_or_override_config_and_repeated_call_reuses_producer(
        tmp_path: Path, monkeypatch):
    repo, freeze = _fixture(tmp_path)
    calls = []

    def fake(root, **kwargs):
        calls.append(kwargs)
        return "same-receipt"

    monkeypatch.setattr(adapters, "collect_population_v2", fake)
    adapter = adapters.population_collection_adapter(freeze=freeze, repo=repo)
    supervisor = Supervisor(tmp_path / "evidence")
    supervisor.root.mkdir()
    assert adapter(supervisor, ()) == adapter(supervisor, ()) == "same-receipt"
    assert len(calls) == 2
    assert all(call["workers"] == 2 for call in calls)
    assert "attempt_driver" not in calls[0]

"""Population production-adapter binding and immutable-input tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import shengji.rl.world_afterstate_v2_stage_adapters as adapters
import shengji.rl.world_afterstate_v2_execution as execution
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
        self.shards = {}
        self.terminal_routes = []

    def emit_progress(self, **value):
        self.progress.append(value)

    def verified_shards(self, stage):
        return tuple(sorted(self.shards.get(stage, {})))

    def register_verified_shard(self, stage, shard, raw):
        self.shards.setdefault(stage, {})[shard] = raw

    def terminal(self, route):
        self.terminal_routes.append(route)


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


class StageFreeze:
    deadline_seconds = 300
    population_tier = "D256"

    def __init__(self, evidence_root: Path, path: str, digest: str):
        self.evidence_root = str(evidence_root)
        self.artifact_bindings = (("config", path, digest),)

    def sha256(self) -> str:
        return FREEZE


def _stage_fixture(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    config = {
        "schema": adapters.STAGE_INPUT_SCHEMA,
        "artifact_root": str(evidence),
        "population_namespace_sha256": "c" * 64,
        "p0-labels-gates": {}, "optimizer-canary": {}, "nested-curve": {},
    }
    raw = canonical_json_bytes(config)
    path = repo / "stage-config.json"
    path.write_bytes(raw)
    path.chmod(0o400)
    return repo, evidence, StageFreeze(
        evidence, "stage-config.json", hashlib.sha256(raw).hexdigest())


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


def test_p0_adapter_selects_exact_96_from_complete_128_before_opening_labels(
        tmp_path: Path, monkeypatch):
    repo, evidence_root, freeze = _stage_fixture(tmp_path)
    states = tuple(SimpleNamespace(
        deal_sha256=f"{index:064x}", slot_sha256=f"{index + 1000:064x}")
                   for index in range(128))
    materials = tuple(SimpleNamespace(
        deal_sha256=state.deal_sha256, state=state)
                      for state in states)
    bundles = tuple(SimpleNamespace(candidates=(
        ("outcome", index, 0), ("outcome", index, 1)))
                    for index in range(128))
    pairs = tuple(zip(materials, bundles, strict=True))
    slots = tuple(SimpleNamespace(
        group="natural-fit", slot_sha256=state.slot_sha256)
                  for state in states)
    observed = {}

    monkeypatch.setattr(adapters, "_natural_fit_inputs",
                        lambda *_args, **_kwargs: pairs)
    monkeypatch.setattr(adapters, "select_p0_population",
                        lambda population, **_kwargs: tuple(population[:96]))
    monkeypatch.setattr(adapters, "build_population_slot_ledger",
                        lambda _tier: slots)

    def mechanics(outcomes, **kwargs):
        observed["mechanics"] = (tuple(outcomes), kwargs)
        return {"mechanics": "derived"}

    def evaluate(outcomes, **kwargs):
        observed["evaluate"] = (tuple(outcomes), kwargs)
        return {"schema": "P0-result", "decision": "PASS_P0_PRECISION"}

    monkeypatch.setattr(adapters, "build_engine_p0_mechanics_evidence", mechanics)
    monkeypatch.setattr(adapters, "evaluate_precision_label", evaluate)
    import shengji.rl.world_afterstate_v2_label as label
    monkeypatch.setattr(label, "validate_precision_label", lambda value: None)

    supervisor = Supervisor(evidence_root)
    adapter = adapters.p0_labels_gates_adapter(freeze=freeze, repo=repo)
    result = adapter(supervisor, ())
    assert result["decision"] == "PASS_P0_PRECISION"
    assert adapter.producer is evaluate
    outcomes, mechanics_kwargs = observed["mechanics"]
    assert len(outcomes) == 96 * 2
    assert len(mechanics_kwargs["materials"]) == 96
    assert len(mechanics_kwargs["bundles"]) == 96
    assert len(mechanics_kwargs["natural_fit_population"]) == 128
    assert len(mechanics_kwargs["required_slots"]) == 96
    assert set(mechanics_kwargs["required_slots"]) == {
        state.deal_sha256 for state in states[:96]}
    evaluated_outcomes, evaluate_kwargs = observed["evaluate"]
    assert evaluated_outcomes == outcomes
    assert len(evaluate_kwargs["natural_fit_population"]) == 128
    assert evaluate_kwargs["mechanics_evidence"] == {"mechanics": "derived"}
    assert supervisor.verified_shards("p0-labels-gates") == ("receipt",)
    assert supervisor.terminal_routes == []


@pytest.mark.parametrize("decision", [
    "STOP_NO_REPRODUCIBLE_VALUE_LABEL",
    "STOP_BELOW_WORTHWHILE_VALUE_FLOOR",
    "REFUSE_MECHANICS_OR_CONTROL",
])
def test_p0_adapter_routes_reviewed_early_stop_before_later_work(
        tmp_path: Path, monkeypatch, decision: str):
    repo, evidence_root, freeze = _stage_fixture(tmp_path)
    states = tuple(SimpleNamespace(
        deal_sha256=f"{index:064x}", slot_sha256=f"{index + 1000:064x}")
                   for index in range(128))
    pairs = tuple((SimpleNamespace(deal_sha256=state.deal_sha256, state=state),
                   SimpleNamespace(candidates=(("outcome", index),)))
                  for index, state in enumerate(states))
    slots = tuple(SimpleNamespace(group="natural-fit", slot_sha256=state.slot_sha256)
                  for state in states)
    monkeypatch.setattr(adapters, "_natural_fit_inputs",
                        lambda *_args, **_kwargs: pairs)
    monkeypatch.setattr(adapters, "select_p0_population",
                        lambda population, **_kwargs: tuple(population[:96]))
    monkeypatch.setattr(adapters, "build_population_slot_ledger",
                        lambda _tier: slots)
    monkeypatch.setattr(adapters, "build_engine_p0_mechanics_evidence",
                        lambda *_args, **_kwargs: {"mechanics": "derived"})
    monkeypatch.setattr(adapters, "evaluate_precision_label",
                        lambda *_args, **_kwargs: {
                            "schema": "P0-result", "decision": decision})
    import shengji.rl.world_afterstate_v2_label as label
    monkeypatch.setattr(label, "validate_precision_label", lambda value: None)
    supervisor = Supervisor(evidence_root)
    adapters.p0_labels_gates_adapter(freeze=freeze, repo=repo)(supervisor, ())
    assert supervisor.terminal_routes == [decision]


def test_unified_stage_config_is_one_exact_freeze_bound_envelope(
        tmp_path: Path):
    repo, _evidence_root, freeze = _stage_fixture(tmp_path)
    assert adapters.p0_labels_gates_adapter(freeze=freeze, repo=repo).producer \
        is adapters.evaluate_precision_label
    assert adapters.optimizer_canary_adapter(freeze=freeze, repo=repo).producer \
        is adapters.produce_optimizer_canary_v2
    path = repo / "stage-config.json"
    value = __import__("json").loads(path.read_bytes())
    value["optimizer-canary"] = {"caller_override": True}
    path.chmod(0o600)
    path.write_bytes(canonical_json_bytes(value))
    path.chmod(0o400)
    with pytest.raises(adapters.StageAdapterUnavailable,
                       match="schema|binding|artifact"):
        adapters.optimizer_canary_adapter(freeze=freeze, repo=repo)


def test_d256_only_producer_cannot_run_under_larger_frozen_tier(tmp_path: Path):
    repo, _evidence_root, freeze = _stage_fixture(tmp_path)
    freeze.population_tier = "D512"
    with pytest.raises(adapters.StageAdapterUnavailable, match="binding"):
        adapters.p0_labels_gates_adapter(freeze=freeze, repo=repo)


def test_optimizer_failure_routes_training_recipe_refusal(
        tmp_path: Path, monkeypatch):
    repo, evidence_root, freeze = _stage_fixture(tmp_path)
    pairs = tuple((SimpleNamespace(), SimpleNamespace()) for _ in range(128))
    monkeypatch.setattr(adapters, "_natural_fit_inputs",
                        lambda *_args, **_kwargs: pairs)

    class Receipt:
        passed = False

        def validate(self):
            return None

        def payload(self):
            return {"schema": "optimizer-canary", "passed": False}

    monkeypatch.setattr(adapters, "produce_optimizer_canary_v2",
                        lambda _population: Receipt())
    supervisor = Supervisor(evidence_root)
    adapter = adapters.optimizer_canary_adapter(freeze=freeze, repo=repo)
    assert adapter.producer is adapters.produce_optimizer_canary_v2
    adapter(supervisor, ())
    assert supervisor.terminal_routes == ["REFUSE_TRAINING_RECIPE"]
    assert supervisor.verified_shards("optimizer-canary") == ("receipt",)


def test_nested_curve_stays_closed_until_training_and_evaluation_are_composed(
        tmp_path: Path):
    repo, _evidence_root, freeze = _stage_fixture(tmp_path)
    with pytest.raises(adapters.StageAdapterUnavailable,
                       match="25/50/100% prefix"):
        adapters.nested_curve_adapter(freeze=freeze, repo=repo)


def test_closed_execution_factory_accepts_only_the_two_composed_early_adapters(
        tmp_path: Path):
    repo, _evidence_root, freeze = _stage_fixture(tmp_path)
    p0 = execution.bind_production_stage_controller(
        "p0-labels-gates", freeze=freeze, repo=repo)
    optimizer = execution.bind_production_stage_controller(
        "optimizer-canary", freeze=freeze, repo=repo)
    assert isinstance(p0.operation, adapters.P0LabelsGatesAdapterV2)
    assert isinstance(optimizer.operation, adapters.OptimizerCanaryAdapterV2)
    p0.validate(); optimizer.validate()
    with pytest.raises(execution.MissingStageError, match="nested-curve"):
        execution.bind_production_stage_controller(
            "nested-curve", freeze=freeze, repo=repo)

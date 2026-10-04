from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from shengji.eval import m9_panel_execution as execution
from shengji.eval import m9_panel_worker
from shengji.eval.m9_panel_plan import ROOTS
from shengji.eval.m9_panel_recipe import (
    FIXTURE_SHA256,
    MODEL_SHA256,
    POLICY,
    SAVED_READOUT_SHA256,
    SCHEMA,
)
from test_m9_panel_readout import _records


def _recipe(tmp_path: Path) -> dict[str, object]:
    source = tmp_path / "source"
    (source / "server").mkdir(parents=True, exist_ok=True)
    model = tmp_path / "model.npz"
    model.write_bytes(b"synthetic model witness")
    return {
        "schema": SCHEMA,
        "python": str(Path(sys.executable).resolve()),
        "source_root": str(source),
        "model": str(model),
        "fixtures": str(tmp_path / "fixtures.jsonl"),
        "saved_readout": str(tmp_path / "readout.json"),
        "output_dir": str(tmp_path / "panel-output"),
        "evidence": str(tmp_path / "process.json"),
        "model_sha256": MODEL_SHA256,
        "fixture_sha256": FIXTURE_SHA256,
        "saved_readout_sha256": SAVED_READOUT_SHA256,
        "seeds": [0, 1, 2],
        "fill_seed": 0,
        "runtime_profile": "panel",
        "policy": POLICY,
    }


class _Loaded:
    def __init__(self, analysis, fixtures, events):
        self.analysis = analysis
        self.fixtures = fixtures
        self.events = events

    def check_unchanged(self):
        self.events.append("inputs")


class _Runtime:
    forced_ok = True

    def __init__(self, manifest, *, profile):
        assert profile == "panel"
        self.events = manifest["_events"]
        self.events.append("runtime-init")
        self.ok = type(self).forced_ok

    def check(self):
        self.events.append("runtime")
        return self.ok


def _harness(monkeypatch, tmp_path, *, collector=None):
    recipe = _recipe(tmp_path)
    analysis, records = _records()
    fixtures = tuple(SimpleNamespace(id=root, seat=0) for root in ROOTS)
    events = []
    loaded = _Loaded(analysis, fixtures, events)
    monkeypatch.setattr(execution, "load_panel_inputs",
                        lambda spec: (events.append("load"), loaded)[1])

    class Runtime(_Runtime):
        def __init__(self, manifest, *, profile):
            manifest = dict(manifest)
            manifest["_events"] = events
            super().__init__(manifest, profile=profile)

    monkeypatch.setattr(execution, "ObservationRuntime", Runtime)
    model = Path(recipe["model"])
    hash_calls = []
    real_file_stamp = execution.file_stamp

    def traced_file_stamp(path):
        mark = real_file_stamp(path)
        if Path(path) == model:
            events.append("model-stamp")
        return mark

    monkeypatch.setattr(execution, "file_stamp", traced_file_stamp)

    def pinned_hash(path):
        hash_calls.append(Path(path))
        return MODEL_SHA256, execution.file_stamp(model)

    monkeypatch.setattr(execution, "_hash_file", pinned_hash)
    bot_calls = []

    def fresh_bot(environment, *, seed):
        assert isinstance(environment, dict)
        bot = object()
        bot_calls.append((seed, bot))
        return f"sentinel-{seed}", bot

    monkeypatch.setattr(execution.tactical, "bot_from_environ", fresh_bot)
    if collector is None:
        records_iter = iter(records)

        def collector(factory, fixture, control, treatment, **kwargs):
            kwargs["check_budget"]()
            first, second = factory(), factory()
            assert first is not second
            assert not isinstance(first, tuple)
            assert kwargs["seed"] in (0, 1, 2)
            return next(records_iter)["panel"]

    monkeypatch.setattr(m9_panel_worker, "collect_public_fixture_panel", collector)
    return recipe, events, hash_calls, bot_calls, loaded


def _manifest(recipe, events):
    return {"source_root": str(Path(recipe["source_root"]) / "server"),
            "_events": events}


def _run(monkeypatch, tmp_path, *, guard=None, budget=None, collector=None):
    recipe, events, hash_calls, bot_calls, loaded = _harness(
        monkeypatch, tmp_path, collector=collector)
    guard = (lambda: True) if guard is None else guard
    budget = (lambda: None) if budget is None else budget
    result = execution.run_panel_body(
        recipe, _manifest(recipe, events), check_admission=guard,
        check_budget=budget)
    return result, recipe, events, hash_calls, bot_calls, loaded


def test_panel_body_is_real_persistence_worker_witness_and_fresh_tuple_unwrap(
        monkeypatch, tmp_path):
    budget_calls = []

    def budget():
        budget_calls.append(1)

    guard_calls = []

    def guard():
        guard_calls.append(1)
        return True

    result, recipe, events, hash_calls, bot_calls, loaded = _run(
        monkeypatch, tmp_path, guard=guard, budget=budget)
    output = Path(recipe["output_dir"])
    assert result["schema"] == "m9-panel-terminal-v1"
    assert result["status"] == "complete"
    assert result["receipt"]["completed_panels"] == 15
    assert len(bot_calls) == 30
    assert sorted(set(seed for seed, _ in bot_calls)) == [0, 1, 2]
    assert all(sum(seed == expected for seed, _ in bot_calls) == 10
               for expected in (0, 1, 2))
    assert len({id(bot) for _, bot in bot_calls}) == 30
    assert hash_calls == [Path(recipe["model"])]
    assert (output / "plan.json").is_file()
    assert (output / "collected-000.json").is_file()
    assert (output / "validated-014.json").is_file()
    assert (output / "terminal.json").is_file()
    assert events[0] == "runtime-init"
    assert events.count("load") == 1
    assert events.count("inputs") == events.count("runtime") == 62
    assert events.count("model-stamp") == 63
    assert len(guard_calls) == 63
    assert len(budget_calls) == 93


@pytest.mark.parametrize("bad_seed", [True, -1, 3, "0"])
def test_supplied_factory_rejects_every_seed_except_strict_zero_one_two(
        monkeypatch, tmp_path, bad_seed):
    recipe, events, _, _, _ = _harness(monkeypatch, tmp_path)
    captured = {}

    def persistence(analysis, fixtures, factory, *, output_dir, check_budget):
        captured["factory"] = factory
        assert factory(0) is not None
        assert factory(1) is not None
        assert factory(2) is not None
        with pytest.raises(ValueError, match="fixed panel seed"):
            factory(bad_seed)
        return {"schema": "synthetic"}

    monkeypatch.setattr(execution, "run_m9_panel_collection", persistence)
    result = execution.run_panel_body(
        recipe, _manifest(recipe, events), check_admission=lambda: True,
        check_budget=lambda: None)
    assert result == {"schema": "synthetic"}
    assert captured["factory"]


@pytest.mark.parametrize("guard_result", [False, 1, None])
def test_admission_must_return_exact_true_before_loading_or_factory(
        monkeypatch, tmp_path, guard_result):
    recipe, events, _, bot_calls, _ = _harness(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="live admission guard"):
        execution.run_panel_body(
            recipe, _manifest(recipe, events),
            check_admission=lambda: guard_result, check_budget=lambda: None)
    assert bot_calls == []
    assert "load" not in events
    assert "runtime-init" not in events


def test_budget_callback_is_mandatory_and_not_inferred(monkeypatch, tmp_path):
    recipe, events, _, bot_calls, _ = _harness(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="guard and deadline"):
        execution.run_panel_body(recipe, _manifest(recipe, events),
                                 check_admission=lambda: True,
                                 check_budget=None)
    assert bot_calls == []


@pytest.mark.parametrize("mutation,pattern", [
    ("source", "source binding"), ("python", "interpreter binding"),
])
def test_source_and_interpreter_bindings_are_exact(monkeypatch, tmp_path,
                                                    mutation, pattern):
    recipe, events, _, bot_calls, _ = _harness(monkeypatch, tmp_path)
    manifest = _manifest(recipe, events)
    if mutation == "source":
        manifest["source_root"] = str(Path(recipe["source_root"]))
    else:
        recipe["python"] = "/definitely/not-this-interpreter"
    with pytest.raises(ValueError, match=pattern):
        execution.run_panel_body(recipe, manifest,
                                 check_admission=lambda: True,
                                 check_budget=lambda: None)
    assert bot_calls == []


def test_model_hash_mismatch_halts_before_factory(monkeypatch, tmp_path):
    recipe, events, hash_calls, bot_calls, _ = _harness(monkeypatch, tmp_path)
    monkeypatch.setattr(execution, "_hash_file",
                        lambda path: ("0" * 64, execution.file_stamp(path)))
    with pytest.raises(ValueError, match="model hash"):
        execution.run_panel_body(recipe, _manifest(recipe, events),
                                 check_admission=lambda: True,
                                 check_budget=lambda: None)
    assert bot_calls == []
    assert hash_calls == []


def test_runtime_and_input_drift_halt_before_any_factory(monkeypatch, tmp_path):
    recipe, events, _, bot_calls, loaded = _harness(monkeypatch, tmp_path)
    loaded.check_unchanged = lambda: (_ for _ in ()).throw(
        ValueError("input drift"))
    with pytest.raises(ValueError, match="input drift"):
        execution.run_panel_body(recipe, _manifest(recipe, events),
                                 check_admission=lambda: True,
                                 check_budget=lambda: None)
    assert bot_calls == []

    recipe, events, _, bot_calls, _ = _harness(monkeypatch, tmp_path)
    execution.ObservationRuntime.forced_ok = False
    with pytest.raises(ValueError, match="runtime drift"):
        execution.run_panel_body(recipe, _manifest(recipe, events),
                                 check_admission=lambda: True,
                                 check_budget=lambda: None)
    assert bot_calls == []


def test_partial_publication_is_preserved_and_failure_is_not_retried(
        monkeypatch, tmp_path):
    calls = []

    def failing_collector(factory, fixture, control, treatment, **kwargs):
        calls.append(kwargs["seed"])
        kwargs["check_budget"]()
        if len(calls) == 2:
            raise RuntimeError("synthetic sampler failure")
        factory()
        return _records()[1][len(calls) - 1]["panel"]

    recipe, events, _, bot_calls, _ = _harness(
        monkeypatch, tmp_path, collector=failing_collector)
    with pytest.raises(RuntimeError, match="synthetic sampler"):
        execution.run_panel_body(recipe, _manifest(recipe, events),
                                 check_admission=lambda: True,
                                 check_budget=lambda: None)
    output = Path(recipe["output_dir"])
    assert len(calls) == 2
    assert len(bot_calls) == 1
    assert (output / "collected-000.json").is_file()
    assert (output / "validated-000.json").is_file()
    assert (output / "terminal.json").is_file()


def test_existing_output_refuses_reuse_without_another_factory(
        monkeypatch, tmp_path):
    result, recipe, events, _, bot_calls, _ = _run(monkeypatch, tmp_path)
    assert result["status"] == "complete"
    first_count = len(bot_calls)
    with pytest.raises(FileExistsError):
        execution.run_panel_body(
            recipe, _manifest(recipe, events), check_admission=lambda: True,
            check_budget=lambda: None)
    assert len(bot_calls) == first_count


def test_final_guard_failure_raises_after_preserving_completed_artifacts(
        monkeypatch, tmp_path):
    checks = []

    def guard():
        checks.append(1)
        return len(checks) < 63

    recipe, events, _, bot_calls, _ = _harness(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="live admission guard"):
        execution.run_panel_body(
            recipe, _manifest(recipe, events), check_admission=guard,
            check_budget=lambda: None)
    output = Path(recipe["output_dir"])
    assert len(bot_calls) == 30
    assert (output / "validated-014.json").is_file()
    assert (output / "terminal.json").is_file()
    terminal = json.loads((output / "terminal.json").read_text())
    assert terminal["status"] == "complete"
    assert terminal["provenance_verified"] is False
    assert len(checks) == 63

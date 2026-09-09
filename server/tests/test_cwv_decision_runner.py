import importlib.util
import json
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import multiprocessing
from pathlib import Path
from types import SimpleNamespace

import pytest


def load_runner():
    path = Path(__file__).resolve().parents[1] / "scripts/cwv_decision_diagnostic.py"
    spec = importlib.util.spec_from_file_location("decision_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parallel_failure_keeps_successes_and_resume_only_opens_missing(tmp_path, monkeypatch):
    runner = load_runner()
    entries = [{"id": str(i) * 64, "deal_key": f"deal-{i}",
                "provenance": {"split": "fit"}} for i in range(3)]
    panel = tmp_path / "panel.json"
    panel.write_text(json.dumps({"schema": "cwv-horizon-panel-v1", "entries": entries}))
    monkeypatch.setattr(runner, "initialize", lambda p: None)
    monkeypatch.setattr(runner, "_EVALUATOR", SimpleNamespace(checkpoint_sha256="a" * 64))
    monkeypatch.setattr(runner, "execution_source_identity", lambda p: {"fixture": True})
    # Real threads and futures exercise the same fan-in/failure path without
    # loading a model or starting scientific rollouts.
    monkeypatch.setattr(runner, "ProcessPoolExecutor",
                        lambda max_workers, **kw: ThreadPoolExecutor(max_workers=max_workers))
    calls = []
    fail = True

    def work(entry, config, seed, worlds, checkpoint_sha256):
        calls.append(entry["id"])
        if fail and entry["id"] == "1" * 64:
            raise ValueError("injected root failure")
        return {"root_sha256": runner.digest(entry), "config_sha256": config,
                "model": {"checkpoint_sha256": checkpoint_sha256},
                "wall_seconds": 1., "metrics": dict.fromkeys([
                    "final_gain_vs_incumbent", "descriptive_coverage_regret",
                    "descriptive_selection_regret", "model_action_gap_mae",
                    "zero_action_gap_mae"], 0.)}

    monkeypatch.setattr(runner, "work", work)
    output = tmp_path / "out"
    partial = runner.run(panel, "fixture", output, checkpoint_sha256="a" * 64,
                         workers=1, reference_worlds=4, max_new_roots=1)
    assert partial["complete"] is False and partial["deals"] == 1
    assert partial["expected_deals"] == 3
    assert calls == ["0" * 64]
    calls.clear()
    with pytest.raises(RuntimeError, match="completed roots retained"):
        runner.run(panel, "fixture", output, checkpoint_sha256="a" * 64,
                   workers=2, reference_worlds=4)
    assert len(list(output.glob("state-*.json"))) == 2
    failure = json.loads((output / "failure.json").read_text())
    assert failure["completed"] == 2
    assert failure["roots"] == [{"root_id": "1" * 64, "error_type": "ValueError",
                                 "message": "injected root failure"}]
    assert json.loads((output / "summary.json").read_text())["complete"] is False
    calls.clear()
    fail = False
    summary = runner.run(panel, "fixture", output, checkpoint_sha256="a" * 64,
                         workers=2, reference_worlds=4)
    assert calls == ["1" * 64]
    assert summary["complete"] is True and summary["deals"] == 3
    assert len(list(output.glob("state-*.json"))) == 3


@pytest.mark.parametrize("change, message", [
    (lambda e: e[0]["provenance"].update(split="test"), "fit-only"),
    (lambda e: e[1].update(deal_key=e[0]["deal_key"]), "independent deal"),
    (lambda e: e[0].update(id="not-a-hash"), "invalid root id"),
])
def test_panel_contract(tmp_path, change, message):
    runner = load_runner()
    entries = [{"id": str(i) * 64, "deal_key": str(i),
                "provenance": {"split": "fit"}} for i in range(2)]
    change(entries)
    path = tmp_path / "panel.json"
    path.write_text(json.dumps({"schema": "cwv-horizon-panel-v1", "entries": entries}))
    with pytest.raises(ValueError, match=message):
        runner.read_panel(path)


def test_importer_to_real_diagnostic_to_saved_result(tmp_path, monkeypatch):
    from scripts import cwv_decision_panel as importer
    from tests.test_cwv_decision_panel import _record, _store, POLICY
    from tests.test_cwv_decision_diagnostic import Values
    from shengji.train.cwv_shortlist import CWVShortlistBot

    runner = load_runner()
    source, assignment = _store(tmp_path, [_record(21, "end-to-end")])
    path = tmp_path / "panel.json"
    panel = importer.build_panel(source, assignment, path, policy=POLICY, max_deals=1)
    assert runner.read_panel(path)["entries"] == panel["entries"]
    with pytest.raises(importer.PanelError, match="already exists"):
        importer.build_panel(source, assignment, path, policy=POLICY, max_deals=1)
    values = Values()
    values.checkpoint_sha256 = "a" * 64
    monkeypatch.setattr(runner, "initialize", lambda p: None)
    monkeypatch.setattr(runner, "_EVALUATOR", values)
    monkeypatch.setattr(runner, "execution_source_identity", lambda p: {"fixture": True})
    monkeypatch.setattr(CWVShortlistBot, "_rollout",
                        lambda self, rnd, seat, sampled, buried, action, **kw: float(len(action)))
    real_diagnose = runner.diagnose
    monkeypatch.setattr(runner, "diagnose", lambda entry, evaluator, **kw:
                        real_diagnose(entry, evaluator, ranking_worlds=1,
                                      selection_worlds=2, report_worlds=30, **kw))
    output = tmp_path / "out"
    with pytest.raises(ValueError, match="evaluation checkpoint SHA mismatch"):
        runner.run(path, "fixture", output, checkpoint_sha256="b" * 64, reference_worlds=4)
    assert not output.exists()
    summary = runner.run(path, "fixture", output, checkpoint_sha256="a" * 64, reference_worlds=4)
    row = json.loads(next(output.glob("state-*.json")).read_text())
    assert row["root_sha256"] == runner.digest(panel["entries"][0])
    assert len(row["reference"]["levels"]) == 4
    assert row["legal_count"] >= 6
    assert row["source_policy"] == POLICY
    assert row["model"]["checkpoint_sha256"] == "a" * 64
    assert summary["complete"] and summary["deals"] == 1


def wrong_worker_model():
    from scripts import cwv_decision_diagnostic as runner
    runner._EVALUATOR = SimpleNamespace(checkpoint_sha256="b" * 64)


def test_spawned_worker_refuses_replaced_checkpoint_before_diagnosis():
    from scripts import cwv_decision_diagnostic as runner
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"),
                             initializer=wrong_worker_model) as pool:
        future = pool.submit(runner.work, {}, "config", 7, 4, "a" * 64)
        with pytest.raises(ValueError, match="^worker evaluation checkpoint SHA mismatch$"):
            future.result(timeout=20)

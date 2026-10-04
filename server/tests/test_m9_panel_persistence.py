from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from shengji.eval import m9_panel_persistence as persistence
from shengji.luna import atomic_io
from test_m9_panel_plan import _analysis
from test_m9_panel_worker import _setup


def _json_analysis():
    analysis = _analysis()
    for root in analysis["roots"]:
        for row in root["seeds"]:
            for arm in ("control", "treatment"):
                row[arm]["decision"].pop("ignored_matrix_means")
    return analysis


def _canonical_hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _files(output, prefix):
    return sorted(output.glob(f"{prefix}-*.json"))


def _run(monkeypatch, tmp_path, **setup_kwargs):
    analysis, fixtures, calls, _records = _setup(monkeypatch, **setup_kwargs)
    analysis = _json_analysis()
    original = copy.deepcopy(analysis)
    output = tmp_path / "panel-attempt"
    factory_calls = []
    receipt = persistence.run_m9_panel_collection(
        analysis, fixtures, lambda seed: factory_calls.append(seed) or object(),
        output_dir=output)
    return analysis, original, output, receipt, calls, factory_calls


def test_success_publishes_plan_raw_validated_and_terminal_json(monkeypatch, tmp_path):
    analysis, original, output, receipt, calls, factory_calls = _run(
        monkeypatch, tmp_path)
    assert receipt["schema"] == "m9-panel-terminal-v1"
    assert receipt["status"] == "complete"
    assert receipt["collected_count"] == receipt["validated_count"] == 15
    assert receipt["provenance_verified"] is False
    assert len(calls) == len(factory_calls) == 15
    assert analysis == original

    plan = json.loads((output / "plan.json").read_text())
    assert plan["schema"] == "m9-panel-attempt-v1"
    assert len(plan["jobs"]) == 15
    assert plan["analysis_sha256"] == _canonical_hash(analysis)
    raw = _files(output, "collected")
    valid = _files(output, "validated")
    assert len(raw) == len(valid) == 15
    for index, path in enumerate(raw):
        item = json.loads(path.read_text())
        assert set(item) == {"job", "panel"}
        assert path.name == f"collected-{index:03d}.json"
        assert path.stat().st_mode & 0o777 == 0o400
    for index, path in enumerate(valid):
        item = json.loads(path.read_text())
        assert {"job", "panel", "replay_consistency", "ledger_cadence"} <= set(item)
        assert path.name == f"validated-{index:03d}.json"
    terminal = json.loads((output / "terminal.json").read_text())
    assert terminal == receipt


def test_replay_drift_persists_raw_before_validation_and_stops(monkeypatch, tmp_path):
    analysis, fixtures, calls, _records = _setup(monkeypatch, drift_seed=1)
    analysis = _json_analysis()
    output = tmp_path / "drift"
    with pytest.raises(ValueError, match="means differ"):
        persistence.run_m9_panel_collection(
            analysis, fixtures, lambda seed: object(), output_dir=output)
    assert len(calls) == 2
    assert len(_files(output, "collected")) == 2
    assert len(_files(output, "validated")) == 1
    terminal = json.loads((output / "terminal.json").read_text())
    assert terminal["schema"] == "m9-panel-terminal-v1"
    assert terminal["status"] == "failed"
    assert terminal["collected_count"] == 2
    assert terminal["validated_count"] == 1
    assert terminal["error_type"] == "ValueError"
    rejected = json.loads((output / "rejected-001.json").read_text())
    assert rejected["validation_status"] == "failed"
    assert rejected["replay_failure"]["arms"]["control"]["captured_value_means"][0] == 1.0
    assert all(kwargs["mode"] == "fresh-root" for _, kwargs, _, _ in calls)


def test_collector_failure_persists_failed_terminal_without_retry(monkeypatch, tmp_path):
    analysis, fixtures, calls, _records = _setup(
        monkeypatch, collector_error=RuntimeError("collector stopped"))
    with pytest.raises(RuntimeError, match="collector stopped"):
        persistence.run_m9_panel_collection(
            _json_analysis(), fixtures, lambda seed: object(),
            output_dir=tmp_path / "collector-failure")
    output = tmp_path / "collector-failure"
    assert len(calls) == 1
    assert _files(output, "collected") == []
    assert _files(output, "validated") == []
    terminal = json.loads((output / "terminal.json").read_text())
    assert terminal["status"] == "failed"
    assert terminal["collected_count"] == terminal["validated_count"] == 0
    assert terminal["error_type"] == "RuntimeError"


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_existing_output_slot_is_refused_before_factory(monkeypatch, tmp_path, kind):
    analysis, fixtures, _calls, _records = _setup(monkeypatch)
    output = tmp_path / "occupied"
    target = tmp_path / "target"
    if kind == "directory":
        output.mkdir()
        (output / "sentinel").write_text("keep")
    else:
        target.mkdir()
        (target / "sentinel").write_text("keep")
        output.symlink_to(target, target_is_directory=True)
    factory_calls = []
    with pytest.raises((FileExistsError, ValueError)):
        persistence.run_m9_panel_collection(
            _json_analysis(), fixtures,
            lambda seed: factory_calls.append(seed) or object(),
            output_dir=output)
    assert factory_calls == []
    assert (target / "sentinel").read_text() == "keep" if kind == "symlink" else (output / "sentinel").read_text() == "keep"


def test_atomic_publish_failure_leaves_partial_evidence_without_retry(
        monkeypatch, tmp_path):
    analysis, fixtures, calls, _records = _setup(monkeypatch)
    original_publish = persistence.publish_exclusive_bytes
    publish_calls = []

    def fail_once(path, payload, *args, **kwargs):
        publish_calls.append(Path(path).name)
        if len(publish_calls) == 4:
            raise OSError("publish interruption")
        return original_publish(path, payload, *args, **kwargs)

    monkeypatch.setattr(persistence, "publish_exclusive_bytes", fail_once)
    output = tmp_path / "publish-failure"
    with pytest.raises(OSError, match="publish interruption"):
        persistence.run_m9_panel_collection(
            _json_analysis(), fixtures, lambda seed: object(), output_dir=output)
    assert len(calls) == 2  # fourth publication is the second raw panel
    assert (output / "plan.json").exists()
    assert len(_files(output, "collected")) == 1
    assert len(_files(output, "validated")) == 1
    terminal = json.loads((output / "terminal.json").read_text())
    assert terminal["status"] == "failed"


def test_keyboard_interrupt_is_terminally_recorded_and_rethrown(monkeypatch,
                                                                  tmp_path):
    analysis, fixtures, calls, _records = _setup(
        monkeypatch, collector_error=KeyboardInterrupt("stop now"))
    output = tmp_path / "interrupt"
    with pytest.raises(KeyboardInterrupt, match="stop now"):
        persistence.run_m9_panel_collection(
            _json_analysis(), fixtures, lambda seed: object(), output_dir=output)
    assert len(calls) == 1
    terminal = json.loads((output / "terminal.json").read_text())
    assert terminal["status"] == "failed"
    assert terminal["error_type"] == "KeyboardInterrupt"


def test_interrupted_atomic_link_preserves_staged_bytes(monkeypatch, tmp_path):
    _, fixtures, calls, _ = _setup(monkeypatch)
    original = atomic_io.os.link
    def fail_link(src, dst, **kwargs):
        if Path(dst).name == "collected-000.json":
            raise OSError("link failed")
        return original(src, dst, **kwargs)
    monkeypatch.setattr(atomic_io.os, "link", fail_link)
    output = tmp_path / "staged"
    with pytest.raises(atomic_io.AtomicPublishError):
        persistence.run_m9_panel_collection(_json_analysis(), fixtures,
                                            lambda seed: object(), output_dir=output)
    staged = output / ".collected-000.json.partial"
    assert json.loads(staged.read_text())["job"]["seed"] == 0
    assert not (output / "collected-000.json").exists()
    assert json.loads((output / "terminal.json").read_text())["status"] == "failed"
    assert len(calls) == 1


def test_raw_callback_is_detached_from_validation(monkeypatch):
    from shengji.eval.m9_panel_worker import collect_m9_panels
    analysis, fixtures, calls, records = _setup(monkeypatch)
    def mutate(record):
        record["panel"]["collection"] = None
        record["job"]["seed"] = 99
    receipt = collect_m9_panels(analysis, fixtures, lambda seed: object(),
                               on_panel=records.append, on_collected=mutate)
    assert receipt["completed_panels"] == 15
    assert all(record["validation_status"] == "passed" for record in records)

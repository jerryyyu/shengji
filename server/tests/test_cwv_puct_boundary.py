import multiprocessing as mp
import time
from types import SimpleNamespace

import pytest

from scripts import cwv_puct_boundary as runner
from shengji.luna.game import _state_snapshot

from test_cwv_bounded_puct import root


def test_json_safe_serializes_tuple_key_maps_as_lists():
    value = {"visits": {("SA", "SA"): 3},
             "totals": {("SA", "SA"): 1.5}}
    out = runner.json_safe(value)
    assert out["visits"] == [{"key": ["SA", "SA"], "value": 3}]
    assert out["totals"][0]["value"] == pytest.approx(1.5)


def test_child_explicitly_requests_outcome_head(monkeypatch):
    seen = {}

    def load(checkpoint, **kwargs):
        seen.update(kwargs)
        raise RuntimeError('stop after constructor witness')

    class Sink:
        def send(self, row):
            self.row = row
        def close(self):
            pass

    monkeypatch.setattr(runner, 'shared_evaluator', load)
    sink = Sink()
    runner._child_run(_spec(), sink)
    assert seen == {'threads': 1, 'value_head': 'outcome'}
    assert sink.row['status'] == 'error'


def test_numpy_head_is_package_bound_and_wrong_head_refused(monkeypatch):
    seen = []
    evaluator = SimpleNamespace(value_head='outcome')
    def load(path, **kwargs):
        seen.append(kwargs)
        return evaluator
    monkeypatch.setattr(runner, 'shared_evaluator', load)
    assert runner._outcome_evaluator('m1.npz') is evaluator
    assert seen == [{'threads': 1}]
    evaluator.value_head = 'search-mean'
    with pytest.raises(ValueError, match='outcome-head'):
        runner._outcome_evaluator('other.npz')


def _spec():
    rnd = root()
    return {"state": 0, "snapshot": _state_snapshot(rnd), "seed": 7,
            "checkpoint": "unused", "prior_checkpoint": "unused",
            "prior_checkpoint_sha256": "a" * 64, "worlds": 1,
            "sweeps": 1, "depth": 1, "source_identity": {"test": "source"},
            "config_sha256": "config"}


def test_supervisor_returns_child_failure_without_hanging(monkeypatch):
    def fail(_spec, send):
        send.send({"status": "error", "state": 0, "schema": runner.SCHEMA,
                   "config_sha256": "config"})

    monkeypatch.setattr(runner, "_child_run", fail)
    row = runner.run_child(_spec(), timeout_seconds=2, context=mp.get_context("fork"))
    assert row["status"] == "error"


def test_supervisor_terminates_timeout_child(monkeypatch):
    def hang(_spec, _send):
        time.sleep(30)

    monkeypatch.setattr(runner, "_child_run", hang)
    started = time.perf_counter()
    row = runner.run_child(_spec(), timeout_seconds=0.1, context=mp.get_context("fork"))
    assert row["status"] == "timeout"
    assert time.perf_counter() - started < 5


def test_supervisor_drains_large_results_before_join(monkeypatch):
    def large(_spec, send):
        send.send({"status": "ok", "diagnostics": "x" * 2_000_000})
        send.close()

    monkeypatch.setattr(runner, "_child_run", large)
    row = runner.run_child(_spec(), timeout_seconds=2, context=mp.get_context("fork"))
    assert row["status"] == "ok"
    assert len(row["diagnostics"]) == 2_000_000


def test_supervisor_records_exit_without_payload(monkeypatch):
    def empty(_spec, send):
        send.close()

    monkeypatch.setattr(runner, "_child_run", empty)
    row = runner.run_child(_spec(), timeout_seconds=2, context=mp.get_context("fork"))
    assert row["status"] == "error"
    assert "without result" in row["error"]


def test_resume_refuses_incompatible_row(tmp_path):
    path = tmp_path / "state-0000.json"
    path.write_text('{"schema":"cwv-puct-boundary-v1","state":0,'
                    '"status":"ok","config_sha256":"old"}')
    with pytest.raises(ValueError, match="incompatible"):
        runner._validate_row(path, 0, "new")

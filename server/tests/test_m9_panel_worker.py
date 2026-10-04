from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from shengji.eval import m9_panel_worker as worker
from shengji.eval.m9_panel_plan import (
    CHECKPOINT_SHA256,
    ROOTS,
    build_m9_panel_plan,
)
from test_m9_panel_plan import _analysis


def _panel(analysis, job, *, drift=False):
    root = next(root for root in analysis["roots"]
                if root["id"] == job["fixture_id"])
    seed_row = next(row for row in root["seeds"] if row["seed"] == job["seed"])
    captures = {}
    for arm in ("control", "treatment"):
        decision = seed_row[arm]["decision"]
        means = list(decision["value_means"])
        if drift and arm == "control":
            means[0] += 1
        captures[arm] = {
            "schema": "fixed-tape-same-leaf-capture-v1",
            "actions": copy.deepcopy(decision["admitted"]),
            "world_count": 64,
            "serving_value_means": means,
        }
    return {
        "schema": "public-fixture-panel-v1",
        "fixture_id": job["fixture_id"], "mode": job["mode"],
        "seed": job["seed"], "fill_seed": 0,
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "effective": {"worlds": 64},
        "legal_count": job["expected_legal_count"],
        "collection": {"schema": "fixed-tape-three-pass-panel-v1",
                       "captures": captures},
        "tape_receipt": {"schema": "public-refusal-tape-v1",
                         "mode": job["mode"], "seed": job["seed"],
                         "fill_seed": 0, "world_count": 64,
                         "checkpoint_sha256": CHECKPOINT_SHA256},
    }


def _setup(monkeypatch, *, drift_seed=None, collector_error=None):
    analysis = _analysis()
    fixtures = [SimpleNamespace(id=root_id, seat=0) for root_id in reversed(ROOTS)]
    calls = []
    records = []

    def collect(factory, fixture, control, treatment, **kwargs):
        calls.append((fixture.id, kwargs, copy.deepcopy(control),
                      copy.deepcopy(treatment)))
        job = {
            "fixture_id": fixture.id, "seed": kwargs["seed"],
            "mode": kwargs["mode"], "expected_legal_count": kwargs["expected_legal_count"],
        }
        if collector_error is not None:
            raise collector_error
        factory()
        return _panel(analysis, job, drift=kwargs["seed"] == drift_seed)

    monkeypatch.setattr(worker, "collect_public_fixture_panel", collect)
    return analysis, fixtures, calls, records


def test_collects_in_plan_order_with_expected_dispatch_and_receipt(monkeypatch):
    analysis, fixtures, calls, records = _setup(monkeypatch)
    seeds = []
    budgets = []

    def factory(seed):
        seeds.append(seed)
        return object()

    receipt = worker.collect_m9_panels(
        analysis, fixtures, factory, on_panel=records.append,
        check_budget=lambda: budgets.append(1))
    assert receipt == {"schema": "m9-panel-collection-v1",
                      "completed_panels": 15, "primary_panels": 3,
                      "secondary_panels": 12,
                      "provenance_verified": False,
                      "serving_choice_assessed": False}
    assert len(calls) == len(records) == 15
    assert len(budgets) == len(seeds) == 15
    assert [record["job"]["seed"] for record in records[:3]] == [0, 1, 2]
    assert all(record["replay_consistency"] is not None for record in records[:3])
    assert all(record["replay_consistency"] is None for record in records[3:])
    assert records[0]["ledger_cadence"] == "fresh-root"
    assert records[3]["ledger_cadence"] == "single-seat-actor-turns"
    expected = build_m9_panel_plan(analysis)
    assert [fixture_id for fixture_id, _, _, _ in calls] == [
        job["fixture_id"] for job in expected]
    assert [kwargs["mode"] for _, kwargs, _, _ in calls] == (
        ["fresh-root"] * 3 + ["history-primed"] * 12)
    assert [kwargs["seed"] for _, kwargs, _, _ in calls] == [
        job["seed"] for job in expected]
    assert [(control, treatment) for _, _, control, treatment in calls] == [
        (job["control_ballot"], job["treatment_ballot"]) for job in expected]
    assert [kwargs["fill_seed"] for _, kwargs, _, _ in calls] == [0] * 15
    assert [kwargs["expected_legal_count"] for _, kwargs, _, _ in calls] == [
        job["expected_legal_count"] for job in expected]


def test_fixture_shape_is_rejected_before_factory(monkeypatch):
    analysis = _analysis()
    calls = []
    fixtures = [SimpleNamespace(id=root_id, seat=0) for root_id in ROOTS[:-1]]
    with pytest.raises(ValueError):
        worker.collect_m9_panels(analysis, fixtures,
                                 lambda seed: calls.append(seed),
                                 on_panel=lambda record: None)
    assert calls == []


def test_duplicate_fixture_ids_are_rejected_before_factory(monkeypatch):
    analysis = _analysis()
    fixtures = [SimpleNamespace(id=root_id, seat=0) for root_id in ROOTS]
    fixtures[-1].id = fixtures[0].id
    calls = []
    with pytest.raises(ValueError):
        worker.collect_m9_panels(analysis, fixtures,
                                 lambda seed: calls.append(seed),
                                 on_panel=lambda record: None)
    assert calls == []


def test_replay_mismatch_stops_before_primed_jobs(monkeypatch):
    analysis, fixtures, calls, records = _setup(monkeypatch, drift_seed=1)
    with pytest.raises(ValueError, match="means differ"):
        worker.collect_m9_panels(analysis, fixtures, lambda seed: object(),
                                 on_panel=records.append)
    assert len(calls) == 2
    assert len(records) == 2
    failed = records[1]
    assert failed["validation_status"] == "failed"
    assert failed["replay_consistency"] is None
    assert "control" in failed["replay_failure"]["message"]
    means = failed["replay_failure"]["arms"]["control"]
    assert means["saved_value_means"][0] == 0.0
    assert means["captured_value_means"][0] == 1.0
    assert failed["panel"]["collection"]["captures"]["control"]["serving_value_means"] == means["captured_value_means"]
    assert all(kwargs["mode"] == "fresh-root" for _, kwargs, _, _ in calls)


def test_sampler_and_callback_failures_are_not_retried(monkeypatch):
    analysis, fixtures, calls, records = _setup(
        monkeypatch, collector_error=RuntimeError("sampler failed"))
    with pytest.raises(RuntimeError, match="sampler"):
        worker.collect_m9_panels(analysis, fixtures, lambda seed: object(),
                                 on_panel=records.append)
    assert len(calls) == 1

    analysis, fixtures, calls, records = _setup(monkeypatch)
    def fail_callback(record):
        records.append(record)
        raise RuntimeError("callback failed")
    with pytest.raises(RuntimeError, match="callback"):
        worker.collect_m9_panels(analysis, fixtures, lambda seed: object(),
                                 on_panel=fail_callback)
    assert len(calls) == len(records) == 1


def test_failed_evidence_callback_preserves_replay_error(monkeypatch):
    analysis, fixtures, calls, records = _setup(monkeypatch, drift_seed=0)
    def fail(record):
        records.append(record)
        raise OSError("disk unavailable")
    with pytest.raises(ValueError, match="means differ") as caught:
        worker.collect_m9_panels(analysis, fixtures, lambda seed: object(), on_panel=fail)
    assert isinstance(caught.value.__cause__, OSError)
    assert records[0]["validation_status"] == "failed"
    assert len(calls) == 1


def test_malformed_capture_still_delivered_as_failed_evidence(monkeypatch):
    analysis, fixtures, calls, records = _setup(monkeypatch)
    original = worker.collect_public_fixture_panel
    def malformed(*args, **kwargs):
        panel = original(*args, **kwargs)
        panel["collection"] = None
        return panel
    monkeypatch.setattr(worker, "collect_public_fixture_panel", malformed)
    with pytest.raises(ValueError, match="collection"):
        worker.collect_m9_panels(analysis, fixtures, lambda seed: object(), on_panel=records.append)
    assert records[0]["validation_status"] == "failed"
    assert records[0]["replay_failure"]["arms"]["control"]["captured_value_means"] is None
    assert len(calls) == 1


def test_metadata_drift_is_rejected(monkeypatch):
    analysis, fixtures, calls, records = _setup(monkeypatch)
    collector = worker.collect_public_fixture_panel

    def drift(*args, **kwargs):
        panel = dict(collector(*args, **kwargs))
        panel["legal_count"] += 1
        return panel

    monkeypatch.setattr(worker, "collect_public_fixture_panel", drift)
    with pytest.raises(ValueError, match="legal pool"):
        worker.collect_m9_panels(analysis, fixtures, lambda seed: object(),
                                 on_panel=records.append)
    assert len(calls) == 1 and records == []


def test_inputs_are_not_mutated(monkeypatch):
    analysis, fixtures, calls, records = _setup(monkeypatch)
    original = copy.deepcopy(analysis)
    worker.collect_m9_panels(analysis, fixtures, lambda seed: object(),
                             on_panel=lambda record: None)
    assert analysis == original


def test_callback_mutation_cannot_change_later_jobs_or_fixtures(monkeypatch):
    analysis, fixtures, calls, records = _setup(monkeypatch)
    original_ids = [fixture.id for fixture in fixtures]

    def mutate(record):
        first = not records
        records.append(record)
        if first:
            record["job"]["control_ballot"][0][0] = "CJ"
            record["panel"]["fixture_id"] = "mutated"
            fixtures[0].id = "mutated-original"
        else:
            assert record["job"]["control_ballot"][0][0] != "CJ"

    worker.collect_m9_panels(analysis, fixtures, lambda seed: object(),
                             on_panel=mutate)
    assert [fixture.id for fixture in fixtures] != original_ids
    assert [fixture_id for fixture_id, _, _, _ in calls] == (
        [ROOTS[0]] * 6 + [ROOTS[1]] * 3 + [ROOTS[2]] * 3 + [ROOTS[3]] * 3)

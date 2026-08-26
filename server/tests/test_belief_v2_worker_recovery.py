"""Wiring witnesses for source-bound BELIEF V2 supervisor recovery."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "belief_v2_worker.py"


def _load_worker():
    spec = importlib.util.spec_from_file_location(
        "belief_v2_worker_recovery_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _root_binding(module, monkeypatch, root):
    freeze = SimpleNamespace()
    admission = SimpleNamespace()
    marker = b"review"
    inventory = {}
    group_split = {}
    monkeypatch.setattr(
        module, "_load_root",
        lambda requested: (
            freeze, admission, marker, inventory, group_split)
        if requested == root else (_ for _ in ()).throw(
            AssertionError("unexpected root")))
    monkeypatch.setattr(module, "_output", lambda _payload: None)
    return freeze, admission


def test_freeze_design_forces_one_consolidated_source_and_freeze_review(
        tmp_path, monkeypatch):
    module = _load_worker()
    expected_git = "a" * 40
    evidence = (tmp_path / "evidence").resolve()
    output = (tmp_path / "freeze.json").resolve()
    captured = {}

    class Freeze:
        execution_git = expected_git
        source_review_commit = expected_git
        training_candidate_device = "cpu"

        @staticmethod
        def canonical_bytes():
            return b"freeze\n"

        @staticmethod
        def sha256():
            return "b" * 64

    monkeypatch.setattr(module, "stable_read_bytes", lambda _path: b"{}\n")
    monkeypatch.setattr(
        module, "resource_caps_from_bytes", lambda _raw: object())
    monkeypatch.setattr(
        module, "build_execution_freeze_from_receipts",
        lambda **kwargs: captured.update(kwargs) or Freeze())
    monkeypatch.setattr(
        module, "publish_exclusive_bytes",
        lambda path, raw: "b" * 64
        if path == output and raw == b"freeze\n"
        else (_ for _ in ()).throw(AssertionError("freeze publish drift")))
    emitted = []
    monkeypatch.setattr(module, "_output", emitted.append)
    args = SimpleNamespace(
        out=str(output), evidence_root=str(evidence),
        expected_git=expected_git, v2_reentry_rationale=None,
        v1_terminal_report="terminal.json",
        v1_resource_failure_receipt=None, inventory="inventory.json",
        group_split="split.json", preflight_result="preflight.json",
        seed_scan="scan.json", seed_registry="registry.json",
        training_candidate_device="cpu",
        deadline_estimate_receipt="deadline.json",
        resource_caps="caps.json")

    module.freeze_design(args)

    assert captured["source_review_commit"] == expected_git
    assert emitted == [{
        "freeze_path": str(output), "freeze_sha256": "b" * 64,
        "execution_git": expected_git,
        "source_review_commit": expected_git,
        "source_review_mode": "consolidated-source-and-freeze",
        "training_candidate_device": "cpu",
        "bounded_offline_pipeline_authorized": False,
        "execution_started": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }]


def test_reference_recovery_uses_manifest_boundary_not_world_reopen(
        tmp_path, monkeypatch):
    module = _load_worker()
    root = (tmp_path / "evidence").resolve()
    final = root / "reference" / "lane-00"
    final.mkdir(parents=True)
    freeze, admission = _root_binding(module, monkeypatch, root)
    observed = []
    monkeypatch.setattr(
        module, "reopen_reference_lane_manifest",
        lambda directory, **kwargs: observed.append((directory, kwargs)) or {
            "reopened": True})
    monkeypatch.setattr(
        module, "run_reference_lane",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("recovery regenerated reference worlds")))

    module.reference_lane(SimpleNamespace(
        root=str(root), lane=0, recover_existing=True))

    assert observed == [(final, {
        "capture_directory": root / "capture" / "lane-00",
        "freeze": freeze, "admission": admission, "lane": 0})]


def test_completed_recovery_task_refuses_missing_final_before_regeneration(
        tmp_path, monkeypatch):
    module = _load_worker()
    root = (tmp_path / "evidence").resolve()
    _root_binding(module, monkeypatch, root)
    monkeypatch.setattr(
        module, "run_capture_lane",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("completed recovery task regenerated output")))

    with pytest.raises(ValueError, match="completed recovery artifact"):
        module.capture_lane(SimpleNamespace(
            root=str(root), lane=0, recover_existing=True,
            require_existing_final=True))

    with pytest.raises(ValueError, match="flag requires recovery"):
        module.capture_lane(SimpleNamespace(
            root=str(root), lane=0, recover_existing=False,
            require_existing_final=True))


def test_human_test_reference_recovery_never_opens_reference_bytes(
        tmp_path, monkeypatch):
    module = _load_worker()
    root = (tmp_path / "evidence").resolve()
    source = (tmp_path / "human.jsonl").resolve()
    source.write_bytes(b"source\n")
    source.chmod(0o400)
    digest = module._human_group_digest(source)
    final = (root / "human-reference" / f"group-{digest}"
             / "test-primary")
    final.mkdir(parents=True)
    freeze, admission = _root_binding(module, monkeypatch, root)
    observed = []
    monkeypatch.setattr(
        module, "reopen_human_reference_group_manifest",
        lambda directory, **kwargs: observed.append((directory, kwargs)) or {
            "reopened": True})
    monkeypatch.setattr(
        module, "run_human_reference_group",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("recovery regenerated human reference worlds")))

    module.human_reference(SimpleNamespace(
        root=str(root), source_path=str(source), replicate="test-primary",
        recover_existing=True))

    assert observed == [(final, {
        "freeze": freeze, "admission": admission})]


def test_training_recovery_reaches_exact_partial_and_reopens_final(
        tmp_path, monkeypatch):
    module = _load_worker()
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze, admission = _root_binding(module, monkeypatch, root)
    primary = SimpleNamespace(
        cohort_id="synthetic-primary", kind="synthetic")
    realization = SimpleNamespace(
        cohort_id="human-mixture", kind="human-mixture")
    calibration = object()
    inputs = SimpleNamespace(
        realizations=(primary, realization),
        common_calibration=calibration)
    plan, result = object(), object()
    calibration_factory = lambda: iter(())
    cache_sha = "c" * 64
    monkeypatch.setattr(
        module, "reopen_training_input_index", lambda *args, **kwargs: (
            {}, inputs))
    monkeypatch.setattr(
        module, "reopen_device_qualification", lambda *args, **kwargs: (
            {}, plan, result))
    monkeypatch.setattr(
        module, "reopen_training_tensor_cache", lambda *args, **kwargs: (
            {}, {realization.cohort_id: lambda: iter(())},
            calibration_factory, 0, cache_sha))
    partial = root / "training" / f"{realization.cohort_id}.partial"
    partial.mkdir(parents=True)
    runs = []
    monkeypatch.setattr(
        module, "run_training_cohort",
        lambda *args, **kwargs: runs.append((args, kwargs)) or {
            "resumed": True})
    monkeypatch.setattr(
        module, "reopen_training_cohort_checkpoint_identity",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("partial recovery used final reopener")))
    args = SimpleNamespace(
        root=str(root), cohort_id=realization.cohort_id,
        recover_existing=True)

    module.train_cohort(args)

    assert len(runs) == 1
    assert runs[0][1]["cache_manifest_sha256"] == cache_sha
    assert runs[0][1]["calibration_batch_factory"] is calibration_factory
    assert runs[0][1]["cache_control_dose"] == 0

    final = root / "training" / realization.cohort_id
    partial.rename(final)
    runs.clear()
    reopens = []
    monkeypatch.setattr(
        module, "reopen_training_cohort_checkpoint_identity",
        lambda directory, **kwargs: reopens.append((directory, kwargs)) or (
            {"reopened": True}, object()))

    module.train_cohort(args)

    assert not runs
    assert reopens[0][0] == final
    assert reopens[0][1]["cache_manifest_sha256"] == cache_sha
    assert "calibration_batch_factory" not in reopens[0][1]
    assert reopens[0][1]["compact_control_dose"] == 0


def test_sealed_terminal_recovery_reopens_and_never_creates_second_opening(
        tmp_path, monkeypatch):
    module = _load_worker()
    root = (tmp_path / "evidence").resolve()
    final = root / "terminal"
    final.mkdir(parents=True)
    freeze, admission = _root_binding(module, monkeypatch, root)
    observed = []
    projection_token = object()
    warmed = []

    class Pool:
        def __enter__(self):
            return projection_token

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(module, "projection_pool", Pool)
    monkeypatch.setattr(
        module, "warm_projection_pool",
        lambda executor: warmed.append(executor))
    monkeypatch.setattr(
        module, "reopen_v2_terminal",
        lambda directory, **kwargs: observed.append((directory, kwargs)) or {
            "reopened": True})
    monkeypatch.setattr(
        module, "run_v2_terminal",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("recovery created a second test opening")))

    module.open_test(SimpleNamespace(
        root=str(root), recover_existing=True))

    assert len(observed) == 1
    assert observed[0][0] == final
    assert observed[0][1]["freeze"] is freeze
    assert observed[0][1]["admission"] is admission
    assert observed[0][1]["projection_executor"] is projection_token
    assert warmed == [projection_token]

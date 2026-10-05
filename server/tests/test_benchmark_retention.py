from __future__ import annotations

import hashlib
import copy
import json
from pathlib import Path

import pytest

from shengji.luna import benchmark_retention as retention
from shengji.luna.canonical import canonical_json_bytes


def _repin_report(plan, source, report):
    """Synthetic plan authoring only; never opens historical artifacts."""
    raw = canonical_json_bytes(report)
    (source / "result.json").write_bytes(raw)
    obj = json.loads(plan.read_text())
    obj["result_sha256"] = hashlib.sha256(raw).hexdigest()
    plan.write_bytes(canonical_json_bytes(obj))
    return hashlib.sha256(plan.read_bytes()).hexdigest()


def _config(*, seed=7, roots=None):
    return {
        "seeds": [seed], "models": ["sol"],
        "information": ["actor-only", "perfect"],
        "policy": "smart", "baseline_recipe": {"recipe": "smart"},
        "checkpoint": {"path": "/tmp/model.npz", "sha256": "a" * 64},
        "prepared_roots_from": roots or {
            "path": "/old/root", "result_sha256": "b" * 64,
            "root_hashes": {str(seed): "c" * 64},
            "source_config": {"old": "ignored"},
        },
    }


def _row(model, mode, seed, flip, *, kind="complete"):
    key = f"{model}-{mode}-seed{seed}-flip{flip}"
    row = {
        "schema": "w32-llm-benchmark-mirror-v1", "key": key,
        "arm": f"{model}-{mode}", "model": model, "information": mode,
        "seed": seed, "flip": flip, "calls": [], "events": [],
    }
    if kind == "complete":
        row.update(complete=True, signed_levels=1.5)
    elif kind == "pending":
        row.update(complete=False, status="not_run")
    elif kind == "typed":
        row.update(
            complete=False, error="IllegalPlay: must follow",
            events=[{"seat": flip, "attempted_cards": ["C2"]}],
            failure={"schema": "benchmark-action-failure-v1",
                     "category": "model_illegal_action", "stage": "engine_play",
                     "seat": flip, "attempted_cards": ["C2"], "event_index": 0})
    return row


def _write_source(tmp_path: Path, *, kinds=None, config=None):
    source = tmp_path / "source"
    source.mkdir()
    config = config or _config()
    seed = config["seeds"][0]
    kinds = kinds or {("actor-only", 0): "complete",
                      ("actor-only", 1): "typed",
                      ("perfect", 0): "pending",
                      ("perfect", 1): "complete"}
    mirrors = []
    for mode in config["information"]:
        for flip in (0, 1):
            row = _row("sol", mode, seed, flip,
                       kind=kinds[(mode, flip)])
            mirrors.append(row)
            (source / f"mirror-sol-{mode}-{seed}-{flip}.json").write_bytes(
                canonical_json_bytes(row))
    report = {
        "schema": "w32-llm-benchmark-v1", "mode": "run",
        "config": config, "mirrors": mirrors, "prior": None,
    }
    result_raw = canonical_json_bytes(report)
    (source / "result.json").write_bytes(result_raw)
    plan = {
        "schema": "benchmark-retention-v1",
        "source_directory": str(source),
        "result_sha256": hashlib.sha256(result_raw).hexdigest(),
        "legacy_illegal_sha256": [],
    }
    plan_path = tmp_path / "plan.json"
    plan_raw = canonical_json_bytes(plan)
    plan_path.write_bytes(plan_raw)
    return plan_path, hashlib.sha256(plan_raw).hexdigest(), config, source


def test_loads_typed_complete_pending_and_cost_without_mutation(tmp_path):
    plan, plan_sha, config, source = _write_source(tmp_path)
    # Add usage to one original source row; cached tokens are intentionally ignored.
    path = source / "mirror-sol-actor-only-7-0.json"
    row = json.loads(path.read_text())
    row["calls"] = [{"usage": {"input_tokens": 4, "output_tokens": 3,
                                  "cached_tokens": 999}}]
    raw = canonical_json_bytes(row)
    path.write_bytes(raw)
    result = json.loads((source / "result.json").read_text())
    result["mirrors"][0] = row
    result_raw = canonical_json_bytes(result)
    (source / "result.json").write_bytes(result_raw)
    plan_obj = json.loads(plan.read_text())
    plan_obj["result_sha256"] = hashlib.sha256(result_raw).hexdigest()
    plan.write_bytes(canonical_json_bytes(plan_obj))
    plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest()

    loaded = retention.load_retained_attempts(plan, plan_sha,
                                               expected_config=config)
    assert set(loaded["rows"]) == {
        "sol-actor-only-seed7-flip0", "sol-actor-only-seed7-flip1",
        "sol-perfect-seed7-flip0", "sol-perfect-seed7-flip1"}
    assert loaded["rows"]["sol-perfect-seed7-flip0"]["status"] == "not_run"
    assert loaded["rows"]["sol-actor-only-seed7-flip1"]["failure"]["schema"] \
        == "benchmark-action-failure-v1"
    assert loaded["prior_cost_tokens"] == 7
    loaded["rows"]["sol-actor-only-seed7-flip0"]["complete"] = False
    assert json.loads(path.read_text())["complete"] is True


def test_generic_untyped_failure_refuses(tmp_path):
    plan, plan_sha, config, source = _write_source(tmp_path)
    path = source / "mirror-sol-actor-only-7-1.json"
    row = json.loads(path.read_text())
    row.update(complete=False, error="RuntimeError: provider", events=[])
    path.write_bytes(canonical_json_bytes(row))
    report = json.loads((source / "result.json").read_text())
    report["mirrors"][1] = row
    result_raw = canonical_json_bytes(report)
    (source / "result.json").write_bytes(result_raw)
    plan_obj = json.loads(plan.read_text())
    plan_obj["result_sha256"] = hashlib.sha256(result_raw).hexdigest()
    plan.write_bytes(canonical_json_bytes(plan_obj))
    with pytest.raises(retention.RetentionRefusal, match="unclassified"):
        retention.load_retained_attempts(
            plan, hashlib.sha256(plan.read_bytes()).hexdigest(),
            expected_config=config)


def test_prepared_root_comparison_ignores_path_and_source_config(tmp_path):
    plan, plan_sha, config, _ = _write_source(tmp_path)
    expected = dict(config)
    expected["prepared_roots_from"] = {
        "path": "/different/absolute/path", "result_sha256": "b" * 64,
        "root_hashes": {"7": "c" * 64}, "source_config": {"new": True},
    }
    loaded = retention.load_retained_attempts(plan, plan_sha,
                                               expected_config=expected)
    assert loaded["result_sha256"]


def test_exact_legacy_witness_can_be_explicitly_allowlisted(tmp_path, monkeypatch):
    assert retention.LEGACY_SHA256 == (
        "71e197bc10ae73bc25e9bf22e7702b48fd32a49b53830c76321b9c85b09b8949")
    seed = 20261002006
    config = _config(seed=seed)
    config["information"] = ["perfect"]
    legacy = _row("sol", "perfect", seed, 1)
    legacy.update(complete=False, error=retention.LEGACY_ERROR,
                  events=[{"seat": 0, "attempted_cards": ["C2"]}] * 22
                  + [{"seat": 3, "attempted_cards": ["C7"]}])
    source = tmp_path / "source"
    source.mkdir()
    other = _row("sol", "perfect", seed, 0)
    for row in (other, legacy):
        (source / f"mirror-sol-perfect-{seed}-{row['flip']}.json").write_bytes(
            canonical_json_bytes(row))
    report = {"schema": "w32-llm-benchmark-v1", "mode": "run",
              "config": config, "mirrors": [other, legacy], "prior": None}
    result_raw = canonical_json_bytes(report)
    (source / "result.json").write_bytes(result_raw)
    legacy_sha = hashlib.sha256(
        (source / f"mirror-sol-perfect-{seed}-1.json").read_bytes()).hexdigest()
    monkeypatch.setattr(retention, "LEGACY_SHA256", legacy_sha)
    plan = {"schema": "benchmark-retention-v1", "source_directory": str(source),
            "result_sha256": hashlib.sha256(result_raw).hexdigest(),
            "legacy_illegal_sha256": [legacy_sha]}
    plan_path = tmp_path / "plan.json"
    plan_path.write_bytes(canonical_json_bytes(plan))
    loaded = retention.load_retained_attempts(
        plan_path, hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        expected_config=config)
    copied = loaded["rows"][retention.LEGACY_KEY]
    assert copied["failure"]["event_index"] == 22
    assert copied["retention_provenance"] == {
        "original_sha256": legacy_sha, "reference": retention.LEGACY_REFERENCE}


@pytest.mark.parametrize("target", ["plan", "report", "mirror"])
def test_tampered_bytes_refuse(tmp_path, target):
    plan, pin, config, source = _write_source(tmp_path)
    if target == "plan":
        plan.write_bytes(plan.read_bytes() + b" ")
    elif target == "report":
        path = source / "result.json"
        path.write_bytes(path.read_bytes() + b" ")
    else:
        path = source / "mirror-sol-actor-only-7-0.json"
        row = json.loads(path.read_text())
        row["signed_levels"] = -1
        path.write_bytes(canonical_json_bytes(row))
    with pytest.raises(retention.RetentionRefusal, match="mismatch|disagrees"):
        retention.load_retained_attempts(plan, pin, expected_config=config)


@pytest.mark.parametrize("field", ["seeds", "models", "information", "policy",
                                  "baseline_recipe", "checkpoint", "prepared_roots_from"])
def test_expected_configuration_mismatch_refuses(tmp_path, field):
    plan, pin, config, _ = _write_source(tmp_path)
    expected = copy.deepcopy(config)
    expected[field] = None
    with pytest.raises(retention.RetentionRefusal, match="disagrees"):
        retention.load_retained_attempts(plan, pin, expected_config=expected)


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "wrong_flip", "prior", "retention"])
def test_authenticated_but_invalid_report_refuses(tmp_path, mutation):
    plan, _, config, source = _write_source(tmp_path)
    report = json.loads((source / "result.json").read_text())
    if mutation == "duplicate":
        report["mirrors"].append(copy.deepcopy(report["mirrors"][0]))
    elif mutation == "missing":
        report["mirrors"].pop()
    elif mutation == "wrong_flip":
        report["mirrors"][0]["flip"] = False
    elif mutation == "prior":
        report["prior"] = {"old": "report"}
    else:
        report["config"]["retained_from"] = "/old/report"
    pin = _repin_report(plan, source, report)
    with pytest.raises(retention.RetentionRefusal):
        retention.load_retained_attempts(plan, pin, expected_config=config)


def test_symlink_mirror_refuses(tmp_path):
    plan, pin, config, source = _write_source(tmp_path)
    path = source / "mirror-sol-actor-only-7-0.json"
    moved = source / "original.json"
    path.rename(moved)
    path.symlink_to(moved)
    with pytest.raises(retention.RetentionRefusal, match="regular file"):
        retention.load_retained_attempts(plan, pin, expected_config=config)


def test_duplicate_json_keys_refuse_even_with_matching_plan_pin(tmp_path):
    plan, _, config, _ = _write_source(tmp_path)
    raw = plan.read_bytes()
    plan.write_bytes(b'{"schema":"benchmark-retention-v1",' + raw[1:])
    with pytest.raises(retention.RetentionRefusal, match="duplicate JSON key"):
        retention.load_retained_attempts(
            plan, hashlib.sha256(plan.read_bytes()).hexdigest(), expected_config=config)

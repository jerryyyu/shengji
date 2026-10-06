from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from shengji.luna import benchmark_retention as retention
from shengji.luna.benchmark_recovery_source import load_recovery_source
from shengji.luna.benchmark_retained_content import validate_retained_content
from shengji.luna.canonical import canonical_json_bytes
from test_benchmark_retained_content import _report, _source


def _fixture(tmp_path: Path):
    loaded, plan, plan_sha = _source(tmp_path)
    report = _report(loaded, plan, plan_sha)
    report["config"]["baseline_recipe"] = {"recipe": "smart"}
    report["budget"] = {
        "tokens": 0, "new_tokens": 0, "prior_tokens": 0,
        "combined_tokens": 0,
    }
    source = Path(loaded["path"])
    for row in report["mirrors"]:
        (source / f"mirror-sol-{row['information']}-{row['seed']}-{row['flip']}.json").write_bytes(
            canonical_json_bytes(row))
    result_raw = canonical_json_bytes(report)
    (source / "result.json").write_bytes(result_raw)
    result_sha = hashlib.sha256(result_raw).hexdigest()
    expected = copy.deepcopy(report["config"])
    expected.pop("retained_attempts")
    return loaded, source, report, expected, result_sha


def _load(tmp_path: Path):
    loaded, source, report, expected, result_sha = _fixture(tmp_path)
    return (load_recovery_source(
        source, result_sha, expected_config=expected,
        authenticated_retention=loaded), loaded, source, report, expected
    )


def test_authenticates_report_sidecars_and_audits_without_retained_input(tmp_path):
    result, loaded, source, report, _ = _load(tmp_path)
    assert result["report"] == report
    assert result["source_pins"] == {
        "path": str(source), "result_sha256": result["result_sha256"]}
    assert len(result["source_rows"]) == 40
    assert result["lineage"]["status"] == "retained-lineage-verified"
    assert result["costs"] == {
        "status": "retained-recorded-costs-verified", "tokens": 0,
        "new_tokens": 0, "prior_tokens": 0, "combined_tokens": 0,
    }
    assert "rows" not in result and "prior_cost_tokens" not in result
    assert all(item["path"].startswith(str(source))
               for item in result["source_rows"].values())


def test_unknown_new_failure_is_preserved_but_not_terminally_accepted(tmp_path):
    loaded, source, report, expected, _ = _fixture(tmp_path)
    row = next(row for row in report["mirrors"]
               if row["key"] == "sol-perfect-seed10-flip0")
    row.pop("signed_levels")
    row.update(complete=False, error="RuntimeError: unknown rollout failure")
    for item in report["mirrors"]:
        (source / f"mirror-sol-{item['information']}-{item['seed']}-{item['flip']}.json").write_bytes(
            canonical_json_bytes(item))
    raw = canonical_json_bytes(report)
    (source / "result.json").write_bytes(raw)
    result = load_recovery_source(
        source, hashlib.sha256(raw).hexdigest(), expected_config=expected,
        authenticated_retention=loaded)
    recovered = next(item for item in result["report"]["mirrors"]
                     if item["key"] == "sol-perfect-seed10-flip0")
    assert recovered["error"] == "RuntimeError: unknown rollout failure"
    with pytest.raises(ValueError, match="unknown failure"):
        validate_retained_content(report, loaded)


def test_recovery_source_requires_authenticated_retention(tmp_path):
    _, source, _, expected, result_sha = _fixture(tmp_path)
    with pytest.raises(ValueError, match="authenticated retention"):
        load_recovery_source(
            source, result_sha, expected_config=expected,
            authenticated_retention=None)


def test_inherited_row_drift_is_refused_even_when_sidecar_matches(tmp_path):
    loaded, source, report, expected, _ = _fixture(tmp_path)
    row = next(row for row in report["mirrors"]
               if row["key"] == "sol-actor-only-seed10-flip0")
    row["events"] = [{"tampered": True}]
    (source / "mirror-sol-actor-only-10-0.json").write_bytes(
        canonical_json_bytes(row))
    raw = canonical_json_bytes(report)
    (source / "result.json").write_bytes(raw)
    with pytest.raises(ValueError, match="retained attempt content changed"):
        load_recovery_source(
            source, hashlib.sha256(raw).hexdigest(), expected_config=expected,
            authenticated_retention=loaded)


def test_recovery_source_audits_nonzero_prior_and_new_costs(tmp_path):
    authenticated0, plan, _ = _source(tmp_path)
    source = Path(authenticated0["path"])
    source_result = json.loads((source / "result.json").read_text())
    source_row = next(row for row in source_result["mirrors"]
                      if row["key"] == "sol-actor-only-seed10-flip0")
    source_row["calls"] = [{"usage": {"input_tokens": 4, "output_tokens": 3}}]
    (source / "mirror-sol-actor-only-10-0.json").write_bytes(
        canonical_json_bytes(source_row))
    source_result["mirrors"][0] = source_row
    source_raw = canonical_json_bytes(source_result)
    (source / "result.json").write_bytes(source_raw)
    plan_obj = json.loads(plan.read_text())
    plan_obj["result_sha256"] = hashlib.sha256(source_raw).hexdigest()
    plan.write_bytes(canonical_json_bytes(plan_obj))
    plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest()
    authenticated = retention.load_retained_attempts(
        plan, plan_sha, expected_config=source_result["config"])
    report = _report(authenticated, plan, plan_sha)
    report["config"]["baseline_recipe"] = {"recipe": "smart"}
    report["budget"] = {
        "tokens": 5, "new_tokens": 5, "prior_tokens": 7,
        "combined_tokens": 12,
    }
    new = next(row for row in report["mirrors"] if "lineage" not in row)
    new["calls"] = [{"usage": {"input_tokens": 2, "output_tokens": 3}}]
    expected = copy.deepcopy(report["config"])
    expected.pop("retained_attempts")
    for item in report["mirrors"]:
        (source / f"mirror-sol-{item['information']}-{item['seed']}-{item['flip']}.json").write_bytes(
            canonical_json_bytes(item))
    raw = canonical_json_bytes(report)
    (source / "result.json").write_bytes(raw)
    result = load_recovery_source(
        source, hashlib.sha256(raw).hexdigest(), expected_config=expected,
        authenticated_retention=authenticated)
    assert result["costs"] == {
        "status": "retained-recorded-costs-verified", "tokens": 5,
        "new_tokens": 5, "prior_tokens": 7, "combined_tokens": 12,
    }


@pytest.mark.parametrize("mutation", ["hash", "sidecar", "missing", "extra", "alias",
                                       "continuation", "unbound", "recipe", "roots", "budget"])
def test_recovery_source_refuses_authentication_drift(tmp_path, mutation):
    loaded, source, report, expected, result_sha = _fixture(tmp_path)
    if mutation == "hash":
        result_sha = "0" * 64
    elif mutation == "sidecar":
        path = source / "mirror-sol-actor-only-10-0.json"
        value = json.loads(path.read_text())
        value["events"] = [{"changed": True}]
        path.write_bytes(canonical_json_bytes(value))
    elif mutation == "missing":
        (source / "mirror-sol-actor-only-10-0.json").unlink()
    elif mutation == "extra":
        (source / "mirror-sol-extra.json").write_text("{}")
    elif mutation == "alias":
        report["retention_plan"] = {}
    elif mutation == "continuation":
        report["prior"] = {"source": "/old"}
    elif mutation == "unbound":
        report["config"].pop("retained_attempts")
        report.pop("retained_attempts")
    elif mutation == "recipe":
        report["config"]["baseline_recipe"]["recipe"] = "other"
    elif mutation == "roots":
        report["config"]["prepared_roots_from"] = {
            "result_sha256": "a" * 64, "root_hashes": {"10": "b" * 64}}
    elif mutation == "budget":
        report["budget"]["combined_tokens"] = 1
    if mutation not in {"sidecar", "missing", "extra"}:
        raw = canonical_json_bytes(report)
        (source / "result.json").write_bytes(raw)
        if mutation != "hash":
            result_sha = hashlib.sha256(raw).hexdigest()
    with pytest.raises((ValueError, retention.RetentionRefusal)):
        load_recovery_source(
            source, result_sha, expected_config=expected,
            authenticated_retention=loaded)


def test_symlink_sidecar_is_rejected(tmp_path):
    loaded, source, report, expected, result_sha = _fixture(tmp_path)
    sidecar = source / "mirror-sol-actor-only-10-0.json"
    target = source / "real-sidecar.json"
    target.write_bytes(sidecar.read_bytes())
    sidecar.unlink()
    sidecar.symlink_to(target)
    with pytest.raises(ValueError):
        load_recovery_source(
            source, result_sha, expected_config=expected,
            authenticated_retention=loaded)

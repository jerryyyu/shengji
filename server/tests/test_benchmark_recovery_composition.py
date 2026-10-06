from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from shengji.luna import benchmark_retention as retention
from shengji.luna.benchmark_failure_protocol import PRESERVE_ILLEGAL, attempt_disposition
from shengji.luna.benchmark_recovery_composition import compose_recovery_sources
from shengji.luna.canonical import canonical_json_bytes
from test_benchmark_retained_content import _report, _source


def _write_report(directory: Path, report: dict) -> str:
    directory.mkdir(exist_ok=True)
    for row in report["mirrors"]:
        (directory / f"mirror-sol-{row['information']}-{row['seed']}-{row['flip']}.json").write_bytes(
            canonical_json_bytes(row))
    raw = canonical_json_bytes(report)
    (directory / "result.json").write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _fixture(tmp_path: Path):
    loaded, plan, plan_sha = _source(tmp_path)
    original_dir = Path(loaded["path"])
    original_result = json.loads((original_dir / "result.json").read_text())
    expected = copy.deepcopy(original_result["config"])

    report = _report(loaded, plan, plan_sha)
    report["config"]["baseline_recipe"] = {"recipe": "smart"}
    report["budget"] = {
        "tokens": 0, "new_tokens": 0, "prior_tokens": 0,
        "combined_tokens": 0,
    }
    recovery_dir = tmp_path / "recovery"
    recovery_sha = _write_report(recovery_dir, report)
    return loaded, plan, plan_sha, expected, recovery_dir, recovery_sha, report


def test_composes_exact_schedule_and_keeps_raw_provenance(tmp_path):
    loaded, plan, plan_sha, expected, recovery_dir, recovery_sha, report = _fixture(tmp_path)
    before = {path: path.read_bytes() for path in Path(loaded["path"]).iterdir()}
    recovery_before = {path: path.read_bytes() for path in recovery_dir.iterdir()}
    result = compose_recovery_sources(
        plan, plan_sha, recovery_dir, recovery_sha, expected_config=expected)

    assert result["schema"] == "benchmark-recovery-composition-v1"
    assert set(result) == {"schema", "original", "recovery", "slots", "costs"}
    assert len(result["slots"]) == 40
    assert result["original"] == {
        "path": loaded["path"], "result_sha256": loaded["result_sha256"],
        "plan": str(plan.resolve()), "plan_sha256": plan_sha,
    }
    assert result["recovery"]["path"] == str(recovery_dir)
    assert "rows" not in result and "prior_cost_tokens" not in result
    for key, slot in result["slots"].items():
        assert slot["original"] == loaded["source_rows"][key]
        assert slot["recovery"]["row"] == next(
            row for row in report["mirrors"] if row["key"] == key)
        assert slot["origin"] in {"original", "recovery"}
        assert slot["recorded_tokens"] >= 0
    typed_key = "sol-actor-only-seed10-flip1"
    assert result["slots"][typed_key]["origin"] == "original"
    assert result["slots"][typed_key]["row"] == loaded["rows"][typed_key]
    assert sum(slot["recorded_tokens"] for slot in result["slots"].values()) == 0
    assert {path: path.read_bytes() for path in Path(loaded["path"]).iterdir()} == before
    assert {path: path.read_bytes() for path in recovery_dir.iterdir()} == recovery_before


def test_old_and_new_costs_are_selected_once_and_unknown_failure_is_preserved(tmp_path):
    loaded, plan, plan_sha, expected, recovery_dir, _, report = _fixture(tmp_path)
    old_key = "sol-actor-only-seed10-flip0"
    old_source = Path(loaded["path"])
    old_row = next(row for row in json.loads((old_source / "result.json").read_text())["mirrors"]
                   if row["key"] == old_key)
    old_row["calls"] = [{"usage": {"input_tokens": 4, "output_tokens": 3}}]
    old_result = json.loads((old_source / "result.json").read_text())
    old_result["mirrors"][0] = old_row
    (old_source / f"mirror-sol-{old_row['information']}-{old_row['seed']}-{old_row['flip']}.json").write_bytes(
        canonical_json_bytes(old_row))
    old_raw = canonical_json_bytes(old_result)
    (old_source / "result.json").write_bytes(old_raw)
    plan_obj = json.loads(plan.read_text())
    plan_obj["result_sha256"] = hashlib.sha256(old_raw).hexdigest()
    plan.write_bytes(canonical_json_bytes(plan_obj))
    plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest()
    loaded = retention.load_retained_attempts(plan, plan_sha, expected_config=expected)

    report = _report(loaded, plan, plan_sha)
    report["config"]["baseline_recipe"] = {"recipe": "smart"}
    new_key = "sol-perfect-seed10-flip0"
    new = next(row for row in report["mirrors"] if row["key"] == new_key)
    new.pop("signed_levels")
    new.update(complete=False, error="RuntimeError: unknown rollout failure",
               calls=[{"usage": {"input_tokens": 2, "output_tokens": 3}}])
    report["budget"] = {"tokens": 5, "new_tokens": 5, "prior_tokens": 7,
                         "combined_tokens": 12}
    recovery_dir = tmp_path / "recovery-cost"
    recovery_sha = _write_report(recovery_dir, report)
    result = compose_recovery_sources(
        plan, plan_sha, recovery_dir, recovery_sha, expected_config=expected)

    assert result["costs"]["combined_tokens"] == 12
    assert sum(slot["recorded_tokens"] for slot in result["slots"].values()) == 12
    assert result["slots"][old_key]["origin"] == "original"
    assert result["slots"][old_key]["recorded_tokens"] == 7
    assert result["slots"][new_key]["origin"] == "recovery"
    assert result["slots"][new_key]["recorded_tokens"] == 5
    assert result["slots"][new_key]["row"]["error"] == "RuntimeError: unknown rollout failure"
    assert attempt_disposition(result["slots"][new_key]["row"],
                               protocol=PRESERVE_ILLEGAL) == "stop"


@pytest.mark.parametrize("mutation", ["hash", "recipe", "roots", "lineage",
                                       "reopen", "prior_attempt"])
def test_composition_refuses_authentication_or_nested_row_drift(tmp_path, mutation):
    loaded, plan, plan_sha, expected, recovery_dir, recovery_sha, report = _fixture(tmp_path)
    target_key = ("sol-perfect-seed10-flip0"
                  if mutation == "prior_attempt"
                  else "sol-actor-only-seed10-flip0")
    target = next(row for row in report["mirrors"] if row["key"] == target_key)
    if mutation == "hash":
        recovery_sha = "0" * 64
    elif mutation == "recipe":
        report["config"]["baseline_recipe"]["recipe"] = "other"
    elif mutation == "roots":
        report["config"]["prepared_roots_from"] = {
            "result_sha256": "a" * 64, "root_hashes": {"10": "b" * 64}}
    elif mutation == "lineage":
        target["lineage"]["source_row_sha256"] = "b" * 64
    elif mutation == "reopen":
        target.pop("lineage")
        target.pop("failure", None)
        target["complete"] = False
        target["status"] = "not_run"
    elif mutation == "prior_attempt":
        target["prior_attempt"] = {"path": "/nested"}
    if mutation != "hash":
        recovery_sha = _write_report(recovery_dir, report)
    with pytest.raises((ValueError, retention.RetentionRefusal)):
        compose_recovery_sources(
            plan, plan_sha, recovery_dir, recovery_sha, expected_config=expected)


@pytest.mark.parametrize("mutation", ["missing", "duplicate"])
def test_composition_refuses_schedule_loss(tmp_path, mutation):
    _, plan, plan_sha, expected, recovery_dir, recovery_sha, report = _fixture(tmp_path)
    if mutation == "missing":
        report["mirrors"].pop()
        (recovery_dir / "mirror-sol-perfect-19-1.json").unlink()
    else:
        report["mirrors"][-1] = copy.deepcopy(report["mirrors"][0])
    recovery_sha = _write_report(recovery_dir, report)
    with pytest.raises((ValueError, retention.RetentionRefusal)):
        compose_recovery_sources(
            plan, plan_sha, recovery_dir, recovery_sha, expected_config=expected)


def test_composition_rejects_same_and_alias_directories(tmp_path):
    loaded, plan, plan_sha, expected, recovery_dir, recovery_sha, _ = _fixture(tmp_path)
    with pytest.raises(ValueError, match="directories must differ"):
        compose_recovery_sources(
            plan, plan_sha, loaded["path"], recovery_sha, expected_config=expected)
    alias = tmp_path / "source-alias"
    alias.symlink_to(loaded["path"], target_is_directory=True)
    with pytest.raises(ValueError, match="directories must differ"):
        compose_recovery_sources(
            plan, plan_sha, alias,
            recovery_sha, expected_config=expected)


def test_composition_rejects_inherited_per_row_retry_even_with_valid_lineage(tmp_path):
    from test_benchmark_retention import _repin_report

    loaded, plan, _, expected, recovery_dir, _, _ = _fixture(tmp_path)
    source = Path(loaded["path"])
    original = json.loads((source / "result.json").read_bytes())
    original["mirrors"][0]["prior_attempt"] = {"cost_tokens": 99}
    _write_report(source, original)
    plan_sha = _repin_report(plan, source, original)
    authenticated = retention.load_retained_attempts(plan, plan_sha, expected_config=expected)
    report = _report(authenticated, plan, plan_sha)
    report["config"]["baseline_recipe"] = {"recipe": "smart"}
    report["budget"] = {"tokens": 0, "new_tokens": 0, "prior_tokens": 0,
                        "combined_tokens": 0}
    recovery_sha = _write_report(recovery_dir, report)
    with pytest.raises(retention.RetentionRefusal, match="original row .* prior_attempt"):
        compose_recovery_sources(plan, plan_sha, recovery_dir, recovery_sha,
                                 expected_config=expected)


def test_composition_refuses_unstatable_source_identity(tmp_path, monkeypatch):
    from shengji.luna import benchmark_recovery_composition as composition

    _, plan, plan_sha, expected, recovery_dir, recovery_sha, _ = _fixture(tmp_path)

    def unavailable(*args):
        raise OSError("identity unavailable")

    monkeypatch.setattr(composition.os.path, "samefile", unavailable)
    with pytest.raises(retention.RetentionRefusal, match="cannot compare"):
        compose_recovery_sources(plan, plan_sha, recovery_dir, recovery_sha,
                                 expected_config=expected)

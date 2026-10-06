from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from shengji.luna import benchmark_retention as retention
from shengji.luna.canonical import canonical_json_bytes

from test_benchmark_legacy_evidence import _legacy_fixture
from test_benchmark_retained_content import _report, _source


def _write_source_result(plan: Path, source: Path, report: dict) -> str:
    raw = canonical_json_bytes(report)
    (source / "result.json").write_bytes(raw)
    plan_obj = json.loads(plan.read_text())
    plan_obj["result_sha256"] = hashlib.sha256(raw).hexdigest()
    plan.write_bytes(canonical_json_bytes(plan_obj))
    return hashlib.sha256(plan.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> dict:
    """Build one authenticated recovery report with a real legacy trace.

    The retention source is adjusted before authentication so the scheduled
    new slot is perfect/seed10/flip1.  The trace itself is produced by the
    real fake-provider seam in test_benchmark_legacy_evidence; only its seed
    and source-relative evidence paths are adapted to that scheduled slot.
    """
    _, plan, _ = _source(tmp_path)
    source = tmp_path / "source"
    source_report = json.loads((source / "result.json").read_text())

    # Move the synthetic unattempted slot from flip0 to flip1.  This leaves
    # the target row unauthenticated while retaining the complete flip0 row.
    for row in source_report["mirrors"]:
        if row["key"] == "sol-perfect-seed10-flip0":
            row.pop("status", None)
            row.update(complete=True, signed_levels=2.0)
        elif row["key"] == "sol-perfect-seed10-flip1":
            row["complete"] = False
            row.pop("signed_levels", None)
            row["status"] = "not_run"
        (source / f"mirror-sol-{row['information']}-{row['seed']}-{row['flip']}.json").write_bytes(
            canonical_json_bytes(row))
    source_plan_sha = _write_source_result(plan, source, source_report)
    authenticated = retention.load_retained_attempts(
        plan, source_plan_sha, expected_config=source_report["config"])

    report = _report(authenticated, plan, source_plan_sha)
    report["config"]["baseline_recipe"] = {"recipe": "smart"}
    expected_config = copy.deepcopy(report["config"])
    expected_config.pop("retained_attempts")

    trace_root = tmp_path / "legacy-trace"
    trace_root.mkdir()
    trace = _legacy_fixture(trace_root)
    row = copy.deepcopy(trace["row"])
    row["seed"] = 10
    row["key"] = "sol-perfect-seed10-flip1"

    evidence_root = source / "evidence"
    evidence = {}
    call_pins = {}
    path_map = {}
    for old_path, blobs in trace["evidence"].items():
        packet = json.loads(blobs["prompt_bytes"].split(b"\n", 1)[1])
        seat = packet["observation"]["seat"]
        old = Path(old_path)
        new = (evidence_root / row["arm"] / "seed-10-flip-1" /
               f"seat-{seat}" / old.name)
        new.mkdir(parents=True)
        (new / "prompt.txt").write_bytes(blobs["prompt_bytes"])
        (new / "final.json").write_bytes(blobs["final_bytes"])
        new_path = str(new)
        evidence[new_path] = blobs
        call_pins[new_path] = trace["pins"]["calls"][old_path]
        path_map[old_path] = new_path

    for call in row["calls"]:
        call["evidence_path"] = path_map[call["evidence_path"]]
    pins = copy.deepcopy(trace["pins"])
    pins["calls"] = call_pins
    pins["row_sha256"] = hashlib.sha256(canonical_json_bytes(row)).hexdigest()

    target = next(item for item in report["mirrors"]
                   if item["key"] == "sol-perfect-seed10-flip1")
    assert "lineage" not in target
    report["mirrors"][report["mirrors"].index(target)] = row
    new_tokens = sum(call["usage"]["input_tokens"] + call["usage"]["output_tokens"]
                     for call in row["calls"])
    report["budget"] = {
        "tokens": new_tokens, "new_tokens": new_tokens,
        "prior_tokens": 0, "combined_tokens": new_tokens,
    }

    for item in report["mirrors"]:
        (source / f"mirror-sol-{item['information']}-{item['seed']}-{item['flip']}.json").write_bytes(
            canonical_json_bytes(item))
    result_raw = canonical_json_bytes(report)
    (source / "result.json").write_bytes(result_raw)
    result_sha = hashlib.sha256(result_raw).hexdigest()
    return {
        "authenticated": authenticated,
        "source": source,
        "report": report,
        "expected_config": expected_config,
        "result_sha": result_sha,
        "mirror_key": row["key"],
        "row": row,
        "pins": pins,
        "evidence": evidence,
    }


def _load(fixture):
    from shengji.luna.benchmark_legacy_source import load_legacy_rollout_audit

    return load_legacy_rollout_audit(
        fixture["source"], fixture["result_sha"],
        expected_config=fixture["expected_config"],
        authenticated_retention=fixture["authenticated"],
        mirror_key=fixture["mirror_key"], pins=fixture["pins"])


def test_actual_chain_loads_recovery_then_audits_real_legacy_trace(tmp_path):
    fixture = _fixture(tmp_path)
    before = {path: path.read_bytes() for path in fixture["source"].rglob("*")
              if path.is_file()}
    result = _load(fixture)

    assert result["schema"] == "benchmark-legacy-source-audit-v1"
    assert result["source_pins"] == {
        "path": str(fixture["source"]), "result_sha256": fixture["result_sha"]}
    assert result["mirror_key"] == fixture["mirror_key"]
    assert result["mirror_path"] == str(
        fixture["source"] / "mirror-sol-perfect-10-1.json")
    assert result["recorded_costs"] == {
        "status": "retained-recorded-costs-verified", "tokens": 720,
        "new_tokens": 720, "prior_tokens": 0, "combined_tokens": 720}
    assert result["audit"]["schema"] == "benchmark-legacy-rollout-audit-v1"
    assert result["audit"]["source_commit"] == fixture["pins"]["source_commit"]
    assert result["audit"]["accepted_call_count"] == 6
    assert result["audit"]["seat"] == 1
    assert result["audit"]["evaluation_index"] == 2
    assert {path: path.read_bytes() for path in fixture["source"].rglob("*")
            if path.is_file()} == before


def test_row_pin_mismatch_is_refused_after_authenticated_source_load(tmp_path):
    fixture = _fixture(tmp_path)
    fixture["pins"]["row_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        _load(fixture)


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_missing_or_extra_call_pins_are_refused(tmp_path, mutation):
    fixture = _fixture(tmp_path)
    pins = fixture["pins"]["calls"]
    path = next(iter(pins))
    if mutation == "missing":
        pins.pop(path)
    else:
        pins[str(fixture["source"] / "evidence" / "sol-perfect" /
                 "seed-10-flip-1" / "seat-1" / "call-extra")] = copy.deepcopy(pins[path])
    with pytest.raises(ValueError):
        _load(fixture)


@pytest.mark.parametrize("mutation", ["outside", "symlink"])
def test_evidence_paths_cannot_escape_or_alias_source_root(tmp_path, mutation):
    fixture = _fixture(tmp_path)
    old_path = next(iter(fixture["pins"]["calls"]))
    if mutation == "outside":
        outside = tmp_path / "outside" / "call"
        fixture["pins"]["calls"][str(outside)] = fixture["pins"]["calls"].pop(old_path)
        call = next(call for call in fixture["row"]["calls"]
                    if call["evidence_path"] == old_path)
        call["evidence_path"] = str(outside)
        target_path = fixture["source"] / "mirror-sol-perfect-10-1.json"
        target_path.write_bytes(canonical_json_bytes(fixture["row"]))
        result_raw = canonical_json_bytes(fixture["report"])
        (fixture["source"] / "result.json").write_bytes(result_raw)
        fixture["result_sha"] = hashlib.sha256(result_raw).hexdigest()
        fixture["pins"]["row_sha256"] = hashlib.sha256(
            canonical_json_bytes(fixture["row"])).hexdigest()
    else:
        call_dir = Path(old_path)
        real_dir = call_dir.with_name(call_dir.name + "-real")
        call_dir.rename(real_dir)
        call_dir.symlink_to(real_dir, target_is_directory=True)
    with pytest.raises(ValueError, match="outside recovery run" if mutation == "outside" else "symlink"):
        _load(fixture)


def test_evidence_byte_mismatch_is_refused(tmp_path):
    fixture = _fixture(tmp_path)
    path = Path(next(iter(fixture["pins"]["calls"]))) / "final.json"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError):
        _load(fixture)

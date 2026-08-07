"""Falsification boundary for the one-shot V11-v2 artifact repair."""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import v11_revalidate_v2 as PARENT  # noqa: E402
import v11_revalidate_v2_artifact_repair as REPAIR  # noqa: E402


def _counters(*, n30: bool) -> dict:
    counters = {field: 0 for field in PARENT.COUNTER_FIELDS}
    if n30:
        counters.update({
            "searches": 1,
            "rollouts": 60,
            "search_secs": 0.01,
            "sample_attempts": 30,
            "accepted_worlds": 30,
        })
    return counters


def _records(*, seed0=PARENT.SEED0, clusters=1):
    records = {}
    for label, policy in PARENT.LABELS.items():
        rows = []
        for seed in range(seed0, seed0 + clusters):
            for flip in (0, 1):
                won = int((seed + flip + (label == "arm")) % 2 == 0)
                rows.append({
                    "run": "repair-test",
                    "label": label,
                    "policy": policy,
                    "seed": seed,
                    "flip": flip,
                    "won": won,
                    "level_utility": 1 if won else -1,
                    "arm": _counters(n30=label != "arm"),
                    "opp": _counters(n30=True),
                })
        records[label] = rows
    return records


def _manifests():
    out = []
    for index in range(PARENT.SHARD_COUNT):
        out.append((Path(f"logical-{index}.manifest.json"), {
            "shard_index": index,
            "complete": index != REPAIR.FAILED_SHARD_INDEX,
            "problems": (sorted(REPAIR.EXPECTED_FAILED_PROBLEMS)
                         if index == REPAIR.FAILED_SHARD_INDEX else []),
        }))
    return out


@pytest.mark.parametrize("utility", [4, -4, 17, -17])
def test_uncapped_adapter_accepts_any_nonzero_sign_consistent_integer(utility):
    records = _records()
    row = records["reference"][0]
    row["won"] = int(utility > 0)
    row["level_utility"] = utility
    assert REPAIR.record_problems_uncapped(
        records, seed0=PARENT.SEED0, clusters=1) == []
    # The repair is validation-only: caller-owned outcome bytes are untouched.
    assert row["level_utility"] == utility


@pytest.mark.parametrize("utility,won", [
    (0, 0), (4, 0), (-4, 1), (True, 1), (4.0, 1),
])
def test_uncapped_adapter_refuses_zero_wrong_sign_bool_or_noninteger(
        utility, won):
    records = _records()
    records["null"][0]["won"] = won
    records["null"][0]["level_utility"] = utility
    assert any("malformed outcome" in problem for problem in
               REPAIR.record_problems_uncapped(
                   records, seed0=PARENT.SEED0, clusters=1))


def test_adapter_does_not_recurse_when_installed_on_parent(monkeypatch):
    records = _records()
    records["null"][0].update(won=1, level_utility=4)
    monkeypatch.setattr(PARENT, "record_problems",
                        REPAIR.record_problems_uncapped)
    assert PARENT.record_problems(
        records, seed0=PARENT.SEED0, clusters=1) == []


def test_validate_population_installs_adapter_and_restores_parent(monkeypatch):
    records = _records()
    records["reference"][0].update(won=1, level_utility=4)
    original = PARENT.record_problems

    def fake_validate(_manifests, observed, _runtime, _head):
        return PARENT.record_problems(
            observed, seed0=PARENT.SEED0, clusters=1)

    monkeypatch.setattr(PARENT, "validate_population", fake_validate)
    assert REPAIR.validate_source_population(
        _manifests(), records, {}) == []
    assert PARENT.record_problems is original


def test_known_failure_normalizes_only_shard_five_and_only_in_memory():
    manifests = _manifests()
    normalized = REPAIR.normalize_known_failure(manifests)
    assert manifests[5][1]["complete"] is False
    assert manifests[5][1]["problems"] == sorted(
        REPAIR.EXPECTED_FAILED_PROBLEMS)
    assert normalized[5][1]["complete"] is True
    assert normalized[5][1]["problems"] == []

    wrong = _manifests()
    wrong[5][1]["problems"] = ["different failure"]
    with pytest.raises(REPAIR.ProtocolRefused, match="known utility-domain"):
        REPAIR.normalize_known_failure(wrong)

    wrong = _manifests()
    wrong[3][1]["complete"] = False
    with pytest.raises(REPAIR.ProtocolRefused,
                       match="outside shard 05"):
        REPAIR.normalize_known_failure(wrong)


def test_inventory_requires_exact_failed_names_and_no_extras(tmp_path):
    sources = REPAIR._source_paths(tmp_path)
    for source in sources:
        source["records"].write_text("")
        source["manifest"].write_text("{}")
    REPAIR._require_exact_inventory(tmp_path, sources)

    sources[0]["records"].unlink()
    with pytest.raises(REPAIR.ProtocolRefused, match="missing="):
        REPAIR._require_exact_inventory(tmp_path, sources)

    sources[0]["records"].write_text("")
    extra = tmp_path / (
        f"{REPAIR.SOURCE_PREFIX}_shard08_{REPAIR.SOURCE_SUFFIX}.jsonl")
    extra.write_text("")
    with pytest.raises(REPAIR.ProtocolRefused, match="extra="):
        REPAIR._require_exact_inventory(tmp_path, sources)


def test_aggregate_payload_never_authorizes_composition_or_production(
        monkeypatch, tmp_path):
    records = _records(clusters=1)
    manifests = []
    sources = []
    for index in range(PARENT.SHARD_COUNT):
        record_path = tmp_path / f"source-{index}.jsonl"
        manifest_path = tmp_path / f"source-{index}.manifest.json"
        record_path.write_text("source\n")
        manifest_path.write_text("{}\n")
        manifest = {
            "shard_index": index,
            "records_sha256": PARENT.sha256(record_path),
        }
        manifests.append((manifest_path, manifest))
        sources.append({
            "shard_index": index,
            "failed": index == REPAIR.FAILED_SHARD_INDEX,
            "records": record_path,
            "manifest": manifest_path,
        })
    monkeypatch.setattr(
        REPAIR, "reopen_and_validate",
        lambda _artifact_dir: ({"runtime": "test"}, manifests,
                               records, sources))
    monkeypatch.setattr(PARENT, "all_contrasts", lambda _records: {
        "arm-reference": {"mean": 1.0, "half_width_95": 0.1},
        "arm-null": {"mean": 1.0, "half_width_95": 0.1},
        "null-reference": {"mean": 0.0, "half_width_95": 0.1},
    })
    monkeypatch.setattr(PARENT, "accepted_dose_summary",
                        lambda _records: {"all": True})
    monkeypatch.setattr(PARENT, "gate_criteria",
                        lambda _stats, _dose: {"all": True})
    payload = REPAIR.aggregate_payload(tmp_path, tmp_path / "aggregate.json")
    assert payload["checkpoint_compatible_with_restored_v1"] is True
    assert payload["protected_composition_authorized"] is False
    assert payload["production_promotion"] is False
    assert payload["repair"]["source_bytes_rewritten"] is False
    assert payload["repair"]["games_rerun"] is False


def test_verify_recomputes_and_refuses_tampered_aggregate(
        monkeypatch, tmp_path, capsys):
    path = tmp_path / "aggregate.json"
    expected = {
        "schema": REPAIR.AGGREGATE_SCHEMA,
        "value": 1,
        "checkpoint_compatible_with_restored_v1": False,
        "protected_composition_authorized": False,
        "production_promotion": False,
    }
    path.write_text(json.dumps(expected))
    monkeypatch.setattr(REPAIR, "aggregate_payload",
                        lambda artifact_dir, out: copy.deepcopy(expected))
    args = argparse.Namespace(artifact_dir=str(tmp_path), aggregate=str(path))
    REPAIR.verify(args)
    assert json.loads(capsys.readouterr().out)["verified"] is True

    path.write_text(json.dumps({**expected, "value": 2}))
    with pytest.raises(REPAIR.ProtocolRefused,
                       match="independently reopened"):
        REPAIR.verify(args)

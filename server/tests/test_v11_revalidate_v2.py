"""Falsification boundary for corrected-encoder V11 revalidation v2."""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import v11_revalidate_v2 as V2  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402


def _counters(*, n30: bool) -> dict:
    counters = {field: 0 for field in V2.COUNTER_FIELDS}
    if n30:
        counters.update({
            "searches": 1,
            "rollouts": 60,
            "search_secs": 0.01,
            "sample_attempts": 30,
            "accepted_worlds": 30,
        })
    return counters


def _records(*, seed0=V2.SEED0, clusters=2, run="test-run"):
    records = {}
    for label, policy in V2.LABELS.items():
        rows = []
        for seed in range(seed0, seed0 + clusters):
            for flip in (0, 1):
                won = int((seed + flip + (label == "arm")) % 2 == 0)
                rows.append({
                    "run": run,
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


def test_v2_freezes_disjoint_geometry_claim_and_invalidates_v1():
    assert V2.SCHEMA == "v11-current-revalidation-v2"
    assert V2.SHARD_COUNT == 8
    assert V2.TOTAL_CLUSTERS == 2_048
    assert V2.CLUSTERS_PER_SHARD == 256
    assert V2.SEED0 == 142_000_000
    assert V2.SEED_HI == 142_002_047
    assert V2.INVALIDATED_V1 == {
        "schema": "v11-current-revalidation-v1",
        "git_sha": "e66b90bc3a50d514472670ea99909add5ea30d19",
        "seed0": 121_000_000,
        "seed_hi": 121_002_047,
        "admissible_parent": False,
        "encoder_source_sha256":
            "a2022b0754597627ba58c2c4630754ae89b5be0b4daefe7a775b6ade587214cf",
        "reason": "banker observation used drifted Memory own-kitty default",
    }
    assert V2.SEED0 > V2.INVALIDATED_V1["seed_hi"]
    assert "restored encoder-v1" in V2.SELECTION_RULE
    assert "does not validate the drifted v1 artifact" in V2.SELECTION_RULE
    assert V2.protocol_problems() == []


def test_historical_v1_runner_bytes_are_untouched():
    old = Path(V2.__file__).with_name("v11_revalidate.py")
    assert V2.sha256(old) == \
        "37d67e164aa84042b6855982ef0c113a3af7338b569122ddc0c2818cbdb51ce5"


def test_encoder_contract_is_literal_transitive_and_drift_refuses(monkeypatch):
    assert V2.encoder_contract() == V2.EXPECTED_ENCODER_CONTRACT
    assert set(V2.EXPECTED_ENCODER_CONTRACT["source_sha256s"]) == {
        "encode", "memory"}

    monkeypatch.setattr(V2, "ENCODER_IMPLEMENTATION_SHA256", "0" * 64)
    assert "restored encoder-v1 contract drifted" in V2.protocol_problems()


def test_true_null_matches_current_except_registered_rng_shift():
    current = make_bot("mc-strong", seed=7)
    null = make_bot("mc-strong-null", seed=7)
    shifted = make_bot("mc-strong", seed=7 + 999_983)
    assert V2.uppercase_contract(current) == V2.uppercase_contract(null)
    assert type(current.rollout_policy) is type(null.rollout_policy)
    assert current.rng.getstate() != null.rng.getstate()
    assert null.rng.getstate() == shifted.rng.getstate()
    assert current.N_DETERMINIZATIONS == null.N_DETERMINIZATIONS == 30
    assert V2.protocol_problems() == []


def test_record_gate_proves_every_mc_search_received_exact_n30():
    records = _records()
    assert V2.record_problems(records, seed0=V2.SEED0, clusters=2) == []
    dose = V2.accepted_dose_summary(records)
    assert dose["all"] is True
    assert dose["cells"]["arm"]["arm"] == {
        "policy_kind": "direct_no_search",
        "searches": 0,
        "accepted_worlds": 0,
        "expected_accepted_worlds": 0,
        "exact": True,
    }
    assert dose["cells"]["arm"]["opp"]["accepted_worlds"] == 120
    assert dose["cells"]["arm"]["opp"]["expected_accepted_worlds"] == 120


@pytest.mark.parametrize(("mutation", "message"), [
    (("arm", 0, "opp", "accepted_worlds", -1), "accepted dose"),
    (("null", 0, "arm", "failed_worlds", 1), "do not reconcile"),
    (("reference", 0, "opp", "short_searches", 1),
     "nonzero short_searches"),
    (("arm", 0, "arm", "searches", 1), "unexpectedly searched"),
])
def test_record_gate_falsifies_short_failed_or_direct_search(mutation, message):
    records = _records()
    label, row_index, side, field, delta = mutation
    records[label][row_index][side][field] += delta
    problems = V2.record_problems(records, seed0=V2.SEED0, clusters=2)
    assert any(message in problem for problem in problems)


def test_record_gate_refuses_coverage_duplicates_and_counter_shape():
    records = _records()
    records["arm"][0]["seed"] += 1
    problems = V2.record_problems(records, seed0=V2.SEED0, clusters=2)
    assert any("duplicate" in problem for problem in problems)
    assert any("coverage" in problem for problem in problems)

    records = _records()
    records["arm"][0]["opp"].pop("accepted_worlds")
    assert any("counter fields mismatch" in problem for problem in
               V2.record_problems(records, seed0=V2.SEED0, clusters=2))


def _contrast(mean, half):
    return {"mean": mean, "half_width_95": half}


def test_gate_needs_two_lcbs_sane_null_and_exact_dose():
    stats = {
        "arm-reference": _contrast(0.30, 0.20),
        "arm-null": _contrast(0.29, 0.20),
        "null-reference": _contrast(0.01, 0.10),
    }
    dose = {"all": True}
    assert V2.gate_criteria(stats, dose)["all"] is True
    for key in ("arm-reference", "arm-null"):
        broken = copy.deepcopy(stats)
        broken[key] = _contrast(0.10, 0.20)
        assert V2.gate_criteria(broken, dose)["all"] is False
    broken = copy.deepcopy(stats)
    broken["null-reference"] = _contrast(0.20, 0.10)
    assert V2.gate_criteria(broken, dose)["all"] is False
    assert V2.gate_criteria(stats, {"all": False})["all"] is False


def test_shard_uses_score_blind_progress_and_publishes_exclusively(
        tmp_path, monkeypatch):
    runtime = {
        "host": "test", "python": "test", "fast_engine": True,
        "require_voids": True, "experimental_sampler_flags": [],
        "encoder_contract": V2.EXPECTED_ENCODER_CONTRACT,
        "digests": {"runner": "a" * 64},
    }
    monkeypatch.setattr(V2, "require_runtime", lambda: (object(), runtime))
    monkeypatch.setattr(V2, "protocol_problems", lambda: [])
    monkeypatch.setattr(
        V2, "git", lambda *args: "f" * 40 if args[-1] == "HEAD" else "dirty")
    monkeypatch.setattr(
        V2, "policy_contract", lambda name: {"policy": name})
    monkeypatch.setattr(
        V2, "arm_ballots", lambda names: {name: "same" for name in names})
    calls = []

    def fake_run_arm(label, policy, opponent, clusters, seed0, fh, run_id,
                     **kwargs):
        calls.append(kwargs)
        rows = _records(seed0=seed0, clusters=clusters, run=run_id)[label]
        for row in rows:
            fh.write(json.dumps(row) + "\n")
        return rows

    monkeypatch.setattr(V2, "run_arm", fake_run_arm)
    out = tmp_path / "v2.jsonl"
    V2.run_shard(argparse.Namespace(shard_index=0, smoke=True, out=str(out)))
    assert calls == [{"progress_scores": False}] * 3
    assert out.is_file() and not Path(str(out) + ".partial").exists()
    manifest_path = Path(str(out) + ".manifest.json")
    manifest = json.loads(manifest_path.read_text())
    assert manifest["evidence_grade"] is False
    assert manifest["score_blind_progress"] is True
    assert manifest["shard_statistics_persisted"] is False
    assert "stats" not in manifest
    assert manifest["encoder_contract"] == V2.EXPECTED_ENCODER_CONTRACT
    assert manifest["accepted_dose"]["all"] is True


def test_exclusive_publication_never_clobbers_competing_bytes(tmp_path):
    final = tmp_path / "final.json"
    final.write_text("winner")
    partial = tmp_path / "partial.json"
    partial.write_text("loser")
    with pytest.raises(V2.ProtocolRefused, match="concurrently published"):
        V2.publish_partial_exclusive(partial, final)
    assert final.read_text() == "winner"
    assert partial.read_text() == "loser"

    out = tmp_path / "aggregate.json"
    V2.write_exclusive_atomic(out, {"first": True})
    with pytest.raises(V2.ProtocolRefused, match="overwrite"):
        V2.write_exclusive_atomic(out, {"first": False})
    assert json.loads(out.read_text()) == {"first": True}


def test_loader_refuses_historical_v1_manifests(tmp_path):
    for index in range(8):
        records = tmp_path / f"old-{index}.jsonl"
        records.write_text("")
        manifest = Path(str(records) + ".manifest.json")
        manifest.write_text(json.dumps({
            "schema": V2.INVALIDATED_V1["schema"],
            "evidence_grade": True,
            "records_sha256": V2.sha256(records),
        }))
    with pytest.raises(V2.ProtocolRefused, match="unexpected/non-evidence"):
        V2.load_population(str(tmp_path / "*.manifest.json"))


def test_population_reopens_counters_and_refuses_summary_or_score_tampering(
        tmp_path, monkeypatch):
    monkeypatch.setattr(V2, "TOTAL_CLUSTERS", 16)
    monkeypatch.setattr(V2, "CLUSTERS_PER_SHARD", 2)
    monkeypatch.setattr(V2, "SEED_HI", V2.SEED0 + 15)
    monkeypatch.setattr(V2, "protocol_problems", lambda: [])
    monkeypatch.setattr(
        V2, "policy_contract", lambda name: {"policy": name})
    monkeypatch.setattr(
        V2, "arm_ballots", lambda names: {name: "same" for name in names})
    runtime = {
        "host": "test", "python": "test", "fast_engine": True,
        "require_voids": True, "experimental_sampler_flags": [],
        "encoder_contract": V2.EXPECTED_ENCODER_CONTRACT,
        "digests": {"runner": "a" * 64},
    }
    contracts = {name: {"policy": name} for name in V2.LABELS.values()}
    ballots = {name: "same" for name in V2.LABELS.values()}
    manifests = []
    records = {label: [] for label in V2.LABELS}
    for index in range(8):
        seed0 = V2.SEED0 + index * 2
        run_id = f"run-{index}"
        record_path = tmp_path / f"shard-{index}.jsonl"
        local = _records(seed0=seed0, clusters=2, run=run_id)
        for label, rows in local.items():
            for row in rows:
                row["_source"] = str(record_path)
            records[label].extend(rows)
        manifest = {
            "schema": V2.SCHEMA,
            "claim": V2.CLAIM,
            "claim_boundary": V2.SHARD_CLAIM_BOUNDARY,
            "run_id": run_id,
            "complete": True,
            "problems": [],
            "evidence_grade": True,
            "tree_dirty": False,
            "production_promotion": False,
            "score_blind_progress": True,
            "shard_statistics_persisted": False,
            "git_sha": "f" * 40,
            **runtime,
            "invalidated_v1": V2.INVALIDATED_V1,
            "labels": V2.LABELS,
            "opponent": V2.OPPONENT,
            "checkpoint_sha256": V2.CHECKPOINT_SHA256,
            "selection_rule": V2.SELECTION_RULE,
            "policy_contracts": contracts,
            "ballots": ballots,
            "shard_index": index,
            "shard_count": 8,
            "total_clusters": 16,
            "clusters": 2,
            "seed0": seed0,
            "seed_hi": seed0 + 1,
            "record_counts": {label: len(rows)
                              for label, rows in local.items()},
            "counter_totals": V2.counter_totals(local),
            "accepted_dose": V2.accepted_dose_summary(local),
        }
        manifest_path = Path(str(record_path) + ".manifest.json")
        manifests.append((manifest_path, manifest))

    assert V2.validate_population(
        manifests, records, runtime, "f" * 40) == []

    broken = copy.deepcopy(manifests)
    broken[0][1]["accepted_dose"]["all"] = False
    assert any("accepted-dose summary drifted" in problem for problem in
               V2.validate_population(broken, records, runtime, "f" * 40))

    broken = copy.deepcopy(manifests)
    broken[0][1]["stats"] = {"peek": 1}
    assert any("not score-blind" in problem for problem in
               V2.validate_population(broken, records, runtime, "f" * 40))

    broken_records = copy.deepcopy(records)
    broken_records["arm"][0]["level_utility"] = 99
    assert any("malformed outcome" in problem for problem in
               V2.validate_population(
                   manifests, broken_records, runtime, "f" * 40))


def test_loader_reopens_record_digest(tmp_path):
    for index in range(8):
        records = tmp_path / f"v2-{index}.jsonl"
        records.write_text("{}\n")
        manifest = Path(str(records) + ".manifest.json")
        manifest.write_text(json.dumps({
            "schema": V2.SCHEMA,
            "evidence_grade": True,
            "records_sha256": "0" * 64,
        }))
    with pytest.raises(V2.ProtocolRefused, match="record digest drift"):
        V2.load_population(str(tmp_path / "*.manifest.json"))


def test_runtime_refuses_experimental_sampler_flags(monkeypatch):
    monkeypatch.setenv("SHENGJI_FAST", "1")
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setenv("SHENGJI_WEIGHTED_SPLITS", "1")
    with pytest.raises(V2.ProtocolRefused, match="must be unset"):
        V2.require_runtime()

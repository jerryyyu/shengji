"""Mutation-focused contract tests for the fresh report-LCB confirmation."""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rlcb_c1 as C1  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402


GIT = "1" * 40


def _counters(*, searches=1, accepted=30, failed=0):
    value = {field: 0 for field in C1.COUNTER_FIELDS}
    value.update({
        "rollouts": searches * 3,
        "searches": searches,
        "search_secs": 0.1,
        "sample_attempts": accepted + failed,
        "accepted_worlds": accepted,
        "failed_worlds": failed,
    })
    return value


def _row(label, seed, flip, *, run="run", utility=1):
    arm_accepted = 330 if label == "report_lcb" else 30
    return {
        "run": run,
        "label": label,
        "policy": C1.LABELS[label],
        "seed": seed,
        "flip": flip,
        "won": int(utility > 0),
        "level_utility": utility,
        "arm": _counters(accepted=arm_accepted),
        "opp": _counters(accepted=30),
    }


def _records(seed0=C1.SEED0, clusters=2):
    return {
        label: [
            _row(label, seed, flip, utility=1 if flip == 0 else -1)
            for seed in range(seed0, seed0 + clusters)
            for flip in (0, 1)
        ]
        for label in C1.LABELS
    }


def test_literal_protocol_is_one_fresh_three_arm_confirmation():
    assert C1.protocol_problems(require_receipt=False) == []
    assert C1.selection_identity() == {
        "schema": "rlcb-c1-shard-v1",
        "aggregate_schema": "rlcb-c1-aggregate-v1",
        "claim": "fresh_report_lcb_superiority_over_current_mc",
        "run_namespace": "rlcb-c1-150m-v1",
        "shard_count": 8,
        "clusters_per_shard": 256,
        "total_clusters": 2_048,
        "seed0": 150_000_000,
        "seed_hi": 150_002_047,
        "opponent": "mc-strong",
        "labels": {
            "report_lcb": "mc-s0-report-lcb",
            "current": "mc-strong",
            "current_null": "mc-strong-null-rlcb-c1",
        },
        "null_offset": 60_000_011,
        "selection_rule": C1.SELECTION_RULE,
        "claim_boundary": C1.CLAIM_BOUNDARY,
    }
    assert "single superiority gate" in C1.SELECTION_RULE
    assert "S0c read" in C1.SELECTION_RULE


def test_fresh_null_stream_proof_kills_the_historical_lag17_offset():
    proof = C1.stream_proof()
    assert proof["null_streams"] == proof["distinct_null_streams"] == 4_096
    assert proof["collisions"] == 0 and proof["problems"] == []
    historical = C1.stream_collision_problems(999_983)
    assert historical
    assert "151000000" in historical[0]
    assert "null:150000017:team0" in historical[0]
    assert "opponent:150000000:team0" in historical[0]


def test_registered_null_is_exact_current_search_with_bound_rng_shift():
    current = make_bot("mc-strong", seed=7)
    null = make_bot("mc-strong-null-rlcb-c1", seed=7)
    shifted = make_bot("mc-strong", seed=7 + C1.NULL_OFFSET)
    current_contract = C1.uppercase_contract(current)
    null_contract = C1.uppercase_contract(null)

    assert null_contract.pop("NULL_SEED_OFFSET") == C1.NULL_OFFSET
    assert null_contract == current_contract
    assert null.rng.getstate() == shifted.rng.getstate()
    assert null.rng.getstate() != current.rng.getstate()


def test_records_require_exact_coverage_uncapped_utility_and_exact_dose():
    records = _records()
    expected = {
        (seed, flip) for seed in range(C1.SEED0, C1.SEED0 + 2)
        for flip in (0, 1)
    }
    # A legitimate level change above three must never repeat the V11
    # artifact consumer's capped-utility bug.
    records["report_lcb"][0]["level_utility"] = 4
    assert C1.record_problems(records, expected_keys=expected) == []

    duplicate = _records()
    duplicate["current"][-1] = duplicate["current"][-2]
    assert any("duplicate" in item for item in
               C1.record_problems(duplicate, expected_keys=expected))

    short = _records()
    short["report_lcb"][0]["arm"] = _counters(accepted=329)
    assert any("accepted dose" in item for item in
               C1.record_problems(short, expected_keys=expected))

    failed = _records()
    failed["current_null"][0]["arm"] = _counters(accepted=30, failed=1)
    assert any("nonzero failed_worlds" in item for item in
               C1.record_problems(failed, expected_keys=expected))

    bad_sign = _records()
    bad_sign["current"][0]["level_utility"] = -1
    assert any("malformed outcome" in item for item in
               C1.record_problems(bad_sign, expected_keys=expected))


def test_gate_has_one_superiority_contrast_and_separate_null_calibration():
    passing = {
        "report_lcb-current": {
            "a": "report_lcb", "b": "current", "mean": 0.30,
            "half_width_95": 0.20, "clusters": 2_048,
        },
        "current_null-current": {
            "a": "current_null", "b": "current", "mean": 0.01,
            "half_width_95": 0.10, "clusters": 2_048,
        },
    }
    criteria = C1.gate_criteria(passing)
    assert criteria == {
        "exact_registered_clusters": True,
        "finite_paired_statistics": True,
        "current_null_interval_contains_zero": True,
        "single_superiority_lcb_gt_zero": True,
        "all": True,
    }
    assert C1.gate_decision(criteria) == "CONFIRM_REPORT_LCB"
    assert set(passing) == {
        "report_lcb-current", "current_null-current"}

    unresolved = json.loads(json.dumps(passing))
    unresolved["report_lcb-current"]["mean"] = 0.10
    criteria = C1.gate_criteria(unresolved)
    assert criteria["single_superiority_lcb_gt_zero"] is False
    assert C1.gate_decision(criteria) == "REPORT_LCB_NOT_CONFIRMED"

    broken_null = json.loads(json.dumps(passing))
    broken_null["current_null-current"].update(mean=0.20,
                                                half_width_95=0.10)
    assert C1.gate_decision(C1.gate_criteria(broken_null)) == \
        "REFUSE_NULL_CALIBRATION"

    wrong_sign = json.loads(json.dumps(passing))
    wrong_sign["report_lcb-current"]["mean"] = -0.30
    assert C1.gate_decision(C1.gate_criteria(wrong_sign)) == \
        "REPORT_LCB_NOT_CONFIRMED"


def test_shard_job_graph_is_exact_and_has_no_s0_or_deployment_command(tmp_path):
    jobs = C1.shard_jobs(tmp_path, GIT)
    assert [job.index for job in jobs] == list(range(8))
    for index, job in enumerate(jobs):
        argv = list(job.argv)
        assert argv[2] == "shard"
        assert argv[argv.index("--shard-index") + 1] == str(index)
        assert argv[argv.index("--expected-git") + 1] == GIT
        assert "s0_run" not in " ".join(argv).lower()
        assert "fly" not in " ".join(argv).lower()


def test_shard_manifest_remains_score_blind_until_full_aggregate(
    tmp_path, monkeypatch,
):
    root = tmp_path / C1.RUN_NAMESPACE
    root.mkdir()
    freeze = tmp_path / "freeze.json"
    freeze.write_text("{}\n")
    monkeypatch.setattr(C1, "FREEZE_RECEIPT", freeze)
    monkeypatch.setattr(C1, "require_environment", lambda: object())
    monkeypatch.setattr(C1, "protocol_problems", lambda: [])
    monkeypatch.setattr(C1, "require_clean_pushed_head", lambda _git: GIT)
    monkeypatch.setattr(C1, "_canonical_root", lambda _root: root)
    monkeypatch.setattr(C1, "runtime_identity", lambda _fast: {"runtime": 1})
    monkeypatch.setattr(
        C1, "policy_contract", lambda name: {"policy": name})
    monkeypatch.setattr(
        C1, "arm_ballots", lambda names: {name: "same" for name in names})
    calls = []

    def fake_run_arm(label, policy, opponent, clusters, seed0, fh, run_id,
                     **kwargs):
        assert opponent == C1.OPPONENT and clusters == 256
        calls.append((label, kwargs))
        rows = [
            _row(label, seed, flip, run=run_id,
                 utility=1 if flip == 0 else -1)
            for seed in range(seed0, seed0 + clusters)
            for flip in (0, 1)
        ]
        for row in rows:
            fh.write(json.dumps(row) + "\n")
        return rows

    monkeypatch.setattr(C1, "run_arm", fake_run_arm)
    C1.run_shard(SimpleNamespace(
        expected_git=GIT, shard_index=0, root=str(root)))

    manifest = json.loads(C1.manifest_path(root, 0).read_text())
    assert manifest["score_blind_progress"] is True
    assert manifest["shard_statistics_persisted"] is False
    assert "stats" not in manifest and "paired_vs_reference" not in manifest
    assert manifest["production_promotion"] is False
    assert manifest["automatic_deployment"] is False
    assert [label for label, _ in calls] == list(C1.LABELS)
    assert all(kwargs == {"progress_scores": False}
               for _, kwargs in calls)


def test_canonical_namespace_refuses_alias_or_retry(tmp_path):
    assert C1._canonical_root(C1.run_root()) == C1.run_root().resolve()
    with pytest.raises(C1.ProtocolRefused, match="exactly"):
        C1._canonical_root(tmp_path / "lookalike")


@pytest.mark.parametrize("bad", [True, -1, 1.5, float("nan")])
def test_counter_schema_rejects_malformed_values(bad):
    counters = _counters()
    counters["accepted_worlds"] = bad
    assert C1._counter_problems("current", "arm", counters)


def test_protocol_source_contains_no_production_mutator():
    source = Path(C1.__file__).read_text().lower()
    assert "flyctl" not in source
    assert "fly.toml" not in source
    assert 'production_promotion": true' not in source
    assert 'automatic_deployment": true' not in source

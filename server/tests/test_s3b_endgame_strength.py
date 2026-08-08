"""Falsifying boundary for the S3b complete-round strength protocol."""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import s3b_endgame_strength as S3B  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine.ballot import ballot_for_policy  # noqa: E402


def _upper(bot):
    return {name: getattr(bot, name) for name in dir(bot) if name.isupper()}


@pytest.mark.parametrize(("champion", "exact", "null"), [
    ("mc-s0-report-lcb", "mc-s0-report-lcb-exact-endgame",
     "mc-s0-report-lcb-null"),
])
def test_registered_treatment_changes_only_exact_continuation(
        champion, exact, null):
    base = make_bot(champion, seed=17)
    treatment = make_bot(exact, seed=17)
    control = make_bot(null, seed=17)
    expected = _upper(base)
    observed = _upper(treatment)
    observed["EXACT_ENDGAME"] = False
    assert observed == expected
    assert treatment.EXACT_ENDGAME is True
    assert treatment.EXACT_ENDGAME_MAX_CARDS == 4
    assert treatment.EXACT_ENDGAME_MAX_NODES == 250_000
    assert treatment.exact_endgame_base_policy == champion
    assert treatment.rng.getstate() == base.rng.getstate()
    assert type(treatment.rollout_policy) is type(base.rollout_policy)
    assert _upper(control) == expected
    assert control.rng.getstate() != base.rng.getstate()
    assert ballot_for_policy(exact).digest == ballot_for_policy(champion).digest


def test_protocol_freezes_complete_round_geometry_and_claim_boundary():
    assert S3B.SHARD_COUNT == 8
    assert S3B.PROTOCOLS == {
        "screen": {
            "seed0": 139_000_000, "clusters": 2_048,
            "clusters_per_shard": 256,
            "claim": "non_promotable_complete_round_exact_endgame_screen",
        },
        "confirm": {
            "seed0": 140_000_000, "clusters": 8_192,
            "clusters_per_shard": 1_024,
            "claim": "independent_complete_round_exact_endgame_confirmation",
        },
    }
    assert S3B.PREFLIGHT_CLUSTERS == 2
    assert S3B.PREFLIGHT_SEED0 == 141_000_000
    for champion in S3B.CHAMPION_LANES:
        assert S3B.protocol_problems(champion) == []
        assert set(S3B.labels_for(champion)) == {"exact", "champion", "null"}
    assert "one complete deal/round" in S3B.SELECTION_RULE
    assert "not multi-round progression" in S3B.SELECTION_RULE


def _counters(*, exact=False):
    out = {field: 0 for field in S3B.COUNTER_FIELDS}
    out.update({
        "rollouts": 40,
        "searches": 2,
        "search_secs": 0.25,
        "sample_attempts": 10,
        "accepted_worlds": 10,
    })
    if exact:
        out.update({
            "exact_endgames": 20,
            "exact_endgame_attempts": 20,
            "exact_endgame_sessions": 10,
            "exact_endgame_nodes": 200,
            "exact_endgame_cache_hits": 30,
        })
    return out


def _records(clusters=2, seed0=139_000_000, run="run"):
    rows = {}
    policies = S3B.labels_for("mc-s0-report-lcb")
    for label, policy in policies.items():
        rows[label] = []
        for seed in range(seed0, seed0 + clusters):
            for flip in (0, 1):
                won = int((seed + flip + (label == "exact")) % 2 == 0)
                rows[label].append({
                    "run": run,
                    "label": label,
                    "policy": policy,
                    "seed": seed,
                    "flip": flip,
                    "won": won,
                    "level_utility": 1 if won else -1,
                    "arm": _counters(exact=label == "exact"),
                    "opp": _counters(),
                })
    return rows


def test_work_gate_requires_real_exact_use_and_zero_refusal_overflow():
    records = _records()
    assert S3B.record_problems(records) == []

    broken = copy.deepcopy(records)
    for row in broken["exact"]:
        for field in S3B.EXACT_COUNTER_FIELDS:
            row["arm"][field] = 0
    assert any("never used" in problem
               for problem in S3B.record_problems(broken))

    broken = copy.deepcopy(records)
    broken["exact"][0]["arm"]["exact_endgame_refusals"] = 1
    assert any("exact_endgame_refusals" in problem
               for problem in S3B.record_problems(broken))

    broken = copy.deepcopy(records)
    broken["exact"][0]["arm"]["exact_endgame_budget_exceeded"] = 1
    assert any("exact_endgame_budget_exceeded" in problem
               for problem in S3B.record_problems(broken))

    broken = copy.deepcopy(records)
    broken["champion"][0]["arm"]["exact_endgames"] = 1
    assert any("non-treatment" in problem
               for problem in S3B.record_problems(broken))

    broken = copy.deepcopy(records)
    broken["exact"][0]["arm"]["sample_attempts"] += 1
    assert any("do not reconcile" in problem
               for problem in S3B.record_problems(broken))


def _contrast(mean, half):
    return {"mean": mean, "half_width_95": half}


def test_strength_gate_needs_both_lcbs_sane_null_and_exact_work():
    stats = {
        "exact-champion": _contrast(0.30, 0.20),
        "exact-null": _contrast(0.29, 0.20),
        "null-champion": _contrast(0.01, 0.10),
    }
    totals = S3B.counter_totals(_records())
    assert S3B.gate_criteria(stats, totals)["all"] is True
    for key in ("exact-champion", "exact-null"):
        broken = copy.deepcopy(stats)
        broken[key] = _contrast(0.10, 0.20)
        assert S3B.gate_criteria(broken, totals)["all"] is False
    broken = copy.deepcopy(stats)
    broken["null-champion"] = _contrast(0.20, 0.10)
    assert S3B.gate_criteria(broken, totals)["all"] is False
    no_use = copy.deepcopy(totals)
    no_use["exact"]["arm"]["exact_endgames"] = 0
    assert S3B.gate_criteria(stats, no_use)["all"] is False


def _runtime():
    return {
        "host": "test-host",
        "python": sys.version.split()[0],
        "fast_engine": True,
        "require_voids": True,
        "experimental_sampler_flags": [],
        "digests": {"runner": "a" * 64},
    }


def _champion_parent():
    return S3B.LIVE_PARENT.expected_parent()


def _throughput_payload(*, wall_seconds=3_600, caps=10_000):
    parent = _champion_parent()
    budgets = {
        "screen_fleet_hours": float(caps),
        "screen_max_shard_wall_hours": float(caps),
        "confirm_fleet_hours": float(caps),
        "confirm_max_shard_wall_hours": float(caps),
    }
    projections = S3B.throughput_projection(wall_seconds)
    criteria = S3B.throughput_criteria(projections, budgets)
    return {
        "schema": S3B.PREFLIGHT_SCHEMA,
        "complete": True,
        "evidence_grade": False,
        "strength_scores_persisted": False,
        "raw_records_persisted": False,
        "budget_role": S3B.BUDGET_ROLE,
        "strength_estimand_locked": True,
        "evaluation_unit": "one_complete_round",
        "primary_outcome": "signed_level_utility",
        "multi_round_progression_tested": False,
        "git_sha": "f" * 40,
        "runtime_identity": _runtime(),
        "mechanics_commit": S3B.MECHANICS_COMMIT,
        "mechanics_asset_sha256": S3B.MECHANICS_ASSET_SHA256,
        "champion_parent": parent,
        "champion_policy": "mc-s0-report-lcb",
        "labels": S3B.labels_for("mc-s0-report-lcb"),
        "clusters": 2,
        "seed0": 141_000_000,
        "seed_hi": 141_000_001,
        "wall_seconds": wall_seconds,
        "wall_seconds_by_label": {
            "exact": wall_seconds * 0.8,
            "champion": wall_seconds * 0.1,
            "null": wall_seconds * 0.1,
        },
        "counter_totals": S3B.counter_totals(_records()),
        "budgets": budgets,
        "projections": projections,
        "criteria": criteria,
        "launch_authorized": criteria["all"],
    }


def test_throughput_receipt_is_score_free_rederived_and_budget_gated(tmp_path):
    path = tmp_path / "throughput.json"
    payload = _throughput_payload()
    path.write_text(json.dumps(payload))
    parent = S3B.load_throughput_parent(
        path, S3B.sha256(path), _champion_parent())
    assert parent["launch_authorized"] is True
    assert "stats" not in payload and "records" not in payload
    different_host = copy.deepcopy(_runtime())
    different_host["host"] = "untimed-host"
    with pytest.raises(S3B.ProtocolRefused, match="host/runtime"):
        S3B.require_throughput_execution_identity(
            parent, parent["git_sha"], different_host)

    tampered = _throughput_payload()
    tampered["projections"]["screen"]["fleet_hours"] += 1
    path.write_text(json.dumps(tampered))
    with pytest.raises(S3B.ProtocolRefused, match="arithmetic"):
        S3B.load_throughput_parent(path, S3B.sha256(path), _champion_parent())

    too_slow = _throughput_payload(caps=0.01)
    path.write_text(json.dumps(too_slow))
    with pytest.raises(S3B.ProtocolRefused, match="exceeds declared"):
        S3B.load_throughput_parent(path, S3B.sha256(path), _champion_parent())

    leaked = _throughput_payload()
    leaked["strength_scores_persisted"] = True
    path.write_text(json.dumps(leaked))
    with pytest.raises(S3B.ProtocolRefused, match="protocol identity"):
        S3B.load_throughput_parent(path, S3B.sha256(path), _champion_parent())


def test_compiled_preflight_discards_outcomes_and_emits_only_work_receipt(
        monkeypatch, tmp_path):
    head = "f" * 40
    runtime = _runtime()
    monkeypatch.setattr(S3B, "require_runtime", lambda: (object(), runtime))
    monkeypatch.setattr(S3B, "load_champion_parent", lambda: _champion_parent())
    monkeypatch.setattr(S3B, "protocol_problems", lambda _champion: [])
    monkeypatch.setattr(
        S3B, "git", lambda *args: head if args == ("rev-parse", "HEAD") else "")
    calls = []

    def fake_run_arm(label, policy, opponent, clusters, seed0, fh, run_id,
                     **kwargs):
        calls.append(kwargs)
        rows = _records(clusters, seed0, run_id)[label]
        # Exercise the real sink boundary: outcomes are written, then the
        # TemporaryFile is closed/unlinked and never named in the receipt.
        for row in rows:
            fh.write(json.dumps(row) + "\n")
        return rows

    monkeypatch.setattr(S3B, "run_arm", fake_run_arm)
    out = tmp_path / "preflight.json"
    args = argparse.Namespace(
        out=str(out),
        screen_fleet_hour_cap=1e9,
        screen_shard_wall_hour_cap=1e9,
        confirm_fleet_hour_cap=1e9,
        confirm_shard_wall_hour_cap=1e9,
    )
    S3B.run_throughput_preflight(args)
    receipt = json.loads(out.read_text())
    assert calls and all(call == {"progress": False, "progress_scores": False}
                         for call in calls)
    assert receipt["evidence_grade"] is False
    assert receipt["strength_scores_persisted"] is False
    assert receipt["raw_records_persisted"] is False
    assert "stats" not in receipt and "won" not in receipt
    assert list(tmp_path.iterdir()) == [out]

def test_exclusive_publication_never_clobbers_competing_result(tmp_path):
    partial = tmp_path / "result.partial"
    final = tmp_path / "result.json"
    partial.write_text("ours")
    final.write_text("theirs")
    with pytest.raises(S3B.ProtocolRefused, match="concurrently published"):
        S3B.publish_partial_exclusive(partial, final)
    assert partial.read_text() == "ours"
    assert final.read_text() == "theirs"


def test_confirmation_reopens_hash_bound_raw_screen_inputs(tmp_path):
    aggregate = tmp_path / "screen.aggregate.json"
    aggregate.write_text("{}")
    inputs = []
    for index in range(8):
        records = tmp_path / f"screen{index}.jsonl"
        records.write_text(json.dumps({"label": "exact", "seed": index}) + "\n")
        manifest = tmp_path / f"screen{index}.jsonl.manifest.json"
        manifest.write_text(json.dumps({
            "records_sha256": S3B.sha256(records),
            "shard_index": index,
        }))
        inputs.append({
            "manifest_path": manifest.name,
            "manifest_sha256": S3B.sha256(manifest),
            "records_path": records.name,
            "records_sha256": S3B.sha256(records),
            "shard_index": index,
        })
    manifests, rows = S3B.load_bound_screen_inputs(aggregate, inputs)
    assert len(manifests) == 8 and len(rows["exact"]) == 8

    # A plausible JSONL mutation after aggregation is caught by reopening the
    # raw bytes, not merely by trusting the aggregate's derived statistics.
    (tmp_path / "screen3.jsonl").write_text(
        json.dumps({"label": "exact", "seed": 999}) + "\n")
    with pytest.raises(S3B.ProtocolRefused, match="records digest mismatch"):
        S3B.load_bound_screen_inputs(aggregate, inputs)


def test_self_consistent_all_shard_claim_rewrite_is_not_stable_enough(
        monkeypatch, tmp_path):
    small_protocols = copy.deepcopy(S3B.PROTOCOLS)
    small_protocols["screen"]["clusters"] = 8
    small_protocols["screen"]["clusters_per_shard"] = 1
    monkeypatch.setattr(S3B, "PROTOCOLS", small_protocols)
    runtime = _runtime()
    head = "f" * 40
    champion_parent = _champion_parent()
    throughput = {
        "git_sha": head,
        "runtime_identity": runtime,
        "budgets": _throughput_payload()["budgets"],
    }
    labels = S3B.labels_for("mc-s0-report-lcb")
    contracts = {name: S3B.policy_contract(name) for name in labels.values()}
    ballots = S3B.arm_ballots(labels.values())
    manifests = []
    all_records = {label: [] for label in labels}
    for index in range(8):
        seed0 = 139_000_000 + index
        run_id = f"{S3B.SCHEMA}_screen_shard{index:02d}_{head[:10]}"
        manifest_path = tmp_path / f"{run_id}.jsonl.manifest.json"
        record_path = str(manifest_path).removesuffix(".manifest.json")
        local = _records(1, seed0, run_id)
        for label, rows in local.items():
            for row in rows:
                row["_source"] = record_path
            all_records[label].extend(rows)
        manifest = {
            "schema": S3B.SCHEMA,
            "phase": "screen",
            "claim": small_protocols["screen"]["claim"],
            "run_id": run_id,
            "evidence_grade": True,
            "screen_only": True,
            "production_promotion": False,
            "evaluation_unit": "one_complete_round",
            "primary_outcome": "signed_level_utility",
            "multi_round_progression_tested": False,
            "git_sha": head,
            "tree_dirty": False,
            "dirty_files": [],
            **runtime,
            "mechanics_commit": S3B.MECHANICS_COMMIT,
            "mechanics_asset_sha256": S3B.MECHANICS_ASSET_SHA256,
            "shard_index": index,
            "shard_count": 8,
            "total_clusters": 8,
            "clusters": 1,
            "seed0": seed0,
            "seed_hi": seed0,
            "opponent": "mc-s0-report-lcb",
            "champion_policy": "mc-s0-report-lcb",
            "labels": labels,
            "selection_rule": S3B.SELECTION_RULE,
            "champion_parent": champion_parent,
            "screen_parent": None,
            "throughput_parent": throughput,
            "policy_contracts": contracts,
            "ballots": ballots,
            "record_counts": {label: len(rows)
                              for label, rows in local.items()},
            "counter_totals": S3B.counter_totals(local),
            "wall_seconds": 4.0,
            "wall_seconds_by_label": {
                "exact": 2.0, "champion": 0.5, "null": 0.5},
            "complete": True,
            "problems": [],
        }
        manifests.append((manifest_path, manifest))

    assert S3B.validate_population(
        "screen", manifests, all_records, runtime, head,
        champion_parent, None, throughput, check_current_protocol=False) == []

    rewritten = copy.deepcopy(manifests)
    for _, manifest in rewritten:
        # All eight agree, their raw records and counters remain self-
        # consistent, and only comparison with the frozen expected contract
        # can detect the rewrite.
        manifest["claim"] = "self_consistent_rewritten_claim"
    problems = S3B.validate_population(
        "screen", rewritten, all_records, runtime, head,
        champion_parent, None, throughput, check_current_protocol=False)
    assert any("frozen policy/claim contract drift" in problem
               for problem in problems)


def test_smoke_runner_hides_scores_and_names_one_round_boundary(
        monkeypatch, tmp_path):
    head = "f" * 40
    runtime = _runtime()
    throughput = {
        "git_sha": head,
        "runtime_identity": runtime,
        "budgets": _throughput_payload()["budgets"],
    }
    monkeypatch.setattr(S3B, "require_runtime", lambda: (object(), runtime))
    monkeypatch.setattr(
        S3B, "parent_args", lambda _args: (_champion_parent(), None, throughput))
    monkeypatch.setattr(S3B, "protocol_problems", lambda _champion: [])
    monkeypatch.setattr(
        S3B, "git", lambda *args: head if args == ("rev-parse", "HEAD") else
        " M unrelated-doc.md")
    observed = []

    def fake_run_arm(label, policy, opponent, clusters, seed0, fh, run_id,
                     **kwargs):
        observed.append(kwargs)
        rows = _records(clusters, seed0, run_id)[label]
        for row in rows:
            row["policy"] = policy
            fh.write(json.dumps(row) + "\n")
        return rows

    monkeypatch.setattr(S3B, "run_arm", fake_run_arm)
    out = tmp_path / "smoke.jsonl"
    args = argparse.Namespace(
        phase="screen", shard_index=0, smoke=True, out=str(out))
    S3B.run_shard(args)
    manifest = json.loads(Path(str(out) + ".manifest.json").read_text())
    assert observed and all(call["progress_scores"] is False
                            for call in observed)
    assert manifest["evaluation_unit"] == "one_complete_round"
    assert manifest["primary_outcome"] == "signed_level_utility"
    assert manifest["multi_round_progression_tested"] is False
    assert manifest["production_promotion"] is False
    assert manifest["evidence_grade"] is False
    assert "stats" not in manifest and "paired" not in manifest

    overclaim = copy.deepcopy(manifest)
    overclaim["multi_round_progression_tested"] = True
    problems = S3B.validate_population(
        "screen", [(Path(str(out) + ".manifest.json"), overclaim)], {},
        runtime, head, _champion_parent(), None, throughput,
        check_current_protocol=False)
    assert any("overclaims its evaluation unit" in problem
               for problem in problems)


def test_only_live_report_lcb_has_a_frozen_v2_lane():
    assert S3B.labels_for("mc-s0-report-lcb") == {
        "exact": "mc-s0-report-lcb-exact-endgame",
        "champion": "mc-s0-report-lcb",
        "null": "mc-s0-report-lcb-null",
    }
    for stale in ("mc-strong", "mc-s0-adaptive", "mc-unknown"):
        with pytest.raises(S3B.ProtocolRefused, match="no frozen S3b-v2 lane"):
            S3B.labels_for(stale)


def test_population_reopener_refuses_self_consistent_parent_rewrite():
    parent = _champion_parent()
    parent["source_sha256s"]["registry"] = "0" * 64
    problems = S3B.validate_population(
        "screen", [], {}, _runtime(), "f" * 40,
        parent, None, {}, check_current_protocol=False)
    assert any("live champion parent" in problem for problem in problems)

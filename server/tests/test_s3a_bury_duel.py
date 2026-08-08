"""Falsification tests for the S3a complete-round duel protocol."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest


def _module():
    path = Path(__file__).parents[1] / "scripts" / "s3a_bury_duel.py"
    spec = importlib.util.spec_from_file_location("s3a_bury_duel", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


A = _module()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _telemetry(structured: bool = False) -> dict:
    values = {name: 0 for name in A.STRUCTURED_BURY_TELEMETRY_FIELDS}
    if structured:
        values.update({
            "opportunities": 1,
            "triggers": 1,
            "overrides": 1,
            "candidate_count_sum": 2,
            "searches": 1,
            "complete_searches": 1,
            "worlds_requested": 8,
            "worlds_used": 8,
            "candidate_world_budget": 16,
            "candidate_rollouts": 16,
            "sample_attempts": 8,
            "accepted_worlds": 8,
        })
    return {
        "schema": "structured-bury-cumulative-telemetry-v1",
        **values,
        "exact_work_complete": True,
    }


def _counter_payload(structured: bool = False) -> dict:
    payload = A.counters([])
    payload["structured_bury"] = _telemetry(structured)
    return payload


def _record(label: str, seed: int, flip: int, utility: int, *,
            run_id: str | None = None) -> dict:
    return {
        "run": run_id or A.PHASES["screen"]["run_id"],
        "label": label,
        "policy": A.LABELS[label],
        "opponent": A.OPPONENT,
        "seed": seed,
        "flip": flip,
        "won": int(utility > 0),
        "level_utility": utility,
        "arm": _counter_payload(label == "structured"),
        "opp": _counter_payload(False),
    }


def _records(structured_utility: int = 2,
             champion_utility: int = -1,
             null_utility: int = -1) -> dict[str, list[dict]]:
    utilities = {
        "structured": structured_utility,
        "champion": champion_utility,
        "null": null_utility,
    }
    return {
        label: [_record(label, seed, flip, utilities[label])
                for seed in (101, 202) for flip in (0, 1)]
        for label in A.LABEL_ORDER
    }


def _flat(records: dict[str, list[dict]]) -> list[dict]:
    return [record for label in A.LABEL_ORDER for record in records[label]]


def _runtime(host: str = "test-host") -> dict:
    return {
        "git": "a" * 40,
        "tree_dirty": False,
        "host": host,
        "python": "3.14.6",
        "fast_engine": True,
        "require_voids": True,
        "experimental_flags": [],
        "source_sha256s": {"runner": "b" * 64},
        "fast_binary_sha256": "c" * 64,
        "policy_contract_sha256s": {"policy": "d" * 64},
        "stream_digests": {
            "preflight": "e" * 64,
            **{phase: "e" * 64 for phase in A.PHASES},
        },
    }


def test_real_policy_contract_changes_only_structured_bury_switches():
    parent = {"champion_policy": A.CHAMPION}
    assert A.protocol_problems(parent) == []
    structured = A.make_bot(A.LABELS["structured"], seed=7)
    champion = A.make_bot(A.LABELS["champion"], seed=7)
    null = A.make_bot(A.LABELS["null"], seed=7)
    assert structured.MC_BURY is structured.STRUCTURED_BURY is True
    assert structured.structured_bury_base_policy == A.CHAMPION
    assert structured.rng.getstate() == champion.rng.getstate()
    assert null.seed == champion.seed + A.NULL_SHIFT


def test_sparse_streams_are_globally_unique_within_each_phase():
    for phase in A.PHASES:
        assert A.stream_problems(phase) == []
        assert len(A.stream_digest(phase)) == 64
    assert A.preflight_stream_problems() == []
    assert A.global_stream_problems() == []


def test_consecutive_seed_mutant_recreates_historical_null_collision(
        monkeypatch):
    monkeypatch.setattr(A, "STREAM_STRIDE", 1)
    monkeypatch.setitem(A.PHASES, "screen", {
        "run_id": "s3a-bury-duel-screen-mutant-v1",
        "seed0": 151_000_000,
        "clusters": 20,
        "clusters_per_shard": 3,
        "claim": "mutant",
    })
    assert A.stream_problems("screen")


def test_record_contract_accepts_exact_treatment_and_controls():
    for label in A.LABEL_ORDER:
        record = _record(label, 101, 0, 2 if label == "structured" else -1)
        assert A.record_problems(
            record, phase="screen", expected_seed=101,
            expected_label=label, expected_flip=0) == []


def test_record_run_identity_cannot_cross_phases():
    record = _record("structured", 101, 0, 2,
                     run_id=A.PHASES["confirm"]["run_id"])
    assert "record identity" in A.record_problems(
        record, phase="screen", expected_seed=101,
        expected_label="structured", expected_flip=0)


def test_control_structured_activation_refuses():
    record = _record("champion", 101, 0, -1)
    record["arm"]["structured_bury"] = _telemetry(True)
    problems = A.record_problems(
        record, phase="screen", expected_seed=101,
        expected_label="champion", expected_flip=0)
    assert "arm: control structured-bury telemetry is nonzero" in problems


def test_treatment_short_search_refuses():
    record = _record("structured", 101, 0, 2)
    telemetry = record["arm"]["structured_bury"]
    telemetry["complete_searches"] = 0
    telemetry["short_searches"] = 1
    telemetry["exact_work_complete"] = False
    problems = A.record_problems(
        record, phase="screen", expected_seed=101,
        expected_label="structured", expected_flip=0)
    assert "arm: structured-bury work is incomplete" in problems
    assert "arm: treatment structured-bury fallback" in problems


def test_sampler_counter_mismatch_refuses():
    record = _record("structured", 101, 0, 2)
    record["arm"]["sample_attempts"] = 1
    problems = A.record_problems(
        record, phase="screen", expected_seed=101,
        expected_label="structured", expected_flip=0)
    assert "arm: sampler counters do not reconcile" in problems


def test_structured_internal_work_mutant_refuses():
    record = _record("structured", 101, 0, 2)
    record["arm"]["structured_bury"]["candidate_rollouts"] -= 1
    problems = A.record_problems(
        record, phase="screen", expected_seed=101,
        expected_label="structured", expected_flip=0)
    assert "arm: structured exact-work flag mismatch" in problems


def test_positive_aggregate_authorizes_confirmation_review_only():
    records = _records()
    shard = {"records": _flat(records)}
    payload = A.build_aggregate(
        phase="screen", shards=[shard], inputs=[],
        parent={"champion_policy": A.CHAMPION}, runtime=_runtime(),
        screen_parent=None)
    assert payload["criteria"]["all"] is True
    assert payload["status"] == "AUTHORIZE_CONFIRM_PACKET_REVIEW"
    assert payload["production_promotion"] is False
    assert payload["explicit_deployment_review_required"] is True


def test_aggregate_contrast_sign_is_treatment_minus_control():
    losing = _records(structured_utility=-2, champion_utility=1, null_utility=1)
    payload = A.build_aggregate(
        phase="screen", shards=[{"records": _flat(losing)}], inputs=[],
        parent={"champion_policy": A.CHAMPION}, runtime=_runtime(),
        screen_parent=None)
    assert payload["stats"]["structured-champion"]["mean"] < 0
    assert payload["status"] == "SELECT_NONE"


def test_null_calibration_is_a_required_two_sided_interval():
    drifted = _records(structured_utility=5, champion_utility=-2,
                       null_utility=2)
    payload = A.build_aggregate(
        phase="screen", shards=[{"records": _flat(drifted)}], inputs=[],
        parent={"champion_policy": A.CHAMPION}, runtime=_runtime(),
        screen_parent=None)
    assert payload["criteria"]["structured_champion_lcb_gt_zero"] is True
    assert payload["criteria"]["null_champion_interval_contains_zero"] is False
    assert payload["status"] == "SELECT_NONE"


def test_shard_requires_exact_interleaved_seed_population(monkeypatch):
    monkeypatch.setitem(A.PHASES, "screen", {
        "run_id": "s3a-bury-duel-screen-test-v1",
        "seed0": 151_000_000,
        "clusters": 8,
        "clusters_per_shard": 1,
        "claim": "test",
    })
    parent = {"champion_policy": A.CHAMPION}
    runtime = _runtime()
    seed = A.cluster_seed("screen", 3)
    records = []
    for label in A.LABEL_ORDER:
        records.extend([_record(label, seed, flip,
                                2 if label == "structured" else -1)
                        for flip in (0, 1)])
    payload = {
        "schema": A.SCHEMA,
        "complete": True,
        "phase": "screen",
        "run_id": A.PHASES["screen"]["run_id"],
        "phase_identity": A.phase_identity("screen"),
        "shard_index": 3,
        "shard_count": A.SHARD_COUNT,
        "parent": parent,
        "runtime": runtime,
        "elapsed_seconds": 1.0,
        "records": records,
        "records_sha256": A.stable_digest(records),
        "production_promotion": False,
        "retry_or_resume_authorized": False,
    }
    assert A.shard_problems(
        payload, phase="screen", shard_index=3,
        parent=parent, runtime=runtime) == []
    payload["records"][0]["seed"] += 1
    payload["records_sha256"] = A.stable_digest(payload["records"])
    assert "record 0: record identity" in A.shard_problems(
        payload, phase="screen", shard_index=3,
        parent=parent, runtime=runtime)


def test_screen_parent_reopens_exact_contract_across_hosts(tmp_path):
    parent = {"champion_policy": A.CHAMPION}
    screen_runtime = _runtime("mini")
    confirm_runtime = _runtime("air")
    payload = A.build_aggregate(
        phase="screen", shards=[{"records": _flat(_records())}], inputs=[],
        parent=parent, runtime=screen_runtime, screen_parent=None)
    path = tmp_path / "screen.json"
    path.write_text(json.dumps(payload))
    reopened = A.load_screen_parent(
        str(path), _sha(path), parent=parent, runtime=confirm_runtime)
    assert reopened["status"] == "AUTHORIZE_CONFIRM_PACKET_REVIEW"


def test_screen_parent_runtime_drift_refuses(tmp_path):
    parent = {"champion_policy": A.CHAMPION}
    payload = A.build_aggregate(
        phase="screen", shards=[{"records": _flat(_records())}], inputs=[],
        parent=parent, runtime=_runtime(), screen_parent=None)
    path = tmp_path / "screen.json"
    path.write_text(json.dumps(payload))
    changed = _runtime()
    changed["source_sha256s"] = {"runner": "f" * 64}
    with pytest.raises(A.ProtocolRefused, match="runtime/source"):
        A.load_screen_parent(
            str(path), _sha(path), parent=parent, runtime=changed)


def test_screen_parent_authority_or_python_drift_refuses(tmp_path):
    parent = {"champion_policy": A.CHAMPION}
    payload = A.build_aggregate(
        phase="screen", shards=[{"records": _flat(_records())}], inputs=[],
        parent=parent, runtime=_runtime(), screen_parent=None)
    payload["retry_or_extension_authorized"] = True
    path = tmp_path / "screen-authority.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(A.ProtocolRefused, match="did not authorize"):
        A.load_screen_parent(
            str(path), _sha(path), parent=parent, runtime=_runtime())

    payload["retry_or_extension_authorized"] = False
    path.write_text(json.dumps(payload))
    changed = _runtime()
    changed["python"] = "3.15.0"
    with pytest.raises(A.ProtocolRefused, match="runtime/source"):
        A.load_screen_parent(
            str(path), _sha(path), parent=parent, runtime=changed)


def test_score_free_preflight_publishes_no_outcomes(tmp_path, monkeypatch):
    parent = {"champion_policy": A.CHAMPION}
    runtime = _runtime()
    monkeypatch.setattr(A, "PREFLIGHT_CLUSTERS", 1)
    monkeypatch.setattr(
        A, "require_runtime", lambda _expected: (object(), parent, runtime))

    def fake_cluster(label, seed, *, run_id):
        utility = 2 if label == "structured" else -1
        return [_record(label, seed, flip, utility, run_id=run_id)
                for flip in (0, 1)]

    monkeypatch.setattr(A, "play_arm_cluster", fake_cluster)
    out = tmp_path / "preflight.json"
    args = Namespace(
        expected_git="a" * 40,
        screen_fleet_hours=1_000.0,
        screen_max_shard_hours=1_000.0,
        confirm_fleet_hours=1_000.0,
        confirm_max_shard_hours=1_000.0,
        out=str(out),
    )
    A.preflight(args)
    payload = json.loads(out.read_text())
    assert payload["score_free"] is True
    assert payload["capacity_pass"] is True
    assert payload["strength_launch_authorized"] is False
    raw = out.read_text()
    assert '"won"' not in raw
    assert '"level_utility"' not in raw
    assert '"records"' not in raw


def test_score_free_preflight_checks_its_literal_run_identity(
        tmp_path, monkeypatch):
    parent = {"champion_policy": A.CHAMPION}
    runtime = _runtime()
    monkeypatch.setattr(A, "PREFLIGHT_CLUSTERS", 1)
    monkeypatch.setattr(
        A, "require_runtime", lambda _expected: (object(), parent, runtime))

    def wrong_run_cluster(label, seed, *, run_id):
        utility = 2 if label == "structured" else -1
        return [_record(label, seed, flip, utility, run_id="wrong-run")
                for flip in (0, 1)]

    monkeypatch.setattr(A, "play_arm_cluster", wrong_run_cluster)
    out = tmp_path / "preflight-wrong-run.json"
    args = Namespace(
        expected_git="a" * 40,
        screen_fleet_hours=1_000.0,
        screen_max_shard_hours=1_000.0,
        confirm_fleet_hours=1_000.0,
        confirm_max_shard_hours=1_000.0,
        out=str(out),
    )
    A.preflight(args)
    payload = json.loads(out.read_text())
    assert payload["capacity_pass"] is False
    assert any("record identity" in problem for problem in payload["problems"])


def test_exclusive_publication_never_overwrites(tmp_path):
    path = tmp_path / "owned.json"
    A.write_exclusive(path, {"first": True})
    with pytest.raises(A.ProtocolRefused, match="overwrite"):
        A.write_exclusive(path, {"second": True})
    assert json.loads(path.read_text()) == {"first": True}

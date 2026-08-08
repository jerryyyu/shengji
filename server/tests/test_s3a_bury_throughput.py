"""S3a sizing is fresh, score-free, arithmetic-bound and non-promotable."""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import s3a_bury_throughput as TIMING  # noqa: E402


def _record(seed: int, *, candidate_worlds: int = 300) -> dict:
    return {
        "deal_seed": seed,
        "champion": TIMING.LIVE_PARENT.CHAMPION_POLICY,
        "arms": {
            arm: {
                "work": {
                    "complete": True,
                    "total_candidate_worlds": candidate_worlds,
                },
            }
            for arm in TIMING.S3A.ARMS
        },
        "folds": {
            name: {
                "requested_worlds": count,
                "sampler_counters": {
                    "sample_attempts": count,
                    "accepted_worlds": count,
                    "failed_worlds": 0,
                    "rejected_worlds": 0,
                    "impossible_worlds": 0,
                },
            }
            for name, count in (("selection", 8), ("report", 120))
        },
        # These are intentionally present in memory. score_free_work must not
        # copy them into its return value or the published receipt.
        "private_test_outcome": {
            "cards": ["SA"], "mean_gain_vs_incumbent": 999.0},
    }


def _records() -> list[dict]:
    return [_record(seed)
            for seed in range(TIMING.SEED0, TIMING.SEED_HI + 1)]


def _runtime() -> dict:
    return {"host": "mini", "digests": {"runner": "a" * 64}}


def _payload(*, wall: float = 10.0) -> dict:
    parent = TIMING.LIVE_PARENT.expected_parent()
    runtime = _runtime()
    caps = {
        "screen_fleet_hours": 1_000.0,
        "screen_max_shard_wall_hours": 1_000.0,
    }
    projected = TIMING.projections(wall)
    decided = TIMING.criteria(projected, caps)
    return {
        "schema": TIMING.SCHEMA,
        "complete": True,
        "evidence_grade": False,
        "strength_scores_persisted": False,
        "raw_records_persisted": False,
        "registered_screen_states_consumed": False,
        "git_sha": "f" * 40,
        "runtime_identity": runtime,
        "live_champion_parent": parent,
        "s3a_schema": TIMING.S3A.SCHEMA,
        "states": TIMING.STATE_COUNT,
        "seed0": TIMING.SEED0,
        "seed_hi": TIMING.SEED_HI,
        "wall_seconds": wall,
        "wall_seconds_by_state": [wall / 4, wall / 4],
        "work_totals": TIMING.score_free_work(_records()),
        "caps": caps,
        "projections": projected,
        "criteria": decided,
        "sizing_admitted": decided["all"],
        "claim_boundary": (
            "Outcome-free operational sizing on fresh 151M states only; no "
            "registered 136M state, strength claim, duel, promotion or deploy."
        ),
    }


def test_projection_is_exact_and_capacity_only():
    projected = TIMING.projections(3_600.0)
    assert projected == {
        "safety_factor": 2.0,
        "seconds_per_state": 1_800.0,
        "screen_fleet_hours": 512.0,
        "screen_max_shard_wall_hours": 64.0,
    }
    assert TIMING.criteria(projected, {
        "screen_fleet_hours": 512.0,
        "screen_max_shard_wall_hours": 64.0,
    })["all"] is True
    assert TIMING.criteria(projected, {
        "screen_fleet_hours": 511.9,
        "screen_max_shard_wall_hours": 64.0,
    })["all"] is False


def test_work_extractor_discards_actions_and_outcomes():
    work = TIMING.score_free_work(_records())
    encoded = json.dumps(work, sort_keys=True)
    assert work["states"] == 2
    assert len(set(work["candidate_worlds_by_arm"].values())) == 1
    assert "SA" not in encoded
    assert "mean_gain" not in encoded
    assert "private_test_outcome" not in encoded

    broken = _records()
    broken[0]["arms"]["structured"]["work"][
        "total_candidate_worlds"] += 1
    with pytest.raises(TIMING.ProtocolRefused, match="unequal"):
        TIMING.score_free_work(broken)


def test_receipt_rederives_arithmetic_and_rejects_outcome_fields():
    payload = _payload()
    kwargs = {
        "parent": payload["live_champion_parent"],
        "runtime": payload["runtime_identity"],
        "head": payload["git_sha"],
        "ancestry_checker": lambda _ancestor, _head: True,
    }
    assert TIMING.receipt_problems(payload, **kwargs) == []

    broken = copy.deepcopy(payload)
    broken["projections"]["screen_fleet_hours"] += 1
    assert any("arithmetic" in problem
               for problem in TIMING.receipt_problems(broken, **kwargs))

    broken = copy.deepcopy(payload)
    broken["stats"] = {"gain": 1.0}
    problems = TIMING.receipt_problems(broken, **kwargs)
    assert any("field set" in problem for problem in problems)
    assert any("forbidden outcome" in problem for problem in problems)


@pytest.mark.parametrize("mutate, expected", [
    (lambda work: work.__setitem__("innocent", {"strength_score": 123.0}),
     "work-total schema"),
    (lambda work: work["candidate_worlds_by_arm"].__setitem__(
        "structured", True), "candidate-work types"),
    (lambda work: work["candidate_worlds_by_arm"].__setitem__(
        "structured", work["candidate_worlds_by_arm"]["structured"] + 1),
     "candidate-work inequality"),
    (lambda work: work["folds"]["report"].__setitem__(
        "accepted_worlds",
        work["folds"]["report"]["accepted_worlds"] - 1),
     "counter equalities"),
    (lambda work: work["folds"]["selection"].__setitem__(
        "harmless_metric", 1), "counter schema"),
])
def test_receipt_rejects_noncanonical_nested_work_schema(mutate, expected):
    payload = _payload()
    kwargs = {
        "parent": payload["live_champion_parent"],
        "runtime": payload["runtime_identity"],
        "head": payload["git_sha"],
        "ancestry_checker": lambda _ancestor, _head: True,
    }
    mutate(payload["work_totals"])
    assert any(expected in problem
               for problem in TIMING.receipt_problems(payload, **kwargs))


def test_run_persists_only_score_free_receipt(monkeypatch, tmp_path):
    parent = TIMING.LIVE_PARENT.expected_parent()
    runtime = _runtime()
    head = "f" * 40
    monkeypatch.setattr(
        TIMING.S3A, "require_real_context", lambda: (parent, runtime, head))
    monkeypatch.setattr(
        TIMING.S3A, "run_state", lambda seed, _champion: _record(seed))
    monkeypatch.setattr(TIMING, "git_is_ancestor", lambda _a, _b: True)
    ticks = iter((0.0, 1.0, 2.0, 3.0, 4.0, 5.0))
    monkeypatch.setattr(TIMING.time, "perf_counter", lambda: next(ticks))
    out = tmp_path / "timing.json"
    args = argparse.Namespace(
        out=str(out), screen_fleet_hour_cap=1_000.0,
        screen_shard_wall_hour_cap=1_000.0)
    receipt = TIMING.run_preflight(args)
    assert json.loads(out.read_text()) == receipt
    assert set(receipt) == TIMING.RECEIPT_KEYS
    assert receipt["wall_seconds"] == 5.0
    assert receipt["wall_seconds_by_state"] == [1.0, 1.0]
    assert receipt["strength_scores_persisted"] is False
    assert receipt["raw_records_persisted"] is False
    assert receipt["registered_screen_states_consumed"] is False
    assert TIMING._forbidden_receipt_keys(receipt) == []


def test_loader_is_hash_bound_and_parent_bound(monkeypatch, tmp_path):
    payload = _payload()
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(TIMING, "git_is_ancestor", lambda _a, _b: True)
    loaded = TIMING.load_receipt(
        path, TIMING.sha256(path),
        parent=payload["live_champion_parent"],
        runtime=payload["runtime_identity"], head=payload["git_sha"])
    assert loaded == payload

    stale = TIMING.LIVE_PARENT.expected_parent()
    stale["champion_policy"] = "mc-strong"
    with pytest.raises(TIMING.ProtocolRefused, match="live parent"):
        TIMING.load_receipt(
            path, TIMING.sha256(path), parent=stale,
            runtime=payload["runtime_identity"], head=payload["git_sha"])

    path.write_text(json.dumps({**payload, "complete": False}))
    with pytest.raises(TIMING.ProtocolRefused, match="fixed field"):
        TIMING.load_receipt(
            path, TIMING.sha256(path),
            parent=payload["live_champion_parent"],
            runtime=payload["runtime_identity"], head=payload["git_sha"])

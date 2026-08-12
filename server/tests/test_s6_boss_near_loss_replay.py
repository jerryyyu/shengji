"""Contracts for the bounded S6 boss/near losing-witness replay."""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import s6_boss_near_loss_replay as REPLAY  # noqa: E402


RESULT = Path(__file__).with_name("data") / \
    "s6_boss_near_override_census.v1.json"


def test_compact_search_omits_rng_and_keeps_decision_evidence():
    record = {
        "rng_state": [1, 2, 3],
        "candidates": [["C3"], ["C4"]],
        "means": [1.0, 2.0],
        "n_by_candidate": [30, 30],
        "eligible_indices": [0, 1],
        "raw_winner_index": 1,
        "report_candidate_index": 1,
        "played_index": 1,
        "played": ["C4"],
        "reason": "report_lcb_override",
        "report_fold": {"gap": 1.0, "se": 0.2, "worlds": 300},
        "work": {"complete": True},
    }
    summary = REPLAY.compact_search(record)
    assert "rng_state" not in summary
    assert summary["played"] == ["C4"]
    assert summary["report_fold"] == {"worlds": 300, "gap": 1.0, "se": 0.2}


def test_first_divergence_handles_equal_prefix_and_length_drift():
    left = [{"seat": 0, "cards": ["C3"]},
            {"seat": 1, "cards": ["C4"]}]
    assert REPLAY.first_divergence(left, list(left)) is None
    assert REPLAY.first_divergence(left, left[:1]) == 1
    changed = [left[0], {"seat": 1, "cards": ["C5"]}]
    assert REPLAY.first_divergence(left, changed) == 1


def test_witness_summary_identifies_failed_throw_without_calling_it_strength():
    treatment = {
        "seed": 123, "flip": 0,
        "history": [{"seat": 0, "cards": ["C3"]}],
        "lead_events": [{
            "action_index": 0, "trick_index": 0, "seat": 0,
            "role": "defender", "attacker_points_before": 0,
            "hand_before": ["C3", "C3", "C4", "C4"],
            "attempted": ["C3", "C3", "C4", "C4"],
            "actual": ["C3", "C3"],
            "s6": {"treatment_override": True, "ballot": {"candidates": []}},
            "component_proof": {
                "all_components_publicly_proven_boss": False,
                "near_boss_components": 1,
            },
            "search": {"report_fold": {"complete": True, "gap": 2.0}},
            "incumbent_search": {"played": ["D3"]},
        }],
        "attacker_points": 75, "winner_team": 0, "level_change": 1,
    }
    champion = {
        "seed": 123, "flip": 0,
        "history": [{"seat": 0, "cards": ["D3"]}],
        "lead_events": [],
        "attacker_points": 75, "winner_team": 0, "level_change": 1,
    }
    row = REPLAY.summarize_witness(treatment, champion)
    assert row["throw_succeeded"] is False
    assert row["signed_level_utility_delta"] == 0
    assert row["incumbent"] == ["D3"]


def test_replay_is_explicitly_exploration_only(monkeypatch):
    treatment = {
        "history": [{"seat": 1, "cards": ["C4"]}],
        "tricks": [],
        "lead_events": [{
            "action_index": 0,
            "s6": {"treatment_override": True},
        }],
        "winner_team": 0,
        "level_change": 1,
    }
    champion = {
        "history": [{"seat": 1, "cards": ["C3"]}],
        "tricks": [],
        "lead_events": [],
        "winner_team": 1,
        "level_change": 1,
    }
    monkeypatch.setattr(
        REPLAY, "trace_round",
        lambda label, *_args: treatment if label == "treatment" else champion)
    payload = REPLAY.build_payload("a" * 40)
    assert payload["signed_level_utility_delta"] == -2
    assert payload["exploration_only"] is True
    assert payload["confirmatory_claim"] is False
    assert payload["strength_claim"] is False
    assert payload["production_promotion"] is False
    assert payload["production_deployment"] is False


def test_frozen_override_census_recomputes_the_public_certainty_split():
    raw = RESULT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "f910a94c66b22144954cd0619e093fc9608896759d8a10c282b355bc56ff4d80")
    payload = json.loads(raw)
    internal = payload.pop("internal_sha256")
    assert REPLAY.PILOT.stable_digest(payload) == internal == (
        "302802c105f17477cba7ee3f6da66935fbba19a53263878dafb4e8c142d06d63")
    assert payload["git"] == "97ac4c22fb2ccf486e2e7c8ba3915e4662efa833"
    rows = payload["rows"]
    assert [(row["seed"], row["flip"])
            for row in rows] == list(REPLAY.OVERRIDE_WITNESSES)
    assert Counter(row["signed_level_utility_delta"] for row in rows) == {
        0: 11, -2: 1}
    assert Counter(row["throw_succeeded"] for row in rows) == {
        True: 11, False: 1}
    assert Counter(row["component_proof"][
        "all_components_publicly_proven_boss"] for row in rows) == {
            True: 10, False: 2}
    failed = [row for row in rows if not row["throw_succeeded"]]
    assert len(failed) == 1
    assert failed[0]["signed_level_utility_delta"] == -2
    assert failed[0]["component_proof"]["near_boss_components"] == 2
    assert payload["summary"] == {
        "all_boss_negative_utility": 0,
        "all_boss_neutral_utility": 10,
        "all_boss_positive_utility": 0,
        "all_boss_public_proof": 10,
        "failed_throw_negative_utility": 1,
        "failed_throws": 1,
        "negative_utility": 1,
        "neutral_utility": 11,
        "positive_utility": 0,
        "successful_throws": 11,
        "witnesses": 12,
    }
    assert payload["exploration_only"] is True
    assert payload["confirmatory_claim"] is False
    assert payload["strength_claim"] is False
    assert payload["production_promotion"] is False
    assert payload["production_deployment"] is False

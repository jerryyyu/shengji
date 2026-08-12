"""Contracts for the bounded S6 boss/near losing-witness replay."""
from __future__ import annotations

import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import s6_boss_near_loss_replay as REPLAY  # noqa: E402


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


def test_replay_is_explicitly_exploration_only(monkeypatch):
    treatment = {
        "history": [{"seat": 1, "cards": ["C4"]}],
        "lead_events": [{
            "action_index": 0,
            "s6": {"treatment_override": True},
        }],
        "winner_team": 0,
        "level_change": 1,
    }
    champion = {
        "history": [{"seat": 1, "cards": ["C3"]}],
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

"""No-authority contracts for the selective S6 whole-round core."""
from __future__ import annotations

import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import s6_throw_full_hand_duel as S  # noqa: E402
from shengji.ai.registry import REGISTRY  # noqa: E402


def _counters(mode: str) -> dict:
    value = S.BASE.counters([])
    value["s6_throw"] = S.BASE.empty_s6_throw_telemetry(mode=mode)
    return value


def _record(label: str, *, flip: int) -> dict:
    mode = {"treatment": "treatment", "matched_null": "matched_null",
            "champion": "off"}[label]
    won = int(flip == 0)
    return {
        "run": "full-hand-test",
        "label": label,
        "policy": S.LABELS[label],
        "opponent": S.OPPONENT,
        "seed": 100,
        "flip": flip,
        "banker": 0,
        "attacker_points": 40,
        "winner_team": 0,
        "level_change": 1,
        "won": won,
        "level_utility": 1 if won else -1,
        "arm": _counters(mode),
        "opp": _counters("off"),
    }


def test_factories_are_explicit_champion_anchored_and_unregistered():
    treatment = S.make_arm("treatment", 7)
    null = S.make_arm("matched_null", 7)
    champion = S.make_arm("champion", 7)
    assert treatment.s6_throw_base_policy == S.CHAMPION
    assert null.s6_throw_base_policy == S.CHAMPION
    assert not hasattr(champion, "s6_throw_search_gate")
    assert S.LABELS["treatment"] not in REGISTRY
    assert S.LABELS["matched_null"] not in REGISTRY


def test_specialized_policy_identity_delegates_to_mature_validator():
    row = _record("treatment", flip=0)
    assert S.record_problems(
        row, expected_label="treatment", expected_seed=100,
        expected_flip=0, expected_run_id="full-hand-test") == []
    row["policy"] = S.BASE.LABELS["treatment"]
    assert S.record_problems(
        row, expected_label="treatment", expected_seed=100,
        expected_flip=0, expected_run_id="full-hand-test") == [
            "record identity"]


def test_aggregate_retains_specialized_labels_without_weakening_checks():
    records = {
        label: [_record(label, flip=0), _record(label, flip=1)]
        for label in S.LABEL_ORDER
    }
    result = S.build_aggregate(records, expected_clusters=1)
    assert result["schema"] == S.AGGREGATE_SCHEMA
    assert result["labels"] == S.LABELS
    assert result["opponent"] == S.CHAMPION
    assert result["criteria"]["matched_null_champion_exact_outcomes"] is True
    assert result["status"] == "SELECT_NONE"
    assert result["strength_claim"] is False

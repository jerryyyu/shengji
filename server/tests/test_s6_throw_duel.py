"""Core S6 whole-round evaluator contracts; no execution authority."""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import s6_throw_duel as S6D  # noqa: E402


def _telemetry(mode: str, *, attacker: int = 0,
               defender: int = 0, overrides: int = 0) -> dict:
    values = {field: 0 for field in S6D.S6_THROW_COUNTER_FIELDS}
    triggers = attacker + defender
    if mode != "off":
        values.update({
            "play_calls": 10,
            "lead_calls": 4,
            "eligible_leads": triggers,
            "source_candidates": triggers,
            "new_candidate_triggers": triggers,
            "new_candidates": triggers,
            "searched_triggers": triggers,
            "treatment_overrides": overrides,
            "matched_noops": triggers if mode == "matched_null" else 0,
            "attacker_triggers": attacker,
            "defender_triggers": defender,
            "base_candidate_count": 8 * triggers,
            "widened_candidate_count": 9 * triggers,
        })
    return {
        "schema": "s6-throw-source-cumulative-telemetry-v1",
        "mode": mode,
        "deterministic_source": True,
        "exact_work_complete": True,
        **values,
    }


def _counters(mode: str, *, attacker: int = 0,
              defender: int = 0, overrides: int = 0) -> dict:
    value = S6D.counters([])
    value["s6_throw"] = _telemetry(
        mode, attacker=attacker, defender=defender, overrides=overrides)
    return value


def _record(label: str, seed: int, flip: int, utility: int) -> dict:
    mode = {"treatment": "treatment", "matched_null": "matched_null",
            "champion": "off"}[label]
    # Banker team wins one level at 40 points.  Flip controls which policy team
    # owns that same outcome, hence the signed utility.
    winner = 0
    won = int(winner == (0 if flip == 0 else 1))
    expected_utility = (1 if won else -1)
    assert utility == expected_utility
    return {
        "run": "s6-test",
        "label": label,
        "policy": S6D.LABELS[label],
        "opponent": S6D.OPPONENT,
        "seed": seed,
        "flip": flip,
        "banker": 0,
        "attacker_points": 40,
        "winner_team": winner,
        "level_change": 1,
        "won": won,
        "level_utility": utility,
        "arm": _counters(
            mode, attacker=int(label != "champion"),
            defender=int(label != "champion"),
            overrides=int(label == "treatment")),
        "opp": _counters("off"),
    }


def _population(clusters: int = 2) -> dict[str, list[dict]]:
    records = {label: [] for label in S6D.LABEL_ORDER}
    for seed in range(100, 100 + clusters):
        for label in S6D.LABEL_ORDER:
            for flip, utility in ((0, 1), (1, -1)):
                records[label].append(_record(label, seed, flip, utility))
    # Make treatment win both flips without changing record legality by using
    # valid alternative outcomes: attacker reaches 80 when treatment is policy
    # team 1, while banker team wins when treatment is policy team 0.
    for row in records["treatment"]:
        if row["flip"] == 1:
            row.update({"attacker_points": 80, "winner_team": 1,
                        "won": 1, "level_change": 0,
                        "level_utility": 1})
    return records


def test_policy_factories_are_explicit_and_unregistered():
    treatment = S6D.make_arm("treatment", 7)
    null = S6D.make_arm("matched_null", 7)
    champion = S6D.make_arm("champion", 7)
    assert treatment.s6_throw_mode == "treatment"
    assert null.s6_throw_mode == "matched_null"
    assert not hasattr(champion, "s6_throw_mode")
    with pytest.raises(S6D.S6ProtocolRefused, match="unknown"):
        S6D.make_arm("mystery", 7)


def test_record_validation_recomputes_house_outcome_and_signed_utility():
    row = _record("matched_null", 100, 0, 1)
    assert S6D.record_problems(
        row, expected_label="matched_null", expected_seed=100,
        expected_flip=0, expected_run_id="s6-test") == []
    bad = deepcopy(row)
    bad["level_utility"] = -1
    assert "record signed utility" in S6D.record_problems(
        bad, expected_label="matched_null", expected_seed=100,
        expected_flip=0, expected_run_id="s6-test")


def test_aggregate_passes_positive_treatment_with_exact_null():
    records = _population()
    result = S6D.build_aggregate(records, expected_clusters=2)
    assert result["stats"]["treatment_champion"]["mean"] == 2
    assert result["stats"]["matched_null_champion"]["mean"] == 0
    assert result["criteria"]["matched_null_champion_exact_outcomes"] is True
    assert result["criteria"]["all"] is True
    assert result["status"] == "AUTHORIZE_CONFIRM_PACKET_REVIEW"
    assert result["strength_claim"] is False


def test_aggregate_rejects_null_outcome_drift_even_when_utility_is_unchanged():
    records = _population()
    row = records["matched_null"][0]
    row["attacker_points"] = 35
    with pytest.raises(S6D.S6ProtocolRefused, match="invalid matched_null"):
        S6D.build_aggregate(records, expected_clusters=2)


def test_telemetry_rejects_null_missing_matched_noop():
    value = _telemetry("matched_null", attacker=1, defender=1)
    value["matched_noops"] = 1
    assert "S6 matched-null dose" in S6D.telemetry_problems(
        value, expected_mode="matched_null")


def test_feature_off_telemetry_refuses_a_hidden_s6_wrapper():
    bot = S6D.make_arm("treatment", 11)
    with pytest.raises(S6D.S6ProtocolRefused, match="feature-off"):
        S6D.s6_telemetry([bot], mode="off")

from __future__ import annotations

import copy

import pytest

from shengji.rl import stage_c_screen as SCREEN


def _counters(stage_c):
    return {
        "rollouts": 600,
        "searches": 1,
        "search_secs": 0.1,
        "void_fallbacks": 0,
        "rejected_worlds": 0,
        "sample_attempts": 300,
        "accepted_worlds": 300,
        "failed_worlds": 0,
        "short_searches": 0,
        "zero_world": 0,
        "exact_endgames": 0,
        "exact_endgame_attempts": 0,
        "exact_endgame_refusals": 0,
        "exact_endgame_budget_exceeded": 0,
        "exact_endgame_sessions": 0,
        "exact_endgame_nodes": 0,
        "exact_endgame_cache_hits": 0,
        "stage_c": stage_c,
    }


def _stage(*, trigger: bool, override: bool = False):
    values = SCREEN.feature_off_telemetry()
    if trigger:
        values.update({
            "focus_calls": 1,
            "model_triggers": 1,
            "report_overrides": int(override),
            "report_rejections": int(not override),
        })
    return values


def _population(clusters=32, seed0=7000):
    rows = {label: [] for label in SCREEN.LABELS}
    for seed in range(seed0, seed0 + clusters):
        for flip in (0, 1):
            # A deterministic +2 per seed treatment advantage, zero null
            # movement, and nonzero legal utilities for every record.
            utilities = {"treatment": 2, "matched_null": 1, "champion": 1}
            for label in SCREEN.LABELS:
                stage = (_stage(trigger=True, override=(label == "treatment"))
                         if label != "champion" else
                         SCREEN.feature_off_telemetry())
                rows[label].append({
                    "schema": SCREEN.SCHEMA,
                    "run": "screen-run",
                    "label": label,
                    "seed": seed,
                    "flip": flip,
                    "won": 1,
                    "level_utility": utilities[label],
                    "arm": _counters(stage),
                    "opp": _counters(SCREEN.feature_off_telemetry()),
                })
    return rows


def test_positive_screen_requires_model_gain_and_clean_null() -> None:
    result = SCREEN.aggregate_screen(
        _population(), expected_seed0=7000, expected_clusters=32)
    assert result["stats"]["treatment_champion"]["lcb95"] > 0
    assert result["stats"]["treatment_matched_null"]["lcb95"] > 0
    assert result["stats"]["matched_null_champion"]["mean"] == 0
    assert result["criteria"]["all"] is True
    assert result["status"] == "AUTHORIZE_CONFIRM_PACKET_REVIEW"
    assert result["strength_claim"] is False
    assert result["production_promotion"] is False


def test_positive_model_result_is_rejected_when_null_also_moves() -> None:
    rows = _population()
    for row in rows["matched_null"]:
        row["level_utility"] = 2
    result = SCREEN.aggregate_screen(
        rows, expected_seed0=7000, expected_clusters=32)
    assert result["criteria"][
        "matched_null_champion_interval_contains_zero"] is False
    assert result["status"] == "SELECT_NONE"


def test_fallback_or_work_failure_refuses_before_statistics() -> None:
    fallback = _population()
    fallback["treatment"][0]["arm"]["stage_c"]["fallbacks"] = 1
    fallback["treatment"][0]["arm"]["stage_c"][
        "exact_reconciliation"] = False
    with pytest.raises(SCREEN.StageCScreenError, match="fallback"):
        SCREEN.aggregate_screen(
            fallback, expected_seed0=7000, expected_clusters=32)

    short = _population()
    short["treatment"][0]["arm"]["short_searches"] = 1
    with pytest.raises(SCREEN.StageCScreenError, match="underfilled"):
        SCREEN.aggregate_screen(
            short, expected_seed0=7000, expected_clusters=32)


def test_duplicate_or_missing_seed_flip_refuses() -> None:
    rows = _population()
    rows["treatment"][-1] = copy.deepcopy(rows["treatment"][0])
    with pytest.raises(SCREEN.StageCScreenError, match="population"):
        SCREEN.aggregate_screen(
            rows, expected_seed0=7000, expected_clusters=32)


def test_win_and_level_utility_sign_must_match() -> None:
    rows = _population()
    rows["champion"][0]["won"] = 0
    with pytest.raises(SCREEN.StageCScreenError, match="value drift"):
        SCREEN.aggregate_screen(
            rows, expected_seed0=7000, expected_clusters=32)

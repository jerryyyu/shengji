from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from shengji.rl import stage_c_screen as SCREEN


def _counters(stage_c, *, feature_on: bool):
    rollouts = 600 if feature_on else 660
    accepted = 300 if feature_on else 330
    return {
        "rollouts": rollouts,
        "searches": 1,
        "search_secs": 0.1,
        "void_fallbacks": 0,
        "rejected_worlds": 0,
        "sample_attempts": accepted,
        "accepted_worlds": accepted,
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
                    "arm": _counters(
                        stage, feature_on=label != "champion"),
                    "opp": _counters(
                        SCREEN.feature_off_telemetry(), feature_on=False),
                })
    return rows


def test_positive_screen_requires_model_gain_and_clean_null() -> None:
    result = SCREEN.aggregate_screen(
        _population(), expected_seed0=7000, expected_clusters=32,
        expected_surface="bury")
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
        rows, expected_seed0=7000, expected_clusters=32,
        expected_surface="bury")
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
            fallback, expected_seed0=7000, expected_clusters=32,
            expected_surface="bury")

    short = _population()
    short["treatment"][0]["arm"]["short_searches"] = 1
    with pytest.raises(SCREEN.StageCScreenError, match="underfilled"):
        SCREEN.aggregate_screen(
            short, expected_seed0=7000, expected_clusters=32,
            expected_surface="bury")

    zero_work = _population()
    zero_work["treatment"][0]["arm"].update({
        "rollouts": 0, "searches": 0, "sample_attempts": 0,
        "accepted_worlds": 0,
    })
    with pytest.raises(SCREEN.StageCScreenError, match="work drift"):
        SCREEN.aggregate_screen(
            zero_work, expected_seed0=7000, expected_clusters=32,
            expected_surface="bury")


def test_duplicate_or_missing_seed_flip_refuses() -> None:
    rows = _population()
    rows["treatment"][-1] = copy.deepcopy(rows["treatment"][0])
    with pytest.raises(SCREEN.StageCScreenError, match="population"):
        SCREEN.aggregate_screen(
            rows, expected_seed0=7000, expected_clusters=32,
            expected_surface="bury")


def test_win_and_level_utility_sign_must_match() -> None:
    rows = _population()
    rows["champion"][0]["won"] = 0
    with pytest.raises(SCREEN.StageCScreenError, match="value drift"):
        SCREEN.aggregate_screen(
            rows, expected_seed0=7000, expected_clusters=32,
            expected_surface="bury")


def test_factory_runner_uses_mirrored_seed_streams_and_records_telemetry(
        monkeypatch) -> None:
    policy_seeds = []
    opponent_seeds = []

    def bot(seed, *, stage_c):
        value = SimpleNamespace()
        if stage_c:
            value.stage_c_focus_calls = 1
            value.stage_c_model_keeps = 1
            value.stage_c_focus_triggers = 0
            value.stage_c_focus_fallbacks = 0
            value.stage_c_report_overrides = 0
            value.stage_c_report_rejections = 0
            value.stage_c_report_underfills = 0
        return value

    def policy(seed):
        policy_seeds.append(seed)
        return bot(seed, stage_c=True)

    def opponent(seed):
        opponent_seeds.append(seed)
        return bot(seed, stage_c=False)

    monkeypatch.setattr(SCREEN, "Game", lambda rng: rng)
    monkeypatch.setattr(
        SCREEN, "play_round",
        lambda _game, _policies: SimpleNamespace(
            winner_team=0, level_change=2),
    )
    records = SCREEN.run_arm_factories(
        "treatment", policy, opponent, clusters=1, seed0=123,
        run_id="factory-run", policy_has_stage_c=True, progress=False)
    assert policy_seeds == [123, 500_123, 123, 500_123]
    assert opponent_seeds == [1_000_123, 1_500_123] * 2
    assert [(record["flip"], record["level_utility"])
            for record in records] == [(0, 2), (1, -2)]
    assert all(record["arm"]["stage_c"]["exact_reconciliation"]
               for record in records)

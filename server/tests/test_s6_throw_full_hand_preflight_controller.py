"""Fail-closed contracts for the selective S6 capacity controller."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import s6_throw_full_hand_preflight_controller as S  # noqa: E402


def _counters(mode: str) -> dict:
    value = S.CORE.BASE.counters([])
    value["s6_throw"] = S.CORE.BASE.empty_s6_throw_telemetry(mode=mode)
    return value


def _record(label: str, flip: int, *, points: int = 40) -> dict:
    mode = {"treatment": "treatment", "matched_null": "matched_null",
            "champion": "off"}[label]
    winner, gain = S.CORE.BASE.expected_round_outcome(
        banker=0, attacker_points=points)
    won = int(winner == (0 if flip == 0 else 1))
    return {
        "run": S.PREFLIGHT_RUN_ID,
        "label": label,
        "policy": S.CORE.LABELS[label],
        "opponent": S.CORE.OPPONENT,
        "seed": S.PREFLIGHT_SEED0,
        "flip": flip,
        "banker": 0,
        "attacker_points": points,
        "winner_team": winner,
        "level_change": gain,
        "won": won,
        "level_utility": (1 if won else -1) * max(1, gain),
        "arm": _counters(mode),
        "opp": _counters("off"),
    }


def test_screen_size_is_powered_from_disclosed_fitting_inputs():
    planning = S.planning_values()
    assert S.SCREEN_CLUSTERS == 7_168
    assert S.SHARD_COUNT == 8
    assert planning["expected_triggered_clusters"] > 120
    assert planning["heuristic_trajectory_trigger_rate"] == pytest.approx(
        1_011 / 50_000)
    assert planning["champion_trajectory_trigger_rate"] == pytest.approx(
        13 / 512)
    assert planning["natural_trigger_rate"] == pytest.approx(1_011 / 50_000)
    assert planning["mixture_planning_mean"] == pytest.approx(0.0062002734375)
    assert planning["mixture_planning_sd"] == pytest.approx(
        0.13569923072248874)
    assert planning["mde80_one_sided_95"] == pytest.approx(
        0.003985313221485745)
    assert planning["planning_power_at_fitting_mean"] > 0.98


def test_champion_census_is_exact_score_free_and_does_not_inflate_sizing():
    evidence = S.champion_census_evidence()
    assert evidence == {
        "path": "server/tests/data/"
                "s6_throw_full_hand_champion_census.v1.json",
        "sha256": S.CHAMPION_CENSUS_SHA256,
        "policy": "mc-s0-report-lcb",
        "deals": 512,
        "leads": 9_382,
        "triggered_deals": 13,
        "triggered_leads": 13,
        "triggered_deal_rate": 13 / 512,
        "triggered_lead_rate": 13 / 9_382,
        "score_free": True,
        "strength_claim": False,
    }
    assert S.PREVALENCE_RATE == S.HEURISTIC_PREVALENCE_RATE
    assert S.CHAMPION_PREVALENCE_RATE > S.PREVALENCE_RATE


def test_policy_contract_is_literal_champion_plus_unregistered_gate():
    contracts = S.policy_contracts()
    assert set(contracts) == set(S.CORE.LABEL_ORDER)
    assert len({row["root_ballot_digest"] for row in contracts.values()}) == 1
    assert contracts["champion"]["policy"] == "mc-s0-report-lcb"
    assert contracts["treatment"]["s6_mode"] == "treatment"
    assert contracts["matched_null"]["s6_mode"] == "matched_null"


def test_selector_marker_must_be_exact_and_single(tmp_path):
    marker = S.SELECTOR_REVIEW_PREFIX + json.dumps(
        S.EXPECTED_SELECTOR_REVIEW, sort_keys=True, separators=(",", ":"))
    path = tmp_path / "review.md"
    path.write_text(marker + "\n")
    parsed = S.parse_marker(
        path, S.SELECTOR_REVIEW_PREFIX, S.EXPECTED_SELECTOR_REVIEW,
        label="selector")
    assert parsed["payload"] == S.EXPECTED_SELECTOR_REVIEW
    path.write_text(marker + "\n" + marker + "\n")
    with pytest.raises(S.ControllerRefused, match="exactly one"):
        S.parse_marker(
            path, S.SELECTOR_REVIEW_PREFIX, S.EXPECTED_SELECTOR_REVIEW,
            label="selector")


def test_packet_reconstructs_exactly_and_grants_no_execution(
        tmp_path, monkeypatch):
    marker = S.SELECTOR_REVIEW_PREFIX + json.dumps(
        S.EXPECTED_SELECTOR_REVIEW, sort_keys=True, separators=(",", ":"))
    review = tmp_path / "review.md"
    review.write_text(marker + "\n")
    monkeypatch.setattr(S, "git_is_ancestor", lambda left, right: True)
    monkeypatch.setattr(S, "source_sha256s", lambda: {"source": "sha"})
    monkeypatch.setattr(S, "require_air_runtime", lambda: {"host": "air"})
    packet = S.packet_payload(
        expected_git="controller", selector_review_record=review)
    internal = packet.pop("internal_sha256")
    assert S.stable_digest(packet) == internal
    packet["internal_sha256"] = internal
    assert packet["proposed_screen"]["clusters"] == 7_168
    assert packet["proposed_screen"]["clusters_per_shard"] == 896
    assert packet["champion_trajectory_census"]["triggered_deals"] == 13
    assert packet["authority"] == {
        "preflight_execution_authorized": False,
        "screen_packet_design_authorized": False,
        "screen_execution_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    assert S.packet_problems(
        packet, expected_git="controller",
        selector_review_record=review) == []
    packet["authority"]["screen_execution_authorized"] = True
    assert S.packet_problems(
        packet, expected_git="controller",
        selector_review_record=review) == [
            "packet differs from reconstruction"]


def test_score_free_preflight_can_pass_without_lucky_four_cluster_trigger(
        monkeypatch):
    monkeypatch.setattr(S, "PREFLIGHT_CLUSTERS", 1)
    monkeypatch.setattr(S, "SCREEN_CLUSTERS", 8)

    def play(label, seed, *, run_id):
        assert seed == S.PREFLIGHT_SEED0
        assert run_id == S.PREFLIGHT_RUN_ID
        return [_record(label, 0), _record(label, 1)]

    monkeypatch.setattr(S.CORE, "play_arm_cluster", play)
    ticks = iter((0.0, 60.0))
    result = S.measure_preflight(
        {"git": "abc", "internal_sha256": "packet"},
        clock=lambda: next(ticks))
    assert result["capacity_pass"] is True
    assert result["null_champion_exact_outcomes"] is True
    assert result["records_discarded"] == 6
    assert result["counts"]["treatment"]["arm_s6"][
        "searched_triggers"] == 0
    assert result["outcomes_published"] is False
    assert result["screen_packet_design_authorized"] is False
    assert result["strength_claim"] is False
    assert S.BASE.score_free_result_problems(result) == []


def test_score_free_preflight_holds_on_null_champion_drift(monkeypatch):
    monkeypatch.setattr(S, "PREFLIGHT_CLUSTERS", 1)
    monkeypatch.setattr(S, "SCREEN_CLUSTERS", 8)

    def play(label, seed, *, run_id):
        points = 45 if label == "matched_null" else 40
        return [_record(label, 0, points=points),
                _record(label, 1, points=points)]

    monkeypatch.setattr(S.CORE, "play_arm_cluster", play)
    ticks = iter((0.0, 60.0))
    result = S.measure_preflight(
        {"git": "abc", "internal_sha256": "packet"},
        clock=lambda: next(ticks))
    assert result["null_champion_exact_outcomes"] is False
    assert result["capacity_pass"] is False
    assert result["supports_screen_packet_review"] is False


def test_score_free_validator_rejects_hidden_outcome():
    value = {"score_free": True, "outcomes_published": False,
             "hidden": {"attacker_points": 80}}
    assert S.BASE.score_free_result_problems(value) == [
        "forbidden score field hidden.attacker_points"]


def test_capacity_review_claim_never_authorizes_execution():
    result = {
        "capacity_pass": True,
        "internal_sha256": "internal",
        "elapsed_seconds": 12.5,
        "git": "controller",
        "null_champion_exact_outcomes": True,
        "projection": {
            "screen_fleet_hours": 100.0,
            "screen_max_shard_hours": 12.5,
        },
    }
    claim = S.capacity_review_claim(
        result=result, result_sha256="result", packet_sha256="packet")
    assert claim["one_screen_packet_design_authorized"] is True
    assert claim["screen_execution_authorized"] is False
    assert claim["strength_claim"] is False
    assert claim["production_deployment"] is False

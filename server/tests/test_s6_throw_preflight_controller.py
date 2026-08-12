"""Fail-closed S6 score-free preflight controller tests."""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import s6_throw_preflight_controller as C  # noqa: E402


def _review(path: Path, prefix: str, payload: dict) -> Path:
    path.write_text(prefix + json.dumps(
        payload, sort_keys=True, separators=(",", ":")) + "\n")
    return path


def _source_review(tmp_path: Path) -> Path:
    return _review(tmp_path / "source-review.txt", C.SOURCE_REVIEW_PREFIX,
                   C.EXPECTED_SOURCE_REVIEW)


def test_source_review_requires_exact_single_marker(tmp_path):
    review = _source_review(tmp_path)
    parsed = C.parse_marker(
        review, C.SOURCE_REVIEW_PREFIX, C.EXPECTED_SOURCE_REVIEW,
        label="source")
    assert parsed["payload"] == C.EXPECTED_SOURCE_REVIEW
    review.write_text(review.read_text() * 2)
    with pytest.raises(C.ControllerRefused, match="exactly one"):
        C.parse_marker(
            review, C.SOURCE_REVIEW_PREFIX, C.EXPECTED_SOURCE_REVIEW,
            label="source")


def test_packet_reconstructs_and_keeps_every_authority_false(tmp_path,
                                                             monkeypatch):
    review = _source_review(tmp_path)
    monkeypatch.setattr(C, "git_is_ancestor", lambda *_args: True)
    monkeypatch.setattr(C, "source_sha256s", lambda: {"source": "1" * 64})
    packet = C.packet_payload(
        expected_git="a" * 40, source_review_record=review)
    assert C.packet_problems(
        packet, expected_git="a" * 40,
        source_review_record=review) == []
    assert packet["source_git"] == C.SOURCE_GIT
    assert packet["preflight"]["score_free"] is True
    assert all(value is False for value in packet["authority"].values())
    assert packet["internal_sha256"] == C.stable_digest(
        {key: value for key, value in packet.items()
         if key != "internal_sha256"})


def test_packet_mutations_are_detected(tmp_path, monkeypatch):
    review = _source_review(tmp_path)
    monkeypatch.setattr(C, "git_is_ancestor", lambda *_args: True)
    monkeypatch.setattr(C, "source_sha256s", lambda: {"source": "1" * 64})
    packet = C.packet_payload(
        expected_git="a" * 40, source_review_record=review)
    for mutate in (
            lambda value: value["screen"].__setitem__("clusters", 256),
            lambda value: value["authority"].__setitem__(
                "screen_execution_authorized", True),
            lambda value: value["capacity"].__setitem__(
                "screen_fleet_hour_cap", 10_000.0)):
        changed = deepcopy(packet)
        mutate(changed)
        changed["internal_sha256"] = C.stable_digest(
            {key: value for key, value in changed.items()
             if key != "internal_sha256"})
        assert C.packet_problems(
            changed, expected_git="a" * 40,
            source_review_record=review)


def _telemetry(mode: str) -> dict:
    values = {field: 0 for field in C.S6_THROW_COUNTER_FIELDS}
    if mode != "off":
        values.update({
            "play_calls": 10, "lead_calls": 4, "eligible_leads": 2,
            "source_candidates": 2, "new_candidate_triggers": 2,
            "new_candidates": 2, "searched_triggers": 2,
            "treatment_overrides": int(mode == "treatment"),
            "matched_noops": 2 if mode == "matched_null" else 0,
            "attacker_triggers": 1, "defender_triggers": 1,
            "base_candidate_count": 16, "widened_candidate_count": 18,
        })
    return {
        "schema": "s6-throw-source-cumulative-telemetry-v1",
        "mode": mode, "deterministic_source": True,
        "exact_work_complete": True, **values,
    }


def _counters(mode: str) -> dict:
    value = C.CORE.counters([])
    value["searches"] = 1 if mode != "off" else 0
    value["accepted_worlds"] = 330 if mode != "off" else 0
    value["sample_attempts"] = value["accepted_worlds"]
    value["rollouts"] = 1_000 if mode != "off" else 0
    value["s6_throw"] = _telemetry(mode)
    return value


def _row(label: str, seed: int, flip: int) -> dict:
    mode = {"treatment": "treatment", "matched_null": "matched_null",
            "champion": "off"}[label]
    winner = 0
    won = int(winner == (0 if flip == 0 else 1))
    return {
        "run": C.PREFLIGHT_RUN_ID, "label": label,
        "policy": C.CORE.LABELS[label], "opponent": C.CORE.OPPONENT,
        "seed": seed, "flip": flip, "banker": 0,
        "attacker_points": 40, "winner_team": winner, "level_change": 1,
        "won": won, "level_utility": 1 if won else -1,
        "arm": _counters(mode), "opp": _counters("off"),
    }


def test_measurement_discards_all_rows_and_projects_capacity(monkeypatch):
    packet = {"git": "a" * 40, "internal_sha256": "b" * 64}

    def play(label, seed, *, run_id):
        assert run_id == C.PREFLIGHT_RUN_ID
        return [_row(label, seed, flip) for flip in (0, 1)]

    ticks = iter((10.0, 22.0))
    monkeypatch.setattr(C.CORE, "play_arm_cluster", play)
    result = C.measure_preflight(packet, clock=lambda: next(ticks))
    assert result["records_discarded"] == 24
    assert result["score_free"] is True
    assert result["outcomes_published"] is False
    assert "records" not in result
    assert result["counts"]["treatment"]["arm_s6"][
        "searched_triggers"] == 16
    assert result["capacity_pass"] is True
    assert result["supports_screen_packet_review"] is True
    assert result["screen_packet_design_authorized"] is False
    assert result["screen_execution_authorized"] is False
    assert C.score_free_result_problems(result) == []


def test_bad_exact_work_refuses_score_free_measurement(monkeypatch):
    packet = {"git": "a" * 40, "internal_sha256": "b" * 64}

    def play(label, seed, *, run_id):
        rows = [_row(label, seed, flip) for flip in (0, 1)]
        if label == "treatment":
            rows[0]["arm"]["accepted_worlds"] -= 1
        return rows

    monkeypatch.setattr(C.CORE, "play_arm_cluster", play)
    with pytest.raises(C.ControllerRefused, match="invalid score-free"):
        C.measure_preflight(packet, clock=lambda: 1.0)


def test_packet_review_claim_grants_only_one_score_free_preflight():
    claim = C.packet_review_claim(
        expected_git="a" * 40, packet_sha256="b" * 64)
    assert claim["one_score_free_preflight_authorized"] is True
    assert claim["screen_execution_authorized"] is False
    assert claim["strength_claim"] is False
    assert claim["production_deployment"] is False


def test_capacity_claim_can_authorize_design_but_never_execution(monkeypatch):
    packet = {"git": "a" * 40, "internal_sha256": "b" * 64}

    def play(label, seed, *, run_id):
        return [_row(label, seed, flip) for flip in (0, 1)]

    ticks = iter((10.0, 22.0))
    monkeypatch.setattr(C.CORE, "play_arm_cluster", play)
    result = C.measure_preflight(packet, clock=lambda: next(ticks))
    claim = C.capacity_review_claim(
        result=result, result_sha256="c" * 64,
        packet_sha256="d" * 64)
    assert claim["one_screen_packet_design_authorized"] is True
    assert claim["screen_execution_authorized"] is False
    assert claim["strength_claim"] is False
    assert claim["production_deployment"] is False


def test_score_free_guard_rejects_nested_outcome_fields():
    value = {"score_free": True, "outcomes_published": False,
             "counts": {"treatment": {"winner_team": 0}}}
    assert C.score_free_result_problems(value) == [
        "forbidden score field counts.treatment.winner_team"]


def test_cli_preflight_refuses_before_gameplay_without_packet_review(
        tmp_path, monkeypatch):
    called = False

    def gameplay(_packet):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(C, "require_clean_exact_git", lambda _git: None)
    monkeypatch.setattr(C, "require_exact_output_path",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(C, "load_packet", lambda *args, **kwargs: {
        "git": "a" * 40, "internal_sha256": "b" * 64})
    monkeypatch.setattr(C, "measure_preflight", gameplay)
    monkeypatch.setattr(C, "require_compiled_strict_runtime", lambda: None)
    args = SimpleNamespace(
        expected_git="a" * 40, packet="packet.json",
        expected_packet_sha256="b" * 64,
        source_review_record="source.txt",
        packet_review_record=tmp_path / "missing-review.txt",
        admission=tmp_path / "admission.json", out=tmp_path / "result.json")
    with pytest.raises(C.ControllerRefused, match="review.*missing"):
        C.preflight_command(args)
    assert called is False
    assert not args.admission.exists()


def test_cli_preflight_binds_singleton_slot_before_opening_packet(
        tmp_path, monkeypatch):
    opened = False

    def load(*_args, **_kwargs):
        nonlocal opened
        opened = True
        return {}

    monkeypatch.setattr(C, "require_clean_exact_git", lambda _git: None)
    monkeypatch.setattr(C, "load_packet", load)
    args = SimpleNamespace(
        expected_git="a" * 40, packet="packet.json",
        expected_packet_sha256="b" * 64,
        source_review_record="source.txt",
        packet_review_record="review.txt",
        admission=tmp_path / "alternate-admission.json",
        out=C.RESULT_PATH)
    with pytest.raises(C.ControllerRefused, match="singleton path"):
        C.preflight_command(args)
    assert opened is False

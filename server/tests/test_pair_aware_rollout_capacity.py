"""Fail-closed tests for the pair-aware whole-round capacity packet."""
from __future__ import annotations

import json
import hashlib
import random
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import pair_aware_rollout_capacity as C  # noqa: E402
import pair_aware_rollout_duel as D  # noqa: E402
from shengji.ai.env import play_round  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine.cards import make_deck  # noqa: E402
from shengji.engine.game import Game  # noqa: E402


WITHDRAWN_V1_PACKET = (
    Path(__file__).resolve().parents[1]
    / "runs/logs/pair-aware-whole-round-preflight-v1/controller-packet.json"
)
FROZEN_V2_PACKET = (
    Path(__file__).resolve().parents[1]
    / "runs/logs/pair-aware-whole-round-preflight-v2/controller-packet.json"
)


def _review(path: Path) -> Path:
    path.write_text(
        C.EXACT_REVIEW_PREFIX + json.dumps(
            C.EXPECTED_EXACT_REVIEW, sort_keys=True, separators=(",", ":"))
        + "\n" + C.DOSE_REVIEW_PREFIX + json.dumps(
            C.EXPECTED_DOSE_REVIEW, sort_keys=True, separators=(",", ":"))
        + "\n")
    return path


def _air_runtime() -> dict:
    return {
        "host": C.EXPECTED_EXECUTION_HOST,
        "python": C.EXPECTED_PYTHON_VERSION,
        "implementation": C.EXPECTED_PYTHON_IMPLEMENTATION,
        "python_executable": C.EXPECTED_PYTHON_EXECUTABLE,
        "fast_required": True,
        "strict_voids_required": True,
        "fast_binary_sha256": C.EXPECTED_FAST_BINARY_SHA256,
    }


def _pair(mode: str, *, triggers: int = 2) -> dict:
    values = {field: 0 for field in C.PAIR_AWARE_COUNTER_FIELDS}
    if mode != "off":
        values.update({
            "lead_calls": 20,
            "single_baseline_leads": 18,
            "pair_candidates_checked": triggers,
            "promoted_boss_pairs": triggers,
            "ruff_safe_promoted_pairs": triggers,
            "opportunities": triggers,
            "triggers": triggers,
            "changes": triggers if mode == "treatment" else 0,
            "matched_noops": triggers if mode == "matched_null" else 0,
            "attacker_triggers": triggers // 2,
            "defender_triggers": triggers - triggers // 2,
            "point_pair_triggers": 0,
        })
    return {
        "schema": "pair-aware-rollout-telemetry-v1",
        "mode": mode,
        "deterministic": True,
        "public_information_only": True,
        "exact_work_complete": True,
        **values,
    }


def _counters(mode: str) -> dict:
    value = D.counters([])
    value["searches"] = 1
    value["accepted_worlds"] = D.ROOT_WORLDS + D.REPORT_WORLDS
    value["sample_attempts"] = value["accepted_worlds"]
    value["rollouts"] = 1_000
    value["pair_aware"] = _pair(mode)
    return value


def _history(*, changed_at: int | None = None,
             plays: int = 100) -> list[dict]:
    assert 4 <= plays <= 100 and plays % 4 == 0
    tricks = plays // 4
    widths = [1] * tricks
    for index in range(25 - tricks):
        widths[index % tricks] += 1
    cards = iter(make_deck()[:100])
    rows = []
    for width in widths:
        for seat in range(4):
            rows.append({"seat": seat,
                         "cards": [next(cards) for _ in range(width)]})
    if changed_at is not None:
        # Exchange two same-seat actions so the altered trajectory remains a
        # physically complete two-deck round rather than fabricating a card.
        other = changed_at + 4
        assert other < len(rows)
        assert rows[changed_at]["seat"] == rows[other]["seat"]
        assert len(rows[changed_at]["cards"]) == len(rows[other]["cards"])
        rows[changed_at]["cards"], rows[other]["cards"] = (
            rows[other]["cards"], rows[changed_at]["cards"])
    return rows


def _row(label: str, seed: int, flip: int, *, changed: bool = False) -> dict:
    mode = {"treatment": "treatment", "matched_null": "matched_null",
            "champion": "off"}[label]
    history = _history(
        changed_at=8 if changed and label == "treatment" else None)
    return {
        "run": C.PREFLIGHT_RUN_ID,
        "label": label,
        "policy": D.LABELS[label],
        "opponent": D.OPPONENT,
        "seed": seed,
        "flip": flip,
        "banker": 1,
        "attacker_points": 40,
        "winner_team": 1,
        "level_change": 1,
        "won": int((0 if flip == 0 else 1) == 1),
        "level_utility": 1 if flip == 1 else -1,
        "history": history,
        "arm": _counters(mode),
        "opp": _counters("off"),
    }


def test_review_records_require_one_exact_marker_each(tmp_path):
    review = _review(tmp_path / "review.md")
    assert C.parse_marker(
        review, C.EXACT_REVIEW_PREFIX, C.EXPECTED_EXACT_REVIEW,
        label="exact")["payload"] == C.EXPECTED_EXACT_REVIEW
    review.write_text(review.read_text() + review.read_text().splitlines()[0] + "\n")
    with pytest.raises(C.CapacityRefused, match="exactly one"):
        C.parse_marker(
            review, C.EXACT_REVIEW_PREFIX, C.EXPECTED_EXACT_REVIEW,
            label="exact")


def test_packet_reconstructs_with_no_successor_authority(tmp_path, monkeypatch):
    review = _review(tmp_path / "review.md")
    monkeypatch.setattr(C, "git_is_ancestor", lambda *_args: True)
    monkeypatch.setattr(C, "source_sha256s", lambda: {"source": "1" * 64})
    monkeypatch.setattr(C, "require_air_runtime", _air_runtime)
    monkeypatch.setattr(C, "policy_contracts", lambda: {"arms": "equal"})
    packet = C.packet_payload(
        expected_git="a" * 40,
        exact_review_record=review,
        dose_review_record=review)
    assert C.packet_problems(
        packet, expected_git="a" * 40,
        exact_review_record=review, dose_review_record=review) == []
    assert packet["successor_projection"]["candidate_clusters"] == [2048, 8192]
    assert all(value is False for value in packet["authority"].values())


def test_packet_mutations_refuse_reconstruction(tmp_path, monkeypatch):
    review = _review(tmp_path / "review.md")
    monkeypatch.setattr(C, "git_is_ancestor", lambda *_args: True)
    monkeypatch.setattr(C, "source_sha256s", lambda: {"source": "1" * 64})
    monkeypatch.setattr(C, "require_air_runtime", _air_runtime)
    monkeypatch.setattr(C, "policy_contracts", lambda: {"arms": "equal"})
    packet = C.packet_payload(
        expected_git="a" * 40,
        exact_review_record=review, dose_review_record=review)
    for mutate in (
            lambda value: value["preflight"].__setitem__("clusters", 8),
            lambda value: value["authority"].__setitem__(
                "screen_execution_authorized", True),
            lambda value: value["successor_projection"].__setitem__(
                "candidate_clusters", [128]),
            lambda value: value["runtime"].__setitem__(
                "host", "Jerrys-Mac-mini.local")):
        changed = deepcopy(packet)
        mutate(changed)
        changed["internal_sha256"] = C.stable_digest(
            {key: val for key, val in changed.items()
             if key != "internal_sha256"})
        assert C.packet_problems(
            changed, expected_git="a" * 40,
            exact_review_record=review, dose_review_record=review)


def test_runtime_identity_is_exact_air():
    assert C.runtime_problems(_air_runtime()) == []
    changed = _air_runtime()
    changed["fast_binary_sha256"] = "0" * 64
    assert C.runtime_problems(changed) == ["runtime is not exact Air"]


def test_pair_telemetry_validation_catches_mode_and_dose_drift():
    assert D.telemetry_problems(_pair("treatment"), expected_mode="treatment") == []
    bad = _pair("matched_null")
    bad["changes"] = 1
    assert "pair matched-null dose" in D.telemetry_problems(
        bad, expected_mode="matched_null")


def test_natural_dose_stops_at_first_shared_trajectory_change():
    treatment = _row("treatment", 7, 0, changed=True)
    null = _row("matched_null", 7, 0)
    dose = D.natural_root_dose(treatment, null)
    assert dose == {
        "shared_prefix_plays": 8,
        "root_action_changed": True,
        "change_play_index": 8,
        "change_phase": "early",
        "change_role": "attacker",
    }


def test_variable_length_complete_round_history_is_valid():
    # Pair/tractor/throw leads consume multiple cards and therefore produce
    # fewer than 25 tricks / 100 play actions in an otherwise complete round.
    treatment = _row("treatment", 7, 0)
    null = _row("matched_null", 7, 0)
    treatment["history"] = _history(plays=84)
    null["history"] = _history(plays=84)
    assert D.record_problems(
        treatment, expected_label="treatment", expected_seed=7,
        expected_flip=0, expected_run_id=C.PREFLIGHT_RUN_ID) == []
    assert D.natural_root_dose(treatment, null) == {
        "shared_prefix_plays": 84,
        "root_action_changed": False,
        "change_play_index": None,
        "change_phase": None,
        "change_role": None,
    }


def test_engine_produced_short_round_proves_physical_completeness():
    bots = [make_bot("smart", seed=seat) for seat in range(4)]
    log = play_round(Game(random.Random(0)), bots, record=True)
    history = D._normalise_history(log.history)
    assert len(history) == 68
    assert D.history_problems(history) == []
    assert sum(len(row["cards"]) for row in history) == 100
    assert Counter(
        {seat: sum(len(row["cards"]) for row in history
                   if row["seat"] == seat) for seat in range(4)}) == Counter(
                       {seat: 25 for seat in range(4)})


def test_complete_round_contract_refuses_impossible_deck_and_seat_counts():
    impossible = _history(plays=84)
    for row in impossible:
        row["cards"] = ["C3"] * len(row["cards"])
    assert D.history_problems(impossible) == [
        "record physical deck completeness"]

    wrong_seat = _history(plays=84)
    wrong_seat[0]["seat"] = 1
    assert "record seat card completeness" in D.history_problems(wrong_seat)
    assert "record play order" in D.history_problems(wrong_seat)


def test_complete_round_contract_refuses_unequal_trick_width():
    history = _history(plays=84)
    history[0]["cards"].pop()
    problems = D.history_problems(history)
    assert "record trick width" in problems
    assert "record seat card completeness" in problems
    assert "record physical deck completeness" in problems


def test_incomplete_equal_prefix_with_different_lengths_refuses():
    treatment = _row("treatment", 7, 0)
    null = _row("matched_null", 7, 0)
    treatment["history"] = _history(plays=84)
    null["history"] = deepcopy(treatment["history"][:-4])
    with pytest.raises(D.PairProtocolRefused, match="history population"):
        D.natural_root_dose(treatment, null)


@pytest.mark.parametrize("plays", [0, 3, 5, 104])
def test_malformed_complete_round_history_lengths_refuse(plays):
    row = _row("treatment", 7, 0)
    if plays <= 5:
        row["history"] = _history()[:plays]
    else:
        row["history"] = _history() + _history()[:4]
    assert "record play history" in D.record_problems(
        row, expected_label="treatment", expected_seed=7,
        expected_flip=0, expected_run_id=C.PREFLIGHT_RUN_ID)


def test_natural_dose_refuses_opponent_first_divergence():
    treatment = _row("treatment", 7, 0)
    null = _row("matched_null", 7, 0)
    treatment["history"] = _history(changed_at=9)
    with pytest.raises(D.PairProtocolRefused, match="treatment-team"):
        D.natural_root_dose(treatment, null)


def test_matched_null_must_replay_champion_exactly():
    null = _row("matched_null", 7, 0)
    champion = _row("champion", 7, 0)
    assert D.matched_null_champion_problems(null, champion) == []
    champion["history"] = _history(changed_at=4)
    assert D.matched_null_champion_problems(null, champion)


def test_score_free_guard_rejects_nested_results_and_actions():
    safe = {"score_free": True, "outcomes_published": False,
            "natural_dose": {"root_action_changes": 3}}
    assert C.score_free_result_problems(safe) == []
    for key in ("winner_team", "history", "action", "records"):
        bad = deepcopy(safe)
        bad["nested"] = {key: 0}
        assert C.score_free_result_problems(bad)


def test_measurement_discards_outcomes_and_projects_both_sizes(monkeypatch):
    def play(label, seed, *, run_id):
        assert run_id == C.PREFLIGHT_RUN_ID
        return [
            _row(label, seed, flip,
                 changed=(label == "treatment" and flip == 0))
            for flip in (0, 1)
        ]

    monkeypatch.setattr(C.CORE, "play_arm_cluster", play)
    monkeypatch.setattr(C.CORE, "record_problems", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(C.CORE, "counter_problems", lambda *_args, **_kwargs: [])
    ticks = iter((10.0, 22.0))
    result = C.measure_preflight(
        {"git": "a" * 40, "internal_sha256": "b" * 64},
        clock=lambda: next(ticks))
    assert result["records_discarded"] == 24
    assert result["natural_dose"]["root_action_changes"] == 4
    assert result["natural_dose"]["changes_by_role"] == {
        "attacker": 4, "defender": 0}
    assert set(result["projection"]["candidates"]) == {"2048", "8192"}
    assert result["capacity_pass"] is True
    assert result["screen_packet_design_authorized"] is False
    assert C.score_free_result_problems(result) == []


def test_measurement_holds_when_no_natural_root_action_changes(monkeypatch):
    def play(label, seed, *, run_id):
        return [_row(label, seed, flip) for flip in (0, 1)]

    monkeypatch.setattr(C.CORE, "play_arm_cluster", play)
    monkeypatch.setattr(C.CORE, "record_problems", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(C.CORE, "counter_problems", lambda *_args, **_kwargs: [])
    ticks = iter((10.0, 22.0))
    result = C.measure_preflight(
        {"git": "a" * 40, "internal_sha256": "b" * 64},
        clock=lambda: next(ticks))
    assert result["natural_dose"]["root_action_changes"] == 0
    assert result["capacity_pass"] is False


def test_packet_review_authorizes_only_one_score_free_preflight():
    claim = C.packet_review_claim(
        expected_git="a" * 40, packet_sha256="b" * 64)
    assert claim["one_score_free_preflight_authorized"] is True
    assert claim["screen_execution_authorized"] is False
    assert claim["strength_claim"] is False


def test_cli_refuses_missing_packet_review_before_gameplay(tmp_path, monkeypatch):
    called = False

    def gameplay(_packet):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(C, "require_clean_exact_git", lambda _git: None)
    monkeypatch.setattr(C, "require_exact_output_path",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(C, "require_compiled_strict_runtime", lambda: None)
    monkeypatch.setattr(C, "load_packet", lambda *_args, **_kwargs: {
        "git": "a" * 40, "internal_sha256": "b" * 64})
    monkeypatch.setattr(C, "measure_preflight", gameplay)
    args = SimpleNamespace(
        expected_git="a" * 40,
        exact_review_record="exact.md", dose_review_record="dose.md",
        packet="packet.json", expected_packet_sha256="b" * 64,
        packet_review_record=tmp_path / "missing.md",
        admission=tmp_path / "admission.json", out=tmp_path / "result.json")
    with pytest.raises(C.CapacityRefused, match="review.*missing"):
        C.preflight_command(args)
    assert called is False
    assert not args.admission.exists()


def test_preflight_binds_singleton_slot_before_opening_packet(
        tmp_path, monkeypatch):
    opened = False

    def load(*_args, **_kwargs):
        nonlocal opened
        opened = True
        return {}

    monkeypatch.setattr(C, "require_clean_exact_git", lambda _git: None)
    monkeypatch.setattr(C, "load_packet", load)
    args = SimpleNamespace(
        expected_git="a" * 40,
        exact_review_record="exact.md", dose_review_record="dose.md",
        packet="packet.json", expected_packet_sha256="b" * 64,
        packet_review_record="review.md",
        admission=tmp_path / "alternate.json", out=C.RESULT_PATH)
    with pytest.raises(C.CapacityRefused, match="singleton path"):
        C.preflight_command(args)
    assert opened is False


def test_withdrawn_v1_packet_is_preserved_and_grants_no_gameplay():
    # This packet was frozen before the variable-length complete-round bug was
    # found.  Preserve its bytes for audit, but v2 constants make it impossible
    # for the active controller to consume or review it.
    raw = WITHDRAWN_V1_PACKET.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "2fc732fd3745134d452b6a2a3c5b3d1fde4836ef044e12629d604b16c0f25610")
    packet = json.loads(raw)
    internal = packet.pop("internal_sha256")
    assert C.stable_digest(packet) == internal == (
        "61875c15d081342444377c9049f4779e292265cb8922f8b1494a77ad956d9aab")
    assert packet["git"] == "54ec8185b16ab82cacb5f0393a8c194fdef60c86"
    assert packet["runtime"] == _air_runtime()
    assert packet["preflight"]["clusters"] == 4
    assert packet["successor_projection"]["candidate_clusters"] == [2048, 8192]
    assert all(value is False for value in packet["authority"].values())
    assert packet["schema"] != C.PACKET_SCHEMA
    assert packet["preflight_run_id"] != C.PREFLIGHT_RUN_ID


def test_withdrawn_v2_air_packet_is_hash_pinned_and_grants_no_gameplay():
    raw = FROZEN_V2_PACKET.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "ba0bb693642c6fcb41357558f96e6b9d8707b810fa8926c97ec01d223abaa0b6")
    packet = json.loads(raw)
    internal = packet.pop("internal_sha256")
    assert C.stable_digest(packet) == internal == (
        "80e8ff89fd6d1c194670d1770422cabf63929278f2dce9b280fab63666056c99")
    assert packet["git"] == "2321790ee7a56106d2d4ded70f34531bd163d913"
    assert packet["schema"] != C.PACKET_SCHEMA
    assert packet["preflight_run_id"] != C.PREFLIGHT_RUN_ID
    assert packet["runtime"] == _air_runtime()
    assert packet["preflight"]["clusters"] == 4
    assert packet["successor_projection"]["candidate_clusters"] == [2048, 8192]
    assert all(value is False for value in packet["authority"].values())

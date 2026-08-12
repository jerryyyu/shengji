"""Contracts for the Mini-only selective-S6 preflight profile."""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import s6_throw_full_hand_preflight_controller as AIR  # noqa: E402
import s6_throw_full_hand_preflight_mini as MINI  # noqa: E402


def _selector_review(tmp_path: Path) -> Path:
    marker = MINI.SELECTOR_REVIEW_PREFIX + json.dumps(
        MINI.EXPECTED_SELECTOR_REVIEW,
        sort_keys=True, separators=(",", ":"))
    path = tmp_path / "review.md"
    path.write_text(marker + "\n", encoding="utf-8")
    return path


def test_profile_does_not_mutate_air_controller():
    assert AIR.RUN_ID == "s6-throw-full-hand-screen-437b-v2"
    assert AIR.PREFLIGHT_RUN_ID == "s6-throw-full-hand-preflight-436b-v2"
    assert AIR.EXPECTED_EXECUTION_HOST == "Jerrys-MacBook-Air.local"
    assert MINI.RUN_ID == "s6-throw-full-hand-screen-437b-mini-v1"
    assert MINI.PREFLIGHT_RUN_ID == "s6-throw-full-hand-preflight-436b-mini-v1"


def test_runtime_contract_is_exact_mini():
    exact = {
        "host": MINI.EXPECTED_EXECUTION_HOST,
        "python": MINI.EXPECTED_PYTHON_VERSION,
        "implementation": "CPython",
        "python_executable": MINI.EXPECTED_PYTHON_EXECUTABLE,
        "fast_required": True,
        "strict_voids_required": True,
        "fast_env_active": True,
        "strict_voids_active": True,
        "compiled_binding_active": True,
        "fast_binary_sha256": MINI.EXPECTED_FAST_BINARY_SHA256,
    }
    assert MINI.runtime_problems(exact) == []
    exact["host"] = AIR.EXPECTED_EXECUTION_HOST
    assert MINI.runtime_problems(exact) == [
        "runtime is not exact reviewed Mini"]


def test_sources_bind_profile_and_reused_controller():
    paths = MINI.source_paths()
    assert paths["controller"] == Path(MINI.__file__).resolve()
    assert paths["base_full_hand_controller"] == Path(AIR.__file__).resolve()
    assert paths["controller"] != paths["base_full_hand_controller"]


def test_packet_keeps_science_and_supersedes_air(tmp_path, monkeypatch):
    review = _selector_review(tmp_path)
    monkeypatch.setattr(MINI._CTRL, "git_is_ancestor", lambda *_: True)
    monkeypatch.setattr(MINI._CTRL, "require_air_runtime", lambda: {
        "host": MINI.EXPECTED_EXECUTION_HOST})
    monkeypatch.setattr(MINI._CTRL, "source_sha256s", lambda: {
        "controller": "c", "base_full_hand_controller": "b"})
    monkeypatch.setattr(
        MINI._CTRL, "freeze_admission_evidence", lambda **_: {
            "path": "freeze.json", "sha256": "f",
            "internal_sha256": "i", "consumed": True})
    packet = MINI.packet_payload(
        expected_git="a" * 40, selector_review_record=review)
    assert packet["preflight"]["seed0"] == AIR.PREFLIGHT_SEED0
    assert packet["proposed_screen"]["seed0"] == AIR.SCREEN_SEED0
    assert packet["proposed_screen"]["clusters"] == AIR.SCREEN_CLUSTERS
    assert packet["capacity"] == {
        "safety_factor": AIR.SAFETY_FACTOR,
        "screen_fleet_hour_cap": AIR.SCREEN_FLEET_HOUR_CAP,
        "screen_max_shard_hour_cap": AIR.SCREEN_MAX_SHARD_HOUR_CAP,
    }
    assert packet["execution_profile"] == {
        "profile": "mini-alternative-v1",
        "scientific_design_changed": False,
        "same_preflight_and_screen_seeds": True,
        "same_work_and_capacity_caps": True,
        "air_packet_must_not_execute_after_mini_pass": True,
    }
    assert packet["supersedes_air_packet"] == MINI.AIR_PACKET
    assert MINI.packet_problems(
        packet, expected_git="a" * 40,
        selector_review_record=review) == []
    changed = deepcopy(packet)
    changed["supersedes_air_packet"][
        "execution_superseded_by_mini_review"] = False
    changed["internal_sha256"] = MINI.stable_digest({
        key: value for key, value in changed.items()
        if key != "internal_sha256"})
    assert MINI.packet_problems(
        changed, expected_git="a" * 40,
        selector_review_record=review) == [
            "packet differs from reconstruction"]
    internal = packet.pop("internal_sha256")
    assert MINI.stable_digest(packet) == internal


def test_packet_review_claim_revokes_air_execution():
    claim = MINI.packet_review_claim(
        expected_git="a" * 40, packet_sha256="b" * 64)
    assert claim["one_score_free_preflight_authorized"] is True
    assert claim["air_preflight_execution_authorized"] is False
    assert claim["supersedes_air_packet_sha256"] == \
        MINI.AIR_PACKET["packet_sha256"]
    assert claim["screen_execution_authorized"] is False
    assert claim["production_deployment"] is False

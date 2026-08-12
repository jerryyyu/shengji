"""Tests for the S6 point-vs-level report objective diagnostic."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import s6_throw_level_objective_audit as AUDIT  # noqa: E402


RESULT = Path(__file__).with_name("data") / (
    "s6_throw_level_objective_audit.v1.json")
RESULT_SHA256 = (
    "f6478baca6d6bf5fb45eb96774d012c001f1c20d0ed99a95074ddd76aa186329")
RESULT_INTERNAL_SHA256 = (
    "6bda5794a2a146ad0069fdd7039a67fc95ebeed3d58314332ec4a49f03a377b6")


def test_level_score_matches_registered_mcbot_objective():
    class Bot:
        LEVEL_OBJECTIVE = False

        def _score(self, points):
            if not self.LEVEL_OBJECTIVE:
                return float(points)
            if points >= 80:
                bracket, deal = min(3, int(points - 80) // 40), 0.5
            elif points == 0:
                bracket, deal = -3, -0.5
            else:
                bracket, deal = -(1 + int(79 - points) // 40), -0.5
            return 40.0 * (bracket + deal) + 0.2 * points

    bot = Bot()
    assert AUDIT._level_score(bot, 79) == -44.2
    assert AUDIT._level_score(bot, 80) == 36.0
    assert AUDIT._level_score(bot, 120) == 84.0
    assert bot.LEVEL_OBJECTIVE is False


def test_signed_delta_flips_for_defender():
    class Round:
        @staticmethod
        def is_attacker(seat):
            return seat == 1

    assert AUDIT._signed_delta(Round(), 1, 10, 4) == 6
    assert AUDIT._signed_delta(Round(), 0, 10, 4) == -6


def test_population_is_exactly_all_frozen_overrides():
    assert len(AUDIT.REPLAY.OVERRIDE_WITNESSES) == 12
    assert len(set(AUDIT.REPLAY.OVERRIDE_WITNESSES)) == 12


def test_frozen_result_closes_level_objective_successor():
    assert hashlib.sha256(RESULT.read_bytes()).hexdigest() == RESULT_SHA256
    payload = json.loads(RESULT.read_bytes())
    assert payload["schema"] == AUDIT.SCHEMA
    assert payload["git"] == (
        "aa0fa54c52a30711972da7e17fd9544724e06bb0")
    assert payload["internal_sha256"] == RESULT_INTERNAL_SHA256
    unsigned = dict(payload)
    del unsigned["internal_sha256"]
    assert AUDIT.RELIABILITY.PILOT.stable_digest(unsigned) == (
        RESULT_INTERNAL_SHA256)
    assert payload["summary"] == {
        "witnesses": 12,
        "point_objective_retained": 12,
        "level_objective_retained": 5,
        "objectives_disagree": 7,
        "level_retained_positive_utility": 0,
        "level_retained_neutral_utility": 4,
        "level_retained_negative_utility": 1,
        "observed_loss_retained": True,
    }
    assert payload["exploration_only"] is True
    assert payload["confirmatory_claim"] is False
    assert payload["whole_game_execution_authorized"] is False
    assert payload["strength_claim"] is False
    assert payload["production_deployment"] is False

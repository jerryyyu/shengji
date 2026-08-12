"""Tests for the S6 point-vs-level report objective diagnostic."""
from __future__ import annotations

import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import s6_throw_level_objective_audit as AUDIT  # noqa: E402


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

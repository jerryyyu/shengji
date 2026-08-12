"""Score-free contracts for the S6 full-hand natural-traffic census."""
from __future__ import annotations

import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import s6_throw_full_hand_prevalence as S  # noqa: E402


def test_design_is_fresh_and_score_free():
    assert S.SEED0 == 434_000_000
    assert S.DEALS == 50_000
    assert S.PHASES == ("early", "mid", "late")
    assert S.ROLES == ("attacker", "defender")


def test_phase_bands_cover_complete_round():
    assert S.phase_band(0) == "early"
    assert S.phase_band(7) == "early"
    assert S.phase_band(8) == "mid"
    assert S.phase_band(16) == "mid"
    assert S.phase_band(17) == "late"
    assert S.phase_band(24) == "late"


def test_named_full_hand_state_is_counted_but_no_action_is_selected():
    rnd, actors = S.BASE._start_round(432_000_152)
    while rnd.phase == "play":
        seat = rnd.turn
        if len(rnd.history) == 15 and seat == 3 and not rnd.trick.plays:
            additions = S.full_hand_additions(rnd, seat)
            assert [row["cards"] for row in additions] == [
                ["H5", "H8", "HK", "HQ"],
            ]
            assert all(len(row["cards"]) == len(rnd.hands[seat])
                       for row in additions)
            return
        rnd.play(seat, actors[seat].decide_play(rnd, seat))
    raise AssertionError("named full-hand state disappeared")


def test_tiny_census_publishes_counts_not_outcomes():
    payload = S.run_census(seed0=S.SEED0, deals=2)
    assert payload["counts"]["deals"] == 2
    assert payload["counts"]["leads"] > 0
    assert set(payload["counts"]["cells"]) == {
        f"{role}:{phase}" for role in S.ROLES for phase in S.PHASES
    }
    assert payload["score_free"] is True
    assert payload["outcomes_published"] is False
    assert payload["whole_game_execution_authorized"] is False
    assert payload["strength_claim"] is False

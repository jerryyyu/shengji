"""Score-free contracts for the S6 full-hand natural-traffic census."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import s6_throw_full_hand_prevalence as S  # noqa: E402


ASSET = Path(__file__).with_name("data") / \
    "s6_throw_full_hand_prevalence.v1.json"
ASSET_SHA256 = (
    "8934c2e39b68afca8a5d8dfc13f4768097c7a61f66627f8f469e1c48b17ea45a")


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


def test_fresh_air_census_is_pinned_score_free_and_complete():
    raw = ASSET.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ASSET_SHA256
    payload = json.loads(raw)
    assert payload["git"] == \
        "9c7e6c845ada0c246e1949e99f3e83f8d1ff0e3d"
    internal = payload.pop("internal_sha256")
    assert internal == \
        "43dc2e62d30ff671308ddba87f4f7dc0cdb45443b3888089b8feb5ecc2115a3d"
    assert S.stable_digest(payload) == internal
    payload["internal_sha256"] = internal

    assert payload["tree_dirty"] is False
    assert payload["counts"] == {
        "by_hand_cards": {
            "2": 597, "3": 308, "4": 126, "5": 39, "6": 14, "7": 1,
        },
        "cells": {
            "attacker:early": 0, "attacker:mid": 222,
            "attacker:late": 399, "defender:early": 0,
            "defender:mid": 136, "defender:late": 328,
        },
        "deals": 50_000,
        "leads": 1_067_189,
        "new_candidates": 1_085,
        "triggered_deals": 1_011,
        "triggered_leads": 1_085,
    }
    assert payload["rates"]["triggered_deals"] == 1_011 / 50_000
    assert payload["score_free"] is True
    assert payload["outcomes_published"] is False
    assert payload["whole_game_execution_authorized"] is False
    assert payload["strength_claim"] is False
    assert payload["production_deployment"] is False

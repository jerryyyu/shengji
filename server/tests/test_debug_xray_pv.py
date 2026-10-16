"""The X-ray overlay on the pv-search decision record and the declaration.

The served bot writes ``pv-search-decision-v1`` (admitted candidates, value
means, policy log-odds and one bounded block per optional rule), not the
shortlist record the overlay first read.  These tests pin the browser view of
that record, the declare view, and -- on the hash-pinned production package
under the served recipe -- that the overlay explains a live play and a live
declaration rather than reporting ``forced_or_no_search``.
"""
from __future__ import annotations

import asyncio
import json
import random
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.smart import SmartBot
from shengji.api import debug
from shengji.api.debug_play import MAX_CANDIDATES, PV_FALLBACK_SCHEMA, PV_SCHEMA, play_analysis
from shengji.engine.game import Game
from test_encoder_round_compat import pinned_production_package, PACKAGE_SHA  # noqa: F401


def _pv_record(**extra):
    return {
        "schema": PV_SCHEMA, "policy": "pv-search-test",
        "worlds": 8, "sample_attempts": 9, "actions": 11, "cap": 256,
        "legal_count": 11, "legal_complete": True,
        "admitted_indices": [3, 0, 7], "value_means": [0.10, 0.35, -0.2],
        "admitted": [["SA"], ["SK"], ["S5", "S5"]],
        "policy_log_odds_admitted": [-0.5, -0.1, -2.0],
        "policy_log_odds_listing": [float(i) for i in range(11)],
        "selected_index": 0, "value_batches": 1, "value_evaluations": 24,
        "anchor_selected": False, "encoder_version": 6,
        "played": ["SK"], "seconds": 0.25, "work_complete": True,
        "refusal_observations": 2, "refusal_rejections": 1,
        "refusal_fallback_worlds": 0, "refusal_pinned_codes": 3,
        "tiebreak_applied": False, "tiebreak_near_set": [0, 1], "tiebreak_points": [5, -10],
        "lead_anchor_applied": False, "lead_anchor_from": "SA", "lead_anchor_to": "SA",
        "lead_anchor_source": "heuristic",
        "doomed_throw_reselect_applied": False, "doomed_throw_reselect_from": "SK",
        "doomed_throw_reselect_to": "SK", "doomed_throw_reselect_doomed_candidates": [],
        "exact_lead_status": "complete", "exact_lead_changed": True,
        "exact_lead_worlds_completed": 8, "exact_lead_nodes": 1234,
        "exact_lead_base_value_means": [0.1, 0.2, 0.3],
        "exact_lead_sampled_worlds": [[["SA"], ["SK"]]],
        "exact_follow_attempted": True, "exact_follow_applied": False,
        "exact_follow_scores": [1.0, 2.0, 3.0],
        "rejected_worlds_delta": 8, "impossible_worlds_delta": 1,
        "accepted_worlds_delta": 7,
        # unlisted fields whose shapes would pass the scalar bound: never shown
        "exact_follow_hidden_hand": ["SA", "SK"],
        "refusal_rng_state": [1, 2, 3],
        "exact_lead_error_message": "/private/sensitive/location",
        "exact_lead_abandon_error": "Traceback: /private/sensitive/trace",
        **extra,
    }


def _bot(record, **attrs):
    return SimpleNamespace(policy_name="pv-search-test", last_decision_record=record,
                           serving_budget_seconds=3.0, **attrs)


def test_pv_record_rows_carry_values_log_odds_and_the_selected_candidate():
    rows, info = play_analysis(_bot(_pv_record()), ["SK"], is_attacker=True, elapsed=0.3)
    assert info["schema"] == PV_SCHEMA and info["reason"] == "pv_search"
    assert [r["play"] for r in rows] == [["SA"], ["SK"], ["S5", "S5"]]
    assert [r["acting_team_levels"] for r in rows] == [0.10, 0.35, -0.2]
    assert [r["model_score"] for r in rows] == [0.10, 0.35, -0.2]
    assert [r["policy_log_odds"] for r in rows] == [-0.5, -0.1, -2.0]
    assert [r["selected"] for r in rows] == [False, True, False]
    assert [r["bot_plays"] for r in rows] == [False, True, False]
    assert rows[0]["anchor"] and rows[0]["heuristic_pick"] and not rows[1]["anchor"]
    assert all(r["selection_worlds"] == 8 for r in rows)
    assert all(r["attackers_avg"] is None and r["se"] is None for r in rows)
    assert info["selected_index"] == 1 and info["anchor_selected"] is False
    assert info["model_score_units"] == "expected signed levels for acting team"
    assert info["recipe"] == {"worlds": 8, "alternatives": 3, "cap": 256,
                              "serving_budget_seconds": 3.0, "encoder_version": 6}
    assert info["search_seconds"] == 0.25 and info["evaluation_seconds"] == 0.3
    assert info["candidate_count"] == 3 and info["candidates_truncated"] is False
    assert info["work"] == {"value_evaluations": 24, "value_batches": 1, "worlds": 8}
    assert info["sampling"] == {"worlds": 8, "sample_attempts": 9,
                                "rejected_worlds_delta": 8, "impossible_worlds_delta": 1}
    assert info["admission"]["legal_count"] == 11 and info["admission"]["admitted"] == 3


def test_pv_record_stages_are_bounded_blocks_and_applied_rules_are_named():
    rows, info = play_analysis(_bot(_pv_record()), ["SK"], is_attacker=True, elapsed=0.3)
    stages = info["stages"]
    assert set(stages) == {"tiebreak", "lead_anchor", "doomed_throw_reselect",
                           "exact_lead", "exact_follow", "refusal"}
    assert stages["exact_lead"]["exact_lead_status"] == "complete"
    assert stages["exact_lead"]["exact_lead_base_value_means"] == [0.1, 0.2, 0.3]
    # a nested value (a world) never reaches the browser; the legal listing neither
    assert "exact_lead_sampled_worlds" not in stages["exact_lead"]
    text = json.dumps({"rows": rows, "info": info})
    assert "policy_log_odds_listing" not in text and "sampled_worlds" not in text
    # an unlisted field is dropped even when it is a flat list or a short string:
    # a hidden hand, an RNG state, an exception text, an unknown sampler counter
    for decoy in ("exact_follow_hidden_hand", "refusal_rng_state", "exact_lead_error_message",
                  "exact_lead_abandon_error", "accepted_worlds_delta", "SA\", \"SK",
                  "/private/sensitive", "[1, 2, 3]"):
        assert decoy not in text, decoy
    assert set(stages["exact_follow"]) == {"exact_follow_attempted", "exact_follow_applied",
                                           "exact_follow_scores"}
    assert stages["refusal"] == {"refusal_observations": 2, "refusal_rejections": 1,
                                 "refusal_fallback_worlds": 0, "refusal_pinned_codes": 3}
    assert info["applied_rules"] == ["exact_lead_changed"]


def test_pv_record_forced_component_play_gets_its_own_row():
    record = _pv_record(played=["S5"], selected_index=7,
                        doomed_throw_reselect_applied=True,
                        doomed_throw_reselect_fallback_forced=True)
    rows, info = play_analysis(_bot(record), ["S5"], is_attacker=False, elapsed=0.1)
    assert [r["selected"] for r in rows] == [False, False, True, False]
    assert rows[-1] == {**rows[-1], "index": None, "play": ["S5"], "bot_plays": True,
                        "forced_component": True, "acting_team_levels": None}
    assert sum(r["bot_plays"] for r in rows) == 1
    assert info["applied_rules"] == ["doomed_throw_reselect_applied", "exact_lead_changed"]


def test_pv_record_lead_anchor_replacement_is_not_the_heuristic_pick():
    record = _pv_record(lead_anchor_applied=True, lead_anchor_source="pair")
    rows, _ = play_analysis(_bot(record), ["SK"], is_attacker=True, elapsed=0.1)
    assert rows[0]["anchor"] is True and rows[0]["heuristic_pick"] is False


def test_pv_record_truncates_a_wide_ballot_without_losing_the_count():
    admitted = [[f"S{i}"] for i in range(2, 2 + MAX_CANDIDATES + 4)]
    record = _pv_record(admitted=admitted, value_means=[0.0] * len(admitted),
                        policy_log_odds_admitted=[0.0] * len(admitted),
                        admitted_indices=list(range(len(admitted))), selected_index=0,
                        played=["S2"])
    rows, info = play_analysis(_bot(record), ["S2"], is_attacker=True, elapsed=0.1)
    assert len(rows) == MAX_CANDIDATES
    assert info["candidate_count"] == MAX_CANDIDATES + 4 and info["candidates_truncated"]


def test_pv_fallback_record_names_its_reason_and_plays_the_anchor():
    record = {"schema": PV_FALLBACK_SCHEMA, "policy": "pv-search-test",
              "action": ["SA"], "played": ["SA"], "reason": "budget",
              "error_class": "PVSearchBudgetExceeded", "error_stage": None,
              "error_message": "/private/secret never shown", "budget_seconds": 3.0,
              "elapsed_seconds": 3.01, "work_complete": False}
    rows, info = play_analysis(_bot(record), ["SA"], is_attacker=True, elapsed=3.1)
    assert info["schema"] == PV_FALLBACK_SCHEMA and info["reason"] == "budget"
    assert info["fallback"] == {"error_class": "PVSearchBudgetExceeded", "error_stage": "",
                                "budget_seconds": 3.0}
    assert info["search_seconds"] == 3.01 and info["work_complete"] is False
    assert rows == [{**rows[0], "play": ["SA"], "bot_plays": True, "heuristic_pick": True}]
    assert "/private/secret" not in json.dumps(info)


def test_shortlist_and_forced_records_keep_their_view():
    bot = SimpleNamespace(last_eval=None, last_decision_record=None)
    rows, info = play_analysis(bot, ["SA"], is_attacker=True, elapsed=.1)
    assert info["reason"] == "forced_or_no_search" and "schema" not in info
    assert rows[0]["bot_plays"] and rows[0]["model_score"] is None


# ---------------------------------------------------------------- declare view

def _dealt_round(seed: int = 73):
    game = Game(random.Random(seed))
    rnd = game.start_round()
    while rnd.phase == "deal":
        rnd.deal_next()
    assert rnd.phase == "declare" and rnd.ordering is None
    return rnd


def _seat_with_options(rnd):
    return next(s for s in range(4) if rnd.declare_options(s))


class _ValueDeclareBot(HeuristicBot):
    policy_name = "value-declare-test"

    def __init__(self):
        super().__init__()
        self.last_declare_record = None

    def decide_declare(self, rnd, seat, final=False):
        heuristic = super().decide_declare(rnd, seat, final)
        options = rnd.declare_options(seat)
        self.last_declare_record = {
            "schema": "pv-value-declare-decision-v1", "policy": self.policy_name,
            "seat": seat, "final": final, "cards_dealt": sum(len(h) for h in rnd.hands),
            "evaluated": True, "heuristic": "PASS" if heuristic is None else " ".join(heuristic),
            "value_choice": " ".join(options[0]), "played": " ".join(options[0]),
            "changed": heuristic != options[0], "worlds": 4, "worlds_completed": 4,
            "fallback_reason": None, "fallback_error": None,
            "outcomes": "0:S=PASS | 0:H=" + " ".join(options[0]),
            "outcome_means": [0.1, 0.4], "heuristic_mean": 0.1, "best_mean": 0.4,
            "margin": 0.0, "seconds": 0.02, "gate": "final",
            "leaf_first_trick": "heuristic", "leaf_first_trick_fallbacks": 0,
            "sampled_deals": [[["SA"]]],
        }
        return list(options[0])


def test_declare_view_reports_the_heuristic_choice_without_a_record():
    rnd = _dealt_round()
    seat = _seat_with_options(rnd)
    bot = SmartBot()
    out = debug._declare_view(rnd, seat, bot)
    assert out["phase"] == "declare" and out["candidates"] is None and out["analysis"] is None
    assert out["hand"] == sorted(rnd.hands[seat]) and out["voids"] == {}
    view = out["declare"]
    assert view["final"] is True and view["cards_dealt"] == sum(len(h) for h in rnd.hands)
    assert view["options"] == [list(o) for o in rnd.declare_options(seat)]
    expected = bot.decide_declare(rnd, seat, final=True)
    assert view["chosen"] == (None if expected is None else list(expected))
    assert view["record"] is None and view["current"] is None
    assert rnd.declaration is None   # the view never declares


def test_declare_view_allowlists_the_value_declare_record():
    rnd = _dealt_round()
    seat = _seat_with_options(rnd)
    out = debug._declare_view(rnd, seat, _ValueDeclareBot())
    view = out["declare"]
    assert view["policy"] == "value-declare-test"
    assert view["chosen"] == list(rnd.declare_options(seat)[0])
    record = view["record"]
    assert record["schema"] == "pv-value-declare-decision-v1"
    assert record["gate"] == "final" and record["evaluated"] is True
    assert record["outcome_means"] == [0.1, 0.4] and record["best_mean"] == 0.4
    assert record["played"] == view["record"]["value_choice"]
    assert "sampled_deals" not in json.dumps(out) and "seat" not in record


def test_declare_view_during_the_deal_is_not_final_and_shows_the_current_declaration():
    game = Game(random.Random(73))
    rnd = game.start_round()
    for _ in range(40):
        rnd.deal_next()
    assert rnd.phase == "deal"
    seat = next((s for s in range(4) if rnd.declare_options(s)), None)
    if seat is None:
        pytest.skip("no declare option after 40 cards on this seed")
    rnd.declare(seat, rnd.declare_options(seat)[0])
    other = (seat + 1) % 4
    out = debug._declare_view(rnd, other, SmartBot())
    assert out["declare"]["final"] is False and out["declare"]["phase"] == "deal"
    assert out["declare"]["current"]["seat"] == seat


def test_xray_room_routes_the_declaration_phases_to_the_declare_view():
    rnd = _dealt_round()
    seat = _seat_with_options(rnd)
    room = SimpleNamespace(lock=asyncio.Lock(), round=rnd, bot=SmartBot())
    out = asyncio.run(debug._xray_room(room, seat, SmartBot()))
    assert "error" not in out and out["declare"]["final"] is True
    room.round = None
    assert asyncio.run(debug._xray_room(room, seat, SmartBot())) == {"error": "no active round"}


# ---------------------------------------------- the production package, served recipe

def _served_entries(path):
    from shengji.train import pv_search_policy as pv

    env = tomllib.loads((Path(__file__).parents[2] / "fly.toml").read_text())["env"]
    recipe = pv.pv_env_recipe({**env, "SHENGJI_PV_CKPT": str(path),
                              "SHENGJI_PV_SHA256": PACKAGE_SHA})
    entries = pv.pv_registry_entries(**recipe)
    name, = entries
    assert name == env["SHENGJI_BOT"]
    return name, entries[name]


def _play_state(seed: int = 73):
    rnd = _dealt_round(seed)
    smart = SmartBot()
    for seat in range(4):
        declaration = smart.decide_declare(rnd, seat, final=True)
        if declaration:
            rnd.declare(seat, declaration)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, smart.decide_bury(rnd, rnd.banker))
    assert rnd.phase == "play" and rnd.turn == rnd.banker
    return rnd


def test_production_overlay_explains_a_served_play_decision(pinned_production_package):
    """The overlay on the served recipe: every admitted candidate carries the
    value head's level, the chosen row is marked, the model identity is the
    package's.  Fails, never skips, under SHENGJI_REQUIRE_PV_PACKAGE=1."""
    name, factory = _served_entries(pinned_production_package)
    bot = factory(seed=17)
    rnd = _play_state()
    out = debug._xray(rnd, rnd.turn, bot)
    info = out["analysis"]
    assert info["schema"] == PV_SCHEMA and info["reason"] == "pv_search"
    assert info["policy"] == name
    assert info["model"]["checkpoint_sha256"] == PACKAGE_SHA
    assert info["model"]["encoder_version"] == out["ml"]["inputs"]["encoder_version"]
    assert info["recipe"]["worlds"] == 64 and info["recipe"]["serving_budget_seconds"] == 3.0
    rows = out["candidates"]
    assert 2 <= len(rows) <= 8 + 2
    assert all(isinstance(r["acting_team_levels"], float) for r in rows if r["index"] is not None)
    assert all(isinstance(r["policy_log_odds"], float) for r in rows if r["index"] is not None)
    assert sum(r["bot_plays"] for r in rows) == 1
    assert sum(r["selected"] for r in rows) == 1
    assert rows[0]["anchor"] is True
    # the served rules leave their blocks: the refusal sampler on every decision
    assert "refusal" in info["stages"]
    assert info["work"]["value_evaluations"] >= len(rows) - 1
    assert info["search_seconds"] > 0 and info["work_complete"] is True


def test_production_overlay_explains_a_served_declaration(pinned_production_package):
    """The value declaration (release 44+) in the grace window: the record's
    outcomes and means reach the view, the chosen cards are the record's."""
    _, factory = _served_entries(pinned_production_package)
    bot = factory(seed=17)
    assert bot.value_declare is True
    rnd = _dealt_round()
    seat = _seat_with_options(rnd)
    out = debug._declare_view(rnd, seat, bot)
    view = out["declare"]
    record = view["record"]
    assert record is not None and record["schema"] == "pv-value-declare-decision-v1"
    assert record["gate"] == "final" and record["evaluated"] is True
    assert record["worlds_completed"] == record["worlds"] == 64
    assert len(record["outcome_means"]) >= 2
    assert all(isinstance(m, float) for m in record["outcome_means"])
    played = None if record["played"] == "PASS" else record["played"].split(" ")
    assert view["chosen"] == played
    assert rnd.declaration is None


def test_production_overlay_keeps_the_panel_fixtures_shape(pinned_production_package):
    """The panel's captured responses (`web/src/components/xray-*.fixture.json`)
    name the fields the served producer writes today; a renamed or dropped
    field fails here before the browser shows 'unavailable'."""
    components = Path(__file__).resolve().parents[2] / "web" / "src" / "components"
    play = json.loads((components / "xray-pv-search.fixture.json").read_text())
    declare = json.loads((components / "xray-declare.fixture.json").read_text())
    _, factory = _served_entries(pinned_production_package)
    bot = factory(seed=17)
    rnd = _play_state()
    out = debug._xray(rnd, rnd.turn, bot)
    assert set(out) == set(play)
    assert set(out["analysis"]) == set(play["analysis"])
    assert set(out["analysis"]["recipe"]) == set(play["analysis"]["recipe"])
    assert set(out["analysis"]["work"]) == set(play["analysis"]["work"])
    assert set(out["candidates"][0]) == set(play["candidates"][0])
    assert set(play["analysis"]["stages"]) <= set(out["analysis"]["stages"]) | {"tiebreak"}
    rnd = _dealt_round()
    view = debug._declare_view(rnd, _seat_with_options(rnd), bot)
    assert set(view) == set(declare)
    assert set(view["declare"]) == set(declare["declare"])
    assert set(view["declare"]["record"]) == set(declare["declare"]["record"])


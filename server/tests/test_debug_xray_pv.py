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
import copy
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
from test_release48_fly_config import pinned_release48_belief_package  # noqa: F401
from test_release50_fly_config import (BELIEF_SHA as R50_BELIEF_SHA, PRIOR_SHA as R50_PRIOR_SHA,
                                       RELEASE50, VALUE_SHA as R50_VALUE_SHA,
                                       release50_packages, served_bot)  # noqa: F401


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

def _served_entries(path, belief_path):
    from shengji.train import pv_search_policy as pv

    env = _r49_env()
    recipe = pv.pv_env_recipe({**env, "SHENGJI_PV_CKPT": str(path),
                              "SHENGJI_PV_SHA256": PACKAGE_SHA,
                              "SHENGJI_PV_BELIEF_CKPT": str(belief_path)})
    # the singleton challenger registers the served recipe under its -sc8 name
    if env.get("SHENGJI_PV_SINGLETON_CHALLENGER") == "1":
        entries = pv.singleton_registry_entries(**recipe)
    else:
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


def test_production_overlay_explains_a_served_play_decision(pinned_production_package, pinned_release48_belief_package):
    """The overlay on the served recipe: every admitted candidate carries the
    value head's level, the chosen row is marked, the model identity is the
    package's.  Fails, never skips, under SHENGJI_REQUIRE_PV_PACKAGE=1."""
    name, factory = _served_entries(pinned_production_package, pinned_release48_belief_package)
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


def test_production_overlay_explains_a_served_declaration(pinned_production_package, pinned_release48_belief_package):
    """The value declaration (release 44+) in the grace window: the record's
    outcomes and means reach the view, the chosen cards are the record's."""
    _, factory = _served_entries(pinned_production_package, pinned_release48_belief_package)
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


def test_production_overlay_keeps_the_panel_fixtures_shape(pinned_production_package, pinned_release48_belief_package):
    """The panel's release-49 captures (`web/src/components/xray-*.fixture.json`)
    stay renderable: every field they name is still written on the rollback
    recipe (the release-50 captures are pinned exactly below)."""
    components = Path(__file__).resolve().parents[2] / "web" / "src" / "components"
    play = json.loads((components / "xray-pv-search.fixture.json").read_text())
    declare = json.loads((components / "xray-declare.fixture.json").read_text())
    _, factory = _served_entries(pinned_production_package, pinned_release48_belief_package)
    bot = factory(seed=17)
    rnd = _play_state()
    out = debug._xray(rnd, rnd.turn, bot)
    assert set(out) == set(play)
    assert set(play["analysis"]) <= set(out["analysis"])
    assert set(out["analysis"]["recipe"]) == set(play["analysis"]["recipe"])
    assert set(out["analysis"]["work"]) == set(play["analysis"]["work"])
    assert set(play["candidates"][0]) <= set(out["candidates"][0])
    assert set(play["analysis"]["stages"]) <= set(out["analysis"]["stages"]) | {"tiebreak"}
    rnd = _dealt_round()
    view = debug._declare_view(rnd, _seat_with_options(rnd), bot)
    assert set(view) == set(declare)
    assert set(declare["declare"]) <= set(view["declare"])
    assert set(view["declare"]["record"]) == set(declare["declare"]["record"])


def _r49_env():
    """Release 49's ``fly.toml`` env: the repo's, with release 50 rolled back (the
    release-49 recipe the identities in this module are derived from)."""
    from test_release49_fly_config import fly_env
    return fly_env()


# ---------------------------------------------- release 50, the served recipe

def _r50_bot(packages, monkeypatch):
    """The release-50 bot as the server builds it from ``fly.toml``, with the
    wall clocks lifted so a slow runner cannot turn these wiring witnesses into
    timing tests (a budget-skipped stage would change what each one shows)."""
    name, bot = served_bot(packages, monkeypatch, seed=7)
    assert name == RELEASE50
    bot.serving_budget_seconds = None
    bot.leaf_greedy_deadline_ms = 0
    return bot


def _advance(rnd, plays):
    heuristic = HeuristicBot()
    for _ in range(plays):
        seat = rnd.turn
        rnd.play(seat, heuristic.decide_play(rnd, seat))
    return rnd


def _advance_to(rnd, *, max_hand, following):
    heuristic = HeuristicBot()
    while not (max(map(len, rnd.hands)) <= max_hand and bool(rnd.trick.plays) == following):
        seat = rnd.turn
        rnd.play(seat, heuristic.decide_play(rnd, seat))
    return rnd


def _stages(verdict):
    return {s["stage"]: s for s in verdict["pipeline"]}


R50_IDS = {"value": R50_VALUE_SHA[:8], "prior": R50_PRIOR_SHA[:8], "belief": R50_BELIEF_SHA[:8]}


def test_r50_lead_names_the_lead_confirmation_that_replaced_the_search(release50_packages, monkeypatch):
    """The release-50 lead the release test plays: lcc32 confirms a challenger
    on fresh worlds and plays it; the verdict says so, names the packages and
    shows the belief draws by stage.  The X-ray's play is the served bot's."""
    from test_pv_search_serving import _play_state as served_play_state
    bot = _r50_bot(release50_packages, monkeypatch)
    rnd = served_play_state()
    expected = copy.deepcopy(bot).decide_play(copy.deepcopy(rnd), rnd.turn)
    out = debug._xray(rnd, rnd.turn, copy.deepcopy(bot))
    info = out["analysis"]
    verdict = info["verdict"]
    assert info["policy"] == RELEASE50          # the full recipe name, not cut
    assert verdict["played"] == expected
    assert info["model_ids"] == verdict["model_ids"] == R50_IDS
    assert verdict["decided_by"] == "lead_confirm" and verdict["degraded"] is False
    stages = _stages(verdict)
    assert list(stages)[:4] == ["anchor", "admission", "singleton_challenger", "search"]
    assert stages["lead_confirm"]["status"] == "applied" and stages["lead_confirm"]["changed"]
    assert stages["lead_confirm"]["play"] == " ".join(expected)
    assert stages["singleton_challenger"]["status"] in ("kept", "applied")
    assert stages["exact_lead"]["status"] == "ineligible"
    assert "lcc delta" in verdict["summary"]
    lcc = info["stages"]["lead_confirm"]
    assert lcc["lead_confirm_status"] == "applied" and lcc["lead_confirm_challengers"]
    assert lcc["lead_confirm_worlds"] >= 64
    chosen = [r for r in out["candidates"] if r["bot_plays"]]
    assert len(chosen) == 1 and chosen[0]["lead_confirm_challenger"] is True
    assert chosen[0]["acting_team_levels"] is None and chosen[0]["lead_confirm_delta"] > 0
    assert info["applied_rules"][-1] == "lead_confirm_applied"
    # the top candidates by value, each with its margin to the next
    top = verdict["top"]
    assert 2 <= len(top) <= 5 and top[0]["value"] >= top[1]["value"]
    assert top[0]["margin_to_next"] == pytest.approx(top[0]["value"] - top[1]["value"])
    # belief health: every draw on B1a, none fell back
    assert info["stages"]["belief"]["belief_fallback_any"] == 0
    assert info["draws"]["world_draws_by_stage"]["lead_confirm"] >= 1
    assert set(info["draws"]["belief_fallback_by_stage"].values()) == {0}
    # lgf greedy-finished the leaves (the lifted deadline writes no deadline fields)
    assert info["stages"]["leaf_greedy"]["leaf_greedy_finish_applied"] is True
    assert "belief_snapshot" not in json.dumps(out) and "belief_seed" not in json.dumps(out)


def test_r50_lead_names_the_singleton_challenger_admission(release50_packages, monkeypatch):
    """A lead where sc8 swaps an omitted singleton into the ballot's last slot."""
    from test_pv_search_serving import _play_state as served_play_state
    bot = _r50_bot(release50_packages, monkeypatch)
    rnd = _advance(served_play_state(), 20)
    out = debug._xray(rnd, rnd.turn, copy.deepcopy(bot))
    info = out["analysis"]
    stage = _stages(info["verdict"])["singleton_challenger"]
    assert stage["status"] == "applied" and stage["changed"] is True
    added = info["stages"]["singleton_challenger"]["singleton_challenger_added"]
    assert stage["play"] == " ".join(added)
    assert [r["play"] for r in out["candidates"] if r.get("singleton_added")] == [added]
    assert info["stages"]["singleton_challenger"]["singleton_probe_margin"] > 0
    assert "singleton_challenger_applied" in info["applied_rules"]


def test_r50_follow_shows_no_lead_stages(release50_packages, monkeypatch):
    """A mid-hand follow: no lead stage runs, the exact follow is out of bounds."""
    bot = _r50_bot(release50_packages, monkeypatch)
    rnd = _advance(_play_state(), 1)
    assert rnd.trick.plays and max(map(len, rnd.hands)) > 7
    out = debug._xray(rnd, rnd.turn, copy.deepcopy(bot))
    verdict = out["analysis"]["verdict"]
    stages = _stages(verdict)
    assert "lead_confirm" not in stages
    assert stages["exact_follow"]["status"] == "ineligible"
    assert stages["exact_lead"]["detail"] == "a follow"
    assert verdict["model_ids"] == R50_IDS and verdict["degraded"] is False
    assert sum(r["bot_plays"] for r in out["candidates"]) == 1


def test_r50_endgame_lead_shows_the_exact_lead_stage(release50_packages, monkeypatch):
    """A lead with every hand within ed7's bound: the exact stage solves it, the
    rows carry the search's own value next to the exact level, lcc defers."""
    from test_pv_search_serving import _play_state as served_play_state
    bot = _r50_bot(release50_packages, monkeypatch)
    bot.exact_lead_max_seconds = 120.0      # the pure engine's solve outlasts the served cap
    rnd = _advance_to(served_play_state(), max_hand=6, following=False)
    out = debug._xray(rnd, rnd.turn, copy.deepcopy(bot))
    info = out["analysis"]
    stages = _stages(info["verdict"])
    assert stages["exact_lead"]["status"] == "complete"
    assert "worlds" in stages["exact_lead"]["detail"] and "nodes" in stages["exact_lead"]["detail"]
    assert stages["lead_confirm"]["status"] == "exact"
    assert info["stages"]["exact_lead"]["exact_lead_worlds_completed"] == 64
    assert all("search_value" in r for r in out["candidates"] if r["index"] is not None)
    assert "exact level" in info["verdict"]["summary"]


def test_r50_endgame_follow_shows_the_exact_follow_stage(release50_packages, monkeypatch):
    """A follow with every hand within xf7's bound: the compact-level solver's
    scores reach the rows and the stage reports its worlds and nodes."""
    from test_pv_search_serving import _play_state as served_play_state
    bot = _r50_bot(release50_packages, monkeypatch)
    rnd = _advance_to(served_play_state(), max_hand=6, following=True)
    out = debug._xray(rnd, rnd.turn, copy.deepcopy(bot))
    info = out["analysis"]
    stage = _stages(info["verdict"])["exact_follow"]
    assert stage["status"] in ("applied", "unchanged")
    assert "nodes" in stage["detail"]
    assert info["stages"]["exact_follow"]["exact_follow_attempted"] is True
    assert all(isinstance(r.get("exact_score"), float) for r in out["candidates"] if r["index"] is not None)


def test_r50_bury_lists_the_wide_value_candidates_on_belief_worlds(release50_packages, monkeypatch):
    """The wide value-only bury on B1a's worlds (bbw): 64 candidates scored on
    32 belief worlds, the best listed with the chosen one marked."""
    from test_cwv_bury_wide_value import bury_state
    bot = _r50_bot(release50_packages, monkeypatch)
    bot.bury_serving_budget_seconds = 120.0
    rnd = bury_state(63)
    expected = copy.deepcopy(bot).decide_bury(copy.deepcopy(rnd), rnd.banker)
    out = debug._xray(rnd, rnd.banker, copy.deepcopy(bot))
    bury = out["bury"]
    assert bury["chooser"] == "wide_value" and bury["chosen"] == expected
    assert bury["candidate_count"] == 64 and bury["candidates_truncated"] is True
    assert bury["work"]["worlds_used"] == 32 and bury["model_positions"] == 64 * 32
    assert bury["belief"] == {**bury["belief"], "bury_belief_worlds": True,
                              "bury_belief_fallbacks": 0, "bury_belief_error": None}
    assert bury["model_ids"] == {"value": R50_VALUE_SHA[:8], "prior": None, "belief": R50_BELIEF_SHA[:8]}
    rows = bury["candidates"]
    assert len(rows) >= debug.BURY_TOP and sum(r["bot_buries"] for r in rows) == 1
    assert sum(r["incumbent"] for r in rows) == 1
    values = [r["value"] for r in rows if r["rank"] is not None and r["rank"] <= debug.BURY_TOP]
    assert values == sorted(values, reverse=True) and all(isinstance(v, float) for v in values)
    chosen = next(r for r in rows if r["bot_buries"])
    assert chosen["rank"] == 1 and bury["margin"] == pytest.approx(chosen["margin_to_next"])
    verdict = bury["verdict"]
    assert verdict["decided_by"] == "wide_value" and verdict["degraded"] is False
    assert "32 belief worlds" in verdict["summary"]


def test_r50_declare_ranks_the_outcomes(release50_packages, monkeypatch):
    bot = _r50_bot(release50_packages, monkeypatch)
    rnd = _dealt_round()
    view = debug._declare_view(rnd, _seat_with_options(rnd), copy.deepcopy(bot))["declare"]
    verdict = view["verdict"]
    assert view["model_ids"] == {"value": R50_VALUE_SHA[:8], "prior": None, "belief": None}
    assert verdict["decided_by"] in ("value", "heuristic") and verdict["degraded"] is False
    values = [t["value"] for t in verdict["top"]]
    assert len(values) >= 2 and values == sorted(values, reverse=True)
    assert sum(t["bot_plays"] for t in verdict["top"]) == 1
    assert view["policy"] == RELEASE50


def test_r50_overlay_matches_the_panel_fixtures(release50_packages, monkeypatch):
    """The panel's release-50 captures (`web/src/components/xray-r50-*.fixture.json`)
    have exactly the shape the served producer writes; a renamed or dropped
    field fails here before the browser shows 'n/a'."""
    from test_cwv_bury_wide_value import bury_state
    from test_pv_search_serving import _play_state as served_play_state
    components = Path(__file__).resolve().parents[2] / "web" / "src" / "components"
    fixture = {k: json.loads((components / f"xray-r50-{k}.fixture.json").read_text())
               for k in ("play", "bury", "declare")}
    bot = _r50_bot(release50_packages, monkeypatch)
    rnd = served_play_state()
    play = debug._xray(rnd, rnd.turn, copy.deepcopy(bot))
    assert set(play) == set(fixture["play"])
    assert set(play["analysis"]) == set(fixture["play"]["analysis"])
    assert set(play["analysis"]["verdict"]) == set(fixture["play"]["analysis"]["verdict"])
    assert set(play["analysis"]["stages"]) == set(fixture["play"]["analysis"]["stages"])
    assert [set(r) for r in play["candidates"]] == [set(r) for r in fixture["play"]["candidates"]]
    assert play["analysis"]["verdict"]["played"] == fixture["play"]["analysis"]["verdict"]["played"]
    rnd = bury_state(63)
    bury = debug._xray(rnd, rnd.banker, copy.deepcopy(bot))["bury"]
    assert set(bury) == set(fixture["bury"]["bury"])
    assert set(bury["verdict"]) == set(fixture["bury"]["bury"]["verdict"])
    assert set(bury["candidates"][0]) == set(fixture["bury"]["bury"]["candidates"][0])
    assert bury["chosen"] == fixture["bury"]["bury"]["chosen"]
    rnd = _dealt_round()
    view = debug._declare_view(rnd, _seat_with_options(rnd), copy.deepcopy(bot))
    assert set(view["declare"]) == set(fixture["declare"]["declare"])
    assert set(view["declare"]["verdict"]) == set(fixture["declare"]["declare"]["verdict"])


# ------------------------------------- older records and degraded decisions

def test_a_record_without_the_release50_fields_renders_them_absent():
    """A record from before lcc / sc8 / package ids (the release-45 era) still
    renders: no lead-confirm or sc8 stage, package ids None, an info note."""
    rows, info = play_analysis(_bot(_pv_record()), ["SK"], is_attacker=True, elapsed=0.3)
    verdict = info["verdict"]
    assert info["model_ids"] is None and verdict["model_ids"] is None
    assert info["draws"] == {}
    stages = _stages(verdict)
    assert "lead_confirm" not in stages and "singleton_challenger" not in stages
    assert [w["code"] for w in verdict["warnings"]] == ["no_model_ids"]
    assert verdict["degraded"] is False
    assert verdict["decided_by"] == "exact_lead"     # the record's exact pass changed the play
    assert all("lead_confirm_challenger" not in r for r in rows)


def test_degraded_stages_raise_the_warning_badge():
    record = _pv_record(
        model_ids={"value": "f4f4127e", "prior": "1fa201b2", "belief": "028131a0"},
        belief_fallback=1, belief_fallback_any=1,
        belief_fallback_by_stage={"base": 1, "lead_confirm": 0, "adaptive_worlds": 0},
        leaf_greedy_deadline_fired=True, leaf_greedy_deadline_cut_leaves=12,
        leaf_greedy_deadline_fired_any=True,
        lead_confirm_status="abandoned", lead_confirm_abandon_reason="leaf_deadline",
        lead_confirm_abandon_error="Traceback /private/never", lead_confirm_applied=False,
        exact_lead_status="skipped_budget", exact_lead_changed=False,
        exact_follow_attempted=False)
    _, info = play_analysis(_bot(record), ["SK"], is_attacker=True, elapsed=0.3)
    verdict = info["verdict"]
    codes = {w["code"] for w in verdict["warnings"]}
    assert {"belief_fallback", "leaf_deadline", "lead_confirm_abandoned",
            "exact_lead_skipped_budget"} <= codes
    assert verdict["degraded"] is True
    assert "base 1" in next(w["text"] for w in verdict["warnings"] if w["code"] == "belief_fallback")
    assert info["draws"]["belief_fallback_by_stage"] == {"base": 1, "lead_confirm": 0, "adaptive_worlds": 0}
    assert _stages(verdict)["lead_confirm"]["status"] == "abandoned"
    assert "/private/never" not in json.dumps(info)


def test_a_fallback_play_is_degraded_and_decided_by_the_fallback():
    record = {"schema": PV_FALLBACK_SCHEMA, "policy": "pv-search-test", "action": ["SA"],
              "played": ["SA"], "reason": "budget", "error_class": "PVSearchBudgetExceeded",
              "budget_seconds": 3.0, "elapsed_seconds": 3.01, "work_complete": False}
    _, info = play_analysis(_bot(record), ["SA"], is_attacker=True, elapsed=3.1)
    assert info["verdict"]["decided_by"] == "fallback" and info["verdict"]["degraded"] is True
    assert info["model_ids"] is None


def test_lead_confirm_applied_marks_the_appended_challenger_row():
    record = _pv_record(
        admitted_indices=[3, 0, 7, 9], admitted=[["SA"], ["SK"], ["S5", "S5"], ["S9"]],
        value_means=[0.10, 0.35, -0.2, None], policy_log_odds_admitted=[-0.5, -0.1, -2.0, -3.0],
        selected_index=9, played=["S9"], exact_lead_status="ineligible", exact_lead_changed=False,
        lead_confirm_status="applied", lead_confirm_applied=True, lead_confirm_to=["S9"],
        lead_confirm_challengers=[["S9"]], lead_confirm_deltas=[0.05], lead_confirm_ses=[0.01],
        lead_confirm_worlds=128, lead_confirm_pool=24,
        singleton_challenger_applied=True, singleton_challenger_added=["SK"],
        singleton_challenger_removed=["S3"], singleton_probe_margin=0.02, singleton_probe_worlds=8)
    rows, info = play_analysis(_bot(record), ["S9"], is_attacker=True, elapsed=0.1)
    assert rows[-1]["lead_confirm_challenger"] is True and rows[-1]["lead_confirm_delta"] == 0.05
    assert rows[1]["singleton_added"] is True
    verdict = info["verdict"]
    assert verdict["decided_by"] == "lead_confirm"
    stages = _stages(verdict)
    assert stages["singleton_challenger"]["status"] == "applied"
    assert "1 admitted" not in stages["admission"]["detail"] and "3 admitted" in stages["admission"]["detail"]
    assert info["stages"]["lead_confirm"]["lead_confirm_challengers"] == ["S9"]


def _s58_wide_record(**extra):
    """A release-45..49 wide value-only bury record: no belief-world or package
    fields (`bury_wide_value.decide_wide_value_bury` before ``bbw``)."""
    pool = [["S2"] * 8, ["S3"] * 8, ["S4"] * 8]
    return {"schema": "cwv-bury-policy-v1", "arm": "hybrid", "candidates": pool,
            "shortlist": [0], "picked_index": 2, "candidate_count": 3, "finalist_count": 0,
            "fallback_reason": None, "model_means": [0.1, -0.2, 0.3], "mc_evidence": None,
            "model_worlds": 32, "selection_worlds": 0,
            "world_counts": {"model": 32, "selection": 0, "model_attempts": 33, "selection_attempts": 0},
            "elapsed_seconds": 0.2, "model_seconds": 0.2, "rollout_seconds": 0.0, "mc_rollouts": 0,
            "model_positions": 96, "counters": {"wrapper": {"secret": 1}},
            "wide_value": {"candidates": 3, "worlds": 32, "chosen_index": 2,
                           "chosen_is_incumbent": False, "seconds": 0.2, "k": 64,
                           "ballot_count": 2, "swap_count": 1, "swaps_enumerated": 9},
            **extra}


class _WideBuryBot:
    policy_name = "pv-search-wide-bury-test"

    def __init__(self, record):
        self.record = record
        self.last_bury_record = None

    def decide_bury(self, rnd, seat):
        self.last_bury_record = copy.deepcopy(self.record)
        return list(self.record["candidates"][self.record["picked_index"]])


def test_a_wide_bury_record_without_belief_fields_renders_them_absent():
    view = debug._bury_xray(None, 0, _WideBuryBot(_s58_wide_record()))
    assert view["chooser"] == "wide_value" and view["chosen"] == ["S4"] * 8
    assert view["belief"] is None and view["model_ids"] is None
    assert [r["rank"] for r in view["candidates"]] == [1, 2, 3]
    assert [r["sources"] for r in view["candidates"]] == [["swap"], ["incumbent"], ["ballot"]]
    assert view["candidates"][0]["bot_buries"] and view["candidates"][1]["incumbent"]
    assert view["margin"] == pytest.approx(0.2) and view["gap_vs_incumbent"] == pytest.approx(0.2)
    assert view["work"]["worlds_used"] == 32 and view["work"]["attempts"] == 33
    assert view["verdict"]["decided_by"] == "wide_value"
    assert [w["code"] for w in view["verdict"]["warnings"]] == ["no_model_ids"]
    assert "32 sampled worlds" in view["verdict"]["summary"]
    assert "secret" not in json.dumps(view)


def test_a_bury_belief_fallback_raises_the_warning_badge():
    record = _s58_wide_record(bury_belief_worlds=True, bury_belief_fallbacks=1,
                              bury_belief_error="ValueError", bury_belief_ms=3.0,
                              model_ids={"value": "f4f4127e", "prior": None, "belief": "028131a0"})
    view = debug._bury_xray(None, 0, _WideBuryBot(record))
    assert view["belief"]["bury_belief_fallbacks"] == 1
    assert view["verdict"]["degraded"] is True
    assert [w["code"] for w in view["verdict"]["warnings"]] == ["bury_belief_fallback"]
    assert "32 sampled worlds" in view["verdict"]["summary"]


def test_a_wide_bury_over_the_listing_bound_keeps_the_incumbent_and_the_choice():
    pool = [[f"S{i}"] * 8 for i in range(40)]
    means = [-float(i) for i in range(40)]
    means[0], means[39] = -100.0, 50.0
    record = _s58_wide_record(candidates=pool, model_means=means, picked_index=39,
                              candidate_count=40,
                              wide_value={"candidates": 40, "worlds": 32, "chosen_index": 39,
                                          "ballot_count": 10})
    view = debug._bury_xray(None, 0, _WideBuryBot(record))
    rows = view["candidates"]
    assert len(rows) == debug.BURY_TOP + 1 and view["candidates_truncated"] is True
    assert rows[0]["bot_buries"] and rows[0]["rank"] == 1
    assert rows[-1]["incumbent"] and rows[-1]["rank"] == 40 and rows[-1]["margin_to_next"] is None

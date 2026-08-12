"""Tests for S6 full-source / boss-near-search separation."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

from shengji.ai.throw_policy import make_s6_throw_bot
from shengji.ai.throw_search_gate import (
    BOSS_NEAR_GATE,
    make_s6_boss_near_bot,
)
from shengji.ai.throw_sourcing import BOSS_NEAR_BUNDLE
from shengji.rl.replay_log import rebuild_round


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import s6_boss_near_prevalence as CENSUS  # noqa: E402


FIXTURE = Path(__file__).with_name("data") / "s6_kesp_throw_witnesses.v1.json"
RESULT = Path(__file__).with_name("data") / \
    "s6_boss_near_prevalence.v1.json"


def _state(witness_id: str):
    fixture = json.loads(FIXTURE.read_text())
    for round_record in fixture["rounds"]:
        witness = next((item for item in round_record["witnesses"]
                        if item["id"] == witness_id), None)
        if witness is None:
            continue
        rnd = rebuild_round(round_record["events"])
        target = tuple(sorted(witness["human_action"]))
        for event in round_record["events"]:
            if event["e"] != "play" or rnd.phase != "play":
                continue
            if (event["seat"] == witness["seat"]
                    and tuple(sorted(event["cards"])) == target):
                return rnd, witness
            rnd.play(event["seat"], list(event["cards"]))
    raise AssertionError(f"unknown witness {witness_id}")


def test_gate_keeps_full_source_but_searches_only_boss_near_suffix():
    rnd, witness = _state("KESP:r4:jerry:partial-near-boss")
    broad = make_s6_throw_bot(treatment=True, seed=3)._source_plan(
        rnd, witness["seat"])
    gated = make_s6_boss_near_bot(treatment=True, seed=3)._source_plan(
        rnd, witness["seat"])
    assert gated["ballot"].record() == broad["ballot"].record()
    assert gated["search_gate"] == BOSS_NEAR_GATE
    assert set(gated["added_keys"]).issubset(set(broad["added_keys"]))
    assert gated["gated_added_count"] <= gated["broad_added_count"]
    by_key = {candidate.cards: candidate for candidate in gated["ballot"].candidates}
    assert all(BOSS_NEAR_BUNDLE in by_key[key].sources
               for key in gated["added_keys"])


def test_whole_suit_only_action_remains_visible_but_is_not_searched():
    rnd, witness = _state("KESP:r5:jerry:whole-suit-evacuation")
    target = tuple(sorted(witness["human_action"]))
    gated = make_s6_boss_near_bot(treatment=True, seed=5)._source_plan(
        rnd, witness["seat"])
    ballot_keys = {candidate.cards for candidate in gated["ballot"].candidates}
    assert target in ballot_keys
    assert target not in set(gated["added_keys"])


def test_hidden_hands_do_not_change_source_or_search_gate():
    rnd, witness = _state("KESP:r4:jerry:partial-near-boss")
    altered = copy.deepcopy(rnd)
    for other in range(4):
        if other != witness["seat"]:
            altered.hands[other] = ["BJ"] * len(altered.hands[other])
    left = make_s6_boss_near_bot(treatment=True, seed=7)._source_plan(
        rnd, witness["seat"])
    right = make_s6_boss_near_bot(treatment=True, seed=7)._source_plan(
        altered, witness["seat"])
    assert left["ballot"].record() == right["ballot"].record()
    assert left["added_keys"] == right["added_keys"]


def test_decision_record_names_source_and_searched_candidate_counts(monkeypatch):
    rnd, witness = _state("KESP:r4:jerry:partial-near-boss")
    bot = make_s6_boss_near_bot(treatment=True, seed=11)
    monkeypatch.setattr(type(bot), "TRACTOR_LOCK", False)
    monkeypatch.setattr(type(bot), "REPORT_FOLD_WORLDS", 0)
    monkeypatch.setattr(type(bot), "REPORT_RULE", "none")
    monkeypatch.setattr(type(bot), "N_DETERMINIZATIONS", 1)
    bot._sample_hands = lambda *_args, **_kwargs: (None, None)
    bot._rollout = lambda *_args, **_kwargs: 0.0
    bot.decide_play(rnd, witness["seat"])
    record = bot.last_s6_throw_record
    assert record["search_gate"] == BOSS_NEAR_GATE
    assert record["source_candidate_count"] >= record["searched_candidate_count"]


def test_prevalence_census_is_score_free_and_gate_is_subset():
    payload = CENSUS.run_census(seed0=446_900_000, rounds=2)
    CENSUS._assert_score_free(payload)
    # Multi-card throws reduce the number of tricks, so a round need not have
    # exactly 25 lead states.
    assert payload["aggregate"]["leads"] == len(payload["rows"]) > 0
    assert payload["aggregate"]["gated_triggers"] <= \
        payload["aggregate"]["broad_triggers"]
    assert all(row["gated_new_candidates"] <= row["broad_new_candidates"]
               for row in payload["rows"])


def test_exclusive_writer_refuses_overwrite(tmp_path):
    target = tmp_path / "census.json"
    CENSUS.write_exclusive(target, {"schema": CENSUS.SCHEMA})
    with pytest.raises(CENSUS.CensusRefused, match="overwrite"):
        CENSUS.write_exclusive(target, {"schema": CENSUS.SCHEMA})


def test_preserved_air_prevalence_recomputes_and_keeps_source_coverage():
    raw = RESULT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "167eabbce94aeb0b202a938c8a604c73e1d874dbc566763360d9b38d0c2e88c3")
    payload = json.loads(raw)
    internal = payload.pop("internal_sha256")
    assert CENSUS.stable_digest(payload) == internal == (
        "ab5547372d9b37c2aaa579a1cbd83c9032068eca51e503a37f1b6ca50b707cf6")
    CENSUS._assert_score_free(payload)
    assert payload["git"] == "6c61f1fb1ffdbe5bd0e358aec38a3274e6fe7f28"
    assert payload["tree_dirty"] is False
    rows = payload["rows"]
    assert len(rows) == len({row["state_id"] for row in rows}) == 10_895
    assert payload["aggregate"]["source_candidates"] == 19_893
    assert payload["aggregate"]["broad_triggers"] == 10_162
    assert payload["aggregate"]["gated_triggers"] == 1_283
    assert payload["aggregate"]["second_search_trigger_reduction"] == \
        pytest.approx(0.8737453257232828)
    assert all(row["gated_new_candidates"] <= row["broad_new_candidates"]
               and (not row["gated_trigger"] or row["broad_trigger"])
               for row in rows)
    assert all(payload["aggregate"]["by_phase"][phase]["gated_triggers"] > 0
               for phase in ("early", "mid", "late"))
    assert all(payload["aggregate"]["by_role"][role]["gated_triggers"] > 0
               for role in ("attacker", "defender"))

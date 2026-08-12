"""S6 treatment/null isolation before any whole-game screen."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shengji.ai.registry import make_bot
from shengji.ai.throw_policy import (S6_THROW_COUNTER_FIELDS,
                                    make_s6_throw_bot)
from shengji.rl.replay_log import rebuild_round


FIXTURE = Path(__file__).with_name("data") / \
    "s6_kesp_throw_witnesses.v1.json"


def _state(witness_id: str):
    payload = json.loads(FIXTURE.read_text())
    for round_record in payload["rounds"]:
        for witness in round_record["witnesses"]:
            if witness["id"] != witness_id:
                continue
            rnd = rebuild_round(round_record["events"])
            target = tuple(sorted(witness["human_action"]))
            for event in round_record["events"]:
                if (event["e"] == "play" and event["seat"] == witness["seat"]
                        and tuple(sorted(event["cards"])) == target):
                    return rnd, witness
                if event["e"] == "play" and rnd.phase == "play":
                    rnd.play(event["seat"], list(event["cards"]))
    raise AssertionError(f"missing S6 witness {witness_id}")


def _stub_search(bot, rnd, target):
    """Make report-LCB deterministic and cheap while exercising real control."""
    acting_value = 30.0 if rnd.is_attacker(rnd.turn) else -30.0
    incumbent = tuple(sorted(bot._candidates(rnd, rnd.turn)[0]))

    def sample(*_args, **_kwargs):
        return None, None

    def rollout(_rnd, _seat, _hands, _buried, candidate, **_kwargs):
        key = tuple(sorted(candidate))
        if key == target:
            return acting_value
        return 0.0 if key == incumbent else -acting_value / 3

    bot._sample_hands = sample
    bot._rollout = rollout


@pytest.mark.parametrize("witness_id", [
    "KESP:r4:jerry:partial-near-boss",
    "KESP:r5:jerry:boss-bundle-under-ruff-risk",
    "KESP:r5:jerry:whole-suit-evacuation",
])
def test_treatment_and_null_share_append_only_widened_ballot(witness_id):
    rnd, witness = _state(witness_id)
    seat = witness["seat"]
    target = tuple(sorted(witness["human_action"]))
    champion = make_bot("mc-s0-report-lcb", seed=13)
    base = champion._candidates(rnd, seat)

    treatment = make_s6_throw_bot(treatment=True, seed=13)
    null = make_s6_throw_bot(treatment=False, seed=13)
    treatment_ballot = treatment._candidates(rnd, seat)
    null_ballot = null._candidates(rnd, seat)

    assert treatment_ballot == null_ballot
    assert treatment_ballot[:len(base)] == base
    assert treatment_ballot[0] == base[0]
    assert target in {tuple(sorted(action)) for action in treatment_ballot}
    assert treatment._s6_context["added_indices"]


def test_matched_null_scores_additions_but_cannot_select_them():
    rnd, witness = _state("KESP:r4:jerry:partial-near-boss")
    seat = witness["seat"]
    treatment = make_s6_throw_bot(treatment=True, seed=17)
    null = make_s6_throw_bot(treatment=False, seed=17)
    candidates = treatment._candidates(rnd, seat)
    null_candidates = null._candidates(rnd, seat)
    assert candidates == null_candidates
    added = treatment._s6_context["added_indices"][0]
    means = [0.0] * len(candidates)
    means[added] = 100.0
    incumbent_alternative = 1
    means[incumbent_alternative] = 5.0

    assert treatment._pick_index(
        candidates, means, range(len(candidates))) == added
    assert null._pick_index(
        candidates, means, range(len(candidates))) == incumbent_alternative
    assert null._pick_index(
        candidates, means, range(1, len(candidates))) == incumbent_alternative


def test_tractor_bypass_compares_only_locked_incumbent_to_s6_suffix():
    rnd, witness = _state("KESP:r4:jerry:partial-near-boss")
    seat = witness["seat"]
    treatment = make_s6_throw_bot(treatment=True, seed=19)
    null = make_s6_throw_bot(treatment=False, seed=19)
    treatment._s6_lock_bypass = True
    null._s6_lock_bypass = True
    candidates = treatment._candidates(rnd, seat)
    assert candidates == null._candidates(rnd, seat)
    assert treatment._s6_context["tractor_lock_bypass"] is True
    added = treatment._s6_context["added_indices"][0]
    assert len(treatment._s6_context["base_candidates"]) > 1

    # A pre-existing base alternative is deliberately made strongest.  It is
    # still ineligible: otherwise the experiment would bundle disabling the
    # champion's tractor lock with adding S6 proposals.
    means = [0.0] * len(candidates)
    means[1] = 100.0
    means[added] = 50.0
    assert treatment._pick_index(
        candidates, means, range(len(candidates))) == added
    assert null._pick_index(
        candidates, means, range(len(candidates))) == 0
    assert null._pick_index(
        candidates, means, range(1, len(candidates))) == added


@pytest.mark.parametrize("witness_id", [
    "KESP:r4:jerry:partial-near-boss",
    "KESP:r5:jerry:boss-bundle-under-ruff-risk",
    "KESP:r5:jerry:whole-suit-evacuation",
])
def test_real_report_control_treatment_changes_and_null_matches_champion(
        witness_id):
    rnd, witness = _state(witness_id)
    seat = witness["seat"]
    target = tuple(sorted(witness["human_action"]))
    champion = make_bot("mc-s0-report-lcb", seed=23)
    treatment = make_s6_throw_bot(treatment=True, seed=23)
    null = make_s6_throw_bot(treatment=False, seed=23)
    for bot in (champion, treatment, null):
        _stub_search(bot, rnd, target)

    champion_play = champion.decide_play(rnd, seat)
    treatment_play = treatment.decide_play(rnd, seat)
    null_play = null.decide_play(rnd, seat)

    assert tuple(sorted(treatment_play)) == target
    assert null_play == champion_play
    assert treatment.last_decision_record["work"]["total_rollouts"] == \
        null.last_decision_record["work"]["total_rollouts"]
    assert treatment.last_s6_throw_record["treatment_override"] is True
    assert null.last_s6_throw_record["matched_noop"] is True
    if treatment.last_s6_throw_record["tractor_lock_bypass"]:
        assert null.last_s6_throw_record["forced_null_incumbent"] is True
    assert null.rng.getstate() == champion.rng.getstate()

    t = treatment.s6_throw_telemetry()
    n = null.s6_throw_telemetry()
    assert t["treatment_overrides"] == t["searched_triggers"] == 1
    assert n["matched_noops"] == n["searched_triggers"] == 1
    assert set(t).issuperset(S6_THROW_COUNTER_FIELDS)


def test_follow_decision_never_reports_an_s6_trigger(monkeypatch):
    rnd, witness = _state("KESP:r4:jerry:partial-near-boss")
    rnd.play(witness["seat"], list(witness["human_action"]))
    bot = make_s6_throw_bot(treatment=True, seed=29)
    monkeypatch.setattr(type(bot), "TRACTOR_LOCK", False)
    monkeypatch.setattr(type(bot), "REPORT_FOLD_WORLDS", 0)
    monkeypatch.setattr(type(bot), "REPORT_RULE", "none")
    monkeypatch.setattr(type(bot), "N_DETERMINIZATIONS", 1)
    bot._sample_hands = lambda *_args, **_kwargs: (None, None)
    bot._rollout = lambda *_args, **_kwargs: 0.0
    bot.decide_play(rnd, rnd.turn)
    assert bot.last_s6_throw_record["lead"] is False
    assert bot.last_s6_throw_record["trigger"] is False
    assert bot.s6_throw_telemetry()["new_candidate_triggers"] == 0


def test_telemetry_rejects_a_null_that_claims_an_override():
    bot = make_s6_throw_bot(treatment=False, seed=31)
    bot._s6_throw_totals["searched_triggers"] = 1
    bot._s6_throw_totals["attacker_triggers"] = 1
    bot._s6_throw_totals["new_candidate_triggers"] = 1
    bot._s6_throw_totals["new_candidates"] = 1
    bot._s6_throw_totals["source_candidates"] = 1
    bot._s6_throw_totals["treatment_overrides"] = 1
    with pytest.raises(AssertionError, match="null recorded a treatment"):
        bot.s6_throw_telemetry()

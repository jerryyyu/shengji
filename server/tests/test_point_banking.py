"""Falsification tests for the rollout-only S4 point-banking mechanism."""

from __future__ import annotations

import copy
import random
from types import MethodType

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.point_banking import (POINT_BANKING_COUNTER_FIELDS,
                                      POINT_BANKING_POLICIES,
                                      PointBankingRolloutPolicy,
                                      empty_point_banking_telemetry,
                                      make_point_banking_bot)
from shengji.ai.registry import make_bot
from shengji.engine.ballot import mc_ballot
from shengji.engine.cards import Ordering
from shengji.engine.round import Round, Trick, TrickPlay


ZERO_POINT_KITTY = ["C2", "C3", "C4", "C6", "C8", "C9", "CJ", "CQ"]


def _last_seat_state(hand, remaining, *, banker=0):
    """Named low-trump witness: seat 3 acts last over opponent seat 2."""
    rnd = Round("7", banker, random.Random(0))
    rnd.phase = "play"
    rnd.ordering = Ordering("H", "7")
    rnd.trump_suit = "H"
    rnd.trump_is_nt = False
    rnd.turn = 3
    rnd.buried = list(ZERO_POINT_KITTY)
    rnd.hands = [list(remaining[0]), list(remaining[1]),
                 list(remaining[2]), list(hand)]
    rnd.trick = Trick(leader=0, plays=[
        TrickPlay(0, ["H3"]),
        TrickPlay(1, ["H4"]),
        TrickPlay(2, ["H5"]),
    ])
    return rnd


def _positive_witness(*, banker=0):
    # H10 banks ten points while HK remains as higher control.  If H6 is used,
    # the defenders' two jokers take both later tricks and strand the H10.
    return _last_seat_state(
        ["H6", "H10", "HK"],
        [["BJ", "LJ"], ["C2", "C3"], ["H8", "H9"]],
        banker=banker,
    )


def _negative_control_cost_witness():
    # With no winner above HK, spending HK now loses future control: retaining
    # it wins the final H10 trick.  The bounded treatment must decline.
    return _last_seat_state(
        ["H6", "HK"], [["H10"], ["H2"], ["H8"]], banker=0)


def _finish_after_forced_choice(rnd, card):
    clone = copy.deepcopy(rnd)
    clone.play(clone.turn, [card])
    policy = HeuristicBot()
    while clone.phase == "play":
        seat = clone.turn
        clone.play(seat, policy.decide_play(clone, seat))
    return clone.attacker_points


def _counter_projection(record):
    return {name: record[name] for name in POINT_BANKING_COUNTER_FIELDS
            if name not in {"changes", "matched_noops"}}


def test_named_positive_witness_changes_only_treatment_and_matched_work():
    rnd = _positive_witness()
    treatment = PointBankingRolloutPolicy(apply_treatment=True)
    null = PointBankingRolloutPolicy(apply_treatment=False)

    assert HeuristicBot().decide_play(rnd, 3) == ["H6"]
    assert null.decide_play(rnd, 3) == ["H6"]
    assert treatment.decide_play(rnd, 3) == ["H10"]

    tr = treatment.point_banking_telemetry()
    nr = null.point_banking_telemetry()
    assert _counter_projection(tr) == _counter_projection(nr)
    assert tr["triggers"] == tr["changes"] == 1
    assert tr["attacker_triggers"] == 1 and tr["point_gain"] == 10
    assert nr["triggers"] == nr["matched_noops"] == 1
    assert tr["candidate_checks"] == nr["candidate_checks"] == 3

    # This named continuation is mutation-sensitive: deleting the treatment or
    # returning the cheap winner erases a real ten-point team-utility gain.
    assert _finish_after_forced_choice(rnd, "H10") == \
        _finish_after_forced_choice(rnd, "H6") + 10


def test_named_negative_witness_declines_when_point_card_is_future_control():
    rnd = _negative_control_cost_witness()
    treatment = PointBankingRolloutPolicy(apply_treatment=True)
    null = PointBankingRolloutPolicy(apply_treatment=False)

    assert treatment.decide_play(rnd, 3) == null.decide_play(rnd, 3) == ["H6"]
    tr, nr = (treatment.point_banking_telemetry(),
              null.point_banking_telemetry())
    assert _counter_projection(tr) == _counter_projection(nr)
    assert tr["opportunities"] == tr["decline_no_higher_reserve"] == 1
    assert tr["triggers"] == tr["changes"] == 0

    # Forcing the seductive HK bank would lose ten attacker points here.  This
    # pins the reason a higher reserve is a load-bearing part of the trigger.
    assert _finish_after_forced_choice(rnd, "H6") == \
        _finish_after_forced_choice(rnd, "HK") + 10


def test_not_last_and_partner_owned_tricks_are_explicit_declines():
    not_last = _positive_witness()
    not_last.turn = 2
    not_last.hands[2] = ["H6", "H10", "HK"]
    not_last.trick = Trick(leader=0, plays=[
        TrickPlay(0, ["H3"]), TrickPlay(1, ["H5"]),
    ])
    policy = PointBankingRolloutPolicy(apply_treatment=True)
    assert policy.decide_play(not_last, 2) == ["H6"]
    assert policy.point_banking_telemetry()["decline_not_last"] == 1

    partner = _positive_witness()
    partner.trick.plays[2] = TrickPlay(2, ["H3"])
    # Seat 1 (seat 3's partner) now owns the H4-high trick.
    policy = PointBankingRolloutPolicy(apply_treatment=True)
    policy.decide_play(partner, 3)
    assert policy.point_banking_telemetry()["decline_partner_winning"] == 1


def test_treatment_never_changes_the_baseline_contest_decision():
    rnd = _positive_witness()
    rnd.hands[3] = ["C2", "H6", "H10", "HK"]
    rnd.trick = Trick(leader=0, plays=[
        TrickPlay(0, ["S3"]),
        TrickPlay(1, ["S4"]),
        TrickPlay(2, ["S6"]),
    ])
    treatment = PointBankingRolloutPolicy(apply_treatment=True)
    baseline = HeuristicBot().decide_play(rnd, 3)
    assert baseline == ["C2"]
    assert treatment.decide_play(rnd, 3) == baseline
    telemetry = treatment.point_banking_telemetry()
    assert telemetry["decline_baseline_not_winning"] == 1
    assert telemetry["candidate_checks"] == telemetry["triggers"] == 0


def test_trigger_is_team_symmetric_and_deterministic():
    # Banker seat 1 makes seat 3 a defender; the same secure ownership logic
    # applies because banking denies points to attackers instead of scoring.
    rnd = _positive_witness(banker=1)
    a = PointBankingRolloutPolicy(apply_treatment=True)
    b = PointBankingRolloutPolicy(apply_treatment=True)
    assert a.decide_play(copy.deepcopy(rnd), 3) == \
        b.decide_play(copy.deepcopy(rnd), 3) == ["H10"]
    assert a.point_banking_telemetry() == b.point_banking_telemetry()
    assert a.point_banking_telemetry()["defender_triggers"] == 1


def test_isolated_s4_arms_change_continuation_only_not_root_ballot():
    assert POINT_BANKING_POLICIES == {
        "base": "mc-s0-report-lcb",
        "treatment": "mc-s0-report-lcb-point-banking",
        "matched_null": "mc-s0-report-lcb-point-banking-null",
    }
    base = make_bot(POINT_BANKING_POLICIES["base"], seed=73)
    treatment = make_point_banking_bot(treatment=True, seed=73)
    null = make_point_banking_bot(treatment=False, seed=73)

    assert type(base.rollout_policy) is HeuristicBot
    assert type(treatment) is type(null)
    assert type(treatment.rollout_policy) is type(null.rollout_policy) \
        is PointBankingRolloutPolicy
    assert treatment.rollout_policy.apply_treatment is True
    assert null.rollout_policy.apply_treatment is False
    assert treatment.rng.getstate() == null.rng.getstate() == base.rng.getstate()
    assert mc_ballot(treatment).digest == mc_ballot(null).digest == \
        mc_ballot(base).digest

    witness = _positive_witness()
    # If the treatment were accidentally applied at root, this would become
    # H10.  The root remains SmartBot/MCBot's H6; only rollout_policy changes.
    assert treatment._follow(witness, 3) == null._follow(witness, 3) == ["H6"]
    assert treatment.rollout_policy.decide_play(witness, 3) == ["H10"]
    assert null.rollout_policy.decide_play(witness, 3) == ["H6"]


def test_per_decision_record_binds_exact_rollout_dose():
    bot = make_point_banking_bot(treatment=True, seed=9)
    bot.N_DETERMINIZATIONS = 1
    bot.REPORT_FOLD_WORLDS = 0
    bot.REPORT_RULE = "none"
    bot.TRACTOR_LOCK = False
    bot._candidates = MethodType(
        lambda self, rnd, seat: [["H6"], ["H10"]], bot)

    def sample(self, rnd, seat, memory):
        self.sample_attempts += 1
        self.accepted_worlds += 1
        return {}, []

    def rollout(self, rnd, seat, sampled, buried, candidate, **kwargs):
        self.rollout_policy.decide_play(_positive_witness(), 3)
        return 10.0 if candidate == ["H10"] else 0.0

    bot._sample_hands = MethodType(sample, bot)
    bot._rollout = MethodType(rollout, bot)
    played = bot.decide_play(_positive_witness(), 3)
    record = bot.last_decision_record["rollout_policy_telemetry"]

    assert played in (["H6"], ["H10"])
    assert record["schema"] == "point-banking-rollout-decision-v1"
    assert record["mode"] == "treatment"
    assert record["deterministic"] is record["exact_work_complete"] is True
    assert record["delta"]["triggers"] == record["delta"]["changes"] == 2
    assert record["delta"]["candidate_checks"] == 6


def test_feature_off_champion_exposes_zero_dose_and_no_decision_hook():
    bot = make_bot(POINT_BANKING_POLICIES["base"], seed=11)
    telemetry = empty_point_banking_telemetry()
    assert telemetry["mode"] == "off"
    assert all(telemetry[name] == 0 for name in POINT_BANKING_COUNTER_FIELDS)
    assert not hasattr(bot, "point_banking_telemetry")
    assert "rollout_policy_telemetry" not in (bot.last_decision_record or {})

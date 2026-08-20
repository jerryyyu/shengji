"""Falsification tests for the rollout-only pair-awareness experiment."""

from __future__ import annotations

import copy
import random
from types import MethodType

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.memory import Memory
from shengji.ai.pair_aware_rollout import (
    PAIR_AWARE_COUNTER_FIELDS,
    PAIR_AWARE_POLICIES,
    PairAwareRolloutPolicy,
    empty_pair_aware_telemetry,
    make_pair_aware_bot,
)
from shengji.ai.registry import make_bot
from shengji.engine.ballot import mc_ballot
from shengji.engine.cards import Ordering
from shengji.engine.round import Round, Trick, TrickPlay


VXVS_LOG_SHA256 = (
    "2210ca46d354f775e3ab125ace89b7e647c8c260cdd4734754ff67968d3af346")


def _trick(leader, plays, winner, points_value):
    return Trick(
        leader=leader,
        plays=[TrickPlay(seat, list(cards)) for seat, cards in plays],
        winner=winner,
        points=points_value,
    )


def _vxvs_promoted_d5_state() -> Round:
    """Exact VXVS round-2/trick-5 position, reduced to engine state.

    Jerry had just drawn out/split every higher diamond pair.  Both ♦5s were
    therefore a public-information winner even though ♦5 is intrinsically
    low.  The human cashed them for a 20-point trick; the live root ballot did
    contain the pair, but an ordinary HeuristicBot continuation leads ♠A.
    """
    rnd = Round("2", 3, random.Random(0))
    rnd.phase = "play"
    rnd.ordering = Ordering("H", "2")
    rnd.trump_suit = "H"
    rnd.trump_is_nt = False
    rnd.turn = 0
    rnd.declaration = {"seat": 3, "cards": ["H2", "H2"], "strength": 2}
    rnd.buried = ["D4", "S3", "C3", "C4", "S6", "C6", "S7", "C8"]
    rnd.hands = [
        ["D5", "D2", "D9", "SQ", "C6", "C9", "HJ", "CJ", "C10",
         "DJ", "H5", "S9", "S10", "SA", "D5", "HQ", "BJ", "D10"],
        ["SK", "C5", "H8", "C8", "H10", "C2", "HK", "S9", "S2",
         "C4", "C7", "C5", "S3", "LJ", "HA", "H5", "DK", "D9"],
        ["CJ", "SJ", "DQ", "DJ", "D2", "HA", "S5", "S7", "S2",
         "S5", "D8", "C9", "CA", "D6", "C2", "SA", "HK", "CQ"],
        ["H3", "C10", "CK", "BJ", "HQ", "HJ", "H10", "H9", "H6",
         "S10", "H4", "S8", "S4", "CQ", "S4", "S8", "H8", "LJ"],
    ]
    rnd.history = [
        _trick(3, [(3, ["H2", "H2"]), (0, ["H7", "H9"]),
                   (1, ["H6", "H7"]), (2, ["H3", "H4"])], 3, 0),
        _trick(3, [(3, ["CA"]), (0, ["C3"]), (1, ["CK"]),
                   (2, ["C7"])], 3, 10),
        _trick(3, [(3, ["SQ"]), (0, ["SK"]), (1, ["SJ"]),
                   (2, ["S6"])], 0, 10),
        _trick(0, [(0, ["DK", "DA", "DA"]),
                   (1, ["D3", "D6", "D8"]),
                   (2, ["D3", "D4", "D10"]),
                   (3, ["D7", "D7", "DQ"])], 0, 20),
    ]
    rnd.last_trick = rnd.history[-1]
    rnd.trick = Trick(leader=0, plays=[])
    rnd.attacker_points = 30
    rnd.kitty_bonus = 0
    rnd.last_trick_winner = None
    rnd.message = None
    return rnd


def _counter_projection(record):
    return {name: record[name] for name in PAIR_AWARE_COUNTER_FIELDS
            if name not in {"changes", "matched_noops"}}


def _finish_after_forced_lead(rnd: Round, action: list[str]) -> int:
    clone = copy.deepcopy(rnd)
    clone.play(clone.turn, list(action))
    policy = HeuristicBot()
    while clone.phase == "play":
        seat = clone.turn
        clone.play(seat, policy.decide_play(clone, seat))
    return clone.attacker_points


def test_vxvs_live_witness_recognizes_promoted_low_pair_with_matched_work():
    assert len(VXVS_LOG_SHA256) == 64
    rnd = _vxvs_promoted_d5_state()
    memory = Memory(rnd, 0)
    treatment = PairAwareRolloutPolicy(apply_treatment=True)
    null = PairAwareRolloutPolicy(apply_treatment=False)

    assert memory.pair_is_boss("D5") is True
    assert HeuristicBot().decide_play(rnd, 0) == ["SA"]
    assert null.decide_play(copy.deepcopy(rnd), 0) == ["SA"]
    assert treatment.decide_play(copy.deepcopy(rnd), 0) == ["D5", "D5"]

    tr = treatment.pair_aware_telemetry()
    nr = null.pair_aware_telemetry()
    assert _counter_projection(tr) == _counter_projection(nr)
    assert tr["triggers"] == tr["changes"] == 1
    assert nr["triggers"] == nr["matched_noops"] == 1
    assert tr["pair_candidates_checked"] == 1
    assert tr["promoted_boss_pairs"] == tr["ruff_safe_promoted_pairs"] == 1
    assert tr["attacker_triggers"] == tr["point_pair_triggers"] == 1

    # Mutation-sensitive exact-world diagnostic: under the same historical
    # continuation, cashing the pair gains 35 attacker points over leading A.
    assert _finish_after_forced_lead(rnd, ["D5", "D5"]) == 125
    assert _finish_after_forced_lead(rnd, ["SA"]) == 90


def test_higher_pair_still_unseen_and_ruff_risk_are_bounded_declines():
    higher_live = _vxvs_promoted_d5_state()
    # Remove the only public DQ.  Both copies are now unseen, so D5 is not
    # provably promoted and the treatment must preserve the baseline.
    higher_live.history[-1].plays[-1].cards[-1] = "D8"
    policy = PairAwareRolloutPolicy(apply_treatment=True)
    assert Memory(higher_live, 0).pair_is_boss("D5") is False
    assert policy.decide_play(higher_live, 0) == ["SA"]
    assert policy.pair_aware_telemetry()["triggers"] == 0

    ruff_risky = _vxvs_promoted_d5_state()
    ruff_risky.history.append(_trick(
        0, [(0, ["D6"]), (1, ["C4"])], 0, 0))
    policy = PairAwareRolloutPolicy(apply_treatment=True)
    assert "D" in Memory(ruff_risky, 0).voids[1]
    assert policy.decide_play(ruff_risky, 0) == ["SA"]
    telemetry = policy.pair_aware_telemetry()
    assert telemetry["promoted_boss_pairs"] == 1
    assert telemetry["ruff_safe_promoted_pairs"] == telemetry["triggers"] == 0


def test_pair_rule_uses_no_determinized_hidden_hand_information():
    rnd = _vxvs_promoted_d5_state()
    altered = copy.deepcopy(rnd)
    altered.hands[1:] = [["BJ"] * 18, ["LJ"] * 18, ["H2"] * 18]
    a = PairAwareRolloutPolicy(apply_treatment=True)
    b = PairAwareRolloutPolicy(apply_treatment=True)
    assert a.decide_play(rnd, 0) == b.decide_play(altered, 0) == ["D5", "D5"]
    assert a.pair_aware_telemetry() == b.pair_aware_telemetry()


def test_isolated_pair_arms_change_continuation_only_not_root_ballot():
    assert PAIR_AWARE_POLICIES["base"] == "mc-s0-report-lcb"
    base = make_bot(PAIR_AWARE_POLICIES["base"], seed=73)
    treatment = make_pair_aware_bot(treatment=True, seed=73)
    null = make_pair_aware_bot(treatment=False, seed=73)

    assert type(base.rollout_policy) is HeuristicBot
    assert type(treatment) is type(null)
    assert type(treatment.rollout_policy) is type(null.rollout_policy) \
        is PairAwareRolloutPolicy
    assert treatment.rng.getstate() == null.rng.getstate() == base.rng.getstate()
    assert mc_ballot(treatment).digest == mc_ballot(null).digest == \
        mc_ballot(base).digest

    witness = _vxvs_promoted_d5_state()
    # The live root already sees D5 as a boss pair.  This experiment leaves
    # that decision untouched and repairs only the HeuristicBot continuation.
    assert treatment._lead(witness, 0) == null._lead(witness, 0) == \
        base._lead(witness, 0) == ["D5", "D5"]
    assert treatment.rollout_policy.decide_play(witness, 0) == ["D5", "D5"]
    assert null.rollout_policy.decide_play(witness, 0) == ["SA"]


def test_per_decision_record_binds_exact_pair_aware_dose():
    bot = make_pair_aware_bot(treatment=True, seed=9)
    bot.N_DETERMINIZATIONS = 1
    bot.REPORT_FOLD_WORLDS = 0
    bot.REPORT_RULE = "none"
    bot.TRACTOR_LOCK = False
    bot._candidates = MethodType(
        lambda self, rnd, seat: [["SA"], ["D5", "D5"]], bot)

    def sample(self, rnd, seat, memory):
        self.sample_attempts += 1
        self.accepted_worlds += 1
        return {}, []

    def rollout(self, rnd, seat, sampled, buried, candidate, **kwargs):
        self.rollout_policy.decide_play(_vxvs_promoted_d5_state(), 0)
        return 10.0 if candidate == ["D5", "D5"] else 0.0

    bot._sample_hands = MethodType(sample, bot)
    bot._rollout = MethodType(rollout, bot)
    played = bot.decide_play(_vxvs_promoted_d5_state(), 0)
    record = bot.last_decision_record["pair_aware_rollout_telemetry"]

    assert played in (["SA"], ["D5", "D5"])
    assert record["schema"] == "pair-aware-rollout-decision-v1"
    assert record["public_information_only"] is True
    assert record["delta"]["triggers"] == record["delta"]["changes"] == 2
    assert record["delta"]["pair_candidates_checked"] == 2


def test_feature_off_telemetry_is_exact_zero_dose():
    telemetry = empty_pair_aware_telemetry()
    assert telemetry["mode"] == "off"
    assert telemetry["public_information_only"] is True
    assert all(telemetry[name] == 0 for name in PAIR_AWARE_COUNTER_FIELDS)

"""Falsification tests for the team-aware opponent-pair-cap extension."""
from __future__ import annotations

import copy
import random
import sys
from pathlib import Path

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.memory import Memory
from shengji.ai.pair_aware_rollout import PairAwareRolloutPolicy
from shengji.ai.pair_cap_rollout import (
    PAIR_CAP_COUNTER_FIELDS,
    OpponentPairCapRolloutPolicy,
    make_pair_cap_bot,
)
from shengji.engine.ballot import mc_ballot
from shengji.engine.cards import Ordering
from shengji.engine.round import Round, Trick, TrickPlay


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import pair_cap_rollout_incremental_dose as DOSE  # noqa: E402


def _pair_cap_only_state() -> Round:
    """A low diamond pair that opponents publicly cannot pair over."""
    rnd = Round("2", 3, random.Random(0))
    rnd.phase = "play"
    rnd.ordering = Ordering("H", "2")
    rnd.trump_suit = "H"
    rnd.trump_is_nt = False
    rnd.turn = 0
    rnd.banker = 3
    rnd.buried = []
    rnd.hands = [
        ["D5", "D5", "SA", "C3", "C4"],
        ["C5"] * 5,
        ["C6"] * 5,
        ["C7"] * 5,
    ]
    # A diamond pair was led. Both opponents (1 and 3) followed in diamonds
    # but showed no pair, proving pair_cap=0 without proving a void/ruff.
    rnd.history = [Trick(
        leader=2,
        plays=[
            TrickPlay(2, ["D3", "D3"]),
            TrickPlay(3, ["D7", "D8"]),
            TrickPlay(0, ["D9", "D10"]),
            TrickPlay(1, ["DJ", "DQ"]),
        ],
        winner=2,
        points=10,
    )]
    rnd.trick = Trick(leader=0, plays=[])
    return rnd


def _projection(payload):
    return {name: payload[name] for name in PAIR_CAP_COUNTER_FIELDS
            if name not in {"changes", "matched_noops"}}


def test_pair_cap_extension_is_strictly_broader_than_v1():
    rnd = _pair_cap_only_state()
    memory = Memory(rnd, 0)
    assert memory.pair_is_boss("D5") is False
    assert [memory.max_pairs(seat, "D") for seat in (1, 3)] == [0, 0]
    assert memory.ruff_risk("D", [1, 3]) is False
    assert HeuristicBot().decide_play(rnd, 0) == ["SA"]
    assert PairAwareRolloutPolicy(
        apply_treatment=True).decide_play(rnd, 0) == ["SA"]

    treatment = OpponentPairCapRolloutPolicy(apply_treatment=True)
    null = OpponentPairCapRolloutPolicy(apply_treatment=False)
    assert treatment.decide_play(copy.deepcopy(rnd), 0) == ["D5", "D5"]
    assert null.decide_play(copy.deepcopy(rnd), 0) == ["SA"]
    t = treatment.pair_cap_telemetry()
    n = null.pair_cap_telemetry()
    assert _projection(t) == _projection(n)
    assert t["triggers"] == t["changes"] == 1
    assert n["triggers"] == n["matched_noops"] == 1


def test_unknown_opponent_cap_and_ruff_risk_are_bounded_declines():
    unknown = _pair_cap_only_state()
    # Make seat 1's response a pair. Its cap is then unknown, so public proof
    # is insufficient and the extension keeps the historical single.
    unknown.history[0].plays[-1].cards = ["DJ", "DJ"]
    policy = OpponentPairCapRolloutPolicy(apply_treatment=True)
    assert Memory(unknown, 0).max_pairs(1, "D") is None
    assert policy.decide_play(unknown, 0) == ["SA"]
    assert policy.pair_cap_telemetry()["triggers"] == 0

    risky = _pair_cap_only_state()
    risky.history.append(Trick(
        leader=0,
        plays=[TrickPlay(0, ["D4"]), TrickPlay(1, ["C5"])],
        winner=0,
        points=0,
    ))
    policy = OpponentPairCapRolloutPolicy(apply_treatment=True)
    assert Memory(risky, 0).ruff_risk("D", [1, 3]) is True
    assert policy.decide_play(risky, 0) == ["SA"]
    telemetry = policy.pair_cap_telemetry()
    assert telemetry["opponent_pair_cap_proofs"] == 1
    assert telemetry["ruff_safe_proofs"] == telemetry["triggers"] == 0


def test_hidden_hands_do_not_change_pair_cap_proof_or_action():
    rnd = _pair_cap_only_state()
    altered = copy.deepcopy(rnd)
    altered.hands[1:] = [["BJ"] * 5, ["LJ"] * 5, ["H2"] * 5]
    left = OpponentPairCapRolloutPolicy(apply_treatment=True)
    right = OpponentPairCapRolloutPolicy(apply_treatment=True)
    assert left.decide_play(rnd, 0) == right.decide_play(altered, 0) \
        == ["D5", "D5"]
    assert left.pair_cap_telemetry() == right.pair_cap_telemetry()


def test_factory_changes_only_rollout_policy_and_keeps_root_ballot():
    treatment = make_pair_cap_bot(treatment=True, seed=17)
    null = make_pair_cap_bot(treatment=False, seed=17)
    assert type(treatment) is type(null)
    assert type(treatment.rollout_policy) is type(null.rollout_policy) \
        is OpponentPairCapRolloutPolicy
    assert mc_ballot(treatment).digest == mc_ballot(null).digest
    assert treatment.rng.getstate() == null.rng.getstate()
    witness = _pair_cap_only_state()
    assert treatment._lead(witness, 0) == null._lead(witness, 0)
    assert treatment.rollout_policy.decide_play(witness, 0) == ["D5", "D5"]
    assert null.rollout_policy.decide_play(witness, 0) == ["SA"]


def test_same_seed_v1_v2_null_preserve_root_ballot_and_exact_work():
    rnd, _ = DOSE._start_round(447_123_456)
    seat = rnd.turn
    assert seat is not None
    row = DOSE.evaluate_state(rnd, seat, decision_seed=992_123_456)
    assert row["root_candidate_count"] >= 1
    assert row["work"]["sample_attempts"] == (
        row["work"]["accepted_worlds"] + row["work"]["failed_worlds"])
    assert row["v2_pair_cap_dose"]["mode"] == "treatment"
    assert row["null_pair_cap_dose"]["mode"] == "matched_null"


def test_score_free_guard_and_exclusive_writer(tmp_path):
    safe = {"v2_action": ["D5", "D5"], "pair_cap_triggers": 3}
    DOSE._assert_score_free(safe)
    with pytest.raises(DOSE.DoseRefused, match="outcome fields"):
        DOSE._assert_score_free({"rows": [{"level_utility": 1}]})
    target = tmp_path / "dose.json"
    DOSE.write_exclusive(target, {"schema": DOSE.SCHEMA})
    with pytest.raises(DOSE.DoseRefused, match="overwrite"):
        DOSE.write_exclusive(target, {"schema": DOSE.SCHEMA})

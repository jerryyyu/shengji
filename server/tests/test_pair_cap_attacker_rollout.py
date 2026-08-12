"""Tests for the attacker-only opponent-pair-cap follow-up."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

from shengji.ai.pair_aware_rollout import PairAwareRolloutPolicy
from shengji.ai.pair_cap_attacker_rollout import (
    AttackerOnlyOpponentPairCapRolloutPolicy,
    make_pair_cap_attacker_bot,
)


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import pair_cap_attacker_gate_replay as REPLAY  # noqa: E402
import pair_cap_rollout_incremental_dose as DOSE  # noqa: E402

from test_pair_cap_rollout import _pair_cap_only_state  # noqa: E402


def test_incremental_pair_cap_fires_only_for_attacker_leads():
    attacker = _pair_cap_only_state()
    assert attacker.is_attacker(0)
    defender = copy.deepcopy(attacker)
    defender.banker = 0
    assert not defender.is_attacker(0)

    attacker_policy = AttackerOnlyOpponentPairCapRolloutPolicy(
        apply_treatment=True)
    defender_policy = AttackerOnlyOpponentPairCapRolloutPolicy(
        apply_treatment=True)
    assert attacker_policy.decide_play(attacker, 0) == ["D5", "D5"]
    assert defender_policy.decide_play(defender, 0) == ["SA"]
    assert attacker_policy.pair_cap_telemetry()["attacker_triggers"] == 1
    assert defender_policy.pair_cap_telemetry()["triggers"] == 0


def test_defender_path_preserves_reviewed_v1_pair_rule():
    defender = _pair_cap_only_state()
    defender.banker = 0
    # One publicly seen K and A leaves at most one unseen copy of each, so the
    # actor's queens are a globally boss pair under v1's public proof.
    defender.history[0].plays[-1].cards = ["DK", "DA"]
    defender.hands[0] = ["DQ", "DQ", "SA", "C3", "C4"]
    v1 = PairAwareRolloutPolicy(apply_treatment=True)
    gated = AttackerOnlyOpponentPairCapRolloutPolicy(apply_treatment=True)
    assert gated.decide_play(copy.deepcopy(defender), 0) == \
        v1.decide_play(copy.deepcopy(defender), 0)
    assert gated.pair_aware_telemetry()["defender_triggers"] == 1
    assert gated.pair_cap_telemetry()["triggers"] == 0


def test_factory_keeps_root_ballot_and_exact_work():
    rnd, _ = DOSE._start_round(447_123_456)
    seat = rnd.turn
    assert seat is not None
    treatment = make_pair_cap_attacker_bot(treatment=True, seed=992_123_456)
    null = make_pair_cap_attacker_bot(treatment=False, seed=992_123_456)
    treatment.decide_play(copy.deepcopy(rnd), seat)
    null.decide_play(copy.deepcopy(rnd), seat)
    assert DOSE._candidates(treatment) == DOSE._candidates(null)
    assert DOSE._work(treatment) == DOSE._work(null)


def test_replay_refuses_score_fields_and_mutated_parent(tmp_path):
    REPLAY._assert_score_free({"action": ["D5", "D5"]})
    with pytest.raises(REPLAY.ReplayRefused, match="outcome fields"):
        REPLAY._assert_score_free({"utility": 1})
    mutated = tmp_path / "dose.json"
    mutated.write_text("{}")
    with pytest.raises(REPLAY.ReplayRefused, match="input hash drift"):
        REPLAY.run_replay(dose=mutated)

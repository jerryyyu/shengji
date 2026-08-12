"""Tests for the attacker-only opponent-pair-cap follow-up."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

from shengji.ai.pair_aware_rollout import PairAwareRolloutPolicy
from shengji.ai.pair_cap_attacker_rollout import (
    AttackerOnlyOpponentPairCapRolloutPolicy,
    make_pair_cap_attacker_bot,
)


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
FROZEN_REPLAY = (
    Path(__file__).resolve().parent
    / "data/pair_cap_attacker_gate_replay.v1.json"
)
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


def test_frozen_attacker_gate_replay_is_hash_pinned_and_bounded():
    raw = FROZEN_REPLAY.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "c45a5739869345dfbce3845234c0e0c513f3161488c8920e5ba009025abcff88"
    )
    payload = json.loads(raw)
    internal = payload.pop("internal_sha256")
    assert REPLAY.stable_digest(payload) == internal == (
        "732be40a4fde7600ddc63055bf884fec35c53320846aeae55494a10f21faf332"
    )
    assert payload["git"] == "e692496c74087279fb287b18d3f6934146e71e8c"
    assert payload["tree_dirty"] is False
    source_paths = {
        "replay": SCRIPTS / "pair_cap_attacker_gate_replay.py",
        "dose_artifact": REPLAY.DEFAULT_DOSE,
        "dose_script": SCRIPTS / "pair_cap_rollout_incremental_dose.py",
        "root_replay": SCRIPTS / "pair_cap_rollout_root_audit.py",
        "attacker_gate": (
            SCRIPTS.parent / "shengji/ai/pair_cap_attacker_rollout.py"),
        "pair_cap": SCRIPTS.parent / "shengji/ai/pair_cap_rollout.py",
        "pair_v1": SCRIPTS.parent / "shengji/ai/pair_aware_rollout.py",
        "mcbot": SCRIPTS.parent / "shengji/ai/mcbot.py",
        "round": SCRIPTS.parent / "shengji/engine/round.py",
    }
    assert payload["source_sha256s"] == {
        name: REPLAY.sha256(path) for name, path in source_paths.items()
    }
    rows = payload["rows"]
    assert len(rows) == len({row["state_id"] for row in rows}) == 192
    assert all(row["pair_cap_dose"]["defender_triggers"] == 0
               for row in rows)
    aggregate = payload["aggregate"]
    assert aggregate["relation_counts"] == {
        "all_equal": 189,
        "protects_v1_from_broad_v2": 1,
        "retains_broad_v2_change": 2,
    }
    assert aggregate["changed_parent_root_relations"] == {
        "447000002:5:2": "v1",
        "447000005:2:1": "broad_v2",
        "447000007:6:3": "broad_v2",
    }
    assert aggregate["root_changes_vs_null"] == 11
    assert aggregate["pair_cap_triggered_roots"] == 32
    assert aggregate["pair_cap_triggers"] == 1419
    assert payload["score_free"] is True
    assert payload["outcomes_published"] is False
    assert payload["exploration_only"] is True
    assert payload["strength_claim"] is False
    assert payload["whole_game_execution_authorized"] is False
    assert payload["production_promotion"] is False
    assert payload["production_deployment"] is False
    REPLAY._assert_score_free(payload)

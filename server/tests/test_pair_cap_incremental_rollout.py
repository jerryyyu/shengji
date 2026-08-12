"""Falsification tests for the attacker-gated v3-versus-v1 estimand."""
from __future__ import annotations

import copy

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.pair_aware_rollout import PairAwareRolloutPolicy
from shengji.ai.pair_cap_incremental_rollout import (
    PAIR_CAP_INCREMENTAL_POLICIES,
    PairCapAttackerIncrementalRolloutPolicy,
    make_pair_cap_incremental_bot,
)
from shengji.ai.registry import make_bot
from shengji.engine.ballot import mc_ballot

from test_pair_cap_rollout import _pair_cap_only_state


def _component_projection(record):
    value = copy.deepcopy(record)
    value.pop("mode", None)
    outer = value["counters"]["outer"]
    outer.pop("changes", None)
    outer.pop("matched_parent_noops", None)
    return value


def test_incremental_treatment_and_parent_null_do_identical_component_work():
    rnd = _pair_cap_only_state()
    assert rnd.is_attacker(0)
    v1 = PairAwareRolloutPolicy(apply_treatment=True)
    treatment = PairCapAttackerIncrementalRolloutPolicy(
        apply_incremental=True)
    parent_null = PairCapAttackerIncrementalRolloutPolicy(
        apply_incremental=False)

    assert v1.decide_play(copy.deepcopy(rnd), 0) == ["SA"]
    assert treatment.decide_play(copy.deepcopy(rnd), 0) == ["D5", "D5"]
    assert parent_null.decide_play(copy.deepcopy(rnd), 0) == ["SA"]

    tr = treatment.pair_cap_incremental_telemetry()
    nr = parent_null.pair_cap_incremental_telemetry()
    assert _component_projection(tr) == _component_projection(nr)
    assert tr["counters"]["outer"]["changes"] == 1
    assert nr["counters"]["outer"]["matched_parent_noops"] == 1
    assert tr["counters"]["outer"]["attacker_triggers"] == 1
    assert tr["counters"]["outer"]["defender_triggers"] == 0
    assert tr["counters"]["v3_pair_cap"]["triggers"] == 1
    assert tr["counters"]["v1_pair_aware"]["triggers"] == 0
    assert tr["counters"]["v3_pair_aware"]["triggers"] == 1


def test_defender_declines_incremental_rule_but_preserves_v1():
    rnd = _pair_cap_only_state()
    rnd.banker = 0
    assert not rnd.is_attacker(0)
    treatment = PairCapAttackerIncrementalRolloutPolicy(
        apply_incremental=True)
    parent_null = PairCapAttackerIncrementalRolloutPolicy(
        apply_incremental=False)
    assert treatment.decide_play(copy.deepcopy(rnd), 0) == \
        parent_null.decide_play(copy.deepcopy(rnd), 0) == ["SA"]
    telemetry = treatment.pair_cap_incremental_telemetry()["counters"]
    assert telemetry["outer"]["triggers"] == 0
    assert telemetry["v3_pair_cap"]["triggers"] == 0

    # A public global-boss proof remains the reviewed v1 behavior in both
    # roles and in both incremental arms.
    rnd.history[0].plays[-1].cards = ["DK", "DA"]
    rnd.hands[0] = ["DQ", "DQ", "SA", "C3", "C4"]
    expected = PairAwareRolloutPolicy(apply_treatment=True).decide_play(
        copy.deepcopy(rnd), 0)
    assert expected == ["DQ", "DQ"]
    a = PairCapAttackerIncrementalRolloutPolicy(apply_incremental=True)
    b = PairCapAttackerIncrementalRolloutPolicy(apply_incremental=False)
    assert a.decide_play(copy.deepcopy(rnd), 0) == \
        b.decide_play(copy.deepcopy(rnd), 0) == expected
    counters = a.pair_cap_incremental_telemetry()["counters"]
    assert counters["v1_pair_aware"]["triggers"] == 1
    assert counters["v3_pair_aware"]["triggers"] == 1
    assert counters["v3_pair_cap"]["triggers"] == 0


def test_factory_names_three_predeclared_roles_and_preserves_root_ballot():
    assert PAIR_CAP_INCREMENTAL_POLICIES == {
        "base": "mc-s0-report-lcb",
        "treatment": "mc-s0-report-lcb-pair-cap-attacker-incremental",
        "matched_parent": "mc-s0-report-lcb-pair-aware-parent-null",
        "literal_champion": "mc-s0-report-lcb",
    }
    champion = make_bot("mc-s0-report-lcb", seed=73)
    treatment = make_pair_cap_incremental_bot(treatment=True, seed=73)
    parent_null = make_pair_cap_incremental_bot(treatment=False, seed=73)
    assert type(champion.rollout_policy) is HeuristicBot
    assert type(treatment) is type(parent_null)
    assert treatment.rng.getstate() == parent_null.rng.getstate() == \
        champion.rng.getstate()
    assert mc_ballot(treatment).digest == mc_ballot(parent_null).digest == \
        mc_ballot(champion).digest

    witness = _pair_cap_only_state()
    # Root behavior remains the literal champion; only simulated continuation
    # leads see the incremental treatment.
    assert treatment._lead(witness, 0) == parent_null._lead(witness, 0)
    assert treatment.rollout_policy.decide_play(
        copy.deepcopy(witness), 0) == ["D5", "D5"]
    assert parent_null.rollout_policy.decide_play(
        copy.deepcopy(witness), 0) == ["SA"]


def test_literal_champion_has_no_incremental_hook():
    champion = make_bot(PAIR_CAP_INCREMENTAL_POLICIES["literal_champion"],
                        seed=11)
    assert not hasattr(champion, "pair_cap_incremental_telemetry")
    assert "pair_cap_incremental_rollout_telemetry" not in \
        (champion.last_decision_record or {})

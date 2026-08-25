"""Pure witnesses for the closed PT1 state-level statistical reduction."""

from __future__ import annotations

import copy
import hashlib
import random
from dataclasses import replace
from fractions import Fraction

import pytest

from shengji.engine.cards import Ordering, make_deck
from shengji.engine.round import Round, Trick
from shengji.rl import privileged_teacher_pt1 as pt1
from shengji.rl import privileged_teacher_pt1_natural as natural
from shengji.rl.privileged_teacher_pt1_statistics import (
    BOOTSTRAP_REPLICATES, POLICY_SEEDS, PT1StatisticsError,
    PASS_STATUS, REFUSED_STATUS, TOTAL_RECORD_COUNT,
    reduce_pt1_statistics, verify_statistics_report,
)


SECRET = bytes(range(32))
SECRET_SHA = hashlib.sha256(SECRET).hexdigest()


def _design() -> natural.NaturalPT1Design:
    return natural.NaturalPT1Design(capture_secret_sha256=SECRET_SHA)


def _round(rank: str, banker: int, role: str, threshold: int,
           *, hidden: int) -> Round:
    deck = make_deck()
    actor = banker if role == "banker-team" else (banker + 1) % 4
    hands = [[deck[(seat * 10 + index + hidden) % len(deck)]
              for index in range(threshold)] for seat in range(4)]
    rnd = Round(rank, banker=banker, rng=random.Random(hidden))
    rnd.phase = "play"
    rnd.ordering = Ordering("H", rank)
    rnd.trump_suit = "H"
    rnd.trump_is_nt = False
    rnd.hands = hands
    rnd.buried = [deck[100], deck[101]]
    rnd.trick = Trick(leader=actor)
    rnd.turn = actor
    rnd.deck = deck
    return rnd


def _population():
    design = _design()
    population = {}
    for index, (rank, banker, role, threshold, replicate) in enumerate(
            design.state_keys):
        rnd = _round(rank, banker, role, threshold, hidden=index % 3)
        # Keep the synthetic fixtures' public identities distinct across the
        # four replicate rows and all 416 cells.
        rnd.attacker_points = index
        population[(rank, banker, role, threshold, replicate)] = \
            natural._state_from_round(
                design, rnd, rank=rank, banker=banker, role=role,
                threshold=threshold, replicate=replicate,
                round_seed=index + 1)
    return design, population


def _record_for(state, seed: int, *, cb: int = 1, ba: int = 0,
                c_action=("C4",)) -> pt1.PT1Record:
    ballot = (("C4",), ("D4",))
    a_value = 0
    b_value = a_value + ba
    c_value = b_value + cb
    utilities = (ballot[0], c_value), (ballot[1], 0)
    points = (ballot[0], 80), (ballot[1], 80)
    evaluator = pt1._evaluator_identity(
        state.public_state_sha256, state.true_world_sha256,
        utilities, points, 0, 0)
    work = pt1.WorkReceipt(30, 300, 1, 30, 1, 300, 1,
                           900, 900, 0, 0, 1)
    arms = tuple(pt1.ArmDecision(
        name, (c_action if name == "C" else ("D4",)), ballot,
        state.public_state_sha256, state.true_world_sha256,
        pt1.PRODUCTION_POLICY if name != "C" else "ExactWorldSession",
        seed, work, evaluator) for name in ("A", "B", "C"))
    return pt1.PT1Record(
        hashlib.sha256(f"{state.capture_id_sha256}:{seed}".encode()).hexdigest(),
        state.public_state_sha256, state.true_world_sha256, ballot, arms,
        (("A", a_value), ("B", b_value), ("C", c_value)),
        (("A", 80), ("B", 80), ("C", 80)), utilities, points, evaluator,
        0, pt1.AUTHORITY)


def _records(design, population, *, cb: int = 1, ba: int = 0):
    return [_record_for(population[key], seed, cb=cb, ba=ba)
            for key in design.state_keys for seed in POLICY_SEEDS]


def test_exact_416_by_four_reduction_and_strata_are_canonical():
    design, population = _population()
    records = _records(design, population)
    report = reduce_pt1_statistics(design, population, records)
    assert report.state_count == 416
    assert report.record_count == TOTAL_RECORD_COUNT == 1664
    assert report.seeds == POLICY_SEEDS
    assert report.mean_cb == Fraction(1)
    assert report.bootstrap_replicates == BOOTSTRAP_REPLICATES
    assert report.status == PASS_STATUS
    assert {row.dimension for row in report.strata} == {
        "trump_rank", "role", "remaining_hand_threshold"}
    assert verify_statistics_report(report.canonical_bytes(), design=design) == report


def test_fixed_seed_bootstrap_and_report_bytes_are_deterministic():
    design, population = _population()
    records = _records(design, population)
    first = reduce_pt1_statistics(design, population, records)
    second = reduce_pt1_statistics(design, population, records)
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.bootstrap_lcb_cb == second.bootstrap_lcb_cb


def test_record_seed_drop_duplicate_and_state_swaps_refuse():
    design, population = _population()
    records = _records(design, population)
    with pytest.raises(PT1StatisticsError, match="exactly 1664"):
        reduce_pt1_statistics(design, population, records[:-1])
    duplicate = list(records)
    duplicate[1] = duplicate[0]
    with pytest.raises(PT1StatisticsError, match="policy seed"):
        reduce_pt1_statistics(design, population, duplicate)
    swapped = dict(population)
    first, second = design.state_keys[:2]
    swapped[first], swapped[second] = swapped[second], swapped[first]
    with pytest.raises(PT1StatisticsError):
        reduce_pt1_statistics(design, swapped, records)


def test_415_and_417_population_rows_refuse_before_statistics():
    design, population = _population()
    records = _records(design, population)
    short = dict(population)
    short.pop(design.state_keys[-1])
    with pytest.raises(PT1StatisticsError, match="population integrity"):
        reduce_pt1_statistics(design, short, records)
    extra = dict(population)
    extra[("2", 0, "banker-team", 3, 99)] = population[design.state_keys[0]]
    with pytest.raises(PT1StatisticsError, match="population integrity"):
        reduce_pt1_statistics(design, extra, records)


def test_gate_failures_include_negative_sign_and_fixed_seed_refusal():
    design, population = _population()
    zero = _records(design, population, cb=0)
    report = reduce_pt1_statistics(design, population, zero)
    assert report.status == REFUSED_STATUS
    assert not dict(report.gate_results)["mean_cb_floor"]
    with pytest.raises(PT1StatisticsError, match="fixed seeds"):
        reduce_pt1_statistics(design, population, _records(design, population),
                              seeds=(1, 2, 3, 4))


def test_arm_or_sign_mutation_is_rejected_before_aggregation():
    design, population = _population()
    records = _records(design, population)
    payload = records[0].payload()
    payload["selected_utilities"][0], payload["selected_utilities"][1] = \
        payload["selected_utilities"][1], payload["selected_utilities"][0]
    payload["record_sha256"] = hashlib.sha256(
        natural.canonical_json_bytes({k: payload[k]
            for k in payload if k != "record_sha256"})).hexdigest()
    records[0] = payload
    with pytest.raises(PT1StatisticsError, match="verification"):
        reduce_pt1_statistics(design, population, records)
    bad_regret = _records(design, population)
    bad_regret[0] = replace(bad_regret[0], c_regret=1)
    with pytest.raises(PT1StatisticsError, match="verification"):
        reduce_pt1_statistics(design, population, bad_regret)


def test_report_reopener_rejects_resealed_semantic_mutations():
    design, population = _population()
    report = reduce_pt1_statistics(design, population, _records(design, population))
    mutated = replace(report, mean_cb=Fraction(2))
    with pytest.raises(PT1StatisticsError, match="mean C-B"):
        verify_statistics_report(mutated, design=design)
    mutated = replace(report, state_statistics=tuple(
        reversed(report.state_statistics)))
    with pytest.raises(PT1StatisticsError, match="state order"):
        verify_statistics_report(mutated, design=design)
    payload = report.payload()
    payload["gate_results"]["mean_cb_floor"] = False
    payload["report_sha256"] = hashlib.sha256(
        natural.canonical_json_bytes({k: payload[k]
            for k in payload if k != "report_sha256"})).hexdigest()
    with pytest.raises(PT1StatisticsError, match="gate"):
        verify_statistics_report(payload, design=design)

"""Inspectable REF-C suit, shape, and point marginal tests."""

from __future__ import annotations

import copy
import random
from dataclasses import replace

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.point_context import EFF_SUITS
from shengji.engine.game import Game
from shengji.engine.round import actual_play_after
from shengji.rl.belief_contract import PublicTranscriptV1
from shengji.rl.belief_marginals import (
    INFORMATION_TAG,
    BeliefMarginalsError,
    build_belief_marginals,
    validate_belief_marginals,
)
from shengji.rl.belief_ownership import PROBABILITY_SCALE
from shengji.rl.belief_refc_capture import capture_ref_c_worlds


def _state(seed=9951, plays=5):
    rnd = Game(random.Random(seed)).start_round()
    bot = HeuristicBot()
    transcript = PublicTranscriptV1()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bot.decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
            accepted = rnd.declaration
            transcript = transcript.with_declaration(
                accepted["seat"], accepted["cards"], accepted["strength"])
    for seat in range(4):
        cards = bot.decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
            accepted = rnd.declaration
            transcript = transcript.with_declaration(
                accepted["seat"], accepted["cards"], accepted["strength"])
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    for _ in range(plays):
        seat = rnd.turn
        attempted = bot.decide_play(rnd, seat)
        previous_last = rnd.last_trick
        rnd.play(seat, attempted)
        transcript = transcript.with_play(
            seat, attempted, actual_play_after(rnd, seat, previous_last))
    return rnd, transcript


def _swap_equal_hidden_hands(rnd):
    changed = copy.deepcopy(rnd)
    actor_seat = rnd.turn
    hidden = [seat for seat in range(4) if seat != actor_seat]
    left, right = next(
        (left, right) for index, left in enumerate(hidden)
        for right in hidden[index + 1:]
        if len(changed.hands[left]) == len(changed.hands[right]))
    changed.hands[left], changed.hands[right] = (
        changed.hands[right], changed.hands[left])
    return changed


def test_ref_c_marginals_are_exact_inspectable_and_conservative(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rnd, transcript = _state()
    batch = capture_ref_c_worlds(
        rnd, rnd.turn, transcript, sampler_seed=1103)
    report = build_belief_marginals(batch)
    validate_belief_marginals(batch, report)
    assert report.information_tag == INFORMATION_TAG
    assert report.sampled_hidden_worlds_consumed is True
    assert report.privileged_targets_consumed is False
    assert report.actor_observation_sha256 == batch.actor.sha256()
    assert report.world_batch_manifest_sha256 == batch.manifest_sha256()
    assert report.sample_count == 256
    assert tuple(receiver.receiver for receiver in report.receivers) \
        == tuple(receiver for receiver, _ in batch.ownership().receiver_sizes)
    for receiver in report.receivers:
        assert tuple(row.effective_suit for row in receiver.effective_suits) \
            == EFF_SUITS
        for row in receiver.effective_suits:
            for distribution in (
                    row.length, row.pair_count, row.max_pair_run,
                    row.top_level, row.point_count):
                assert sum(probability for _, probability
                           in distribution.probabilities_ppb) \
                    == PROBABILITY_SCALE
        assert sum(row.length.expected_value_ppb
                   for row in receiver.effective_suits) \
            == receiver.card_count * PROBABILITY_SCALE

    assert sum(receiver.total_point_count.expected_value_ppb
               for receiver in report.receivers) \
        == report.points_left_total * PROBABILITY_SCALE
    for suit_index, (_, public_points) in enumerate(
            report.points_left_by_suit):
        assert sum(receiver.effective_suits[
            suit_index].point_count.expected_value_ppb
                   for receiver in report.receivers) \
            == public_points * PROBABILITY_SCALE
    raw = report.canonical_bytes()
    assert b'"target"' not in raw
    assert b'"contains_round_outcome"' not in raw


def test_ref_c_public_twins_have_identical_marginal_reports(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rnd, transcript = _state(9953)
    changed = _swap_equal_hidden_hands(rnd)
    first = capture_ref_c_worlds(
        rnd, rnd.turn, transcript, sampler_seed=1117)
    second = capture_ref_c_worlds(
        changed, changed.turn, transcript, sampler_seed=1117)
    assert build_belief_marginals(first).canonical_bytes() \
        == build_belief_marginals(second).canonical_bytes()


def test_marginal_validator_refuses_derived_and_distribution_drift(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rnd, transcript = _state(9967)
    batch = capture_ref_c_worlds(
        rnd, rnd.turn, transcript, sampler_seed=1123)
    report = build_belief_marginals(batch)
    with pytest.raises(BeliefMarginalsError, match="derivation drift"):
        validate_belief_marginals(
            batch, replace(report,
                           points_left_total=report.points_left_total + 1))
    receiver = report.receivers[0]
    suit = receiver.effective_suits[0]
    distribution = suit.length
    rows = list(distribution.probabilities_ppb)
    left = next(index for index, (_, probability) in enumerate(rows)
                if probability)
    right = next(index for index in range(len(rows)) if index != left)
    rows[left] = (rows[left][0], rows[left][1] - 1)
    rows[right] = (rows[right][0], rows[right][1] + 1)
    changed_distribution = replace(
        distribution, probabilities_ppb=tuple(rows))
    changed_suit = replace(suit, length=changed_distribution)
    changed_receiver = replace(
        receiver,
        effective_suits=(changed_suit, *receiver.effective_suits[1:]))
    with pytest.raises(BeliefMarginalsError, match="derivation drift"):
        validate_belief_marginals(
            batch, replace(report,
                           receivers=(changed_receiver, *report.receivers[1:])))

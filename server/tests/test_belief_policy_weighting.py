"""R4 opened-DEV world-weight bridge witnesses."""

from __future__ import annotations

import copy
import math
import random
from dataclasses import replace

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.engine.round import actual_play_after
from shengji.rl.belief_contract import (
    PublicTranscriptV1,
    build_actor_observation,
    build_belief_targets,
)
from shengji.rl.belief_ownership import KITTY_RECEIVER
from shengji.rl.belief_policy_weighting import (
    PPB,
    BeliefPolicyWeightingError,
    adapt_proposal_ownership_to_v2,
    common_tempered_world_weights,
    weighted_mean_and_se,
    world_log_ratio_nanonats,
)
from shengji.rl.belief_reference import (
    REF_C_WORLD_COUNT,
    ReceiverCardsV1,
    SampledOwnershipWorldV1,
    reference_ownership,
)


def _state(seed: int = 19101):
    rnd = Game(random.Random(seed)).start_round()
    bot = HeuristicBot()
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    transcript = PublicTranscriptV1()
    seat = rnd.turn
    attempted = bot.decide_play(rnd, seat)
    previous = rnd.last_trick
    rnd.play(seat, attempted)
    transcript = transcript.with_play(
        seat, attempted, actual_play_after(rnd, seat, previous))
    actor = build_actor_observation(rnd, rnd.turn, transcript)
    return rnd, actor, transcript


def _world(rnd, actor):
    target = build_belief_targets(rnd, rnd.turn)
    rows = [ReceiverCardsV1(
        receiver=f"seat-relative-{hand.seat_relative}", cards=hand.cards)
        for hand in target.other_hands]
    if actor.hidden_burial_size:
        rows.append(ReceiverCardsV1(
            receiver=KITTY_RECEIVER, cards=target.hidden_burial))
    return SampledOwnershipWorldV1(
        actor_observation_sha256=actor.sha256(), receivers=tuple(rows))


def _hidden_twin(rnd, actor, transcript):
    changed = copy.deepcopy(rnd)
    hidden = [seat for seat in range(4) if seat != rnd.turn]
    left, right = next(
        (left, right) for index, left in enumerate(hidden)
        for right in hidden[index + 1:]
        if len(changed.hands[left]) == len(changed.hands[right]))
    changed.hands[left], changed.hands[right] = (
        changed.hands[right], changed.hands[left])
    twin_actor = build_actor_observation(changed, rnd.turn, transcript)
    assert twin_actor.canonical_bytes() == actor.canonical_bytes()
    return changed, _world(changed, twin_actor)


def _adapt(belief, actor):
    return adapt_proposal_ownership_to_v2(
        actor, belief,
        behavior_policy_ids=belief.behavior_policy_ids,
    )


def test_marginal_ratio_prefers_world_supported_by_candidate():
    rnd, actor, transcript = _state()
    first = _world(rnd, actor)
    _, second = _hidden_twin(rnd, actor, transcript)
    reference = _adapt(reference_ownership(
        actor, (first,) * 128 + (second,) * 128,
        sampler_source_sha256="a" * 64,
        behavior_policy_ids=("mc-s0-report-lcb",)), actor)
    candidate = _adapt(reference_ownership(
        actor, (first,) * 224 + (second,) * 32,
        sampler_source_sha256="b" * 64,
        behavior_policy_ids=("mc-s0-report-lcb",)), actor)
    scores = world_log_ratio_nanonats(
        actor, candidate, reference, (first, second))
    assert scores[0] > scores[1]


def test_common_temperature_is_limited_by_more_concentrated_control():
    primary, control = common_tempered_world_weights(
        (0,) * 30,
        (100_000_000_000,) + (0,) * 29,
    )
    assert primary.alpha_ppb == control.alpha_ppb
    assert primary.alpha_ppb < PPB
    assert primary.ess_ppb >= 30 * 500_000_000
    assert control.ess_ppb >= 30 * 500_000_000
    assert max(control.normalized_weight_ppb) * 30 <= 4 * PPB
    # The common rule also tempers the otherwise-uniform primary arm; callers
    # cannot choose a favorable temperature separately for each cohort.
    assert len(set(primary.normalized_weight_ppb)) <= 2


def test_uniform_weighted_moments_match_sample_mean_standard_error():
    weights = (250_000_000,) * 4
    mean, se = weighted_mean_and_se((1.0, 2.0, 3.0, 4.0), weights)
    assert mean == pytest.approx(2.5)
    assert se == pytest.approx(math.sqrt((5.0 / 3.0) / 4.0))


def test_world_actor_drift_refuses_before_weighting():
    rnd, actor, _ = _state(19103)
    world = _world(rnd, actor)
    belief = _adapt(reference_ownership(
        actor, (world,) * REF_C_WORLD_COUNT,
        sampler_source_sha256="c" * 64,
        behavior_policy_ids=("mc-s0-report-lcb",)), actor)
    forged = replace(world, actor_observation_sha256="0" * 64)
    with pytest.raises(BeliefPolicyWeightingError, match="mechanics refused"):
        world_log_ratio_nanonats(
            actor, belief, belief, (forged,))


def test_weight_vector_input_and_probability_population_are_strict():
    with pytest.raises(BeliefPolicyWeightingError, match="score population"):
        common_tempered_world_weights((0,), (0, 1))
    with pytest.raises(BeliefPolicyWeightingError, match="moment population"):
        weighted_mean_and_se((1.0, 2.0), (PPB,))

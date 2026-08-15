"""Exact REF-C sampled-world and empirical-probability tests."""

from __future__ import annotations

import copy
import random
from collections import Counter
from dataclasses import replace

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.combos import decompose
from shengji.engine.game import Game
from shengji.engine.round import actual_play_after
from shengji.rl.belief_contract import (
    DeclarationEligibilityV1,
    PublicTranscriptV1,
    build_actor_observation,
    build_belief_targets,
)
from shengji.rl.belief_ownership import (
    KITTY_RECEIVER,
    count_brier_fraction,
    receiver_sizes,
)
from shengji.rl.belief_reference import (
    REF_C_MODEL_SCHEMA,
    REF_C_WORLD_COUNT,
    BeliefReferenceError,
    ReceiverCardsV1,
    SampledOwnershipWorldV1,
    reference_ownership,
    validate_sampled_world,
)


def _state(seed=9701):
    rnd = Game(random.Random(seed)).start_round()
    bot = HeuristicBot()
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    transcript = PublicTranscriptV1()
    seat = rnd.turn
    attempted = bot.decide_play(rnd, seat)
    previous_last = rnd.last_trick
    rnd.play(seat, attempted)
    transcript = transcript.with_play(
        seat, attempted, actual_play_after(rnd, seat, previous_last))
    actor = build_actor_observation(rnd, rnd.turn, transcript)
    target = build_belief_targets(rnd, rnd.turn)
    return rnd, actor, target, transcript


def _world(actor, target):
    rows = []
    for hand in target.other_hands:
        rows.append(ReceiverCardsV1(
            receiver=f"seat-relative-{hand.seat_relative}",
            cards=hand.cards,
        ))
    if actor.hidden_burial_size:
        rows.append(ReceiverCardsV1(
            receiver=KITTY_RECEIVER,
            cards=target.hidden_burial,
        ))
    return SampledOwnershipWorldV1(
        actor_observation_sha256=actor.sha256(),
        receivers=tuple(rows),
    )


def _counts(actor, world):
    counts = {
        (card, receiver): 0
        for card, _ in actor.deductions.unseen
        for receiver, _ in receiver_sizes(actor)
    }
    counts.update({
        (card, row.receiver): count
        for row in world.receivers
        for card, count in row.cards
    })
    return counts


def _swap_hidden_hands(rnd, actor_seat):
    changed = copy.deepcopy(rnd)
    hidden = [seat for seat in range(4) if seat != actor_seat]
    left, right = next(
        (left, right) for index, left in enumerate(hidden)
        for right in hidden[index + 1:]
        if len(changed.hands[left]) == len(changed.hands[right]))
    changed.hands[left], changed.hands[right] = (
        changed.hands[right], changed.hands[left])
    return changed


def test_truth_reference_is_exact_and_scores_zero():
    _, actor, target, _ = _state()
    world = _world(actor, target)
    validate_sampled_world(actor, world)
    belief = reference_ownership(
        actor, (world,) * REF_C_WORLD_COUNT,
        sampler_source_sha256="a" * 64,
        behavior_policy_ids=("mc-s0-report-lcb",),
    )
    assert belief.model_schema == REF_C_MODEL_SCHEMA
    assert belief.model_sha256 == "a" * 64
    assert count_brier_fraction(belief, _counts(actor, world))[0] == 0


def test_public_twin_two_world_mixture_has_exact_empirical_counts():
    rnd, actor, target, transcript = _state(9703)
    first = _world(actor, target)
    changed = _swap_hidden_hands(rnd, rnd.turn)
    changed_actor = build_actor_observation(changed, rnd.turn, transcript)
    assert changed_actor.canonical_bytes() == actor.canonical_bytes()
    second = _world(changed_actor, build_belief_targets(changed, rnd.turn))
    worlds = (first,) * 128 + (second,) * 128
    belief = reference_ownership(
        actor, worlds, sampler_source_sha256="b" * 64,
        behavior_policy_ids=("mc-s0-report-lcb",),
    )
    reference_ownership(
        changed_actor, worlds, sampler_source_sha256="b" * 64,
        behavior_policy_ids=("mc-s0-report-lcb",),
    )
    first_counts = _counts(actor, first)
    second_counts = _counts(actor, second)
    changed_key = next(key for key, value in first_counts.items()
                       if value != second_counts[key])
    card, receiver = changed_key
    row = next(row for row in belief.probabilities
               if row.card == card and row.receiver == receiver)
    histogram = Counter((first_counts[changed_key],
                         second_counts[changed_key]))
    assert [row.count_0_ppb, row.count_1_ppb, row.count_2_ppb] == [
        histogram[count] * 500_000_000 for count in range(3)]


def test_world_refuses_receiver_card_and_hard_constraint_drift():
    _, actor, target, _ = _state(9709)
    world = _world(actor, target)
    with pytest.raises(BeliefReferenceError, match="actor/schema"):
        validate_sampled_world(actor, replace(
            world, actor_observation_sha256="0" * 64))
    with pytest.raises(BeliefReferenceError, match="population/order"):
        validate_sampled_world(actor, replace(
            world, receivers=tuple(reversed(world.receivers))))

    row = world.receivers[0]
    card, count = row.cards[0]
    changed_cards = ((card, count + 1), *row.cards[1:])
    with pytest.raises(BeliefReferenceError, match="receiver cards|size|unseen"):
        validate_sampled_world(actor, replace(
            world, receivers=(replace(row, cards=changed_cards),
                              *world.receivers[1:])))
    with pytest.raises(BeliefReferenceError, match="receiver cards"):
        validate_sampled_world(actor, replace(
            world, receivers=(replace(row, cards=((1, 1), *row.cards[1:])),
                              *world.receivers[1:])))

    relative = 1
    receiver = "seat-relative-1"
    counts = dict(world.receivers[0].cards)
    card = next(iter(counts))
    from shengji.engine.cards import Ordering
    suit = Ordering(actor.trump_suit, actor.trump_rank).eff_suit(card)
    voids = list(actor.deductions.voids_by_relative)
    voids[relative] = tuple(sorted({*voids[relative], suit}))
    void_actor = replace(actor, deductions=replace(
        actor.deductions, voids_by_relative=tuple(voids)))
    rebound = replace(world, actor_observation_sha256=void_actor.sha256())
    assert rebound.receivers[0].receiver == receiver
    with pytest.raises(BeliefReferenceError, match="proven void"):
        validate_sampled_world(void_actor, rebound)

    ordering = Ordering(actor.trump_suit, actor.trump_rank)
    pair_fixture = None
    for relative, receiver_row in enumerate(world.receivers[:3], start=1):
        cards_by_suit = {}
        for current_card, current_count in receiver_row.cards:
            cards_by_suit.setdefault(ordering.eff_suit(current_card), {})[
                current_card] = current_count
        for current_suit, current_counts in cards_by_suit.items():
            pairs = sum(value // 2 for value in current_counts.values())
            if pairs:
                pair_fixture = relative, current_suit, pairs
                break
        if pair_fixture is not None:
            break
    assert pair_fixture is not None
    relative, pair_suit, pair_count = pair_fixture
    pair_caps = list(actor.deductions.pair_caps_by_relative)
    caps = dict(pair_caps[relative])
    caps[pair_suit] = pair_count - 1
    pair_caps[relative] = tuple(sorted(caps.items()))
    capped_actor = replace(actor, deductions=replace(
        actor.deductions, pair_caps_by_relative=tuple(pair_caps)))
    rebound = replace(world, actor_observation_sha256=capped_actor.sha256())
    with pytest.raises(BeliefReferenceError, match="proven pair cap"):
        validate_sampled_world(capped_actor, rebound)

    receiver_row = world.receivers[relative - 1]
    suited_cards = [
        current_card
        for current_card, current_count in receiver_row.cards
        for _ in range(current_count)
        if ordering.eff_suit(current_card) == pair_suit
    ]
    run_count = decompose(suited_cards, ordering).max_pair_run()
    assert run_count > 0
    run_caps = list(actor.deductions.run_caps_by_relative)
    caps = dict(run_caps[relative])
    caps[pair_suit] = run_count - 1
    run_caps[relative] = tuple(sorted(caps.items()))
    capped_actor = replace(actor, deductions=replace(
        actor.deductions, run_caps_by_relative=tuple(run_caps)))
    rebound = replace(world, actor_observation_sha256=capped_actor.sha256())
    with pytest.raises(BeliefReferenceError, match="proven run cap"):
        validate_sampled_world(capped_actor, rebound)

    pinned_card = world.receivers[0].cards[0][0]
    absent_relative = next(
        current_relative
        for current_relative, current_row in enumerate(
            world.receivers[:3], start=1)
        if dict(current_row.cards).get(pinned_card, 0) == 0
    )
    pinned_actor = replace(actor, deductions=replace(
        actor.deductions,
        declaration_pins=((pinned_card, absent_relative, 1),),
    ))
    rebound = replace(world, actor_observation_sha256=pinned_actor.sha256())
    with pytest.raises(BeliefReferenceError, match="declaration pin"):
        validate_sampled_world(pinned_actor, rebound)

    # A banker declaration is a group constraint, not a hand pin.  Move the
    # shown copy from banker/kitty to an unrelated receiver while swapping a
    # second card back.  Population, receiver sizes, and per-card conservation
    # stay exact; only declaration eligibility changes.
    _, actor, target, _ = _state(9717)
    world = _world(actor, target)
    counters = {
        row.receiver: Counter(dict(row.cards)) for row in world.receivers
    }
    group = (f"seat-relative-{actor.banker_relative}", KITTY_RECEIVER)
    declared = next(
        card for card, _ in actor.deductions.unseen
        if sum(counters[receiver][card] for receiver in group) == 1
    )
    constraint = DeclarationEligibilityV1(
        card=declared, eligible_receivers=group, minimum_copies=1)
    clean = replace(actor, deductions=replace(
        actor.deductions,
        voids_by_relative=((), (), (), ()),
        pair_caps_by_relative=((), (), (), ()),
        run_caps_by_relative=((), (), (), ()),
        declaration_pins=(),
        declaration_eligibility=(constraint,),
    ))
    world = replace(world, actor_observation_sha256=clean.sha256())
    source = next(receiver for receiver in group
                  if counters[receiver][declared] > 0)
    outside = next(
        receiver for receiver in counters
        if receiver not in group and counters[receiver][declared] == 0
    )
    exchange = next(
        card for card, count in counters[outside].items()
        if count > 0 and counters[source][card] == 0
    )
    counters[source][declared] -= 1
    counters[outside][declared] += 1
    counters[outside][exchange] -= 1
    counters[source][exchange] += 1
    changed = replace(world, receivers=tuple(
        ReceiverCardsV1(
            receiver=row.receiver,
            cards=tuple(sorted((card, count)
                               for card, count
                               in counters[row.receiver].items()
                               if count)),
        )
        for row in world.receivers
    ))
    with pytest.raises(
            BeliefReferenceError,
            match="declaration eligibility"):
        validate_sampled_world(clean, changed)


@pytest.mark.parametrize("world_count", [0, 1, 255, 257])
def test_reference_requires_fixed_world_count_and_source_identity(world_count):
    _, actor, target, _ = _state(9719)
    world = _world(actor, target)
    with pytest.raises(BeliefReferenceError, match="exactly 256"):
        reference_ownership(
            actor, (world,) * world_count,
            sampler_source_sha256="c" * 64,
            behavior_policy_ids=("mc-s0-report-lcb",),
        )
    if world_count == 0:
        with pytest.raises(BeliefReferenceError, match="source identity"):
            reference_ownership(
                actor, (world,) * REF_C_WORLD_COUNT,
                sampler_source_sha256="not-a-sha",
                behavior_policy_ids=("mc-s0-report-lcb",),
            )

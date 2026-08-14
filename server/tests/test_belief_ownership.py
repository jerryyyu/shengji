"""Synthetic mechanics and leakage tests for BELIEF-V1 ownership output."""

from __future__ import annotations

import copy
import json
import random
from collections import Counter
from dataclasses import replace

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.engine.cards import Ordering
from shengji.engine.round import actual_play_after
from shengji.rl.belief_contract import (
    BeliefTargetsV1,
    PublicTranscriptV1,
    build_actor_observation,
    build_belief_targets,
)
from shengji.rl.belief_ownership import (
    KITTY_RECEIVER,
    PROBABILITY_SCALE,
    SEAT_RECEIVERS,
    BeliefOwnershipError,
    BeliefOwnershipV1,
    ReceiverCountProbabilityV1,
    count_brier_fraction,
    ownership_from_bytes,
    receiver_sizes,
    validate_ownership,
)


def _state(seed: int = 9323):
    game = Game(random.Random(seed))
    rnd = game.start_round()
    bot = HeuristicBot()
    while rnd.phase == "deal":
        rnd.deal_next()
    # Deliberately retain no declaration so hidden-hand permutations stay in
    # the same hard-constraint information set.
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    transcript = PublicTranscriptV1()
    first = rnd.turn
    attempted = bot.decide_play(rnd, first)
    previous_last = rnd.last_trick
    rnd.play(first, attempted)
    transcript = transcript.with_play(
        first, attempted, actual_play_after(rnd, first, previous_last))
    actor = build_actor_observation(rnd, rnd.turn, transcript)
    target = build_belief_targets(rnd, rnd.turn)
    return rnd, actor, target, transcript


def _late_state_with_capacity_one(seed: int = 9301):
    """Return a fixed public state with one one-card hidden receiver."""
    game = Game(random.Random(seed))
    rnd = game.start_round()
    bot = HeuristicBot()
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    transcript = PublicTranscriptV1()
    while rnd.phase == "play" and min(map(len, rnd.hands)) > 1:
        seat = rnd.turn
        attempted = bot.decide_play(rnd, seat)
        previous_last = rnd.last_trick
        rnd.play(seat, attempted)
        transcript = transcript.with_play(
            seat, attempted, actual_play_after(rnd, seat, previous_last))
    actor = build_actor_observation(rnd, rnd.turn, transcript)
    target = build_belief_targets(rnd, rnd.turn)
    assert ("seat-relative-3", 1) in receiver_sizes(actor)
    return actor, target


def _target_counts(actor, target: BeliefTargetsV1):
    result = {
        (card, receiver): 0
        for card, _ in actor.deductions.unseen
        for receiver, _ in receiver_sizes(actor)
    }
    for hand in target.other_hands:
        receiver = f"seat-relative-{hand.seat_relative}"
        for card, count in hand.cards:
            result[(card, receiver)] = count
    for card, count in target.hidden_burial:
        result[(card, KITTY_RECEIVER)] = count
    return result


def _belief(actor, worlds: list[dict[tuple[str, str], int]]):
    assert PROBABILITY_SCALE % len(worlds) == 0
    unit = PROBABILITY_SCALE // len(worlds)
    rows = []
    for card, _ in actor.deductions.unseen:
        for receiver, _ in receiver_sizes(actor):
            histogram = Counter(world[(card, receiver)] for world in worlds)
            rows.append(ReceiverCountProbabilityV1(
                card=card,
                receiver=receiver,
                count_0_ppb=histogram[0] * unit,
                count_1_ppb=histogram[1] * unit,
                count_2_ppb=histogram[2] * unit,
            ))
    return BeliefOwnershipV1(
        actor_observation_sha256=actor.sha256(),
        model_schema="synthetic-two-world-mixture-v1",
        model_sha256="a" * 64,
        behavior_policy_ids=("heuristic",),
        receiver_sizes=receiver_sizes(actor),
        probabilities=tuple(rows),
    )


def _swap_two_hidden_hands(rnd, actor_seat):
    changed = copy.deepcopy(rnd)
    hidden = [seat for seat in range(4) if seat != actor_seat]
    pair = next((left, right) for index, left in enumerate(hidden)
                for right in hidden[index + 1:]
                if len(changed.hands[left]) == len(changed.hands[right]))
    changed.hands[pair[0]], changed.hands[pair[1]] = (
        changed.hands[pair[1]], changed.hands[pair[0]])
    return changed


def test_truth_and_two_world_mixture_satisfy_exact_conservation():
    rnd, actor, target, transcript = _state()
    first_counts = _target_counts(actor, target)
    changed = _swap_two_hidden_hands(rnd, rnd.turn)
    changed_actor = build_actor_observation(changed, rnd.turn, transcript)
    assert changed_actor.canonical_bytes() == actor.canonical_bytes()
    second_target = build_belief_targets(changed, rnd.turn)
    second_counts = _target_counts(changed_actor, second_target)

    truth = _belief(actor, [first_counts])
    mixture = _belief(actor, [first_counts, second_counts])
    validate_ownership(actor, truth)
    validate_ownership(actor, mixture)
    validate_ownership(changed_actor, mixture)
    assert changed_actor.sha256() == actor.sha256()
    payload = json.loads(mixture.canonical_bytes())
    assert payload["privileged_targets_consumed"] is False
    assert payload["probability_scale"] == PROBABILITY_SCALE
    assert len(mixture.sha256()) == 64

    truth_score = count_brier_fraction(truth, first_counts)
    mixture_score = count_brier_fraction(mixture, first_counts)
    assert truth_score[0] == 0
    assert mixture_score[0] > 0
    assert truth_score[1] == mixture_score[1]


def test_actor_binding_receiver_population_and_policy_identity_refuse():
    rnd, actor, target, _ = _state(9329)
    belief = _belief(actor, [_target_counts(actor, target)])
    validate_ownership(actor, belief)

    changed_actor = copy.deepcopy(actor)
    object.__setattr__(changed_actor, "attacker_points", actor.attacker_points + 5)
    with pytest.raises(BeliefOwnershipError, match="actor binding"):
        validate_ownership(changed_actor, belief)
    with pytest.raises(BeliefOwnershipError, match="receiver population"):
        validate_ownership(actor, type(belief)(
            **{**belief.__dict__, "receiver_sizes": belief.receiver_sizes[:-1]}))
    with pytest.raises(BeliefOwnershipError, match="policy identity"):
        validate_ownership(actor, type(belief)(
            **{**belief.__dict__, "behavior_policy_ids": ("z", "a")}))

    incomplete = replace(actor, attempted_play_history_complete=False)
    incomplete_belief = _belief(incomplete, [_target_counts(actor, target)])
    with pytest.raises(BeliefOwnershipError, match="complete public history"):
        validate_ownership(incomplete, incomplete_belief)


def test_banker_has_no_hidden_kitty_receiver():
    game = Game(random.Random(9502))
    rnd = game.start_round()
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
    assert rnd.declaration["seat"] == rnd.banker
    assert rnd.declaration["strength"] == 2
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    assert rnd.turn == rnd.banker
    actor = build_actor_observation(rnd, rnd.turn, transcript)
    target = build_belief_targets(rnd, rnd.turn)
    assert actor.hidden_burial_size == 0
    assert actor.actor_known_burial
    assert not actor.deductions.declaration_pins
    assert KITTY_RECEIVER not in dict(receiver_sizes(actor))
    belief = _belief(actor, [_target_counts(actor, target)])
    validate_ownership(actor, belief)

    # Memory intentionally omits the actor's own declaration from hidden-seat
    # pins. A forged relative-zero pin must not create a new receiver class.
    own_card = actor.actor_hand[0][0]
    forged_actor = replace(
        actor,
        deductions=replace(
            actor.deductions,
            declaration_pins=((own_card, 0, True),),
        ),
    )
    forged = _belief(forged_actor, [_target_counts(forged_actor, target)])
    with pytest.raises(BeliefOwnershipError, match="declaration pin is malformed"):
        validate_ownership(forged_actor, forged)


def test_probability_types_scale_population_and_conservation_refuse():
    _, actor, target, _ = _state(9337)
    belief = _belief(actor, [_target_counts(actor, target)])
    rows = list(belief.probabilities)
    row = rows[0]

    rows[0] = type(row)(row.card, row.receiver, True,
                        row.count_1_ppb, row.count_2_ppb)
    with pytest.raises(BeliefOwnershipError, match="probability"):
        validate_ownership(actor, type(belief)(
            **{**belief.__dict__, "probabilities": tuple(rows)}))

    rows = list(belief.probabilities)
    row = rows[0]
    rows[0] = type(row)(row.card, row.receiver,
                        row.count_0_ppb - 1, row.count_1_ppb + 1,
                        row.count_2_ppb)
    with pytest.raises(BeliefOwnershipError, match="conservation"):
        validate_ownership(actor, type(belief)(
            **{**belief.__dict__, "probabilities": tuple(rows)}))

    with pytest.raises(BeliefOwnershipError, match="population/order"):
        validate_ownership(actor, type(belief)(
            **{**belief.__dict__, "probabilities": belief.probabilities[:-1]}))


def test_one_copy_card_pair_mass_guard_has_an_expectation_conserving_witness():
    _, actor, target, _ = _state(9340)
    counts = _target_counts(actor, target)
    belief = _belief(actor, [counts])
    one_copy = next(card for card, copies in actor.deductions.unseen
                    if copies == 1)
    owner = next(receiver for receiver, _ in receiver_sizes(actor)
                 if counts[(one_copy, receiver)] == 1)
    other = next(receiver for receiver, _ in receiver_sizes(actor)
                 if receiver != owner)
    rows = list(belief.probabilities)
    replacements = {
        # The two rows still contribute exactly one expected copy in total,
        # but the second row now has impossible two-copy mass.
        (one_copy, owner): (2, PROBABILITY_SCALE - 2, 0),
        (one_copy, other): (PROBABILITY_SCALE - 1, 0, 1),
    }
    for index, row in enumerate(rows):
        values = replacements.get((row.card, row.receiver))
        if values is not None:
            rows[index] = replace(
                row, count_0_ppb=values[0], count_1_ppb=values[1],
                count_2_ppb=values[2])
    assert sum(row.expected_count_ppb for row in rows
               if row.card == one_copy) == PROBABILITY_SCALE
    with pytest.raises(BeliefOwnershipError,
                       match="one-copy card has two-copy mass"):
        validate_ownership(actor, replace(belief, probabilities=tuple(rows)))


def test_capacity_one_receiver_pair_mass_guard_has_a_direct_witness():
    actor, target = _late_state_with_capacity_one()
    counts = _target_counts(actor, target)
    belief = _belief(actor, [counts])
    receiver = "seat-relative-3"
    pair_card = next(card for card, copies in actor.deductions.unseen
                     if copies == 2 and counts[(card, receiver)] == 0)
    rows = list(belief.probabilities)
    index = next(index for index, row in enumerate(rows)
                 if row.card == pair_card and row.receiver == receiver)
    rows[index] = replace(
        rows[index], count_0_ppb=PROBABILITY_SCALE - 1,
        count_1_ppb=0, count_2_ppb=1)
    with pytest.raises(BeliefOwnershipError,
                       match="receiver capacity forbids two copies"):
        validate_ownership(actor, replace(belief, probabilities=tuple(rows)))


def test_card_expectation_conservation_guard_has_a_probability_valid_witness():
    _, actor, target, _ = _state(9344)
    counts = _target_counts(actor, target)
    belief = _belief(actor, [counts])
    card = next(card for card, copies in actor.deductions.unseen
                if copies == 1)
    empty = next(receiver for receiver, _ in receiver_sizes(actor)
                 if counts[(card, receiver)] == 0)
    rows = list(belief.probabilities)
    index = next(index for index, row in enumerate(rows)
                 if row.card == card and row.receiver == empty)
    rows[index] = replace(
        rows[index], count_0_ppb=PROBABILITY_SCALE - 1,
        count_1_ppb=1)
    with pytest.raises(BeliefOwnershipError,
                       match="card expectation violates conservation"):
        validate_ownership(actor, replace(belief, probabilities=tuple(rows)))


def test_receiver_expectation_conservation_guard_has_a_card_balanced_witness():
    _, actor, target, _ = _state(9346)
    counts = _target_counts(actor, target)
    belief = _belief(actor, [counts])
    card = next(card for card, copies in actor.deductions.unseen
                if copies == 1)
    owner = next(receiver for receiver, _ in receiver_sizes(actor)
                 if counts[(card, receiver)] == 1)
    other = next(receiver for receiver, _ in receiver_sizes(actor)
                 if receiver != owner)
    rows = list(belief.probabilities)
    replacements = {
        (card, owner): (1, PROBABILITY_SCALE - 1, 0),
        (card, other): (PROBABILITY_SCALE - 1, 1, 0),
    }
    for index, row in enumerate(rows):
        values = replacements.get((row.card, row.receiver))
        if values is not None:
            rows[index] = replace(
                row, count_0_ppb=values[0], count_1_ppb=values[1],
                count_2_ppb=values[2])
    assert sum(row.expected_count_ppb for row in rows if row.card == card) \
        == PROBABILITY_SCALE
    with pytest.raises(BeliefOwnershipError,
                       match="receiver expectation violates conservation"):
        validate_ownership(actor, replace(belief, probabilities=tuple(rows)))


def test_proven_void_is_a_probability_one_zero_count():
    fixture = None
    for seed in range(9341, 9441):
        _, actor, target, _ = _state(seed)
        counts = _target_counts(actor, target)
        ordering = Ordering(actor.trump_suit, actor.trump_rank)
        for relative, receiver in enumerate(SEAT_RECEIVERS, start=1):
            held = {
                ordering.eff_suit(card)
                for (card, current), count in counts.items()
                if current == receiver and count
            }
            candidate_suit = next((
                suit for suit in {ordering.eff_suit(card)
                                  for card, _ in actor.deductions.unseen}
                if suit not in held), None)
            if candidate_suit is not None:
                fixture = actor, target, relative, receiver, candidate_suit
                break
        if fixture is not None:
            break
    assert fixture is not None
    actor, target, relative, receiver, void_suit = fixture
    voids = list(actor.deductions.voids_by_relative)
    voids[relative] = tuple(sorted({*voids[relative], void_suit}))
    actor = replace(
        actor,
        deductions=replace(actor.deductions,
                           voids_by_relative=tuple(voids)),
    )
    belief = _belief(actor, [_target_counts(actor, target)])
    validate_ownership(actor, belief)

    rows = list(belief.probabilities)
    index = next(index for index, row in enumerate(rows)
                 if row.receiver == receiver
                 and Ordering(actor.trump_suit, actor.trump_rank).eff_suit(
                     row.card) == void_suit)
    row = rows[index]
    assert row.count_0_ppb == PROBABILITY_SCALE
    other = next(current for current, _ in receiver_sizes(actor)
                 if current != receiver and counts[(row.card, current)] == 1)
    exchange_card = next(
        card for card, _ in actor.deductions.unseen
        if counts[(card, receiver)] == 1 and counts[(card, other)] == 0)
    changes = {
        # Move one ppb of this card into the proven-void receiver.
        (row.card, receiver): (PROBABILITY_SCALE - 1, 1, 0),
        (row.card, other): (1, PROBABILITY_SCALE - 1, 0),
        # Exchange one ppb of another card in the opposite direction so both
        # per-card and per-receiver expectations remain exact.
        (exchange_card, receiver): (1, PROBABILITY_SCALE - 1, 0),
        (exchange_card, other): (PROBABILITY_SCALE - 1, 1, 0),
    }
    for current_index, current_row in enumerate(rows):
        values = changes.get((current_row.card, current_row.receiver))
        if values is not None:
            rows[current_index] = type(current_row)(
                current_row.card, current_row.receiver, *values)
    with pytest.raises(BeliefOwnershipError, match="proven void"):
        validate_ownership(actor, replace(belief, probabilities=tuple(rows)))


def test_single_declaration_is_lower_bound_not_exact_count():
    fixture = None
    for seed in range(9451, 9551):
        game = Game(random.Random(seed))
        rnd = game.start_round()
        bot = HeuristicBot()
        transcript = PublicTranscriptV1()
        while rnd.phase == "deal":
            seat, _, _ = rnd.deal_next()
            cards = bot.decide_declare(rnd, seat)
            if cards:
                rnd.declare(seat, cards)
                accepted = rnd.declaration
                transcript = transcript.with_declaration(
                    accepted["seat"], accepted["cards"],
                    accepted["strength"])
        for seat in range(4):
            cards = bot.decide_declare(rnd, seat, final=True)
            if cards:
                rnd.declare(seat, cards)
                accepted = rnd.declaration
                transcript = transcript.with_declaration(
                    accepted["seat"], accepted["cards"],
                    accepted["strength"])
        rnd.finalize_declare()
        if rnd.declaration is None or rnd.declaration["strength"] != 1:
            continue
        rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
        first = rnd.turn
        attempted = bot.decide_play(rnd, first)
        previous_last = rnd.last_trick
        rnd.play(first, attempted)
        transcript = transcript.with_play(
            first, attempted, actual_play_after(rnd, first, previous_last))
        actor = build_actor_observation(rnd, rnd.turn, transcript)
        if not actor.deductions.declaration_pins:
            continue
        target = build_belief_targets(rnd, rnd.turn)
        counts = _target_counts(actor, target)
        card, relative, copies = actor.deductions.declaration_pins[0]
        owner = f"seat-relative-{relative}"
        if copies != 1 or counts[(card, owner)] != 1 \
                or dict(actor.deductions.unseen).get(card) != 2:
            continue
        fixture = actor, target
        break
    assert fixture is not None
    actor, target = fixture
    counts = _target_counts(actor, target)
    belief = _belief(actor, [counts])
    validate_ownership(actor, belief)
    card, relative, copies = actor.deductions.declaration_pins[0]
    assert copies == 1
    owner = f"seat-relative-{relative}"
    owner_count = counts[(card, owner)]
    assert owner_count == 1

    rows = list(belief.probabilities)
    index = next(index for index, row in enumerate(rows)
                 if row.card == card and row.receiver == owner)
    row = rows[index]
    # Preserve the owner's expected count while introducing impossible absence:
    # p(0)=p(2)=1/2 has expectation one but violates the public declaration.
    rows[index] = type(row)(card, owner,
                            PROBABILITY_SCALE // 2, 0,
                            PROBABILITY_SCALE // 2)
    with pytest.raises(BeliefOwnershipError, match="absent owner"):
        validate_ownership(actor,
                           replace(belief, probabilities=tuple(rows)))


def test_pair_declaration_is_exact_probability_one_ownership():
    seed = 9502
    game = Game(random.Random(seed))
    rnd = game.start_round()
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
    assert rnd.declaration["strength"] == 2
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    first = rnd.turn
    attempted = bot.decide_play(rnd, first)
    previous_last = rnd.last_trick
    rnd.play(first, attempted)
    transcript = transcript.with_play(
        first, attempted, actual_play_after(rnd, first, previous_last))
    actor = build_actor_observation(rnd, rnd.turn, transcript)
    target = build_belief_targets(rnd, rnd.turn)
    counts = _target_counts(actor, target)
    belief = _belief(actor, [counts])
    validate_ownership(actor, belief)

    card, relative, copies = actor.deductions.declaration_pins[0]
    assert copies == 2
    owner = f"seat-relative-{relative}"
    other = next(receiver for receiver, _ in receiver_sizes(actor)
                 if receiver != owner)
    exchange_card = next(
        candidate for candidate, _ in actor.deductions.unseen
        if candidate != card and counts[(candidate, owner)] == 0
        and counts[(candidate, other)] == 1)

    rows = list(belief.probabilities)
    replacements = {
        (card, owner): (0, PROBABILITY_SCALE, 0),
        (card, other): (0, PROBABILITY_SCALE, 0),
        (exchange_card, owner): (0, PROBABILITY_SCALE, 0),
        (exchange_card, other): (PROBABILITY_SCALE, 0, 0),
    }
    for index, row in enumerate(rows):
        values = replacements.get((row.card, row.receiver))
        if values is not None:
            rows[index] = type(row)(row.card, row.receiver, *values)
    with pytest.raises(BeliefOwnershipError, match="declared pair"):
        validate_ownership(actor, replace(belief, probabilities=tuple(rows)))


def test_brier_refuses_wrong_privileged_evaluation_population():
    _, actor, target, _ = _state(9349)
    counts = _target_counts(actor, target)
    belief = _belief(actor, [counts])
    missing = dict(counts)
    missing.pop(next(iter(missing)))
    with pytest.raises(BeliefOwnershipError, match="evaluation population"):
        count_brier_fraction(belief, missing)
    bool_count = dict(counts)
    bool_count[next(iter(bool_count))] = False
    with pytest.raises(BeliefOwnershipError, match="evaluation population"):
        count_brier_fraction(belief, bool_count)


def test_artifact_reopen_is_closed_canonical_and_same_byte_bound():
    _, actor, target, _ = _state(9353)
    belief = _belief(actor, [_target_counts(actor, target)])
    raw = belief.canonical_bytes()
    reopened = ownership_from_bytes(actor, raw)
    assert reopened == belief
    assert reopened.canonical_bytes() == raw

    duplicate = b'{"schema":"forged",' + raw[1:]
    with pytest.raises(BeliefOwnershipError, match="duplicate key"):
        ownership_from_bytes(actor, duplicate)
    with pytest.raises(BeliefOwnershipError, match="not canonical bytes"):
        ownership_from_bytes(actor, raw[:-1] + b" \n")

    payload = json.loads(raw)
    payload["utility"] = 1
    with pytest.raises(BeliefOwnershipError, match="root schema is open"):
        ownership_from_bytes(actor, json.dumps(
            payload, sort_keys=True, separators=(",", ":")).encode() + b"\n")

    payload.pop("utility")
    payload["privileged_targets_consumed"] = True
    with pytest.raises(BeliefOwnershipError, match="privileged targets"):
        ownership_from_bytes(actor, json.dumps(
            payload, sort_keys=True, separators=(",", ":")).encode() + b"\n")

    payload["privileged_targets_consumed"] = False
    payload["count_probabilities"][0]["expected_count_ppb"] += 1
    with pytest.raises(BeliefOwnershipError, match="expected-count field"):
        ownership_from_bytes(actor, json.dumps(
            payload, sort_keys=True, separators=(",", ":")).encode() + b"\n")

    payload["count_probabilities"][0]["expected_count_ppb"] -= 1
    payload["count_probabilities"][0]["count_probability_ppb"][0] = True
    with pytest.raises(BeliefOwnershipError, match="count probability"):
        ownership_from_bytes(actor, json.dumps(
            payload, sort_keys=True, separators=(",", ":")).encode() + b"\n")

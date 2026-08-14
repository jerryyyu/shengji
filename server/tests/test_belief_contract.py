"""Adversarial mechanics tests for BELIEF-V1's typed information boundary."""

from __future__ import annotations

import copy
import json
import random
from collections import Counter

import pytest

from shengji.ai.smart import SmartBot
from shengji.engine.game import Game
from shengji.engine.round import Round
from shengji.rl.belief_contract import (
    ACTOR_OBSERVATION_SCHEMA,
    BELIEF_CONTRACT_SOURCE_SHA256S,
    BELIEF_TARGETS_SCHEMA,
    PARTITION_SCHEMA,
    BeliefContractError,
    build_actor_observation,
    build_belief_targets,
    build_information_partition,
)


def _play_state(seed: int = 8617) -> tuple[Round, SmartBot]:
    game = Game(random.Random(seed))
    rnd = game.start_round()
    while rnd.phase == "deal":
        rnd.deal_next()
    bot = SmartBot()
    for seat in range(4):
        declaration = bot.decide_declare(rnd, seat, final=True)
        if declaration:
            rnd.declare(seat, declaration)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    assert rnd.phase == "play" and rnd.turn == rnd.banker
    return rnd, bot


def _nonbanker_turn(seed: int = 8617) -> tuple[Round, int]:
    rnd, bot = _play_state(seed)
    banker = rnd.banker
    attempted = bot.decide_play(rnd, banker)
    rnd.play(banker, attempted)
    assert rnd.turn == (banker + 1) % 4
    return rnd, rnd.turn


def _swap_hidden_hands(rnd: Round, seat: int) -> Round:
    changed = copy.deepcopy(rnd)
    first = (seat + 1) % 4
    second = (seat + 2) % 4
    assert len(changed.hands[first]) == len(changed.hands[second])
    changed.hands[first], changed.hands[second] = (
        changed.hands[second], changed.hands[first])
    return changed


def _swap_hidden_hand_and_burial(rnd: Round, seat: int) -> Round:
    changed = copy.deepcopy(rnd)
    declaration_cards = set(
        changed.declaration["cards"] if changed.declaration else [])
    hidden_seat = next(s for s in range(4) if s != seat)
    for hand_index, hand_card in enumerate(changed.hands[hidden_seat]):
        if hand_card in declaration_cards:
            continue
        for burial_index, buried_card in enumerate(changed.buried):
            if buried_card != hand_card:
                changed.hands[hidden_seat][hand_index] = buried_card
                changed.buried[burial_index] = hand_card
                return changed
    raise AssertionError("fixture could not find a distinct hidden swap")


def _rotate_round(rnd: Round, offset: int) -> Round:
    """Relabel every absolute seat while preserving relative game truth."""
    changed = copy.deepcopy(rnd)
    rotated_hands = [[] for _ in range(4)]
    for old_seat, hand in enumerate(changed.hands):
        rotated_hands[(old_seat + offset) % 4] = hand
    changed.hands = rotated_hands
    changed.banker = (changed.banker + offset) % 4
    changed.turn = (changed.turn + offset) % 4
    changed.passed = {(seat + offset) % 4 for seat in changed.passed}
    if changed.declaration is not None:
        changed.declaration["seat"] = (
            changed.declaration["seat"] + offset) % 4
    for trick in [*changed.history, changed.trick]:
        if trick is None:
            continue
        trick.leader = (trick.leader + offset) % 4
        if trick.winner is not None:
            trick.winner = (trick.winner + offset) % 4
        for play in trick.plays:
            play.seat = (play.seat + offset) % 4
    if changed.last_trick_winner is not None:
        changed.last_trick_winner = (
            changed.last_trick_winner + offset) % 4
    return changed


def test_contract_has_exact_source_and_schema_boundary():
    rnd, seat = _nonbanker_turn()
    partition = build_information_partition(rnd, seat)
    assert partition.schema == PARTITION_SCHEMA
    assert partition.actor.schema == ACTOR_OBSERVATION_SCHEMA
    assert partition.targets.schema == BELIEF_TARGETS_SCHEMA
    assert set(BELIEF_CONTRACT_SOURCE_SHA256S) == {
        "belief_contract", "memory", "cards", "combos", "round",
    }
    assert all(len(digest) == 64 for digest in
               BELIEF_CONTRACT_SOURCE_SHA256S.values())
    assert partition.manifest() == {
        "schema": PARTITION_SCHEMA,
        "actor_schema": ACTOR_OBSERVATION_SCHEMA,
        "actor_sha256": partition.actor.sha256(),
        "targets_schema": BELIEF_TARGETS_SCHEMA,
        "targets_sha256": partition.targets.sha256(),
        "runtime_consumes_targets": False,
    }
    assert len(partition.sha256()) == 64
    assert json.loads(partition.canonical_bytes()) == partition.manifest()


def test_hidden_other_hand_allocation_changes_target_not_actor_bytes():
    rnd, seat = _nonbanker_turn()
    changed = _swap_hidden_hands(rnd, seat)
    first = build_information_partition(rnd, seat)
    second = build_information_partition(changed, seat)
    assert first.actor.canonical_bytes() == second.actor.canonical_bytes()
    assert first.targets.canonical_bytes() != second.targets.canonical_bytes()


def test_hidden_burial_allocation_changes_target_not_nonbanker_actor_bytes():
    rnd, seat = _nonbanker_turn(8621)
    changed = _swap_hidden_hand_and_burial(rnd, seat)
    first = build_information_partition(rnd, seat)
    second = build_information_partition(changed, seat)
    assert first.actor.canonical_bytes() == second.actor.canonical_bytes()
    assert first.targets.canonical_bytes() != second.targets.canonical_bytes()
    assert first.actor.hidden_burial_size == 8
    assert not first.actor.actor_known_burial
    assert sum(dict(first.targets.hidden_burial).values()) == 8


def test_actor_builder_does_not_inspect_poisoned_hidden_card_contents():
    rnd, seat = _nonbanker_turn(8623)
    actor_bytes = build_actor_observation(rnd, seat).canonical_bytes()
    changed = copy.deepcopy(rnd)
    hidden = (seat + 2) % 4
    changed.hands[hidden][0] = "NOT_A_CARD"
    changed.hands[hidden].append("ALSO_NOT_A_CARD")
    # The runtime actor boundary may inspect public hand sizes, but not the
    # contents of another hand.  Privileged target construction must reject.
    assert build_actor_observation(changed, seat).canonical_bytes() == actor_bytes
    with pytest.raises(BeliefContractError, match="unknown card"):
        build_belief_targets(changed, seat)


def test_banker_burial_is_actor_private_and_not_a_hidden_target():
    rnd, _ = _play_state(8627)
    seat = rnd.banker
    original = build_information_partition(rnd, seat)
    changed = copy.deepcopy(rnd)
    hand_index = next(
        i for i, card in enumerate(changed.hands[seat])
        if card != changed.buried[0])
    changed.hands[seat][hand_index], changed.buried[0] = (
        changed.buried[0], changed.hands[seat][hand_index])
    altered = build_information_partition(changed, seat)
    assert original.actor.canonical_bytes() != altered.actor.canonical_bytes()
    assert sum(dict(original.actor.actor_known_burial).values()) == 8
    assert original.actor.hidden_burial_size == 0
    assert not original.targets.hidden_burial


def test_actor_view_exposes_facts_deductions_and_explicit_history_limit():
    rnd, seat = _nonbanker_turn(8633)
    actor = build_actor_observation(rnd, seat)
    payload = json.loads(actor.canonical_bytes())
    assert payload["phase"] == "play"
    assert payload["perspective"] == "acting-seat-relative-zero"
    assert payload["declaration_history_complete"] is False
    assert payload["attempted_play_history_complete"] is False
    assert payload["hand_sizes_relative"][0] == len(rnd.hands[seat])
    assert sum(payload["actor_hand"].values()) == len(rnd.hands[seat])
    assert len(payload["current_trick"]["plays"]) == 1
    assert payload["current_trick"]["plays"][0]["seat_relative"] == 3
    assert payload["deductions"]["played"]
    assert payload["source_sha256s"] == BELIEF_CONTRACT_SOURCE_SHA256S


def test_targets_cover_exact_other_hands_and_perspective():
    rnd, seat = _nonbanker_turn(8639)
    target = build_belief_targets(rnd, seat)
    assert [view.seat_relative for view in target.other_hands] == [1, 2, 3]
    for view in target.other_hands:
        absolute = (seat + view.seat_relative) % 4
        assert Counter(dict(view.cards)) == Counter(rnd.hands[absolute])
    assert Counter(dict(target.hidden_burial)) == Counter(rnd.buried)


def test_absolute_seat_rotation_preserves_actor_and_target_bytes():
    rnd, seat = _nonbanker_turn(8640)
    first = build_information_partition(rnd, seat)
    rotated = _rotate_round(rnd, 1)
    second = build_information_partition(rotated, (seat + 1) % 4)
    assert first.actor.canonical_bytes() == second.actor.canonical_bytes()
    assert first.targets.canonical_bytes() == second.targets.canonical_bytes()


def test_canonical_bytes_are_stable_newline_terminated_and_nonaliased():
    rnd, seat = _nonbanker_turn(8641)
    actor = build_actor_observation(rnd, seat)
    first = actor.canonical_bytes()
    second = actor.canonical_bytes()
    assert first == second and first.endswith(b"\n")
    assert json.dumps(json.loads(first), sort_keys=True,
                      separators=(",", ":")) + "\n" == first.decode()
    changed = copy.deepcopy(rnd)
    changed.hands[(seat + 1) % 4].reverse()
    # Physical ordering inside a hidden hand is not information.
    assert build_actor_observation(changed, seat).canonical_bytes() == first


@pytest.mark.parametrize("seat", [-1, 4, True, 1.0, "1"])
def test_boundary_refuses_invalid_actor_seat(seat):
    rnd, _ = _play_state(8647)
    with pytest.raises(BeliefContractError, match="acting seat"):
        build_information_partition(rnd, seat)


def test_boundary_refuses_nondecision_subclass_and_visible_or_target_drift():
    rnd, _ = _play_state(8651)
    seat = rnd.banker
    deal = Game(random.Random(9)).start_round()
    with pytest.raises(BeliefContractError, match="play decision"):
        build_actor_observation(deal, 0)

    class ForgedRound(Round):
        pass

    forged = copy.deepcopy(rnd)
    forged.__class__ = ForgedRound
    with pytest.raises(BeliefContractError, match="exact Round"):
        build_actor_observation(forged, seat)

    corrupted = copy.deepcopy(rnd)
    corrupted.hands[seat][0] = corrupted.hands[seat][1]
    with pytest.raises(BeliefContractError, match="physical card population"):
        build_belief_targets(corrupted, seat)

    visible = copy.deepcopy(rnd)
    visible.hands[seat][:3] = [visible.hands[seat][0]] * 3
    with pytest.raises(BeliefContractError, match="more than two"):
        build_actor_observation(visible, seat)


def test_target_mutation_cannot_change_already_built_actor_snapshot():
    rnd, seat = _nonbanker_turn(8653)
    partition = build_information_partition(rnd, seat)
    actor_bytes = partition.actor.canonical_bytes()
    rnd.hands[(seat + 2) % 4].reverse()
    rnd.buried.reverse()
    assert partition.actor.canonical_bytes() == actor_bytes


@pytest.mark.parametrize("seed", [8701, 8707, 8713, 8719])
def test_contract_reconstructs_every_natural_play_decision(seed):
    rnd, bot = _play_state(seed)
    decisions = 0
    while rnd.phase == "play":
        seat = rnd.turn
        partition = build_information_partition(rnd, seat)
        actor = json.loads(partition.actor.canonical_bytes())
        targets = json.loads(partition.targets.canonical_bytes())
        assert actor["hand_sizes_relative"][0] == len(rnd.hands[seat])
        assert sum(actor["actor_hand"].values()) == len(rnd.hands[seat])
        assert [row["seat_relative"] for row in targets["other_hands"]] \
            == [1, 2, 3]
        assert partition.manifest()["runtime_consumes_targets"] is False
        rnd.play(seat, bot.decide_play(rnd, seat))
        decisions += 1
    assert decisions >= 70

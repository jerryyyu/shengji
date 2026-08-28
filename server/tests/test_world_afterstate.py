from __future__ import annotations

import copy
import random

import numpy as np
import pytest
import torch

from shengji.ai.registry import make_bot
from shengji.engine.cards import RANKS
from shengji.engine.round import Round
from shengji.rl.world_afterstate import (
    OUTCOME_CLASSES,
    WorldAfterstateError,
    bind_outcome_to_afterstate,
    build_afterstate_audit,
    build_afterstate_tensors,
    build_outcome,
    category_signed_level,
    reopen_afterstate_audit,
    replay_root_state,
    root_replay,
    signed_level_category,
    validate_outcome,
)
from shengji.rl.world_afterstate_model import (
    CAPACITY_SHAPES,
    collate_world_afterstates,
    distributional_value_loss,
    new_world_afterstate_model,
    proper_score_rows,
)


def _state(seed: int = 771_450_021, plays: int | None = 0, *,
           trump_rank: str = "2", initial_banker: int | None = None):
    rnd = Round(trump_rank, initial_banker, random.Random(seed))
    bots = [make_bot("smart", seed=seed + 1000 + seat)
            for seat in range(4)]
    declarations = []
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bots[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({
                "stage": "deal", "deal_pos": rnd._deal_pos,
                "seat": seat, "cards": list(cards),
            })
    for seat in range(4):
        cards = bots[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({
                "stage": "final", "deal_pos": rnd._deal_pos,
                "seat": seat, "cards": list(cards),
            })
    rnd.finalize_declare()
    assert rnd.banker is not None
    burial = bots[rnd.banker].decide_bury(rnd, rnd.banker)
    rnd.bury(rnd.banker, burial)
    played = []
    while True:
        if plays is not None and len(played) >= plays:
            break
        if plays is None and len(rnd.trick.plays) == 3 \
                and sum(len(hand) for hand in rnd.hands) \
                == len(rnd.hands[rnd.turn]):
            break
        seat = rnd.turn
        assert seat is not None
        action = bots[seat].decide_play(rnd, seat)
        rnd.play(seat, action)
        played.append({"seat": seat, "cards": list(action)})
    assert rnd.turn is not None
    row = root_replay(
        deal_seed=seed, initial_banker=initial_banker,
        trump_rank=trump_rank, declarations=declarations, buried=burial,
        plays=played, root_seat=rnd.turn)
    action = bots[rnd.turn].decide_play(rnd, rnd.turn)
    hands = {seat: list(rnd.hands[seat]) for seat in range(4)}
    return row, hands, list(rnd.buried), action


def _record(plays: int | None = 0):
    row, hands, buried, action = _state(plays=plays)
    return build_afterstate_audit(row, hands, buried, action)


def test_engine_transition_reopens_byte_exact_and_model_has_no_action_input():
    record = _record(plays=1)
    reopened = reopen_afterstate_audit(record)
    assert record["prestate_sha256"] != record["successor_sha256"]
    assert reopened.turn != record["root_seat"] or reopened.phase == "round_end"
    tensors = build_afterstate_tensors(record)
    assert set(vars(tensors)) == {"public", "history", "world", "perspective"}
    assert "action" not in vars(tensors)


def test_successor_reconstruction_guard_refuses_coordinated_visible_drift():
    record = _record()
    forged = copy.deepcopy(record)
    forged["successor"]["public"]["attacker_points"] += 10
    # The producer cannot repair this by merely replacing the claimed hash:
    # reopening replays the source state and action through Round.play.
    import hashlib
    from shengji.rl.belief_contract import canonical_json_bytes
    forged["successor_sha256"] = hashlib.sha256(
        canonical_json_bytes(forged["successor"])).hexdigest()
    with pytest.raises(WorldAfterstateError,
                       match="successor reconstruction drift"):
        reopen_afterstate_audit(forged)


def test_root_action_is_replayed_by_engine_and_cannot_be_substituted():
    record = _record()
    rnd = replay_root_state(record["source_state"])
    root = record["root_seat"]
    replacement = next([card] for card in rnd.hands[root]
                       if [card] != record["attempted_action"])
    forged = copy.deepcopy(record)
    forged["attempted_action"] = replacement
    with pytest.raises(WorldAfterstateError,
                       match="successor reconstruction drift"):
        reopen_afterstate_audit(forged)


@pytest.mark.parametrize("trump_rank", RANKS)
def test_root_replay_supports_every_trump_rank(trump_rank):
    row, hands, buried, action = _state(
        seed=771_451_000 + RANKS.index(trump_rank), plays=2,
        trump_rank=trump_rank, initial_banker=2)
    rnd = replay_root_state(row)
    assert rnd.trump_rank == trump_rank
    record = build_afterstate_audit(row, hands, buried, action)
    assert reopen_afterstate_audit(record).trump_rank == trump_rank


def test_complete_world_conservation_and_root_hand_are_load_bearing():
    row, hands, buried, action = _state()
    root = row["root_seat"]
    other = (root + 1) % 4
    hands[other][0] = hands[other][1]
    with pytest.raises(WorldAfterstateError,
                       match="physical deck conservation"):
        build_afterstate_audit(row, hands, buried, action)
    row, hands, buried, action = _state()
    root = row["root_seat"]
    hands[root][0] = hands[(root + 1) % 4][0]
    with pytest.raises(WorldAfterstateError, match="root actor hand"):
        build_afterstate_audit(row, hands, buried, action)


def test_public_successor_is_hidden_twin_invariant_but_world_tensor_is_not():
    row, hands, buried, action = _state(plays=1)
    root = row["root_seat"]
    others = [seat for seat in range(4) if seat != root]
    left, right = others[:2]
    left_index = right_index = None
    for i, left_card in enumerate(hands[left]):
        for j, right_card in enumerate(hands[right]):
            if left_card != right_card:
                left_index, right_index = i, j
                break
        if left_index is not None:
            break
    assert left_index is not None and right_index is not None
    twin_hands = copy.deepcopy(hands)
    twin_hands[left][left_index], twin_hands[right][right_index] = (
        twin_hands[right][right_index], twin_hands[left][left_index])
    natural = build_afterstate_audit(row, hands, buried, action)
    twin = build_afterstate_audit(row, twin_hands, buried, action)
    assert natural["successor"]["public"] == twin["successor"]["public"]
    natural_tensors = build_afterstate_tensors(natural)
    twin_tensors = build_afterstate_tensors(twin)
    assert np.array_equal(natural_tensors.public, twin_tensors.public)
    assert np.array_equal(natural_tensors.history, twin_tensors.history)
    assert np.array_equal(natural_tensors.perspective,
                          twin_tensors.perspective)
    assert not np.array_equal(natural_tensors.world, twin_tensors.world)


def test_terminal_afterstate_is_reopenable_and_tensorized():
    record = _record(plays=None)
    assert record["successor"]["public"]["terminal"] is True
    reopened = reopen_afterstate_audit(record)
    assert reopened.phase == "round_end"
    tensors = build_afterstate_tensors(record)
    assert tensors.public[-1] == 1.0
    assert tensors.world[:4].sum() == 0.0


def test_signed_level_support_roundtrips_and_perspective_is_not_optional():
    for category in range(OUTCOME_CLASSES):
        utility = category_signed_level(category)
        assert utility != 0 and not utility.is_integer()
    assert signed_level_category(0, True) \
        != signed_level_category(0, False)
    assert category_signed_level(signed_level_category(4_120, True)) == 101.5
    assert category_signed_level(signed_level_category(4_120, False)) == -101.5
    with pytest.raises(WorldAfterstateError, match="perspective"):
        signed_level_category(80, 1)


def test_outcome_rederives_label_from_raw_engine_points():
    record = _record()
    root_is_attacker = record["successor"]["root_role"] == "attacker"
    outcome = build_outcome(record["successor_sha256"], 120,
                            root_is_attacker)
    validate_outcome(outcome)
    forged = dict(outcome)
    forged["signed_level_category"] += 1
    with pytest.raises(WorldAfterstateError, match="derivation drift"):
        validate_outcome(forged)


def test_outcome_must_bind_to_exact_successor_and_root_perspective():
    first = _record()
    second = _record(plays=1)
    root_is_attacker = first["successor"]["root_role"] == "attacker"
    outcome = build_outcome(first["successor_sha256"], 80,
                            root_is_attacker)
    bind_outcome_to_afterstate(first, outcome)
    with pytest.raises(WorldAfterstateError, match="successor binding drift"):
        bind_outcome_to_afterstate(second, outcome)
    flipped = build_outcome(first["successor_sha256"], 80,
                            not root_is_attacker)
    with pytest.raises(WorldAfterstateError,
                       match="root perspective binding drift"):
        bind_outcome_to_afterstate(first, flipped)


def test_model_training_and_proper_score_mechanics_are_executable():
    first_record = _record(plays=0)
    second_record = _record(plays=2)
    first_role = first_record["successor"]["root_role"] == "attacker"
    second_role = second_record["successor"]["root_role"] == "attacker"
    first = bind_outcome_to_afterstate(
        first_record, build_outcome(
            first_record["successor_sha256"], 80, first_role))
    second = bind_outcome_to_afterstate(
        second_record, build_outcome(
            second_record["successor_sha256"], 40, second_role))
    batch = collate_world_afterstates([first, second])
    model = new_world_afterstate_model(991, CAPACITY_SHAPES["small"])
    same = new_world_afterstate_model(991, CAPACITY_SHAPES["small"])
    assert all(torch.equal(left, right) for left, right in zip(
        model.state_dict().values(), same.state_dict().values()))
    logits = model(*batch[:-1])
    assert logits.shape == (2, OUTCOME_CLASSES)
    loss = distributional_value_loss(logits, batch[-1])
    assert torch.isfinite(loss) and float(loss.detach()) > 0
    loss.backward()
    assert any(parameter.grad is not None for parameter in model.parameters())
    nll, brier, utility_error = proper_score_rows(logits.detach(), batch[-1])
    assert nll.shape == brier.shape == utility_error.shape == (2,)
    assert bool(torch.all(torch.isfinite(nll)))
    assert bool(torch.all((brier >= 0) & (brier <= 2)))

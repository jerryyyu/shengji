"""BELIEF-V1 GRU mechanics, target isolation, and projection tests."""

from __future__ import annotations

import copy
import random

import numpy as np
import pytest
import torch

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.engine.round import actual_play_after
from shengji.rl.belief_contract import (
    PublicTranscriptV1,
    build_actor_observation,
    build_belief_targets,
)
from shengji.rl.belief_model import (
    MASKED_LOGIT,
    BeliefModelError,
    inference_logits,
    masked_count_cross_entropy,
    new_from_scratch_model,
    predict_ownership,
    predict_ownership_from_tensors,
    quantize_raw_count_weights,
)
from shengji.rl.belief_ownership import validate_ownership
from shengji.rl.belief_tensor import build_history_ownership_tensors


POLICIES = ("mc-s0-report-lcb",)


def _state(seed=10301, plays=5):
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
    actor = build_actor_observation(rnd, rnd.turn, transcript)
    return rnd, actor, transcript


def test_model_logits_masks_and_exact_projected_ownership():
    _, actor, _ = _state()
    tensors = build_history_ownership_tensors(
        actor, behavior_policy_ids=POLICIES)
    model = new_from_scratch_model(495023836)
    logits = inference_logits(model, tensors)
    assert logits.shape == (54, 4, 3)
    assert logits.dtype == np.float32
    for card in range(54):
        for receiver in range(4):
            active = tensors.unseen_mask[card] and tensors.receiver_mask[receiver]
            for count in range(3):
                allowed = active and (
                    tensors.count_minimums[card, receiver] <= count
                    <= tensors.count_maximums[card, receiver])
                assert (logits[card, receiver, count] > MASKED_LOGIT) == allowed
    raw = quantize_raw_count_weights(tensors, logits)
    assert all(all(type(weight) is int for weight in row.count_weights)
               for row in raw)
    belief = predict_ownership(
        model, actor, behavior_policy_ids=POLICIES, model_sha256="e" * 64)
    validate_ownership(actor, belief)
    assert predict_ownership_from_tensors(
        model, actor, tensors, behavior_policy_ids=POLICIES,
        model_sha256="e" * 64) == belief


def test_model_seed_is_deterministic_without_advancing_global_rng():
    before = torch.get_rng_state().clone()
    first = new_from_scratch_model(847673502)
    after = torch.get_rng_state().clone()
    second = new_from_scratch_model(847673502)
    assert torch.equal(before, after)
    assert all(torch.equal(left, right) for left, right in zip(
        first.state_dict().values(), second.state_dict().values(), strict=True))
    third = new_from_scratch_model(1041799603)
    assert any(not torch.equal(left, right) for left, right in zip(
        first.state_dict().values(), third.state_dict().values(), strict=True))


def test_public_hidden_twins_have_bit_identical_model_outputs():
    rnd, actor, transcript = _state(10303)
    changed = copy.deepcopy(rnd)
    hidden = [seat for seat in range(4) if seat != rnd.turn]
    left, right = next(
        (left, right) for index, left in enumerate(hidden)
        for right in hidden[index + 1:]
        if len(changed.hands[left]) == len(changed.hands[right]))
    changed.hands[left], changed.hands[right] = (
        changed.hands[right], changed.hands[left])
    twin = build_actor_observation(changed, rnd.turn, transcript)
    assert build_belief_targets(changed, rnd.turn) \
        != build_belief_targets(rnd, rnd.turn)
    model = new_from_scratch_model(588875658)
    first = inference_logits(model, build_history_ownership_tensors(
        actor, behavior_policy_ids=POLICIES))
    second = inference_logits(model, build_history_ownership_tensors(
        twin, behavior_policy_ids=POLICIES))
    assert first.tobytes() == second.tobytes()


def test_offline_label_inlet_is_closed_and_differentiable():
    _, actor, _ = _state(10305)
    tensors = build_history_ownership_tensors(
        actor, behavior_policy_ids=POLICIES)
    model = new_from_scratch_model(442958256)
    batch = (
        torch.from_numpy(tensors.events).unsqueeze(0),
        torch.tensor([len(tensors.events)], dtype=torch.long),
        torch.from_numpy(tensors.global_features).unsqueeze(0),
        torch.from_numpy(tensors.card_features).unsqueeze(0),
        torch.from_numpy(tensors.receiver_features).unsqueeze(0),
        torch.from_numpy(tensors.receiver_mask).unsqueeze(0),
        torch.from_numpy(tensors.unseen_mask).unsqueeze(0),
        torch.from_numpy(tensors.count_minimums).unsqueeze(0),
        torch.from_numpy(tensors.count_maximums).unsqueeze(0),
    )
    logits = model(*batch)
    active = (batch[6][:, :, None] & batch[5][:, None, :])
    labels = torch.full(active.shape, -1, dtype=torch.long)
    labels[active] = batch[7][active]
    loss = masked_count_cross_entropy(
        logits, labels, active, batch[7], batch[8])
    assert loss.ndim == 0 and torch.isfinite(loss)
    loss.backward()
    assert any(parameter.grad is not None for parameter in model.parameters())
    labels[~active] = 0
    with pytest.raises(BeliefModelError, match="population/bounds"):
        masked_count_cross_entropy(
            logits.detach(), labels, active, batch[7], batch[8])


def test_model_refuses_bad_seed_gpu_or_logit_contract():
    with pytest.raises(BeliefModelError, match="model seed"):
        new_from_scratch_model(True)
    _, actor, _ = _state(10307)
    tensors = build_history_ownership_tensors(
        actor, behavior_policy_ids=POLICIES)
    logits = inference_logits(new_from_scratch_model(517235703), tensors)
    with pytest.raises(BeliefModelError, match="quantization input"):
        quantize_raw_count_weights(tensors, logits.astype(np.float64))
    changed = logits.copy()
    changed[0, 0, 0] = np.nan
    with pytest.raises(BeliefModelError, match="quantization input"):
        quantize_raw_count_weights(tensors, changed)

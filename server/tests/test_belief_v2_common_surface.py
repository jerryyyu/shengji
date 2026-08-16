"""Common human/synthetic input-surface witnesses for BELIEF-V1 V2."""

from __future__ import annotations

import copy
import random
from dataclasses import replace

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.engine.round import actual_play_after
from shengji.rl.belief_contract import PublicTranscriptV1, build_actor_observation
from shengji.rl.belief_input import CARD_CODES
from shengji.rl.belief_reopen import (
    BeliefReopenError,
    actor_observation_from_dict,
    actor_observation_from_dict_allow_incomplete,
)
from shengji.rl.belief_v2_common_surface import (
    ARRAY_FIELDS,
    BeliefV2CommonSurfaceError,
    build_common_surface_tensors,
    common_surface_actor,
    validate_common_surface_tensors,
)


POLICIES = ("mc-s0-report-lcb",)


def _state(seed: int = 12001, plays: int = 9):
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
    full = build_actor_observation(rnd, rnd.turn, transcript)
    replay_only = build_actor_observation(rnd, rnd.turn)
    return rnd, full, replay_only, transcript


def test_complete_synthetic_and_incomplete_replay_have_identical_model_bytes():
    _, full, replay_only, _ = _state()
    assert full.attempted_play_history_complete is True
    assert replay_only.attempted_play_history_complete is False
    assert actor_observation_from_dict_allow_incomplete(
        replay_only.to_dict()) == replay_only
    with pytest.raises(BeliefReopenError, match="history is incomplete"):
        actor_observation_from_dict(replay_only.to_dict())
    first = build_common_surface_tensors(
        full, behavior_policy_ids=POLICIES)
    second = build_common_surface_tensors(
        replay_only, behavior_policy_ids=POLICIES)
    assert first.source_actor_sha256 != second.source_actor_sha256
    assert first.common_surface_actor_sha256 \
        == second.common_surface_actor_sha256
    assert first.tensors.history_input_sha256 \
        == second.tensors.history_input_sha256
    assert first.to_dict()["source_channels"] != second.to_dict()[
        "source_channels"]
    assert first.to_dict()["model_surface"] == second.to_dict()[
        "model_surface"]
    for field in ARRAY_FIELDS:
        assert np.array_equal(
            getattr(first.tensors, field), getattr(second.tensors, field))


def test_common_surface_masks_attempts_failure_and_overwritten_declarations():
    _, full, _, _ = _state(12003, plays=10)
    common = common_surface_actor(full)
    assert common.declaration_history_complete is False
    assert common.attempted_play_history_complete is False
    assert common.declaration_history == (() if common.declaration is None
                                           else (common.declaration,))
    plays = [play for trick in (*common.completed_tricks,
                                common.current_trick)
             for play in trick.plays]
    assert plays
    assert all(play.attempted_cards == () and play.failed_throw is False
               for play in plays)

    tensor = build_common_surface_tensors(
        full, behavior_policy_ids=POLICIES).tensors
    play_rows = tensor.events[len(common.declaration_history):]
    attempted_start = tensor.events.shape[1] - 2 * len(CARD_CODES)
    actual_start = tensor.events.shape[1] - len(CARD_CODES)
    assert np.all(play_rows[:, attempted_start:actual_start] == 0)
    assert np.any(play_rows[:, actual_start:] != 0)


def test_hidden_world_twins_remain_bit_identical_on_common_surface():
    rnd, full, _, transcript = _state(12005)
    changed = copy.deepcopy(rnd)
    hidden = [seat for seat in range(4) if seat != rnd.turn]
    left, right = next(
        (left, right) for index, left in enumerate(hidden)
        for right in hidden[index + 1:]
        if len(changed.hands[left]) == len(changed.hands[right]))
    changed.hands[left], changed.hands[right] = (
        changed.hands[right], changed.hands[left])
    twin = build_actor_observation(changed, rnd.turn, transcript)
    first = build_common_surface_tensors(
        full, behavior_policy_ids=POLICIES)
    second = build_common_surface_tensors(
        twin, behavior_policy_ids=POLICIES)
    assert first.canonical_bytes() == second.canonical_bytes()
    for field in ARRAY_FIELDS:
        assert getattr(first.tensors, field).tobytes() \
            == getattr(second.tensors, field).tobytes()


def test_common_surface_validator_witnesses_metadata_and_tensor_wiring():
    _, full, _, _ = _state(12007)
    value = build_common_surface_tensors(
        full, behavior_policy_ids=POLICIES)
    with pytest.raises(BeliefV2CommonSurfaceError,
                       match="derivation drift"):
        validate_common_surface_tensors(
            full, replace(
                value,
                source_attempted_play_history_complete=False))
    changed = value.tensors.events.copy()
    changed[0, 0] = 1.0 - changed[0, 0]
    with pytest.raises(BeliefV2CommonSurfaceError,
                       match="derivation drift"):
        validate_common_surface_tensors(
            full, replace(value, tensors=replace(
                value.tensors, events=changed)))

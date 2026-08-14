"""Exact current-sampler REF-C batch tests."""

from __future__ import annotations

import copy
import random
from dataclasses import replace

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.mcbot import MCBot
from shengji.engine.game import Game
from shengji.engine.round import actual_play_after
from shengji.rl.belief_contract import PublicTranscriptV1
from shengji.rl.belief_refc_capture import (
    REF_C_SAMPLER_SHA256,
    REF_C_SOURCE_SHA256S,
    BeliefRefCCaptureError,
    capture_champion_round_with_ref_c,
    capture_ref_c_worlds,
    validate_reference_world_batch,
    validate_reference_captured_round,
)
from shengji.rl.belief_b2_protocol import b2_split_round_seeds
from shengji.rl import belief_capture as CAPTURE
from shengji.rl.belief_reference import REF_C_WORLD_COUNT


def _state(seed=9901, plays=1):
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


def test_ref_c_draw_is_exact_reproducible_and_score_free(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rnd, transcript = _state()
    batch = capture_ref_c_worlds(
        rnd, rnd.turn, transcript, sampler_seed=991)
    validate_reference_world_batch(batch)
    assert len(batch.worlds) == REF_C_WORLD_COUNT
    assert batch.sampler_source_sha256 == REF_C_SAMPLER_SHA256
    assert set(REF_C_SOURCE_SHA256S) == {"mcbot", "memory", "cards", "combos"}
    delta = dict(batch.sampler_delta)
    assert delta["accepted_worlds"] == REF_C_WORLD_COUNT
    assert delta["sample_attempts"] == (
        delta["accepted_worlds"] + delta["failed_worlds"])
    assert delta["impossible_worlds"] == 0
    manifest = batch.manifest_dict()
    assert manifest["contains_sampled_hidden_worlds"] is True
    assert manifest["contains_round_outcome"] is False
    assert manifest["runtime_input"] is False
    assert not ({"winner", "attacker_points", "level_change"} & set(manifest))
    ownership = batch.ownership()
    assert ownership.actor_observation_sha256 == batch.actor.sha256()

    repeated = capture_ref_c_worlds(
        rnd, rnd.turn, transcript, sampler_seed=991)
    assert repeated.manifest_bytes() == batch.manifest_bytes()
    assert tuple(world.canonical_bytes() for world in repeated.worlds) \
        == tuple(world.canonical_bytes() for world in batch.worlds)


def test_ref_c_public_twin_does_not_read_hidden_hand_contents(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rnd, transcript = _state(9907)
    changed = _swap_equal_hidden_hands(rnd)
    first = capture_ref_c_worlds(
        rnd, rnd.turn, transcript, sampler_seed=997)
    second = capture_ref_c_worlds(
        changed, changed.turn, transcript, sampler_seed=997)
    assert first.actor.canonical_bytes() == second.actor.canonical_bytes()
    assert first.manifest_bytes() == second.manifest_bytes()
    assert tuple(world.canonical_bytes() for world in first.worlds) \
        == tuple(world.canonical_bytes() for world in second.worlds)


def test_ref_c_handles_banker_without_predicting_known_kitty(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rnd, transcript = _state(9913, plays=0)
    assert rnd.turn == rnd.banker
    batch = capture_ref_c_worlds(
        rnd, rnd.turn, transcript, sampler_seed=1009)
    assert batch.actor.hidden_burial_size == 0
    assert all(len(world.receivers) == 3 for world in batch.worlds)
    validate_reference_world_batch(batch)


def test_ref_c_refuses_wrong_mode_seed_underfill_and_counter_drift(
        monkeypatch):
    rnd, transcript = _state(9917)
    monkeypatch.delenv("SHENGJI_REQUIRE_VOIDS", raising=False)
    with pytest.raises(BeliefRefCCaptureError, match="strict void"):
        capture_ref_c_worlds(
            rnd, rnd.turn, transcript, sampler_seed=1013)
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    for seed in (True, -1, 2**63, 1.0):
        with pytest.raises(BeliefRefCCaptureError, match="seed"):
            capture_ref_c_worlds(
                rnd, rnd.turn, transcript, sampler_seed=seed)

    original = MCBot._sample_hands

    def fail(self, *_args):
        self.sample_attempts += 1
        self.failed_worlds += 1
        return None

    monkeypatch.setattr(MCBot, "_sample_hands", fail)
    with pytest.raises(BeliefRefCCaptureError, match="underfilled"):
        capture_ref_c_worlds(
            rnd, rnd.turn, transcript, sampler_seed=1019)
    monkeypatch.setattr(MCBot, "_sample_hands", original)
    batch = capture_ref_c_worlds(
        rnd, rnd.turn, transcript, sampler_seed=1021)
    changed_delta = dict(batch.sampler_delta)
    changed_delta["accepted_worlds"] -= 1
    with pytest.raises(BeliefRefCCaptureError, match="work"):
        validate_reference_world_batch(replace(
            batch, sampler_delta=tuple(changed_delta.items())))


def test_full_replay_observes_every_calibration_decision_exactly(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(
        CAPTURE, "make_bot", lambda _name, *, seed: HeuristicBot())
    seed = b2_split_round_seeds("calibration")[0]
    result = capture_champion_round_with_ref_c(
        seed, replicate="calibration-replicate-0")
    validate_reference_captured_round(result)
    assert len(result.batches) == len(result.captured.pairs)
    assert result.manifest_dict()["accepted_world_count"] \
        == len(result.batches) * REF_C_WORLD_COUNT
    assert result.manifest_dict()["contains_round_outcome"] is False
    assert all(result.manifest_dict()[key] is False
               for key in result.manifest_dict()
               if key.endswith("_authorized"))
    with pytest.raises(BeliefRefCCaptureError, match="actor/seed"):
        validate_reference_captured_round(replace(
            result, batches=(replace(
                result.batches[0], sampler_seed=
                result.batches[0].sampler_seed + 1),
                             *result.batches[1:])))
    with pytest.raises(BeliefRefCCaptureError, match="replicate/split"):
        capture_champion_round_with_ref_c(seed, replicate="test-primary")

"""Separation and physical-binding tests for V2 human corpus rows."""

from __future__ import annotations

import json
import random

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.round import Round, actual_play_after
from shengji.engine.game import Game
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.belief_artifacts import (
    reference_external_actor_batch_bundle_bytes,
    reopen_reference_external_actor_batch_bundle,
)
from shengji.rl.belief_v2_human_corpus import (
    BeliefV2HumanCorpusError,
    capture_human_corpus_pair,
    capture_human_source_group,
    reopen_human_actor_row,
    validate_human_group_capture,
    validate_human_corpus_pair,
)
from shengji.rl.belief_v2_human_reference import (
    capture_human_ref_c_source_group,
)


def _state(seed: int = 12101, plays: int = 9):
    rnd = Game(random.Random(seed)).start_round()
    bot = HeuristicBot()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bot.decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = bot.decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    for _ in range(plays):
        seat = rnd.turn
        rnd.play(seat, bot.decide_play(rnd, seat))
    return rnd


def _pair(seed: int = 12101):
    rnd = _state(seed)
    return capture_human_corpus_pair(
        rnd, rnd.turn,
        group_digest="1" * 64,
        round_digest="2" * 64,
        decision_index=9,
        split="train",
    )


def _reseal(row):
    value = dict(row)
    value.pop("artifact_sha256", None)
    value["artifact_sha256"] = __import__("hashlib").sha256(
        canonical_json_bytes(value)).hexdigest()
    return canonical_json_bytes(value)


def test_human_pair_round_trips_with_incomplete_source_and_common_tensors():
    pair = _pair()
    actor, target, common, metadata = validate_human_corpus_pair(
        pair.actor_bytes, pair.target_bytes)
    assert actor.declaration_history_complete is False
    assert actor.attempted_play_history_complete is False
    assert common.to_dict()["model_surface"] == {
        "declarations": "final-winning-declaration-only-v1",
        "plays": "engine-accepted-cards-only-v1",
        "attempted_cards_masked": True,
        "failed_throw_masked": True,
        "source_channel_availability_model_input": False,
    }
    assert metadata["split"] == "train"
    assert len(target.other_hands) == 3


def test_actor_only_reopen_never_needs_privileged_target_bytes():
    pair = _pair(12103)
    actor, common, metadata = reopen_human_actor_row(pair.actor_bytes)
    assert actor.sha256() == common.source_actor_sha256
    assert metadata["decision_index"] == 9
    assert b'"target"' not in pair.actor_bytes
    assert b'"runtime_input"' not in pair.actor_bytes


def test_pair_refuses_cross_file_metadata_and_exact_actor_byte_drift():
    pair = _pair(12105)
    target = json.loads(pair.target_bytes)
    target["split"] = "calibration"
    with pytest.raises(BeliefV2HumanCorpusError,
                       match="binding or authority"):
        validate_human_corpus_pair(pair.actor_bytes, _reseal(target))

    actor = json.loads(pair.actor_bytes)
    actor["actor"]["attempted_play_history_complete"] = True
    actor["actor_sha256"] = __import__("hashlib").sha256(
        canonical_json_bytes(actor["actor"])).hexdigest()
    with pytest.raises(BeliefV2HumanCorpusError,
                       match="channel/authority"):
        reopen_human_actor_row(_reseal(actor))


def test_target_reseal_cannot_hide_physical_ownership_substitution():
    first = _pair(12107)
    second = _pair(12109)
    first_target = json.loads(first.target_bytes)
    second_target = json.loads(second.target_bytes)
    first_target["target"] = second_target["target"]
    first_target["target_sha256"] = __import__("hashlib").sha256(
        canonical_json_bytes(first_target["target"])).hexdigest()
    # Rehashing every self-derived target field still cannot repair the
    # target's physical disagreement with the independently bound actor.
    first_target["partition_sha256"] = "3" * 64
    with pytest.raises(BeliefV2HumanCorpusError,
                       match="physical reconstruction"):
        validate_human_corpus_pair(
            first.actor_bytes, _reseal(first_target))


def _event(round_number, kind, **fields):
    return {"round": round_number, "e": kind, **fields}


def _source_round():
    rnd = Round("9", 0, random.Random(731))
    events = [_event(
        1, "round_start", deck=list(rnd.deck), banker=rnd.banker,
        trump_rank=rnd.trump_rank, levels=["9"] * 4,
        players=[
            {"seat": 0, "name": "Alice", "is_bot": False},
            {"seat": 1, "name": "Bot 1", "is_bot": True},
            {"seat": 2, "name": "Bot 2", "is_bot": True},
            {"seat": 3, "name": "Bot 3", "is_bot": True},
        ])]
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    events.append(_event(
        1, "trump", suit=rnd.trump_suit, rank=rnd.trump_rank,
        banker=rnd.banker, declared=False))
    bot = HeuristicBot()
    bury = bot.decide_bury(rnd, rnd.banker)
    rnd.bury(rnd.banker, bury)
    events.append(_event(
        1, "bury", seat=rnd.banker, cards=bury, bot=False))
    first = True
    while rnd.phase == "play":
        seat = rnd.turn
        attempted = bot.decide_play(rnd, seat)
        previous_last = rnd.last_trick
        rnd.play(seat, attempted)
        actual = actual_play_after(rnd, seat, previous_last)
        events.append(_event(
            1, "play", seat=seat, cards=actual, bot=not first))
        first = False
    events.append(_event(
        1, "round_end", attacker_points=rnd.attacker_points,
        kitty=list(rnd.buried), kitty_points=rnd.kitty_bonus,
        winner_team="attackers", level_change=1,
        new_levels=["10"] * 4, next_banker=0, game_over=False))
    return events


def test_source_group_replay_matches_h0_decision_and_privacy_surface():
    raw = b"".join(
        json.dumps(event, sort_keys=True).encode() + b"\n"
        for event in _source_round())
    digest = __import__("hashlib").sha256(raw).hexdigest()
    result = capture_human_source_group(
        raw, source_sha256=digest, split="train")
    validate_human_group_capture(result)
    assert result.complete_round_count == 1
    assert result.incomplete_round_count == 0
    assert result.human_decision_count == 1
    manifest = result.manifest_bytes()
    assert b"Alice" not in manifest
    assert manifest.endswith(b"\n")
    assert b'"training_authorized":false' in manifest


def test_human_reference_replay_constructs_no_privileged_target(
        monkeypatch):
    raw = b"".join(
        json.dumps(event, sort_keys=True).encode() + b"\n"
        for event in _source_round())
    digest = __import__("hashlib").sha256(raw).hexdigest()
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(
        "shengji.rl.belief_refc_capture.REF_C_WORLD_COUNT", 4)
    monkeypatch.setattr(
        "shengji.rl.belief_reference.REF_C_WORLD_COUNT", 4)
    monkeypatch.setattr(
        "shengji.rl.belief_reference._WORLD_UNIT_PPB", 250_000_000)

    def target_tripwire(*args, **kwargs):
        raise AssertionError("human REF-C constructed a target")

    monkeypatch.setattr(
        "shengji.rl.belief_v2_human_corpus.build_belief_targets",
        target_tripwire)
    result = capture_human_ref_c_source_group(
        raw, source_sha256=digest, split="calibration",
        replicate="calibration-replicate-0")
    assert result.replay.human_decision_count == 1
    assert len(result.decisions) == 1
    assert result.decisions[0].batch.actor.declaration_history_complete is True
    assert result.decisions[0].batch.actor.attempted_play_history_complete \
        is True
    raw_batch = reference_external_actor_batch_bundle_bytes(
        result.decisions[0].batch)
    assert reopen_reference_external_actor_batch_bundle(
        raw_batch, actor=result.decisions[0].batch.actor) \
        == result.decisions[0].batch

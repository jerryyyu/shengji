"""Compact bundle and stable publication tests for BELIEF-V1."""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace

import pytest

import shengji.rl.belief_capture as capture_module
from shengji.ai.heuristic import HeuristicBot
from shengji.ai.mcbot import MCBot
from shengji.rl.belief_artifacts import (
    BeliefArtifactError,
    capture_bundle_bytes,
    checkpoint_bundle_bytes,
    publish_exclusive_bytes,
    reference_round_bundle_bytes,
    reopen_capture_bundle,
    reopen_checkpoint_bundle,
    reopen_reference_round_bundle,
    stable_read_bytes,
)
from shengji.rl.belief_b2_protocol import (
    B2_ROUND_COUNT,
    B2_SEED_START,
    champion_policy_seeds,
    reference_sampler_seed,
)
from shengji.rl.belief_capture import (
    captured_round_artifacts,
    capture_champion_round,
    reopen_captured_round_artifacts,
)
from shengji.rl.belief_checkpoint import (
    build_model_checkpoint,
    reopen_model_checkpoint,
)
from shengji.rl.belief_cohort import COHORT_SEEDS
from shengji.rl.belief_corpus import split_for_round_seed
from shengji.rl.belief_evaluation import reopen_score_pair
from shengji.rl.belief_refc_capture import (
    ReferenceCapturedRoundV1,
    ReferenceWorldBatchV1,
)
from shengji.rl.belief_reference import (
    ReceiverCardsV1,
    SampledOwnershipWorldV1,
)
from shengji.rl.belief_model import new_from_scratch_model
from shengji.rl.belief_trainer import (
    model_state_sha256,
    new_b2_optimizer,
    train_epoch,
)
from shengji.rl.belief_training import (
    build_training_example,
    collate_training_examples,
)


def _seed(split):
    return next(seed for seed in range(
        B2_SEED_START, B2_SEED_START + B2_ROUND_COUNT)
                if split_for_round_seed(seed) == split)


def _captured(monkeypatch, split="calibration"):
    monkeypatch.setattr(
        capture_module, "make_bot",
        lambda _name, seed: HeuristicBot())
    seed = _seed(split)
    return capture_champion_round(seed, champion_policy_seeds(seed))


def _reference_round(monkeypatch):
    captured = _captured(monkeypatch)
    batches = []
    counters = (
        ("sample_attempts", 256), ("accepted_worlds", 256),
        ("failed_worlds", 0), ("rejected_worlds", 0),
        ("impossible_worlds", 0))
    zero = tuple((name, 0) for name, _ in counters)
    for index, pair in enumerate(captured.pairs):
        actor, target, metadata = reopen_score_pair(pair)
        receivers = [ReceiverCardsV1(
            receiver=f"seat-relative-{hand.seat_relative}",
            cards=hand.cards) for hand in target.other_hands]
        if actor.hidden_burial_size:
            receivers.append(ReceiverCardsV1(
                receiver="hidden-kitty", cards=target.hidden_burial))
        world = SampledOwnershipWorldV1(
            actor_observation_sha256=actor.sha256(),
            receivers=tuple(receivers))
        batches.append(ReferenceWorldBatchV1(
            actor=actor, sampler_seed=reference_sampler_seed(
                metadata["decision_key"], "calibration-replicate-0"),
            attempts=256,
            attempt_cap=256 * MCBot.SAMPLE_ATTEMPT_FACTOR,
            sampler_before=zero, sampler_after=counters,
            sampler_delta=counters, worlds=(world,) * 256))
    return ReferenceCapturedRoundV1(
        captured=captured, replicate="calibration-replicate-0",
        batches=tuple(batches))


def test_capture_bundle_round_trip_and_mutations(monkeypatch):
    captured = _captured(monkeypatch)
    artifacts = captured_round_artifacts(captured)
    raw = capture_bundle_bytes(artifacts)
    reopened = reopen_capture_bundle(raw)
    assert reopened == artifacts
    assert reopen_captured_round_artifacts(reopened) == captured
    with pytest.raises(BeliefArtifactError, match="magic"):
        reopen_capture_bundle(b"X" + raw[1:])
    with pytest.raises(BeliefArtifactError, match="trailing"):
        reopen_capture_bundle(raw + b"x")
    with pytest.raises(BeliefArtifactError):
        reopen_capture_bundle(raw[:-1])


def test_reference_round_bundle_reopens_every_world(monkeypatch):
    result = _reference_round(monkeypatch)
    raw = reference_round_bundle_bytes(result)
    reopened = reopen_reference_round_bundle(raw)
    assert reopened == result
    assert reference_round_bundle_bytes(reopened) == raw
    changed = bytearray(raw)
    changed[-1] ^= 1
    with pytest.raises(BeliefArtifactError):
        reopen_reference_round_bundle(bytes(changed))


def test_exclusive_publish_and_stable_read_refuse_aliases(tmp_path):
    path = tmp_path / "artifact.bin"
    raw = b"belief-v1-evidence\n"
    assert publish_exclusive_bytes(path, raw) == hashlib.sha256(raw).hexdigest()
    assert stable_read_bytes(path) == raw
    assert path.stat().st_nlink == 1 and not path.stat().st_mode & 0o222
    with pytest.raises(BeliefArtifactError, match="occupied"):
        publish_exclusive_bytes(path, raw)

    symlink = tmp_path / "symlink.bin"
    symlink.symlink_to(path)
    with pytest.raises(BeliefArtifactError, match="lexical"):
        stable_read_bytes(symlink)
    hardlink = tmp_path / "hardlink.bin"
    os.link(path, hardlink)
    with pytest.raises(BeliefArtifactError, match="unlinked"):
        stable_read_bytes(path)


def test_manifest_byte_drift_refuses_even_if_framing_is_valid(monkeypatch):
    captured = _captured(monkeypatch)
    artifacts = captured_round_artifacts(captured)
    manifest = artifacts.manifest_bytes.replace(
        b'"contains_round_outcome":false',
        b'"contains_round_outcome":true')
    changed = replace(artifacts, manifest_bytes=manifest)
    with pytest.raises((BeliefArtifactError, ValueError)):
        capture_bundle_bytes(changed)


def test_checkpoint_bundle_round_trip_has_no_pickle_surface(monkeypatch):
    captured = _captured(monkeypatch, split="train")
    examples = tuple(build_training_example(
        pair, behavior_policy_ids=("mc-s0-report-lcb",))
                     for pair in captured.pairs[:3])
    batch = collate_training_examples(examples)
    seed = COHORT_SEEDS[0]
    model = new_from_scratch_model(seed)
    receipt = train_epoch(
        model, new_b2_optimizer(model), (batch,), epoch=1)
    checkpoint = build_model_checkpoint(
        model, initialization_seed=seed, selected_epoch=1,
        final_epoch_receipt=receipt)
    raw = checkpoint_bundle_bytes(checkpoint, receipt)
    reopened, reopened_receipt = reopen_checkpoint_bundle(raw)
    rebuilt = reopen_model_checkpoint(
        reopened, final_epoch_receipt=reopened_receipt)
    assert reopened_receipt == receipt
    assert reopened.sha256() == checkpoint.sha256()
    assert model_state_sha256(rebuilt) == model_state_sha256(model)
    changed = bytearray(raw)
    changed[-1] ^= 1
    with pytest.raises(BeliefArtifactError):
        reopen_checkpoint_bundle(bytes(changed))

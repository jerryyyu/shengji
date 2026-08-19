"""Witnesses for the hash-bound training tensor cache.

Load-bearing claims: reloaded batches train byte-identically to freshly built
ones; actor and privileged tensors live in separately hashed files; the test
split refuses at build and load; tampering, reordering, missing and extra
files refuse; and the cache composes with the pipelined prefetch adapter.
"""
from __future__ import annotations

from dataclasses import replace

import pytest
import torch

from shengji.ai.heuristic import HeuristicBot
from shengji.rl.belief_capture import CHAMPION_POLICY, _capture_with_policies
from shengji.rl.belief_cohort import COHORT_SEEDS
from shengji.rl.belief_model import new_from_scratch_model
from shengji.rl.belief_v2_accelerator import (
    evaluate_v2_calibration_cohort_stream_nanonats,
    move_models_to_device,
    new_v2_optimizer,
    portable_model_state_sha256,
    train_v2_cohort_epoch_stream,
)
from shengji.rl.belief_v2_pipelined_batches import pipelined_batches
from shengji.rl.belief_v2_tensor_cache import (
    MANIFEST_FILENAME,
    BeliefV2TensorCacheError,
    build_tensor_cache,
    cached_batch_factory,
)
from shengji.rl.belief_v2_training import (
    build_synthetic_training_example,
    collate_v2_training_examples,
)


@pytest.fixture(autouse=True)
def _deterministic_algorithms():
    previous = torch.are_deterministic_algorithms_enabled()
    previous_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    try:
        yield
    finally:
        torch.use_deterministic_algorithms(previous)
        torch.set_num_threads(previous_threads)


def _real_batches(split: str = "train", count: int = 3):
    captured = _capture_with_policies(
        2, CHAMPION_POLICY, (101, 102, 103, 104),
        [HeuristicBot() for _ in range(4)])
    examples = tuple(build_synthetic_training_example(pair)
                     for pair in captured.pairs)
    size = len(examples) // count
    return tuple(
        replace(collate_v2_training_examples(
            examples[index * size:(index + 1) * size]), split=split)
        for index in range(count))


def _models():
    models = tuple(new_from_scratch_model(seed) for seed in COHORT_SEEDS)
    move_models_to_device(models, device="cpu")
    return models


def _built(tmp_path, split="train"):
    batches = _real_batches(split)
    receipt = build_tensor_cache(
        tmp_path / "cache", batches=lambda: iter(batches),
        cache_id="witness-cache", split=split)
    return batches, receipt


def test_cached_training_is_byte_identical_to_fresh_batches(tmp_path):
    batches, receipt = _built(tmp_path)
    factory = cached_batch_factory(
        tmp_path / "cache",
        expected_manifest_sha256=receipt["manifest_sha256"])

    fresh_models = _models()
    cached_models = _models()
    fresh_receipts = train_v2_cohort_epoch_stream(
        fresh_models,
        tuple(new_v2_optimizer(model) for model in fresh_models),
        iter(batches), epoch=1, device="cpu")
    cached_receipts = train_v2_cohort_epoch_stream(
        cached_models,
        tuple(new_v2_optimizer(model) for model in cached_models),
        factory(), epoch=1, device="cpu")

    assert cached_receipts == fresh_receipts
    assert tuple(portable_model_state_sha256(model)
                 for model in cached_models) \
        == tuple(portable_model_state_sha256(model)
                 for model in fresh_models)


def test_cached_calibration_composes_with_pipeline(tmp_path):
    batches, receipt = _built(tmp_path, split="calibration")
    factory = cached_batch_factory(
        tmp_path / "cache",
        expected_manifest_sha256=receipt["manifest_sha256"])
    models = _models()
    direct = evaluate_v2_calibration_cohort_stream_nanonats(
        models, iter(batches), device="cpu")
    piped_cached = evaluate_v2_calibration_cohort_stream_nanonats(
        models, pipelined_batches(factory), device="cpu")
    assert piped_cached == direct


def test_actor_and_privileged_tensors_are_separately_bound(tmp_path):
    _built(tmp_path)
    cache = tmp_path / "cache"
    actor_files = sorted(cache.glob("*.actor.pt"))
    label_files = sorted(cache.glob("*.labels.pt"))
    assert len(actor_files) == 3 and len(label_files) == 3
    for path in actor_files:
        raw = path.read_bytes()
        assert b"count_labels" not in raw
        assert b"active_mask" not in raw
    for path in label_files:
        raw = path.read_bytes()
        assert b"count_labels" in raw
        assert b"events" not in raw


def test_test_split_refuses_at_build_and_load(tmp_path):
    with pytest.raises(BeliefV2TensorCacheError, match="refuses non-train"):
        build_tensor_cache(
            tmp_path / "cache", batches=lambda: iter(_real_batches("test")),
            cache_id="never", split="test")
    assert not (tmp_path / "cache").exists() \
        or not any((tmp_path / "cache").iterdir())


def test_tamper_reorder_missing_and_extra_files_refuse(tmp_path):
    _, receipt = _built(tmp_path)
    cache = tmp_path / "cache"
    sha = receipt["manifest_sha256"]

    victim = cache / "batch-00001.actor.pt"
    original = victim.read_bytes()
    victim.write_bytes(original[:100] + b"\x00" + original[101:])
    with pytest.raises(BeliefV2TensorCacheError, match="batch 1 byte drift"):
        list(cached_batch_factory(cache, expected_manifest_sha256=sha)())
    victim.write_bytes(original)

    other = cache / "batch-00002.actor.pt"
    swap = other.read_bytes()
    other.write_bytes(original)
    victim.write_bytes(swap)
    with pytest.raises(BeliefV2TensorCacheError, match="byte drift"):
        list(cached_batch_factory(cache, expected_manifest_sha256=sha)())
    victim.write_bytes(original)
    other.write_bytes(swap)

    extra = cache / "batch-99999.actor.pt"
    extra.write_bytes(b"foreign")
    with pytest.raises(BeliefV2TensorCacheError, match="file population"):
        list(cached_batch_factory(cache, expected_manifest_sha256=sha)())
    extra.unlink()

    (cache / "batch-00000.labels.pt").rename(cache / "hidden")
    with pytest.raises(BeliefV2TensorCacheError, match="file population"):
        list(cached_batch_factory(cache, expected_manifest_sha256=sha)())
    (cache / "hidden").rename(cache / "batch-00000.labels.pt")

    manifest_raw = (cache / MANIFEST_FILENAME).read_bytes()
    (cache / MANIFEST_FILENAME).write_bytes(
        manifest_raw.replace(b'"train"', b'"chain"', 1))
    with pytest.raises(BeliefV2TensorCacheError, match="manifest drift"):
        list(cached_batch_factory(cache, expected_manifest_sha256=sha)())
    (cache / MANIFEST_FILENAME).write_bytes(manifest_raw)
    list(cached_batch_factory(cache, expected_manifest_sha256=sha)())


def test_existing_directory_and_bad_inputs_refuse(tmp_path):
    _built(tmp_path)
    with pytest.raises(BeliefV2TensorCacheError, match="already exists"):
        build_tensor_cache(
            tmp_path / "cache", batches=lambda: iter(_real_batches()),
            cache_id="dup", split="train")
    with pytest.raises(BeliefV2TensorCacheError, match="load inputs"):
        cached_batch_factory(tmp_path / "cache",
                             expected_manifest_sha256="short")

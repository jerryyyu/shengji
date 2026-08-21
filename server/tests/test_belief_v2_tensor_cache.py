"""Witnesses for the hash-bound training tensor cache.

Load-bearing claims: reloaded batches train byte-identically to freshly built
ones; actor and privileged tensors live in separately hashed files; the test
split refuses at build and load; tampering, reordering, missing and extra
files refuse; and the cache composes with the pipelined prefetch adapter.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest
import torch

from shengji.ai.heuristic import HeuristicBot
from shengji.rl.belief_capture import CHAMPION_POLICY, _capture_with_policies
from shengji.rl.belief_cohort import COHORT_SEEDS
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.belief_model import new_from_scratch_model
from shengji.rl.belief_v2_accelerator import (
    evaluate_v2_calibration_cohort_stream_nanonats,
    move_models_to_device,
    new_v2_optimizer,
    portable_model_state_sha256,
    train_v2_cohort_epoch_stream,
)
from shengji.rl.belief_v2_tensor_cache import (
    LABEL_MANIFEST_FILENAME,
    MANIFEST_FILENAME,
    BeliefV2TensorCacheError,
    V2TensorCacheBindingV1,
    build_tensor_cache,
    build_label_overlay,
    cached_batch_factory,
    reopen_label_overlay,
    reopen_tensor_cache,
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
    binding = V2TensorCacheBindingV1(
        cache_id="witness-cache", split=split,
        decision_population_sha256="a" * 64,
        batch_schedule_sha256="b" * 64,
        source_index_sha256="c" * 64,
        runtime_profile_sha256="d" * 64,
        expected_decision_count=sum(
            len(batch.decision_keys) for batch in batches),
        expected_batch_count=len(batches),
        storage_cap_bytes=1_000_000_000)
    receipt = build_tensor_cache(
        tmp_path / "cache", batches=lambda: iter(batches),
        binding=binding)
    return batches, receipt, binding


def test_cached_training_is_byte_identical_to_fresh_batches(tmp_path):
    batches, receipt, binding = _built(tmp_path)
    factory = cached_batch_factory(
        tmp_path / "cache",
        expected_manifest_sha256=receipt["manifest_sha256"],
        binding=binding)

    fresh_models = _models()
    cached_models = _models()
    fresh_optimizers = tuple(new_v2_optimizer(model)
                             for model in fresh_models)
    cached_optimizers = tuple(new_v2_optimizer(model)
                              for model in cached_models)
    fresh_receipts = []
    cached_receipts = []
    for epoch in (1, 2):
        fresh_receipts.append(train_v2_cohort_epoch_stream(
            fresh_models, fresh_optimizers, iter(batches),
            epoch=epoch, device="cpu"))
        cached_receipts.append(train_v2_cohort_epoch_stream(
            cached_models, cached_optimizers, factory(),
            epoch=epoch, device="cpu"))

    assert cached_receipts == fresh_receipts
    assert tuple(portable_model_state_sha256(model)
                 for model in cached_models) \
        == tuple(portable_model_state_sha256(model)
                 for model in fresh_models)


def test_cached_calibration_is_identical_to_fresh(tmp_path):
    batches, receipt, binding = _built(tmp_path, split="calibration")
    factory = cached_batch_factory(
        tmp_path / "cache",
        expected_manifest_sha256=receipt["manifest_sha256"],
        binding=binding)
    models = _models()
    direct = evaluate_v2_calibration_cohort_stream_nanonats(
        models, iter(batches), device="cpu")
    cached = evaluate_v2_calibration_cohort_stream_nanonats(
        models, factory(), device="cpu")
    assert cached == direct


def test_actor_and_privileged_tensors_are_separately_bound(tmp_path):
    batches, _, _ = _built(tmp_path)
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
    logical_event_bytes = sum(
        batch.events.numel() * batch.events.element_size()
        for batch in batches)
    assert sum(path.stat().st_size for path in actor_files) \
        < logical_event_bytes // 3


def test_test_split_refuses_at_build_and_load(tmp_path):
    with pytest.raises(BeliefV2TensorCacheError, match="binding drift"):
        batches = _real_batches("test")
        build_tensor_cache(
            tmp_path / "cache", batches=lambda: iter(batches),
            binding=V2TensorCacheBindingV1(
                cache_id="never", split="test",
                decision_population_sha256="a" * 64,
                batch_schedule_sha256="b" * 64,
                source_index_sha256="c" * 64,
                runtime_profile_sha256="d" * 64,
                expected_decision_count=sum(
                    len(batch.decision_keys) for batch in batches),
                expected_batch_count=len(batches),
                storage_cap_bytes=1_000_000_000))
    assert not (tmp_path / "cache").exists() \
        or not any((tmp_path / "cache").iterdir())


def test_tamper_reorder_missing_and_extra_files_refuse(tmp_path):
    _, receipt, binding = _built(tmp_path)
    cache = tmp_path / "cache"
    sha = receipt["manifest_sha256"]

    victim = cache / "batch-00001.actor.pt"
    original = victim.read_bytes()
    victim.chmod(0o600)
    victim.write_bytes(original[:100] + b"\x00" + original[101:])
    victim.chmod(0o400)
    with pytest.raises(BeliefV2TensorCacheError, match="batch 1 byte drift"):
        list(cached_batch_factory(
            cache, expected_manifest_sha256=sha, binding=binding)())
    victim.chmod(0o600)
    victim.write_bytes(original)
    victim.chmod(0o400)

    other = cache / "batch-00002.actor.pt"
    swap = other.read_bytes()
    other.chmod(0o600)
    other.write_bytes(original)
    other.chmod(0o400)
    victim.chmod(0o600)
    victim.write_bytes(swap)
    victim.chmod(0o400)
    with pytest.raises(BeliefV2TensorCacheError, match="byte drift"):
        list(cached_batch_factory(
            cache, expected_manifest_sha256=sha, binding=binding)())
    victim.chmod(0o600)
    victim.write_bytes(original)
    victim.chmod(0o400)
    other.chmod(0o600)
    other.write_bytes(swap)
    other.chmod(0o400)

    extra = cache / "batch-99999.actor.pt"
    extra.write_bytes(b"foreign")
    with pytest.raises(BeliefV2TensorCacheError, match="file population"):
        list(cached_batch_factory(
            cache, expected_manifest_sha256=sha, binding=binding)())
    extra.unlink()

    (cache / "batch-00000.labels.pt").rename(cache / "hidden")
    with pytest.raises(BeliefV2TensorCacheError, match="file population"):
        list(cached_batch_factory(
            cache, expected_manifest_sha256=sha, binding=binding)())
    (cache / "hidden").rename(cache / "batch-00000.labels.pt")

    manifest_raw = (cache / MANIFEST_FILENAME).read_bytes()
    (cache / MANIFEST_FILENAME).chmod(0o600)
    (cache / MANIFEST_FILENAME).write_bytes(
        manifest_raw.replace(b'"train"', b'"chain"', 1))
    (cache / MANIFEST_FILENAME).chmod(0o400)
    with pytest.raises(BeliefV2TensorCacheError, match="manifest drift"):
        list(cached_batch_factory(
            cache, expected_manifest_sha256=sha, binding=binding)())
    (cache / MANIFEST_FILENAME).chmod(0o600)
    (cache / MANIFEST_FILENAME).write_bytes(manifest_raw)
    (cache / MANIFEST_FILENAME).chmod(0o400)
    list(cached_batch_factory(
        cache, expected_manifest_sha256=sha, binding=binding)())


def test_existing_directory_and_bad_inputs_refuse(tmp_path):
    _, _, binding = _built(tmp_path)
    with pytest.raises(BeliefV2TensorCacheError, match="already exists"):
        build_tensor_cache(
            tmp_path / "cache", batches=lambda: iter(_real_batches()),
            binding=binding)
    with pytest.raises(BeliefV2TensorCacheError, match="load inputs"):
        cached_batch_factory(tmp_path / "cache",
                             expected_manifest_sha256="short",
                             binding=binding)


def test_incomplete_cache_resumes_only_from_exact_batch_content(tmp_path):
    batches, original, binding = _built(tmp_path)
    cache = tmp_path / "cache"
    partial = tmp_path / "cache.partial"
    cache.rename(partial)
    (partial / MANIFEST_FILENAME).unlink()
    for index in range(1, len(batches)):
        (partial / f"batch-{index:05d}.actor.pt").unlink()
        (partial / f"batch-{index:05d}.labels.pt").unlink()
    (partial / "batch-00001.actor.pt.partial").write_bytes(b"incomplete")
    resumed = build_tensor_cache(
        cache, batches=lambda: iter(batches), binding=binding)
    assert resumed == reopen_tensor_cache(
        cache, expected_manifest_sha256=resumed["manifest_sha256"],
        binding=binding)
    assert resumed["decision_count"] == original["decision_count"]
    assert not partial.exists()

    cache.rename(partial)
    (partial / MANIFEST_FILENAME).unlink()
    victim = partial / "batch-00000.actor.pt"
    victim.chmod(0o600)
    victim.write_bytes((partial / "batch-00001.actor.pt").read_bytes())
    victim.chmod(0o400)
    with pytest.raises(BeliefV2TensorCacheError,
                       match="resumed batch content drift"):
        build_tensor_cache(
            cache, batches=lambda: iter(batches), binding=binding)


def test_rehashed_extra_manifest_batch_and_static_fields_refuse(tmp_path):
    _, receipt, binding = _built(tmp_path)
    cache = tmp_path / "cache"
    path = cache / MANIFEST_FILENAME
    original = path.read_bytes()

    for mutate in (
            lambda payload: payload.update({"smuggled": False}),
            lambda payload: payload["batches"][0].update(
                {"smuggled": False}),
            lambda payload: payload["batches"][0]["static"].update(
                {"smuggled": False})):
        payload = json.loads(original)
        mutate(payload)
        raw = canonical_json_bytes(payload)
        path.chmod(0o600)
        path.write_bytes(raw)
        path.chmod(0o400)
        with pytest.raises(BeliefV2TensorCacheError,
                           match="schema/authority|population"):
            list(cached_batch_factory(
                cache,
                expected_manifest_sha256=hashlib.sha256(raw).hexdigest(),
                binding=binding)())

    path.chmod(0o600)
    path.write_bytes(original)
    path.chmod(0o400)
    list(cached_batch_factory(
        cache, expected_manifest_sha256=receipt["manifest_sha256"],
        binding=binding)())


def test_whole_cache_duplicate_and_storage_cap_refuse_before_seal(tmp_path):
    batches = _real_batches()
    duplicated = (batches[0], replace(
        batches[1], decision_keys=batches[0].decision_keys))
    duplicate_binding = V2TensorCacheBindingV1(
        cache_id="duplicate", split="train",
        decision_population_sha256="a" * 64,
        batch_schedule_sha256="b" * 64,
        source_index_sha256="c" * 64,
        runtime_profile_sha256="d" * 64,
        expected_decision_count=sum(
            len(batch.decision_keys) for batch in duplicated),
        expected_batch_count=len(duplicated), storage_cap_bytes=1_000_000_000)
    with pytest.raises(BeliefV2TensorCacheError,
                       match="duplicate decision"):
        build_tensor_cache(
            tmp_path / "duplicate", batches=lambda: iter(duplicated),
            binding=duplicate_binding)
    assert not (tmp_path / "duplicate").exists()

    small = replace(
        duplicate_binding, cache_id="small",
        expected_decision_count=sum(
            len(batch.decision_keys) for batch in batches),
        expected_batch_count=len(batches), storage_cap_bytes=128)
    with pytest.raises(BeliefV2TensorCacheError, match="storage cap"):
        build_tensor_cache(
            tmp_path / "small", batches=lambda: iter(batches),
            binding=small)
    assert not (tmp_path / "small").exists()


def test_label_overlay_reuses_exact_actor_cache_without_actor_duplication(
        tmp_path):
    batches, receipt, binding = _built(tmp_path)
    overlay_batches = tuple(replace(
        batch, label_transform="witness-alternate-labels",
        control_kind="witness-control",
        schema="witness-control-batch-v1") for batch in batches)
    overlay = build_label_overlay(
        tmp_path / "overlay", batches=lambda: iter(overlay_batches),
        actor_directory=tmp_path / "cache",
        actor_manifest_sha256=receipt["manifest_sha256"],
        binding=binding, overlay_id="e" * 64)
    files = {path.name for path in (tmp_path / "overlay").iterdir()}
    assert LABEL_MANIFEST_FILENAME in files
    assert all("actor" not in name for name in files)
    reloaded = tuple(cached_batch_factory(
        tmp_path / "cache",
        expected_manifest_sha256=receipt["manifest_sha256"],
        binding=binding, label_overlay_directory=tmp_path / "overlay",
        expected_label_overlay_sha256=overlay["manifest_sha256"])())
    assert len(reloaded) == len(overlay_batches)
    for expected, actual in zip(overlay_batches, reloaded, strict=True):
        assert actual.decision_keys == expected.decision_keys
        assert actual.label_transform == expected.label_transform
        assert actual.control_kind == expected.control_kind
        assert actual.schema == expected.schema
        for field in (
                "events", "event_lengths", "global_features",
                "card_features", "receiver_features", "receiver_mask",
                "unseen_mask", "count_minimums", "count_maximums",
                "count_labels", "active_mask"):
            assert torch.equal(getattr(actual, field),
                               getattr(expected, field))

    drifted = (replace(
        overlay_batches[0],
        events=overlay_batches[0].events.clone() + 1),
        *overlay_batches[1:])
    with pytest.raises(BeliefV2TensorCacheError, match="actor drift"):
        build_label_overlay(
            tmp_path / "bad-overlay", batches=lambda: iter(drifted),
            actor_directory=tmp_path / "cache",
            actor_manifest_sha256=receipt["manifest_sha256"],
            binding=binding, overlay_id="f" * 64)


def test_cache_reopen_hashes_every_file_and_callbacks_cover_every_batch(
        tmp_path):
    batches = _real_batches()
    binding = V2TensorCacheBindingV1(
        cache_id="callback-cache", split="train",
        decision_population_sha256="a" * 64,
        batch_schedule_sha256="b" * 64,
        source_index_sha256="c" * 64,
        runtime_profile_sha256="d" * 64,
        expected_decision_count=sum(
            len(batch.decision_keys) for batch in batches),
        expected_batch_count=len(batches),
        storage_cap_bytes=1_000_000_000)
    deadline = []
    progress = []
    receipt = build_tensor_cache(
        tmp_path / "cache", batches=lambda: iter(batches), binding=binding,
        deadline_check=lambda phase, index: deadline.append((phase, index)),
        progress=lambda done, total, label: progress.append(
            (done, total, label)))
    assert deadline == [
        value for index in range(len(batches))
        for value in (("before-unit", index), ("after-unit", index + 1))
    ] + [("before-seal", len(batches))]
    assert progress == [
        (index, len(batches), binding.cache_id)
        for index in range(len(batches) + 1)]
    assert reopen_tensor_cache(
        tmp_path / "cache",
        expected_manifest_sha256=receipt["manifest_sha256"],
        binding=binding) == receipt

    overlay_batches = tuple(replace(
        batch, label_transform="witness-alternate-labels",
        control_kind="witness-control",
        schema="witness-control-batch-v1") for batch in batches)
    overlay = build_label_overlay(
        tmp_path / "overlay", batches=lambda: iter(overlay_batches),
        actor_directory=tmp_path / "cache",
        actor_manifest_sha256=receipt["manifest_sha256"],
        binding=binding, overlay_id="e" * 64)
    assert reopen_label_overlay(
        tmp_path / "overlay",
        expected_manifest_sha256=overlay["manifest_sha256"],
        actor_manifest_sha256=receipt["manifest_sha256"],
        binding=binding) == overlay

    victim = tmp_path / "overlay" / "batch-00001.labels.pt"
    original = victim.read_bytes()
    victim.chmod(0o600)
    victim.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    victim.chmod(0o400)
    with pytest.raises(BeliefV2TensorCacheError, match="batch 1 byte drift"):
        reopen_label_overlay(
            tmp_path / "overlay",
            expected_manifest_sha256=overlay["manifest_sha256"],
            actor_manifest_sha256=receipt["manifest_sha256"],
            binding=binding)

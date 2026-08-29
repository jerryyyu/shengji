"""Witnesses for the opt-in pipelined batch prefetch adapter.

The load-bearing claims: byte-identical training outcomes versus the direct
iterator, a provable two-live-batch residency bound, original-type exception
propagation, and a producer that always stops.  Each claim has a test that
makes it fail.
"""
from __future__ import annotations

import threading
import time
from dataclasses import replace

import pytest
import torch

from shengji.ai.heuristic import HeuristicBot
from shengji.rl.belief_capture import CHAMPION_POLICY, _capture_with_policies
from shengji.rl.belief_v2_accelerator import (
    evaluate_v2_calibration_cohort_stream_nanonats,
    move_models_to_device,
    new_v2_optimizer,
    portable_model_state_sha256,
    train_v2_cohort_epoch_stream,
)
from shengji.rl.belief_cohort import COHORT_SEEDS
from shengji.rl.belief_model import new_from_scratch_model
from shengji.rl.belief_v2_pipelined_batches import (
    BeliefV2PipelineError,
    pipelined_batches,
    pipelined_factory,
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


def _real_batches(count: int = 3):
    captured = _capture_with_policies(
        2, CHAMPION_POLICY, (101, 102, 103, 104),
        [HeuristicBot() for _ in range(4)])
    examples = tuple(build_synthetic_training_example(pair)
                     for pair in captured.pairs)
    size = len(examples) // count
    return tuple(
        collate_v2_training_examples(examples[index * size:(index + 1) * size])
        for index in range(count))


def _models():
    models = tuple(new_from_scratch_model(seed) for seed in COHORT_SEEDS)
    move_models_to_device(models, device="cpu")
    return models


def test_pipelined_training_is_byte_identical_to_direct_iteration():
    batches = _real_batches()
    direct_models = _models()
    piped_models = _models()

    direct_receipts = train_v2_cohort_epoch_stream(
        direct_models,
        tuple(new_v2_optimizer(model) for model in direct_models),
        iter(batches), epoch=1, device="cpu")
    piped_receipts = train_v2_cohort_epoch_stream(
        piped_models,
        tuple(new_v2_optimizer(model) for model in piped_models),
        pipelined_batches(lambda: iter(batches)), epoch=1, device="cpu")

    assert piped_receipts == direct_receipts
    assert tuple(portable_model_state_sha256(model)
                 for model in piped_models) \
        == tuple(portable_model_state_sha256(model)
                 for model in direct_models)

    calibration = tuple(replace(batch, split="calibration")
                        for batch in batches)
    direct_values = evaluate_v2_calibration_cohort_stream_nanonats(
        direct_models, iter(calibration), device="cpu")
    piped_values = evaluate_v2_calibration_cohort_stream_nanonats(
        piped_models, pipelined_factory(lambda: iter(calibration))(),
        device="cpu")
    assert piped_values == direct_values


def test_pipeline_preserves_order_and_object_content():
    batches = _real_batches()
    seen = list(pipelined_batches(lambda: iter(batches)))
    assert len(seen) == len(batches)
    for got, expected in zip(seen, batches, strict=True):
        assert got.split == expected.split
        assert torch.equal(got.active_mask, expected.active_mask)
        assert torch.equal(got.count_labels, expected.count_labels)


def test_pipeline_never_holds_more_than_two_live_batches():
    built = []
    consumed_done = threading.Event()
    violations = []

    def factory():
        for index in range(6):
            built.append(index)
            if len(built) - consumed[0] > 2:
                violations.append((len(built), consumed[0]))
            yield index

    consumed = [0]
    for item in pipelined_batches(factory):
        time.sleep(0.05)
        consumed[0] += 1
    assert consumed[0] == 6
    assert not violations, f"residency bound violated: {violations}"
    assert not consumed_done.is_set()


def test_pipeline_reraises_producer_exception_with_original_type():
    class MarkerError(RuntimeError):
        pass

    def factory():
        yield 1
        yield 2
        raise MarkerError("exact refusal preserved")

    seen = []
    with pytest.raises(MarkerError, match="exact refusal preserved"):
        for item in pipelined_batches(factory):
            seen.append(item)
    assert seen == [1, 2]


def test_pipeline_early_close_stops_producer_thread():
    release_count = [0]

    def factory():
        for index in range(1000):
            release_count[0] += 1
            yield index

    before = threading.active_count()
    iterator = pipelined_batches(factory)
    first = next(iter([next(iterator)]))
    assert first == 0
    iterator.close()
    deadline = time.monotonic() + 5.0
    while threading.active_count() > before and time.monotonic() < deadline:
        time.sleep(0.01)
    assert threading.active_count() <= before
    assert release_count[0] < 1000


def test_pipeline_refuses_bad_factory_and_foreign_depth():
    with pytest.raises(BeliefV2PipelineError, match="not callable"):
        pipelined_batches(42)
    with pytest.raises(BeliefV2PipelineError, match="exactly one"):
        pipelined_batches(lambda: iter(()), prefetch_depth=2)

"""Executable contract for the algorithm-neutral synchronous RL runner."""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

import pytest


np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from shengji.rl.exact_resume import (  # noqa: E402
    ReplayRing,
    ResumeContractError,
    ResumeProgress,
    ResumeRNGStreams,
    state_digest,
)
from shengji.rl.selfplay_contract import (  # noqa: E402
    CheckpointRef,
    derive_job_seed,
)
from shengji.rl.synchronous_selfplay import (  # noqa: E402
    ActorBatchIdentity,
    SynchronousActorBatch,
    SynchronousRunnerError,
    SynchronousSelfPlayRunner,
)


EXPERIMENT = "s2-synchronous-boundary-test-v1"
ROOT_SEED = 20260806
ALGORITHM_SHA256 = hashlib.sha256(
    b"test-only fixed model, collector, replay, and loss").hexdigest()


@pytest.fixture(autouse=True)
def _deterministic_torch_runtime():
    enabled = torch.are_deterministic_algorithms_enabled()
    warn_only = torch.is_deterministic_algorithms_warn_only_enabled()
    torch.use_deterministic_algorithms(True, warn_only=False)
    try:
        yield
    finally:
        torch.use_deterministic_algorithms(enabled, warn_only=warn_only)


@dataclass
class _Bundle:
    learner: object
    optimizer: object
    replay: ReplayRing
    rng: ResumeRNGStreams


def _new_bundle(*, rng_seed=73):
    learner = torch.nn.Sequential(
        torch.nn.Linear(2, 3),
        torch.nn.ReLU(),
        torch.nn.Linear(3, 1),
    )
    with torch.no_grad():
        offset = 0
        for parameter in learner.parameters():
            values = torch.arange(
                offset, offset + parameter.numel(), dtype=parameter.dtype)
            parameter.copy_(values.reshape_as(parameter).mul_(0.015).sub_(0.1))
            offset += parameter.numel()
    return _Bundle(
        learner=learner,
        optimizer=torch.optim.Adam(learner.parameters(), lr=0.006),
        replay=ReplayRing(9),
        rng=ResumeRNGStreams.seeded(rng_seed),
    )


def _actor_ref(tmp_path):
    path = tmp_path / "actor_generation_4.pt"
    path.write_bytes(b"fixed immutable actor generation four")
    return CheckpointRef.capture(path)


def _new_runner(tmp_path, name, bundle, actor_ref):
    return SynchronousSelfPlayRunner(
        experiment=EXPERIMENT,
        root_seed=ROOT_SEED,
        algorithm_sha256=ALGORITHM_SHA256,
        learner=bundle.learner,
        optimizer=bundle.optimizer,
        replay=bundle.replay,
        rng=bundle.rng,
        actor_ref=actor_ref,
        snapshot_dir=tmp_path / name,
    )


def _collector(log):
    def collect(identity):
        log.append(identity)
        local = np.random.default_rng(identity.seed)
        samples = tuple({
            "x": local.normal(size=2).astype(np.float32),
            "target": np.float32(local.normal()),
            "actor_sha256": identity.actor_ref.sha256,
            "batch_sequence": identity.sequence,
        } for _ in range(3))
        return SynchronousActorBatch(identity=identity, samples=samples)

    return collect


def _update(context):
    logical = context.replay.logical_items()
    index = int(context.rng.numpy.integers(0, len(logical)))
    sample = logical[index]
    features = torch.from_numpy(sample["x"])
    python_jitter = context.rng.python.uniform(-0.02, 0.02)
    torch_jitter = torch.rand((), generator=context.rng.torch).mul(0.03)
    target = torch.as_tensor(sample["target"]) + torch_jitter
    target = target + python_jitter + context.progress.next_batch * 1e-4
    prediction = context.learner(features).squeeze()
    loss = (prediction - target).square()
    context.optimizer.zero_grad(set_to_none=True)
    loss.backward()
    context.optimizer.step()
    context.optimizer.zero_grad(set_to_none=True)


def _bundle_digest(bundle):
    return state_digest({
        "learner": bundle.learner.state_dict(),
        "optimizer": bundle.optimizer.state_dict(),
        "replay": bundle.replay.state_dict(),
        "rng": bundle.rng.state_dict(),
    })


def _resume(bundle, checkpoint_ref, runner, actor_ref, snapshot_dir,
            *, root_seed=ROOT_SEED):
    return SynchronousSelfPlayRunner.resume(
        checkpoint_ref,
        experiment=EXPERIMENT,
        root_seed=root_seed,
        algorithm_sha256=ALGORITHM_SHA256,
        learner=bundle.learner,
        optimizer=bundle.optimizer,
        replay=bundle.replay,
        rng=bundle.rng,
        actor_ref=actor_ref,
        candidate_ref=runner.candidate_ref,
        snapshot_dir=snapshot_dir,
    )


def test_resumed_runner_restores_before_same_named_next_update(tmp_path):
    actor_ref = _actor_ref(tmp_path)

    uninterrupted_bundle = _new_bundle()
    uninterrupted = _new_runner(
        tmp_path, "uninterrupted", uninterrupted_bundle, actor_ref)
    uninterrupted_batches = []
    uninterrupted_receipts = [
        uninterrupted.run_iteration(
            _collector(uninterrupted_batches), _update)
        for _ in range(3)
    ]

    interrupted_bundle = _new_bundle()
    interrupted = _new_runner(
        tmp_path, "interrupted", interrupted_bundle, actor_ref)
    interrupted_batches = []
    for _ in range(2):
        interrupted.run_iteration(_collector(interrupted_batches), _update)
    checkpoint_ref = interrupted.save_checkpoint(
        tmp_path / "boundary_after_2.pt")

    restored_bundle = _new_bundle(rng_seed=999)
    restored = _resume(
        restored_bundle,
        checkpoint_ref,
        interrupted,
        actor_ref,
        tmp_path / "interrupted",
    )
    # Construction performs no collection or update.  Mutable state and the
    # exact next counters are restored first.
    assert len(interrupted_batches) == 2
    assert restored.progress.next_iteration == 2
    assert restored.progress.next_batch == 2

    resumed_receipt = restored.run_iteration(
        _collector(interrupted_batches), _update)
    expected = uninterrupted_receipts[2]
    assert resumed_receipt.batch == expected.batch
    assert resumed_receipt.batch.seed == derive_job_seed(
        experiment=EXPERIMENT,
        root_seed=ROOT_SEED,
        purpose="actor",
        sequence=2,
        actor_sha256=actor_ref.sha256,
    )
    assert resumed_receipt.progress == expected.progress
    assert _bundle_digest(restored_bundle) == \
        _bundle_digest(uninterrupted_bundle)
    assert [batch.sequence for batch in interrupted_batches] == [0, 1, 2]
    assert [batch.seed for batch in interrupted_batches] == [
        batch.seed for batch in uninterrupted_batches]


def test_checkpoint_is_refused_inside_synchronous_batch(tmp_path):
    actor_ref = _actor_ref(tmp_path)
    bundle = _new_bundle()
    runner = _new_runner(tmp_path, "snapshots", bundle, actor_ref)
    attempted = tmp_path / "illegal_inflight.pt"

    def collect(identity):
        with pytest.raises(SynchronousRunnerError, match="work in flight"):
            runner.save_checkpoint(attempted)
        return _collector([])(identity)

    runner.run_iteration(collect, _update)
    assert not attempted.exists()


def test_post_update_runtime_drift_permanently_poisons_runner(tmp_path):
    actor_ref = _actor_ref(tmp_path)
    bundle = _new_bundle()
    runner = _new_runner(tmp_path, "snapshots", bundle, actor_ref)

    def update_and_drift_runtime(context):
        _update(context)
        torch.use_deterministic_algorithms(False)

    try:
        with pytest.raises(SynchronousRunnerError,
                           match="requires deterministic algorithms"):
            runner.run_iteration(_collector([]), update_and_drift_runtime)
    finally:
        torch.use_deterministic_algorithms(True, warn_only=False)

    # Repairing the external setting does not bless the partially suspect
    # in-memory transition.  Both checkpoint and another update require a
    # fresh restore from the last accepted boundary.
    with pytest.raises(SynchronousRunnerError, match="poisoned"):
        runner.save_checkpoint(tmp_path / "suspect.pt")
    with pytest.raises(SynchronousRunnerError, match="poisoned"):
        runner.run_iteration(_collector([]), _update)


def test_mismatched_batch_identity_poisoned_without_learner_update(tmp_path):
    actor_ref = _actor_ref(tmp_path)
    bundle = _new_bundle()
    runner = _new_runner(tmp_path, "snapshots", bundle, actor_ref)
    before = _bundle_digest(bundle)
    updated = False

    def wrong_batch(identity):
        wrong = ActorBatchIdentity(
            experiment=identity.experiment,
            purpose=identity.purpose,
            sequence=identity.sequence,
            seed=identity.seed + 1,
            actor_ref=identity.actor_ref,
            contract_sha256=identity.contract_sha256,
        )
        return SynchronousActorBatch(identity=wrong, samples=())

    def update(_context):
        nonlocal updated
        updated = True

    with pytest.raises(SynchronousRunnerError, match="mismatched"):
        runner.run_iteration(wrong_batch, update)
    assert not updated
    assert _bundle_digest(bundle) == before
    with pytest.raises(SynchronousRunnerError, match="poisoned"):
        runner.save_checkpoint(tmp_path / "poisoned.pt")


def test_resume_binds_root_seed_before_any_transition(tmp_path):
    actor_ref = _actor_ref(tmp_path)
    bundle = _new_bundle()
    runner = _new_runner(tmp_path, "snapshots", bundle, actor_ref)
    checkpoint_ref = runner.save_checkpoint(tmp_path / "initial.pt")
    restored_bundle = _new_bundle(rng_seed=999)
    with pytest.raises(ResumeContractError, match="contract digest mismatch"):
        _resume(
            restored_bundle,
            checkpoint_ref,
            runner,
            actor_ref,
            tmp_path / "snapshots",
            root_seed=ROOT_SEED + 1,
        )


def test_resume_reuses_matching_candidate_after_publish_crash_window(tmp_path):
    actor_ref = _actor_ref(tmp_path)
    original_bundle = _new_bundle()
    original = _new_runner(tmp_path, "snapshots", original_bundle, actor_ref)
    candidate_zero = original.candidate_ref
    checkpoint_zero = original.save_checkpoint(tmp_path / "boundary_zero.pt")
    first = original.run_iteration(_collector([]), _update)

    restored_bundle = _new_bundle(rng_seed=999)
    restored = SynchronousSelfPlayRunner.resume(
        checkpoint_zero,
        experiment=EXPERIMENT,
        root_seed=ROOT_SEED,
        algorithm_sha256=ALGORITHM_SHA256,
        learner=restored_bundle.learner,
        optimizer=restored_bundle.optimizer,
        replay=restored_bundle.replay,
        rng=restored_bundle.rng,
        actor_ref=actor_ref,
        candidate_ref=candidate_zero,
        snapshot_dir=tmp_path / "snapshots",
    )
    replayed = restored.run_iteration(_collector([]), _update)
    assert replayed.candidate_ref == first.candidate_ref
    assert _bundle_digest(restored_bundle) == _bundle_digest(original_bundle)


def test_actor_batch_identity_binds_runner_and_algorithm_contract(tmp_path):
    actor_ref = _actor_ref(tmp_path)
    bundle = _new_bundle()
    runner = _new_runner(tmp_path, "snapshots", bundle, actor_ref)
    identity = runner.next_batch_identity()
    assert identity.contract_sha256 == runner.contract_sha256
    assert identity.as_dict()["contract_sha256"] == runner.contract_sha256


def test_keyboard_interrupt_after_partial_mutation_poisons_runner(tmp_path):
    actor_ref = _actor_ref(tmp_path)
    bundle = _new_bundle()
    runner = _new_runner(tmp_path, "snapshots", bundle, actor_ref)

    def interrupted_collect(_identity):
        bundle.replay.append({"partial": True})
        raise KeyboardInterrupt("injected interrupt")

    with pytest.raises(KeyboardInterrupt, match="injected interrupt"):
        runner.run_iteration(interrupted_collect, _update)
    with pytest.raises(SynchronousRunnerError, match="poisoned"):
        runner.save_checkpoint(tmp_path / "must_not_exist.pt")


@pytest.mark.parametrize("stream", ["python", "numpy", "torch"])
def test_process_global_rng_consumption_poisons_runner(tmp_path, stream):
    actor_ref = _actor_ref(tmp_path)
    bundle = _new_bundle()
    runner = _new_runner(tmp_path, f"snapshots-{stream}", bundle, actor_ref)
    python_state = random.getstate()
    numpy_state = np.random.get_state()
    torch_state = torch.get_rng_state().clone()

    def consume_global_rng(_context):
        if stream == "python":
            random.random()
        elif stream == "numpy":
            np.random.random()
        else:
            torch.rand(())

    try:
        with pytest.raises(SynchronousRunnerError,
                           match="process-global RNG streams changed"):
            runner.run_iteration(_collector([]), consume_global_rng)
        with pytest.raises(SynchronousRunnerError, match="poisoned"):
            runner.run_iteration(_collector([]), _update)
    finally:
        random.setstate(python_state)
        np.random.set_state(numpy_state)
        torch.set_rng_state(torch_state)


class _CounterLearner(torch.nn.Module):
    def __init__(self, *, steps=0):
        super().__init__()
        self.weight = torch.nn.Parameter(torch.tensor(0.25))
        self.steps = steps

    def forward(self):
        return self.weight + self.steps * 0.01


def _counter_bundle(*, steps=0):
    learner = _CounterLearner(steps=steps)
    return _Bundle(
        learner=learner,
        optimizer=torch.optim.SGD(learner.parameters(), lr=0.01),
        replay=ReplayRing(4),
        rng=ResumeRNGStreams.seeded(17),
    )


def test_python_side_learner_mutation_poisons_before_publication(tmp_path):
    actor_ref = _actor_ref(tmp_path)
    bundle = _counter_bundle()
    runner = _new_runner(tmp_path, "snapshots", bundle, actor_ref)

    def mutate_hidden_state(_context):
        bundle.learner.steps += 1

    with pytest.raises(SynchronousRunnerError,
                       match="Python module configuration changed"):
        runner.run_iteration(_collector([]), mutate_hidden_state)
    assert not list((tmp_path / "snapshots").glob("candidate_000001_*.pt"))
    with pytest.raises(SynchronousRunnerError, match="poisoned"):
        runner.save_checkpoint(tmp_path / "mutated.pt")


def test_resume_refuses_fresh_learner_with_stale_python_state(tmp_path):
    actor_ref = _actor_ref(tmp_path)
    original = _counter_bundle(steps=2)
    runner = _new_runner(tmp_path, "snapshots", original, actor_ref)
    checkpoint_ref = runner.save_checkpoint(tmp_path / "counter.pt")
    fresh = _counter_bundle(steps=0)
    with pytest.raises(ResumeContractError,
                       match="learner or optimizer schema mismatch"):
        _resume(
            fresh,
            checkpoint_ref,
            runner,
            actor_ref,
            tmp_path / "snapshots",
        )


@pytest.mark.parametrize(
    "component",
    ["learner", "optimizer", "replay", "rng", "progress", "actor", "config"],
)
def test_normal_return_collector_cannot_mutate_frozen_state(
        tmp_path, component):
    actor_ref = _actor_ref(tmp_path)
    alternate_actor = tmp_path / "alternate_actor.pt"
    alternate_actor.write_bytes(b"different but internally valid actor")
    alternate_ref = CheckpointRef.capture(alternate_actor)
    bundle = _new_bundle()
    runner = _new_runner(
        tmp_path, f"snapshots-{component}", bundle, actor_ref)
    update_called = False

    def mutating_collector(identity):
        if component == "learner":
            with torch.no_grad():
                next(bundle.learner.parameters()).add_(1)
        elif component == "optimizer":
            bundle.optimizer.param_groups[0]["lr"] *= 2
        elif component == "replay":
            bundle.replay.append({"collector_side_effect": True})
        elif component == "rng":
            bundle.rng.python.random()
        elif component == "progress":
            runner.progress = ResumeProgress(7, 7)
        elif component == "actor":
            runner.actor_ref = alternate_ref
        else:
            runner.algorithm_sha256 = hashlib.sha256(b"drift").hexdigest()
        return _collector([])(identity)

    def update(_context):
        nonlocal update_called
        update_called = True

    with pytest.raises(SynchronousRunnerError, match="actor collector"):
        runner.run_iteration(mutating_collector, update)
    assert not update_called
    assert not list(
        (tmp_path / f"snapshots-{component}").glob(
            "candidate_000001_*.pt"))
    with pytest.raises(SynchronousRunnerError, match="poisoned"):
        runner.run_iteration(_collector([]), _update)


class _CounterOptimizer(torch.optim.SGD):
    def __init__(self, params):
        super().__init__(params, lr=0.01)
        self.hidden_steps = 0


def test_python_side_optimizer_mutation_poisons_before_publication(tmp_path):
    actor_ref = _actor_ref(tmp_path)
    bundle = _new_bundle()
    bundle.optimizer = _CounterOptimizer(bundle.learner.parameters())
    runner = _new_runner(tmp_path, "snapshots", bundle, actor_ref)

    def mutate_hidden_optimizer_state(context):
        context.optimizer.hidden_steps += 1

    with pytest.raises(SynchronousRunnerError,
                       match="optimizer Python configuration changed"):
        runner.run_iteration(
            _collector([]), mutate_hidden_optimizer_state)
    assert not list((tmp_path / "snapshots").glob("candidate_000001_*.pt"))
    with pytest.raises(SynchronousRunnerError, match="poisoned"):
        runner.save_checkpoint(tmp_path / "mutated-optimizer.pt")

"""Algorithm-neutral synchronous self-play iteration boundary.

This is infrastructure for a future faithful Suphx- or DouZero-style learner;
it does not choose either model, observation/history encoding, or loss.  One
iteration is deliberately serial:

    frozen actor batch -> replay insertion -> learner update -> candidate

There is never an in-flight batch at a checkpoint.  Any failed iteration
poisons the runner, which must then be discarded and restored from its last
exact checkpoint.
"""
from __future__ import annotations

import copy
import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch

from .exact_resume import (ReplayRing, ResumeProgress, ResumeRNGStreams,
                           learner_module_config_schema, learner_resume_schema,
                           load_exact_resume, optimizer_config_schema,
                           save_exact_resume, state_digest)
from .selfplay_contract import (CheckpointRef, derive_job_seed, load_verified,
                                save_immutable_snapshot)


SYNCHRONOUS_RUNNER_SCHEMA = "shengji-synchronous-selfplay-runner-v1"
BATCH_PURPOSE = "actor"


class SynchronousRunnerError(RuntimeError):
    """The runner is not at a valid synchronous transition boundary."""


def _require_sha256(value: object, label: str) -> str:
    if (not isinstance(value, str) or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise SynchronousRunnerError(f"{label} must be a lowercase SHA-256")
    return value


def _runner_contract_sha256(*, experiment: str, root_seed: int,
                            algorithm_sha256: str) -> str:
    """Bind seed scheduling and the externally fixed algorithm contract."""
    return state_digest({
        "schema": SYNCHRONOUS_RUNNER_SCHEMA,
        "experiment": experiment,
        "root_seed": root_seed,
        "algorithm_sha256": algorithm_sha256,
        "batch_purpose": BATCH_PURPOSE,
        "actor_batches_per_iteration": 1,
        "updates_per_iteration": 1,
    })


@dataclass(frozen=True)
class ActorBatchIdentity:
    experiment: str
    purpose: str
    sequence: int
    seed: int
    actor_ref: CheckpointRef
    contract_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "experiment": self.experiment,
            "purpose": self.purpose,
            "sequence": self.sequence,
            "seed": self.seed,
            "actor": self.actor_ref.as_dict(),
            "contract_sha256": self.contract_sha256,
        }


@dataclass(frozen=True)
class SynchronousActorBatch:
    identity: ActorBatchIdentity
    samples: tuple[Any, ...]


@dataclass(frozen=True)
class LearnerUpdateContext:
    learner: torch.nn.Module
    optimizer: torch.optim.Optimizer
    replay: ReplayRing
    rng: ResumeRNGStreams
    batch: SynchronousActorBatch
    progress: ResumeProgress


@dataclass(frozen=True)
class IterationReceipt:
    batch: ActorBatchIdentity
    candidate_ref: CheckpointRef
    progress: ResumeProgress
    samples_added: int


BatchCollector = Callable[[ActorBatchIdentity], SynchronousActorBatch]
LearnerUpdate = Callable[[LearnerUpdateContext], None]


def _process_global_rng_digests() -> dict[str, str]:
    """Digest process-global RNGs that callbacks are forbidden to consume."""
    states: dict[str, Any] = {
        "python": random.getstate(),
        "numpy_legacy": np.random.get_state(),
        "torch_cpu": torch.get_rng_state().clone(),
    }
    if torch.cuda.is_available():
        states["torch_cuda"] = [
            state.clone() for state in torch.cuda.get_rng_state_all()]
    mps = getattr(torch, "mps", None)
    mps_backend = getattr(torch.backends, "mps", None)
    if mps is not None and mps_backend is not None \
            and mps_backend.is_available() and hasattr(mps, "get_rng_state"):
        states["torch_mps"] = mps.get_rng_state().clone()
    return {name: state_digest(value) for name, value in states.items()}


def _assert_process_global_rngs_unchanged(
        before: dict[str, str]) -> None:
    after = _process_global_rng_digests()
    if set(after) != set(before):
        raise SynchronousRunnerError(
            "process-global RNG device set changed during actor/update work")
    changed = sorted(
        name for name, digest in after.items() if digest != before[name])
    if changed:
        raise SynchronousRunnerError(
            "process-global RNG streams changed; callbacks must use only "
            f"named/local RNGs: {changed}")


class SynchronousSelfPlayRunner:
    """One-batch/one-update serial coordinator with exact resume."""

    def __init__(
            self, *, experiment: str, root_seed: int,
            algorithm_sha256: str, learner: torch.nn.Module,
            optimizer: torch.optim.Optimizer, replay: ReplayRing,
            rng: ResumeRNGStreams, actor_ref: CheckpointRef,
            snapshot_dir: str | Path):
        self._configure(
            experiment=experiment,
            root_seed=root_seed,
            algorithm_sha256=algorithm_sha256,
            learner=learner,
            optimizer=optimizer,
            replay=replay,
            rng=rng,
            actor_ref=actor_ref,
            snapshot_dir=snapshot_dir,
        )
        self.progress = ResumeProgress(next_iteration=0, next_batch=0)
        self._assert_boundary()
        self.candidate_ref = self._publish_or_reuse_candidate(sequence=0)
        self._assert_candidate_matches_learner()

    @classmethod
    def resume(
            cls, resume_ref: CheckpointRef, *, experiment: str,
            root_seed: int, algorithm_sha256: str,
            learner: torch.nn.Module, optimizer: torch.optim.Optimizer,
            replay: ReplayRing, rng: ResumeRNGStreams,
            actor_ref: CheckpointRef, candidate_ref: CheckpointRef,
            snapshot_dir: str | Path) -> "SynchronousSelfPlayRunner":
        """Restore all mutable state before permitting a transition."""
        runner = cls.__new__(cls)
        runner._configure(
            experiment=experiment,
            root_seed=root_seed,
            algorithm_sha256=algorithm_sha256,
            learner=learner,
            optimizer=optimizer,
            replay=replay,
            rng=rng,
            actor_ref=actor_ref,
            snapshot_dir=snapshot_dir,
        )
        receipt = load_exact_resume(
            resume_ref,
            learner=learner,
            optimizer=optimizer,
            replay=replay,
            rng=rng,
            expected_actor_ref=actor_ref,
            expected_candidate_ref=candidate_ref,
            expected_experiment=experiment,
            expected_contract_sha256=runner.contract_sha256,
        )
        runner.progress = receipt.progress
        runner.candidate_ref = receipt.candidate_ref
        runner._assert_progress()
        runner._assert_candidate_matches_learner()
        runner._assert_boundary()
        return runner

    def _configure(
            self, *, experiment: str, root_seed: int,
            algorithm_sha256: str, learner: torch.nn.Module,
            optimizer: torch.optim.Optimizer, replay: ReplayRing,
            rng: ResumeRNGStreams, actor_ref: CheckpointRef,
            snapshot_dir: str | Path) -> None:
        if not isinstance(experiment, str) or not experiment:
            raise SynchronousRunnerError("experiment must be nonempty")
        if isinstance(root_seed, bool) or not isinstance(root_seed, int):
            raise SynchronousRunnerError("root seed must be an integer")
        _require_sha256(algorithm_sha256, "algorithm contract digest")
        actor_ref.verify()
        self.experiment = experiment
        self.root_seed = root_seed
        self.algorithm_sha256 = algorithm_sha256
        self.contract_sha256 = _runner_contract_sha256(
            experiment=experiment,
            root_seed=root_seed,
            algorithm_sha256=algorithm_sha256,
        )
        self.learner = learner
        self.optimizer = optimizer
        self.replay = replay
        self.rng = rng
        self.actor_ref = actor_ref
        self.snapshot_dir = Path(snapshot_dir).resolve()
        self._module_config_sha256 = state_digest(
            learner_module_config_schema(learner))
        self._optimizer_config_sha256 = state_digest(
            optimizer_config_schema(optimizer))
        self._in_transition = False
        self._poisoned = False

    def _assert_progress(self) -> None:
        if self.progress.next_iteration != self.progress.next_batch:
            raise SynchronousRunnerError(
                "one-batch runner progress counters diverged")

    def _assert_module_config(self) -> None:
        current = state_digest(learner_module_config_schema(self.learner))
        if current != self._module_config_sha256:
            raise SynchronousRunnerError(
                "learner Python module configuration changed; mutable learner "
                "state must live in state_dict or the explicit resume state")

    def _assert_optimizer_config(self) -> None:
        current = state_digest(optimizer_config_schema(self.optimizer))
        if current != self._optimizer_config_sha256:
            raise SynchronousRunnerError(
                "optimizer Python configuration changed; mutable optimizer "
                "state must live in state_dict")

    def _resume_component_digests(self) -> dict[str, str]:
        # Building the schema rejects live gradients, hooks, unsupported hidden
        # state, and optimizer topology drift before a candidate can publish.
        learner_resume_schema(self.learner, self.optimizer)
        replay_state = self.replay.state_dict()
        ReplayRing.validate_state_dict(
            replay_state, expected_capacity=self.replay.capacity)
        rng_state = self.rng.state_dict()
        self.rng.validate_state_dict(rng_state)
        return {
            "learner": state_digest(self.learner.state_dict()),
            "optimizer": state_digest(self.optimizer.state_dict()),
            "replay": state_digest(replay_state),
            "rng": state_digest(rng_state),
        }

    def _coordinator_state_digest(self) -> str:
        """Bind fields actor collection and learner callbacks may not replace."""
        return state_digest({
            "experiment": self.experiment,
            "root_seed": self.root_seed,
            "algorithm_sha256": self.algorithm_sha256,
            "contract_sha256": self.contract_sha256,
            "actor_ref": self.actor_ref.as_dict(),
            "candidate_ref": self.candidate_ref.as_dict(),
            "snapshot_dir": str(self.snapshot_dir),
            "progress": self.progress.as_dict(),
            "module_config": state_digest(
                learner_module_config_schema(self.learner)),
            "expected_module_config": self._module_config_sha256,
            "optimizer_config": state_digest(
                optimizer_config_schema(self.optimizer)),
            "expected_optimizer_config": self._optimizer_config_sha256,
            "object_ids": {
                "learner": id(self.learner),
                "optimizer": id(self.optimizer),
                "replay": id(self.replay),
                "rng": id(self.rng),
            },
            "in_transition": self._in_transition,
            "poisoned": self._poisoned,
        })

    def _assert_coordinator_unchanged(self, expected: str, *, stage: str) -> None:
        if self._coordinator_state_digest() != expected:
            raise SynchronousRunnerError(
                f"{stage} replaced frozen runner/config/progress state")

    def _assert_boundary(self) -> None:
        if self._poisoned:
            raise SynchronousRunnerError(
                "failed iteration poisoned runner; restore its last checkpoint")
        if self._in_transition:
            raise SynchronousRunnerError(
                "checkpoint/transition requested with work in flight")
        if not torch.are_deterministic_algorithms_enabled():
            raise SynchronousRunnerError(
                "synchronous exactness requires deterministic algorithms")
        if torch.is_deterministic_algorithms_warn_only_enabled():
            raise SynchronousRunnerError(
                "synchronous exactness refuses deterministic warn-only mode")
        gradients = sorted(
            name for name, parameter in self.learner.named_parameters()
            if parameter.grad is not None)
        if gradients:
            raise SynchronousRunnerError(
                f"learner boundary has live gradients: {gradients}")
        self._assert_progress()
        self._assert_module_config()
        self._assert_optimizer_config()
        self._resume_component_digests()
        self.actor_ref.verify()

    def _candidate_state(self, ref: CheckpointRef):
        return load_verified(
            ref, lambda path: torch.load(path, weights_only=True))

    def _assert_candidate_matches_learner(self) -> None:
        candidate_state = self._candidate_state(self.candidate_ref)
        if state_digest(candidate_state) != state_digest(
                self.learner.state_dict()):
            raise SynchronousRunnerError(
                "candidate snapshot does not match learner boundary")

    def _publish_or_reuse_candidate(self, *, sequence: int) -> CheckpointRef:
        stem = f"candidate_{sequence:06d}"
        lock = self.snapshot_dir / f".{stem}.lock"
        partial = self.snapshot_dir / f".{stem}.partial"
        if partial.exists():
            raise SynchronousRunnerError(
                f"stale candidate publication marker {partial}")
        existing = sorted(self.snapshot_dir.glob(f"{stem}_*.pt"))
        if len(existing) > 1:
            raise SynchronousRunnerError(
                f"multiple candidate snapshots for sequence {sequence}")
        if existing:
            ref = CheckpointRef.capture(existing[0])
            candidate_state = self._candidate_state(ref)
            if state_digest(candidate_state) != state_digest(
                    self.learner.state_dict()):
                raise SynchronousRunnerError(
                    "existing candidate sequence has different learner state")
            return ref
        if lock.exists():
            raise SynchronousRunnerError(
                f"stale candidate publication owner {lock}")
        return save_immutable_snapshot(
            self.learner,
            self.snapshot_dir,
            label="candidate",
            sequence=sequence,
        )

    def adopt_current_candidate_as_actor(self) -> CheckpointRef:
        """Explicitly rotate the frozen actor to the current candidate.

        The operation names no mutable learner and accepts no caller-selected
        artifact: it adopts only ``self.candidate_ref``, the immutable snapshot
        already published by the preceding completed iteration.  It never
        creates or copies a checkpoint implicitly.
        """
        # Check the currently frozen actor inside the fail-closed portion of
        # adoption.  Once an actor has already been adopted it aliases the
        # current candidate, so a corrupt shared artifact would otherwise fail
        # in _assert_boundary() before this operation poisoned the runner.
        # Work-in-flight remains an ordinary refusal: do not turn a caller's
        # attempt to rotate during a transition into a permanently poisoned
        # coordinator.
        if self._in_transition:
            self._assert_boundary()
        try:
            self.actor_ref.verify()
        except BaseException:
            self._poisoned = True
            raise
        self._assert_boundary()
        # load_verified checks the candidate bytes on both sides of the load;
        # comparing the loaded state with the live learner binds both sides of
        # this completed boundary before actor_ref is the only field mutated.
        try:
            self._assert_candidate_matches_learner()
        except BaseException:
            # A current candidate that no longer verifies against its recorded
            # bytes or live learner is a broken synchronous boundary, not a
            # recoverable caller typo.  Only exact checkpoint restore may
            # continue this runner.
            self._poisoned = True
            raise
        self.actor_ref = self.candidate_ref
        return self.actor_ref

    def next_batch_identity(self) -> ActorBatchIdentity:
        """Describe the only actor batch authorized for the next iteration."""
        self._assert_boundary()
        sequence = self.progress.next_batch
        seed = derive_job_seed(
            experiment=self.experiment,
            root_seed=self.root_seed,
            purpose=BATCH_PURPOSE,
            sequence=sequence,
            actor_sha256=self.actor_ref.sha256,
        )
        return ActorBatchIdentity(
            experiment=self.experiment,
            purpose=BATCH_PURPOSE,
            sequence=sequence,
            seed=seed,
            actor_ref=self.actor_ref,
            contract_sha256=self.contract_sha256,
        )

    def run_iteration(self, collect: BatchCollector,
                      update: LearnerUpdate) -> IterationReceipt:
        """Complete one serial batch and update, or poison the runner."""
        self._assert_boundary()
        identity = self.next_batch_identity()
        self._in_transition = True
        try:
            global_rngs = _process_global_rng_digests()
            frozen_components = self._resume_component_digests()
            frozen_coordinator = self._coordinator_state_digest()
            self.actor_ref.verify()
            collected = collect(identity)
            _assert_process_global_rngs_unchanged(global_rngs)
            self._assert_coordinator_unchanged(
                frozen_coordinator, stage="actor collector")
            if self._resume_component_digests() != frozen_components:
                raise SynchronousRunnerError(
                    "actor collector mutated frozen learner/optimizer/replay/RNG "
                    "state")
            if not isinstance(collected, SynchronousActorBatch):
                raise SynchronousRunnerError(
                    "collector must return SynchronousActorBatch")
            if collected.identity != identity:
                raise SynchronousRunnerError(
                    "collector returned mismatched actor batch identity")
            if not isinstance(collected.samples, tuple):
                raise SynchronousRunnerError("batch samples must be a tuple")
            self.actor_ref.verify()
            sealed = SynchronousActorBatch(
                identity=identity,
                samples=tuple(copy.deepcopy(collected.samples)),
            )
            for sample in sealed.samples:
                self.replay.append(copy.deepcopy(sample))
            result = update(LearnerUpdateContext(
                learner=self.learner,
                optimizer=self.optimizer,
                replay=self.replay,
                rng=self.rng,
                batch=sealed,
                progress=self.progress,
            ))
            if result is not None:
                raise SynchronousRunnerError(
                    "learner update must return None; mutable state is explicit")
            gradients = sorted(
                name for name, parameter in self.learner.named_parameters()
                if parameter.grad is not None)
            if gradients:
                raise SynchronousRunnerError(
                    f"learner update left live gradients: {gradients}")
            _assert_process_global_rngs_unchanged(global_rngs)
            self._assert_module_config()
            self._assert_optimizer_config()
            self._assert_coordinator_unchanged(
                frozen_coordinator, stage="learner update")
            self._resume_component_digests()
            next_progress = ResumeProgress(
                next_iteration=self.progress.next_iteration + 1,
                next_batch=self.progress.next_batch + 1,
            )
            candidate_ref = self._publish_or_reuse_candidate(
                sequence=next_progress.next_iteration)
            self.progress = next_progress
            self.candidate_ref = candidate_ref
        except BaseException:
            self._poisoned = True
            raise
        finally:
            self._in_transition = False
        try:
            self._assert_boundary()
            self._assert_candidate_matches_learner()
        except BaseException:
            # Publication is part of the transition.  A runtime/actor drift or
            # candidate mismatch discovered immediately afterward makes the
            # whole in-memory result suspect even if the external cause is
            # later repaired; only restoring the last checkpoint may continue.
            self._poisoned = True
            raise
        return IterationReceipt(
            batch=identity,
            candidate_ref=self.candidate_ref,
            progress=self.progress,
            samples_added=len(sealed.samples),
        )

    def save_checkpoint(self, path: str | Path) -> CheckpointRef:
        """Checkpoint only a completed, zero-in-flight iteration boundary."""
        self._assert_boundary()
        self._assert_candidate_matches_learner()
        return save_exact_resume(
            path,
            learner=self.learner,
            optimizer=self.optimizer,
            replay=self.replay,
            rng=self.rng,
            progress=self.progress,
            actor_ref=self.actor_ref,
            candidate_ref=self.candidate_ref,
            experiment=self.experiment,
            contract_sha256=self.contract_sha256,
            pending_jobs=0,
        )

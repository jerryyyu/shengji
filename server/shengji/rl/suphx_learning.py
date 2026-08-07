"""Exact synchronous policy-gradient mechanics for the Suphx microbaseline.

This module adds one immutable-actor batch -> one on-policy update -> one exact
candidate transition.  A schedule is part of the runner algorithm digest; it
cannot be changed across resume.  This remains a code gate: there is no CLI,
frozen evidence population, experiment launch, result gate, registry entry, or
production authority.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import torch

from .exact_resume import ReplayRing, ResumeRNGStreams, state_digest
from .selfplay_contract import CheckpointRef, load_verified, sha256_file
from .suphx_actor import (ACTOR_SPEC_SHA256, SuphxActorError,
                          SuphxMicroCollector, load_actor, validate_sample)
from .suphx_micro import EXPERIMENT, apply_privilege_mask
from .suphx_policy import (POLICY_SPEC_SHA256, SURFACE_NAMES,
                           SuphxPolicyValue, new_from_scratch_model,
                           surface_key)
from .synchronous_selfplay import (LearnerUpdateContext,
                                   SynchronousSelfPlayRunner)


LEARNING_SCHEMA = "suphx-micro-onpolicy-actor-critic-v2"
SCHEDULE_SCHEMA = "suphx-micro-privilege-schedule-v2"
VALUE_COEFFICIENT = 0.5
TARGET_ENTROPY_FRACTION = 0.60
ENTROPY_CONTROLLER_STEP = 0.001
MAX_ENTROPY_ALPHA = 0.10
GRADIENT_NORM_CAP = 1.0
REPLAY_CAPACITY = 256

LEARNING_SOURCE_SHA256S = {
    "suphx_learning": sha256_file(Path(__file__).resolve()),
    "suphx_actor": sha256_file(
        Path(__file__).resolve().with_name("suphx_actor.py")),
    "suphx_features": sha256_file(
        Path(__file__).resolve().with_name("suphx_micro.py")),
    "suphx_policy": sha256_file(
        Path(__file__).resolve().with_name("suphx_policy.py")),
    "exact_resume": sha256_file(
        Path(__file__).resolve().with_name("exact_resume.py")),
    "synchronous_selfplay": sha256_file(
        Path(__file__).resolve().with_name("synchronous_selfplay.py")),
}

LEARNING_SPEC: dict[str, Any] = {
    "schema": LEARNING_SCHEMA,
    "claim": "synchronous learning mechanics only; no strength authority",
    "policy_spec_sha256": POLICY_SPEC_SHA256,
    "actor_spec_sha256": ACTOR_SPEC_SHA256,
    "source_sha256s": LEARNING_SOURCE_SHA256S,
    "batch": "current immutable actor batch only",
    "causal_deals": (
        "schedule-bound root shared across arms; independent of actor digest"
    ),
    "objective": {
        "policy": "negative chosen log probability times detached advantage",
        "value": "mean squared clipped attacker-point-bracket baseline",
        "value_coefficient": VALUE_COEFFICIENT,
        "entropy": "per-role-surface adaptive coefficient",
        "target_entropy_fraction_of_log_ballot": TARGET_ENTROPY_FRACTION,
        "entropy_controller_step": ENTROPY_CONTROLLER_STEP,
        "max_entropy_alpha": MAX_ENTROPY_ALPHA,
        "importance_sampling": False,
        "behavior_probability_must_reopen_preupdate": True,
    },
    "optimizer": {
        "name": "Adam",
        "betas": [0.9, 0.999],
        "eps": 1e-8,
        "weight_decay": 0.0,
        "amsgrad": False,
        "gradient_norm_cap": GRADIENT_NORM_CAP,
    },
    "replay": {
        "capacity": REPLAY_CAPACITY,
        "older_samples_used_for_update": False,
    },
}
LEARNING_SPEC_SHA256 = state_digest(LEARNING_SPEC)


class SuphxLearningError(SuphxActorError):
    """The synchronous policy-learning contract was violated."""


def _valid_probability(value: object) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(float(value)) and 0.0 <= float(value) <= 1.0)


@dataclass(frozen=True)
class SuphxSchedule:
    """One exact synchronous segment, including every per-batch gamma."""

    segment_id: str
    keep_probabilities: tuple[float, ...]
    learning_rate: float
    deal_stream_root_seed: int

    def __post_init__(self) -> None:
        if not isinstance(self.segment_id, str) or not self.segment_id \
                or len(self.segment_id) > 128 \
                or any(not (char.isalnum() or char in "-_.")
                       for char in self.segment_id):
            raise SuphxLearningError("schedule segment id is invalid")
        if not isinstance(self.keep_probabilities, tuple) \
                or not self.keep_probabilities \
                or any(not _valid_probability(value)
                       for value in self.keep_probabilities):
            raise SuphxLearningError(
                "schedule keep probabilities must be a nonempty tuple in [0,1]")
        if isinstance(self.learning_rate, bool) \
                or not isinstance(self.learning_rate, (int, float)) \
                or not math.isfinite(float(self.learning_rate)) \
                or not 0.0 < float(self.learning_rate) <= 0.1:
            raise SuphxLearningError("schedule learning rate is invalid")
        if isinstance(self.deal_stream_root_seed, bool) \
                or not isinstance(self.deal_stream_root_seed, int) \
                or self.deal_stream_root_seed < 0:
            raise SuphxLearningError(
                "schedule deal stream root must be a nonnegative integer")

    def keep_probability(self, sequence: int) -> float:
        if isinstance(sequence, bool) or not isinstance(sequence, int) \
                or not 0 <= sequence < len(self.keep_probabilities):
            raise SuphxLearningError(
                "batch sequence is outside the frozen privilege schedule")
        return float(self.keep_probabilities[sequence])

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEDULE_SCHEMA,
            "segment_id": self.segment_id,
            "keep_probabilities": [float(value)
                                   for value in self.keep_probabilities],
            "learning_rate": float(self.learning_rate),
            "deal_stream_root_seed": self.deal_stream_root_seed,
            "iterations": len(self.keep_probabilities),
        }


def algorithm_spec(schedule: SuphxSchedule) -> dict[str, Any]:
    if not isinstance(schedule, SuphxSchedule):
        raise SuphxLearningError("algorithm schedule has the wrong type")
    return {
        "schema": "suphx-micro-segment-algorithm-v2",
        "learning_spec_sha256": LEARNING_SPEC_SHA256,
        "schedule": schedule.as_dict(),
    }


def algorithm_sha256(schedule: SuphxSchedule) -> str:
    return state_digest(algorithm_spec(schedule))


@dataclass(frozen=True)
class SuphxScheduledCollector:
    expected_runner_contract_sha256: str
    schedule: SuphxSchedule

    def __call__(self, identity):
        keep_probability = self.schedule.keep_probability(identity.sequence)
        return SuphxMicroCollector(
            self.expected_runner_contract_sha256,
            keep_probability,
            self.schedule.deal_stream_root_seed,
        )(identity)


def _preupdate_terms(
        model: SuphxPolicyValue, sample: Mapping[str, Any]) \
        -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, float, str]:
    masked = apply_privilege_mask(sample["perfect"], sample["mask"])
    history = sample["history"][:sample["history_length"]].copy()
    logits, value = model.score_candidates(
        role=sample["role"],
        surface=sample["decision_surface"],
        observation=sample["observation"],
        legal_private=sample["legal_private"],
        history=history,
        masked_perfect=masked,
        actions=sample["candidates"],
        grad=True,
    )
    log_probabilities = torch.log_softmax(logits, dim=0)
    probabilities = torch.softmax(logits, dim=0)
    chosen_log_probability = log_probabilities[sample["chosen_index"]]
    if not math.isclose(
            float(chosen_log_probability.detach().item()),
            sample["behavior_log_probability"],
            rel_tol=0.0, abs_tol=1e-7):
        raise SuphxLearningError(
            "learner does not match immutable behavior actor pre-update")
    if not math.isclose(
            float(value.detach().item()), sample["behavior_value"],
            rel_tol=0.0, abs_tol=1e-7):
        raise SuphxLearningError(
            "learner value does not match immutable behavior actor pre-update")
    entropy = -(probabilities * log_probabilities).sum()
    target_entropy = TARGET_ENTROPY_FRACTION * math.log(len(logits))
    key = surface_key(sample["role"], sample["decision_surface"])
    return chosen_log_probability, value, entropy, target_entropy, key


@dataclass(frozen=True)
class SuphxPolicyGradientUpdate:
    schedule: SuphxSchedule

    def __call__(self, context: LearnerUpdateContext) -> None:
        if not isinstance(context.learner, SuphxPolicyValue):
            raise SuphxLearningError("learner has the wrong policy type")
        sequence = context.progress.next_iteration
        expected_keep = self.schedule.keep_probability(sequence)
        if context.batch.identity.sequence != sequence:
            raise SuphxLearningError("batch/update sequence drift")
        samples = list(context.batch.samples)
        if not samples:
            raise SuphxLearningError("cannot update from an empty actor batch")
        policy_terms = []
        value_terms = []
        entropy_terms = []
        entropy_by_surface: dict[str, list[torch.Tensor]] = {}
        target_entropy_by_surface: dict[str, list[float]] = {}
        for sample in samples:
            validate_sample(
                sample,
                contract_sha256=context.batch.identity.contract_sha256)
            if sample["keep_probability"] != expected_keep:
                raise SuphxLearningError(
                    "sample keep probability differs from frozen schedule")
            if sample["deal_stream_root_seed"] != \
                    self.schedule.deal_stream_root_seed:
                raise SuphxLearningError(
                    "sample deal stream differs from frozen schedule")
            log_probability, value, entropy, target_entropy, key = \
                _preupdate_terms(context.learner, sample)
            target = torch.tensor(sample["target"], dtype=torch.float32)
            advantage = target - value
            policy_terms.append(-log_probability * advantage.detach())
            value_terms.append(advantage.square())
            alpha = context.learner.surfaces[key].entropy_alpha.detach()
            entropy_terms.append(alpha * entropy)
            entropy_by_surface.setdefault(key, []).append(entropy.detach())
            target_entropy_by_surface.setdefault(key, []).append(target_entropy)

        loss = (
            torch.stack(policy_terms).mean()
            + VALUE_COEFFICIENT * torch.stack(value_terms).mean()
            - torch.stack(entropy_terms).mean()
        )
        if not bool(torch.isfinite(loss)):
            raise SuphxLearningError("policy-gradient loss is non-finite")
        context.optimizer.zero_grad(set_to_none=True)
        loss.backward()
        gradient_norm = torch.nn.utils.clip_grad_norm_(
            context.learner.parameters(), GRADIENT_NORM_CAP)
        if not bool(torch.isfinite(gradient_norm)):
            context.optimizer.zero_grad(set_to_none=True)
            raise SuphxLearningError("policy-gradient norm is non-finite")
        context.optimizer.step()
        context.optimizer.zero_grad(set_to_none=True)

        with torch.no_grad():
            for key, values in entropy_by_surface.items():
                observed = float(torch.stack(values).mean().item())
                target = sum(target_entropy_by_surface[key]) / len(
                    target_entropy_by_surface[key])
                head = context.learner.surfaces[key]
                updated = float(head.entropy_alpha.item()) \
                    + ENTROPY_CONTROLLER_STEP * (target - observed)
                head.entropy_alpha.fill_(
                    min(MAX_ENTROPY_ALPHA, max(0.0, updated)))


@dataclass
class SuphxMicroBundle:
    learner: SuphxPolicyValue
    optimizer: torch.optim.Optimizer
    replay: ReplayRing
    rng: ResumeRNGStreams


def new_bundle(
        *, model_seed: int, learner_rng_seed: int,
        learning_rate: float) -> SuphxMicroBundle:
    schedule = SuphxSchedule(
        segment_id="bundle-validation",
        keep_probabilities=(0.0,),
        learning_rate=learning_rate,
        deal_stream_root_seed=0,
    )
    learner = new_from_scratch_model(model_seed)
    return SuphxMicroBundle(
        learner=learner,
        optimizer=torch.optim.Adam(
            learner.parameters(), lr=schedule.learning_rate),
        replay=ReplayRing(REPLAY_CAPACITY),
        rng=ResumeRNGStreams.seeded(learner_rng_seed),
    )


def _require_bundle_schedule(
        bundle: SuphxMicroBundle, schedule: SuphxSchedule) -> None:
    if not isinstance(bundle, SuphxMicroBundle):
        raise SuphxLearningError("runner bundle has the wrong type")
    groups = bundle.optimizer.param_groups
    if len(groups) != 1 or groups[0].get("lr") != schedule.learning_rate:
        raise SuphxLearningError("optimizer learning rate differs from schedule")


def _require_actor_matches_learner(
        actor_ref: CheckpointRef, learner: SuphxPolicyValue) -> None:
    actor = load_verified(actor_ref, load_actor)
    if state_digest(actor.state_dict()) != state_digest(learner.state_dict()):
        raise SuphxLearningError(
            "initial immutable actor does not match learner state")


def new_runner(
        *, bundle: SuphxMicroBundle, actor_ref: CheckpointRef,
        snapshot_dir: str | Path, root_seed: int,
        schedule: SuphxSchedule) -> SynchronousSelfPlayRunner:
    _require_bundle_schedule(bundle, schedule)
    _require_actor_matches_learner(actor_ref, bundle.learner)
    return SynchronousSelfPlayRunner(
        experiment=EXPERIMENT,
        root_seed=root_seed,
        algorithm_sha256=algorithm_sha256(schedule),
        learner=bundle.learner,
        optimizer=bundle.optimizer,
        replay=bundle.replay,
        rng=bundle.rng,
        actor_ref=actor_ref,
        snapshot_dir=snapshot_dir,
    )


def resume_runner(
        resume_ref: CheckpointRef, *, bundle: SuphxMicroBundle,
        actor_ref: CheckpointRef, candidate_ref: CheckpointRef,
        snapshot_dir: str | Path, root_seed: int,
        schedule: SuphxSchedule) -> SynchronousSelfPlayRunner:
    _require_bundle_schedule(bundle, schedule)
    return SynchronousSelfPlayRunner.resume(
        resume_ref,
        experiment=EXPERIMENT,
        root_seed=root_seed,
        algorithm_sha256=algorithm_sha256(schedule),
        learner=bundle.learner,
        optimizer=bundle.optimizer,
        replay=bundle.replay,
        rng=bundle.rng,
        actor_ref=actor_ref,
        candidate_ref=candidate_ref,
        snapshot_dir=snapshot_dir,
    )


def bundle_digest(bundle: SuphxMicroBundle) -> str:
    return state_digest({
        "learner": bundle.learner.state_dict(),
        "optimizer": bundle.optimizer.state_dict(),
        "replay": bundle.replay.state_dict(),
        "rng": bundle.rng.state_dict(),
    })


def contract_digest(spec: Mapping[str, Any]) -> str:
    return state_digest(copy.deepcopy(spec))

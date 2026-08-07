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

from .exact_resume import (ReplayRing, ResumeRNGStreams,
                           exact_resume_boundary_identity, state_digest)
from .selfplay_contract import CheckpointRef, load_verified, sha256_file
from .suphx_actor import (ACTOR_SPEC_SHA256, SuphxActorError,
                          SuphxMicroCollector, derive_deal_seed, load_actor,
                          validate_sample)
from .suphx_micro import EXPERIMENT, apply_privilege_mask
from .suphx_policy import (POLICY_SPEC_SHA256, SURFACE_NAMES,
                           SuphxPolicyValue, new_from_scratch_model,
                           surface_key)
from .synchronous_selfplay import (LearnerUpdateContext,
                                   SynchronousSelfPlayRunner,
                                   _runner_contract_sha256)


LEARNING_SCHEMA = "suphx-micro-onpolicy-actor-critic-v2"
SCHEDULE_SCHEMA = "suphx-micro-privilege-schedule-v2"
VALUE_COEFFICIENT = 0.5
TARGET_ENTROPY_FRACTION = 0.60
ENTROPY_CONTROLLER_STEP = 0.001
MAX_ENTROPY_ALPHA = 0.10
GRADIENT_NORM_CAP = 1.0
REPLAY_CAPACITY = 256
LOWER_RATE_FACTOR = 0.1
LOWER_RATE_TRANSITION_SCHEMA = "suphx-micro-lower-rate-public-transition-v1"

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
    "lower_rate_public_transition": {
        "schema": LOWER_RATE_TRANSITION_SCHEMA,
        "requires_exhausted_parent_checkpoint": True,
        "requires_adopted_terminal_actor": True,
        "requires_privileged_to_zero_parent": True,
        "keep_probability": 0.0,
        "learning_rate_factor": LOWER_RATE_FACTOR,
        "model_and_entropy_controller": "preserve exact parent actor state",
        "optimizer": "fresh Adam with empty state",
        "replay": "fresh empty ring",
        "learner_rng": "fresh explicitly seeded streams",
        "deal_stream": "fresh root with finite parent/child disjointness proof",
        "automatic_training": False,
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
        if any(float(after) > float(before) for before, after in zip(
                self.keep_probabilities, self.keep_probabilities[1:])):
            raise SuphxLearningError(
                "schedule privilege keep probability cannot increase")
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


@dataclass
class SuphxLowerRateStart:
    """In-memory child segment plus its deterministic transition receipt."""

    parent_checkpoint_ref: CheckpointRef
    schedule: SuphxSchedule
    bundle: SuphxMicroBundle
    runner: SynchronousSelfPlayRunner
    transition: dict[str, Any]
    transition_sha256: str


def lower_rate_public_schedule(
        parent: SuphxSchedule, *, segment_id: str, iterations: int,
        deal_stream_root_seed: int) -> SuphxSchedule:
    """Derive the only admitted post-curriculum public-only schedule."""
    if not isinstance(parent, SuphxSchedule):
        raise SuphxLearningError("lower-rate parent schedule has wrong type")
    if (parent.keep_probabilities[0] != 1.0
            or parent.keep_probabilities[-1] != 0.0):
        raise SuphxLearningError(
            "lower-rate parent must transition from full privilege to zero")
    if isinstance(iterations, bool) or not isinstance(iterations, int) \
            or iterations <= 0:
        raise SuphxLearningError(
            "lower-rate public segment needs a positive iteration count")
    child = SuphxSchedule(
        segment_id=segment_id,
        keep_probabilities=(0.0,) * iterations,
        learning_rate=float(parent.learning_rate) * LOWER_RATE_FACTOR,
        deal_stream_root_seed=deal_stream_root_seed,
    )
    parent_deals = {
        derive_deal_seed(parent.deal_stream_root_seed, sequence, 0)
        for sequence in range(len(parent.keep_probabilities))
    }
    child_deals = {
        derive_deal_seed(child.deal_stream_root_seed, sequence, 0)
        for sequence in range(len(child.keep_probabilities))
    }
    if parent_deals & child_deals:
        raise SuphxLearningError(
            "lower-rate public deal stream overlaps its parent segment")
    return child


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


def _fresh_bundle_from_actor(
        actor_ref: CheckpointRef, *, learner_rng_seed: int,
        learning_rate: float) -> SuphxMicroBundle:
    if isinstance(learner_rng_seed, bool) \
            or not isinstance(learner_rng_seed, int) \
            or learner_rng_seed < 0:
        raise SuphxLearningError(
            "child learner RNG seed must be a nonnegative integer")
    learner = load_verified(actor_ref, load_actor)
    learner.train()
    bundle = SuphxMicroBundle(
        learner=learner,
        optimizer=torch.optim.Adam(learner.parameters(), lr=learning_rate),
        replay=ReplayRing(REPLAY_CAPACITY),
        rng=ResumeRNGStreams.seeded(learner_rng_seed),
    )
    if bundle.optimizer.state_dict()["state"] or len(bundle.replay):
        raise SuphxLearningError(
            "lower-rate optimizer/replay did not start empty")
    return bundle


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


def start_lower_rate_public_segment(
        parent_checkpoint_ref: CheckpointRef, *,
        parent_schedule: SuphxSchedule, parent_runner_root_seed: int,
        child_segment_id: str, child_iterations: int,
        child_deal_stream_root_seed: int, child_runner_root_seed: int,
        child_learner_rng_seed: int,
        child_snapshot_dir: str | Path) -> SuphxLowerRateStart:
    """Reopen one exhausted parent and create a zero-update child boundary.

    The returned runner has published only its initial candidate snapshot.  It
    has generated no game and performed no learner update; a later launch gate
    must bind and authorize any call to ``run_iteration``.
    """
    if not isinstance(parent_checkpoint_ref, CheckpointRef):
        raise SuphxLearningError("parent checkpoint reference has wrong type")
    for name, value in (
        ("parent runner root", parent_runner_root_seed),
        ("child runner root", child_runner_root_seed),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SuphxLearningError(
                f"{name} seed must be a nonnegative integer")
    parent_checkpoint_ref.verify()
    parent_boundary = exact_resume_boundary_identity(parent_checkpoint_ref)
    parent_algorithm = algorithm_sha256(parent_schedule)
    expected_parent_contract = _runner_contract_sha256(
        experiment=EXPERIMENT,
        root_seed=parent_runner_root_seed,
        algorithm_sha256=parent_algorithm,
    )
    if (parent_boundary.get("experiment") != EXPERIMENT
            or parent_boundary.get("contract_sha256") !=
            expected_parent_contract):
        raise SuphxLearningError(
            "lower-rate parent checkpoint contract differs")
    expected_progress = {
        "next_iteration": len(parent_schedule.keep_probabilities),
        "next_batch": len(parent_schedule.keep_probabilities),
    }
    if parent_boundary.get("progress") != expected_progress:
        raise SuphxLearningError(
            "lower-rate parent schedule is not exactly exhausted")
    if parent_boundary.get("actor_ref") != \
            parent_boundary.get("candidate_ref"):
        raise SuphxLearningError(
            "lower-rate parent terminal candidate was not adopted")
    actor_dict = parent_boundary["actor_ref"]
    parent_actor_ref = CheckpointRef(
        path=actor_dict["path"], sha256=actor_dict["sha256"])
    parent_actor = load_verified(parent_actor_ref, load_actor)
    parent_model_sha256 = state_digest(parent_actor.state_dict())
    if parent_model_sha256 != \
            parent_boundary["component_sha256s"]["learner"]:
        raise SuphxLearningError(
            "lower-rate parent actor differs from checkpoint learner")

    child_schedule = lower_rate_public_schedule(
        parent_schedule,
        segment_id=child_segment_id,
        iterations=child_iterations,
        deal_stream_root_seed=child_deal_stream_root_seed,
    )
    child_bundle = _fresh_bundle_from_actor(
        parent_actor_ref,
        learner_rng_seed=child_learner_rng_seed,
        learning_rate=child_schedule.learning_rate,
    )
    child_model_sha256 = state_digest(child_bundle.learner.state_dict())
    if child_model_sha256 != parent_model_sha256:
        raise SuphxLearningError(
            "lower-rate child did not preserve exact parent model state")
    parent_entropy = {
        key: float(head.entropy_alpha.item())
        for key, head in parent_actor.surfaces.items()
    }
    child_entropy = {
        key: float(head.entropy_alpha.item())
        for key, head in child_bundle.learner.surfaces.items()
    }
    if child_entropy != parent_entropy:
        raise SuphxLearningError(
            "lower-rate child did not preserve entropy-controller state")

    child_runner = new_runner(
        bundle=child_bundle,
        actor_ref=parent_actor_ref,
        snapshot_dir=child_snapshot_dir,
        root_seed=child_runner_root_seed,
        schedule=child_schedule,
    )
    child_candidate = load_verified(
        child_runner.candidate_ref, load_actor)
    child_candidate_model_sha256 = state_digest(
        child_candidate.state_dict())
    if child_candidate_model_sha256 != parent_model_sha256:
        raise SuphxLearningError(
            "lower-rate initial candidate differs from parent model")
    if (child_runner.progress.next_iteration != 0
            or child_runner.progress.next_batch != 0
            or child_bundle.optimizer.state_dict()["state"]
            or len(child_bundle.replay)):
        raise SuphxLearningError(
            "lower-rate child boundary performed hidden work")

    parent_deals = [
        derive_deal_seed(
            parent_schedule.deal_stream_root_seed, sequence, 0)
        for sequence in range(len(parent_schedule.keep_probabilities))
    ]
    child_deals = [
        derive_deal_seed(
            child_schedule.deal_stream_root_seed, sequence, 0)
        for sequence in range(len(child_schedule.keep_probabilities))
    ]
    transition = {
        "schema": LOWER_RATE_TRANSITION_SCHEMA,
        "parent_checkpoint_ref": parent_checkpoint_ref.as_dict(),
        "parent_boundary": parent_boundary,
        "parent_schedule": parent_schedule.as_dict(),
        "parent_algorithm_sha256": parent_algorithm,
        "parent_runner_root_seed": parent_runner_root_seed,
        "parent_deal_seed_digest": state_digest(parent_deals),
        "child_schedule": child_schedule.as_dict(),
        "child_algorithm_sha256": algorithm_sha256(child_schedule),
        "child_runner_contract_sha256": child_runner.contract_sha256,
        "child_runner_root_seed": child_runner_root_seed,
        "child_learner_rng_seed": child_learner_rng_seed,
        "child_deal_seed_digest": state_digest(child_deals),
        "child_actor_ref": child_runner.actor_ref.as_dict(),
        "child_initial_candidate_ref": child_runner.candidate_ref.as_dict(),
        "model_state_sha256": parent_model_sha256,
        "entropy_controller": child_entropy,
        "optimizer_reset": True,
        "replay_reset": True,
        "learner_rng_reset": True,
        "games_generated": 0,
        "training_updates": 0,
        "automatic_training": False,
    }
    parent_checkpoint_ref.verify()
    if exact_resume_boundary_identity(parent_checkpoint_ref) != parent_boundary:
        raise SuphxLearningError(
            "lower-rate parent checkpoint changed during transition")
    return SuphxLowerRateStart(
        parent_checkpoint_ref=parent_checkpoint_ref,
        schedule=child_schedule,
        bundle=child_bundle,
        runner=child_runner,
        transition=transition,
        transition_sha256=state_digest(transition),
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

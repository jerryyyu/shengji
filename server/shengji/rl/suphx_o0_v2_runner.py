"""Executable, non-authorizing runner mechanics for the Suphx O0-v2 battery.

The original O0 screen paired causal deals, but oracle and public endpoints
sampled actions from arm-specific streams.  This module integrates the reviewed
public-key CRN boundary into the actual actor batch and keeps the old learning
recipe unchanged in the ``crn_control`` cell.  ``crn_plus_margin`` differs by
exactly one additive, two-sided logit-margin term.

This is runner infrastructure only.  It deliberately contains no frozen seed
population, artifact namespace, CLI, review admission, result gate, experiment
launch, strength claim, or production authority.  Those belong to a separately
reviewed packet.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch

from ..ai.env import play_round
from ..ai.smart import SmartBot
from ..engine.game import Game
from ..engine.round import Round
from .douzero_micro import (
    BALLOT_SCHEMA,
    HISTORY_EVENT_DIM,
    HISTORY_MAX_EVENTS,
    acting_team_return,
)
from .encode import ACT_DIM, encode_action
from .exact_resume import ReplayRing, ResumeRNGStreams, state_digest
from .selfplay_contract import CheckpointRef, load_verified, sha256_file
from .suphx_actor import (
    ACTOR_SPEC_SHA256,
    REWARD_SCHEMA,
    SAMPLE_SCHEMA,
    _SAMPLE_FIELDS,
    _sample_index,
    _verify_behavior,
    clipped_attacker_bracket_return,
    load_actor,
    validate_sample,
)
from .suphx_learning import (
    ENTROPY_CONTROLLER_STEP,
    GRADIENT_NORM_CAP,
    MAX_ENTROPY_ALPHA,
    REPLAY_CAPACITY,
    TARGET_ENTROPY_FRACTION,
    VALUE_COEFFICIENT,
    SuphxMicroBundle,
)
from .suphx_micro import (
    FEATURE_SPEC_SHA256,
    MASK_SCHEMA,
    PERFECT_DIM,
    apply_privilege_mask,
    encode_perfect_features,
)
from .suphx_o0_v2_integration import (
    INTEGRATION_SPEC_SHA256,
    KeyedDecisionDraws,
    SharedPublicDecisionCRN,
)
from .suphx_o0_v2_mechanics import (
    ARMS,
    MECHANICS_SPEC_SHA256,
    UNCHANGED_ITERATIONS_PER_ARM,
    CrossedCRNSpec,
    CrossedCRNStreams,
    LogitMarginSpec,
    public_decision_key,
    two_sided_margin_loss,
)
from .suphx_policy import (
    POLICY_SPEC_SHA256,
    SURFACE_NAMES,
    SuphxPolicyValue,
    new_from_scratch_model,
    surface_key,
)
from .synchronous_selfplay import (
    ActorBatchIdentity,
    LearnerUpdateContext,
    SynchronousActorBatch,
    SynchronousSelfPlayRunner,
)


RUNNER_SCHEMA = "suphx-o0-v2-keyed-runner-v1"
ACTOR_SCHEMA = "suphx-o0-v2-keyed-ordinary-actor-v1"
SAMPLE_SCHEMA_V2 = "suphx-o0-v2-policy-gradient-sample-v1"
MASK_SCHEMA_V2 = "suphx-o0-v2-public-keyed-bernoulli-mask-v1"
ALGORITHM_SCHEMA = "suphx-o0-v2-runner-algorithm-v1"
EXPERIMENT = "suphx-o0-v2-ordinary-play-v1"

CELL_CONTROL = "crn_control"
CELL_MARGIN = "crn_plus_margin"
CELLS = (CELL_CONTROL, CELL_MARGIN)
KEEP_PROBABILITIES = {"oracle": 1.0, "public": 0.0}
LEARNING_RATE = 1e-3

_SOURCE_ROOT = Path(__file__).resolve().parents[1]
RUNNER_SOURCE_SHA256S = {
    "suphx_o0_v2_runner": sha256_file(Path(__file__).resolve()),
    "suphx_o0_v2_mechanics": sha256_file(
        Path(__file__).resolve().with_name("suphx_o0_v2_mechanics.py")),
    "suphx_o0_v2_integration": sha256_file(
        Path(__file__).resolve().with_name("suphx_o0_v2_integration.py")),
    "suphx_actor": sha256_file(
        Path(__file__).resolve().with_name("suphx_actor.py")),
    "suphx_learning": sha256_file(
        Path(__file__).resolve().with_name("suphx_learning.py")),
    "suphx_features": sha256_file(
        Path(__file__).resolve().with_name("suphx_micro.py")),
    "suphx_policy": sha256_file(
        Path(__file__).resolve().with_name("suphx_policy.py")),
    "synchronous_selfplay": sha256_file(
        Path(__file__).resolve().with_name("synchronous_selfplay.py")),
    "round_driver": sha256_file(_SOURCE_ROOT / "ai" / "env.py"),
    "smart_controls": sha256_file(_SOURCE_ROOT / "ai" / "smart.py"),
    "game": sha256_file(_SOURCE_ROOT / "engine" / "game.py"),
    "round": sha256_file(_SOURCE_ROOT / "engine" / "round.py"),
}

ACTOR_SPEC: dict[str, Any] = {
    "schema": ACTOR_SCHEMA,
    "claim": "keyed actor mechanics only; no experiment authority",
    "experiment": EXPERIMENT,
    "feature_spec_sha256": FEATURE_SPEC_SHA256,
    "policy_spec_sha256": POLICY_SPEC_SHA256,
    "legacy_actor_spec_sha256": ACTOR_SPEC_SHA256,
    "mechanics_spec_sha256": MECHANICS_SPEC_SHA256,
    "integration_spec_sha256": INTEGRATION_SPEC_SHA256,
    "source_sha256s": RUNNER_SOURCE_SHA256S,
    "ordinary_play_only": True,
    "declaration": "SmartBot",
    "burial": "SmartBot",
    "rounds_per_iteration": 1,
    "public_projection_constructed_once_per_decision": True,
    "perfect_features_constructed_separately_after_public_key": True,
    "mask_schema": MASK_SCHEMA_V2,
    "same_public_context_same_mask_and_action_draws": True,
    "arm_identity_in_draw_key": False,
    "experiment_launch_authorized": False,
    "strength_claim": False,
    "production_promotion": False,
}
ACTOR_SPEC_SHA256_V2 = state_digest(ACTOR_SPEC)

RUNNER_SPEC: dict[str, Any] = {
    "schema": RUNNER_SCHEMA,
    "claim": "runner mechanics only; no frozen population or launch authority",
    "actor_spec_sha256": ACTOR_SPEC_SHA256_V2,
    "mechanics_spec_sha256": MECHANICS_SPEC_SHA256,
    "integration_spec_sha256": INTEGRATION_SPEC_SHA256,
    "cells": [
        {"name": CELL_CONTROL, "margin_controller": False},
        {"name": CELL_MARGIN, "margin_controller": True},
    ],
    "unchanged_recipe": {
        "iterations_per_endpoint": UNCHANGED_ITERATIONS_PER_ARM,
        "rounds_per_iteration": 1,
        "updates_per_iteration": 1,
        "learning_rate": LEARNING_RATE,
        "reward_target": "clipped-acting-team-attacker-point-bracket-v2",
        "optimizer": "Adam-defaults",
        "value_coefficient": VALUE_COEFFICIENT,
        "target_entropy_fraction": TARGET_ENTROPY_FRACTION,
        "entropy_controller_step": ENTROPY_CONTROLLER_STEP,
        "maximum_entropy_alpha": MAX_ENTROPY_ALPHA,
        "gradient_norm_cap": GRADIENT_NORM_CAP,
        "replay_capacity": REPLAY_CAPACITY,
    },
    "experiment_launch_authorized": False,
    "o1_authorized": False,
    "strength_claim": False,
    "production_promotion": False,
}
RUNNER_SPEC_SHA256 = state_digest(RUNNER_SPEC)


class SuphxO0V2RunnerError(RuntimeError):
    """The executable O0-v2 actor or learner boundary drifted."""


@dataclass(frozen=True)
class O0V2Algorithm:
    """One endpoint's exact algorithm contract, absent population authority."""

    crn_spec: CrossedCRNSpec
    training_seed_index: int
    arm: str
    cell: str
    margin_spec: LogitMarginSpec | None = None
    learning_rate: float = LEARNING_RATE

    def __post_init__(self) -> None:
        if not isinstance(self.crn_spec, CrossedCRNSpec):
            raise SuphxO0V2RunnerError("algorithm requires an exact CRN spec")
        if self.training_seed_index not in self.crn_spec.training_seed_indices:
            raise SuphxO0V2RunnerError("algorithm training seed is outside CRN spec")
        if self.arm not in ARMS or self.cell not in CELLS:
            raise SuphxO0V2RunnerError("algorithm arm/cell is unsupported")
        if self.learning_rate != LEARNING_RATE:
            raise SuphxO0V2RunnerError("O0-v2 cannot change the frozen learning rate")
        if self.cell == CELL_CONTROL and self.margin_spec is not None:
            raise SuphxO0V2RunnerError("control cell cannot carry a margin spec")
        if self.cell == CELL_MARGIN and not isinstance(
                self.margin_spec, LogitMarginSpec):
            raise SuphxO0V2RunnerError("margin cell requires an exact margin spec")

    @property
    def keep_probability(self) -> float:
        return KEEP_PROBABILITIES[self.arm]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": ALGORITHM_SCHEMA,
            "runner_spec_sha256": RUNNER_SPEC_SHA256,
            "crn_spec": self.crn_spec.as_dict(),
            "training_seed_index": self.training_seed_index,
            "arm": self.arm,
            "cell": self.cell,
            "keep_probability": self.keep_probability,
            "iterations": self.crn_spec.iterations_per_arm,
            "learning_rate": self.learning_rate,
            "margin_spec": None if self.margin_spec is None
            else self.margin_spec.as_dict(),
        }

    @property
    def sha256(self) -> str:
        return state_digest(self.as_dict())


@dataclass(frozen=True)
class _DecisionRecordV2:
    draws: KeyedDecisionDraws
    perfect: np.ndarray
    mask: np.ndarray
    candidates: np.ndarray
    chosen_index: int
    behavior_log_probability: float
    behavior_value: float


class SuphxO0V2OrdinaryActor:
    """Categorical ordinary-play actor whose draws are public-context keyed."""

    def __init__(
            self, model: SuphxPolicyValue, *, keep_probability: float,
            trace: SharedPublicDecisionCRN):
        if not isinstance(model, SuphxPolicyValue):
            raise SuphxO0V2RunnerError("actor model has the wrong type")
        if keep_probability not in tuple(KEEP_PROBABILITIES.values()):
            raise SuphxO0V2RunnerError("actor privilege endpoint is unsupported")
        if not isinstance(trace, SharedPublicDecisionCRN):
            raise SuphxO0V2RunnerError("actor requires a shared public CRN trace")
        self.model = model
        self.keep_probability = float(keep_probability)
        self.trace = trace
        self.records: list[_DecisionRecordV2] = []

    def decide_play(self, rnd: Round, seat: int) -> list[str]:
        draws = self.trace.decision_draws(rnd, seat)
        projection = draws.projection
        perfect = encode_perfect_features(rnd, seat)
        mask = np.fromiter(
            (1.0 if draw < self.keep_probability else 0.0
             for draw in draws.mask_uniforms),
            dtype=np.float32,
            count=PERFECT_DIM,
        )
        masked = apply_privilege_mask(perfect, mask)
        candidates = np.asarray([
            encode_action(action, rnd) for action in projection.candidate_cards
        ], dtype=np.float32).reshape(-1, ACT_DIM)
        # The projection is immutable so the key cannot be invalidated.  Torch
        # warns on read-only NumPy buffers, so score byte-identical writable
        # copies; sample validation recomputes the key from those exact bytes.
        observation = projection.observation.copy()
        legal_private = projection.legal_private.copy()
        history = projection.history.copy()
        logits, value = self.model.score_candidates(
            role=projection.role,
            surface=projection.surface,
            observation=observation,
            legal_private=legal_private,
            history=history,
            masked_perfect=masked,
            actions=candidates,
        )
        probabilities = torch.softmax(logits, dim=0)
        log_probabilities = torch.log_softmax(logits, dim=0)
        chosen = _sample_index(probabilities, draws.action_uniform)
        probability = float(probabilities[chosen].item())
        if not 0.0 < probability <= 1.0:
            raise SuphxO0V2RunnerError("chosen behavior probability is invalid")
        self.records.append(_DecisionRecordV2(
            draws=draws,
            perfect=perfect.copy(),
            mask=mask,
            candidates=candidates,
            chosen_index=chosen,
            behavior_log_probability=float(log_probabilities[chosen].item()),
            behavior_value=float(value.item()),
        ))
        return list(projection.candidate_cards[chosen])


class _Composite:
    def __init__(self, actor: SuphxO0V2OrdinaryActor):
        self.actor = actor
        self.control = SmartBot()

    def decide_declare(self, rnd: Round, seat: int, final: bool = False):
        return self.control.decide_declare(rnd, seat, final=final)

    def decide_bury(self, rnd: Round, seat: int):
        return self.control.decide_bury(rnd, seat)

    def decide_play(self, rnd: Round, seat: int):
        return self.actor.decide_play(rnd, seat)


def _sample_from_record(
        record: _DecisionRecordV2, *, identity: ActorBatchIdentity,
        decision_index: int, algorithm: O0V2Algorithm,
        attacker_bracket_return: float) -> dict[str, Any]:
    projection = record.draws.projection
    history_length = len(projection.history)
    history = np.zeros(
        (HISTORY_MAX_EVENTS, HISTORY_EVENT_DIM), dtype=np.float32)
    history[:history_length] = projection.history
    return {
        "schema": SAMPLE_SCHEMA_V2,
        "surface": "ordinary_play",
        "feature_spec_sha256": FEATURE_SPEC_SHA256,
        "policy_spec_sha256": POLICY_SPEC_SHA256,
        "actor_spec_sha256": ACTOR_SPEC_SHA256_V2,
        "ballot_schema": BALLOT_SCHEMA,
        "reward_schema": REWARD_SCHEMA,
        "mask_schema": MASK_SCHEMA_V2,
        "role": projection.role,
        "decision_surface": projection.surface,
        "observation": projection.observation.copy(),
        "legal_private": projection.legal_private.copy(),
        "history": history,
        "history_length": history_length,
        "perfect": record.perfect.copy(),
        "mask": record.mask.copy(),
        "keep_probability": algorithm.keep_probability,
        "candidates": record.candidates.copy(),
        "candidate_cards": projection.candidate_cards,
        "chosen_index": record.chosen_index,
        "action_cards": projection.candidate_cards[record.chosen_index],
        "action_draw": record.draws.action_uniform,
        "behavior_log_probability": record.behavior_log_probability,
        "behavior_value": record.behavior_value,
        "attacker_bracket_return": float(attacker_bracket_return),
        "target": acting_team_return(attacker_bracket_return, projection.role),
        "seat": projection.seat,
        "round_index": 0,
        "decision_index": decision_index,
        "game_seed": projection.deal_seed,
        "actor_sha256": identity.actor_ref.sha256,
        "batch_sequence": identity.sequence,
        "runner_contract_sha256": identity.contract_sha256,
        "runner_spec_sha256": RUNNER_SPEC_SHA256,
        "algorithm_sha256": algorithm.sha256,
        "crn_spec_sha256": state_digest(algorithm.crn_spec.as_dict()),
        "crn_root_seed": algorithm.crn_spec.root_seed,
        "training_seed_index": algorithm.training_seed_index,
        "cell": algorithm.cell,
        "arm": algorithm.arm,
        "public_decision_key": projection.public_key,
        "public_key_occurrence": record.draws.occurrence,
    }


_V2_EXTRA_FIELDS = {
    "runner_spec_sha256", "algorithm_sha256", "crn_spec_sha256",
    "crn_root_seed", "training_seed_index", "cell", "arm",
    "public_decision_key", "public_key_occurrence",
}
_V2_FIELDS = (_SAMPLE_FIELDS - {"deal_stream_root_seed"}) | _V2_EXTRA_FIELDS


def _legacy_sample(sample: Mapping[str, Any]) -> dict[str, Any]:
    legacy = {
        key: sample[key] for key in _SAMPLE_FIELDS
        if key != "deal_stream_root_seed"
    }
    legacy.update({
        "schema": SAMPLE_SCHEMA,
        "actor_spec_sha256": ACTOR_SPEC_SHA256,
        "mask_schema": MASK_SCHEMA,
        "deal_stream_root_seed": sample["crn_root_seed"],
    })
    return legacy


def validate_o0_v2_sample(
        sample: object, *, identity: ActorBatchIdentity | None = None,
        contract_sha256: str | None = None,
        algorithm: O0V2Algorithm | None = None) -> None:
    if (identity is None) == (contract_sha256 is None):
        raise SuphxO0V2RunnerError(
            "sample validation requires exactly one provenance boundary")
    if not isinstance(sample, Mapping) or set(sample) != _V2_FIELDS:
        raise SuphxO0V2RunnerError("O0-v2 sample fields mismatch")
    if sample.get("schema") != SAMPLE_SCHEMA_V2 \
            or sample.get("actor_spec_sha256") != ACTOR_SPEC_SHA256_V2 \
            or sample.get("mask_schema") != MASK_SCHEMA_V2 \
            or sample.get("runner_spec_sha256") != RUNNER_SPEC_SHA256 \
            or sample.get("cell") not in CELLS \
            or sample.get("arm") not in ARMS:
        raise SuphxO0V2RunnerError("O0-v2 sample identity drift")
    validate_sample(
        _legacy_sample(sample), identity=identity,
        contract_sha256=contract_sha256)
    expected_contract = identity.contract_sha256 if identity is not None \
        else contract_sha256
    if sample["runner_contract_sha256"] != expected_contract:
        raise SuphxO0V2RunnerError("O0-v2 sample runner contract drift")
    for name in ("crn_root_seed", "training_seed_index",
                 "public_key_occurrence"):
        value = sample[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SuphxO0V2RunnerError(f"O0-v2 sample {name} is invalid")
    for name in ("algorithm_sha256", "crn_spec_sha256",
                 "public_decision_key"):
        value = sample[name]
        if not isinstance(value, str) or len(value) != 64 \
                or any(char not in "0123456789abcdef" for char in value):
            raise SuphxO0V2RunnerError(f"O0-v2 sample {name} is malformed")
    expected_public_key = public_decision_key(
        deal_seed=sample["game_seed"],
        seat=sample["seat"],
        role=sample["role"],
        surface=sample["decision_surface"],
        observation=sample["observation"],
        legal_private=sample["legal_private"],
        history=sample["history"][:sample["history_length"]].copy(),
        candidate_cards=sample["candidate_cards"],
    )
    if sample["public_decision_key"] != expected_public_key:
        raise SuphxO0V2RunnerError("O0-v2 sample public decision key drift")
    if algorithm is not None and (
            sample["algorithm_sha256"] != algorithm.sha256
            or sample["crn_spec_sha256"]
            != state_digest(algorithm.crn_spec.as_dict())
            or sample["crn_root_seed"] != algorithm.crn_spec.root_seed
            or sample["training_seed_index"] != algorithm.training_seed_index
            or sample["cell"] != algorithm.cell
            or sample["arm"] != algorithm.arm
            or sample["keep_probability"] != algorithm.keep_probability
            or sample["batch_sequence"]
            >= algorithm.crn_spec.iterations_per_arm):
        raise SuphxO0V2RunnerError("O0-v2 sample algorithm provenance drift")


def _verify_o0_v2_behavior(
        sample: Mapping[str, Any], model: SuphxPolicyValue) -> None:
    _verify_behavior(_legacy_sample(sample), model)


@dataclass
class SuphxO0V2Collector:
    expected_runner_contract_sha256: str
    algorithm: O0V2Algorithm
    key_receipt: dict[str, Any] | None = None

    def __call__(self, identity: ActorBatchIdentity) -> SynchronousActorBatch:
        if identity.experiment != EXPERIMENT or identity.purpose != "actor" \
                or identity.contract_sha256 \
                != self.expected_runner_contract_sha256 \
                or identity.sequence >= self.algorithm.crn_spec.iterations_per_arm:
            raise SuphxO0V2RunnerError("actor batch identity/contract mismatch")
        if self.key_receipt is not None:
            raise SuphxO0V2RunnerError("collector instance cannot be reused")
        streams = CrossedCRNStreams(
            self.algorithm.crn_spec,
            self.algorithm.training_seed_index,
            identity.sequence,
        )
        trace = SharedPublicDecisionCRN(streams)
        model = load_verified(identity.actor_ref, load_actor)
        actor = SuphxO0V2OrdinaryActor(
            model,
            keep_probability=self.algorithm.keep_probability,
            trace=trace,
        )
        game = Game(random.Random(streams.deal_seed()))
        play_round(game, [_Composite(actor) for _ in range(4)])
        if game.round is None or game.result is None or not actor.records:
            raise SuphxO0V2RunnerError("actor collection ended without a round")
        attacker_return = clipped_attacker_bracket_return(
            game.result.attacker_points)
        samples = tuple(_sample_from_record(
            record,
            identity=identity,
            decision_index=index,
            algorithm=self.algorithm,
            attacker_bracket_return=attacker_return,
        ) for index, record in enumerate(actor.records))
        for sample in samples:
            validate_o0_v2_sample(
                sample, identity=identity, algorithm=self.algorithm)
            _verify_o0_v2_behavior(sample, model)
        self.key_receipt = trace.receipt(arm=self.algorithm.arm)
        mechanics = self.key_receipt["mechanics_receipt"]
        if mechanics["deal_seed"] != streams.deal_seed() \
                or mechanics["public_decision_keys"] != [
                    sample["public_decision_key"] for sample in samples]:
            raise SuphxO0V2RunnerError("actor samples/key receipt drift")
        return SynchronousActorBatch(identity=identity, samples=samples)


def _preupdate_terms(
        model: SuphxPolicyValue, sample: Mapping[str, Any],
        margin_spec: LogitMarginSpec | None) \
        -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, float, str,
                 torch.Tensor, float]:
    masked = apply_privilege_mask(sample["perfect"], sample["mask"])
    history = sample["history"][:sample["history_length"]].copy()
    logits, value = model.score_candidates(
        role=sample["role"], surface=sample["decision_surface"],
        observation=sample["observation"],
        legal_private=sample["legal_private"], history=history,
        masked_perfect=masked, actions=sample["candidates"], grad=True)
    log_probabilities = torch.log_softmax(logits, dim=0)
    probabilities = torch.softmax(logits, dim=0)
    chosen_log_probability = log_probabilities[sample["chosen_index"]]
    if not math.isclose(
            float(chosen_log_probability.detach().item()),
            sample["behavior_log_probability"], rel_tol=0.0, abs_tol=1e-7):
        raise SuphxO0V2RunnerError(
            "learner does not match immutable behavior actor pre-update")
    if not math.isclose(
            float(value.detach().item()), sample["behavior_value"],
            rel_tol=0.0, abs_tol=1e-7):
        raise SuphxO0V2RunnerError(
            "learner value does not match immutable behavior actor pre-update")
    entropy = -(probabilities * log_probabilities).sum()
    target_entropy = TARGET_ENTROPY_FRACTION * math.log(len(logits))
    key = surface_key(sample["role"], sample["decision_surface"])
    if margin_spec is None:
        margin_loss = logits.sum() * 0.0
        observed_margin = 0.0 if len(logits) == 1 else float(
            (torch.topk(logits.detach(), 2).values[0]
             - torch.topk(logits.detach(), 2).values[1]).item())
    else:
        margin_loss, observed = two_sided_margin_loss(logits, margin_spec)
        observed_margin = float(observed.item())
    return (chosen_log_probability, value, entropy, target_entropy, key,
            margin_loss, observed_margin)


@dataclass
class SuphxO0V2PolicyGradientUpdate:
    algorithm: O0V2Algorithm
    margin_summary: dict[str, dict[str, float | int]] | None = None

    def __call__(self, context: LearnerUpdateContext) -> None:
        if not isinstance(context.learner, SuphxPolicyValue):
            raise SuphxO0V2RunnerError("learner has the wrong policy type")
        if context.batch.identity.sequence != context.progress.next_iteration:
            raise SuphxO0V2RunnerError("batch/update sequence drift")
        samples = list(context.batch.samples)
        if not samples:
            raise SuphxO0V2RunnerError("cannot update from an empty actor batch")
        policy_terms: list[torch.Tensor] = []
        value_terms: list[torch.Tensor] = []
        entropy_terms: list[torch.Tensor] = []
        margin_terms: list[torch.Tensor] = []
        entropy_by_surface: dict[str, list[torch.Tensor]] = defaultdict(list)
        target_entropy_by_surface: dict[str, list[float]] = defaultdict(list)
        margins_by_surface: dict[str, list[float]] = defaultdict(list)
        for sample in samples:
            validate_o0_v2_sample(
                sample,
                contract_sha256=context.batch.identity.contract_sha256,
                algorithm=self.algorithm,
            )
            (log_probability, value, entropy, target_entropy, key,
             margin_loss, observed_margin) = _preupdate_terms(
                context.learner, sample, self.algorithm.margin_spec)
            target = torch.tensor(sample["target"], dtype=torch.float32)
            advantage = target - value
            policy_terms.append(-log_probability * advantage.detach())
            value_terms.append(advantage.square())
            alpha = context.learner.surfaces[key].entropy_alpha.detach()
            entropy_terms.append(alpha * entropy)
            margin_terms.append(margin_loss)
            entropy_by_surface[key].append(entropy.detach())
            target_entropy_by_surface[key].append(target_entropy)
            margins_by_surface[key].append(observed_margin)

        loss = (
            torch.stack(policy_terms).mean()
            + VALUE_COEFFICIENT * torch.stack(value_terms).mean()
            - torch.stack(entropy_terms).mean()
            + torch.stack(margin_terms).mean()
        )
        if not bool(torch.isfinite(loss)):
            raise SuphxO0V2RunnerError("policy-gradient loss is non-finite")
        context.optimizer.zero_grad(set_to_none=True)
        loss.backward()
        gradient_norm = torch.nn.utils.clip_grad_norm_(
            context.learner.parameters(), GRADIENT_NORM_CAP)
        if not bool(torch.isfinite(gradient_norm)):
            context.optimizer.zero_grad(set_to_none=True)
            raise SuphxO0V2RunnerError("policy-gradient norm is non-finite")
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
        self.margin_summary = {
            key: {
                "decisions": len(values),
                "mean_top_two_margin": float(np.mean(values)),
            }
            for key, values in sorted(margins_by_surface.items())
        }


def new_o0_v2_bundle(
        *, model_seed: int, learner_rng_seed: int) -> SuphxMicroBundle:
    learner = new_from_scratch_model(model_seed)
    return SuphxMicroBundle(
        learner=learner,
        optimizer=torch.optim.Adam(learner.parameters(), lr=LEARNING_RATE),
        replay=ReplayRing(REPLAY_CAPACITY),
        rng=ResumeRNGStreams.seeded(learner_rng_seed),
    )


def _require_bundle(
        bundle: SuphxMicroBundle, actor_ref: CheckpointRef) -> None:
    if not isinstance(bundle, SuphxMicroBundle):
        raise SuphxO0V2RunnerError("runner bundle has the wrong type")
    groups = bundle.optimizer.param_groups
    if len(groups) != 1 or groups[0].get("lr") != LEARNING_RATE:
        raise SuphxO0V2RunnerError("optimizer differs from frozen learning rate")
    actor = load_verified(actor_ref, load_actor)
    if state_digest(actor.state_dict()) != state_digest(
            bundle.learner.state_dict()):
        raise SuphxO0V2RunnerError("initial actor does not match learner")


def new_o0_v2_runner(
        *, bundle: SuphxMicroBundle, actor_ref: CheckpointRef,
        snapshot_dir: str | Path, root_seed: int,
        algorithm: O0V2Algorithm) -> SynchronousSelfPlayRunner:
    _require_bundle(bundle, actor_ref)
    return SynchronousSelfPlayRunner(
        experiment=EXPERIMENT,
        root_seed=root_seed,
        algorithm_sha256=algorithm.sha256,
        learner=bundle.learner,
        optimizer=bundle.optimizer,
        replay=bundle.replay,
        rng=bundle.rng,
        actor_ref=actor_ref,
        snapshot_dir=snapshot_dir,
    )


def resume_o0_v2_runner(
        resume_ref: CheckpointRef, *, bundle: SuphxMicroBundle,
        actor_ref: CheckpointRef, candidate_ref: CheckpointRef,
        snapshot_dir: str | Path, root_seed: int,
        algorithm: O0V2Algorithm) -> SynchronousSelfPlayRunner:
    groups = bundle.optimizer.param_groups
    if len(groups) != 1 or groups[0].get("lr") != LEARNING_RATE:
        raise SuphxO0V2RunnerError("optimizer differs from frozen learning rate")
    return SynchronousSelfPlayRunner.resume(
        resume_ref,
        experiment=EXPERIMENT,
        root_seed=root_seed,
        algorithm_sha256=algorithm.sha256,
        learner=bundle.learner,
        optimizer=bundle.optimizer,
        replay=bundle.replay,
        rng=bundle.rng,
        actor_ref=actor_ref,
        candidate_ref=candidate_ref,
        snapshot_dir=snapshot_dir,
    )

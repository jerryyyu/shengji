"""Immutable ordinary-play actor boundary for the Suphx microbaseline.

The actor uses separate named RNG streams for Bernoulli privilege masks and
policy sampling, plus an externally frozen actor-independent deal stream.  It
records the complete ordered ballot and behavior probability and emits clipped
role-signed attacker-point-bracket samples.  This module deliberately contains
no learner update, curriculum schedule, CLI, registry entry, evidence gate, or
production policy.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch

from ..ai.env import play_round
from ..ai.smart import SmartBot
from ..engine.game import Game
from ..engine.round import Round
from .actions import enumerate_actions
from .douzero_micro import (
    BALLOT_SCHEMA,
    HISTORY_EVENT_DIM,
    HISTORY_MAX_EVENTS,
    ROLE_ATTACKER,
    ROLE_DEFENDER,
    acting_team_return,
    terminal_attacker_return as _legacy_clipped_attacker_bracket,
)
from .encode import ACT_DIM, CARD_INDEX, OBS_DIM, encode_action
from .exact_resume import state_digest
from .selfplay_contract import (CheckpointRef, load_verified,
                                save_immutable_snapshot, sha256_file)
from .suphx_micro import (EXPERIMENT, FEATURE_SPEC_SHA256, LEGAL_PRIVATE_DIM,
                          MASK_SCHEMA, PERFECT_DIM, SuphxMicroError,
                          apply_privilege_mask, draw_privilege_mask,
                          encode_feature_partition)
from .suphx_policy import (POLICY_SPEC_SHA256, SURFACE_NAMES,
                           SuphxPolicyValue, new_from_scratch_model, role_for,
                           surface_for)
from .synchronous_selfplay import (ActorBatchIdentity, SynchronousActorBatch)


ACTOR_SCHEMA = "suphx-micro-immutable-ordinary-actor-v2"
SAMPLE_SCHEMA = "suphx-micro-policy-gradient-sample-v2"
REWARD_SCHEMA = "clipped-acting-team-attacker-point-bracket-v2"
EXPLORATION_SCHEMA = "categorical-and-causal-deal-named-streams-v2"
ROUNDS_PER_BATCH = 1

_SOURCE_ROOT = Path(__file__).resolve().parents[1]
ACTOR_SOURCE_SHA256S = {
    "suphx_actor": sha256_file(Path(__file__).resolve()),
    "suphx_features": sha256_file(
        Path(__file__).resolve().with_name("suphx_micro.py")),
    "suphx_policy": sha256_file(
        Path(__file__).resolve().with_name("suphx_policy.py")),
    "actions": sha256_file(Path(__file__).resolve().with_name("actions.py")),
    "encode": sha256_file(Path(__file__).resolve().with_name("encode.py")),
    "round_driver": sha256_file(_SOURCE_ROOT / "ai" / "env.py"),
    "smart_controls": sha256_file(_SOURCE_ROOT / "ai" / "smart.py"),
    "game": sha256_file(_SOURCE_ROOT / "engine" / "game.py"),
    "round": sha256_file(_SOURCE_ROOT / "engine" / "round.py"),
}

ACTOR_SPEC: dict[str, Any] = {
    "schema": ACTOR_SCHEMA,
    "claim": "actor mechanics only; no learning or strength authority",
    "experiment": EXPERIMENT,
    "feature_spec_sha256": FEATURE_SPEC_SHA256,
    "policy_spec_sha256": POLICY_SPEC_SHA256,
    "source_sha256s": ACTOR_SOURCE_SHA256S,
    "surface": "ordinary_play_only",
    "ballot": {
        "schema": BALLOT_SCHEMA,
        "exhaustive_follows": False,
        "include_throws": False,
        "ordered_complete_ballot_stored": True,
    },
    "sampling": {
        "schema": EXPLORATION_SCHEMA,
        "distribution": "softmax_policy_logits",
        "one_uniform_draw_per_decision": True,
        "mask_rng_separate_from_action_rng": True,
        "deal_rng_separate_from_mask_and_action_rngs": True,
        "deal_stream_root_externally_frozen": True,
        "deal_seed_excludes_actor_and_arm_identity": True,
        "mask_schema": MASK_SCHEMA,
    },
    "reward": {
        "schema": REWARD_SCHEMA,
        "target": (
            "role_sign * clipped attacker-point terminal bracket in "
            "{-3.5,-2.5,-1.5,0.5,1.5,2.5,3.5}"
        ),
        "not_uncapped_engine_level_change": True,
        "oracle_scalar": False,
    },
    "controls": {
        "declare": "SmartBot",
        "bury": "SmartBot",
        "ordinary_play_fallback": False,
    },
    "batch": {"rounds": ROUNDS_PER_BATCH},
}
ACTOR_SPEC_SHA256 = state_digest(ACTOR_SPEC)


class SuphxActorError(SuphxMicroError):
    """The immutable actor/sample contract was violated."""


def clipped_attacker_bracket_return(attacker_points: int) -> float:
    """Legacy bounded attacker-point bracket, named without overclaiming.

    This is intentionally not ``RoundResult.level_change``: attacker results
    above the third 40-point step remain capped at ``+3.5``.  The bounded O0/O1
    launch packet may compare this target, but may not describe it as uncapped
    engine progression utility.
    """
    return _legacy_clipped_attacker_bracket(attacker_points)


def _child_seed(parent: int, domain: str, sequence: int) -> int:
    if isinstance(parent, bool) or not isinstance(parent, int):
        raise SuphxActorError("parent seed must be an integer")
    if not isinstance(domain, str) or not domain:
        raise SuphxActorError("seed domain must be nonempty")
    if isinstance(sequence, bool) or not isinstance(sequence, int) \
            or sequence < 0:
        raise SuphxActorError("seed sequence must be a nonnegative integer")
    payload = f"{parent}|{domain}|{sequence}".encode("ascii")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def load_actor(path: str) -> SuphxPolicyValue:
    model = new_from_scratch_model(0)
    state = torch.load(path, map_location="cpu", weights_only=True)
    model.load_state_dict(state, strict=True)
    model.eval()
    return model


def publish_initial_actor(
        model: SuphxPolicyValue, directory: str | Path) -> CheckpointRef:
    if not isinstance(model, SuphxPolicyValue):
        raise SuphxActorError("initial actor has the wrong policy type")
    return save_immutable_snapshot(
        model, directory, label="suphx_actor", sequence=0)


def _sample_index(probabilities: torch.Tensor, draw: float) -> int:
    if probabilities.ndim != 1 or not len(probabilities):
        raise SuphxActorError("policy probability vector is empty or malformed")
    if isinstance(draw, bool) or not isinstance(draw, float) \
            or not math.isfinite(draw) or not 0.0 <= draw < 1.0:
        raise SuphxActorError("action draw must be a float in [0, 1)")
    values = [float(value) for value in probabilities.detach().cpu().tolist()]
    if any(not math.isfinite(value) or value < 0.0 for value in values):
        raise SuphxActorError("policy probabilities are invalid")
    total = sum(values)
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=2e-6):
        raise SuphxActorError("policy probabilities do not sum to one")
    cumulative = 0.0
    for index, value in enumerate(values):
        cumulative += value
        if draw < cumulative:
            return index
    # Float32 softmax may sum just below one.  The validated final bucket owns
    # that representational remainder.
    return len(values) - 1


@dataclass
class _DecisionRecord:
    role: int
    surface: int
    observation: np.ndarray
    legal_private: np.ndarray
    history: np.ndarray
    perfect: np.ndarray
    mask: np.ndarray
    candidates: np.ndarray
    candidate_cards: tuple[tuple[str, ...], ...]
    chosen_index: int
    action_draw: float
    behavior_log_probability: float
    behavior_value: float
    seat: int


class SuphxOrdinaryActor:
    """Frozen categorical policy for every ordinary-play seat."""

    def __init__(
            self, model: SuphxPolicyValue, *, keep_probability: float,
            mask_rng: random.Random, action_rng: random.Random):
        if not isinstance(model, SuphxPolicyValue):
            raise SuphxActorError("actor model has the wrong type")
        if not isinstance(mask_rng, random.Random) \
                or not isinstance(action_rng, random.Random) \
                or mask_rng is action_rng:
            raise SuphxActorError("mask and action RNGs must be separate locals")
        # Validate the probability without consuming the real mask stream.
        draw_privilege_mask(keep_probability, random.Random(0))
        self.model = model
        self.keep_probability = float(keep_probability)
        self.mask_rng = mask_rng
        self.action_rng = action_rng
        self.records: list[_DecisionRecord] = []

    def decide_declare(self, *_args, **_kwargs):
        raise SuphxActorError("Suphx micro actor does not implement declaration")

    def decide_bury(self, *_args, **_kwargs):
        raise SuphxActorError("Suphx micro actor does not implement burial")

    def decide_play(self, rnd: Round, seat: int) -> list[str]:
        if rnd.phase != "play" or rnd.turn != seat or rnd.trick is None \
                or rnd.ordering is None:
            raise SuphxActorError(
                "Suphx micro actor supports only a legal ordinary-play turn")
        actions = enumerate_actions(
            rnd, seat, exhaustive_follows=False, include_throws=False)
        if not actions:
            raise SuphxActorError("ordinary-play ballot is empty")
        partition = encode_feature_partition(rnd, seat)
        mask = draw_privilege_mask(self.keep_probability, self.mask_rng)
        masked = apply_privilege_mask(partition["perfect"], mask)
        encoded_actions = np.asarray(
            [encode_action(action, rnd) for action in actions],
            dtype=np.float32,
        ).reshape(-1, ACT_DIM)
        role = role_for(rnd, seat)
        surface = surface_for(rnd)
        logits, value = self.model.score_candidates(
            role=role,
            surface=surface,
            observation=partition["observation"],
            legal_private=partition["legal_private"],
            history=partition["public_history"],
            masked_perfect=masked,
            actions=encoded_actions,
        )
        probabilities = torch.softmax(logits, dim=0)
        log_probabilities = torch.log_softmax(logits, dim=0)
        action_draw = self.action_rng.random()
        chosen = _sample_index(probabilities, action_draw)
        probability = float(probabilities[chosen].item())
        if not 0.0 < probability <= 1.0:
            raise SuphxActorError("chosen behavior probability is invalid")
        self.records.append(_DecisionRecord(
            role=role,
            surface=surface,
            observation=partition["observation"].copy(),
            legal_private=partition["legal_private"].copy(),
            history=partition["public_history"].copy(),
            perfect=partition["perfect"].copy(),
            mask=mask.copy(),
            candidates=encoded_actions.copy(),
            candidate_cards=tuple(tuple(action) for action in actions),
            chosen_index=chosen,
            action_draw=action_draw,
            behavior_log_probability=float(log_probabilities[chosen].item()),
            behavior_value=float(value.item()),
            seat=seat,
        ))
        return list(actions[chosen])


class _ExplicitSurfaceComposite:
    def __init__(self, actor: SuphxOrdinaryActor):
        self.actor = actor
        self.control = SmartBot()

    def decide_declare(self, rnd: Round, seat: int, final: bool = False):
        return self.control.decide_declare(rnd, seat, final=final)

    def decide_bury(self, rnd: Round, seat: int):
        return self.control.decide_bury(rnd, seat)

    def decide_play(self, rnd: Round, seat: int):
        return self.actor.decide_play(rnd, seat)


def _sample_from_record(
        record: _DecisionRecord, *, identity: ActorBatchIdentity,
        round_index: int, decision_index: int, game_seed: int,
        deal_stream_root_seed: int, attacker_bracket_return: float,
        keep_probability: float) -> dict[str, Any]:
    history_length = len(record.history)
    history = np.zeros(
        (HISTORY_MAX_EVENTS, HISTORY_EVENT_DIM), dtype=np.float32)
    history[:history_length] = record.history
    return {
        "schema": SAMPLE_SCHEMA,
        "surface": "ordinary_play",
        "feature_spec_sha256": FEATURE_SPEC_SHA256,
        "policy_spec_sha256": POLICY_SPEC_SHA256,
        "actor_spec_sha256": ACTOR_SPEC_SHA256,
        "ballot_schema": BALLOT_SCHEMA,
        "reward_schema": REWARD_SCHEMA,
        "mask_schema": MASK_SCHEMA,
        "role": record.role,
        "decision_surface": record.surface,
        "observation": record.observation.copy(),
        "legal_private": record.legal_private.copy(),
        "history": history,
        "history_length": history_length,
        "perfect": record.perfect.copy(),
        "mask": record.mask.copy(),
        "keep_probability": float(keep_probability),
        "candidates": record.candidates.copy(),
        "candidate_cards": record.candidate_cards,
        "chosen_index": record.chosen_index,
        "action_cards": record.candidate_cards[record.chosen_index],
        "action_draw": record.action_draw,
        "behavior_log_probability": record.behavior_log_probability,
        "behavior_value": record.behavior_value,
        "attacker_bracket_return": float(attacker_bracket_return),
        "target": acting_team_return(attacker_bracket_return, record.role),
        "seat": record.seat,
        "round_index": round_index,
        "decision_index": decision_index,
        "game_seed": game_seed,
        "deal_stream_root_seed": deal_stream_root_seed,
        "actor_sha256": identity.actor_ref.sha256,
        "batch_sequence": identity.sequence,
        "runner_contract_sha256": identity.contract_sha256,
    }


@dataclass(frozen=True)
class SuphxMicroCollector:
    expected_runner_contract_sha256: str
    keep_probability: float
    deal_stream_root_seed: int
    rounds_per_batch: int = ROUNDS_PER_BATCH

    def __post_init__(self) -> None:
        if not isinstance(self.expected_runner_contract_sha256, str) \
                or len(self.expected_runner_contract_sha256) != 64:
            raise SuphxActorError("expected runner contract must be SHA-256")
        if self.rounds_per_batch != ROUNDS_PER_BATCH:
            raise SuphxActorError("round count is fixed by actor contract")
        if isinstance(self.deal_stream_root_seed, bool) \
                or not isinstance(self.deal_stream_root_seed, int) \
                or self.deal_stream_root_seed < 0:
            raise SuphxActorError(
                "deal stream root seed must be a nonnegative integer")
        draw_privilege_mask(self.keep_probability, random.Random(0))

    def __call__(self, identity: ActorBatchIdentity) -> SynchronousActorBatch:
        if identity.experiment != EXPERIMENT or identity.purpose != "actor" \
                or identity.contract_sha256 != self.expected_runner_contract_sha256:
            raise SuphxActorError("actor batch identity/contract mismatch")
        model = load_verified(identity.actor_ref, load_actor)
        actor = SuphxOrdinaryActor(
            model,
            keep_probability=self.keep_probability,
            mask_rng=random.Random(_child_seed(identity.seed, "mask", 0)),
            action_rng=random.Random(_child_seed(identity.seed, "action", 0)),
        )
        policies = [_ExplicitSurfaceComposite(actor) for _ in range(4)]
        samples: list[dict[str, Any]] = []
        for round_index in range(self.rounds_per_batch):
            deal_sequence = (
                identity.sequence * self.rounds_per_batch + round_index)
            game_seed = _child_seed(
                self.deal_stream_root_seed, "shared-deal", deal_sequence)
            actor.records = []
            game = Game(random.Random(game_seed))
            play_round(game, policies)
            if game.round is None or game.result is None:
                raise SuphxActorError("round collection ended without result")
            attacker_bracket_return = clipped_attacker_bracket_return(
                game.result.attacker_points)
            for decision_index, record in enumerate(actor.records):
                sample = _sample_from_record(
                    record,
                    identity=identity,
                    round_index=round_index,
                    decision_index=decision_index,
                    game_seed=game_seed,
                    deal_stream_root_seed=self.deal_stream_root_seed,
                    attacker_bracket_return=attacker_bracket_return,
                    keep_probability=self.keep_probability,
                )
                validate_sample(sample, identity=identity)
                _verify_behavior(sample, model)
                samples.append(sample)
        if not samples:
            raise SuphxActorError("actor batch contains no ordinary-play samples")
        return SynchronousActorBatch(identity=identity, samples=tuple(samples))


_SAMPLE_FIELDS = {
    "schema", "surface", "feature_spec_sha256", "policy_spec_sha256",
    "actor_spec_sha256", "ballot_schema", "reward_schema", "mask_schema",
    "role", "decision_surface", "observation", "legal_private", "history",
    "history_length", "perfect", "mask", "keep_probability", "candidates",
    "candidate_cards", "chosen_index", "action_cards", "action_draw",
    "behavior_log_probability", "behavior_value", "attacker_bracket_return",
    "target", "seat", "round_index", "decision_index", "game_seed",
    "deal_stream_root_seed", "actor_sha256", "batch_sequence",
    "runner_contract_sha256",
}


def validate_sample(
        sample: object, *, identity: ActorBatchIdentity | None = None,
        contract_sha256: str | None = None) -> None:
    if (identity is None) == (contract_sha256 is None):
        raise SuphxActorError(
            "sample validation requires exactly one provenance boundary")
    if not isinstance(sample, Mapping) or set(sample) != _SAMPLE_FIELDS:
        raise SuphxActorError("actor sample fields mismatch")
    for field, expected in (
        ("schema", SAMPLE_SCHEMA),
        ("surface", "ordinary_play"),
        ("feature_spec_sha256", FEATURE_SPEC_SHA256),
        ("policy_spec_sha256", POLICY_SPEC_SHA256),
        ("actor_spec_sha256", ACTOR_SPEC_SHA256),
        ("ballot_schema", BALLOT_SCHEMA),
        ("reward_schema", REWARD_SCHEMA),
        ("mask_schema", MASK_SCHEMA),
    ):
        if sample[field] != expected:
            raise SuphxActorError(f"sample {field} contract drift")
    if isinstance(sample["role"], bool) \
            or not isinstance(sample["role"], int) \
            or sample["role"] not in (ROLE_ATTACKER, ROLE_DEFENDER) \
            or isinstance(sample["decision_surface"], bool) \
            or not isinstance(sample["decision_surface"], int) \
            or sample["decision_surface"] not in SURFACE_NAMES:
        raise SuphxActorError("sample role/surface is unsupported")
    arrays = {
        "observation": ((OBS_DIM,), np.float32),
        "legal_private": ((LEGAL_PRIVATE_DIM,), np.float32),
        "history": ((HISTORY_MAX_EVENTS, HISTORY_EVENT_DIM), np.float32),
        "perfect": ((PERFECT_DIM,), np.float32),
        "mask": ((PERFECT_DIM,), np.float32),
    }
    for name, (shape, dtype) in arrays.items():
        value = sample[name]
        if not isinstance(value, np.ndarray) or value.shape != shape \
                or value.dtype != dtype or not np.all(np.isfinite(value)):
            raise SuphxActorError(f"sample {name} tensor drift")
    candidates = sample["candidates"]
    if not isinstance(candidates, np.ndarray) or candidates.dtype != np.float32 \
            or candidates.ndim != 2 or candidates.shape[1] != ACT_DIM \
            or not len(candidates) or not np.all(np.isfinite(candidates)):
        raise SuphxActorError("sample candidate tensor drift")
    mask = sample["mask"]
    if not np.all((mask == 0.0) | (mask == 1.0)):
        raise SuphxActorError("sample mask is not binary")
    probability = sample["keep_probability"]
    if isinstance(probability, bool) or not isinstance(probability, float) \
            or not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
        raise SuphxActorError("sample keep probability is invalid")
    if probability == 0.0 and np.any(mask != 0.0):
        raise SuphxActorError("zero-probability sample retained perfect features")
    if probability == 1.0 and np.any(mask != 1.0):
        raise SuphxActorError("one-probability sample dropped perfect features")
    history_length = sample["history_length"]
    if isinstance(history_length, bool) or not isinstance(history_length, int) \
            or not 0 <= history_length <= HISTORY_MAX_EVENTS \
            or np.any(sample["history"][history_length:] != 0.0):
        raise SuphxActorError("sample history length/padding drift")
    candidate_cards = sample["candidate_cards"]
    if not isinstance(candidate_cards, tuple) \
            or len(candidate_cards) != len(candidates) \
            or any(not isinstance(action, tuple) or not action
                   or any(card not in CARD_INDEX for card in action)
                   for action in candidate_cards):
        raise SuphxActorError("sample candidate-card ballot drift")
    chosen = sample["chosen_index"]
    if isinstance(chosen, bool) or not isinstance(chosen, int) \
            or not 0 <= chosen < len(candidates) \
            or sample["action_cards"] != candidate_cards[chosen]:
        raise SuphxActorError("sample chosen action drift")
    for name in ("action_draw", "behavior_log_probability", "behavior_value",
                 "attacker_bracket_return", "target"):
        if not isinstance(sample[name], float) or not math.isfinite(sample[name]):
            raise SuphxActorError(f"sample {name} is non-finite or non-float")
    if not 0.0 <= sample["action_draw"] < 1.0:
        raise SuphxActorError("sample action draw is outside [0, 1)")
    if sample["behavior_log_probability"] > 1e-7:
        raise SuphxActorError("sample behavior log probability is positive")
    if sample["attacker_bracket_return"] not in {
            -3.5, -2.5, -1.5, 0.5, 1.5, 2.5, 3.5} \
            or sample["target"] != acting_team_return(
                sample["attacker_bracket_return"], sample["role"]):
        raise SuphxActorError("sample clipped role-signed bracket drift")
    for name in ("seat", "round_index", "decision_index", "game_seed",
                 "deal_stream_root_seed", "batch_sequence"):
        value = sample[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SuphxActorError(f"sample {name} is invalid")
    if sample["seat"] not in range(4):
        raise SuphxActorError("sample seat is outside range(4)")
    actor_sha = sample["actor_sha256"]
    if not isinstance(actor_sha, str) or len(actor_sha) != 64 \
            or any(char not in "0123456789abcdef" for char in actor_sha):
        raise SuphxActorError("sample actor digest is malformed")
    expected_contract = identity.contract_sha256 if identity is not None \
        else contract_sha256
    if sample["runner_contract_sha256"] != expected_contract:
        raise SuphxActorError("sample runner contract provenance drift")
    if identity is not None and (
            actor_sha != identity.actor_ref.sha256
            or sample["batch_sequence"] != identity.sequence):
        raise SuphxActorError("sample actor/batch provenance drift")


def _verify_behavior(sample: Mapping[str, Any], model: SuphxPolicyValue) -> None:
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
    )
    probabilities = torch.softmax(logits, dim=0)
    log_probabilities = torch.log_softmax(logits, dim=0)
    chosen = _sample_index(probabilities, sample["action_draw"])
    if chosen != sample["chosen_index"]:
        raise SuphxActorError("stored action draw does not select chosen action")
    if not math.isclose(
            float(log_probabilities[sample["chosen_index"]].item()),
            sample["behavior_log_probability"],
            rel_tol=0.0, abs_tol=1e-7):
        raise SuphxActorError("stored behavior probability does not reopen")
    if not math.isclose(
            float(value.item()), sample["behavior_value"],
            rel_tol=0.0, abs_tol=1e-7):
        raise SuphxActorError("stored behavior value does not reopen")


def _wire_value(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        array = np.ascontiguousarray(value)
        return {
            "__ndarray__": True,
            "dtype": array.dtype.str,
            "shape": list(array.shape),
            "data": base64.b64encode(array.tobytes()).decode("ascii"),
        }
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise SuphxActorError("wire mappings require string keys")
        return {key: _wire_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_wire_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise SuphxActorError(
        f"unsupported actor-batch wire value {type(value).__name__}")


def actor_batch_bytes(batch: SynchronousActorBatch) -> bytes:
    if not isinstance(batch, SynchronousActorBatch):
        raise SuphxActorError("expected SynchronousActorBatch")
    payload = {
        "schema": "suphx-micro-actor-batch-wire-v1",
        "identity": batch.identity.as_dict(),
        "samples": batch.samples,
    }
    return json.dumps(
        _wire_value(payload), sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode("utf-8")

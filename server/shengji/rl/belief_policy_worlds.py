"""Literal production-world capture for the R4 opened-DEV policy probe.

Unlike the sound offline REF-C adapter, this module intentionally calls the
same ``MCBot._sample_hands`` proposal used by ``mc-s0-report-lcb``.  That makes
the unweighted arm a literal production baseline and lets the diagnostic
measure, rather than silently repair, the known banker-declaration support
gap.  Every returned world still passes the reviewed sound world validator.

There is no writer, model, target, rollout, action selection, filesystem or
execution authority here.
"""

from __future__ import annotations

import hashlib
import os
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ..ai.mcbot import MCBot
from ..ai.memory import Memory
from ..ai.registry import make_bot
from ..engine.round import Round
from .belief_capture import CHAMPION_POLICY
from .belief_contract import (
    ActorObservationV1,
    PublicTranscriptV1,
    build_actor_observation,
    canonical_json_bytes,
)
from .belief_ownership import (
    KITTY_RECEIVER,
    BeliefOwnershipV1,
    validate_ownership,
)
from .belief_reference import (
    ReceiverCardsV1,
    SampledOwnershipWorldV1,
    reference_ownership,
    validate_sampled_world,
)


POLICY_WORLD_BATCH_SCHEMA = "belief-r4-policy-production-world-batch-v1"
MAX_SAMPLER_SEED = 2**63 - 1
MAX_POLICY_WORLD_COUNT = 4096
PRODUCTION_PROPOSAL_MODEL_SCHEMA = (
    "belief-r4-policy-production-proposal-marginals-256-v1")
_SOURCE_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_PROPOSAL_SOURCE_SHA256 = hashlib.sha256(canonical_json_bytes({
    "schema": "belief-r4-policy-production-proposal-source-v1",
    "source_sha256s": {
        name: hashlib.sha256((_SOURCE_ROOT / path).read_bytes()).hexdigest()
        for name, path in {
            "belief_policy_worlds": "rl/belief_policy_worlds.py",
            "belief_reference": "rl/belief_reference.py",
            "mcbot": "ai/mcbot.py",
            "memory": "ai/memory.py",
            "cards": "engine/cards.py",
            "combos": "engine/combos.py",
        }.items()
    },
})).hexdigest()
_COUNTERS = (
    "sample_attempts",
    "accepted_worlds",
    "failed_worlds",
    "rejected_worlds",
    "impossible_worlds",
)


class BeliefPolicyWorldError(ValueError):
    """A production sampler input, world stream, or work receipt drifted."""


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _snapshot(bot: MCBot) -> tuple[tuple[str, int], ...]:
    return tuple((name, int(getattr(bot, name))) for name in _COUNTERS)


def _world_stream_sha256(
        worlds: tuple[SampledOwnershipWorldV1, ...]) -> str:
    digest = hashlib.sha256()
    for world in worlds:
        raw = world.canonical_bytes()
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def production_relative_world(
        actor: ActorObservationV1, seat: int,
        hands: dict[int, list[str]], buried: list[str]) \
        -> SampledOwnershipWorldV1:
    if type(actor) is not ActorObservationV1 \
            or type(seat) is not int or seat not in range(4) \
            or type(hands) is not dict \
            or set(hands) != {absolute for absolute in range(4)
                              if absolute != seat} \
            or any(type(cards) is not list for cards in hands.values()) \
            or type(buried) is not list:
        raise BeliefPolicyWorldError(
            "production sampled-world population drift")
    rows = []
    for relative in range(1, 4):
        absolute = (seat + relative) % 4
        rows.append(ReceiverCardsV1(
            receiver=f"seat-relative-{relative}",
            cards=tuple(sorted(Counter(hands[absolute]).items())),
        ))
    if actor.hidden_burial_size:
        rows.append(ReceiverCardsV1(
            receiver=KITTY_RECEIVER,
            cards=tuple(sorted(Counter(buried).items())),
        ))
    world = SampledOwnershipWorldV1(
        actor_observation_sha256=actor.sha256(), receivers=tuple(rows))
    try:
        validate_sampled_world(actor, world)
    except ValueError as exc:
        raise BeliefPolicyWorldError(
            "production sampled world violates reviewed mechanics") from exc
    return world


@dataclass(frozen=True)
class ProductionWorldBatchV1:
    actor: ActorObservationV1
    sampler_seed: int
    requested_world_count: int
    attempts: int
    attempt_cap: int
    sampler_before: tuple[tuple[str, int], ...]
    sampler_after: tuple[tuple[str, int], ...]
    sampler_delta: tuple[tuple[str, int], ...]
    worlds: tuple[SampledOwnershipWorldV1, ...]
    policy_name: str = CHAMPION_POLICY
    schema: str = POLICY_WORLD_BATCH_SCHEMA

    def manifest_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "actor_observation_sha256": self.actor.sha256(),
            "policy_name": self.policy_name,
            "sampler_seed": self.sampler_seed,
            "requested_world_count": self.requested_world_count,
            "accepted_world_count": len(self.worlds),
            "attempts": self.attempts,
            "attempt_cap": self.attempt_cap,
            "sampler_before": dict(self.sampler_before),
            "sampler_after": dict(self.sampler_after),
            "sampler_delta": dict(self.sampler_delta),
            "world_stream_sha256": _world_stream_sha256(self.worlds),
            "strict_void_sampling": True,
            "contains_round_outcome": False,
            "contains_privileged_target": False,
            "runtime_input": False,
            "gameplay_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        }

    def manifest_sha256(self) -> str:
        return hashlib.sha256(
            canonical_json_bytes(self.manifest_dict())).hexdigest()


def validate_production_world_batch(value: ProductionWorldBatchV1) -> None:
    if type(value) is not ProductionWorldBatchV1 \
            or value.schema != POLICY_WORLD_BATCH_SCHEMA \
            or value.policy_name != CHAMPION_POLICY \
            or type(value.actor) is not ActorObservationV1 \
            or type(value.sampler_seed) is not int \
            or not 0 <= value.sampler_seed <= MAX_SAMPLER_SEED \
            or type(value.requested_world_count) is not int \
            or not 1 <= value.requested_world_count <= MAX_POLICY_WORLD_COUNT \
            or type(value.attempts) is not int or value.attempts < 0 \
            or type(value.attempt_cap) is not int \
            or value.attempt_cap \
            != value.requested_world_count * MCBot.SAMPLE_ATTEMPT_FACTOR \
            or not value.attempts <= value.attempt_cap \
            or type(value.worlds) is not tuple \
            or len(value.worlds) != value.requested_world_count \
            or any(type(row) is not tuple or len(row) != 2
                   or row[0] not in _COUNTERS or type(row[1]) is not int
                   for rows in (value.sampler_before, value.sampler_after,
                                value.sampler_delta) for row in rows) \
            or tuple(name for name, _ in value.sampler_before) != _COUNTERS \
            or tuple(name for name, _ in value.sampler_after) != _COUNTERS \
            or tuple(name for name, _ in value.sampler_delta) != _COUNTERS:
        raise BeliefPolicyWorldError(
            "production world-batch population drift")
    before = dict(value.sampler_before)
    after = dict(value.sampler_after)
    delta = dict(value.sampler_delta)
    if any(after[name] - before[name] != delta[name]
           for name in _COUNTERS) \
            or delta["sample_attempts"] != value.attempts \
            or delta["accepted_worlds"] != len(value.worlds) \
            or delta["failed_worlds"] != value.attempts - len(value.worlds) \
            or delta["accepted_worlds"] + delta["failed_worlds"] \
            != delta["sample_attempts"] \
            or delta["impossible_worlds"] != 0:
        raise BeliefPolicyWorldError(
            "production world-batch sampler accounting drift")
    for world in value.worlds:
        try:
            validate_sampled_world(value.actor, world)
        except ValueError as exc:
            raise BeliefPolicyWorldError(
                "production world-batch mechanics refused") from exc
    if not _is_sha256(value.manifest_dict()["world_stream_sha256"]):
        raise BeliefPolicyWorldError(
            "production world stream identity drift")


def production_proposal_ownership(
        batch: ProductionWorldBatchV1) -> BeliefOwnershipV1:
    """Convert one exact 256-world proposal batch into V2 scoring marginals."""
    validate_production_world_batch(batch)
    if batch.requested_world_count != 256:
        raise BeliefPolicyWorldError(
            "production proposal marginals require exactly 256 worlds")
    try:
        original = reference_ownership(
            batch.actor,
            batch.worlds,
            sampler_source_sha256=PRODUCTION_PROPOSAL_SOURCE_SHA256,
            behavior_policy_ids=(CHAMPION_POLICY,),
        )
        result = replace(
            original,
            model_schema=PRODUCTION_PROPOSAL_MODEL_SCHEMA,
        )
        validate_ownership(batch.actor, result)
    except ValueError as exc:
        raise BeliefPolicyWorldError(
            "production proposal marginal derivation refused") from exc
    return result


def sample_production_worlds(
        rnd: Round, seat: int, transcript: PublicTranscriptV1, *,
        sampler_seed: int, world_count: int) -> ProductionWorldBatchV1:
    """Draw exact-work worlds through the deployed proposal kernel."""
    if type(rnd) is not Round or rnd.phase != "play" or rnd.turn != seat \
            or type(seat) is not int or seat not in range(4) \
            or type(transcript) is not PublicTranscriptV1 \
            or type(sampler_seed) is not int \
            or not 0 <= sampler_seed <= MAX_SAMPLER_SEED \
            or type(world_count) is not int \
            or not 1 <= world_count <= MAX_POLICY_WORLD_COUNT:
        raise BeliefPolicyWorldError(
            "production world sampler input drift")
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise BeliefPolicyWorldError(
            "production policy diagnostic requires strict void sampling")
    try:
        actor = build_actor_observation(rnd, seat, transcript)
    except ValueError as exc:
        raise BeliefPolicyWorldError(
            "production world actor derivation refused") from exc
    bot = make_bot(CHAMPION_POLICY, seed=sampler_seed)
    if not isinstance(bot, MCBot):
        raise BeliefPolicyWorldError(
            "production world sampler policy type drift")
    memory = Memory(rnd, seat, own_kitty=True)
    before = _snapshot(bot)
    worlds = []
    attempts = 0
    attempt_cap = world_count * bot.SAMPLE_ATTEMPT_FACTOR
    while len(worlds) < world_count and attempts < attempt_cap:
        attempts += 1
        sampled = bot._sample_hands(rnd, seat, memory)
        if sampled is None:
            continue
        worlds.append(production_relative_world(
            actor, seat, sampled[0], sampled[1]))
    after = _snapshot(bot)
    before_dict = dict(before)
    after_dict = dict(after)
    result = ProductionWorldBatchV1(
        actor=actor,
        sampler_seed=sampler_seed,
        requested_world_count=world_count,
        attempts=attempts,
        attempt_cap=attempt_cap,
        sampler_before=before,
        sampler_after=after,
        sampler_delta=tuple((name, after_dict[name] - before_dict[name])
                            for name in _COUNTERS),
        worlds=tuple(worlds),
    )
    if len(worlds) != world_count:
        raise BeliefPolicyWorldError(
            "production world sampler underfilled exact work")
    validate_production_world_batch(result)
    return result

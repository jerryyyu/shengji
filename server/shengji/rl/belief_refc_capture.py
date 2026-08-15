"""Exact in-memory REF-C draws from the sound constraint sampler.

This is the only B2 adapter allowed to call ``MCBot._sample_hands``.  It draws
256 complete worlds from one actor-visible decision under a named RNG seed,
requires the strict-void sampler mode, records all work counters, validates
every world against ``ActorObservationV1``, and returns no rollout value or
round outcome.  It has no file writer, CLI, training, policy registration, or
execution authority.
"""

from __future__ import annotations

import hashlib
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..ai.mcbot import MCBot
from ..ai.memory import Memory
from ..engine.round import Round
from .belief_b2_protocol import (B2_REFERENCE_REPLICATES,
                                 champion_policy_seeds,
                                 reference_sampler_seed)
from .belief_capture import (CHAMPION_POLICY, CapturedActorRoundV1,
                             capture_champion_actor_round,
                             validate_actor_round)
from .belief_corpus import reopen_actor_row, split_for_round_seed
from .belief_contract import (ActorObservationV1, PublicTranscriptV1,
                              build_actor_observation, canonical_json_bytes)
from .belief_ownership import BeliefOwnershipV1, KITTY_RECEIVER
from .belief_input import build_history_ownership_input
from .belief_reference import (REF_C_WORLD_COUNT, BeliefReferenceError,
                               ReceiverCardsV1,
                               SampledOwnershipWorldV1, reference_ownership,
                               validate_sampled_world)


REF_C_BATCH_SCHEMA = "belief-v1-ref-c-sound-constraint-sampler-batch-v2"
MAX_SAMPLER_SEED = 2**63 - 1
_SOURCE_ROOT = Path(__file__).resolve().parents[1]
REF_C_SOURCE_SHA256S = {
    name: hashlib.sha256((_SOURCE_ROOT / path).read_bytes()).hexdigest()
    for name, path in {
        "belief_contract": "rl/belief_contract.py",
        "belief_refc_capture": "rl/belief_refc_capture.py",
        "belief_reference": "rl/belief_reference.py",
        "mcbot": "ai/mcbot.py",
        "memory": "ai/memory.py",
        "cards": "engine/cards.py",
        "combos": "engine/combos.py",
    }.items()
}
REF_C_SAMPLER_SHA256 = hashlib.sha256(canonical_json_bytes({
    "schema": "belief-v1-ref-c-sound-constraint-sampler-source-v2",
    "source_sha256s": REF_C_SOURCE_SHA256S,
})).hexdigest()
_COUNTERS = ("sample_attempts", "accepted_worlds", "failed_worlds",
             "rejected_worlds", "impossible_worlds")


def _world_stream_sha256(
        worlds: tuple[SampledOwnershipWorldV1, ...]) -> str:
    if type(worlds) is not tuple or not worlds:
        raise BeliefRefCCaptureError("REF-C world stream is empty")
    digest = hashlib.sha256()
    for world in worlds:
        raw = world.canonical_bytes()
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


class BeliefRefCCaptureError(ValueError):
    """A current-sampler reference batch failed its exact-work contract."""


@dataclass(frozen=True)
class ReferenceCapturedRoundV1:
    captured: CapturedActorRoundV1
    replicate: str
    batches: tuple[ReferenceWorldBatchV1, ...]

    def manifest_dict(self) -> dict[str, Any]:
        return {
            "schema": "belief-v1-ref-c-captured-round-v1",
            "round_seed": self.captured.round_seed,
            "split": split_for_round_seed(self.captured.round_seed),
            "replicate": self.replicate,
            "actor_capture_manifest_sha256": self.captured.manifest_sha256(),
            "decision_count": len(self.batches),
            "accepted_world_count": sum(
                len(batch.worlds) for batch in self.batches),
            "attempt_count": sum(batch.attempts for batch in self.batches),
            "batch_manifest_sha256s": [
                batch.manifest_sha256() for batch in self.batches],
            "contains_sampled_hidden_worlds": True,
            "contains_round_outcome": False,
            "runtime_input": False,
            "reference_generation_authorized": False,
            "training_authorized": False,
            "gameplay_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        }

    def manifest_bytes(self) -> bytes:
        return canonical_json_bytes(self.manifest_dict())

    def manifest_sha256(self) -> str:
        return hashlib.sha256(self.manifest_bytes()).hexdigest()


@dataclass(frozen=True)
class ReferenceWorldBatchV1:
    actor: ActorObservationV1
    sampler_seed: int
    attempts: int
    attempt_cap: int
    sampler_before: tuple[tuple[str, int], ...]
    sampler_after: tuple[tuple[str, int], ...]
    sampler_delta: tuple[tuple[str, int], ...]
    worlds: tuple[SampledOwnershipWorldV1, ...]
    sampler_source_sha256: str = REF_C_SAMPLER_SHA256
    behavior_policy_ids: tuple[str, ...] = (CHAMPION_POLICY,)
    schema: str = REF_C_BATCH_SCHEMA

    def manifest_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "actor_observation_sha256": self.actor.sha256(),
            "sampler_seed": self.sampler_seed,
            "sampler_source_sha256": self.sampler_source_sha256,
            "sampler_source_sha256s": REF_C_SOURCE_SHA256S,
            "behavior_policy_ids": list(self.behavior_policy_ids),
            "accepted_world_count": len(self.worlds),
            "attempts": self.attempts,
            "attempt_cap": self.attempt_cap,
            "sampler_counters": {
                "before": dict(self.sampler_before),
                "after": dict(self.sampler_after),
                "delta": dict(self.sampler_delta),
            },
            "world_stream_sha256": _world_stream_sha256(self.worlds),
            "contains_sampled_hidden_worlds": True,
            "contains_round_outcome": False,
            "runtime_input": False,
        }

    def manifest_bytes(self) -> bytes:
        return canonical_json_bytes(self.manifest_dict())

    def manifest_sha256(self) -> str:
        return hashlib.sha256(self.manifest_bytes()).hexdigest()

    def ownership(self) -> BeliefOwnershipV1:
        validate_reference_world_batch(self)
        return reference_ownership(
            self.actor, self.worlds,
            sampler_source_sha256=self.sampler_source_sha256,
            behavior_policy_ids=self.behavior_policy_ids,
        )


def _snapshot(bot: MCBot) -> tuple[tuple[str, int], ...]:
    return tuple((name, int(getattr(bot, name))) for name in _COUNTERS)


def _relative_world(actor: ActorObservationV1, seat: int,
                    hands: dict[int, list[str]], buried: list[str]) \
        -> SampledOwnershipWorldV1:
    if type(hands) is not dict or set(hands) != {
            absolute for absolute in range(4) if absolute != seat} \
            or type(buried) is not list:
        raise BeliefRefCCaptureError("REF-C sampler return population drift")
    rows = []
    for relative in range(1, 4):
        absolute = (seat + relative) % 4
        if type(hands[absolute]) is not list:
            raise BeliefRefCCaptureError("REF-C sampled hand type drift")
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
    return world


def _sample_ref_c_hands(
        bot: MCBot, rnd: Round, seat: int, memory: Memory,
        actor: ActorObservationV1) -> tuple[dict[int, list[str]], list[str]] \
        | None:
    """Run the production assignment kernel with sound declaration slots.

    The deployed sampler pins a banker-declarer's shown cards to the banker
    hand.  That changes live decisions and is deliberately left untouched.
    REF-C instead treats each still-shown physical copy as labelled public
    evidence and places it uniformly without replacement into the only legal
    slots: banker hand or hidden kitty.  The remaining cards then use the
    exact production ``_assign`` kernel and its void/pair/run constraints.
    """
    bot.sample_attempts += 1
    ordering = rnd.ordering
    assert ordering is not None
    pool = list(memory.unseen.elements())
    if seat == rnd.banker:
        if not getattr(memory, "own_kitty_known", False):
            pool = list((Counter(pool) - Counter(rnd.buried)).elements())
        buried = list(rnd.buried)
        kitty_slots = 0
    else:
        buried = []
        kitty_slots = len(rnd.buried)
    others = [absolute for absolute in range(4) if absolute != seat]
    sizes = {absolute: len(rnd.hands[absolute]) for absolute in others}
    if len(pool) != sum(sizes.values()) + kitty_slots:
        raise BeliefRefCCaptureError(
            "REF-C unseen pool and receiver capacities disagree")

    eligibility_cards = {
        constraint.card for constraint
        in actor.deductions.declaration_eligibility
    }
    fixed_pre: dict[int, list[str]] = {absolute: [] for absolute in others}
    fixed_pins: Counter[str] = Counter()
    if bot.DECLARER_PIN:
        for card, (owner, copies) in memory.known.items():
            if card in eligibility_cards or owner not in fixed_pre:
                continue
            take = min(copies, sizes[owner] - len(fixed_pre[owner]))
            fixed_pre[owner].extend([card] * take)
            fixed_pins[card] += take

    pool_counts = Counter(pool)
    for attempt in range(bot.SAMPLE_RETRIES):
        pre = {absolute: list(cards)
               for absolute, cards in fixed_pre.items()}
        pinned = Counter(fixed_pins)
        pre_kitty: list[str] = []
        eligibility_ok = True
        for constraint in actor.deductions.declaration_eligibility:
            hand_receiver = constraint.eligible_receivers[0]
            relative = int(hand_receiver.removeprefix("seat-relative-"))
            owner = (seat + relative) % 4
            hand_slots = sizes[owner] - len(pre[owner])
            if ordering.eff_suit(constraint.card) in memory.voids[owner]:
                hand_slots = 0
            available_kitty = kitty_slots - len(pre_kitty)
            slots = ([owner] * hand_slots
                     + ["kitty"] * available_kitty)
            if len(slots) < constraint.minimum_copies \
                    or pool_counts[constraint.card] - pinned[constraint.card] \
                    < constraint.minimum_copies:
                eligibility_ok = False
                break
            bot.rng.shuffle(slots)
            for receiver in slots[:constraint.minimum_copies]:
                if receiver == "kitty":
                    pre_kitty.append(constraint.card)
                else:
                    pre[receiver].append(constraint.card)
                pinned[constraint.card] += 1
        if not eligibility_ok:
            continue

        free = list((pool_counts - pinned).elements())
        caps = {absolute: sizes[absolute] - len(pre[absolute])
                for absolute in others}
        remaining_kitty = kitty_slots - len(pre_kitty)
        respect_voids = attempt < bot.SAMPLE_RETRIES - 1
        got = bot._assign(
            free, caps, remaining_kitty, ordering, memory, pre,
            respect_voids=respect_voids)
        if got is None:
            continue
        if not respect_voids:
            if os.environ.get("SHENGJI_REQUIRE_VOIDS"):
                bot.rejected_worlds += 1
                bot.failed_worlds += 1
                return None
            bot.impossible_worlds += 1
        hands, kitty = got
        for absolute in others:
            hands[absolute] = pre[absolute] + hands[absolute]
        bot.accepted_worlds += 1
        return hands, (buried or [*pre_kitty, *kitty])
    bot.failed_worlds += 1
    return None


def capture_ref_c_worlds_from_bound_actor(
        rnd: Round, seat: int, actor: ActorObservationV1, *,
        sampler_seed: int) -> ReferenceWorldBatchV1:
    """Draw REF-C for an independently bound complete scoring actor.

    The V2 human adapter constructs its source-neutral scoring actor from the
    exact replayed public state before calling this function.  No target or
    hidden label is accepted here.
    """
    if type(rnd) is not Round or rnd.phase != "play" or rnd.turn != seat \
            or type(seat) is not int or seat not in range(4) \
            or type(actor) is not ActorObservationV1:
        raise BeliefRefCCaptureError("REF-C requires an exact play decision")
    if type(sampler_seed) is not int \
            or not 0 <= sampler_seed <= MAX_SAMPLER_SEED:
        raise BeliefRefCCaptureError("REF-C sampler seed is invalid")
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise BeliefRefCCaptureError("REF-C requires strict void sampling")
    if actor.declaration_history_complete is not True \
            or actor.attempted_play_history_complete is not True:
        raise BeliefRefCCaptureError("REF-C actor history is incomplete")
    bot = MCBot(seed=sampler_seed)
    memory = Memory(rnd, seat, own_kitty=True)
    before = _snapshot(bot)
    worlds = []
    attempts = 0
    attempt_cap = REF_C_WORLD_COUNT * bot.SAMPLE_ATTEMPT_FACTOR
    while len(worlds) < REF_C_WORLD_COUNT and attempts < attempt_cap:
        attempts += 1
        sampled = _sample_ref_c_hands(bot, rnd, seat, memory, actor)
        if sampled is None:
            continue
        hands, buried = sampled
        world = _relative_world(actor, seat, hands, buried)
        validate_sampled_world(actor, world)
        worlds.append(world)
    after = _snapshot(bot)
    before_dict = dict(before)
    after_dict = dict(after)
    delta = tuple((name, after_dict[name] - before_dict[name])
                  for name in _COUNTERS)
    if len(worlds) != REF_C_WORLD_COUNT:
        raise BeliefRefCCaptureError("REF-C reference batch underfilled")
    batch = ReferenceWorldBatchV1(
        actor=actor, sampler_seed=sampler_seed,
        attempts=attempts, attempt_cap=attempt_cap,
        sampler_before=before, sampler_after=after,
        sampler_delta=delta, worlds=tuple(worlds),
    )
    validate_reference_world_batch(batch)
    return batch


def capture_ref_c_worlds(
        rnd: Round, seat: int, transcript: PublicTranscriptV1, *,
        sampler_seed: int) -> ReferenceWorldBatchV1:
    """Draw one exact sound-constraint reference batch from full history."""
    if type(transcript) is not PublicTranscriptV1:
        raise BeliefRefCCaptureError("REF-C requires an exact play decision")
    actor = build_actor_observation(rnd, seat, transcript)
    return capture_ref_c_worlds_from_bound_actor(
        rnd, seat, actor, sampler_seed=sampler_seed)


def validate_reference_world_batch(batch: ReferenceWorldBatchV1) -> None:
    """Recompute world and work integrity without drawing another sample."""
    if type(batch) is not ReferenceWorldBatchV1 \
            or batch.schema != REF_C_BATCH_SCHEMA \
            or type(batch.actor) is not ActorObservationV1 \
            or type(batch.sampler_seed) is not int \
            or not 0 <= batch.sampler_seed <= MAX_SAMPLER_SEED \
            or batch.sampler_source_sha256 != REF_C_SAMPLER_SHA256 \
            or batch.behavior_policy_ids != (CHAMPION_POLICY,) \
            or type(batch.worlds) is not tuple \
            or len(batch.worlds) != REF_C_WORLD_COUNT:
        raise BeliefRefCCaptureError("REF-C batch identity/population drift")
    try:
        build_history_ownership_input(
            batch.actor, behavior_policy_ids=batch.behavior_policy_ids)
        for world in batch.worlds:
            validate_sampled_world(batch.actor, world)
    except (BeliefReferenceError, ValueError) as exc:
        raise BeliefRefCCaptureError("REF-C sampled world refused") from exc
    counters = {}
    for label, rows in (("before", batch.sampler_before),
                        ("after", batch.sampler_after),
                        ("delta", batch.sampler_delta)):
        if type(rows) is not tuple or tuple(name for name, _ in rows) \
                != _COUNTERS or any(type(value) is not int or value < 0
                                    for _, value in rows):
            raise BeliefRefCCaptureError(
                f"REF-C sampler {label} counters drift")
        counters[label] = dict(rows)
    if type(batch.attempts) is not int or batch.attempts <= 0 \
            or type(batch.attempt_cap) is not int \
            or batch.attempt_cap != REF_C_WORLD_COUNT \
            * MCBot.SAMPLE_ATTEMPT_FACTOR \
            or batch.attempts > batch.attempt_cap \
            or counters["delta"] != {
                name: counters["after"][name] - counters["before"][name]
                for name in _COUNTERS
            } \
            or any(counters["before"].values()) \
            or counters["after"] != counters["delta"] \
            or counters["delta"]["sample_attempts"] != batch.attempts \
            or counters["delta"]["accepted_worlds"] != REF_C_WORLD_COUNT \
            or counters["delta"]["sample_attempts"] != (
                counters["delta"]["accepted_worlds"]
                + counters["delta"]["failed_worlds"]) \
            or counters["delta"]["rejected_worlds"] \
            > counters["delta"]["failed_worlds"] \
            or counters["delta"]["impossible_worlds"] != 0:
        raise BeliefRefCCaptureError("REF-C sampler work does not reconcile")
    manifest = batch.manifest_dict()
    expected_keys = {
        "schema", "actor_observation_sha256", "sampler_seed",
        "sampler_source_sha256", "sampler_source_sha256s",
        "behavior_policy_ids", "accepted_world_count", "attempts",
        "attempt_cap", "sampler_counters", "world_stream_sha256",
        "contains_sampled_hidden_worlds", "contains_round_outcome",
        "runtime_input",
    }
    if set(manifest) != expected_keys \
            or manifest["contains_sampled_hidden_worlds"] is not True \
            or manifest["contains_round_outcome"] is not False \
            or manifest["runtime_input"] is not False:
        raise BeliefRefCCaptureError("REF-C manifest authority drift")


def capture_champion_round_with_ref_c(
        round_seed: int, *, replicate: str) -> ReferenceCapturedRoundV1:
    """Replay one frozen champion round and observe every REF-C decision."""
    split = split_for_round_seed(round_seed)
    if replicate not in B2_REFERENCE_REPLICATES \
            or (split == "calibration"
                and not replicate.startswith("calibration-replicate-")) \
            or (split == "test" and replicate != "test-primary") \
            or split == "train":
        raise BeliefRefCCaptureError("REF-C round replicate/split drift")
    batches = []

    def observe(rnd: Round, seat: int, transcript: PublicTranscriptV1,
                actor_row: bytes) -> None:
        try:
            actor, metadata = reopen_actor_row(actor_row)
        except ValueError as exc:
            raise BeliefRefCCaptureError(
                "REF-C observed actor row refused") from exc
        batch = capture_ref_c_worlds(
            rnd, seat, transcript, sampler_seed=reference_sampler_seed(
                metadata["decision_key"], replicate))
        if batch.actor.canonical_bytes() != actor.canonical_bytes():
            raise BeliefRefCCaptureError(
                "REF-C observed actor reconstruction drift")
        batches.append(batch)

    captured = capture_champion_actor_round(
        round_seed, champion_policy_seeds(round_seed),
        decision_observer=observe)
    result = ReferenceCapturedRoundV1(
        captured=captured, replicate=replicate, batches=tuple(batches))
    validate_reference_captured_round(result)
    return result


def validate_reference_captured_round(
        result: ReferenceCapturedRoundV1) -> None:
    if type(result) is not ReferenceCapturedRoundV1 \
            or type(result.captured) is not CapturedActorRoundV1 \
            or type(result.batches) is not tuple \
            or result.replicate not in B2_REFERENCE_REPLICATES:
        raise BeliefRefCCaptureError("REF-C captured round schema drift")
    try:
        validate_actor_round(result.captured)
    except ValueError as exc:
        raise BeliefRefCCaptureError("REF-C captured round refused") from exc
    split = split_for_round_seed(result.captured.round_seed)
    if (split == "calibration"
            and not result.replicate.startswith("calibration-replicate-")) \
            or (split == "test" and result.replicate != "test-primary") \
            or split == "train" \
            or len(result.batches) != len(result.captured.actor_rows):
        raise BeliefRefCCaptureError(
            "REF-C captured round replicate/population drift")
    for actor_row, batch in zip(result.captured.actor_rows, result.batches,
                           strict=True):
        try:
            actor, metadata = reopen_actor_row(actor_row)
            validate_reference_world_batch(batch)
        except ValueError as exc:
            raise BeliefRefCCaptureError(
                "REF-C captured round batch refused") from exc
        if batch.actor.canonical_bytes() != actor.canonical_bytes() \
                or batch.sampler_seed != reference_sampler_seed(
                    metadata["decision_key"], result.replicate):
            raise BeliefRefCCaptureError(
                "REF-C captured round actor/seed binding drift")
    manifest = result.manifest_dict()
    expected_keys = {
        "schema", "round_seed", "split", "replicate",
        "actor_capture_manifest_sha256", "decision_count",
        "accepted_world_count", "attempt_count",
        "batch_manifest_sha256s", "contains_sampled_hidden_worlds",
        "contains_round_outcome", "runtime_input",
        "reference_generation_authorized", "training_authorized",
        "gameplay_authorized", "strength_claim_authorized",
        "deployment_authorized",
    }
    if set(manifest) != expected_keys \
            or manifest["accepted_world_count"] != (
                len(result.batches) * REF_C_WORLD_COUNT) \
            or manifest["contains_sampled_hidden_worlds"] is not True \
            or manifest["contains_round_outcome"] is not False \
            or manifest["runtime_input"] is not False \
            or any(manifest[key] is not False for key in expected_keys
                   if key.endswith("_authorized")):
        raise BeliefRefCCaptureError(
            "REF-C captured round manifest/authority drift")

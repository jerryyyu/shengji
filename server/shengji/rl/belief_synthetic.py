"""Exact enumerable-posterior control for the BELIEF-V1 B2 pipeline.

C4 is a deliberately small, independent learning problem.  Each of four
public contexts has exactly two compatible hidden worlds.  The worlds have
equal prior mass, while the named synthetic observation policy emits the
observed public action with likelihoods three and one.  The exact posterior is
therefore 3/4 versus 1/4.  The two worlds must be real hash-bound corpus rows
with byte-identical actor observations and different privileged targets.

The control trains the same actor encoder, ownership model, AdamW step, count
head, and exact conservation projection as B2.  It then compares every
receiver/card/count probability against the fully enumerated Bayes posterior.
This module has no filesystem, network, CLI, sampler, gameplay, strength,
promotion, or deployment surface.
"""

from __future__ import annotations

import copy
import hashlib
import random
from dataclasses import dataclass, replace
from typing import Any

from ..ai.heuristic import HeuristicBot
from ..engine.game import Game
from ..engine.round import Round, actual_play_after
from .belief_contract import (PublicTranscriptV1, build_actor_observation,
                              canonical_json_bytes)
from .belief_corpus import (CorpusPairV1, decision_key,
                            capture_corpus_pair, split_for_round_seed)
from .belief_evaluation import reopen_score_pair, target_count_population
from .belief_model import (MODEL_SCHEMA, new_from_scratch_model,
                           predict_ownership)
from .belief_ownership import (BeliefOwnershipV1, PROBABILITY_SCALE,
                               validate_ownership)
from .belief_trainer import (EpochTrainingReceiptV1, model_state_sha256,
                             new_b2_optimizer, train_epoch)
from .belief_training import (BeliefTrainingExampleV1,
                              build_training_example,
                              collate_training_examples)


C4_CONTEXT_SCHEMA = "belief-v1-c4-two-world-context-v2"
C4_RESULT_SCHEMA = "belief-v1-c4-exact-posterior-result-v1"
C4_POLICY = "equal-prior-public-action-likelihood-3-to-1-v1"
C4_CONTEXT_IDS = tuple(f"context-{index}" for index in range(4))
C4_BEHAVIOR_POLICY_IDS = ("c4-enumerable-known-policy-v1",)
C4_TRAIN_ROWS_PER_CONTEXT = 1024
C4_TRAIN_ROW_COUNT = C4_TRAIN_ROWS_PER_CONTEXT * len(C4_CONTEXT_IDS)
C4_BATCH_SIZE = 16
C4_BATCH_COUNT = C4_TRAIN_ROW_COUNT // C4_BATCH_SIZE
C4_EPOCHS = 30
C4_MODEL_SEED = 495023836
C4_SEED_START = 7104125432620400640
C4_WORLD_POSTERIOR_WEIGHTS = (3, 1)
C4_POSTERIOR_DENOMINATOR = sum(C4_WORLD_POSTERIOR_WEIGHTS)
C4_MAX_EVENT_ERROR_PPB = 20_000_000
C4_MAX_ROW_TOTAL_VARIATION_PPB = 20_000_000


class BeliefSyntheticError(ValueError):
    """The exact C4 population, training trace, or posterior drifted."""


@dataclass(frozen=True)
class C4PublicTwinContextV1:
    context_id: str
    world_0: CorpusPairV1
    world_1: CorpusPairV1
    rotated_world_0: CorpusPairV1
    prior_weights: tuple[int, int] = (1, 1)
    observed_action_likelihood_weights: tuple[int, int] = (3, 1)
    schema: str = C4_CONTEXT_SCHEMA


@dataclass(frozen=True)
class C4ExactPosteriorResultV1:
    context_ids: tuple[str, ...]
    known_policy: str
    compatible_worlds_per_context: int
    prior_weights: tuple[int, int]
    observed_action_likelihood_weights: tuple[int, int]
    posterior_world_weights: tuple[int, int]
    posterior_denominator: int
    train_row_count: int
    batch_size: int
    batch_count: int
    epoch_count: int
    model_seed: int
    model_state_sha256: str
    training_receipts_sha256: str
    candidate_ownership_sha256s: tuple[str, ...]
    probability_row_count: int
    event_probability_count: int
    max_event_probability_error_ppb: int
    max_row_total_variation_ppb: int
    mean_row_total_variation_ppb: int
    passed: bool
    schema: str = C4_RESULT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "context_ids": list(self.context_ids),
            "known_policy": self.known_policy,
            "compatible_worlds_per_context": (
                self.compatible_worlds_per_context),
            "prior_weights": list(self.prior_weights),
            "observed_action_likelihood_weights": list(
                self.observed_action_likelihood_weights),
            "posterior_world_weights": list(self.posterior_world_weights),
            "posterior_denominator": self.posterior_denominator,
            "training": {
                "same_actor_encoder": True,
                "same_ownership_model": True,
                "same_adamw_step": True,
                "same_count_head": True,
                "same_exact_projection": True,
                "train_row_count": self.train_row_count,
                "batch_size": self.batch_size,
                "batch_count": self.batch_count,
                "epoch_count": self.epoch_count,
                "model_seed": self.model_seed,
                "model_state_sha256": self.model_state_sha256,
                "training_receipts_sha256": (
                    self.training_receipts_sha256),
            },
            "candidate_ownership_sha256s": list(
                self.candidate_ownership_sha256s),
            "test": {
                "fold": "untouched-enumerated-posterior-v1",
                "probability_row_count": self.probability_row_count,
                "event_probability_count": self.event_probability_count,
                "max_event_probability_error_ppb": (
                    self.max_event_probability_error_ppb),
                "max_event_probability_error_cap_ppb": (
                    C4_MAX_EVENT_ERROR_PPB),
                "max_row_total_variation_ppb": (
                    self.max_row_total_variation_ppb),
                "max_row_total_variation_cap_ppb": (
                    C4_MAX_ROW_TOTAL_VARIATION_PPB),
                "mean_row_total_variation_ppb": (
                    self.mean_row_total_variation_ppb),
            },
            "passed": self.passed,
            "privileged_targets_consumed": True,
            "runtime_artifact": False,
            "sampler_implementation_authorized": False,
            "gameplay_authorized": False,
            "strength_claim_authorized": False,
            "promotion_authorized": False,
            "deployment_authorized": False,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True)
class C4SyntheticEvidenceV1:
    contexts: tuple[C4PublicTwinContextV1, ...]
    training_receipts: tuple[EpochTrainingReceiptV1, ...]
    candidates: tuple[BeliefOwnershipV1, ...]
    result: C4ExactPosteriorResultV1


def _rotate_round(rnd: Round, offset: int) -> Round:
    changed = copy.deepcopy(rnd)
    hands = [[] for _ in range(4)]
    for old_seat, hand in enumerate(changed.hands):
        hands[(old_seat + offset) % 4] = hand
    changed.hands = hands
    changed.banker = (changed.banker + offset) % 4
    changed.turn = (changed.turn + offset) % 4
    changed.passed = {(seat + offset) % 4 for seat in changed.passed}
    if changed.declaration is not None:
        changed.declaration["seat"] = (
            changed.declaration["seat"] + offset) % 4
    for trick in (*changed.history, changed.trick):
        if trick is None:
            continue
        trick.leader = (trick.leader + offset) % 4
        if trick.winner is not None:
            trick.winner = (trick.winner + offset) % 4
        for play in trick.plays:
            play.seat = (play.seat + offset) % 4
    if changed.last_trick_winner is not None:
        changed.last_trick_winner = (
            changed.last_trick_winner + offset) % 4
    return changed


def _rotate_transcript(
        transcript: PublicTranscriptV1, offset: int) -> PublicTranscriptV1:
    return PublicTranscriptV1(
        declarations=tuple(type(event)(
            seat=(event.seat + offset) % 4, cards=event.cards,
            strength=event.strength) for event in transcript.declarations),
        plays=tuple(type(event)(
            seat=(event.seat + offset) % 4,
            attempted_cards=event.attempted_cards,
            actual_cards=event.actual_cards) for event in transcript.plays))


def build_c4_contexts() -> tuple[C4PublicTwinContextV1, ...]:
    """Build the frozen public-twin and absolute-rotation control fixtures."""
    contexts = []
    for index, seed in enumerate((10405, 10407, 10409, 10415)):
        plays = 5 + index
        rnd = Game(random.Random(seed)).start_round()
        bot = HeuristicBot()
        transcript = PublicTranscriptV1()
        while rnd.phase == "deal":
            rnd.deal_next()
        rnd.finalize_declare()
        rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
        for _ in range(plays):
            seat = rnd.turn
            attempted = bot.decide_play(rnd, seat)
            previous_last = rnd.last_trick
            rnd.play(seat, attempted)
            transcript = transcript.with_play(
                seat, attempted, actual_play_after(
                    rnd, seat, previous_last))
        actor = build_actor_observation(rnd, rnd.turn, transcript)
        rotated = _rotate_round(rnd, 1)
        rotated_actor = build_actor_observation(
            rotated, (rnd.turn + 1) % 4,
            _rotate_transcript(transcript, 1))
        if rotated_actor.canonical_bytes() != actor.canonical_bytes():
            raise BeliefSyntheticError("C4 rotation fixture drift")
        changed = copy.deepcopy(rnd)
        hidden = [seat for seat in range(4) if seat != rnd.turn]
        left, right = next(
            (left, right) for left_index, left in enumerate(hidden)
            for right in hidden[left_index + 1:]
            if len(changed.hands[left]) == len(changed.hands[right]))
        changed.hands[left], changed.hands[right] = (
            changed.hands[right], changed.hands[left])
        if build_actor_observation(
                changed, rnd.turn, transcript).canonical_bytes() \
                != actor.canonical_bytes():
            raise BeliefSyntheticError("C4 public-twin fixture drift")
        world_0, world_1 = tuple(capture_corpus_pair(
            world, rnd.turn, round_seed=seed, decision_index=plays,
            transcript=transcript) for world in (rnd, changed))
        rotated_world_0 = capture_corpus_pair(
            rotated, rotated.turn, round_seed=seed,
            decision_index=plays,
            transcript=_rotate_transcript(transcript, 1))
        contexts.append(C4PublicTwinContextV1(
            context_id=C4_CONTEXT_IDS[index],
            world_0=world_0, world_1=world_1,
            rotated_world_0=rotated_world_0))
    result = tuple(contexts)
    _context_examples(result)
    return result


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _context_examples(
        contexts: tuple[C4PublicTwinContextV1, ...]) -> tuple[
            tuple[BeliefTrainingExampleV1, BeliefTrainingExampleV1], ...]:
    if type(contexts) is not tuple or len(contexts) != len(C4_CONTEXT_IDS) \
            or any(type(context) is not C4PublicTwinContextV1
                   for context in contexts) \
            or tuple(context.context_id for context in contexts) \
            != C4_CONTEXT_IDS:
        raise BeliefSyntheticError("C4 context population/order drift")
    rows = []
    actor_hashes = []
    for context in contexts:
        if context.schema != C4_CONTEXT_SCHEMA \
                or context.prior_weights != (1, 1) \
                or context.observed_action_likelihood_weights != (3, 1):
            raise BeliefSyntheticError("C4 known-policy contract drift")
        try:
            actor_0, target_0, _ = reopen_score_pair(context.world_0)
            actor_1, target_1, _ = reopen_score_pair(context.world_1)
            rotated_actor, rotated_target, _ = reopen_score_pair(
                context.rotated_world_0)
        except (TypeError, ValueError) as exc:
            raise BeliefSyntheticError("C4 corpus context refused") from exc
        if actor_0.canonical_bytes() != actor_1.canonical_bytes() \
                or actor_0.canonical_bytes() \
                != rotated_actor.canonical_bytes() \
                or target_0.canonical_bytes() == target_1.canonical_bytes() \
                or target_0.canonical_bytes() \
                != rotated_target.canonical_bytes():
            raise BeliefSyntheticError(
                "C4 worlds are not public twins with distinct targets "
                "and rotated targets")
        actor_hashes.append(actor_0.sha256())
        try:
            examples = tuple(build_training_example(
                pair, behavior_policy_ids=C4_BEHAVIOR_POLICY_IDS)
                for pair in (context.world_0, context.world_1))
            rotated_example = build_training_example(
                context.rotated_world_0,
                behavior_policy_ids=C4_BEHAVIOR_POLICY_IDS)
        except (TypeError, ValueError) as exc:
            raise BeliefSyntheticError("C4 training context refused") from exc
        if examples[0].tensors.history_input_sha256 \
                != examples[1].tensors.history_input_sha256 \
                or examples[0].tensors.history_input_sha256 \
                != rotated_example.tensors.history_input_sha256 \
                or examples[0].count_labels.tobytes() \
                == examples[1].count_labels.tobytes() \
                or examples[0].count_labels.tobytes() \
                != rotated_example.count_labels.tobytes():
            raise BeliefSyntheticError("C4 public-twin tensor/label drift")
        rows.append(examples)
    if len(set(actor_hashes)) != len(actor_hashes):
        raise BeliefSyntheticError("C4 public contexts are not distinct")
    return tuple(rows)  # type: ignore[return-value]


def _training_seeds() -> tuple[int, ...]:
    seeds = []
    seed = C4_SEED_START
    while len(seeds) < C4_TRAIN_ROW_COUNT:
        if split_for_round_seed(seed) == "train":
            seeds.append(seed)
        seed += 1
    return tuple(seeds)


def _training_batches(
        examples: tuple[
            tuple[BeliefTrainingExampleV1, BeliefTrainingExampleV1], ...]) \
        -> tuple[Any, ...]:
    seeds = _training_seeds()
    rows = []
    # Every consecutive batch contains four draws from each context: exactly
    # three posterior-world-0 rows and one posterior-world-1 row.
    for index, seed in enumerate(seeds):
        context_index = index % len(C4_CONTEXT_IDS)
        draw_index = (index // len(C4_CONTEXT_IDS)) % 4
        base = examples[context_index][0 if draw_index < 3 else 1]
        rows.append(replace(
            base,
            round_seed=seed,
            decision_index=0,
            decision_key=decision_key(seed, 0, base.actor_seat),
            split="train",
        ))
    batches = tuple(collate_training_examples(tuple(
        rows[offset:offset + C4_BATCH_SIZE]))
        for offset in range(0, len(rows), C4_BATCH_SIZE))
    if len(batches) != C4_BATCH_COUNT:
        raise BeliefSyntheticError("C4 batch population drift")
    return batches


def _receipt_population_sha256(
        receipts: tuple[EpochTrainingReceiptV1, ...], *,
        final_model_sha256: str) -> str:
    if type(receipts) is not tuple or len(receipts) != C4_EPOCHS \
            or any(type(receipt) is not EpochTrainingReceiptV1
                   for receipt in receipts) \
            or tuple(receipt.epoch for receipt in receipts) \
            != tuple(range(1, C4_EPOCHS + 1)) \
            or any(receipt.batch_count != C4_BATCH_COUNT
                   or receipt.decision_count != C4_TRAIN_ROW_COUNT
                   for receipt in receipts) \
            or any(left.model_state_sha256_after
                   != right.model_state_sha256_before
                   for left, right in zip(receipts, receipts[1:])) \
            or receipts[-1].model_state_sha256_after != final_model_sha256:
        raise BeliefSyntheticError("C4 training receipt chain drift")
    digest = hashlib.sha256()
    digest.update(canonical_json_bytes({
        "schema": "belief-v1-c4-training-receipt-population-v1",
        "receipt_count": len(receipts),
    }))
    for receipt in receipts:
        raw = receipt.canonical_bytes()
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def _evaluate(
        contexts: tuple[C4PublicTwinContextV1, ...],
        candidates: tuple[BeliefOwnershipV1, ...], *,
        model_sha256: str,
        training_receipts_sha256: str) -> C4ExactPosteriorResultV1:
    _context_examples(contexts)
    if not _is_sha256(model_sha256) \
            or not _is_sha256(training_receipts_sha256) \
            or type(candidates) is not tuple \
            or len(candidates) != len(contexts):
        raise BeliefSyntheticError("C4 candidate identity/population drift")
    max_event_error = 0
    max_row_tv = 0
    row_tv_sum = 0
    row_count = 0
    for context, candidate in zip(contexts, candidates, strict=True):
        actor, target_0, _ = reopen_score_pair(context.world_0)
        _, target_1, _ = reopen_score_pair(context.world_1)
        try:
            validate_ownership(actor, candidate)
        except ValueError as exc:
            raise BeliefSyntheticError("C4 candidate ownership refused") \
                from exc
        if candidate.model_schema != MODEL_SCHEMA \
                or candidate.model_sha256 != model_sha256 \
                or candidate.behavior_policy_ids != C4_BEHAVIOR_POLICY_IDS:
            raise BeliefSyntheticError("C4 candidate model binding drift")
        counts = (target_count_population(actor, target_0),
                  target_count_population(actor, target_1))
        for row in candidate.probabilities:
            key = (row.card, row.receiver)
            expected = tuple(sum(
                weight for world_count, weight in zip(
                    (counts[0][key], counts[1][key]),
                    C4_WORLD_POSTERIOR_WEIGHTS, strict=True)
                if world_count == count) * PROBABILITY_SCALE
                // C4_POSTERIOR_DENOMINATOR
                for count in range(3))
            observed = (row.count_0_ppb, row.count_1_ppb,
                        row.count_2_ppb)
            errors = tuple(abs(left - right) for left, right in zip(
                expected, observed, strict=True))
            row_tv = sum(errors) // 2
            max_event_error = max(max_event_error, *errors)
            max_row_tv = max(max_row_tv, row_tv)
            row_tv_sum += row_tv
            row_count += 1
    if row_count <= 0:
        raise BeliefSyntheticError("C4 posterior event population is empty")
    result = C4ExactPosteriorResultV1(
        context_ids=C4_CONTEXT_IDS,
        known_policy=C4_POLICY,
        compatible_worlds_per_context=2,
        prior_weights=(1, 1),
        observed_action_likelihood_weights=(3, 1),
        posterior_world_weights=C4_WORLD_POSTERIOR_WEIGHTS,
        posterior_denominator=C4_POSTERIOR_DENOMINATOR,
        train_row_count=C4_TRAIN_ROW_COUNT,
        batch_size=C4_BATCH_SIZE,
        batch_count=C4_BATCH_COUNT,
        epoch_count=C4_EPOCHS,
        model_seed=C4_MODEL_SEED,
        model_state_sha256=model_sha256,
        training_receipts_sha256=training_receipts_sha256,
        candidate_ownership_sha256s=tuple(
            candidate.sha256() for candidate in candidates),
        probability_row_count=row_count,
        event_probability_count=row_count * 3,
        max_event_probability_error_ppb=max_event_error,
        max_row_total_variation_ppb=max_row_tv,
        mean_row_total_variation_ppb=row_tv_sum // row_count,
        passed=(max_event_error <= C4_MAX_EVENT_ERROR_PPB
                and max_row_tv <= C4_MAX_ROW_TOTAL_VARIATION_PPB),
    )
    return result


def run_c4_synthetic_pipeline(
        contexts: tuple[C4PublicTwinContextV1, ...]) \
        -> C4SyntheticEvidenceV1:
    """Train and score the exact small-domain control once in memory."""
    examples = _context_examples(contexts)
    batches = _training_batches(examples)
    model = new_from_scratch_model(C4_MODEL_SEED)
    optimizer = new_b2_optimizer(model)
    receipts = tuple(train_epoch(
        model, optimizer, batches, epoch=epoch)
        for epoch in range(1, C4_EPOCHS + 1))
    model_sha = model_state_sha256(model)
    receipt_sha = _receipt_population_sha256(
        receipts, final_model_sha256=model_sha)
    actors = tuple(reopen_score_pair(context.world_0)[0]
                   for context in contexts)
    candidates = tuple(predict_ownership(
        model, actor, behavior_policy_ids=C4_BEHAVIOR_POLICY_IDS,
        model_sha256=model_sha) for actor in actors)
    result = _evaluate(
        contexts, candidates, model_sha256=model_sha,
        training_receipts_sha256=receipt_sha)
    evidence = C4SyntheticEvidenceV1(
        contexts=contexts, training_receipts=receipts,
        candidates=candidates, result=result)
    validate_c4_synthetic_evidence(evidence)
    return evidence


def validate_c4_synthetic_evidence(evidence: C4SyntheticEvidenceV1) -> None:
    """Reopen training identities and recompute the exact Bayes comparison."""
    if type(evidence) is not C4SyntheticEvidenceV1 \
            or type(evidence.result) is not C4ExactPosteriorResultV1 \
            or evidence.result.schema != C4_RESULT_SCHEMA:
        raise BeliefSyntheticError("C4 evidence/result schema drift")
    receipt_sha = _receipt_population_sha256(
        evidence.training_receipts,
        final_model_sha256=evidence.result.model_state_sha256)
    expected = _evaluate(
        evidence.contexts, evidence.candidates,
        model_sha256=evidence.result.model_state_sha256,
        training_receipts_sha256=receipt_sha)
    if evidence.result != expected:
        raise BeliefSyntheticError("C4 result derivation drift")

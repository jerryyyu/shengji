"""In-memory, score-free BELIEF-V1 round capture.

The public entry point fixes the behavior policy to the production champion.
It owns ``PublicTranscriptV1`` from the first accepted declaration through the
last play and returns canonical actor/privileged row pairs plus a score-free
manifest.  This module has no CLI, file writer, sampler, model, training loop,
result field, or execution authority.
"""

from __future__ import annotations

import hashlib
import random
from collections import Counter
from dataclasses import dataclass
from typing import Any

from ..ai.registry import make_bot
from ..engine.cards import Ordering, make_deck
from ..engine.game import Game
from ..engine.round import actual_play_after
from .belief_contract import (CapturedDeclarationEvent, CapturedPlayEvent,
                              PublicTranscriptV1, canonical_json_bytes)
from .belief_corpus import (SPLITS, CorpusPairV1, capture_corpus_pair,
                            split_for_round_seed, validate_corpus_pair)


CAPTURE_SCHEMA = "belief-v1-score-free-round-capture-v1"
CHAMPION_POLICY = "mc-s0-report-lcb"
MAX_POLICY_SEED = 2**63 - 1
_CARD_CODES = frozenset(make_deck())


class BeliefCaptureError(ValueError):
    """An in-memory capture violated transcript or manifest boundaries."""


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


@dataclass(frozen=True)
class CapturedBeliefRoundV1:
    round_seed: int
    policy_name: str
    policy_seeds: tuple[int, int, int, int]
    pairs: tuple[CorpusPairV1, ...]
    public_transcript: PublicTranscriptV1
    schema: str = CAPTURE_SCHEMA

    def manifest_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "round_seed": self.round_seed,
            "split": split_for_round_seed(self.round_seed),
            "policy_name": self.policy_name,
            "policy_seeds": list(self.policy_seeds),
            "decision_count": len(self.pairs),
            "declaration_count": len(self.public_transcript.declarations),
            "public_play_count": len(self.public_transcript.plays),
            "engine_adjusted_play_count": sum(
                event.attempted_cards != event.actual_cards
                for event in self.public_transcript.plays),
            "public_transcript_sha256": hashlib.sha256(
                _transcript_bytes(self.public_transcript)).hexdigest(),
            "actor_row_sha256s": [pair.actor_file_sha256
                                  for pair in self.pairs],
            "target_row_sha256s": [pair.target_file_sha256
                                   for pair in self.pairs],
            "contains_round_outcome": False,
            "privileged_rows_are_runtime_inputs": False,
        }

    def manifest_bytes(self) -> bytes:
        return canonical_json_bytes(self.manifest_dict())

    def manifest_sha256(self) -> str:
        return hashlib.sha256(self.manifest_bytes()).hexdigest()


def _validate_seeds(round_seed: int,
                    policy_seeds: tuple[int, int, int, int]) -> None:
    # split_for_round_seed supplies the exact non-bool round-seed boundary.
    split_for_round_seed(round_seed)
    if type(policy_seeds) is not tuple or len(policy_seeds) != 4 \
            or any(type(seed) is not int or not 0 <= seed <= MAX_POLICY_SEED
                   for seed in policy_seeds) \
            or len(set(policy_seeds)) != 4:
        raise BeliefCaptureError(
            "capture requires four distinct exact policy seeds")


def _transcript_dict(transcript: PublicTranscriptV1) -> dict[str, Any]:
    return {
        "schema": "belief-v1-complete-public-transcript-v1",
        "declarations": [
            {"seat": event.seat, "cards": list(event.cards),
             "strength": event.strength}
            for event in transcript.declarations
        ],
        "plays": [
            {"seat": event.seat,
             "attempted_cards": list(event.attempted_cards),
             "actual_cards": list(event.actual_cards)}
            for event in transcript.plays
        ],
    }


def _transcript_bytes(transcript: PublicTranscriptV1) -> bytes:
    return canonical_json_bytes(_transcript_dict(transcript))


def _validate_transcript(transcript: PublicTranscriptV1) -> None:
    if type(transcript) is not PublicTranscriptV1 \
            or type(transcript.declarations) is not tuple \
            or type(transcript.plays) is not tuple:
        raise BeliefCaptureError("capture public transcript type drift")
    for event in transcript.declarations:
        if type(event) is not CapturedDeclarationEvent \
                or type(event.seat) is not int or event.seat not in range(4) \
                or type(event.cards) is not tuple or not event.cards \
                or any(type(card) is not str or card not in _CARD_CODES
                       for card in event.cards) \
                or type(event.strength) is not int \
                or event.strength not in range(1, 5):
            raise BeliefCaptureError("capture declaration event is malformed")
    for event in transcript.plays:
        if type(event) is not CapturedPlayEvent \
                or type(event.seat) is not int or event.seat not in range(4) \
                or type(event.attempted_cards) is not tuple \
                or not event.attempted_cards \
                or type(event.actual_cards) is not tuple \
                or not event.actual_cards \
                or any(type(card) is not str or card not in _CARD_CODES
                       for card in (*event.attempted_cards,
                                    *event.actual_cards)) \
                or Counter(event.actual_cards) - Counter(
                    event.attempted_cards):
            raise BeliefCaptureError("capture play event is malformed")


def _capture_with_policies(
        round_seed: int, policy_name: str,
        policy_seeds: tuple[int, int, int, int], policies: list[Any]
        ) -> CapturedBeliefRoundV1:
    _validate_seeds(round_seed, policy_seeds)
    if type(policy_name) is not str or not policy_name \
            or type(policies) is not list or len(policies) != 4:
        raise BeliefCaptureError("capture policy population is malformed")
    required = ("decide_declare", "decide_bury", "decide_play")
    if any(any(not callable(getattr(policy, method, None))
               for method in required) for policy in policies):
        raise BeliefCaptureError("capture policy interface is incomplete")

    rnd = Game(random.Random(round_seed)).start_round()
    transcript = PublicTranscriptV1()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = policies[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
            accepted = rnd.declaration
            transcript = transcript.with_declaration(
                accepted["seat"], accepted["cards"], accepted["strength"])
    for seat in range(4):
        cards = policies[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
            accepted = rnd.declaration
            transcript = transcript.with_declaration(
                accepted["seat"], accepted["cards"], accepted["strength"])
    rnd.finalize_declare()
    rnd.bury(rnd.banker,
             policies[rnd.banker].decide_bury(rnd, rnd.banker))

    pairs: list[CorpusPairV1] = []
    while rnd.phase == "play":
        seat = rnd.turn
        pair = capture_corpus_pair(
            rnd, seat, round_seed=round_seed,
            decision_index=len(pairs), transcript=transcript)
        attempted = policies[seat].decide_play(rnd, seat)
        previous_last = rnd.last_trick
        rnd.play(seat, attempted)
        actual = actual_play_after(rnd, seat, previous_last)
        transcript = transcript.with_play(seat, attempted, actual)
        pairs.append(pair)

    captured = CapturedBeliefRoundV1(
        round_seed=round_seed,
        policy_name=policy_name,
        policy_seeds=policy_seeds,
        pairs=tuple(pairs),
        public_transcript=transcript,
    )
    validate_captured_round(captured)
    return captured


def capture_champion_round(
        round_seed: int,
        policy_seeds: tuple[int, int, int, int]) -> CapturedBeliefRoundV1:
    """Capture one full champion round in memory without exposing outcomes."""
    _validate_seeds(round_seed, policy_seeds)
    policies = [make_bot(CHAMPION_POLICY, seed=seed)
                for seed in policy_seeds]
    return _capture_with_policies(
        round_seed, CHAMPION_POLICY, policy_seeds, policies)


def validate_captured_round(captured: CapturedBeliefRoundV1) -> None:
    """Reopen ordered rows and validate the closed score-free manifest."""
    if type(captured) is not CapturedBeliefRoundV1 \
            or captured.schema != CAPTURE_SCHEMA:
        raise BeliefCaptureError("capture schema drift")
    _validate_seeds(captured.round_seed, captured.policy_seeds)
    if captured.policy_name != CHAMPION_POLICY:
        raise BeliefCaptureError("capture is not the exact champion policy")
    if type(captured.pairs) is not tuple or not captured.pairs \
            or len(captured.pairs) > 128:
        raise BeliefCaptureError("capture decision population is malformed")
    _validate_transcript(captured.public_transcript)
    if len(captured.public_transcript.plays) != len(captured.pairs):
        raise BeliefCaptureError("capture transcript decision count drift")

    split = split_for_round_seed(captured.round_seed)
    if split not in SPLITS:
        raise BeliefCaptureError("capture split drift")
    actor_hashes: list[str] = []
    target_hashes: list[str] = []
    for index, pair in enumerate(captured.pairs):
        if type(pair) is not CorpusPairV1:
            raise BeliefCaptureError("capture pair type drift")
        actor, target = validate_corpus_pair(
            pair.actor_bytes, pair.target_bytes)
        if actor["round_seed"] != captured.round_seed \
                or actor["decision_index"] != index \
                or actor["split"] != split \
                or target["decision_index"] != index:
            raise BeliefCaptureError("capture row sequence drift")
        actor_seat = actor["actor_seat"]
        ordering = Ordering(actor["actor"]["trump_suit"],
                            actor["actor"]["trump_rank"])
        expected_declarations = [
            {"schema": "final-winning-declaration-v1",
             "seat_relative": (event.seat - actor_seat) % 4,
             "cards": sorted(event.cards, key=ordering.sort_key),
             "strength": event.strength}
            for event in captured.public_transcript.declarations
        ]
        if actor["actor"]["declaration_history"] != expected_declarations:
            raise BeliefCaptureError("capture declaration prefix drift")
        actor_plays = []
        for trick in (*actor["actor"]["completed_tricks"],
                      actor["actor"]["current_trick"]):
            actor_plays.extend(trick["plays"])
        expected_plays = [
            {"seat_relative": (event.seat - actor_seat) % 4,
             "attempted_cards": sorted(event.attempted_cards,
                                       key=ordering.sort_key),
             "cards": sorted(event.actual_cards, key=ordering.sort_key)}
            for event in captured.public_transcript.plays[:index]
        ]
        if actor_plays != expected_plays:
            raise BeliefCaptureError("capture play prefix drift")
        actor_hashes.append(pair.actor_file_sha256)
        target_hashes.append(pair.target_file_sha256)
    manifest = captured.manifest_dict()
    expected_keys = {
        "schema", "round_seed", "split", "policy_name", "policy_seeds",
        "decision_count", "declaration_count", "public_play_count",
        "engine_adjusted_play_count", "public_transcript_sha256",
        "actor_row_sha256s",
        "target_row_sha256s", "contains_round_outcome",
        "privileged_rows_are_runtime_inputs",
    }
    if set(manifest) != expected_keys \
            or manifest["actor_row_sha256s"] != actor_hashes \
            or manifest["target_row_sha256s"] != target_hashes \
            or any(not _is_sha256(value)
                   for value in (*actor_hashes, *target_hashes)) \
            or not _is_sha256(manifest["public_transcript_sha256"]) \
            or manifest["contains_round_outcome"] is not False \
            or manifest["privileged_rows_are_runtime_inputs"] is not False:
        raise BeliefCaptureError("capture manifest drift")

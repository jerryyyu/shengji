"""Transcript replay for REF-C state reconstruction (V2 building block).

The V1 reference stage rebuilds every decision state by re-running the full
champion Monte-Carlo search for every play (``_capture_with_policies``), even
though the searched moves are already sealed, byte-exact, in the capture rows.
Measured on Mini, the world sampling itself costs milliseconds per decision;
the re-search dominates the stage by orders of magnitude.

This module reconstructs the identical decision states WITHOUT re-searching
plays:

- the deal, every declaration decision and the bury are re-run through the
  same seeded policies capture used (declarations and bury are cheap heuristic
  decisions, and the bury MUST be policy-derived here: buried cards are not
  public, and this module — like all REF-C code — never touches targets);
- every PLAY is applied from the sealed public transcript's attempted cards,
  letting the engine resolve failed throws exactly as it did at capture;
- at every decision the replayed actor row is recomputed and must be
  BYTE-IDENTICAL to the sealed row (the load-bearing witness — any divergence
  in replay ordering, engine semantics or inputs refuses loudly);
- the engine-resolved actual cards must equal the transcript's recorded
  actual cards (second witness, same fail-stop).

Nothing here is wired into the reviewed V1 pipeline: no CLI, no stage change,
no import from the V1 reference driver. Adoption is a V2 design decision.
Target-blind by construction: this module imports no target constructor and
opens no target bytes.
"""
from __future__ import annotations

import hashlib
import random
from typing import Any, Callable

from ..engine.game import Game
from ..engine.round import actual_play_after
from .belief_capture import CapturedActorRoundV1, validate_actor_round
from .belief_contract import PublicTranscriptV1
from .belief_corpus import BeliefCorpusError, capture_actor_row


class BeliefReplayError(ValueError):
    """The transcript replay diverged from the sealed capture evidence."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def replay_actor_round(
        *, round_seed: int, policy_name: str,
        policy_seeds: tuple[int, int, int, int], policies: list,
        sealed: CapturedActorRoundV1,
        decision_observer: Callable[..., Any] | None = None) \
        -> CapturedActorRoundV1:
    """Reproduce a sealed actor round from its transcript, without play search.

    ``policies`` must be constructed exactly as they were for capture (same
    classes, same ``policy_seeds``): declarations and the bury are re-run
    through them so the pre-play state — including policy RNG consumption —
    is identical to capture. Plays are then applied from the sealed
    transcript. ``decision_observer`` receives ``(rnd, seat, transcript,
    actor_row)`` at every decision, exactly like the V1 capture driver, so
    REF-C world generation can consume this function as a drop-in state
    source.
    """
    if type(sealed) is not CapturedActorRoundV1 \
            or sealed.round_seed != round_seed \
            or sealed.policy_name != policy_name \
            or sealed.policy_seeds != tuple(policy_seeds):
        raise BeliefReplayError("sealed round identity does not match inputs")
    validate_actor_round(sealed)
    if type(policies) is not list or len(policies) != 4 or any(
            not callable(getattr(policy, method, None))
            for policy in policies
            for method in ("decide_declare", "decide_bury")):
        raise BeliefReplayError("replay policy population is malformed")

    recorded_plays = sealed.public_transcript.plays
    rnd = Game(random.Random(round_seed)).start_round()
    transcript = PublicTranscriptV1()

    # Deal + declarations + bury: identical policy calls to capture. These are
    # cheap heuristic decisions; re-running them (rather than replaying
    # declaration events) guarantees identical engine state AND identical
    # policy RNG streams entering the bury.
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

    if transcript.declarations != sealed.public_transcript.declarations:
        raise BeliefReplayError(
            "replayed declarations diverge from sealed transcript")

    actor_rows: list[bytes] = []
    while rnd.phase == "play":
        seat = rnd.turn
        decision_index = len(actor_rows)
        if decision_index >= len(recorded_plays):
            raise BeliefReplayError(
                "replay produced more decisions than the sealed transcript")
        event = recorded_plays[decision_index]
        if event.seat != seat:
            raise BeliefReplayError(
                f"replayed turn diverges from sealed transcript at decision "
                f"{decision_index}")
        try:
            actor_row = capture_actor_row(
                rnd, seat, round_seed=round_seed,
                decision_index=decision_index, transcript=transcript)
        except BeliefCorpusError as exc:
            raise BeliefReplayError(
                f"replayed state cannot be recaptured at decision "
                f"{decision_index}") from exc
        if actor_row != sealed.actor_rows[decision_index]:
            raise BeliefReplayError(
                f"replayed state diverges from sealed actor row "
                f"{decision_index} (sealed "
                f"{_sha256(sealed.actor_rows[decision_index])[:16]}, replayed "
                f"{_sha256(actor_row)[:16]})")
        if decision_observer is not None:
            decision_observer(rnd, seat, transcript, actor_row)
            try:
                repeated = capture_actor_row(
                    rnd, seat, round_seed=round_seed,
                    decision_index=decision_index, transcript=transcript)
            except BeliefCorpusError as exc:
                raise BeliefReplayError(
                    "replay decision observer mutated round state") from exc
            if repeated != actor_row:
                raise BeliefReplayError(
                    "replay decision observer mutated round state")
        actor_rows.append(actor_row)

        attempted = list(event.attempted_cards)
        previous_last = rnd.last_trick
        rnd.play(seat, attempted)
        actual = actual_play_after(rnd, seat, previous_last)
        if tuple(actual) != tuple(event.actual_cards):
            raise BeliefReplayError(
                f"replayed play resolution diverges from transcript at "
                f"decision {decision_index}")
        transcript = transcript.with_play(seat, attempted, actual)

    if len(actor_rows) != len(sealed.actor_rows):
        raise BeliefReplayError(
            "replay produced fewer decisions than the sealed round")

    result = CapturedActorRoundV1(
        round_seed=round_seed, policy_name=policy_name,
        policy_seeds=tuple(policy_seeds), actor_rows=tuple(actor_rows),
        public_transcript=transcript)
    validate_actor_round(result)
    if result != sealed:
        raise BeliefReplayError(
            "replayed round does not reproduce the sealed round")
    return result

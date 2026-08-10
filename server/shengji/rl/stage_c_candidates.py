"""Public-information candidate sourcing for Stage-C model composition.

Stage-C is trained on a bounded union rather than the live MC ballot alone:
the live ballot, one top V11 proposal, one named structured proposal, and one
deterministic random novel action.  Production inference must rebuild that
same source family or the model would be evaluated on a different action
distribution from the one captured for training.

The builders below deliberately accept the experiment namespace, split and
state key as inputs.  That lets tests reproduce the frozen capture source
byte-for-byte while a whole-game screen derives its seed solely from the
acting player's public observation and own hand.  No opponent hand, sampled
world, rollout value, label, or REPORT outcome enters candidate generation.
"""
from __future__ import annotations

import hashlib
import math
import random
from typing import Iterable, Sequence

from ..ai.bury import structured_bury_ballot
from ..ai.point_banking import PointBankingRolloutPolicy
from ..ai.registry import make_bot
from ..ai.smart import SmartBot
from ..pilot_arms import propose as structured_lead_propose
from .actions import enumerate_actions
from .encode import encode_action, encode_obs
from .stage_c_model import canonical_json


SCHEMA = "teacher-stage-c-candidate-source-v1"
INFERENCE_EXPERIMENT_ID = "teacher-stage-c-composition-screen-v1"
INFERENCE_SPLIT = "SCREEN"
PLAY_CANDIDATE_CAP = 20
BURY_CANDIDATE_CAP = 33


class StageCCandidateError(RuntimeError):
    """The public state, candidate geometry, or proposal source drifted."""


def action_key(action: Sequence[str]) -> tuple[str, ...]:
    if (not isinstance(action, (list, tuple)) or not action
            or any(not isinstance(card, str) or not card for card in action)):
        raise StageCCandidateError("Stage-C candidate action geometry drift")
    return tuple(sorted(action))


def _seed(*parts: object) -> int:
    value = "|".join(str(part) for part in parts).encode()
    return int.from_bytes(hashlib.sha256(value).digest()[:16], "big")


def _dedupe(actions: Iterable[Sequence[str]]) -> list[list[str]]:
    seen: set[tuple[str, ...]] = set()
    result: list[list[str]] = []
    for action in actions:
        key = action_key(action)
        if key not in seen:
            seen.add(key)
            result.append(list(key))
    return result


def public_state_key(rnd, seat: int,
                     live_candidates: Sequence[Sequence[str]]) -> str:
    """Bind inference randomness to public observation plus the live ballot."""
    if (isinstance(seat, bool) or not isinstance(seat, int)
            or not 0 <= seat < 4):
        raise StageCCandidateError("Stage-C candidate seat drift")
    live = _dedupe(live_candidates)
    payload = {
        "schema": "teacher-stage-c-public-candidate-state-v1",
        "seat": seat,
        "observation": encode_obs(rnd, seat),
        "live_candidate_keys": [list(action_key(action)) for action in live],
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def build_play_union(
    rnd, seat: int, state_id: str, split: str, net, production,
    *, experiment_id: str,
    observed_live: Sequence[Sequence[str]] | None = None,
) -> tuple[list[dict], dict]:
    """Build the frozen Stage-C play source family from legal visible inputs."""
    if (not isinstance(state_id, str) or not state_id
            or not isinstance(split, str) or not split
            or not isinstance(experiment_id, str) or not experiment_id):
        raise StageCCandidateError("Stage-C play source identity drift")
    generated_live = _dedupe(production._candidates(rnd, seat))
    if observed_live is not None:
        observed = _dedupe(observed_live)
        if observed != generated_live:
            raise StageCCandidateError(
                "Stage-C observed live ballot differs from production")
        live = observed
    else:
        live = generated_live
    if not live or len(live) > PLAY_CANDIDATE_CAP:
        raise StageCCandidateError("live Stage-C play ballot cap/emptiness drift")

    exhaustive = _dedupe(enumerate_actions(
        rnd, seat, exhaustive_follows=True, include_throws=True))
    live_keys = {action_key(action) for action in live}
    novel = [action for action in exhaustive
             if action_key(action) not in live_keys]

    v11 = None
    if novel:
        values = [float(value) for value in net.value_candidates(
            encode_obs(rnd, seat),
            [encode_action(action, rnd) for action in novel],
        )]
        if (len(values) != len(novel)
                or not all(math.isfinite(value) for value in values)):
            raise StageCCandidateError(
                "V11 proposal returned missing/non-finite values")
        v11 = novel[max(range(len(novel)), key=lambda index: values[index])]

    structured = None
    if not rnd.trick.plays:
        proposed = structured_lead_propose(
            "quota", production, rnd, seat, budget=PLAY_CANDIDATE_CAP,
            seed=_seed(experiment_id, split, state_id, "structured-lead"),
            state_key=state_id,
        )
        structured = next((action for action in proposed
                           if action_key(action) not in live_keys), None)
    else:
        treatment = PointBankingRolloutPolicy(apply_treatment=True)
        candidate = treatment._follow(rnd, seat)
        if action_key(candidate) not in live_keys:
            structured = list(candidate)

    random_novel = None
    if novel:
        random_novel = random.Random(_seed(
            experiment_id, split, state_id, "matched-random")).choice(novel)

    by_key: dict[tuple[str, ...], dict] = {}
    order: list[tuple[str, ...]] = []

    def add(action: Sequence[str] | None, source: str) -> None:
        if action is None:
            return
        key = action_key(action)
        if key not in by_key:
            if len(order) >= PLAY_CANDIDATE_CAP:
                return
            by_key[key] = {"cards": list(key), "sources": []}
            order.append(key)
        if source not in by_key[key]["sources"]:
            by_key[key]["sources"].append(source)

    for action in live:
        add(action, "live_production_ballot")
    add(v11, "v11pair_top_proposal")
    add(structured, "named_structured_lead_or_follow_mechanism")
    add(random_novel, "same_budget_random_diversifier")
    union = [by_key[key] for key in order]
    for candidate in union:
        candidate["sources"].sort()
    if (not union
            or action_key(union[0]["cards"]) != action_key(live[0])):
        raise StageCCandidateError(
            "Stage-C candidate zero differs from live ballot")
    source_names = {source for candidate in union
                    for source in candidate["sources"]}
    diagnostics = {
        "schema": SCHEMA,
        "surface": "play",
        "experiment_id": experiment_id,
        "split": split,
        "state_id": state_id,
        "live_candidates": len(live),
        "exhaustive_actions": len(exhaustive),
        "novel_actions": len(novel),
        "v11_novel": "v11pair_top_proposal" in source_names,
        "structured_novel": (
            "named_structured_lead_or_follow_mechanism" in source_names),
        "random_novel": "same_budget_random_diversifier" in source_names,
        "candidate_count": len(union),
        "candidate_sources": [list(candidate["sources"])
                              for candidate in union],
        "public_information_only": True,
    }
    return union, diagnostics


def build_bury_union(
    rnd, seat: int, state_id: str, *, experiment_id: str,
) -> tuple[list[dict], dict]:
    """Build the frozen structured-plus-random banker bury source family."""
    if (not isinstance(state_id, str) or not state_id
            or not isinstance(experiment_id, str) or not experiment_id):
        raise StageCCandidateError("Stage-C bury source identity drift")
    incumbent = SmartBot().decide_bury(rnd, seat)
    ballot = structured_bury_ballot(
        rnd.hands[seat], rnd.ordering, incumbent, max_candidates=32)
    if (not ballot.candidates or len(ballot.candidates) > 32
            or action_key(ballot.candidates[0].cards)
            != action_key(incumbent)):
        raise StageCCandidateError("Stage-C structured bury ballot drift")
    by_key: dict[tuple[str, ...], dict] = {}
    order: list[tuple[str, ...]] = []

    def add(cards: Sequence[str], sources: Iterable[str]) -> None:
        key = action_key(cards)
        if key not in by_key:
            if len(order) >= BURY_CANDIDATE_CAP:
                return
            by_key[key] = {"cards": list(key), "sources": []}
            order.append(key)
        for source in sources:
            if source not in by_key[key]["sources"]:
                by_key[key]["sources"].append(source)

    for candidate in ballot.candidates:
        add(candidate.cards,
            ("s3a_structured_point_void_bury", *candidate.sources))
    rng = random.Random(_seed(experiment_id, state_id, "random-bury"))
    hand = list(rnd.hands[seat])
    for _ in range(64):
        indices = sorted(rng.sample(range(len(hand)), 8))
        candidate = [hand[index] for index in indices]
        if action_key(candidate) not in by_key:
            add(candidate, ("same_budget_random_structured_bury",))
            break
    union = [by_key[key] for key in order]
    for candidate in union:
        candidate["sources"].sort()
    diagnostics = {
        "schema": SCHEMA,
        "surface": "bury",
        "experiment_id": experiment_id,
        "state_id": state_id,
        "candidate_count": len(union),
        "structured_candidates": len(ballot.candidates),
        "structured_generated_unique": ballot.generated_unique,
        "structured_truncated": ballot.truncated,
        "random_novel": any(
            "same_budget_random_structured_bury" in item["sources"]
            for item in union),
        "candidate_sources": [list(candidate["sources"])
                              for candidate in union],
        "public_information_only": True,
    }
    return union, diagnostics


def make_play_candidate_source(net, *, policy: str = "mc-s0-report-lcb"):
    """Return the candidate-source callback consumed by the play wrapper."""
    production = make_bot(policy, seed=0)

    def source(_wrapper, rnd, seat: int, observed_live):
        state_id = public_state_key(rnd, seat, observed_live)
        union, diagnostics = build_play_union(
            rnd, seat, state_id, INFERENCE_SPLIT, net, production,
            experiment_id=INFERENCE_EXPERIMENT_ID,
            observed_live=observed_live,
        )
        return [list(candidate["cards"]) for candidate in union], diagnostics

    return source


def make_bury_candidate_source(*, policy: str = "mc-s0-report-lcb"):
    """Return a public structured-bury source with live-incumbent binding."""
    production = make_bot(policy, seed=0)

    def source(_wrapper, rnd, seat: int, observed_live):
        live = _dedupe(observed_live)
        expected = _dedupe([production.decide_bury(rnd, seat)])
        if live != expected:
            raise StageCCandidateError(
                "Stage-C observed bury incumbent differs from production")
        state_id = public_state_key(rnd, seat, live)
        union, diagnostics = build_bury_union(
            rnd, seat, state_id, experiment_id=INFERENCE_EXPERIMENT_ID)
        if action_key(union[0]["cards"]) != action_key(live[0]):
            raise StageCCandidateError(
                "Stage-C bury candidate zero differs from live incumbent")
        return [list(candidate["cards"]) for candidate in union], diagnostics

    return source

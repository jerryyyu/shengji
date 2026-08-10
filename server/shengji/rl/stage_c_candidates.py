"""Public-information candidate sourcing for Stage-C model composition.

Stage-C was trained on a bounded union rather than the live MC ballot alone.
The frozen corpus included a V11-origin action, but proposal provenance is not
a model feature and the terminal recall gate did not admit V11 for inference.
Production therefore uses the learned MC-Teacher ensemble itself to propose
one exhaustive novel action, alongside the live ballot, one named structured
proposal, and one deterministic random novel action.  The final whole-game
screen is the authority for this deliberate source-distribution change.

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


SCHEMA = "teacher-stage-c-candidate-source-v3"
INFERENCE_EXPERIMENT_ID = "teacher-stage-c-composition-screen-v3"
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


class _ParentBoundLeadPolicy:
    """Expose one already-observed parent ballot without wrapper recursion.

    ``pilot_arms.structured_universe`` asks its policy for both the protected
    canonical lead and the deployed candidate ballot.  During composition the
    policy object is itself the Stage-C wrapper, so calling its ``_candidates``
    method would recursively re-enter candidate generation.  This narrow
    adapter keeps the exact parent-bound ballot already returned by
    ``super()._candidates`` and delegates only the non-overridden canonical
    lead boundary to the observing wrapper.
    """

    def __init__(self, parent, rnd, seat: int,
                 observed_live: Sequence[Sequence[str]]):
        self._parent = parent
        self._rnd = rnd
        self._seat = seat
        self._live = _dedupe(observed_live)

    def _require_state(self, rnd, seat: int) -> None:
        if rnd is not self._rnd or seat != self._seat:
            raise StageCCandidateError(
                "parent-bound structured lead state drift")

    def canonical_lead(self, rnd, seat: int) -> list[str]:
        self._require_state(rnd, seat)
        value = list(self._parent.canonical_lead(rnd, seat))
        if action_key(value) != action_key(self._live[0]):
            raise StageCCandidateError(
                "parent-bound canonical lead differs from observed ballot")
        return list(self._live[0])

    def _candidates(self, rnd, seat: int) -> list[list[str]]:
        self._require_state(rnd, seat)
        return [list(value) for value in self._live]


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
    observed_live_is_parent_bound: bool = False,
    novel_model_source: str = "v11pair",
) -> tuple[list[dict], dict]:
    """Build the frozen Stage-C play source family from legal visible inputs."""
    if (not isinstance(state_id, str) or not state_id
            or not isinstance(split, str) or not split
            or not isinstance(experiment_id, str) or not experiment_id
            or novel_model_source not in {
                "v11pair", "stage_c_mc_teacher"}):
        raise StageCCandidateError("Stage-C play source identity drift")
    if observed_live_is_parent_bound:
        if observed_live is None:
            raise StageCCandidateError(
                "parent-bound Stage-C play source lacks observed ballot")
        # The composition wrapper obtained this ballot by calling the exact
        # live parent's `_candidates` through `super()`. Calling `_candidates`
        # again here would either recurse into the wrapper or use a detached
        # helper bot whose Memory never observed the current game.
        live = _dedupe(observed_live)
    else:
        generated_live = _dedupe(production._candidates(rnd, seat))
        live = generated_live
    if observed_live is not None and not observed_live_is_parent_bound:
        observed = _dedupe(observed_live)
        if observed != generated_live:
            raise StageCCandidateError(
                "Stage-C observed live ballot differs from production")
        live = observed
    if not live or len(live) > PLAY_CANDIDATE_CAP:
        raise StageCCandidateError("live Stage-C play ballot cap/emptiness drift")

    # The model observation and action encoding treat the hand as a multiset.
    # enumerate_actions preserves incidental engine-list order, so canonicalize
    # before V11 tie-breaking and deterministic random selection.
    exhaustive = sorted(_dedupe(enumerate_actions(
        rnd, seat, exhaustive_follows=True, include_throws=True)),
        key=action_key)
    live_keys = {action_key(action) for action in live}
    novel = [action for action in exhaustive
             if action_key(action) not in live_keys]

    model_proposal = None
    model_source_name = None
    if novel:
        obs = encode_obs(rnd, seat)
        actions = [encode_action(action, rnd) for action in novel]
        if novel_model_source == "v11pair":
            values = [float(value) for value in net.value_candidates(
                obs, actions)]
            if (len(values) != len(novel)
                    or not all(math.isfinite(value) for value in values)):
                raise StageCCandidateError(
                    "V11 proposal returned missing/non-finite values")
            selected = max(
                range(len(novel)), key=lambda index: values[index])
            model_source_name = "v11pair_top_proposal"
        elif novel_model_source == "stage_c_mc_teacher":
            record = net.select(obs, actions)
            selected = record.get("selected_index") \
                if isinstance(record, dict) else None
            if (isinstance(selected, bool) or not isinstance(selected, int)
                    or not 0 <= selected < len(novel)
                    or record.get("candidate_count") != len(novel)):
                raise StageCCandidateError(
                    "Stage-C Teacher proposal returned invalid selection")
            model_source_name = "stage_c_mc_teacher_top_proposal"
        model_proposal = novel[selected]

    structured = None
    if not rnd.trick.plays:
        structured_policy = (
            _ParentBoundLeadPolicy(production, rnd, seat, live)
            if observed_live_is_parent_bound else production)
        proposed = structured_lead_propose(
            "quota", structured_policy, rnd, seat,
            budget=PLAY_CANDIDATE_CAP,
            seed=_seed(experiment_id, split, state_id, "structured-lead"),
            state_key=state_id,
        )
        structured = next((action for action in proposed
                           if action_key(action) not in live_keys), None)
    else:
        treatment = PointBankingRolloutPolicy(apply_treatment=True)
        # The shared follow heuristic walks the stored hand list. Match the
        # capture source's multiset boundary without changing shared policy
        # code or leaving the live round mutated.
        saved_hand = rnd.hands[seat]
        rnd.hands[seat] = sorted(saved_hand)
        try:
            candidate = treatment._follow(rnd, seat)
        finally:
            rnd.hands[seat] = saved_hand
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
    add(model_proposal, model_source_name or "missing_model_proposal")
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
        "novel_model_source": novel_model_source,
        "v11_novel": "v11pair_top_proposal" in source_names,
        "stage_c_teacher_novel": (
            "stage_c_mc_teacher_top_proposal" in source_names),
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
    incumbent: Sequence[str] | None = None,
) -> tuple[list[dict], dict]:
    """Build the frozen structured-plus-random banker bury source family."""
    if (not isinstance(state_id, str) or not state_id
            or not isinstance(experiment_id, str) or not experiment_id):
        raise StageCCandidateError("Stage-C bury source identity drift")
    # Match the frozen capture source: the model observation is a hand
    # multiset, while SmartBot's stable bury sort otherwise inherits list
    # order at equal-valued boundaries.  A caller-provided live incumbent
    # remains literal; only the supplemental ballot sees the canonical hand.
    saved_hand = rnd.hands[seat]
    rnd.hands[seat] = sorted(saved_hand)
    try:
        incumbent = (SmartBot().decide_bury(rnd, seat)
                     if incumbent is None else list(incumbent))
        ballot = structured_bury_ballot(
            rnd.hands[seat], rnd.ordering, incumbent, max_candidates=32)
    finally:
        rnd.hands[seat] = saved_hand
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
    hand = sorted(rnd.hands[seat])
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


def make_play_candidate_source(
    net, *, policy: str = "mc-s0-report-lcb",
    novel_model_source: str = "stage_c_mc_teacher",
):
    """Return the candidate-source callback consumed by the play wrapper."""
    # Resolve the policy eagerly so a stale registry name refuses factory
    # construction. The callback itself must use `_wrapper`: unlike a detached
    # helper, it has observed every declaration, trick and play in this game.
    make_bot(policy, seed=0)

    def source(wrapper, rnd, seat: int, observed_live):
        state_id = public_state_key(rnd, seat, observed_live)
        union, diagnostics = build_play_union(
            rnd, seat, state_id, INFERENCE_SPLIT, net, wrapper,
            experiment_id=INFERENCE_EXPERIMENT_ID,
            observed_live=observed_live,
            observed_live_is_parent_bound=True,
            novel_model_source=novel_model_source,
        )
        return [list(candidate["cards"]) for candidate in union], diagnostics

    return source


def make_bury_candidate_source(*, policy: str = "mc-s0-report-lcb"):
    """Return a public structured-bury source with live-incumbent binding."""
    make_bot(policy, seed=0)

    def source(_wrapper, rnd, seat: int, observed_live):
        live = _dedupe(observed_live)
        if len(live) != 1:
            raise StageCCandidateError(
                "Stage-C observed bury incumbent population drift")
        state_id = public_state_key(rnd, seat, live)
        union, diagnostics = build_bury_union(
            rnd, seat, state_id, experiment_id=INFERENCE_EXPERIMENT_ID,
            incumbent=live[0])
        if action_key(union[0]["cards"]) != action_key(live[0]):
            raise StageCCandidateError(
                "Stage-C bury candidate zero differs from live incumbent")
        return [list(candidate["cards"]) for candidate in union], diagnostics

    return source

#!/usr/bin/env python3
"""Fail-closed S3a structured-bury mechanism screen.

This runner does not register a production policy and does not run a duel.  It
compares three bury candidate sources at exact equal candidate-world work:

* the bounded structured source;
* the historical incumbent-plus-three (``legacy_four``) source; and
* a trigger- and candidate-count-matched random widening control.

Candidate zero is the independently confirmed live champion's literal
banker-visible bury.  A
named selection fold chooses each arm's action, and a disjoint named report
fold estimates its paired gain over candidate zero.  A real shard cannot start
without reopening the exact RLCB-C1 live-parent authority, a clean tree, the
compiled engine, and strict void sampling.  Formal S0's stale ``mc-strong``
fallback is unreachable.  Even a successful aggregate only authorizes
designing a fresh full-game duel; it cannot promote anything itself.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


SERVER = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPTS))

import live_champion_parent as LIVE_PARENT  # noqa: E402
from shengji.ai.bury import (DEFAULT_MAX_CANDIDATES,  # noqa: E402
                             structured_bury_ballot)
from shengji.ai.memory import Memory  # noqa: E402
from shengji.ai.mcbot import (MCBot, _BuryLoose, _BuryNoVoid,  # noqa: E402
                              _BuryStrict)
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine.cards import Ordering  # noqa: E402
from shengji.engine.game import Game  # noqa: E402
from shengji.engine.round import HAND_SIZE, KITTY_SIZE  # noqa: E402


SCHEMA = "s3a-bury-pilot-v2"
AGGREGATE_SCHEMA = "s3a-bury-pilot-aggregate-v2"
STREAM_SCHEMA = "s3a-named-stream-v1"
WORK_SCHEMA = "s3a-exact-work-v1"
SHARD_COUNT = 8
TOTAL_STATES = 512
STATES_PER_SHARD = TOTAL_STATES // SHARD_COUNT
# This is a state-level mechanism screen, not a duel seed/reference freeze.
# V2 preserves the frozen v1 state geometry but authenticates the actual live
# champion.  V1 artifacts cannot enter this namespace.
SEED0 = 136_000_000
SEED_HI = SEED0 + TOTAL_STATES - 1
STRUCTURED_MAX_CANDIDATES = DEFAULT_MAX_CANDIDATES
MIN_STRUCTURED_SELECTION_WORLDS = 8
REPORT_WORLDS = 120
REPORT_Z_95 = 1.96
ARMS = ("structured", "legacy_four", "random_widening")
SCORER_CALL_ORDER = (
    "arms=structured,legacy_four,random_widening",
    "selection=world_index_ascending,candidate_index_ascending",
    "report=world_index_ascending,selected_then_incumbent",
)
SELECTION_RULE = (
    "On a named selection fold, choose the empirical banker-value argmax only "
    "when its paired mean gain over literal candidate zero is at least the "
    "live champion's fixed MARGIN. Score the selected action and candidate "
    "zero on 120 disjoint common report worlds. AUTHORIZE_DUEL_DESIGN only if "
    "the clustered paired 95% lower bounds for structured-minus-incumbent, "
    "structured-minus-equal-work-legacy-four, and structured-minus-trigger-"
    "matched-random are all greater than zero. This screen never promotes."
)
EXPERIMENTAL_FLAGS = (
    "SHENGJI_WEIGHTED_SPLITS",
    "SHENGJI_UNIFORM_DEAL",
    "SHENGJI_PHYSICAL_FILLS",
    "SHENGJI_ALLOW_BALLOT_MISMATCH",
)


class ProtocolRefused(RuntimeError):
    """A fail-closed protocol boundary was not satisfied."""


class HiddenInformationAccess(RuntimeError):
    """A candidate source attempted to read a non-banker hand."""


def _json_bytes(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: os.PathLike | str) -> str:
    return sha256_bytes(Path(path).read_bytes())


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=SERVER.parent, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def atomic_json_exclusive(path: os.PathLike | str, value) -> None:
    """Publish one complete JSON object without an overwrite race.

    ``os.replace`` can overwrite a file created after a preflight check.  A
    same-directory hard link publishes fully-fsynced bytes atomically and
    fails with ``EEXIST`` if another worker already owns the final path.
    """
    path = Path(path)
    partial = Path(str(path) + ".partial")
    if path.exists() or partial.exists():
        raise ProtocolRefused(f"refusing to overwrite {path} or {partial}")
    payload = _json_bytes(value)  # Serialization failures create no residue.
    path.parent.mkdir(parents=True, exist_ok=True)
    published = False
    try:
        with partial.open("xb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.link(partial, path)  # Atomic and exclusive: never replaces `path`.
        published = True
    finally:
        if partial.exists():
            partial.unlink()
    if not published:  # Defensive; normally an exception already escaped.
        raise ProtocolRefused(f"failed to publish {path}")


def canonical_cards(cards: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(cards))


@dataclass(frozen=True)
class Candidate:
    cards: tuple[str, ...]
    sources: tuple[str, ...]

    def record(self) -> dict:
        return {"cards": list(self.cards), "sources": list(self.sources)}


@dataclass(frozen=True)
class ArmBallot:
    arm: str
    candidates: tuple[Candidate, ...]
    triggered: bool
    source: dict

    def record(self) -> dict:
        return {
            "arm": self.arm,
            "triggered": self.triggered,
            "candidate_count": len(self.candidates),
            "source": self.source,
            "candidates": [candidate.record() for candidate in self.candidates],
        }


class _BankerHandOnly:
    def __init__(self, banker: int, hand: Iterable[str]):
        self._banker = banker
        self._hand = list(hand)

    def __getitem__(self, seat: int) -> list[str]:
        if seat != self._banker:
            raise HiddenInformationAccess(
                f"bury source requested hidden seat {seat}; banker is {self._banker}")
        return self._hand

    def __iter__(self):
        raise HiddenInformationAccess("bury source attempted to enumerate hands")

    def __len__(self) -> int:
        raise HiddenInformationAccess("bury source attempted to count all hands")


class _BankerVisibleBuryState:
    """Minimal capability object exposed to incumbent/legacy bury policies."""

    def __init__(self, banker: int, hand: Iterable[str], ordering):
        self.banker = banker
        self.turn = banker
        self.phase = "bury"
        self.ordering = ordering
        self.hands = _BankerHandOnly(banker, hand)


def feature_off_problems(bot) -> list[str]:
    problems = []
    for flag in ("MC_BURY", "STRUCTURED_BURY", "EXACT_ENDGAME"):
        if getattr(bot, flag, None) is not False:
            problems.append(f"{type(bot).__name__}.{flag} is not False")
    return problems


def literal_incumbent(bot, hand: Iterable[str], ordering,
                      banker: int) -> tuple[str, ...]:
    """Run the actual champion bury through a banker-only capability view."""
    problems = feature_off_problems(bot)
    if problems:
        raise ProtocolRefused("production S3 flags are not OFF: " + "; ".join(problems))
    view = _BankerVisibleBuryState(banker, hand, ordering)
    incumbent = canonical_cards(bot.decide_bury(view, banker))
    if len(incumbent) != KITTY_SIZE:
        raise ProtocolRefused("live champion did not return an eight-card bury")
    if Counter(incumbent) - Counter(hand):
        raise ProtocolRefused("live champion returned cards outside its own hand")
    return incumbent


def structured_source(hand: Iterable[str], ordering,
                      incumbent: Iterable[str]) -> ArmBallot:
    raw = structured_bury_ballot(
        list(hand), ordering, list(incumbent),
        max_candidates=STRUCTURED_MAX_CANDIDATES,
    )
    candidates = tuple(
        Candidate(canonical_cards(candidate.cards), tuple(candidate.sources))
        for candidate in raw.candidates
    )
    return ArmBallot(
        arm="structured", candidates=candidates,
        triggered=len(candidates) > 1,
        source={
            "schema": raw.schema,
            "max_candidates": raw.max_candidates,
            "generated_unique": raw.generated_unique,
            "truncated": raw.truncated,
            "visible_inputs": ["banker_hand", "ordering", "incumbent"],
        },
    )


def legacy_four_source(hand: Iterable[str], ordering,
                       incumbent: Iterable[str], banker: int) -> ArmBallot:
    """The exact old incumbent/loose/strict/no-void source, visibility-capped."""
    candidates: list[Candidate] = [
        Candidate(canonical_cards(incumbent), ("incumbent",))]
    seen = {candidates[0].cards}
    view = _BankerVisibleBuryState(banker, hand, ordering)
    for name, policy in (
        ("legacy_loose", _BuryLoose()),
        ("legacy_strict", _BuryStrict()),
        ("legacy_no_void", _BuryNoVoid()),
    ):
        cards = canonical_cards(policy.decide_bury(view, banker))
        if len(cards) != KITTY_SIZE or Counter(cards) - Counter(hand):
            raise ProtocolRefused(f"{name} generated an illegal bury")
        if cards not in seen:
            candidates.append(Candidate(cards, (name,)))
            seen.add(cards)
    return ArmBallot(
        arm="legacy_four", candidates=tuple(candidates),
        triggered=len(candidates) > 1,
        source={
            "schema": "legacy-four-bury-source-v1",
            "source_slots": ["incumbent", "loose", "strict", "no_void"],
            "deduplicated": True,
            "visible_inputs": ["banker_hand", "ordering", "incumbent"],
        },
    )


def named_stream(*, deal_seed: int, state_id: str, purpose: str, fold: str,
                 seat: int | None = None, policy: str | None = None) -> dict:
    identity = {
        "schema": STREAM_SCHEMA,
        "experiment": SCHEMA,
        "deal_seed": int(deal_seed),
        "state_id": state_id,
        "purpose": purpose,
        "fold": fold,
        "seat": seat,
        "policy": policy,
    }
    digest = sha256_bytes(_json_bytes(identity))
    return {**identity, "identity_sha256": digest,
            "seed": int.from_bytes(bytes.fromhex(digest[:32]), "big")}


_STREAM_IDENTITY_FIELDS = (
    "schema", "experiment", "deal_seed", "state_id", "purpose", "fold",
    "seat", "policy",
)


def stream_problems(stream: dict, *, deal_seed: int | None = None,
                    state_id: str | None = None, purpose: str | None = None,
                    fold: str | None = None, seat: int | None = None,
                    policy: str | None = None) -> list[str]:
    problems = []
    identity = {name: stream.get(name) for name in _STREAM_IDENTITY_FIELDS}
    digest = sha256_bytes(_json_bytes(identity))
    expected_seed = int.from_bytes(bytes.fromhex(digest[:32]), "big")
    if stream.get("schema") != STREAM_SCHEMA or \
            stream.get("experiment") != SCHEMA:
        problems.append("stream schema/experiment drift")
    if stream.get("identity_sha256") != digest:
        problems.append("stream identity SHA-256 does not reconcile")
    if stream.get("seed") != expected_seed:
        problems.append("stream seed does not derive from its identity")
    expected = {
        "deal_seed": deal_seed, "state_id": state_id, "purpose": purpose,
        "fold": fold, "seat": seat, "policy": policy,
    }
    for name, value in expected.items():
        if value is not None and stream.get(name) != value:
            problems.append(f"stream {name} drift")
    return sorted(set(problems))


def random_widening_source(hand: Iterable[str], incumbent: Iterable[str],
                           candidate_count: int, triggered: bool,
                           stream: dict) -> ArmBallot:
    """Random physical-subset control with the structured source's trigger/K."""
    if candidate_count < 1:
        raise ProtocolRefused("random control requires candidate zero")
    if stream.get("purpose") != "candidate_source" or stream.get("fold") != "random":
        raise ProtocolRefused("random source did not receive its named source stream")
    physical = sorted(hand)
    incumbent_key = canonical_cards(incumbent)
    candidates = [Candidate(incumbent_key, ("incumbent",))]
    seen = {incumbent_key}
    rng = random.Random(stream["seed"])
    attempts = 0
    cap = max(10_000, candidate_count * 1_000)
    target = candidate_count if triggered else 1
    while len(candidates) < target and attempts < cap:
        attempts += 1
        indices = sorted(rng.sample(range(len(physical)), KITTY_SIZE))
        cards = canonical_cards(physical[index] for index in indices)
        if cards in seen:
            continue
        candidates.append(Candidate(cards, (f"random_draw:{attempts}",)))
        seen.add(cards)
    if len(candidates) != target:
        raise ProtocolRefused(
            f"random control sourced {len(candidates)}/{target} candidates")
    return ArmBallot(
        arm="random_widening", candidates=tuple(candidates),
        triggered=triggered,
        source={
            "schema": "random-physical-subset-bury-source-v1",
            "stream": stream,
            "attempts": attempts,
            "visible_inputs": ["banker_hand", "incumbent", "candidate_count",
                               "trigger"],
        },
    )


def build_ballots(hand: Iterable[str], ordering, incumbent: Iterable[str],
                  banker: int, source_stream: dict) -> dict[str, ArmBallot]:
    hand = list(hand)
    if len(hand) != HAND_SIZE + KITTY_SIZE:
        raise ProtocolRefused("bury candidate source did not receive 33 banker cards")
    incumbent = canonical_cards(incumbent)
    structured = structured_source(hand, ordering, incumbent)
    legacy = legacy_four_source(hand, ordering, incumbent, banker)
    random_control = random_widening_source(
        hand, incumbent, len(structured.candidates), structured.triggered,
        source_stream,
    )
    ballots = {ballot.arm: ballot for ballot in
               (structured, legacy, random_control)}
    for ballot in ballots.values():
        if not ballot.candidates or ballot.candidates[0].cards != incumbent:
            raise ProtocolRefused(f"{ballot.arm} candidate zero is not incumbent")
    if len(random_control.candidates) != len(structured.candidates):
        raise ProtocolRefused("random control candidate count is not matched")
    if random_control.triggered != structured.triggered:
        raise ProtocolRefused("random control trigger is not matched")
    return ballots


def exact_work_plan(candidate_counts: dict[str, int], *,
                    min_structured_worlds: int = MIN_STRUCTURED_SELECTION_WORLDS,
                    report_worlds: int = REPORT_WORLDS) -> dict:
    if set(candidate_counts) != set(ARMS):
        raise ProtocolRefused(f"work plan arms differ: {sorted(candidate_counts)}")
    if any(not isinstance(value, int) or value <= 0
           for value in candidate_counts.values()):
        raise ProtocolRefused("every arm needs a positive integer candidate count")
    if candidate_counts["random_widening"] != candidate_counts["structured"]:
        raise ProtocolRefused("random widening K must equal structured K")
    if min_structured_worlds <= 0 or report_worlds < 30:
        raise ProtocolRefused("selection worlds must be positive and report >=30")

    quantum = math.lcm(*candidate_counts.values())
    target = min_structured_worlds * candidate_counts["structured"]
    selection_work = math.ceil(target / quantum) * quantum
    selection_worlds = {
        arm: selection_work // count for arm, count in candidate_counts.items()
    }
    report_work = 2 * report_worlds
    total_work = selection_work + report_work
    return {
        "schema": WORK_SCHEMA,
        "candidate_counts": dict(candidate_counts),
        "selection": {
            "common_worlds_by_arm": selection_worlds,
            "candidate_worlds_per_arm": selection_work,
            "minimum_structured_worlds": min_structured_worlds,
            "divisibility_quantum": quantum,
        },
        "report": {
            "common_worlds": report_worlds,
            "candidates_scored_per_world": 2,
            "candidate_worlds_per_arm": report_work,
            "purpose": "selected_action_vs_literal_incumbent_only",
        },
        "total_candidate_worlds_per_arm": total_work,
    }


SAMPLER_FIELDS = (
    "sample_attempts", "accepted_worlds", "failed_worlds",
    "rejected_worlds", "impossible_worlds",
)


def _sampler_snapshot(bot) -> dict[str, int]:
    return {name: int(getattr(bot, name, 0)) for name in SAMPLER_FIELDS}


def _counter_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {name: after[name] - before[name] for name in SAMPLER_FIELDS}


def world_digest(hands: dict[int, list[str]]) -> str:
    value = {str(seat): sorted(cards) for seat, cards in sorted(hands.items())}
    return sha256_bytes(_json_bytes(value))


def fold_problems(record: dict, requested: int) -> list[str]:
    problems = []
    if record.get("requested_worlds") != requested:
        problems.append("requested world count drift")
    if record.get("accepted_worlds") != requested:
        problems.append("short fold")
    ids = record.get("draw_ids", [])
    digests = record.get("world_sha256", [])
    if len(ids) != requested or len(set(ids)) != requested:
        problems.append("draw ids are missing or repeated")
    if len(digests) != requested or any(
            not isinstance(value, str) or len(value) != 64 or
            any(char not in "0123456789abcdef" for char in value)
            for value in digests):
        problems.append("world digests are missing or malformed")
    counters = record.get("sampler_counters", {})
    attempts = int(counters.get("sample_attempts", -1))
    accepted = int(counters.get("accepted_worlds", -1))
    failed = int(counters.get("failed_worlds", -1))
    if attempts != accepted + failed:
        problems.append("sampler counters do not reconcile")
    if attempts != requested or accepted != requested:
        problems.append("fold did not consume exactly one accepted draw per world")
    for name in ("failed_worlds", "rejected_worlds", "impossible_worlds"):
        if int(counters.get(name, -1)) != 0:
            problems.append(f"nonzero or missing {name}")
    stream = record.get("stream", {})
    problems.extend(stream_problems(stream))
    if stream.get("fold") != record.get("fold"):
        problems.append("fold/stream identity drift")
    expected_ids = [
        f"{stream.get('identity_sha256')}:{record.get('fold')}:{index:04d}"
        for index in range(requested)
    ]
    if ids != expected_ids:
        problems.append("draw IDs do not derive from the named stream")
    return sorted(set(problems))


BotFactory = Callable[..., object]
ProgressFn = Callable[[str], None]


def draw_world_fold(rnd, seat: int, champion: str, requested: int,
                    stream: dict, *, bot_factory: BotFactory = make_bot
                    ) -> tuple[list[dict[int, list[str]]], dict]:
    if requested <= 0:
        raise ProtocolRefused("world fold must request a positive count")
    bot = bot_factory(champion, seed=stream["seed"])
    off = feature_off_problems(bot)
    if off:
        raise ProtocolRefused("fold sampler activated an S3 feature: " + "; ".join(off))
    mem = Memory(rnd, seat, own_kitty=True)
    before = _sampler_snapshot(bot)
    worlds: list[dict[int, list[str]]] = []
    digests: list[str] = []
    draw_ids: list[str] = []
    for index in range(requested):
        sampled = bot._sample_hands(rnd, seat, mem)
        if sampled is None:
            raise ProtocolRefused(
                f"{stream['fold']} fold sampler rejected/failed draw {index}")
        hands, buried = sampled
        if buried:
            raise ProtocolRefused("banker bury-state sampler returned a hidden kitty")
        try:
            bot._complete_determinized_hands(rnd, seat, hands, buried=[])
        except Exception as exc:
            raise ProtocolRefused(
                f"{stream['fold']} fold produced invalid world {index}: "
                f"{type(exc).__name__}: {exc}") from exc
        worlds.append({int(other): list(cards) for other, cards in hands.items()})
        digests.append(world_digest(hands))
        draw_ids.append(
            f"{stream['identity_sha256']}:{stream['fold']}:{index:04d}")
    after = _sampler_snapshot(bot)
    record = {
        "schema": "s3a-world-fold-v1",
        "fold": stream["fold"],
        "stream": stream,
        "requested_worlds": requested,
        "accepted_worlds": len(worlds),
        "draw_ids": draw_ids,
        "world_sha256": digests,
        "sampler_counters": _counter_delta(before, after),
    }
    problems = fold_problems(record, requested)
    if problems:
        raise ProtocolRefused(
            f"{stream['fold']} fold failed closed: " + "; ".join(problems))
    return worlds, record


def _paired_se(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    return statistics.stdev(values) / math.sqrt(len(values))


ValueFunction = Callable[[dict[int, list[str]], tuple[str, ...]], float]


def evaluate_arm(ballot: ArmBallot, selection_worlds: list,
                 report_worlds: list, plan: dict, margin: float,
                 value_fn: ValueFunction, *, selection_ids: list[str],
                 report_ids: list[str]) -> dict:
    candidates = ballot.candidates
    arm = ballot.arm
    requested_selection = plan["selection"]["common_worlds_by_arm"][arm]
    requested_report = plan["report"]["common_worlds"]
    if len(selection_worlds) < requested_selection:
        raise ProtocolRefused(f"{arm}: short selection fold")
    if len(report_worlds) != requested_report:
        raise ProtocolRefused(f"{arm}: short report fold")
    selection_worlds = selection_worlds[:requested_selection]
    selection_ids = selection_ids[:requested_selection]

    totals = [0.0] * len(candidates)
    paired = [[] for _ in candidates]
    selection_values = []
    selection_calls = 0
    for world in selection_worlds:
        values = []
        for index, candidate in enumerate(candidates):
            value = float(value_fn(world, candidate.cards))
            if not math.isfinite(value):
                raise ProtocolRefused(f"{arm}: non-finite selection value")
            values.append(value)
            totals[index] += value
            selection_calls += 1
        selection_values.append(values)
        for index, value in enumerate(values):
            paired[index].append(value - values[0])
    means = [total / requested_selection for total in totals]
    best = max(range(len(candidates)), key=lambda index: (means[index], -index))
    gap = sum(paired[best]) / requested_selection
    chosen = best if best != 0 and gap >= margin else 0
    reason = (
        "incumbent_best" if best == 0 else
        "below_fixed_margin" if chosen == 0 else
        "selection_override"
    )

    report_deltas = []
    report_selected_values = []
    report_incumbent_values = []
    report_calls = 0
    for world in report_worlds:
        # Score twice even when chosen == 0. Equal total work is a protocol
        # fact, not a shortcut conditional on the selected result.
        selected_value = float(value_fn(world, candidates[chosen].cards))
        incumbent_value = float(value_fn(world, candidates[0].cards))
        if not math.isfinite(selected_value) or not math.isfinite(incumbent_value):
            raise ProtocolRefused(f"{arm}: non-finite report value")
        report_selected_values.append(selected_value)
        report_incumbent_values.append(incumbent_value)
        report_deltas.append(selected_value - incumbent_value)
        report_calls += 2
    report_mean = sum(report_deltas) / requested_report
    report_se = _paired_se(report_deltas)

    expected_selection = plan["selection"]["candidate_worlds_per_arm"]
    expected_report = plan["report"]["candidate_worlds_per_arm"]
    expected_total = plan["total_candidate_worlds_per_arm"]
    work = {
        "selection_candidate_worlds": selection_calls,
        "report_candidate_worlds": report_calls,
        "total_candidate_worlds": selection_calls + report_calls,
        "expected_selection_candidate_worlds": expected_selection,
        "expected_report_candidate_worlds": expected_report,
        "expected_total_candidate_worlds": expected_total,
        "complete": (
            selection_calls == expected_selection and
            report_calls == expected_report and
            selection_calls + report_calls == expected_total
        ),
    }
    if not work["complete"]:
        raise ProtocolRefused(f"{arm}: exact candidate-world work underfilled")
    return {
        "schema": "s3a-arm-evaluation-v1",
        "arm": arm,
        "triggered": ballot.triggered,
        "candidate_count": len(candidates),
        "incumbent_index": 0,
        "candidates": [candidate.record() for candidate in candidates],
        "selection": {
            "worlds": requested_selection,
            "draw_ids": selection_ids,
            "values_by_world": selection_values,
            "means": means,
            "paired_mean_vs_incumbent": [
                sum(values) / requested_selection for values in paired],
            "raw_winner_index": best,
            "chosen_index": chosen,
            "reason": reason,
            "margin": margin,
            "raw_gap_vs_incumbent": gap,
        },
        "report": {
            "worlds": requested_report,
            "draw_ids": list(report_ids),
            "chosen_index": chosen,
            "selected_values": report_selected_values,
            "incumbent_values": report_incumbent_values,
            "deltas_vs_incumbent": report_deltas,
            "mean_gain_vs_incumbent": report_mean,
            "paired_se": report_se,
        },
        "work": work,
    }


def evaluate_all_arms(rnd, seat: int, champion: str,
                      ballots: dict[str, ArmBallot], plan: dict,
                      selection_worlds: list, report_worlds: list,
                      selection_ids: list[str], report_ids: list[str],
                      scorer_stream: dict, *,
                      bot_factory: BotFactory = make_bot) -> tuple[dict, object]:
    """Score every arm in one frozen order with one fresh named scorer.

    Both production and independent reopening call this exact routine.  The
    order is protocol-significant even though today's heuristic continuation
    is deterministic: for each registered arm, selection walks worlds then
    candidates, followed by report worlds scored selected-first/incumbent-
    second.  A future scorer cannot silently consume its RNG in another order.
    """
    scorer = bot_factory(champion, seed=scorer_stream["seed"])
    off = feature_off_problems(scorer)
    if off:
        raise ProtocolRefused(
            "rollout scorer activated an S3 feature: " + "; ".join(off))

    def banker_value(world, cards) -> float:
        attacker_points = scorer._rollout_from_bury(
            rnd, seat, world, list(cards))
        return -float(scorer._score(attacker_points))

    margin = float(getattr(scorer, "MARGIN", 5.0))
    arm_records = {}
    for arm in ARMS:
        arm_records[arm] = evaluate_arm(
            ballots[arm], selection_worlds, report_worlds, plan, margin,
            banker_value,
            selection_ids=selection_ids,
            report_ids=report_ids,
        )
    return arm_records, scorer


def _cards_legal(candidate: Iterable[str], hand: Iterable[str]) -> bool:
    candidate = list(candidate)
    return len(candidate) == KITTY_SIZE and not (Counter(candidate) - Counter(hand))


def _finite_numbers(values) -> bool:
    return isinstance(values, list) and all(
        isinstance(value, (int, float)) and math.isfinite(value)
        for value in values)


def _same_float(left, right) -> bool:
    return (isinstance(left, (int, float)) and
            isinstance(right, (int, float)) and
            math.isfinite(left) and math.isfinite(right) and
            math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12))


def _same_float_list(left, right) -> bool:
    return (isinstance(left, list) and isinstance(right, list) and
            len(left) == len(right) and
            all(_same_float(a, b) for a, b in zip(left, right)))


def _finite_matrix(value, rows: int, columns: int) -> bool:
    return (isinstance(value, list) and len(value) == rows and
            all(_finite_numbers(row) and len(row) == columns for row in value))


def state_record_problems(record: dict, *,
                          bot_factory: BotFactory = make_bot,
                          replay_evidence: bool = True) -> list[str]:
    problems = []
    if record.get("schema") != "s3a-bury-state-v1":
        problems.append("state schema drift")
    deal_seed = record.get("deal_seed")
    champion = record.get("champion")
    if not isinstance(deal_seed, int):
        problems.append("deal seed is not an integer")
    if not isinstance(champion, str) or not champion:
        problems.append("champion identity is missing")
    try:
        champion_contract = policy_contract(champion) if champion else None
    except Exception as exc:
        champion_contract = None
        problems.append(f"champion contract replay failed: {type(exc).__name__}: {exc}")
    source_input = record.get("source_input", {})
    incumbent = record.get("incumbent", [])
    hand = source_input.get("banker_hand", [])
    banker = source_input.get("banker")
    ordering_value = source_input.get("ordering", {})
    if len(hand) != HAND_SIZE + KITTY_SIZE:
        problems.append("source input is not a 33-card banker hand")
    if not _cards_legal(incumbent, hand):
        problems.append("illegal literal incumbent")
    if incumbent != list(canonical_cards(incumbent)):
        problems.append("literal incumbent is not canonical")
    if source_input.get("incumbent") != incumbent:
        problems.append("source-input incumbent differs")
    if not isinstance(banker, int) or not 0 <= banker < 4:
        problems.append("invalid source-input banker")
    state_id = record.get("state_id")
    if isinstance(deal_seed, int) and isinstance(banker, int):
        expected_state_id = f"{SCHEMA}:deal:{deal_seed}:banker:{banker}"
        if state_id != expected_state_id:
            problems.append("state ID does not derive from deal seed/banker")
    if record.get("source_input_sha256") != sha256_bytes(_json_bytes(source_input)):
        problems.append("source-input SHA-256 does not reconcile")
    try:
        ordering = Ordering(
            ordering_value.get("trump_suit"), ordering_value["trump_rank"])
    except Exception as exc:
        ordering = None
        problems.append(f"invalid source ordering: {type(exc).__name__}")

    flags = record.get("production_s3_flags", {})
    expected_flags = {"MC_BURY": False, "STRUCTURED_BURY": False,
                      "EXACT_ENDGAME": False}
    if flags != expected_flags:
        problems.append("record production S3 flags are not exactly OFF")
    scoring = record.get("scoring", {})
    if scoring.get("perspective") != "banker_team" or scoring.get("value") != \
            "negative_terminal_champion_score_of_attacker_points":
        problems.append("scoring perspective/objective drift")
    if scoring.get("rollout_policy_class") != "HeuristicBot":
        problems.append("scoring continuation is not the frozen heuristic")
    if scoring.get("call_order") != list(SCORER_CALL_ORDER):
        problems.append("scorer call order drift")
    if champion_contract is not None:
        if not _same_float(scoring.get("champion_margin"),
                           champion_contract.get("margin")):
            problems.append("scoring margin differs from champion contract")
        if scoring.get("level_objective") is not bool(
                champion_contract.get("level_objective")):
            problems.append("scoring level objective differs from champion contract")
        if scoring.get("rollout_policy_class") != champion_contract.get(
                "rollout_policy_class"):
            problems.append("scoring continuation differs from champion contract")
    scorer_stream = scoring.get("stream", {})
    if isinstance(deal_seed, int) and isinstance(banker, int):
        problems.extend(
            f"scorer {problem}" for problem in stream_problems(
                scorer_stream, deal_seed=deal_seed, state_id=state_id,
                purpose="rollout_scorer", fold="shared", seat=banker,
                policy=champion,
            ))

    replay = record.get("replay", {})
    if replay.get("deal_seed") != deal_seed or replay.get("banker") != banker:
        problems.append("replay deal/banker identity drift")
    if replay.get("ordering") != ordering_value:
        problems.append("replay/source ordering drift")
    deck_sha = replay.get("deck_sha256")
    if not isinstance(deck_sha, str) or len(deck_sha) != 64 or any(
            char not in "0123456789abcdef" for char in deck_sha):
        problems.append("replay deck SHA-256 is malformed")
    actor_streams = replay.get("actor_streams", [])
    if len(actor_streams) != 4:
        problems.append("replay does not carry four actor streams")
    elif isinstance(deal_seed, int):
        for seat, stream in enumerate(actor_streams):
            problems.extend(
                f"actor {seat} {problem}" for problem in stream_problems(
                    stream, deal_seed=deal_seed, state_id=f"deal:{deal_seed}",
                    purpose="actor", fold="deal", seat=seat, policy=champion,
                ))

    # A digest of producer-supplied bytes is only a self-consistency check. It
    # cannot stop one valid state from being copied and renamed to every seed.
    # Re-run the cheap deal/declaration boundary from the registered seed and
    # champion, then require byte-level agreement before reopening any scores.
    replay_round = None
    replay_incumbent = None
    if isinstance(deal_seed, int) and champion:
        try:
            replay_round, replay_incumbent, expected_replay = build_bury_state(
                deal_seed, champion)
            replay_banker = replay_round.banker
            assert replay_banker is not None and replay_round.ordering is not None
            expected_source_input = {
                "banker": replay_banker,
                "banker_hand": list(replay_round.hands[replay_banker]),
                "ordering": _ordering_record(replay_round.ordering),
                "incumbent": list(replay_incumbent),
            }
        except Exception as exc:
            problems.append(
                "named deal/champion replay failed: "
                f"{type(exc).__name__}: {exc}")
        else:
            if replay != expected_replay:
                problems.append("replay transcript differs from named deal/champion")
            if source_input != expected_source_input:
                problems.append("source input differs from named deal/champion replay")
            if incumbent != list(replay_incumbent):
                problems.append("incumbent differs from named deal/champion replay")

    if ordering is not None and isinstance(banker, int) and champion:
        try:
            expected_incumbent = literal_incumbent(
                make_bot(champion, seed=7), hand, ordering, banker)
        except Exception as exc:
            problems.append(
                f"literal incumbent replay failed: {type(exc).__name__}: {exc}")
        else:
            if list(expected_incumbent) != incumbent:
                problems.append("candidate zero differs from replayed champion bury")

    arms = record.get("arms", {})
    if set(arms) != set(ARMS):
        problems.append(f"arm set drift: {sorted(arms)}")
        return problems
    plan = record.get("work_plan", {})
    counts = plan.get("candidate_counts", {})
    try:
        expected_plan = exact_work_plan(counts)
    except Exception as exc:
        expected_plan = None
        problems.append(f"invalid exact-work plan: {type(exc).__name__}: {exc}")
    else:
        if plan != expected_plan:
            problems.append("exact-work plan does not match the registered formula")
    expected_selection = plan.get("selection", {}).get(
        "candidate_worlds_per_arm")
    expected_report = plan.get("report", {}).get("candidate_worlds_per_arm")
    expected_total = plan.get("total_candidate_worlds_per_arm")

    ballot_records = record.get("ballots", {})
    if set(ballot_records) != set(ARMS):
        problems.append("source ballot arm set drift")
    source_stream = ballot_records.get("random_widening", {}).get(
        "source", {}).get("stream", {})
    if isinstance(deal_seed, int) and isinstance(banker, int):
        problems.extend(
            f"random source {problem}" for problem in stream_problems(
                source_stream, deal_seed=deal_seed, state_id=state_id,
                purpose="candidate_source", fold="random", seat=banker,
                policy=champion,
            ))
    if ordering is not None and isinstance(banker, int):
        try:
            rebuilt = build_ballots(
                hand, ordering, incumbent, banker, source_stream)
            rebuilt_records = {arm: rebuilt[arm].record() for arm in ARMS}
        except Exception as exc:
            problems.append(
                f"candidate source replay failed: {type(exc).__name__}: {exc}")
        else:
            if ballot_records != rebuilt_records:
                problems.append("candidate source records do not replay exactly")

    for arm in ARMS:
        arm_record = arms[arm]
        if arm_record.get("schema") != "s3a-arm-evaluation-v1" or \
                arm_record.get("arm") != arm:
            problems.append(f"{arm}: arm schema/identity drift")
        candidates = arm_record.get("candidates", [])
        if not candidates or candidates[0].get("cards") != incumbent:
            problems.append(f"{arm}: candidate zero is not literal incumbent")
        if ballot_records.get(arm, {}).get("candidates") != candidates:
            problems.append(f"{arm}: source/evaluation candidates differ")
        if ballot_records.get(arm, {}).get("triggered") != arm_record.get("triggered"):
            problems.append(f"{arm}: source/evaluation trigger differs")
        keys = [canonical_cards(candidate.get("cards", []))
                for candidate in candidates]
        if len(keys) != len(set(keys)):
            problems.append(f"{arm}: duplicate candidate multiset")
        if any(not _cards_legal(candidate.get("cards", []), hand)
               for candidate in candidates):
            problems.append(f"{arm}: illegal candidate")
        if arm_record.get("candidate_count") != len(candidates):
            problems.append(f"{arm}: candidate count mismatch")
        if counts.get(arm) != len(candidates):
            problems.append(f"{arm}: work-plan candidate count mismatch")
        selection = arm_record.get("selection", {})
        chosen = selection.get("chosen_index")
        raw = selection.get("raw_winner_index")
        if not isinstance(chosen, int) or not 0 <= chosen < len(candidates):
            problems.append(f"{arm}: invalid chosen index")
        if not isinstance(raw, int) or not 0 <= raw < len(candidates):
            problems.append(f"{arm}: invalid raw winner index")
        expected_worlds = plan.get("selection", {}).get(
            "common_worlds_by_arm", {}).get(arm)
        if selection.get("worlds") != expected_worlds:
            problems.append(f"{arm}: selection world count drift")
        if len(selection.get("draw_ids", [])) != expected_worlds:
            problems.append(f"{arm}: selection draw coverage drift")
        raw_matrix = selection.get("values_by_world", [])
        matrix_ok = (
            isinstance(expected_worlds, int) and expected_worlds > 0 and
            len(candidates) > 0 and
            _finite_matrix(raw_matrix, expected_worlds, len(candidates))
        )
        if not matrix_ok:
            problems.append(f"{arm}: raw selection value matrix is malformed")
            derived_means = None
            derived_paired = None
        else:
            derived_means = [
                sum(row[index] for row in raw_matrix) / expected_worlds
                for index in range(len(candidates))
            ]
            derived_paired = [
                sum(row[index] - row[0] for row in raw_matrix) / expected_worlds
                for index in range(len(candidates))
            ]
        means = selection.get("means", [])
        paired_means = selection.get("paired_mean_vs_incumbent", [])
        if len(means) != len(candidates) or not _finite_numbers(means):
            problems.append(f"{arm}: selection means are malformed")
        if len(paired_means) != len(candidates) or not _finite_numbers(paired_means):
            problems.append(f"{arm}: paired selection means are malformed")
        if derived_means is not None and not _same_float_list(means, derived_means):
            problems.append(f"{arm}: selection means do not derive from raw values")
        if derived_paired is not None and not _same_float_list(
                paired_means, derived_paired):
            problems.append(
                f"{arm}: paired selection means do not derive from raw values")
        if derived_means is not None:
            expected_raw = max(
                range(len(candidates)),
                key=lambda index: (derived_means[index], -index))
            if raw != expected_raw:
                problems.append(f"{arm}: raw winner does not match argmax")
        else:
            expected_raw = None
        if derived_paired is not None:
            if not _same_float(derived_paired[0], 0.0):
                problems.append(f"{arm}: candidate-zero paired mean is not zero")
            if isinstance(expected_raw, int):
                expected_gap = derived_paired[expected_raw]
                if not _same_float(selection.get("raw_gap_vs_incumbent"),
                                   expected_gap):
                    problems.append(f"{arm}: raw paired gap does not reconcile")
                margin = selection.get("margin")
                if not _same_float(margin, scoring.get("champion_margin")):
                    problems.append(f"{arm}: selection/champion margin drift")
                if isinstance(margin, (int, float)) and math.isfinite(margin):
                    expected_chosen = (expected_raw if expected_raw != 0 and
                                       expected_gap >= margin else 0)
                    if chosen != expected_chosen:
                        problems.append(f"{arm}: chosen index violates margin rule")
                    expected_reason = (
                        "incumbent_best" if expected_raw == 0 else
                        "below_fixed_margin" if expected_chosen == 0 else
                        "selection_override"
                    )
                    if selection.get("reason") != expected_reason:
                        problems.append(f"{arm}: selection reason drift")
        report = arm_record.get("report", {})
        report_worlds = plan.get("report", {}).get("common_worlds")
        selected_values = report.get("selected_values", [])
        incumbent_values = report.get("incumbent_values", [])
        deltas = report.get("deltas_vs_incumbent", [])
        raw_report_ok = (
            isinstance(report_worlds, int) and report_worlds > 0 and
            _finite_numbers(selected_values) and
            _finite_numbers(incumbent_values) and
            len(selected_values) == report_worlds and
            len(incumbent_values) == report_worlds
        )
        if not raw_report_ok:
            problems.append(f"{arm}: raw report values are malformed")
            derived_deltas = None
        else:
            derived_deltas = [selected - base for selected, base in
                              zip(selected_values, incumbent_values)]
        if report.get("worlds") != report_worlds or len(deltas) != report_worlds:
            problems.append(f"{arm}: report world count drift")
        if len(report.get("draw_ids", [])) != report_worlds:
            problems.append(f"{arm}: report draw coverage drift")
        if report.get("chosen_index") != chosen:
            problems.append(f"{arm}: selection/report chosen index drift")
        if not _finite_numbers(deltas):
            problems.append(f"{arm}: report deltas are non-finite/malformed")
        elif derived_deltas is not None:
            if not _same_float_list(deltas, derived_deltas):
                problems.append(f"{arm}: report deltas do not derive from raw values")
            mean = sum(derived_deltas) / len(derived_deltas)
            if not _same_float(mean, report.get("mean_gain_vs_incumbent")):
                problems.append(f"{arm}: report mean does not reconcile")
            expected_se = _paired_se(derived_deltas)
            if expected_se is None:
                if report.get("paired_se") is not None:
                    problems.append(f"{arm}: report SE does not reconcile")
            elif not _same_float(expected_se, report.get("paired_se")):
                problems.append(f"{arm}: report SE does not reconcile")
            if chosen == 0 and not _same_float_list(
                    selected_values, incumbent_values):
                problems.append(
                    f"{arm}: incumbent-vs-itself raw report values differ")
        work = arm_record.get("work", {})
        actual_selection_work = (
            sum(len(row) for row in raw_matrix) if matrix_ok else None)
        actual_report_work = (
            len(selected_values) + len(incumbent_values)
            if raw_report_ok else None)
        actual_total_work = (
            actual_selection_work + actual_report_work
            if actual_selection_work is not None and
            actual_report_work is not None else None)
        if work.get("selection_candidate_worlds") != actual_selection_work:
            problems.append(f"{arm}: selection work does not derive from raw values")
        if work.get("report_candidate_worlds") != actual_report_work:
            problems.append(f"{arm}: report work does not derive from raw values")
        if work.get("total_candidate_worlds") != actual_total_work:
            problems.append(f"{arm}: total work does not derive from raw values")
        if work.get("selection_candidate_worlds") != expected_selection:
            problems.append(f"{arm}: selection work differs")
        if work.get("report_candidate_worlds") != expected_report:
            problems.append(f"{arm}: report work differs")
        if work.get("total_candidate_worlds") != expected_total:
            problems.append(f"{arm}: total work differs")
        if work.get("expected_selection_candidate_worlds") != expected_selection or \
                work.get("expected_report_candidate_worlds") != expected_report or \
                work.get("expected_total_candidate_worlds") != expected_total:
            problems.append(f"{arm}: embedded expected-work fields drift")
        if work.get("complete") is not True:
            problems.append(f"{arm}: incomplete work")

    if len(arms["random_widening"].get("candidates", [])) != len(
            arms["structured"].get("candidates", [])):
        problems.append("random/structured candidate counts differ")
    if arms["random_widening"].get("triggered") != arms["structured"].get(
            "triggered"):
        problems.append("random/structured trigger differs")
    if len(arms["legacy_four"].get("candidates", [])) > 4:
        problems.append("legacy-four source has more than four candidates")

    folds = record.get("folds", {})
    selection_fold = folds.get("selection", {})
    report_fold = folds.get("report", {})
    selection_world_map = plan.get("selection", {}).get(
        "common_worlds_by_arm", {})
    selection_requested = (max(selection_world_map.values())
                           if selection_world_map else 0)
    report_requested = plan.get("report", {}).get("common_worlds", 0)
    problems.extend(f"selection fold: {problem}" for problem in
                    fold_problems(selection_fold, selection_requested))
    problems.extend(f"report fold: {problem}" for problem in
                    fold_problems(report_fold, report_requested))
    selection_ids = selection_fold.get("draw_ids", [])
    report_ids = report_fold.get("draw_ids", [])
    if set(selection_ids) & set(report_ids):
        problems.append("selection and report draw IDs overlap")
    if selection_fold.get("stream", {}).get("identity_sha256") == \
            report_fold.get("stream", {}).get("identity_sha256"):
        problems.append("selection and report streams are identical")
    if isinstance(deal_seed, int) and isinstance(banker, int):
        problems.extend(
            f"selection {problem}" for problem in stream_problems(
                selection_fold.get("stream", {}), deal_seed=deal_seed,
                state_id=state_id, purpose="determinizations",
                fold="selection", seat=banker, policy=champion,
            ))
        problems.extend(
            f"report {problem}" for problem in stream_problems(
                report_fold.get("stream", {}), deal_seed=deal_seed,
                state_id=state_id, purpose="determinizations",
                fold="report", seat=banker, policy=champion,
            ))
    for arm in ARMS:
        selection = arms[arm]["selection"]["draw_ids"]
        report = arms[arm]["report"]["draw_ids"]
        if selection != selection_ids[:len(selection)]:
            problems.append(f"{arm}: selection is not the common prefix")
        if report != report_ids:
            problems.append(f"{arm}: report fold is not common")
    if arms["structured"]["selection"]["draw_ids"] != \
            arms["random_widening"]["selection"]["draw_ids"]:
        problems.append("structured/random selection worlds differ")

    # Reopen the evidence from executable inputs, never from producer values.
    # The deal, ballots, named streams, sampled worlds, and scorer are all
    # reconstructed afresh.  Comparing only summaries to persisted raw values
    # would let a producer replace both consistently; comparing only stream
    # identities would leave the recorded world hashes decorative.
    if replay_evidence and replay_round is not None and \
            replay_incumbent is not None:
        try:
            replay_banker = replay_round.banker
            replay_ordering = replay_round.ordering
            assert replay_banker is not None and replay_ordering is not None
            replay_state_id = (
                f"{SCHEMA}:deal:{deal_seed}:banker:{replay_banker}")
            expected_source_stream = named_stream(
                deal_seed=deal_seed, state_id=replay_state_id,
                purpose="candidate_source", fold="random",
                seat=replay_banker, policy=champion,
            )
            replay_ballots = build_ballots(
                replay_round.hands[replay_banker], replay_ordering,
                replay_incumbent, replay_banker, expected_source_stream,
            )
            replay_plan = exact_work_plan({
                arm: len(replay_ballots[arm].candidates) for arm in ARMS})
            expected_selection_stream = named_stream(
                deal_seed=deal_seed, state_id=replay_state_id,
                purpose="determinizations", fold="selection",
                seat=replay_banker, policy=champion,
            )
            expected_report_stream = named_stream(
                deal_seed=deal_seed, state_id=replay_state_id,
                purpose="determinizations", fold="report",
                seat=replay_banker, policy=champion,
            )
            replay_selection_count = max(
                replay_plan["selection"]["common_worlds_by_arm"].values())
            replay_selection_worlds, expected_selection_fold = draw_world_fold(
                replay_round, replay_banker, champion,
                replay_selection_count, expected_selection_stream,
                bot_factory=bot_factory,
            )
            replay_report_worlds, expected_report_fold = draw_world_fold(
                replay_round, replay_banker, champion, REPORT_WORLDS,
                expected_report_stream, bot_factory=bot_factory,
            )
            expected_scorer_stream = named_stream(
                deal_seed=deal_seed, state_id=replay_state_id,
                purpose="rollout_scorer", fold="shared",
                seat=replay_banker, policy=champion,
            )
            expected_arms, replay_scorer = evaluate_all_arms(
                replay_round, replay_banker, champion, replay_ballots,
                replay_plan, replay_selection_worlds, replay_report_worlds,
                expected_selection_fold["draw_ids"],
                expected_report_fold["draw_ids"], expected_scorer_stream,
                bot_factory=bot_factory,
            )
        except Exception as exc:
            problems.append(
                "named fold/scorer replay failed: "
                f"{type(exc).__name__}: {exc}")
        else:
            for fold_name, persisted_fold, expected_fold in (
                ("selection", selection_fold, expected_selection_fold),
                ("report", report_fold, expected_report_fold),
            ):
                if persisted_fold.get("draw_ids") != expected_fold["draw_ids"]:
                    problems.append(
                        f"{fold_name} fold draw IDs differ from named-stream replay")
                if persisted_fold.get("world_sha256") != \
                        expected_fold["world_sha256"]:
                    problems.append(
                        f"{fold_name} fold ordered world SHA-256 differs from "
                        "named-stream replay")
                if persisted_fold.get("sampler_counters") != \
                        expected_fold["sampler_counters"]:
                    problems.append(
                        f"{fold_name} fold sampler counters differ from "
                        "named-stream replay")
                if persisted_fold != expected_fold:
                    problems.append(
                        f"{fold_name} fold transcript differs from "
                        "named-stream replay")

            expected_scoring = {
                "perspective": "banker_team",
                "value": "negative_terminal_champion_score_of_attacker_points",
                "champion_margin": float(
                    getattr(replay_scorer, "MARGIN", 5.0)),
                "level_objective": bool(
                    getattr(replay_scorer, "LEVEL_OBJECTIVE", False)),
                "rollout_policy_class": type(
                    replay_scorer.rollout_policy).__name__,
                "call_order": list(SCORER_CALL_ORDER),
                "stream": expected_scorer_stream,
            }
            if scoring != expected_scoring:
                problems.append("scoring contract differs from fresh scorer replay")

            for arm in ARMS:
                persisted_arm = arms[arm]
                expected_arm = expected_arms[arm]
                if persisted_arm.get("selection", {}).get(
                        "values_by_world") != \
                        expected_arm["selection"]["values_by_world"]:
                    problems.append(
                        f"{arm}: raw selection values differ from fresh scorer replay")
                for field in ("selected_values", "incumbent_values"):
                    if persisted_arm.get("report", {}).get(field) != \
                            expected_arm["report"][field]:
                        problems.append(
                            f"{arm}: raw report {field} differ from fresh "
                            "scorer replay")
                if persisted_arm != expected_arm:
                    problems.append(
                        f"{arm}: evaluation differs from named world/scorer replay")
    return sorted(set(problems))


def _ordering_record(ordering) -> dict:
    return {"trump_suit": ordering.trump_suit,
            "trump_rank": ordering.trump_rank}


def _declaration_record(rnd) -> dict | None:
    if rnd.declaration is None:
        return None
    return {
        "seat": rnd.declaration["seat"],
        "cards": list(rnd.declaration["cards"]),
        "strength": rnd.declaration["strength"],
    }


def build_bury_state(deal_seed: int, champion: str):
    game = Game(random.Random(deal_seed))
    rnd = game.start_round()
    actors = []
    actor_streams = []
    declaration_log = []
    deal_state_id = f"deal:{deal_seed}"
    for seat in range(4):
        stream = named_stream(
            deal_seed=deal_seed, state_id=deal_state_id,
            purpose="actor", fold="deal", seat=seat, policy=champion,
        )
        actor_streams.append(stream)
        bot = make_bot(champion, seed=stream["seed"])
        off = feature_off_problems(bot)
        if off:
            raise ProtocolRefused("live champion activates S3: " + "; ".join(off))
        actors.append(bot)
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = actors[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
            declaration_log.append({
                "stage": "deal", "deal_pos": rnd._deal_pos,
                "seat": seat, "cards": list(cards),
            })
    for seat in range(4):
        cards = actors[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
            declaration_log.append({
                "stage": "final", "deal_pos": rnd._deal_pos,
                "seat": seat, "cards": list(cards),
            })
    rnd.finalize_declare()
    if rnd.phase != "bury" or rnd.banker is None or rnd.ordering is None:
        raise ProtocolRefused("deterministic deal did not reach a banker bury state")
    incumbent = literal_incumbent(
        actors[rnd.banker], rnd.hands[rnd.banker], rnd.ordering, rnd.banker)
    replay = {
        "deal_seed": deal_seed,
        "deck_sha256": sha256_bytes(_json_bytes(list(rnd.deck))),
        "declarations": declaration_log,
        "final_declaration": _declaration_record(rnd),
        "banker": rnd.banker,
        "ordering": _ordering_record(rnd.ordering),
        "actor_streams": actor_streams,
    }
    return rnd, incumbent, replay


def run_state(deal_seed: int, champion: str, *,
              bot_factory: BotFactory = make_bot) -> dict:
    rnd, incumbent, replay = build_bury_state(deal_seed, champion)
    seat = rnd.banker
    assert seat is not None and rnd.ordering is not None
    state_id = f"{SCHEMA}:deal:{deal_seed}:banker:{seat}"
    source_stream = named_stream(
        deal_seed=deal_seed, state_id=state_id,
        purpose="candidate_source", fold="random", seat=seat,
        policy=champion,
    )
    ballots = build_ballots(
        rnd.hands[seat], rnd.ordering, incumbent, seat, source_stream)
    plan = exact_work_plan({arm: len(ballots[arm].candidates) for arm in ARMS})
    selection_stream = named_stream(
        deal_seed=deal_seed, state_id=state_id,
        purpose="determinizations", fold="selection", seat=seat,
        policy=champion,
    )
    report_stream = named_stream(
        deal_seed=deal_seed, state_id=state_id,
        purpose="determinizations", fold="report", seat=seat,
        policy=champion,
    )
    max_selection_worlds = max(
        plan["selection"]["common_worlds_by_arm"].values())
    selection_worlds, selection_fold = draw_world_fold(
        rnd, seat, champion, max_selection_worlds, selection_stream,
        bot_factory=bot_factory,
    )
    report_worlds, report_fold = draw_world_fold(
        rnd, seat, champion, REPORT_WORLDS, report_stream,
        bot_factory=bot_factory,
    )
    scorer_stream = named_stream(
        deal_seed=deal_seed, state_id=state_id,
        purpose="rollout_scorer", fold="shared", seat=seat,
        policy=champion,
    )
    arm_records, scorer = evaluate_all_arms(
        rnd, seat, champion, ballots, plan, selection_worlds, report_worlds,
        selection_fold["draw_ids"], report_fold["draw_ids"], scorer_stream,
        bot_factory=bot_factory,
    )
    margin = float(getattr(scorer, "MARGIN", 5.0))
    source_input = {
        "banker": seat,
        "banker_hand": list(rnd.hands[seat]),
        "ordering": _ordering_record(rnd.ordering),
        "incumbent": list(incumbent),
    }
    record = {
        "schema": "s3a-bury-state-v1",
        "state_id": state_id,
        "deal_seed": deal_seed,
        "champion": champion,
        "production_s3_flags": {
            name: getattr(scorer, name, None)
            for name in ("MC_BURY", "STRUCTURED_BURY", "EXACT_ENDGAME")
        },
        "scoring": {
            "perspective": "banker_team",
            "value": "negative_terminal_champion_score_of_attacker_points",
            "champion_margin": margin,
            "level_objective": bool(getattr(scorer, "LEVEL_OBJECTIVE", False)),
            "rollout_policy_class": type(scorer.rollout_policy).__name__,
            "call_order": list(SCORER_CALL_ORDER),
            "stream": scorer_stream,
        },
        "replay": replay,
        "source_input": source_input,
        "source_input_sha256": sha256_bytes(_json_bytes(source_input)),
        "incumbent": list(incumbent),
        "ballots": {arm: ballots[arm].record() for arm in ARMS},
        "work_plan": plan,
        "folds": {"selection": selection_fold, "report": report_fold},
        "arms": arm_records,
    }
    # Full independent fold/scorer reopening happens when the artifact is
    # validated.  Avoid a redundant third set of full-game rollouts while the
    # producer is still assembling this not-yet-published record.
    problems = state_record_problems(
        record, bot_factory=bot_factory, replay_evidence=False)
    if problems:
        raise ProtocolRefused(
            f"state {deal_seed} failed validation: " + "; ".join(problems))
    return record


def live_parent() -> dict:
    try:
        return LIVE_PARENT.require_live_champion_parent()
    except LIVE_PARENT.ProtocolRefused as exc:
        raise ProtocolRefused(f"live champion parent refused: {exc}") from exc


def policy_contract(champion: str) -> dict:
    bot = make_bot(champion, seed=7)
    return {
        "policy": champion,
        "class": type(bot).__name__,
        "n_determinizations": getattr(bot, "N_DETERMINIZATIONS", None),
        "margin": getattr(bot, "MARGIN", None),
        "level_objective": getattr(bot, "LEVEL_OBJECTIVE", None),
        "rollout_policy_class": type(getattr(bot, "rollout_policy", None)).__name__,
        "mc_bury": getattr(bot, "MC_BURY", None),
        "structured_bury": getattr(bot, "STRUCTURED_BURY", None),
        "exact_endgame": getattr(bot, "EXACT_ENDGAME", None),
    }


def runtime_identity(fast) -> dict:
    files = {
        "runner": Path(__file__),
        "live_champion_parent": SCRIPTS / "live_champion_parent.py",
        "rlcb_closeout": SCRIPTS / "rlcb_c1_artifact_closeout.py",
        "bury_source": SERVER / "shengji/ai/bury.py",
        "mcbot": SERVER / "shengji/ai/mcbot.py",
        "registry": SERVER / "shengji/ai/registry.py",
        "smart": SERVER / "shengji/ai/smart.py",
        "heuristic": SERVER / "shengji/ai/heuristic.py",
        "memory": SERVER / "shengji/ai/memory.py",
        "game": SERVER / "shengji/engine/game.py",
        "round": SERVER / "shengji/engine/round.py",
        "cards": SERVER / "shengji/engine/cards.py",
        "legal": SERVER / "shengji/engine/legal.py",
        "combos": SERVER / "shengji/engine/combos.py",
        "fast_router": Path(fast.__file__),
        "fast_binary": Path(fast._fast.__file__),
    }
    return {
        "host": os.uname().nodename,
        "python": platform.python_version(),
        "fast_engine": True,
        "require_voids": True,
        "experimental_sampler_ballot_flags": [],
        "digests": {name: sha256(path) for name, path in files.items()},
    }


def protocol_problems(champion: str) -> list[str]:
    problems = []
    if champion != LIVE_PARENT.CHAMPION_POLICY:
        problems.append("S3a v2 reference is not exact live report-LCB")
    if TOTAL_STATES != 512 or SHARD_COUNT != 8 or STATES_PER_SHARD != 64:
        problems.append("registered state/shard geometry drifted")
    if SEED0 != 136_000_000 or SEED_HI != 136_000_511:
        problems.append("registered state seed block drifted")
    if STRUCTURED_MAX_CANDIDATES != 32:
        problems.append("structured candidate cap drifted")
    if MIN_STRUCTURED_SELECTION_WORLDS != 8 or REPORT_WORLDS != 120:
        problems.append("selection/report dose drifted")
    if ARMS != ("structured", "legacy_four", "random_widening"):
        problems.append("registered controls drifted")
    try:
        contract = policy_contract(champion)
    except Exception as exc:
        problems.append(f"champion construction failed: {type(exc).__name__}: {exc}")
    else:
        if any(contract[name] is not False for name in
               ("mc_bury", "structured_bury", "exact_endgame")):
            problems.append("production S3 flags are not all OFF")
        if contract["rollout_policy_class"] != "HeuristicBot":
            problems.append("S3a v2 requires the frozen heuristic continuation")
        if not isinstance(contract["margin"], (int, float)):
            problems.append("live champion has no numeric fixed margin")
    return sorted(set(problems))


def require_real_context() -> tuple[dict, dict, str]:
    if os.environ.get("SHENGJI_FAST") != "1" or \
            os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise ProtocolRefused("set SHENGJI_FAST=1 and SHENGJI_REQUIRE_VOIDS=1")
    enabled = [name for name in EXPERIMENTAL_FLAGS if name in os.environ]
    if enabled:
        raise ProtocolRefused(
            f"experimental sampler/ballot flags must be unset: {enabled}")
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise ProtocolRefused("compiled engine requested but not active")
    dirty = git("status", "--porcelain")
    if dirty:
        raise ProtocolRefused("S3a refuses a dirty real-run/verifier tree")
    head = git("rev-parse", "HEAD")
    parent = live_parent()
    problems = protocol_problems(parent["champion_policy"])
    if problems:
        raise ProtocolRefused("S3a protocol drift: " + "; ".join(problems))
    return parent, runtime_identity(fast), head


def _sha_field(value) -> bool:
    return (isinstance(value, str) and len(value) == 64 and
            all(char in "0123456789abcdef" for char in value))


def parent_problems(parent: dict) -> list[str]:
    return LIVE_PARENT.parent_problems(parent)


def records_digest(records: list[dict]) -> str:
    return sha256_bytes(_json_bytes(records))


def summarize_records(records: list[dict]) -> dict:
    """Untrusted shard convenience summary; every consumer re-derives it."""
    gain_sums = {}
    candidate_worlds = {}
    for arm in ARMS:
        gain_sums[arm] = sum(
            float(record.get("arms", {}).get(arm, {}).get("report", {}).get(
                "mean_gain_vs_incumbent", 0.0))
            for record in records
        )
        candidate_worlds[arm] = sum(
            int(record.get("arms", {}).get(arm, {}).get("work", {}).get(
                "total_candidate_worlds", 0))
            for record in records
        )
    return {
        "states": len(records),
        "report_gain_sums": gain_sums,
        "candidate_worlds": candidate_worlds,
    }


def artifact_problems(artifact: dict, *,
                      bot_factory: BotFactory = make_bot,
                      progress: ProgressFn | None = None) -> list[str]:
    problems = []
    if artifact.get("schema") != SCHEMA:
        problems.append("artifact schema drift")
    manifest = artifact.get("manifest", {})
    records = artifact.get("records", [])
    if manifest.get("schema") != SCHEMA:
        problems.append("manifest schema drift")
    if manifest.get("complete") is not True or manifest.get("problems"):
        problems.append("manifest is incomplete/failed")
    if manifest.get("tree_dirty") is not False:
        problems.append("manifest tree is dirty")
    if not isinstance(manifest.get("evidence_eligible"), bool):
        problems.append("manifest evidence bit is not boolean")
    if manifest.get("production_promotion") is not False:
        problems.append("state screen claims production promotion")
    if manifest.get("fast_engine") is not True or \
            manifest.get("require_voids") is not True:
        problems.append("manifest runtime is not compiled+strict")
    frozen = {
        "selection_rule": SELECTION_RULE,
        "arms": list(ARMS),
        "structured_max_candidates": STRUCTURED_MAX_CANDIDATES,
        "minimum_structured_selection_worlds": MIN_STRUCTURED_SELECTION_WORLDS,
        "report_worlds": REPORT_WORLDS,
        "shard_count": SHARD_COUNT,
        "total_states": TOTAL_STATES,
    }
    for name, value in frozen.items():
        if manifest.get(name) != value:
            problems.append(f"manifest frozen field drift: {name}")
    index = manifest.get("shard_index")
    if not isinstance(index, int) or not 0 <= index < SHARD_COUNT:
        problems.append("manifest shard index is invalid")
    else:
        expected_seed0 = SEED0 + index * STATES_PER_SHARD
        expected_states = (STATES_PER_SHARD if manifest.get("evidence_eligible")
                           else 2)
        if manifest.get("states") != expected_states:
            problems.append("manifest smoke/evidence state count drift")
        if manifest.get("seed0") != expected_seed0 or \
                manifest.get("seed_hi") != expected_seed0 + expected_states - 1:
            problems.append("manifest shard seed geometry drift")
    runtime = manifest.get("runtime_identity", {})
    if runtime != {
        "host": manifest.get("host"),
        "python": manifest.get("python"),
        "fast_engine": manifest.get("fast_engine"),
        "require_voids": manifest.get("require_voids"),
        "experimental_sampler_ballot_flags": manifest.get(
            "experimental_sampler_ballot_flags"),
        "digests": manifest.get("digests"),
    }:
        problems.append("manifest runtime identity does not reconcile")
    digests = runtime.get("digests", {}) if isinstance(runtime, dict) else {}
    if not isinstance(digests, dict) or not _sha_field(digests.get("fast_binary")):
        problems.append("manifest lacks compiled binary SHA-256")
    if manifest.get("record_count") != len(records):
        problems.append("manifest record count drift")
    if manifest.get("records_sha256") != records_digest(records):
        problems.append("manifest records SHA-256 does not reconcile")
    if manifest.get("summary") != summarize_records(records):
        problems.append("manifest local summary does not reconcile")
    if len(records) != manifest.get("states"):
        problems.append("artifact state count drift")
    seeds = [record.get("deal_seed") for record in records]
    if len(seeds) != len(set(seeds)):
        problems.append("duplicate deal seed")
    if seeds and (min(seeds) != manifest.get("seed0") or
                  max(seeds) != manifest.get("seed_hi") or
                  sorted(seeds) != list(range(min(seeds), max(seeds) + 1))):
        problems.append("artifact seed coverage is not exact contiguous")
    parent = manifest.get("parent", {})
    problems.extend(parent_problems(parent))
    champion = parent.get("champion_policy")
    if manifest.get("champion") != champion:
        problems.append("manifest champion differs from terminal parent")
    contract = manifest.get("policy_contract", {})
    if any(contract.get(name) is not False for name in
           ("mc_bury", "structured_bury", "exact_endgame")):
        problems.append("manifest production S3 flags are not OFF")
    try:
        expected_contract = policy_contract(champion)
    except Exception as exc:
        problems.append(f"manifest champion contract cannot replay: {exc}")
    else:
        if contract != expected_contract:
            problems.append("manifest policy contract differs from executable champion")
    replay_started = time.perf_counter()
    for offset, record in enumerate(records, start=1):
        seed = record.get("deal_seed")
        if progress is not None:
            progress(
                f"S3a replay shard {manifest.get('shard_index')}: "
                f"starting {offset}/{len(records)} seed={seed}")
        if record.get("champion") != champion:
            problems.append("record champion differs")
        problems.extend(
            f"seed {seed}: {problem}"
            for problem in state_record_problems(
                record, bot_factory=bot_factory))
        if progress is not None:
            elapsed = time.perf_counter() - replay_started
            progress(
                f"S3a replay shard {manifest.get('shard_index')}: "
                f"completed {offset}/{len(records)} seed={seed} "
                f"elapsed={elapsed:.1f}s")
    return sorted(set(problems))


def run_shard(args) -> None:
    parent, runtime, head = require_real_context()
    if not 0 <= args.shard_index < SHARD_COUNT:
        raise ProtocolRefused(f"shard-index must satisfy 0 <= i < {SHARD_COUNT}")
    states = 2 if args.smoke else STATES_PER_SHARD
    seed0 = SEED0 + args.shard_index * STATES_PER_SHARD
    run_id = (f"{SCHEMA}_shard{args.shard_index:02d}_{head[:10]}" +
              ("_SMOKE" if args.smoke else ""))
    out = Path(args.out or f"runs/logs/{run_id}.json")
    if out.exists() or Path(str(out) + ".partial").exists():
        raise ProtocolRefused(f"refusing to overwrite {out}")

    started = time.strftime("%Y-%m-%d %H:%M:%S %Z")
    records = []
    t0 = time.perf_counter()
    for offset, seed in enumerate(range(seed0, seed0 + states), start=1):
        records.append(run_state(seed, parent["champion_policy"]))
        if offset == 1 or offset == states or offset % args.progress_every == 0:
            elapsed = time.perf_counter() - t0
            print(
                f"S3a shard {args.shard_index}: {offset}/{states} states "
                f"seed={seed} elapsed={elapsed:.1f}s", flush=True)
    manifest = {
        "schema": SCHEMA,
        "run_id": run_id,
        "evidence_eligible": not args.smoke,
        "production_promotion": False,
        "git_sha": head,
        "tree_dirty": False,
        "host": runtime["host"],
        "python": runtime["python"],
        "fast_engine": runtime["fast_engine"],
        "require_voids": runtime["require_voids"],
        "experimental_sampler_ballot_flags": runtime[
            "experimental_sampler_ballot_flags"],
        "digests": runtime["digests"],
        "runtime_identity": runtime,
        "parent": parent,
        "champion": parent["champion_policy"],
        "policy_contract": policy_contract(parent["champion_policy"]),
        "selection_rule": SELECTION_RULE,
        "arms": list(ARMS),
        "structured_max_candidates": STRUCTURED_MAX_CANDIDATES,
        "minimum_structured_selection_worlds": MIN_STRUCTURED_SELECTION_WORLDS,
        "report_worlds": REPORT_WORLDS,
        "shard_index": args.shard_index,
        "shard_count": SHARD_COUNT,
        "total_states": TOTAL_STATES,
        "states": states,
        "seed0": seed0,
        "seed_hi": seed0 + states - 1,
        "started": started,
        "completed": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "record_count": len(records),
        "records_sha256": records_digest(records),
        "summary": summarize_records(records),
        "complete": True,
        "problems": [],
    }
    artifact = {"schema": SCHEMA, "manifest": manifest, "records": records}
    problems = artifact_problems(
        artifact, progress=lambda message: print(message, flush=True))
    if problems:
        raise ProtocolRefused("S3a shard failed closed: " + "; ".join(problems))
    atomic_json_exclusive(out, artifact)
    print(f"S3a artifact: {out}", flush=True)


def _manifest_identity(manifest: dict) -> dict:
    return {key: manifest.get(key) for key in (
        "git_sha", "runtime_identity", "parent", "champion",
        "policy_contract", "selection_rule", "arms",
        "structured_max_candidates", "minimum_structured_selection_worlds",
        "report_worlds", "shard_count", "total_states",
    )}


def validate_artifacts(artifacts: list[tuple[Path, dict]], *,
                       current_runtime: dict | None = None,
                       current_head: str | None = None,
                       parent: dict | None = None,
                       bot_factory: BotFactory = make_bot,
                       progress: ProgressFn | None = None) -> list[str]:
    problems = []
    if len(artifacts) != SHARD_COUNT:
        problems.append(f"found {len(artifacts)} shards, expected {SHARD_COUNT}")
    manifests = [artifact.get("manifest", {}) for _, artifact in artifacts]
    indices = [manifest.get("shard_index") for manifest in manifests]
    if sorted(indices, key=str) != list(range(SHARD_COUNT)):
        problems.append(f"shard indices are {sorted(indices, key=str)}")
    identities = {_json_bytes(_manifest_identity(manifest)) for manifest in manifests}
    if len(identities) > 1:
        problems.append("shards disagree on protocol/runtime/parent identity")
    all_seeds = []
    for path, artifact in artifacts:
        manifest = artifact.get("manifest", {})
        if manifest.get("evidence_eligible") is not True:
            problems.append(f"non-evidence/smoke shard {path}")
        if manifest.get("states") != STATES_PER_SHARD:
            problems.append(f"wrong state count in {path}")
        index = manifest.get("shard_index")
        if isinstance(index, int) and 0 <= index < SHARD_COUNT:
            want = SEED0 + index * STATES_PER_SHARD
            if manifest.get("seed0") != want or \
                    manifest.get("seed_hi") != want + STATES_PER_SHARD - 1:
                problems.append(f"shard {index}: seed block drift")
        if current_runtime is not None and manifest.get("runtime_identity") != current_runtime:
            problems.append(f"runtime identity differs in {path}")
        if current_head is not None and manifest.get("git_sha") != current_head:
            problems.append(f"git identity differs in {path}")
        if parent is not None and manifest.get("parent") != parent:
            problems.append(f"live champion parent differs in {path}")
        subproblems = artifact_problems(
            artifact, bot_factory=bot_factory, progress=progress)
        problems.extend(f"{path}: {problem}" for problem in subproblems)
        all_seeds.extend(record.get("deal_seed") for record in
                         artifact.get("records", []))
    if len(all_seeds) != TOTAL_STATES or len(set(all_seeds)) != TOTAL_STATES:
        problems.append("combined record count/uniqueness is not 512")
    if set(all_seeds) != set(range(SEED0, SEED0 + TOTAL_STATES)):
        problems.append("combined exact seed coverage differs")
    return sorted(set(problems))


def _summary(values: list[float]) -> dict:
    n = len(values)
    if n < 2:
        return {"mean": None, "half_width_95": None, "lcb_95": None,
                "states": n}
    mean = sum(values) / n
    half = REPORT_Z_95 * statistics.stdev(values) / math.sqrt(n)
    return {"mean": mean, "half_width_95": half,
            "lcb_95": mean - half, "states": n,
            "interval": "paired_state_cluster_normal_approx_z1.96"}


def aggregate_result(artifacts: list[tuple[Path, dict]], *,
                     runtime: dict, head: str, parent: dict,
                     bot_factory: BotFactory = make_bot,
                     progress: ProgressFn | None = None) -> dict:
    problems = validate_artifacts(
        artifacts, current_runtime=runtime, current_head=head, parent=parent,
        bot_factory=bot_factory, progress=progress)
    if problems:
        return {
            "schema": AGGREGATE_SCHEMA,
            "status": "HOLD",
            "git_sha": head,
            "runtime_identity": runtime,
            "parent": parent,
            "champion": parent.get("champion_policy"),
            "states": 0,
            "seed0": SEED0,
            "seed_hi": SEED_HI,
            "selection_rule": SELECTION_RULE,
            "shards": [{"path": str(path), "sha256": sha256(path)}
                       for path, _ in artifacts if path.is_file()],
            "stats": {},
            "criteria": {"all": False},
            "problems": problems,
            "duel_design_authorized": False,
            "production_promotion": False,
            "duel_reference_frozen": False,
            "note": "Invalid/incomplete inputs force HOLD; no duel is authorized.",
        }
    records = [record for _, artifact in artifacts
               for record in artifact["records"]]
    gains = {
        arm: [float(record["arms"][arm]["report"]["mean_gain_vs_incumbent"])
              for record in records]
        for arm in ARMS
    }
    values = {
        "structured-incumbent": gains["structured"],
        "structured-legacy_four": [
            a - b for a, b in zip(gains["structured"], gains["legacy_four"])],
        "structured-random_widening": [
            a - b for a, b in zip(gains["structured"], gains["random_widening"])],
    }
    stats = {name: _summary(rows) for name, rows in values.items()}
    criteria = {
        f"{name}_lcb_gt_0": stat["lcb_95"] is not None and stat["lcb_95"] > 0
        for name, stat in stats.items()
    }
    criteria["all"] = all(criteria.values())
    return {
        "schema": AGGREGATE_SCHEMA,
        "status": "AUTHORIZE_DUEL_DESIGN" if criteria["all"] else "HOLD",
        "git_sha": head,
        "runtime_identity": runtime,
        "parent": parent,
        "champion": parent["champion_policy"],
        "states": TOTAL_STATES,
        "seed0": SEED0,
        "seed_hi": SEED_HI,
        "selection_rule": SELECTION_RULE,
        "shards": [{"path": str(path), "sha256": sha256(path)}
                   for path, _ in artifacts],
        "stats": stats,
        "criteria": criteria,
        "problems": [],
        "duel_design_authorized": criteria["all"],
        "production_promotion": False,
        "duel_reference_frozen": False,
        "note": (
            "A PASS authorizes preregistering a fresh full-game duel only. "
            "This state-level screen cannot promote or deploy structured bury."
        ),
    }


def load_artifacts(pattern: str) -> list[tuple[Path, dict]]:
    artifacts = []
    for value in sorted(glob.glob(pattern)):
        path = Path(value)
        try:
            artifact = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if artifact.get("schema") != SCHEMA:
            continue
        if artifact.get("manifest", {}).get("evidence_eligible") is not True:
            continue
        artifacts.append((path, artifact))
    return artifacts


def aggregate(args) -> None:
    parent, runtime, head = require_real_context()
    artifacts = load_artifacts(args.pattern)
    result = aggregate_result(
        artifacts, runtime=runtime, head=head, parent=parent,
        progress=lambda message: print(message, flush=True))
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    if args.out:
        atomic_json_exclusive(args.out, result)
    if result["problems"]:
        raise ProtocolRefused(
            "S3a aggregation held invalid inputs: " +
            "; ".join(result["problems"]))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--shard-index", type=int, required=True)
    run.add_argument("--smoke", action="store_true")
    run.add_argument("--progress-every", type=int, default=1)
    run.add_argument("--out", type=Path)
    agg = sub.add_parser("aggregate")
    agg.add_argument("--pattern", default="runs/logs/s3a-bury-pilot-v2_shard*.json")
    agg.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if getattr(args, "progress_every", 1) <= 0:
        raise ProtocolRefused("progress-every must be positive")
    if args.command == "run":
        run_shard(args)
    else:
        aggregate(args)


if __name__ == "__main__":
    try:
        main()
    except ProtocolRefused as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc

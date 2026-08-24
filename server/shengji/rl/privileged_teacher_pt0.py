"""Score-free mechanics for the privileged-teacher PT0 boundary.

PT0 is deliberately smaller than a learned teacher.  It converts exact
perfect-information endgame values into the same signed-level utility used by
whole-round evaluation, measures named baseline regret, and reduces a fixed
population of compatible hidden worlds to an actor-legal information-set
target.  It has no registry entry, model, training loop, gameplay hook, or
fleet authority.

The aggregation API intentionally has no ``true_world`` argument.  A true
hidden deal may be an evaluation label, but it may never select the public
target action.
"""

from __future__ import annotations

import hashlib
import json
import copy
import math
import time
from dataclasses import dataclass
from fractions import Fraction
from typing import Callable, Iterable, Mapping, Sequence


PT0_TARGET_SCHEMA = "privileged-teacher-pt0-information-set-target-v1"
PT0_RECEIPT_SCHEMA = "privileged-teacher-pt0-miniature-receipt-v1"
PT0_CHECKPOINT_SCHEMA = "privileged-teacher-pt0-prefix-checkpoint-v1"
PT0_BASELINE_POLICIES = (
    "heuristic", "smart", "mc-strong", "mc-s0-report-lcb")


class PrivilegedTeacherPT0Error(ValueError):
    """The proposed mechanics artifact is outside the PT0 contract."""


def _pt0_contract_metadata() -> dict[str, str]:
    """Fixed estimand metadata; these are not caller-selectable knobs."""
    return {
        "world_distribution": (
            "P(w|h): caller-supplied compatible worlds, sorted by world SHA-256"),
        "continuation": "pi_cont: existing ExactWorldSession partnership minimax",
        "legal_action_enumeration": "existing exhaustive_legal_actions",
        "acting_team_perspective": (
            "acting seat signed against banker-team parity"),
        "return_definition": "signed_level_utility at round_end",
        "terminal_horizon": "round_end",
    }


def canonical_json_bytes(value: object) -> bytes:
    """Return the closed canonical encoding used by PT0 target hashes."""
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True) + "\n").encode("ascii")


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PrivilegedTeacherPT0Error(
            f"{label} must be a nonnegative integer")
    return value


def signed_level_utility(
        attacker_points: int, *, banker_seat: int,
        perspective_seat: int) -> int:
    """Convert final attacker points to signed one-round level utility.

    This exactly matches ``Game.finish_round`` plus the evaluation convention
    that a successful 80-point attacker takeover is worth one level even
    though the raw ``(points - 80) // 40`` expression is zero at 80.
    Positive values mean the perspective seat's partnership won the round.
    """
    points = _positive_int(attacker_points, "attacker_points")
    for value, label in ((banker_seat, "banker_seat"),
                         (perspective_seat, "perspective_seat")):
        if isinstance(value, bool) or not isinstance(value, int) \
                or not 0 <= value < 4:
            raise PrivilegedTeacherPT0Error(
                f"{label} must be an integer seat in [0, 3]")

    perspective_is_attacker = perspective_seat % 2 != banker_seat % 2
    if points >= 80:
        attacker_won = True
        gain = max(1, (points - 80) // 40)
    else:
        attacker_won = False
        gain = 3 if points == 0 else (2 if points < 40 else 1)
    perspective_won = perspective_is_attacker == attacker_won
    return gain if perspective_won else -gain


def _action_key(cards: Sequence[str]) -> tuple[str, ...]:
    if (isinstance(cards, (str, bytes))
            or not isinstance(cards, Sequence) or not cards):
        raise PrivilegedTeacherPT0Error(
            "an action must be a nonempty card-code sequence")
    if any(type(card) is not str or not card for card in cards):
        raise PrivilegedTeacherPT0Error("action card codes must be strings")
    return tuple(sorted(cards))


@dataclass(frozen=True)
class WorldActionValues:
    """Exact values for every retained action in one compatible world."""

    world_sha256: str
    action_utilities: tuple[tuple[tuple[str, ...], int], ...]

    @classmethod
    def build(
            cls, world_sha256: str,
            action_utilities: Mapping[Sequence[str], int] | Iterable[
                tuple[Sequence[str], int]]) -> "WorldActionValues":
        if type(world_sha256) is not str or len(world_sha256) != 64 \
                or any(char not in "0123456789abcdef"
                       for char in world_sha256):
            raise PrivilegedTeacherPT0Error("invalid world SHA-256")
        source = (action_utilities.items()
                  if isinstance(action_utilities, Mapping)
                  else action_utilities)
        rows: list[tuple[tuple[str, ...], int]] = []
        for cards, utility in source:
            key = _action_key(cards)
            if isinstance(utility, bool) or not isinstance(utility, int) \
                    or utility == 0:
                raise PrivilegedTeacherPT0Error(
                    "signed action utility must be a nonzero integer")
            rows.append((key, utility))
        rows.sort(key=lambda row: (len(row[0]), row[0]))
        if not rows or len({cards for cards, _ in rows}) != len(rows):
            raise PrivilegedTeacherPT0Error(
                "world action population must be nonempty and unique")
        return cls(world_sha256=world_sha256,
                   action_utilities=tuple(rows))


@dataclass(frozen=True)
class ExactWorldEvaluation:
    """One complete forced-action evaluation inside a known hidden world."""

    values: WorldActionValues
    final_attacker_points: tuple[tuple[tuple[str, ...], int], ...]
    nodes: int
    cache_hits: int


@dataclass(frozen=True)
class BaselineEvaluation:
    """One frozen public-policy choice measured against a PT0 target."""

    policy: str
    seed: int
    selected_cards: tuple[str, ...]
    information_set_regret: Fraction


@dataclass(frozen=True)
class PT0MiniatureResult:
    """Pure in-memory result for one bounded compatible-world run.

    ``checkpoint`` is the latest canonical prefix receipt.  ``checkpoints``
    contains only checkpoints emitted during this call; callers may persist
    those bytes themselves, but PT0 never opens a path or writes a file.
    """

    status: str
    completed_units: int
    total_units: int
    target: dict[str, object] | None
    receipt: dict[str, object]
    checkpoint: bytes
    checkpoints: tuple[bytes, ...]


def exact_world_action_values(
        rnd: object, *, world_sha256: str, perspective_seat: int,
        max_hand_cards: int = 3,
        max_nodes: int = 250_000) -> ExactWorldEvaluation:
    """Force and solve every legal root action in one complete endgame.

    One exact transposition table is shared across all root actions in this
    world.  It is never shared across worlds.  This calls the same bounded
    solver used by the already-reviewed S3b mechanics gate; PT0 only adds the
    signed-level conversion and closed receipt.
    """
    # Imports remain local so importing this score-free data contract cannot
    # activate an engine or policy path.
    if (isinstance(max_hand_cards, bool)
            or not isinstance(max_hand_cards, int)
            or max_hand_cards < 1):
        raise PrivilegedTeacherPT0Error(
            "max_hand_cards must be a positive integer")
    if (isinstance(max_nodes, bool) or not isinstance(max_nodes, int)
            or max_nodes < 1):
        raise PrivilegedTeacherPT0Error(
            "max_nodes must be a positive integer")
    from shengji.ai.endgame import (  # pylint: disable=import-outside-toplevel
        ExactWorldSession,
        _clone_for_play,
        exhaustive_legal_actions,
    )
    from shengji.engine.round import Round  # pylint: disable=import-outside-toplevel

    if type(rnd) is not Round:
        raise PrivilegedTeacherPT0Error("exact evaluator requires exact Round")
    if rnd.phase != "play" or rnd.turn is None or rnd.banker is None:
        raise PrivilegedTeacherPT0Error(
            "exact evaluator requires an active play decision")
    if perspective_seat != rnd.turn:
        raise PrivilegedTeacherPT0Error(
            "PT0 action values use the acting seat perspective")
    actions = exhaustive_legal_actions(
        rnd, rnd.turn, max_hand_cards=max_hand_cards)
    session = ExactWorldSession(
        rnd, max_hand_cards=max_hand_cards, max_nodes=max_nodes)
    points_rows: list[tuple[tuple[str, ...], int]] = []
    utility_rows: list[tuple[tuple[str, ...], int]] = []
    for action in actions:
        child = _clone_for_play(rnd)
        child.play(rnd.turn, list(action))
        points = session.solver.value(child)
        cards = _action_key(action)
        points_rows.append((cards, points))
        utility_rows.append((cards, signed_level_utility(
            points, banker_seat=rnd.banker,
            perspective_seat=perspective_seat)))
    values = WorldActionValues.build(world_sha256, utility_rows)
    ordered_points = tuple(sorted(
        points_rows, key=lambda row: (len(row[0]), row[0])))
    if tuple(cards for cards, _ in ordered_points) != tuple(
            cards for cards, _ in values.action_utilities):
        raise PrivilegedTeacherPT0Error(
            "exact point and utility action populations disagree")
    return ExactWorldEvaluation(
        values=values,
        final_attacker_points=ordered_points,
        nodes=session.nodes,
        cache_hits=session.cache_hits,
    )


def _evaluation_payload(evaluation: ExactWorldEvaluation) -> dict[str, object]:
    """Encode one exact result without retaining a Round or hidden state."""
    return {
        "world_sha256": evaluation.values.world_sha256,
        "action_utilities": [
            [list(cards), utility]
            for cards, utility in evaluation.values.action_utilities
        ],
        "final_attacker_points": [
            [list(cards), points]
            for cards, points in evaluation.final_attacker_points
        ],
        "nodes": evaluation.nodes,
        "cache_hits": evaluation.cache_hits,
    }


def _evaluation_from_payload(payload: object) -> ExactWorldEvaluation:
    """Decode and validate a checkpointed exact result."""
    if not isinstance(payload, Mapping):
        raise PrivilegedTeacherPT0Error("PT0 checkpoint evaluation drift")
    if set(payload) != {"world_sha256", "action_utilities",
                        "final_attacker_points", "nodes", "cache_hits"}:
        raise PrivilegedTeacherPT0Error("PT0 checkpoint evaluation drift")
    world_sha256 = payload.get("world_sha256")
    action_rows = payload.get("action_utilities")
    point_rows = payload.get("final_attacker_points")
    if (type(world_sha256) is not str
            or not isinstance(action_rows, list)
            or not isinstance(point_rows, list)):
        raise PrivilegedTeacherPT0Error("PT0 checkpoint evaluation drift")
    try:
        values = WorldActionValues.build(world_sha256, action_rows)
        final_points = []
        for row in point_rows:
            if not isinstance(row, list) or len(row) != 2:
                raise PrivilegedTeacherPT0Error(
                    "PT0 checkpoint point rows drift")
            cards, points = row
            if (isinstance(points, bool) or not isinstance(points, int)
                    or points < 0):
                raise PrivilegedTeacherPT0Error(
                    "PT0 checkpoint point rows drift")
            final_points.append((_action_key(cards), points))
        final_points.sort(key=lambda row: (len(row[0]), row[0]))
        if tuple(cards for cards, _ in final_points) != tuple(
                cards for cards, _ in values.action_utilities):
            raise PrivilegedTeacherPT0Error(
                "PT0 checkpoint action populations disagree")
        nodes = payload["nodes"]
        cache_hits = payload["cache_hits"]
    except (KeyError, TypeError, ValueError) as exc:
        raise PrivilegedTeacherPT0Error(
            "PT0 checkpoint evaluation drift") from exc
    if (isinstance(nodes, bool) or not isinstance(nodes, int) or nodes < 0
            or isinstance(cache_hits, bool)
            or not isinstance(cache_hits, int) or cache_hits < 0):
        raise PrivilegedTeacherPT0Error("PT0 checkpoint work drift")
    return ExactWorldEvaluation(
        values=values,
        final_attacker_points=tuple(final_points),
        nodes=nodes,
        cache_hits=cache_hits,
    )


def _pt0_authority() -> dict[str, bool]:
    return {
        "gameplay_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
        "training_authorized": False,
    }


def _run_progress(
        completed: int, total: int, elapsed: float,
        deadline_headroom: float | None) -> dict[str, object]:
    return {
        "completed_units": completed,
        "total_units": total,
        "percent_basis_points": (completed * 10_000) // total,
        "elapsed_seconds": elapsed,
        "deadline_headroom_seconds": deadline_headroom,
    }


def _checkpoint_bytes(
        *, public_state_sha256: str, perspective_seat: int,
        max_hand_cards: int, max_nodes: int, world_sha256s: Sequence[str],
        evaluations: Sequence[ExactWorldEvaluation], nodes: int,
        cache_hits: int, elapsed: float,
        deadline_headroom: float | None, checkpoint_monotonic: float) -> bytes:
    payload = {
        "schema": PT0_CHECKPOINT_SCHEMA,
        "contract": _pt0_contract_metadata(),
        "public_state_sha256": public_state_sha256,
        "perspective_seat": perspective_seat,
        "max_hand_cards": max_hand_cards,
        "max_nodes": max_nodes,
        "world_sha256s": list(world_sha256s),
        "completed_evaluations": [
            _evaluation_payload(evaluation) for evaluation in evaluations
        ],
        "work": {"nodes": nodes, "cache_hits": cache_hits},
        "progress": _run_progress(
            len(evaluations), len(world_sha256s), elapsed,
            deadline_headroom),
        "checkpoint_monotonic": checkpoint_monotonic,
        "authority": _pt0_authority(),
    }
    return canonical_json_bytes(payload)


def _load_checkpoint(
        checkpoint: bytes, *, public_state_sha256: str, perspective_seat: int,
        max_hand_cards: int, max_nodes: int,
        world_sha256s: Sequence[str]) -> tuple[list[ExactWorldEvaluation], int,
                                                int, float, float | None, float]:
    if not isinstance(checkpoint, bytes):
        raise PrivilegedTeacherPT0Error("PT0 checkpoint must be canonical bytes")
    try:
        payload = json.loads(checkpoint.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PrivilegedTeacherPT0Error("PT0 checkpoint is not JSON") from exc
    if canonical_json_bytes(payload) != checkpoint:
        raise PrivilegedTeacherPT0Error("PT0 checkpoint is not canonical")
    if not isinstance(payload, Mapping) \
            or payload.get("schema") != PT0_CHECKPOINT_SCHEMA:
        raise PrivilegedTeacherPT0Error("PT0 checkpoint schema drift")
    if set(payload) != {
            "schema", "contract", "public_state_sha256", "perspective_seat",
            "max_hand_cards", "max_nodes", "world_sha256s",
            "completed_evaluations", "work", "progress",
            "checkpoint_monotonic", "authority"}:
        raise PrivilegedTeacherPT0Error("PT0 checkpoint schema drift")
    if payload.get("contract") != _pt0_contract_metadata():
        raise PrivilegedTeacherPT0Error("PT0 checkpoint contract drift")
    if payload.get("public_state_sha256") != public_state_sha256 \
            or payload.get("perspective_seat") != perspective_seat \
            or payload.get("max_hand_cards") != max_hand_cards \
            or payload.get("max_nodes") != max_nodes \
            or payload.get("world_sha256s") != list(world_sha256s):
        raise PrivilegedTeacherPT0Error("PT0 checkpoint run identity drift")
    if payload.get("authority") != _pt0_authority():
        raise PrivilegedTeacherPT0Error("PT0 checkpoint authority drift")
    evaluations_payload = payload.get("completed_evaluations")
    if not isinstance(evaluations_payload, list):
        raise PrivilegedTeacherPT0Error("PT0 checkpoint prefix drift")
    if len(evaluations_payload) > len(world_sha256s):
        raise PrivilegedTeacherPT0Error("PT0 checkpoint prefix exceeds total")
    evaluations = [_evaluation_from_payload(item)
                   for item in evaluations_payload]
    prefix = list(world_sha256s[:len(evaluations)])
    if [evaluation.values.world_sha256 for evaluation in evaluations] != prefix:
        raise PrivilegedTeacherPT0Error(
            "PT0 checkpoint is not an exact world prefix")
    work = payload.get("work")
    if not isinstance(work, Mapping) or set(work) != {"nodes", "cache_hits"}:
        raise PrivilegedTeacherPT0Error("PT0 checkpoint work drift")
    nodes, cache_hits = work.get("nodes"), work.get("cache_hits")
    if (isinstance(nodes, bool) or not isinstance(nodes, int) or nodes < 0
            or isinstance(cache_hits, bool)
            or not isinstance(cache_hits, int) or cache_hits < 0
            or nodes != sum(item.nodes for item in evaluations)
            or cache_hits != sum(item.cache_hits for item in evaluations)):
        raise PrivilegedTeacherPT0Error("PT0 checkpoint work drift")
    progress = payload.get("progress")
    if (not isinstance(progress, Mapping)
            or set(progress) != {"completed_units", "total_units",
                                  "percent_basis_points", "elapsed_seconds",
                                  "deadline_headroom_seconds"}) \
            or progress.get("completed_units") != len(evaluations) \
            or progress.get("total_units") != len(world_sha256s) \
            or progress.get("percent_basis_points") != (
                len(evaluations) * 10_000) // len(world_sha256s):
        raise PrivilegedTeacherPT0Error("PT0 checkpoint progress drift")
    elapsed = progress.get("elapsed_seconds")
    headroom = progress.get("deadline_headroom_seconds")
    checkpoint_monotonic = payload.get("checkpoint_monotonic")
    if (isinstance(elapsed, bool) or not isinstance(elapsed, (int, float))
            or not math.isfinite(elapsed) or elapsed < 0
            or (headroom is not None and (
                isinstance(headroom, bool)
                or not isinstance(headroom, (int, float))
                or not math.isfinite(headroom)))
            or isinstance(checkpoint_monotonic, bool)
            or not isinstance(checkpoint_monotonic, (int, float))
            or not math.isfinite(checkpoint_monotonic)):
        raise PrivilegedTeacherPT0Error("PT0 checkpoint timing drift")
    return (evaluations, nodes, cache_hits, float(elapsed),
            None if headroom is None else float(headroom),
            float(checkpoint_monotonic))


def run_pt0_miniature(
        public_state_sha256: str,
        worlds: Sequence[tuple[str, object]], *, perspective_seat: int,
        max_hand_cards: int = 3, max_nodes: int = 250_000,
        deadline: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        checkpoint: bytes | None = None,
        checkpoint_sink: Callable[[bytes], object] | None = None,
) -> PT0MiniatureResult:
    """Run exact PT0 worlds with resumable pure progress receipts.

    ``worlds`` is sorted by its public world hash.  A checkpoint can resume
    only the exact prefix of that same sorted population and configuration.
    The deadline is an absolute value from the supplied monotonic clock; work
    is bounded at world boundaries, so an in-flight exact world finishes before
    a clean ``DEADLINE`` result is returned.
    """
    if (type(public_state_sha256) is not str
            or len(public_state_sha256) != 64
            or any(char not in "0123456789abcdef"
                   for char in public_state_sha256)):
        raise PrivilegedTeacherPT0Error("invalid public-state SHA-256")
    if (isinstance(perspective_seat, bool)
            or not isinstance(perspective_seat, int)
            or not 0 <= perspective_seat < 4):
        raise PrivilegedTeacherPT0Error(
            "perspective_seat must be an integer seat in [0, 3]")
    if (isinstance(worlds, (str, bytes))
            or not isinstance(worlds, Sequence) or len(worlds) < 2):
        raise PrivilegedTeacherPT0Error(
            "miniature run requires at least two compatible worlds")
    if not callable(monotonic):
        raise PrivilegedTeacherPT0Error("monotonic clock must be callable")
    if checkpoint_sink is not None and not callable(checkpoint_sink):
        raise PrivilegedTeacherPT0Error("checkpoint sink must be callable")
    if deadline is not None and (
            isinstance(deadline, bool) or not isinstance(deadline, (int, float))
            or not math.isfinite(deadline)):
        raise PrivilegedTeacherPT0Error("deadline must be finite monotonic time")
    if (isinstance(max_hand_cards, bool)
            or not isinstance(max_hand_cards, int) or max_hand_cards < 1
            or isinstance(max_nodes, bool) or not isinstance(max_nodes, int)
            or max_nodes < 1):
        raise PrivilegedTeacherPT0Error("miniature run bounds are invalid")
    ordered_worlds: list[tuple[str, object]] = []
    for item in worlds:
        if (not isinstance(item, tuple) or len(item) != 2
                or type(item[0]) is not str
                or len(item[0]) != 64
                or any(char not in "0123456789abcdef" for char in item[0])):
            raise PrivilegedTeacherPT0Error("miniature world identity drift")
        ordered_worlds.append(item)
    ordered_worlds.sort(key=lambda item: item[0])
    world_sha256s = [item[0] for item in ordered_worlds]
    if len(set(world_sha256s)) != len(world_sha256s):
        raise PrivilegedTeacherPT0Error("duplicate compatible world")

    now = float(monotonic())
    if not math.isfinite(now):
        raise PrivilegedTeacherPT0Error("monotonic clock returned non-finite time")
    if checkpoint is None:
        evaluations: list[ExactWorldEvaluation] = []
        nodes = cache_hits = 0
        elapsed_base = 0.0
        checkpoint_clock = now
        headroom = None if deadline is None else deadline - now
    else:
        (evaluations, nodes, cache_hits, elapsed_base, headroom,
         checkpoint_clock) = _load_checkpoint(
             checkpoint, public_state_sha256=public_state_sha256,
             perspective_seat=perspective_seat, max_hand_cards=max_hand_cards,
             max_nodes=max_nodes, world_sha256s=world_sha256s)
    emitted: list[bytes] = []

    def timing() -> tuple[float, float | None, float]:
        current = float(monotonic())
        if not math.isfinite(current):
            raise PrivilegedTeacherPT0Error(
                "monotonic clock returned non-finite time")
        elapsed = elapsed_base + max(0.0, current - checkpoint_clock)
        remaining = None if deadline is None else deadline - current
        return elapsed, remaining, current

    while len(evaluations) < len(ordered_worlds):
        elapsed, remaining, current = timing()
        if remaining is not None and remaining <= 0:
            break
        world_sha256, rnd = ordered_worlds[len(evaluations)]
        evaluation = exact_world_action_values(
            rnd, world_sha256=world_sha256, perspective_seat=perspective_seat,
            max_hand_cards=max_hand_cards, max_nodes=max_nodes)
        if evaluations and tuple(
                cards for cards, _ in evaluation.values.action_utilities) != \
                tuple(cards for cards, _ in
                      evaluations[0].values.action_utilities):
            raise PrivilegedTeacherPT0Error(
                "compatible worlds disagree on the public legal-action set")
        evaluations.append(evaluation)
        nodes += evaluation.nodes
        cache_hits += evaluation.cache_hits
        elapsed, remaining, current = timing()
        emitted_checkpoint = _checkpoint_bytes(
            public_state_sha256=public_state_sha256,
            perspective_seat=perspective_seat, max_hand_cards=max_hand_cards,
            max_nodes=max_nodes, world_sha256s=world_sha256s,
            evaluations=evaluations, nodes=nodes, cache_hits=cache_hits,
            elapsed=elapsed, deadline_headroom=remaining,
            checkpoint_monotonic=current)
        emitted.append(emitted_checkpoint)
        if checkpoint_sink is not None:
            checkpoint_sink(emitted_checkpoint)
        if remaining is not None and remaining <= 0:
            break

    elapsed, remaining, current = timing()
    latest_checkpoint = emitted[-1] if emitted else _checkpoint_bytes(
        public_state_sha256=public_state_sha256,
        perspective_seat=perspective_seat, max_hand_cards=max_hand_cards,
        max_nodes=max_nodes, world_sha256s=world_sha256s,
        evaluations=evaluations, nodes=nodes, cache_hits=cache_hits,
        elapsed=elapsed, deadline_headroom=remaining,
        checkpoint_monotonic=current)
    complete = len(evaluations) == len(ordered_worlds)
    target = (information_set_target(
        public_state_sha256, [evaluation.values for evaluation in evaluations])
              if complete else None)
    receipt = {
        "schema": PT0_RECEIPT_SCHEMA,
        "contract": _pt0_contract_metadata(),
        "perspective_seat": perspective_seat,
        "status": "COMPLETE" if complete else "DEADLINE",
        "progress": _run_progress(
            len(evaluations), len(ordered_worlds), elapsed, remaining),
        "work": {"nodes": nodes, "cache_hits": cache_hits},
        "target_sha256": (hashlib.sha256(canonical_json_bytes(target)).hexdigest()
                           if target is not None else None),
        "authority": _pt0_authority(),
    }
    canonical_json_bytes(receipt)
    return PT0MiniatureResult(
        status=receipt["status"], completed_units=len(evaluations),
        total_units=len(ordered_worlds), target=target, receipt=receipt,
        checkpoint=latest_checkpoint, checkpoints=tuple(emitted),
    )


def evaluate_named_baseline(
        rnd: object, target: Mapping[str, object], *, policy: str,
        seed: int) -> BaselineEvaluation:
    """Run one named existing policy and measure its exact PT0 regret."""
    from shengji.ai.registry import make_bot  # pylint: disable=import-outside-toplevel
    from shengji.engine.round import Round  # pylint: disable=import-outside-toplevel

    if policy not in PT0_BASELINE_POLICIES:
        raise PrivilegedTeacherPT0Error("PT0 baseline policy is not frozen")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise PrivilegedTeacherPT0Error(
            "PT0 baseline seed must be a nonnegative integer")
    if type(rnd) is not Round or rnd.phase != "play" or rnd.turn is None:
        raise PrivilegedTeacherPT0Error(
            "PT0 baseline requires an active exact Round")
    try:
        bot = make_bot(policy, seed=seed)
        selected = _action_key(bot.decide_play(rnd, rnd.turn))
    except PrivilegedTeacherPT0Error:
        raise
    except Exception as exc:  # policy refusal is not a successful baseline
        raise PrivilegedTeacherPT0Error(
            f"PT0 baseline {policy!r} could not evaluate this exact state") \
            from exc
    return BaselineEvaluation(
        policy=policy,
        seed=seed,
        selected_cards=selected,
        information_set_regret=baseline_regret(target, selected),
    )


def rotate_round_seats(rnd: object, offset: int) -> object:
    """Return an exact seat-rotated Round for paired PT0 mechanics checks."""
    from shengji.engine.round import (  # pylint: disable=import-outside-toplevel
        Round, Trick, TrickPlay)

    if type(rnd) is not Round:
        raise PrivilegedTeacherPT0Error("seat rotation requires exact Round")
    if isinstance(offset, bool) or not isinstance(offset, int) \
            or not 0 <= offset < 4:
        raise PrivilegedTeacherPT0Error(
            "seat rotation offset must be an integer in [0, 3]")

    def seat(value: int | None) -> int | None:
        return None if value is None else (value + offset) % 4

    def trick(value: object | None) -> object | None:
        if value is None:
            return None
        return Trick(
            leader=seat(value.leader),
            plays=[TrickPlay(seat(play.seat), list(play.cards))
                   for play in value.plays],
            winner=seat(value.winner),
            points=value.points,
        )

    clone = copy.copy(rnd)
    clone.deck = list(rnd.deck)
    clone.hands = [[] for _ in range(4)]
    for old_seat, hand in enumerate(rnd.hands):
        clone.hands[seat(old_seat)] = list(hand)
    clone.kitty = list(rnd.kitty)
    clone.buried = list(rnd.buried)
    clone.banker = seat(rnd.banker)
    clone.turn = seat(rnd.turn)
    clone.passed = {seat(value) for value in rnd.passed}
    clone.declaration = (None if rnd.declaration is None else {
        **rnd.declaration,
        "seat": seat(rnd.declaration["seat"]),
        "cards": list(rnd.declaration.get("cards", [])),
    })
    clone.history = [trick(value) for value in rnd.history]
    clone.trick = trick(rnd.trick)
    clone.last_trick = (clone.history[-1] if rnd.last_trick is not None
                        and rnd.history and rnd.last_trick is rnd.history[-1]
                        else trick(rnd.last_trick))
    clone.last_trick_winner = seat(rnd.last_trick_winner)
    clone.message = None
    clone.__dict__.pop("_trusted_rollout", None)
    clone.__dict__.pop("_determinized_world", None)
    return clone


def _fraction(value: Fraction) -> dict[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def information_set_target(
        public_state_sha256: str,
        worlds: Sequence[WorldActionValues]) -> dict[str, object]:
    """Average exact action values over one fixed compatible-world set.

    The result is invariant to input order and contains only the hash of the
    sorted world population, never a true-world identity.  Ties count every
    maximizing action as best for that world; the per-action probability is
    therefore descriptive and need not sum to one.
    """
    if type(public_state_sha256) is not str \
            or len(public_state_sha256) != 64 \
            or any(char not in "0123456789abcdef"
                   for char in public_state_sha256):
        raise PrivilegedTeacherPT0Error("invalid public-state SHA-256")
    if (isinstance(worlds, (str, bytes))
            or not isinstance(worlds, Sequence) or len(worlds) < 2):
        raise PrivilegedTeacherPT0Error(
            "information-set aggregation requires at least two worlds")
    if any(type(world) is not WorldActionValues for world in worlds):
        raise PrivilegedTeacherPT0Error(
            "compatible worlds must be exact WorldActionValues")
    ordered = sorted(worlds, key=lambda world: world.world_sha256)
    if len({world.world_sha256 for world in ordered}) != len(ordered):
        raise PrivilegedTeacherPT0Error("duplicate compatible world")
    action_population = tuple(cards for cards, _ in ordered[0].action_utilities)
    for world in ordered:
        if tuple(cards for cards, _ in world.action_utilities) \
                != action_population:
            raise PrivilegedTeacherPT0Error(
                "compatible worlds disagree on the public legal-action set")

    rows = []
    for index, cards in enumerate(action_population):
        values = [world.action_utilities[index][1] for world in ordered]
        mean = Fraction(sum(values), len(values))
        variance = sum((Fraction(value) - mean) ** 2
                       for value in values) / len(values)
        best_count = sum(
            value == max(item[1] for item in world.action_utilities)
            for value, world in zip(values, ordered, strict=True))
        rows.append({
            "cards": list(cards),
            "mean_signed_level_utility": _fraction(mean),
            "signed_level_variance": _fraction(variance),
            "best_world_count": best_count,
            "best_world_probability": _fraction(
                Fraction(best_count, len(ordered))),
        })

    best_mean = max(
        Fraction(row["mean_signed_level_utility"]["numerator"],
                 row["mean_signed_level_utility"]["denominator"])
        for row in rows)
    selected = [row["cards"] for row in rows
                if Fraction(row["mean_signed_level_utility"]["numerator"],
                            row["mean_signed_level_utility"]["denominator"])
                == best_mean]
    world_population_bytes = canonical_json_bytes(
        [world.world_sha256 for world in ordered])
    target = {
        "schema": PT0_TARGET_SCHEMA,
        "public_state_sha256": public_state_sha256,
        "world_population_sha256": hashlib.sha256(
            world_population_bytes).hexdigest(),
        "world_count": len(ordered),
        "actions": rows,
        "information_set_argmax": selected,
        "true_world_selects_target": False,
        "gameplay_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }
    # Exercise the canonical encoder here so an unencodable value cannot leave
    # this boundary and fail only when a later artifact is sealed.
    canonical_json_bytes(target)
    return target


def baseline_regret(
        target: Mapping[str, object], selected_cards: Sequence[str]) \
        -> Fraction:
    """Return exact information-set regret for one named baseline action."""
    if target.get("schema") != PT0_TARGET_SCHEMA:
        raise PrivilegedTeacherPT0Error("PT0 target schema drift")
    for flag in ("true_world_selects_target", "gameplay_authorized",
                 "strength_claim_authorized", "deployment_authorized"):
        if target.get(flag) is not False:
            raise PrivilegedTeacherPT0Error("PT0 target authority drift")
    rows = target.get("actions")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise PrivilegedTeacherPT0Error("PT0 target action population drift")
    selected = _action_key(selected_cards)
    utilities: dict[tuple[str, ...], Fraction] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise PrivilegedTeacherPT0Error("PT0 target action row drift")
        cards = _action_key(row.get("cards", []))
        value = row.get("mean_signed_level_utility")
        if not isinstance(value, Mapping):
            raise PrivilegedTeacherPT0Error("PT0 target utility drift")
        try:
            parsed = Fraction(value["numerator"], value["denominator"])
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            raise PrivilegedTeacherPT0Error(
                "PT0 target utility drift") from exc
        if cards in utilities:
            raise PrivilegedTeacherPT0Error(
                "PT0 target action population has duplicate action")
        utilities[cards] = parsed
    if not utilities:
        raise PrivilegedTeacherPT0Error("PT0 target action population is empty")
    if selected not in utilities:
        raise PrivilegedTeacherPT0Error(
            "baseline selected an action outside the retained ballot")
    return max(utilities.values()) - utilities[selected]

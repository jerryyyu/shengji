"""Adaptive full-information Sol planner for the open-DEV PT roots.

The external model never owns or mutates a :class:`Round`.  It talks to this
module through a narrow local controller, while this module generates the
ballot, executes exact-world continuations, validates the committed play and
advances production-policy opponents.  Raw state and model text are private
teacher evidence; the public outcome contains only aggregate telemetry and
cryptographic bindings.
"""

from __future__ import annotations

import base64
import copy
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import secrets
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable, Mapping, Protocol

from ..ai.heuristic import HeuristicBot
from ..ai.smart import SmartBot
from ..engine.cards import total_points
from ..engine.combos import decompose
from ..engine.round import Round
from . import privileged_teacher_c0 as c0
from . import privileged_teacher_full_ab as full
from .privileged_teacher_pt0 import canonical_json_bytes, signed_level_utility


MODEL = "gpt-5.6-sol"
REASONING_EFFORT = "high"
SESSION_SCHEMA = "privileged-teacher-sol0-session-v1"
OUTCOME_SCHEMA = "privileged-teacher-sol0-outcome-v1"
PRIVATE_TRANSCRIPT_SCHEMA = "privileged-teacher-sol0-private-transcript-v1"
PRIVATE_EVIDENCE_SCHEMA = "privileged-teacher-sol0-private-evidence-v1"
TOOL_RESPONSE_SCHEMA = "privileged-teacher-sol0-tool-response-v1"
FINAL_RESPONSE_SCHEMA = "privileged-teacher-sol0-final-response-v1"

CONTINUATIONS = (
    "heuristic-all",
    "smart-all",
    "team-smart",
    "opponent-smart",
    "exact-endgame-smart",
)
PLANNER_PROMPT_TEMPLATE = """You are PT-Sol0, an offline full-information Shengji teacher.
You control both seats of one treatment partnership for one complete round.
Your only goal is to maximize final signed-level utility for that partnership.

Use only this game tool; do not inspect or modify other files:
  {tool} observe
  {tool} rollout --decision SHA --candidates 0,1 --continuations smart-all,team-smart
  {tool} play --decision SHA --candidate 0 --confidence low

At every decision, call observe first. You see all hands and the burial because
this is a privileged teacher diagnostic. Candidate zero is the production
prior and is always a valid fallback. You may request any useful subset of
candidate/continuation evaluations, inspect the results, and adaptively request
more. Never repeat an identical candidate/continuation pair merely to obtain
another sample: the exact world and named continuation are deterministic.
For each rollout command, candidate count times continuation count must be at
most 16. A tool error changes no game state: correct the request, observe again
if needed, and continue.
Use at most two rollout commands per decision; spend the second only when the
first result leaves a material signed-level choice unresolved. Then play.
Consider multi-trick control, partnership entries, point timing, trump
exhaustion, banker defense, attacker thresholds, and the risk that a conclusion
depends on one continuation assumption. Commit exactly one listed candidate
with play, then continue until the tool reports round_end.

Do not stop early. Do not invent cards, values, or tool results. The final
legal play returns a one-time completion_token. After round_end, return the
required JSON object with status complete and that exact completion_token.
The final response must contain only this JSON shape, with TOKEN replaced by
the engine-returned value:
{{"schema":"privileged-teacher-sol0-final-response-v1","status":"complete","completion_token":"TOKEN"}}
"""
MAX_NEW_EVALUATIONS_PER_CALL = 16
MAX_ROLLOUT_CALLS_PER_DECISION = 2
MAX_EVALUATIONS_PER_DECISION = 32
MAX_EVALUATIONS_PER_ROUND = 1024
MAX_SESSION_WALL_SECONDS = 1200
MAX_PRIVATE_EVENT_BYTES = 1 << 20
MAX_PRIVATE_PROCESS_BYTES = 16 << 20
CONFIDENCE_LEVELS = ("low", "medium", "high")

PUBLIC_TELEMETRY_FIELDS = (
    "treatment_decisions",
    "forced_decisions",
    "contested_decisions",
    "observe_calls",
    "rollout_calls",
    "unique_rollouts",
    "cached_rollouts",
    "candidate_zero_selections",
    "selected_differs_from_candidate_zero",
    "selected_outside_production_ballot",
    "decisions_without_rollout",
    "rejected_tool_calls",
)


class PrivilegedTeacherSol0Error(ValueError):
    """The planner boundary, work receipt, or private/public split drifted."""


class PrivilegedTeacherSol0RequestError(PrivilegedTeacherSol0Error):
    """A recoverable model-authored request was refused without state change."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


PLANNER_PROMPT_TEMPLATE_SHA256 = _sha_bytes(
    PLANNER_PROMPT_TEMPLATE.encode("utf-8"))


def _sha(payload: object) -> str:
    return _sha_bytes(canonical_json_bytes(payload))


def _strict_int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PrivilegedTeacherSol0Error(f"{label} drift")
    return value


def _strict_token(value: object, allowed: tuple[str, ...], label: str) -> str:
    if type(value) is not str or value not in allowed:
        raise PrivilegedTeacherSol0Error(f"{label} drift")
    return value


def _private_event_size(payload: Mapping[str, object]) -> None:
    if len(canonical_json_bytes(dict(payload))) > MAX_PRIVATE_EVENT_BYTES:
        raise PrivilegedTeacherSol0Error("private planner event too large")


def _publish_private(path: Path, raw: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise PrivilegedTeacherSol0Error("private transcript slot occupied")
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    except BaseException:
        raise


def _private_evidence_bytes(
        session: "Sol0GameSession", *, model_stdout: bytes,
        final_raw: bytes, process_returncode: int | None,
        process_error: str | None) -> bytes:
    if (len(model_stdout) > MAX_PRIVATE_PROCESS_BYTES
            or len(final_raw) > MAX_PRIVATE_PROCESS_BYTES):
        raise PrivilegedTeacherSol0Error("private model output too large")
    transcript_raw = session.private_transcript_bytes()
    transcript = json.loads(transcript_raw.decode("ascii"))
    body = {
        "schema": PRIVATE_EVIDENCE_SCHEMA,
        "transcript": transcript,
        "model_stdout_base64": base64.b64encode(model_stdout).decode("ascii"),
        "model_final_base64": base64.b64encode(final_raw).decode("ascii"),
        "process_returncode": process_returncode,
        "process_error": process_error,
    }
    return canonical_json_bytes({**body, "evidence_sha256": _sha(body)})


@dataclass(frozen=True)
class Sol0PlannerConfig:
    model: str = MODEL
    reasoning_effort: str = REASONING_EFFORT
    max_new_evaluations_per_call: int = MAX_NEW_EVALUATIONS_PER_CALL
    max_evaluations_per_decision: int = MAX_EVALUATIONS_PER_DECISION
    max_evaluations_per_round: int = MAX_EVALUATIONS_PER_ROUND
    max_session_wall_seconds: int = MAX_SESSION_WALL_SECONDS

    def __post_init__(self) -> None:
        if self.model != MODEL or self.reasoning_effort != REASONING_EFFORT:
            raise PrivilegedTeacherSol0Error("planner model identity drift")
        if (self.max_new_evaluations_per_call !=
                MAX_NEW_EVALUATIONS_PER_CALL
                or self.max_evaluations_per_decision !=
                MAX_EVALUATIONS_PER_DECISION
                or self.max_evaluations_per_round !=
                MAX_EVALUATIONS_PER_ROUND
                or self.max_session_wall_seconds !=
                MAX_SESSION_WALL_SECONDS):
            raise PrivilegedTeacherSol0Error("planner budget drift")

    def payload(self) -> dict[str, object]:
        return {
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "continuations": list(CONTINUATIONS),
            "max_new_evaluations_per_call": (
                self.max_new_evaluations_per_call),
            "max_rollout_calls_per_decision":
                MAX_ROLLOUT_CALLS_PER_DECISION,
            "max_evaluations_per_decision": (
                self.max_evaluations_per_decision),
            "max_evaluations_per_round": self.max_evaluations_per_round,
            "max_session_wall_seconds": self.max_session_wall_seconds,
        }


@dataclass(frozen=True)
class Sol0Outcome:
    attacker_points: int
    signed_level_utility: int
    decision_count: int
    telemetry: Mapping[str, int]
    continuation_counts: Mapping[str, int]
    confidence_counts: Mapping[str, int]
    opponent_work: Mapping[str, int]
    transcript_sha256: str
    model_output_sha256: str
    model_exit_code: int
    model_wall_milliseconds: int

    def payload(self) -> dict[str, object]:
        return {
            "schema": OUTCOME_SCHEMA,
            "attacker_points": self.attacker_points,
            "signed_level_utility": self.signed_level_utility,
            "decision_count": self.decision_count,
            "telemetry": dict(self.telemetry),
            "continuation_counts": dict(self.continuation_counts),
            "confidence_counts": dict(self.confidence_counts),
            "opponent_work": dict(self.opponent_work),
            "transcript_sha256": self.transcript_sha256,
            "model_output_sha256": self.model_output_sha256,
            "model_exit_code": self.model_exit_code,
            "model_wall_milliseconds": self.model_wall_milliseconds,
        }


class _SeatContinuation:
    """Choose a deterministic public-style continuation by seat team."""

    def __init__(self, treatment_team: int, *, treatment_smart: bool,
                 opponents_smart: bool):
        self._treatment_team = treatment_team
        self._bots = [
            (SmartBot() if ((seat % 2 == treatment_team and treatment_smart)
                            or (seat % 2 != treatment_team
                                and opponents_smart))
             else HeuristicBot())
            for seat in range(4)
        ]

    def decide_play(self, rnd: Round, seat: int) -> list[str]:
        return self._bots[seat].decide_play(rnd, seat)


def _continuation(name: str, treatment_team: int) -> tuple[object, bool]:
    _strict_token(name, CONTINUATIONS, "continuation")
    if name == "heuristic-all":
        return HeuristicBot(), False
    if name == "smart-all":
        return SmartBot(), False
    if name == "team-smart":
        return _SeatContinuation(
            treatment_team, treatment_smart=True,
            opponents_smart=False), False
    if name == "opponent-smart":
        return _SeatContinuation(
            treatment_team, treatment_smart=False,
            opponents_smart=True), False
    return SmartBot(), True


def _trick_payload(trick: object) -> dict[str, object] | None:
    if trick is None:
        return None
    plays = getattr(trick, "plays", None)
    if type(plays) is not list:
        raise PrivilegedTeacherSol0Error("trick payload drift")
    return {
        "leader": trick.leader,
        "plays": [
            {"seat": play.seat, "cards": list(play.cards)} for play in plays
        ],
        "winner": trick.winner,
        "points": trick.points,
    }


def _candidate_payload(rnd: Round, cards: list[str], index: int,
                       production_ballot: set[tuple[str, ...]]) \
        -> dict[str, object]:
    if rnd.ordering is None:
        raise PrivilegedTeacherSol0Error("candidate ordering absent")
    decomposition = decompose(cards, rnd.ordering)
    return {
        "index": index,
        "cards": list(cards),
        "card_count": len(cards),
        "points": total_points(cards),
        "effective_suit": rnd.ordering.eff_suit(cards[0]),
        "shape": [list(decomposition.shape()[0]), decomposition.shape()[1]],
        "components": [
            {
                "kind": component.kind,
                "cards": list(component.cards),
                "top_level": component.top,
                "pair_length": component.pair_len,
            }
            for component in decomposition.components
        ],
        "is_candidate_zero": index == 0,
        "in_production_ballot": tuple(sorted(cards)) in production_ballot,
    }


class Sol0GameSession:
    """In-memory exact-world controller exposed to one ephemeral Sol session."""

    def __init__(self, root: Round, *, treatment_team: int,
                 seed_secret: bytes, coordinate: tuple[str, int, int],
                 role: str, config: Sol0PlannerConfig | None = None,
                 clock: Callable[[], float] = time.monotonic):
        if treatment_team not in (0, 1) or role not in full.ROLES:
            raise PrivilegedTeacherSol0Error("session role identity drift")
        if type(seed_secret) is not bytes or len(seed_secret) != 32:
            raise PrivilegedTeacherSol0Error("session seed identity drift")
        rank, banker, replicate = coordinate
        if (rank != root.trump_rank or banker != root.banker
                or isinstance(replicate, bool)
                or not isinstance(replicate, int) or replicate < 0
                or root.phase != "play" or root.trick is None
                or root.ordering is None):
            raise PrivilegedTeacherSol0Error("session root identity drift")
        self.config = config or Sol0PlannerConfig()
        self.rnd = copy.deepcopy(root)
        self.rnd._ptfull_true_world = True
        self.treatment_team = treatment_team
        self.coordinate = coordinate
        self.role = role
        self._clock = clock
        self._started = clock()
        self._opponents = [
            full._Production(seed=full._policy_seed(
                seed_secret, rank, banker, replicate, seat))
            for seat in range(4)
        ]
        self._ballot = [
            c0.C0WideHeuristicBot(seed=full._policy_seed(
                seed_secret, rank, banker, replicate, seat))
            for seat in range(4)
        ]
        self._decision_number = 0
        self._decision_sha256: str | None = None
        self._candidates: list[list[str]] | None = None
        self._production_ballot: set[tuple[str, ...]] | None = None
        self._evaluation_cache: dict[tuple[int, str], dict[str, object]] = {}
        self._decision_unique_rollouts = 0
        self._decision_rollout_calls = 0
        self._round_unique_rollouts = 0
        self._decision_observed = False
        self._events: list[dict[str, object]] = []
        self._decision_count = 0
        self._opponent_verified_rollouts = 0
        self._telemetry = {field: 0 for field in PUBLIC_TELEMETRY_FIELDS}
        self._continuation_counts = {name: 0 for name in CONTINUATIONS}
        self._confidence_counts = {name: 0 for name in CONFIDENCE_LEVELS}
        self._failed: str | None = None
        self._completion_token = secrets.token_hex(32)
        self._advance_to_contested()

    @property
    def failed(self) -> str | None:
        return self._failed

    @property
    def complete(self) -> bool:
        return self.rnd.phase == "round_end" and self._failed is None

    def _deadline(self) -> None:
        if self._clock() - self._started > self.config.max_session_wall_seconds:
            self._fail("Sol session wall deadline exceeded")

    def _fail(self, message: str) -> None:
        if self._failed is None:
            self._failed = message
        raise PrivilegedTeacherSol0Error(message)

    @staticmethod
    def _reject(message: str) -> None:
        raise PrivilegedTeacherSol0RequestError(message)

    def _record_rejection(self, request: Mapping[str, object],
                          error: str) -> None:
        response = {"status": "error", "error": error}
        self._telemetry["rejected_tool_calls"] += 1
        self._event("rejected", request, response)

    def _event(self, operation: str, request: Mapping[str, object],
               response: Mapping[str, object]) -> None:
        event = {
            "index": len(self._events),
            "operation": operation,
            "request": dict(request),
            "response": dict(response),
        }
        _private_event_size(event)
        self._events.append(event)

    def _candidate_list(self) -> list[list[str]]:
        seat = self.rnd.turn
        if seat is None or seat % 2 != self.treatment_team:
            self._fail("planner requested outside treatment turn")
        candidates = self._ballot[seat]._candidates(self.rnd, seat)
        if not candidates:
            self._fail("planner ballot is empty")
        return [list(cards) for cards in candidates]

    def _play_opponent(self) -> None:
        seat = self.rnd.turn
        if seat is None or seat % 2 == self.treatment_team:
            self._fail("opponent advance identity drift")
        cards = self._opponents[seat].decide_play(self.rnd, seat)
        try:
            verified = full._verify_decision_work(self._opponents[seat])
        except full.PrivilegedTeacherFullABError as exc:
            self._fail("opponent production work drift")
            raise AssertionError("unreachable") from exc
        self._opponent_verified_rollouts += verified
        self.rnd.play(seat, cards)
        self._decision_count += 1

    def _play_forced_treatment(self, cards: list[str]) -> None:
        seat = self.rnd.turn
        if seat is None or seat % 2 != self.treatment_team:
            self._fail("forced treatment identity drift")
        self.rnd.play(seat, list(cards))
        self._decision_count += 1
        self._telemetry["treatment_decisions"] += 1
        self._telemetry["forced_decisions"] += 1

    def _advance_to_contested(self) -> None:
        self._decision_sha256 = None
        self._candidates = None
        self._production_ballot = None
        self._evaluation_cache = {}
        self._decision_unique_rollouts = 0
        self._decision_rollout_calls = 0
        self._decision_observed = False
        while self.rnd.phase == "play":
            self._deadline()
            seat = self.rnd.turn
            if seat is None:
                self._fail("play round lost turn")
            if seat % 2 != self.treatment_team:
                self._play_opponent()
                continue
            candidates = self._candidate_list()
            if len(candidates) == 1:
                self._play_forced_treatment(candidates[0])
                continue
            production_ballot = c0._production_ballot(self.rnd, seat)
            self._decision_number += 1
            identity = {
                "schema": SESSION_SCHEMA,
                "coordinate": list(self.coordinate),
                "role": self.role,
                "treatment_team": self.treatment_team,
                "decision_number": self._decision_number,
                "turn": seat,
                "history_count": len(self.rnd.history),
                "current_trick": _trick_payload(self.rnd.trick),
                "hands": [sorted(hand) for hand in self.rnd.hands],
                "buried": sorted(self.rnd.buried),
                "candidates": [list(cards) for cards in candidates],
            }
            self._decision_sha256 = _sha(identity)
            self._candidates = candidates
            self._production_ballot = production_ballot
            return

    def _status_payload(self) -> dict[str, object]:
        if self._failed is not None:
            return {"status": "failed", "error": self._failed}
        if self.rnd.phase == "round_end":
            return {
                "status": "round_end",
                "attacker_points": self.rnd.attacker_points,
                "signed_level_utility": signed_level_utility(
                    self.rnd.attacker_points, banker_seat=self.rnd.banker,
                    perspective_seat=self.treatment_team),
                "completion_token": self._completion_token,
            }
        return {"status": "decision", "decision_sha256": (
            self._decision_sha256)}

    def observe(self) -> dict[str, object]:
        self._deadline()
        if self.rnd.phase == "round_end":
            response = {"schema": TOOL_RESPONSE_SCHEMA,
                        **self._status_payload()}
            self._event("observe", {"op": "observe"}, response)
            return response
        if self._candidates is None or self._decision_sha256 is None \
                or self._production_ballot is None or self.rnd.turn is None:
            self._fail("contested decision state absent")
        self._telemetry["observe_calls"] += 1
        self._decision_observed = True
        o = self.rnd.ordering
        if o is None:
            self._fail("round ordering absent")
        history = [_trick_payload(trick) for trick in self.rnd.history]
        response = {
            "schema": TOOL_RESPONSE_SCHEMA,
            "status": "decision",
            "decision_sha256": self._decision_sha256,
            "role": self.role,
            "treatment_team": self.treatment_team,
            "acting_seat": self.rnd.turn,
            "banker": self.rnd.banker,
            "team_is_attacker": self.rnd.is_attacker(self.rnd.turn),
            "attacker_points": self.rnd.attacker_points,
            "kitty_bonus_so_far": self.rnd.kitty_bonus,
            "trump_rank": self.rnd.trump_rank,
            "trump_suit": self.rnd.trump_suit,
            "trump_is_nt": self.rnd.trump_is_nt,
            "hands_by_seat": [sorted(hand) for hand in self.rnd.hands],
            "hidden_burial": sorted(self.rnd.buried),
            "completed_tricks": history,
            "current_trick": _trick_payload(self.rnd.trick),
            "remaining_points_by_seat": [
                sum(total_points([card]) for card in hand)
                for hand in self.rnd.hands
            ],
            "candidate_zero_is_production_prior": True,
            "candidates": [
                _candidate_payload(
                    self.rnd, cards, index, self._production_ballot)
                for index, cards in enumerate(self._candidates)
            ],
            "available_continuations": list(CONTINUATIONS),
            "budget": {
                "decision_rollout_calls_used": self._decision_rollout_calls,
                "decision_rollout_calls_limit":
                    MAX_ROLLOUT_CALLS_PER_DECISION,
                "decision_used": self._decision_unique_rollouts,
                "decision_limit": self.config.max_evaluations_per_decision,
                "round_used": self._round_unique_rollouts,
                "round_limit": self.config.max_evaluations_per_round,
                "per_call_new_limit": (
                    self.config.max_new_evaluations_per_call),
            },
            "objective": {
                "unit": "signed_levels_for_treatment_team",
                "attacker_threshold": 80,
                "attacker_brackets": [80, 120, 160, 200],
                "banker_brackets": [0, 40, 80],
                "goal": "maximize final signed-level utility",
            },
        }
        self._event("observe", {"op": "observe"}, response)
        return response

    def _evaluate(self, candidate_index: int, continuation_name: str) \
            -> dict[str, object]:
        if self._candidates is None or self.rnd.turn is None:
            self._fail("rollout requested outside contested decision")
        policy, exact_endgame = _continuation(
            continuation_name, self.treatment_team)
        evaluator = c0.C0ProductionBallotBot(seed=0)
        evaluator.rollout_policy = policy
        evaluator.EXACT_ENDGAME = exact_endgame
        sampled = {
            seat: list(self.rnd.hands[seat]) for seat in range(4)
            if seat != self.rnd.turn
        }
        exact_session = evaluator._new_exact_world_session(
            self.rnd, list(self.rnd.buried))
        attacker_points = evaluator._rollout(
            self.rnd, self.rnd.turn, sampled, list(self.rnd.buried),
            list(self._candidates[candidate_index]),
            exact_session=exact_session)
        if (not isinstance(attacker_points, (int, float))
                or isinstance(attacker_points, bool)
                or not math.isfinite(attacker_points)
                or not float(attacker_points).is_integer()
                or attacker_points < 0):
            self._fail("rollout result drift")
        points = int(attacker_points)
        return {
            "candidate_index": candidate_index,
            "continuation": continuation_name,
            "attacker_points": points,
            "signed_level_utility": signed_level_utility(
                points, banker_seat=self.rnd.banker,
                perspective_seat=self.treatment_team),
            "exact_endgame_calls": evaluator.exact_endgame_calls,
            "exact_endgame_nodes": evaluator.exact_endgame_nodes,
        }

    def rollout(self, request: Mapping[str, object]) -> dict[str, object]:
        self._deadline()
        expected = {"op", "decision_sha256", "candidate_indices",
                    "continuations"}
        if set(request) != expected or request.get("op") != "rollout" \
                or request.get("decision_sha256") != self._decision_sha256:
            self._reject("rollout request binding drift")
        candidates = request.get("candidate_indices")
        continuations = request.get("continuations")
        if (type(candidates) is not list or not candidates
                or type(continuations) is not list or not continuations
                or any(type(value) is not int for value in candidates)
                or any(type(value) is not str for value in continuations)
                or len(set(candidates)) != len(candidates)
                or len(set(continuations)) != len(continuations)
                or self._candidates is None):
            self._reject("rollout request shape drift")
        candidate_indices = [
            _strict_int(value, "rollout candidate") for value in candidates]
        if any(index >= len(self._candidates) for index in candidate_indices):
            self._reject("rollout candidate outside ballot")
        continuation_names = [
            _strict_token(value, CONTINUATIONS, "continuation")
            for value in continuations
        ]
        keys = [(index, name) for index in candidate_indices
                for name in continuation_names]
        new_keys = [key for key in keys if key not in self._evaluation_cache]
        if self._decision_rollout_calls >= MAX_ROLLOUT_CALLS_PER_DECISION:
            self._reject("rollout call budget exceeded")
        if len(new_keys) > self.config.max_new_evaluations_per_call:
            self._reject("rollout per-call budget exceeded")
        if (self._decision_unique_rollouts + len(new_keys) >
                self.config.max_evaluations_per_decision):
            self._reject("rollout decision budget exceeded")
        if (self._round_unique_rollouts + len(new_keys) >
                self.config.max_evaluations_per_round):
            self._reject("rollout round budget exceeded")
        for index, name in new_keys:
            result = self._evaluate(index, name)
            self._evaluation_cache[(index, name)] = result
            self._continuation_counts[name] += 1
        self._decision_unique_rollouts += len(new_keys)
        self._decision_rollout_calls += 1
        self._round_unique_rollouts += len(new_keys)
        self._telemetry["rollout_calls"] += 1
        self._telemetry["unique_rollouts"] += len(new_keys)
        self._telemetry["cached_rollouts"] += len(keys) - len(new_keys)
        response = {
            "schema": TOOL_RESPONSE_SCHEMA,
            "status": "rollout_complete",
            "decision_sha256": self._decision_sha256,
            "new_evaluations": len(new_keys),
            "cached_evaluations": len(keys) - len(new_keys),
            "results": [dict(self._evaluation_cache[key]) for key in keys],
            "budget": {
                "decision_rollout_calls_used": self._decision_rollout_calls,
                "decision_rollout_calls_limit":
                    MAX_ROLLOUT_CALLS_PER_DECISION,
                "decision_used": self._decision_unique_rollouts,
                "decision_limit": self.config.max_evaluations_per_decision,
                "round_used": self._round_unique_rollouts,
                "round_limit": self.config.max_evaluations_per_round,
            },
        }
        self._event("rollout", request, response)
        return response

    def play(self, request: Mapping[str, object]) -> dict[str, object]:
        self._deadline()
        expected = {"op", "decision_sha256", "candidate_index",
                    "confidence"}
        if set(request) != expected or request.get("op") != "play" \
                or request.get("decision_sha256") != self._decision_sha256:
            self._reject("play request binding drift")
        if not self._decision_observed:
            self._reject("play requires current observation")
        index = _strict_int(request.get("candidate_index"), "play candidate")
        confidence = _strict_token(
            request.get("confidence"), CONFIDENCE_LEVELS, "confidence")
        if self._candidates is None or index >= len(self._candidates) \
                or self._production_ballot is None or self.rnd.turn is None:
            self._reject("play candidate outside ballot")
        selected = list(self._candidates[index])
        incumbent = list(self._candidates[0])
        self.rnd.play(self.rnd.turn, selected)
        self._decision_count += 1
        self._telemetry["treatment_decisions"] += 1
        self._telemetry["contested_decisions"] += 1
        self._telemetry["candidate_zero_selections"] += int(index == 0)
        self._telemetry["selected_differs_from_candidate_zero"] += int(
            tuple(sorted(selected)) != tuple(sorted(incumbent)))
        self._telemetry["selected_outside_production_ballot"] += int(
            tuple(sorted(selected)) not in self._production_ballot)
        self._telemetry["decisions_without_rollout"] += int(
            self._decision_unique_rollouts == 0)
        self._confidence_counts[confidence] += 1
        private_response = {
            "schema": TOOL_RESPONSE_SCHEMA,
            "status": "play_committed",
            "decision_sha256": self._decision_sha256,
            "candidate_index": index,
            "confidence": confidence,
            "candidate_cards": selected,
            "decision_unique_rollouts": self._decision_unique_rollouts,
        }
        self._event("play", request, private_response)
        self._advance_to_contested()
        return {
            "schema": TOOL_RESPONSE_SCHEMA,
            **self._status_payload(),
        }

    def handle(self, request: Mapping[str, object]) -> dict[str, object]:
        if self._failed is not None:
            raise PrivilegedTeacherSol0Error(self._failed)
        if type(request) is not dict or type(request.get("op")) is not str:
            self._reject("tool request shape drift")
        operation = request["op"]
        if operation == "observe" and set(request) == {"op"}:
            return self.observe()
        if operation == "rollout":
            return self.rollout(request)
        if operation == "play":
            return self.play(request)
        self._reject("unknown planner operation")
        raise AssertionError("unreachable")

    def private_transcript_bytes(self) -> bytes:
        body = {
            "schema": PRIVATE_TRANSCRIPT_SCHEMA,
            "coordinate": list(self.coordinate),
            "role": self.role,
            "treatment_team": self.treatment_team,
            "events": list(self._events),
            "status": self._status_payload(),
            "completion_token_sha256": _sha_bytes(
                self._completion_token.encode("ascii")),
        }
        return canonical_json_bytes({**body, "transcript_sha256": _sha(body)})

    def outcome(self, *, model_output_sha256: str, model_exit_code: int,
                model_wall_milliseconds: int) -> Sol0Outcome:
        if not self.complete:
            raise PrivilegedTeacherSol0Error(
                "cannot publish unfinished Sol0 outcome")
        transcript = self.private_transcript_bytes()
        opponent_work = full._work(self._opponents)
        opponent_work["verified_rollouts"] = self._opponent_verified_rollouts
        if (sum(self._continuation_counts.values()) !=
                self._telemetry["unique_rollouts"]
                or self._telemetry["unique_rollouts"] !=
                self._round_unique_rollouts
                or self._telemetry["contested_decisions"] !=
                sum(self._confidence_counts.values())
                or self._telemetry["treatment_decisions"] !=
                self._telemetry["forced_decisions"] +
                self._telemetry["contested_decisions"]
                or self._decision_count != sum(
                    len(trick.plays) for trick in self.rnd.history)
                or opponent_work["verified_rollouts"] !=
                opponent_work["rollouts"]):
            raise PrivilegedTeacherSol0Error("Sol0 outcome accounting drift")
        return Sol0Outcome(
            attacker_points=self.rnd.attacker_points,
            signed_level_utility=signed_level_utility(
                self.rnd.attacker_points, banker_seat=self.rnd.banker,
                perspective_seat=self.treatment_team),
            decision_count=self._decision_count,
            telemetry=dict(self._telemetry),
            continuation_counts=dict(self._continuation_counts),
            confidence_counts=dict(self._confidence_counts),
            opponent_work=opponent_work,
            transcript_sha256=_sha_bytes(transcript),
            model_output_sha256=model_output_sha256,
            model_exit_code=model_exit_code,
            model_wall_milliseconds=model_wall_milliseconds,
        )


class Sol0ToolServer:
    """Single-session file mailbox for sandboxed Codex shell tool calls."""

    def __init__(self, path: Path, session: Sol0GameSession):
        if path.exists() or path.is_symlink():
            raise PrivilegedTeacherSol0Error("tool mailbox already exists")
        self.path = path
        self.session = session
        path.mkdir(mode=0o700)
        self._stop = threading.Event()
        self._error: BaseException | None = None
        self._handled: set[str] = set()
        self._thread = threading.Thread(
            target=self._serve, name="pt-sol0-tool-server",
            daemon=True)

    @staticmethod
    def _read_request(path: Path) -> dict[str, object]:
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            before = os.fstat(descriptor)
            raw = os.read(descriptor, MAX_PRIVATE_EVENT_BYTES + 1)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if (before.st_nlink != 1 or before.st_uid != os.getuid()
                or stat.S_IMODE(before.st_mode) != 0o600
                or len(raw) > MAX_PRIVATE_EVENT_BYTES
                or (before.st_dev, before.st_ino, before.st_size,
                    before.st_mtime_ns, before.st_ctime_ns) !=
                (after.st_dev, after.st_ino, after.st_size,
                 after.st_mtime_ns, after.st_ctime_ns)
                or len(raw) != before.st_size):
            raise PrivilegedTeacherSol0Error("tool request identity drift")
        try:
            request = json.loads(raw.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PrivilegedTeacherSol0Error("tool request JSON drift") from exc
        if type(request) is not dict or canonical_json_bytes(request) != raw:
            raise PrivilegedTeacherSol0Error("tool request JSON drift")
        return request

    @staticmethod
    def _publish_response(path: Path, response: Mapping[str, object]) -> None:
        raw = canonical_json_bytes(dict(response))
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0), 0o400)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            raise

    def _serve(self) -> None:
        try:
            while not self._stop.is_set():
                for request_path in sorted(self.path.glob("request-*.json")):
                    token = request_path.name.removeprefix(
                        "request-").removesuffix(".json")
                    if (token in self._handled or len(token) != 64
                            or any(char not in "0123456789abcdef"
                                   for char in token)):
                        continue
                    self._handled.add(token)
                    response_path = self.path / f"response-{token}.json"
                    request: dict[str, object] = {"op": "unreadable"}
                    try:
                        request = self._read_request(request_path)
                        response = self.session.handle(request)
                    except PrivilegedTeacherSol0Error as exc:
                        if self.session.failed is None:
                            self.session._record_rejection(
                                request, str(exc))
                        response = {"status": "error", "error": str(exc)}
                    self._publish_response(response_path, response)
                self._stop.wait(0.01)
        except BaseException as exc:
            self._error = exc
            self._stop.set()

    def __enter__(self) -> "Sol0ToolServer":
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            raise PrivilegedTeacherSol0Error("tool mailbox server did not stop")
        if self._error is not None and exc_type is None:
            raise PrivilegedTeacherSol0Error(
                "tool mailbox server failed") from self._error
        for child in self.path.iterdir():
            if not child.is_file() or child.is_symlink():
                raise PrivilegedTeacherSol0Error(
                    "tool mailbox file population drift")
            child.unlink()
        self.path.rmdir()


class PlannerProcess(Protocol):
    def __call__(self, session: Sol0GameSession, *, workspace: Path,
                 mailbox_path: Path, tool_script: Path,
                 codex_binary: Path,
                 prompt: str,
                 final_output_path: Path) -> subprocess.CompletedProcess[bytes]:
        ...


def planner_prompt(*, mailbox_path: Path, tool_script: Path,
                   python: Path) -> str:
    tool = (
        f"{python} -P -B {tool_script} --mailbox {mailbox_path}")
    return PLANNER_PROMPT_TEMPLATE.format(tool=tool)


def _default_planner_process(
        session: Sol0GameSession, *, workspace: Path, mailbox_path: Path,
        tool_script: Path, codex_binary: Path, prompt: str,
        final_output_path: Path) -> subprocess.CompletedProcess[bytes]:
    del session, mailbox_path, tool_script
    command = (
        str(codex_binary), "exec", "--ephemeral", "--ignore-user-config",
        "--ignore-rules", "--skip-git-repo-check", "--sandbox",
        "workspace-write", "-C", str(workspace), "-m", MODEL,
        "-c", f'model_reasoning_effort="{REASONING_EFFORT}"',
        "--output-last-message", str(final_output_path), "-",
    )
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        command, input=prompt.encode("utf-8"), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, cwd=workspace, env=env,
        timeout=MAX_SESSION_WALL_SECONDS, check=False)


def run_sol_session(
        session: Sol0GameSession, *, private_output: Path,
        tool_script: Path, planner_process: PlannerProcess | None = None,
        codex_binary: Path | None = None) \
        -> Sol0Outcome:
    """Run one ephemeral Codex process and publish one private transcript."""
    if private_output.exists() or private_output.is_symlink():
        raise PrivilegedTeacherSol0Error("private transcript slot occupied")
    if not tool_script.is_file():
        raise PrivilegedTeacherSol0Error("planner tool script absent")
    if codex_binary is None:
        found = shutil.which("codex")
        if found is None:
            raise PrivilegedTeacherSol0Error("Codex binary absent")
        codex_binary = Path(found)
    codex_binary = codex_binary.resolve()
    if not codex_binary.is_file():
        raise PrivilegedTeacherSol0Error("Codex binary absent")
    runner = planner_process or _default_planner_process
    started = time.monotonic()
    with tempfile.TemporaryDirectory(
            prefix="pt-sol0-", dir="/tmp") as raw_workspace:
        workspace = Path(raw_workspace)
        os.chmod(workspace, 0o700)
        mailbox_path = workspace / "controller-mailbox"
        final_path = workspace / "final.json"
        prompt_builder = getattr(
            session, "planner_prompt_builder", None) or planner_prompt
        prompt = prompt_builder(
            mailbox_path=mailbox_path, tool_script=tool_script,
            python=Path(sys.executable))
        completed: subprocess.CompletedProcess[bytes] | None = None
        process_error: str | None = None
        timed_out_output = b""
        with Sol0ToolServer(mailbox_path, session):
            try:
                completed = runner(
                    session, workspace=workspace, mailbox_path=mailbox_path,
                    tool_script=tool_script, codex_binary=codex_binary,
                    prompt=prompt,
                    final_output_path=final_path)
            except subprocess.TimeoutExpired as exc:
                process_error = "Sol model process exceeded wall deadline"
                timed_out_output = bytes(exc.stdout or b"")
        model_wall_ms = int((time.monotonic() - started) * 1000)
        model_output = (bytes(completed.stdout or b"") if completed
                        else timed_out_output)
        final_raw = final_path.read_bytes() if final_path.is_file() else b""
        combined_model_output = model_output + b"\0" + final_raw
        if completed is not None and completed.returncode != 0:
            process_error = "Sol model process did not complete engine round"
        try:
            final = json.loads(final_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            final = None
            process_error = process_error or "Sol model final response absent"
        if (completed is None or completed.returncode != 0 or final != {
                "schema": FINAL_RESPONSE_SCHEMA, "status": "complete",
                "completion_token": session._completion_token}
                or not session.complete):
            process_error = process_error or (
                "Sol model process did not complete engine round")
        private_raw = _private_evidence_bytes(
            session, model_stdout=model_output, final_raw=final_raw,
            process_returncode=(completed.returncode
                                if completed is not None else None),
            process_error=process_error)
        _publish_private(private_output, private_raw)
        if process_error is not None:
            raise PrivilegedTeacherSol0Error(process_error)
        assert completed is not None
        transcript = session.private_transcript_bytes()
        return session.outcome(
            model_output_sha256=_sha_bytes(combined_model_output),
            model_exit_code=completed.returncode,
            model_wall_milliseconds=model_wall_ms)


def tool_request(mailbox_path: Path, request: Mapping[str, object]) \
        -> dict[str, object]:
    """Small client used by the isolated command-line bridge and tests."""
    if not mailbox_path.is_dir() or mailbox_path.is_symlink():
        raise PrivilegedTeacherSol0Error("tool mailbox identity drift")
    raw = canonical_json_bytes(dict(request))
    if len(raw) > MAX_PRIVATE_EVENT_BYTES:
        raise PrivilegedTeacherSol0Error("tool request too large")
    token = secrets.token_hex(32)
    request_path = mailbox_path / f"request-{token}.json"
    response_path = mailbox_path / f"response-{token}.json"
    descriptor = os.open(
        request_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb", closefd=True) as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    deadline = time.monotonic() + MAX_SESSION_WALL_SECONDS
    while not response_path.is_file():
        if time.monotonic() > deadline:
            raise PrivilegedTeacherSol0Error("tool response deadline exceeded")
        time.sleep(0.01)
    descriptor = os.open(
        response_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        response_raw = os.read(descriptor, MAX_PRIVATE_EVENT_BYTES + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (before.st_nlink != 1 or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o400
            or len(response_raw) > MAX_PRIVATE_EVENT_BYTES
            or (before.st_dev, before.st_ino, before.st_size,
                before.st_mtime_ns, before.st_ctime_ns) !=
            (after.st_dev, after.st_ino, after.st_size,
             after.st_mtime_ns, after.st_ctime_ns)
            or len(response_raw) != before.st_size):
        raise PrivilegedTeacherSol0Error("tool response identity drift")
    try:
        response = json.loads(response_raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PrivilegedTeacherSol0Error("tool response drift") from exc
    if type(response) is not dict:
        raise PrivilegedTeacherSol0Error("tool response drift")
    return response


__all__ = [
    "CONTINUATIONS", "FINAL_RESPONSE_SCHEMA", "MODEL",
    "PrivilegedTeacherSol0Error", "PrivilegedTeacherSol0RequestError",
    "Sol0GameSession", "Sol0Outcome",
    "Sol0PlannerConfig", "Sol0ToolServer", "planner_prompt",
    "run_sol_session", "tool_request",
]

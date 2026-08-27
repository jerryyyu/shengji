"""PT-Pub0: public-information adaptive planner arm on the Sol0 harness.

v1 estimand — **acting-seat public information**: at every contested decision
the planner sees exactly what production MC sees from the acting seat (that
seat's own hand, the public trick state and history, and the burial only when
the acting seat is the banker), and rollouts evaluate candidates over
``WORLDS_PER_EVALUATION`` hidden worlds drawn from production's own
constraint sampler instead of the exact hidden world.  This makes the arm an
equal-information comparison against PT-Full arm A: any edge must come from
decision quality, not information.  Partnership-level information (both
controlled hands visible) is a deliberately deferred v2 estimand, noted here
so nobody mistakes v1 for it.

Everything else — mailbox protocol, ballots, budgets, completion token,
private evidence, report machinery, both planner adapters — is reused from
the Sol0/Cla0 stack unchanged.
"""

from __future__ import annotations

import hashlib
from typing import Mapping

from ..ai.memory import Memory
from . import privileged_teacher_c0 as c0
from . import privileged_teacher_full_ab as full_ab
from .privileged_teacher_sol0 import (
    Sol0GameSession,
    TOOL_RESPONSE_SCHEMA,
    _candidate_payload,
    _continuation,
    _trick_payload,
    signed_level_utility,
)

PUB0_SESSION_SCHEMA = "privileged-teacher-pub0-session-v1"
PUB0_DESIGN_SCHEMA = "privileged-teacher-pub0-design-v1"
INFO_MODEL = "acting-seat-public-v1"
WORLD_SOURCE = "production-constraint-sampler-v1"
WORLDS_PER_EVALUATION = 8
MAX_WORLD_SAMPLE_ATTEMPTS = 64

PUB0_PROMPT_TEMPLATE = """You are PT-Pub0, an offline public-information Shengji player.
You control both seats of one treatment partnership for one complete round.
Your only goal is to maximize final signed-level utility for that partnership.

Use only this game tool; do not inspect or modify other files:
  {tool} observe
  {tool} rollout --decision SHA --candidates 0,1 --continuations smart-all,team-smart
  {tool} play --decision SHA --candidate 0 --confidence low

At every decision, call observe first. You see ONLY what the acting seat
legitimately knows: its own hand, the public trick state and history, and the
burial only when the acting seat is the banker. Opponent and partner hands are
hidden. Candidate zero is the production prior and is always a valid fallback.
Rollout results are averages over {worlds} hidden worlds sampled from the
production constraint sampler consistent with public information; treat them
as noisy estimates, not exact values. Never repeat an identical
candidate/continuation pair merely to obtain another sample. For each rollout
command, candidate count times continuation count must be at most 16. A tool
error changes no game state: correct the request, observe again if needed,
and continue.
Use at most two rollout commands per decision; spend the second only when the
first result leaves a material signed-level choice unresolved. Then play.
Consider multi-trick control, partnership entries, point timing, trump
exhaustion, banker defense, attacker thresholds, and the risk that a
conclusion depends on one continuation assumption. Commit exactly one listed
candidate with play, then continue until the tool reports round_end.

Do not stop early. Do not invent cards, values, or tool results. The final
legal play returns a one-time completion_token. After round_end, return the
required JSON object with status complete and that exact completion_token.
The final response must contain only this JSON shape, with TOKEN replaced by
the engine-returned value:
{{"schema":"privileged-teacher-sol0-final-response-v1","status":"complete","completion_token":"TOKEN"}}
"""
PUB0_PROMPT_TEMPLATE_SHA256 = hashlib.sha256(
    PUB0_PROMPT_TEMPLATE.encode("utf-8")).hexdigest()


def pub0_planner_prompt(*, mailbox_path, tool_script, python) -> str:
    tool = f"{python} -P -B {tool_script} --mailbox {mailbox_path}"
    return PUB0_PROMPT_TEMPLATE.format(tool=tool, worlds=WORLDS_PER_EVALUATION)


class Pub0GameSession(Sol0GameSession):
    """Sol0 engine session with acting-seat-public observation and
    production-sampled rollout worlds.

    The engine still holds the exact round; redaction applies only to what
    the planner is served.  The private event log records exactly the
    redacted responses, so the sealed evidence shows what the planner saw.
    """

    planner_prompt_builder = staticmethod(pub0_planner_prompt)

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
        if self.rnd.ordering is None:
            self._fail("round ordering absent")
        seat = self.rnd.turn
        burial_known = seat == self.rnd.banker
        history = [_trick_payload(trick) for trick in self.rnd.history]
        response = {
            "schema": TOOL_RESPONSE_SCHEMA,
            "status": "decision",
            "decision_sha256": self._decision_sha256,
            "role": self.role,
            "treatment_team": self.treatment_team,
            "acting_seat": seat,
            "banker": self.rnd.banker,
            "team_is_attacker": self.rnd.is_attacker(seat),
            "attacker_points": self.rnd.attacker_points,
            "kitty_bonus_so_far": self.rnd.kitty_bonus,
            "trump_rank": self.rnd.trump_rank,
            "trump_suit": self.rnd.trump_suit,
            "trump_is_nt": self.rnd.trump_is_nt,
            "information_model": INFO_MODEL,
            "acting_hand": sorted(self.rnd.hands[seat]),
            "burial_if_banker": (
                sorted(self.rnd.buried) if burial_known else None),
            "completed_tricks": history,
            "current_trick": _trick_payload(self.rnd.trick),
            "cards_remaining_by_seat": [
                len(hand) for hand in self.rnd.hands],
            "candidate_zero_is_production_prior": True,
            "candidates": [
                _candidate_payload(
                    self.rnd, cards, index, self._production_ballot)
                for index, cards in enumerate(self._candidates)
            ],
        }
        self._event("observe", {"op": "observe"}, response)
        return response

    def _evaluate(self, candidate_index: int,
                  continuation_name: str) -> dict[str, object]:
        if self._candidates is None or self.rnd.turn is None:
            self._fail("rollout requested outside contested decision")
        seat = self.rnd.turn
        policy, exact_endgame = _continuation(
            continuation_name, self.treatment_team)
        per_world: list[int] = []
        world_fingerprints: list[str] = []
        sampler_attempts = 0
        for world_index in range(WORLDS_PER_EVALUATION):
            world_seed = int.from_bytes(hashlib.sha256((
                f"{PUB0_SESSION_SCHEMA}|{self._decision_sha256}|"
                f"{candidate_index}|{continuation_name}|{world_index}"
            ).encode("ascii")).digest()[:8], "big")
            evaluator = c0.C0ProductionBallotBot(seed=world_seed)
            evaluator.rollout_policy = policy
            evaluator.EXACT_ENDGAME = exact_endgame
            mem = Memory(self.rnd, seat, own_kitty=True)
            world = None
            for _ in range(MAX_WORLD_SAMPLE_ATTEMPTS):
                sampler_attempts += 1
                # Explicit base-class call: the C0/full-AB bot classes
                # override _sample_hands to return the exact true world on
                # marked privileged rounds (arm B's implementation), which
                # would silently reintroduce perfect information here.  The
                # production base sampler is the honest public-information
                # world source.  Witnessed by the fingerprint-spread and
                # cross-session determinism assertions.
                world = full_ab._Production._sample_hands(
                    evaluator, self.rnd, seat, mem)
                if world is not None:
                    break
            if world is None:
                self._fail("public world sampling exhausted")
            sampled_hands, sampled_buried = world
            world_fingerprints.append(hashlib.sha256(repr((
                sorted((seat_key, tuple(sorted(hand)))
                       for seat_key, hand in sampled_hands.items()),
                tuple(sorted(sampled_buried)),
            )).encode("ascii")).hexdigest()[:16])
            exact_session = evaluator._new_exact_world_session(
                self.rnd, list(sampled_buried))
            attacker_points = evaluator._rollout(
                self.rnd, seat, sampled_hands, list(sampled_buried),
                list(self._candidates[candidate_index]),
                exact_session=exact_session)
            if (not isinstance(attacker_points, (int, float))
                    or isinstance(attacker_points, bool)
                    or int(attacker_points) != attacker_points
                    or attacker_points < 0):
                self._fail("rollout result drift")
            per_world.append(int(attacker_points))
        mean_points = sum(per_world) / len(per_world)
        return {
            "candidate_index": candidate_index,
            "continuation": continuation_name,
            "information_model": INFO_MODEL,
            "worlds": WORLDS_PER_EVALUATION,
            "sampler_attempts": sampler_attempts,
            "attacker_points_per_world": list(per_world),
            "world_fingerprints": list(world_fingerprints),
            "attacker_points_mean": mean_points,
            "attacker_points_min": min(per_world),
            "attacker_points_max": max(per_world),
            "signed_level_utility_mean": signed_level_utility(
                round(mean_points), banker_seat=self.rnd.banker,
                perspective_seat=self.treatment_team),
        }




from dataclasses import dataclass

from .privileged_teacher_sol0 import (
    MAX_EVALUATIONS_PER_DECISION,
    MAX_EVALUATIONS_PER_ROUND,
    MAX_NEW_EVALUATIONS_PER_CALL,
    MAX_ROLLOUT_CALLS_PER_DECISION,
    MAX_SESSION_WALL_SECONDS,
    PrivilegedTeacherSol0Error,
)
from .privileged_teacher_sol0_report import Sol0Design

ALLOWED_PLANNERS = ("codex", "claude")


@dataclass(frozen=True)
class Pub0Design(Sol0Design):
    """Frozen design honestly identifying the public-information arm."""

    planner: str = "codex"
    planner_model: str = "gpt-5.6-sol"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.planner not in ALLOWED_PLANNERS:
            raise PrivilegedTeacherSol0Error("Pub0 planner identity drift")
        if (type(self.planner_model) is not str or not self.planner_model
                or len(self.planner_model) > 64):
            raise PrivilegedTeacherSol0Error("Pub0 model identity drift")

    def payload(self) -> dict[str, object]:
        payload = super().payload()
        payload["schema"] = PUB0_DESIGN_SCHEMA
        payload["model"] = self.planner_model
        payload["prompt_template_sha256"] = PUB0_PROMPT_TEMPLATE_SHA256
        payload["planner_config"] = {
            "planner": self.planner,
            "model": self.planner_model,
            "reasoning_effort": "high",
            "information_model": INFO_MODEL,
            "world_source": WORLD_SOURCE,
            "worlds_per_evaluation": WORLDS_PER_EVALUATION,
            "max_new_evaluations_per_call": MAX_NEW_EVALUATIONS_PER_CALL,
            "max_evaluations_per_decision": MAX_EVALUATIONS_PER_DECISION,
            "max_evaluations_per_round": MAX_EVALUATIONS_PER_ROUND,
            "max_rollout_calls_per_decision": MAX_ROLLOUT_CALLS_PER_DECISION,
            "max_session_wall_seconds": MAX_SESSION_WALL_SECONDS,
        }
        return payload

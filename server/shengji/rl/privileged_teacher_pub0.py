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

Each partnership seat receives its own persistent planner process and mailbox;
the shared engine advances only the seat whose turn it is.  The mailbox
protocol, ballots, budgets, completion token, private evidence, and both
planner adapters remain the Sol0/Cla0 implementations.  Report machinery has
only an injected runner seam whose default remains the original Sol0 runner.
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Mapping

from ..ai.memory import Memory
from . import privileged_teacher_c0 as c0
from . import privileged_teacher_full_ab as full_ab
from .privileged_teacher_pt0 import (
    canonical_json_bytes,
    pt0_public_state_sha256,
)
from .privileged_teacher_sol0 import (
    FINAL_RESPONSE_SCHEMA,
    MAX_EVALUATIONS_PER_DECISION,
    MAX_EVALUATIONS_PER_ROUND,
    MAX_NEW_EVALUATIONS_PER_CALL,
    MAX_ROLLOUT_CALLS_PER_DECISION,
    MAX_SESSION_WALL_SECONDS,
    PlannerProcess,
    PrivilegedTeacherSol0Error,
    PrivilegedTeacherSol0RequestError,
    Sol0GameSession,
    Sol0Outcome,
    Sol0ToolServer,
    TOOL_RESPONSE_SCHEMA,
    _default_planner_process,
    _candidate_payload,
    _continuation,
    _private_evidence_bytes,
    _publish_private,
    _sha,
    _sha_bytes,
    _trick_payload,
    signed_level_utility,
)

PUB0_SESSION_SCHEMA = "privileged-teacher-pub0-session-v1"
PUB0_DESIGN_SCHEMA = "privileged-teacher-pub0-design-v1"
PUB0_DECISION_SCHEMA = "privileged-teacher-pub0-public-decision-v1"
PUB0_MODEL_OUTPUT_SCHEMA = "privileged-teacher-pub0-model-output-v1"
INFO_MODEL = "acting-seat-public-v1"
WORLD_SOURCE = "production-constraint-sampler-v1"
WORLDS_PER_EVALUATION = 8
MAX_WORLD_SAMPLE_ATTEMPTS = 64

PUB0_PROMPT_TEMPLATE = """You are PT-Pub0, an offline public-information Shengji player.
You control fixed seat {seat} for one complete round. A separate isolated
planner controls your teammate; you never receive that planner's private hand
or reasoning context. You may infer only from the public plays you observe.
Your only goal is to maximize final signed-level utility for that partnership.

Use only this game tool; do not inspect or modify other files:
  {tool} observe
  {tool} rollout --decision SHA --candidates 0,1 --continuations smart-all,team-smart
  {tool} play --decision SHA --candidate 0 --confidence low

Call observe now. It waits safely while another seat is acting and returns only
when fixed seat {seat} must decide or the round has ended. At every decision you
see ONLY what seat {seat} legitimately knows: its own hand, the public trick
state and history, and the burial only when seat {seat} is the banker. Opponent
and partner hands are hidden. Candidate zero is the production prior and is
always a valid fallback.
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
candidate with play, then call observe again and continue until the tool
reports round_end.

Do not stop early. Do not invent cards, values, or tool results. The final
legal play returns a one-time completion_token. After round_end, return the
required JSON object with status complete and that exact completion_token.
The final response must contain only this JSON shape, with TOKEN replaced by
the engine-returned value:
{{"schema":"privileged-teacher-sol0-final-response-v1","status":"complete","completion_token":"TOKEN"}}
"""
PUB0_PROMPT_TEMPLATE_SHA256 = hashlib.sha256(
    PUB0_PROMPT_TEMPLATE.encode("utf-8")).hexdigest()


def pub0_planner_prompt(*, mailbox_path, tool_script, python, seat: int) -> str:
    if isinstance(seat, bool) or not isinstance(seat, int) \
            or not 0 <= seat < 4:
        raise PrivilegedTeacherSol0Error("Pub0 planner seat drift")
    tool = f"{python} -P -B {tool_script} --mailbox {mailbox_path}"
    return PUB0_PROMPT_TEMPLATE.format(
        tool=tool, worlds=WORLDS_PER_EVALUATION, seat=seat)


def _public_decision_sha256(
        session: "Pub0GameSession") -> tuple[str, str]:
    if session.rnd.turn is None or session._candidates is None:
        raise PrivilegedTeacherSol0Error("Pub0 public decision state absent")
    public_state = pt0_public_state_sha256(
        session.rnd, perspective_seat=session.rnd.turn)
    decision = _sha({
        "schema": PUB0_DECISION_SCHEMA,
        "public_state_sha256": public_state,
        "candidates": [list(cards) for cards in session._candidates],
    })
    return public_state, decision


def _mean_signed_level_utility(
        points: list[int], *, banker_seat: int,
        perspective_seat: int) -> tuple[list[int], float]:
    if not points:
        raise PrivilegedTeacherSol0Error("Pub0 rollout population is empty")
    utilities = [signed_level_utility(
        value, banker_seat=banker_seat,
        perspective_seat=perspective_seat) for value in points]
    return utilities, sum(utilities) / len(utilities)


class Pub0GameSession(Sol0GameSession):
    """Sol0 engine session with acting-seat-public observation and
    production-sampled rollout worlds.

    The engine still holds the exact round; redaction applies only to what
    the planner is served.  The private event log records exactly the
    redacted responses, so the sealed evidence shows what the planner saw.
    """

    planner_prompt_builder = staticmethod(pub0_planner_prompt)

    def __init__(self, *args, **kwargs):
        self._public_state_sha256: str | None = None
        self._sampled_world_bank: tuple[
            tuple[tuple[tuple[int, tuple[str, ...]], ...],
                  tuple[str, ...], str, int], ...] | None = None
        super().__init__(*args, **kwargs)

    def _advance_to_contested(self) -> None:
        self._public_state_sha256 = None
        self._sampled_world_bank = None
        super()._advance_to_contested()
        if self.rnd.phase == "play":
            public_state, decision = _public_decision_sha256(self)
            self._public_state_sha256 = public_state
            self._decision_sha256 = decision

    def _sample_public_world_bank(self) -> tuple[
            tuple[tuple[tuple[int, tuple[str, ...]], ...],
                  tuple[str, ...], str, int], ...]:
        if self._sampled_world_bank is not None:
            return self._sampled_world_bank
        if self.rnd.turn is None or self._decision_sha256 is None:
            self._fail("public world sampling requested outside decision")
        seat = self.rnd.turn
        mem = Memory(self.rnd, seat, own_kitty=True)
        rows = []
        for world_index in range(WORLDS_PER_EVALUATION):
            sampler_seed = int.from_bytes(hashlib.sha256((
                f"{PUB0_SESSION_SCHEMA}|{self._decision_sha256}|"
                f"sample-world|{world_index}"
            ).encode("ascii")).digest()[:8], "big")
            sampler = c0.C0ProductionBallotBot(seed=sampler_seed)
            world = None
            attempts = 0
            for _ in range(MAX_WORLD_SAMPLE_ATTEMPTS):
                attempts += 1
                world = full_ab._Production._sample_hands(
                    sampler, self.rnd, seat, mem)
                if world is not None:
                    break
            if world is None:
                self._fail("public world sampling exhausted")
            sampled_hands, sampled_buried = world
            frozen_hands = tuple(sorted(
                (seat_key, tuple(sorted(hand)))
                for seat_key, hand in sampled_hands.items()))
            frozen_buried = tuple(sorted(sampled_buried))
            fingerprint = hashlib.sha256(repr((
                frozen_hands, frozen_buried,
            )).encode("ascii")).hexdigest()[:16]
            rows.append((
                frozen_hands, frozen_buried, fingerprint, attempts))
        self._sampled_world_bank = tuple(rows)
        return self._sampled_world_bank

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
            "public_state_sha256": self._public_state_sha256,
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
        world_bank = self._sample_public_world_bank()
        sampler_attempts = sum(row[3] for row in world_bank)
        for world_index, (
                frozen_hands, frozen_buried, fingerprint,
                _) in enumerate(world_bank):
            rollout_seed = int.from_bytes(hashlib.sha256((
                f"{PUB0_SESSION_SCHEMA}|{self._decision_sha256}|"
                f"rollout|{world_index}"
            ).encode("ascii")).digest()[:8], "big")
            evaluator = c0.C0ProductionBallotBot(seed=rollout_seed)
            evaluator.rollout_policy = policy
            evaluator.EXACT_ENDGAME = exact_endgame
            sampled_hands = {
                seat_key: list(hand) for seat_key, hand in frozen_hands}
            sampled_buried = list(frozen_buried)
            world_fingerprints.append(fingerprint)
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
        per_world_utility, mean_utility = _mean_signed_level_utility(
            per_world, banker_seat=self.rnd.banker,
            perspective_seat=self.treatment_team)
        return {
            "candidate_index": candidate_index,
            "continuation": continuation_name,
            "information_model": INFO_MODEL,
            "worlds": WORLDS_PER_EVALUATION,
            "sampler_attempts": sampler_attempts,
            "attacker_points_per_world": list(per_world),
            "signed_level_utility_per_world": per_world_utility,
            "world_fingerprints": list(world_fingerprints),
            "attacker_points_mean": mean_points,
            "attacker_points_min": min(per_world),
            "attacker_points_max": max(per_world),
            "signed_level_utility_mean": mean_utility,
        }


class _Pub0SeatController:
    """Expose one fixed seat while serializing access to the shared round."""

    def __init__(self, session: Pub0GameSession, seat: int,
                 condition: threading.Condition):
        if type(session) is not Pub0GameSession or seat not in range(4) \
                or seat % 2 != session.treatment_team \
                or not isinstance(condition, threading.Condition):
            raise PrivilegedTeacherSol0Error(
                "Pub0 seat controller identity drift")
        self.session = session
        self.seat = seat
        self._condition = condition

    @property
    def failed(self) -> str | None:
        return self.session.failed

    @property
    def complete(self) -> bool:
        return self.session.complete

    def _record_rejection(self, request: Mapping[str, object],
                          error: str) -> None:
        with self._condition:
            self.session._record_rejection(request, error)

    def fail_shared(self, message: str) -> None:
        with self._condition:
            if self.session._failed is None:
                self.session._failed = message
            self._condition.notify_all()

    def handle(self, request: Mapping[str, object]) -> dict[str, object]:
        with self._condition:
            if type(request) is not dict or type(request.get("op")) is not str:
                self.session._reject("tool request shape drift")
            if request["op"] == "observe" and set(request) == {"op"}:
                deadline = (self.session._started
                            + self.session.config.max_session_wall_seconds)
                while (not self.session.complete
                       and self.session.failed is None
                       and self.session.rnd.turn != self.seat):
                    remaining = deadline - self.session._clock()
                    if remaining <= 0:
                        self.fail_shared("Pub0 seat wait exceeded wall deadline")
                        raise PrivilegedTeacherSol0Error(
                            "Pub0 seat wait exceeded wall deadline")
                    self._condition.wait(timeout=remaining)
            if self.session.failed is not None:
                raise PrivilegedTeacherSol0Error(self.session.failed)
            if not self.session.complete and self.session.rnd.turn != self.seat:
                self.session._reject("planner requested outside fixed seat")
            response = self.session.handle(request)
            if request["op"] == "play":
                self._condition.notify_all()
            return response

    # Direct helpers keep fake-planner tests on the same fixed-seat boundary.
    def observe(self) -> dict[str, object]:
        return self.handle({"op": "observe"})

    def rollout(self, request: Mapping[str, object]) -> dict[str, object]:
        return self.handle(request)

    def play(self, request: Mapping[str, object]) -> dict[str, object]:
        return self.handle(request)


def _model_frame(field: str, rows: Mapping[int, bytes]) -> bytes:
    if field not in {"stdout", "final"} or len(rows) != 2 \
            or any(type(seat) is not int or seat not in range(4)
                   or type(raw) is not bytes for seat, raw in rows.items()):
        raise PrivilegedTeacherSol0Error("Pub0 model frame drift")
    return canonical_json_bytes({
        "schema": PUB0_MODEL_OUTPUT_SCHEMA,
        "field": field,
        "seats": [
            {"seat": seat,
             "base64": base64.b64encode(rows[seat]).decode("ascii")}
            for seat in sorted(rows)],
    })


def run_pub0_session(
        session: Pub0GameSession, *, private_output: Path,
        tool_script: Path, planner_process: PlannerProcess | None = None,
        codex_binary: Path | None = None) -> Sol0Outcome:
    """Run two isolated persistent planners, one for each partnership seat."""
    if type(session) is not Pub0GameSession:
        raise PrivilegedTeacherSol0Error("Pub0 session runner identity drift")
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
    seats = tuple(seat for seat in range(4)
                  if seat % 2 == session.treatment_team)
    condition = threading.Condition(threading.RLock())
    controllers = {
        seat: _Pub0SeatController(session, seat, condition) for seat in seats}
    started = time.monotonic()

    def run_seat(seat: int, parent: Path) -> dict[str, object]:
        workspace = parent / f"seat-{seat}"
        workspace.mkdir(mode=0o700)
        mailbox_path = workspace / "controller-mailbox"
        final_path = workspace / "final.json"
        prompt = pub0_planner_prompt(
            mailbox_path=mailbox_path, tool_script=tool_script,
            python=Path(sys.executable), seat=seat)
        completed: subprocess.CompletedProcess[bytes] | None = None
        process_error: str | None = None
        timed_out_output = b""
        try:
            with Sol0ToolServer(mailbox_path, controllers[seat]):
                try:
                    completed = runner(
                        controllers[seat], workspace=workspace,
                        mailbox_path=mailbox_path, tool_script=tool_script,
                        codex_binary=codex_binary, prompt=prompt,
                        final_output_path=final_path)
                except subprocess.TimeoutExpired as exc:
                    process_error = (
                        f"Pub0 seat {seat} process exceeded wall deadline")
                    timed_out_output = bytes(exc.stdout or b"")
        except Exception as exc:
            process_error = process_error or (
                f"Pub0 seat {seat} tool boundary failed: {exc}")
        model_output = (bytes(completed.stdout or b"") if completed
                        else timed_out_output)
        final_raw = final_path.read_bytes() if final_path.is_file() else b""
        if completed is not None and completed.returncode != 0:
            process_error = (
                f"Pub0 seat {seat} process did not complete engine round")
        try:
            final = json.loads(final_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            final = None
            process_error = process_error or (
                f"Pub0 seat {seat} final response absent")
        if (completed is None or completed.returncode != 0 or final != {
                "schema": FINAL_RESPONSE_SCHEMA, "status": "complete",
                "completion_token": session._completion_token}):
            process_error = process_error or (
                f"Pub0 seat {seat} process did not complete engine round")
        if process_error is not None:
            controllers[seat].fail_shared(process_error)
        return {
            "stdout": model_output,
            "final": final_raw,
            "returncode": (completed.returncode
                           if completed is not None else None),
            "error": process_error,
        }

    results: dict[int, dict[str, object]] = {}
    with tempfile.TemporaryDirectory(prefix="pt-pub0-", dir="/tmp") as raw:
        parent = Path(raw)
        os.chmod(parent, 0o700)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {seat: executor.submit(run_seat, seat, parent)
                       for seat in seats}
            for seat in seats:
                results[seat] = futures[seat].result()
    wall_ms = int((time.monotonic() - started) * 1000)
    stdout_frame = _model_frame(
        "stdout", {seat: results[seat]["stdout"] for seat in seats})
    final_frame = _model_frame(
        "final", {seat: results[seat]["final"] for seat in seats})
    errors = [results[seat]["error"] for seat in seats
              if results[seat]["error"] is not None]
    returncodes = [results[seat]["returncode"] for seat in seats]
    process_error = "; ".join(str(value) for value in errors) or None
    if not session.complete:
        process_error = process_error or (
            "Pub0 planners did not complete engine round")
    private_raw = _private_evidence_bytes(
        session, model_stdout=stdout_frame, final_raw=final_frame,
        process_returncode=(0 if returncodes == [0, 0] else None),
        process_error=process_error)
    _publish_private(private_output, private_raw)
    if process_error is not None:
        raise PrivilegedTeacherSol0Error(process_error)
    transcript = session.private_transcript_bytes()
    return session.outcome(
        model_output_sha256=_sha_bytes(stdout_frame + b"\0" + final_frame),
        model_exit_code=0, model_wall_milliseconds=wall_ms)




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
            "planner_context_scope": "fixed-seat-isolated-persistent-v1",
            "planner_contexts_per_role": 2,
            "world_source": WORLD_SOURCE,
            "world_comparison": "common-random-world-bank-v1",
            "worlds_per_evaluation": WORLDS_PER_EVALUATION,
            "utility_aggregation": "mean-per-world-signed-level-v1",
            "max_new_evaluations_per_call": MAX_NEW_EVALUATIONS_PER_CALL,
            "max_evaluations_per_decision": MAX_EVALUATIONS_PER_DECISION,
            "max_evaluations_per_round": MAX_EVALUATIONS_PER_ROUND,
            "max_rollout_calls_per_decision": MAX_ROLLOUT_CALLS_PER_DECISION,
            "max_session_wall_seconds": MAX_SESSION_WALL_SECONDS,
        }
        return payload

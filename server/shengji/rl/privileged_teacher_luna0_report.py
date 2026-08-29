"""Paired public report for the descriptive PT-Luna0 benchmark.

This layer reuses the reviewed Sol0 controller, but gives the Luna treatment a
separate immutable design/report namespace and binds every row to the sealed
public Sol0 row at the same coordinate and role.  No Sol0 private receipt is
opened here.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import math
import os
import platform
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Mapping

from ..engine.cards import RANKS
from . import privileged_teacher_c0 as c0
from . import privileged_teacher_full_ab as full
from . import privileged_teacher_sol0 as sol0
from . import privileged_teacher_sol0_report as sol_report
from .privileged_teacher_pt0 import canonical_json_bytes


SCHEMA = "privileged-teacher-luna0-open-dev-v1"
RECORD_SCHEMA = "privileged-teacher-luna0-record-v1"
DESIGN_SCHEMA = "privileged-teacher-luna0-design-v1"
DEV_NAMESPACE = "privileged-teacher-luna0-open-dev-v1"
ROLES = full.ROLES
CONTRASTS = ("luna0_minus_sol0", "luna0_minus_a", "luna0_minus_b",
             "luna0_minus_c0_s")
MODEL = "gpt-5.6-luna"
LUNA_MODEL = MODEL
TOKEN_COMPARISON_STATUS = "UNAVAILABLE_PUBLIC_SOL0_ARTIFACT"
WALL_COMPARISON_STATUS = "DESCRIPTIVE_CROSS_RUN_HOST_LOAD_CONFOUNDED"
AUTHORITY = {
    **full.AUTHORITY,
    "test_opening_authorized": False,
    "retry_authorized": False,
}


class PrivilegedTeacherLuna0Error(ValueError):
    """The paired Luna0 public boundary or receipt drifted."""


@dataclass(frozen=True)
class Luna0PlannerConfig:
    """Luna-only execution config; never accepted by the Sol0 report."""

    model: str = MODEL
    reasoning_effort: str = sol0.REASONING_EFFORT
    max_new_evaluations_per_call: int = sol0.MAX_NEW_EVALUATIONS_PER_CALL
    max_evaluations_per_decision: int = sol0.MAX_EVALUATIONS_PER_DECISION
    max_evaluations_per_round: int = sol0.MAX_EVALUATIONS_PER_ROUND
    max_session_wall_seconds: int = sol0.MAX_SESSION_WALL_SECONDS

    def __post_init__(self) -> None:
        if self.model != MODEL or self.reasoning_effort != sol0.REASONING_EFFORT:
            raise PrivilegedTeacherLuna0Error("Luna0 planner identity drift")
        if (self.max_new_evaluations_per_call != sol0.MAX_NEW_EVALUATIONS_PER_CALL
                or self.max_evaluations_per_decision != sol0.MAX_EVALUATIONS_PER_DECISION
                or self.max_evaluations_per_round != sol0.MAX_EVALUATIONS_PER_ROUND
                or self.max_session_wall_seconds != sol0.MAX_SESSION_WALL_SECONDS):
            raise PrivilegedTeacherLuna0Error("Luna0 planner budget drift")

    def payload(self) -> dict[str, object]:
        return {
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "continuations": list(sol0.CONTINUATIONS),
            "max_new_evaluations_per_call": self.max_new_evaluations_per_call,
            "max_rollout_calls_per_decision": sol0.MAX_ROLLOUT_CALLS_PER_DECISION,
            "max_evaluations_per_decision": self.max_evaluations_per_decision,
            "max_evaluations_per_round": self.max_evaluations_per_round,
            "max_session_wall_seconds": self.max_session_wall_seconds,
        }


def _sha(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _strict_sha(value: object, label: str, *, length: int = 64) -> str:
    if (type(value) is not str or len(value) != length
            or any(char not in "0123456789abcdef" for char in value)):
        raise PrivilegedTeacherLuna0Error(f"{label} drift")
    return value


@dataclass(frozen=True)
class Luna0Design:
    seed_commitment_sha256: str
    execution_git: str
    native_sha256: str
    hostname: str
    c0_external_sha256: str
    c0_report_sha256: str
    c0_execution_git: str
    full_external_sha256: str
    full_report_sha256: str
    full_execution_git: str
    codex_binary_sha256: str
    codex_version: str
    python_binary_sha256: str
    python_version: str
    tool_script_sha256: str
    sol0_external_sha256: str
    sol0_report_sha256: str
    sol0_execution_git: str
    sol0_design_sha256: str
    namespace: str = DEV_NAMESPACE
    planner_model: str = MODEL

    def __post_init__(self) -> None:
        for name in (
                "seed_commitment_sha256", "native_sha256",
                "c0_external_sha256", "c0_report_sha256",
                "full_external_sha256", "full_report_sha256",
                "codex_binary_sha256", "python_binary_sha256",
                "tool_script_sha256", "sol0_external_sha256",
                "sol0_report_sha256", "sol0_design_sha256"):
            _strict_sha(getattr(self, name), name.replace("_", " "))
        for name in ("execution_git", "c0_execution_git",
                     "full_execution_git", "sol0_execution_git"):
            _strict_sha(getattr(self, name), name.replace("_", " "),
                        length=40)
        if self.hostname != full.MINI_HOSTNAME:
            raise PrivilegedTeacherLuna0Error("Luna0 execution hostname drift")
        if (type(self.codex_version) is not str or not self.codex_version
                or len(self.codex_version) > 128
                or type(self.python_version) is not str
                or not self.python_version or len(self.python_version) > 256):
            raise PrivilegedTeacherLuna0Error("runtime version drift")
        if self.namespace != DEV_NAMESPACE:
            raise PrivilegedTeacherLuna0Error("Luna0 namespace drift")
        if self.planner_model != MODEL:
            raise PrivilegedTeacherLuna0Error("Luna0 model identity drift")
        Luna0PlannerConfig(model=self.planner_model)

    @property
    def root_coordinates(self) -> tuple[tuple[str, int, int], ...]:
        return tuple((rank, banker, 0)
                     for rank in RANKS for banker in full.BANKER_SEATS)

    def payload(self) -> dict[str, object]:
        return {
            "schema": DESIGN_SCHEMA,
            "namespace": self.namespace,
            "seed_commitment_sha256": self.seed_commitment_sha256,
            "execution_git": self.execution_git,
            "native_sha256": self.native_sha256,
            "hostname": self.hostname,
            "c0_external_sha256": self.c0_external_sha256,
            "c0_report_sha256": self.c0_report_sha256,
            "c0_execution_git": self.c0_execution_git,
            "full_external_sha256": self.full_external_sha256,
            "full_report_sha256": self.full_report_sha256,
            "full_execution_git": self.full_execution_git,
            "codex_binary_sha256": self.codex_binary_sha256,
            "codex_version": self.codex_version,
            "python_binary_sha256": self.python_binary_sha256,
            "python_version": self.python_version,
            "tool_script_sha256": self.tool_script_sha256,
            "sol0_external_sha256": self.sol0_external_sha256,
            "sol0_report_sha256": self.sol0_report_sha256,
            "sol0_execution_git": self.sol0_execution_git,
            "sol0_design_sha256": self.sol0_design_sha256,
            "model": self.planner_model,
            "prompt_template_sha256": sol0.PLANNER_PROMPT_TEMPLATE_SHA256,
            "planner_config": Luna0PlannerConfig(
                model=self.planner_model).payload(),
            "root_count": len(self.root_coordinates),
            "record_count": len(self.root_coordinates) * len(ROLES),
            "roles": list(ROLES),
            "trump_ranks": list(RANKS),
            "banker_seats": list(full.BANKER_SEATS),
            "authority": dict(AUTHORITY),
            "token_comparison": TOKEN_COMPARISON_STATUS,
            "wall_comparison": WALL_COMPARISON_STATUS,
        }


def _sol_design(payload: Mapping[str, object]) -> sol_report.Sol0Design:
    try:
        return sol_report.Sol0Design(
            seed_commitment_sha256=payload["seed_commitment_sha256"],
            execution_git=payload["execution_git"],
            native_sha256=payload["native_sha256"],
            hostname=payload["hostname"],
            c0_external_sha256=payload["c0_external_sha256"],
            c0_report_sha256=payload["c0_report_sha256"],
            c0_execution_git=payload["c0_execution_git"],
            full_external_sha256=payload["full_external_sha256"],
            full_report_sha256=payload["full_report_sha256"],
            full_execution_git=payload["full_execution_git"],
            codex_binary_sha256=payload["codex_binary_sha256"],
            codex_version=payload["codex_version"],
            python_binary_sha256=payload["python_binary_sha256"],
            python_version=payload["python_version"],
            tool_script_sha256=payload["tool_script_sha256"],
            namespace=sol_report.DEV_NAMESPACE,
        )
    except (KeyError, TypeError, sol0.PrivilegedTeacherSol0Error) as exc:
        raise PrivilegedTeacherLuna0Error("Sol0 design drift") from exc


def _parent_maps(c0_report: Mapping[str, object],
                 sol0_report: Mapping[str, object]) -> tuple[dict, dict]:
    try:
        return c0._parent_records(c0_report), {
            (row["trump_rank"], row["banker"], row["replicate"], row["role"]): row
            for row in sol0_report["records"]
        }
    except (KeyError, TypeError):
        raise PrivilegedTeacherLuna0Error("parent record population drift")


def validate_sol_report(
        design: Luna0Design, *, sol0_report: dict[str, object],
        sol0_external_sha256: str, c0_report: dict[str, object],
        c0_external_sha256: str, full_report: dict[str, object],
        full_external_sha256: str) -> None:
    """Validate the sealed Sol0 artifact and exact public pairing identity."""
    if _sha_bytes(canonical_json_bytes(sol0_report)) != sol0_external_sha256:
        raise PrivilegedTeacherLuna0Error("Sol0 external identity drift")
    payload = sol0_report.get("design")
    if type(payload) is not dict:
        raise PrivilegedTeacherLuna0Error("Sol0 design drift")
    sol_design = _sol_design(payload)
    if (sol0_external_sha256 != design.sol0_external_sha256
            or sol0_report.get("report_sha256") != design.sol0_report_sha256
            or sol_design.execution_git != design.sol0_execution_git
            or _sha(payload) != design.sol0_design_sha256
            or payload.get("model") != sol0.MODEL
            or sol_design.seed_commitment_sha256 != design.seed_commitment_sha256
            or sol_design.native_sha256 != design.native_sha256
            or sol_design.hostname != design.hostname
            or sol_design.c0_external_sha256 != design.c0_external_sha256
            or sol_design.c0_report_sha256 != design.c0_report_sha256
            or sol_design.c0_execution_git != design.c0_execution_git
            or sol_design.full_external_sha256 != design.full_external_sha256
            or sol_design.full_report_sha256 != design.full_report_sha256
            or sol_design.full_execution_git != design.full_execution_git
            or sol_design.codex_binary_sha256 != design.codex_binary_sha256
            or sol_design.codex_version != design.codex_version
            or sol_design.python_binary_sha256 != design.python_binary_sha256
            or sol_design.python_version != design.python_version
            or sol_design.tool_script_sha256 != design.tool_script_sha256):
        raise PrivilegedTeacherLuna0Error("Sol0 paired design identity drift")
    try:
        sol_report.validate_report(
            sol0_report, sol_design, c0_report=c0_report,
            c0_external_sha256=c0_external_sha256,
            full_report=full_report,
            full_external_sha256=full_external_sha256)
    except (sol0.PrivilegedTeacherSol0Error, KeyError, TypeError) as exc:
        raise PrivilegedTeacherLuna0Error("Sol0 public report refused") from exc
    if sol_design.root_coordinates != design.root_coordinates:
        raise PrivilegedTeacherLuna0Error("Sol0 coordinate population drift")
    expected = {(*coordinate, role) for coordinate in design.root_coordinates
                for role in ROLES}
    _require_sol0_population(sol0_report, expected)
    _require_complete_sol_report(sol0_report, expected_count=len(expected))


def _require_sol0_population(
        sol0_report: Mapping[str, object],
        expected: set[tuple[str, int, int, str]]) -> None:
    records = sol0_report.get("records")
    if type(records) is not list:
        raise PrivilegedTeacherLuna0Error("Sol0 paired role population drift")
    try:
        actual = {(row["trump_rank"], row["banker"], row["replicate"],
                   row["role"]) for row in records}
    except (KeyError, TypeError):
        raise PrivilegedTeacherLuna0Error("Sol0 paired role population drift")
    if actual != expected or len(records) != len(expected):
        raise PrivilegedTeacherLuna0Error("Sol0 paired role population drift")


def _require_complete_sol_report(sol0_report: Mapping[str, object], *,
                                 expected_count: int = 52) -> None:
    """Luna cannot start unless every paired Sol0 role is sealed complete."""
    records = sol0_report.get("records")
    if (sol0_report.get("status") != "COMPLETE"
            or sol0_report.get("completed_record_count") != expected_count
            or sol0_report.get("incomplete_record_count") != 0
            or type(records) is not list or len(records) != expected_count
            or any(type(row) is not dict or row.get("status") != "COMPLETE"
                   for row in records)):
        raise PrivilegedTeacherLuna0Error("Sol0 parent is not complete")


def _sol_tokens(outcome: object) -> int | None:
    if type(outcome) is not dict:
        return None
    value = outcome.get("model_reported_tokens")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PrivilegedTeacherLuna0Error("model token receipt drift")
    return value


def _sol_wall(outcome: object) -> int | None:
    if type(outcome) is not dict:
        return None
    value = outcome.get("model_wall_milliseconds")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PrivilegedTeacherLuna0Error("model wall receipt drift")
    return value


def _luna_outcome(payload: Mapping[str, object]) -> dict[str, object]:
    """Copy only Sol0's already-public outcome fields into Luna's namespace."""
    result = dict(payload)
    result["schema"] = "privileged-teacher-luna0-outcome-v1"
    result["model_reported_tokens"] = _sol_tokens(payload)
    return result


def _validate_outcome(payload: object, *, banker: int,
                      treatment_team: int) -> None:
    if type(payload) is not dict or set(payload) != {
            "schema", "attacker_points", "signed_level_utility",
            "decision_count", "telemetry", "continuation_counts",
            "confidence_counts", "opponent_work", "transcript_sha256",
            "model_output_sha256", "model_exit_code",
            "model_wall_milliseconds", "model_reported_tokens"}:
        raise PrivilegedTeacherLuna0Error("Luna0 outcome schema drift")
    tokens = payload["model_reported_tokens"]
    if (tokens is not None and
            (isinstance(tokens, bool) or not isinstance(tokens, int)
             or tokens < 0)):
        raise PrivilegedTeacherLuna0Error("model token receipt drift")
    base = dict(payload)
    base.pop("schema")
    base.pop("model_reported_tokens")
    base["schema"] = sol0.OUTCOME_SCHEMA
    try:
        sol_report._validate_outcome(base, banker=banker,
                                     treatment_team=treatment_team)
    except sol0.PrivilegedTeacherSol0Error as exc:
        raise PrivilegedTeacherLuna0Error("Luna0 outcome identity drift") from exc


def _fraction(values: list[int]) -> dict[str, int]:
    value = Fraction(sum(values), len(values))
    return {"numerator": value.numerator, "denominator": value.denominator}


def _token_summary(rows: list[dict[str, object]], key: str) -> dict[str, object]:
    values = [row[key]["model_reported_tokens"] for row in rows
              if row[key]["model_reported_tokens"] is not None]
    return {"n": len(values), "total": sum(values),
            "mean": _fraction(values) if values else None}


def _wall_summary(rows: list[dict[str, object]], key: str) -> dict[str, object]:
    values = [row[key]["model_wall_milliseconds"] for row in rows]
    return {"n": len(values), "total": sum(values),
            "mean": _fraction(values) if values else None}


def _summaries(records: list[dict[str, object]]) -> dict[str, object]:
    complete = [row for row in records if row["status"] == "COMPLETE"]

    def contrast(rows: list[dict[str, object]], name: str) -> dict[str, object]:
        values = [row["contrasts"][name] for row in rows]
        return {"n": len(values), "mean": _fraction(values) if values else None,
                "positive_count": sum(value > 0 for value in values),
                "zero_count": sum(value == 0 for value in values),
                "negative_count": sum(value < 0 for value in values)}

    luna_tokens = _token_summary(complete, "luna0")
    sol_tokens = _token_summary(complete, "sol0")
    luna_wall = _wall_summary(complete, "luna0")
    sol_wall = _wall_summary(complete, "sol0")
    wall_ratio = {"numerator": luna_wall["total"],
                  "denominator": sol_wall["total"]} if complete else None
    ratio = None
    if luna_tokens["n"] == len(complete) and sol_tokens["n"] == len(complete):
        ratio = {"numerator": luna_tokens["total"],
                 "denominator": sol_tokens["total"]}
    return {
        "contrasts": {name: contrast(complete, name) for name in CONTRASTS},
        "by_role": {role: {name: contrast(
            [row for row in complete if row["role"] == role], name)
            for name in CONTRASTS} for role in ROLES},
        "by_rank": {rank: {name: contrast(
            [row for row in complete if row["trump_rank"] == rank], name)
            for name in CONTRASTS} for rank in RANKS},
        "telemetry_totals": {
            field: sum(row["luna0"]["telemetry"][field] for row in complete)
            for field in sol0.PUBLIC_TELEMETRY_FIELDS},
        "continuation_totals": {
            name: sum(row["luna0"]["continuation_counts"][name]
                      for row in complete) for name in sol0.CONTINUATIONS},
        "confidence_totals": {
            name: sum(row["luna0"]["confidence_counts"][name]
                      for row in complete) for name in sol0.CONFIDENCE_LEVELS},
        "efficiency": {
            "luna_reported_tokens": luna_tokens,
            "sol_reported_tokens": sol_tokens,
            "luna_to_sol_token_ratio": ratio,
            "token_comparison": TOKEN_COMPARISON_STATUS,
            "candidate": None,
            "wall_milliseconds": {
                "luna": luna_wall, "sol": sol_wall,
                "luna_to_sol_ratio": wall_ratio,
                "comparison": WALL_COMPARISON_STATUS,
            },
        },
    }


def _record_payload(*, coordinate: tuple[str, int, int], role: str,
                    parent: Mapping[str, object], sol_row: Mapping[str, object],
                    outcome: Mapping[str, object] | None,
                    private_evidence_sha256: str,
                    failure_sha256: str | None = None) -> dict[str, object]:
    _strict_sha(private_evidence_sha256, "private evidence")
    if role not in ROLES:
        raise PrivilegedTeacherLuna0Error("Luna0 role drift")
    anchors = {name: sol_report._anchor(parent, name)
               for name in ("A", "B", "C0-S")}
    sol_payload = sol_row.get("sol0")
    sol_public = {
        "signed_level_utility": sol_payload["signed_level_utility"]
        if type(sol_payload) is dict else None,
        "model_reported_tokens": _sol_tokens(sol_payload),
        "model_wall_milliseconds": _sol_wall(sol_payload),
    }
    if outcome is None:
        _strict_sha(failure_sha256, "failure identity")
        luna = None
        contrasts = None
        status = "INCOMPLETE"
    else:
        if failure_sha256 is not None:
            raise PrivilegedTeacherLuna0Error("completed record failure drift")
        luna = dict(outcome)
        contrasts = {
            "luna0_minus_sol0": luna["signed_level_utility"] -
            sol_public["signed_level_utility"],
            "luna0_minus_a": luna["signed_level_utility"] -
            anchors["A"]["signed_level_utility"],
            "luna0_minus_b": luna["signed_level_utility"] -
            anchors["B"]["signed_level_utility"],
            "luna0_minus_c0_s": luna["signed_level_utility"] -
            anchors["C0-S"]["signed_level_utility"],
        }
        status = "COMPLETE"
    rank, banker, replicate = coordinate
    body = {
        "schema": RECORD_SCHEMA, "status": status,
        "trump_rank": rank, "banker": banker, "replicate": replicate,
        "role": role, "treatment_team": parent["treatment_team"],
        "root_sha256": parent["root_sha256"],
        "parent_c0_record_sha256": parent["record_sha256"],
        "parent_sol0_record_sha256": sol_row["record_sha256"],
        "anchors": anchors, "sol0": sol_public, "luna0": luna,
        "contrasts": contrasts, "private_evidence_sha256": private_evidence_sha256,
        "failure_sha256": failure_sha256, "authority": dict(AUTHORITY),
    }
    return {**body, "record_sha256": _sha(body)}


def _validate_source_population(
        records: list[dict[str, object]], design: Luna0Design) -> None:
    expected = {(*coordinate, role) for coordinate in design.root_coordinates
                for role in ROLES}
    seen = set()
    for row in records:
        if type(row) is not dict:
            raise PrivilegedTeacherLuna0Error("Luna0 worker population drift")
        try:
            key = (row["trump_rank"], row["banker"], row["replicate"],
                   row["role"])
        except KeyError as exc:
            raise PrivilegedTeacherLuna0Error(
                "Luna0 worker population drift") from exc
        if key not in expected or key in seen:
            raise PrivilegedTeacherLuna0Error("Luna0 worker population drift")
        seen.add(key)
    if seen != expected:
        raise PrivilegedTeacherLuna0Error("Luna0 worker population drift")


def run_dev(
        design: Luna0Design, *, c0_report: dict[str, object],
        c0_external_sha256: str, full_report: dict[str, object],
        full_external_sha256: str, sol0_report: dict[str, object],
        sol0_external_sha256: str, seed_secret: bytes, private_root: Path,
        tool_script: Path, codex_binary: Path, workers: int = 2,
        planner_process: sol0.PlannerProcess | None = None,
        progress_sink: Callable[[dict[str, object]], object] | None = None) \
        -> dict[str, object]:
    if workers != 2:
        raise PrivilegedTeacherLuna0Error("Luna0 requires exactly two workers")
    validate_sol_report(
        design, sol0_report=sol0_report,
        sol0_external_sha256=sol0_external_sha256,
        c0_report=c0_report, c0_external_sha256=c0_external_sha256,
        full_report=full_report, full_external_sha256=full_external_sha256)
    if (_sha_bytes(seed_secret) != design.seed_commitment_sha256
            or _sha_bytes(tool_script.read_bytes()) != design.tool_script_sha256
            or _sha_bytes(codex_binary.resolve().read_bytes()) != design.codex_binary_sha256
            or _sha_bytes(Path(sys.executable).resolve().read_bytes()) != design.python_binary_sha256
            or sys.version != design.python_version
            or platform.node() != design.hostname):
        raise PrivilegedTeacherLuna0Error("Luna0 input binding drift")
    codex_version = subprocess.run(
        (str(codex_binary.resolve()), "--version"), check=True,
        capture_output=True, text=True).stdout.strip()
    private_stat = private_root.stat() if private_root.exists() else None
    if (codex_version != design.codex_version or private_stat is None
            or not stat.S_ISDIR(private_stat.st_mode)
            or private_root.is_symlink() or private_stat.st_uid != os.getuid()
            or stat.S_IMODE(private_stat.st_mode) != 0o700
            or any(private_root.iterdir())):
        raise PrivilegedTeacherLuna0Error("private evidence root not empty")
    sol_design = _sol_design(sol0_report["design"])
    full_design = sol_report.validate_parents(
        sol_design, c0_report=c0_report,
        c0_external_sha256=c0_external_sha256, full_report=full_report,
        full_external_sha256=full_external_sha256)
    c0_records, sol_records = _parent_maps(c0_report, sol0_report)
    started = time.monotonic()
    coordinates = design.root_coordinates
    completed: dict[tuple[str, int, int], tuple[dict[str, object], ...]] = {}
    progress_lock = threading.Lock()
    completed_records = 0

    def publish_role() -> None:
        nonlocal completed_records
        with progress_lock:
            completed_records += 1
            done = completed_records
            total = len(coordinates) * len(ROLES)
            elapsed = time.monotonic() - started
            if progress_sink is not None:
                progress_sink({"stage": "role_rounds", "completed_records": done,
                               "total_records": total,
                               "percent_basis_points": done * 10_000 // total,
                               "elapsed_seconds": elapsed,
                               "eta_seconds": max(0.0, elapsed * (total - done) / done)})

    kwargs = {
        "full_design": full_design, "c0_records": c0_records,
        "seed_secret": seed_secret, "private_root": private_root,
        "tool_script": tool_script, "codex_binary": codex_binary,
        "planner_process": planner_process,
        "planner_config": Luna0PlannerConfig(),
        "role_completed": publish_role,
    }
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(sol_report._run_root,
                               coordinate=coordinate, **kwargs): coordinate
                   for coordinate in coordinates}
        for future in as_completed(futures):
            completed[futures[future]] = future.result()
    source = {"records": [row for coordinate in coordinates
                           for row in completed[coordinate]],
              "elapsed_seconds": time.monotonic() - started}
    _validate_source_population(source["records"], design)
    rows = []
    for source_row in source["records"]:
        key = (source_row["trump_rank"], source_row["banker"],
               source_row["replicate"], source_row["role"])
        parent = c0_records[key]
        sol_row = sol_records[key]
        if source_row["status"] == "COMPLETE" and sol_row["status"] == "COMPLETE":
            outcome = _luna_outcome(source_row["sol0"])
            failure = None
        else:
            outcome = None
            failure = source_row.get("failure_sha256")
            if source_row["status"] != "INCOMPLETE":
                raise PrivilegedTeacherLuna0Error("Luna0 source status drift")
        rows.append(_record_payload(
            coordinate=key[:3], role=key[3], parent=parent, sol_row=sol_row,
            outcome=outcome,
            private_evidence_sha256=source_row["private_evidence_sha256"],
            failure_sha256=failure or source_row.get("failure_sha256")))
    complete = sum(row["status"] == "COMPLETE" for row in rows)
    body = {
        "schema": SCHEMA,
        "status": "COMPLETE" if complete == len(rows) else "INCOMPLETE",
        "design": design.payload(), "completed_record_count": complete,
        "incomplete_record_count": len(rows) - complete,
        "refusal_count": len(rows) - complete, "records": rows,
        "summaries": _summaries(rows),
        "elapsed_seconds": source["elapsed_seconds"],
        "authority": dict(AUTHORITY),
    }
    return {**body, "report_sha256": _sha(body)}


_FORBIDDEN_PUBLIC_KEYS = {
    "hands", "hands_by_seat", "buried", "hidden_burial", "events",
    "hidden_cards", "burial", "model_output", "model_stdout", "model_final",
    "private_output", "raw_seed", "seed_secret", "completion_token",
    "candidates", "prompt",
}


def _check_public(value: object) -> None:
    if type(value) is dict:
        if set(value) & _FORBIDDEN_PUBLIC_KEYS:
            raise PrivilegedTeacherLuna0Error("Luna0 public leakage")
        for item in value.values():
            _check_public(item)
    elif type(value) is list:
        for item in value:
            _check_public(item)


def validate_report(
        report: dict[str, object], design: Luna0Design, *,
        c0_report: dict[str, object], c0_external_sha256: str,
        full_report: dict[str, object], full_external_sha256: str,
        sol0_report: dict[str, object], sol0_external_sha256: str) -> None:
    validate_sol_report(
        design, sol0_report=sol0_report,
        sol0_external_sha256=sol0_external_sha256, c0_report=c0_report,
        c0_external_sha256=c0_external_sha256, full_report=full_report,
        full_external_sha256=full_external_sha256)
    if type(report) is not dict or set(report) != {
            "schema", "status", "design", "completed_record_count",
            "incomplete_record_count", "refusal_count", "records", "summaries",
            "elapsed_seconds", "authority", "report_sha256"}:
        raise PrivilegedTeacherLuna0Error("Luna0 report schema drift")
    _check_public(report)
    body = {key: value for key, value in report.items() if key != "report_sha256"}
    records = report["records"]
    try:
        derived = _summaries(records) if type(records) is list else None
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise PrivilegedTeacherLuna0Error("Luna0 report summary drift") from exc
    if (report["schema"] != SCHEMA or report["design"] != design.payload()
            or type(records) is not list
            or len(records) != len(design.root_coordinates) * len(ROLES)
            or any(isinstance(report[name], bool)
                   or not isinstance(report[name], int) or report[name] < 0
                   for name in ("completed_record_count",
                                "incomplete_record_count", "refusal_count"))
            or report["status"] not in ("COMPLETE", "INCOMPLETE")
            or isinstance(report["elapsed_seconds"], bool)
            or not isinstance(report["elapsed_seconds"], (int, float))
            or not math.isfinite(report["elapsed_seconds"])
            or report["elapsed_seconds"] < 0
            or report["refusal_count"] != report["incomplete_record_count"]
            or report["authority"] != AUTHORITY
            or report["report_sha256"] != _sha(body)
            or report["summaries"] != derived):
        raise PrivilegedTeacherLuna0Error("Luna0 report identity drift")
    c0_records, sol_records = _parent_maps(c0_report, sol0_report)
    expected = {(*coordinate, role) for coordinate in design.root_coordinates
                for role in ROLES}
    seen = set(); complete = 0
    for record in records:
        if type(record) is not dict or set(record) != {
                "schema", "status", "trump_rank", "banker", "replicate",
                "role", "treatment_team", "root_sha256",
                "parent_c0_record_sha256", "parent_sol0_record_sha256",
                "anchors", "sol0", "luna0", "contrasts",
                "private_evidence_sha256", "failure_sha256", "authority",
                "record_sha256"}:
            raise PrivilegedTeacherLuna0Error("Luna0 record schema drift")
        if (type(record["trump_rank"]) is not str
                or isinstance(record["banker"], bool)
                or not isinstance(record["banker"], int)
                or isinstance(record["replicate"], bool)
                or not isinstance(record["replicate"], int)
                or type(record["role"]) is not str):
            raise PrivilegedTeacherLuna0Error("Luna0 coordinate identity drift")
        key = (record["trump_rank"], record["banker"], record["replicate"], record["role"])
        parent = c0_records.get(key); sol_row = sol_records.get(key)
        record_body = {k: v for k, v in record.items() if k != "record_sha256"}
        if (key not in expected or key in seen or type(parent) is not dict
                or type(sol_row) is not dict
                or record["schema"] != RECORD_SCHEMA
                or record["treatment_team"] != parent["treatment_team"]
                or record["root_sha256"] != parent["root_sha256"]
                or record["parent_c0_record_sha256"] != parent["record_sha256"]
                or record["parent_sol0_record_sha256"] != sol_row["record_sha256"]
                or record["anchors"] != {name: sol_report._anchor(parent, name)
                                           for name in ("A", "B", "C0-S")}
                or record["authority"] != AUTHORITY
                or record["record_sha256"] != _sha(record_body)):
            raise PrivilegedTeacherLuna0Error("Luna0 record identity drift")
        _strict_sha(record["private_evidence_sha256"], "private evidence")
        sol_payload = sol_row.get("sol0")
        expected_sol = {"signed_level_utility":
                        sol_payload["signed_level_utility"] if type(sol_payload) is dict else None,
                        "model_reported_tokens": _sol_tokens(sol_payload),
                        "model_wall_milliseconds": _sol_wall(sol_payload)}
        if record["sol0"] != expected_sol:
            raise PrivilegedTeacherLuna0Error("Sol0 paired utility drift")
        if record["status"] == "COMPLETE":
            if sol_row["status"] != "COMPLETE" or record["failure_sha256"] is not None:
                raise PrivilegedTeacherLuna0Error("Luna0 completion state drift")
            _validate_outcome(record["luna0"], banker=record["banker"],
                              treatment_team=record["treatment_team"])
            if record["contrasts"] != {
                    "luna0_minus_sol0": record["luna0"]["signed_level_utility"] - record["sol0"]["signed_level_utility"],
                    "luna0_minus_a": record["luna0"]["signed_level_utility"] - record["anchors"]["A"]["signed_level_utility"],
                    "luna0_minus_b": record["luna0"]["signed_level_utility"] - record["anchors"]["B"]["signed_level_utility"],
                    "luna0_minus_c0_s": record["luna0"]["signed_level_utility"] - record["anchors"]["C0-S"]["signed_level_utility"]}:
                raise PrivilegedTeacherLuna0Error("Luna0 contrast drift")
            complete += 1
        elif record["status"] == "INCOMPLETE":
            _strict_sha(record["failure_sha256"], "failure identity")
            if record["luna0"] is not None or record["contrasts"] is not None:
                raise PrivilegedTeacherLuna0Error("Luna0 incomplete state drift")
        else:
            raise PrivilegedTeacherLuna0Error("Luna0 record status drift")
        _check_public(record); seen.add(key)
    if (seen != expected or report["completed_record_count"] != complete
            or report["incomplete_record_count"] != len(records) - complete
            or report["refusal_count"] != len(records) - complete
            or report["status"] != ("COMPLETE" if complete == len(records) else "INCOMPLETE")):
        raise PrivilegedTeacherLuna0Error("Luna0 record population drift")


def report_bytes(report: dict[str, object], design: Luna0Design, *,
                 c0_report: dict[str, object], c0_external_sha256: str,
                 full_report: dict[str, object], full_external_sha256: str,
                 sol0_report: dict[str, object], sol0_external_sha256: str) -> bytes:
    validate_report(report, design, c0_report=c0_report,
                    c0_external_sha256=c0_external_sha256,
                    full_report=full_report, full_external_sha256=full_external_sha256,
                    sol0_report=sol0_report, sol0_external_sha256=sol0_external_sha256)
    return canonical_json_bytes(report)


__all__ = ["AUTHORITY", "CONTRASTS", "DESIGN_SCHEMA", "DEV_NAMESPACE",
           "LUNA_MODEL", "MODEL", "TOKEN_COMPARISON_STATUS",
           "WALL_COMPARISON_STATUS",
           "Luna0Design", "Luna0PlannerConfig", "PrivilegedTeacherLuna0Error",
           "report_bytes",
           "run_dev", "validate_report", "validate_sol_report"]

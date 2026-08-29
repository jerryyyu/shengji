"""Public report and parent bindings for the open-DEV PT-Sol0 diagnostic."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import math
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys
import threading
import time
from typing import Callable, Mapping

from ..engine.cards import RANKS
from . import privileged_teacher_c0 as c0
from . import privileged_teacher_full_ab as full
from .privileged_teacher_pt0 import canonical_json_bytes, signed_level_utility
from .privileged_teacher_sol0 import (
    CONFIDENCE_LEVELS,
    CONTINUATIONS,
    MAX_SESSION_WALL_SECONDS,
    MODEL,
    PLANNER_PROMPT_TEMPLATE_SHA256,
    PUBLIC_TELEMETRY_FIELDS,
    PlannerProcess,
    PrivilegedTeacherSol0Error,
    Sol0GameSession,
    Sol0Outcome,
    Sol0PlannerConfig,
    run_sol_session,
)


SCHEMA = "privileged-teacher-sol0-open-dev-v1"
RECORD_SCHEMA = "privileged-teacher-sol0-record-v1"
DESIGN_SCHEMA = "privileged-teacher-sol0-design-v1"
DEV_NAMESPACE = "privileged-teacher-sol0-open-dev-v1"
ROLES = full.ROLES
CONTRASTS = ("sol0_minus_a", "sol0_minus_b", "sol0_minus_c0_s")
AUTHORITY = dict(full.AUTHORITY)


def _sha(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _strict_sha(value: object, label: str, *, length: int = 64) -> str:
    if (type(value) is not str or len(value) != length
            or any(char not in "0123456789abcdef" for char in value)):
        raise PrivilegedTeacherSol0Error(f"{label} drift")
    return value


@dataclass(frozen=True)
class Sol0Design:
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
    namespace: str = DEV_NAMESPACE

    def __post_init__(self) -> None:
        for name in (
                "seed_commitment_sha256", "native_sha256",
                "c0_external_sha256", "c0_report_sha256",
                "full_external_sha256", "full_report_sha256",
                "codex_binary_sha256", "python_binary_sha256",
                "tool_script_sha256"):
            _strict_sha(getattr(self, name), name.replace("_", " "))
        for name in ("execution_git", "c0_execution_git",
                     "full_execution_git"):
            _strict_sha(getattr(self, name), name.replace("_", " "),
                        length=40)
        if self.hostname != full.MINI_HOSTNAME:
            raise PrivilegedTeacherSol0Error("Sol0 execution hostname drift")
        if (type(self.codex_version) is not str or not self.codex_version
                or len(self.codex_version) > 128
                or type(self.python_version) is not str
                or not self.python_version or len(self.python_version) > 256):
            raise PrivilegedTeacherSol0Error("runtime version drift")
        if self.namespace != DEV_NAMESPACE:
            raise PrivilegedTeacherSol0Error("Sol0 namespace drift")

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
            "model": MODEL,
            "prompt_template_sha256": PLANNER_PROMPT_TEMPLATE_SHA256,
            "planner_config": Sol0PlannerConfig().payload(),
            "root_count": len(self.root_coordinates),
            "record_count": len(self.root_coordinates) * len(ROLES),
            "roles": list(ROLES),
            "trump_ranks": list(RANKS),
            "banker_seats": list(full.BANKER_SEATS),
            "authority": dict(AUTHORITY),
        }


def _full_design(report: Mapping[str, object]) -> full.FullABDesign:
    payload = report.get("design")
    if type(payload) is not dict:
        raise PrivilegedTeacherSol0Error("PT-Full design drift")
    try:
        return full.FullABDesign(
            seed_commitment_sha256=payload["seed_commitment_sha256"],
            execution_git=payload["execution_git"],
            native_sha256=payload["native_sha256"],
            hostname=payload["hostname"],
            replicates=payload["replicates"],
            production_policy=payload["production_policy"],
            namespace=payload["namespace"],
        )
    except (KeyError, TypeError, full.PrivilegedTeacherFullABError) as exc:
        raise PrivilegedTeacherSol0Error("PT-Full design drift") from exc


def _c0_design(report: Mapping[str, object]) -> c0.C0Design:
    payload = report.get("design")
    if type(payload) is not dict:
        raise PrivilegedTeacherSol0Error("C0 design drift")
    try:
        return c0.C0Design(
            seed_commitment_sha256=payload["seed_commitment_sha256"],
            execution_git=payload["execution_git"],
            native_sha256=payload["native_sha256"],
            hostname=payload["hostname"],
            parent_external_sha256=payload["parent_external_sha256"],
            parent_report_sha256=payload["parent_report_sha256"],
            parent_execution_git=payload["parent_execution_git"],
            namespace=payload["namespace"],
        )
    except (KeyError, TypeError, c0.PrivilegedTeacherC0Error) as exc:
        raise PrivilegedTeacherSol0Error("C0 design drift") from exc


def validate_parents(
        design: Sol0Design, *, c0_report: dict[str, object],
        c0_external_sha256: str, full_report: dict[str, object],
        full_external_sha256: str) -> full.FullABDesign:
    if (_sha_bytes(canonical_json_bytes(c0_report)) != c0_external_sha256
            or _sha_bytes(canonical_json_bytes(full_report)) !=
            full_external_sha256):
        raise PrivilegedTeacherSol0Error("parent canonical identity drift")
    c0_design = _c0_design(c0_report)
    full_design = _full_design(full_report)
    try:
        c0.validate_report(
            c0_report, c0_design, full_report,
            parent_external_sha256=full_external_sha256)
    except c0.PrivilegedTeacherC0Error as exc:
        raise PrivilegedTeacherSol0Error("Sol0 parent report refused") from exc
    if (c0_external_sha256 != design.c0_external_sha256
            or c0_report.get("report_sha256") != design.c0_report_sha256
            or c0_design.execution_git != design.c0_execution_git
            or full_external_sha256 != design.full_external_sha256
            or full_report.get("report_sha256") != design.full_report_sha256
            or full_design.execution_git != design.full_execution_git
            or c0_design.parent_external_sha256 != full_external_sha256
            or c0_design.parent_report_sha256 !=
            full_report.get("report_sha256")
            or c0_design.seed_commitment_sha256 !=
            design.seed_commitment_sha256
            or full_design.seed_commitment_sha256 !=
            design.seed_commitment_sha256
            or c0_design.native_sha256 != design.native_sha256
            or full_design.native_sha256 != design.native_sha256
            or c0_design.hostname != design.hostname
            or full_design.hostname != design.hostname
            or c0_design.root_coordinates != design.root_coordinates
            or full_design.root_coordinates != design.root_coordinates):
        raise PrivilegedTeacherSol0Error("Sol0 parent identity drift")
    return full_design


def _anchor(parent: Mapping[str, object], name: str) -> dict[str, int]:
    if name in ("A", "B"):
        source = parent.get("anchors")
    elif name == "C0-S":
        source = parent.get("arms")
    else:
        raise PrivilegedTeacherSol0Error("Sol0 anchor name drift")
    row = source.get(name) if type(source) is dict else None
    if type(row) is not dict:
        raise PrivilegedTeacherSol0Error("Sol0 anchor drift")
    points = row.get("attacker_points")
    utility = row.get("signed_level_utility")
    if (isinstance(points, bool) or not isinstance(points, int) or points < 0
            or isinstance(utility, bool) or not isinstance(utility, int)):
        raise PrivilegedTeacherSol0Error("Sol0 anchor drift")
    return {"attacker_points": points, "signed_level_utility": utility}


def _record_payload(
        *, coordinate: tuple[str, int, int], role: str,
        parent: Mapping[str, object], outcome: Sol0Outcome | None,
        private_evidence_sha256: str, failure_sha256: str | None = None) \
        -> dict[str, object]:
    rank, banker, replicate = coordinate
    _strict_sha(private_evidence_sha256, "private evidence")
    if role not in ROLES:
        raise PrivilegedTeacherSol0Error("Sol0 role drift")
    anchors = {name: _anchor(parent, name) for name in ("A", "B", "C0-S")}
    if outcome is None:
        _strict_sha(failure_sha256, "failure identity")
        sol = None
        contrasts = None
        status = "INCOMPLETE"
    else:
        if failure_sha256 is not None:
            raise PrivilegedTeacherSol0Error("completed record failure drift")
        sol = outcome.payload()
        contrasts = {
            "sol0_minus_a": outcome.signed_level_utility -
            anchors["A"]["signed_level_utility"],
            "sol0_minus_b": outcome.signed_level_utility -
            anchors["B"]["signed_level_utility"],
            "sol0_minus_c0_s": outcome.signed_level_utility -
            anchors["C0-S"]["signed_level_utility"],
        }
        status = "COMPLETE"
    body = {
        "schema": RECORD_SCHEMA,
        "status": status,
        "trump_rank": rank,
        "banker": banker,
        "replicate": replicate,
        "role": role,
        "treatment_team": parent["treatment_team"],
        "root_sha256": parent["root_sha256"],
        "parent_c0_record_sha256": parent["record_sha256"],
        "anchors": anchors,
        "sol0": sol,
        "contrasts": contrasts,
        "private_evidence_sha256": private_evidence_sha256,
        "failure_sha256": failure_sha256,
        "authority": dict(AUTHORITY),
    }
    return {**body, "record_sha256": _sha(body)}


def _run_role(
        *, parent: Mapping[str, object], seed_secret: bytes,
        coordinate: tuple[str, int, int], role: str, root,
        private_root: Path, tool_script: Path, codex_binary: Path,
        planner_process: PlannerProcess | None,
        planner_config: Sol0PlannerConfig) -> dict[str, object]:
    rank, banker, replicate = coordinate
    treatment_team = banker % 2 if role == "banker-team" \
        else 1 - banker % 2
    private_path = private_root / (
        f"rank-{rank}-banker-{banker}-replicate-{replicate}-{role}.json")
    session = Sol0GameSession(
        root, treatment_team=treatment_team, seed_secret=seed_secret,
        coordinate=coordinate, role=role, config=planner_config)
    outcome: Sol0Outcome | None = None
    failure_sha256: str | None = None
    try:
        outcome = run_sol_session(
            session, private_output=private_path, tool_script=tool_script,
            planner_process=planner_process, codex_binary=codex_binary)
    except PrivilegedTeacherSol0Error as exc:
        if not private_path.is_file():
            raise
        failure_sha256 = _sha({
            "schema": "privileged-teacher-sol0-failure-v1",
            "message": str(exc),
        })
    private_raw = private_path.read_bytes()
    return _record_payload(
        coordinate=coordinate, role=role, parent=parent, outcome=outcome,
        private_evidence_sha256=_sha_bytes(private_raw),
        failure_sha256=failure_sha256)


def _run_root(
        *, full_design: full.FullABDesign,
        c0_records: Mapping[tuple[str, int, int, str], dict[str, object]],
        seed_secret: bytes, coordinate: tuple[str, int, int],
        private_root: Path, tool_script: Path, codex_binary: Path,
        planner_process: PlannerProcess | None,
        planner_config: Sol0PlannerConfig,
        role_completed: Callable[[], object] | None = None) \
        -> tuple[dict[str, object], ...]:
    rank, banker, replicate = coordinate
    root = full._build_root(full_design, seed_secret, *coordinate)
    root_sha256 = full._root_sha256(root)
    parents = {role: c0_records.get((*coordinate, role)) for role in ROLES}
    # Bind every role before the first external model is invoked.
    if any(type(parent) is not dict
           or parent.get("root_sha256") != root_sha256
           for parent in parents.values()):
        raise PrivilegedTeacherSol0Error("reconstructed C0 root drift")
    records = []
    for role in ROLES:
        records.append(_run_role(
            parent=parents[role], seed_secret=seed_secret,
            coordinate=coordinate, role=role, root=root,
            private_root=private_root, tool_script=tool_script,
            codex_binary=codex_binary,
            planner_process=planner_process,
            planner_config=planner_config))
        if role_completed is not None:
            role_completed()
    return tuple(records)


def _fraction(values: list[int]) -> dict[str, int]:
    value = Fraction(sum(values), len(values))
    return {"numerator": value.numerator, "denominator": value.denominator}


def _summaries(records: list[dict[str, object]]) -> dict[str, object]:
    complete = [row for row in records if row["status"] == "COMPLETE"]
    def contrast(rows: list[dict[str, object]], name: str) -> dict[str, object]:
        values = [row["contrasts"][name] for row in rows]
        return {
            "n": len(values),
            "mean": _fraction(values) if values else None,
            "positive_count": sum(value > 0 for value in values),
            "zero_count": sum(value == 0 for value in values),
            "negative_count": sum(value < 0 for value in values),
        }
    return {
        "contrasts": {name: contrast(complete, name) for name in CONTRASTS},
        "by_role": {
            role: {name: contrast(
                [row for row in complete if row["role"] == role], name)
                   for name in CONTRASTS}
            for role in ROLES
        },
        "by_rank": {
            rank: {name: contrast(
                [row for row in complete if row["trump_rank"] == rank], name)
                   for name in CONTRASTS}
            for rank in RANKS
        },
        "telemetry_totals": {
            field: sum(row["sol0"]["telemetry"][field] for row in complete)
            for field in PUBLIC_TELEMETRY_FIELDS
        },
        "continuation_totals": {
            name: sum(row["sol0"]["continuation_counts"][name]
                      for row in complete)
            for name in CONTINUATIONS
        },
        "confidence_totals": {
            name: sum(row["sol0"]["confidence_counts"][name]
                      for row in complete)
            for name in CONFIDENCE_LEVELS
        },
    }


def run_dev(
        design: Sol0Design, *, c0_report: dict[str, object],
        c0_external_sha256: str, full_report: dict[str, object],
        full_external_sha256: str, seed_secret: bytes,
        private_root: Path, tool_script: Path, workers: int = 2,
        codex_binary: Path,
        planner_process: PlannerProcess | None = None,
        progress_sink: Callable[[dict[str, object]], object] | None = None) \
        -> dict[str, object]:
    if workers not in (1, 2):
        raise PrivilegedTeacherSol0Error("Sol0 workers drift")
    private_stat = private_root.stat() if private_root.exists() else None
    if (_sha_bytes(seed_secret) != design.seed_commitment_sha256
            or _sha_bytes(tool_script.read_bytes()) !=
            design.tool_script_sha256
            or _sha_bytes(codex_binary.resolve().read_bytes()) !=
            design.codex_binary_sha256
            or _sha_bytes(Path(sys.executable).resolve().read_bytes()) !=
            design.python_binary_sha256
            or sys.version != design.python_version
            or platform.node() != design.hostname):
        raise PrivilegedTeacherSol0Error("Sol0 input binding drift")
    codex_version = subprocess.run(
        (str(codex_binary.resolve()), "--version"), check=True,
        capture_output=True, text=True).stdout.strip()
    if (codex_version != design.codex_version
            or private_stat is None
            or not stat.S_ISDIR(private_stat.st_mode)
            or private_root.is_symlink()
            or private_stat.st_uid != os.getuid()
            or stat.S_IMODE(private_stat.st_mode) != 0o700
            or any(private_root.iterdir())):
        raise PrivilegedTeacherSol0Error("private evidence root not empty")
    full_design = validate_parents(
        design, c0_report=c0_report,
        c0_external_sha256=c0_external_sha256,
        full_report=full_report,
        full_external_sha256=full_external_sha256)
    c0_records = c0._parent_records(c0_report)
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
                progress_sink({
                    "stage": "role_rounds",
                    "completed_records": done,
                    "total_records": total,
                    "percent_basis_points": done * 10_000 // total,
                    "elapsed_seconds": elapsed,
                    "eta_seconds": max(
                        0.0, elapsed * (total - done) / done),
                })

    kwargs = {
        "full_design": full_design, "c0_records": c0_records,
        "seed_secret": seed_secret,
        "private_root": private_root, "tool_script": tool_script,
        "codex_binary": codex_binary,
        "planner_process": planner_process,
        "planner_config": Sol0PlannerConfig(),
        "role_completed": publish_role,
    }
    if workers == 1:
        for coordinate in coordinates:
            completed[coordinate] = _run_root(
                coordinate=coordinate, **kwargs)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(
                _run_root, coordinate=coordinate, **kwargs): coordinate
                for coordinate in coordinates}
            for future in as_completed(futures):
                coordinate = futures[future]
                completed[coordinate] = future.result()
    records = [row for coordinate in coordinates
               for row in completed[coordinate]]
    complete_count = sum(row["status"] == "COMPLETE" for row in records)
    body = {
        "schema": SCHEMA,
        "status": "COMPLETE" if complete_count == len(records)
        else "INCOMPLETE",
        "design": design.payload(),
        "completed_record_count": complete_count,
        "incomplete_record_count": len(records) - complete_count,
        "records": records,
        "summaries": _summaries(records),
        "elapsed_seconds": time.monotonic() - started,
        "authority": dict(AUTHORITY),
    }
    return {**body, "report_sha256": _sha(body)}


def _validate_outcome(payload: object, *, banker: int,
                      treatment_team: int) -> None:
    if type(payload) is not dict or set(payload) != {
            "schema", "attacker_points", "signed_level_utility",
            "decision_count", "telemetry", "continuation_counts",
            "confidence_counts", "opponent_work", "transcript_sha256",
            "model_output_sha256", "model_exit_code",
            "model_wall_milliseconds"}:
        raise PrivilegedTeacherSol0Error("Sol0 outcome schema drift")
    telemetry = payload["telemetry"]
    continuations = payload["continuation_counts"]
    confidence = payload["confidence_counts"]
    work = payload["opponent_work"]
    points = payload["attacker_points"]
    if (payload["schema"] != "privileged-teacher-sol0-outcome-v1"
            or isinstance(points, bool) or not isinstance(points, int)
            or points < 0 or isinstance(payload["decision_count"], bool)
            or not isinstance(payload["decision_count"], int)
            or payload["decision_count"] < 1
            or type(telemetry) is not dict
            or set(telemetry) != set(PUBLIC_TELEMETRY_FIELDS)
            or any(isinstance(value, bool) or not isinstance(value, int)
                   or value < 0 for value in telemetry.values())
            or type(continuations) is not dict
            or set(continuations) != set(CONTINUATIONS)
            or any(isinstance(value, bool) or not isinstance(value, int)
                   or value < 0 for value in continuations.values())
            or type(confidence) is not dict
            or set(confidence) != set(CONFIDENCE_LEVELS)
            or any(isinstance(value, bool) or not isinstance(value, int)
                   or value < 0 for value in confidence.values())
            or type(work) is not dict or set(work) != set(full._WORK_FIELDS)
            or any(isinstance(value, bool) or not isinstance(value, int)
                   or value < 0 for value in work.values())
            or payload["signed_level_utility"] != signed_level_utility(
                points, banker_seat=banker, perspective_seat=treatment_team)
            or payload["model_exit_code"] != 0
            or isinstance(payload["model_wall_milliseconds"], bool)
            or not isinstance(payload["model_wall_milliseconds"], int)
            or not 0 <= payload["model_wall_milliseconds"] <=
            (MAX_SESSION_WALL_SECONDS + 5) * 1000
            or work["short_search_decisions"] != 0
            or work["zero_world_decisions"] != 0
            or work["sample_attempts"] !=
            work["accepted_worlds"] + work["failed_worlds"]
            or work["accepted_worlds"] != 330 * work["search_calls"]
            or work["rejected_worlds"] > work["failed_worlds"]
            or work["rollouts"] < 660 * work["search_calls"]
            or work["verified_rollouts"] != work["rollouts"]):
        raise PrivilegedTeacherSol0Error("Sol0 outcome identity drift")
    _strict_sha(payload["transcript_sha256"], "transcript")
    _strict_sha(payload["model_output_sha256"], "model output")
    if (telemetry["unique_rollouts"] != sum(continuations.values())
            or telemetry["contested_decisions"] != sum(confidence.values())
            or telemetry["treatment_decisions"] !=
            telemetry["forced_decisions"] +
            telemetry["contested_decisions"]
            or telemetry["selected_differs_from_candidate_zero"] >
            telemetry["contested_decisions"]
            or telemetry["selected_outside_production_ballot"] >
            telemetry["selected_differs_from_candidate_zero"]
            or telemetry["candidate_zero_selections"] +
            telemetry["selected_differs_from_candidate_zero"] !=
            telemetry["contested_decisions"]
            or telemetry["decisions_without_rollout"] >
            telemetry["contested_decisions"]):
        raise PrivilegedTeacherSol0Error("Sol0 outcome accounting drift")


def validate_report(
        report: dict[str, object], design: Sol0Design, *,
        c0_report: dict[str, object], c0_external_sha256: str,
        full_report: dict[str, object], full_external_sha256: str) -> None:
    validate_parents(
        design, c0_report=c0_report,
        c0_external_sha256=c0_external_sha256,
        full_report=full_report,
        full_external_sha256=full_external_sha256)
    if type(report) is not dict or set(report) != {
            "schema", "status", "design", "completed_record_count",
            "incomplete_record_count", "records", "summaries",
            "elapsed_seconds", "authority", "report_sha256"}:
        raise PrivilegedTeacherSol0Error("Sol0 report schema drift")
    records = report["records"]
    elapsed = report["elapsed_seconds"]
    body = {key: value for key, value in report.items()
            if key != "report_sha256"}
    try:
        derived_summaries = _summaries(records) if type(records) is list \
            else None
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise PrivilegedTeacherSol0Error(
            "Sol0 report summary drift") from exc
    if (report["schema"] != SCHEMA
            or report["status"] not in ("COMPLETE", "INCOMPLETE")
            or report["design"] != design.payload()
            or type(records) is not list
            or len(records) != len(design.root_coordinates) * len(ROLES)
            or isinstance(elapsed, bool)
            or not isinstance(elapsed, (int, float))
            or not math.isfinite(elapsed) or elapsed < 0
            or report["authority"] != AUTHORITY
            or report["report_sha256"] != _sha(body)
            or report["summaries"] != derived_summaries):
        raise PrivilegedTeacherSol0Error("Sol0 report identity drift")
    c0_records = c0._parent_records(c0_report)
    expected = {(*coordinate, role) for coordinate in design.root_coordinates
                for role in ROLES}
    seen = set()
    complete = 0
    for record in records:
        if type(record) is not dict or set(record) != {
                "schema", "status", "trump_rank", "banker", "replicate",
                "role", "treatment_team", "root_sha256",
                "parent_c0_record_sha256", "anchors", "sol0", "contrasts",
                "private_evidence_sha256", "failure_sha256", "authority",
                "record_sha256"}:
            raise PrivilegedTeacherSol0Error("Sol0 record schema drift")
        key = (record["trump_rank"], record["banker"],
               record["replicate"], record["role"])
        parent = c0_records.get(key)
        record_body = {name: value for name, value in record.items()
                       if name != "record_sha256"}
        if (key not in expected or key in seen or type(parent) is not dict
                or record["schema"] != RECORD_SCHEMA
                or record["treatment_team"] != parent["treatment_team"]
                or record["root_sha256"] != parent["root_sha256"]
                or record["parent_c0_record_sha256"] !=
                parent["record_sha256"]
                or record["anchors"] != {
                    name: _anchor(parent, name)
                    for name in ("A", "B", "C0-S")}
                or record["authority"] != AUTHORITY
                or record["record_sha256"] != _sha(record_body)):
            raise PrivilegedTeacherSol0Error("Sol0 record identity drift")
        _strict_sha(record["private_evidence_sha256"], "private evidence")
        if record["status"] == "COMPLETE":
            if record["failure_sha256"] is not None:
                raise PrivilegedTeacherSol0Error("Sol0 failure state drift")
            _validate_outcome(
                record["sol0"], banker=record["banker"],
                treatment_team=record["treatment_team"])
            expected_contrasts = {
                "sol0_minus_a": record["sol0"]["signed_level_utility"] -
                record["anchors"]["A"]["signed_level_utility"],
                "sol0_minus_b": record["sol0"]["signed_level_utility"] -
                record["anchors"]["B"]["signed_level_utility"],
                "sol0_minus_c0_s":
                record["sol0"]["signed_level_utility"] -
                record["anchors"]["C0-S"]["signed_level_utility"],
            }
            if record["contrasts"] != expected_contrasts:
                raise PrivilegedTeacherSol0Error("Sol0 contrast drift")
            complete += 1
        elif record["status"] == "INCOMPLETE":
            _strict_sha(record["failure_sha256"], "failure identity")
            if record["sol0"] is not None or record["contrasts"] is not None:
                raise PrivilegedTeacherSol0Error("Sol0 incomplete state drift")
        else:
            raise PrivilegedTeacherSol0Error("Sol0 record status drift")
        seen.add(key)
    if (seen != expected
            or report["completed_record_count"] != complete
            or report["incomplete_record_count"] != len(records) - complete
            or report["status"] != (
                "COMPLETE" if complete == len(records) else "INCOMPLETE")):
        raise PrivilegedTeacherSol0Error("Sol0 report population drift")


def report_bytes(
        report: dict[str, object], design: Sol0Design, *,
        c0_report: dict[str, object], c0_external_sha256: str,
        full_report: dict[str, object], full_external_sha256: str) -> bytes:
    validate_report(
        report, design, c0_report=c0_report,
        c0_external_sha256=c0_external_sha256,
        full_report=full_report,
        full_external_sha256=full_external_sha256)
    return canonical_json_bytes(report)


__all__ = [
    "AUTHORITY", "CONTRASTS", "DEV_NAMESPACE", "Sol0Design",
    "report_bytes", "run_dev", "validate_parents", "validate_report",
]

#!/usr/bin/env python3
"""One-shot controller for the score-free S3a full-game sizing preflight.

This controller deliberately stops before strength compute.  It binds one
host, clean Git tree, Python/native runtime, live champion parent, runner and
controller bytes, capacity budgets, command and output namespace.  A valid
capacity PASS authorizes only a separately reviewed screen packet.  A failure,
interruption, capacity HOLD or namespace collision is terminal for this run
ID; the controller never retries, resumes, deletes, tunes or launches a duel.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import secrets
import signal
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO


ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "server"
SCRIPTS = SERVER / "scripts"
sys.path.insert(0, str(SCRIPTS))

import s3a_bury_duel as DUEL  # noqa: E402


SCHEMA = "s3a-bury-duel-preflight-controller-v1"
RECEIPT_SCHEMA = "s3a-bury-duel-preflight-receipt-v1"
EXIT_SCHEMA = "s3a-bury-duel-preflight-exit-v1"
FINAL_SCHEMA = "s3a-bury-duel-preflight-final-v1"
RUN_ID = DUEL.PREFLIGHT_RUN_ID
SUPPORTED_HOSTS = (
    "Jerrys-Mac-mini.local",
    "Jerrys-MacBook-Air.local",
)
EXPECTED_PYTHON = "3.14.6"
NAMESPACE = Path("server/runs/logs") / RUN_ID
RUNNER = Path("server/scripts/s3a_bury_duel.py")
RECEIPT_NAME = "receipt.json"
PREFLIGHT_NAME = "preflight.json"
LOG_NAME = "preflight.log"
EXIT_NAME = "preflight.exit.json"
PROGRESS_NAME = "supervisor.jsonl"
FINAL_NAME = "supervisor-final.json"
FORBIDDEN_OUTCOME_KEYS = {
    "won", "level_utility", "records", "stats", "mean", "lcb_95",
    "ucb_95", "winner", "outcome", "played", "selected_index",
    "duel_result",
}


class ControllerRefusal(RuntimeError):
    """The one-shot preflight can no longer support its registered claim."""


@dataclass(frozen=True)
class Config:
    expected_git: str
    expected_runner_sha256: str
    expected_controller_sha256: str
    expected_host: str
    screen_fleet_hours: float
    screen_max_shard_hours: float
    confirm_fleet_hours: float
    confirm_max_shard_hours: float
    heartbeat_seconds: float

    @property
    def budgets(self) -> dict[str, float]:
        return {
            "screen_fleet_hours": self.screen_fleet_hours,
            "screen_max_shard_hours": self.screen_max_shard_hours,
            "confirm_fleet_hours": self.confirm_fleet_hours,
            "confirm_max_shard_hours": self.confirm_max_shard_hours,
        }


@dataclass(frozen=True)
class Paths:
    namespace: Path
    runner: Path
    controller: Path
    receipt: Path
    preflight: Path
    log_partial: Path
    log_final: Path
    exit_final: Path
    progress_partial: Path
    progress_final: Path
    final: Path


@dataclass
class Job:
    argv: tuple[str, ...]
    output: Path
    log_partial: Path
    log_final: Path
    exit_final: Path
    handle: IO[str]
    process: subprocess.Popen
    finished: bool = False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_digest(value: object) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def is_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def is_positive_finite(value: object) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value > 0)


def lexists(path: Path) -> bool:
    return os.path.lexists(path)


def partial(path: Path) -> Path:
    return Path(str(path) + ".partial")


def is_regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISREG(info.st_mode) and info.st_nlink == 1


def paths_for() -> Paths:
    namespace = ROOT / NAMESPACE
    return Paths(
        namespace=namespace,
        runner=ROOT / RUNNER,
        controller=Path(__file__).resolve(),
        receipt=namespace / RECEIPT_NAME,
        preflight=namespace / PREFLIGHT_NAME,
        log_partial=namespace / f"{LOG_NAME}.partial",
        log_final=namespace / LOG_NAME,
        exit_final=namespace / EXIT_NAME,
        progress_partial=namespace / f"{PROGRESS_NAME}.partial",
        progress_final=namespace / PROGRESS_NAME,
        final=namespace / FINAL_NAME,
    )


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _write_json_exclusive(path: Path, payload: dict) -> None:
    try:
        DUEL.write_exclusive(path, payload)
    except Exception as exc:
        raise ControllerRefusal(f"cannot publish {path}: {exc}") from exc


def _publish_partial(partial_path: Path, final_path: Path) -> None:
    try:
        os.link(partial_path, final_path)
    except FileExistsError as exc:
        raise ControllerRefusal(f"refusing to overwrite {final_path}") from exc
    os.unlink(partial_path)


def _number(value: float) -> str:
    return format(value, ".17g")


def preflight_argv(config: Config, output: Path) -> tuple[str, ...]:
    return (
        sys.executable, str(ROOT / RUNNER), "preflight",
        "--expected-git", config.expected_git,
        "--screen-fleet-hours", _number(config.screen_fleet_hours),
        "--screen-max-shard-hours", _number(config.screen_max_shard_hours),
        "--confirm-fleet-hours", _number(config.confirm_fleet_hours),
        "--confirm-max-shard-hours", _number(config.confirm_max_shard_hours),
        "--out", str(output),
    )


def packet_contract(config: Config, paths: Paths, *, parent: dict,
                    runtime: dict) -> dict:
    return {
        "schema": SCHEMA,
        "run_id": RUN_ID,
        "one_shot": True,
        "retry_or_resume_authorized": False,
        "host": config.expected_host,
        "python_executable": sys.executable,
        "python_version": EXPECTED_PYTHON,
        "environment": {
            "SHENGJI_FAST": "1",
            "SHENGJI_REQUIRE_VOIDS": "1",
            "experimental_flags_present": [],
        },
        "execution": {
            "git": config.expected_git,
            "runner_sha256": config.expected_runner_sha256,
            "controller_sha256": config.expected_controller_sha256,
        },
        "parent": parent,
        "runtime": runtime,
        "population": {
            "clusters": DUEL.PREFLIGHT_CLUSTERS,
            "seed0": DUEL.PREFLIGHT_SEED0,
            "stream_stride": DUEL.STREAM_STRIDE,
            "run_id": DUEL.PREFLIGHT_RUN_ID,
            "global_stream_separation": not DUEL.global_stream_problems(),
        },
        "capacity": {
            "budgets": config.budgets,
            "throughput_safety_factor": DUEL.THROUGHPUT_SAFETY_FACTOR,
            "screen": DUEL.phase_identity("screen"),
            "confirm": DUEL.phase_identity("confirm"),
        },
        "command": list(preflight_argv(config, paths.preflight)),
        "outputs": {
            "namespace": str(paths.namespace),
            "receipt": str(paths.receipt),
            "preflight": str(paths.preflight),
            "log": str(paths.log_final),
            "exit": str(paths.exit_final),
            "progress": str(paths.progress_final),
            "final": str(paths.final),
        },
        "gate": {
            "capacity_pass_authorizes_screen_packet_review_only": True,
            "strength_launch_authorized": False,
            "production_promotion": False,
        },
    }


def _config_problems(config: Config) -> list[str]:
    problems = []
    if (not isinstance(config.expected_git, str)
            or len(config.expected_git) != 40
            or any(char not in "0123456789abcdef"
                   for char in config.expected_git)):
        problems.append("expected git is malformed")
    if not is_sha256(config.expected_runner_sha256):
        problems.append("expected runner SHA-256 is malformed")
    if not is_sha256(config.expected_controller_sha256):
        problems.append("expected controller SHA-256 is malformed")
    if config.expected_host not in SUPPORTED_HOSTS:
        problems.append("expected host is not registered")
    for name, value in config.budgets.items():
        if not is_positive_finite(value):
            problems.append(f"capacity budget {name} is invalid")
    if not is_positive_finite(config.heartbeat_seconds) or not (
            1 <= config.heartbeat_seconds <= 60):
        problems.append("heartbeat must be between 1 and 60 seconds")
    return sorted(problems)


def _identity_context(config: Config, paths: Paths) -> tuple[dict, dict]:
    problems = _config_problems(config)
    if problems:
        raise ControllerRefusal("; ".join(problems))
    if os.uname().nodename != config.expected_host:
        raise ControllerRefusal(
            f"preflight pinned to {config.expected_host}, "
            f"got {os.uname().nodename}")
    if platform.python_version() != EXPECTED_PYTHON:
        raise ControllerRefusal(
            f"preflight requires Python {EXPECTED_PYTHON}")
    if _git("rev-parse", "HEAD") != config.expected_git:
        raise ControllerRefusal("preflight exact git predeclaration drift")
    if _git("status", "--porcelain"):
        raise ControllerRefusal("preflight refuses a dirty tree")
    if sha256_file(paths.runner) != config.expected_runner_sha256:
        raise ControllerRefusal("preflight runner SHA-256 drift")
    if sha256_file(paths.controller) != config.expected_controller_sha256:
        raise ControllerRefusal("preflight controller SHA-256 drift")
    if os.environ.get("SHENGJI_FAST") != "1" or \
            os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise ControllerRefusal(
            "set SHENGJI_FAST=1 and SHENGJI_REQUIRE_VOIDS=1")
    enabled = [name for name in DUEL.REFUSED_ENV_KEYS if os.environ.get(name)]
    if enabled:
        raise ControllerRefusal(
            f"experimental sampler/ballot flags must be unset: {enabled}")
    try:
        _, parent, runtime = DUEL.require_runtime(config.expected_git)
    except Exception as exc:
        raise ControllerRefusal(f"S3a duel runtime refused: {exc}") from exc
    if runtime.get("host") != config.expected_host:
        raise ControllerRefusal("runner/controller host identity mismatch")
    if runtime.get("python") != EXPECTED_PYTHON:
        raise ControllerRefusal("runner/controller Python identity mismatch")
    return parent, runtime


def _all_namespace_targets(paths: Paths) -> tuple[Path, ...]:
    finals = (
        paths.receipt, paths.preflight, paths.log_final, paths.exit_final,
        paths.progress_final, paths.final,
    )
    return finals + tuple(partial(path) for path in finals)


def launch_preflight(config: Config, paths: Paths) -> tuple[dict, dict, dict]:
    parent, runtime = _identity_context(config, paths)
    collisions = [str(path) for path in _all_namespace_targets(paths)
                  if lexists(path)]
    if collisions:
        raise ControllerRefusal(
            f"preflight namespace collision: {collisions[:3]}")
    if paths.namespace.exists() and any(paths.namespace.iterdir()):
        raise ControllerRefusal("preflight namespace contains unknown bytes")
    contract = packet_contract(
        config, paths, parent=parent, runtime=runtime)
    return contract, parent, runtime


class Progress:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.handle = path.open("x", encoding="utf-8")
        except FileExistsError as exc:
            raise ControllerRefusal(f"progress collision: {path}") from exc
        self.closed = False

    def event(self, status: str, **fields: object) -> None:
        payload = {
            "schema": SCHEMA,
            "time_ns": time.time_ns(),
            "phase": "preflight",
            "status": status,
            **fields,
        }
        line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        self.handle.write(line + "\n")
        self.handle.flush()
        os.fsync(self.handle.fileno())
        print(line, flush=True)

    def close(self) -> None:
        if not self.closed:
            self.handle.close()
            self.closed = True


def _start_job(config: Config, paths: Paths) -> Job:
    try:
        handle = paths.log_partial.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise ControllerRefusal(
            f"job log collision: {paths.log_partial}") from exc
    argv = preflight_argv(config, paths.preflight)
    process = subprocess.Popen(
        argv, cwd=ROOT, env=os.environ.copy(),
        stdout=handle, stderr=subprocess.STDOUT, text=True,
        start_new_session=True,
    )
    return Job(
        argv=argv, output=paths.preflight,
        log_partial=paths.log_partial, log_final=paths.log_final,
        exit_final=paths.exit_final, handle=handle, process=process,
    )


def _finish_job(job: Job) -> int:
    if job.finished:
        return int(job.process.returncode)
    returncode = job.process.wait()
    job.handle.flush()
    os.fsync(job.handle.fileno())
    job.handle.close()
    _publish_partial(job.log_partial, job.log_final)
    output_ok = is_regular_unlinked(job.output) and not lexists(
        partial(job.output))
    _write_json_exclusive(job.exit_final, {
        "schema": EXIT_SCHEMA,
        "run_id": RUN_ID,
        "argv": list(job.argv),
        "returncode": returncode,
        "output": str(job.output),
        "output_regular_unlinked": output_ok,
        "output_sha256": sha256_file(job.output) if output_ok else None,
        "log": str(job.log_final),
        "log_sha256": sha256_file(job.log_final),
    })
    job.finished = True
    return returncode if output_ok else 3


def _terminate(job: Job | None) -> None:
    if job is not None and not job.finished and job.process.poll() is None:
        try:
            os.killpg(job.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def _wait(job: Job, progress: Progress, heartbeat_seconds: float) -> int:
    last_heartbeat = 0.0
    while job.process.poll() is None:
        now = time.monotonic()
        if now - last_heartbeat >= heartbeat_seconds:
            progress.event("running", pid=job.process.pid)
            last_heartbeat = now
        time.sleep(0.2)
    return _finish_job(job)


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ControllerRefusal(f"cannot reopen {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ControllerRefusal(f"artifact is not an object: {path}")
    return value


def _load_jsonl(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        values = [json.loads(line) for line in lines]
    except (OSError, ValueError) as exc:
        raise ControllerRefusal(f"cannot reopen {path}: {exc}") from exc
    if any(not isinstance(value, dict) for value in values):
        raise ControllerRefusal(f"JSONL event is not an object: {path}")
    return values


def _all_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(str(key) for key in value)
        for item in value.values():
            keys.update(_all_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(_all_keys(item))
    return keys


def progress_problems(path: Path, *, receipt_sha256: str,
                      contract_sha256: str, preflight_sha256: str,
                      capacity_pass: bool) -> list[str]:
    events = _load_jsonl(path)
    problems = []
    if len(events) < 4:
        return ["progress event population"]
    statuses = [event.get("status") for event in events]
    if (statuses[:2] != ["receipt-published", "started"]
            or statuses[-1] != "complete"
            or any(status != "running" for status in statuses[2:-1])):
        problems.append("progress event ordering")
    times = [event.get("time_ns") for event in events]
    if (any(isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in times)
            or times != sorted(times)):
        problems.append("progress event time ordering")
    for event in events:
        if (event.get("schema") != SCHEMA
                or event.get("phase") != "preflight"):
            problems.append("progress event identity")
        if _all_keys(event) & FORBIDDEN_OUTCOME_KEYS:
            problems.append("progress leaked outcome fields")
    expected_first = {
        "schema", "time_ns", "phase", "status",
        "receipt_sha256", "contract_sha256",
    }
    if (set(events[0]) != expected_first
            or events[0].get("receipt_sha256") != receipt_sha256
            or events[0].get("contract_sha256") != contract_sha256):
        problems.append("progress receipt event")
    pid = events[1].get("pid")
    if (set(events[1]) != {"schema", "time_ns", "phase", "status", "pid"}
            or isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0):
        problems.append("progress start event")
    for event in events[2:-1]:
        if (set(event) != {"schema", "time_ns", "phase", "status", "pid"}
                or event.get("pid") != pid):
            problems.append("progress heartbeat event")
    expected_last = {
        "schema", "time_ns", "phase", "status",
        "capacity_pass", "preflight_sha256",
    }
    if (set(events[-1]) != expected_last
            or events[-1].get("capacity_pass") is not capacity_pass
            or events[-1].get("preflight_sha256") != preflight_sha256):
        problems.append("progress terminal event")
    return sorted(set(problems))


def _telemetry_problems(value: object, *, allow_structured: bool) -> list[str]:
    if not isinstance(value, dict):
        return ["telemetry is not an object"]
    expected = set(DUEL.STRUCTURED_BURY_TELEMETRY_FIELDS)
    problems = []
    if set(value) != expected:
        problems.append("telemetry field population")
        return problems
    if any(isinstance(value[name], bool) or not isinstance(value[name], int)
           or value[name] < 0 for name in expected):
        problems.append("telemetry non-negative integers")
        return problems
    if not allow_structured and any(value.values()):
        problems.append("control structured telemetry is nonzero")
    if value["triggers"] != value["searches"]:
        problems.append("structured triggers/searches mismatch")
    if value["searches"] != (
            value["complete_searches"] + value["short_searches"]):
        problems.append("structured search completion mismatch")
    if value["triggers"] > value["opportunities"]:
        problems.append("structured triggers exceed opportunities")
    if not (value["opportunities"] <= value["candidate_count_sum"] <=
            value["opportunities"] * DUEL.STRUCTURED_MAX_CANDIDATES):
        problems.append("structured candidate-count accounting")
    if value["candidate_rollouts"] > value["candidate_world_budget"]:
        problems.append("structured rollouts exceed budget")
    if value["overrides"] > value["complete_searches"]:
        problems.append("structured overrides exceed completions")
    if value["zero_world_searches"] > value["short_searches"]:
        problems.append("structured zero-world accounting")
    if value["worlds_used"] > value["worlds_requested"]:
        problems.append("structured worlds exceed request")
    if value["sample_attempts"] != (
            value["accepted_worlds"] + value["failed_worlds"]):
        problems.append("structured sampler accounting")
    if value["accepted_worlds"] != value["worlds_used"]:
        problems.append("structured accepted/scored mismatch")
    if value["rejected_worlds"] > value["failed_worlds"]:
        problems.append("structured rejected/failed mismatch")
    return sorted(set(problems))


def preflight_artifact_problems(payload: object, *, config: Config,
                                parent: dict, runtime: dict) -> list[str]:
    if not isinstance(payload, dict):
        return ["preflight root is not an object"]
    expected_fields = {
        "schema", "complete", "score_free", "clusters", "run_id", "seed0",
        "stream_stride", "parent", "runtime", "elapsed_seconds",
        "seconds_per_cluster", "integer_counters",
        "structured_bury_telemetry", "projections",
        "throughput_safety_factor", "problems", "budgets", "capacity_pass",
        "strength_launch_authorized", "production_promotion",
    }
    problems = []
    if set(payload) != expected_fields:
        problems.append("preflight field population")
    if (payload.get("schema") != DUEL.PREFLIGHT_SCHEMA
            or payload.get("complete") is not True
            or payload.get("score_free") is not True
            or payload.get("clusters") != DUEL.PREFLIGHT_CLUSTERS
            or payload.get("run_id") != RUN_ID
            or payload.get("seed0") != DUEL.PREFLIGHT_SEED0
            or payload.get("stream_stride") != DUEL.STREAM_STRIDE
            or payload.get("parent") != parent
            or payload.get("runtime") != runtime
            or payload.get("throughput_safety_factor") !=
            DUEL.THROUGHPUT_SAFETY_FACTOR
            or payload.get("budgets") != config.budgets
            or payload.get("strength_launch_authorized") is not False
            or payload.get("production_promotion") is not False):
        problems.append("preflight identity/provenance/authority")
    if _all_keys(payload) & FORBIDDEN_OUTCOME_KEYS:
        problems.append("preflight leaked outcome fields")
    elapsed = payload.get("elapsed_seconds")
    per_cluster = payload.get("seconds_per_cluster")
    if not is_positive_finite(elapsed) or not is_positive_finite(per_cluster):
        problems.append("preflight elapsed time")
    elif not math.isclose(
            elapsed, per_cluster * DUEL.PREFLIGHT_CLUSTERS,
            rel_tol=1e-12, abs_tol=1e-9):
        problems.append("preflight elapsed-time accounting")

    counters = payload.get("integer_counters")
    counter_fields = set(DUEL.counters([])) - {"search_secs"}
    if not isinstance(counters, dict) or set(counters) != set(DUEL.LABEL_ORDER):
        problems.append("preflight counter label population")
    else:
        for label, values in counters.items():
            if (not isinstance(values, dict) or set(values) != counter_fields
                    or any(isinstance(item, bool) or not isinstance(item, int)
                           or item < 0 for item in values.values())):
                problems.append(f"preflight counters {label}")
                continue
            if values["sample_attempts"] != (
                    values["accepted_worlds"] + values["failed_worlds"]):
                problems.append(f"preflight counters {label} sampler")
            if values["rejected_worlds"] > values["failed_worlds"]:
                problems.append(f"preflight counters {label} rejected")
            for name in DUEL.FORBIDDEN_COUNTER_FIELDS:
                if values[name] != 0:
                    problems.append(
                        f"preflight counters {label} forbidden {name}")

    telemetry = payload.get("structured_bury_telemetry")
    if not isinstance(telemetry, dict) or set(telemetry) != set(DUEL.LABEL_ORDER):
        problems.append("preflight telemetry label population")
    else:
        for label, values in telemetry.items():
            problems += [
                f"preflight telemetry {label}: {problem}"
                for problem in _telemetry_problems(
                    values, allow_structured=label == "structured")]
    if (isinstance(counters, dict) and isinstance(telemetry, dict)
            and set(counters) == set(telemetry) == set(DUEL.LABEL_ORDER)):
        subset_fields = {
            "searches": "searches",
            "candidate_rollouts": "rollouts",
            "sample_attempts": "sample_attempts",
            "accepted_worlds": "accepted_worlds",
            "failed_worlds": "failed_worlds",
            "rejected_worlds": "rejected_worlds",
        }
        for label in DUEL.LABEL_ORDER:
            general = counters[label]
            structured = telemetry[label]
            if not isinstance(general, dict) or not isinstance(structured, dict):
                continue
            for structured_name, general_name in subset_fields.items():
                if (isinstance(structured.get(structured_name), int)
                        and isinstance(general.get(general_name), int)
                        and structured[structured_name] > general[general_name]):
                    problems.append(
                        f"preflight telemetry {label} exceeds general "
                        f"counter {general_name}")

    projections = payload.get("projections")
    projection_values: dict[str, dict[str, float]] = {}
    if not isinstance(projections, dict) or set(projections) != set(DUEL.PHASES):
        problems.append("preflight projection population")
    elif is_positive_finite(per_cluster):
        for phase, spec in DUEL.PHASES.items():
            expected = {
                "fleet_hours": (per_cluster * spec["clusters"] *
                                DUEL.THROUGHPUT_SAFETY_FACTOR / 3_600),
                "max_shard_hours": (
                    per_cluster * spec["clusters_per_shard"] *
                    DUEL.THROUGHPUT_SAFETY_FACTOR / 3_600),
            }
            actual = projections.get(phase)
            if (not isinstance(actual, dict) or set(actual) != set(expected)
                    or any(not is_positive_finite(actual.get(name))
                           or not math.isclose(actual[name], value,
                                             rel_tol=1e-12, abs_tol=1e-12)
                           for name, value in expected.items())):
                problems.append(f"preflight projection {phase}")
            else:
                projection_values[phase] = actual

    recorded_problems = payload.get("problems")
    if (not isinstance(recorded_problems, list)
            or any(not isinstance(item, str) or not item
                   for item in recorded_problems)
            or recorded_problems != sorted(set(recorded_problems))):
        problems.append("preflight recorded-problem population")
        recorded_problems = ["invalid-recorded-problems"]
    derived_recorded_problems = []
    if isinstance(telemetry, dict) and isinstance(
            telemetry.get("structured"), dict):
        treatment = telemetry["structured"]
        if treatment.get("triggers", 0) <= 0:
            derived_recorded_problems.append(
                "score-free preflight did not exercise structured bury")
        if (treatment.get("short_searches") != 0
                or treatment.get("zero_world_searches") != 0
                or treatment.get("candidate_rollouts") !=
                treatment.get("candidate_world_budget")):
            derived_recorded_problems.append(
                "score-free preflight structured work incomplete")
    if not set(derived_recorded_problems).issubset(set(recorded_problems)):
        problems.append("preflight recorded problems omit derived failures")
    expected_capacity = False
    if set(projection_values) == set(DUEL.PHASES):
        expected_capacity = (
            not recorded_problems
            and projection_values["screen"]["fleet_hours"] <=
            config.screen_fleet_hours
            and projection_values["screen"]["max_shard_hours"] <=
            config.screen_max_shard_hours
            and projection_values["confirm"]["fleet_hours"] <=
            config.confirm_fleet_hours
            and projection_values["confirm"]["max_shard_hours"] <=
            config.confirm_max_shard_hours)
    if payload.get("capacity_pass") is not expected_capacity:
        problems.append("preflight capacity verdict drift")
    return sorted(set(problems))


def receipt_problems(receipt: object, contract: dict) -> list[str]:
    if not isinstance(receipt, dict):
        return ["receipt root is not an object"]
    problems = []
    if set(receipt) != {
            "schema", "run_id", "complete", "created_time_ns", "nonce",
            "contract", "contract_sha256"}:
        problems.append("receipt field population")
    if (receipt.get("schema") != RECEIPT_SCHEMA
            or receipt.get("run_id") != RUN_ID
            or receipt.get("complete") is not True):
        problems.append("receipt identity/completion")
    if receipt.get("contract") != contract:
        problems.append("receipt contract drift")
    if receipt.get("contract_sha256") != stable_digest(contract):
        problems.append("receipt contract SHA-256 drift")
    if not is_sha256(receipt.get("nonce")):
        problems.append("receipt nonce")
    created = receipt.get("created_time_ns")
    if isinstance(created, bool) or not isinstance(created, int) or created <= 0:
        problems.append("receipt creation time")
    return sorted(set(problems))


def job_evidence_problems(paths: Paths, config: Config) -> tuple[dict, list[str]]:
    artifacts = {
        "output": paths.preflight,
        "log": paths.log_final,
        "exit": paths.exit_final,
    }
    problems = [
        f"preflight terminal artifact invalid: {name}"
        for name, path in artifacts.items()
        if not is_regular_unlinked(path) or lexists(partial(path))
    ]
    if problems:
        return {}, problems
    expected_exit = {
        "schema": EXIT_SCHEMA,
        "run_id": RUN_ID,
        "argv": list(preflight_argv(config, paths.preflight)),
        "returncode": 0,
        "output": str(paths.preflight),
        "output_regular_unlinked": True,
        "output_sha256": sha256_file(paths.preflight),
        "log": str(paths.log_final),
        "log_sha256": sha256_file(paths.log_final),
    }
    actual_exit = _load_json(paths.exit_final)
    if actual_exit != expected_exit:
        return {}, ["preflight exit receipt full recomputation drift"]
    return {
        "output": {
            "path": str(paths.preflight),
            "sha256": sha256_file(paths.preflight),
        },
        "log": {
            "path": str(paths.log_final),
            "sha256": sha256_file(paths.log_final),
        },
        "exit": {
            "path": str(paths.exit_final),
            "sha256": sha256_file(paths.exit_final),
        },
    }, []


def expected_final(*, contract: dict, receipt_sha256: str,
                   progress_sha256: str, preflight: dict,
                   job_evidence: dict) -> dict:
    capacity_pass = preflight.get("capacity_pass") is True
    status = (
        "AUTHORIZE_SCREEN_PACKET_REVIEW" if capacity_pass
        else "TERMINAL_PROTOCOL_HOLD" if preflight.get("problems")
        else "TERMINAL_CAPACITY_HOLD")
    return {
        "schema": FINAL_SCHEMA,
        "run_id": RUN_ID,
        "complete": True,
        "contract_sha256": stable_digest(contract),
        "receipt_sha256": receipt_sha256,
        "progress_sha256": progress_sha256,
        "job": job_evidence,
        "preflight": {
            "path": job_evidence["output"]["path"],
            "sha256": job_evidence["output"]["sha256"],
            "capacity_pass": capacity_pass,
        },
        "status": status,
        "screen_packet_review_authorized": capacity_pass,
        "strength_launch_authorized": False,
        "production_promotion": False,
        "retry_or_resume_authorized": False,
    }


def launch(config: Config) -> None:
    paths = paths_for()
    contract, parent, runtime = launch_preflight(config, paths)
    paths.namespace.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "run_id": RUN_ID,
        "complete": True,
        "created_time_ns": time.time_ns(),
        "nonce": secrets.token_hex(32),
        "contract": contract,
        "contract_sha256": stable_digest(contract),
    }
    _write_json_exclusive(paths.receipt, receipt)
    progress = Progress(paths.progress_partial)
    job: Job | None = None
    try:
        progress.event(
            "receipt-published",
            receipt_sha256=sha256_file(paths.receipt),
            contract_sha256=stable_digest(contract),
        )
        job = _start_job(config, paths)
        progress.event("started", pid=job.process.pid)
        if _wait(job, progress, config.heartbeat_seconds) != 0:
            raise ControllerRefusal(
                "preflight child failure consumed namespace")
        payload = _load_json(paths.preflight)
        problems = preflight_artifact_problems(
            payload, config=config, parent=parent, runtime=runtime)
        if problems:
            raise ControllerRefusal(
                "preflight artifact: " + "; ".join(problems))
        evidence, evidence_problems = job_evidence_problems(paths, config)
        if evidence_problems:
            raise ControllerRefusal("; ".join(evidence_problems))
        progress.event(
            "complete", capacity_pass=payload["capacity_pass"],
            preflight_sha256=sha256_file(paths.preflight),
        )
        progress.close()
        _publish_partial(paths.progress_partial, paths.progress_final)
        progress_issues = progress_problems(
            paths.progress_final,
            receipt_sha256=sha256_file(paths.receipt),
            contract_sha256=stable_digest(contract),
            preflight_sha256=sha256_file(paths.preflight),
            capacity_pass=payload["capacity_pass"],
        )
        if progress_issues:
            raise ControllerRefusal(
                "progress artifact: " + "; ".join(progress_issues))
        final = expected_final(
            contract=contract,
            receipt_sha256=sha256_file(paths.receipt),
            progress_sha256=sha256_file(paths.progress_final),
            preflight=payload, job_evidence=evidence,
        )
        _write_json_exclusive(paths.final, final)
        print(json.dumps(final, indent=2, sort_keys=True), flush=True)
    except BaseException:
        _terminate(job)
        if job is not None and not job.finished:
            try:
                _finish_job(job)
            except Exception:
                pass
        raise
    finally:
        progress.close()


def verify(config: Config) -> None:
    paths = paths_for()
    parent, runtime = _identity_context(config, paths)
    contract = packet_contract(
        config, paths, parent=parent, runtime=runtime)
    for path in (
            paths.receipt, paths.preflight, paths.log_final, paths.exit_final,
            paths.progress_final, paths.final):
        if not is_regular_unlinked(path) or lexists(partial(path)):
            raise ControllerRefusal(
                f"terminal artifact missing/nonregular/partial: {path}")
    problems = receipt_problems(_load_json(paths.receipt), contract)
    payload = _load_json(paths.preflight)
    problems += preflight_artifact_problems(
        payload, config=config, parent=parent, runtime=runtime)
    evidence, evidence_problems = job_evidence_problems(paths, config)
    problems += evidence_problems
    problems += progress_problems(
        paths.progress_final,
        receipt_sha256=sha256_file(paths.receipt),
        contract_sha256=stable_digest(contract),
        preflight_sha256=sha256_file(paths.preflight),
        capacity_pass=payload.get("capacity_pass") is True,
    )
    if not evidence_problems:
        expected = expected_final(
            contract=contract,
            receipt_sha256=sha256_file(paths.receipt),
            progress_sha256=sha256_file(paths.progress_final),
            preflight=payload, job_evidence=evidence,
        )
        if _load_json(paths.final) != expected:
            problems.append("supervisor final full recomputation drift")
    if problems:
        raise ControllerRefusal(
            "terminal verify: " + "; ".join(sorted(set(problems))))
    print(json.dumps({
        "verified": True,
        "run_id": RUN_ID,
        "status": expected["status"],
        "final_sha256": sha256_file(paths.final),
    }, sort_keys=True), flush=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("launch", "verify"))
    parser.add_argument("--expected-git", required=True)
    parser.add_argument("--expected-runner-sha256", required=True)
    parser.add_argument("--expected-controller-sha256", required=True)
    parser.add_argument("--expected-host", required=True)
    parser.add_argument("--screen-fleet-hours", type=float, required=True)
    parser.add_argument("--screen-max-shard-hours", type=float, required=True)
    parser.add_argument("--confirm-fleet-hours", type=float, required=True)
    parser.add_argument("--confirm-max-shard-hours", type=float, required=True)
    parser.add_argument("--heartbeat-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)
    config = Config(
        expected_git=args.expected_git,
        expected_runner_sha256=args.expected_runner_sha256,
        expected_controller_sha256=args.expected_controller_sha256,
        expected_host=args.expected_host,
        screen_fleet_hours=args.screen_fleet_hours,
        screen_max_shard_hours=args.screen_max_shard_hours,
        confirm_fleet_hours=args.confirm_fleet_hours,
        confirm_max_shard_hours=args.confirm_max_shard_hours,
        heartbeat_seconds=args.heartbeat_seconds,
    )
    problems = _config_problems(config)
    if problems:
        raise ControllerRefusal("; ".join(problems))
    if args.command == "launch":
        launch(config)
    else:
        verify(config)


if __name__ == "__main__":
    try:
        main()
    except ControllerRefusal as exc:
        print(f"REFUSING: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(3) from exc

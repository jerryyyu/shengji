#!/usr/bin/env python3
"""Freeze, review, admit, supervise, and verify the S4 Air replication.

The controller is deliberately one-shot.  It can launch exactly the fixed
2,048-cluster population registered by ``s4_point_banking_replication.py``
after a score-free Air preflight and an external packet review.  It cannot
retry, extend, promote, deploy, train, or touch T4 REPORT.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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

import s4_point_banking_replication as CORE  # noqa: E402

SCHEMA = "s4-point-banking-replication-air-controller-v1"
EXIT_SCHEMA = "s4-point-banking-replication-air-exit-v1"
FINAL_SCHEMA = "s4-point-banking-replication-air-final-v1"
RUN_ID = CORE.RUN_ID
NAMESPACE = CORE.NAMESPACE
RUNNER = Path("server/scripts/s4_point_banking_replication.py")
CONTROLLER = Path("server/scripts/s4_point_banking_replication_air.py")
SHARD_COUNT = CORE.SHARD_COUNT
SHARD_NAMES = tuple(f"shard-{index:02d}.json" for index in range(SHARD_COUNT))
PACKET_NAME = "launch_packet.json"
REVIEW_NAME = "review_record.txt"
ADMISSION_NAME = "review_admission.json"
RECEIPT_NAME = "receipt.json"
PROGRESS_NAME = "supervisor.jsonl"
FINAL_NAME = "supervisor-final.json"
AGGREGATE_NAME = "aggregate.json"
PREFLIGHT_PATH = CORE.PREFLIGHT_NAMESPACE / "preflight.json"
SCREEN_AGGREGATE_PATH = CORE.SCREEN_NAMESPACE / "aggregate.json"
SCREEN_FINAL_PATH = CORE.SCREEN_NAMESPACE / "supervisor-final.json"

EXPECTED_HOST = "Jerrys-MacBook-Air.local"
EXPECTED_PYTHON = "3.14.6"
EXPECTED_FAST_SHA256 = (
    "9c9e77fbdc4c6caceec195465155f37ec6369e409462fd838bc142bf8a0be4c1"
)


class SupervisorRefused(RuntimeError):
    """The one-shot Air packet or evidence boundary was violated."""


@dataclass(frozen=True)
class Config:
    expected_git: str
    expected_runner_sha256: str
    expected_controller_sha256: str
    heartbeat_seconds: float = 30.0


@dataclass(frozen=True)
class Paths:
    namespace: Path
    runner: Path
    controller: Path
    preflight: Path
    screen_aggregate: Path
    screen_final: Path
    packet: Path
    review_copy: Path
    admission: Path
    receipt: Path
    progress_partial: Path
    progress_final: Path
    final: Path
    shards: tuple[Path, ...]
    shard_logs: tuple[Path, ...]
    shard_exits: tuple[Path, ...]
    aggregate: Path


@dataclass
class Job:
    name: str
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
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def is_sha256(value: object) -> bool:
    return CORE.is_sha256(value)


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


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve()))


def paths_for() -> Paths:
    namespace = ROOT / NAMESPACE
    return Paths(
        namespace=namespace,
        runner=ROOT / RUNNER,
        controller=ROOT / CONTROLLER,
        preflight=ROOT / PREFLIGHT_PATH,
        screen_aggregate=ROOT / SCREEN_AGGREGATE_PATH,
        screen_final=ROOT / SCREEN_FINAL_PATH,
        packet=namespace / PACKET_NAME,
        review_copy=namespace / REVIEW_NAME,
        admission=namespace / ADMISSION_NAME,
        receipt=namespace / RECEIPT_NAME,
        progress_partial=namespace / f"{PROGRESS_NAME}.partial",
        progress_final=namespace / PROGRESS_NAME,
        final=namespace / FINAL_NAME,
        shards=tuple(namespace / name for name in SHARD_NAMES),
        shard_logs=tuple(namespace / f"shard-{index:02d}.log"
                         for index in range(SHARD_COUNT)),
        shard_exits=tuple(namespace / f"exit-shard-{index:02d}.json"
                          for index in range(SHARD_COUNT)),
        aggregate=namespace / AGGREGATE_NAME,
    )


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise SupervisorRefused(f"cannot reopen {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SupervisorRefused(f"artifact is not an object: {path}")
    return value


def _write_json_exclusive(path: Path, payload: dict) -> None:
    try:
        CORE.write_exclusive(path, payload)
    except Exception as exc:
        raise SupervisorRefused(f"cannot publish {path}: {exc}") from exc


def _write_bytes_exclusive(path: Path, raw: bytes) -> None:
    candidate = partial(path)
    if lexists(path) or lexists(candidate):
        raise SupervisorRefused(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with candidate.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(candidate, path)
        candidate.unlink()
    except BaseException:
        raise


def _publish_partial(candidate: Path, final: Path) -> None:
    try:
        os.link(candidate, final)
    except FileExistsError as exc:
        raise SupervisorRefused(f"refusing to overwrite {final}") from exc
    candidate.unlink()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def command_template(index: int) -> list[str]:
    if not 0 <= index < SHARD_COUNT:
        raise SupervisorRefused("shard index outside registered population")
    return [
        "{python}", str(RUNNER), "run",
        "--expected-git", "{git}",
        "--shard-index", str(index),
        "--progress-every", "1",
        "--execution-receipt", str(NAMESPACE / RECEIPT_NAME),
        "--expected-execution-receipt-sha256",
        "{execution_receipt_sha256}",
        "--out", str(NAMESPACE / SHARD_NAMES[index]),
    ]


def aggregate_template() -> list[str]:
    return [
        "{python}", str(RUNNER), "aggregate",
        "--expected-git", "{git}",
        "--shards", *[str(NAMESPACE / name) for name in SHARD_NAMES],
        "--screen-aggregate", str(SCREEN_AGGREGATE_PATH),
        "--screen-final", str(SCREEN_FINAL_PATH),
        "--execution-receipt", str(NAMESPACE / RECEIPT_NAME),
        "--expected-execution-receipt-sha256",
        "{execution_receipt_sha256}",
        "--out", str(NAMESPACE / AGGREGATE_NAME),
    ]


def shard_argv(config: Config, index: int, output: Path,
               execution_receipt_sha256: str) -> tuple[str, ...]:
    expected_output = ROOT / NAMESPACE / SHARD_NAMES[index]
    if output != expected_output:
        raise SupervisorRefused("shard output path drift")
    if not is_sha256(execution_receipt_sha256):
        raise SupervisorRefused("execution receipt SHA-256 is invalid")
    relative_paths = {
        str(RUNNER), str(NAMESPACE / RECEIPT_NAME),
        str(NAMESPACE / SHARD_NAMES[index]),
    }
    return tuple(
        sys.executable if item == "{python}"
        else config.expected_git if item == "{git}"
        else execution_receipt_sha256
        if item == "{execution_receipt_sha256}"
        else str(ROOT / item) if item in relative_paths
        else item
        for item in command_template(index)
    )


def _artifact_ref(path: Path, expected_sha256: str | None,
                  label: str) -> dict:
    if not is_regular_unlinked(path) or lexists(partial(path)):
        raise SupervisorRefused(f"{label} is missing, linked, or partial")
    actual = sha256_file(path)
    if expected_sha256 is not None and actual != expected_sha256:
        raise SupervisorRefused(f"{label} SHA-256 drift")
    return {"path": rel(path), "sha256": actual}


def _identity_context(config: Config, paths: Paths) -> tuple[dict, dict]:
    if _git("rev-parse", "HEAD") != config.expected_git:
        raise SupervisorRefused("replication controller exact Git drift")
    if _git("status", "--porcelain"):
        raise SupervisorRefused("replication controller refuses a dirty tree")
    if (sha256_file(paths.runner) != config.expected_runner_sha256
            or sha256_file(paths.controller) !=
            config.expected_controller_sha256):
        raise SupervisorRefused("replication source SHA-256 drift")
    try:
        parent, runtime = CORE.require_runtime(config.expected_git)
    except Exception as exc:
        raise SupervisorRefused(
            f"replication runtime refused: {exc}") from exc
    if (runtime.get("host") != EXPECTED_HOST
            or runtime.get("python") != EXPECTED_PYTHON
            or runtime.get("fast_binary_sha256") != EXPECTED_FAST_SHA256
            or runtime.get("replication_runner_sha256") !=
            config.expected_runner_sha256):
        raise SupervisorRefused("replication is frozen to exact Air runtime")
    return parent, runtime


def preflight_evidence(config: Config, paths: Paths, *,
                       parent: dict, runtime: dict) -> dict:
    ref = _artifact_ref(paths.preflight, None, "replication preflight")
    payload = _load_json(paths.preflight)
    expected_fields = {
        "schema", "complete", "score_free", "outcomes_published",
        "outcomes_discarded", "run_id", "clusters", "seed0",
        "stream_stride", "parent", "runtime", "elapsed_seconds",
        "throughput_safety_factor", "counter_totals",
        "point_banking_telemetry", "projection", "criteria", "status",
        "replication_launch_authorized", "strength_claim",
        "training_authorized", "production_promotion",
        "retry_or_extension_authorized",
    }
    projection = payload.get("projection")
    criteria = payload.get("criteria")
    if (set(payload) != expected_fields
            or payload.get("schema") != CORE.PREFLIGHT_SCHEMA
            or payload.get("complete") is not True
            or payload.get("score_free") is not True
            or payload.get("outcomes_published") is not False
            or payload.get("outcomes_discarded") is not True
            or payload.get("run_id") != CORE.PREFLIGHT_RUN_ID
            or payload.get("clusters") != CORE.PREFLIGHT_CLUSTERS
            or payload.get("seed0") != CORE.PREFLIGHT_SEED0
            or payload.get("stream_stride") != CORE.DUEL.STREAM_STRIDE
            or payload.get("parent") != parent
            or payload.get("runtime") != runtime
            or payload.get("status") != "AUTHORIZE_REPLICATION_PACKET_REVIEW"
            or not isinstance(criteria, dict)
            or criteria.get("all") is not True
            or not all(criteria.values())
            or not isinstance(projection, dict)
            or projection.get("fleet_hours", float("inf")) >
            CORE.MAX_PROJECTED_FLEET_HOURS
            or projection.get("max_shard_hours", float("inf")) >
            CORE.MAX_PROJECTED_SHARD_HOURS
            or payload.get("replication_launch_authorized") is not False
            or payload.get("strength_claim") is not False
            or payload.get("training_authorized") is not False
            or payload.get("production_promotion") is not False
            or payload.get("retry_or_extension_authorized") is not False):
        raise SupervisorRefused("replication preflight identity/authority drift")
    return {
        **ref,
        "score_free": True,
        "outcomes_published": False,
        "status": payload["status"],
        "elapsed_seconds": payload["elapsed_seconds"],
        "projection": projection,
    }


def screen_evidence(paths: Paths, *, parent: dict, runtime: dict) -> dict:
    try:
        return CORE.load_screen_parent(
            aggregate_path=paths.screen_aggregate,
            final_path=paths.screen_final, parent=parent, runtime=runtime)
    except Exception as exc:
        raise SupervisorRefused(f"S4 screen parent refused: {exc}") from exc


def packet_contract(config: Config, paths: Paths, *, parent: dict,
                    runtime: dict, preflight: dict,
                    screen_parent: dict) -> dict:
    jobs = [{
        "name": f"shard-{index:02d}",
        "command_template": command_template(index),
        "output": str(NAMESPACE / SHARD_NAMES[index]),
        "clusters": CORE.CLUSTERS_PER_SHARD,
        "null_sentinel_clusters": len([
            value for value in CORE.shard_indexes(index)
            if CORE.is_null_sentinel(value)]),
    } for index in range(SHARD_COUNT)]
    return {
        "schema": CORE.PACKET_SCHEMA,
        "run_id": RUN_ID,
        "git": config.expected_git,
        "runner": {"path": str(RUNNER),
                   "sha256": config.expected_runner_sha256},
        "controller": {"path": str(CONTROLLER),
                       "sha256": config.expected_controller_sha256},
        "runtime": runtime,
        "parent": parent,
        "screen_parent": screen_parent,
        "score_free_preflight": preflight,
        "schedule": CORE.schedule(),
        "namespace": str(NAMESPACE),
        "jobs": jobs,
        "aggregate_command_template": aggregate_template(),
        "aggregate_output": str(NAMESPACE / AGGREGATE_NAME),
        "heartbeat_seconds": config.heartbeat_seconds,
        "selection_rule": CORE.SELECTION_RULE,
        "claim_boundary": CORE.CLAIM_BOUNDARY,
        "packet_review_authorized": True,
        "replication_launch_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "retry_or_extension_authorized": False,
    }


def _expected_packet(config: Config, paths: Paths) -> tuple[dict, dict, dict]:
    parent, runtime = _identity_context(config, paths)
    preflight = preflight_evidence(
        config, paths, parent=parent, runtime=runtime)
    screen_parent = screen_evidence(paths, parent=parent, runtime=runtime)
    packet = packet_contract(
        config, paths, parent=parent, runtime=runtime,
        preflight=preflight, screen_parent=screen_parent)
    return packet, parent, runtime


def freeze_packet(config: Config) -> dict:
    paths = paths_for()
    if paths.namespace.exists():
        raise SupervisorRefused("replication namespace already exists")
    packet, _, _ = _expected_packet(config, paths)
    _write_json_exclusive(paths.packet, packet)
    return {
        "path": rel(paths.packet),
        "sha256": sha256_file(paths.packet),
        "packet_review_authorized": True,
        "replication_launch_authorized": False,
    }


def verify_packet(config: Config, paths: Paths | None = None) -> dict:
    paths = paths or paths_for()
    if not is_regular_unlinked(paths.packet) or lexists(partial(paths.packet)):
        raise SupervisorRefused("replication packet missing, linked, or partial")
    expected, _, _ = _expected_packet(config, paths)
    actual = _load_json(paths.packet)
    if actual != expected:
        raise SupervisorRefused("replication packet full recomputation drift")
    return actual


def _expected_review_claim(*, packet_sha256: str,
                           preflight_sha256: str,
                           config: Config) -> dict:
    return {
        "schema": CORE.PACKET_REVIEW_SCHEMA,
        "git": config.expected_git,
        "run_id": RUN_ID,
        "packet_sha256": packet_sha256,
        "preflight_sha256": preflight_sha256,
        "screen_aggregate_sha256": CORE.SCREEN_AGGREGATE_SHA256,
        "screen_final_sha256": CORE.SCREEN_FINAL_SHA256,
        "fixed_look_clusters": CORE.CLUSTERS,
        "null_sentinel_clusters": CORE.NULL_SENTINEL_CLUSTERS,
        "independent_review": True,
        "replication_launch_authorized": True,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "verdict": "PASS",
    }


def _review_claim(raw: bytes, *, packet_sha256: str,
                  preflight_sha256: str, config: Config) -> dict:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SupervisorRefused("review record is not UTF-8") from exc
    matches = [
        line[len(CORE.PACKET_REVIEW_MARKER):]
        for line in text.splitlines()
        if line.startswith(CORE.PACKET_REVIEW_MARKER)
    ]
    if len(matches) != 1:
        raise SupervisorRefused("review record must contain exactly one marker")
    try:
        claim = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise SupervisorRefused("review marker is invalid JSON") from exc
    expected = _expected_review_claim(
        packet_sha256=packet_sha256, preflight_sha256=preflight_sha256,
        config=config)
    if claim != expected:
        raise SupervisorRefused("review marker grants wrong authority")
    return claim


def admit_packet(config: Config, review_record: Path,
                 expected_review_sha256: str,
                 expected_packet_sha256: str) -> dict:
    paths = paths_for()
    packet = verify_packet(config, paths)
    packet_sha256 = sha256_file(paths.packet)
    if packet_sha256 != expected_packet_sha256:
        raise SupervisorRefused("expected packet SHA-256 mismatch")
    if (not is_regular_unlinked(review_record)
            or review_record.resolve().is_relative_to(
                paths.namespace.resolve())):
        raise SupervisorRefused("review source must be external regular file")
    raw = review_record.read_bytes()
    if sha256_file(review_record) != expected_review_sha256:
        raise SupervisorRefused("expected review SHA-256 mismatch")
    preflight_sha256 = packet["score_free_preflight"]["sha256"]
    claim = _review_claim(
        raw, packet_sha256=packet_sha256,
        preflight_sha256=preflight_sha256, config=config)
    _write_bytes_exclusive(paths.review_copy, raw)
    admission = {
        "schema": CORE.ADMISSION_SCHEMA,
        "run_id": RUN_ID,
        "packet": {"path": str(NAMESPACE / PACKET_NAME),
                   "sha256": packet_sha256},
        "review": {"path": str(NAMESPACE / REVIEW_NAME),
                   "sha256": expected_review_sha256},
        "review_claim": claim,
        "operator_asserted_independent_review": True,
        "replication_launch_authorized": True,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
    }
    _write_json_exclusive(paths.admission, admission)
    return {"path": rel(paths.admission),
            "sha256": sha256_file(paths.admission),
            "replication_launch_authorized": True}


def _require_admission(config: Config, paths: Paths) -> tuple[dict, dict]:
    packet = verify_packet(config, paths)
    for path, label in ((paths.review_copy, "review copy"),
                        (paths.admission, "review admission")):
        if not is_regular_unlinked(path) or lexists(partial(path)):
            raise SupervisorRefused(f"{label} missing, linked, or partial")
    packet_sha256 = sha256_file(paths.packet)
    review_sha256 = sha256_file(paths.review_copy)
    preflight_sha256 = packet["score_free_preflight"]["sha256"]
    claim = _review_claim(
        paths.review_copy.read_bytes(), packet_sha256=packet_sha256,
        preflight_sha256=preflight_sha256, config=config)
    expected = {
        "schema": CORE.ADMISSION_SCHEMA,
        "run_id": RUN_ID,
        "packet": {"path": str(NAMESPACE / PACKET_NAME),
                   "sha256": packet_sha256},
        "review": {"path": str(NAMESPACE / REVIEW_NAME),
                   "sha256": review_sha256},
        "review_claim": claim,
        "operator_asserted_independent_review": True,
        "replication_launch_authorized": True,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
    }
    if _load_json(paths.admission) != expected:
        raise SupervisorRefused("replication review admission drift")
    return packet, expected


def _execution_targets(paths: Paths) -> tuple[Path, ...]:
    return (
        paths.receipt, partial(paths.receipt),
        paths.progress_partial, paths.progress_final,
        paths.final, partial(paths.final),
        *paths.shards, *[partial(path) for path in paths.shards],
        *paths.shard_logs, *[partial(path) for path in paths.shard_logs],
        *paths.shard_exits, *[partial(path) for path in paths.shard_exits],
        paths.aggregate, partial(paths.aggregate),
    )


def launch_preflight(config: Config, paths: Paths) -> tuple[dict, dict, dict]:
    packet, parent, runtime = _expected_packet(config, paths)
    actual, admission = _require_admission(config, paths)
    if actual != packet:
        raise SupervisorRefused("admitted replication packet drift")
    collisions = [str(path) for path in _execution_targets(paths)
                  if lexists(path)]
    if collisions:
        raise SupervisorRefused(
            f"replication namespace collision: {collisions[:3]}")
    allowed = {PACKET_NAME, REVIEW_NAME, ADMISSION_NAME}
    present = {path.name for path in paths.namespace.iterdir()}
    if present != allowed:
        raise SupervisorRefused(
            f"replication namespace contains unknown bytes: "
            f"{sorted(present - allowed)}")
    return parent, runtime, admission


def receipt_problems(receipt: dict, *, config: Config,
                     packet_sha256: str, admission_sha256: str,
                     preflight_sha256: str) -> list[str]:
    expected = {
        "schema": CORE.RECEIPT_SCHEMA,
        "run_id": RUN_ID,
        "complete": True,
        "git": config.expected_git,
        "runner_sha256": config.expected_runner_sha256,
        "controller_sha256": config.expected_controller_sha256,
        "created_time_ns": receipt.get("created_time_ns"),
        "nonce": receipt.get("nonce"),
        "packet_sha256": packet_sha256,
        "admission_sha256": admission_sha256,
        "preflight_sha256": preflight_sha256,
        "screen_aggregate_sha256": CORE.SCREEN_AGGREGATE_SHA256,
        "screen_final_sha256": CORE.SCREEN_FINAL_SHA256,
        "replication_launch_authorized": True,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "retry_or_extension_authorized": False,
    }
    problems = [] if receipt == expected else ["receipt recomputation drift"]
    created = receipt.get("created_time_ns")
    if isinstance(created, bool) or not isinstance(created, int) or created <= 0:
        problems.append("receipt creation time")
    if not is_sha256(receipt.get("nonce")):
        problems.append("receipt nonce")
    return sorted(set(problems))


class Progress:
    def __init__(self, path: Path):
        if lexists(path):
            raise SupervisorRefused("progress partial already exists")
        self.path = path
        self.handle = path.open("xb", buffering=0)

    def event(self, phase: str, status: str, **fields) -> None:
        payload = {
            "schema": SCHEMA,
            "phase": phase,
            "status": status,
            "time_ns": time.time_ns(),
            **fields,
        }
        self.handle.write((json.dumps(
            payload, sort_keys=True, separators=(",", ":")) + "\n").encode())
        os.fsync(self.handle.fileno())

    def close(self) -> None:
        if not self.handle.closed:
            self.handle.close()


def _start_job(name: str, argv: tuple[str, ...], output: Path,
               log_final: Path, exit_final: Path) -> Job:
    log_partial = partial(log_final)
    if any(lexists(path) for path in (
            output, partial(output), log_final, log_partial,
            exit_final, partial(exit_final))):
        raise SupervisorRefused(f"child namespace collision: {name}")
    handle = log_partial.open("x", encoding="utf-8")
    try:
        process = subprocess.Popen(
            argv, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT,
            text=True, start_new_session=True)
    except BaseException:
        handle.close()
        raise
    return Job(name, argv, output, log_partial, log_final,
               exit_final, handle, process)


def _finish_job(job: Job) -> int:
    if job.finished:
        return int(job.process.returncode or 0)
    returncode = job.process.wait()
    job.handle.flush()
    os.fsync(job.handle.fileno())
    job.handle.close()
    _publish_partial(job.log_partial, job.log_final)
    output_ok = is_regular_unlinked(job.output) and not lexists(partial(job.output))
    exit_record = {
        "schema": EXIT_SCHEMA,
        "run_id": RUN_ID,
        "job": job.name,
        "argv": list(job.argv),
        "returncode": returncode,
        "output": rel(job.output),
        "output_regular_unlinked": output_ok,
        "output_sha256": sha256_file(job.output) if output_ok else None,
        "log": rel(job.log_final),
        "log_sha256": sha256_file(job.log_final),
    }
    _write_json_exclusive(job.exit_final, exit_record)
    job.finished = True
    return returncode


def _terminate(jobs: list[Job]) -> None:
    for job in jobs:
        if job.process.poll() is None:
            try:
                os.killpg(job.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + 10
    for job in jobs:
        if job.process.poll() is None:
            try:
                job.process.wait(max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(job.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def _job_progress(job: Job) -> dict:
    latest = None
    source = (job.log_partial if job.log_partial.is_file()
              else job.log_final)
    if source.is_file():
        try:
            for line in source.read_text(errors="replace").splitlines():
                if '"event": "s4-point-banking-replication-progress-v1"' \
                        not in line:
                    continue
                candidate = json.loads(line)
                if candidate.get("shard_index") == int(job.name[-2:]):
                    latest = candidate
        except (OSError, ValueError):
            latest = None
    return {
        "job": job.name,
        "clusters_complete": int((latest or {}).get("clusters_complete", 0)),
        "clusters_total": CORE.CLUSTERS_PER_SHARD,
        "finished": job.process.poll() is not None,
    }


def _wait_parallel(jobs: list[Job], progress: Progress,
                   heartbeat_seconds: float) -> None:
    while True:
        failures = []
        live = []
        complete = 0
        for job in jobs:
            code = job.process.poll()
            if code is None:
                live.append(job.name)
            elif not job.finished:
                code = _finish_job(job)
                if code != 0:
                    failures.append((job.name, code))
            if job.finished and job.process.returncode == 0:
                complete += 1
        progress.event(
            "shards", "running" if live else "finished",
            complete=complete, total=len(jobs), live=live,
            shard_progress=[_job_progress(job) for job in jobs])
        if failures:
            raise SupervisorRefused(f"replication child failure: {failures}")
        if not live:
            if complete != len(jobs):
                raise SupervisorRefused("child population did not complete")
            return
        time.sleep(heartbeat_seconds)


def _job_specs(config: Config, paths: Paths,
               execution_receipt_sha256: str):
    return [(
        f"shard-{index:02d}",
        shard_argv(config, index, paths.shards[index],
                   execution_receipt_sha256),
        paths.shards[index], paths.shard_logs[index], paths.shard_exits[index],
    ) for index in range(SHARD_COUNT)]


def _recompute_aggregate(config: Config, paths: Paths, *, parent: dict,
                         runtime: dict) -> dict:
    try:
        receipt = CORE.require_receipt(
            paths.receipt, sha256_file(paths.receipt),
            expected_git=config.expected_git)
        screen_parent = CORE.load_screen_parent(
            aggregate_path=paths.screen_aggregate,
            final_path=paths.screen_final, parent=parent, runtime=runtime)
    except Exception as exc:
        raise SupervisorRefused(
            f"replication authority refused during aggregation: {exc}") \
            from exc
    args = argparse.Namespace(shards=[str(path) for path in paths.shards])
    try:
        shards, inputs = CORE.load_shards(
            args, parent=parent, runtime=runtime, receipt=receipt)
        return CORE.build_aggregate(
            shards=shards, inputs=inputs, parent=parent, runtime=runtime,
            screen_parent=screen_parent)
    except Exception as exc:
        raise SupervisorRefused(f"aggregate recomputation refused: {exc}") \
            from exc


def terminal_job_evidence(config: Config, paths: Paths,
                          execution_receipt_sha256: str):
    evidence = []
    problems = []
    for name, argv, output, log, exit_path in _job_specs(
            config, paths, execution_receipt_sha256):
        artifacts = {"output": output, "log": log, "exit": exit_path}
        invalid = [label for label, path in artifacts.items()
                   if not is_regular_unlinked(path) or lexists(partial(path))]
        if invalid:
            problems.append(f"{name} invalid: {','.join(invalid)}")
            continue
        expected_exit = {
            "schema": EXIT_SCHEMA,
            "run_id": RUN_ID,
            "job": name,
            "argv": list(argv),
            "returncode": 0,
            "output": rel(output),
            "output_regular_unlinked": True,
            "output_sha256": sha256_file(output),
            "log": rel(log),
            "log_sha256": sha256_file(log),
        }
        if _load_json(exit_path) != expected_exit:
            problems.append(f"{name} exit receipt drift")
            continue
        evidence.append({
            "job": name,
            "output": {"path": rel(output), "sha256": sha256_file(output)},
            "log": {"path": rel(log), "sha256": sha256_file(log)},
            "exit": {"path": rel(exit_path),
                     "sha256": sha256_file(exit_path)},
        })
    if len(evidence) != SHARD_COUNT:
        problems.append("terminal child evidence population")
    return evidence, sorted(set(problems))


def final_payload(*, paths: Paths, packet_sha256: str,
                  admission_sha256: str, aggregate: dict,
                  job_evidence: list[dict]) -> dict:
    status = aggregate.get("status")
    return {
        "schema": FINAL_SCHEMA,
        "run_id": RUN_ID,
        "complete": True,
        "packet_sha256": packet_sha256,
        "admission_sha256": admission_sha256,
        "receipt_sha256": sha256_file(paths.receipt),
        "progress_sha256": sha256_file(paths.progress_final),
        "jobs": job_evidence,
        "shards": [{"path": rel(path), "sha256": sha256_file(path),
                    "shard_index": index}
                   for index, path in enumerate(paths.shards)],
        "aggregate": {"path": rel(paths.aggregate),
                      "sha256": sha256_file(paths.aggregate),
                      "status": status},
        "replication_confirmed": (
            status == "CONFIRM_S4_POINT_BANKING_REPLICATION"),
        "strength_claim": (
            status == "CONFIRM_S4_POINT_BANKING_REPLICATION"),
        "production_promotion": False,
        "explicit_deployment_review_required": True,
        "retry_or_extension_authorized": False,
    }


def launch(config: Config) -> None:
    paths = paths_for()
    parent, runtime, _ = launch_preflight(config, paths)
    packet = _load_json(paths.packet)
    packet_sha256 = sha256_file(paths.packet)
    admission_sha256 = sha256_file(paths.admission)
    receipt = {
        "schema": CORE.RECEIPT_SCHEMA,
        "run_id": RUN_ID,
        "complete": True,
        "git": config.expected_git,
        "runner_sha256": config.expected_runner_sha256,
        "controller_sha256": config.expected_controller_sha256,
        "created_time_ns": time.time_ns(),
        "nonce": secrets.token_hex(32),
        "packet_sha256": packet_sha256,
        "admission_sha256": admission_sha256,
        "preflight_sha256": packet["score_free_preflight"]["sha256"],
        "screen_aggregate_sha256": CORE.SCREEN_AGGREGATE_SHA256,
        "screen_final_sha256": CORE.SCREEN_FINAL_SHA256,
        "replication_launch_authorized": True,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "retry_or_extension_authorized": False,
    }
    problems = receipt_problems(
        receipt, config=config, packet_sha256=packet_sha256,
        admission_sha256=admission_sha256,
        preflight_sha256=packet["score_free_preflight"]["sha256"])
    if problems:
        raise SupervisorRefused("; ".join(problems))
    _write_json_exclusive(paths.receipt, receipt)
    execution_receipt_sha256 = sha256_file(paths.receipt)
    progress = Progress(paths.progress_partial)
    jobs: list[Job] = []
    try:
        progress.event(
            "launch", "receipt-published",
            packet_sha256=packet_sha256,
            admission_sha256=admission_sha256,
            receipt_sha256=execution_receipt_sha256)
        for name, argv, output, log, exit_path in _job_specs(
                config, paths, execution_receipt_sha256):
            job = _start_job(name, argv, output, log, exit_path)
            jobs.append(job)
            progress.event("shard", "started", job=name,
                           pid=job.process.pid, output=rel(output))
        _wait_parallel(jobs, progress, config.heartbeat_seconds)
        aggregate = _recompute_aggregate(
            config, paths, parent=parent, runtime=runtime)
        _write_json_exclusive(paths.aggregate, aggregate)
        if _load_json(paths.aggregate) != aggregate:
            raise SupervisorRefused("aggregate failed exact reopen")
        job_evidence, evidence_problems = terminal_job_evidence(
            config, paths, execution_receipt_sha256)
        if evidence_problems:
            raise SupervisorRefused("; ".join(evidence_problems))
        progress.event("aggregate", "complete",
                       status_value=aggregate.get("status"),
                       aggregate_sha256=sha256_file(paths.aggregate))
        progress.close()
        _publish_partial(paths.progress_partial, paths.progress_final)
        final = final_payload(
            paths=paths, packet_sha256=packet_sha256,
            admission_sha256=admission_sha256, aggregate=aggregate,
            job_evidence=job_evidence)
        _write_json_exclusive(paths.final, final)
        print(json.dumps(final, indent=2, sort_keys=True), flush=True)
    except BaseException:
        _terminate(jobs)
        for job in jobs:
            if not job.finished:
                try:
                    _finish_job(job)
                except Exception:
                    pass
        raise
    finally:
        progress.close()


def verify(config: Config) -> dict:
    paths = paths_for()
    packet, parent, runtime = _expected_packet(config, paths)
    actual_packet, _ = _require_admission(config, paths)
    if actual_packet != packet:
        raise SupervisorRefused("terminal replication packet drift")
    terminal = (
        paths.receipt, paths.progress_final, paths.final,
        *paths.shards, *paths.shard_logs, *paths.shard_exits, paths.aggregate,
    )
    for path in terminal:
        if not is_regular_unlinked(path) or lexists(partial(path)):
            raise SupervisorRefused(
                f"terminal artifact missing, linked, or partial: {path}")
    packet_sha256 = sha256_file(paths.packet)
    admission_sha256 = sha256_file(paths.admission)
    preflight_sha256 = packet["score_free_preflight"]["sha256"]
    problems = receipt_problems(
        _load_json(paths.receipt), config=config,
        packet_sha256=packet_sha256, admission_sha256=admission_sha256,
        preflight_sha256=preflight_sha256)
    execution_receipt_sha256 = sha256_file(paths.receipt)
    aggregate = _load_json(paths.aggregate)
    if aggregate != _recompute_aggregate(
            config, paths, parent=parent, runtime=runtime):
        problems.append("aggregate full recomputation drift")
    job_evidence, evidence_problems = terminal_job_evidence(
        config, paths, execution_receipt_sha256)
    problems += evidence_problems
    expected_final = final_payload(
        paths=paths, packet_sha256=packet_sha256,
        admission_sha256=admission_sha256, aggregate=aggregate,
        job_evidence=job_evidence)
    if _load_json(paths.final) != expected_final:
        problems.append("supervisor final full recomputation drift")
    if problems:
        raise SupervisorRefused("terminal replication verify: "
                                + "; ".join(sorted(set(problems))))
    result = {
        "verified": True,
        "run_id": RUN_ID,
        "status": aggregate.get("status"),
        "final_sha256": sha256_file(paths.final),
        "strength_claim": aggregate.get("strength_claim") is True,
        "production_promotion": False,
    }
    print(json.dumps(result, sort_keys=True), flush=True)
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=("freeze", "verify-packet", "admit", "launch",
                            "verify"))
    parser.add_argument("--expected-git", required=True)
    parser.add_argument("--expected-runner-sha256", required=True)
    parser.add_argument("--expected-controller-sha256", required=True)
    parser.add_argument("--heartbeat-seconds", type=float, default=30.0)
    parser.add_argument("--review-record")
    parser.add_argument("--expected-review-sha256")
    parser.add_argument("--expected-packet-sha256")
    args = parser.parse_args(argv)
    if not 1.0 <= args.heartbeat_seconds <= 60.0:
        raise SupervisorRefused("heartbeat must be between 1 and 60 seconds")
    config = Config(
        expected_git=args.expected_git,
        expected_runner_sha256=args.expected_runner_sha256,
        expected_controller_sha256=args.expected_controller_sha256,
        heartbeat_seconds=args.heartbeat_seconds)
    if args.command == "freeze":
        print(json.dumps(freeze_packet(config), sort_keys=True))
    elif args.command == "verify-packet":
        packet = verify_packet(config)
        print(json.dumps({
            "verified": True,
            "packet_sha256": sha256_file(paths_for().packet),
            "replication_launch_authorized":
            packet["replication_launch_authorized"],
        }, sort_keys=True))
    elif args.command == "admit":
        if not all((args.review_record, args.expected_review_sha256,
                    args.expected_packet_sha256)):
            raise SupervisorRefused(
                "admit requires review path and both hashes")
        print(json.dumps(admit_packet(
            config, Path(args.review_record), args.expected_review_sha256,
            args.expected_packet_sha256), sort_keys=True))
    elif args.command == "launch":
        launch(config)
    else:
        verify(config)


if __name__ == "__main__":
    try:
        main()
    except (SupervisorRefused, CORE.ProtocolRefused,
            CORE.DUEL.ProtocolRefused) as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc

#!/usr/bin/env python3
"""Freeze, admit, and supervise the S3a complete-round Mini screen.

The score-free preflight may authorize only review of this packet.  The
freeze command binds terminal evidence, live champion, runtime, source bytes,
fresh 2,048-cluster population, eight commands and output namespace without
granting strength compute.  Admit accepts one hash-pinned external PASS.
Only then can launch run the eight shards once and aggregate them.

Any collision, child failure, signal, source drift or aggregate mismatch
consumes the namespace in place and leaves no terminal supervisor final.  The
controller never retries, resumes, deletes, confirms, promotes or deploys.
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

import s3a_bury_duel as DUEL  # noqa: E402


SCHEMA = "s3a-bury-duel-screen-controller-v1"
PACKET_SCHEMA = "s3a-bury-duel-screen-packet-v1"
ADMISSION_SCHEMA = "s3a-bury-duel-screen-admission-v1"
PACKET_REVIEW_SCHEMA = "s3a-bury-duel-screen-review-v1"
PACKET_REVIEW_MARKER = "S3A_DUEL_SCREEN_PACKET_V1_REVIEW "
RECEIPT_SCHEMA = "s3a-bury-duel-screen-receipt-v1"
FINAL_SCHEMA = "s3a-bury-duel-screen-final-v1"
EXIT_SCHEMA = "s3a-bury-duel-screen-exit-v1"
RUN_ID = DUEL.PHASES["screen"]["run_id"]
EXPECTED_HOST = "Jerrys-Mac-mini.local"
EXPECTED_PYTHON = "3.14.3"
NAMESPACE = Path("server/runs/logs") / RUN_ID
RUNNER = Path("server/scripts/s3a_bury_duel.py")
SHARD_COUNT = DUEL.SHARD_COUNT
SHARD_NAMES = tuple(f"shard-{index:02d}.json" for index in range(SHARD_COUNT))
AGGREGATE_NAME = "aggregate.json"
PACKET_NAME = "launch_packet.json"
REVIEW_NAME = "review_record.txt"
ADMISSION_NAME = "review_admission.json"
RECEIPT_NAME = "receipt.json"
PROGRESS_NAME = "supervisor.jsonl"
FINAL_NAME = "supervisor-final.json"
PREFLIGHT_ROOT = ROOT / "server/runs/logs/s3a-bury-duel-preflight-18b-v1"
PREFLIGHT_RECEIPT_SHA256 = (
    "972809744b837130b958e7a6de6c9cb9d8e6d57f17c444bf7bf40c53b82468ca"
)
PREFLIGHT_SHA256 = (
    "09692f823d26d38ea76c7c6e36ea007a5031c0f05ca1a76795c84e7d0722edf0"
)
PREFLIGHT_PROGRESS_SHA256 = (
    "44ad26d0f5621ef23b4afa078d4ea98b84bf611010f007075846c72853f14e16"
)
PREFLIGHT_FINAL_SHA256 = (
    "56943242f3620b09774a55eab992fbac0bce6ad224c3ada6a7b54a5634799e9f"
)
PREFLIGHT_CONTRACT_SHA256 = (
    "5e0f6ade690f308b812cdb8ff73e87df7f3619514f6a89c27c9b1cbb15b44653"
)


class SupervisorRefusal(RuntimeError):
    """A one-shot launch or terminal evidence boundary was violated."""


@dataclass(frozen=True)
class Config:
    expected_git: str
    expected_runner_sha256: str
    expected_controller_sha256: str
    heartbeat_seconds: float


@dataclass(frozen=True)
class Paths:
    namespace: Path
    runner: Path
    controller: Path
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
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


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
    shards = tuple(namespace / name for name in SHARD_NAMES)
    shard_logs = tuple(namespace / f"shard-{index:02d}.log"
                       for index in range(SHARD_COUNT))
    # Keep exit receipts visibly distinct from evidence-shard names.
    shard_exits = tuple(namespace / f"exit-shard-{index:02d}.json"
                       for index in range(SHARD_COUNT))
    aggregate = namespace / AGGREGATE_NAME
    return Paths(
        namespace=namespace,
        runner=ROOT / RUNNER,
        controller=Path(__file__).resolve(),
        packet=namespace / PACKET_NAME,
        review_copy=namespace / REVIEW_NAME,
        admission=namespace / ADMISSION_NAME,
        receipt=namespace / RECEIPT_NAME,
        progress_partial=namespace / f"{PROGRESS_NAME}.partial",
        progress_final=namespace / PROGRESS_NAME,
        final=namespace / FINAL_NAME,
        shards=shards,
        shard_logs=shard_logs,
        shard_exits=shard_exits,
        aggregate=aggregate,
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
        raise SupervisorRefusal(f"cannot publish {path}: {exc}") from exc


def _publish_partial(partial_path: Path, final_path: Path) -> None:
    try:
        os.link(partial_path, final_path)
    except FileExistsError as exc:
        raise SupervisorRefusal(f"refusing to overwrite {final_path}") from exc
    os.unlink(partial_path)


def shard_argv(config: Config, index: int, output: Path) -> tuple[str, ...]:
    return (
        sys.executable, str(ROOT / RUNNER), "run",
        "--expected-git", config.expected_git,
        "--phase", "screen",
        "--shard-index", str(index),
        "--progress-every", "1",
        "--out", str(output),
    )


def _artifact_ref(path: Path, expected_sha256: str, label: str) -> dict:
    if not is_regular_unlinked(path) or lexists(partial(path)):
        raise SupervisorRefusal(f"{label} is missing, linked, or partial")
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise SupervisorRefusal(f"{label} SHA-256 drift")
    return {"path": str(path), "sha256": actual}


def preflight_evidence() -> dict:
    receipt_ref = _artifact_ref(
        PREFLIGHT_ROOT / "receipt.json",
        PREFLIGHT_RECEIPT_SHA256, "preflight receipt")
    preflight_ref = _artifact_ref(
        PREFLIGHT_ROOT / "preflight.json",
        PREFLIGHT_SHA256, "preflight output")
    progress_ref = _artifact_ref(
        PREFLIGHT_ROOT / "supervisor.jsonl",
        PREFLIGHT_PROGRESS_SHA256, "preflight progress")
    final_ref = _artifact_ref(
        PREFLIGHT_ROOT / "supervisor-final.json",
        PREFLIGHT_FINAL_SHA256, "preflight final")
    payload = _load_json(PREFLIGHT_ROOT / "preflight.json")
    final = _load_json(PREFLIGHT_ROOT / "supervisor-final.json")
    if (payload.get("schema") != DUEL.PREFLIGHT_SCHEMA
            or payload.get("complete") is not True
            or payload.get("score_free") is not True
            or payload.get("capacity_pass") is not True
            or payload.get("problems") != []
            or payload.get("strength_launch_authorized") is not False
            or payload.get("production_promotion") is not False):
        raise SupervisorRefusal("preflight output identity/authority drift")
    projections = payload.get("projections")
    budgets = payload.get("budgets")
    if (not isinstance(projections, dict) or not isinstance(budgets, dict)
            or projections.get("screen", {}).get("fleet_hours", float("inf"))
            > budgets.get("screen_fleet_hours", -1)
            or projections.get("screen", {}).get(
                "max_shard_hours", float("inf"))
            > budgets.get("screen_max_shard_hours", -1)):
        raise SupervisorRefusal("preflight screen capacity arithmetic drift")
    if (final.get("schema") !=
            "s3a-bury-duel-preflight-final-v1"
            or final.get("complete") is not True
            or final.get("contract_sha256") != PREFLIGHT_CONTRACT_SHA256
            or final.get("receipt_sha256") != PREFLIGHT_RECEIPT_SHA256
            or final.get("progress_sha256") != PREFLIGHT_PROGRESS_SHA256
            or final.get("preflight", {}).get("sha256") != PREFLIGHT_SHA256
            or final.get("status") != "AUTHORIZE_SCREEN_PACKET_REVIEW"
            or final.get("screen_packet_review_authorized") is not True
            or final.get("strength_launch_authorized") is not False
            or final.get("retry_or_resume_authorized") is not False
            or final.get("production_promotion") is not False):
        raise SupervisorRefusal("preflight terminal authority drift")
    return {
        "receipt": receipt_ref,
        "preflight": preflight_ref,
        "progress": progress_ref,
        "final": final_ref,
        "contract_sha256": PREFLIGHT_CONTRACT_SHA256,
        "terminal_status": final["status"],
        "screen_projection": projections["screen"],
        "screen_budgets": {
            "fleet_hours": budgets["screen_fleet_hours"],
            "max_shard_hours": budgets["screen_max_shard_hours"],
        },
        "strength_launch_authorized": False,
    }


def packet_contract(config: Config, paths: Paths, *, parent: dict,
                    runtime: dict, preflight: dict) -> dict:
    phase = DUEL.phase_identity("screen")
    return {
        "schema": PACKET_SCHEMA,
        "run_id": RUN_ID,
        "phase": "screen",
        "phase_identity": phase,
        "claim_boundary": DUEL.CLAIM_BOUNDARY,
        "one_shot": True,
        "review_required": True,
        "screen_launch_authorized": False,
        "confirmation_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "retry_or_resume_authorized": False,
        "host": EXPECTED_HOST,
        "python": {
            "executable": sys.executable,
            "version": EXPECTED_PYTHON,
        },
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
        "runtime_identity": runtime,
        "parent": parent,
        "preflight_evidence": preflight,
        "mechanism": {
            "runner_schema": DUEL.SCHEMA,
            "aggregate_schema": DUEL.AGGREGATE_SCHEMA,
            "labels": DUEL.LABELS,
            "label_order": list(DUEL.LABEL_ORDER),
            "opponent": DUEL.OPPONENT,
            "selection_rule": DUEL.SELECTION_RULE,
            "clusters": phase["clusters"],
            "shard_count": phase["shard_count"],
            "clusters_per_shard": phase["clusters_per_shard"],
            "seed0": phase["seed0"],
            "stream_stride": phase["stream_stride"],
            "stream_digest": runtime["stream_digests"]["screen"],
            "unit": "mirrored complete-round deal cluster",
        },
        "commands": {
            "shards": [
                list(shard_argv(config, index, paths.shards[index]))
                for index in range(SHARD_COUNT)
            ],
            "aggregate": (
                "controller reopens exact shard bytes/hashes and calls "
                "DUEL.build_aggregate once"),
        },
        "outputs": {
            "namespace": str(paths.namespace),
            "packet": str(paths.packet),
            "review_copy": str(paths.review_copy),
            "admission": str(paths.admission),
            "receipt": str(paths.receipt),
            "shards": [str(path) for path in paths.shards],
            "shard_logs": [str(path) for path in paths.shard_logs],
            "shard_exits": [str(path) for path in paths.shard_exits],
            "aggregate": str(paths.aggregate),
            "progress": str(paths.progress_final),
            "supervisor_final": str(paths.final),
        },
        "stop_rule": (
            "first nonzero shard terminates siblings; no aggregate; preserve "
            "all bytes; never retry or extend this namespace"),
        "terminal_gate": {
            "pass": "AUTHORIZE_CONFIRM_PACKET_REVIEW",
            "failure": "SELECT_NONE",
            "confirmation_launch": False,
            "production_promotion": False,
        },
    }


def _identity_context(config: Config, paths: Paths) -> tuple[dict, dict]:
    if not all(is_sha256(value) for value in (
            config.expected_runner_sha256,
            config.expected_controller_sha256)):
        raise SupervisorRefusal("expected source SHA-256 is malformed")
    if (not isinstance(config.expected_git, str)
            or len(config.expected_git) != 40
            or any(character not in "0123456789abcdef"
                   for character in config.expected_git)):
        raise SupervisorRefusal("expected git is malformed")
    if os.uname().nodename != EXPECTED_HOST:
        raise SupervisorRefusal(
            f"screen is pinned to {EXPECTED_HOST}, got {os.uname().nodename}")
    if _git("rev-parse", "HEAD") != config.expected_git:
        raise SupervisorRefusal("screen exact git predeclaration drift")
    if _git("status", "--porcelain"):
        raise SupervisorRefusal("screen refuses a dirty tree")
    if sha256_file(paths.runner) != config.expected_runner_sha256:
        raise SupervisorRefusal("screen runner SHA-256 drift")
    if sha256_file(paths.controller) != config.expected_controller_sha256:
        raise SupervisorRefusal("screen controller SHA-256 drift")
    if os.environ.get("SHENGJI_FAST") != "1" or \
            os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise SupervisorRefusal(
            "set SHENGJI_FAST=1 and SHENGJI_REQUIRE_VOIDS=1")
    enabled = [name for name in DUEL.REFUSED_ENV_KEYS if name in os.environ]
    if enabled:
        raise SupervisorRefusal(
            f"experimental sampler/ballot keys must be absent: {enabled}")
    try:
        _, parent, runtime = DUEL.require_runtime(config.expected_git)
    except Exception as exc:
        raise SupervisorRefusal(f"S3a duel context refused: {exc}") from exc
    if (runtime.get("host") != EXPECTED_HOST
            or runtime.get("python") != EXPECTED_PYTHON):
        raise SupervisorRefusal("runtime host/Python identity mismatch")
    return parent, runtime


def _execution_targets(paths: Paths) -> tuple[Path, ...]:
    finals = (
        paths.receipt, paths.progress_final, paths.final,
        *paths.shards, *paths.shard_logs, *paths.shard_exits,
        paths.aggregate,
    )
    return tuple(finals) + tuple(partial(path) for path in finals)


def _expected_packet(config: Config, paths: Paths) -> tuple[dict, dict, dict]:
    parent, runtime = _identity_context(config, paths)
    preflight = preflight_evidence()
    packet = packet_contract(
        config, paths, parent=parent, runtime=runtime, preflight=preflight)
    return packet, parent, runtime


def freeze_packet(config: Config) -> dict:
    paths = paths_for()
    packet, _, _ = _expected_packet(config, paths)
    if paths.namespace.exists() and any(paths.namespace.iterdir()):
        raise SupervisorRefusal("screen freeze namespace must be absent or empty")
    paths.namespace.mkdir(parents=True, exist_ok=True)
    _write_json_exclusive(paths.packet, packet)
    if _load_json(paths.packet) != packet:
        raise SupervisorRefusal("frozen packet failed exact reopen")
    return {
        "path": str(paths.packet),
        "sha256": sha256_file(paths.packet),
        "screen_launch_authorized": False,
        "review_required": True,
    }


def verify_packet(config: Config, paths: Paths | None = None) -> dict:
    paths = paths or paths_for()
    packet, _, _ = _expected_packet(config, paths)
    if (not is_regular_unlinked(paths.packet)
            or lexists(partial(paths.packet))
            or _load_json(paths.packet) != packet):
        raise SupervisorRefusal("frozen screen packet drift")
    return packet


def _write_bytes_exclusive(path: Path, raw: bytes) -> None:
    candidate = partial(path)
    if lexists(path) or lexists(candidate):
        raise SupervisorRefusal(f"refusing to overwrite {path}")
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


def _review_claim(raw: bytes, *, packet_sha256: str,
                  config: Config) -> dict:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SupervisorRefusal("review record is not UTF-8") from exc
    matches = [
        line[len(PACKET_REVIEW_MARKER):]
        for line in text.splitlines()
        if line.startswith(PACKET_REVIEW_MARKER)
    ]
    if len(matches) != 1:
        raise SupervisorRefusal(
            "review record must contain exactly one packet marker")
    try:
        claim = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise SupervisorRefusal("review marker is invalid JSON") from exc
    expected = {
        "schema": PACKET_REVIEW_SCHEMA,
        "git": config.expected_git,
        "run_id": RUN_ID,
        "packet_sha256": packet_sha256,
        "preflight_final_sha256": PREFLIGHT_FINAL_SHA256,
        "independent_review": True,
        "screen_launch_authorized": True,
        "confirmation_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "verdict": "PASS",
    }
    if claim != expected:
        raise SupervisorRefusal(
            "review marker does not grant the exact narrow screen authority")
    return claim


def admit_packet(config: Config, review_record: Path,
                 expected_review_sha256: str,
                 expected_packet_sha256: str) -> dict:
    paths = paths_for()
    verify_packet(config, paths)
    packet_sha256 = sha256_file(paths.packet)
    if packet_sha256 != expected_packet_sha256:
        raise SupervisorRefusal("expected packet SHA-256 mismatch")
    if (not is_regular_unlinked(review_record)
            or review_record.resolve().is_relative_to(paths.namespace.resolve())):
        raise SupervisorRefusal(
            "review source must be a regular external file")
    raw = review_record.read_bytes()
    if sha256_file(review_record) != expected_review_sha256:
        raise SupervisorRefusal("expected review SHA-256 mismatch")
    claim = _review_claim(
        raw, packet_sha256=packet_sha256, config=config)
    _write_bytes_exclusive(paths.review_copy, raw)
    admission = {
        "schema": ADMISSION_SCHEMA,
        "run_id": RUN_ID,
        "packet": {"path": str(paths.packet), "sha256": packet_sha256},
        "review": {
            "path": str(paths.review_copy),
            "sha256": expected_review_sha256,
        },
        "review_claim": claim,
        "operator_asserted_independent_review": True,
        "screen_launch_authorized": True,
        "confirmation_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
    }
    _write_json_exclusive(paths.admission, admission)
    return {
        "path": str(paths.admission),
        "sha256": sha256_file(paths.admission),
        "screen_launch_authorized": True,
    }


def _require_admission(config: Config, paths: Paths) -> tuple[dict, dict]:
    packet = verify_packet(config, paths)
    for path, label in (
            (paths.review_copy, "review copy"),
            (paths.admission, "review admission")):
        if not is_regular_unlinked(path) or lexists(partial(path)):
            raise SupervisorRefusal(f"{label} is missing, linked, or partial")
    packet_sha256 = sha256_file(paths.packet)
    review_raw = paths.review_copy.read_bytes()
    review_sha256 = sha256_file(paths.review_copy)
    claim = _review_claim(
        review_raw, packet_sha256=packet_sha256, config=config)
    expected = {
        "schema": ADMISSION_SCHEMA,
        "run_id": RUN_ID,
        "packet": {"path": str(paths.packet), "sha256": packet_sha256},
        "review": {
            "path": str(paths.review_copy),
            "sha256": review_sha256,
        },
        "review_claim": claim,
        "operator_asserted_independent_review": True,
        "screen_launch_authorized": True,
        "confirmation_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
    }
    if _load_json(paths.admission) != expected:
        raise SupervisorRefusal("review admission drift")
    return packet, expected


def launch_preflight(
        config: Config, paths: Paths) -> tuple[dict, dict, dict, dict]:
    packet, parent, runtime = _expected_packet(config, paths)
    actual, admission = _require_admission(config, paths)
    if actual != packet:
        raise SupervisorRefusal("admitted packet drift")
    collisions = [
        str(path) for path in _execution_targets(paths) if lexists(path)
    ]
    if collisions:
        raise SupervisorRefusal(
            f"screen execution namespace collision: {collisions[:3]}")
    allowed = {paths.packet.name, paths.review_copy.name, paths.admission.name}
    present = {path.name for path in paths.namespace.iterdir()}
    if present != allowed:
        raise SupervisorRefusal(
            f"screen namespace contains unknown bytes: {sorted(present - allowed)}")
    return packet, parent, runtime, admission


class Progress:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.handle = path.open("x", encoding="utf-8")
        except FileExistsError as exc:
            raise SupervisorRefusal(f"progress collision: {path}") from exc
        self.path = path
        self.closed = False

    def event(self, phase: str, status: str, **fields: object) -> None:
        payload = {
            "schema": SCHEMA,
            "time_ns": time.time_ns(),
            "phase": phase,
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


def _start_job(name: str, argv: tuple[str, ...], output: Path,
               log_final: Path, exit_final: Path) -> Job:
    log_partial = partial(log_final)
    try:
        handle = log_partial.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise SupervisorRefusal(f"job log collision: {log_partial}") from exc
    process = subprocess.Popen(
        argv, cwd=ROOT, env=os.environ.copy(),
        stdout=handle, stderr=subprocess.STDOUT, text=True,
        start_new_session=True,
    )
    return Job(
        name=name, argv=argv, output=output,
        log_partial=log_partial, log_final=log_final,
        exit_final=exit_final, handle=handle, process=process,
    )


def _finish_job(job: Job) -> int:
    if job.finished:
        return int(job.process.returncode)
    returncode = job.process.wait()
    job.handle.flush()
    os.fsync(job.handle.fileno())
    job.handle.close()
    _publish_partial(job.log_partial, job.log_final)
    output_ok = is_regular_unlinked(job.output) and not lexists(partial(job.output))
    _write_json_exclusive(job.exit_final, {
        "schema": EXIT_SCHEMA,
        "run_id": RUN_ID,
        "job": job.name,
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


def _terminate(jobs: list[Job]) -> None:
    for job in jobs:
        if not job.finished and job.process.poll() is None:
            try:
                os.killpg(job.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def _job_progress(job: Job) -> dict:
    source = job.log_final if job.finished else job.log_partial
    completed = 0
    if source.is_file():
        try:
            lines = source.read_text(encoding="utf-8", errors="strict").splitlines()
        except OSError:
            lines = []
        for line in reversed(lines):
            try:
                payload = json.loads(line)
            except (TypeError, ValueError):
                continue
            if (isinstance(payload, dict)
                    and payload.get("event") == "s3a-bury-duel-progress-v1"
                    and payload.get("phase") == "screen"
                    and payload.get("clusters_total")
                    == DUEL.PHASES["screen"]["clusters_per_shard"]
                    and isinstance(payload.get("clusters_complete"), int)):
                completed = payload["clusters_complete"]
                break
    if job.finished and job.process.returncode == 0:
        completed = DUEL.PHASES["screen"]["clusters_per_shard"]
    return {
        "job": job.name,
        "clusters_complete": completed,
        "clusters_total": DUEL.PHASES["screen"]["clusters_per_shard"],
        "finished": job.finished,
    }


def _wait_parallel(jobs: list[Job], progress: Progress,
                   heartbeat_seconds: float) -> None:
    last_heartbeat = 0.0
    first_failure = None
    while any(not job.finished for job in jobs):
        for job in jobs:
            if job.finished or job.process.poll() is None:
                continue
            returncode = _finish_job(job)
            progress.event(
                "shard", "complete" if returncode == 0 else "failed",
                job=job.name, returncode=returncode,
                output=str(job.output),
            )
            if returncode != 0 and first_failure is None:
                first_failure = job.name
                _terminate(jobs)
        now = time.monotonic()
        if now - last_heartbeat >= heartbeat_seconds:
            progress.event(
                "shards", "running",
                complete=sum(job.finished for job in jobs),
                total=len(jobs),
                live=[job.name for job in jobs if not job.finished],
                shard_progress=[_job_progress(job) for job in jobs],
            )
            last_heartbeat = now
        time.sleep(0.2)
    if first_failure is not None:
        raise SupervisorRefusal(
            f"shard failure consumed namespace: {first_failure}")


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise SupervisorRefusal(f"cannot reopen {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SupervisorRefusal(f"artifact is not an object: {path}")
    return value



def _recompute_aggregate(paths: Paths, *, parent: dict,
                         runtime: dict) -> dict:
    shards = []
    inputs = []
    problems = []
    for index, path in enumerate(paths.shards):
        if not is_regular_unlinked(path) or lexists(partial(path)):
            problems.append(f"shard {index} missing, linked, or partial")
            continue
        payload = _load_json(path)
        problems.extend(
            f"shard {index}: {problem}"
            for problem in DUEL.shard_problems(
                payload, phase="screen", shard_index=index,
                parent=parent, runtime=runtime)
        )
        shards.append(payload)
        inputs.append({
            "path": str(path),
            "sha256": sha256_file(path),
            "shard_index": index,
        })
    if len(shards) != SHARD_COUNT:
        problems.append("aggregate shard population")
    if len({item["path"] for item in inputs}) != SHARD_COUNT:
        problems.append("aggregate shard path uniqueness")
    if len({item["sha256"] for item in inputs}) != SHARD_COUNT:
        problems.append("aggregate shard hash uniqueness")
    if problems:
        raise SupervisorRefusal(
            "aggregate inputs: " + "; ".join(sorted(set(problems))))
    return DUEL.build_aggregate(
        phase="screen", shards=shards, inputs=inputs,
        parent=parent, runtime=runtime, screen_parent=None)


def receipt_problems(receipt: dict, *, packet_sha256: str,
                     admission_sha256: str) -> list[str]:
    expected = {
        "schema": RECEIPT_SCHEMA,
        "run_id": RUN_ID,
        "complete": True,
        "created_time_ns": receipt.get("created_time_ns"),
        "nonce": receipt.get("nonce"),
        "packet_sha256": packet_sha256,
        "admission_sha256": admission_sha256,
        "preflight_final_sha256": PREFLIGHT_FINAL_SHA256,
        "screen_launch_authorized": True,
        "confirmation_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "retry_or_resume_authorized": False,
    }
    problems = []
    if receipt != expected:
        problems.append("receipt full recomputation drift")
    created = receipt.get("created_time_ns")
    if isinstance(created, bool) or not isinstance(created, int) or created <= 0:
        problems.append("receipt creation time")
    if not is_sha256(receipt.get("nonce")):
        problems.append("receipt nonce")
    return sorted(set(problems))


def _job_specs(
        config: Config, paths: Paths,
) -> list[tuple[str, tuple[str, ...], Path, Path, Path]]:
    return [
        (
            f"shard-{index:02d}",
            shard_argv(config, index, paths.shards[index]),
            paths.shards[index],
            paths.shard_logs[index],
            paths.shard_exits[index],
        )
        for index in range(SHARD_COUNT)
    ]


def terminal_job_evidence(
        config: Config, paths: Paths,
) -> tuple[list[dict], list[str]]:
    evidence = []
    problems = []
    for name, argv, output, log, exit_path in _job_specs(config, paths):
        artifacts = {"output": output, "log": log, "exit": exit_path}
        invalid = [
            label for label, path in artifacts.items()
            if not is_regular_unlinked(path) or lexists(partial(path))
        ]
        if invalid:
            problems.append(
                f"{name} terminal artifact invalid: {','.join(invalid)}")
            continue
        output_sha256 = sha256_file(output)
        log_sha256 = sha256_file(log)
        expected_exit = {
            "schema": EXIT_SCHEMA,
            "run_id": RUN_ID,
            "job": name,
            "argv": list(argv),
            "returncode": 0,
            "output": str(output),
            "output_regular_unlinked": True,
            "output_sha256": output_sha256,
            "log": str(log),
            "log_sha256": log_sha256,
        }
        try:
            actual_exit = _load_json(exit_path)
        except SupervisorRefusal as exc:
            problems.append(str(exc))
            continue
        if actual_exit != expected_exit:
            problems.append(f"{name} exit receipt full recomputation drift")
            continue
        evidence.append({
            "job": name,
            "output": {"path": str(output), "sha256": output_sha256},
            "log": {"path": str(log), "sha256": log_sha256},
            "exit": {
                "path": str(exit_path),
                "sha256": sha256_file(exit_path),
            },
        })
    if len(evidence) != SHARD_COUNT:
        problems.append("terminal child evidence population")
    return evidence, sorted(set(problems))


def final_problems(final: dict, *, packet_sha256: str,
                   admission_sha256: str, receipt_sha256: str,
                   progress_sha256: str, shard_sha256s: list[str],
                   aggregate_sha256: str, aggregate: dict,
                   job_evidence: list[dict], paths: Paths) -> list[str]:
    status = aggregate.get("status")
    expected = {
        "schema": FINAL_SCHEMA,
        "run_id": RUN_ID,
        "complete": True,
        "packet_sha256": packet_sha256,
        "admission_sha256": admission_sha256,
        "receipt_sha256": receipt_sha256,
        "progress_sha256": progress_sha256,
        "jobs": job_evidence,
        "shards": [
            {
                "path": str(paths.shards[index]),
                "sha256": shard_sha256s[index],
                "shard_index": index,
            }
            for index in range(SHARD_COUNT)
        ],
        "aggregate": {
            "path": str(paths.aggregate),
            "sha256": aggregate_sha256,
            "status": status,
        },
        "screen_gate_passed": status == "AUTHORIZE_CONFIRM_PACKET_REVIEW",
        "confirm_packet_review_authorized": (
            status == "AUTHORIZE_CONFIRM_PACKET_REVIEW"),
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "retry_or_resume_authorized": False,
    }
    return ([] if final == expected else
            ["supervisor final full recomputation drift"])


def launch(config: Config) -> None:
    paths = paths_for()
    _, parent, runtime, _ = launch_preflight(config, paths)
    packet_sha256 = sha256_file(paths.packet)
    admission_sha256 = sha256_file(paths.admission)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "run_id": RUN_ID,
        "complete": True,
        "created_time_ns": time.time_ns(),
        "nonce": secrets.token_hex(32),
        "packet_sha256": packet_sha256,
        "admission_sha256": admission_sha256,
        "preflight_final_sha256": PREFLIGHT_FINAL_SHA256,
        "screen_launch_authorized": True,
        "confirmation_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "retry_or_resume_authorized": False,
    }
    problems = receipt_problems(
        receipt, packet_sha256=packet_sha256,
        admission_sha256=admission_sha256)
    if problems:
        raise SupervisorRefusal("; ".join(problems))
    _write_json_exclusive(paths.receipt, receipt)
    progress = Progress(paths.progress_partial)
    jobs: list[Job] = []
    try:
        progress.event(
            "launch", "receipt-published",
            receipt_sha256=sha256_file(paths.receipt),
            packet_sha256=packet_sha256,
            admission_sha256=admission_sha256,
        )
        for index in range(SHARD_COUNT):
            job = _start_job(
                f"shard-{index:02d}",
                shard_argv(config, index, paths.shards[index]),
                paths.shards[index], paths.shard_logs[index],
                paths.shard_exits[index],
            )
            jobs.append(job)
            progress.event(
                "shard", "started", job=job.name,
                pid=job.process.pid, output=str(job.output),
            )
        _wait_parallel(jobs, progress, config.heartbeat_seconds)

        aggregate = _recompute_aggregate(
            paths, parent=parent, runtime=runtime)
        _write_json_exclusive(paths.aggregate, aggregate)
        if _load_json(paths.aggregate) != aggregate:
            raise SupervisorRefusal("aggregate failed exact reopen")
        job_evidence, evidence_problems = terminal_job_evidence(config, paths)
        if evidence_problems:
            raise SupervisorRefusal("; ".join(evidence_problems))
        progress.event(
            "aggregate", "complete",
            status_value=aggregate.get("status"),
            aggregate_sha256=sha256_file(paths.aggregate),
        )
        progress.close()
        _publish_partial(paths.progress_partial, paths.progress_final)
        final = {
            "schema": FINAL_SCHEMA,
            "run_id": RUN_ID,
            "complete": True,
            "packet_sha256": packet_sha256,
            "admission_sha256": admission_sha256,
            "receipt_sha256": sha256_file(paths.receipt),
            "progress_sha256": sha256_file(paths.progress_final),
            "jobs": job_evidence,
            "shards": [
                {
                    "path": str(path),
                    "sha256": sha256_file(path),
                    "shard_index": index,
                }
                for index, path in enumerate(paths.shards)
            ],
            "aggregate": {
                "path": str(paths.aggregate),
                "sha256": sha256_file(paths.aggregate),
                "status": aggregate.get("status"),
            },
            "screen_gate_passed": (
                aggregate.get("status")
                == "AUTHORIZE_CONFIRM_PACKET_REVIEW"),
            "confirm_packet_review_authorized": (
                aggregate.get("status")
                == "AUTHORIZE_CONFIRM_PACKET_REVIEW"),
            "confirmation_launch_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "retry_or_resume_authorized": False,
        }
        problems = final_problems(
            final,
            packet_sha256=packet_sha256,
            admission_sha256=admission_sha256,
            receipt_sha256=sha256_file(paths.receipt),
            progress_sha256=sha256_file(paths.progress_final),
            shard_sha256s=[sha256_file(path) for path in paths.shards],
            aggregate_sha256=sha256_file(paths.aggregate),
            aggregate=aggregate,
            job_evidence=job_evidence,
            paths=paths,
        )
        if problems:
            raise SupervisorRefusal("; ".join(problems))
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


def verify(config: Config) -> None:
    paths = paths_for()
    packet, parent, runtime = _expected_packet(config, paths)
    actual_packet, _ = _require_admission(config, paths)
    if actual_packet != packet:
        raise SupervisorRefusal("terminal packet drift")
    terminal_paths = (
        paths.receipt, paths.progress_final, paths.final,
        *paths.shards, *paths.shard_logs, *paths.shard_exits,
        paths.aggregate,
    )
    for path in terminal_paths:
        if not is_regular_unlinked(path) or lexists(partial(path)):
            raise SupervisorRefusal(
                f"terminal artifact is missing, linked, or partial: {path}")
    packet_sha256 = sha256_file(paths.packet)
    admission_sha256 = sha256_file(paths.admission)
    receipt = _load_json(paths.receipt)
    problems = receipt_problems(
        receipt, packet_sha256=packet_sha256,
        admission_sha256=admission_sha256)
    aggregate = _load_json(paths.aggregate)
    expected_aggregate = _recompute_aggregate(
        paths, parent=parent, runtime=runtime)
    if aggregate != expected_aggregate:
        problems.append("aggregate full recomputation drift")
    job_evidence, evidence_problems = terminal_job_evidence(config, paths)
    problems += evidence_problems
    final = _load_json(paths.final)
    problems += final_problems(
        final,
        packet_sha256=packet_sha256,
        admission_sha256=admission_sha256,
        receipt_sha256=sha256_file(paths.receipt),
        progress_sha256=sha256_file(paths.progress_final),
        shard_sha256s=[sha256_file(path) for path in paths.shards],
        aggregate_sha256=sha256_file(paths.aggregate),
        aggregate=aggregate,
        job_evidence=job_evidence,
        paths=paths,
    )
    if problems:
        raise SupervisorRefusal(
            "terminal verify: " + "; ".join(sorted(set(problems))))
    print(json.dumps({
        "verified": True,
        "run_id": RUN_ID,
        "status": aggregate.get("status"),
        "final_sha256": sha256_file(paths.final),
        "confirmation_launch_authorized": False,
        "production_promotion": False,
    }, sort_keys=True), flush=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("freeze", "verify-packet", "admit", "launch", "verify"))
    parser.add_argument("--expected-git", required=True)
    parser.add_argument("--expected-runner-sha256", required=True)
    parser.add_argument("--expected-controller-sha256", required=True)
    parser.add_argument("--heartbeat-seconds", type=float, default=30.0)
    parser.add_argument("--review-record")
    parser.add_argument("--expected-review-sha256")
    parser.add_argument("--expected-packet-sha256")
    args = parser.parse_args(argv)
    if not 1.0 <= args.heartbeat_seconds <= 60.0:
        raise SupervisorRefusal(
            "heartbeat must be between 1 and 60 seconds")
    config = Config(
        expected_git=args.expected_git,
        expected_runner_sha256=args.expected_runner_sha256,
        expected_controller_sha256=args.expected_controller_sha256,
        heartbeat_seconds=args.heartbeat_seconds,
    )
    if args.command == "freeze":
        print(json.dumps(
            {"launch_packet": freeze_packet(config)},
            sort_keys=True), flush=True)
        return
    if args.command == "verify-packet":
        verify_packet(config)
        print(json.dumps({
            "verified_packet": {
                "path": str(paths_for().packet),
                "sha256": sha256_file(paths_for().packet),
            },
            "screen_launch_authorized": False,
        }, sort_keys=True), flush=True)
        return
    if args.command == "admit":
        if not all((
                args.review_record,
                args.expected_review_sha256,
                args.expected_packet_sha256)):
            raise SupervisorRefusal(
                "admit requires review record and exact hashes")
        print(json.dumps({
            "review_admission": admit_packet(
                config, Path(args.review_record),
                args.expected_review_sha256,
                args.expected_packet_sha256),
        }, sort_keys=True), flush=True)
        return
    if any((
            args.review_record,
            args.expected_review_sha256,
            args.expected_packet_sha256)):
        raise SupervisorRefusal(
            "review arguments are accepted only by admit")
    if args.command == "launch":
        launch(config)
    else:
        verify(config)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError,
            SupervisorRefusal) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(3) from exc

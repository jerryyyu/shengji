#!/usr/bin/env python3
"""One-shot Mini supervisor for the reviewed S3a 512-state screen.

This file changes no S3a estimand.  It freezes one host, namespace, command
matrix and terminal publication order around :mod:`s3a_bury_pilot`.  Any
collision, child failure, signal, source drift or aggregate mismatch consumes
the namespace in place and leaves no terminal supervisor final.  It never
retries, resumes, deletes, promotes, deploys or interprets a partial result.
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

import s3a_bury_pilot as S3A  # noqa: E402


SCHEMA = "s3a-bury-screen-supervisor-v1"
RECEIPT_SCHEMA = "s3a-bury-screen-receipt-v1"
FINAL_SCHEMA = "s3a-bury-screen-final-v1"
EXIT_SCHEMA = "s3a-bury-screen-exit-v1"
RUN_ID = "s3a-bury-v2-screen-136m-v1"
EXPECTED_HOST = "Jerrys-Mac-mini.local"
NAMESPACE = Path("server/runs/logs") / RUN_ID
RUNNER = Path("server/scripts/s3a_bury_pilot.py")
SHARD_COUNT = 8
SHARD_NAMES = tuple(f"shard-{index:02d}.json" for index in range(SHARD_COUNT))
AGGREGATE_NAME = "aggregate.json"
RECEIPT_NAME = "receipt.json"
PROGRESS_NAME = "supervisor.jsonl"
FINAL_NAME = "supervisor-final.json"
EXPERIMENTAL_FLAGS = S3A.EXPERIMENTAL_FLAGS


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
    receipt: Path
    progress_partial: Path
    progress_final: Path
    final: Path
    shards: tuple[Path, ...]
    shard_logs: tuple[Path, ...]
    shard_exits: tuple[Path, ...]
    aggregate: Path
    aggregate_log: Path
    aggregate_exit: Path


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


def stable_digest(value: object) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


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
    # Keep exit receipts outside ``shard-*.json``: that literal pattern is
    # passed to the aggregate child and must resolve to evidence shards only.
    shard_exits = tuple(namespace / f"exit-shard-{index:02d}.json"
                       for index in range(SHARD_COUNT))
    aggregate = namespace / AGGREGATE_NAME
    return Paths(
        namespace=namespace,
        runner=ROOT / RUNNER,
        controller=Path(__file__).resolve(),
        receipt=namespace / RECEIPT_NAME,
        progress_partial=namespace / f"{PROGRESS_NAME}.partial",
        progress_final=namespace / PROGRESS_NAME,
        final=namespace / FINAL_NAME,
        shards=shards,
        shard_logs=shard_logs,
        shard_exits=shard_exits,
        aggregate=aggregate,
        aggregate_log=namespace / "aggregate.log",
        aggregate_exit=namespace / "aggregate.exit.json",
    )


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _write_json_exclusive(path: Path, payload: dict) -> None:
    try:
        S3A.atomic_json_exclusive(path, payload)
    except Exception as exc:
        raise SupervisorRefusal(f"cannot publish {path}: {exc}") from exc


def _publish_partial(partial_path: Path, final_path: Path) -> None:
    try:
        os.link(partial_path, final_path)
    except FileExistsError as exc:
        raise SupervisorRefusal(f"refusing to overwrite {final_path}") from exc
    os.unlink(partial_path)


def shard_argv(index: int, output: Path) -> tuple[str, ...]:
    return (
        sys.executable, str(ROOT / RUNNER), "run",
        "--shard-index", str(index), "--progress-every", "1",
        "--out", str(output),
    )


def aggregate_argv(paths: Paths) -> tuple[str, ...]:
    return (
        sys.executable, str(ROOT / RUNNER), "aggregate",
        "--pattern", str(paths.namespace / "shard-*.json"),
        "--out", str(paths.aggregate),
    )


def packet_contract(config: Config, paths: Paths, *, parent: dict,
                    runtime: dict) -> dict:
    return {
        "schema": SCHEMA,
        "run_id": RUN_ID,
        "one_shot": True,
        "retry_or_resume_authorized": False,
        "host": EXPECTED_HOST,
        "python": sys.executable,
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
        "mechanism": {
            "runner_schema": S3A.SCHEMA,
            "aggregate_schema": S3A.AGGREGATE_SCHEMA,
            "arms": list(S3A.ARMS),
            "selection_rule": S3A.SELECTION_RULE,
            "total_states": S3A.TOTAL_STATES,
            "shard_count": S3A.SHARD_COUNT,
            "states_per_shard": S3A.STATES_PER_SHARD,
            "seed0": S3A.SEED0,
            "seed_hi": S3A.SEED_HI,
            "minimum_structured_selection_worlds": (
                S3A.MIN_STRUCTURED_SELECTION_WORLDS),
            "report_worlds": S3A.REPORT_WORLDS,
            "interval": "paired_state_cluster_normal_approx_z1.96",
        },
        "commands": {
            "shards": [list(shard_argv(index, paths.shards[index]))
                       for index in range(SHARD_COUNT)],
            "aggregate": list(aggregate_argv(paths)),
        },
        "outputs": {
            "namespace": str(paths.namespace),
            "shards": [str(path) for path in paths.shards],
            "shard_logs": [str(path) for path in paths.shard_logs],
            "shard_exits": [str(path) for path in paths.shard_exits],
            "aggregate": str(paths.aggregate),
            "aggregate_log": str(paths.aggregate_log),
            "aggregate_exit": str(paths.aggregate_exit),
            "receipt": str(paths.receipt),
            "progress": str(paths.progress_final),
            "supervisor_final": str(paths.final),
        },
        "stop_rule": (
            "first nonzero shard terminates siblings; no aggregate; preserve "
            "all bytes; never retry this namespace"),
        "gate": {
            "authorize_duel_design_only_if_all_three_clustered_lcb_gt_zero": (
                True),
            "production_promotion": False,
            "duel_reference_frozen": False,
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
    enabled = [name for name in EXPERIMENTAL_FLAGS if name in os.environ]
    if enabled:
        raise SupervisorRefusal(
            f"experimental sampler/ballot flags must be unset: {enabled}")
    try:
        parent, runtime, head = S3A.require_real_context()
    except Exception as exc:
        raise SupervisorRefusal(f"S3a live context refused: {exc}") from exc
    if head != config.expected_git:
        raise SupervisorRefusal("runner/controller git identity mismatch")
    if runtime.get("host") != EXPECTED_HOST:
        raise SupervisorRefusal("runtime host identity mismatch")
    return parent, runtime


def _all_namespace_targets(paths: Paths) -> tuple[Path, ...]:
    finals = (
        paths.receipt, paths.progress_final, paths.final,
        *paths.shards, *paths.shard_logs, *paths.shard_exits,
        paths.aggregate, paths.aggregate_log, paths.aggregate_exit,
    )
    return tuple(finals) + tuple(partial(path) for path in finals)


def launch_preflight(config: Config, paths: Paths) -> tuple[dict, dict, dict]:
    parent, runtime = _identity_context(config, paths)
    collisions = [str(path) for path in _all_namespace_targets(paths)
                  if lexists(path)]
    if collisions:
        raise SupervisorRefusal(
            f"screen namespace collision: {collisions[:3]}")
    if paths.namespace.exists() and any(paths.namespace.iterdir()):
        raise SupervisorRefusal("screen namespace contains unknown bytes")
    contract = packet_contract(
        config, paths, parent=parent, runtime=runtime)
    return contract, parent, runtime


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
                         runtime: dict, head: str) -> dict:
    artifacts = [(path, _load_json(path)) for path in paths.shards]
    return S3A.aggregate_result(
        artifacts, runtime=runtime, head=head, parent=parent)


def receipt_problems(receipt: dict, contract: dict) -> list[str]:
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
    return sorted(set(problems))


def _job_specs(paths: Paths) -> list[tuple[str, tuple[str, ...], Path,
                                                Path, Path]]:
    specs = [
        (
            f"shard-{index:02d}",
            shard_argv(index, paths.shards[index]),
            paths.shards[index],
            paths.shard_logs[index],
            paths.shard_exits[index],
        )
        for index in range(SHARD_COUNT)
    ]
    specs.append((
        "aggregate",
        aggregate_argv(paths),
        paths.aggregate,
        paths.aggregate_log,
        paths.aggregate_exit,
    ))
    return specs


def terminal_job_evidence(paths: Paths) -> tuple[list[dict], list[str]]:
    """Reopen every child output/log/exit and derive exact final evidence."""
    evidence = []
    problems = []
    for name, argv, output, log, exit_path in _job_specs(paths):
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
            "exit": {"path": str(exit_path),
                     "sha256": sha256_file(exit_path)},
        })
    if len(evidence) != SHARD_COUNT + 1:
        problems.append("terminal child evidence population")
    return evidence, sorted(set(problems))


def final_problems(final: dict, *, contract: dict, receipt_sha256: str,
                   progress_sha256: str, shard_sha256s: list[str],
                   aggregate_sha256: str, aggregate: dict,
                   job_evidence: list[dict]) -> list[str]:
    expected = {
        "schema": FINAL_SCHEMA,
        "run_id": RUN_ID,
        "complete": True,
        "contract_sha256": stable_digest(contract),
        "receipt_sha256": receipt_sha256,
        "progress_sha256": progress_sha256,
        "jobs": job_evidence,
        "shards": [
            {"path": contract["outputs"]["shards"][index],
             "sha256": shard_sha256s[index], "shard_index": index}
            for index in range(SHARD_COUNT)
        ],
        "aggregate": {
            "path": contract["outputs"]["aggregate"],
            "sha256": aggregate_sha256,
            "status": aggregate.get("status"),
        },
        "duel_design_authorized": bool(
            aggregate.get("duel_design_authorized")),
        "production_promotion": False,
        "retry_or_resume_authorized": False,
    }
    return ([] if final == expected else
            ["supervisor final full recomputation drift"])


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
    jobs: list[Job] = []
    try:
        progress.event(
            "launch", "receipt-published",
            receipt_sha256=sha256_file(paths.receipt),
            contract_sha256=stable_digest(contract),
        )
        for index in range(SHARD_COUNT):
            job = _start_job(
                f"shard-{index:02d}",
                shard_argv(index, paths.shards[index]),
                paths.shards[index], paths.shard_logs[index],
                paths.shard_exits[index],
            )
            jobs.append(job)
            progress.event(
                "shard", "started", job=job.name,
                pid=job.process.pid, output=str(job.output),
            )
        _wait_parallel(jobs, progress, config.heartbeat_seconds)

        aggregate_job = _start_job(
            "aggregate", aggregate_argv(paths), paths.aggregate,
            paths.aggregate_log, paths.aggregate_exit,
        )
        jobs.append(aggregate_job)
        progress.event(
            "aggregate", "started", pid=aggregate_job.process.pid,
            output=str(paths.aggregate),
        )
        aggregate_return = _finish_job(aggregate_job)
        if aggregate_return != 0:
            raise SupervisorRefusal(
                "aggregate failure consumed namespace")
        aggregate = _load_json(paths.aggregate)
        expected_aggregate = _recompute_aggregate(
            paths, parent=parent, runtime=runtime,
            head=config.expected_git)
        if aggregate != expected_aggregate:
            raise SupervisorRefusal("aggregate full recomputation drift")
        job_evidence, evidence_problems = terminal_job_evidence(paths)
        if evidence_problems:
            raise SupervisorRefusal("; ".join(evidence_problems))
        progress.event(
            "aggregate", "complete", status_value=aggregate.get("status"),
            aggregate_sha256=sha256_file(paths.aggregate),
        )
        progress.close()
        _publish_partial(paths.progress_partial, paths.progress_final)
        final = {
            "schema": FINAL_SCHEMA,
            "run_id": RUN_ID,
            "complete": True,
            "contract_sha256": stable_digest(contract),
            "receipt_sha256": sha256_file(paths.receipt),
            "progress_sha256": sha256_file(paths.progress_final),
            "jobs": job_evidence,
            "shards": [
                {"path": str(path), "sha256": sha256_file(path),
                 "shard_index": index}
                for index, path in enumerate(paths.shards)
            ],
            "aggregate": {
                "path": str(paths.aggregate),
                "sha256": sha256_file(paths.aggregate),
                "status": aggregate.get("status"),
            },
            "duel_design_authorized": bool(
                aggregate.get("duel_design_authorized")),
            "production_promotion": False,
            "retry_or_resume_authorized": False,
        }
        problems = final_problems(
            final, contract=contract,
            receipt_sha256=sha256_file(paths.receipt),
            progress_sha256=sha256_file(paths.progress_final),
            shard_sha256s=[sha256_file(path) for path in paths.shards],
            aggregate_sha256=sha256_file(paths.aggregate),
            aggregate=aggregate,
            job_evidence=job_evidence,
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
    parent, runtime = _identity_context(config, paths)
    contract = packet_contract(
        config, paths, parent=parent, runtime=runtime)
    for path in (
            paths.receipt, paths.progress_final, paths.final,
            *paths.shards, *paths.shard_logs, *paths.shard_exits,
            paths.aggregate, paths.aggregate_log, paths.aggregate_exit):
        if not is_regular_unlinked(path) or lexists(partial(path)):
            raise SupervisorRefusal(
                f"terminal artifact is missing/nonregular/partial: {path}")
    receipt = _load_json(paths.receipt)
    problems = receipt_problems(receipt, contract)
    aggregate = _load_json(paths.aggregate)
    expected_aggregate = _recompute_aggregate(
        paths, parent=parent, runtime=runtime,
        head=config.expected_git)
    if aggregate != expected_aggregate:
        problems.append("aggregate full recomputation drift")
    job_evidence, evidence_problems = terminal_job_evidence(paths)
    problems += evidence_problems
    final = _load_json(paths.final)
    problems += final_problems(
        final, contract=contract,
        receipt_sha256=sha256_file(paths.receipt),
        progress_sha256=sha256_file(paths.progress_final),
        shard_sha256s=[sha256_file(path) for path in paths.shards],
        aggregate_sha256=sha256_file(paths.aggregate),
        aggregate=aggregate,
        job_evidence=job_evidence,
    )
    if problems:
        raise SupervisorRefusal("terminal verify: " + "; ".join(problems))
    print(json.dumps({
        "verified": True,
        "run_id": RUN_ID,
        "status": aggregate.get("status"),
        "final_sha256": sha256_file(paths.final),
    }, sort_keys=True), flush=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("launch", "verify"))
    parser.add_argument("--expected-git", required=True)
    parser.add_argument("--expected-runner-sha256", required=True)
    parser.add_argument("--expected-controller-sha256", required=True)
    parser.add_argument("--heartbeat-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)
    if not 1.0 <= args.heartbeat_seconds <= 60.0:
        raise SupervisorRefusal("heartbeat must be between 1 and 60 seconds")
    config = Config(
        expected_git=args.expected_git,
        expected_runner_sha256=args.expected_runner_sha256,
        expected_controller_sha256=args.expected_controller_sha256,
        heartbeat_seconds=args.heartbeat_seconds,
    )
    if args.command == "launch":
        launch(config)
    else:
        verify(config)


if __name__ == "__main__":
    try:
        main()
    except SupervisorRefusal as exc:
        print(f"REFUSING: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(3) from exc

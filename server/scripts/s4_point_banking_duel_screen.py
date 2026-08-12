#!/usr/bin/env python3
"""Freeze, admit, supervise, and verify the S4 complete-round screen.

The packet is path-neutral but runtime-specific: it binds exact source/Git,
the authenticated live champion, the terminal S4 mechanism screen, the Air
score-free preflight, the fresh seed population, eight command templates, and
every output name.  External review may authorize one Mini execution only.

No command retries, resumes, deletes, confirms, promotes, trains, or deploys.
The supervisor exposes count/status heartbeats while shards are running; it
does not surface partial wins or utility.
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

import s4_point_banking_duel as DUEL  # noqa: E402
import s4_point_banking_screen as MECHANISM  # noqa: E402


SCHEMA = "s4-point-banking-duel-screen-controller-v2"
PACKET_SCHEMA = DUEL.PACKET_SCHEMA
PACKET_REVIEW_SCHEMA = DUEL.PACKET_REVIEW_SCHEMA
PACKET_REVIEW_MARKER = DUEL.PACKET_REVIEW_MARKER
ADMISSION_SCHEMA = DUEL.ADMISSION_SCHEMA
RECEIPT_SCHEMA = DUEL.EXECUTION_RECEIPT_SCHEMA
EXIT_SCHEMA = "s4-point-banking-duel-screen-exit-v2"
FINAL_SCHEMA = "s4-point-banking-duel-screen-final-v2"
RUN_ID = DUEL.PHASES["screen"]["run_id"]
EXPECTED_HOST = "Jerrys-Mac-mini.local"
EXPECTED_PYTHON = "3.14.3"
EXPECTED_FAST_SHA256 = (
    "9c9e77fbdc4c6caceec195465155f37ec6369e409462fd838bc142bf8a0be4c1"
)
NAMESPACE = Path("server/runs/logs") / RUN_ID
RUNNER = Path("server/scripts/s4_point_banking_duel.py")
CONTROLLER = Path("server/scripts/s4_point_banking_duel_screen.py")
SHARD_COUNT = DUEL.SHARD_COUNT
SHARD_NAMES = tuple(f"shard-{index:02d}.json" for index in range(SHARD_COUNT))
PACKET_NAME = "launch_packet.json"
REVIEW_NAME = "review_record.txt"
ADMISSION_NAME = "review_admission.json"
RECEIPT_NAME = "receipt.json"
PROGRESS_NAME = "supervisor.jsonl"
FINAL_NAME = "supervisor-final.json"
AGGREGATE_NAME = "aggregate.json"
PREFLIGHT_PATH = Path("server/runs/logs") / DUEL.PREFLIGHT_RUN_ID / \
    "preflight.json"
PREFLIGHT_SHA256 = (
    "fcc8b8913d80db5b1fe4bb7d6b727dc722bb7d0f4ec9c8806842535fc43ee060"
)
PREFLIGHT_GIT = "57ab02dbe7632d59f97ee16967df39dc829848ae"
MECHANISM_NAMESPACE = Path("server/runs/logs") / MECHANISM.RUN_ID
MECHANISM_STATES_SHA256 = (
    "4538be8573a4d4bcf50524afe83c5dac25c5269b3ed95ab15f645343d0ff6b5f"
)
MECHANISM_ADMISSION_SHA256 = (
    "83993ec6609c2a7528853d4c1db789f137d3f0cbfff97d20fbf526cbd5ff5e6d"
)
MECHANISM_RECEIPT_SHA256 = (
    "90124eb6f89c27cedc38770b2da5b3b8597400694281729656105f67803f526b"
)
MECHANISM_SCREEN_SHA256 = (
    "abd9f36fa3e84c81b90e22f1c827f828a549f7fd6a9420ffbdb7c168974cdc00"
)


class SupervisorRefused(RuntimeError):
    """A one-shot S4 packet or evidence boundary was violated."""


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
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


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
        DUEL.write_exclusive(path, payload)
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
        "--phase", "screen",
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
        "--phase", "screen",
        "--shards", *[str(NAMESPACE / name) for name in SHARD_NAMES],
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
    template = command_template(index)
    relative_paths = {
        str(RUNNER), str(NAMESPACE / RECEIPT_NAME),
        str(NAMESPACE / SHARD_NAMES[index]),
    }
    resolved = [
        sys.executable if item == "{python}"
        else config.expected_git if item == "{git}"
        else execution_receipt_sha256
        if item == "{execution_receipt_sha256}"
        else str(ROOT / item) if item in relative_paths
        else item
        for item in template
    ]
    return tuple(resolved)


def _artifact_ref(path: Path, expected_sha256: str, label: str) -> dict:
    if not is_regular_unlinked(path) or lexists(partial(path)):
        raise SupervisorRefused(f"{label} is missing, linked, or partial")
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise SupervisorRefused(f"{label} SHA-256 drift")
    return {"path": rel(path), "sha256": actual}


def preflight_evidence() -> dict:
    path = ROOT / PREFLIGHT_PATH
    ref = _artifact_ref(path, PREFLIGHT_SHA256, "S4 duel preflight")
    payload = _load_json(path)
    expected_fields = {
        "schema", "complete", "score_free", "outcomes_published",
        "outcomes_discarded", "run_id", "clusters", "seed0",
        "stream_stride", "parent", "runtime", "elapsed_seconds",
        "throughput_safety_factor", "counter_totals",
        "point_banking_telemetry", "projections", "criteria", "status",
        "screen_launch_authorized", "confirmation_launch_authorized",
        "strength_claim", "training_authorized", "production_promotion",
        "retry_or_extension_authorized",
    }
    criteria = payload.get("criteria")
    telemetry = payload.get("point_banking_telemetry")
    runtime = payload.get("runtime")
    if (set(payload) != expected_fields
            or payload.get("schema") != DUEL.PREFLIGHT_SCHEMA
            or payload.get("complete") is not True
            or payload.get("score_free") is not True
            or payload.get("outcomes_published") is not False
            or payload.get("outcomes_discarded") is not True
            or payload.get("run_id") != DUEL.PREFLIGHT_RUN_ID
            or payload.get("clusters") != DUEL.PREFLIGHT_CLUSTERS
            or payload.get("seed0") != DUEL.PREFLIGHT_SEED0
            or payload.get("stream_stride") != DUEL.STREAM_STRIDE
            or payload.get("status") != "AUTHORIZE_FULL_GAME_PACKET_REVIEW"
            or not isinstance(criteria, dict)
            or criteria.get("all") is not True
            or not all(criteria.values())
            or payload.get("screen_launch_authorized") is not False
            or payload.get("confirmation_launch_authorized") is not False
            or payload.get("strength_claim") is not False
            or payload.get("training_authorized") is not False
            or payload.get("production_promotion") is not False
            or payload.get("retry_or_extension_authorized") is not False):
        raise SupervisorRefused("S4 duel preflight identity/authority drift")
    if (not isinstance(runtime, dict)
            or runtime.get("git") != PREFLIGHT_GIT
            or runtime.get("tree_dirty") is not False
            or runtime.get("host") != "Jerrys-MacBook-Air.local"
            or runtime.get("python") != "3.14.6"
            or runtime.get("fast_binary_sha256") != EXPECTED_FAST_SHA256
            or runtime.get("source_sha256s", {}).get("runner") !=
            sha256_file(ROOT / RUNNER)):
        raise SupervisorRefused("S4 duel preflight runtime/source drift")
    projections = payload.get("projections")
    if (not isinstance(projections, dict)
            or projections.get("screen", {}).get("fleet_hours", float("inf")) > 100
            or projections.get("screen", {}).get(
                "max_shard_hours", float("inf")) > 15):
        raise SupervisorRefused("S4 duel preflight exceeds frozen screen budget")
    if not isinstance(telemetry, dict):
        raise SupervisorRefused("S4 duel preflight telemetry missing")
    treatment = telemetry.get("treatment", {})
    matched_null = telemetry.get("matched_null", {})
    champion = telemetry.get("champion", {})
    if (treatment.get("attacker_triggers", 0) <= 0
            or treatment.get("defender_triggers", 0) <= 0
            or treatment.get("changes") != treatment.get("triggers")
            or matched_null.get("attacker_triggers", 0) <= 0
            or matched_null.get("defender_triggers", 0) <= 0
            or matched_null.get("matched_noops") != matched_null.get("triggers")
            or matched_null.get("changes") != 0
            or any(champion.get(name) != 0
                   for name in DUEL.POINT_BANKING_COUNTER_FIELDS)):
        raise SupervisorRefused("S4 duel preflight activation/dose drift")
    return {
        **ref,
        "git": PREFLIGHT_GIT,
        "status": payload["status"],
        "elapsed_seconds": payload["elapsed_seconds"],
        "projections": projections,
        "score_free": True,
        "outcomes_published": False,
    }


def mechanism_evidence() -> dict:
    namespace = ROOT / MECHANISM_NAMESPACE
    states = namespace / "states.json"
    admission = namespace / "review_admission.json"
    receipt = namespace / "screen_receipt.json"
    screen = namespace / "screen.json"
    refs = {
        "states": _artifact_ref(
            states, MECHANISM_STATES_SHA256, "S4 mechanism states"),
        "admission": _artifact_ref(
            admission, MECHANISM_ADMISSION_SHA256, "S4 mechanism admission"),
        "receipt": _artifact_ref(
            receipt, MECHANISM_RECEIPT_SHA256, "S4 mechanism receipt"),
        "screen": _artifact_ref(
            screen, MECHANISM_SCREEN_SHA256, "S4 mechanism screen"),
    }
    state_payload = _load_json(states)
    runtime = state_payload.get("runtime")
    if not isinstance(runtime, dict):
        raise SupervisorRefused("S4 mechanism runtime missing")
    try:
        payload = MECHANISM.verify_screen_artifact(
            states_path=states, admission_path=admission,
            output_path=screen, receipt_path=receipt, rt=runtime)
    except Exception as exc:
        raise SupervisorRefused(
            f"S4 mechanism full recomputation refused: {exc}") from exc
    aggregate = payload.get("aggregate", {})
    criteria = aggregate.get("criteria")
    if (aggregate.get("verdict") != "AUTHORIZE_FULL_GAME_PACKET_REVIEW"
            or not isinstance(criteria, dict)
            or not criteria
            or not all(criteria.values())
            or aggregate.get("full_game_launch_authorized") is not False
            or aggregate.get("strength_claim") is not False
            or aggregate.get("production_promotion") is not False):
        raise SupervisorRefused("S4 mechanism did not authorize packet review")
    return {
        **refs,
        "verdict": aggregate["verdict"],
        "overall_point_delta": aggregate["points"]["mean"],
        "overall_point_lcb95": aggregate["points"]["lcb_one_sided_95"],
        "full_game_launch_authorized": False,
        "strength_claim": False,
    }


def _identity_context(config: Config, paths: Paths) -> tuple[dict, dict]:
    if _git("rev-parse", "HEAD") != config.expected_git:
        raise SupervisorRefused("S4 controller exact Git drift")
    if _git("status", "--porcelain"):
        raise SupervisorRefused("S4 controller refuses a dirty tree")
    if (sha256_file(paths.runner) != config.expected_runner_sha256
            or sha256_file(paths.controller) !=
            config.expected_controller_sha256):
        raise SupervisorRefused("S4 controller source SHA-256 drift")
    try:
        parent, runtime = DUEL.require_runtime(config.expected_git)
    except Exception as exc:
        raise SupervisorRefused(f"S4 duel runtime refused: {exc}") from exc
    if (runtime.get("host") != EXPECTED_HOST
            or runtime.get("python") != EXPECTED_PYTHON
            or runtime.get("fast_binary_sha256") != EXPECTED_FAST_SHA256):
        raise SupervisorRefused("S4 screen is frozen to exact Mini runtime")
    return parent, runtime


def packet_contract(config: Config, paths: Paths, *, parent: dict,
                    runtime: dict, preflight: dict,
                    mechanism: dict) -> dict:
    jobs = [{
        "name": f"shard-{index:02d}",
        "command_template": command_template(index),
        "output": str(NAMESPACE / SHARD_NAMES[index]),
        "clusters": DUEL.PHASES["screen"]["clusters_per_shard"],
    } for index in range(SHARD_COUNT)]
    return {
        "schema": PACKET_SCHEMA,
        "run_id": RUN_ID,
        "git": config.expected_git,
        "runner": {"path": str(RUNNER),
                   "sha256": config.expected_runner_sha256},
        "controller": {"path": str(CONTROLLER),
                       "sha256": config.expected_controller_sha256},
        "runtime": runtime,
        "parent": parent,
        "mechanism_parent": mechanism,
        "score_free_preflight": preflight,
        "phase_identity": DUEL.phase_identity("screen"),
        "namespace": str(NAMESPACE),
        "jobs": jobs,
        "aggregate_command_template": aggregate_template(),
        "aggregate_output": str(NAMESPACE / AGGREGATE_NAME),
        "heartbeat_seconds": config.heartbeat_seconds,
        "screen_clusters": DUEL.PHASES["screen"]["clusters"],
        "shard_count": SHARD_COUNT,
        "selection_rule": DUEL.SELECTION_RULE,
        "claim_boundary": DUEL.CLAIM_BOUNDARY,
        "packet_review_authorized": True,
        "screen_launch_authorized": False,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "retry_or_extension_authorized": False,
    }


def _expected_packet(config: Config, paths: Paths) -> tuple[dict, dict, dict]:
    parent, runtime = _identity_context(config, paths)
    preflight = preflight_evidence()
    mechanism = mechanism_evidence()
    packet = packet_contract(
        config, paths, parent=parent, runtime=runtime,
        preflight=preflight, mechanism=mechanism)
    return packet, parent, runtime


def freeze_packet(config: Config) -> dict:
    paths = paths_for()
    if paths.namespace.exists():
        raise SupervisorRefused("S4 screen namespace already exists")
    packet, _, _ = _expected_packet(config, paths)
    _write_json_exclusive(paths.packet, packet)
    return {
        "path": rel(paths.packet),
        "sha256": sha256_file(paths.packet),
        "packet_review_authorized": True,
        "screen_launch_authorized": False,
    }


def verify_packet(config: Config, paths: Paths | None = None) -> dict:
    paths = paths or paths_for()
    if not is_regular_unlinked(paths.packet) or lexists(partial(paths.packet)):
        raise SupervisorRefused("S4 packet missing, linked, or partial")
    expected, _, _ = _expected_packet(config, paths)
    actual = _load_json(paths.packet)
    if actual != expected:
        raise SupervisorRefused("S4 launch packet full recomputation drift")
    return actual


def _review_claim(raw: bytes, *, packet_sha256: str,
                  config: Config) -> dict:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SupervisorRefused("review record is not UTF-8") from exc
    matches = [
        line[len(PACKET_REVIEW_MARKER):]
        for line in text.splitlines()
        if line.startswith(PACKET_REVIEW_MARKER)
    ]
    if len(matches) != 1:
        raise SupervisorRefused("review record must contain exactly one marker")
    try:
        claim = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise SupervisorRefused("review marker is invalid JSON") from exc
    expected = {
        "schema": PACKET_REVIEW_SCHEMA,
        "git": config.expected_git,
        "run_id": RUN_ID,
        "packet_sha256": packet_sha256,
        "preflight_sha256": PREFLIGHT_SHA256,
        "mechanism_screen_sha256": MECHANISM_SCREEN_SHA256,
        "independent_review": True,
        "screen_launch_authorized": True,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "verdict": "PASS",
    }
    if claim != expected:
        raise SupervisorRefused("review marker grants wrong S4 authority")
    return claim


def admit_packet(config: Config, review_record: Path,
                 expected_review_sha256: str,
                 expected_packet_sha256: str) -> dict:
    paths = paths_for()
    verify_packet(config, paths)
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
    claim = _review_claim(
        raw, packet_sha256=packet_sha256, config=config)
    _write_bytes_exclusive(paths.review_copy, raw)
    admission = {
        "schema": ADMISSION_SCHEMA,
        "run_id": RUN_ID,
        "packet": {"path": str(NAMESPACE / PACKET_NAME),
                   "sha256": packet_sha256},
        "review": {"path": str(NAMESPACE / REVIEW_NAME),
                   "sha256": expected_review_sha256},
        "review_claim": claim,
        "operator_asserted_independent_review": True,
        "screen_launch_authorized": True,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
    }
    _write_json_exclusive(paths.admission, admission)
    return {"path": rel(paths.admission),
            "sha256": sha256_file(paths.admission),
            "screen_launch_authorized": True}


def _require_admission(config: Config, paths: Paths) -> tuple[dict, dict]:
    packet = verify_packet(config, paths)
    for path, label in ((paths.review_copy, "review copy"),
                        (paths.admission, "review admission")):
        if not is_regular_unlinked(path) or lexists(partial(path)):
            raise SupervisorRefused(f"{label} missing, linked, or partial")
    packet_sha256 = sha256_file(paths.packet)
    review_raw = paths.review_copy.read_bytes()
    review_sha256 = sha256_file(paths.review_copy)
    claim = _review_claim(
        review_raw, packet_sha256=packet_sha256, config=config)
    expected = {
        "schema": ADMISSION_SCHEMA,
        "run_id": RUN_ID,
        "packet": {"path": str(NAMESPACE / PACKET_NAME),
                   "sha256": packet_sha256},
        "review": {"path": str(NAMESPACE / REVIEW_NAME),
                   "sha256": review_sha256},
        "review_claim": claim,
        "operator_asserted_independent_review": True,
        "screen_launch_authorized": True,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
    }
    if _load_json(paths.admission) != expected:
        raise SupervisorRefused("S4 review admission drift")
    return packet, expected


def _execution_targets(paths: Paths) -> tuple[Path, ...]:
    return (
        paths.receipt, partial(paths.receipt),
        paths.progress_partial, paths.progress_final,
        paths.final, partial(paths.final),
        *paths.shards, *[partial(p) for p in paths.shards],
        *paths.shard_logs, *[partial(p) for p in paths.shard_logs],
        *paths.shard_exits, *[partial(p) for p in paths.shard_exits],
        paths.aggregate, partial(paths.aggregate),
    )


def launch_preflight(config: Config, paths: Paths) -> tuple[dict, dict, dict]:
    packet, parent, runtime = _expected_packet(config, paths)
    actual, admission = _require_admission(config, paths)
    if actual != packet:
        raise SupervisorRefused("admitted S4 packet drift")
    collisions = [str(path) for path in _execution_targets(paths)
                  if lexists(path)]
    if collisions:
        raise SupervisorRefused(
            f"S4 execution namespace collision: {collisions[:3]}")
    allowed = {PACKET_NAME, REVIEW_NAME, ADMISSION_NAME}
    present = {path.name for path in paths.namespace.iterdir()}
    if present != allowed:
        raise SupervisorRefused(
            f"S4 namespace contains unknown bytes: {sorted(present - allowed)}")
    return parent, runtime, admission


class Progress:
    def __init__(self, path: Path):
        if lexists(path):
            raise SupervisorRefused("S4 progress partial already exists")
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
        raise SupervisorRefused(f"S4 child namespace collision: {name}")
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
                if '"event": "s4-point-banking-duel-progress-v1"' not in line:
                    continue
                candidate = json.loads(line)
                if candidate.get("shard_index") == int(job.name[-2:]):
                    latest = candidate
        except (OSError, ValueError):
            latest = None
    return {
        "job": job.name,
        "clusters_complete": int((latest or {}).get("clusters_complete", 0)),
        "clusters_total": DUEL.PHASES["screen"]["clusters_per_shard"],
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
            raise SupervisorRefused(f"S4 child failure: {failures}")
        if not live:
            if complete != len(jobs):
                raise SupervisorRefused("S4 child population did not complete")
            return
        time.sleep(heartbeat_seconds)


def _recompute_aggregate(config: Config, paths: Paths, *, parent: dict,
                         runtime: dict) -> dict:
    try:
        execution_receipt = DUEL.require_execution_receipt(
            paths.receipt, sha256_file(paths.receipt),
            expected_git=config.expected_git, phase="screen")
    except Exception as exc:
        raise SupervisorRefused(
            f"S4 execution receipt refused during aggregation: {exc}") from exc
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
                parent=parent, runtime=runtime,
                execution_receipt=execution_receipt))
        shards.append(payload)
        inputs.append({"path": rel(path), "sha256": sha256_file(path),
                       "shard_index": index})
    if len(shards) != SHARD_COUNT:
        problems.append("S4 aggregate shard population")
    if len({item["sha256"] for item in inputs}) != SHARD_COUNT:
        problems.append("S4 aggregate shard digest uniqueness")
    if problems:
        raise SupervisorRefused(
            "S4 aggregate inputs: " + "; ".join(sorted(set(problems))))
    return DUEL.build_aggregate(
        phase="screen", shards=shards, inputs=inputs,
        parent=parent, runtime=runtime, screen_parent=None)


def receipt_problems(receipt: dict, *, config: Config,
                     packet_sha256: str, admission_sha256: str) -> list[str]:
    expected = {
        "schema": RECEIPT_SCHEMA,
        "run_id": RUN_ID,
        "phase": "screen",
        "complete": True,
        "git": config.expected_git,
        "runner_sha256": config.expected_runner_sha256,
        "created_time_ns": receipt.get("created_time_ns"),
        "nonce": receipt.get("nonce"),
        "packet_sha256": packet_sha256,
        "admission_sha256": admission_sha256,
        "preflight_sha256": PREFLIGHT_SHA256,
        "mechanism_screen_sha256": MECHANISM_SCREEN_SHA256,
        "screen_launch_authorized": True,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "retry_or_resume_authorized": False,
    }
    problems = [] if receipt == expected else ["S4 receipt recomputation drift"]
    created = receipt.get("created_time_ns")
    if isinstance(created, bool) or not isinstance(created, int) or created <= 0:
        problems.append("S4 receipt creation time")
    if not is_sha256(receipt.get("nonce")):
        problems.append("S4 receipt nonce")
    return sorted(set(problems))


def _job_specs(config: Config, paths: Paths,
               execution_receipt_sha256: str):
    return [(
        f"shard-{index:02d}",
        shard_argv(config, index, paths.shards[index],
                   execution_receipt_sha256),
        paths.shards[index], paths.shard_logs[index], paths.shard_exits[index],
    ) for index in range(SHARD_COUNT)]


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
        problems.append("S4 terminal child evidence population")
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
        "screen_gate_passed": status == "AUTHORIZE_CONFIRM_PACKET_REVIEW",
        "confirm_packet_review_authorized": (
            status == "AUTHORIZE_CONFIRM_PACKET_REVIEW"),
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "retry_or_resume_authorized": False,
    }


def launch(config: Config) -> None:
    paths = paths_for()
    parent, runtime, _ = launch_preflight(config, paths)
    packet_sha256 = sha256_file(paths.packet)
    admission_sha256 = sha256_file(paths.admission)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "run_id": RUN_ID,
        "phase": "screen",
        "complete": True,
        "git": config.expected_git,
        "runner_sha256": config.expected_runner_sha256,
        "created_time_ns": time.time_ns(),
        "nonce": secrets.token_hex(32),
        "packet_sha256": packet_sha256,
        "admission_sha256": admission_sha256,
        "preflight_sha256": PREFLIGHT_SHA256,
        "mechanism_screen_sha256": MECHANISM_SCREEN_SHA256,
        "screen_launch_authorized": True,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "retry_or_resume_authorized": False,
    }
    problems = receipt_problems(
        receipt, config=config, packet_sha256=packet_sha256,
        admission_sha256=admission_sha256)
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
            raise SupervisorRefused("S4 aggregate failed exact reopen")
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
        raise SupervisorRefused("terminal S4 packet drift")
    terminal = (
        paths.receipt, paths.progress_final, paths.final,
        *paths.shards, *paths.shard_logs, *paths.shard_exits, paths.aggregate,
    )
    for path in terminal:
        if not is_regular_unlinked(path) or lexists(partial(path)):
            raise SupervisorRefused(
                f"S4 terminal artifact missing, linked, or partial: {path}")
    packet_sha256 = sha256_file(paths.packet)
    admission_sha256 = sha256_file(paths.admission)
    problems = receipt_problems(
        _load_json(paths.receipt), config=config,
        packet_sha256=packet_sha256,
        admission_sha256=admission_sha256)
    execution_receipt_sha256 = sha256_file(paths.receipt)
    aggregate = _load_json(paths.aggregate)
    if aggregate != _recompute_aggregate(
            config, paths, parent=parent, runtime=runtime):
        problems.append("S4 aggregate full recomputation drift")
    job_evidence, evidence_problems = terminal_job_evidence(
        config, paths, execution_receipt_sha256)
    problems += evidence_problems
    expected_final = final_payload(
        paths=paths, packet_sha256=packet_sha256,
        admission_sha256=admission_sha256, aggregate=aggregate,
        job_evidence=job_evidence)
    if _load_json(paths.final) != expected_final:
        problems.append("S4 supervisor final full recomputation drift")
    if problems:
        raise SupervisorRefused("terminal S4 verify: "
                                + "; ".join(sorted(set(problems))))
    result = {
        "verified": True,
        "run_id": RUN_ID,
        "status": aggregate.get("status"),
        "final_sha256": sha256_file(paths.final),
        "confirmation_launch_authorized": False,
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
            "screen_launch_authorized": packet["screen_launch_authorized"],
        }, sort_keys=True))
    elif args.command == "admit":
        if not all((args.review_record, args.expected_review_sha256,
                    args.expected_packet_sha256)):
            raise SupervisorRefused("admit requires review path and both hashes")
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
    except (SupervisorRefused, DUEL.ProtocolRefused) as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc

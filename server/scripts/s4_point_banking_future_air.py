#!/usr/bin/env python3
"""Freeze, review, admit, supervise, and verify future S4 on Air.

The controller launches one reviewed two-look contract.  It creates tranche
2's immutable pre-authorization before gameplay, runs exactly 8,192 clusters,
and applies the reviewed transition mechanically.  Only a clean look-1
``CONTINUE_AUTOMATICALLY`` record can create the release that starts tranche
2.  No operator choice exists between looks.

It cannot retry, resize, change alpha, promote, deploy, train, or touch T4.
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

import s4_point_banking_future as CORE  # noqa: E402

SCHEMA = "s4-point-banking-future-air-controller-v1"
EXIT_SCHEMA = "s4-point-banking-future-air-exit-v1"
FINAL_SCHEMA = "s4-point-banking-future-air-final-v1"
PREAUTH_SCHEMA = "s4-point-banking-future-tranche2-preauthorization-v1"
RELEASE_SCHEMA = "s4-point-banking-future-tranche2-release-v1"
PREFLIGHT_ADMISSION_SCHEMA = (
    "s4-point-banking-future-preflight-admission-v1")
CONTROLLER_REVIEW_MARKER = "S4_POINT_BANKING_FUTURE_CONTROLLER_V1_REVIEW "
RUN_ID = CORE.RUN_ID
NAMESPACE = CORE.NAMESPACE
RUNNER = Path("server/scripts/s4_point_banking_future.py")
CONTROLLER = Path("server/scripts/s4_point_banking_future_air.py")
SHARD_COUNT = CORE.SHARD_COUNT
TRANCHE_COUNT = CORE.TRANCHE_COUNT
SHARD_NAMES = CORE.SHARD_NAMES
PACKET_NAME = "launch_packet.json"
REVIEW_NAME = "review_record.txt"
ADMISSION_NAME = "review_admission.json"
RECEIPT_NAME = "receipt.json"
DESIGN_REVIEW_NAME = "design-review-record.txt"
TRANCHE2_PREAUTH_NAME = "tranche-2-preauthorization.json"
TRANCHE2_RELEASE_NAME = "tranche-2-release.json"
PROGRESS_NAME = "supervisor.jsonl"
FINAL_NAME = "supervisor-final.json"
AGGREGATE_NAMES = CORE.AGGREGATE_NAMES
PREFLIGHT_PATH = CORE.PREFLIGHT_NAMESPACE / "preflight.json"

EXPECTED_HOST = "Jerrys-MacBook-Air.local"
EXPECTED_PYTHON = "3.14.6"
EXPECTED_FAST_SHA256 = (
    "9c9e77fbdc4c6caceec195465155f37ec6369e409462fd838bc142bf8a0be4c1"
)
DESIGN_REVIEW_GIT = CORE.DESIGN_REVIEW_GIT
DESIGN_REVIEW_HEADING = (
    "PASS TO IMPLEMENT: S4-FUTURE-C1 sequential design (PR #40, 1824599)"
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
    preflight_review_copy: Path
    preflight_admission: Path
    packet: Path
    design_review_copy: Path
    review_copy: Path
    admission: Path
    receipt: Path
    tranche2_preauthorization: Path
    tranche2_release: Path
    progress_partial: Path
    progress_final: Path
    final: Path
    shards: tuple[Path, ...]
    shard_logs: tuple[Path, ...]
    shard_exits: tuple[Path, ...]
    aggregates: tuple[Path, ...]


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
        preflight_review_copy=ROOT / CORE.PREFLIGHT_REVIEW_PATH,
        preflight_admission=ROOT / CORE.PREFLIGHT_ADMISSION_PATH,
        packet=namespace / PACKET_NAME,
        design_review_copy=namespace / DESIGN_REVIEW_NAME,
        review_copy=namespace / REVIEW_NAME,
        admission=namespace / ADMISSION_NAME,
        receipt=namespace / RECEIPT_NAME,
        tranche2_preauthorization=namespace / TRANCHE2_PREAUTH_NAME,
        tranche2_release=namespace / TRANCHE2_RELEASE_NAME,
        progress_partial=namespace / f"{PROGRESS_NAME}.partial",
        progress_final=namespace / PROGRESS_NAME,
        final=namespace / FINAL_NAME,
        shards=tuple(namespace / name for name in SHARD_NAMES),
        shard_logs=tuple(namespace / name.replace(".json", ".log")
                         for name in SHARD_NAMES),
        shard_exits=tuple(namespace / f"exit-{name}"
                          for name in SHARD_NAMES),
        aggregates=tuple(namespace / name for name in AGGREGATE_NAMES),
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


def shard_position(tranche: int, index: int) -> int:
    try:
        return CORE.shard_position(tranche, index)
    except CORE.ProtocolRefused as exc:
        raise SupervisorRefused(str(exc)) from exc


def command_template(tranche: int, index: int) -> list[str]:
    return CORE.command_template(tranche, index)


def aggregate_template(look: int) -> list[str]:
    try:
        return CORE.aggregate_template(look)
    except CORE.ProtocolRefused as exc:
        raise SupervisorRefused(str(exc)) from exc


def shard_argv(config: Config, tranche: int, index: int, output: Path,
               execution_receipt_sha256: str) -> tuple[str, ...]:
    position = shard_position(tranche, index)
    expected_output = ROOT / NAMESPACE / SHARD_NAMES[position]
    if output != expected_output:
        raise SupervisorRefused("shard output path drift")
    if not is_sha256(execution_receipt_sha256):
        raise SupervisorRefused("execution receipt SHA-256 is invalid")
    relative_paths = {
        str(RUNNER), str(NAMESPACE / RECEIPT_NAME),
        str(NAMESPACE / SHARD_NAMES[position]),
    }
    return tuple(
        sys.executable if item == "{python}"
        else config.expected_git if item == "{git}"
        else execution_receipt_sha256
        if item == "{execution_receipt_sha256}"
        else str(ROOT / item) if item in relative_paths
        else item
        for item in command_template(tranche, index)
    )


def _artifact_ref(path: Path, expected_sha256: str | None,
                  label: str) -> dict:
    if not is_regular_unlinked(path) or lexists(partial(path)):
        raise SupervisorRefused(f"{label} is missing, linked, or partial")
    actual = sha256_file(path)
    if expected_sha256 is not None and actual != expected_sha256:
        raise SupervisorRefused(f"{label} SHA-256 drift")
    try:
        rendered_path = rel(path)
    except ValueError:
        rendered_path = str(path.resolve())
    return {"path": rendered_path, "sha256": actual}


def _identity_context(config: Config, paths: Paths) -> tuple[dict, dict]:
    if _git("rev-parse", "HEAD") != config.expected_git:
        raise SupervisorRefused("future S4 controller exact Git drift")
    if _git("status", "--porcelain"):
        raise SupervisorRefused("future S4 controller refuses a dirty tree")
    if (sha256_file(paths.runner) != config.expected_runner_sha256
            or sha256_file(paths.controller) !=
            config.expected_controller_sha256):
        raise SupervisorRefused("future S4 source SHA-256 drift")
    try:
        parent, runtime = CORE.require_runtime(config.expected_git)
    except Exception as exc:
        raise SupervisorRefused(
            f"future S4 runtime refused: {exc}") from exc
    if (runtime.get("host") != EXPECTED_HOST
            or runtime.get("python") != EXPECTED_PYTHON
            or runtime.get("fast_binary_sha256") != EXPECTED_FAST_SHA256
            or runtime.get("future_runner_sha256") !=
            config.expected_runner_sha256):
        raise SupervisorRefused("future S4 is frozen to exact Air runtime")
    return parent, runtime


def controller_review_claim(config: Config) -> dict:
    return {
        "schema": "s4-point-banking-future-controller-review-v1",
        "git": config.expected_git,
        "design_git": DESIGN_REVIEW_GIT,
        "design_sha256": sha256_file(Path(CORE.DESIGN.__file__)),
        "independent_review": True,
        "automatic_two_look_contract_verified": True,
        "one_score_free_preflight_authorized": True,
        "sequential_packet_design_authorized": True,
        "sequential_execution_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def _controller_review_claim(raw: bytes, config: Config) -> dict:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SupervisorRefused("controller review is not UTF-8") from exc
    matches = [line[len(CONTROLLER_REVIEW_MARKER):]
               for line in text.splitlines()
               if line.startswith(CONTROLLER_REVIEW_MARKER)]
    if len(matches) != 1:
        raise SupervisorRefused(
            "controller review must contain exactly one marker")
    try:
        claim = json.loads(matches[0])
    except ValueError as exc:
        raise SupervisorRefused("controller review marker is invalid") from exc
    if claim != controller_review_claim(config):
        raise SupervisorRefused("controller review grants wrong authority")
    return claim


def preflight_admission_payload(*, config: Config, review_sha256: str,
                                review_claim: dict, nonce: str,
                                created_time_ns: int) -> dict:
    return {
        "schema": PREFLIGHT_ADMISSION_SCHEMA,
        "run_id": CORE.PREFLIGHT_RUN_ID,
        "git": config.expected_git,
        "runner_sha256": config.expected_runner_sha256,
        "controller_sha256": config.expected_controller_sha256,
        "design_sha256": sha256_file(Path(CORE.DESIGN.__file__)),
        "controller_review_sha256": review_sha256,
        "controller_review_claim": review_claim,
        "nonce": nonce,
        "created_time_ns": created_time_ns,
        "one_score_free_preflight_authorized": True,
        "sequential_execution_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }


def _require_preflight_chain(config: Config, paths: Paths) -> tuple[dict, dict]:
    review_ref = _artifact_ref(
        paths.preflight_review_copy, None, "future S4 controller review")
    admission_ref = _artifact_ref(
        paths.preflight_admission, None, "future S4 preflight admission")
    raw = paths.preflight_review_copy.read_bytes()
    claim = _controller_review_claim(raw, config)
    admission = _load_json(paths.preflight_admission)
    nonce = admission.get("nonce")
    created = admission.get("created_time_ns")
    if (not is_sha256(nonce) or isinstance(created, bool)
            or not isinstance(created, int) or created <= 0
            or admission != preflight_admission_payload(
                config=config, review_sha256=review_ref["sha256"],
                review_claim=claim, nonce=nonce, created_time_ns=created)):
        raise SupervisorRefused("future S4 preflight admission drift")
    return review_ref, admission_ref


def run_score_free_preflight(config: Config, review_record: Path,
                             expected_review_sha256: str) -> dict:
    paths = paths_for()
    _identity_context(config, paths)
    if (not is_regular_unlinked(review_record)
            or sha256_file(review_record) != expected_review_sha256):
        raise SupervisorRefused("controller review source identity drift")
    raw = review_record.read_bytes()
    claim = _controller_review_claim(raw, config)
    design_review_evidence(review_record)
    collisions = [path for path in (
        paths.preflight_review_copy, partial(paths.preflight_review_copy),
        paths.preflight_admission, partial(paths.preflight_admission),
        paths.preflight, partial(paths.preflight)) if lexists(path)]
    if collisions:
        raise SupervisorRefused(
            f"future S4 preflight slot already consumed: {collisions[:2]}")
    _write_bytes_exclusive(paths.preflight_review_copy, raw)
    admission = preflight_admission_payload(
        config=config, review_sha256=expected_review_sha256,
        review_claim=claim, nonce=secrets.token_hex(32),
        created_time_ns=time.time_ns())
    _write_json_exclusive(paths.preflight_admission, admission)
    CORE.preflight(argparse.Namespace(
        expected_git=config.expected_git,
        controller_review=str(paths.preflight_review_copy),
        expected_controller_review_sha256=expected_review_sha256,
        preflight_admission=str(paths.preflight_admission),
        expected_preflight_admission_sha256=sha256_file(
            paths.preflight_admission),
        out=str(paths.preflight)))
    parent, runtime = CORE.require_runtime(config.expected_git)
    evidence = preflight_evidence(
        config, paths, parent=parent, runtime=runtime)
    return {"status": evidence["status"], "preflight": evidence,
            "sequential_execution_authorized": False}


def preflight_evidence(config: Config, paths: Paths, *,
                       parent: dict, runtime: dict) -> dict:
    _require_preflight_chain(config, paths)
    ref = _artifact_ref(paths.preflight, None, "future S4 preflight")
    review_ref = _artifact_ref(
        paths.preflight_review_copy, None, "future S4 controller review")
    admission_ref = _artifact_ref(
        paths.preflight_admission, None, "future S4 preflight admission")
    payload = _load_json(paths.preflight)
    expected_fields = {
        "schema", "complete", "score_free", "outcomes_published",
        "outcomes_discarded", "run_id", "clusters", "seed0",
        "stream_stride", "parent", "runtime", "design",
        "controller_review", "preflight_admission", "elapsed_seconds",
        "throughput_safety_factor", "counter_totals",
        "point_banking_telemetry", "projection", "criteria", "status",
        "sequential_launch_authorized", "tranche_2_pre_authorized",
        "strength_claim",
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
            or payload.get("design") != CORE.DESIGN_RECORD
            or payload.get("controller_review") != {
                "path": review_ref["path"], "sha256": review_ref["sha256"]}
            or payload.get("preflight_admission") != {
                "path": admission_ref["path"],
                "sha256": admission_ref["sha256"]}
            or payload.get("status") != "AUTHORIZE_SEQUENTIAL_PACKET_REVIEW"
            or not isinstance(criteria, dict)
            or criteria.get("all") is not True
            or not all(criteria.values())
            or not isinstance(projection, dict)
            or projection.get("fleet_hours", float("inf")) >
            CORE.MAX_PROJECTED_FLEET_HOURS
            or projection.get("max_shard_hours", float("inf")) >
            CORE.MAX_PROJECTED_SHARD_HOURS
            or payload.get("sequential_launch_authorized") is not False
            or payload.get("tranche_2_pre_authorized") is not False
            or payload.get("strength_claim") is not False
            or payload.get("training_authorized") is not False
            or payload.get("production_promotion") is not False
            or payload.get("retry_or_extension_authorized") is not False):
        raise SupervisorRefused("future S4 preflight identity/authority drift")
    return {
        **ref,
        "score_free": True,
        "outcomes_published": False,
        "status": payload["status"],
        "elapsed_seconds": payload["elapsed_seconds"],
        "projection": projection,
    }


def design_review_evidence(path: Path) -> dict:
    ref = _artifact_ref(path, None, "S4 future design review")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SupervisorRefused("cannot read S4 future design review") from exc
    matches = [line for line in text.splitlines()
               if DESIGN_REVIEW_HEADING in line]
    if len(matches) != 1 or DESIGN_REVIEW_GIT[:7] not in matches[0]:
        raise SupervisorRefused("S4 future design PASS identity drift")
    return {**ref, "git": DESIGN_REVIEW_GIT,
            "verdict": "PASS_TO_IMPLEMENT"}


def packet_contract(config: Config, paths: Paths, *, parent: dict,
                    runtime: dict, preflight: dict,
                    design_review: dict) -> dict:
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
        "design": CORE.json_copy(CORE.DESIGN_RECORD),
        "design_review": design_review,
        "score_free_preflight": preflight,
        "schedule": CORE.schedule(),
        "namespace": str(NAMESPACE),
        "tranches": CORE.tranche_contract(),
        "heartbeat_seconds": config.heartbeat_seconds,
        "transition_table": {
            "look_1": dict(CORE.LOOK1_TRANSITION),
            "final": dict(CORE.FINAL_TRANSITION),
        },
        "selection_rule": CORE.SELECTION_RULE,
        "claim_boundary": CORE.CLAIM_BOUNDARY,
        "packet_review_authorized": True,
        "sequential_launch_authorized": False,
        "tranche_2_pre_authorized": True,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "retry_or_extension_authorized": False,
    }


def _expected_packet(config: Config, paths: Paths) -> tuple[dict, dict, dict]:
    parent, runtime = _identity_context(config, paths)
    preflight = preflight_evidence(
        config, paths, parent=parent, runtime=runtime)
    design_review = design_review_evidence(paths.design_review_copy)
    packet = packet_contract(
        config, paths, parent=parent, runtime=runtime,
        preflight=preflight, design_review=design_review)
    return packet, parent, runtime


def freeze_packet(config: Config, design_review_record: Path) -> dict:
    paths = paths_for()
    if paths.namespace.exists():
        raise SupervisorRefused("future S4 namespace already exists")
    review = design_review_evidence(design_review_record)
    _write_bytes_exclusive(
        paths.design_review_copy, design_review_record.read_bytes())
    if sha256_file(paths.design_review_copy) != review["sha256"]:
        raise SupervisorRefused("copied design review differs from source")
    packet, _, _ = _expected_packet(config, paths)
    _write_json_exclusive(paths.packet, packet)
    return {
        "path": rel(paths.packet),
        "sha256": sha256_file(paths.packet),
        "packet_review_authorized": True,
        "sequential_launch_authorized": False,
    }


def verify_packet(config: Config, paths: Paths | None = None) -> dict:
    paths = paths or paths_for()
    if not is_regular_unlinked(paths.packet) or lexists(partial(paths.packet)):
        raise SupervisorRefused("future S4 packet missing, linked, or partial")
    expected, _, _ = _expected_packet(config, paths)
    actual = _load_json(paths.packet)
    if actual != expected:
        raise SupervisorRefused("future S4 packet full recomputation drift")
    return actual


def _expected_review_claim(*, packet_sha256: str,
                           preflight_sha256: str,
                           design_review_sha256: str,
                           config: Config) -> dict:
    return CORE.expected_review_claim(
        expected_git=config.expected_git,
        packet_sha256=packet_sha256,
        preflight_sha256=preflight_sha256,
        design_review_sha256=design_review_sha256)


def _review_claim(raw: bytes, *, packet_sha256: str,
                  preflight_sha256: str, design_review_sha256: str,
                  config: Config) -> dict:
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
        design_review_sha256=design_review_sha256,
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
    design_review_sha256 = packet["design_review"]["sha256"]
    claim = _review_claim(
        raw, packet_sha256=packet_sha256,
        preflight_sha256=preflight_sha256,
        design_review_sha256=design_review_sha256, config=config)
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
        "sequential_launch_authorized": True,
        "tranche_2_pre_authorized": True,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
    }
    _write_json_exclusive(paths.admission, admission)
    return {"path": rel(paths.admission),
            "sha256": sha256_file(paths.admission),
            "sequential_launch_authorized": True}


def _require_admission(config: Config, paths: Paths) -> tuple[dict, dict]:
    packet = verify_packet(config, paths)
    for path, label in ((paths.review_copy, "review copy"),
                        (paths.admission, "review admission")):
        if not is_regular_unlinked(path) or lexists(partial(path)):
            raise SupervisorRefused(f"{label} missing, linked, or partial")
    packet_sha256 = sha256_file(paths.packet)
    review_sha256 = sha256_file(paths.review_copy)
    preflight_sha256 = packet["score_free_preflight"]["sha256"]
    design_review_sha256 = packet["design_review"]["sha256"]
    claim = _review_claim(
        paths.review_copy.read_bytes(), packet_sha256=packet_sha256,
        preflight_sha256=preflight_sha256,
        design_review_sha256=design_review_sha256, config=config)
    expected = {
        "schema": CORE.ADMISSION_SCHEMA,
        "run_id": RUN_ID,
        "packet": {"path": str(NAMESPACE / PACKET_NAME),
                   "sha256": packet_sha256},
        "review": {"path": str(NAMESPACE / REVIEW_NAME),
                   "sha256": review_sha256},
        "review_claim": claim,
        "operator_asserted_independent_review": True,
        "sequential_launch_authorized": True,
        "tranche_2_pre_authorized": True,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
    }
    if _load_json(paths.admission) != expected:
        raise SupervisorRefused("future S4 review admission drift")
    return packet, expected


def _execution_targets(paths: Paths) -> tuple[Path, ...]:
    return (
        paths.receipt, partial(paths.receipt),
        paths.tranche2_preauthorization,
        partial(paths.tranche2_preauthorization),
        paths.tranche2_release, partial(paths.tranche2_release),
        paths.progress_partial, paths.progress_final,
        paths.final, partial(paths.final),
        *paths.shards, *[partial(path) for path in paths.shards],
        *paths.shard_logs, *[partial(path) for path in paths.shard_logs],
        *paths.shard_exits, *[partial(path) for path in paths.shard_exits],
        *paths.aggregates, *[partial(path) for path in paths.aggregates],
    )


def launch_preflight(config: Config, paths: Paths) -> tuple[dict, dict, dict]:
    packet, parent, runtime = _expected_packet(config, paths)
    actual, admission = _require_admission(config, paths)
    if actual != packet:
        raise SupervisorRefused("admitted future S4 packet drift")
    collisions = [str(path) for path in _execution_targets(paths)
                  if lexists(path)]
    if collisions:
        raise SupervisorRefused(
            f"future S4 namespace collision: {collisions[:3]}")
    allowed = {PACKET_NAME, DESIGN_REVIEW_NAME, REVIEW_NAME, ADMISSION_NAME}
    present = {path.name for path in paths.namespace.iterdir()}
    if present != allowed:
        raise SupervisorRefused(
            f"future S4 namespace contains unknown bytes: "
            f"{sorted(present - allowed)}")
    return parent, runtime, admission


def receipt_problems(receipt: dict, *, config: Config,
                     packet_sha256: str, admission_sha256: str,
                     preflight_sha256: str,
                     design_review_sha256: str) -> list[str]:
    expected = {
        "schema": CORE.RECEIPT_SCHEMA,
        "run_id": RUN_ID,
        "complete": True,
        "git": config.expected_git,
        "runner_sha256": config.expected_runner_sha256,
        "controller_sha256": config.expected_controller_sha256,
        "design_sha256": sha256_file(Path(CORE.DESIGN.__file__)),
        "created_time_ns": receipt.get("created_time_ns"),
        "nonce": receipt.get("nonce"),
        "packet_sha256": packet_sha256,
        "admission_sha256": admission_sha256,
        "preflight_sha256": preflight_sha256,
        "design_review_sha256": design_review_sha256,
        "sequential_launch_authorized": True,
        "tranche_2_pre_authorized": True,
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
                if '"event": "s4-point-banking-future-progress-v1"' \
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
        "clusters_total": CORE.TRANCHE_CLUSTERS_PER_SHARD,
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
            raise SupervisorRefused(f"future S4 child failure: {failures}")
        if not live:
            if complete != len(jobs):
                raise SupervisorRefused("child population did not complete")
            return
        time.sleep(heartbeat_seconds)


def _job_specs(config: Config, paths: Paths,
               execution_receipt_sha256: str, *, tranche: int):
    specs = []
    for index in range(SHARD_COUNT):
        position = shard_position(tranche, index)
        specs.append((
            f"tranche-{tranche}-shard-{index:02d}",
            shard_argv(config, tranche, index, paths.shards[position],
                       execution_receipt_sha256),
            paths.shards[position], paths.shard_logs[position],
            paths.shard_exits[position],
        ))
    return specs


def _recompute_aggregate(config: Config, paths: Paths, *, parent: dict,
                         runtime: dict, look: int) -> dict:
    try:
        receipt = CORE.require_receipt(
            paths.receipt, sha256_file(paths.receipt),
            expected_git=config.expected_git)
    except Exception as exc:
        raise SupervisorRefused(
            f"future S4 authority refused during aggregation: {exc}") \
            from exc
    args = argparse.Namespace(
        look=look,
        shards=[str(path) for path in paths.shards[:look * SHARD_COUNT]])
    try:
        shards, inputs = CORE.load_shards(
            args, parent=parent, runtime=runtime, receipt=receipt)
        return CORE.build_aggregate(
            shards=shards, inputs=inputs, parent=parent, runtime=runtime,
            look=look)
    except Exception as exc:
        raise SupervisorRefused(f"aggregate recomputation refused: {exc}") \
            from exc


def terminal_job_evidence(config: Config, paths: Paths,
                          execution_receipt_sha256: str, *,
                          tranches_run: int):
    evidence = []
    problems = []
    for tranche in range(1, tranches_run + 1):
        for name, argv, output, log, exit_path in _job_specs(
                config, paths, execution_receipt_sha256, tranche=tranche):
            artifacts = {"output": output, "log": log, "exit": exit_path}
            invalid = [label for label, path in artifacts.items()
                       if (not is_regular_unlinked(path)
                           or lexists(partial(path)))]
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
                "output": {"path": rel(output),
                           "sha256": sha256_file(output)},
                "log": {"path": rel(log), "sha256": sha256_file(log)},
                "exit": {"path": rel(exit_path),
                         "sha256": sha256_file(exit_path)},
            })
    if len(evidence) != SHARD_COUNT * tranches_run:
        problems.append("terminal child evidence population")
    return evidence, sorted(set(problems))


def mechanical_transition(aggregate: dict, *, look: int) -> str:
    if (aggregate.get("schema") != CORE.AGGREGATE_SCHEMA
            or aggregate.get("look") != look
            or aggregate.get("clusters") != CORE.LOOK_CLUSTERS[look - 1]):
        raise SupervisorRefused("aggregate identity cannot drive transition")
    integrity = aggregate.get("integrity")
    stats = aggregate.get("stats")
    if not isinstance(integrity, dict) or not isinstance(stats, dict):
        raise SupervisorRefused("aggregate transition inputs are missing")
    integrity_pass = integrity.get("all") is True and all(
        value is True for name, value in integrity.items() if name != "all")
    primary = stats.get("treatment_champion")
    if not isinstance(primary, dict) or not isinstance(primary.get("lcb"),
                                                        (int, float)):
        raise SupervisorRefused("aggregate efficacy input is missing")
    efficacy_pass = primary["lcb"] > 0
    if look == 1:
        status = ("STOP_HOLD" if not integrity_pass else
                  "STOP_PASS" if efficacy_pass else
                  "CONTINUE_AUTOMATICALLY")
    else:
        status = ("HOLD" if not integrity_pass else
                  "PASS" if efficacy_pass else "SELECT_NONE")
    if (aggregate.get("efficacy_pass") is not efficacy_pass
            or aggregate.get("status") != status):
        raise SupervisorRefused("aggregate transition is not mechanical")
    return status


def tranche2_preauthorization_payload(*, packet_sha256: str,
                                      receipt_sha256: str) -> dict:
    return {
        "schema": PREAUTH_SCHEMA,
        "run_id": RUN_ID,
        "packet_sha256": packet_sha256,
        "receipt_sha256": receipt_sha256,
        "tranche": 2,
        "look_1_required_status": "CONTINUE_AUTOMATICALLY",
        "look_1_transition": dict(CORE.LOOK1_TRANSITION),
        "tranche_2_commands_sha256": CORE.stable_digest(
            [command_template(2, index) for index in range(SHARD_COUNT)]),
        "preauthorized_before_gameplay": True,
        "execution_unlocked": False,
        "human_choice_between_looks": False,
        "production_promotion": False,
    }


def tranche2_release_payload(*, paths: Paths, look1: dict) -> dict:
    status = mechanical_transition(look1, look=1)
    if status != "CONTINUE_AUTOMATICALLY":
        raise SupervisorRefused("look 1 does not mechanically release tranche 2")
    preauthorization = _load_json(paths.tranche2_preauthorization)
    expected = tranche2_preauthorization_payload(
        packet_sha256=sha256_file(paths.packet),
        receipt_sha256=sha256_file(paths.receipt))
    if preauthorization != expected:
        raise SupervisorRefused("tranche 2 preauthorization drift")
    return {
        "schema": RELEASE_SCHEMA,
        "run_id": RUN_ID,
        "tranche": 2,
        "preauthorization_sha256": sha256_file(
            paths.tranche2_preauthorization),
        "look_1_aggregate_sha256": sha256_file(paths.aggregates[0]),
        "look_1_status": status,
        "mechanical_transition_only": True,
        "tranche_2_execution_authorized": True,
        "human_choice_between_looks": False,
        "production_promotion": False,
    }


def final_payload(*, paths: Paths, packet_sha256: str,
                  admission_sha256: str, aggregate: dict,
                  job_evidence: list[dict], terminal_look: int) -> dict:
    status = aggregate.get("status")
    release = (None if terminal_look == 1 else {
        "path": rel(paths.tranche2_release),
        "sha256": sha256_file(paths.tranche2_release)})
    return {
        "schema": FINAL_SCHEMA,
        "run_id": RUN_ID,
        "complete": True,
        "packet_sha256": packet_sha256,
        "admission_sha256": admission_sha256,
        "receipt_sha256": sha256_file(paths.receipt),
        "progress_sha256": sha256_file(paths.progress_final),
        "terminal_look": terminal_look,
        "jobs": job_evidence,
        "shards": [{"path": rel(path), "sha256": sha256_file(path),
                    "tranche": position // SHARD_COUNT + 1,
                    "shard_index": position % SHARD_COUNT}
                   for position, path in enumerate(
                       paths.shards[:terminal_look * SHARD_COUNT])],
        "aggregates": [{
            "path": rel(paths.aggregates[index]),
            "sha256": sha256_file(paths.aggregates[index]),
            "look": index + 1,
        } for index in range(terminal_look)],
        "terminal_aggregate": {
                      "path": rel(paths.aggregates[terminal_look - 1]),
                      "sha256": sha256_file(
                          paths.aggregates[terminal_look - 1]),
                      "status": status},
        "tranche_2_preauthorization": {
            "path": rel(paths.tranche2_preauthorization),
            "sha256": sha256_file(paths.tranche2_preauthorization)},
        "tranche_2_release": release,
        "strength_claim": status in ("STOP_PASS", "PASS"),
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
        "design_sha256": sha256_file(Path(CORE.DESIGN.__file__)),
        "created_time_ns": time.time_ns(),
        "nonce": secrets.token_hex(32),
        "packet_sha256": packet_sha256,
        "admission_sha256": admission_sha256,
        "preflight_sha256": packet["score_free_preflight"]["sha256"],
        "design_review_sha256": packet["design_review"]["sha256"],
        "sequential_launch_authorized": True,
        "tranche_2_pre_authorized": True,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "retry_or_extension_authorized": False,
    }
    problems = receipt_problems(
        receipt, config=config, packet_sha256=packet_sha256,
        admission_sha256=admission_sha256,
        preflight_sha256=packet["score_free_preflight"]["sha256"],
        design_review_sha256=packet["design_review"]["sha256"])
    if problems:
        raise SupervisorRefused("; ".join(problems))
    _write_json_exclusive(paths.receipt, receipt)
    execution_receipt_sha256 = sha256_file(paths.receipt)
    _write_json_exclusive(
        paths.tranche2_preauthorization,
        tranche2_preauthorization_payload(
            packet_sha256=packet_sha256,
            receipt_sha256=execution_receipt_sha256))
    progress = Progress(paths.progress_partial)
    all_jobs: list[Job] = []
    terminal_look = 0
    try:
        progress.event(
            "launch", "receipt-published",
            packet_sha256=packet_sha256,
            admission_sha256=admission_sha256,
            receipt_sha256=execution_receipt_sha256,
            tranche_2_preauthorization_sha256=sha256_file(
                paths.tranche2_preauthorization))
        aggregate = None
        for tranche in (1, 2):
            jobs: list[Job] = []
            for name, argv, output, log, exit_path in _job_specs(
                    config, paths, execution_receipt_sha256,
                    tranche=tranche):
                job = _start_job(name, argv, output, log, exit_path)
                jobs.append(job)
                all_jobs.append(job)
                progress.event("shard", "started", tranche=tranche,
                               job=name, pid=job.process.pid,
                               output=rel(output))
            _wait_parallel(jobs, progress, config.heartbeat_seconds)
            aggregate = _recompute_aggregate(
                config, paths, parent=parent, runtime=runtime, look=tranche)
            _write_json_exclusive(paths.aggregates[tranche - 1], aggregate)
            if _load_json(paths.aggregates[tranche - 1]) != aggregate:
                raise SupervisorRefused("aggregate failed exact reopen")
            status = mechanical_transition(aggregate, look=tranche)
            progress.event(
                "aggregate", "complete", look=tranche,
                status_value=status,
                aggregate_sha256=sha256_file(paths.aggregates[tranche - 1]))
            terminal_look = tranche
            if tranche == 1 and status == "CONTINUE_AUTOMATICALLY":
                release = tranche2_release_payload(paths=paths,
                                                    look1=aggregate)
                _write_json_exclusive(paths.tranche2_release, release)
                progress.event(
                    "transition", "tranche-2-released",
                    release_sha256=sha256_file(paths.tranche2_release))
                continue
            break
        if aggregate is None or terminal_look not in (1, 2):
            raise SupervisorRefused("sequential controller produced no terminal")
        job_evidence, evidence_problems = terminal_job_evidence(
            config, paths, execution_receipt_sha256,
            tranches_run=terminal_look)
        if evidence_problems:
            raise SupervisorRefused("; ".join(evidence_problems))
        progress.close()
        _publish_partial(paths.progress_partial, paths.progress_final)
        final = final_payload(
            paths=paths, packet_sha256=packet_sha256,
            admission_sha256=admission_sha256, aggregate=aggregate,
            job_evidence=job_evidence, terminal_look=terminal_look)
        _write_json_exclusive(paths.final, final)
        print(json.dumps(final, indent=2, sort_keys=True), flush=True)
    except BaseException:
        _terminate(all_jobs)
        for job in all_jobs:
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
        raise SupervisorRefused("terminal future S4 packet drift")
    if not is_regular_unlinked(paths.final):
        raise SupervisorRefused("terminal future S4 final is missing")
    recorded_final = _load_json(paths.final)
    terminal_look = recorded_final.get("terminal_look")
    if terminal_look not in (1, 2):
        raise SupervisorRefused("terminal look is invalid")
    terminal = (
        paths.receipt, paths.tranche2_preauthorization,
        paths.progress_final, paths.final,
        *paths.shards[:terminal_look * SHARD_COUNT],
        *paths.shard_logs[:terminal_look * SHARD_COUNT],
        *paths.shard_exits[:terminal_look * SHARD_COUNT],
        *paths.aggregates[:terminal_look],
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
        preflight_sha256=preflight_sha256,
        design_review_sha256=packet["design_review"]["sha256"])
    preauthorization = tranche2_preauthorization_payload(
        packet_sha256=packet_sha256,
        receipt_sha256=sha256_file(paths.receipt))
    if _load_json(paths.tranche2_preauthorization) != preauthorization:
        problems.append("tranche 2 preauthorization drift")
    execution_receipt_sha256 = sha256_file(paths.receipt)
    aggregates = [_load_json(path)
                  for path in paths.aggregates[:terminal_look]]
    aggregate = aggregates[-1]
    for index, value in enumerate(aggregates, 1):
        if value != _recompute_aggregate(
                config, paths, parent=parent, runtime=runtime, look=index):
            problems.append(f"look {index} aggregate full recomputation drift")
        try:
            mechanical_transition(value, look=index)
        except SupervisorRefused as exc:
            problems.append(str(exc))
    if terminal_look == 2:
        if not is_regular_unlinked(paths.tranche2_release):
            problems.append("tranche 2 release missing")
        elif _load_json(paths.tranche2_release) != tranche2_release_payload(
                paths=paths, look1=aggregates[0]):
            problems.append("tranche 2 release drift")
    elif lexists(paths.tranche2_release):
        problems.append("tranche 2 release exists after look-1 stop")
    if terminal_look == 1:
        unused = (
            *paths.shards[SHARD_COUNT:], *paths.shard_logs[SHARD_COUNT:],
            *paths.shard_exits[SHARD_COUNT:], paths.aggregates[1],
            *[partial(path) for path in (
                *paths.shards[SHARD_COUNT:], *paths.shard_logs[SHARD_COUNT:],
                *paths.shard_exits[SHARD_COUNT:], paths.aggregates[1])],
        )
        if any(lexists(path) for path in unused):
            problems.append("tranche 2 artifact exists after look-1 stop")
    job_evidence, evidence_problems = terminal_job_evidence(
        config, paths, execution_receipt_sha256,
        tranches_run=terminal_look)
    problems += evidence_problems
    expected_final = final_payload(
        paths=paths, packet_sha256=packet_sha256,
        admission_sha256=admission_sha256, aggregate=aggregate,
        job_evidence=job_evidence, terminal_look=terminal_look)
    if _load_json(paths.final) != expected_final:
        problems.append("supervisor final full recomputation drift")
    if problems:
        raise SupervisorRefused("terminal future S4 verify: "
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
        "command", choices=("controller-review-claim", "run-preflight",
                            "freeze", "verify-packet", "admit", "launch",
                            "verify"))
    parser.add_argument("--expected-git", required=True)
    parser.add_argument("--expected-runner-sha256", required=True)
    parser.add_argument("--expected-controller-sha256", required=True)
    parser.add_argument("--heartbeat-seconds", type=float, default=30.0)
    parser.add_argument("--design-review-record")
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
    if args.command == "controller-review-claim":
        print(CONTROLLER_REVIEW_MARKER + json.dumps(
            controller_review_claim(config), sort_keys=True,
            separators=(",", ":")))
    elif args.command == "run-preflight":
        if not all((args.review_record, args.expected_review_sha256)):
            raise SupervisorRefused(
                "run-preflight requires review path and SHA-256")
        print(json.dumps(run_score_free_preflight(
            config, Path(args.review_record),
            args.expected_review_sha256), sort_keys=True))
    elif args.command == "freeze":
        if not args.design_review_record:
            raise SupervisorRefused("freeze requires design review record")
        print(json.dumps(freeze_packet(
            config, Path(args.design_review_record)), sort_keys=True))
    elif args.command == "verify-packet":
        packet = verify_packet(config)
        print(json.dumps({
            "verified": True,
            "packet_sha256": sha256_file(paths_for().packet),
            "sequential_launch_authorized":
            packet["sequential_launch_authorized"],
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

#!/usr/bin/env python3
"""One-shot, outcome-discarding capacity preflight for Stage-C labels.

The reviewed Stage-C design requires a capacity measurement after the exact
2,048-state population passes review and before the label controller can be
frozen.  This program samples two deterministic states from every future
label shard and runs the exact label path in eight spawned workers.  A worker
may compute an outcome tensor transiently so that timing is representative,
but it validates and discards that tensor before returning.  Only work,
sampler and timing telemetry can reach the parent or a durable artifact.

The packet, execution, result and result review are separate boundaries.  A
PASS authorizes only a later label-controller packet review.  It never
authorizes labels, training, REPORT opening, strength, promotion or deploy.
Any consumed execution that times out, refuses, crashes or underfills is a
terminal hold for this run ID; there is no retry or extension path here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing
import os
import stat
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SCRIPT.parent))

import teacher_stage_c_capture_runtime as CAPTURE  # noqa: E402
import teacher_stage_c_label_controller as CTRL  # noqa: E402
import teacher_stage_c_label_runtime as LABEL  # noqa: E402


SCHEMA = "teacher-stage-c-label-capacity-controller-v2"
PACKET_ID = "teacher-v3-hard-tail-stage-c-label-capacity-controller-v2"
RUN_ID = "teacher-v3-hard-tail-stage-c-label-capacity-v2"
PACKET_PATH = f"server/runs/logs/{RUN_ID}/controller_packet.json"
RESULT_PATH = f"server/runs/logs/{RUN_ID}/capacity-result.json"
PACKET_REVIEW_SCHEMA = "teacher-stage-c-label-capacity-controller-review-v2"
PACKET_REVIEW_MARKER = "TEACHER_STAGE_C_LABEL_CAPACITY_V2_REVIEW "
RESULT_SCHEMA = "teacher-stage-c-label-capacity-result-v2"
RESULT_REVIEW_SCHEMA = "teacher-stage-c-label-capacity-result-review-v2"
RESULT_REVIEW_MARKER = "TEACHER_STAGE_C_LABEL_CAPACITY_RESULT_V2_REVIEW "
ADMISSION_SCHEMA = "teacher-stage-c-label-capacity-admission-v2"

SAMPLES_PER_SHARD = 2
SAMPLE_STATES = CTRL.LABEL_SHARDS * SAMPLES_PER_SHARD
WORKERS = 8
THROUGHPUT_SAFETY_FACTOR = 2.0
MAX_PREFLIGHT_WALL_HOURS = 4.0
MAX_PROJECTED_FLEET_HOURS = 192.0
MAX_PROJECTED_SHARD_HOURS = 24.0
MAX_PROJECTED_EIGHT_WORKER_WALL_HOURS = 24.0
HEARTBEAT_SECONDS = 30.0

# Exact keys forbidden anywhere in a durable packet/result.  Provenance names
# such as ``label_schedule_sha256`` are safe; action tensors and world/outcome
# identities are not.
FORBIDDEN_OUTCOME_KEYS = {
    "actions", "audit", "buried", "bury", "cards", "candidates",
    "decision", "hands", "label_action", "mean", "outcome", "played",
    "points", "raw_attacker_points", "report", "row_sha256", "selection",
    "signed_level_utility", "utilities", "utility", "winner",
    "world_key_sha256s", "world_keys_sha256",
}

SAMPLE_TELEMETRY_FIELDS = {
    "shard_index", "sample_role", "state_id", "split", "surface_type",
    "stratum", "ply", "candidate_count", "audit_expected",
    "expected_candidate_worlds", "sampler_attempt_cap", "status",
    "candidate_worlds_attempted", "candidate_worlds_completed", "sampler",
    "elapsed_seconds", "v11_load_seconds", "reason_class", "reason_sha256",
    "outcome_tensor_returned", "outcomes_retained",
}
SAMPLER_TELEMETRY_FIELDS = {
    "sampler_attempts", "accepted_worlds", "failed_worlds",
    "rejected_worlds", "impossible_worlds", "unique_worlds_within_folds",
    "duplicate_draws_retained", "prior_fold_overlap_draws_retained",
}

SOURCE_PATHS = tuple(dict.fromkeys((
    "server/scripts/teacher_stage_c_label_capacity.py",
    *CTRL.SOURCE_PATHS,
)))


class CapacityRefused(RuntimeError):
    """The frozen preflight cannot support its bounded capacity claim."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def self_hash(value: Mapping[str, object], field: str) -> str:
    return sha256_bytes(canonical_json({
        key: item for key, item in value.items() if key != field
    }))


def is_regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink())


def load_json(path: Path) -> dict:
    if not is_regular_unlinked(path):
        raise CapacityRefused(f"input is not regular/unlinked: {path}")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise CapacityRefused(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CapacityRefused(f"JSON root is not an object: {path}")
    return value


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _is_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def forbidden_outcome_paths(value: object, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_OUTCOME_KEYS:
                found.append(child_path)
            found.extend(forbidden_outcome_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(forbidden_outcome_paths(child, f"{path}[{index}]"))
    return found


def marker_claim(path: Path, marker: str) -> dict:
    if not is_regular_unlinked(path):
        raise CapacityRefused("review record is not regular/unlinked")
    matches = [line[len(marker):] for line in path.read_text().splitlines()
               if line.startswith(marker)]
    if len(matches) != 1:
        raise CapacityRefused(
            f"review record must contain exactly one {marker.strip()} marker")
    try:
        value = json.loads(matches[0])
    except ValueError as exc:
        raise CapacityRefused("capacity review marker is not valid JSON") from exc
    if not isinstance(value, dict):
        raise CapacityRefused("capacity review marker is not an object")
    return value


def admission_slot_logical_path() -> str:
    return f"server/runs/locks/{RUN_ID}.consumed.json"


def require_admission_slot_ignored() -> dict:
    logical = admission_slot_logical_path()
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", logical], cwd=REPO,
        capture_output=True,
    )
    if result.returncode != 0:
        raise CapacityRefused(f"admission slot is not Git-ignored: {logical}")
    return {"logical_path": logical, "gitignored": True}


def runtime_sources() -> dict[str, str]:
    values = {}
    for logical in SOURCE_PATHS:
        path = REPO / logical
        if not is_regular_unlinked(path):
            raise CapacityRefused(f"capacity runtime source missing: {logical}")
        values[logical] = sha256_file(path)
    return dict(sorted(values.items()))


def producer_identity(*, smoke: bool) -> dict:
    require_admission_slot_ignored()
    dirty = bool(_git("status", "--porcelain", "--untracked-files=all"))
    if dirty and not smoke:
        raise CapacityRefused("real capacity freeze refuses a dirty tree")
    return {
        "git": _git("rev-parse", "HEAD"),
        "tree_dirty": dirty,
        "promotable": not smoke,
        "controller_script_sha256": sha256_file(SCRIPT),
    }


def _sample_descriptor(state: Mapping[str, object], *, shard_index: int,
                       sample_role: str, audit: bool) -> dict:
    ply = state.get("ply")
    if isinstance(ply, bool) or not isinstance(ply, int) or ply < 0:
        raise CapacityRefused("capacity state ply is not a nonnegative integer")
    return {
        "shard_index": shard_index,
        "sample_role": sample_role,
        "state_id": state["state_id"],
        "split": state["split"],
        "surface_type": state["surface_type"],
        "stratum": state["stratum"],
        "ply": ply,
        "candidate_count": len(state["candidates"]),
        "audit_expected": audit,
        "expected_candidate_worlds": CTRL._label_candidate_worlds(state, audit),
        "sampler_attempt_cap": CTRL._sampler_attempt_cap(state, audit),
    }


def build_capacity_schedule(state_set: Mapping[str, object]) -> dict:
    """Choose lowest-support late and maximal-work witnesses per label shard."""
    label_schedule = CTRL.build_schedule(state_set)
    states = {str(state["state_id"]): state for state in state_set["states"]}
    if len(states) != CTRL.EXPECTED_STATES:
        raise CapacityRefused("capacity state identity collision")
    samples = []
    for shard in label_schedule["shards"]:
        audit_ids = set(shard["audit_state_ids"])
        rows = [states[str(state_id)] for state_id in shard["state_ids"]]
        ranked_late = sorted(
            rows,
            key=lambda state: (
                -int(state["ply"]),
                -CTRL._label_candidate_worlds(
                    state, state["state_id"] in audit_ids),
                str(state["state_id"]),
            ),
        )
        late = ranked_late[0]
        remaining = [state for state in rows
                     if state["state_id"] != late["state_id"]]
        ranked_work = sorted(
            remaining,
            key=lambda state: (
                -CTRL._label_candidate_worlds(
                    state, state["state_id"] in audit_ids),
                int(state["ply"]), str(state["state_id"]),
            ),
        )
        heavy = ranked_work[0]
        samples.extend((
            _sample_descriptor(
                late, shard_index=shard["index"],
                sample_role="latest_ply", audit=late["state_id"] in audit_ids),
            _sample_descriptor(
                heavy, shard_index=shard["index"],
                sample_role="max_candidate_worlds",
                audit=heavy["state_id"] in audit_ids),
        ))
    samples.sort(key=lambda value: (
        int(value["shard_index"]), str(value["sample_role"])))
    if (len(samples) != SAMPLE_STATES
            or len({sample["state_id"] for sample in samples}) != SAMPLE_STATES
            or Counter(sample["shard_index"] for sample in samples)
            != {index: SAMPLES_PER_SHARD for index in range(CTRL.LABEL_SHARDS)}):
        raise CapacityRefused("capacity sample geometry drift")
    payload = {
        "selection_rule": {
            "per_shard": [
                "maximum ply, then maximum expected candidate-world work, "
                "then state ID",
                "maximum expected candidate-world work among remaining states, "
                "then minimum ply, then state ID",
            ],
            "selection_uses_no_outcomes": True,
        },
        "workers": WORKERS,
        "samples_per_shard": SAMPLES_PER_SHARD,
        "sample_states": SAMPLE_STATES,
        "samples": samples,
        "sample_candidate_worlds": sum(
            int(sample["expected_candidate_worlds"]) for sample in samples),
        "sample_sampler_attempt_cap": sum(
            int(sample["sampler_attempt_cap"]) for sample in samples),
        "label_schedule_sha256": label_schedule["schedule_sha256"],
        "label_candidate_worlds": label_schedule["candidate_worlds"],
        "label_shards": CTRL.LABEL_SHARDS,
    }
    payload["schedule_sha256"] = sha256_bytes(canonical_json(payload))
    return payload


def build_packet(
    capture_controller_path: Path,
    state_set_path: Path, state_set_sha256: str,
    verification_path: Path, verification_sha256: str,
    state_set_review_record: Path, *, smoke: bool,
) -> dict:
    capture = CTRL.validate_capture_controller(capture_controller_path)
    state_set, verification, state_review = CTRL.validate_state_set(
        state_set_path, state_set_sha256,
        verification_path, verification_sha256,
        state_set_review_record)
    label_schedule = CTRL.build_schedule(state_set)
    schedule = build_capacity_schedule(state_set)
    packet = {
        "schema": SCHEMA,
        "packet_id": PACKET_ID,
        "run_id": RUN_ID,
        "producer": producer_identity(smoke=smoke),
        "parents": {
            "capture_controller": {
                "logical_path": str(capture_controller_path.relative_to(REPO)),
                "external_sha256": CTRL.CAPTURE_CONTROLLER_SHA256,
                "internal_sha256": capture["packet_sha256"],
            },
            "state_set": {
                "logical_path": str(state_set_path.relative_to(REPO)),
                "external_sha256": state_set_sha256,
                "internal_sha256": state_set["dataset_sha256"],
                "review_claim": state_review,
            },
            "capture_verification": {
                "logical_path": str(verification_path.relative_to(REPO)),
                "external_sha256": verification_sha256,
                "internal_sha256": verification["verification_sha256"],
            },
        },
        "runtime_mode": CTRL.CAPTURE_CTRL.require_runtime_mode(),
        "runtime_sources": runtime_sources(),
        "label_schedule": {
            "schedule_sha256": label_schedule["schedule_sha256"],
            "shards": label_schedule["shard_count"],
            "states": label_schedule["state_count"],
            "candidate_worlds": label_schedule["candidate_worlds"],
            "sampler_attempt_cap": label_schedule["sampler_attempt_cap"],
        },
        "preflight_schedule": schedule,
        "execution_contract": {
            "spawn_workers": WORKERS,
            "worker_loads_frozen_v11_once": True,
            "exact_label_state_and_semantic_validator": True,
            "outcome_tensor_exists_only_in_ephemeral_worker_memory": True,
            "outcome_tensor_discarded_before_worker_return": True,
            "durable_outcome_fields_forbidden": sorted(FORBIDDEN_OUTCOME_KEYS),
            "heartbeat_seconds": HEARTBEAT_SECONDS,
            "max_preflight_wall_hours": MAX_PREFLIGHT_WALL_HOURS,
            "retry_or_extension": "TERMINAL_HOLD_NO_RETRY",
        },
        "capacity_gate": {
            "throughput_safety_factor": THROUGHPUT_SAFETY_FACTOR,
            "max_projected_fleet_hours": MAX_PROJECTED_FLEET_HOURS,
            "max_projected_shard_hours": MAX_PROJECTED_SHARD_HOURS,
            "max_projected_eight_worker_wall_hours":
                MAX_PROJECTED_EIGHT_WORKER_WALL_HOURS,
            "projection_adds_max_observed_v11_load_to_every_shard": True,
            "projection_uses_slower_sample_rate_per_shard": True,
        },
        "result_contract": {
            "result": RESULT_PATH,
            "required_complete_samples": SAMPLE_STATES,
            "one_shot_admission": require_admission_slot_ignored(),
            "result_review_required_before_label_controller_freeze": True,
        },
        "command": [
            "{python}",
            "server/scripts/teacher_stage_c_label_capacity.py", "run",
            "--controller-packet", PACKET_PATH,
            "--expected-controller-packet-sha256", "{packet_sha256}",
            "--controller-review-record", "{capacity_controller_review_record}",
            "--state-set-review-record", "{state_set_review_record}",
            "--out", RESULT_PATH,
        ],
        "authority": {
            "worlds_sampled": False,
            "outcomes_computed": False,
            "outcomes_retained": False,
            "one_capacity_execution_authorized": False,
            "label_controller_freeze_authorized": False,
            "labels_authorized": False,
            "training_authorized": False,
            "report_open_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    if forbidden_outcome_paths(packet):
        raise CapacityRefused("capacity packet leaked forbidden outcome fields")
    packet["packet_sha256"] = self_hash(packet, "packet_sha256")
    return packet


def expected_packet_review_claim(packet: Mapping[str, object],
                                 external_sha256: str) -> dict:
    return {
        "schema": PACKET_REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "packet_sha256": external_sha256,
        "packet_internal_sha256": packet["packet_sha256"],
        "state_set_sha256": packet["parents"]["state_set"]["external_sha256"],
        "label_schedule_sha256": packet["label_schedule"]["schedule_sha256"],
        "preflight_schedule_sha256": packet[
            "preflight_schedule"]["schedule_sha256"],
        "sample_states": SAMPLE_STATES,
        "label_shards": CTRL.LABEL_SHARDS,
        "samples_per_shard": SAMPLES_PER_SHARD,
        "spawn_workers": WORKERS,
        "throughput_safety_factor": THROUGHPUT_SAFETY_FACTOR,
        "max_preflight_wall_hours": MAX_PREFLIGHT_WALL_HOURS,
        "max_projected_fleet_hours": MAX_PROJECTED_FLEET_HOURS,
        "max_projected_shard_hours": MAX_PROJECTED_SHARD_HOURS,
        "max_projected_eight_worker_wall_hours":
            MAX_PROJECTED_EIGHT_WORKER_WALL_HOURS,
        "outcomes_computed_before_review": False,
        "outcomes_retained": False,
        "independent_review": True,
        "one_capacity_execution_authorized": True,
        "label_controller_freeze_authorized": False,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def validate_packet_review(path: Path, packet: Mapping[str, object],
                           external_sha256: str) -> dict:
    claim = marker_claim(path, PACKET_REVIEW_MARKER)
    if claim != expected_packet_review_claim(packet, external_sha256):
        raise CapacityRefused("capacity-controller PASS marker drift")
    return claim


def _reopen_packet(
    packet_path: Path, expected_packet_sha256: str,
    controller_review_record: Path, state_set_review_record: Path,
) -> tuple[dict, dict, dict]:
    if sha256_file(packet_path) != expected_packet_sha256:
        raise CapacityRefused("capacity-controller external SHA-256 drift")
    packet = load_json(packet_path)
    if (packet.get("schema") != SCHEMA
            or packet.get("packet_id") != PACKET_ID
            or packet.get("run_id") != RUN_ID
            or packet.get("packet_sha256") != self_hash(packet, "packet_sha256")
            or packet.get("producer", {}).get("git") != _git("rev-parse", "HEAD")
            or _git("status", "--porcelain", "--untracked-files=all")
            or packet.get("runtime_sources") != runtime_sources()
            or packet.get("runtime_mode") !=
                CTRL.CAPTURE_CTRL.require_runtime_mode()
            or forbidden_outcome_paths(packet)):
        raise CapacityRefused("capacity-controller identity/source drift")
    parents = packet["parents"]
    capture_path = REPO / parents["capture_controller"]["logical_path"]
    state_path = REPO / parents["state_set"]["logical_path"]
    verification_path = REPO / parents["capture_verification"]["logical_path"]
    state_set, verification, _claim = CTRL.validate_state_set(
        state_path, parents["state_set"]["external_sha256"],
        verification_path,
        parents["capture_verification"]["external_sha256"],
        state_set_review_record)
    rebuilt = build_packet(
        capture_path, state_path, parents["state_set"]["external_sha256"],
        verification_path,
        parents["capture_verification"]["external_sha256"],
        state_set_review_record, smoke=False)
    if rebuilt != packet:
        raise CapacityRefused("capacity-controller reconstruction drift")
    review = validate_packet_review(
        controller_review_record, packet, expected_packet_sha256)
    return packet, state_set, review


def _require_postcompute_identity(
    packet_path: Path, expected_packet_sha256: str,
    controller_review_record: Path, state_set_review_record: Path,
    packet: Mapping[str, object], state_set: Mapping[str, object],
    review: Mapping[str, object],
) -> None:
    """Fail closed if any reviewed input or runtime source changed in flight."""
    reopened_packet, reopened_state_set, reopened_review = _reopen_packet(
        packet_path, expected_packet_sha256,
        controller_review_record, state_set_review_record)
    if (reopened_packet != packet or reopened_state_set != state_set
            or reopened_review != review):
        raise CapacityRefused(
            "capacity controller/input identity changed during preflight")


def _aggregate_sampler_telemetry(work: Mapping[str, object]) -> dict[str, int]:
    values = {
        "sampler_attempts": 0,
        "accepted_worlds": 0,
        "failed_worlds": 0,
        "rejected_worlds": 0,
        "impossible_worlds": 0,
        "unique_worlds_within_folds": 0,
        "duplicate_draws_retained": 0,
        "prior_fold_overlap_draws_retained": 0,
    }
    samplers = work.get("samplers", {})
    if not isinstance(samplers, dict):
        raise CapacityRefused("capacity work sampler map missing")
    for sampler in samplers.values():
        counters = sampler["counters"]
        values["sampler_attempts"] += int(sampler["attempts"])
        # Every successful iid draw is retained; repeated worlds carry their
        # posterior probability mass instead of being flattened away.
        values["accepted_worlds"] += int(counters["accepted_worlds"])
        for name in ("failed_worlds", "rejected_worlds", "impossible_worlds"):
            values[name] += int(counters[name])
        values["unique_worlds_within_folds"] += int(
            sampler["unique_worlds"])
        values["duplicate_draws_retained"] += int(
            sampler["duplicate_draws_retained"])
        values["prior_fold_overlap_draws_retained"] += int(
            sampler["prior_fold_overlap_draws_retained"])
    return values


_WORKER_NET = None
_WORKER_V11_LOAD_SECONDS = 0.0
_WORKER_INIT_ERROR_CLASS = None
_WORKER_INIT_ERROR_SHA256 = None


def _worker_init() -> None:
    global _WORKER_NET, _WORKER_V11_LOAD_SECONDS
    global _WORKER_INIT_ERROR_CLASS, _WORKER_INIT_ERROR_SHA256
    started = time.monotonic()
    try:
        _WORKER_NET = LABEL._load_v11()
    except Exception as exc:
        _WORKER_NET = None
        _WORKER_INIT_ERROR_CLASS = type(exc).__name__
        _WORKER_INIT_ERROR_SHA256 = sha256_bytes(
            f"{type(exc).__name__}:{exc}".encode())
    finally:
        _WORKER_V11_LOAD_SECONDS = max(time.monotonic() - started, 1e-9)


def _run_sample(task: tuple[dict, dict]) -> dict:
    descriptor, state = task
    started = time.monotonic()
    ledger = LABEL.WorkLedger()
    row = None
    try:
        if _WORKER_INIT_ERROR_CLASS is not None or _WORKER_NET is None:
            raise CapacityRefused(
                "frozen V11 load failed: "
                f"{_WORKER_INIT_ERROR_CLASS}:{_WORKER_INIT_ERROR_SHA256}")
        row = LABEL.label_state(
            state, net=_WORKER_NET,
            include_audit=bool(descriptor["audit_expected"]), ledger=ledger)
        rnd = CAPTURE.replay_state(state)
        LABEL.validate_label_row(
            state, rnd, row,
            audit_expected=bool(descriptor["audit_expected"]))
        work = row["work"]
        if (work["total_candidate_worlds_attempted"]
                != descriptor["expected_candidate_worlds"]
                or work["total_candidate_worlds_completed"]
                != descriptor["expected_candidate_worlds"]):
            raise CapacityRefused("capacity sample work differs from schedule")
        status = "COMPLETE_OUTCOMES_DISCARDED"
        reason_class = None
        reason_sha256 = None
    except Exception as exc:
        refusal = LABEL.refusal_record(state, exc, ledger)
        work = refusal["attempted_work"]
        status = "REFUSED_NO_OUTCOME_RETAINED"
        reason_class = type(exc).__name__
        reason_sha256 = sha256_bytes(
            f"{type(exc).__name__}:{exc}".encode())
    finally:
        row = None
    elapsed = max(time.monotonic() - started, 1e-9)
    telemetry = {
        **descriptor,
        "status": status,
        "candidate_worlds_attempted": int(
            work["total_candidate_worlds_attempted"]),
        "candidate_worlds_completed": int(
            work["total_candidate_worlds_completed"]),
        "sampler": _aggregate_sampler_telemetry(work),
        "elapsed_seconds": elapsed,
        "v11_load_seconds": _WORKER_V11_LOAD_SECONDS,
        "reason_class": reason_class,
        "reason_sha256": reason_sha256,
        "outcome_tensor_returned": False,
        "outcomes_retained": False,
    }
    forbidden = forbidden_outcome_paths(telemetry)
    if forbidden:
        raise CapacityRefused(
            "capacity worker telemetry leaked outcomes: " + ",".join(forbidden))
    return telemetry


def capacity_projection(samples: Sequence[Mapping[str, object]],
                        label_schedule: Mapping[str, object]) -> dict:
    if len(samples) != SAMPLE_STATES:
        raise CapacityRefused("capacity projection sample count drift")
    by_shard: dict[int, list[Mapping[str, object]]] = {
        index: [] for index in range(CTRL.LABEL_SHARDS)}
    max_load = 0.0
    for sample in samples:
        shard = sample.get("shard_index")
        if isinstance(shard, bool) or not isinstance(shard, int) \
                or shard not in by_shard:
            raise CapacityRefused("capacity projection shard index drift")
        if (sample.get("status") != "COMPLETE_OUTCOMES_DISCARDED"
                or sample.get("candidate_worlds_attempted")
                != sample.get("expected_candidate_worlds")
                or sample.get("candidate_worlds_completed")
                != sample.get("expected_candidate_worlds")):
            raise CapacityRefused("capacity projection received incomplete sample")
        elapsed = sample.get("elapsed_seconds")
        load = sample.get("v11_load_seconds")
        if (isinstance(elapsed, bool) or not isinstance(elapsed, (int, float))
                or not math.isfinite(float(elapsed)) or float(elapsed) <= 0
                or isinstance(load, bool) or not isinstance(load, (int, float))
                or not math.isfinite(float(load)) or float(load) <= 0):
            raise CapacityRefused("capacity projection timing drift")
        by_shard[shard].append(sample)
        max_load = max(max_load, float(load))
    if any(len(values) != SAMPLES_PER_SHARD for values in by_shard.values()):
        raise CapacityRefused("capacity projection per-shard geometry drift")
    projected_shards = []
    for shard in label_schedule["shards"]:
        rates = [float(sample["elapsed_seconds"])
                 / int(sample["candidate_worlds_completed"])
                 for sample in by_shard[shard["index"]]]
        seconds = (max(rates) * int(shard["candidate_worlds"]) + max_load) \
            * THROUGHPUT_SAFETY_FACTOR
        projected_shards.append({
            "shard_index": shard["index"],
            "split": shard["split"],
            "projected_seconds": seconds,
            "projected_hours": seconds / 3_600.0,
        })
    # Predeclare a reproducible eight-worker longest-processing-time schedule.
    assignments = [{"worker": index, "shards": [], "seconds": 0.0}
                   for index in range(WORKERS)]
    for shard in sorted(
            projected_shards,
            key=lambda value: (-float(value["projected_seconds"]),
                               int(value["shard_index"]))):
        target = min(assignments, key=lambda value: (
            float(value["seconds"]), int(value["worker"])))
        target["shards"].append(shard["shard_index"])
        target["seconds"] += float(shard["projected_seconds"])
    fleet_seconds = sum(float(value["projected_seconds"])
                        for value in projected_shards)
    max_shard_seconds = max(float(value["projected_seconds"])
                            for value in projected_shards)
    wall_seconds = max(float(value["seconds"]) for value in assignments)
    return {
        "throughput_safety_factor": THROUGHPUT_SAFETY_FACTOR,
        "max_observed_v11_load_seconds": max_load,
        "shards": sorted(projected_shards,
                         key=lambda value: int(value["shard_index"])),
        "eight_worker_lpt_assignment": [{
            "worker": value["worker"],
            "shards": value["shards"],
            "projected_hours": value["seconds"] / 3_600.0,
        } for value in assignments],
        "projected_fleet_hours": fleet_seconds / 3_600.0,
        "projected_max_shard_hours": max_shard_seconds / 3_600.0,
        "projected_eight_worker_wall_hours": wall_seconds / 3_600.0,
    }


def _capacity_problems(samples: Sequence[Mapping[str, object]],
                       projection: Mapping[str, object],
                       elapsed_seconds: float) -> list[str]:
    problems = []
    if len(samples) != SAMPLE_STATES:
        problems.append("sample count incomplete")
    if any(sample.get("status") != "COMPLETE_OUTCOMES_DISCARDED"
           for sample in samples):
        problems.append("one or more sample states refused")
    if any(sample.get("candidate_worlds_attempted")
           != sample.get("expected_candidate_worlds")
           or sample.get("candidate_worlds_completed")
           != sample.get("expected_candidate_worlds") for sample in samples):
        problems.append("sample candidate-world work is inexact")
    if elapsed_seconds > MAX_PREFLIGHT_WALL_HOURS * 3_600:
        problems.append("preflight wall-time ceiling exceeded")
    if float(projection["projected_fleet_hours"]) \
            > MAX_PROJECTED_FLEET_HOURS:
        problems.append("projected fleet-hour ceiling exceeded")
    if float(projection["projected_max_shard_hours"]) \
            > MAX_PROJECTED_SHARD_HOURS:
        problems.append("projected shard-hour ceiling exceeded")
    if float(projection["projected_eight_worker_wall_hours"]) \
            > MAX_PROJECTED_EIGHT_WORKER_WALL_HOURS:
        problems.append("projected eight-worker wall ceiling exceeded")
    if forbidden_outcome_paths(samples):
        problems.append("durable sample telemetry leaked outcomes")
    return sorted(set(problems))


def _result_payload(packet: Mapping[str, object], packet_sha256: str,
                    admission_sha256: str, samples: Sequence[dict],
                    elapsed_seconds: float, *, terminal_problem: str | None = None
                    ) -> dict:
    if terminal_problem is None:
        raise AssertionError("_result_payload requires caller projection")
    payload = {
        "schema": RESULT_SCHEMA,
        "run_id": RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "controller_review_claim_sha256": sha256_bytes(canonical_json(
            expected_packet_review_claim(packet, packet_sha256))),
        "state_set_sha256": packet["parents"]["state_set"]["external_sha256"],
        "preflight_schedule_sha256": packet[
            "preflight_schedule"]["schedule_sha256"],
        "admission_file_sha256": admission_sha256,
        "status": "TERMINAL_HOLD_NO_RETRY",
        "complete_samples": len(samples),
        "refused_samples": sum(
            sample.get("status") != "COMPLETE_OUTCOMES_DISCARDED"
            for sample in samples),
        "samples": list(samples),
        "elapsed_seconds": elapsed_seconds,
        "terminal_problem_sha256": sha256_bytes(terminal_problem.encode()),
        "outcomes_computed_in_ephemeral_workers": bool(samples),
        "outcomes_returned_by_workers": False,
        "outcomes_retained": False,
        "capacity_pass": False,
        "label_controller_freeze_authorized": False,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    forbidden = forbidden_outcome_paths(payload)
    if forbidden:
        raise CapacityRefused(
            "terminal capacity result leaked outcomes: " + ",".join(forbidden))
    payload["result_sha256"] = self_hash(payload, "result_sha256")
    return payload


def build_pass_or_hold_result(
    packet: Mapping[str, object], packet_sha256: str,
    admission_sha256: str, samples: Sequence[dict], elapsed_seconds: float,
    label_schedule: Mapping[str, object],
) -> dict:
    projection = capacity_projection(samples, label_schedule)
    problems = _capacity_problems(samples, projection, elapsed_seconds)
    work = {
        "candidate_worlds_attempted": sum(
            int(sample["candidate_worlds_attempted"]) for sample in samples),
        "candidate_worlds_completed": sum(
            int(sample["candidate_worlds_completed"]) for sample in samples),
        "sampler_attempts": sum(
            int(sample["sampler"]["sampler_attempts"]) for sample in samples),
        "accepted_worlds": sum(
            int(sample["sampler"]["accepted_worlds"]) for sample in samples),
    }
    passed = not problems
    payload = {
        "schema": RESULT_SCHEMA,
        "run_id": RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "controller_review_claim_sha256": sha256_bytes(canonical_json(
            expected_packet_review_claim(packet, packet_sha256))),
        "state_set_sha256": packet["parents"]["state_set"]["external_sha256"],
        "label_schedule_sha256": packet["label_schedule"]["schedule_sha256"],
        "preflight_schedule_sha256": packet[
            "preflight_schedule"]["schedule_sha256"],
        "admission_file_sha256": admission_sha256,
        "status": ("AUTHORIZE_LABEL_CONTROLLER_PACKET_REVIEW" if passed
                   else "TERMINAL_HOLD_NO_RETRY"),
        "complete_samples": sum(
            sample["status"] == "COMPLETE_OUTCOMES_DISCARDED"
            for sample in samples),
        "refused_samples": sum(
            sample["status"] != "COMPLETE_OUTCOMES_DISCARDED"
            for sample in samples),
        "samples": sorted(samples, key=lambda value: (
            int(value["shard_index"]), str(value["sample_role"]))),
        "work": work,
        "elapsed_seconds": elapsed_seconds,
        "projection": projection,
        "capacity_problems": problems,
        "outcomes_computed_in_ephemeral_workers": True,
        "outcomes_returned_by_workers": False,
        "outcomes_retained": False,
        "capacity_pass": passed,
        "label_controller_freeze_authorized": passed,
        "labels_authorized": False,
        "training_authorized": False,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    forbidden = forbidden_outcome_paths(payload)
    if forbidden:
        raise CapacityRefused(
            "capacity result leaked forbidden outcomes: " + ",".join(forbidden))
    payload["result_sha256"] = self_hash(payload, "result_sha256")
    return payload


def expected_result_review_claim(result: Mapping[str, object],
                                 result_external_sha256: str) -> dict:
    projection = result["projection"]
    return {
        "schema": RESULT_REVIEW_SCHEMA,
        "git": result["git"],
        "controller_packet_sha256": result["controller_packet_sha256"],
        "controller_review_claim_sha256": result[
            "controller_review_claim_sha256"],
        "result_sha256": result_external_sha256,
        "result_internal_sha256": result["result_sha256"],
        "state_set_sha256": result["state_set_sha256"],
        "label_schedule_sha256": result["label_schedule_sha256"],
        "preflight_schedule_sha256": result["preflight_schedule_sha256"],
        "complete_samples": SAMPLE_STATES,
        "refused_samples": 0,
        "projected_fleet_hours": projection["projected_fleet_hours"],
        "projected_max_shard_hours": projection[
            "projected_max_shard_hours"],
        "projected_eight_worker_wall_hours": projection[
            "projected_eight_worker_wall_hours"],
        "outcomes_returned_by_workers": False,
        "outcomes_retained": False,
        "capacity_pass": True,
        "independent_review": True,
        "label_controller_freeze_authorized": True,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def validate_pass_result_semantics(
    result: Mapping[str, object], packet: Mapping[str, object],
    state_set: Mapping[str, object],
) -> None:
    samples = result.get("samples")
    if not isinstance(samples, list) or len(samples) != SAMPLE_STATES:
        raise CapacityRefused("capacity-result sample population drift")
    expected_samples = packet["preflight_schedule"]["samples"]
    descriptor_fields = set(expected_samples[0])
    observed_descriptors = []
    for sample in samples:
        if not isinstance(sample, dict) or set(sample) != SAMPLE_TELEMETRY_FIELDS:
            raise CapacityRefused("capacity-result sample field drift")
        sampler = sample.get("sampler")
        if (not isinstance(sampler, dict)
                or set(sampler) != SAMPLER_TELEMETRY_FIELDS
                or not all(isinstance(value, int) and not isinstance(value, bool)
                           and value >= 0 for value in sampler.values())
                or sampler["accepted_worlds"]
                + sampler["failed_worlds"] != sampler["sampler_attempts"]
                or sampler["unique_worlds_within_folds"]
                + sampler["duplicate_draws_retained"]
                != sampler["accepted_worlds"]
                or sampler["prior_fold_overlap_draws_retained"]
                > sampler["accepted_worlds"]
                or sampler["rejected_worlds"] > sampler["failed_worlds"]
                or sample.get("reason_class") is not None
                or sample.get("reason_sha256") is not None
                or sample.get("outcome_tensor_returned") is not False
                or sample.get("outcomes_retained") is not False):
            raise CapacityRefused("capacity-result safe telemetry drift")
        observed_descriptors.append({
            key: sample[key] for key in descriptor_fields
        })
    if sorted(observed_descriptors, key=lambda value: (
            int(value["shard_index"]), str(value["sample_role"]))) \
            != expected_samples:
        raise CapacityRefused("capacity-result sample identity drift")
    label_schedule = CTRL.build_schedule(state_set)
    projection = capacity_projection(samples, label_schedule)
    elapsed = result.get("elapsed_seconds")
    if (isinstance(elapsed, bool) or not isinstance(elapsed, (int, float))
            or not math.isfinite(float(elapsed)) or float(elapsed) <= 0
            or result.get("projection") != projection
            or result.get("capacity_problems")
            != _capacity_problems(samples, projection, float(elapsed))):
        raise CapacityRefused("capacity-result projection/gate drift")
    expected_work = {
        "candidate_worlds_attempted": sum(
            int(sample["candidate_worlds_attempted"]) for sample in samples),
        "candidate_worlds_completed": sum(
            int(sample["candidate_worlds_completed"]) for sample in samples),
        "sampler_attempts": sum(
            int(sample["sampler"]["sampler_attempts"]) for sample in samples),
        "accepted_worlds": sum(
            int(sample["sampler"]["accepted_worlds"]) for sample in samples),
    }
    if (result.get("work") != expected_work
            or expected_work["candidate_worlds_attempted"]
            != packet["preflight_schedule"]["sample_candidate_worlds"]
            or expected_work["candidate_worlds_completed"]
            != packet["preflight_schedule"]["sample_candidate_worlds"]):
        raise CapacityRefused("capacity-result aggregate work drift")


def validate_result(result_path: Path, expected_result_sha256: str,
                    packet: Mapping[str, object], packet_sha256: str,
                    state_set: Mapping[str, object]) -> dict:
    if sha256_file(result_path) != expected_result_sha256:
        raise CapacityRefused("capacity-result external SHA-256 drift")
    result = load_json(result_path)
    if (result.get("schema") != RESULT_SCHEMA
            or result.get("run_id") != RUN_ID
            or result.get("git") != packet["producer"]["git"]
            or result.get("controller_packet_sha256") != packet_sha256
            or result.get("controller_review_claim_sha256")
            != sha256_bytes(canonical_json(
                expected_packet_review_claim(packet, packet_sha256)))
            or result.get("state_set_sha256")
            != packet["parents"]["state_set"]["external_sha256"]
            or result.get("label_schedule_sha256")
            != packet["label_schedule"]["schedule_sha256"]
            or result.get("preflight_schedule_sha256")
            != packet["preflight_schedule"]["schedule_sha256"]
            or result.get("result_sha256") != self_hash(result, "result_sha256")
            or result.get("status")
            != "AUTHORIZE_LABEL_CONTROLLER_PACKET_REVIEW"
            or result.get("complete_samples") != SAMPLE_STATES
            or result.get("refused_samples") != 0
            or result.get("capacity_problems") != []
            or result.get("outcomes_computed_in_ephemeral_workers") is not True
            or result.get("outcomes_returned_by_workers") is not False
            or result.get("outcomes_retained") is not False
            or not _is_sha256(result.get("admission_file_sha256"))
            or result.get("capacity_pass") is not True
            or result.get("label_controller_freeze_authorized") is not True
            or result.get("labels_authorized") is not False
            or result.get("training_authorized") is not False
            or forbidden_outcome_paths(result)):
        raise CapacityRefused("capacity-result identity/authority drift")
    validate_pass_result_semantics(result, packet, state_set)
    return result


def validate_result_review(review_path: Path, result: Mapping[str, object],
                           result_external_sha256: str) -> dict:
    claim = marker_claim(review_path, RESULT_REVIEW_MARKER)
    if claim != expected_result_review_claim(result, result_external_sha256):
        raise CapacityRefused("capacity-result PASS marker drift")
    return claim


def _consume_admission(packet: Mapping[str, object], packet_sha256: str,
                       review: Mapping[str, object]) -> str:
    slot = REPO / admission_slot_logical_path()
    slot.parent.mkdir(parents=True, exist_ok=True)
    value = {
        "schema": ADMISSION_SCHEMA,
        "run_id": RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "controller_review_claim_sha256": sha256_bytes(canonical_json(review)),
        "retry_or_extension_authorized": False,
    }
    value["admission_sha256"] = self_hash(value, "admission_sha256")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(slot, flags, 0o600)
    except FileExistsError as exc:
        raise CapacityRefused("capacity execution admission already consumed") from exc
    with os.fdopen(fd, "wb") as handle:
        handle.write(canonical_json(value))
        handle.flush()
        os.fsync(handle.fileno())
    return sha256_file(slot)


def run_capacity(
    packet_path: Path, expected_packet_sha256: str,
    controller_review_record: Path, state_set_review_record: Path,
    out: Path,
) -> dict:
    packet, state_set, review = _reopen_packet(
        packet_path, expected_packet_sha256,
        controller_review_record, state_set_review_record)
    if out.resolve() != (REPO / RESULT_PATH).resolve():
        raise CapacityRefused("real capacity-result path drift")
    if os.path.lexists(out) or os.path.lexists(Path(str(out) + ".partial")):
        raise CapacityRefused("capacity-result namespace already exists")
    admission_sha256 = _consume_admission(
        packet, expected_packet_sha256, review)
    states = {str(state["state_id"]): state for state in state_set["states"]}
    tasks = [(dict(sample), states[str(sample["state_id"])])
             for sample in packet["preflight_schedule"]["samples"]]
    started = time.monotonic()
    samples: list[dict] = []
    context = multiprocessing.get_context("spawn")
    pool = context.Pool(processes=WORKERS, initializer=_worker_init)
    try:
        iterator = pool.imap_unordered(_run_sample, tasks, chunksize=1)
        while len(samples) < len(tasks):
            remaining = MAX_PREFLIGHT_WALL_HOURS * 3_600 \
                - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError("capacity preflight wall-time ceiling")
            try:
                sample = iterator.next(timeout=min(HEARTBEAT_SECONDS, remaining))
            except multiprocessing.TimeoutError:
                print(json.dumps({
                    "status": "CAPACITY_HEARTBEAT",
                    "samples_complete": len(samples),
                    "samples_total": len(tasks),
                    "elapsed_seconds": time.monotonic() - started,
                    "outcomes_retained": False,
                }, sort_keys=True), file=sys.stderr, flush=True)
                continue
            samples.append(sample)
            print(json.dumps({
                "status": "CAPACITY_RUNNING",
                "samples_complete": len(samples),
                "samples_total": len(tasks),
                "candidate_worlds_completed": sum(
                    int(value["candidate_worlds_completed"])
                    for value in samples),
                "refusals": sum(
                    value["status"] != "COMPLETE_OUTCOMES_DISCARDED"
                    for value in samples),
                "elapsed_seconds": time.monotonic() - started,
                "outcomes_retained": False,
            }, sort_keys=True), file=sys.stderr, flush=True)
        pool.close()
        pool.join()
        _require_postcompute_identity(
            packet_path, expected_packet_sha256,
            controller_review_record, state_set_review_record,
            packet, state_set, review)
        label_schedule = CTRL.build_schedule(state_set)
        result = build_pass_or_hold_result(
            packet, expected_packet_sha256, admission_sha256,
            samples, time.monotonic() - started, label_schedule)
    except BaseException as exc:
        pool.terminate()
        pool.join()
        result = _result_payload(
            packet, expected_packet_sha256, admission_sha256,
            samples, time.monotonic() - started,
            terminal_problem=f"{type(exc).__name__}:{exc}")
    CTRL.publish_exclusive(out, result)
    return result


def publish_exclusive(path: Path, value: Mapping[str, object]) -> None:
    CTRL.publish_exclusive(path, value)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("freeze", "verify"):
        child = commands.add_parser(name)
        child.add_argument("--capture-controller", required=True)
        child.add_argument("--state-set", required=True)
        child.add_argument("--expected-state-set-sha256", required=True)
        child.add_argument("--capture-verification", required=True)
        child.add_argument("--expected-capture-verification-sha256", required=True)
        child.add_argument("--state-set-review-record", required=True)
        child.add_argument("--out", required=True)
        if name == "freeze":
            child.add_argument("--smoke", action="store_true")
        else:
            child.add_argument("--expected-packet-sha256", required=True)
    run = commands.add_parser("run")
    run.add_argument("--controller-packet", required=True)
    run.add_argument("--expected-controller-packet-sha256", required=True)
    run.add_argument("--controller-review-record", required=True)
    run.add_argument("--state-set-review-record", required=True)
    run.add_argument("--out", required=True)
    result = commands.add_parser("verify-result")
    result.add_argument("--controller-packet", required=True)
    result.add_argument("--expected-controller-packet-sha256", required=True)
    result.add_argument("--controller-review-record", required=True)
    result.add_argument("--state-set-review-record", required=True)
    result.add_argument("--result", required=True)
    result.add_argument("--expected-result-sha256", required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command in {"freeze", "verify"}:
        packet = build_packet(
            Path(args.capture_controller).resolve(),
            Path(args.state_set).resolve(), args.expected_state_set_sha256,
            Path(args.capture_verification).resolve(),
            args.expected_capture_verification_sha256,
            Path(args.state_set_review_record).resolve(),
            smoke=bool(getattr(args, "smoke", False)))
        out = Path(args.out).resolve()
        if args.command == "freeze":
            if out != (REPO / PACKET_PATH).resolve() and not args.smoke:
                raise CapacityRefused("real capacity-controller path drift")
            publish_exclusive(out, packet)
        elif (not is_regular_unlinked(out)
              or sha256_file(out) != args.expected_packet_sha256
              or load_json(out) != packet):
            raise CapacityRefused("capacity-controller verification drift")
        external = sha256_file(out)
        print(json.dumps({
            "status": "FROZEN" if args.command == "freeze" else "VERIFIED",
            "path": str(out),
            "sha256": external,
            "review_marker": PACKET_REVIEW_MARKER + json.dumps(
                expected_packet_review_claim(packet, external),
                sort_keys=True, separators=(",", ":")),
            "outcomes_computed": False,
        }, sort_keys=True))
        return 0
    if args.command == "run":
        result = run_capacity(
            Path(args.controller_packet).resolve(),
            args.expected_controller_packet_sha256,
            Path(args.controller_review_record).resolve(),
            Path(args.state_set_review_record).resolve(),
            Path(args.out).resolve())
        external = sha256_file(Path(args.out).resolve())
        output = {
            "status": result["status"],
            "path": str(Path(args.out).resolve()),
            "sha256": external,
            "capacity_pass": result["capacity_pass"],
            "outcomes_retained": False,
        }
        if result["capacity_pass"]:
            output["review_marker"] = RESULT_REVIEW_MARKER + json.dumps(
                expected_result_review_claim(result, external),
                sort_keys=True, separators=(",", ":"))
        print(json.dumps(output, sort_keys=True))
        return 0 if result["capacity_pass"] else 4
    packet, states, _review = _reopen_packet(
        Path(args.controller_packet).resolve(),
        args.expected_controller_packet_sha256,
        Path(args.controller_review_record).resolve(),
        Path(args.state_set_review_record).resolve())
    result = validate_result(
        Path(args.result).resolve(), args.expected_result_sha256,
        packet, args.expected_controller_packet_sha256, states)
    print(json.dumps({
        "status": "VERIFIED_CAPACITY_PASS",
        "sha256": args.expected_result_sha256,
        "review_marker": RESULT_REVIEW_MARKER + json.dumps(
            expected_result_review_claim(result, args.expected_result_sha256),
            sort_keys=True, separators=(",", ":")),
        "outcomes_retained": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CapacityRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2)

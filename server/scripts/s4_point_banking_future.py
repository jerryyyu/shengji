#!/usr/bin/env python3
"""Future-only two-look confirmation runtime for S4 point banking.

The reviewed design spends no historical outcome in its estimator.  Treatment
and the exact live champion run on every fresh cluster; an exact matched-null
sentinel runs on a deterministic one-in-eight subset.  Look 1 consumes exactly
8,192 clusters.  A clean efficacy nonpass mechanically unlocks the already
pre-authorized second tranche; no human can change the population, statistic,
or stopping rule after looking.  Integrity failure always stops HOLD.

This module owns deterministic schedules, shard validation, score-free capacity
measurement, and cumulative aggregation.  The companion Cloud controller owns
review admission, process supervision, and the automatic transition.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
import sys
import time
from collections import Counter
from pathlib import Path

SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import s4_point_banking_duel as DUEL  # noqa: E402
import s4_point_banking_future_design as DESIGN  # noqa: E402

SCHEMA = "s4-point-banking-future-shard-v1"
AGGREGATE_SCHEMA = "s4-point-banking-future-aggregate-v1"
VALIDATION_SCHEMA = "s4-point-banking-future-runtime-validation-v1"
PREFLIGHT_SCHEMA = "s4-point-banking-future-preflight-v1"
PACKET_SCHEMA = "s4-point-banking-future-cloud-packet-v1"
PACKET_REVIEW_SCHEMA = "s4-point-banking-future-cloud-review-v1"
PACKET_REVIEW_MARKER = "S4_POINT_BANKING_FUTURE_CLOUD_V1_REVIEW "
ADMISSION_SCHEMA = "s4-point-banking-future-cloud-admission-v1"
RECEIPT_SCHEMA = "s4-point-banking-future-cloud-receipt-v1"
DESIGN_REVIEW_GIT = "182459941226b96969e2c2b207406cf5b53167ab"

RUN_ID = DESIGN.RUN_ID
NAMESPACE = Path("server/runs/logs") / RUN_ID
RUNNER_PATH = Path("server/scripts/s4_point_banking_future.py")
CONTROLLER_PATH = Path("server/scripts/s4_point_banking_future_cloud.py")
SEED0 = DESIGN.SCREEN_SEED0
LOOK_CLUSTERS = tuple(look.clusters for look in DESIGN.Design().looks)
LOOK1_CLUSTERS, MAX_CLUSTERS = LOOK_CLUSTERS
TRANCHE_COUNT = len(LOOK_CLUSTERS)
SHARD_COUNT = DESIGN.SHARD_COUNT
CLUSTERS_PER_SHARD = MAX_CLUSTERS // SHARD_COUNT
TRANCHE_CLUSTERS_PER_SHARD = LOOK1_CLUSTERS // SHARD_COUNT
NULL_SENTINEL_STRIDE = DESIGN.NULL_SENTINEL_MODULUS
NULL_SENTINEL_CLUSTERS = MAX_CLUSTERS // NULL_SENTINEL_STRIDE
PRIMARY_LABELS = ("treatment", "champion")
SHARD_NAMES = tuple(
    f"tranche-{tranche}-shard-{index:02d}.json"
    for tranche in range(1, TRANCHE_COUNT + 1)
    for index in range(SHARD_COUNT))
AGGREGATE_NAMES = ("look-1-aggregate.json", "look-2-aggregate.json")

PREFLIGHT_RUN_ID = "s4-point-banking-future-cloud-preflight-239b-v1"
PREFLIGHT_NAMESPACE = Path("server/runs/logs") / PREFLIGHT_RUN_ID
PREFLIGHT_RESULT_PATH = PREFLIGHT_NAMESPACE / "preflight.json"
PREFLIGHT_REVIEW_PATH = PREFLIGHT_NAMESPACE / "controller-review.txt"
PREFLIGHT_ADMISSION_PATH = PREFLIGHT_NAMESPACE / "preflight-admission.json"
PREFLIGHT_SEED0 = DESIGN.PREFLIGHT_SEED0
PREFLIGHT_CLUSTERS = DESIGN.PREFLIGHT_CLUSTERS
THROUGHPUT_SAFETY_FACTOR = 2.0
MAX_PROJECTED_FLEET_HOURS = 768.0
MAX_PROJECTED_SHARD_HOURS = 96.0

CLAIM_BOUNDARY = (
    "One future-only two-look complete-round confirmation of frozen S4 versus "
    "exact live report-LCB. Historical outcomes are planning-only. Matched "
    "null is an identity sentinel, not an efficacy arm. No retry, parameter "
    "change, promotion, deployment, or discretionary continuation."
)
DESIGN_RECORD = json.loads(json.dumps(
    DESIGN.design_record(), sort_keys=True, separators=(",", ":")))
SELECTION_RULE = DESIGN.PRIMARY_EFFICACY
LOOK1_TRANSITION = DESIGN_RECORD["look_1_transition"]
FINAL_TRANSITION = DESIGN_RECORD["final_transition"]
PACKET_EXTRA_FIELDS: frozenset[str] = frozenset()
DESIGN_REVIEW_EXTRA: dict[str, object] = {}


class ProtocolRefused(RuntimeError):
    """The requested artifact cannot support the registered claim."""


def sha256(path: os.PathLike | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_digest(value: object) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=list,
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def json_copy(value):
    return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))


def is_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def require_regular_unlinked(path: Path, *, label: str) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise ProtocolRefused(f"{label} is missing") from exc
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or os.path.lexists(Path(str(path) + ".partial"))):
        raise ProtocolRefused(f"{label} is linked, nonregular, or partial")


def write_exclusive(path: os.PathLike | str, payload: dict) -> None:
    try:
        DUEL.write_exclusive(path, payload)
    except DUEL.ProtocolRefused as exc:
        raise ProtocolRefused(str(exc)) from exc


def cluster_seed(cluster_index: int, *, preflight: bool = False) -> int:
    total = PREFLIGHT_CLUSTERS if preflight else MAX_CLUSTERS
    seed0 = PREFLIGHT_SEED0 if preflight else SEED0
    if not 0 <= cluster_index < total:
        raise ProtocolRefused("cluster index outside registered population")
    return seed0 + DUEL.STREAM_STRIDE * cluster_index


def tranche_bounds(tranche: int) -> tuple[int, int]:
    if tranche == 1:
        return 0, LOOK1_CLUSTERS
    if tranche == 2:
        return LOOK1_CLUSTERS, MAX_CLUSTERS
    raise ProtocolRefused("tranche must be 1 or 2")


def shard_indexes(shard_index: int, *, tranche: int | None = None) -> list[int]:
    if not 0 <= shard_index < SHARD_COUNT:
        raise ProtocolRefused("shard index outside registered population")
    start, stop = ((0, MAX_CLUSTERS) if tranche is None
                   else tranche_bounds(tranche))
    return list(range(start + shard_index, stop, SHARD_COUNT))


def is_null_sentinel(cluster_index: int) -> bool:
    if not 0 <= cluster_index < MAX_CLUSTERS:
        raise ProtocolRefused("sentinel index outside registered population")
    # Every shard contributes exactly one sentinel per eight local clusters.
    return (cluster_index // SHARD_COUNT) % NULL_SENTINEL_STRIDE == 0


def labels_for_cluster(cluster_index: int) -> tuple[str, ...]:
    return ("treatment", "matched_null", "champion") \
        if is_null_sentinel(cluster_index) else PRIMARY_LABELS


def preflight_labels(cluster_index: int) -> tuple[str, ...]:
    # One full sentinel cluster proves treatment/null/champion wiring while
    # all four clusters estimate the expensive primary workload.
    return ("treatment", "matched_null", "champion") \
        if cluster_index == 0 else PRIMARY_LABELS


def sentinel_indexes(*, clusters: int | None = None) -> list[int]:
    clusters = MAX_CLUSTERS if clusters is None else clusters
    if clusters not in LOOK_CLUSTERS:
        raise ProtocolRefused("sentinel population must end at a frozen look")
    return [index for index in range(clusters) if is_null_sentinel(index)]


def schedule() -> dict:
    per_tranche = {
        str(tranche): [shard_indexes(index, tranche=tranche)
                       for index in range(SHARD_COUNT)]
        for tranche in range(1, TRANCHE_COUNT + 1)
    }
    sentinels = sentinel_indexes()
    return {
        "run_id": RUN_ID,
        "seed0": SEED0,
        "stream_stride": DUEL.STREAM_STRIDE,
        "looks": list(LOOK_CLUSTERS),
        "maximum_clusters": MAX_CLUSTERS,
        "tranche_clusters": LOOK1_CLUSTERS,
        "shard_count": SHARD_COUNT,
        "clusters_per_shard": CLUSTERS_PER_SHARD,
        "tranche_clusters_per_shard": TRANCHE_CLUSTERS_PER_SHARD,
        "primary_labels": list(PRIMARY_LABELS),
        "null_sentinel_stride": NULL_SENTINEL_STRIDE,
        "null_sentinel_clusters": NULL_SENTINEL_CLUSTERS,
        "null_sentinel_indexes_sha256": stable_digest(sentinels),
        "per_tranche_shard_indexes_sha256": {
            tranche: [stable_digest(value) for value in populations]
            for tranche, populations in per_tranche.items()
        },
        "maximum_records": (MAX_CLUSTERS * len(PRIMARY_LABELS) * 2
                            + NULL_SENTINEL_CLUSTERS * 2),
        "design": json_copy(DESIGN_RECORD),
        "look_1_transition": dict(LOOK1_TRANSITION),
        "final_transition": dict(FINAL_TRANSITION),
        "selection_rule": SELECTION_RULE,
        "claim_boundary": CLAIM_BOUNDARY,
    }


def shard_position(tranche: int, shard_index: int) -> int:
    tranche_bounds(tranche)
    if not 0 <= shard_index < SHARD_COUNT:
        raise ProtocolRefused("shard index outside registered population")
    return (tranche - 1) * SHARD_COUNT + shard_index


def command_template(tranche: int, shard_index: int) -> list[str]:
    position = shard_position(tranche, shard_index)
    return [
        "{python}", str(RUNNER_PATH), "run",
        "--expected-git", "{git}",
        "--tranche", str(tranche),
        "--shard-index", str(shard_index),
        "--progress-every", "1",
        "--execution-receipt", str(NAMESPACE / "receipt.json"),
        "--expected-execution-receipt-sha256", "{execution_receipt_sha256}",
        "--out", str(NAMESPACE / SHARD_NAMES[position]),
    ]


def aggregate_template(look: int) -> list[str]:
    if look not in (1, 2):
        raise ProtocolRefused("aggregate look outside frozen contract")
    return [
        "{python}", str(RUNNER_PATH), "aggregate",
        "--expected-git", "{git}",
        "--look", str(look),
        "--shards", *[str(NAMESPACE / name)
                       for name in SHARD_NAMES[:look * SHARD_COUNT]],
        "--execution-receipt", str(NAMESPACE / "receipt.json"),
        "--expected-execution-receipt-sha256", "{execution_receipt_sha256}",
        "--out", str(NAMESPACE / AGGREGATE_NAMES[look - 1]),
    ]


def runtime_validation_template() -> list[str]:
    return [
        "{python}", str(RUNNER_PATH), "validate-runtime",
        "--expected-git", "{git}",
        "--execution-receipt", str(NAMESPACE / "receipt.json"),
        "--expected-execution-receipt-sha256",
        "{execution_receipt_sha256}",
    ]


def tranche_contract() -> list[dict]:
    tranches = []
    for tranche in range(1, TRANCHE_COUNT + 1):
        jobs = []
        for index in range(SHARD_COUNT):
            position = shard_position(tranche, index)
            indexes = shard_indexes(index, tranche=tranche)
            jobs.append({
                "name": f"tranche-{tranche}-shard-{index:02d}",
                "command_template": command_template(tranche, index),
                "output": str(NAMESPACE / SHARD_NAMES[position]),
                "clusters": len(indexes),
                "null_sentinel_clusters": sum(
                    is_null_sentinel(value) for value in indexes),
            })
        tranches.append({
            "tranche": tranche,
            "jobs": jobs,
            "aggregate_command_template": aggregate_template(tranche),
            "aggregate_output": str(NAMESPACE / AGGREGATE_NAMES[tranche - 1]),
            "execution_gate": (
                "reviewed_packet_admission" if tranche == 1
                else "look_1_status_exactly_CONTINUE_AUTOMATICALLY"),
        })
    return tranches


def _stream_uses(seed0: int, clusters: int) -> list[tuple[int, int, str]]:
    return DUEL._stream_uses(seed0, clusters)


def stream_problems() -> list[str]:
    populations = {
        "future_preflight": _stream_uses(
            PREFLIGHT_SEED0, PREFLIGHT_CLUSTERS),
        "future_primary": _stream_uses(SEED0, MAX_CLUSTERS),
        "old_preflight": _stream_uses(
            DUEL.PREFLIGHT_SEED0, DUEL.PREFLIGHT_CLUSTERS),
        **{f"old_{phase}": _stream_uses(spec["seed0"], spec["clusters"])
           for phase, spec in DUEL.PHASES.items()},
    }
    by_seed: dict[int, list[tuple[str, int, str]]] = {}
    for population, uses in populations.items():
        for seed, cluster_index, role in uses:
            by_seed.setdefault(seed, []).append(
                (population, cluster_index, role))
    collisions = [
        f"global seed collision {seed}: {uses}"
        for seed, uses in by_seed.items() if len(uses) != 1
    ]
    return sorted(set(collisions + DESIGN.design_problems(DESIGN.Design())))


def require_runtime(expected_git: str) -> tuple[dict, dict]:
    try:
        parent, base = DUEL.require_runtime(
            expected_git, compatible_fast=True)
    except DUEL.ProtocolRefused as exc:
        raise ProtocolRefused(f"base S4 runtime refused: {exc}") from exc
    problems = stream_problems()
    if problems:
        raise ProtocolRefused("future S4 stream drift: " + "; ".join(problems))
    runtime = {
        **base,
        "future_runner_sha256": sha256(SCRIPT),
        "future_design_sha256": sha256(Path(DESIGN.__file__)),
        "future_schedule_sha256": stable_digest(schedule()),
    }
    return parent, runtime


def _load_json(path: Path, *, label: str) -> dict:
    require_regular_unlinked(path, label=label)
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ProtocolRefused(f"cannot reopen {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProtocolRefused(f"{label} is not an object")
    return value


def expected_receipt_fields() -> set[str]:
    return {
        "schema", "run_id", "complete", "git", "runner_sha256",
        "controller_sha256", "design_sha256", "created_time_ns", "nonce",
        "packet_sha256", "admission_sha256", "preflight_sha256",
        "design_review_sha256", "sequential_launch_authorized",
        "tranche_2_pre_authorized",
        "strength_claim", "training_authorized", "production_promotion",
        "retry_or_extension_authorized",
    }


def expected_review_claim(*, expected_git: str, packet_sha256: str,
                          preflight_sha256: str,
                          design_review_sha256: str) -> dict:
    return {
        "schema": PACKET_REVIEW_SCHEMA,
        "git": expected_git,
        "run_id": RUN_ID,
        "packet_sha256": packet_sha256,
        "preflight_sha256": preflight_sha256,
        "design_sha256": sha256(Path(DESIGN.__file__)),
        "design_review_sha256": design_review_sha256,
        "look_clusters": list(LOOK_CLUSTERS),
        "look_1_transition": dict(LOOK1_TRANSITION),
        "final_transition": dict(FINAL_TRANSITION),
        "independent_review": True,
        "sequential_launch_authorized": True,
        "tranche_2_pre_authorized": True,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def packet_profile_problems(packet: dict, *, expected_git: str,
                            receipt: dict,
                            current_runtime: dict) -> list[str]:
    """Validate fields added by a thin runtime profile.

    The base C1 packet has no profile-only fields. Successor adapters replace
    this hook after loading C1 in isolation; the child process therefore
    validates the same profile contract as its controller before gameplay.
    """
    del packet, expected_git, receipt, current_runtime
    return []


def require_receipt(path: Path, expected_sha256: str, *,
                    expected_git: str) -> dict:
    expected_path = (REPO / NAMESPACE / "receipt.json").resolve()
    if path.resolve() != expected_path:
        raise ProtocolRefused("future S4 receipt is not canonical")
    require_regular_unlinked(path, label="future S4 receipt")
    if not is_sha256(expected_sha256) or sha256(path) != expected_sha256:
        raise ProtocolRefused("future S4 receipt SHA-256 drift")
    receipt = _load_json(path, label="future S4 receipt")
    if (set(receipt) != expected_receipt_fields()
            or receipt.get("schema") != RECEIPT_SCHEMA
            or receipt.get("run_id") != RUN_ID
            or receipt.get("complete") is not True
            or receipt.get("git") != expected_git
            or receipt.get("runner_sha256") != sha256(SCRIPT)
            or not is_sha256(receipt.get("controller_sha256"))
            or receipt.get("design_sha256") != sha256(Path(DESIGN.__file__))
            or not is_sha256(receipt.get("nonce"))
            or not all(is_sha256(receipt.get(name)) for name in (
                "packet_sha256", "admission_sha256", "preflight_sha256",
                "design_review_sha256"))
            or receipt.get("sequential_launch_authorized") is not True
            or receipt.get("tranche_2_pre_authorized") is not True
            or receipt.get("strength_claim") is not False
            or receipt.get("training_authorized") is not False
            or receipt.get("production_promotion") is not False
            or receipt.get("retry_or_extension_authorized") is not False):
        raise ProtocolRefused("future S4 receipt authority/identity drift")
    created = receipt.get("created_time_ns")
    if isinstance(created, bool) or not isinstance(created, int) or created <= 0:
        raise ProtocolRefused("future S4 receipt creation time drift")

    namespace = REPO / NAMESPACE
    packet_path = namespace / "launch_packet.json"
    design_review_path = namespace / "design-review-record.txt"
    review_path = namespace / "review_record.txt"
    admission_path = namespace / "review_admission.json"
    for artifact, digest, label in (
            (packet_path, receipt["packet_sha256"], "future S4 packet"),
            (admission_path, receipt["admission_sha256"],
             "future S4 admission")):
        require_regular_unlinked(artifact, label=label)
        if sha256(artifact) != digest:
            raise ProtocolRefused(f"{label} SHA-256 drift")
    require_regular_unlinked(review_path, label="future S4 review record")
    require_regular_unlinked(
        design_review_path, label="future S4 design review record")
    if sha256(design_review_path) != receipt["design_review_sha256"]:
        raise ProtocolRefused("future S4 design review SHA-256 drift")
    packet = _load_json(packet_path, label="future S4 packet")
    admission = _load_json(admission_path, label="future S4 admission")
    try:
        review_text = review_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ProtocolRefused(f"cannot reopen future S4 review: {exc}") \
            from exc

    packet_fields = {
        "schema", "run_id", "git", "runner", "controller", "runtime",
        "parent", "design", "design_review", "score_free_preflight",
        "schedule", "namespace", "tranches", "heartbeat_seconds",
        "transition_table", "selection_rule", "claim_boundary",
        "packet_review_authorized", "sequential_launch_authorized",
        "tranche_2_pre_authorized", "strength_claim",
        "training_authorized", "production_promotion",
        "retry_or_extension_authorized",
    } | set(PACKET_EXTRA_FIELDS)
    runner = packet.get("runner") if isinstance(packet, dict) else None
    controller = packet.get("controller") if isinstance(packet, dict) else None
    preflight = (packet.get("score_free_preflight")
                 if isinstance(packet, dict) else None)
    try:
        parent, current_runtime = require_runtime(expected_git)
    except ProtocolRefused as exc:
        raise ProtocolRefused(
            f"cannot reopen receipt runtime: {exc}") from exc
    preflight_path = REPO / PREFLIGHT_RESULT_PATH
    require_regular_unlinked(preflight_path, label="future S4 preflight")
    controller_path = REPO / CONTROLLER_PATH
    require_regular_unlinked(controller_path, label="future S4 controller")
    expected_design_review = {
        "path": str(NAMESPACE / "design-review-record.txt"),
        "sha256": receipt["design_review_sha256"],
        "git": DESIGN_REVIEW_GIT,
        "verdict": "PASS_TO_IMPLEMENT",
        **DESIGN_REVIEW_EXTRA,
    }
    if (set(packet) != packet_fields
            or packet.get("schema") != PACKET_SCHEMA
            or packet.get("run_id") != RUN_ID
            or packet.get("git") != expected_git
            or runner != {
                "path": str(RUNNER_PATH),
                "sha256": sha256(SCRIPT),
            }
            or not isinstance(controller, dict)
            or controller.get("path") != str(CONTROLLER_PATH)
            or controller.get("sha256") != receipt["controller_sha256"]
            or sha256(controller_path) != receipt["controller_sha256"]
            or packet.get("runtime") != current_runtime
            or packet.get("parent") != parent
            or packet.get("design") != DESIGN_RECORD
            or packet.get("design_review") != expected_design_review
            or packet.get("schedule") != schedule()
            or packet.get("tranches") != tranche_contract()
            or packet.get("namespace") != str(NAMESPACE)
            or not isinstance(preflight, dict)
            or preflight.get("path") != str(PREFLIGHT_RESULT_PATH)
            or preflight.get("sha256") != receipt["preflight_sha256"]
            or sha256(preflight_path) != receipt["preflight_sha256"]
            or preflight.get("score_free") is not True
            or preflight.get("outcomes_published") is not False
            or packet.get("transition_table") != {
                "look_1": LOOK1_TRANSITION, "final": FINAL_TRANSITION}
            or packet.get("selection_rule") != SELECTION_RULE
            or packet.get("claim_boundary") != CLAIM_BOUNDARY
            or packet.get("packet_review_authorized") is not True
            or packet.get("sequential_launch_authorized") is not False
            or packet.get("tranche_2_pre_authorized") is not True
            or packet.get("strength_claim") is not False
            or packet.get("training_authorized") is not False
            or packet.get("production_promotion") is not False
            or packet.get("retry_or_extension_authorized") is not False
            or packet_profile_problems(
                packet, expected_git=expected_git, receipt=receipt,
                current_runtime=current_runtime)):
        raise ProtocolRefused("future S4 packet identity/authority drift")

    marker_matches = [
        line[len(PACKET_REVIEW_MARKER):]
        for line in review_text.splitlines()
        if line.startswith(PACKET_REVIEW_MARKER)
    ]
    if len(marker_matches) != 1:
        raise ProtocolRefused("future S4 review must contain one marker")
    try:
        review_claim = json.loads(marker_matches[0])
    except ValueError as exc:
        raise ProtocolRefused("future S4 review marker is invalid") from exc
    expected_claim = expected_review_claim(
        expected_git=expected_git,
        packet_sha256=receipt["packet_sha256"],
        preflight_sha256=receipt["preflight_sha256"],
        design_review_sha256=receipt["design_review_sha256"])
    expected_admission = {
        "schema": ADMISSION_SCHEMA,
        "run_id": RUN_ID,
        "packet": {"path": str(NAMESPACE / "launch_packet.json"),
                   "sha256": receipt["packet_sha256"]},
        "review": {"path": str(NAMESPACE / "review_record.txt"),
                   "sha256": sha256(review_path)},
        "review_claim": expected_claim,
        "operator_asserted_independent_review": True,
        "sequential_launch_authorized": True,
        "tranche_2_pre_authorized": True,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
    }
    if admission != expected_admission or review_claim != expected_claim:
        raise ProtocolRefused("future S4 review/admission authority drift")
    return {
        "path": str(path.resolve().relative_to(REPO.resolve())),
        "sha256": expected_sha256,
    }


def validate_runtime(args: argparse.Namespace) -> None:
    """Exercise the complete child identity boundary without gameplay."""
    require_runtime(args.expected_git)
    receipt = require_receipt(
        Path(args.execution_receipt),
        args.expected_execution_receipt_sha256,
        expected_git=args.expected_git,
    )
    print(json.dumps({
        "schema": VALIDATION_SCHEMA,
        "run_id": RUN_ID,
        "receipt": receipt,
        "validated": True,
        "outcomes_published": False,
    }, sort_keys=True, separators=(",", ":")))


def record_problems(record: object, *, expected_seed: int,
                    expected_label: str, expected_flip: int) -> list[str]:
    return DUEL.record_problems(
        record, phase="screen", expected_seed=expected_seed,
        expected_label=expected_label, expected_flip=expected_flip,
        expected_run_id=RUN_ID)


def shard_problems(payload: object, *, tranche: int, shard_index: int,
                   parent: dict, runtime: dict, receipt: dict) -> list[str]:
    if not isinstance(payload, dict):
        return ["shard is not an object"]
    expected_fields = {
        "schema", "complete", "run_id", "schedule", "tranche", "shard_index",
        "cluster_indexes", "parent", "runtime", "execution_receipt",
        "records", "strength_claim", "production_promotion",
        "retry_or_extension_authorized",
    }
    problems = []
    indexes = shard_indexes(shard_index, tranche=tranche)
    if (set(payload) != expected_fields
            or payload.get("schema") != SCHEMA
            or payload.get("complete") is not True
            or payload.get("run_id") != RUN_ID
            or payload.get("schedule") != schedule()
            or payload.get("tranche") != tranche
            or payload.get("shard_index") != shard_index
            or payload.get("cluster_indexes") != indexes
            or payload.get("parent") != parent
            or payload.get("runtime") != runtime
            or payload.get("execution_receipt") != receipt
            or payload.get("strength_claim") is not False
            or payload.get("production_promotion") is not False
            or payload.get("retry_or_extension_authorized") is not False):
        problems.append("shard identity")
    records = payload.get("records")
    expected_count = sum(len(labels_for_cluster(index)) * 2
                         for index in indexes)
    if not isinstance(records, list) or len(records) != expected_count:
        problems.append("shard record count")
        return sorted(set(problems))
    cursor = 0
    for cluster_index in indexes:
        seed = cluster_seed(cluster_index)
        for label in labels_for_cluster(cluster_index):
            for flip in (0, 1):
                problems.extend(
                    f"record {cursor}: {problem}"
                    for problem in record_problems(
                        records[cursor], expected_seed=seed,
                        expected_label=label, expected_flip=flip))
                cursor += 1
    return sorted(set(problems))


def run_shard(args: argparse.Namespace) -> None:
    parent, runtime = require_runtime(args.expected_git)
    receipt = require_receipt(
        Path(args.execution_receipt), args.expected_execution_receipt_sha256,
        expected_git=args.expected_git)
    expected_out = (REPO / NAMESPACE
                    / f"tranche-{args.tranche}-shard-"
                    f"{args.shard_index:02d}.json").resolve()
    if Path(args.out).resolve() != expected_out:
        raise ProtocolRefused("future S4 shard output is not canonical")
    indexes = shard_indexes(args.shard_index, tranche=args.tranche)
    records: list[dict] = []
    for local_index, cluster_index in enumerate(indexes, 1):
        seed = cluster_seed(cluster_index)
        for label in labels_for_cluster(cluster_index):
            records.extend(DUEL.play_arm_cluster(label, seed, run_id=RUN_ID))
        if args.progress_every and local_index % args.progress_every == 0:
            print(json.dumps({
                "event": "s4-point-banking-future-progress-v1",
                "tranche": args.tranche,
                "shard_index": args.shard_index,
                "clusters_complete": local_index,
                "clusters_total": len(indexes),
            }, sort_keys=True), flush=True)
    payload = {
        "schema": SCHEMA,
        "complete": True,
        "run_id": RUN_ID,
        "schedule": schedule(),
        "tranche": args.tranche,
        "shard_index": args.shard_index,
        "cluster_indexes": indexes,
        "parent": parent,
        "runtime": runtime,
        "execution_receipt": receipt,
        "records": records,
        "strength_claim": False,
        "production_promotion": False,
        "retry_or_extension_authorized": False,
    }
    problems = shard_problems(
        payload, tranche=args.tranche, shard_index=args.shard_index,
        parent=parent,
        runtime=runtime, receipt=receipt)
    if problems:
        raise ProtocolRefused("invalid future S4 shard: "
                              + "; ".join(problems))
    write_exclusive(args.out, payload)


def _sum_telemetry(records: list[dict], side: str) -> dict:
    totals = Counter({name: 0 for name in DUEL.POINT_BANKING_COUNTER_FIELDS})
    modes = set()
    for record in records:
        telemetry = record[side]["point_banking"]
        modes.add(telemetry["mode"])
        totals.update({name: telemetry[name]
                       for name in DUEL.POINT_BANKING_COUNTER_FIELDS})
    if len(modes) != 1:
        raise ProtocolRefused("aggregate point-banking mode drift")
    return {"mode": next(iter(modes)), **dict(totals)}


def contrast(a_records: list[dict], b_records: list[dict], *,
             a: str, b: str, look: int) -> dict:
    if look not in (1, 2):
        raise ProtocolRefused("aggregate look must be 1 or 2")
    by_seed: dict[int, list[int]] = {}
    for row in a_records:
        by_seed.setdefault(row["seed"], [0, 0])[0] += row["level_utility"]
    for row in b_records:
        by_seed.setdefault(row["seed"], [0, 0])[1] += row["level_utility"]
    differences = [left - right for left, right in by_seed.values()]
    clusters = len(differences)
    if clusters < 2:
        raise ProtocolRefused("aggregate contrast has fewer than two clusters")
    mean = sum(differences) / clusters
    variance = sum((value - mean) ** 2 for value in differences) / \
        (clusters - 1)
    standard_error = math.sqrt(variance / clusters)
    spec = DESIGN.Design().looks[look - 1]
    half = spec.critical * standard_error
    return {
        "a": a,
        "b": b,
        "mean": mean,
        "standard_error": standard_error,
        "half_width": half,
        "lcb": mean - half,
        "ucb": mean + half,
        "clusters": clusters,
        "look": look,
        "alpha": spec.alpha,
        "critical": spec.critical,
        "family_alpha_bound": DESIGN.FAMILY_ALPHA,
    }


def build_aggregate(*, shards: list[dict], inputs: list[dict], parent: dict,
                    runtime: dict, look: int) -> dict:
    if look not in (1, 2):
        raise ProtocolRefused("aggregate look must be 1 or 2")
    clusters = LOOK_CLUSTERS[look - 1]
    sentinel_clusters = clusters // NULL_SENTINEL_STRIDE
    records = {label: [] for label in DUEL.LABEL_ORDER}
    for shard in shards:
        for record in shard["records"]:
            records[record["label"]].append(record)
    expected = {
        "treatment": clusters * 2,
        "champion": clusters * 2,
        "matched_null": sentinel_clusters * 2,
    }
    if any(len(records[label]) != count for label, count in expected.items()):
        raise ProtocolRefused("aggregate record population drift")
    primary_keys = {
        label: {(row["seed"], row["flip"]) for row in records[label]}
        for label in PRIMARY_LABELS
    }
    sentinel_seed_set = {
        cluster_seed(index) for index in sentinel_indexes(clusters=clusters)}
    sentinel_keys = {(seed, flip) for seed in sentinel_seed_set
                     for flip in (0, 1)}
    null_keys = {(row["seed"], row["flip"])
                 for row in records["matched_null"]}
    if (len(primary_keys["treatment"]) != clusters * 2
            or primary_keys["treatment"] != primary_keys["champion"]
            or null_keys != sentinel_keys):
        raise ProtocolRefused("aggregate CRN/sentinel population drift")
    treatment_sentinel = [row for row in records["treatment"]
                          if row["seed"] in sentinel_seed_set]
    champion_sentinel = [row for row in records["champion"]
                         if row["seed"] in sentinel_seed_set]
    stats = {
        "treatment_champion": contrast(
            records["treatment"], records["champion"],
            a="treatment", b="champion", look=look),
        "treatment_matched_null_sentinel": contrast(
            treatment_sentinel, records["matched_null"],
            a="treatment", b="matched_null", look=look),
        "matched_null_champion_sentinel": contrast(
            records["matched_null"], champion_sentinel,
            a="matched_null", b="champion", look=look),
    }
    telemetry = {
        label: {
            "arm": _sum_telemetry(values, "arm"),
            "opp": _sum_telemetry(values, "opp"),
        }
        for label, values in records.items()
    }
    treatment = telemetry["treatment"]["arm"]
    matched_null = telemetry["matched_null"]["arm"]
    outcome_names = (
        "banker", "attacker_points", "winner_team", "level_change",
        "won", "level_utility")
    null_by_key = {(row["seed"], row["flip"]): row
                   for row in records["matched_null"]}
    champion_by_key = {(row["seed"], row["flip"]): row
                       for row in champion_sentinel}
    sentinel_equal = null_by_key.keys() == champion_by_key.keys() and all(
        tuple(null_by_key[key][name] for name in outcome_names)
        == tuple(champion_by_key[key][name] for name in outcome_names)
        for key in null_by_key)
    controls_zero = all(
        telemetry[label][side][name] == 0
        for label in records
        for side in ("arm", "opp")
        for name in DUEL.POINT_BANKING_COUNTER_FIELDS
        if label == "champion" or side == "opp"
    )
    modes = {"treatment": "treatment", "matched_null": "matched_null",
             "champion": "off"}
    exact_work = all(
        not DUEL.counter_problems(
            row[side], expected_mode=(modes[label] if side == "arm" else "off"))
        for label, values in records.items()
        for row in values
        for side in ("arm", "opp")
    )
    integrity = {
        "fixed_primary_population": (
            stats["treatment_champion"]["clusters"] == clusters),
        "sentinel_population_exact": (
            stats["matched_null_champion_sentinel"]["clusters"] ==
            sentinel_clusters),
        "matched_null_champion_sentinel_exact_outcomes": sentinel_equal,
        "treatment_triggered_both_roles": (
            treatment["attacker_triggers"] > 0
            and treatment["defender_triggers"] > 0),
        "matched_null_triggered_both_roles": (
            matched_null["attacker_triggers"] > 0
            and matched_null["defender_triggers"] > 0),
        "treatment_dose_exact": (
            treatment["triggers"] > 0
            and treatment["changes"] == treatment["triggers"]
            and treatment["matched_noops"] == 0),
        "matched_null_dose_exact": (
            matched_null["triggers"] > 0
            and matched_null["changes"] == 0
            and matched_null["matched_noops"] == matched_null["triggers"]),
        "controls_feature_off": controls_zero,
        "all_records_exact_work": exact_work,
    }
    integrity["all"] = all(integrity.values())
    efficacy_pass = stats["treatment_champion"]["lcb"] > 0
    if not integrity["all"]:
        status = "STOP_HOLD" if look == 1 else "HOLD"
    elif efficacy_pass:
        status = "STOP_PASS" if look == 1 else "PASS"
    else:
        status = "CONTINUE_AUTOMATICALLY" if look == 1 else "SELECT_NONE"
    transition_table = LOOK1_TRANSITION if look == 1 else FINAL_TRANSITION
    return {
        "schema": AGGREGATE_SCHEMA,
        "complete": True,
        "run_id": RUN_ID,
        "look": look,
        "clusters": clusters,
        "schedule": schedule(),
        "parent": parent,
        "runtime": runtime,
        "inputs": inputs,
        "stats": stats,
        "point_banking_telemetry": telemetry,
        "integrity": integrity,
        "efficacy_pass": efficacy_pass,
        "transition_table": dict(transition_table),
        "status": status,
        "strength_claim": status in ("STOP_PASS", "PASS"),
        "historical_outcomes_used_for_claim": False,
        "production_promotion": False,
        "explicit_deployment_review_required": True,
        "retry_or_extension_authorized": False,
    }


def load_shards(args: argparse.Namespace, *, parent: dict, runtime: dict,
                receipt: dict) -> tuple[list[dict], list[dict]]:
    if args.look not in (1, 2):
        raise ProtocolRefused("aggregate look must be 1 or 2")
    expected_count = SHARD_COUNT * args.look
    if len(args.shards) != expected_count:
        raise ProtocolRefused(f"expected exactly {expected_count} shards")
    shards = []
    inputs = []
    seen = set()
    for position, raw_path in enumerate(args.shards):
        tranche = position // SHARD_COUNT + 1
        expected_index = position % SHARD_COUNT
        path = Path(raw_path).resolve()
        expected_path = (REPO / NAMESPACE
                         / f"tranche-{tranche}-shard-"
                         f"{expected_index:02d}.json").resolve()
        if path != expected_path:
            raise ProtocolRefused("aggregate shard path is not canonical")
        require_regular_unlinked(
            path, label=f"future S4 tranche {tranche} shard {expected_index}")
        digest = sha256(path)
        if digest in seen:
            raise ProtocolRefused("duplicate shard digest")
        seen.add(digest)
        payload = _load_json(
            path, label=f"future S4 tranche {tranche} shard {expected_index}")
        problems = shard_problems(
            payload, tranche=tranche, shard_index=expected_index, parent=parent,
            runtime=runtime, receipt=receipt)
        if problems:
            raise ProtocolRefused(
                f"invalid shard {expected_index}: " + "; ".join(problems))
        shards.append(payload)
        inputs.append({"path": str(path.relative_to(REPO)),
                       "sha256": digest, "tranche": tranche,
                       "shard_index": expected_index})
    return shards, inputs


def aggregate_command(args: argparse.Namespace) -> None:
    parent, runtime = require_runtime(args.expected_git)
    receipt = require_receipt(
        Path(args.execution_receipt), args.expected_execution_receipt_sha256,
        expected_git=args.expected_git)
    expected_out = (REPO / NAMESPACE
                    / f"look-{args.look}-aggregate.json").resolve()
    if Path(args.out).resolve() != expected_out:
        raise ProtocolRefused("future S4 aggregate output is not canonical")
    shards, inputs = load_shards(
        args, parent=parent, runtime=runtime, receipt=receipt)
    payload = build_aggregate(
        shards=shards, inputs=inputs, parent=parent, runtime=runtime,
        look=args.look)
    write_exclusive(args.out, payload)
    print(json.dumps({
        "schema": AGGREGATE_SCHEMA,
        "status": payload["status"],
        "integrity": payload["integrity"],
        "strength_claim": payload["strength_claim"],
        "production_promotion": False,
    }, sort_keys=True), flush=True)


def _add_record_counters(totals: Counter, record: dict) -> None:
    for side in ("arm", "opp"):
        values = record[side]
        for name in set(DUEL.counters([])) - {"search_secs"}:
            totals[f"{side}_{name}"] += values[name]
        totals[f"{side}_search_secs_millis"] += round(
            1_000 * values["search_secs"])


def preflight(args: argparse.Namespace) -> None:
    parent, runtime = require_runtime(args.expected_git)
    expected_out = (REPO / PREFLIGHT_NAMESPACE / "preflight.json").resolve()
    if Path(args.out).resolve() != expected_out:
        raise ProtocolRefused("future S4 preflight output is not canonical")
    review_path = Path(args.controller_review).resolve()
    admission_path = Path(args.preflight_admission).resolve()
    expected_review = (REPO / PREFLIGHT_REVIEW_PATH).resolve()
    expected_admission = (REPO / PREFLIGHT_ADMISSION_PATH).resolve()
    if review_path != expected_review or admission_path != expected_admission:
        raise ProtocolRefused("future S4 preflight evidence path drift")
    for path, expected_sha, label in (
            (review_path, args.expected_controller_review_sha256,
             "controller review"),
            (admission_path, args.expected_preflight_admission_sha256,
             "preflight admission")):
        require_regular_unlinked(path, label=label)
        if not is_sha256(expected_sha) or sha256(path) != expected_sha:
            raise ProtocolRefused(f"future S4 {label} SHA-256 drift")
    started = time.perf_counter()
    totals = {label: Counter() for label in DUEL.LABEL_ORDER}
    telemetry = {
        label: Counter({name: 0 for name in DUEL.POINT_BANKING_COUNTER_FIELDS})
        for label in DUEL.LABEL_ORDER
    }
    modes = {"treatment": "treatment", "matched_null": "matched_null",
             "champion": "off"}
    problems = []
    arm_clusters = 0
    for cluster_index in range(PREFLIGHT_CLUSTERS):
        seed = cluster_seed(cluster_index, preflight=True)
        labels = preflight_labels(cluster_index)
        arm_clusters += len(labels)
        for label in labels:
            records = DUEL.play_arm_cluster(
                label, seed, run_id=PREFLIGHT_RUN_ID)
            for flip, record in enumerate(records):
                problems.extend(DUEL.record_problems(
                    record, phase="screen", expected_seed=seed,
                    expected_label=label, expected_flip=flip,
                    expected_run_id=PREFLIGHT_RUN_ID))
                _add_record_counters(totals[label], record)
                telemetry[label].update({
                    name: record["arm"]["point_banking"][name]
                    for name in DUEL.POINT_BANKING_COUNTER_FIELDS
                })
            del records
        print(json.dumps({
            "event": "s4-point-banking-future-preflight-progress-v1",
            "clusters_complete": cluster_index + 1,
            "clusters_total": PREFLIGHT_CLUSTERS,
        }, sort_keys=True), flush=True)
    elapsed = time.perf_counter() - started
    target_arm_clusters = (MAX_CLUSTERS * len(PRIMARY_LABELS)
                           + NULL_SENTINEL_CLUSTERS)
    per_arm_cluster = elapsed / arm_clusters
    fleet_hours = (per_arm_cluster * target_arm_clusters
                   * THROUGHPUT_SAFETY_FACTOR / 3_600)
    projection = {
        "fleet_hours": fleet_hours,
        "max_shard_hours": fleet_hours / SHARD_COUNT,
        "target_arm_clusters": target_arm_clusters,
        "preflight_arm_clusters": arm_clusters,
        "look_1_fleet_hours": fleet_hours * LOOK1_CLUSTERS / MAX_CLUSTERS,
        "look_1_max_shard_hours": (
            fleet_hours / SHARD_COUNT * LOOK1_CLUSTERS / MAX_CLUSTERS),
    }
    treatment = telemetry["treatment"]
    matched_null = telemetry["matched_null"]
    controls_zero = all(
        telemetry["champion"][name] == 0
        for name in DUEL.POINT_BANKING_COUNTER_FIELDS)
    criteria = {
        "records_valid": not problems,
        "stream_populations_disjoint": not stream_problems(),
        "treatment_triggered_both_roles": (
            treatment["attacker_triggers"] > 0
            and treatment["defender_triggers"] > 0),
        "matched_null_triggered_both_roles": (
            matched_null["attacker_triggers"] > 0
            and matched_null["defender_triggers"] > 0),
        "treatment_dose_exact": (
            treatment["changes"] == treatment["triggers"]
            and treatment["matched_noops"] == 0),
        "matched_null_dose_exact": (
            matched_null["changes"] == 0
            and matched_null["matched_noops"] == matched_null["triggers"]),
        "champion_feature_off": controls_zero,
        "fleet_hours_le_cap": fleet_hours <= MAX_PROJECTED_FLEET_HOURS,
        "max_shard_hours_le_cap": (
            fleet_hours / SHARD_COUNT <= MAX_PROJECTED_SHARD_HOURS),
    }
    criteria["all"] = all(criteria.values())
    payload = {
        "schema": PREFLIGHT_SCHEMA,
        "complete": True,
        "score_free": True,
        "outcomes_published": False,
        "outcomes_discarded": True,
        "run_id": PREFLIGHT_RUN_ID,
        "clusters": PREFLIGHT_CLUSTERS,
        "seed0": PREFLIGHT_SEED0,
        "stream_stride": DUEL.STREAM_STRIDE,
        "parent": parent,
        "runtime": runtime,
        "design": json_copy(DESIGN_RECORD),
        "controller_review": {
            "path": str(review_path.relative_to(REPO)),
            "sha256": args.expected_controller_review_sha256},
        "preflight_admission": {
            "path": str(admission_path.relative_to(REPO)),
            "sha256": args.expected_preflight_admission_sha256},
        "elapsed_seconds": elapsed,
        "throughput_safety_factor": THROUGHPUT_SAFETY_FACTOR,
        "counter_totals": {label: dict(values)
                           for label, values in totals.items()},
        "point_banking_telemetry": {
            label: {"mode": modes[label], **dict(values)}
            for label, values in telemetry.items()},
        "projection": projection,
        "criteria": criteria,
        "status": ("AUTHORIZE_SEQUENTIAL_PACKET_REVIEW"
                   if criteria["all"] else "HOLD"),
        "sequential_launch_authorized": False,
        "tranche_2_pre_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "retry_or_extension_authorized": False,
    }
    write_exclusive(args.out, payload)
    print(json.dumps({
        "schema": PREFLIGHT_SCHEMA,
        "score_free": True,
        "status": payload["status"],
        "criteria": criteria,
        "projection": projection,
    }, sort_keys=True), flush=True)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run")
    run.add_argument("--expected-git", required=True)
    run.add_argument("--tranche", type=int, choices=(1, 2), required=True)
    run.add_argument("--shard-index", type=int, required=True)
    run.add_argument("--progress-every", type=int, default=1)
    run.add_argument("--execution-receipt", required=True)
    run.add_argument("--expected-execution-receipt-sha256", required=True)
    run.add_argument("--out", required=True)

    aggregate = commands.add_parser("aggregate")
    aggregate.add_argument("--expected-git", required=True)
    aggregate.add_argument("--look", type=int, choices=(1, 2), required=True)
    aggregate.add_argument("--shards", nargs="+", required=True)
    aggregate.add_argument("--execution-receipt", required=True)
    aggregate.add_argument("--expected-execution-receipt-sha256", required=True)
    aggregate.add_argument("--out", required=True)

    validate = commands.add_parser("validate-runtime")
    validate.add_argument("--expected-git", required=True)
    validate.add_argument("--execution-receipt", required=True)
    validate.add_argument("--expected-execution-receipt-sha256",
                          required=True)

    capacity = commands.add_parser("preflight")
    capacity.add_argument("--expected-git", required=True)
    capacity.add_argument("--controller-review", required=True)
    capacity.add_argument("--expected-controller-review-sha256", required=True)
    capacity.add_argument("--preflight-admission", required=True)
    capacity.add_argument("--expected-preflight-admission-sha256",
                          required=True)
    capacity.add_argument("--out", required=True)
    return root


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if args.command == "run":
        run_shard(args)
    elif args.command == "aggregate":
        aggregate_command(args)
    elif args.command == "validate-runtime":
        validate_runtime(args)
    else:
        preflight(args)


if __name__ == "__main__":
    try:
        main()
    except (ProtocolRefused, DUEL.ProtocolRefused) as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc

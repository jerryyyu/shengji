#!/usr/bin/env python3
"""Fixed-size Air replication for the S4 point-banking rollout policy.

The first complete-round screen used 2,048 fresh mirrored deal clusters and
three full arms.  It passed.  This independent replication keeps the same
2,048-cluster primary comparison while avoiding a redundant full-population
matched-null arm:

* treatment and the live champion run on every cluster;
* the behavior-identical matched null runs on a deterministic 1/8 sentinel
  sample, stratified equally across the eight shards; and
* the primary gate is a fixed-look clustered z=1.96 lower bound for
  treatment-minus-champion.  There are no optional interim looks or extensions.

The sentinel is an implementation-drift control, not a second powered strength
contrast.  It must remain outcome-identical to champion on every sampled
seed/flip and must exercise both roles with exact dose.  A passing replication
can record strength, but never promotes or deploys automatically.
"""

from __future__ import annotations

import argparse
import hashlib
import json
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

SCHEMA = "s4-point-banking-replication-shard-v1"
AGGREGATE_SCHEMA = "s4-point-banking-replication-aggregate-v1"
PREFLIGHT_SCHEMA = "s4-point-banking-replication-preflight-v1"
PACKET_SCHEMA = "s4-point-banking-replication-air-packet-v1"
PACKET_REVIEW_SCHEMA = "s4-point-banking-replication-air-review-v1"
PACKET_REVIEW_MARKER = "S4_POINT_BANKING_REPLICATION_AIR_V1_REVIEW "
ADMISSION_SCHEMA = "s4-point-banking-replication-air-admission-v1"
RECEIPT_SCHEMA = "s4-point-banking-replication-air-receipt-v1"

RUN_ID = "s4-point-banking-replication-air-180b-v1"
NAMESPACE = Path("server/runs/logs") / RUN_ID
SEED0 = 180_000_000_000
CLUSTERS = 2_048
SHARD_COUNT = 8
CLUSTERS_PER_SHARD = CLUSTERS // SHARD_COUNT
NULL_SENTINEL_STRIDE = 8
NULL_SENTINEL_CLUSTERS = CLUSTERS // NULL_SENTINEL_STRIDE
PRIMARY_LABELS = ("treatment", "champion")

PREFLIGHT_RUN_ID = "s4-point-banking-replication-preflight-179b-v1"
PREFLIGHT_NAMESPACE = Path("server/runs/logs") / PREFLIGHT_RUN_ID
PREFLIGHT_SEED0 = 179_000_000_000
PREFLIGHT_CLUSTERS = 8
THROUGHPUT_SAFETY_FACTOR = 2.0
MAX_PROJECTED_FLEET_HOURS = 100.0
MAX_PROJECTED_SHARD_HOURS = 15.0
Z_95 = 1.96

SCREEN_RUN_ID = DUEL.PHASES["screen"]["run_id"]
SCREEN_NAMESPACE = Path("server/runs/logs") / SCREEN_RUN_ID
SCREEN_AGGREGATE_SHA256 = (
    "3c7f27b8466ec9ece73820d21d26349bfd95c4fc17db144b26408db4af6b4268"
)
SCREEN_FINAL_SHA256 = (
    "e188f7e8ee80fe2fc17fee6d79b4eb4c6a41a45713c76825ef707981e30f2b24"
)
SCREEN_RUNNER_SHA256 = (
    "8bf72a64caced9ef9e771b1efde608d52623234939d7920783f28a2adbc6cbf7"
)

CLAIM_BOUNDARY = (
    "One fixed-look independent 2,048-cluster complete-round replication of "
    "the frozen S4 rollout-only continuation against exact live report-LCB. "
    "Matched null is a stratified implementation sentinel, not a powered "
    "strength arm. No optional look, extension, promotion, deployment, or "
    "multi-round progression claim."
)
SELECTION_RULE = (
    "Confirm only when z1.96 clustered LCB(treatment-champion)>0 over all "
    "2,048 fresh mirrored clusters; matched-null and champion outcomes are "
    "exactly equal on all 256 preregistered sentinel clusters; treatment and "
    "matched null trigger in both roles with exact dose; controls stay off; "
    "and every retained record consumes exact report-LCB work. Otherwise "
    "SELECT_NONE. This fixed population has no retry or extension authority."
)


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
    total = PREFLIGHT_CLUSTERS if preflight else CLUSTERS
    seed0 = PREFLIGHT_SEED0 if preflight else SEED0
    if not 0 <= cluster_index < total:
        raise ProtocolRefused("cluster index outside registered population")
    return seed0 + DUEL.STREAM_STRIDE * cluster_index


def shard_indexes(shard_index: int) -> list[int]:
    if not 0 <= shard_index < SHARD_COUNT:
        raise ProtocolRefused("shard index outside registered population")
    return list(range(shard_index, CLUSTERS, SHARD_COUNT))


def is_null_sentinel(cluster_index: int) -> bool:
    if not 0 <= cluster_index < CLUSTERS:
        raise ProtocolRefused("sentinel index outside registered population")
    # Every shard sees local indexes 0,8,...,248: 32 sentinels per shard.
    return (cluster_index // SHARD_COUNT) % NULL_SENTINEL_STRIDE == 0


def labels_for_cluster(cluster_index: int) -> tuple[str, ...]:
    return ("treatment", "matched_null", "champion") \
        if is_null_sentinel(cluster_index) else PRIMARY_LABELS


def preflight_labels(cluster_index: int) -> tuple[str, ...]:
    # Exercise one full sentinel cluster and seven primary-only clusters.
    return ("treatment", "matched_null", "champion") \
        if cluster_index == 0 else PRIMARY_LABELS


def sentinel_indexes() -> list[int]:
    return [index for index in range(CLUSTERS) if is_null_sentinel(index)]


def schedule() -> dict:
    per_shard = [shard_indexes(index) for index in range(SHARD_COUNT)]
    sentinels = sentinel_indexes()
    return {
        "run_id": RUN_ID,
        "seed0": SEED0,
        "stream_stride": DUEL.STREAM_STRIDE,
        "clusters": CLUSTERS,
        "shard_count": SHARD_COUNT,
        "clusters_per_shard": CLUSTERS_PER_SHARD,
        "primary_labels": list(PRIMARY_LABELS),
        "null_sentinel_stride": NULL_SENTINEL_STRIDE,
        "null_sentinel_clusters": NULL_SENTINEL_CLUSTERS,
        "null_sentinel_indexes_sha256": stable_digest(sentinels),
        "per_shard_indexes_sha256": [stable_digest(value)
                                      for value in per_shard],
        "records": (CLUSTERS * len(PRIMARY_LABELS) * 2
                    + NULL_SENTINEL_CLUSTERS * 2),
        "selection_rule": SELECTION_RULE,
        "claim_boundary": CLAIM_BOUNDARY,
    }


def _stream_uses(seed0: int, clusters: int) -> list[tuple[int, int, str]]:
    return DUEL._stream_uses(seed0, clusters)


def stream_problems() -> list[str]:
    populations = {
        "replication_preflight": _stream_uses(
            PREFLIGHT_SEED0, PREFLIGHT_CLUSTERS),
        "replication": _stream_uses(SEED0, CLUSTERS),
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
    return [
        f"global seed collision {seed}: {uses}"
        for seed, uses in by_seed.items() if len(uses) != 1
    ]


def require_runtime(expected_git: str) -> tuple[dict, dict]:
    try:
        parent, base = DUEL.require_runtime(expected_git)
    except DUEL.ProtocolRefused as exc:
        raise ProtocolRefused(f"base S4 runtime refused: {exc}") from exc
    problems = stream_problems()
    if problems:
        raise ProtocolRefused("replication stream drift: " + "; ".join(problems))
    runtime = {
        **base,
        "replication_runner_sha256": sha256(SCRIPT),
        "replication_schedule_sha256": stable_digest(schedule()),
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


def load_screen_parent(*, aggregate_path: Path, final_path: Path,
                       parent: dict, runtime: dict) -> dict:
    require_regular_unlinked(aggregate_path, label="S4 screen aggregate")
    require_regular_unlinked(final_path, label="S4 screen final")
    if sha256(aggregate_path) != SCREEN_AGGREGATE_SHA256:
        raise ProtocolRefused("S4 screen aggregate SHA-256 drift")
    if sha256(final_path) != SCREEN_FINAL_SHA256:
        raise ProtocolRefused("S4 screen final SHA-256 drift")
    aggregate = _load_json(aggregate_path, label="S4 screen aggregate")
    final = _load_json(final_path, label="S4 screen final")
    if (aggregate.get("schema") != DUEL.AGGREGATE_SCHEMA
            or aggregate.get("complete") is not True
            or aggregate.get("phase") != "screen"
            or aggregate.get("status") != "AUTHORIZE_CONFIRM_PACKET_REVIEW"
            or aggregate.get("parent") != parent
            or aggregate.get("criteria", {}).get("all") is not True
            or aggregate.get("strength_claim") is not False
            or aggregate.get("production_promotion") is not False):
        raise ProtocolRefused("S4 screen aggregate does not authorize review")
    aggregate_ref = final.get("aggregate")
    if (final.get("complete") is not True
            or final.get("run_id") != SCREEN_RUN_ID
            or not isinstance(final.get("jobs"), list)
            or len(final["jobs"]) != DUEL.SHARD_COUNT
            or aggregate_ref != {
                "path": str(SCREEN_NAMESPACE / "aggregate.json"),
                "sha256": SCREEN_AGGREGATE_SHA256,
                "status": "AUTHORIZE_CONFIRM_PACKET_REVIEW",
            }
            or final.get("screen_gate_passed") is not True
            or final.get("confirm_packet_review_authorized") is not True
            or final.get("confirmation_launch_authorized") is not False
            or final.get("strength_claim") is not False
            or final.get("production_promotion") is not False):
        raise ProtocolRefused("S4 screen final identity/authority drift")
    prior = aggregate.get("runtime")
    current_sources = runtime.get("source_sha256s", {})
    prior_sources = prior.get("source_sha256s", {}) \
        if isinstance(prior, dict) else {}
    expected_prior_sources = dict(current_sources)
    expected_prior_sources["runner"] = SCREEN_RUNNER_SHA256
    if (not isinstance(prior, dict)
            or prior_sources != expected_prior_sources
            or prior.get("fast_engine") is not True
            or prior.get("require_voids") is not True
            or prior.get("experimental_flags") != []
            or prior.get("fast_binary_sha256") !=
            runtime.get("fast_binary_sha256")
            or prior.get("policy_contract_sha256s") !=
            runtime.get("policy_contract_sha256s")):
        raise ProtocolRefused("S4 screen runtime is not the frozen policy")
    stats = aggregate.get("stats", {})
    if (stats.get("treatment_champion", {}).get("clusters") != 2_048
            or stats.get("treatment_champion", {}).get("lcb95", 0) <= 0
            or stats.get("matched_null_champion", {}).get("mean") != 0
            or stats.get("matched_null_champion", {}).get("half_width95") != 0):
        raise ProtocolRefused("S4 screen statistics do not support replication")
    return {
        "aggregate": {"path": str(aggregate_path.relative_to(REPO)),
                      "sha256": SCREEN_AGGREGATE_SHA256},
        "final": {"path": str(final_path.relative_to(REPO)),
                  "sha256": SCREEN_FINAL_SHA256},
        "status": "AUTHORIZE_CONFIRM_PACKET_REVIEW",
        "clusters": 2_048,
    }


def expected_receipt_fields() -> set[str]:
    return {
        "schema", "run_id", "complete", "git", "runner_sha256",
        "controller_sha256", "created_time_ns", "nonce", "packet_sha256",
        "admission_sha256", "preflight_sha256", "screen_aggregate_sha256",
        "screen_final_sha256", "replication_launch_authorized",
        "strength_claim", "training_authorized", "production_promotion",
        "retry_or_extension_authorized",
    }


def require_receipt(path: Path, expected_sha256: str, *,
                    expected_git: str) -> dict:
    expected_path = (REPO / NAMESPACE / "receipt.json").resolve()
    if path.resolve() != expected_path:
        raise ProtocolRefused("replication receipt is not canonical")
    require_regular_unlinked(path, label="replication receipt")
    if not is_sha256(expected_sha256) or sha256(path) != expected_sha256:
        raise ProtocolRefused("replication receipt SHA-256 drift")
    receipt = _load_json(path, label="replication receipt")
    if (set(receipt) != expected_receipt_fields()
            or receipt.get("schema") != RECEIPT_SCHEMA
            or receipt.get("run_id") != RUN_ID
            or receipt.get("complete") is not True
            or receipt.get("git") != expected_git
            or receipt.get("runner_sha256") != sha256(SCRIPT)
            or not is_sha256(receipt.get("controller_sha256"))
            or not is_sha256(receipt.get("nonce"))
            or not all(is_sha256(receipt.get(name)) for name in (
                "packet_sha256", "admission_sha256", "preflight_sha256",
                "screen_aggregate_sha256", "screen_final_sha256"))
            or receipt.get("screen_aggregate_sha256") !=
            SCREEN_AGGREGATE_SHA256
            or receipt.get("screen_final_sha256") != SCREEN_FINAL_SHA256
            or receipt.get("replication_launch_authorized") is not True
            or receipt.get("strength_claim") is not False
            or receipt.get("training_authorized") is not False
            or receipt.get("production_promotion") is not False
            or receipt.get("retry_or_extension_authorized") is not False):
        raise ProtocolRefused("replication receipt authority/identity drift")
    created = receipt.get("created_time_ns")
    if isinstance(created, bool) or not isinstance(created, int) or created <= 0:
        raise ProtocolRefused("replication receipt creation time drift")

    namespace = REPO / NAMESPACE
    packet_path = namespace / "launch_packet.json"
    review_path = namespace / "review_record.txt"
    admission_path = namespace / "review_admission.json"
    for artifact, digest, label in (
            (packet_path, receipt["packet_sha256"], "replication packet"),
            (admission_path, receipt["admission_sha256"],
             "replication admission")):
        require_regular_unlinked(artifact, label=label)
        if sha256(artifact) != digest:
            raise ProtocolRefused(f"{label} SHA-256 drift")
    require_regular_unlinked(review_path, label="replication review record")
    packet = _load_json(packet_path, label="replication packet")
    admission = _load_json(admission_path, label="replication admission")
    try:
        review_text = review_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ProtocolRefused(f"cannot reopen replication review: {exc}") \
            from exc

    packet_fields = {
        "schema", "run_id", "git", "runner", "controller", "runtime",
        "parent", "screen_parent", "score_free_preflight", "schedule",
        "namespace", "jobs", "aggregate_command_template",
        "aggregate_output", "heartbeat_seconds", "selection_rule",
        "claim_boundary", "packet_review_authorized",
        "replication_launch_authorized", "strength_claim",
        "training_authorized", "production_promotion",
        "retry_or_extension_authorized",
    }
    runner = packet.get("runner") if isinstance(packet, dict) else None
    controller = packet.get("controller") if isinstance(packet, dict) else None
    preflight = (packet.get("score_free_preflight")
                 if isinstance(packet, dict) else None)
    screen = packet.get("screen_parent") if isinstance(packet, dict) else None
    try:
        parent, current_runtime = require_runtime(expected_git)
    except ProtocolRefused as exc:
        raise ProtocolRefused(
            f"cannot reopen receipt runtime: {exc}") from exc
    preflight_path = REPO / PREFLIGHT_NAMESPACE / "preflight.json"
    require_regular_unlinked(preflight_path, label="replication preflight")
    controller_path = REPO / "server/scripts/s4_point_banking_replication_air.py"
    require_regular_unlinked(controller_path, label="replication controller")
    screen_parent = load_screen_parent(
        aggregate_path=REPO / SCREEN_NAMESPACE / "aggregate.json",
        final_path=REPO / SCREEN_NAMESPACE / "supervisor-final.json",
        parent=parent, runtime=current_runtime)
    if (set(packet) != packet_fields
            or packet.get("schema") != PACKET_SCHEMA
            or packet.get("run_id") != RUN_ID
            or packet.get("git") != expected_git
            or runner != {
                "path": "server/scripts/s4_point_banking_replication.py",
                "sha256": sha256(SCRIPT),
            }
            or not isinstance(controller, dict)
            or controller.get("path") !=
            "server/scripts/s4_point_banking_replication_air.py"
            or controller.get("sha256") != receipt["controller_sha256"]
            or sha256(controller_path) != receipt["controller_sha256"]
            or packet.get("runtime") != current_runtime
            or packet.get("parent") != parent
            or packet.get("screen_parent") != screen_parent
            or packet.get("schedule") != schedule()
            or packet.get("namespace") != str(NAMESPACE)
            or not isinstance(preflight, dict)
            or preflight.get("path") !=
            str(PREFLIGHT_NAMESPACE / "preflight.json")
            or preflight.get("sha256") != receipt["preflight_sha256"]
            or sha256(preflight_path) != receipt["preflight_sha256"]
            or preflight.get("score_free") is not True
            or preflight.get("outcomes_published") is not False
            or not isinstance(screen, dict)
            or screen.get("aggregate", {}).get("sha256") !=
            SCREEN_AGGREGATE_SHA256
            or screen.get("final", {}).get("sha256") != SCREEN_FINAL_SHA256
            or packet.get("selection_rule") != SELECTION_RULE
            or packet.get("claim_boundary") != CLAIM_BOUNDARY
            or packet.get("packet_review_authorized") is not True
            or packet.get("replication_launch_authorized") is not False
            or packet.get("strength_claim") is not False
            or packet.get("training_authorized") is not False
            or packet.get("production_promotion") is not False
            or packet.get("retry_or_extension_authorized") is not False):
        raise ProtocolRefused("replication packet identity/authority drift")

    marker_matches = [
        line[len(PACKET_REVIEW_MARKER):]
        for line in review_text.splitlines()
        if line.startswith(PACKET_REVIEW_MARKER)
    ]
    if len(marker_matches) != 1:
        raise ProtocolRefused("replication review must contain one marker")
    try:
        review_claim = json.loads(marker_matches[0])
    except ValueError as exc:
        raise ProtocolRefused("replication review marker is invalid") from exc
    expected_claim = {
        "schema": PACKET_REVIEW_SCHEMA,
        "git": expected_git,
        "run_id": RUN_ID,
        "packet_sha256": receipt["packet_sha256"],
        "preflight_sha256": receipt["preflight_sha256"],
        "screen_aggregate_sha256": SCREEN_AGGREGATE_SHA256,
        "screen_final_sha256": SCREEN_FINAL_SHA256,
        "fixed_look_clusters": CLUSTERS,
        "null_sentinel_clusters": NULL_SENTINEL_CLUSTERS,
        "independent_review": True,
        "replication_launch_authorized": True,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "verdict": "PASS",
    }
    expected_admission = {
        "schema": ADMISSION_SCHEMA,
        "run_id": RUN_ID,
        "packet": {"path": str(NAMESPACE / "launch_packet.json"),
                   "sha256": receipt["packet_sha256"]},
        "review": {"path": str(NAMESPACE / "review_record.txt"),
                   "sha256": sha256(review_path)},
        "review_claim": expected_claim,
        "operator_asserted_independent_review": True,
        "replication_launch_authorized": True,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
    }
    if admission != expected_admission or review_claim != expected_claim:
        raise ProtocolRefused("replication review/admission authority drift")
    return {"path": str(path.relative_to(REPO)), "sha256": expected_sha256}


def record_problems(record: object, *, expected_seed: int,
                    expected_label: str, expected_flip: int) -> list[str]:
    return DUEL.record_problems(
        record, phase="screen", expected_seed=expected_seed,
        expected_label=expected_label, expected_flip=expected_flip,
        expected_run_id=RUN_ID)


def shard_problems(payload: object, *, shard_index: int, parent: dict,
                   runtime: dict, receipt: dict) -> list[str]:
    if not isinstance(payload, dict):
        return ["shard is not an object"]
    expected_fields = {
        "schema", "complete", "run_id", "schedule", "shard_index",
        "cluster_indexes", "parent", "runtime", "execution_receipt",
        "records", "strength_claim", "production_promotion",
        "retry_or_extension_authorized",
    }
    problems = []
    indexes = shard_indexes(shard_index)
    if (set(payload) != expected_fields
            or payload.get("schema") != SCHEMA
            or payload.get("complete") is not True
            or payload.get("run_id") != RUN_ID
            or payload.get("schedule") != schedule()
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
                    / f"shard-{args.shard_index:02d}.json").resolve()
    if Path(args.out).resolve() != expected_out:
        raise ProtocolRefused("replication shard output is not canonical")
    indexes = shard_indexes(args.shard_index)
    records: list[dict] = []
    for local_index, cluster_index in enumerate(indexes, 1):
        seed = cluster_seed(cluster_index)
        for label in labels_for_cluster(cluster_index):
            records.extend(DUEL.play_arm_cluster(label, seed, run_id=RUN_ID))
        if args.progress_every and local_index % args.progress_every == 0:
            print(json.dumps({
                "event": "s4-point-banking-replication-progress-v1",
                "shard_index": args.shard_index,
                "clusters_complete": local_index,
                "clusters_total": len(indexes),
            }, sort_keys=True), flush=True)
    payload = {
        "schema": SCHEMA,
        "complete": True,
        "run_id": RUN_ID,
        "schedule": schedule(),
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
        payload, shard_index=args.shard_index, parent=parent,
        runtime=runtime, receipt=receipt)
    if problems:
        raise ProtocolRefused("invalid replication shard: "
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
             a: str, b: str) -> dict:
    mean, half, clusters = DUEL.paired_by_seed(a_records, b_records)
    return {
        "a": a,
        "b": b,
        "mean": mean,
        "half_width95": half,
        "lcb95": mean - half,
        "ucb95": mean + half,
        "clusters": clusters,
        "z": Z_95,
        "fixed_look": True,
    }


def build_aggregate(*, shards: list[dict], inputs: list[dict], parent: dict,
                    runtime: dict, screen_parent: dict) -> dict:
    records = {label: [] for label in DUEL.LABEL_ORDER}
    for shard in shards:
        for record in shard["records"]:
            records[record["label"]].append(record)
    expected = {
        "treatment": CLUSTERS * 2,
        "champion": CLUSTERS * 2,
        "matched_null": NULL_SENTINEL_CLUSTERS * 2,
    }
    if any(len(records[label]) != count for label, count in expected.items()):
        raise ProtocolRefused("aggregate record population drift")
    primary_keys = {
        label: {(row["seed"], row["flip"]) for row in records[label]}
        for label in PRIMARY_LABELS
    }
    sentinel_seed_set = {cluster_seed(index) for index in sentinel_indexes()}
    sentinel_keys = {(seed, flip) for seed in sentinel_seed_set
                     for flip in (0, 1)}
    null_keys = {(row["seed"], row["flip"])
                 for row in records["matched_null"]}
    if (len(primary_keys["treatment"]) != CLUSTERS * 2
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
            a="treatment", b="champion"),
        "treatment_matched_null_sentinel": contrast(
            treatment_sentinel, records["matched_null"],
            a="treatment", b="matched_null"),
        "matched_null_champion_sentinel": contrast(
            records["matched_null"], champion_sentinel,
            a="matched_null", b="champion"),
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
    sentinel_equal = all(
        tuple(left[name] for name in (
            "banker", "attacker_points", "winner_team", "level_change",
            "won", "level_utility"))
        == tuple(right[name] for name in (
            "banker", "attacker_points", "winner_team", "level_change",
            "won", "level_utility"))
        for left, right in zip(
            records["matched_null"], champion_sentinel, strict=True)
    )
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
    criteria = {
        "fixed_primary_population": (
            stats["treatment_champion"]["clusters"] == CLUSTERS),
        "treatment_champion_lcb_gt_zero": (
            stats["treatment_champion"]["lcb95"] > 0),
        "sentinel_population_exact": (
            stats["matched_null_champion_sentinel"]["clusters"] ==
            NULL_SENTINEL_CLUSTERS),
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
    criteria["all"] = all(criteria.values())
    status = ("CONFIRM_S4_POINT_BANKING_REPLICATION"
              if criteria["all"] else "SELECT_NONE")
    return {
        "schema": AGGREGATE_SCHEMA,
        "complete": True,
        "run_id": RUN_ID,
        "schedule": schedule(),
        "parent": parent,
        "runtime": runtime,
        "screen_parent": screen_parent,
        "inputs": inputs,
        "stats": stats,
        "point_banking_telemetry": telemetry,
        "criteria": criteria,
        "status": status,
        "strength_claim": criteria["all"],
        "production_promotion": False,
        "explicit_deployment_review_required": True,
        "retry_or_extension_authorized": False,
    }


def load_shards(args: argparse.Namespace, *, parent: dict, runtime: dict,
                receipt: dict) -> tuple[list[dict], list[dict]]:
    if len(args.shards) != SHARD_COUNT:
        raise ProtocolRefused(f"expected exactly {SHARD_COUNT} shards")
    shards = []
    inputs = []
    seen = set()
    for expected_index, raw_path in enumerate(args.shards):
        path = Path(raw_path).resolve()
        expected_path = (REPO / NAMESPACE
                         / f"shard-{expected_index:02d}.json").resolve()
        if path != expected_path:
            raise ProtocolRefused("aggregate shard path is not canonical")
        require_regular_unlinked(path, label=f"replication shard {expected_index}")
        digest = sha256(path)
        if digest in seen:
            raise ProtocolRefused("duplicate shard digest")
        seen.add(digest)
        payload = _load_json(path, label=f"replication shard {expected_index}")
        problems = shard_problems(
            payload, shard_index=expected_index, parent=parent,
            runtime=runtime, receipt=receipt)
        if problems:
            raise ProtocolRefused(
                f"invalid shard {expected_index}: " + "; ".join(problems))
        shards.append(payload)
        inputs.append({"path": str(path.relative_to(REPO)),
                       "sha256": digest, "shard_index": expected_index})
    return shards, inputs


def aggregate_command(args: argparse.Namespace) -> None:
    parent, runtime = require_runtime(args.expected_git)
    receipt = require_receipt(
        Path(args.execution_receipt), args.expected_execution_receipt_sha256,
        expected_git=args.expected_git)
    expected_out = (REPO / NAMESPACE / "aggregate.json").resolve()
    if Path(args.out).resolve() != expected_out:
        raise ProtocolRefused("replication aggregate output is not canonical")
    screen_parent = load_screen_parent(
        aggregate_path=Path(args.screen_aggregate),
        final_path=Path(args.screen_final), parent=parent, runtime=runtime)
    shards, inputs = load_shards(
        args, parent=parent, runtime=runtime, receipt=receipt)
    payload = build_aggregate(
        shards=shards, inputs=inputs, parent=parent, runtime=runtime,
        screen_parent=screen_parent)
    write_exclusive(args.out, payload)
    print(json.dumps({
        "schema": AGGREGATE_SCHEMA,
        "status": payload["status"],
        "criteria": payload["criteria"],
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
        raise ProtocolRefused("replication preflight output is not canonical")
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
            "event": "s4-point-banking-replication-preflight-progress-v1",
            "clusters_complete": cluster_index + 1,
            "clusters_total": PREFLIGHT_CLUSTERS,
        }, sort_keys=True), flush=True)
    elapsed = time.perf_counter() - started
    target_arm_clusters = (CLUSTERS * len(PRIMARY_LABELS)
                           + NULL_SENTINEL_CLUSTERS)
    per_arm_cluster = elapsed / arm_clusters
    fleet_hours = (per_arm_cluster * target_arm_clusters
                   * THROUGHPUT_SAFETY_FACTOR / 3_600)
    projection = {
        "fleet_hours": fleet_hours,
        "max_shard_hours": fleet_hours / SHARD_COUNT,
        "target_arm_clusters": target_arm_clusters,
        "preflight_arm_clusters": arm_clusters,
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
        "elapsed_seconds": elapsed,
        "throughput_safety_factor": THROUGHPUT_SAFETY_FACTOR,
        "counter_totals": {label: dict(values)
                           for label, values in totals.items()},
        "point_banking_telemetry": {
            label: {"mode": modes[label], **dict(values)}
            for label, values in telemetry.items()},
        "projection": projection,
        "criteria": criteria,
        "status": ("AUTHORIZE_REPLICATION_PACKET_REVIEW"
                   if criteria["all"] else "HOLD"),
        "replication_launch_authorized": False,
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
    run.add_argument("--shard-index", type=int, required=True)
    run.add_argument("--progress-every", type=int, default=1)
    run.add_argument("--execution-receipt", required=True)
    run.add_argument("--expected-execution-receipt-sha256", required=True)
    run.add_argument("--out", required=True)

    aggregate = commands.add_parser("aggregate")
    aggregate.add_argument("--expected-git", required=True)
    aggregate.add_argument("--shards", nargs="+", required=True)
    aggregate.add_argument("--screen-aggregate", required=True)
    aggregate.add_argument("--screen-final", required=True)
    aggregate.add_argument("--execution-receipt", required=True)
    aggregate.add_argument("--expected-execution-receipt-sha256", required=True)
    aggregate.add_argument("--out", required=True)

    capacity = commands.add_parser("preflight")
    capacity.add_argument("--expected-git", required=True)
    capacity.add_argument("--out", required=True)
    return root


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if args.command == "run":
        run_shard(args)
    elif args.command == "aggregate":
        aggregate_command(args)
    else:
        preflight(args)


if __name__ == "__main__":
    try:
        main()
    except (ProtocolRefused, DUEL.ProtocolRefused) as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc

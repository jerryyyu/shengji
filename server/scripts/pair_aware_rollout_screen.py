#!/usr/bin/env python3
"""Freeze and run one powered pair-aware whole-round strength screen.

The score-free capacity run measured natural traffic and runtime but did not
publish outcomes.  This controller consumes its independent review, freezes a
fresh 7,168-cluster population, and compares the pair-aware rollout policy to
both a same-work no-op and the literal live champion.  Eight shards publish no
partial aggregate; an independent supervisor-final review is required before
the one aggregate can be opened.

PASS is a screen signal that may open confirmation design.  It never confirms,
promotes, deploys, retries, or extends this population.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import secrets
import signal
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import pair_aware_rollout_capacity as CAPACITY  # noqa: E402
import pair_aware_rollout_duel as CORE  # noqa: E402


PACKET_SCHEMA = "pair-aware-rollout-screen-packet-v1"
RECEIPT_SCHEMA = "pair-aware-rollout-screen-receipt-v1"
SHARD_SCHEMA = "pair-aware-rollout-screen-shard-v1"
SUPERVISOR_SCHEMA = "pair-aware-rollout-screen-supervisor-final-v1"
AGGREGATE_SCHEMA = "pair-aware-rollout-screen-result-v1"
RUN_ID = CAPACITY.RUN_ID
SCREEN_CLUSTERS = 7_168
SHARD_COUNT = 8
CLUSTERS_PER_SHARD = SCREEN_CLUSTERS // SHARD_COUNT
SCREEN_SEED0 = CAPACITY.SCREEN_SEED0
STREAM_STRIDE = CAPACITY.STREAM_STRIDE
ONE_SIDED_ALPHA = 0.05
Z_ONE_SIDED_95 = 1.6448536269514722
Z_POWER_80 = 0.8416212335729143
PLANNING_CLUSTER_SD = 1.6
TARGET_EFFECT = 0.05
CAPACITY_RESULT_SHA256 = (
    "08f7282cc2317550336647642085a1c165ae708cb6483b4710d0359b498ef7c1")
CAPACITY_RESULT_INTERNAL_SHA256 = (
    "222b89c9ff1c0d47530e9980bbb81161d1d22d8c9baf9a60a130ecb870ac9c5e")
CAPACITY_PACKET_SHA256 = (
    "67294a93dc94dbf4d95449518b2cb71ca13e30f085ebbb20371d313af0e4a9b4")
CAPACITY_RESULT_PATH = (
    SERVER / "runs/logs/pair-aware-whole-round-preflight-v3/capacity.json")
PLANNING_REVIEW_PATH = (
    REPO / "docs_archive/"
    "handoff-review-2026-08-08-through-2026-08-11-10-22.md")
PLANNING_REVIEW_PREFIX = "S4_POINT_BANKING_REPLICATION_AIR_RESULT_V1_REVIEW "
PACKET_REVIEW_PREFIX = "PAIR_AWARE_ROLLOUT_SCREEN_PACKET_V1_REVIEW "
SUPERVISOR_REVIEW_PREFIX = (
    "PAIR_AWARE_ROLLOUT_SCREEN_SUPERVISOR_V1_REVIEW ")
RUN_DIR = SERVER / "runs/logs" / RUN_ID
PACKET_PATH = RUN_DIR / "controller-packet.json"
RECEIPT_PATH = RUN_DIR / "screen-receipt.json"
SUPERVISOR_FINAL_PATH = RUN_DIR / "supervisor-final.json"
AGGREGATE_PATH = RUN_DIR / "aggregate.json"
EXECUTION_ADMISSION_PATH = (
    SERVER / "runs/locks" / f"{RUN_ID}.execution.consumed.json")
SUPERVISOR_ADMISSION_PATH = (
    SERVER / "runs/locks" / f"{RUN_ID}.supervisor.consumed.json")
AGGREGATE_ADMISSION_PATH = (
    SERVER / "runs/locks" / f"{RUN_ID}.aggregate.consumed.json")
SHARD_PATHS = tuple(RUN_DIR / f"shard-{index:02d}.json"
                    for index in range(SHARD_COUNT))
SHARD_LOG_PATHS = tuple(RUN_DIR / f"shard-{index:02d}.log"
                        for index in range(SHARD_COUNT))
SHARD_ADMISSION_PATHS = tuple(
    SERVER / "runs/locks" / f"{RUN_ID}.shard-{index:02d}.consumed.json"
    for index in range(SHARD_COUNT))
PROGRESS_EVERY = 16
MAX_SHARD_SECONDS = CAPACITY.BASE_MAX_SHARD_HOUR_CAP * 3_600.0


class ScreenRefused(RuntimeError):
    """The reviewed identity, one-shot boundary, or work contract drifted."""


def sha256(path: os.PathLike | str) -> str:
    return CAPACITY.sha256(path)


def stable_digest(value) -> str:
    return CAPACITY.stable_digest(value)


def git(*args: str) -> str:
    return CAPACITY.git(*args)


def write_exclusive(path: os.PathLike | str, payload: dict) -> None:
    try:
        CAPACITY.write_exclusive(path, payload)
    except CAPACITY.CapacityRefused as exc:
        raise ScreenRefused(str(exc)) from exc


def require_regular_unlinked(path: Path, *, label: str) -> None:
    try:
        CAPACITY.require_regular_unlinked(path, label=label)
    except CAPACITY.CapacityRefused as exc:
        raise ScreenRefused(str(exc)) from exc


def require_clean_exact_git(expected_git: str) -> None:
    if git("rev-parse", "HEAD") != expected_git:
        raise ScreenRefused("pair screen Git identity drift")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise ScreenRefused("pair screen refuses a dirty tree")


def require_exact_path(value: os.PathLike | str, expected: Path,
                       *, label: str) -> None:
    if Path(value).resolve(strict=False) != expected.resolve(strict=False):
        raise ScreenRefused(f"{label} singleton path drift")


def require_publishable(path: Path, *, label: str) -> None:
    if os.path.lexists(path) or os.path.lexists(str(path) + ".partial"):
        raise ScreenRefused(f"refusing existing {label}: {path}")


def parse_marker(path: os.PathLike | str, prefix: str,
                 expected: dict, *, label: str) -> dict:
    try:
        return CAPACITY.parse_marker(path, prefix, expected, label=label)
    except CAPACITY.CapacityRefused as exc:
        raise ScreenRefused(str(exc)) from exc


def load_json(path: Path, *, label: str) -> dict:
    require_regular_unlinked(path, label=label)
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ScreenRefused(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ScreenRefused(f"{label} is not an object")
    return value


def source_paths() -> dict[str, Path]:
    paths = CAPACITY.source_paths()
    paths.update({
        "screen_controller": SCRIPT,
        "capacity_result": CAPACITY_RESULT_PATH,
        "planning_review_record": PLANNING_REVIEW_PATH,
    })
    return paths


def source_sha256s() -> dict[str, str]:
    return {name: sha256(path) for name, path in sorted(source_paths().items())}


def planning_anchor() -> dict:
    require_regular_unlinked(
        PLANNING_REVIEW_PATH, label="pair screen planning review record")
    matches = [line[len(PLANNING_REVIEW_PREFIX):]
               for line in PLANNING_REVIEW_PATH.read_text().splitlines()
               if line.startswith(PLANNING_REVIEW_PREFIX)]
    if len(matches) != 1:
        raise ScreenRefused("pair screen planning review marker population")
    try:
        claim = json.loads(matches[0])
    except ValueError as exc:
        raise ScreenRefused("pair screen planning review marker malformed") \
            from exc
    contrast = claim.get("treatment_champion", {})
    if (claim.get("schema")
            != "s4-point-banking-replication-air-result-review-v1"
            or claim.get("aggregate_sha256")
            != "d6b73f45c17f1b7ae6e1648147b82d248df82fd0f5b35a82a601108e8ba8f4d4"
            or claim.get("clusters") != 2_048
            or claim.get("independent_review") is not True
            or claim.get("status") != "SELECT_NONE"
            or claim.get("verdict") != "PASS"
            or contrast.get("half_width95") != 0.055711812163936635):
        raise ScreenRefused("pair screen planning review marker drift")
    implied_sd = (
        contrast["half_width95"] / Z_ONE_SIDED_95
        * math.sqrt(claim["clusters"]))
    if not 1.5 < implied_sd < PLANNING_CLUSTER_SD:
        raise ScreenRefused("pair screen planning dispersion drift")
    return {
        "record_path": str(PLANNING_REVIEW_PATH.relative_to(REPO)),
        "record_sha256": sha256(PLANNING_REVIEW_PATH),
        "marker": PLANNING_REVIEW_PREFIX + matches[0],
        "source_clusters": claim["clusters"],
        "source_half_width95": contrast["half_width95"],
        "implied_cluster_sd": implied_sd,
    }


def planning_contract(elapsed_seconds: float) -> dict:
    if not math.isfinite(elapsed_seconds) or elapsed_seconds <= 0:
        raise ScreenRefused("capacity elapsed time is invalid")
    standard_error = PLANNING_CLUSTER_SD / math.sqrt(SCREEN_CLUSTERS)
    mde80 = ((Z_ONE_SIDED_95 + Z_POWER_80) * standard_error)
    power = 0.5 * (1.0 + math.erf(
        (TARGET_EFFECT / standard_error - Z_ONE_SIDED_95) / math.sqrt(2.0)))
    fleet_hours = (
        elapsed_seconds / CAPACITY.PREFLIGHT_CLUSTERS
        * SCREEN_CLUSTERS * CAPACITY.SAFETY_FACTOR / 3_600.0)
    max_shard_hours = fleet_hours / SHARD_COUNT
    return {
        "clusters": SCREEN_CLUSTERS,
        "shards": SHARD_COUNT,
        "clusters_per_shard": CLUSTERS_PER_SHARD,
        "one_sided_alpha": ONE_SIDED_ALPHA,
        "planning_cluster_sd": PLANNING_CLUSTER_SD,
        "planning_dispersion_anchor": planning_anchor(),
        "target_effect": TARGET_EFFECT,
        "standard_error_at_max": standard_error,
        "minimum_detectable_effect_80pct": mde80,
        "power_at_target_effect": power,
        "capacity_safety_factor": CAPACITY.SAFETY_FACTOR,
        "projected_fleet_hours": fleet_hours,
        "projected_max_shard_hours": max_shard_hours,
        "fleet_hour_cap": CAPACITY.BASE_FLEET_HOUR_CAP,
        "max_shard_hour_cap": CAPACITY.BASE_MAX_SHARD_HOUR_CAP,
        "within_reviewed_capacity": (
            fleet_hours <= CAPACITY.BASE_FLEET_HOUR_CAP
            and max_shard_hours <= CAPACITY.BASE_MAX_SHARD_HOUR_CAP),
    }


def capacity_evidence(*, result_path: Path,
                      capacity_review_record: Path) -> tuple[dict, dict]:
    require_exact_path(result_path, CAPACITY_RESULT_PATH,
                       label="pair capacity result")
    if sha256(result_path) != CAPACITY_RESULT_SHA256:
        raise ScreenRefused("pair capacity result SHA-256 drift")
    result = load_json(result_path, label="pair capacity result")
    unsigned = dict(result)
    observed_internal = unsigned.pop("internal_sha256", None)
    if (observed_internal != CAPACITY_RESULT_INTERNAL_SHA256
            or stable_digest(unsigned) != observed_internal
            or result.get("schema") != CAPACITY.RESULT_SCHEMA
            or result.get("capacity_pass") is not True
            or result.get("supports_screen_packet_review") is not True
            or result.get("screen_packet_design_authorized") is not False
            or result.get("screen_execution_authorized") is not False
            or result.get("strength_claim") is not False
            or result.get("packet_sha256") != CAPACITY_PACKET_SHA256
            or result.get("natural_dose", {}).get("root_action_changes") != 6
            or CAPACITY.score_free_result_problems(result)):
        raise ScreenRefused("pair capacity result identity/authority drift")
    claim = CAPACITY.capacity_review_claim(
        result=result, result_sha256=CAPACITY_RESULT_SHA256,
        packet_sha256=CAPACITY_PACKET_SHA256)
    review = parse_marker(
        capacity_review_record, CAPACITY.CAPACITY_REVIEW_PREFIX, claim,
        label="pair capacity result review")
    if claim.get("one_screen_packet_design_authorized") is not True \
            or claim.get("screen_execution_authorized") is not False:
        raise ScreenRefused("capacity review authority drift")
    return result, review


def packet_payload(*, expected_git: str, result_path: Path,
                   capacity_review_record: Path) -> dict:
    if not CAPACITY.git_is_ancestor(result_path_payload_git(result_path),
                                    expected_git):
        raise ScreenRefused("capacity source is not an ancestor of screen")
    result, review = capacity_evidence(
        result_path=result_path,
        capacity_review_record=capacity_review_record)
    planning = planning_contract(float(result["elapsed_seconds"]))
    if planning["within_reviewed_capacity"] is not True \
            or planning["minimum_detectable_effect_80pct"] > TARGET_EFFECT:
        raise ScreenRefused("pair screen is underpowered or over capacity")
    payload = {
        "schema": PACKET_SCHEMA,
        "run_id": RUN_ID,
        "git": expected_git,
        "source_sha256s": source_sha256s(),
        "runtime": CAPACITY.require_air_runtime(),
        "policy_contracts": CAPACITY.policy_contracts(),
        "capacity_result": {
            "path": str(result_path.relative_to(REPO)),
            "sha256": CAPACITY_RESULT_SHA256,
            "internal_sha256": CAPACITY_RESULT_INTERNAL_SHA256,
            "review_record_sha256": review["sha256"],
            "review_marker": review["marker"],
        },
        "screen": {
            "seed0": SCREEN_SEED0,
            "clusters": SCREEN_CLUSTERS,
            "shards": SHARD_COUNT,
            "clusters_per_shard": CLUSTERS_PER_SHARD,
            "stream_stride": STREAM_STRIDE,
            "labels": list(CORE.LABEL_ORDER),
            "primary_metric": "mirrored mean signed level utility",
            "primary_contrasts": [
                "treatment_minus_matched_null",
                "treatment_minus_champion",
            ],
            "secondary_metric": "mirrored game win rate",
            "decision_rule": (
                "PASS_SCREEN iff both primary one-sided 95% lower bounds "
                "are positive, matched-null equals champion exactly, pair "
                "dose covers both roles, and all integrity gates pass"),
            "population": "fresh fixed deal stream; no retry or extension",
            "shard_paths": [str(path.relative_to(REPO))
                            for path in SHARD_PATHS],
            "shard_log_paths": [str(path.relative_to(REPO))
                                for path in SHARD_LOG_PATHS],
            "receipt_path": str(RECEIPT_PATH.relative_to(REPO)),
            "supervisor_final_path": str(
                SUPERVISOR_FINAL_PATH.relative_to(REPO)),
            "aggregate_path": str(AGGREGATE_PATH.relative_to(REPO)),
        },
        "planning": planning,
        "authority": {
            "screen_execution_authorized": False,
            "aggregate_execution_authorized": False,
            "confirmation_packet_design_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
            "retry_or_extension_authorized": False,
        },
    }
    payload["internal_sha256"] = stable_digest(payload)
    return payload


def result_path_payload_git(result_path: Path) -> str:
    result = load_json(result_path, label="pair capacity result")
    value = result.get("git")
    if not isinstance(value, str) or len(value) != 40:
        raise ScreenRefused("capacity result Git drift")
    return value


def packet_review_claim(packet: dict, packet_sha256: str) -> dict:
    return {
        "clusters": SCREEN_CLUSTERS,
        "git": packet["git"],
        "independent_review": True,
        "one_screen_execution_authorized": True,
        "packet_sha256": packet_sha256,
        "production_deployment": False,
        "production_promotion": False,
        "retry_or_extension_authorized": False,
        "run_id": RUN_ID,
        "schema": "pair-aware-rollout-screen-packet-review-v1",
        "shards": SHARD_COUNT,
        "strength_claim": False,
        "verdict": "PASS",
    }


def load_packet(path: Path, expected_sha256: str, *, expected_git: str,
                result_path: Path, capacity_review_record: Path) -> dict:
    require_exact_path(path, PACKET_PATH, label="pair screen packet")
    if sha256(path) != expected_sha256:
        raise ScreenRefused("pair screen packet SHA-256 drift")
    value = load_json(path, label="pair screen packet")
    expected = packet_payload(
        expected_git=expected_git, result_path=result_path,
        capacity_review_record=capacity_review_record)
    if value != expected:
        raise ScreenRefused("pair screen packet reconstruction drift")
    return value


def receipt_payload(packet: dict, packet_sha256: str,
                    packet_review: dict) -> dict:
    value = {
        "schema": RECEIPT_SCHEMA,
        "run_id": RUN_ID,
        "git": packet["git"],
        "packet_sha256": packet_sha256,
        "packet_internal_sha256": packet["internal_sha256"],
        "packet_review_record_sha256": packet_review["sha256"],
        "packet_review_marker": packet_review["marker"],
        "execution_admission_path": str(
            EXECUTION_ADMISSION_PATH.relative_to(REPO)),
        "nonce": secrets.token_hex(32),
        "created_time_ns": time.time_ns(),
        "one_screen_execution_authorized": True,
        "aggregate_execution_authorized": False,
        "strength_claim": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    value["internal_sha256"] = stable_digest(value)
    return value


def load_receipt(path: Path, expected_sha256: str, *, packet: dict,
                 packet_sha256: str, packet_review_record: Path) -> dict:
    require_exact_path(path, RECEIPT_PATH, label="pair screen receipt")
    if sha256(path) != expected_sha256:
        raise ScreenRefused("pair screen receipt SHA-256 drift")
    value = load_json(path, label="pair screen receipt")
    unsigned = dict(value)
    observed = unsigned.pop("internal_sha256", None)
    claim = packet_review_claim(packet, packet_sha256)
    review = parse_marker(
        packet_review_record, PACKET_REVIEW_PREFIX, claim,
        label="pair screen packet review")
    require_regular_unlinked(
        EXECUTION_ADMISSION_PATH, label="pair screen execution admission")
    if (observed != stable_digest(unsigned)
            or value.get("schema") != RECEIPT_SCHEMA
            or value.get("run_id") != RUN_ID
            or value.get("git") != packet["git"]
            or value.get("packet_sha256") != packet_sha256
            or value.get("packet_internal_sha256")
            != packet["internal_sha256"]
            or value.get("packet_review_record_sha256") != review["sha256"]
            or value.get("packet_review_marker") != review["marker"]
            or value.get("execution_admission_path")
            != str(EXECUTION_ADMISSION_PATH.relative_to(REPO))
            or not isinstance(value.get("execution_admission_sha256"), str)
            or len(value["execution_admission_sha256"]) != 64
            or value.get("execution_admission_sha256")
            != sha256(EXECUTION_ADMISSION_PATH)
            or value.get("one_screen_execution_authorized") is not True
            or value.get("aggregate_execution_authorized") is not False
            or value.get("strength_claim") is not False
            or value.get("retry_or_extension_authorized") is not False):
        raise ScreenRefused("pair screen receipt identity/authority drift")
    return value


def _plain_totals(records: list[dict], side: str) -> dict:
    names = set(CAPACITY.CORE.counters([]))
    totals = {name: 0.0 if name == "search_secs" else 0 for name in names}
    for record in records:
        for name in names:
            totals[name] += record[side][name]
    return totals


def _pair_totals(records: list[dict], side: str) -> dict:
    modes = {record[side]["pair_aware"]["mode"] for record in records}
    if len(modes) != 1:
        raise ScreenRefused("pair screen telemetry mode drift")
    totals = Counter({field: 0 for field in CAPACITY.PAIR_AWARE_COUNTER_FIELDS})
    for record in records:
        totals.update({field: record[side]["pair_aware"][field]
                       for field in CAPACITY.PAIR_AWARE_COUNTER_FIELDS})
    return {"mode": next(iter(modes)), **dict(totals)}


def cluster_row(*, cluster_index: int, seed: int,
                by_label: dict[str, list[dict]]) -> dict:
    if set(by_label) != set(CORE.LABEL_ORDER):
        raise ScreenRefused("pair screen arm population drift")
    for label, records in by_label.items():
        if len(records) != 2:
            raise ScreenRefused("pair screen mirror population drift")
        for flip, record in enumerate(records):
            problems = CORE.record_problems(
                record, expected_label=label, expected_seed=seed,
                expected_flip=flip, expected_run_id=RUN_ID)
            if problems:
                raise ScreenRefused(
                    "invalid pair screen row: " + "; ".join(problems))
    for null, champion in zip(
            by_label["matched_null"], by_label["champion"], strict=True):
        problems = CORE.matched_null_champion_problems(null, champion)
        if problems:
            raise ScreenRefused("; ".join(problems))
    dose = [CORE.natural_root_dose(treatment, null)
            for treatment, null in zip(
                by_label["treatment"], by_label["matched_null"], strict=True)]
    return {
        "cluster_index": cluster_index,
        "seed": seed,
        "level_utility": {
            label: [int(row["level_utility"]) for row in by_label[label]]
            for label in CORE.LABEL_ORDER
        },
        "won": {
            label: [int(row["won"]) for row in by_label[label]]
            for label in CORE.LABEL_ORDER
        },
        "natural_dose": dose,
    }


def _dose_summary(rows: list[dict]) -> dict:
    doses = [dose for row in rows for dose in row["natural_dose"]]
    expected_fields = {
        "shared_prefix_plays", "root_action_changed", "change_play_index",
        "change_phase", "change_role",
    }
    for dose in doses:
        if not isinstance(dose, dict):
            raise ScreenRefused("pair screen natural-dose shape drift")
        changed = dose.get("root_action_changed")
        if (set(dose) != expected_fields
                or not isinstance(dose.get("shared_prefix_plays"), int)
                or isinstance(dose.get("shared_prefix_plays"), bool)
                or not 0 <= dose["shared_prefix_plays"] <= 100
                or not isinstance(changed, bool)):
            raise ScreenRefused("pair screen natural-dose shape drift")
        if changed:
            if (not isinstance(dose.get("change_play_index"), int)
                    or dose["change_play_index"]
                    != dose["shared_prefix_plays"]
                    or dose.get("change_phase")
                    not in {"early", "mid", "late"}
                    or dose.get("change_role")
                    not in {"attacker", "defender"}):
                raise ScreenRefused("pair screen changed-dose identity drift")
        elif any(dose.get(field) is not None for field in (
                "change_play_index", "change_phase", "change_role")):
            raise ScreenRefused("pair screen unchanged-dose identity drift")
    changes = [dose for dose in doses if dose["root_action_changed"]]
    phases = Counter(dose["change_phase"] for dose in changes)
    roles = Counter(dose["change_role"] for dose in changes)
    return {
        "complete_round_pairs": len(doses),
        "root_action_changes": len(changes),
        "rounds_without_root_change": len(doses) - len(changes),
        "shared_prefix_plays": sum(
            dose["shared_prefix_plays"] for dose in doses),
        "changes_by_phase": {
            phase: int(phases[phase]) for phase in ("early", "mid", "late")
        },
        "changes_by_role": {
            role: int(roles[role]) for role in ("attacker", "defender")
        },
        "matched_null_champion_exact_histories": True,
    }


def run_shard_payload(*, packet: dict, packet_sha256: str,
                      receipt_sha256: str, shard_index: int,
                      progress_every: int = PROGRESS_EVERY) -> dict:
    if not 0 <= shard_index < SHARD_COUNT:
        raise ScreenRefused("pair screen shard index drift")
    started = time.perf_counter()
    rows = []
    all_records = {label: [] for label in CORE.LABEL_ORDER}
    first = shard_index * CLUSTERS_PER_SHARD
    for local_index in range(CLUSTERS_PER_SHARD):
        cluster_index = first + local_index
        seed = SCREEN_SEED0 + STREAM_STRIDE * cluster_index
        by_label = {
            label: CORE.play_arm_cluster(label, seed, run_id=RUN_ID)
            for label in CORE.LABEL_ORDER
        }
        rows.append(cluster_row(
            cluster_index=cluster_index, seed=seed, by_label=by_label))
        for label in CORE.LABEL_ORDER:
            all_records[label].extend(by_label[label])
        if (local_index + 1) % progress_every == 0 \
                or local_index + 1 == CLUSTERS_PER_SHARD:
            print(json.dumps({
                "event": "pair-aware-rollout-screen-progress-v1",
                "shard_index": shard_index,
                "clusters_complete": local_index + 1,
                "clusters_total": CLUSTERS_PER_SHARD,
            }, sort_keys=True), flush=True)
    elapsed = time.perf_counter() - started
    counts = {
        label: {
            "records": len(records),
            "arm": _plain_totals(records, "arm"),
            "opp": _plain_totals(records, "opp"),
            "arm_pair": _pair_totals(records, "arm"),
            "opp_pair": _pair_totals(records, "opp"),
        }
        for label, records in all_records.items()
    }
    value = {
        "schema": SHARD_SCHEMA,
        "run_id": RUN_ID,
        "git": packet["git"],
        "packet_sha256": packet_sha256,
        "packet_internal_sha256": packet["internal_sha256"],
        "receipt_sha256": receipt_sha256,
        "shard_index": shard_index,
        "cluster_index_start": first,
        "clusters": CLUSTERS_PER_SHARD,
        "seed0": SCREEN_SEED0 + STREAM_STRIDE * first,
        "stream_stride": STREAM_STRIDE,
        "elapsed_seconds": elapsed,
        "cluster_rows": rows,
        "counts": counts,
        "natural_dose": _dose_summary(rows),
        "exact_work_complete": True,
        "aggregate_execution_authorized": False,
        "strength_claim": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    value["internal_sha256"] = stable_digest(value)
    return value


def _integer_pair(value: object, allowed: range) -> bool:
    return (isinstance(value, list) and len(value) == 2
            and all(isinstance(item, int) and not isinstance(item, bool)
                    and item in allowed for item in value))


def validate_shard(value: dict, *, packet: dict, packet_sha256: str,
                   receipt_sha256: str, shard_index: int) -> None:
    unsigned = dict(value)
    observed = unsigned.pop("internal_sha256", None)
    first = shard_index * CLUSTERS_PER_SHARD
    rows = value.get("cluster_rows")
    if (observed != stable_digest(unsigned)
            or value.get("schema") != SHARD_SCHEMA
            or value.get("run_id") != RUN_ID
            or value.get("git") != packet["git"]
            or value.get("packet_sha256") != packet_sha256
            or value.get("packet_internal_sha256")
            != packet["internal_sha256"]
            or value.get("receipt_sha256") != receipt_sha256
            or value.get("shard_index") != shard_index
            or value.get("cluster_index_start") != first
            or value.get("clusters") != CLUSTERS_PER_SHARD
            or value.get("seed0") != SCREEN_SEED0 + STREAM_STRIDE * first
            or value.get("stream_stride") != STREAM_STRIDE
            or not isinstance(value.get("elapsed_seconds"), (int, float))
            or not math.isfinite(value["elapsed_seconds"])
            or value["elapsed_seconds"] <= 0
            or not isinstance(rows, list)
            or len(rows) != CLUSTERS_PER_SHARD
            or value.get("exact_work_complete") is not True
            or value.get("aggregate_execution_authorized") is not False
            or value.get("strength_claim") is not False
            or value.get("retry_or_extension_authorized") is not False):
        raise ScreenRefused(f"pair screen shard {shard_index} identity drift")
    for local_index, row in enumerate(rows):
        cluster_index = first + local_index
        seed = SCREEN_SEED0 + STREAM_STRIDE * cluster_index
        utility = row.get("level_utility", {})
        won = row.get("won", {})
        if (row.get("cluster_index") != cluster_index
                or row.get("seed") != seed
                or set(utility) != set(CORE.LABEL_ORDER)
                or set(won) != set(CORE.LABEL_ORDER)
                or not all(_integer_pair(utility[label], range(-101, 102))
                           for label in CORE.LABEL_ORDER)
                or not all(_integer_pair(won[label], range(0, 2))
                           for label in CORE.LABEL_ORDER)
                or utility["matched_null"] != utility["champion"]
                or won["matched_null"] != won["champion"]
                or not isinstance(row.get("natural_dose"), list)
                or len(row["natural_dose"]) != 2):
            raise ScreenRefused(
                f"pair screen shard {shard_index} cluster-row drift")
    if value.get("natural_dose") != _dose_summary(rows):
        raise ScreenRefused(f"pair screen shard {shard_index} dose drift")
    counts = value.get("counts")
    if not isinstance(counts, dict) or set(counts) != set(CORE.LABEL_ORDER):
        raise ScreenRefused(f"pair screen shard {shard_index} counts drift")
    plain_fields = set(CORE.counters([]))
    for label, expected_mode in (
            ("treatment", "treatment"),
            ("matched_null", "matched_null"),
            ("champion", "off")):
        item = counts[label]
        if (not isinstance(item, dict)
                or set(item) != {"records", "arm", "opp", "arm_pair",
                                 "opp_pair"}
                or item["records"] != 2 * CLUSTERS_PER_SHARD
                or set(item["arm"]) != plain_fields
                or set(item["opp"]) != plain_fields
                or CORE.telemetry_problems(
                    item["arm_pair"], expected_mode=expected_mode)
                or CORE.telemetry_problems(
                    item["opp_pair"], expected_mode="off")):
            raise ScreenRefused(
                f"pair screen shard {shard_index} {label} work drift")
        for side in ("arm", "opp"):
            counters = item[side]
            for name, counter in counters.items():
                valid = ((name == "search_secs"
                          and isinstance(counter, (int, float))
                          and not isinstance(counter, bool)
                          and math.isfinite(counter) and counter >= 0)
                         or (name != "search_secs"
                             and isinstance(counter, int)
                             and not isinstance(counter, bool)
                             and counter >= 0))
                if not valid:
                    raise ScreenRefused(
                        f"pair screen shard {shard_index} counter drift")
            if counters["sample_attempts"] != (
                    counters["accepted_worlds"] + counters["failed_worlds"]):
                raise ScreenRefused(
                    f"pair screen shard {shard_index} sampler drift")
            if counters["accepted_worlds"] != (
                    (CORE.ROOT_WORLDS + CORE.REPORT_WORLDS)
                    * counters["searches"]):
                raise ScreenRefused(
                    f"pair screen shard {shard_index} search dose drift")


def paired_stats(values: list[float]) -> dict:
    if len(values) < 2 or any(not math.isfinite(value) for value in values):
        raise ScreenRefused("pair screen statistic population drift")
    n = len(values)
    mean = sum(values) / n
    variance = sum((value - mean) ** 2 for value in values) / (n - 1)
    se = math.sqrt(variance / n)
    return {
        "n": n,
        "mean": mean,
        "sample_sd": math.sqrt(variance),
        "se": se,
        "lcb_one_sided_95": mean - Z_ONE_SIDED_95 * se,
        "wins": sum(value > 0 for value in values),
        "losses": sum(value < 0 for value in values),
        "ties": sum(value == 0 for value in values),
    }


def aggregate_payload(*, packet: dict, packet_sha256: str,
                      receipt_sha256: str, shard_values: list[dict],
                      shard_sha256s: list[str], supervisor_final_sha256: str,
                      supervisor_review: dict) -> dict:
    if len(shard_values) != SHARD_COUNT or len(shard_sha256s) != SHARD_COUNT:
        raise ScreenRefused("pair screen aggregate shard population drift")
    for index, value in enumerate(shard_values):
        validate_shard(
            value, packet=packet, packet_sha256=packet_sha256,
            receipt_sha256=receipt_sha256, shard_index=index)
    rows = [row for shard in shard_values for row in shard["cluster_rows"]]
    if len(rows) != SCREEN_CLUSTERS:
        raise ScreenRefused("pair screen aggregate cluster population drift")

    def mirrored(row: dict, label: str, metric: str) -> float:
        return sum(row[metric][label]) / 2.0

    utility_tn = [mirrored(row, "treatment", "level_utility")
                  - mirrored(row, "matched_null", "level_utility")
                  for row in rows]
    utility_tc = [mirrored(row, "treatment", "level_utility")
                  - mirrored(row, "champion", "level_utility")
                  for row in rows]
    utility_nc = [mirrored(row, "matched_null", "level_utility")
                  - mirrored(row, "champion", "level_utility")
                  for row in rows]
    win_tc = [mirrored(row, "treatment", "won")
              - mirrored(row, "champion", "won") for row in rows]
    dose = _dose_summary(rows)
    primary = {
        "treatment_minus_matched_null": paired_stats(utility_tn),
        "treatment_minus_champion": paired_stats(utility_tc),
        "matched_null_minus_champion": paired_stats(utility_nc),
    }
    controls_exact = all(value == 0 for value in utility_nc)
    both_roles = all(value > 0 for value in dose["changes_by_role"].values())
    passed = (
        controls_exact and both_roles
        and primary["treatment_minus_matched_null"]
        ["lcb_one_sided_95"] > 0
        and primary["treatment_minus_champion"]
        ["lcb_one_sided_95"] > 0)
    value = {
        "schema": AGGREGATE_SCHEMA,
        "run_id": RUN_ID,
        "git": packet["git"],
        "packet_sha256": packet_sha256,
        "receipt_sha256": receipt_sha256,
        "supervisor_final_sha256": supervisor_final_sha256,
        "supervisor_review_record_sha256": supervisor_review["sha256"],
        "supervisor_review_marker": supervisor_review["marker"],
        "clusters": SCREEN_CLUSTERS,
        "shards": SHARD_COUNT,
        "shard_sha256s": shard_sha256s,
        "primary_level_utility": primary,
        "secondary_game_win_rate": {
            "treatment_minus_champion": paired_stats(win_tc),
        },
        "natural_dose": dose,
        "integrity": {
            "matched_null_champion_exact": controls_exact,
            "both_roles_changed": both_roles,
            "all_shards_exact_work": all(
                shard["exact_work_complete"] is True
                for shard in shard_values),
        },
        "status": "PASS_SCREEN" if passed else "SELECT_NONE",
        "screen_passed": passed,
        "confirmation_packet_design_authorized": passed,
        "confirmation_execution_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    value["internal_sha256"] = stable_digest(value)
    return value


def _slot_payload(*, schema: str, packet: dict, packet_sha256: str,
                  receipt_sha256: str | None = None,
                  shard_index: int | None = None) -> dict:
    value = {
        "schema": schema,
        "run_id": RUN_ID,
        "git": packet["git"],
        "packet_sha256": packet_sha256,
        "nonce": secrets.token_hex(32),
        "created_time_ns": time.time_ns(),
        "retry_or_extension_authorized": False,
        "production_deployment": False,
    }
    if receipt_sha256 is not None:
        value["receipt_sha256"] = receipt_sha256
    if shard_index is not None:
        value["shard_index"] = shard_index
    value["internal_sha256"] = stable_digest(value)
    return value


def freeze_command(args) -> None:
    require_clean_exact_git(args.expected_git)
    require_exact_path(args.out, PACKET_PATH, label="pair screen packet")
    payload = packet_payload(
        expected_git=args.expected_git,
        result_path=Path(args.capacity_result),
        capacity_review_record=Path(args.capacity_review_record))
    write_exclusive(args.out, payload)
    packet_sha = sha256(args.out)
    print(json.dumps({
        "status": "FROZEN_FOR_PACKET_REVIEW",
        "packet_sha256": packet_sha,
        "packet_internal_sha256": payload["internal_sha256"],
        "packet_review_claim": packet_review_claim(payload, packet_sha),
    }, sort_keys=True))


def verify_command(args) -> None:
    require_clean_exact_git(args.expected_git)
    packet = load_packet(
        Path(args.packet), args.expected_packet_sha256,
        expected_git=args.expected_git,
        result_path=Path(args.capacity_result),
        capacity_review_record=Path(args.capacity_review_record))
    print(json.dumps({"status": "VERIFIED",
                      "packet_internal_sha256": packet["internal_sha256"]},
                     sort_keys=True))


def admit_command(args) -> None:
    require_clean_exact_git(args.expected_git)
    CAPACITY.require_compiled_strict_runtime()
    require_exact_path(args.admission, EXECUTION_ADMISSION_PATH,
                       label="pair screen execution admission")
    require_exact_path(args.out, RECEIPT_PATH, label="pair screen receipt")
    for path in (
            args.admission, args.out, SUPERVISOR_ADMISSION_PATH,
            SUPERVISOR_FINAL_PATH, AGGREGATE_ADMISSION_PATH, AGGREGATE_PATH,
            *SHARD_PATHS, *SHARD_LOG_PATHS, *SHARD_ADMISSION_PATHS):
        require_publishable(Path(path), label="pair screen namespace")
    packet = load_packet(
        Path(args.packet), args.expected_packet_sha256,
        expected_git=args.expected_git,
        result_path=Path(args.capacity_result),
        capacity_review_record=Path(args.capacity_review_record))
    claim = packet_review_claim(packet, args.expected_packet_sha256)
    review = parse_marker(
        args.packet_review_record, PACKET_REVIEW_PREFIX, claim,
        label="pair screen packet review")
    admission = _slot_payload(
        schema="pair-aware-rollout-screen-execution-admission-v1",
        packet=packet, packet_sha256=args.expected_packet_sha256)
    admission["packet_review_record_sha256"] = review["sha256"]
    admission.pop("internal_sha256")
    admission["internal_sha256"] = stable_digest(admission)
    write_exclusive(args.admission, admission)
    receipt = receipt_payload(packet, args.expected_packet_sha256, review)
    receipt["execution_admission_sha256"] = sha256(args.admission)
    receipt.pop("internal_sha256")
    receipt["internal_sha256"] = stable_digest(receipt)
    write_exclusive(args.out, receipt)
    print(json.dumps({"status": "SCREEN_ADMITTED",
                      "receipt_sha256": sha256(args.out)}, sort_keys=True))


def _common(args) -> tuple[dict, dict]:
    packet = load_packet(
        Path(args.packet), args.expected_packet_sha256,
        expected_git=args.expected_git,
        result_path=Path(args.capacity_result),
        capacity_review_record=Path(args.capacity_review_record))
    receipt = load_receipt(
        Path(args.screen_receipt), args.expected_screen_receipt_sha256,
        packet=packet, packet_sha256=args.expected_packet_sha256,
        packet_review_record=Path(args.packet_review_record))
    return packet, receipt


def shard_command(args) -> None:
    require_clean_exact_git(args.expected_git)
    CAPACITY.require_compiled_strict_runtime()
    if not 0 <= args.shard_index < SHARD_COUNT:
        raise ScreenRefused("pair screen shard index drift")
    require_exact_path(args.admission, SHARD_ADMISSION_PATHS[args.shard_index],
                       label="pair screen shard admission")
    require_exact_path(args.out, SHARD_PATHS[args.shard_index],
                       label="pair screen shard output")
    require_publishable(Path(args.admission), label="pair screen shard admission")
    require_publishable(Path(args.out), label="pair screen shard output")
    packet, _ = _common(args)
    slot = _slot_payload(
        schema="pair-aware-rollout-screen-shard-admission-v1",
        packet=packet, packet_sha256=args.expected_packet_sha256,
        receipt_sha256=args.expected_screen_receipt_sha256,
        shard_index=args.shard_index)
    write_exclusive(args.admission, slot)
    value = run_shard_payload(
        packet=packet, packet_sha256=args.expected_packet_sha256,
        receipt_sha256=args.expected_screen_receipt_sha256,
        shard_index=args.shard_index)
    value["shard_admission_sha256"] = sha256(args.admission)
    value.pop("internal_sha256")
    value["internal_sha256"] = stable_digest(value)
    write_exclusive(args.out, value)
    print(json.dumps({
        "status": "SHARD_COMPLETE",
        "shard_index": args.shard_index,
        "shard_sha256": sha256(args.out),
    }, sort_keys=True))


def _child_argv(args, index: int) -> list[str]:
    return [
        sys.executable, str(SCRIPT), "run-shard",
        "--expected-git", args.expected_git,
        "--capacity-result", args.capacity_result,
        "--capacity-review-record", args.capacity_review_record,
        "--packet", args.packet,
        "--expected-packet-sha256", args.expected_packet_sha256,
        "--packet-review-record", args.packet_review_record,
        "--screen-receipt", args.screen_receipt,
        "--expected-screen-receipt-sha256",
        args.expected_screen_receipt_sha256,
        "--shard-index", str(index),
        "--admission", str(SHARD_ADMISSION_PATHS[index]),
        "--out", str(SHARD_PATHS[index]),
    ]


def supervisor_review_claim(packet: dict, packet_sha256: str,
                            receipt_sha256: str, final: dict,
                            final_sha256: str) -> dict:
    return {
        "all_shards_complete": final["all_shards_complete"],
        "git": packet["git"],
        "independent_review": True,
        "one_aggregate_authorized": final["all_shards_complete"],
        "packet_sha256": packet_sha256,
        "production_deployment": False,
        "production_promotion": False,
        "receipt_sha256": receipt_sha256,
        "run_id": RUN_ID,
        "schema": "pair-aware-rollout-screen-supervisor-review-v1",
        "shards": SHARD_COUNT,
        "strength_claim": False,
        "supervisor_final_sha256": final_sha256,
        "verdict": "PASS" if final["all_shards_complete"] else "HOLD",
    }


def validate_supervisor_final(value: dict, *, packet: dict,
                              packet_sha256: str,
                              receipt_sha256: str) -> None:
    unsigned = dict(value)
    observed = unsigned.pop("internal_sha256", None)
    refs = value.get("shards")
    if (observed != stable_digest(unsigned)
            or value.get("schema") != SUPERVISOR_SCHEMA
            or value.get("run_id") != RUN_ID
            or value.get("git") != packet["git"]
            or value.get("packet_sha256") != packet_sha256
            or value.get("receipt_sha256") != receipt_sha256
            or value.get("supervisor_admission_sha256")
            != sha256(SUPERVISOR_ADMISSION_PATH)
            or not isinstance(value.get("elapsed_seconds"), (int, float))
            or not math.isfinite(value["elapsed_seconds"])
            or value["elapsed_seconds"] <= 0
            or not isinstance(refs, list) or len(refs) != SHARD_COUNT
            or value.get("all_shards_complete") is not True
            or value.get("outcomes_published") is not False
            or value.get("statistics_published") is not False
            or value.get("aggregate_execution_authorized") is not False
            or value.get("strength_claim") is not False
            or value.get("production_deployment") is not False
            or value.get("retry_or_extension_authorized") is not False):
        raise ScreenRefused("pair screen supervisor-final identity drift")
    for index, ref in enumerate(refs):
        expected_path = str(SHARD_PATHS[index].relative_to(REPO))
        expected_log = str(SHARD_LOG_PATHS[index].relative_to(REPO))
        if (not isinstance(ref, dict)
                or ref.get("index") != index
                or ref.get("path") != expected_path
                or ref.get("clusters") != CLUSTERS_PER_SHARD
                or ref.get("log_path") != expected_log
                or ref.get("sha256") != sha256(SHARD_PATHS[index])
                or ref.get("log_sha256") != sha256(SHARD_LOG_PATHS[index])):
            raise ScreenRefused(
                f"pair screen supervisor shard {index} reference drift")


def supervise_command(args) -> None:
    require_clean_exact_git(args.expected_git)
    CAPACITY.require_compiled_strict_runtime()
    require_exact_path(args.admission, SUPERVISOR_ADMISSION_PATH,
                       label="pair screen supervisor admission")
    require_exact_path(args.out, SUPERVISOR_FINAL_PATH,
                       label="pair screen supervisor final")
    packet, _ = _common(args)
    for path in (
            args.admission, args.out, AGGREGATE_ADMISSION_PATH, AGGREGATE_PATH,
            *SHARD_PATHS, *SHARD_LOG_PATHS, *SHARD_ADMISSION_PATHS):
        require_publishable(Path(path), label="pair screen supervisor namespace")
    slot = _slot_payload(
        schema="pair-aware-rollout-screen-supervisor-admission-v1",
        packet=packet, packet_sha256=args.expected_packet_sha256,
        receipt_sha256=args.expected_screen_receipt_sha256)
    write_exclusive(args.admission, slot)
    processes: dict[int, tuple[subprocess.Popen, object]] = {}
    started = time.monotonic()
    interrupted = {"signal": None}

    def handle_signal(signum, _frame):
        interrupted["signal"] = int(signum)

    old_handlers = {
        signum: signal.signal(signum, handle_signal)
        for signum in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        for index in range(SHARD_COUNT):
            SHARD_LOG_PATHS[index].parent.mkdir(parents=True, exist_ok=True)
            handle = SHARD_LOG_PATHS[index].open("xb")
            process = subprocess.Popen(
                _child_argv(args, index), stdout=handle,
                stderr=subprocess.STDOUT, cwd=REPO)
            processes[index] = (process, handle)
        last_heartbeat = 0.0
        while True:
            if interrupted["signal"] is not None:
                raise ScreenRefused(
                    f"pair supervisor received signal {interrupted['signal']}")
            codes = {index: process.poll()
                     for index, (process, _handle) in processes.items()}
            failed = {index: code for index, code in codes.items()
                      if code not in (None, 0)}
            if failed:
                raise ScreenRefused(f"pair screen child failure: {failed}")
            if all(code == 0 for code in codes.values()):
                break
            if time.monotonic() - started > MAX_SHARD_SECONDS + 300.0:
                raise ScreenRefused("pair screen supervisor timeout")
            if time.monotonic() - last_heartbeat >= 30.0:
                print(json.dumps({
                    "event": "pair-aware-rollout-supervisor-progress-v1",
                    "shards_complete": sum(code == 0 for code in codes.values()),
                    "shards_total": SHARD_COUNT,
                    "workers_alive": sum(code is None for code in codes.values()),
                }, sort_keys=True), flush=True)
                last_heartbeat = time.monotonic()
            time.sleep(1.0)
        shard_refs = []
        for index, path in enumerate(SHARD_PATHS):
            value = load_json(path, label=f"pair screen shard {index}")
            validate_shard(
                value, packet=packet,
                packet_sha256=args.expected_packet_sha256,
                receipt_sha256=args.expected_screen_receipt_sha256,
                shard_index=index)
            shard_refs.append({
                "index": index,
                "path": str(path.relative_to(REPO)),
                "sha256": sha256(path),
                "clusters": CLUSTERS_PER_SHARD,
                "log_path": str(SHARD_LOG_PATHS[index].relative_to(REPO)),
                "log_sha256": sha256(SHARD_LOG_PATHS[index]),
            })
        final = {
            "schema": SUPERVISOR_SCHEMA,
            "run_id": RUN_ID,
            "git": packet["git"],
            "packet_sha256": args.expected_packet_sha256,
            "receipt_sha256": args.expected_screen_receipt_sha256,
            "supervisor_admission_sha256": sha256(args.admission),
            "elapsed_seconds": time.monotonic() - started,
            "shards": shard_refs,
            "all_shards_complete": True,
            "outcomes_published": False,
            "statistics_published": False,
            "aggregate_execution_authorized": False,
            "strength_claim": False,
            "production_deployment": False,
            "retry_or_extension_authorized": False,
        }
        final["internal_sha256"] = stable_digest(final)
        write_exclusive(args.out, final)
        final_sha = sha256(args.out)
        print(json.dumps({
            "status": "SUPERVISOR_COMPLETE_AWAITING_REVIEW",
            "supervisor_final_sha256": final_sha,
            "supervisor_review_claim": supervisor_review_claim(
                packet, args.expected_packet_sha256,
                args.expected_screen_receipt_sha256, final, final_sha),
        }, sort_keys=True))
    finally:
        for process, handle in processes.values():
            if process.poll() is None:
                process.terminate()
        for process, handle in processes.values():
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            handle.close()
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)


def aggregate_command(args) -> None:
    require_clean_exact_git(args.expected_git)
    CAPACITY.require_compiled_strict_runtime()
    require_exact_path(args.admission, AGGREGATE_ADMISSION_PATH,
                       label="pair screen aggregate admission")
    require_exact_path(args.out, AGGREGATE_PATH,
                       label="pair screen aggregate")
    require_publishable(Path(args.admission),
                        label="pair screen aggregate admission")
    require_publishable(Path(args.out), label="pair screen aggregate")
    packet, _ = _common(args)
    require_exact_path(args.supervisor_final, SUPERVISOR_FINAL_PATH,
                       label="pair screen supervisor final")
    final = load_json(
        Path(args.supervisor_final), label="pair screen supervisor final")
    final_sha = sha256(args.supervisor_final)
    validate_supervisor_final(
        final, packet=packet, packet_sha256=args.expected_packet_sha256,
        receipt_sha256=args.expected_screen_receipt_sha256)
    claim = supervisor_review_claim(
        packet, args.expected_packet_sha256,
        args.expected_screen_receipt_sha256, final, final_sha)
    review = parse_marker(
        args.supervisor_review_record, SUPERVISOR_REVIEW_PREFIX, claim,
        label="pair screen supervisor review")
    slot = _slot_payload(
        schema="pair-aware-rollout-screen-aggregate-admission-v1",
        packet=packet, packet_sha256=args.expected_packet_sha256,
        receipt_sha256=args.expected_screen_receipt_sha256)
    slot["supervisor_review_record_sha256"] = review["sha256"]
    slot.pop("internal_sha256")
    slot["internal_sha256"] = stable_digest(slot)
    write_exclusive(args.admission, slot)
    shards = [load_json(path, label=f"pair screen shard {index}")
              for index, path in enumerate(SHARD_PATHS)]
    value = aggregate_payload(
        packet=packet, packet_sha256=args.expected_packet_sha256,
        receipt_sha256=args.expected_screen_receipt_sha256,
        shard_values=shards,
        shard_sha256s=[sha256(path) for path in SHARD_PATHS],
        supervisor_final_sha256=final_sha, supervisor_review=review)
    value["aggregate_admission_sha256"] = sha256(args.admission)
    value.pop("internal_sha256")
    value["internal_sha256"] = stable_digest(value)
    write_exclusive(args.out, value)
    print(json.dumps({
        "status": value["status"],
        "aggregate_sha256": sha256(args.out),
        "aggregate_internal_sha256": value["internal_sha256"],
        "confirmation_packet_design_authorized": value[
            "confirmation_packet_design_authorized"],
    }, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("--expected-git", required=True)
    freeze.add_argument("--capacity-result", required=True)
    freeze.add_argument("--capacity-review-record", required=True)
    freeze.add_argument("--out", required=True)
    freeze.set_defaults(func=freeze_command)
    verify = sub.add_parser("verify")
    verify.add_argument("--expected-git", required=True)
    verify.add_argument("--capacity-result", required=True)
    verify.add_argument("--capacity-review-record", required=True)
    verify.add_argument("--packet", required=True)
    verify.add_argument("--expected-packet-sha256", required=True)
    verify.set_defaults(func=verify_command)
    admit = sub.add_parser("admit")
    for cmd in (admit,):
        cmd.add_argument("--expected-git", required=True)
        cmd.add_argument("--capacity-result", required=True)
        cmd.add_argument("--capacity-review-record", required=True)
        cmd.add_argument("--packet", required=True)
        cmd.add_argument("--expected-packet-sha256", required=True)
        cmd.add_argument("--packet-review-record", required=True)
    admit.add_argument("--admission", required=True)
    admit.add_argument("--out", required=True)
    admit.set_defaults(func=admit_command)
    for name, func in (("run-shard", shard_command),
                       ("supervise", supervise_command),
                       ("aggregate", aggregate_command)):
        cmd = sub.add_parser(name)
        cmd.add_argument("--expected-git", required=True)
        cmd.add_argument("--capacity-result", required=True)
        cmd.add_argument("--capacity-review-record", required=True)
        cmd.add_argument("--packet", required=True)
        cmd.add_argument("--expected-packet-sha256", required=True)
        cmd.add_argument("--packet-review-record", required=True)
        cmd.add_argument("--screen-receipt", required=True)
        cmd.add_argument("--expected-screen-receipt-sha256", required=True)
        if name == "run-shard":
            cmd.add_argument("--shard-index", type=int, required=True)
        if name == "aggregate":
            cmd.add_argument("--supervisor-final", required=True)
            cmd.add_argument("--supervisor-review-record", required=True)
        cmd.add_argument("--admission", required=True)
        cmd.add_argument("--out", required=True)
        cmd.set_defaults(func=func)
    return root


def main() -> None:
    args = parser().parse_args()
    try:
        args.func(args)
    except (ScreenRefused, CAPACITY.CapacityRefused,
            CORE.PairProtocolRefused, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"REFUSED: {exc}") from exc


if __name__ == "__main__":
    main()

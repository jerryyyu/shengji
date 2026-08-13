#!/usr/bin/env python3
"""Reconstruct the reviewed T4 terminal result without writing anything."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

try:
    from terminal_review_common import (
        ReviewRefused, exact_source, import_script, marker,
        load_json_with_sha256, require_sha256, reviewer_sources, sha256)
except ModuleNotFoundError:  # package import in focused tests
    from .terminal_review_common import (
        ReviewRefused, exact_source, import_script, marker,
        load_json_with_sha256, require_sha256, reviewer_sources, sha256)


GIT = "c89c87121fb44ee98ec16753efce0ae5c825eea4"
PACKET_SHA = "713acb78fcd06cf0b7a503a1826b945b912e9fd5b17c9e2c40c605114da6db9c"
PREFIX = "TEACHER_STAGE_C_MIDLATE_COMPOSITION_RESULT_V1_REVIEW "
MODULES = {
    "server/scripts/teacher_stage_c_composition_runtime.py":
        "cb3b854dc6c9f8a17d08ed0b1380024f6e715a2ea49da91cb698c87229ced3fb",
    "server/scripts/teacher_stage_c_midlate_composition_controller.py":
        "f33f01a3d574f6d80be667124b7e591dd93317572eeaf1a7b16a5eb18fcfa603",
    "server/scripts/teacher_stage_c_midlate_composition_runtime.py":
        "e5247519806412e20356b286452a12a3bfe82938cd483c06005aed21d6fe606b",
}
DEPENDENCIES = {
    "teacher_stage_c_composition_runtime":
        "server/scripts/teacher_stage_c_composition_runtime.py",
    "teacher_stage_c_midlate_composition_controller":
        "server/scripts/teacher_stage_c_midlate_composition_controller.py",
}


def review(repo: Path, packet_review: Path, capacity_review: Path,
           supervisor_review: Path) -> dict:
    exact_source(repo, GIT, MODULES)
    os.environ["SHENGJI_STAGE_C_COMPOSITION_CONTROLLER"] = \
        "teacher_stage_c_midlate_composition_controller"
    runtime = import_script(
        repo, "teacher_stage_c_midlate_composition_runtime",
        "server/scripts/teacher_stage_c_midlate_composition_runtime.py",
        DEPENDENCIES, git=GIT).BASE
    ctrl, screen = runtime.CTRL, runtime.SCREEN
    aggregate_path = (runtime.REPO / ctrl.RESULT_PATH).resolve()
    # Terminal-only: refuse before loading any other evidence unless the
    # aggregate already exists.
    aggregate, aggregate_sha = load_json_with_sha256(
        aggregate_path, "T4 aggregate")
    packet_path = (runtime.REPO / ctrl.PACKET_PATH).resolve()
    receipt_path = (runtime.REPO / ctrl.RECEIPT_PATH).resolve()
    capacity_path = (runtime.REPO / ctrl.CAPACITY_RESULT_PATH).resolve()
    final_path = (runtime.REPO / ctrl.SUPERVISOR_FINAL_PATH).resolve()
    packet_snapshot, packet_file_sha = load_json_with_sha256(
        packet_path, "T4 packet")
    receipt_snapshot, receipt_sha = load_json_with_sha256(
        receipt_path, "T4 receipt")
    capacity_snapshot, capacity_sha = load_json_with_sha256(
        capacity_path, "T4 capacity result")
    final_snapshot, final_sha = load_json_with_sha256(
        final_path, "T4 supervisor final")
    packet_review_sha = sha256(packet_review)
    capacity_review_sha = sha256(capacity_review)
    packet, _ = runtime._packet(packet_path, PACKET_SHA)
    if packet != packet_snapshot:
        raise ReviewRefused("T4 packet changed during validation")
    receipt, capacity = runtime._receipt(
        receipt_path, receipt_sha, packet, PACKET_SHA, packet_review,
        capacity_path, capacity_sha, capacity_review)
    final = runtime._supervisor_final(
        path=final_path, expected_sha256=final_sha, packet=packet,
        packet_sha256=PACKET_SHA, receipt_sha256=receipt_sha,
        controller_review_record=packet_review, capacity_result=capacity,
        capacity_result_sha256=capacity_sha,
        capacity_review_record=capacity_review)
    if receipt != receipt_snapshot or capacity != capacity_snapshot:
        raise ReviewRefused("T4 receipt/capacity changed during validation")
    if final != final_snapshot:
        raise ReviewRefused("T4 supervisor final changed during validation")
    supervisor_claim = runtime._supervisor_review_claim(
        supervisor_review, packet, PACKET_SHA, final, final_sha)
    review_sha = sha256(supervisor_review)
    preopen = (
        aggregate.get("schema") == runtime.AGGREGATE_SCHEMA
        and aggregate.get("run_id") == ctrl.RUN_ID
        and aggregate.get("git") == GIT
        and aggregate.get("controller_packet_sha256") == PACKET_SHA
        and aggregate.get("screen_receipt_sha256") == receipt_sha
        and aggregate.get("supervisor_final_sha256") == final_sha
        and aggregate.get("supervisor_final_internal_sha256")
            == final["final_sha256"]
        and aggregate.get("supervisor_review_record_sha256") == review_sha
        and aggregate.get("supervisor_review_claim") == supervisor_claim
        and aggregate.get("aggregate_admission_slot")
            == ctrl.AGGREGATE_ADMISSION_PATH
        and aggregate.get("result_sha256")
            == runtime.self_hash(aggregate, "result_sha256")
        and aggregate.get("confirmation_launch_authorized") is False
        and aggregate.get("strength_claim") is False
        and aggregate.get("production_promotion") is False
        and aggregate.get("production_deployment") is False
        and aggregate.get("retry_or_extension_authorized") is False)
    if not preopen:
        raise ReviewRefused("T4 aggregate pre-open binding drift")
    runtime._validate_attempt_slot(
        logical=ctrl.AGGREGATE_ADMISSION_PATH,
        expected_sha256=str(aggregate["aggregate_admission_slot_sha256"]),
        packet=packet, packet_sha256=PACKET_SHA,
        receipt_sha256=receipt_sha, review_record=packet_review,
        kind="aggregate")

    merged = {label: [] for label in screen.LABELS}
    manifest = []
    for index, sealed in enumerate(final["shards"]):
        path = (runtime.REPO / ctrl.SHARD_PATHS[index]).resolve()
        log = (runtime.REPO / ctrl.SHARD_LOG_PATHS[index]).resolve()
        shard, shard_sha = load_json_with_sha256(
            path, f"T4 shard {index}")
        runtime.validate_shard(
            shard, packet=packet, packet_sha256=PACKET_SHA,
            receipt_sha256=receipt_sha, review_record=packet_review,
            index=index, supervisor_slot_sha256=str(
                final["supervisor_admission_slot_sha256"]))
        if (shard_sha != sealed["external_sha256"]
                or shard["shard_sha256"] != sealed["internal_sha256"]
                or sha256(log) != sealed["log_sha256"]):
            raise ReviewRefused(f"T4 sealed shard {index} drift")
        for label in screen.LABELS:
            merged[label].extend(shard["records"][label])
        manifest.append({
            "index": index, "logical_path": ctrl.SHARD_PATHS[index],
            "external_sha256": shard_sha,
            "internal_sha256": shard["shard_sha256"]})
    rebuilt = screen.aggregate_screen(
        merged, expected_seed0=ctrl.SCREEN_SEED0,
        expected_clusters=ctrl.SCREEN_CLUSTERS,
        expected_surface=str(packet["selected_capability"]["surface"]))
    expected = {
        "schema": runtime.AGGREGATE_SCHEMA, "run_id": ctrl.RUN_ID,
        "git": GIT, "controller_packet_sha256": PACKET_SHA,
        "screen_receipt_sha256": receipt_sha,
        "supervisor_final_sha256": final_sha,
        "supervisor_final_internal_sha256": final["final_sha256"],
        "supervisor_review_record_sha256": review_sha,
        "supervisor_review_claim": supervisor_claim,
        "aggregate_admission_slot": ctrl.AGGREGATE_ADMISSION_PATH,
        "aggregate_admission_slot_sha256": aggregate[
            "aggregate_admission_slot_sha256"],
        "selected_capability": packet["selected_capability"],
        "model_exports_sha256": packet["model_exports_sha256"],
        "shards": manifest, "screen": rebuilt, "decision": rebuilt["status"],
        "confirmation_packet_review_authorized": (
            rebuilt["status"] == "AUTHORIZE_CONFIRM_PACKET_REVIEW"),
        "strength_claim": False, "confirmation_launch_authorized": False,
        "production_promotion": False, "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    expected["result_sha256"] = runtime.self_hash(expected, "result_sha256")
    if aggregate != expected:
        raise ReviewRefused("T4 recursive aggregate reconstruction drift")
    stable = [
        (aggregate_path, aggregate_sha, "T4 aggregate"),
        (packet_path, packet_file_sha, "T4 packet"),
        (receipt_path, receipt_sha, "T4 receipt"),
        (capacity_path, capacity_sha, "T4 capacity result"),
        (final_path, final_sha, "T4 supervisor final"),
        (packet_review, packet_review_sha, "T4 packet review"),
        (capacity_review, capacity_review_sha, "T4 capacity review"),
        (supervisor_review, review_sha, "T4 supervisor review"),
        ((runtime.REPO / ctrl.AGGREGATE_ADMISSION_PATH).resolve(),
         aggregate["aggregate_admission_slot_sha256"],
         "T4 aggregate admission"),
        ((runtime.REPO / ctrl.SUPERVISOR_ADMISSION_PATH).resolve(),
         final["supervisor_admission_slot_sha256"],
         "T4 supervisor admission"),
    ]
    for index, shard in enumerate(final["shards"]):
        stable.extend((
            ((runtime.REPO / ctrl.SHARD_PATHS[index]).resolve(),
             shard["external_sha256"], f"T4 shard {index}"),
            ((runtime.REPO / ctrl.SHARD_LOG_PATHS[index]).resolve(),
             shard["log_sha256"], f"T4 shard log {index}"),
        ))
    for path, digest, label in stable:
        require_sha256(path, digest, label)
    return {
        "schema": "teacher-stage-c-midlate-composition-result-review-v1",
        "git": GIT, "run_id": ctrl.RUN_ID, "packet_sha256": PACKET_SHA,
        "receipt_sha256": receipt_sha, "supervisor_final_sha256": final_sha,
        "supervisor_review_record_sha256": review_sha,
        "aggregate_admission_sha256": aggregate[
            "aggregate_admission_slot_sha256"],
        "aggregate_sha256": aggregate_sha,
        "aggregate_internal_sha256": aggregate["result_sha256"],
        "decision": aggregate["decision"], "screen": aggregate["screen"],
        "recursive_statistic_reconstruction": True,
        "source_module_sha256s": MODULES,
        "reviewer_source_sha256s": reviewer_sources(
            Path(__file__), Path(__file__).with_name("terminal_review_common.py")),
        "independent_review": True,
        "confirmation_packet_review_authorized": aggregate[
            "confirmation_packet_review_authorized"],
        "confirmation_launch_authorized": False, "strength_claim": False,
        "production_promotion": False, "production_deployment": False,
        "verdict": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repo", type=Path, required=True)
    parser.add_argument("--packet-review-record", type=Path, required=True)
    parser.add_argument("--capacity-review-record", type=Path, required=True)
    parser.add_argument("--supervisor-review-record", type=Path, required=True)
    args = parser.parse_args()
    try:
        claim = review(args.source_repo, args.packet_review_record,
                       args.capacity_review_record,
                       args.supervisor_review_record)
    except (ReviewRefused, OSError, ValueError, RuntimeError) as exc:
        parser.error(f"REFUSED: {exc}")
    print(marker(PREFIX, claim))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

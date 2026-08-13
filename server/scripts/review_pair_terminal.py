#!/usr/bin/env python3
"""Reconstruct the reviewed Pair V3 terminal result without writes."""
from __future__ import annotations

import argparse
from pathlib import Path

try:
    from terminal_review_common import (
        ReviewRefused, exact_source, import_script, load_json, marker,
        reviewer_sources, sha256)
except ModuleNotFoundError:  # package import in focused tests
    from .terminal_review_common import (
        ReviewRefused, exact_source, import_script, load_json, marker,
        reviewer_sources, sha256)


GIT = "cd206707f56fbb576c6333b1ef7f86d8fc9c4451"
PACKET_SHA = "4ece02b93ebb49020b9654bdc3d9bc2cd27d8f9db4bf9201b14443f479cdae47"
PREFIX = "PAIR_AWARE_ROLLOUT_SCREEN_RESULT_V1_REVIEW "
MODULES = {"server/scripts/pair_aware_rollout_screen.py":
           "a3135593f6d1305233337d4ddf7cea6f56431c0556c5eecbe4c41bea96fc3d72"}


def review(repo: Path, packet_review: Path,
           supervisor_review: Path) -> dict:
    exact_source(repo, GIT, MODULES)
    screen = import_script(repo, "pair_aware_rollout_screen")
    # Terminal-only: aggregate existence is the first evidence condition.
    aggregate = load_json(screen.AGGREGATE_PATH, "Pair aggregate")
    capacity_review = screen.PLANNING_REVIEW_PATH
    packet = screen.load_packet(
        screen.PACKET_PATH, PACKET_SHA, expected_git=GIT,
        result_path=screen.CAPACITY_RESULT_PATH,
        capacity_review_record=capacity_review)
    packet_claim = screen.packet_review_claim(packet, PACKET_SHA)
    packet_marker = screen.parse_marker(
        packet_review, screen.PACKET_REVIEW_PREFIX, packet_claim,
        label="Pair packet review")
    receipt_sha = sha256(screen.RECEIPT_PATH)
    receipt = screen.load_receipt(
        screen.RECEIPT_PATH, receipt_sha, packet=packet,
        packet_sha256=PACKET_SHA, packet_review_record=packet_review)
    final = load_json(screen.SUPERVISOR_FINAL_PATH, "Pair supervisor final")
    final_sha = sha256(screen.SUPERVISOR_FINAL_PATH)
    supervisor_claim = screen.supervisor_review_claim(
        packet, PACKET_SHA, receipt_sha, final, final_sha)
    supervisor_marker = screen.parse_marker(
        supervisor_review, screen.SUPERVISOR_REVIEW_PREFIX,
        supervisor_claim, label="Pair supervisor review")
    unsigned = dict(aggregate)
    observed = unsigned.pop("internal_sha256", None)
    preopen = (
        observed == screen.stable_digest(unsigned)
        and aggregate.get("schema") == screen.AGGREGATE_SCHEMA
        and aggregate.get("run_id") == screen.RUN_ID
        and aggregate.get("git") == GIT
        and aggregate.get("packet_sha256") == PACKET_SHA
        and aggregate.get("receipt_sha256") == receipt_sha
        and aggregate.get("supervisor_final_sha256") == final_sha
        and aggregate.get("supervisor_review_record_sha256")
            == supervisor_marker["sha256"]
        and aggregate.get("supervisor_review_marker")
            == supervisor_marker["marker"]
        and isinstance(aggregate.get("aggregate_admission_sha256"), str)
        and len(aggregate["aggregate_admission_sha256"]) == 64
        and aggregate.get("confirmation_execution_authorized") is False
        and aggregate.get("strength_claim") is False
        and aggregate.get("production_promotion") is False
        and aggregate.get("production_deployment") is False
        and aggregate.get("retry_or_extension_authorized") is False)
    if not preopen:
        raise ReviewRefused("Pair aggregate pre-open binding drift")
    admission = load_json(
        screen.AGGREGATE_ADMISSION_PATH, "Pair aggregate admission")
    admission_unsigned = dict(admission)
    admission_internal = admission_unsigned.pop("internal_sha256", None)
    nonce, created = admission.get("nonce"), admission.get("created_time_ns")
    if (sha256(screen.AGGREGATE_ADMISSION_PATH)
            != aggregate["aggregate_admission_sha256"]
            or set(admission) != {
                "schema", "run_id", "git", "packet_sha256", "nonce",
                "created_time_ns", "retry_or_extension_authorized",
                "production_deployment", "receipt_sha256",
                "supervisor_review_record_sha256", "internal_sha256"}
            or admission_internal != screen.stable_digest(admission_unsigned)
            or admission.get("schema")
                != "pair-aware-rollout-screen-aggregate-admission-v1"
            or admission.get("run_id") != screen.RUN_ID
            or admission.get("git") != GIT
            or admission.get("packet_sha256") != PACKET_SHA
            or admission.get("receipt_sha256") != receipt_sha
            or admission.get("supervisor_review_record_sha256")
                != supervisor_marker["sha256"]
            or not isinstance(nonce, str) or len(nonce) != 64
            or any(char not in "0123456789abcdef" for char in nonce)
            or isinstance(created, bool) or not isinstance(created, int)
            or created <= 0
            or admission.get("retry_or_extension_authorized") is not False
            or admission.get("production_deployment") is not False):
        raise ReviewRefused("Pair aggregate admission binding drift")

    # Outcome bytes are opened only after aggregate and admission bind.
    screen.validate_supervisor_final(
        final, packet=packet, packet_sha256=PACKET_SHA,
        receipt_sha256=receipt_sha)
    shards = [load_json(path, f"Pair shard {index}")
              for index, path in enumerate(screen.SHARD_PATHS)]
    rebuilt = screen.aggregate_payload(
        packet=packet, packet_sha256=PACKET_SHA, receipt_sha256=receipt_sha,
        shard_values=shards,
        shard_sha256s=[sha256(path) for path in screen.SHARD_PATHS],
        supervisor_final_sha256=final_sha,
        supervisor_review=supervisor_marker)
    rebuilt["aggregate_admission_sha256"] = aggregate[
        "aggregate_admission_sha256"]
    rebuilt.pop("internal_sha256")
    rebuilt["internal_sha256"] = screen.stable_digest(rebuilt)
    if aggregate != rebuilt:
        raise ReviewRefused("Pair recursive aggregate reconstruction drift")
    return {
        "schema": "pair-aware-rollout-screen-result-review-v1",
        "git": GIT, "run_id": screen.RUN_ID, "packet_sha256": PACKET_SHA,
        "packet_review_record_sha256": packet_marker["sha256"],
        "receipt_sha256": receipt_sha, "supervisor_final_sha256": final_sha,
        "supervisor_review_record_sha256": supervisor_marker["sha256"],
        "aggregate_admission_sha256": aggregate[
            "aggregate_admission_sha256"],
        "aggregate_sha256": sha256(screen.AGGREGATE_PATH),
        "aggregate_internal_sha256": aggregate["internal_sha256"],
        "status": aggregate["status"],
        "primary_level_utility": aggregate["primary_level_utility"],
        "secondary_game_win_rate": aggregate["secondary_game_win_rate"],
        "natural_dose": aggregate["natural_dose"],
        "recursive_statistic_reconstruction": True,
        "source_module_sha256s": MODULES,
        "reviewer_source_sha256s": reviewer_sources(
            Path(__file__), Path(__file__).with_name("terminal_review_common.py")),
        "independent_review": True,
        "confirmation_packet_design_authorized": aggregate[
            "confirmation_packet_design_authorized"],
        "confirmation_execution_authorized": False, "strength_claim": False,
        "production_promotion": False, "production_deployment": False,
        "verdict": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repo", type=Path, required=True)
    parser.add_argument("--packet-review-record", type=Path, required=True)
    parser.add_argument("--supervisor-review-record", type=Path, required=True)
    args = parser.parse_args()
    try:
        claim = review(args.source_repo, args.packet_review_record,
                       args.supervisor_review_record)
    except (ReviewRefused, OSError, ValueError, RuntimeError) as exc:
        parser.error(f"REFUSED: {exc}")
    print(marker(PREFIX, claim))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

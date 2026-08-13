#!/usr/bin/env python3
"""Reconstruct the reviewed Pair V3 terminal result without writes."""
from __future__ import annotations

import argparse
from pathlib import Path

try:
    from terminal_review_common import (
        ReviewRefused, exact_source, import_script, marker,
        load_json_with_sha256, require_sha256, reviewer_sources, sha256)
except ModuleNotFoundError:  # package import in focused tests
    from .terminal_review_common import (
        ReviewRefused, exact_source, import_script, marker,
        load_json_with_sha256, require_sha256, reviewer_sources, sha256)


GIT = "cd206707f56fbb576c6333b1ef7f86d8fc9c4451"
PACKET_SHA = "4ece02b93ebb49020b9654bdc3d9bc2cd27d8f9db4bf9201b14443f479cdae47"
PREFIX = "PAIR_AWARE_ROLLOUT_SCREEN_RESULT_V1_REVIEW "
MODULES = {
    "server/scripts/pair_aware_rollout_screen.py":
        "a3135593f6d1305233337d4ddf7cea6f56431c0556c5eecbe4c41bea96fc3d72",
    "server/scripts/pair_aware_rollout_capacity.py":
        "0ba9b131a49730f546653177042bc50f4ddbd5c81325e23b568f67c075b23c56",
    "server/scripts/pair_aware_rollout_duel.py":
        "c034f1cd04f97c6cd0e9877eb3fe186ee59194be27d93bb1b8d01e4e9ff9cc2b",
}
DEPENDENCIES = {
    "pair_aware_rollout_capacity":
        "server/scripts/pair_aware_rollout_capacity.py",
    "pair_aware_rollout_duel": "server/scripts/pair_aware_rollout_duel.py",
}


def _is_hex(value: object, length: int) -> bool:
    return (isinstance(value, str) and len(value) == length
            and all(char in "0123456789abcdef" for char in value))


def _admission(
    path: Path, expected_sha256: str, *, screen, schema: str, packet: dict,
    receipt_sha256: str | None = None, shard_index: int | None = None,
    packet_review_sha256: str | None = None,
    supervisor_review_sha256: str | None = None,
) -> dict:
    value, observed_sha256 = load_json_with_sha256(path, schema)
    expected_fields = {
        "schema", "run_id", "git", "packet_sha256", "nonce",
        "created_time_ns", "retry_or_extension_authorized",
        "production_deployment", "internal_sha256",
    }
    expected = {
        "schema": schema,
        "run_id": screen.RUN_ID,
        "git": packet["git"],
        "packet_sha256": PACKET_SHA,
        "retry_or_extension_authorized": False,
        "production_deployment": False,
    }
    for field, child in (
            ("receipt_sha256", receipt_sha256),
            ("shard_index", shard_index),
            ("packet_review_record_sha256", packet_review_sha256),
            ("supervisor_review_record_sha256", supervisor_review_sha256)):
        if child is not None:
            expected_fields.add(field)
            expected[field] = child
    unsigned = dict(value)
    internal = unsigned.pop("internal_sha256", None)
    nonce, created = value.get("nonce"), value.get("created_time_ns")
    if (observed_sha256 != expected_sha256
            or set(value) != expected_fields
            or any(value.get(field) != child
                   for field, child in expected.items())
            or not _is_hex(nonce, 64)
            or isinstance(created, bool) or not isinstance(created, int)
            or created <= 0
            or internal != screen.stable_digest(unsigned)):
        raise ReviewRefused(f"{schema} binding drift")
    return value


def review(repo: Path, packet_review: Path,
           supervisor_review: Path) -> dict:
    exact_source(repo, GIT, MODULES)
    screen = import_script(
        repo, "pair_aware_rollout_screen",
        "server/scripts/pair_aware_rollout_screen.py", DEPENDENCIES, git=GIT)
    # Terminal-only: aggregate existence is the first evidence condition.
    aggregate, aggregate_sha = load_json_with_sha256(
        screen.AGGREGATE_PATH, "Pair aggregate")
    packet_snapshot, packet_file_sha = load_json_with_sha256(
        screen.PACKET_PATH, "Pair packet")
    capacity_review = screen.PLANNING_REVIEW_PATH
    packet = screen.load_packet(
        screen.PACKET_PATH, PACKET_SHA, expected_git=GIT,
        result_path=screen.CAPACITY_RESULT_PATH,
        capacity_review_record=capacity_review)
    if packet != packet_snapshot:
        raise ReviewRefused("Pair packet changed during validation")
    packet_claim = screen.packet_review_claim(packet, PACKET_SHA)
    packet_marker = screen.parse_marker(
        packet_review, screen.PACKET_REVIEW_PREFIX, packet_claim,
        label="Pair packet review")
    receipt_snapshot, receipt_sha = load_json_with_sha256(
        screen.RECEIPT_PATH, "Pair receipt")
    receipt = screen.load_receipt(
        screen.RECEIPT_PATH, receipt_sha, packet=packet,
        packet_sha256=PACKET_SHA, packet_review_record=packet_review)
    if receipt != receipt_snapshot:
        raise ReviewRefused("Pair receipt changed during validation")
    _admission(
        screen.EXECUTION_ADMISSION_PATH,
        receipt["execution_admission_sha256"], screen=screen,
        schema="pair-aware-rollout-screen-execution-admission-v1",
        packet=packet, packet_review_sha256=packet_marker["sha256"])
    final, final_sha = load_json_with_sha256(
        screen.SUPERVISOR_FINAL_PATH, "Pair supervisor final")
    supervisor_claim = screen.supervisor_review_claim(
        packet, PACKET_SHA, receipt_sha, final, final_sha)
    supervisor_marker = screen.parse_marker(
        supervisor_review, screen.SUPERVISOR_REVIEW_PREFIX,
        supervisor_claim, label="Pair supervisor review")
    _admission(
        screen.SUPERVISOR_ADMISSION_PATH,
        final["supervisor_admission_sha256"], screen=screen,
        schema="pair-aware-rollout-screen-supervisor-admission-v1",
        packet=packet, receipt_sha256=receipt_sha)
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
    _admission(
        screen.AGGREGATE_ADMISSION_PATH,
        aggregate["aggregate_admission_sha256"], screen=screen,
        schema="pair-aware-rollout-screen-aggregate-admission-v1",
        packet=packet, receipt_sha256=receipt_sha,
        supervisor_review_sha256=supervisor_marker["sha256"])

    # Outcome bytes are opened only after aggregate and admission bind.
    screen.validate_supervisor_final(
        final, packet=packet, packet_sha256=PACKET_SHA,
        receipt_sha256=receipt_sha)
    shard_snapshots = [
        load_json_with_sha256(path, f"Pair shard {index}")
        for index, path in enumerate(screen.SHARD_PATHS)]
    shards = [value for value, _digest in shard_snapshots]
    shard_sha256s = [digest for _value, digest in shard_snapshots]
    for index, shard in enumerate(shards):
        _admission(
            screen.SHARD_ADMISSION_PATHS[index],
            shard["shard_admission_sha256"], screen=screen,
            schema="pair-aware-rollout-screen-shard-admission-v1",
            packet=packet, receipt_sha256=receipt_sha, shard_index=index)
    rebuilt = screen.aggregate_payload(
        packet=packet, packet_sha256=PACKET_SHA, receipt_sha256=receipt_sha,
        shard_values=shards,
        shard_sha256s=shard_sha256s,
        supervisor_final_sha256=final_sha,
        supervisor_review=supervisor_marker)
    rebuilt["aggregate_admission_sha256"] = aggregate[
        "aggregate_admission_sha256"]
    rebuilt.pop("internal_sha256")
    rebuilt["internal_sha256"] = screen.stable_digest(rebuilt)
    if aggregate != rebuilt:
        raise ReviewRefused("Pair recursive aggregate reconstruction drift")
    stable = [
        (screen.AGGREGATE_PATH, aggregate_sha, "Pair aggregate"),
        (screen.PACKET_PATH, packet_file_sha, "Pair packet"),
        (screen.RECEIPT_PATH, receipt_sha, "Pair receipt"),
        (screen.SUPERVISOR_FINAL_PATH, final_sha, "Pair supervisor final"),
        (packet_review, packet_marker["sha256"], "Pair packet review"),
        (supervisor_review, supervisor_marker["sha256"],
         "Pair supervisor review"),
        (screen.EXECUTION_ADMISSION_PATH,
         receipt["execution_admission_sha256"],
         "Pair execution admission"),
        (screen.SUPERVISOR_ADMISSION_PATH,
         final["supervisor_admission_sha256"],
         "Pair supervisor admission"),
        (screen.AGGREGATE_ADMISSION_PATH,
         aggregate["aggregate_admission_sha256"],
         "Pair aggregate admission"),
    ]
    for index, shard in enumerate(shards):
        stable.extend((
            (screen.SHARD_PATHS[index], shard_sha256s[index],
             f"Pair shard {index}"),
            (screen.SHARD_LOG_PATHS[index],
             final["shards"][index]["log_sha256"],
             f"Pair shard log {index}"),
            (screen.SHARD_ADMISSION_PATHS[index],
             shard["shard_admission_sha256"],
             f"Pair shard admission {index}"),
        ))
    for path, digest, label in stable:
        require_sha256(path, digest, label)
    return {
        "schema": "pair-aware-rollout-screen-result-review-v1",
        "git": GIT, "run_id": screen.RUN_ID, "packet_sha256": PACKET_SHA,
        "packet_review_record_sha256": packet_marker["sha256"],
        "receipt_sha256": receipt_sha, "supervisor_final_sha256": final_sha,
        "supervisor_review_record_sha256": supervisor_marker["sha256"],
        "aggregate_admission_sha256": aggregate[
            "aggregate_admission_sha256"],
        "aggregate_sha256": aggregate_sha,
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

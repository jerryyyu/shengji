#!/usr/bin/env python3
"""Read-only terminal review for the live T4 and pair-aware screens.

The live controllers deliberately require an independent score-free review
before their one aggregate is admitted.  After that aggregate exists, this
program reopens the complete terminal population, reconstructs every statistic
through the exact pinned pure evaluator, and prints one review marker to
stdout.  It has no code path that launches gameplay, consumes an admission,
or writes a file.

The two profiles share only artifact and authority plumbing.  Their shard
validators and aggregators remain separate and are loaded from the exact live
source commits whose hashes are frozen below.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping, Sequence


sys.dont_write_bytecode = True


class ReviewRefused(RuntimeError):
    """A source, artifact, statistic, or authority boundary drifted."""


@dataclass(frozen=True)
class Profile:
    name: str
    git: str
    packet_sha256: str
    run_id: str
    shards: int
    marker: str
    schema: str
    source_sha256s: Mapping[str, str]


T4 = Profile(
    name="t4",
    git="c89c87121fb44ee98ec16753efce0ae5c825eea4",
    packet_sha256=(
        "713acb78fcd06cf0b7a503a1826b945b912e9fd5b17c9e2c40c605114da6db9c"),
    run_id="teacher-v3-stage-c-midlate-composition-screen-v1",
    shards=8,
    marker="TEACHER_STAGE_C_MIDLATE_COMPOSITION_RESULT_V1_REVIEW ",
    schema="teacher-stage-c-midlate-composition-result-review-v1",
    source_sha256s={
        "server/scripts/teacher_stage_c_composition_runtime.py":
            "cb3b854dc6c9f8a17d08ed0b1380024f6e715a2ea49da91cb698c87229ced3fb",
        "server/scripts/teacher_stage_c_midlate_composition_controller.py":
            "f33f01a3d574f6d80be667124b7e591dd93317572eeaf1a7b16a5eb18fcfa603",
        "server/scripts/teacher_stage_c_midlate_composition_runtime.py":
            "e5247519806412e20356b286452a12a3bfe82938cd483c06005aed21d6fe606b",
        "server/scripts/teacher_stage_c_midlate_state_controller.py":
            "f8f9f5e3ac2ff94fe2fcf79f124cfeba0970d0e9b2493c3fa0a7fa7534cc57b3",
        "server/shengji/rl/npnet.py":
            "0ee6e5e3387c6ce834c9209ebb9ab95421228807c1b4713ca8d34374facd9cbb",
        "server/shengji/rl/stage_c_candidates.py":
            "938c419aa59780c39078b8daab93160770d6a2b0aa4776f119ee4965828c02a7",
        "server/shengji/rl/stage_c_composition.py":
            "f8c5cbe56102c4cf58b31c11b00cf0dbce27fb40d484ce0a6cac3c861356dae5",
        "server/shengji/rl/stage_c_npnet.py":
            "943cd62669cc7bee421eda28c5a02101308021b93c52ee703d4e0a89b7b27b3a",
        "server/shengji/rl/stage_c_screen.py":
            "244de53dfa2a447c628784f3227e56d2c642895f173aef4bc6d21787c2882be3",
    },
)


PAIR = Profile(
    name="pair",
    git="cd206707f56fbb576c6333b1ef7f86d8fc9c4451",
    packet_sha256=(
        "4ece02b93ebb49020b9654bdc3d9bc2cd27d8f9db4bf9201b14443f479cdae47"),
    run_id="pair-aware-whole-round-screen-v3",
    shards=8,
    marker="PAIR_AWARE_ROLLOUT_SCREEN_RESULT_V1_REVIEW ",
    schema="pair-aware-rollout-screen-result-review-v1",
    source_sha256s={
        "capacity_result":
            "08f7282cc2317550336647642085a1c165ae708cb6483b4710d0359b498ef7c1",
        "controller":
            "0ba9b131a49730f546653177042bc50f4ddbd5c81325e23b568f67c075b23c56",
        "duel_core":
            "c034f1cd04f97c6cd0e9877eb3fe186ee59194be27d93bb1b8d01e4e9ff9cc2b",
        "env":
            "04b1d18e2ad4783c5160913b66c2adf568625de1aaf6bdf300c6a4b00c2f0d8b",
        "evaluation":
            "ae4739a19767391cb9734a59f7b6cf5f4143d44d8de4beb00dcc3c2c96fcbb4c",
        "fast_binary":
            "9371ab7fc8bbcceb19cc5c4fe799860cf5ad3f51b11b26ab0e375ced36713e32",
        "game":
            "613c5dd72a1cbd3b50a96eef6e0b84746052dc2b0b28fb08005ff34455359e43",
        "mcbot":
            "45a82f44b95d1bce5126c63b1a5af6baaed54270aca9d55677b2e0bbb9c9d957",
        "memory":
            "905873b332fd54471070b25ce24f100b813c9a9f234c1b50254d00895140cf51",
        "pair_aware":
            "55f94a58b914301bfb456d91a98b13efb8e40de66750b1ccb07b316fef0b6391",
        "planning_review_record":
            "9f4c04abefbfd21dc3305c55096081aa4c45827dd304d8bbb471f242fca3af15",
        "registry":
            "dbb2848535eda766df737cda8decffe56e00d514b12ba5fa5c9386ff9d86fd1a",
        "root_dose":
            "515775e3f0b9222874c71791b3dbb10c47270c32211e5300ec86929fb58c3cb4",
        "round":
            "7a91b3573ecb34c488e3960008d21ebfda283e01003f6454a1ffd62c41b9b679",
        "screen_controller":
            "a3135593f6d1305233337d4ddf7cea6f56431c0556c5eecbe4c41bea96fc3d72",
    },
)


def sha256(path: os.PathLike[str] | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_digest(value: object, *, newline: bool = False) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    if newline:
        raw += "\n"
    return hashlib.sha256(raw.encode()).hexdigest()


def regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink())


def _pairs_no_duplicates(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ReviewRefused(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def load_json(path: Path, label: str) -> dict:
    if not regular_unlinked(path):
        raise ReviewRefused(f"{label} is not a regular unlinked file")
    try:
        value = json.loads(
            path.read_bytes(), object_pairs_hook=_pairs_no_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ReviewRefused(f"{label} contains {token}")))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ReviewRefused(f"cannot parse {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReviewRefused(f"{label} is not an object")
    return value


def one_marker(path: Path, prefix: str, expected: dict, label: str) -> dict:
    if not regular_unlinked(path):
        raise ReviewRefused(f"{label} is not a regular unlinked file")
    try:
        lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ReviewRefused(f"cannot read {label}: {exc}") from exc
    matches = [line[len(prefix):] for line in lines if line.startswith(prefix)]
    if len(matches) != 1:
        raise ReviewRefused(f"{label} needs exactly one raw marker")
    try:
        claim = json.loads(matches[0], object_pairs_hook=_pairs_no_duplicates)
    except ValueError as exc:
        raise ReviewRefused(f"{label} marker is invalid JSON") from exc
    if claim != expected:
        raise ReviewRefused(f"{label} claim drift")
    return {"sha256": sha256(path), "marker": prefix + matches[0],
            "claim": claim}


def _git(repo: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=repo, check=True, text=True,
            capture_output=True).stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise ReviewRefused(f"cannot inspect source Git: {exc.stderr}") from exc


def _load_source(profile: Profile, source_repo: Path) -> SimpleNamespace:
    source_repo = source_repo.resolve()
    if _git(source_repo, "rev-parse", "HEAD") != profile.git:
        raise ReviewRefused(f"{profile.name} source Git drift")
    server = source_repo / "server"
    scripts = server / "scripts"
    sys.path[:0] = [str(scripts), str(server)]
    if profile is T4:
        observed = {logical: sha256(source_repo / logical)
                    for logical in profile.source_sha256s}
        if observed != dict(profile.source_sha256s):
            raise ReviewRefused("T4 pinned source hash drift")
        controller = importlib.import_module(
            "teacher_stage_c_midlate_composition_controller")
        runtime = importlib.import_module("teacher_stage_c_composition_runtime")
        if (Path(controller.__file__).resolve()
                != source_repo / "server/scripts/teacher_stage_c_midlate_composition_controller.py"
                or Path(runtime.__file__).resolve()
                != source_repo / "server/scripts/teacher_stage_c_composition_runtime.py"):
            raise ReviewRefused("T4 module resolved outside pinned source")
        return SimpleNamespace(controller=controller, runtime=runtime,
                               screen=controller.SCREEN)
    screen = importlib.import_module("pair_aware_rollout_screen")
    if Path(screen.__file__).resolve() != (
            source_repo / "server/scripts/pair_aware_rollout_screen.py"):
        raise ReviewRefused("pair module resolved outside pinned source")
    observed = {name: sha256(path)
                for name, path in screen.source_paths().items()}
    if observed != dict(profile.source_sha256s):
        raise ReviewRefused("pair pinned source hash drift")
    return SimpleNamespace(screen=screen)


def _distinct(paths: Sequence[Path]) -> None:
    identities = []
    for path in paths:
        if not regular_unlinked(path):
            raise ReviewRefused(f"terminal input is not regular/unlinked: {path}")
        info = path.stat()
        identities.append((info.st_dev, info.st_ino))
    if len(identities) != len(set(identities)):
        raise ReviewRefused("terminal inputs alias one another")


def _t4_review(args, api, profile: Profile = T4) -> dict:
    paths = [args.packet, args.receipt, args.capacity_result,
             args.packet_review_record, args.capacity_review_record,
             args.supervisor_final, args.supervisor_review_record,
             args.aggregate_admission, args.aggregate,
             *args.shards, *args.logs]
    _distinct(paths)
    if len(args.shards) != profile.shards or len(args.logs) != profile.shards:
        raise ReviewRefused("T4 requires exactly eight shards and eight logs")
    controller, runtime, screen = api.controller, api.runtime, api.screen
    packet = load_json(args.packet, "T4 packet")
    if (sha256(args.packet) != profile.packet_sha256
            or packet.get("schema") != controller.SCHEMA
            or packet.get("run_id") != profile.run_id
            or packet.get("producer", {}).get("git") != profile.git
            or packet.get("producer", {}).get("sources")
            != dict(profile.source_sha256s)
            or packet.get("packet_sha256")
            != controller.self_hash(packet, "packet_sha256")):
        raise ReviewRefused("T4 packet identity/source drift")
    packet_review = one_marker(
        args.packet_review_record, controller.REVIEW_MARKER,
        controller.expected_review_claim(packet, profile.packet_sha256),
        "T4 packet review")

    capacity = load_json(args.capacity_result, "T4 capacity result")
    capacity_sha = sha256(args.capacity_result)
    if (capacity.get("schema") != controller.CAPACITY_RESULT_SCHEMA
            or capacity.get("run_id") != profile.run_id
            or capacity.get("git") != profile.git
            or capacity.get("controller_packet_sha256")
            != profile.packet_sha256
            or capacity.get("result_sha256")
            != controller.self_hash(capacity, "result_sha256")
            or capacity.get("capacity_pass") is not True
            or capacity.get("score_free") is not True
            or capacity.get("outcomes_published") is not False):
        raise ReviewRefused("T4 capacity identity/authority drift")
    capacity_review = one_marker(
        args.capacity_review_record, controller.CAPACITY_REVIEW_MARKER,
        controller.expected_capacity_review_claim(
            packet, profile.packet_sha256, capacity, capacity_sha),
        "T4 capacity review")

    receipt = load_json(args.receipt, "T4 receipt")
    receipt_sha = sha256(args.receipt)
    if (receipt.get("schema") != controller.RUNTIME_RECEIPT_SCHEMA
            or receipt.get("run_id") != profile.run_id
            or receipt.get("git") != profile.git
            or receipt.get("controller_packet_sha256")
            != profile.packet_sha256
            or receipt.get("controller_review_record_sha256")
            != packet_review["sha256"]
            or receipt.get("controller_review_claim")
            != packet_review["claim"]
            or receipt.get("capacity_result_sha256") != capacity_sha
            or receipt.get("capacity_review_record_sha256")
            != capacity_review["sha256"]
            or receipt.get("capacity_review_claim")
            != capacity_review["claim"]
            or receipt.get("receipt_sha256")
            != controller.self_hash(receipt, "receipt_sha256")
            or receipt.get("screen_execution_authorized") is not True
            or any(receipt.get(field) is not False for field in (
                "confirmation_launch_authorized", "strength_claim",
                "production_promotion", "production_deployment",
                "retry_or_extension_authorized"))):
        raise ReviewRefused("T4 receipt identity/authority drift")

    final = load_json(args.supervisor_final, "T4 supervisor final")
    final_sha = sha256(args.supervisor_final)
    refs = final.get("shards")
    final_keys = {
        "schema", "run_id", "git", "controller_packet_sha256",
        "controller_review_record_sha256", "screen_receipt_sha256",
        "capacity_result_sha256", "capacity_review_record_sha256",
        "supervisor_admission_slot", "supervisor_admission_slot_sha256",
        "commands", "shards", "shard_manifest_sha256", "elapsed_seconds",
        "all_children_exit_zero", "outcomes_published",
        "statistics_published", "aggregate_execution_authorized",
        "confirmation_launch_authorized", "strength_claim",
        "production_promotion", "production_deployment",
        "retry_or_extension_authorized", "final_sha256",
    }
    elapsed = final.get("elapsed_seconds")
    if (set(final) != final_keys
            or final.get("schema")
            != controller.RUNTIME_SUPERVISOR_FINAL_SCHEMA
            or final.get("run_id") != profile.run_id
            or final.get("git") != profile.git
            or final.get("controller_packet_sha256")
            != profile.packet_sha256
            or final.get("screen_receipt_sha256") != receipt_sha
            or final.get("capacity_result_sha256") != capacity_sha
            or final.get("controller_review_record_sha256")
            != packet_review["sha256"]
            or final.get("capacity_review_record_sha256")
            != capacity_review["sha256"]
            or final.get("supervisor_admission_slot")
            != controller.SUPERVISOR_ADMISSION_PATH
            or not controller.is_sha256(
                final.get("supervisor_admission_slot_sha256"))
            or not isinstance(final.get("commands"), list)
            or len(final["commands"]) != profile.shards
            or isinstance(elapsed, bool)
            or not isinstance(elapsed, (int, float))
            or not math.isfinite(float(elapsed)) or float(elapsed) <= 0
            or float(elapsed) > float(capacity["screen_max_shard_seconds"]) + 120
            or final.get("final_sha256")
            != controller.self_hash(final, "final_sha256")
            or not isinstance(refs, list) or len(refs) != profile.shards
            or final.get("shard_manifest_sha256")
            != controller.manifest_hash(refs)
            or final.get("all_children_exit_zero") is not True
            or final.get("outcomes_published") is not False
            or final.get("statistics_published") is not False
            or any(final.get(field) is not False for field in (
                "aggregate_execution_authorized",
                "confirmation_launch_authorized", "strength_claim",
                "production_promotion", "production_deployment",
                "retry_or_extension_authorized"))):
        raise ReviewRefused("T4 supervisor-final identity/authority drift")
    supervisor_expected = controller.expected_supervisor_review_claim(
        packet, profile.packet_sha256, final, final_sha)
    supervisor_review = one_marker(
        args.supervisor_review_record, controller.SUPERVISOR_REVIEW_MARKER,
        supervisor_expected, "T4 supervisor review")

    expected_commands = [runtime._child_command(
        index=index, packet=packet, packet_sha256=profile.packet_sha256,
        controller_review_record=args.packet_review_record,
        receipt_path=args.receipt, receipt_sha256=receipt_sha,
        capacity_result_path=args.capacity_result,
        capacity_result_sha256=capacity_sha,
        capacity_review_record=args.capacity_review_record,
        supervisor_slot_sha256=str(
            final["supervisor_admission_slot_sha256"]))
        for index in range(profile.shards)]
    if final["commands"] != expected_commands:
        raise ReviewRefused("T4 supervisor child command population drift")

    # Outcome-bearing bytes become readable only after both the aggregate
    # exists and the score-free final has an exact independent PASS.  Bind the
    # aggregate envelope before opening any shard payload.
    aggregate = load_json(args.aggregate, "T4 aggregate")
    aggregate_sha = sha256(args.aggregate)
    if (aggregate.get("schema") != runtime.AGGREGATE_SCHEMA
            or aggregate.get("run_id") != profile.run_id
            or aggregate.get("git") != profile.git
            or aggregate.get("controller_packet_sha256")
            != profile.packet_sha256
            or aggregate.get("screen_receipt_sha256") != receipt_sha
            or aggregate.get("supervisor_final_sha256") != final_sha
            or aggregate.get("supervisor_final_internal_sha256")
            != final["final_sha256"]
            or aggregate.get("supervisor_review_record_sha256")
            != supervisor_review["sha256"]
            or aggregate.get("supervisor_review_claim")
            != supervisor_review["claim"]
            or aggregate.get("aggregate_admission_slot")
            != controller.AGGREGATE_ADMISSION_PATH
            or not controller.is_sha256(
                aggregate.get("aggregate_admission_slot_sha256"))
            or aggregate.get("result_sha256")
            != controller.self_hash(aggregate, "result_sha256")):
        raise ReviewRefused("T4 aggregate pre-open binding drift")
    admission = load_json(args.aggregate_admission, "T4 aggregate admission")
    expected_admission = runtime._attempt_slot_payload(
        packet=packet, packet_sha256=profile.packet_sha256,
        receipt_sha256=receipt_sha,
        review_record=args.packet_review_record, kind="aggregate")
    if (sha256(args.aggregate_admission)
            != aggregate["aggregate_admission_slot_sha256"]
            or admission != expected_admission):
        raise ReviewRefused("T4 aggregate admission binding drift")

    merged = {label: [] for label in screen.LABELS}
    shard_manifest = []
    for index, (path, log_path, ref) in enumerate(
            zip(args.shards, args.logs, refs, strict=True)):
        shard = load_json(path, f"T4 shard {index}")
        ref_keys = {
            "index", "logical_path", "external_sha256", "internal_sha256",
            "log_logical_path", "log_sha256", "exit_code",
        }
        shard_keys = {
            "schema", "run_id", "git", "controller_packet_sha256",
            "screen_receipt_sha256", "supervisor_admission_slot",
            "supervisor_admission_slot_sha256", "attempt_admission_slot",
            "attempt_admission_slot_sha256", "shard_index", "seed0",
            "clusters", "records", "record_counts", "complete",
            "strength_claim", "confirmation_launch_authorized",
            "production_promotion", "production_deployment",
            "retry_or_extension_authorized", "shard_sha256",
        }
        if (not isinstance(ref, dict) or set(ref) != ref_keys
                or ref.get("index") != index
                or ref.get("logical_path") != controller.SHARD_PATHS[index]
                or ref.get("external_sha256") != sha256(path)
                or ref.get("internal_sha256") != shard.get("shard_sha256")
                or ref.get("log_logical_path")
                != controller.SHARD_LOG_PATHS[index]
                or ref.get("log_sha256") != sha256(log_path)
                or ref.get("exit_code") != 0
                or set(shard) != shard_keys
                or shard.get("schema") != runtime.SHARD_SCHEMA
                or shard.get("run_id") != profile.run_id
                or shard.get("git") != profile.git
                or shard.get("controller_packet_sha256")
                != profile.packet_sha256
                or shard.get("screen_receipt_sha256") != receipt_sha
                or shard.get("shard_index") != index
                or shard.get("seed0")
                != controller.SCREEN_SEED0 + index * controller.CLUSTERS_PER_SHARD
                or shard.get("clusters") != controller.CLUSTERS_PER_SHARD
                or shard.get("record_counts") != {
                    label: 2 * controller.CLUSTERS_PER_SHARD
                    for label in screen.LABELS}
                or shard.get("shard_sha256")
                != controller.self_hash(shard, "shard_sha256")
                or shard.get("complete") is not True
                or any(shard.get(field) is not False for field in (
                    "strength_claim", "confirmation_launch_authorized",
                    "production_promotion", "production_deployment",
                    "retry_or_extension_authorized"))):
            raise ReviewRefused(f"T4 shard {index} identity drift")
        records = shard.get("records")
        if not isinstance(records, dict) or set(records) != set(screen.LABELS):
            raise ReviewRefused(f"T4 shard {index} record population drift")
        # This pure call recursively checks outcome derivation, exact work,
        # telemetry reconciliation, and every shard statistic.
        screen.aggregate_screen(
            records, expected_seed0=shard["seed0"],
            expected_clusters=controller.CLUSTERS_PER_SHARD,
            expected_surface=str(packet["selected_capability"]["surface"]))
        for label in screen.LABELS:
            merged[label].extend(records[label])
        shard_manifest.append({
            "index": index,
            "logical_path": controller.SHARD_PATHS[index],
            "external_sha256": sha256(path),
            "internal_sha256": shard["shard_sha256"],
        })
    rebuilt = screen.aggregate_screen(
        merged, expected_seed0=controller.SCREEN_SEED0,
        expected_clusters=controller.SCREEN_CLUSTERS,
        expected_surface=str(packet["selected_capability"]["surface"]))
    expected = {
        "schema": runtime.AGGREGATE_SCHEMA,
        "run_id": profile.run_id,
        "git": profile.git,
        "controller_packet_sha256": profile.packet_sha256,
        "screen_receipt_sha256": receipt_sha,
        "supervisor_final_sha256": final_sha,
        "supervisor_final_internal_sha256": final["final_sha256"],
        "supervisor_review_record_sha256": supervisor_review["sha256"],
        "supervisor_review_claim": supervisor_review["claim"],
        "aggregate_admission_slot": aggregate.get("aggregate_admission_slot"),
        "aggregate_admission_slot_sha256": aggregate.get(
            "aggregate_admission_slot_sha256"),
        "selected_capability": packet["selected_capability"],
        "model_exports_sha256": packet["model_exports_sha256"],
        "shards": shard_manifest,
        "screen": rebuilt,
        "decision": rebuilt["status"],
        "confirmation_packet_review_authorized": (
            rebuilt["status"] == "AUTHORIZE_CONFIRM_PACKET_REVIEW"),
        "strength_claim": False,
        "confirmation_launch_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    expected["result_sha256"] = controller.self_hash(expected, "result_sha256")
    if (aggregate != expected
            or aggregate.get("aggregate_admission_slot")
            != controller.AGGREGATE_ADMISSION_PATH
            or not controller.is_sha256(
                aggregate.get("aggregate_admission_slot_sha256"))):
        raise ReviewRefused("T4 aggregate recursive reconstruction drift")
    return {
        "schema": profile.schema,
        "verifier_sha256": sha256(Path(__file__)),
        "git": profile.git,
        "run_id": profile.run_id,
        "packet_sha256": profile.packet_sha256,
        "receipt_sha256": receipt_sha,
        "supervisor_final_sha256": final_sha,
        "supervisor_review_record_sha256": supervisor_review["sha256"],
        "aggregate_sha256": aggregate_sha,
        "aggregate_internal_sha256": aggregate["result_sha256"],
        "clusters": controller.SCREEN_CLUSTERS,
        "primary_statistics": rebuilt["stats"],
        "criteria": rebuilt["criteria"],
        "decision": rebuilt["status"],
        "recursive_statistic_reconstruction": True,
        "all_shards_reopened": True,
        "outcomes_read_only_after_supervisor_review": True,
        "independent_review": True,
        "confirmation_packet_review_authorized": aggregate[
            "confirmation_packet_review_authorized"],
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def _pair_review(args, api, profile: Profile = PAIR) -> dict:
    paths = [args.packet, args.receipt, args.packet_review_record,
             args.supervisor_final, args.supervisor_review_record,
             args.aggregate_admission, args.aggregate,
             *args.shards, *args.logs]
    _distinct(paths)
    if len(args.shards) != profile.shards or len(args.logs) != profile.shards:
        raise ReviewRefused("pair requires exactly eight shards and eight logs")
    screen = api.screen
    packet = load_json(args.packet, "pair packet")
    packet_sha = sha256(args.packet)
    if (packet_sha != profile.packet_sha256
            or packet.get("schema") != screen.PACKET_SCHEMA
            or packet.get("run_id") != profile.run_id
            or packet.get("git") != profile.git
            or packet.get("source_sha256s") != dict(profile.source_sha256s)
            or packet.get("internal_sha256")
            != screen.stable_digest({
                key: value for key, value in packet.items()
                if key != "internal_sha256"})):
        raise ReviewRefused("pair packet identity/source drift")
    packet_review = one_marker(
        args.packet_review_record, screen.PACKET_REVIEW_PREFIX,
        screen.packet_review_claim(packet, packet_sha), "pair packet review")
    receipt = load_json(args.receipt, "pair receipt")
    receipt_sha = sha256(args.receipt)
    receipt_unsigned = dict(receipt)
    receipt_internal = receipt_unsigned.pop("internal_sha256", None)
    if (receipt_internal != screen.stable_digest(receipt_unsigned)
            or receipt.get("schema") != screen.RECEIPT_SCHEMA
            or receipt.get("run_id") != profile.run_id
            or receipt.get("git") != profile.git
            or receipt.get("packet_sha256") != packet_sha
            or receipt.get("packet_internal_sha256")
            != packet["internal_sha256"]
            or receipt.get("packet_review_record_sha256")
            != packet_review["sha256"]
            or receipt.get("packet_review_marker")
            != packet_review["marker"]
            or receipt.get("execution_admission_path")
            != str(screen.EXECUTION_ADMISSION_PATH.relative_to(screen.REPO))
            or not isinstance(receipt.get("execution_admission_sha256"), str)
            or len(receipt["execution_admission_sha256"]) != 64
            or not isinstance(receipt.get("nonce"), str)
            or len(receipt["nonce"]) != 64
            or isinstance(receipt.get("created_time_ns"), bool)
            or not isinstance(receipt.get("created_time_ns"), int)
            or receipt["created_time_ns"] <= 0
            or receipt.get("one_screen_execution_authorized") is not True
            or receipt.get("aggregate_execution_authorized") is not False
            or receipt.get("strength_claim") is not False
            or receipt.get("production_deployment") is not False
            or receipt.get("retry_or_extension_authorized") is not False):
        raise ReviewRefused("pair receipt identity/authority drift")

    final = load_json(args.supervisor_final, "pair supervisor final")
    final_sha = sha256(args.supervisor_final)
    final_unsigned = dict(final)
    final_internal = final_unsigned.pop("internal_sha256", None)
    refs = final.get("shards")
    if (final_internal != screen.stable_digest(final_unsigned)
            or final.get("schema") != screen.SUPERVISOR_SCHEMA
            or final.get("run_id") != profile.run_id
            or final.get("git") != profile.git
            or final.get("packet_sha256") != packet_sha
            or final.get("receipt_sha256") != receipt_sha
            or not isinstance(final.get("supervisor_admission_sha256"), str)
            or len(final["supervisor_admission_sha256"]) != 64
            or isinstance(final.get("elapsed_seconds"), bool)
            or not isinstance(final.get("elapsed_seconds"), (int, float))
            or not math.isfinite(final["elapsed_seconds"])
            or final["elapsed_seconds"] <= 0
            or not isinstance(refs, list) or len(refs) != profile.shards
            or final.get("all_shards_complete") is not True
            or final.get("outcomes_published") is not False
            or final.get("statistics_published") is not False
            or final.get("aggregate_execution_authorized") is not False
            or final.get("strength_claim") is not False
            or final.get("production_deployment") is not False
            or final.get("retry_or_extension_authorized") is not False):
        raise ReviewRefused("pair supervisor-final identity/authority drift")
    for index, (path, log_path, ref) in enumerate(
            zip(args.shards, args.logs, refs, strict=True)):
        if (not isinstance(ref, dict)
                or ref.get("index") != index
                or ref.get("path")
                != str(screen.SHARD_PATHS[index].relative_to(screen.REPO))
                or ref.get("clusters") != screen.CLUSTERS_PER_SHARD
                or ref.get("log_path")
                != str(screen.SHARD_LOG_PATHS[index].relative_to(screen.REPO))):
            raise ReviewRefused(f"pair supervisor shard {index} binding drift")
    supervisor_review = one_marker(
        args.supervisor_review_record, screen.SUPERVISOR_REVIEW_PREFIX,
        screen.supervisor_review_claim(
            packet, packet_sha, receipt_sha, final, final_sha),
        "pair supervisor review")

    # As in T4, bind the outcome-bearing envelope to the reviewed score-free
    # final before reading even one shard JSON payload.
    aggregate = load_json(args.aggregate, "pair aggregate")
    aggregate_sha = sha256(args.aggregate)
    aggregate_unsigned = dict(aggregate)
    aggregate_internal = aggregate_unsigned.pop("internal_sha256", None)
    if (aggregate_internal != screen.stable_digest(aggregate_unsigned)
            or aggregate.get("run_id") != profile.run_id
            or aggregate.get("git") != profile.git
            or aggregate.get("packet_sha256") != packet_sha
            or aggregate.get("receipt_sha256") != receipt_sha
            or aggregate.get("supervisor_final_sha256") != final_sha
            or aggregate.get("supervisor_review_record_sha256")
            != supervisor_review["sha256"]
            or aggregate.get("supervisor_review_marker")
            != supervisor_review["marker"]
            or not isinstance(aggregate.get("aggregate_admission_sha256"), str)
            or len(aggregate["aggregate_admission_sha256"]) != 64):
        raise ReviewRefused("pair aggregate pre-open binding drift")
    admission = load_json(
        args.aggregate_admission, "pair aggregate admission")
    admission_unsigned = dict(admission)
    admission_internal = admission_unsigned.pop("internal_sha256", None)
    expected_admission_keys = {
        "schema", "run_id", "git", "packet_sha256", "nonce",
        "created_time_ns", "retry_or_extension_authorized",
        "production_deployment", "receipt_sha256",
        "supervisor_review_record_sha256", "internal_sha256",
    }
    nonce = admission.get("nonce")
    created = admission.get("created_time_ns")
    if (sha256(args.aggregate_admission)
            != aggregate["aggregate_admission_sha256"]
            or set(admission) != expected_admission_keys
            or admission_internal != screen.stable_digest(admission_unsigned)
            or admission.get("schema")
            != "pair-aware-rollout-screen-aggregate-admission-v1"
            or admission.get("run_id") != profile.run_id
            or admission.get("git") != profile.git
            or admission.get("packet_sha256") != packet_sha
            or admission.get("receipt_sha256") != receipt_sha
            or admission.get("supervisor_review_record_sha256")
            != supervisor_review["sha256"]
            or not isinstance(nonce, str) or len(nonce) != 64
            or any(character not in "0123456789abcdef" for character in nonce)
            or isinstance(created, bool) or not isinstance(created, int)
            or created <= 0
            or admission.get("retry_or_extension_authorized") is not False
            or admission.get("production_deployment") is not False):
        raise ReviewRefused("pair aggregate admission binding drift")

    for index, (path, log_path, ref) in enumerate(
            zip(args.shards, args.logs, refs, strict=True)):
        if (ref.get("sha256") != sha256(path)
                or ref.get("log_sha256") != sha256(log_path)):
            raise ReviewRefused(f"pair supervisor shard {index} hash drift")

    shards = []
    for index, path in enumerate(args.shards):
        shard = load_json(path, f"pair shard {index}")
        screen.validate_shard(
            shard, packet=packet, packet_sha256=packet_sha,
            receipt_sha256=receipt_sha, shard_index=index)
        shards.append(shard)
    rebuilt = screen.aggregate_payload(
        packet=packet, packet_sha256=packet_sha,
        receipt_sha256=receipt_sha, shard_values=shards,
        shard_sha256s=[sha256(path) for path in args.shards],
        supervisor_final_sha256=final_sha,
        supervisor_review=supervisor_review)
    expected = dict(rebuilt)
    expected["aggregate_admission_sha256"] = aggregate.get(
        "aggregate_admission_sha256")
    expected.pop("internal_sha256")
    expected["internal_sha256"] = screen.stable_digest(expected)
    if (aggregate != expected
            or not isinstance(aggregate.get("aggregate_admission_sha256"), str)
            or len(aggregate["aggregate_admission_sha256"]) != 64):
        raise ReviewRefused("pair aggregate recursive reconstruction drift")
    return {
        "schema": profile.schema,
        "verifier_sha256": sha256(Path(__file__)),
        "git": profile.git,
        "run_id": profile.run_id,
        "packet_sha256": packet_sha,
        "receipt_sha256": receipt_sha,
        "supervisor_final_sha256": final_sha,
        "supervisor_review_record_sha256": supervisor_review["sha256"],
        "aggregate_sha256": aggregate_sha,
        "aggregate_internal_sha256": aggregate["internal_sha256"],
        "clusters": screen.SCREEN_CLUSTERS,
        "primary_level_utility": aggregate["primary_level_utility"],
        "secondary_game_win_rate": aggregate["secondary_game_win_rate"],
        "natural_dose": aggregate["natural_dose"],
        "integrity": aggregate["integrity"],
        "decision": aggregate["status"],
        "recursive_statistic_reconstruction": True,
        "all_shards_reopened": True,
        "outcomes_read_only_after_supervisor_review": True,
        "independent_review": True,
        "confirmation_packet_design_authorized": aggregate[
            "confirmation_packet_design_authorized"],
        "confirmation_execution_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("profile", choices=("t4", "pair"))
    root.add_argument("--source-repo", type=Path, required=True)
    root.add_argument("--packet", type=Path, required=True)
    root.add_argument("--packet-review-record", type=Path, required=True)
    root.add_argument("--capacity-result", type=Path)
    root.add_argument("--capacity-review-record", type=Path)
    root.add_argument("--receipt", type=Path, required=True)
    root.add_argument("--supervisor-final", type=Path, required=True)
    root.add_argument("--supervisor-review-record", type=Path, required=True)
    root.add_argument("--aggregate-admission", type=Path, required=True)
    root.add_argument("--aggregate", type=Path, required=True)
    root.add_argument("--shards", type=Path, nargs="+", required=True)
    root.add_argument("--logs", type=Path, nargs="+", required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    profile = T4 if args.profile == "t4" else PAIR
    if profile is T4 and (args.capacity_result is None
                          or args.capacity_review_record is None):
        raise ReviewRefused(
            "T4 requires --capacity-result and --capacity-review-record")
    if profile is PAIR and (args.capacity_result is not None
                            or args.capacity_review_record is not None):
        raise ReviewRefused("pair profile does not accept T4 capacity inputs")
    api = _load_source(profile, args.source_repo)
    claim = (_t4_review(args, api, profile) if profile is T4
             else _pair_review(args, api, profile))
    print(profile.marker + json.dumps(
        claim, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReviewRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

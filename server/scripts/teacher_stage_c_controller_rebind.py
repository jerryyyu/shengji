#!/usr/bin/env python3
"""Freeze the score-free Stage-C controller-dependency rebind.

The independently passed Stage-C-v3 curriculum is immutable, but it names
H0-v2 and S3c-v1 controllers that cannot reopen after their one-shot admission
files are published.  This bridge binds the reviewed H0-v3 and S3c-v2
replacements without copying or changing the curriculum.  A future capture
controller must consume both the original design packet and this bridge.

Freeze and verify read packet geometry and external review markers only.  They
do not capture a state, sample a world, run a solver, compute an outcome, label
an action, train a model, promote a policy, or deploy code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Mapping


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SCRIPT.parent))

import h0_human_counterfactual_controller as H0  # noqa: E402
import s3c_one_card_controller as S3C  # noqa: E402
import teacher_stage_c_design as BASE  # noqa: E402


SCHEMA = "teacher-stage-c-controller-rebind-v1"
PACKET_ID = "teacher-v3-hard-tail-stage-c-controller-rebind-v1"
REVIEW_SCHEMA = "teacher-stage-c-controller-rebind-review-v1"
REVIEW_MARKER = "TEACHER_STAGE_C_CONTROLLER_REBIND_V1_REVIEW "
REVIEW_CLAIM_FIELDS = (
    "schema", "git", "script_sha256", "packet_sha256",
    "base_stage_c_sha256", "base_stage_c_review_schema",
    "h0_controller_sha256", "h0_controller_review_schema",
    "s3c_controller_sha256", "s3c_controller_review_schema", "states",
    "play_candidate_cap", "bury_candidate_cap", "max_candidate_worlds",
    "recursive_mc_continuation_rollouts", "curriculum_changed",
    "worlds_sampled_before_review", "exact_solver_sessions_before_review",
    "outcomes_computed_before_review", "independent_review",
    "capture_controller_implementation_authorized",
    "state_capture_authorized", "labels_authorized", "training_authorized",
    "strength_claim", "production_promotion", "production_deployment",
    "verdict",
)

BASE_PACKET_SHA256 = (
    "f213314ace8ead497fcaccde150d0694851069b970948a10d0823cf74ceb93b4"
)
H0_PACKET_SHA256 = (
    "cf074871cf977c0b072c528c395082b453b3b589f445c524baae9016e1d35392"
)
S3C_PACKET_SHA256 = (
    "cafbee439f8c30a07b0b6801d52620d7197afc3633badbc531bc5b156ce2f23e"
)
H0_SOURCE_GIT = "4ebcd09111af0ef76ffd6f862764f28b275e4383"
S3C_SOURCE_GIT = H0_SOURCE_GIT
SUPERSEDED_H0_PACKET_SHA256 = BASE.H0_CONTROLLER_SHA256
SUPERSEDED_S3C_PACKET_SHA256 = BASE.S3C_CONDITIONAL[
    "controller_packet_sha256"]


class RebindRefused(RuntimeError):
    """A packet, review, authority, or immutable-curriculum binding drifted."""


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


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise RebindRefused(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RebindRefused(f"JSON root is not an object: {path}")
    return value


def require_regular_unlinked(path: Path, label: str) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise RebindRefused(f"{label} is unavailable") from exc
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or path.is_symlink()):
        raise RebindRefused(f"{label} is not regular/unlinked")


def marker_claim(path: Path, marker: str) -> dict:
    require_regular_unlinked(path, "review record")
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        raise RebindRefused("cannot read review record") from exc
    matches = [line[len(marker):] for line in lines if line.startswith(marker)]
    if len(matches) != 1:
        raise RebindRefused(
            f"review record must contain exactly one {marker.strip()} marker")
    try:
        claim = json.loads(matches[0])
    except ValueError as exc:
        raise RebindRefused("review marker is not valid JSON") from exc
    if not isinstance(claim, dict):
        raise RebindRefused("review marker claim is not an object")
    return claim


def self_hash(packet: Mapping[str, object]) -> str:
    return sha256_bytes(canonical_json({
        key: value for key, value in packet.items()
        if key != "packet_sha256"
    }))


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def producer_identity(*, smoke: bool) -> dict:
    git = _git("rev-parse", "HEAD")
    dirty = bool(_git("status", "--porcelain", "--untracked-files=all"))
    if dirty and not smoke:
        raise RebindRefused("real Stage-C rebind refuses a dirty tree")
    return {
        "git": git,
        "tree_dirty": dirty,
        "promotable": not smoke,
        "script_sha256": sha256_file(__file__),
    }


def expected_h0_review_claim(packet: dict) -> dict:
    preflight = packet["score_free_preflight"]
    runtime = packet["execution_runtime"]
    sources = packet["runtime_sources"]
    inputs = packet["inputs"]
    return {
        "schema": H0.REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "controller_script_sha256": packet["producer"]["script_sha256"],
        "runtime_script_sha256": sources[
            "server/scripts/h0_human_counterfactual_runtime.py"],
        "packet_sha256": H0_PACKET_SHA256,
        "design_packet_sha256": packet["design"]["sha256"],
        "design_review_git": packet["design"]["review_git"],
        "corpus_manifest_sha256": inputs["human_corpus"]["manifest_sha256"],
        "source_manifest_sha256": inputs["source_snapshot"][
            "manifest_sha256"],
        "v11_checkpoint_sha256": inputs["v11pair"]["sha256"],
        "selected_play_rows_sha256": inputs["selected_play_rows_sha256"],
        "selected_bury_rows_sha256": inputs["selected_bury_rows_sha256"],
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "candidate_geometry_sha256": preflight[
            "candidate_geometry_sha256"],
        "max_candidate_worlds": packet["result_contract"]["work"][
            "candidate_world_ceiling"],
        "score_free_preflight_verified": True,
        "strict_runtime_verified": True,
        "fast_router_sha256": runtime["fast_router_sha256"],
        "compiled_fast_binary_sha256": runtime[
            "compiled_fast_binary_sha256"],
        "admission_slot_logical_path": packet["result_contract"][
            "durable_one_shot_admission_slot"],
        "deletion_proof_one_shot": True,
        "worlds_sampled_before_review": 0,
        "outcomes_computed_before_review": False,
        "independent_review": True,
        "one_counterfactual_execution_authorized": True,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def expected_s3c_review_claim(packet: dict) -> dict:
    schedule = packet["schedule"]
    preflight = packet["score_free_preflight"]
    sources = packet["runtime_sources"]
    return {
        "schema": S3C.REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "controller_script_sha256": packet["producer"][
            "controller_script_sha256"],
        "runtime_script_sha256": sources[
            "server/scripts/s3c_one_card_runtime.py"],
        "packet_sha256": S3C_PACKET_SHA256,
        "design_packet_sha256": packet["design"]["external_sha256"],
        "census_sha256": packet["census"]["external_sha256"],
        "design_review_git": packet["design"]["review_git"],
        "schedule_sha256": schedule["schedule_sha256"],
        "root_geometry_sha256": preflight["root_geometry_sha256"],
        "roots": schedule["root_count"],
        "worlds": sum(len(root["worlds"]) for root in schedule["roots"]),
        "max_execution_nodes": schedule["max_execution_nodes"],
        "max_terminal_replay_nodes": schedule["max_terminal_replay_nodes"],
        "score_free_preflight_verified": True,
        "worlds_sampled_before_review": 0,
        "exact_solver_sessions_before_review": 0,
        "outcomes_computed_before_review": False,
        "independent_review": True,
        "one_card_capacity_execution_authorized": True,
        "two_card_packet_review_authorized": False,
        "solver_or_strength_screen_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def validate_base(path: Path, review_record: Path) -> tuple[dict, dict]:
    require_regular_unlinked(path, "base Stage-C packet")
    if sha256_file(path) != BASE_PACKET_SHA256:
        raise RebindRefused("base Stage-C external SHA-256 drift")
    packet = load_json(path)
    authority = packet.get("authority", {})
    if (packet.get("schema") != BASE.SCHEMA
            or packet.get("packet_id") != BASE.PACKET_ID
            or packet.get("packet_sha256") != self_hash(packet)
            or packet.get("population_contract", {}).get("total_states") != 2048
            or packet.get("work_contract", {}).get(
                "all_optional_mechanisms_max") != 10_494_720
            or authority.get("score_free") is not True
            or authority.get("worlds_sampled") is not False
            or authority.get("outcomes_computed") is not False
            or authority.get("state_capture_authorized") is not False
            or authority.get("labels_authorized") is not False
            or authority.get("training_authorized") is not False):
        raise RebindRefused("base Stage-C identity/authority drift")
    claim = marker_claim(review_record, BASE.REVIEW_MARKER)
    if claim != BASE.expected_review_claim(packet, BASE_PACKET_SHA256):
        raise RebindRefused("base Stage-C PASS marker drift")
    return packet, claim


def validate_h0(path: Path, review_record: Path) -> tuple[dict, dict]:
    require_regular_unlinked(path, "H0-v3 packet")
    if sha256_file(path) != H0_PACKET_SHA256:
        raise RebindRefused("H0-v3 external SHA-256 drift")
    packet = load_json(path)
    preflight = packet.get("score_free_preflight", {})
    result = packet.get("result_contract", {})
    authority = packet.get("authority", {})
    if (packet.get("schema") != H0.SCHEMA
            or packet.get("packet_id") != H0.PACKET_ID
            or packet.get("run_id") != H0.RUN_ID
            or packet.get("producer", {}).get("git") != H0_SOURCE_GIT
            or packet.get("packet_sha256") != self_hash(packet)
            or preflight.get("rows_replayed") != 557
            or preflight.get("worlds_sampled") != 0
            or preflight.get("candidate_world_rollouts") != 0
            or preflight.get("outcomes_computed") is not False
            or result.get("admission_slot_gitignored") is not True
            or result.get("admit_then_runtime_reopen_required") is not True
            or result.get("unrelated_git_dirt_refused") is not True
            or authority.get("score_free") is not True
            or authority.get("counterfactual_execution_authorized") is not False
            or authority.get("labels_authorized") is not False
            or authority.get("training_authorized") is not False):
        raise RebindRefused("H0-v3 identity/authority drift")
    claim = marker_claim(review_record, H0.REVIEW_MARKER)
    if claim != expected_h0_review_claim(packet):
        raise RebindRefused("H0-v3 PASS marker drift")
    return packet, claim


def validate_s3c(path: Path, review_record: Path) -> tuple[dict, dict]:
    require_regular_unlinked(path, "S3c-v2 packet")
    if sha256_file(path) != S3C_PACKET_SHA256:
        raise RebindRefused("S3c-v2 external SHA-256 drift")
    packet = load_json(path)
    preflight = packet.get("score_free_preflight", {})
    result = packet.get("result_contract", {})
    authority = packet.get("authority", {})
    if (packet.get("schema") != S3C.SCHEMA
            or packet.get("packet_id") != S3C.PACKET_ID
            or packet.get("run_id") != S3C.RUN_ID
            or packet.get("producer", {}).get("git") != S3C_SOURCE_GIT
            or packet.get("packet_sha256") != self_hash(packet)
            or preflight.get("roots_replayed") != 64
            or preflight.get("worlds_sampled") != 0
            or preflight.get("exact_solver_sessions") != 0
            or preflight.get("outcomes_computed") is not False
            or result.get("admission_slot_gitignored") is not True
            or result.get("admit_then_runtime_reopen_required") is not True
            or result.get("unrelated_git_dirt_refused") is not True
            or authority.get("score_free") is not True
            or authority.get("one_card_capacity_execution_authorized")
            is not False
            or authority.get("solver_or_strength_screen_authorized") is not False
            or authority.get("training_authorized") is not False):
        raise RebindRefused("S3c-v2 identity/authority drift")
    claim = marker_claim(review_record, S3C.REVIEW_MARKER)
    if claim != expected_s3c_review_claim(packet):
        raise RebindRefused("S3c-v2 PASS marker drift")
    return packet, claim


def curriculum_commitments(base: dict) -> dict:
    fields = (
        "objective", "population_contract", "candidate_contract",
        "label_contract", "work_contract", "gate_contract",
        "execution_stages",
    )
    return {
        field: sha256_bytes(canonical_json(base[field])) for field in fields
    }


def build_packet(base_path: Path, h0_path: Path, s3c_path: Path,
                 review_record: Path, *, smoke: bool) -> dict:
    base, base_review = validate_base(base_path, review_record)
    h0, h0_review = validate_h0(h0_path, review_record)
    s3c, s3c_review = validate_s3c(s3c_path, review_record)
    commitments = curriculum_commitments(base)
    packet = {
        "schema": SCHEMA,
        "packet_id": PACKET_ID,
        "producer": producer_identity(smoke=smoke),
        "base_stage_c": {
            "schema": base["schema"],
            "packet_id": base["packet_id"],
            "external_sha256": BASE_PACKET_SHA256,
            "internal_sha256": base["packet_sha256"],
            "review_claim": base_review,
            "curriculum_commitments": commitments,
            "states": base["population_contract"]["total_states"],
            "max_candidate_worlds": base["work_contract"][
                "all_optional_mechanisms_max"],
        },
        "replacement_bindings": {
            "h0": {
                "schema": h0["schema"],
                "packet_id": h0["packet_id"],
                "external_sha256": H0_PACKET_SHA256,
                "internal_sha256": h0["packet_sha256"],
                "source_git": h0["producer"]["git"],
                "review_claim": h0_review,
                "supersedes_packet_sha256": SUPERSEDED_H0_PACKET_SHA256,
                "execution_remains_separately_admitted": True,
                "execution_result_is_not_label_authority": True,
            },
            "s3c": {
                "schema": s3c["schema"],
                "packet_id": s3c["packet_id"],
                "external_sha256": S3C_PACKET_SHA256,
                "internal_sha256": s3c["packet_sha256"],
                "source_git": s3c["producer"]["git"],
                "review_claim": s3c_review,
                "supersedes_packet_sha256": SUPERSEDED_S3C_PACKET_SHA256,
                "one_card_result_remains_conditional": True,
                "two_or_three_card_requires_separate_review": True,
            },
        },
        "delta_contract": {
            "allowed_changes": [
                "H0 controller packet/review schema and lock namespace",
                "S3c controller packet/review schema and lock namespace",
            ],
            "curriculum_fields_copied_or_rewritten": False,
            "population_changed": False,
            "candidate_contract_changed": False,
            "label_contract_changed": False,
            "work_contract_changed": False,
            "gate_contract_changed": False,
            "state_count": 2048,
            "play_candidate_cap": base["candidate_contract"][
                "max_unique_play_actions"],
            "bury_candidate_cap": base["candidate_contract"][
                "max_unique_bury_actions"],
            "max_candidate_worlds": base["work_contract"][
                "all_optional_mechanisms_max"],
            "recursive_mc_continuation_rollouts": base["work_contract"][
                "recursive_mc_continuation_rollouts"],
        },
        "consumer_contract": {
            "capture_controller_must_reopen_base_and_rebind": True,
            "capture_controller_must_reopen_both_replacement_pass_markers": True,
            "superseded_h0_or_s3c_packet_must_refuse": True,
            "capture_controller_implementation_authorized_only_after_review":
                True,
            "state_capture_requires_separate_packet_review": True,
            "labels_require_separate_packet_review": True,
        },
        "review_contract": {
            "schema": REVIEW_SCHEMA,
            "marker": REVIEW_MARKER.strip(),
            "required_verdict": "PASS",
            "pass_authorizes": (
                "implementation of one score-free Stage-C capture/controller "
                "that consumes the exact base design plus this rebind"
            ),
            "pass_does_not_authorize": [
                "state capture", "belief-world sampling", "solver work",
                "labels", "training", "strength", "promotion", "deployment",
            ],
            "required_claim_fields": list(REVIEW_CLAIM_FIELDS),
            "packet_sha256_field": "external SHA-256 of canonical packet file",
        },
        "authority": {
            "score_free": True,
            "worlds_sampled": False,
            "exact_solver_invoked": False,
            "outcomes_computed": False,
            "curriculum_changed": False,
            "rebind_review_authorized": True,
            "capture_controller_implementation_authorized": False,
            "state_capture_authorized": False,
            "labels_authorized": False,
            "training_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    packet["packet_sha256"] = self_hash(packet)
    return packet


def packet_problems(actual: dict, expected: dict) -> list[str]:
    problems = []
    if actual != expected:
        problems.append("Stage-C rebind full recomputation drift")
    authority = actual.get("authority", {})
    delta = actual.get("delta_contract", {})
    if (authority != expected.get("authority")
            or authority.get("score_free") is not True
            or authority.get("worlds_sampled") is not False
            or authority.get("exact_solver_invoked") is not False
            or authority.get("outcomes_computed") is not False
            or authority.get("curriculum_changed") is not False
            or authority.get("capture_controller_implementation_authorized")
            is not False
            or authority.get("state_capture_authorized") is not False
            or authority.get("labels_authorized") is not False
            or authority.get("training_authorized") is not False
            or authority.get("strength_claim") is not False
            or authority.get("production_promotion") is not False
            or authority.get("production_deployment") is not False):
        problems.append("Stage-C rebind authority widened")
    if (delta.get("curriculum_fields_copied_or_rewritten") is not False
            or delta.get("population_changed") is not False
            or delta.get("candidate_contract_changed") is not False
            or delta.get("label_contract_changed") is not False
            or delta.get("work_contract_changed") is not False
            or delta.get("gate_contract_changed") is not False):
        problems.append("Stage-C curriculum delta widened")
    return sorted(set(problems))


def expected_review_claim(packet: dict, external_sha256: str) -> dict:
    if (packet.get("schema") != SCHEMA
            or packet.get("producer", {}).get("promotable") is not True
            or len(external_sha256) != 64):
        raise RebindRefused("cannot derive review claim")
    delta = packet["delta_contract"]
    claim = {
        "schema": REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "script_sha256": packet["producer"]["script_sha256"],
        "packet_sha256": external_sha256,
        "base_stage_c_sha256": BASE_PACKET_SHA256,
        "base_stage_c_review_schema": BASE.REVIEW_SCHEMA,
        "h0_controller_sha256": H0_PACKET_SHA256,
        "h0_controller_review_schema": H0.REVIEW_SCHEMA,
        "s3c_controller_sha256": S3C_PACKET_SHA256,
        "s3c_controller_review_schema": S3C.REVIEW_SCHEMA,
        "states": delta["state_count"],
        "play_candidate_cap": delta["play_candidate_cap"],
        "bury_candidate_cap": delta["bury_candidate_cap"],
        "max_candidate_worlds": delta["max_candidate_worlds"],
        "recursive_mc_continuation_rollouts": delta[
            "recursive_mc_continuation_rollouts"],
        "curriculum_changed": False,
        "worlds_sampled_before_review": 0,
        "exact_solver_sessions_before_review": 0,
        "outcomes_computed_before_review": False,
        "independent_review": True,
        "capture_controller_implementation_authorized": True,
        "state_capture_authorized": False,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }
    if tuple(claim) != REVIEW_CLAIM_FIELDS:
        raise RebindRefused("review claim field order/set drift")
    return claim


def publish_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    partial = Path(str(path) + ".partial")
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path) or os.path.lexists(partial):
        raise RebindRefused("refusing existing packet or partial")
    try:
        with partial.open("xb") as handle:
            handle.write(canonical_json(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.link(partial, path)
        partial.unlink()
    except Exception:
        if partial.exists() and not path.exists():
            partial.unlink()
        raise
    require_regular_unlinked(path, "published rebind packet")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("freeze", "verify"):
        child = sub.add_parser(command)
        child.add_argument("--base-stage-c", required=True)
        child.add_argument("--h0-controller", required=True)
        child.add_argument("--s3c-controller", required=True)
        child.add_argument("--review-record", required=True)
        child.add_argument("--packet", required=True)
        child.add_argument("--expected-git")
        child.add_argument("--smoke", action="store_true")
        if command == "verify":
            child.add_argument("--expected-packet-sha256")
    return parser


def main() -> None:
    args = _parser().parse_args()
    if not args.smoke and not args.expected_git:
        raise RebindRefused("real rebind freeze/verify requires --expected-git")
    if (args.command == "verify" and not args.smoke
            and not args.expected_packet_sha256):
        raise RebindRefused("real rebind verify requires packet SHA-256")
    if args.expected_git and _git("rev-parse", "HEAD") != args.expected_git:
        raise RebindRefused("producer Git differs from expected Git")
    expected = build_packet(
        Path(args.base_stage_c), Path(args.h0_controller),
        Path(args.s3c_controller), Path(args.review_record), smoke=args.smoke)
    packet_path = Path(args.packet)
    if args.command == "freeze":
        publish_exclusive(packet_path, expected)
        print(json.dumps({
            "status": "FROZEN_FOR_REBIND_REVIEW",
            "packet": str(packet_path),
            "sha256": sha256_file(packet_path),
            "states_captured": 0,
            "compute_authorized": False,
        }, sort_keys=True))
        return
    require_regular_unlinked(packet_path, "rebind packet")
    if (args.expected_packet_sha256
            and sha256_file(packet_path) != args.expected_packet_sha256):
        raise RebindRefused("external rebind packet SHA-256 drift")
    actual = load_json(packet_path)
    problems = packet_problems(actual, expected)
    if problems:
        raise RebindRefused("; ".join(problems))
    print(json.dumps({
        "status": "VERIFIED_FOR_REBIND_REVIEW",
        "packet": str(packet_path),
        "sha256": sha256_file(packet_path),
        "states_captured": 0,
        "compute_authorized": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()

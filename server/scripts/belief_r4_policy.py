#!/usr/bin/env python3
"""Capacity, freeze, execution, and cheap verification for R4 policy use."""

from __future__ import annotations

import sys


if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("R4 policy diagnostic requires Python -P -B")

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

from shengji.rl.belief_artifacts import (
    publish_exclusive_bytes,
    stable_read_bytes,
)
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.belief_policy_controller import (
    CAPACITY_WORKER_ARMS,
    run_score_free_capacity,
    run_scientific_diagnostic,
    verify_scientific_diagnostic,
)
from shengji.rl.belief_policy_execution import (
    FREEZE_REVIEW_PREFIX,
    SOURCE_REVIEW_PREFIX,
    authenticate_capacity_envelope_source,
    authenticate_review,
    authenticate_scientific_freeze_review,
    build_admission,
    build_capacity_envelope,
    build_freeze,
    build_runtime_identity,
    build_source_identity,
    expected_freeze_review_claim,
    expected_source_review_claim,
    model_identity,
    validate_freeze,
)
from shengji.rl.belief_policy_models import load_r4_policy_models


SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[2]


def _strict(path: Path) -> dict:
    raw = stable_read_bytes(path)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path.name} is not JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise ValueError(f"{path.name} is not canonical")
    return value


def _models(args):
    return load_r4_policy_models(
        args.model_root.resolve(),
        expected_freeze_sha256=args.r4_freeze_sha256,
        expected_admission_sha256=args.r4_admission_sha256)


def _progress(stage: str):
    started = time.monotonic_ns()

    def update(payload: dict) -> None:
        if type(payload) is not dict:
            raise ValueError("policy progress payload drift")
        completed = payload.get("completed")
        total = payload.get("total")
        if type(completed) is not int or type(total) is not int \
                or not 0 <= completed <= total or total <= 0:
            raise ValueError("policy progress count drift")
        elapsed = time.monotonic_ns() - started
        row = dict(payload)
        if "estimated_remaining_seconds" not in row:
            remaining = None if completed == 0 else (
                elapsed * (total - completed) // completed)
            row["estimated_remaining_seconds"] = (
                None if remaining is None else remaining // 1_000_000_000)
        row.update({
            "stage": stage,
            "percent": completed * 100 // total,
            "elapsed_seconds": elapsed // 1_000_000_000,
            "outcome_blind_progress": True,
        })
        print(json.dumps(
            row, sort_keys=True, separators=(",", ":")), flush=True)
    return update


def _add_model_args(parser) -> None:
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--r4-freeze-sha256", required=True)
    parser.add_argument("--r4-admission-sha256", required=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    source_claim = commands.add_parser("source-review-claim")
    source_claim.add_argument("--expected-git", required=True)
    _add_model_args(source_claim)

    capacity = commands.add_parser("capacity")
    capacity.add_argument("--expected-git", required=True)
    capacity.add_argument("--source-review-commit", required=True)
    capacity.add_argument("--out", type=Path, required=True)
    _add_model_args(capacity)

    freeze_command = commands.add_parser("freeze")
    freeze_command.add_argument("--capacity-envelope", type=Path,
                                required=True)
    freeze_command.add_argument("--evidence-root", type=Path, required=True)
    freeze_command.add_argument("--model-root", type=Path, required=True)
    freeze_command.add_argument("--out", type=Path, required=True)

    freeze_claim = commands.add_parser("freeze-review-claim")
    freeze_claim.add_argument("freeze", type=Path)

    initialize = commands.add_parser("initialize")
    initialize.add_argument("--freeze", type=Path, required=True)
    initialize.add_argument("--freeze-review-commit", required=True)

    run = commands.add_parser("run")
    run.add_argument("root", type=Path)

    verify = commands.add_parser("verify")
    verify.add_argument("root", type=Path)

    args = parser.parse_args()
    if os.environ.get("PYTHONPATH"):
        raise ValueError("R4 policy diagnostic refuses PYTHONPATH")

    if args.command == "source-review-claim":
        source = build_source_identity(
            REPO, expected_git=args.expected_git)
        models = _models(args)
        claim = expected_source_review_claim(source=source, models=models)
        sys.stdout.buffer.write(
            SOURCE_REVIEW_PREFIX.encode("ascii")
            + canonical_json_bytes(claim))
        return

    if args.command == "capacity":
        output = args.out.resolve()
        attempt_path = Path(str(output) + ".attempt.json")
        if output.exists() or output.is_symlink() \
                or attempt_path.exists() or attempt_path.is_symlink():
            raise ValueError("capacity output already exists")
        source = build_source_identity(
            REPO, expected_git=args.expected_git)
        runtime = build_runtime_identity()
        models = _models(args)
        claim = expected_source_review_claim(source=source, models=models)
        marker = authenticate_review(
            repo=REPO, review_commit=args.source_review_commit,
            prefix=SOURCE_REVIEW_PREFIX, claim=claim)
        publish_exclusive_bytes(attempt_path, canonical_json_bytes({
            "execution_git": args.expected_git,
            "source_manifest_sha256": source["source_manifest_sha256"],
            "source_review_commit": args.source_review_commit,
            "source_review_marker_sha256": hashlib.sha256(marker).hexdigest(),
            "worker_arms": list(CAPACITY_WORKER_ARMS),
            "contains_actions": False,
            "contains_outcomes": False,
            "scientific_execution_authorized": False,
            "retry_authorized": False,
        }))
        receipt = run_score_free_capacity(
            models=models, execution_git=args.expected_git,
            source_manifest_sha256=source["source_manifest_sha256"],
            progress=_progress("capacity"))
        envelope = build_capacity_envelope(
            receipt, source=source, runtime=runtime, models=models,
            source_review_commit=args.source_review_commit,
            source_review_marker=marker)
        digest = publish_exclusive_bytes(
            output, canonical_json_bytes(envelope))
        print(json.dumps({
            "capacity_envelope": str(output),
            "capacity_envelope_sha256": digest,
            "selected_workers": receipt["selected_workers"],
            "headroom_workers": receipt["headroom_workers"],
            "scientific_execution_authorized": False,
        }, sort_keys=True, separators=(",", ":")))
        return

    if args.command == "freeze":
        output = args.out.resolve()
        if output.exists() or output.is_symlink():
            raise ValueError("freeze output already exists")
        envelope_path = args.capacity_envelope.resolve()
        envelope_raw = stable_read_bytes(envelope_path)
        envelope = _strict(envelope_path)
        authenticate_capacity_envelope_source(
            repo=REPO, envelope=envelope)
        freeze = build_freeze(
            envelope_raw,
            evidence_root=args.evidence_root.resolve(),
            model_root=args.model_root.resolve())
        digest = publish_exclusive_bytes(
            output, canonical_json_bytes(freeze))
        print(json.dumps({
            "freeze": str(output), "freeze_sha256": digest,
            "scientific_execution_authorized": False,
        }, sort_keys=True, separators=(",", ":")))
        return

    if args.command == "freeze-review-claim":
        freeze = _strict(args.freeze.resolve())
        claim = expected_freeze_review_claim(freeze)
        sys.stdout.buffer.write(
            FREEZE_REVIEW_PREFIX.encode("ascii")
            + canonical_json_bytes(claim))
        return

    if args.command == "initialize":
        freeze_path = args.freeze.resolve()
        freeze = _strict(freeze_path)
        validate_freeze(freeze)
        root = Path(freeze["evidence_root"])
        if root.exists() or root.is_symlink():
            raise ValueError("scientific evidence root already exists")
        marker = authenticate_review(
            repo=REPO, review_commit=args.freeze_review_commit,
            prefix=FREEZE_REVIEW_PREFIX,
            claim=expected_freeze_review_claim(freeze))
        admission = build_admission(
            freeze, review_commit=args.freeze_review_commit,
            review_marker=marker)
        root.mkdir(parents=True)
        publish_exclusive_bytes(root / "freeze.json",
                                canonical_json_bytes(freeze))
        publish_exclusive_bytes(root / "admission.json",
                                canonical_json_bytes(admission))
        publish_exclusive_bytes(root / "review.marker", marker)
        print(json.dumps({
            "evidence_root": str(root), "initialized": True,
            "scientific_execution_authorized": True,
            "r4_test_opening_authorized": False,
        }, sort_keys=True, separators=(",", ":")))
        return

    root = args.root.resolve()
    if args.command == "verify":
        manifest = verify_scientific_diagnostic(root)
        print(json.dumps({
            "verified": True,
            "route": manifest["terminal"]["route"],
            "round_count": manifest["terminal"]["round_count"],
            "expensive_reconstruction_performed": False,
        }, sort_keys=True, separators=(",", ":")))
        return
    freeze_raw = stable_read_bytes(root / "freeze.json")
    freeze = _strict(root / "freeze.json")
    validate_freeze(freeze)
    if Path(freeze["evidence_root"]) != root:
        raise ValueError("scientific evidence root drift")
    admission = _strict(root / "admission.json")
    marker = stable_read_bytes(root / "review.marker")
    claim_marker = FREEZE_REVIEW_PREFIX.encode("ascii") \
        + canonical_json_bytes(expected_freeze_review_claim(freeze))
    admission_authority = admission.get("authority")
    if set(admission) != {
            "schema", "freeze_sha256", "review_commit",
            "review_marker_sha256", "created_unix_nanoseconds",
            "authority"} \
            or admission.get("schema") \
            != "belief-r4-policy-scientific-admission-v1" \
            or admission.get("freeze_sha256") \
            != hashlib.sha256(freeze_raw).hexdigest() \
            or admission.get("review_marker_sha256") \
            != hashlib.sha256(marker).hexdigest() \
            or marker != claim_marker \
            or not isinstance(admission.get("created_unix_nanoseconds"), int) \
            or admission_authority != {
                "one_scientific_execution_authorized": True,
                "resume_missing_shards_before_deadline_authorized": True,
                "r4_test_opening_authorized": False,
                "retry_after_terminal_authorized": False,
                "r5_authorized": False,
                "gameplay_authorized": False,
                "strength_claim_authorized": False,
                "deployment_authorized": False,
            }:
        raise ValueError("scientific admission drift")
    authenticate_scientific_freeze_review(
        repo=REPO, freeze=freeze, admission=admission, marker=marker)
    source = build_source_identity(
        REPO, expected_git=freeze["execution_git"])
    runtime = build_runtime_identity()
    if source["source_manifest_sha256"] \
            != freeze["source_manifest_sha256"] \
            or runtime["compatibility_sha256"] \
            != freeze["runtime_compatibility_sha256"]:
        raise ValueError("scientific live source/runtime drift")
    if (root / "manifest.json").exists():
        raise ValueError("scientific terminal already exists")
    models = load_r4_policy_models(
        Path(freeze["model_root"]),
        expected_freeze_sha256=freeze["models"]["r4_freeze_sha256"],
        expected_admission_sha256=freeze["models"][
            "r4_admission_sha256"])
    if model_identity(models) != freeze["models"]:
        raise ValueError("scientific model package differs from freeze")
    start_path = root / "run-start.json"
    if start_path.exists():
        start = _strict(start_path)
    else:
        started_unix_nanoseconds = time.time_ns()
        start = {
            "started_unix_nanoseconds": started_unix_nanoseconds,
            "deadline_unix_nanoseconds": (
                started_unix_nanoseconds
                + freeze["scientific_wall_cap_nanoseconds"]),
            "resume_count": 0,
        }
        publish_exclusive_bytes(start_path, canonical_json_bytes(start))
    if set(start) != {
            "started_unix_nanoseconds", "deadline_unix_nanoseconds",
            "resume_count"} \
            or type(start["started_unix_nanoseconds"]) is not int \
            or type(start["deadline_unix_nanoseconds"]) is not int \
            or start["deadline_unix_nanoseconds"] \
            != start["started_unix_nanoseconds"] \
            + freeze["scientific_wall_cap_nanoseconds"] \
            or start["resume_count"] != 0:
        raise ValueError("scientific run-start drift")
    if time.time_ns() >= start["deadline_unix_nanoseconds"]:
        raise ValueError("scientific deadline is exhausted")
    try:
        manifest = run_scientific_diagnostic(
            root, models=models, workers=freeze["workers"],
            deadline_unix_ns=start["deadline_unix_nanoseconds"],
            next_unit_reserve_ns=freeze["next_unit_reserve_nanoseconds"],
            scientific_wall_estimate_ns=freeze[
                "scientific_wall_estimate_nanoseconds"],
            execution_freeze_sha256=hashlib.sha256(freeze_raw).hexdigest(),
            admission_sha256=hashlib.sha256(
                canonical_json_bytes(admission)).hexdigest(),
            progress=_progress("scientific"))
    except Exception as exc:
        if time.time_ns() >= start["deadline_unix_nanoseconds"]:
            failure_path = root / "deadline-incomplete.json"
            if not failure_path.exists():
                completed = len(tuple((root / "shards").glob(
                    "rank-*/selected-*.json")))
                publish_exclusive_bytes(failure_path, canonical_json_bytes({
                    "route": "REFUSE_INCOMPLETE_DEADLINE",
                    "completed_shards": completed,
                    "target_shards": 104,
                    "deadline_unix_nanoseconds": (
                        start["deadline_unix_nanoseconds"]),
                    "r4_test_opened": False,
                    "retry_authorized": False,
                    "strength_claim_authorized": False,
                    "deployment_authorized": False,
                }))
        raise
    print(json.dumps({
        "complete": True,
        "route": manifest["terminal"]["route"],
        "round_count": manifest["terminal"]["round_count"],
        "r4_test_opened": False,
        "r5_authorized": False,
    }, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()

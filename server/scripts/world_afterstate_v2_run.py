#!/usr/bin/env python3
"""Small fail-closed command wrapper for the Value-Afterstate V2 supervisor."""

from __future__ import annotations

import os
import sys

# Reject ambient import redirection before importing any non-bootstrap module.
if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("Value V2 scientific execution requires Python -P -B")
if os.environ.get("PYTHONPATH"):
    raise RuntimeError("Value V2 scientific execution refuses PYTHONPATH")


def _require_runtime_environment() -> None:
    if (os.environ.get("SHENGJI_FAST") != "1"
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1"):
        raise RuntimeError(
            "Value V2 requires SHENGJI_FAST=1 and SHENGJI_REQUIRE_VOIDS=1")

from pathlib import Path  # noqa: E402

SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
if not sys.path or sys.path[0] != str(SERVER):
    sys.path.insert(0, str(SERVER))


def _preimport_bytecode_scan() -> None:
    """Refuse ignored bytecode before importing any project module."""
    for prefix in (SERVER / "scripts", SERVER / "shengji"):
        if not prefix.is_dir() or prefix.is_symlink():
            raise RuntimeError("Value V2 scientific execution source root drift")
        for _current, dirs, files in os.walk(
                prefix, topdown=True, followlinks=False):
            if "__pycache__" in dirs or any(name.endswith(".pyc") for name in files):
                raise RuntimeError(
                    "Value V2 scientific execution refuses source bytecode artifacts")


if __name__ in ("__main__", "__mp_main__"):
    _require_runtime_environment()
    _preimport_bytecode_scan()

import argparse  # noqa: E402
import json  # noqa: E402

from shengji.rl import world_afterstate_v2_execution as _execution_module  # noqa: E402
from shengji.rl.world_afterstate_v2_execution import (  # noqa: E402
    ExecutionFreezeV2, StageSupervisorV2, DurableProgressSinkV2,
    WorldAfterstateV2ExecutionError,
    RESOURCE_CLOSEOUT_RELATIVE,
    MissingStageError, authenticate_review_commit, build_admission,
    execution_freeze_from_bytes, initialize_admission, reopen_supervisor,
    seal_resource_incomplete_recovery,
    verify_resource_incomplete_recovery,
    validate_production_stage_set, production_stage_controllers,
    run_v2_pipeline,
)

if not Path(_execution_module.__file__).resolve().is_relative_to(SERVER.resolve()):
    raise RuntimeError("Value V2 scientific execution module origin drift")


def _bootstrap_check() -> None:
    if not SCRIPT.is_file() or SCRIPT.is_symlink():
        raise RuntimeError("Value V2 runner path drift")
    if not (SERVER / "shengji" / "rl" / "world_afterstate_v2_execution.py").is_file():
        raise RuntimeError("Value V2 supervisor missing")
    print("VALUE_AFTERSTATE_V2_BOOTSTRAP_PASS", flush=True)


def _initialize(args: argparse.Namespace) -> None:
    freeze_raw = Path(args.freeze).read_bytes()
    freeze = execution_freeze_from_bytes(freeze_raw)
    admission = initialize_admission(
        Path(args.root), freeze_raw=freeze_raw, repo=REPO,
        review_commit=args.review_commit, canonical_ref=args.canonical_ref,
        remote_url=args.remote_url)
    print(admission.canonical_bytes().decode("ascii"), flush=True)


def _verify(args: argparse.Namespace) -> None:
    freeze = execution_freeze_from_bytes(Path(args.freeze).read_bytes())
    marker = authenticate_review_commit(
        freeze, repo=REPO, review_commit=args.review_commit,
        canonical_ref=args.canonical_ref, remote_url=args.remote_url)
    admission = build_admission(freeze, review_commit=args.review_commit,
                                review_marker=marker)
    root = Path(args.root)
    if (root / RESOURCE_CLOSEOUT_RELATIVE).is_file():
        receipt = verify_resource_incomplete_recovery(
            root, freeze=freeze, admission=admission,
            review_marker=marker, repo=REPO)
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")),
              flush=True)
        return
    supervisor = reopen_supervisor(root, freeze=freeze,
                                   admission=admission, review_marker=marker,
                                   repo=REPO)
    print(supervisor.state.payload(), flush=True)


def _run(args: argparse.Namespace) -> None:
    # Dependency resolution is deliberately before admission consumption: a
    # partial controller namespace cannot spend the one scientific tombstone.
    freeze_raw = Path(args.freeze).read_bytes()
    freeze = execution_freeze_from_bytes(freeze_raw)
    missing = validate_production_stage_set(freeze=freeze, repo=REPO)
    if missing:
        raise MissingStageError("reviewed stage producer unavailable: " + ", ".join(missing))
    admission = initialize_admission(
        Path(args.root), freeze_raw=freeze_raw, repo=REPO,
        review_commit=args.review_commit, canonical_ref=args.canonical_ref,
        remote_url=args.remote_url)
    progress = DurableProgressSinkV2(Path(args.root), freeze=freeze,
                                     admission=admission)
    supervisor = StageSupervisorV2(Path(args.root), freeze, admission,
                                   progress_callback=progress)
    operations = production_stage_controllers(freeze=freeze, repo=REPO)
    run_v2_pipeline(supervisor, operations)


def _resume(args: argparse.Namespace) -> None:
    freeze_raw = Path(args.freeze).read_bytes()
    freeze = execution_freeze_from_bytes(freeze_raw)
    marker = authenticate_review_commit(
        freeze, repo=REPO, review_commit=args.review_commit,
        canonical_ref=args.canonical_ref, remote_url=args.remote_url)
    admission = build_admission(freeze, review_commit=args.review_commit,
                                review_marker=marker)
    progress = DurableProgressSinkV2(Path(args.root), freeze=freeze,
                                     admission=admission)
    supervisor = reopen_supervisor(Path(args.root), freeze=freeze,
                                   admission=admission, review_marker=marker,
                                   repo=REPO, progress_callback=progress)
    missing = validate_production_stage_set(freeze=freeze, repo=REPO)
    if missing:
        raise MissingStageError("reviewed stage producer unavailable: " + ", ".join(missing))
    operations = production_stage_controllers(freeze=freeze, repo=REPO)
    run_v2_pipeline(supervisor, operations)


def _recover_resource_incomplete(args: argparse.Namespace) -> None:
    freeze = execution_freeze_from_bytes(Path(args.freeze).read_bytes())
    marker = authenticate_review_commit(
        freeze, repo=REPO, review_commit=args.review_commit,
        canonical_ref=args.canonical_ref, remote_url=args.remote_url)
    admission = build_admission(
        freeze, review_commit=args.review_commit, review_marker=marker)
    receipt = seal_resource_incomplete_recovery(
        Path(args.root), freeze=freeze, admission=admission,
        review_marker=marker, repo=REPO)
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")),
          flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-check-only", action="store_true")
    sub = parser.add_subparsers(dest="command")
    initialize = sub.add_parser("initialize")
    initialize.add_argument("--root", required=True)
    initialize.add_argument("--freeze", required=True)
    initialize.add_argument("--review-commit", required=True)
    initialize.add_argument("--canonical-ref", default="origin/main")
    initialize.add_argument("--remote-url", default="https://github.com/jerryyyu/shengji.git")
    verify = sub.add_parser("verify")
    verify.add_argument("--root", required=True)
    verify.add_argument("--freeze", required=True)
    verify.add_argument("--review-commit", required=True)
    verify.add_argument("--canonical-ref", default="origin/main")
    verify.add_argument("--remote-url", default="https://github.com/jerryyyu/shengji.git")
    run = sub.add_parser("run")
    resume = sub.add_parser("resume")
    recover = sub.add_parser("recover-resource-incomplete")
    for command in (run, resume, recover):
        command.add_argument("--root", required=True)
        command.add_argument("--freeze", required=True)
        command.add_argument("--review-commit", required=True)
        command.add_argument("--canonical-ref", default="origin/main")
        command.add_argument("--remote-url", default="https://github.com/jerryyyu/shengji.git")
    args = parser.parse_args(argv)
    if args.bootstrap_check_only:
        _bootstrap_check()
        return 0
    if args.command != "initialize":
        if args.command == "verify":
            try:
                _verify(args)
            except (OSError, ValueError, WorldAfterstateV2ExecutionError) as exc:
                parser.exit(1, f"world-afterstate-v2 refused: {exc}\n")
            return 0
        if args.command == "run":
            try:
                _run(args)
            except (OSError, ValueError, WorldAfterstateV2ExecutionError) as exc:
                parser.exit(1, f"world-afterstate-v2 refused: {exc}\n")
            return 0
        if args.command == "resume":
            try:
                _resume(args)
            except (OSError, ValueError, WorldAfterstateV2ExecutionError) as exc:
                parser.exit(1, f"world-afterstate-v2 refused: {exc}\n")
            return 0
        if args.command == "recover-resource-incomplete":
            try:
                _recover_resource_incomplete(args)
            except (OSError, ValueError,
                    WorldAfterstateV2ExecutionError) as exc:
                parser.exit(1, f"world-afterstate-v2 refused: {exc}\n")
            return 0
        parser.error("one of --bootstrap-check-only, initialize, or verify is required")
    try:
        _initialize(args)
    except (OSError, ValueError, WorldAfterstateV2ExecutionError) as exc:
        parser.exit(1, f"world-afterstate-v2 refused: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

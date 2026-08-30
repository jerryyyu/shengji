#!/usr/bin/env python3
"""Administrative entry points for the reviewed PT-Luna source lane.

The CLI has no scientific execution authority by default.  ``build-census``
and ``capacity --fake`` are score-free preparation tools.  Collection requires
an immutable candidate freeze and an exact externally reviewed commit fetched
from the pinned canonical ``main`` remote.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

from shengji.rl import privileged_teacher_luna_selfplay as luna
from shengji.rl import privileged_teacher_luna_selfplay_controller as controller
from shengji.rl import privileged_teacher_luna_selfplay_execution as execution
from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes


def _design(path: Path) -> luna.LunaDesign:
    payload = json.loads(path.read_text())
    expected = set(luna.LunaDesign().payload())
    if type(payload) is not dict or set(payload) != expected:
        raise controller.ControllerError("design file schema drift")
    design = luna.LunaDesign(
        seed_commitment_sha256=payload["seed_commitment_sha256"],
        execution_git=payload["execution_git"],
        native_sha256=payload["native_sha256"], hostname=payload["hostname"],
        namespace=payload["namespace"])
    luna.validate_design(payload, design)
    return design


def _secret(path: Path) -> bytes:
    secret = path.read_bytes()
    if len(secret) != 32:
        raise controller.ControllerError("seed secret must be 32 bytes")
    return secret


def _load(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text())
    if type(payload) is not dict:
        raise controller.ControllerError("record must be an object")
    return payload


def _write_once(path: Path, raw: bytes) -> None:
    """Publish one output without replacement, with direct fsyncs."""
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise controller.ControllerError("output slot occupied")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, "O_NOFOLLOW", 0), 0o400)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    except BaseException:
        raise


def _load_freeze(path: Path) -> dict[str, object]:
    path = Path(path)
    try:
        st = path.lstat()
    except OSError as exc:
        raise controller.ControllerError("launch freeze read refused") from exc
    if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
            or st.st_uid != os.getuid()
            or stat.S_IMODE(st.st_mode) & 0o222):
        raise controller.ControllerError("launch freeze is not immutable")
    return _load(path)


def _fake_metric(workers: int, worker: int, game: int) -> dict[str, object]:
    # This is deliberately an opt-in capacity seam, not a production estimate.
    mechanics = hashlib.sha256(b"pt-luna-fake-mechanics").hexdigest()
    return {"complete": True, "verified": True,
            "wall_nanoseconds": 1_000_000_000,
            "busy_cpu_nanoseconds": 1_000_000_000,
            "peak_rss_bytes": 1_000_000, "swap_bytes": 0,
            "process_errors": 0, "tool_calls": 1,
            "token_count": 1, "token_rate_milli": 1,
            "mechanics_sha256": mechanics}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    census = commands.add_parser("build-census")
    census.add_argument("--design", type=Path, required=True)
    census.add_argument("--secret-file", type=Path, required=True)
    census.add_argument("--output", type=Path, required=True)
    capacity = commands.add_parser("capacity")
    capacity.add_argument("--fake", action="store_true",
                          help="use a score-free fake seam; never launches a model")
    capacity.add_argument("--secret-file", type=Path,
                          help="distinct 32-byte capacity namespace secret")
    capacity.add_argument("--tool-script", type=Path,
                          help="reviewed PT-Luna mailbox tool")
    capacity.add_argument("--output", type=Path, required=True)
    capacity.add_argument("--deadline-seconds", type=int, default=1200)
    capacity.add_argument("--physical-memory-bytes", type=int, required=True)
    capacity.add_argument("--wall-budget-seconds", type=int, default=3600)
    capacity.add_argument("--token-budget", type=int, default=1_000_000_000)
    collect = commands.add_parser("collect")
    collect.add_argument("--design", type=Path, required=True)
    collect.add_argument("--secret-file", type=Path, required=True)
    collect.add_argument("--census", type=Path, required=True)
    collect.add_argument("--capacity", type=Path, required=True)
    collect.add_argument("--output-root", type=Path, required=True)
    collect.add_argument("--tool-script", type=Path, required=True)
    collect.add_argument("--launch-freeze", "--candidate-freeze", dest="launch_freeze",
                         type=Path, required=True,
                         help="immutable candidate freeze (review-authenticated at launch)")
    collect.add_argument("--review-commit", required=True,
                         help="exact external review commit on canonical main")
    collect.add_argument("--repo-root", type=Path, required=True,
                         help="source repository root for the reviewed execution")
    args = parser.parse_args(argv)
    try:
        if args.command == "build-census":
            design = _design(args.design)
            secret = _secret(args.secret_file)
            if hashlib.sha256(secret).hexdigest() != design.seed_commitment_sha256:
                raise controller.ControllerError("seed commitment drift")
            result = luna.root_census(secret, design).serialized()
            _write_once(args.output, canonical_json_bytes(result))
            return 0
        if args.command == "capacity":
            if args.fake:
                receipt = controller.run_capacity(
                    deadline_nanoseconds=args.deadline_seconds * 1_000_000_000,
                    physical_memory_bytes=args.physical_memory_bytes,
                    cumulative_wall_budget_nanoseconds=(
                        args.wall_budget_seconds * 1_000_000_000),
                    cumulative_token_budget=args.token_budget,
                    game_runner=_fake_metric)
            else:
                if args.secret_file is None or args.tool_script is None:
                    raise controller.ControllerError(
                        "real capacity requires secret and tool")
                receipt = controller.run_real_capacity(
                    capacity_secret=_secret(args.secret_file),
                    tool_script=args.tool_script,
                    deadline_nanoseconds=args.deadline_seconds * 1_000_000_000,
                    physical_memory_bytes=args.physical_memory_bytes,
                    cumulative_wall_budget_nanoseconds=(
                        args.wall_budget_seconds * 1_000_000_000),
                    cumulative_token_budget=args.token_budget)
            _write_once(args.output, canonical_json_bytes(receipt.serialized()))
            return 0
        design = _design(args.design)
        secret = _secret(args.secret_file)
        census = luna.RootCensus.reopen(_load(args.census), design=design)
        capacity_receipt = controller.CapacityReceipt.reopen(_load(args.capacity))
        freeze = _load_freeze(args.launch_freeze)
        controller.authenticate_source_review(
            freeze=freeze, design=design, census=census,
            capacity=capacity_receipt, output_root=args.output_root,
            tool_script=args.tool_script, review_commit=args.review_commit,
            repo_root=args.repo_root)
        planner = execution.LunaPlannerConfig()
        runner = controller.production_game_runner(
            private_root=args.output_root / "attempts",
            tool_script=args.tool_script, config=planner)
        report = controller.run_source_population(
            design=design, seed_secret=secret, census=census,
            capacity=capacity_receipt, evidence_root=args.output_root,
            game_runner=runner,
            worker_count=int(capacity_receipt.body["selected_workers"]),
            candidate_freeze=freeze, review_commit=args.review_commit,
            repo_root=args.repo_root, tool_script=args.tool_script)
        print(json.dumps({"report_sha256": report["report_sha256"],
                          "route": report["terminal_route"]}, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

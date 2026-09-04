#!/usr/bin/env python3
"""Run bounded, score-free real-state PT-Luna turn-RPC canaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time

from shengji.rl import privileged_teacher_luna_selfplay as selfplay
from shengji.rl.privileged_teacher_luna_rpc_journal import FileTurnJournal
from shengji.rl.privileged_teacher_luna_rpc_io import publish_exclusive_bytes
from shengji.rl.privileged_teacher_luna_rpc_capacity import source_identity
from shengji.rl.privileged_teacher_luna_rpc_supervisor import (
    SOURCE_REVIEW_PREFIX, authenticate_review_claim, source_review_claim,
)
from shengji.rl.privileged_teacher_luna_rpc_transport import (
    CodexExecPlannerTransport,
)
from shengji.rl.privileged_teacher_luna_turn_rpc import TurnDriver
from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes


SCHEMA = "pt-luna-turn-rpc-real-canaries-v1"


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _publish(path: Path, payload: object) -> None:
    publish_exclusive_bytes(path, canonical_json_bytes(payload))


def _summary(name, game, evidence, wall_ns):
    plays = [row for row in evidence if row.intent.get("kind") == "play"]
    rollouts = [row for row in evidence if row.intent.get("kind") == "rollout"]
    return {"schema": "pt-luna-turn-rpc-real-canary-row-v1",
            "name": name, "completed_contested_decisions": len(plays),
            "planner_rpc_count": len(evidence),
            "rollout_rpc_count": len(rollouts),
            "play_rpc_count": len(plays),
            "play_teams": [row.team for row in plays],
            "provider_request_sha256s": [
                row.provider_request_sha256 for row in evidence],
            "provider_response_sha256s": [
                row.provider_response_sha256 for row in evidence],
            "tool_event_count": sum(
                row.tool_event_count for row in evidence),
            "input_tokens": sum(row.usage.input_tokens for row in evidence),
            "cached_input_tokens": sum(
                row.usage.cached_input_tokens for row in evidence),
            "cache_write_input_tokens": sum(
                row.usage.cache_write_input_tokens for row in evidence),
            "output_tokens": sum(row.usage.output_tokens for row in evidence),
            "reasoning_output_tokens": sum(
                row.usage.reasoning_output_tokens for row in evidence),
            "total_tokens": sum(row.usage.total_tokens for row in evidence),
            "rpc_wall_milliseconds": sum(
                row.usage.wall_ms for row in evidence),
            "wall_nanoseconds": wall_ns,
            "engine_complete": game.complete,
            "engine_failed": game.failed is not None}


def _run_one(*, name: str, secret: bytes, coordinate, mirror: int,
             decisions: int, policy_mode: str, codex_binary: Path,
             work_root: Path):
    game = selfplay.LunaSelfPlayGame(
        selfplay.build_root(secret, coordinate), coordinate=coordinate,
        mirror=mirror, seed_secret=secret)
    before = _sha(selfplay._state_snapshot(game.rnd))
    started = time.monotonic_ns()
    with tempfile.TemporaryDirectory(prefix=f"{name}-", dir=work_root) as directory:
        journal = FileTurnJournal(Path(directory) / "journal")
        transport = CodexExecPlannerTransport(
            codex_binary=codex_binary, temp_root=Path(directory),
            policy_mode=policy_mode)
        evidence = TurnDriver(game, transport, journal=journal).run(
            max_decisions=decisions)
        journal_summary = journal.summary()
    wall = max(1, time.monotonic_ns() - started)
    row = _summary(name, game, evidence, wall)
    plays = [event for event in evidence if event.intent.get("kind") == "play"]
    if name == "nonterminal":
        if (len(evidence) != 2 or [event.phase for event in evidence] != [1, 2]
                or evidence[0].intent.get("kind") != "rollout"
                or evidence[1].intent.get("kind") != "play"
                or len(plays) != 1 or game.complete or game.failed is not None):
            raise ValueError("nonterminal canary contract failed")
    elif (len(plays) < 4
          or sorted({event.team for event in plays[:4]}) != [0, 1]
          or game.failed is not None):
        raise ValueError("alternation canary contract failed")
    if game.acting_team not in (0, 1):
        raise ValueError("canary reached unexpected terminal state")
    after = _sha(selfplay._state_snapshot(game.rnd))
    row["state_changed"] = before != after
    row["journal_summary_sha256"] = _sha(journal_summary)
    return row


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--source-review-commit", required=True)
    parser.add_argument("--codex-binary", type=Path, default=Path("codex"))
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        raise ValueError("canary output slot occupied")
    review = authenticate_review_claim(
        claim=source_review_claim(args.repo_root),
        prefix=SOURCE_REVIEW_PREFIX,
        review_commit=args.source_review_commit)
    if args.work_root.exists() and any(args.work_root.iterdir()):
        raise ValueError("canary work namespace occupied")
    args.work_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    runtime = source_identity(args.codex_binary)
    secret = hashlib.sha256(b"pt-luna-turn-rpc-real-canaries-v1").digest()
    rows = [
        _run_one(name="nonterminal", secret=secret,
                 coordinate=("2", 0, 0), mirror=0, decisions=1,
                 policy_mode="canary-rollout-then-play",
                 codex_binary=args.codex_binary, work_root=args.work_root),
        _run_one(name="alternation", secret=secret,
                 coordinate=("3", 1, 0), mirror=1, decisions=4,
                 policy_mode="free", codex_binary=args.codex_binary,
                 work_root=args.work_root),
    ]
    if source_identity(args.codex_binary) != runtime:
        raise ValueError("canary terminal runtime drift")
    body = {"schema": SCHEMA, "scientific": False,
            "seed_commitment_sha256": hashlib.sha256(secret).hexdigest(),
            "rows": rows, "runtime": runtime, "source_review": review,
            "authority": dict(selfplay.AUTHORITY)}
    result = {**body, "receipt_sha256": _sha(body)}
    _publish(args.output, result)
    print(canonical_json_bytes(result).decode(), end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"schema": "pt-luna-turn-rpc-canary-failure-v1",
                          "failure_kind": type(exc).__name__,
                          "scientific": False}), file=sys.stderr)
        raise

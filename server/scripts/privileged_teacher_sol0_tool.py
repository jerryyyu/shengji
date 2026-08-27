#!/usr/bin/env python3
"""Narrow command-line bridge from an ephemeral Sol session to PT-Sol0."""

from __future__ import annotations

import sys

if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("PT-Sol0 tool requires Python -P -B")

import argparse
import json
from pathlib import Path

from shengji.rl.privileged_teacher_sol0 import tool_request


def _csv_ints(value: str) -> list[int]:
    try:
        result = [int(item) for item in value.split(",") if item]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected comma-separated integers") \
            from exc
    if not result:
        raise argparse.ArgumentTypeError("at least one integer is required")
    return result


def _csv_tokens(value: str) -> list[str]:
    result = [item for item in value.split(",") if item]
    if not result:
        raise argparse.ArgumentTypeError("at least one token is required")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mailbox", type=Path, required=True)
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("observe")

    rollout = commands.add_parser("rollout")
    rollout.add_argument("--decision", required=True)
    rollout.add_argument("--candidates", type=_csv_ints, required=True)
    rollout.add_argument("--continuations", type=_csv_tokens, required=True)

    play = commands.add_parser("play")
    play.add_argument("--decision", required=True)
    play.add_argument("--candidate", type=int, required=True)
    play.add_argument(
        "--confidence", choices=("low", "medium", "high"), required=True)
    args = parser.parse_args()

    if args.operation == "observe":
        request = {"op": "observe"}
    elif args.operation == "rollout":
        request = {
            "op": "rollout",
            "decision_sha256": args.decision,
            "candidate_indices": args.candidates,
            "continuations": args.continuations,
        }
    else:
        request = {
            "op": "play",
            "decision_sha256": args.decision,
            "candidate_index": args.candidate,
            "confidence": args.confidence,
        }
    response = tool_request(args.mailbox, request)
    print(json.dumps(response, sort_keys=True, separators=(",", ":")))
    return 0 if response.get("status") != "error" else 2


if __name__ == "__main__":
    raise SystemExit(main())

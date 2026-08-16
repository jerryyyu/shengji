#!/usr/bin/env python3
"""Run or independently verify the score-free V2 deadline preflight."""

from __future__ import annotations

import sys


if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("V2 deadline preflight requires Python -P -B")

import argparse
import json
import os
from pathlib import Path

from shengji.rl.belief_artifacts import publish_exclusive_bytes
from shengji.rl.belief_v2_accelerator import require_training_device
from shengji.rl.belief_v2_deadline_estimate import (
    deadline_estimate_receipt_bytes,
    run_deadline_estimate_preflight,
    validate_deadline_estimate_receipt,
)
from shengji.rl.belief_v2_execution_identity import (
    build_runtime_profile,
    build_source_bindings,
    configure_numerical_runtime,
)
from shengji.rl.belief_v2_preflight import verify_preflight_result


SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[2]


def _load(path: Path) -> dict:
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("V2 deadline input is not JSON") from exc
    if type(value) is not dict:
        raise ValueError("V2 deadline input is not an object")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--expected-git", required=True)
    run.add_argument("--preflight-result", type=Path, required=True)
    run.add_argument("--training-device", required=True)
    run.add_argument("--out", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("receipt", type=Path)
    args = parser.parse_args()
    if args.command == "verify":
        raw = args.receipt.read_bytes()
        receipt = _load(args.receipt)
        validate_deadline_estimate_receipt(receipt)
        if deadline_estimate_receipt_bytes(receipt) != raw:
            raise ValueError("V2 deadline receipt is not canonical bytes")
        print("verified=true")
        return
    if os.environ.get("PYTHONPATH"):
        raise ValueError("V2 deadline preflight refuses PYTHONPATH")
    output = args.out.resolve()
    if output.exists() or output.is_symlink():
        raise ValueError("V2 deadline output already exists")
    configure_numerical_runtime()
    build_source_bindings(REPO, expected_git=args.expected_git)
    runtime = build_runtime_profile()
    device = require_training_device(args.training_device)
    preflight = _load(args.preflight_result)
    verify_preflight_result(preflight)
    receipt = run_deadline_estimate_preflight(
        execution_git=args.expected_git, runtime=runtime,
        preflight_result=preflight, training_device=device)
    digest = publish_exclusive_bytes(
        output, deadline_estimate_receipt_bytes(receipt))
    print(json.dumps({
        "receipt_path": str(output),
        "receipt_sha256": digest,
        "capture_sample_count": receipt["capture_sample_count"],
        "reference_sample_count": receipt["reference_sample_count"],
        "training_epoch_sample_count": receipt["training_epoch_sample_count"],
        "pipeline_execution_authorized": False,
        "test_split_opened": False,
        "strength_claim_authorized": False,
    }, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()

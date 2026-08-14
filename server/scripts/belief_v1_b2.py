#!/usr/bin/env python3
"""Single reviewed controller for the BELIEF-V1 B2 offline pipeline.

The initial command freezes the exact source/runtime/evidence-root design that
the independent reviewer must approve.  Capture, reference, streaming train,
test-once, and terminal-reopen commands are added to this same controller and
consume that same one review; the run never grows a per-stage packet chain.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from shengji.rl.belief_artifacts import publish_exclusive_bytes  # noqa: E402
from shengji.rl.belief_b2_execution import (  # noqa: E402
    B2ExecutionDesignV1,
    build_runtime_profile,
    build_source_bindings,
    expected_review_claim,
    validate_execution_design,
)
from shengji.rl.belief_contract import canonical_json_bytes  # noqa: E402


def freeze_design(args: argparse.Namespace) -> None:
    evidence_root = Path(args.evidence_root)
    output = Path(args.out)
    if not evidence_root.is_absolute() or not output.is_absolute() \
            or output.parent != evidence_root.parent:
        raise ValueError(
            "design and evidence root require absolute sibling paths")
    design = B2ExecutionDesignV1(
        execution_git=args.expected_git,
        source_bindings=build_source_bindings(
            REPO, expected_git=args.expected_git),
        runtime=build_runtime_profile(),
        evidence_root=str(evidence_root))
    validate_execution_design(design)
    digest = publish_exclusive_bytes(output, design.canonical_bytes())
    if digest != design.sha256():
        raise ValueError("published design digest drift")
    print(canonical_json_bytes({
        "design_path": str(output),
        "design_sha256": digest,
        "review_prefix": expected_review_claim(design),
        "execution_started": False,
    }).decode("ascii"), end="")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    commands = result.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze-design")
    freeze.add_argument("--expected-git", required=True)
    freeze.add_argument("--evidence-root", required=True)
    freeze.add_argument("--out", required=True)
    freeze.set_defaults(function=freeze_design)
    return result


def main() -> None:
    args = parser().parse_args()
    args.function(args)


if __name__ == "__main__":
    main()

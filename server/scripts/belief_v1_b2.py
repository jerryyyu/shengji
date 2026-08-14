#!/usr/bin/env python3
"""Single reviewed controller for the BELIEF-V1 B2 offline pipeline.

The initial command freezes the exact source/runtime/evidence-root design that
the independent reviewer must approve.  Capture, reference, streaming train,
test-once, and terminal-reopen commands are added to this same controller and
consume that same one review; the run never grows a per-stage packet chain.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from shengji.rl.belief_artifacts import (  # noqa: E402
    publish_exclusive_bytes,
    stable_read_bytes,
)
from shengji.rl.belief_b2_execution import (  # noqa: E402
    B2ExecutionDesignV1,
    authenticate_review_commit,
    build_pipeline_admission,
    build_runtime_profile,
    build_source_bindings,
    execution_design_from_bytes,
    expected_review_claim,
    pipeline_admission_from_bytes,
    pipeline_admission_review_commit,
    validate_live_execution,
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


def _fsync_parent(path: Path) -> None:
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def initialize(args: argparse.Namespace) -> None:
    design_path = Path(args.design)
    raw = stable_read_bytes(design_path)
    if hashlib.sha256(raw).hexdigest() != args.expected_design_sha256:
        raise ValueError("design file SHA drift")
    design = execution_design_from_bytes(raw)
    validate_live_execution(design, repo=REPO)
    marker = authenticate_review_commit(
        design, repo=REPO, review_commit=args.review_commit)
    admission = build_pipeline_admission(
        design, review_commit=args.review_commit, review_marker=marker)
    root = Path(design.evidence_root)
    partial = root.with_name(root.name + ".partial")
    if root.exists() or partial.exists() or root.is_symlink() \
            or partial.is_symlink():
        raise ValueError("pipeline evidence namespace is already occupied")
    partial.mkdir(mode=0o700, parents=False)
    try:
        publish_exclusive_bytes(partial / "design.json", raw)
        publish_exclusive_bytes(partial / "review.md", marker)
        publish_exclusive_bytes(
            partial / "admission.json", admission.canonical_bytes())
        os.rename(partial, root)
        _fsync_parent(root)
    except BaseException:
        # A partially initialized one-shot namespace is preserved for review.
        raise
    _load_authorized_root(root)
    print(canonical_json_bytes({
        "run_id": "belief-v1-b2-open-dev-offline-v1",
        "evidence_root": str(root),
        "design_sha256": design.sha256(),
        "admission_sha256": admission.sha256(),
        "review_commit": admission.review_commit,
        "execution_initialized": True,
        "gameplay_started": False,
    }).decode("ascii"), end="")


def _load_authorized_root(root: Path):
    if not isinstance(root, Path) or not root.is_absolute() \
            or root.is_symlink() or not root.is_dir():
        raise ValueError("pipeline evidence root shape drift")
    design_raw = stable_read_bytes(root / "design.json")
    review_raw = stable_read_bytes(root / "review.md")
    admission_raw = stable_read_bytes(root / "admission.json")
    design = execution_design_from_bytes(design_raw)
    if Path(design.evidence_root) != root:
        raise ValueError("pipeline evidence root binding drift")
    validate_live_execution(design, repo=REPO)
    review_commit = pipeline_admission_review_commit(admission_raw)
    marker = authenticate_review_commit(
        design, repo=REPO, review_commit=review_commit)
    if marker != review_raw:
        raise ValueError("pipeline review snapshot drift")
    admission = pipeline_admission_from_bytes(
        admission_raw, design=design, review_marker=marker)
    return design, admission


def verify_root(args: argparse.Namespace) -> None:
    design, admission = _load_authorized_root(Path(args.root))
    print(canonical_json_bytes({
        "verified": True,
        "design_sha256": design.sha256(),
        "admission_sha256": admission.sha256(),
        "execution_git": design.execution_git,
        "evidence_root": design.evidence_root,
        "offline_pipeline_authorized": True,
        "gameplay_strength_screen_authorized": False,
        "deployment_authorized": False,
    }).decode("ascii"), end="")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    commands = result.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze-design")
    freeze.add_argument("--expected-git", required=True)
    freeze.add_argument("--evidence-root", required=True)
    freeze.add_argument("--out", required=True)
    freeze.set_defaults(function=freeze_design)
    init = commands.add_parser("initialize")
    init.add_argument("--design", required=True)
    init.add_argument("--expected-design-sha256", required=True)
    init.add_argument("--review-commit", required=True)
    init.set_defaults(function=initialize)
    verify = commands.add_parser("verify-root")
    verify.add_argument("--root", required=True)
    verify.set_defaults(function=verify_root)
    return result


def main() -> None:
    args = parser().parse_args()
    args.function(args)


if __name__ == "__main__":
    main()

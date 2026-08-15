#!/usr/bin/env python3
"""Single reviewed controller for the BELIEF-V1 B2 offline pipeline.

The initial command freezes the exact source/runtime/evidence-root design that
the independent reviewer must approve.  Capture, reference, streaming train,
test-once, and terminal-reopen commands are added to this same controller and
consume that same one review; the run never grows a per-stage packet chain.
"""

from __future__ import annotations

import sys


if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError(
        "Belief V1 B2 requires Python -P -B safe interpreter flags")

import argparse
import hashlib
import os
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent


def _refuse_import_shadows() -> None:
    """Reject executable bytes outside the exact tracked/native surface."""
    if os.environ.get("PYTHONPATH"):
        raise RuntimeError("Belief V1 B2 refuses PYTHONPATH")
    try:
        tracked_raw = subprocess.run(
            ("git", "ls-files", "-z"), cwd=REPO, check=True,
            capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("Belief V1 B2 bootstrap Git probe failed") from exc
    tracked = {value.decode("utf-8") for value in tracked_raw.split(b"\0")
               if value}
    loadable_suffixes = {".py", ".pyc", ".pyo", ".so", ".pyd", ".dylib"}
    candidates = set()
    candidates.update(path for path in SERVER.iterdir()
                      if path.is_file()
                      and path.suffix in loadable_suffixes)
    candidates.update(path for path in SERVER.glob("*/__init__.py"))
    for root in (SERVER / "shengji", SERVER / "scripts"):
        candidates.update(path for path in root.rglob("*")
                          if path.is_file()
                          and path.suffix in loadable_suffixes)
    native = []
    for path in sorted(candidates):
        relative = path.relative_to(REPO).as_posix()
        if path.suffix in {".pyc", ".pyo"}:
            raise RuntimeError("Belief V1 B2 refuses bytecode shadows")
        if path.suffix in {".so", ".pyd", ".dylib"} \
                and path.parent == SERVER / "shengji" / "engine" \
                and path.name.startswith("_fast."):
            native.append(path)
            continue
        if relative not in tracked:
            raise RuntimeError("Belief V1 B2 refuses untracked import shadows")
    if len(native) > 1:
        raise RuntimeError("Belief V1 B2 native extension population drift")


_refuse_import_shadows()
if sys.argv[1:] == ["--bootstrap-check-only"]:
    print("BELIEF_V1_B2_BOOTSTRAP_PASS")
    raise SystemExit(0)

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
    configure_numerical_runtime,
    execution_design_from_bytes,
    expected_review_claim,
    pipeline_admission_from_bytes,
    pipeline_admission_review_commit,
    pipeline_consumption_tombstone_bytes,
    validate_pipeline_consumption_tombstone,
    validate_live_execution,
    validate_execution_design,
    verify_canonical_remote_main,
)
from shengji.rl.belief_contract import canonical_json_bytes  # noqa: E402
from shengji.rl.belief_b2_controller import (  # noqa: E402
    run_capture_lane,
    run_reference_lane,
    run_training_cohort,
)
from shengji.rl.belief_b2_terminal_controller import (  # noqa: E402
    run_open_test,
    verify_terminal,
)


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
    verify_canonical_remote_main(REPO)
    marker = authenticate_review_commit(
        design, repo=REPO, review_commit=args.review_commit)
    admission = build_pipeline_admission(
        design, review_commit=args.review_commit, review_marker=marker)
    root = Path(design.evidence_root)
    partial = root.with_name(root.name + ".partial")
    tombstone = root.with_name(root.name + ".consumed.json")
    if root.exists() or partial.exists() or root.is_symlink() \
            or partial.is_symlink() or tombstone.exists() \
            or tombstone.is_symlink():
        raise ValueError("pipeline evidence namespace is already occupied")
    publish_exclusive_bytes(
        tombstone, pipeline_consumption_tombstone_bytes(admission))
    _fsync_parent(tombstone)
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
    tombstone = root.with_name(root.name + ".consumed.json")
    validate_pipeline_consumption_tombstone(
        stable_read_bytes(tombstone), admission=admission)
    return design, admission, marker


def verify_root(args: argparse.Namespace) -> None:
    design, admission, _ = _load_authorized_root(Path(args.root))
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


def capture_lane(args: argparse.Namespace) -> None:
    root = Path(args.root)
    design, admission, marker = _load_authorized_root(root)
    result = run_capture_lane(
        root, design, admission, lane=args.lane, review_marker=marker)
    print(canonical_json_bytes({
        "capture_lane": args.lane,
        "round_count": result["round_count"],
        "manifest_sha256": hashlib.sha256(
            canonical_json_bytes(result)).hexdigest(),
        "retry_count": 0,
        "complete": True,
    }).decode("ascii"), end="")


def reference_lane(args: argparse.Namespace) -> None:
    root = Path(args.root)
    design, admission, marker = _load_authorized_root(root)
    result = run_reference_lane(
        root, design, admission, lane=args.lane, review_marker=marker)
    print(canonical_json_bytes({
        "reference_lane": args.lane,
        "job_count": result["job_count"],
        "manifest_sha256": hashlib.sha256(
            canonical_json_bytes(result)).hexdigest(),
        "retry_count": 0,
        "complete": True,
    }).decode("ascii"), end="")


def train_cohort(args: argparse.Namespace) -> None:
    root = Path(args.root)
    design, admission, marker = _load_authorized_root(root)
    result = run_training_cohort(
        root, design, admission, kind=args.kind, review_marker=marker)
    print(canonical_json_bytes({
        "cohort_kind": args.kind,
        "epoch_count": result["epoch_count"],
        "selected_common_epoch": result["selected_common_epoch"],
        "manifest_sha256": hashlib.sha256(
            canonical_json_bytes(result)).hexdigest(),
        "test_split_opened": False,
        "retry_count": 0,
        "complete": True,
    }).decode("ascii"), end="")


def open_test(args: argparse.Namespace) -> None:
    root = Path(args.root)
    design, admission, marker = _load_authorized_root(root)
    result = run_open_test(
        root, design, admission, review_marker=marker)
    print(canonical_json_bytes({
        "terminal_decision": result["terminal"]["decision"],
        "terminal_result_sha256": hashlib.sha256(
            canonical_json_bytes(result)).hexdigest(),
        "test_split_open_count": 1,
        "terminal_reproducibility_review_required": True,
        "complete": True,
    }).decode("ascii"), end="")


def terminal_verify(args: argparse.Namespace) -> None:
    root = Path(args.root)
    design, admission, _ = _load_authorized_root(root)
    result = verify_terminal(root, design, admission)
    print(canonical_json_bytes({
        "verified": True,
        "terminal_decision": result["terminal"]["decision"],
        "terminal_result_sha256": hashlib.sha256(
            canonical_json_bytes(result)).hexdigest(),
        "b3_sampler_implementation_authorized": False,
        "sampler_run_authorized": False,
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
    capture = commands.add_parser("capture-lane")
    capture.add_argument("--root", required=True)
    capture.add_argument("--lane", required=True, type=int)
    capture.set_defaults(function=capture_lane)
    reference = commands.add_parser("reference-lane")
    reference.add_argument("--root", required=True)
    reference.add_argument("--lane", required=True, type=int)
    reference.set_defaults(function=reference_lane)
    train = commands.add_parser("train-cohort")
    train.add_argument("--root", required=True)
    train.add_argument(
        "--kind", required=True,
        choices=("candidate", "hard-geometry-label-permutation"))
    train.set_defaults(function=train_cohort)
    test = commands.add_parser("open-test")
    test.add_argument("--root", required=True)
    test.set_defaults(function=open_test)
    terminal = commands.add_parser("verify-terminal")
    terminal.add_argument("--root", required=True)
    terminal.set_defaults(function=terminal_verify)
    return result


def main() -> None:
    configure_numerical_runtime()
    args = parser().parse_args()
    args.function(args)


if __name__ == "__main__":
    main()

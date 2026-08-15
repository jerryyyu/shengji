#!/usr/bin/env python3
"""Single reviewed worker for the BELIEF-V1 V2 offline pipeline."""

from __future__ import annotations

import sys


if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("BELIEF-V1 V2 requires Python -P -B safe flags")

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent


def _refuse_import_shadows() -> None:
    if os.environ.get("PYTHONPATH"):
        raise RuntimeError("BELIEF-V1 V2 refuses PYTHONPATH")
    try:
        tracked_raw = subprocess.run(
            ("git", "ls-files", "-z"), cwd=REPO, check=True,
            capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("BELIEF-V1 V2 bootstrap Git probe failed") from exc
    tracked = {value.decode("utf-8") for value in tracked_raw.split(b"\0")
               if value}
    suffixes = {".py", ".pyc", ".pyo", ".so", ".pyd", ".dylib"}
    candidates = set()
    for root in (SERVER / "shengji", SERVER / "scripts"):
        candidates.update(path for path in root.rglob("*")
                          if path.is_file() and path.suffix in suffixes)
    native = []
    for path in sorted(candidates):
        relative = path.relative_to(REPO).as_posix()
        if path.suffix in {".pyc", ".pyo"}:
            raise RuntimeError("BELIEF-V1 V2 refuses bytecode shadows")
        if path.suffix in {".so", ".pyd", ".dylib"} \
                and path.parent == SERVER / "shengji" / "engine" \
                and path.name.startswith("_fast."):
            native.append(path)
            continue
        if relative not in tracked:
            raise RuntimeError("BELIEF-V1 V2 refuses untracked import shadows")
    if len(native) > 1:
        raise RuntimeError("BELIEF-V1 V2 native extension population drift")


_refuse_import_shadows()
if sys.argv[1:] == ["--bootstrap-check-only"]:
    print("BELIEF_V1_V2_BOOTSTRAP_PASS")
    raise SystemExit(0)

if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from shengji.rl.belief_artifacts import (  # noqa: E402
    publish_exclusive_bytes,
    stable_read_bytes,
)
from shengji.rl.belief_contract import canonical_json_bytes  # noqa: E402
from shengji.rl.belief_v2_calibration_controller import (  # noqa: E402
    run_v2_calibration_selection,
)
from shengji.rl.belief_v2_controller import (  # noqa: E402
    run_capture_lane,
    run_reference_lane,
)
from shengji.rl.belief_v2_device_controller import (  # noqa: E402
    reopen_device_qualification,
    run_device_qualification,
)
from shengji.rl.belief_v2_execution_identity import (  # noqa: E402
    configure_numerical_runtime,
    validate_live_execution,
)
from shengji.rl.belief_v2_freeze import (  # noqa: E402
    build_pipeline_admission,
    execution_freeze_from_bytes,
    pipeline_admission_from_bytes,
    pipeline_consumption_tombstone_bytes,
    reauthenticate_pipeline_admission,
    validate_pipeline_consumption_tombstone,
)
from shengji.rl.belief_v2_human_controller import (  # noqa: E402
    run_human_group_capture,
)
from shengji.rl.belief_v2_human_inventory import (  # noqa: E402
    group_split_bytes,
    inventory_bytes,
)
from shengji.rl.belief_v2_human_reference_controller import (  # noqa: E402
    run_human_reference_group,
)
from shengji.rl.belief_v2_terminal_controller import (  # noqa: E402
    reopen_v2_terminal,
    run_v2_terminal,
)
from shengji.rl.belief_v2_training_controller import (  # noqa: E402
    run_training_cohort,
)
from shengji.rl.belief_v2_training_inputs import (  # noqa: E402
    reopen_v2_training_inputs,
    training_examples_for_realization,
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _fsync_parent(path: Path) -> None:
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _strict_json(raw: bytes, *, label: str) -> dict:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"V2 {label} is not JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise ValueError(f"V2 {label} is not canonical")
    return value


def _private_inputs(inventory_raw: bytes, split_raw: bytes, freeze):
    inventory = _strict_json(inventory_raw, label="H0 inventory")
    group_split = _strict_json(split_raw, label="H0 group split")
    if inventory_bytes(inventory) != inventory_raw \
            or group_split_bytes(group_split, inventory=inventory) \
            != split_raw \
            or _sha256(inventory_raw) != freeze.h0_inventory_sha256 \
            or inventory["source_manifest_sha256"] \
            != freeze.h0_source_manifest_sha256 \
            or inventory["source_digest_population_sha256"] \
            != freeze.h0_source_digest_population_sha256 \
            or _sha256(split_raw) != freeze.human_group_split_sha256:
        raise ValueError("V2 H0 inventory/group-split freeze binding drift")
    return inventory, group_split


def initialize(args: argparse.Namespace) -> None:
    freeze_path = Path(args.freeze)
    freeze_raw = stable_read_bytes(freeze_path)
    if _sha256(freeze_raw) != args.expected_freeze_sha256:
        raise ValueError("V2 freeze file SHA drift")
    freeze = execution_freeze_from_bytes(freeze_raw)
    root = Path(freeze.evidence_root)
    if not root.is_absolute() or freeze_path.parent != root.parent:
        raise ValueError("V2 freeze and evidence root must be absolute siblings")
    validate_live_execution(
        repo=REPO, execution_git=freeze.execution_git,
        source_bindings=freeze.source_bindings, runtime=freeze.runtime)
    inventory_raw = stable_read_bytes(Path(args.inventory))
    split_raw = stable_read_bytes(Path(args.group_split))
    _private_inputs(inventory_raw, split_raw, freeze)
    admission, marker = build_pipeline_admission(
        freeze, repo=REPO, review_commit=args.review_commit)
    partial = root.with_name(root.name + ".partial")
    tombstone = root.with_name(root.name + ".consumed.json")
    if root.exists() or partial.exists() or root.is_symlink() \
            or partial.is_symlink() or tombstone.exists() \
            or tombstone.is_symlink():
        raise ValueError("V2 evidence namespace is already occupied")
    publish_exclusive_bytes(
        tombstone, pipeline_consumption_tombstone_bytes(admission))
    _fsync_parent(tombstone)
    partial.mkdir(mode=0o700)
    publish_exclusive_bytes(partial / "freeze.json", freeze_raw)
    publish_exclusive_bytes(partial / "review.md", marker)
    publish_exclusive_bytes(
        partial / "admission.json", admission.canonical_bytes())
    publish_exclusive_bytes(partial / "inventory.json", inventory_raw)
    publish_exclusive_bytes(partial / "group-split.json", split_raw)
    os.rename(partial, root)
    _fsync_parent(root)
    _load_root(root)
    print(canonical_json_bytes({
        "run_id": "belief-v1-v2-all-ranks-human-offline-v1",
        "evidence_root": str(root), "freeze_sha256": freeze.sha256(),
        "admission_sha256": admission.sha256(),
        "review_commit": admission.review_commit,
        "execution_initialized": True,
        "gameplay_started": False,
        "strength_claim_authorized": False,
    }).decode("ascii"), end="")


def _load_root(root: Path):
    if not isinstance(root, Path) or not root.is_absolute() \
            or root.is_symlink() or not root.is_dir():
        raise ValueError("V2 evidence root shape drift")
    freeze_raw = stable_read_bytes(root / "freeze.json")
    review_marker = stable_read_bytes(root / "review.md")
    admission_raw = stable_read_bytes(root / "admission.json")
    inventory_raw = stable_read_bytes(root / "inventory.json")
    split_raw = stable_read_bytes(root / "group-split.json")
    freeze = execution_freeze_from_bytes(freeze_raw)
    if Path(freeze.evidence_root) != root:
        raise ValueError("V2 evidence root binding drift")
    admission = pipeline_admission_from_bytes(
        admission_raw, freeze=freeze, review_marker=review_marker)
    validate_pipeline_consumption_tombstone(
        stable_read_bytes(root.with_name(root.name + ".consumed.json")),
        admission=admission)
    inventory, group_split = _private_inputs(
        inventory_raw, split_raw, freeze)
    reauthenticate_pipeline_admission(
        freeze, admission, repo=REPO, review_marker=review_marker)
    validate_live_execution(
        repo=REPO, execution_git=freeze.execution_git,
        source_bindings=freeze.source_bindings, runtime=freeze.runtime)
    return freeze, admission, review_marker, inventory, group_split


def _output(payload: dict) -> None:
    print(canonical_json_bytes(payload).decode("ascii"), end="")


def verify_root(args: argparse.Namespace) -> None:
    freeze, admission, _, inventory, group_split = _load_root(
        Path(args.root))
    _output({
        "verified": True, "freeze_sha256": freeze.sha256(),
        "admission_sha256": admission.sha256(),
        "inventory_sha256": _sha256(inventory_bytes(inventory)),
        "group_split_sha256": _sha256(group_split_bytes(
            group_split, inventory=inventory)),
        "bounded_offline_pipeline_authorized": True,
        "retry_authorized": False,
        "sampler_implementation_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    })


def capture_lane(args: argparse.Namespace) -> None:
    root = Path(args.root)
    freeze, admission, marker, _, _ = _load_root(root)
    _output(run_capture_lane(
        root, freeze, admission, repo=REPO, lane=args.lane,
        review_marker=marker))


def reference_lane(args: argparse.Namespace) -> None:
    root = Path(args.root)
    freeze, admission, marker, _, _ = _load_root(root)
    _output(run_reference_lane(
        root, freeze, admission, repo=REPO, lane=args.lane,
        review_marker=marker))


def human_capture(args: argparse.Namespace) -> None:
    root = Path(args.root)
    freeze, admission, marker, inventory, group_split = _load_root(root)
    _output(run_human_group_capture(
        root, freeze, admission, repo=REPO,
        source_path=Path(args.source_path), inventory=inventory,
        group_split=group_split, review_marker=marker))


def human_reference(args: argparse.Namespace) -> None:
    root = Path(args.root)
    freeze, admission, marker, inventory, group_split = _load_root(root)
    _output(run_human_reference_group(
        root, freeze, admission, repo=REPO,
        source_path=Path(args.source_path), inventory=inventory,
        group_split=group_split, replicate=args.replicate,
        review_marker=marker))


def _training_inputs(root: Path, freeze, admission, inventory, group_split):
    return reopen_v2_training_inputs(
        root, freeze=freeze, admission=admission,
        inventory=inventory, group_split=group_split)


def qualify_device(args: argparse.Namespace) -> None:
    root = Path(args.root)
    freeze, admission, marker, inventory, group_split = _load_root(root)
    inputs = _training_inputs(
        root, freeze, admission, inventory, group_split)
    primary = next(row for row in inputs.realizations
                   if row.cohort_id == "synthetic-primary")
    _output(run_device_qualification(
        root, freeze, admission, repo=REPO, review_marker=marker,
        primary=primary,
        primary_examples=training_examples_for_realization(inputs, primary)))


def train_cohort(args: argparse.Namespace) -> None:
    root = Path(args.root)
    freeze, admission, marker, inventory, group_split = _load_root(root)
    inputs = _training_inputs(
        root, freeze, admission, inventory, group_split)
    primary = next(row for row in inputs.realizations
                   if row.cohort_id == "synthetic-primary")
    candidates = [row for row in inputs.realizations
                  if row.cohort_id == args.cohort_id]
    if len(candidates) != 1:
        raise ValueError("V2 requested cohort is absent or duplicated")
    realization = candidates[0]
    _, plan, result = reopen_device_qualification(
        root / "device-qualification" / "result", freeze=freeze,
        admission=admission, primary=primary)
    _output(run_training_cohort(
        root, freeze, admission, repo=REPO, review_marker=marker,
        primary=primary, realization=realization,
        training_examples=training_examples_for_realization(
            inputs, realization), calibration=inputs.common_calibration,
        calibration_examples=inputs.synthetic_calibration_examples,
        qualification_plan=plan, qualification_result=result))


def calibrate(args: argparse.Namespace) -> None:
    root = Path(args.root)
    freeze, admission, marker, inventory, group_split = _load_root(root)
    _output(run_v2_calibration_selection(
        root, freeze, admission, repo=REPO, review_marker=marker,
        inventory=inventory, group_split=group_split))


def open_test(args: argparse.Namespace) -> None:
    root = Path(args.root)
    freeze, admission, marker, inventory, group_split = _load_root(root)
    _output(run_v2_terminal(
        root, freeze, admission, repo=REPO, review_marker=marker,
        inventory=inventory, group_split=group_split))


def verify_terminal(args: argparse.Namespace) -> None:
    root = Path(args.root)
    freeze, admission, _, inventory, group_split = _load_root(root)
    _output(reopen_v2_terminal(
        root / "terminal", freeze=freeze, admission=admission,
        inventory=inventory, group_split=group_split))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    initialize_parser = commands.add_parser("initialize")
    initialize_parser.add_argument("--freeze", required=True)
    initialize_parser.add_argument("--expected-freeze-sha256", required=True)
    initialize_parser.add_argument("--review-commit", required=True)
    initialize_parser.add_argument("--inventory", required=True)
    initialize_parser.add_argument("--group-split", required=True)
    initialize_parser.set_defaults(function=initialize)
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
    human_capture_parser = commands.add_parser("human-capture")
    human_capture_parser.add_argument("--root", required=True)
    human_capture_parser.add_argument("--source-path", required=True)
    human_capture_parser.set_defaults(function=human_capture)
    human_reference_parser = commands.add_parser("human-reference")
    human_reference_parser.add_argument("--root", required=True)
    human_reference_parser.add_argument("--source-path", required=True)
    human_reference_parser.add_argument(
        "--replicate", required=True,
        choices=("calibration-replicate-0", "calibration-replicate-1",
                 "test-primary"))
    human_reference_parser.set_defaults(function=human_reference)
    qualify = commands.add_parser("qualify-device")
    qualify.add_argument("--root", required=True)
    qualify.set_defaults(function=qualify_device)
    train = commands.add_parser("train-cohort")
    train.add_argument("--root", required=True)
    train.add_argument("--cohort-id", required=True)
    train.set_defaults(function=train_cohort)
    calibration = commands.add_parser("calibrate")
    calibration.add_argument("--root", required=True)
    calibration.set_defaults(function=calibrate)
    test = commands.add_parser("open-test")
    test.add_argument("--root", required=True)
    test.set_defaults(function=open_test)
    terminal = commands.add_parser("verify-terminal")
    terminal.add_argument("--root", required=True)
    terminal.set_defaults(function=verify_terminal)
    return result


def main() -> None:
    configure_numerical_runtime()
    args = parser().parse_args()
    args.function(args)


if __name__ == "__main__":
    main()

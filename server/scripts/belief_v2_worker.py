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


def _refuse_foreign_import_roots() -> None:
    """Refuse .pth-injected roots from another experiment environment."""
    allowed_roots = (
        Path(sys.base_prefix).resolve(),
        Path(sys.prefix).resolve(),
        SERVER,
    )
    for entry in sys.path:
        if type(entry) is not str or not entry:
            continue
        resolved = Path(entry).resolve()
        if not any(resolved.is_relative_to(root) for root in allowed_roots):
            raise RuntimeError("BELIEF-V1 V2 refuses foreign import roots")


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


_refuse_foreign_import_roots()
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
    reopen_actor_capture_lane_manifest,
    reopen_reference_lane_manifest,
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
from shengji.rl.belief_v2_freeze_builder import (  # noqa: E402
    build_v1_resource_failure_receipt,
    build_execution_freeze_from_receipts,
    resource_caps_from_bytes,
)
from shengji.rl.belief_v2_human_controller import (  # noqa: E402
    reopen_human_group_manifest,
    run_human_group_capture,
)
from shengji.rl.belief_v2_human_inventory import (  # noqa: E402
    H0_GROUP_SCHEMA,
    group_split_bytes,
    inventory_bytes,
)
from shengji.rl.belief_v2_human_reference_controller import (  # noqa: E402
    reopen_human_reference_group_manifest,
    run_human_reference_group,
)
from shengji.rl.belief_v2_terminal_controller import (  # noqa: E402
    reopen_v2_terminal,
    run_v2_terminal,
)
from shengji.rl.belief_v2_training_controller import (  # noqa: E402
    reopen_training_cohort_checkpoint_identity,
    run_training_cohort,
)
from shengji.rl.belief_v2_input_index_controller import (  # noqa: E402
    reopen_training_input_index,
    run_training_input_index,
)
from shengji.rl.belief_v2_tensor_cache_controller import (  # noqa: E402
    reopen_training_tensor_cache,
    run_training_tensor_cache,
)
from shengji.rl.belief_v2_progress import V2ProgressReporter  # noqa: E402
from shengji.rl.belief_v2_readiness_controller import (  # noqa: E402
    publish_v2_calibration_readiness,
    reopen_v2_calibration_readiness,
)
from shengji.rl.belief_v2_scoring import (  # noqa: E402
    V2DecisionScoringPool,
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


def freeze_design(args: argparse.Namespace) -> None:
    output = Path(args.out)
    evidence_root = Path(args.evidence_root)
    if not output.is_absolute() or not evidence_root.is_absolute() \
            or output.parent != evidence_root.parent \
            or output.exists() or output.is_symlink() \
            or evidence_root.exists() or evidence_root.is_symlink():
        raise ValueError(
            "V2 freeze output and unused evidence root must be absolute siblings")
    rationale_raw = (None if args.v2_reentry_rationale is None
                     else stable_read_bytes(Path(args.v2_reentry_rationale)))
    terminal_raw = (None if args.v1_terminal_report is None
                    else stable_read_bytes(Path(args.v1_terminal_report)))
    failure_raw = (
        None if args.v1_resource_failure_receipt is None
        else stable_read_bytes(Path(args.v1_resource_failure_receipt)))
    freeze = build_execution_freeze_from_receipts(
        repo=REPO, expected_git=args.expected_git,
        source_review_commit=args.expected_git,
        v1_terminal_report_raw=terminal_raw,
        v1_resource_failure_receipt_raw=failure_raw,
        v2_reentry_rationale_raw=rationale_raw,
        inventory_raw=stable_read_bytes(Path(args.inventory)),
        group_split_raw=stable_read_bytes(Path(args.group_split)),
        preflight_raw=stable_read_bytes(Path(args.preflight_result)),
        seed_scan_raw=stable_read_bytes(Path(args.seed_scan)),
        seed_registry_raw=stable_read_bytes(Path(args.seed_registry)),
        training_candidate_device=args.training_candidate_device,
        deadline_estimate_raw=stable_read_bytes(
            Path(args.deadline_estimate_receipt)),
        resource_caps=resource_caps_from_bytes(stable_read_bytes(
            Path(args.resource_caps))), evidence_root=evidence_root)
    digest = publish_exclusive_bytes(output, freeze.canonical_bytes())
    if digest != freeze.sha256():
        raise ValueError("V2 published freeze digest drift")
    _output({
        "freeze_path": str(output), "freeze_sha256": digest,
        "execution_git": freeze.execution_git,
        "source_review_commit": freeze.source_review_commit,
        "source_review_mode": "consolidated-source-and-freeze",
        "training_candidate_device": freeze.training_candidate_device,
        "bounded_offline_pipeline_authorized": False,
        "execution_started": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    })


def close_v1_resource_failure(args: argparse.Namespace) -> None:
    output = Path(args.out)
    if not output.is_absolute() or output.exists() or output.is_symlink():
        raise ValueError("V2 V1 closeout output path drift")
    raw = build_v1_resource_failure_receipt(
        repo=REPO, design_path=Path(args.v1_design),
        evidence_root=Path(args.v1_evidence_root),
        supervisor_log_path=Path(args.v1_supervisor_log),
        termination_review_commit=args.termination_review_commit,
        closeout_ledger_commit=args.closeout_ledger_commit)
    digest = publish_exclusive_bytes(output, raw)
    _output({
        "schema": "belief-v1-b2-operator-stopped-resource-failure-v1",
        "receipt_path": str(output), "receipt_sha256": digest,
        "v1_retry_authorized": False, "v1_result_exists": False,
        "v2_execution_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    })


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


def _progress(stage: str, worker: str):
    return V2ProgressReporter(stage=stage, worker=worker).update


def _recover_final(args: argparse.Namespace, final: Path) -> bool:
    """Return whether recovery must authenticate an existing final slot."""
    if getattr(args, "require_existing_final", False) \
            and not args.recover_existing:
        raise ValueError("V2 completed-artifact flag requires recovery")
    exists = final.exists() or final.is_symlink()
    if getattr(args, "require_existing_final", False) and not exists:
        raise ValueError("V2 completed recovery artifact is absent")
    return bool(args.recover_existing and exists)


def _human_group_digest(source_path: Path) -> str:
    source_sha256 = _sha256(stable_read_bytes(source_path))
    return hashlib.sha256(
        f"{H0_GROUP_SCHEMA}|{source_sha256}".encode("ascii")).hexdigest()


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
    final = root / "capture" / f"lane-{args.lane:02d}"
    if _recover_final(args, final):
        _output(reopen_actor_capture_lane_manifest(
            final, freeze=freeze, admission=admission, lane=args.lane))
        return
    _output(run_capture_lane(
        root, freeze, admission, repo=REPO, lane=args.lane,
        review_marker=marker,
        progress=_progress("capture", f"lane-{args.lane:02d}")))


def reference_lane(args: argparse.Namespace) -> None:
    root = Path(args.root)
    freeze, admission, marker, _, _ = _load_root(root)
    final = root / "reference" / f"lane-{args.lane:02d}"
    if _recover_final(args, final):
        _output(reopen_reference_lane_manifest(
            final,
            capture_directory=root / "capture" / f"lane-{args.lane:02d}",
            freeze=freeze, admission=admission, lane=args.lane))
        return
    _output(run_reference_lane(
        root, freeze, admission, repo=REPO, lane=args.lane,
        review_marker=marker,
        progress=_progress("reference", f"lane-{args.lane:02d}")))


def human_capture(args: argparse.Namespace) -> None:
    root = Path(args.root)
    freeze, admission, marker, inventory, group_split = _load_root(root)
    final = (root / "human-capture"
             / f"group-{_human_group_digest(Path(args.source_path))}")
    if _recover_final(args, final):
        _output(reopen_human_group_manifest(
            final, freeze=freeze, admission=admission))
        return
    _output(run_human_group_capture(
        root, freeze, admission, repo=REPO,
        source_path=Path(args.source_path), inventory=inventory,
        group_split=group_split, review_marker=marker,
        progress=_progress("human-capture", "source-group")))


def human_reference(args: argparse.Namespace) -> None:
    root = Path(args.root)
    freeze, admission, marker, inventory, group_split = _load_root(root)
    final = (root / "human-reference"
             / f"group-{_human_group_digest(Path(args.source_path))}"
             / args.replicate)
    if _recover_final(args, final):
        _output(reopen_human_reference_group_manifest(
            final, freeze=freeze, admission=admission))
        return
    _output(run_human_reference_group(
        root, freeze, admission, repo=REPO,
        source_path=Path(args.source_path), inventory=inventory,
        group_split=group_split, replicate=args.replicate,
        review_marker=marker,
        progress=_progress("human-reference", args.replicate)))


def build_training_index(args: argparse.Namespace) -> None:
    root = Path(args.root)
    freeze, admission, marker, inventory, group_split = _load_root(root)
    final = root / "training-input-index" / "result"
    if _recover_final(args, final):
        manifest, _ = reopen_training_input_index(
            final, freeze=freeze, admission=admission)
        _output(manifest)
        return
    _output(run_training_input_index(
        root, freeze, admission, repo=REPO, review_marker=marker,
        inventory=inventory, group_split=group_split,
        progress=_progress("training-input-index", "all-sources")))


def build_training_cache(args: argparse.Namespace) -> None:
    root = Path(args.root)
    freeze, admission, marker, _, _ = _load_root(root)
    final = root / "training-tensor-cache" / "result"
    if _recover_final(args, final):
        manifest, _, _, _, _ = reopen_training_tensor_cache(
            final, freeze=freeze, admission=admission,
            verify_all_bytes=False)
        _output(manifest)
        return
    _output(run_training_tensor_cache(
        root, freeze, admission, repo=REPO, review_marker=marker,
        progress=_progress("training-tensor-cache", "all-cohorts")))


def qualify_device(args: argparse.Namespace) -> None:
    root = Path(args.root)
    freeze, admission, marker, _, _ = _load_root(root)
    _, inputs = reopen_training_input_index(
        root / "training-input-index" / "result", freeze=freeze,
        admission=admission)
    primary = next(row for row in inputs.realizations
                   if row.cohort_id == "synthetic-primary")
    final = root / "device-qualification" / "result"
    if _recover_final(args, final):
        manifest, _, _ = reopen_device_qualification(
            final, freeze=freeze, admission=admission, primary=primary)
        _output(manifest)
        return
    _, factories, _, _, _ = reopen_training_tensor_cache(
        root / "training-tensor-cache" / "result", freeze=freeze,
        admission=admission, verify_all_bytes=False)
    _output(run_device_qualification(
        root, freeze, admission, repo=REPO, review_marker=marker,
        primary=primary, primary_examples=None,
        batch_factory=factories[primary.cohort_id],
        progress=_progress("device-qualification", "candidate-device")))


def train_cohort(args: argparse.Namespace) -> None:
    root = Path(args.root)
    freeze, admission, marker, _, _ = _load_root(root)
    _, inputs = reopen_training_input_index(
        root / "training-input-index" / "result", freeze=freeze,
        admission=admission)
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
    _, factories, calibration_factory, control_dose, cache_sha256 = (
        reopen_training_tensor_cache(
            root / "training-tensor-cache" / "result", freeze=freeze,
            admission=admission, verify_all_bytes=False))
    compact_control_dose = (
        control_dose if realization.kind
        == "hard-geometry-label-permutation" else 0)
    final = root / "training" / realization.cohort_id
    if _recover_final(args, final):
        manifest, _ = reopen_training_cohort_checkpoint_identity(
            final, freeze=freeze, admission=admission,
            primary=primary, realization=realization,
            calibration=inputs.common_calibration,
            qualification_plan=plan, qualification_result=result,
            compact_control_dose=compact_control_dose,
            cache_manifest_sha256=cache_sha256)
        _output(manifest)
        return
    _output(run_training_cohort(
        root, freeze, admission, repo=REPO, review_marker=marker,
        primary=primary, realization=realization,
        training_examples=None, calibration=inputs.common_calibration,
        calibration_examples=None,
        training_batch_factory=factories[realization.cohort_id],
        calibration_batch_factory=calibration_factory,
        cache_manifest_sha256=cache_sha256,
        cache_control_dose=compact_control_dose,
        qualification_plan=plan, qualification_result=result,
        progress=_progress("training", args.cohort_id)))


def calibrate(args: argparse.Namespace) -> None:
    root = Path(args.root)
    freeze, admission, marker, inventory, group_split = _load_root(root)
    progress = _progress("calibration", "all-cohorts")
    final = root / "calibration" / "selection"
    if _recover_final(args, final):
        readiness = root / "calibration" / "readiness"
        if readiness.exists() or readiness.is_symlink():
            reopened = reopen_v2_calibration_readiness(
                readiness, freeze=freeze, admission=admission,
                inventory=inventory, group_split=group_split)
            _output(reopened[1])
        else:
            publish_v2_calibration_readiness(
                root, freeze=freeze, admission=admission,
                inventory=inventory, group_split=group_split,
                progress=progress)
            _output(reopen_v2_calibration_readiness(
                readiness, freeze=freeze, admission=admission,
                inventory=inventory, group_split=group_split)[1])
        return
    _output(run_v2_calibration_selection(
        root, freeze, admission, repo=REPO, review_marker=marker,
        inventory=inventory, group_split=group_split,
        progress=progress))


def open_test(args: argparse.Namespace) -> None:
    root = Path(args.root)
    freeze, admission, marker, inventory, group_split = _load_root(root)
    final = root / "terminal"
    readiness = reopen_v2_calibration_readiness(
        root / "calibration" / "readiness", freeze=freeze,
        admission=admission, inventory=inventory, group_split=group_split)
    cohorts = readiness[4]
    with V2DecisionScoringPool(cohorts) as decision_pool:
        decision_pool.warm()
        if _recover_final(args, final):
            _output(reopen_v2_terminal(
                final, freeze=freeze, admission=admission,
                inventory=inventory, group_split=group_split,
                decision_pool=decision_pool,
                progress=_progress("terminal", "test-opening-reopen")))
            return
        _output(run_v2_terminal(
            root, freeze, admission, repo=REPO, review_marker=marker,
            inventory=inventory, group_split=group_split,
            decision_pool=decision_pool,
            progress=_progress("terminal", "test-opening")))


def verify_terminal(args: argparse.Namespace) -> None:
    root = Path(args.root)
    freeze, admission, _, inventory, group_split = _load_root(root)
    readiness = reopen_v2_calibration_readiness(
        root / "calibration" / "readiness", freeze=freeze,
        admission=admission, inventory=inventory, group_split=group_split)
    cohorts = readiness[4]
    with V2DecisionScoringPool(cohorts) as decision_pool:
        decision_pool.warm()
        _output(reopen_v2_terminal(
            root / "terminal", freeze=freeze, admission=admission,
            inventory=inventory, group_split=group_split,
            decision_pool=decision_pool,
            progress=_progress("terminal-verification", "reopen")))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    close_v1 = commands.add_parser("close-v1-resource-failure")
    close_v1.add_argument("--v1-design", required=True)
    close_v1.add_argument("--v1-evidence-root", required=True)
    close_v1.add_argument("--v1-supervisor-log", required=True)
    close_v1.add_argument("--termination-review-commit", required=True)
    close_v1.add_argument("--closeout-ledger-commit", required=True)
    close_v1.add_argument("--out", required=True)
    close_v1.set_defaults(function=close_v1_resource_failure)
    freeze = commands.add_parser("freeze-design")
    freeze.add_argument("--expected-git", required=True)
    v1_route = freeze.add_mutually_exclusive_group(required=True)
    v1_route.add_argument("--v1-terminal-report")
    v1_route.add_argument("--v1-resource-failure-receipt")
    freeze.add_argument("--v2-reentry-rationale")
    freeze.add_argument("--inventory", required=True)
    freeze.add_argument("--group-split", required=True)
    freeze.add_argument("--preflight-result", required=True)
    freeze.add_argument("--seed-scan", required=True)
    freeze.add_argument("--seed-registry", required=True)
    freeze.add_argument("--training-candidate-device", required=True)
    freeze.add_argument("--deadline-estimate-receipt", required=True)
    freeze.add_argument("--resource-caps", required=True)
    freeze.add_argument("--evidence-root", required=True)
    freeze.add_argument("--out", required=True)
    freeze.set_defaults(function=freeze_design)
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
    training_index = commands.add_parser("build-training-index")
    training_index.add_argument("--root", required=True)
    training_index.set_defaults(function=build_training_index)
    training_cache = commands.add_parser("build-training-cache")
    training_cache.add_argument("--root", required=True)
    training_cache.set_defaults(function=build_training_cache)
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
    for operational in (
            capture, reference, human_capture_parser,
            human_reference_parser, training_index, training_cache,
            qualify, train, calibration, test, terminal):
        operational.add_argument(
            "--recover-existing", action="store_true",
            help=argparse.SUPPRESS)
        operational.add_argument(
            "--require-existing-final", action="store_true",
            help=argparse.SUPPRESS)
    return result


def main() -> None:
    configure_numerical_runtime()
    args = parser().parse_args()
    args.function(args)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Run one externally reviewed Value V1 P1 pilot stage by stage."""

from __future__ import annotations

import sys


if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("Value V1 scientific execution requires Python -P -B")

import argparse
import hashlib
import json
import os
import resource
import stat
import subprocess
import time
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent


def _refuse_import_shadows() -> None:
    if os.environ.get("PYTHONPATH"):
        raise RuntimeError("Value V1 scientific execution refuses PYTHONPATH")
    tracked_raw = subprocess.run(
        ("git", "ls-files", "-z"), cwd=REPO, check=True,
        capture_output=True).stdout
    tracked = {value.decode("utf-8") for value in tracked_raw.split(b"\0")
               if value}
    loadable = {".py", ".pyc", ".pyo", ".so", ".pyd", ".dylib"}
    natives = []
    for root in (SERVER / "shengji", SERVER / "scripts"):
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in loadable:
                continue
            relative = path.relative_to(REPO).as_posix()
            if path.suffix in {".pyc", ".pyo"}:
                raise RuntimeError(
                    "Value V1 scientific execution refuses bytecode")
            if path.suffix in {".so", ".pyd", ".dylib"} \
                    and path.parent == SERVER / "shengji" / "engine" \
                    and path.name.startswith("_fast."):
                natives.append(path)
            elif relative not in tracked:
                raise RuntimeError(
                    "Value V1 scientific execution refuses import shadow")
    if len(natives) != 1:
        raise RuntimeError("Value V1 scientific native population drift")


_refuse_import_shadows()
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

import torch  # noqa: E402

from shengji.rl.belief_contract import canonical_json_bytes  # noqa: E402
from shengji.rl.world_afterstate_population import (  # noqa: E402
    reopen_population_audit_fold, validate_population_audit_manifest,
    validate_population_manifest)
from shengji.rl.world_afterstate_v1_capacity import (  # noqa: E402
    _runtime)
from shengji.rl.world_afterstate_v1_execution import (  # noqa: E402
    build_scientific_pipeline, build_target_free_prediction_build,
    independently_reconstruct_scientific_pipeline,
    publish_target_free_prediction_build, reopen_calibration_labels,
    reopen_scientific_cohort_build,
    reopen_target_free_prediction_directory, train_scientific_cohort)
from shengji.rl.world_afterstate_v1_experiment import (  # noqa: E402
    SOURCE_PATHS)
from shengji.rl.world_afterstate_v1_pipeline import (  # noqa: E402
    publish_pipeline_build, reopen_pipeline_directory)
from shengji.rl.world_afterstate_v1_scientific import (  # noqa: E402
    consume_stage_attempt, initialize_scientific_root,
    reopen_scientific_root)
from shengji.rl.world_afterstate_v1_training_controller import (  # noqa: E402
    TRAINING_COHORTS, publish_cohort_build)


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_read(path: Path, label: str):
    if path.is_symlink():
        raise RuntimeError(f"{label} path drift")
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        raw = handle.read()
        after = os.fstat(handle.fileno())
    identity = lambda value: (
        value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
        value.st_ctime_ns)
    if identity(before) != identity(after) or before.st_nlink != 1 \
            or stat.S_IMODE(before.st_mode) != 0o400 \
            or not stat.S_ISREG(before.st_mode):
        raise RuntimeError(f"{label} is mutable or changed while read")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError(f"{label} is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise RuntimeError(f"{label} is not canonical JSON")
    return raw, value


def _git(*args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=REPO, check=True,
        capture_output=True, text=True).stdout.strip()


def _strict_live(freeze: dict, expected_git: str) -> None:
    if freeze["source_git"] != expected_git \
            or _git("rev-parse", "HEAD") != expected_git \
            or _git("status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("Value V1 scientific source head drift")
    paths = {key: REPO / relative
             for key, relative in SOURCE_PATHS.items()}
    if set(paths) != set(freeze["source_sha256s"]) \
            or any(path.is_symlink() or not path.is_file()
                   for path in paths.values()) \
            or {key: _sha_file(path) for key, path in sorted(paths.items())} \
            != freeze["source_sha256s"]:
        raise RuntimeError("Value V1 scientific source bytes drift")
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(freeze["learner"]["torch_threads"])
    if _runtime() != freeze["runtime"]:
        raise RuntimeError("Value V1 scientific runtime drift")


def _context(args):
    root = Path(args.root).resolve()
    freeze, capacity, admission, _manifest = reopen_scientific_root(
        root, repo=REPO)
    _strict_live(freeze, args.expected_git)
    return root, freeze, capacity, admission


def _progress(stage: str, started: int):
    def emit(value, total=None):
        if type(value) is dict:
            completed = value["completed_units"]
            units = value["total_units"]
            phase = f"epoch-{value.get('epoch', 0)}"
        else:
            completed = value
            units = total
            phase = "rows"
        elapsed = time.monotonic_ns() - started
        remaining = (elapsed * (units - completed) // completed
                     if completed else None)
        print(canonical_json_bytes({
            "schema": "world-afterstate-v1-p1-progress-v1",
            "stage": stage, "phase": phase,
            "completed_units": completed, "total_units": units,
            "percent_basis_points": completed * 10_000 // units,
            "elapsed_nanoseconds": elapsed,
            "estimated_remaining_nanoseconds": remaining,
            "cpu_load_1m_milli": int(os.getloadavg()[0] * 1000),
            "peak_rss_bytes": resource.getrusage(
                resource.RUSAGE_SELF).ru_maxrss * 1024,
            "evidence_artifact": False,
            "gameplay_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        }).decode("ascii").rstrip(), flush=True)
    return emit


def _write_receipt(path: Path, value: dict) -> None:
    if path.exists() or path.is_symlink():
        raise RuntimeError("verification receipt namespace occupied")
    raw = canonical_json_bytes(value)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o400)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _public_audits(args, freeze):
    population_raw, population = _canonical_read(
        Path(args.population), "V0 population")
    audit_raw, audit_manifest = _canonical_read(
        Path(args.audit_manifest), "V0 audit manifest")
    inputs = freeze["v0_inputs"]
    if _sha_bytes(population_raw) != inputs["population_external_sha256"] \
            or population["manifest_sha256"] \
            != inputs["population_manifest_sha256"] \
            or _sha_bytes(audit_raw) \
            != inputs["audit_manifest_external_sha256"] \
            or audit_manifest["manifest_sha256"] \
            != inputs["audit_manifest_sha256"]:
        raise RuntimeError("V0 audit input binding drift")
    validate_population_manifest(population)
    validate_population_audit_manifest(audit_manifest, population)
    return population, audit_manifest


def _cohort_builds(root: Path):
    return {name: reopen_scientific_cohort_build(
        root / "outputs" / "cohorts" / name) for name in TRAINING_COHORTS}


def _initialize(args) -> None:
    freeze_raw, freeze = _canonical_read(Path(args.freeze), "P1 freeze")
    from shengji.rl.world_afterstate_v1_capacity import \
        reopen_capacity_directory
    capacity = reopen_capacity_directory(Path(args.capacity))
    # Refuse a wrong head or runtime before the durable admission lock is
    # created.  The post-publication _context check remains as an independent
    # reconstruction witness, but it must not be the first live check.
    _strict_live(freeze, args.expected_git)
    initialize_scientific_root(
        Path(args.root), freeze_raw=freeze_raw, capacity_build=capacity,
        repo=REPO, review_commit=args.review_commit)
    root, freeze, _capacity, _admission = _context(args)
    if root != Path(args.root).resolve() or freeze["source_git"] \
            != args.expected_git:
        raise RuntimeError("Value V1 initialization reconstruction drift")


def _train(args) -> None:
    root, freeze, capacity, admission = _context(args)
    name = args.cohort
    if name not in TRAINING_COHORTS:
        raise RuntimeError("Value V1 cohort name drift")
    target = root / "outputs" / "cohorts" / name
    consume_stage_attempt(
        root, stage=f"train-{name}",
        freeze_sha256=freeze["freeze_sha256"],
        admission_sha256=admission["admission_sha256"],
        inputs={
            "cohort_name": name,
            "train_row_population_sha256": freeze["population"][
                "train_row_population_sha256"],
            "subsplit_manifest_sha256": freeze["population"][
                "subsplit_manifest_sha256"],
            "wall_cap_nanoseconds": freeze["resources"][
                "cohort_wall_cap_nanoseconds"],
        })
    started = time.monotonic_ns()
    build = train_scientific_cohort(
        freeze=freeze, capacity_build=capacity, cohort_name=name,
        population_path=Path(args.population),
        dataset_manifest_path=Path(args.dataset_manifest),
        row_root=Path(args.row_root), progress=_progress(name, started))
    if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024 \
            > freeze["resources"]["memory_limit_bytes"]:
        raise RuntimeError("Value V1 cohort exceeded memory cap")
    publish_cohort_build(target, build)
    if reopen_scientific_cohort_build(target) != build:
        raise RuntimeError("Value V1 cohort immediate reconstruction drift")


def _predictions(args) -> None:
    root, freeze, _capacity, admission = _context(args)
    cohorts = _cohort_builds(root)
    population, audit_manifest = _public_audits(args, freeze)
    consume_stage_attempt(
        root, stage="seal-target-free-predictions",
        freeze_sha256=freeze["freeze_sha256"],
        admission_sha256=admission["admission_sha256"],
        inputs={
            "cohort_manifest_sha256s": {
                name: cohorts[name].manifest["manifest_sha256"]
                for name in TRAINING_COHORTS},
            "population_manifest_sha256": population["manifest_sha256"],
            "audit_manifest_sha256": audit_manifest["manifest_sha256"],
            "calibration_labels_opened": False,
        })
    materials = reopen_population_audit_fold(
        audit_manifest, population, Path(args.audit_root),
        fold="calibration")
    build = build_target_free_prediction_build(
        freeze=freeze, population_manifest=population,
        audit_manifest=audit_manifest, audit_materials=materials,
        cohort_builds=cohorts)
    target = root / "outputs" / "target-free-predictions"
    publish_target_free_prediction_build(target, build)
    if reopen_target_free_prediction_directory(target) != build:
        raise RuntimeError("Value V1 prediction immediate reopen drift")


def _calibration(args) -> None:
    root, freeze, capacity, admission = _context(args)
    cohorts = _cohort_builds(root)
    prediction = reopen_target_free_prediction_directory(
        root / "outputs" / "target-free-predictions")
    consume_stage_attempt(
        root, stage="open-calibration-labels",
        freeze_sha256=freeze["freeze_sha256"],
        admission_sha256=admission["admission_sha256"],
        inputs={
            "prediction_manifest_sha256": prediction.manifest[
                "manifest_sha256"],
            "calibration_label_row_count": freeze["population"][
                "calibration_label_row_count"],
            "calibration_label_pair_count": freeze["population"][
                "calibration_label_pair_count"],
            "report_rows_opened": False,
        })
    started = time.monotonic_ns()
    pairs = reopen_calibration_labels(
        freeze=freeze, population_path=Path(args.population),
        dataset_manifest_path=Path(args.dataset_manifest),
        row_root=Path(args.row_root),
        deadline_monotonic_ns=started + freeze["resources"][
            "audit_wall_cap_nanoseconds"],
        progress=_progress("calibration-labels", started))
    pipeline = build_scientific_pipeline(
        freeze=freeze, capacity_build=capacity, cohort_builds=cohorts,
        prediction_build=prediction, calibration_pairs=pairs)
    target = root / "outputs" / "terminal"
    publish_pipeline_build(target, pipeline)
    if reopen_pipeline_directory(target) != pipeline:
        raise RuntimeError("Value V1 terminal immediate reconstruction drift")


def _verify(args) -> None:
    root, freeze, capacity, admission = _context(args)
    cohorts = _cohort_builds(root)
    prediction = reopen_target_free_prediction_directory(
        root / "outputs" / "target-free-predictions")
    terminal = reopen_pipeline_directory(root / "outputs" / "terminal")
    consume_stage_attempt(
        root, stage="independent-reconstruction",
        freeze_sha256=freeze["freeze_sha256"],
        admission_sha256=admission["admission_sha256"],
        inputs={
            "terminal_manifest_sha256": terminal.manifest["manifest_sha256"],
            "prediction_manifest_sha256": prediction.manifest[
                "manifest_sha256"],
            "calibration_reopen_for_reconstruction": True,
            "report_rows_opened": False,
        })
    population, audit_manifest = _public_audits(args, freeze)
    materials = reopen_population_audit_fold(
        audit_manifest, population, Path(args.audit_root),
        fold="calibration")
    started = time.monotonic_ns()
    pairs = reopen_calibration_labels(
        freeze=freeze, population_path=Path(args.population),
        dataset_manifest_path=Path(args.dataset_manifest),
        row_root=Path(args.row_root),
        deadline_monotonic_ns=started + freeze["resources"][
            "reconstruction_wall_cap_nanoseconds"],
        progress=_progress("independent-reconstruction", started))
    rebuilt = independently_reconstruct_scientific_pipeline(
        expected_pipeline_root=root / "outputs" / "terminal",
        freeze=freeze, capacity_build=capacity,
        population_manifest=population, audit_manifest=audit_manifest,
        audit_materials=materials, cohort_builds=cohorts,
        prediction_build=prediction, calibration_pairs=pairs)
    body = {
        "schema": "world-afterstate-v1-p1-independent-reconstruction-v1",
        "freeze_sha256": freeze["freeze_sha256"],
        "prediction_manifest_sha256": prediction.manifest[
            "manifest_sha256"],
        "terminal_manifest_sha256": rebuilt.manifest["manifest_sha256"],
        "terminal_decision": rebuilt.manifest["terminal_decision"],
        "calibration_label_reconstruction_open_count": 1,
        "report_rows_opened": False,
        "provider_audit_rows_opened": False,
        "verified": True,
        "elapsed_nanoseconds": time.monotonic_ns() - started,
        "gameplay_authorized": False,
        "strength_claim_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "retry_authorized": False,
        "r5_authorized": False,
    }
    receipt = {**body, "receipt_sha256": hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()}
    _write_receipt(
        root / "outputs" / "independent-reconstruction.json", receipt)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("mode", choices=(
        "initialize", "train-cohort", "seal-predictions",
        "open-calibration", "verify"))
    value.add_argument("--root", required=True)
    value.add_argument("--expected-git", required=True)
    value.add_argument("--population")
    value.add_argument("--audit-manifest")
    value.add_argument("--audit-root")
    value.add_argument("--dataset-manifest")
    value.add_argument("--row-root")
    value.add_argument("--freeze")
    value.add_argument("--capacity")
    value.add_argument("--review-commit")
    value.add_argument("--cohort", choices=TRAINING_COHORTS)
    return value


def main() -> None:
    args = parser().parse_args()
    initialization = (args.freeze, args.capacity, args.review_commit)
    data = (args.population, args.audit_manifest, args.audit_root,
            args.dataset_manifest, args.row_root)
    if args.mode == "initialize":
        if not all(initialization) or any(data) or args.cohort is not None:
            raise RuntimeError("Value V1 initialization argument drift")
        _initialize(args)
        return
    if any(initialization):
        raise RuntimeError("Value V1 stage argument drift")
    if args.mode == "train-cohort":
        if args.cohort is None or not args.population \
                or not args.dataset_manifest or not args.row_root \
                or args.audit_manifest or args.audit_root:
            raise RuntimeError("Value V1 training argument drift")
        _train(args)
    elif args.mode == "seal-predictions":
        if args.cohort is not None or not args.population \
                or not args.audit_manifest or not args.audit_root \
                or args.dataset_manifest or args.row_root:
            raise RuntimeError(
                "Value V1 target-free prediction argument drift")
        _predictions(args)
    else:
        if args.cohort is not None or not all(data):
            raise RuntimeError("Value V1 held-out stage argument drift")
        if args.mode == "open-calibration":
            _calibration(args)
        else:
            _verify(args)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""One reviewed, staged Value-Afterstate V0 scientific execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import stat
import subprocess
import sys
import time
from pathlib import Path


def _preimport_guard() -> None:
    if not sys.flags.safe_path or not sys.dont_write_bytecode \
            or os.environ.get("PYTHONPATH") \
            or os.environ.get("SHENGJI_FAST") != "1" \
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise RuntimeError(
            "scientific run requires -P -B and strict environment")
    server = Path(__file__).resolve().parents[1]
    bytecode = [
        path for root in (server / "shengji", server / "scripts")
        for path in root.rglob("*")
        if path.is_file() and (path.suffix == ".pyc"
                               or "__pycache__" in path.parts)]
    if bytecode:
        raise RuntimeError(
            "scientific source tree contains Python bytecode")


_preimport_guard()
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import torch

from shengji.ai import mcbot, registry
from shengji.engine import ballot, combos, fast, legal, round as round_mod
from shengji.rl import (
    world_afterstate, world_afterstate_admission,
    world_afterstate_checkpoint, world_afterstate_controller,
    world_afterstate_controls, world_afterstate_dataset,
    world_afterstate_evaluation, world_afterstate_experiment,
    world_afterstate_label, world_afterstate_model,
    world_afterstate_population, world_afterstate_population_builder,
    world_afterstate_population_packet, world_afterstate_scientific,
    world_afterstate_sources, world_afterstate_terminal,
    world_afterstate_terminal_controller, world_afterstate_training,
    world_afterstate_training_controller)
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_controller import (
    build_scientific_dataset, population_materials_for_dataset,
    publish_scientific_dataset, reopen_scientific_dataset)
from shengji.rl.world_afterstate_experiment import (
    EXPERIMENT_RUNTIME_KEYS, EXPERIMENT_SOURCE_KEYS,
    validate_experiment_freeze)
from shengji.rl.world_afterstate_population import (
    validate_population_manifest)
from shengji.rl.world_afterstate_population_packet import (
    validate_population_packet_identity)
from shengji.rl.world_afterstate_scientific import (
    consume_stage_attempt, initialize_scientific_root,
    reopen_scientific_root)
from shengji.rl.world_afterstate_terminal_controller import (
    run_open_report, verify_terminal_artifact)
from shengji.rl.world_afterstate_training_controller import (
    publish_training_build, reopen_training_build,
    train_eight_seed_cohort)


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=repo, check=True, capture_output=True,
        text=True).stdout.strip()


def _source_paths() -> dict[str, Path]:
    paths = {
        "afterstate": Path(world_afterstate.__file__),
        "sources": Path(world_afterstate_sources.__file__),
        "label": Path(world_afterstate_label.__file__),
        "model": Path(world_afterstate_model.__file__),
        "population": Path(world_afterstate_population.__file__),
        "population_packet": Path(world_afterstate_population_packet.__file__),
        "population_builder": Path(world_afterstate_population_builder.__file__),
        "dataset": Path(world_afterstate_dataset.__file__),
        "controller": Path(world_afterstate_controller.__file__),
        "training": Path(world_afterstate_training.__file__),
        "training_controller": Path(world_afterstate_training_controller.__file__),
        "checkpoint": Path(world_afterstate_checkpoint.__file__),
        "evaluation": Path(world_afterstate_evaluation.__file__),
        "controls": Path(world_afterstate_controls.__file__),
        "terminal": Path(world_afterstate_terminal.__file__),
        "terminal_controller": Path(world_afterstate_terminal_controller.__file__),
        "admission": Path(world_afterstate_admission.__file__),
        "scientific_controller": Path(world_afterstate_scientific.__file__),
        "experiment": Path(world_afterstate_experiment.__file__),
        "launcher": Path(__file__).with_name(
            "world_afterstate_v0_experiment.py"),
        "population_launcher": Path(__file__).with_name(
            "world_afterstate_v0_population.py"),
        "scientific_launcher": Path(__file__),
        "engine_round": Path(round_mod.__file__),
        "engine_legal": Path(legal.__file__),
        "engine_fast": Path(fast.__file__),
        "engine_ballot": Path(ballot.__file__),
        "ai_mcbot": Path(mcbot.__file__),
        "ai_registry": Path(registry.__file__),
    }
    if set(paths) != set(EXPERIMENT_SOURCE_KEYS) \
            or any(path.is_symlink() or not path.is_file()
                   for path in paths.values()):
        raise RuntimeError("scientific source population drift")
    return paths


def _strict_live(repo: Path, freeze: dict, expected_git: str) -> None:
    if freeze.get("source_git") != expected_git \
            or _git(repo, "rev-parse", "HEAD") != expected_git \
            or _git(repo, "status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("scientific run requires exact clean source head")
    native = getattr(fast, "_fast", None)
    if fast.HAVE_FAST is not True or native is None \
            or combos.decompose is not fast.decompose \
            or round_mod.Round.play is not native.round_play:
        raise RuntimeError("scientific run requires active compiled engine")
    observed_sources = {
        key: _sha_file(path) for key, path in sorted(_source_paths().items())}
    if observed_sources != freeze.get("source_sha256s"):
        raise RuntimeError("scientific source bytes differ from freeze")
    runtime = freeze.get("runtime")
    if type(runtime) is not dict or set(runtime) != EXPERIMENT_RUNTIME_KEYS:
        raise RuntimeError("scientific runtime population drift")
    python = Path(sys.executable).resolve()
    router = Path(fast.__file__).resolve()
    native_path = Path(native.__file__).resolve()
    observed = {
        "host": os.uname().nodename,
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "torch": str(torch.__version__),
        "device": runtime["device"],
        "cpu_count": os.cpu_count(),
        "torch_threads": torch.get_num_threads(),
        "torch_interop_threads": torch.get_num_interop_threads(),
        "environment": {"SHENGJI_FAST": os.environ.get("SHENGJI_FAST"),
                        "SHENGJI_REQUIRE_VOIDS":
                            os.environ.get("SHENGJI_REQUIRE_VOIDS")},
        "python_executable": str(python),
        "python_executable_sha256": _sha_file(python),
        "fast_router_path": str(router),
        "fast_router_sha256": _sha_file(router),
        "native_path": str(native_path),
        "native_sha256": _sha_file(native_path),
        "compiled_engine_active": True,
        "safe_path": True,
        "dont_write_bytecode": True,
        "pythonpath_absent": True,
    }
    if observed != runtime:
        raise RuntimeError("scientific runtime differs from freeze")


def _read_canonical(path: Path, label: str) -> tuple[bytes, dict]:
    if path.is_symlink():
        raise RuntimeError(f"{label} path is a symlink")
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        raw = handle.read()
        after = os.fstat(handle.fileno())
    identity = lambda item: (
        item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns,
        item.st_ctime_ns)
    if identity(before) != identity(after) \
            or before.st_size != len(raw) or before.st_nlink != 1 \
            or not stat.S_ISREG(before.st_mode):
        raise RuntimeError(f"{label} changed while read")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError(f"{label} is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise RuntimeError(f"{label} is not canonical JSON")
    return raw, value


def _public_population(population_root: Path, freeze: dict):
    public_raw, public = _read_canonical(
        population_root / "population.json", "population manifest")
    packet_raw, packet = _read_canonical(
        population_root / "packet.json", "population packet")
    validate_population_manifest(public)
    validate_population_packet_identity(packet)
    binding = freeze["population_packet"]
    if hashlib.sha256(packet_raw).hexdigest() \
            != binding["external_sha256"] \
            or packet["packet_sha256"] != binding["packet_sha256"] \
            or hashlib.sha256(public_raw).hexdigest() \
            != binding["population_manifest_external_sha256"] \
            or public["manifest_sha256"] \
            != binding["population_manifest_sha256"]:
        raise RuntimeError("scientific population differs from freeze")
    return public, packet_raw


def _context(args):
    repo = Path(__file__).resolve().parents[2]
    root = Path(args.root)
    freeze, capacity, packet, admission, _manifest = \
        reopen_scientific_root(root, repo=repo)
    _strict_live(repo, freeze, args.expected_git)
    population, packet_raw = _public_population(
        Path(args.population_root), freeze)
    if canonical_json_bytes(packet) != packet_raw:
        raise RuntimeError("scientific root/population packet drift")
    return repo, root, freeze, capacity, packet, admission, population


def _progress(stage: str, started: int):
    def emit(*values):
        if len(values) == 2:
            completed, total = values
            phase = stage
        elif len(values) == 3 and isinstance(values[0], int):
            _epoch, completed, total = values
            phase = f"{stage}-epoch-{_epoch}"
        elif len(values) == 3:
            phase, completed, total = values
        else:
            raise RuntimeError("scientific progress callback drift")
        elapsed = time.monotonic_ns() - started
        remaining = (elapsed * (total - completed) // completed
                     if completed else None)
        print(json.dumps({
            "schema": "world-afterstate-e3-e4-progress-v0",
            "stage": stage, "phase": phase,
            "completed_units": completed, "total_units": total,
            "percent_basis_points": completed * 10_000 // total,
            "elapsed_nanoseconds": elapsed,
            "estimated_remaining_nanoseconds": remaining,
            "evidence_artifact": False,
            "gameplay_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        }, sort_keys=True, separators=(",", ":")), flush=True)
    return emit


def _write_receipt(path: Path, value: dict) -> None:
    if path.exists() or path.is_symlink():
        raise RuntimeError("scientific receipt namespace occupied")
    with path.open("xb") as handle:
        handle.write(canonical_json_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o400)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _initialize(args) -> None:
    repo = Path(__file__).resolve().parents[2]
    freeze_raw, freeze = _read_canonical(Path(args.freeze), "freeze")
    capacity_raw, _ = _read_canonical(Path(args.capacity), "capacity")
    packet_raw, _ = _read_canonical(
        Path(args.population_packet), "population packet")
    validate_experiment_freeze(freeze, capacity_raw, packet_raw)
    _strict_live(repo, freeze, args.expected_git)
    _public_population(Path(args.population_root), freeze)
    initialize_scientific_root(
        Path(args.root), freeze_raw=freeze_raw,
        capacity_raw=capacity_raw, population_packet_raw=packet_raw,
        repo=repo, review_commit=args.review_commit)


def _dataset(args) -> None:
    _repo, root, freeze, _capacity, _packet, admission, population = \
        _context(args)
    target = root / "artifacts" / "dataset"
    if target.exists() or target.is_symlink():
        raise RuntimeError("scientific dataset namespace occupied")
    consume_stage_attempt(
        root, stage="dataset", freeze_sha256=freeze["freeze_sha256"],
        admission_sha256=admission["admission_sha256"],
        inputs={
            "population_manifest_sha256": population["manifest_sha256"],
            "workers": freeze["labels"]["workers"],
            "wall_cap_seconds": freeze["labels"]["wall_cap_seconds"],
        })
    reopened_public, _audit, materials = population_materials_for_dataset(
        Path(args.population_root))
    if canonical_json_bytes(reopened_public) != canonical_json_bytes(population):
        raise RuntimeError("scientific private population drift")
    started = time.monotonic_ns()
    build = build_scientific_dataset(
        freeze_sha256=freeze["freeze_sha256"],
        population_manifest=population, audit_materials=materials,
        repetitions_by_fold=freeze["labels"]["repetitions_by_fold"],
        workers=freeze["labels"]["workers"],
        wall_budget_nanoseconds=(
            freeze["labels"]["wall_cap_seconds"] * 1_000_000_000),
        progress=_progress("dataset", started))
    publish_scientific_dataset(
        target, build, population_manifest=population)
    reopen_scientific_dataset(
        target, population_manifest=population,
        allowed_folds=("train", "calibration", "report", "provider-audit"))


def _training(args) -> None:
    _repo, root, freeze, _capacity, _packet, admission, population = \
        _context(args)
    dataset_root = root / "artifacts" / "dataset"
    target = root / "artifacts" / "training"
    manifest_raw, dataset_manifest = _read_canonical(
        dataset_root / "manifest.json", "dataset manifest")
    del manifest_raw
    consume_stage_attempt(
        root, stage="training", freeze_sha256=freeze["freeze_sha256"],
        admission_sha256=admission["admission_sha256"],
        inputs={"dataset_manifest_sha256":
                dataset_manifest["manifest_sha256"],
                "soft_deadline_seconds":
                    freeze["learner"]["soft_deadline_seconds"],
                "hard_wall_cap_seconds":
                    freeze["learner"]["hard_wall_cap_seconds"]})
    reopened_manifest, train_rows = reopen_scientific_dataset(
        dataset_root, population_manifest=population,
        allowed_folds=("train",))
    _calibration_manifest, calibration_rows = reopen_scientific_dataset(
        dataset_root, population_manifest=population,
        allowed_folds=("calibration",))
    started = time.monotonic_ns()
    build = train_eight_seed_cohort(
        freeze=freeze,
        dataset_manifest_sha256=reopened_manifest["manifest_sha256"],
        train_rows=train_rows, calibration_rows=calibration_rows,
        wall_budget_nanoseconds=(
            freeze["learner"]["soft_deadline_seconds"] * 1_000_000_000),
        progress=_progress("training", started))
    if time.monotonic_ns() - started \
            > freeze["learner"]["hard_wall_cap_seconds"] * 1_000_000_000:
        raise RuntimeError("scientific training hard wall cap exceeded")
    publish_training_build(target, build)
    reopen_training_build(target)


def _report(args) -> None:
    _repo, root, freeze, _capacity, _packet, admission, population = \
        _context(args)
    dataset_root = root / "artifacts" / "dataset"
    training_root = root / "artifacts" / "training"
    _training_raw, training_manifest = _read_canonical(
        training_root / "manifest.json", "training manifest")
    consume_stage_attempt(
        root, stage="report", freeze_sha256=freeze["freeze_sha256"],
        admission_sha256=admission["admission_sha256"],
        inputs={"training_manifest_sha256":
                training_manifest["manifest_sha256"],
                "report_wall_cap_seconds":
                    freeze["gates"]["report_wall_cap_seconds"]})
    started = time.monotonic_ns()
    run_open_report(
        root / "artifacts" / "terminal", freeze=freeze,
        population_manifest=population, dataset_root=dataset_root,
        training_root=training_root, progress=_progress("report", started))


def _verify(args) -> None:
    _repo, root, freeze, _capacity, _packet, admission, population = \
        _context(args)
    terminal_root = root / "artifacts" / "terminal"
    receipt_path = root / "artifacts" / "independent-verification.json"
    _terminal_raw, terminal = _read_canonical(
        terminal_root / "terminal.json", "terminal result")
    consume_stage_attempt(
        root, stage="independent-verification",
        freeze_sha256=freeze["freeze_sha256"],
        admission_sha256=admission["admission_sha256"],
        inputs={"terminal_sha256": terminal["terminal_sha256"],
                "wall_cap_seconds": freeze["gates"][
                    "independent_verification_wall_cap_seconds"],
                "workers": freeze["labels"]["workers"]})
    started = time.monotonic_ns()
    verification = verify_terminal_artifact(
        terminal_root, freeze=freeze, population_manifest=population,
        dataset_root=root / "artifacts" / "dataset",
        training_root=root / "artifacts" / "training",
        reconstruct_continuations=True,
        progress=_progress("independent-verification", started))
    body = {
        "schema": "world-afterstate-e3-e4-independent-verification-v0",
        **verification,
        "elapsed_nanoseconds": time.monotonic_ns() - started,
    }
    receipt = {**body, "receipt_sha256": hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()}
    _write_receipt(receipt_path, receipt)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("mode", choices=(
        "initialize", "generate-dataset", "train", "open-report",
        "verify-terminal"))
    value.add_argument("--root", required=True)
    value.add_argument("--population-root", required=True)
    value.add_argument("--expected-git", required=True)
    value.add_argument("--freeze")
    value.add_argument("--capacity")
    value.add_argument("--population-packet")
    value.add_argument("--review-commit")
    return value


def main() -> None:
    args = parser().parse_args()
    if args.mode == "initialize":
        if not all((args.freeze, args.capacity, args.population_packet,
                    args.review_commit)):
            raise RuntimeError("scientific initialization inputs missing")
        _initialize(args)
    elif any((args.freeze, args.capacity, args.population_packet,
              args.review_commit)):
        raise RuntimeError("scientific stage received initialization inputs")
    elif args.mode == "generate-dataset":
        _dataset(args)
    elif args.mode == "train":
        _training(args)
    elif args.mode == "open-report":
        _report(args)
    else:
        _verify(args)


if __name__ == "__main__":
    main()

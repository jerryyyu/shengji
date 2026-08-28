#!/usr/bin/env python3
"""Build or independently reconstruct one immutable E3/E4 freeze."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path


def _preimport_guard() -> None:
    """Refuse mutable source bytecode before importing any project package."""
    if not sys.flags.safe_path or not sys.dont_write_bytecode \
            or os.environ.get("PYTHONPATH") \
            or os.environ.get("SHENGJI_FAST") != "1" \
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise RuntimeError("experiment requires -P -B and strict environment")
    server = Path(__file__).resolve().parents[1]
    ignored_python = [
        path for root in (server / "shengji", server / "scripts")
        for path in root.rglob("*")
        if path.is_file() and (path.suffix == ".pyc"
                               or "__pycache__" in path.parts)]
    if ignored_python:
        raise RuntimeError("experiment source tree contains Python bytecode")


_preimport_guard()
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import torch

from shengji.ai import mcbot, registry
from shengji.engine import ballot, fast, legal, round as round_mod
from shengji.engine import combos
from shengji.rl import (
    world_afterstate, world_afterstate_checkpoint, world_afterstate_dataset,
    world_afterstate_admission,
    world_afterstate_controller, world_afterstate_controls,
    world_afterstate_evaluation,
    world_afterstate_experiment,
    world_afterstate_label, world_afterstate_model,
    world_afterstate_population, world_afterstate_population_packet,
    world_afterstate_population_builder, world_afterstate_sources,
    world_afterstate_scientific, world_afterstate_terminal,
    world_afterstate_terminal_controller,
    world_afterstate_training, world_afterstate_training_controller)
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_capacity import validate_capacity_receipt
from shengji.rl.world_afterstate_experiment import (
    EXPERIMENT_RUNTIME_KEYS, EXPERIMENT_SOURCE_KEYS, build_experiment_freeze,
    reviewed_teacher_binding, validate_experiment_freeze)


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True,
        text=True).stdout.strip()


def _source_paths() -> dict[str, Path]:
    native = getattr(fast, "_fast", None)
    if fast.HAVE_FAST is not True or native is None \
            or combos.decompose is not fast.decompose \
            or round_mod.Round.play is not native.round_play:
        raise RuntimeError("experiment requires the active compiled engine")
    paths = {
        "afterstate": Path(world_afterstate.__file__),
        "sources": Path(world_afterstate_sources.__file__),
        "label": Path(world_afterstate_label.__file__),
        "model": Path(world_afterstate_model.__file__),
        "population": Path(world_afterstate_population.__file__),
        "population_packet": Path(world_afterstate_population_packet.__file__),
        "population_builder": Path(
            world_afterstate_population_builder.__file__),
        "dataset": Path(world_afterstate_dataset.__file__),
        "controller": Path(world_afterstate_controller.__file__),
        "training": Path(world_afterstate_training.__file__),
        "training_controller": Path(
            world_afterstate_training_controller.__file__),
        "checkpoint": Path(world_afterstate_checkpoint.__file__),
        "evaluation": Path(world_afterstate_evaluation.__file__),
        "controls": Path(world_afterstate_controls.__file__),
        "terminal": Path(world_afterstate_terminal.__file__),
        "terminal_controller": Path(
            world_afterstate_terminal_controller.__file__),
        "admission": Path(world_afterstate_admission.__file__),
        "scientific_controller": Path(world_afterstate_scientific.__file__),
        "experiment": Path(world_afterstate_experiment.__file__),
        "launcher": Path(__file__),
        "population_launcher": Path(__file__).with_name(
            "world_afterstate_v0_population.py"),
        "scientific_launcher": Path(__file__).with_name(
            "world_afterstate_v0_run.py"),
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
        raise RuntimeError("experiment source population drift")
    return paths


def _strict_live(repo: Path, expected_git: str,
                 capacity: dict) -> tuple[dict[str, str], dict]:
    if _git(repo, "rev-parse", "HEAD") != expected_git \
            or _git(repo, "status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("experiment requires the exact clean source head")
    runtime = capacity["runtime"]
    python = Path(sys.executable).resolve()
    native = Path(fast._fast.__file__).resolve()
    router = Path(fast.__file__).resolve()
    if os.uname().nodename != runtime["host"] \
            or platform.platform() != runtime["platform"] \
            or sys.version.split()[0] != runtime["python"] \
            or str(torch.__version__) != runtime["torch"] \
            or _sha_file(python) != runtime["python_executable_sha256"] \
            or _sha_file(native) != runtime["native_sha256"] \
            or _sha_file(router) != runtime["fast_router_sha256"]:
        raise RuntimeError("experiment runtime differs from capacity receipt")
    observed_runtime = {
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
        "native_path": str(native),
        "native_sha256": _sha_file(native),
        "compiled_engine_active": True,
        "safe_path": True,
        "dont_write_bytecode": True,
        "pythonpath_absent": True,
    }
    if set(observed_runtime) != EXPERIMENT_RUNTIME_KEYS:
        raise RuntimeError("experiment runtime population drift")
    return ({name: _sha_file(path)
             for name, path in sorted(_source_paths().items())},
            observed_runtime)


def _read_canonical(path: Path, label: str) -> tuple[bytes, dict]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError(f"{label} is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise RuntimeError(f"{label} is not canonical JSON")
    return raw, value


def _derive(args: argparse.Namespace) -> tuple[bytes, dict]:
    repo = Path(__file__).resolve().parents[2]
    capacity_raw, capacity = _read_canonical(
        Path(args.capacity), "capacity receipt")
    validate_capacity_receipt(capacity)
    population_packet_raw, _population_packet = _read_canonical(
        Path(args.population_packet), "population packet")
    sources, runtime = _strict_live(repo, args.expected_git, capacity)
    sol_raw, _ = _read_canonical(Path(args.pt_sol), "PT-Sol report")
    luna_raw, _ = _read_canonical(Path(args.pt_luna), "PT-Luna report")
    sol = reviewed_teacher_binding(sol_raw, model="gpt-5.6-sol")
    luna = reviewed_teacher_binding(luna_raw, model="gpt-5.6-luna")
    freeze = build_experiment_freeze(
        capacity_raw, population_packet_raw, source_git=args.expected_git,
        experiment_source_sha256s=sources,
        experiment_runtime=runtime,
        pt_sol0_external_sha256=sol["external_sha256"],
        pt_sol0_report_sha256=sol["report_sha256"],
        pt_sol0_execution_git=sol["execution_git"],
        pt_luna0_external_sha256=luna["external_sha256"],
        pt_luna0_report_sha256=luna["report_sha256"],
        pt_luna0_execution_git=luna["execution_git"])
    validate_experiment_freeze(
        freeze, capacity_raw, population_packet_raw)
    return canonical_json_bytes(freeze), freeze


def _publish(path: Path, raw: bytes) -> None:
    target = path.resolve()
    partial = target.with_name(f".{target.name}.partial")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink() \
            or partial.exists() or partial.is_symlink():
        raise FileExistsError("experiment freeze namespace is occupied")
    with partial.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(partial, 0o400)
    os.link(partial, target)
    partial.unlink()
    directory = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("mode", choices=("build-freeze", "verify-freeze"))
    value.add_argument("--capacity", required=True)
    value.add_argument("--population-packet", required=True)
    value.add_argument("--pt-sol", required=True)
    value.add_argument("--pt-luna", required=True)
    value.add_argument("--expected-git", required=True)
    value.add_argument("--out", required=True)
    return value


def main() -> None:
    args = parser().parse_args()
    raw, _ = _derive(args)
    target = Path(args.out)
    if args.mode == "build-freeze":
        _publish(target, raw)
    else:
        observed = target.read_bytes()
        if observed != raw:
            raise RuntimeError("experiment freeze reconstruction drift")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build or independently reconstruct the reviewed Value V1 P1 freeze."""

from __future__ import annotations

import sys


if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("Value V1 experiment requires Python -P -B")

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
        raise RuntimeError("Value V1 experiment refuses PYTHONPATH")
    try:
        tracked_raw = subprocess.run(
            ("git", "ls-files", "-z"), cwd=REPO, check=True,
            capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("Value V1 experiment Git probe failed") from exc
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
                    "Value V1 experiment refuses bytecode shadows")
            if path.suffix in {".so", ".pyd", ".dylib"} \
                    and path.parent == SERVER / "shengji" / "engine" \
                    and path.name.startswith("_fast."):
                natives.append(path)
            elif relative not in tracked:
                raise RuntimeError(
                    "Value V1 experiment refuses untracked import shadows")
    if len(natives) != 1:
        raise RuntimeError("Value V1 experiment native population drift")


_refuse_import_shadows()
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

import torch  # noqa: E402

from shengji.engine import (  # noqa: E402
    ballot, cards, combos, fast, legal, round as round_mod)
from shengji.rl import (  # noqa: E402
    belief_contract, world_afterstate, world_afterstate_dataset,
    world_afterstate_model, world_afterstate_population,
    world_afterstate_v1, world_afterstate_v1_admission,
    world_afterstate_v1_audit_controller, world_afterstate_v1_capacity,
    world_afterstate_v1_checkpoint, world_afterstate_v1_controls,
    world_afterstate_v1_dataset, world_afterstate_v1_evaluation,
    world_afterstate_v1_execution, world_afterstate_v1_experiment,
    world_afterstate_v1_inference, world_afterstate_v1_model,
    world_afterstate_v1_pipeline, world_afterstate_v1_result,
    world_afterstate_v1_schedule, world_afterstate_v1_scientific,
    world_afterstate_v1_training, world_afterstate_v1_training_controller)
from shengji.rl.belief_contract import canonical_json_bytes  # noqa: E402
from shengji.rl.world_afterstate_v1_capacity import (  # noqa: E402
    CapacityBuildV1, _runtime, reopen_capacity_directory)
from shengji.rl.world_afterstate_v1_admission import (  # noqa: E402
    authenticate_capacity_operator_reentry,
    authenticate_capacity_operator_reentry_v2)
from shengji.rl.world_afterstate_v1_experiment import (  # noqa: E402
    SOURCE_KEYS, SOURCE_PATHS, build_experiment_freeze,
    validate_experiment_freeze)


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=REPO, check=True,
        capture_output=True, text=True).stdout.strip()


def _source_paths() -> dict[str, Path]:
    native = getattr(fast, "_fast", None)
    if fast.HAVE_FAST is not True or native is None \
            or combos.decompose is not fast.decompose \
            or round_mod.Round.play is not native.round_play:
        raise RuntimeError("Value V1 experiment requires compiled engine")
    paths = {key: REPO / relative
             for key, relative in SOURCE_PATHS.items()}
    if set(paths) != set(SOURCE_KEYS) \
            or any(path.is_symlink() or not path.is_file()
                   for path in paths.values()):
        raise RuntimeError("Value V1 experiment source population drift")
    return paths


def _strict_live(expected_git: str, capacity: CapacityBuildV1):
    if _git("rev-parse", "HEAD") != expected_git \
            or _git("status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("Value V1 experiment requires exact clean head")
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(capacity.receipt["selection"]["torch_threads"])
    runtime = _runtime()
    sources = {name: _sha_file(path)
               for name, path in sorted(_source_paths().items())}
    return sources, runtime


def _derive(args):
    capacity = reopen_capacity_directory(Path(args.capacity))
    sources, runtime = _strict_live(args.expected_git, capacity)
    capacity_operator_reentry = authenticate_capacity_operator_reentry(
        repo=REPO, review_commit=args.capacity_operator_reentry_commit)
    capacity_operator_reentry_v2 = authenticate_capacity_operator_reentry_v2(
        repo=REPO, review_commit=args.capacity_operator_reentry_v2_commit)
    freeze = build_experiment_freeze(
        capacity, source_git=args.expected_git,
        source_sha256s=sources, experiment_runtime=runtime,
        scientific_root=str(args.scientific_root),
        capacity_operator_reentry=capacity_operator_reentry,
        capacity_operator_reentry_v2=capacity_operator_reentry_v2)
    validate_experiment_freeze(freeze, capacity)
    return canonical_json_bytes(freeze), freeze


def _publish(path: Path, raw: bytes) -> None:
    target = path.resolve()
    partial = target.with_name(f".{target.name}.partial")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink() \
            or partial.exists() or partial.is_symlink():
        raise RuntimeError("Value V1 experiment freeze namespace occupied")
    with partial.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(partial, 0o400)
    os.rename(partial, target)
    descriptor = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("mode", choices=("build-freeze", "verify-freeze"))
    value.add_argument("--capacity", type=Path, required=True)
    value.add_argument("--capacity-operator-reentry-commit", required=True)
    value.add_argument("--capacity-operator-reentry-v2-commit", required=True)
    value.add_argument("--expected-git", required=True)
    value.add_argument("--scientific-root", type=Path, required=True)
    value.add_argument("--out", type=Path, required=True)
    return value


def main() -> None:
    args = parser().parse_args()
    raw, _freeze = _derive(args)
    if args.mode == "build-freeze":
        _publish(args.out, raw)
    elif args.out.read_bytes() != raw:
        raise RuntimeError("Value V1 experiment freeze reconstruction drift")


if __name__ == "__main__":
    main()

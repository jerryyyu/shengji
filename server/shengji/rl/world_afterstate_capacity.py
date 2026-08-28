"""Outcome-blind capacity mechanics for the V0 afterstate experiment.

The receipt produced here can size a later immutable experiment.  It cannot
select a model by prediction quality: fixtures are out-of-namespace mechanics
states, no continuation is run, and the synthetic backward objective is never
reported.  Every authority remains false.
"""

from __future__ import annotations

import hashlib
import os
import platform
import random
import resource
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import torch

from ..ai.registry import make_bot
from ..engine.cards import RANKS
from ..engine.round import Round
from .belief_contract import canonical_json_bytes
from .world_afterstate import (WorldAfterstateError, build_afterstate_audit,
                               build_afterstate_tensors, root_replay)
from .world_afterstate_model import (CAPACITY_SHAPES,
                                     WorldAfterstateShapeV0,
                                     new_world_afterstate_model)


CAPACITY_SCHEMA = "world-afterstate-capacity-receipt-v0"
CAPACITY_FIXTURE_SCHEMA = "world-afterstate-capacity-fixture-v0"
CAPACITY_SEED_START = 883_700_000
AUTHORITY = {
    "population_freeze_authorized": False,
    "continuation_authorized": False,
    "training_authorized": False,
    "test_opening_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "deployment_authorized": False,
}


class WorldAfterstateCapacityError(WorldAfterstateError):
    """A capacity fixture, runtime, measurement, or receipt drifted."""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True,
        text=True).stdout.strip()


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _natural_capacity_audit(seed: int, trump_rank: str,
                            initial_banker: int | None,
                            target_plays: int) -> dict[str, Any]:
    rnd = Round(trump_rank, initial_banker, random.Random(seed))
    bots = [make_bot("smart", seed=seed + 10_000 + seat)
            for seat in range(4)]
    declarations = []
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bots[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({
                "stage": "deal", "deal_pos": rnd._deal_pos,
                "seat": seat, "cards": list(cards),
            })
    for seat in range(4):
        cards = bots[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({
                "stage": "final", "deal_pos": rnd._deal_pos,
                "seat": seat, "cards": list(cards),
            })
    rnd.finalize_declare()
    if rnd.banker is None:
        raise WorldAfterstateCapacityError("fixture did not determine banker")
    burial = bots[rnd.banker].decide_bury(rnd, rnd.banker)
    rnd.bury(rnd.banker, burial)
    plays = []
    latest = None
    while rnd.phase == "play":
        actor = rnd.turn
        if actor is None:
            raise WorldAfterstateCapacityError("fixture play has no actor")
        action = bots[actor].decide_play(rnd, actor)
        latest = (
            root_replay(
                deal_seed=seed, initial_banker=initial_banker,
                trump_rank=trump_rank, declarations=declarations,
                buried=burial, plays=plays, root_seat=actor),
            {seat: list(rnd.hands[seat]) for seat in range(4)},
            list(rnd.buried), list(action),
        )
        if len(plays) >= target_plays:
            break
        rnd.play(actor, action)
        plays.append({"seat": actor, "cards": list(action)})
    if latest is None:
        raise WorldAfterstateCapacityError("fixture has no play decision")
    return build_afterstate_audit(*latest)


def build_capacity_fixtures(count: int) -> tuple[dict[str, Any], ...]:
    """Build deterministic, outcome-unopened mechanics rows across all ranks."""
    if isinstance(count, bool) or not isinstance(count, int) \
            or not 13 <= count <= 256:
        raise WorldAfterstateCapacityError(
            "capacity fixture count must be between 13 and 256")
    rows = []
    targets = (0, 1, 3, 7, 12, 20, 32, 48)
    for index in range(count):
        rows.append(_natural_capacity_audit(
            CAPACITY_SEED_START + index, RANKS[index % len(RANKS)],
            None if index % 5 == 0 else index % 4,
            targets[index % len(targets)]))
    return tuple(rows)


def _tensor_digest(audit: Mapping[str, Any]) -> str:
    tensors = build_afterstate_tensors(audit)
    digest = hashlib.sha256()
    for value in (tensors.public, tensors.history, tensors.world,
                  tensors.perspective):
        digest.update(str(value.shape).encode("ascii"))
        digest.update(value.astype("<f4", copy=False).tobytes())
    return digest.hexdigest()


def _tensor_worker(payload: tuple[dict[str, Any], int]) -> str:
    audit, _occurrence = payload
    return _tensor_digest(audit)


def _worker_measurement(
        audits: Sequence[dict[str, Any]], workers: int,
        repetitions: int) -> dict[str, Any]:
    tasks = [(audit, occurrence) for occurrence in range(repetitions)
             for audit in audits]
    started = time.perf_counter_ns()
    if workers == 1:
        digests = [_tensor_worker(task) for task in tasks]
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            digests = list(executor.map(_tensor_worker, tasks, chunksize=1))
    elapsed = time.perf_counter_ns() - started
    if elapsed <= 0 or len(digests) != len(tasks):
        raise WorldAfterstateCapacityError(
            "tensor worker measurement did not complete")
    expected = [_tensor_digest(audit) for audit in audits]
    for occurrence in range(repetitions):
        if digests[occurrence * len(audits):(occurrence + 1) * len(audits)] \
                != expected:
            raise WorldAfterstateCapacityError(
                "parallel tensor bytes differ from serial bytes")
    return {
        "workers": workers,
        "tasks": len(tasks),
        "elapsed_nanoseconds": elapsed,
        "tasks_per_second_ppm": len(tasks) * 10**15 // elapsed,
        "output_population_sha256": _sha256_bytes(
            canonical_json_bytes({"digests": digests})),
    }


def _device(name: str) -> torch.device:
    if name == "auto":
        if torch.cuda.is_available():
            name = "cuda"
        elif torch.backends.mps.is_available():
            name = "mps"
        else:
            name = "cpu"
    if name not in ("cpu", "cuda", "mps"):
        raise WorldAfterstateCapacityError("unsupported capacity device")
    if name == "cuda" and not torch.cuda.is_available():
        raise WorldAfterstateCapacityError("CUDA capacity device unavailable")
    if name == "mps" and not torch.backends.mps.is_available():
        raise WorldAfterstateCapacityError("MPS capacity device unavailable")
    return torch.device(name)


def _synchronize(device: torch.device) -> None:
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    elif device.type == "mps":
        torch.mps.synchronize()


def _model_measurement(
        audits: Sequence[dict[str, Any]], shape_name: str,
        shape: WorldAfterstateShapeV0, batch_size: int, steps: int,
        device: torch.device) -> dict[str, Any]:
    tensors = [build_afterstate_tensors(audit) for audit in audits]
    selected = [tensors[index % len(tensors)] for index in range(batch_size)]
    max_events = max(len(value.history) for value in selected)
    public = torch.as_tensor(
        np.stack([value.public for value in selected]),
        dtype=torch.float32, device=device)
    history = torch.zeros(
        (batch_size, max_events, selected[0].history.shape[1]),
        dtype=torch.float32, device=device)
    for index, value in enumerate(selected):
        if len(value.history):
            history[index, :len(value.history)] = torch.as_tensor(
                value.history, dtype=torch.float32, device=device)
    lengths = torch.as_tensor(
        [len(value.history) for value in selected], dtype=torch.long,
        device=device)
    world = torch.as_tensor(
        np.stack([value.world for value in selected]),
        dtype=torch.float32, device=device)
    perspective = torch.as_tensor(
        np.stack([value.perspective for value in selected]),
        dtype=torch.float32, device=device)
    model = new_world_afterstate_model(902_001, shape).to(device)
    model.train()
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    for _ in range(2):
        model.zero_grad(set_to_none=True)
        logits = model(public, history, lengths, world, perspective)
        logits.square().mean().backward()
    _synchronize(device)
    started = time.perf_counter_ns()
    for _ in range(steps):
        model.zero_grad(set_to_none=True)
        logits = model(public, history, lengths, world, perspective)
        # Mechanics-only objective. Its value and the logits are discarded.
        logits.square().mean().backward()
    _synchronize(device)
    elapsed = time.perf_counter_ns() - started
    if elapsed <= 0:
        raise WorldAfterstateCapacityError("model capacity clock did not advance")
    result = {
        "shape": shape_name,
        "shape_values": {
            "public_hidden": shape.public_hidden,
            "history_hidden": shape.history_hidden,
            "world_hidden": shape.world_hidden,
            "perspective_hidden": shape.perspective_hidden,
            "head_hidden": shape.head_hidden,
        },
        "batch_size": batch_size,
        "steps": steps,
        "parameter_count": sum(parameter.numel()
                               for parameter in model.parameters()),
        "elapsed_nanoseconds": elapsed,
        "examples_per_second_ppm": batch_size * steps * 10**15 // elapsed,
    }
    if device.type == "cuda":
        result["device_peak_allocated_bytes"] = int(
            torch.cuda.max_memory_allocated(device))
    elif device.type == "mps":
        result["device_current_allocated_bytes"] = int(
            torch.mps.current_allocated_memory())
        result["device_driver_allocated_bytes"] = int(
            torch.mps.driver_allocated_memory())
    return result


def run_capacity(
        *, repo: Path, expected_git: str, fixture_count: int,
        worker_counts: Sequence[int], worker_repetitions: int,
        batch_sizes: Sequence[int], model_steps: int, device_name: str) \
        -> dict[str, Any]:
    """Run one score-free resource measurement and return its receipt."""
    repo = repo.resolve()
    head = _git(repo, "rev-parse", "HEAD")
    if head != expected_git:
        raise WorldAfterstateCapacityError("capacity Git head drift")
    if _git(repo, "status", "--porcelain"):
        raise WorldAfterstateCapacityError("capacity refuses a dirty tree")
    if type(worker_counts) not in (list, tuple) or not worker_counts \
            or any(isinstance(value, bool) or not isinstance(value, int)
                   or not 1 <= value <= 16 for value in worker_counts) \
            or len(set(worker_counts)) != len(worker_counts):
        raise WorldAfterstateCapacityError("capacity worker schedule drift")
    if type(batch_sizes) not in (list, tuple) or not batch_sizes \
            or any(isinstance(value, bool) or not isinstance(value, int)
                   or not 1 <= value <= 4096 for value in batch_sizes):
        raise WorldAfterstateCapacityError("capacity batch schedule drift")
    if isinstance(worker_repetitions, bool) \
            or not isinstance(worker_repetitions, int) \
            or not 1 <= worker_repetitions <= 64 \
            or isinstance(model_steps, bool) or not isinstance(model_steps, int) \
            or not 1 <= model_steps <= 1000:
        raise WorldAfterstateCapacityError("capacity repetition schedule drift")
    device = _device(device_name)
    fixtures_started = time.perf_counter_ns()
    audits = build_capacity_fixtures(fixture_count)
    fixture_elapsed = time.perf_counter_ns() - fixtures_started
    ranks = Counter(
        audit["source_state"]["trump_rank"] for audit in audits)
    if set(ranks) != set(RANKS):
        raise WorldAfterstateCapacityError(
            "capacity fixtures do not cover every trump rank")
    audit_bytes = [canonical_json_bytes(audit) for audit in audits]
    population_sha = _sha256_bytes(canonical_json_bytes({
        "schema": CAPACITY_FIXTURE_SCHEMA,
        "audit_sha256s": [_sha256_bytes(raw) for raw in audit_bytes],
    }))
    tensor_scaling = [
        _worker_measurement(audits, workers, worker_repetitions)
        for workers in worker_counts
    ]
    model_measurements = [
        _model_measurement(
            audits, shape_name, shape, batch_size, model_steps, device)
        for shape_name, shape in CAPACITY_SHAPES.items()
        for batch_size in batch_sizes
    ]
    source_root = Path(__file__).resolve().parents[1]
    source_files = {
        "capacity": Path(__file__).resolve(),
        "afterstate": Path(__file__).resolve().with_name(
            "world_afterstate.py"),
        "model": Path(__file__).resolve().with_name(
            "world_afterstate_model.py"),
        "engine_round": source_root / "engine" / "round.py",
        "engine_legal": source_root / "engine" / "legal.py",
    }
    return {
        "schema": CAPACITY_SCHEMA,
        "git": head,
        "outcome_blind": True,
        "evidence_artifact": False,
        "runtime": {
            "host": platform.node(),
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "torch": str(torch.__version__),
            "device": str(device),
            "cpu_count": os.cpu_count(),
            "torch_threads": torch.get_num_threads(),
            "torch_interop_threads": torch.get_num_interop_threads(),
            "max_rss_raw": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
            "max_rss_unit": "bytes-on-macos-kibibytes-on-linux",
        },
        "source_sha256s": {
            name: _sha256_file(path) for name, path in source_files.items()
        },
        "fixtures": {
            "schema": CAPACITY_FIXTURE_SCHEMA,
            "seed_start": CAPACITY_SEED_START,
            "count": len(audits),
            "trump_rank_counts": dict(sorted(ranks.items())),
            "population_sha256": population_sha,
            "generation_elapsed_nanoseconds": fixture_elapsed,
            "minimum_audit_bytes": min(map(len, audit_bytes)),
            "maximum_audit_bytes": max(map(len, audit_bytes)),
            "total_audit_bytes": sum(map(len, audit_bytes)),
        },
        "tensor_worker_scaling": tensor_scaling,
        "model_measurements": model_measurements,
        "authority": dict(AUTHORITY),
    }


def validate_capacity_receipt(value: Mapping[str, Any]) -> None:
    if type(value) is not dict or value.get("schema") != CAPACITY_SCHEMA:
        raise WorldAfterstateCapacityError("capacity receipt schema drift")
    required = {
        "schema", "git", "outcome_blind", "evidence_artifact", "runtime",
        "source_sha256s", "fixtures", "tensor_worker_scaling",
        "model_measurements", "authority",
    }
    if set(value) != required:
        raise WorldAfterstateCapacityError(
            "capacity receipt field population drift")
    if value["outcome_blind"] is not True \
            or value["evidence_artifact"] is not False \
            or value["authority"] != AUTHORITY:
        raise WorldAfterstateCapacityError("capacity authority drift")
    if type(value["git"]) is not str or len(value["git"]) != 40 \
            or any(char not in "0123456789abcdef" for char in value["git"]):
        raise WorldAfterstateCapacityError("capacity Git identity drift")
    if type(value["source_sha256s"]) is not dict \
            or set(value["source_sha256s"]) != {
                "capacity", "afterstate", "model", "engine_round",
                "engine_legal"} \
            or any(type(digest) is not str or len(digest) != 64
                   or any(char not in "0123456789abcdef" for char in digest)
                   for digest in value["source_sha256s"].values()):
        raise WorldAfterstateCapacityError("capacity source identity drift")
    runtime = value["runtime"]
    if type(runtime) is not dict or set(runtime) != {
        "host", "platform", "python", "torch", "device", "cpu_count",
        "torch_threads", "torch_interop_threads", "max_rss_raw",
        "max_rss_unit"}:
        raise WorldAfterstateCapacityError("capacity runtime schema drift")
    for key in ("cpu_count", "torch_threads", "torch_interop_threads"):
        if isinstance(runtime[key], bool) or not isinstance(runtime[key], int) \
                or runtime[key] <= 0:
            raise WorldAfterstateCapacityError(
                "capacity runtime resource drift")
    fixtures = value["fixtures"]
    if type(fixtures) is not dict \
            or set(fixtures) != {
                "schema", "seed_start", "count", "trump_rank_counts",
                "population_sha256", "generation_elapsed_nanoseconds",
                "minimum_audit_bytes", "maximum_audit_bytes",
                "total_audit_bytes"} \
            or fixtures.get("schema") != CAPACITY_FIXTURE_SCHEMA \
            or set(fixtures.get("trump_rank_counts", {})) != set(RANKS) \
            or any(fixtures["trump_rank_counts"][rank] <= 0 for rank in RANKS):
        raise WorldAfterstateCapacityError(
            "capacity receipt trump-rank coverage drift")
    if sum(fixtures["trump_rank_counts"].values()) != fixtures["count"] \
            or fixtures["seed_start"] != CAPACITY_SEED_START \
            or any(isinstance(fixtures[key], bool)
                   or not isinstance(fixtures[key], int)
                   or fixtures[key] <= 0 for key in (
                       "count", "generation_elapsed_nanoseconds",
                       "minimum_audit_bytes", "maximum_audit_bytes",
                       "total_audit_bytes")) \
            or fixtures["minimum_audit_bytes"] \
            > fixtures["maximum_audit_bytes"] \
            or type(fixtures["population_sha256"]) is not str \
            or len(fixtures["population_sha256"]) != 64:
        raise WorldAfterstateCapacityError(
            "capacity receipt fixture accounting drift")
    workers = value["tensor_worker_scaling"]
    if type(workers) is not list or not workers:
        raise WorldAfterstateCapacityError("capacity worker receipt drift")
    for row in workers:
        if type(row) is not dict or set(row) != {
                "workers", "tasks", "elapsed_nanoseconds",
                "tasks_per_second_ppm", "output_population_sha256"} \
                or any(isinstance(row[key], bool)
                       or not isinstance(row[key], int) or row[key] <= 0
                       for key in ("workers", "tasks", "elapsed_nanoseconds",
                                   "tasks_per_second_ppm")) \
                or type(row["output_population_sha256"]) is not str \
                or len(row["output_population_sha256"]) != 64:
            raise WorldAfterstateCapacityError("capacity worker receipt drift")
    if len({row["workers"] for row in workers}) != len(workers):
        raise WorldAfterstateCapacityError("capacity worker identities duplicate")
    measurements = value["model_measurements"]
    if type(measurements) is not list or not measurements:
        raise WorldAfterstateCapacityError("capacity model receipt drift")
    base_keys = {
        "shape", "shape_values", "batch_size", "steps", "parameter_count",
        "elapsed_nanoseconds", "examples_per_second_ppm"}
    optional_keys = {
        "device_peak_allocated_bytes", "device_current_allocated_bytes",
        "device_driver_allocated_bytes"}
    for row in measurements:
        if type(row) is not dict or not base_keys <= set(row) \
                or not set(row) <= base_keys | optional_keys \
                or row["shape"] not in CAPACITY_SHAPES \
                or type(row["shape_values"]) is not dict \
                or any(isinstance(row[key], bool)
                       or not isinstance(row[key], int) or row[key] <= 0
                       for key in ("batch_size", "steps", "parameter_count",
                                   "elapsed_nanoseconds",
                                   "examples_per_second_ppm")):
            raise WorldAfterstateCapacityError("capacity model receipt drift")
    forbidden_tokens = ("attacker_points", "signed_level_category", "label",
                        "logit", "prediction", "proper_score")
    raw = canonical_json_bytes(dict(value)).decode("ascii")
    if any(token in raw for token in forbidden_tokens):
        raise WorldAfterstateCapacityError(
            "capacity receipt contains outcome-bearing vocabulary")

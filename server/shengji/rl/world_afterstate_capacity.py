"""Outcome-blind capacity mechanics for the V0 afterstate experiment.

The receipt produced here can size a later immutable experiment.  It cannot
select a model by prediction quality: fixtures are out-of-namespace mechanics
states, the one measured continuation discards its terminal result, and the
synthetic backward objective is never reported.  Every authority remains
false.
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
from ..engine import combos, fast
from ..engine.ballot import mc_ballot
from ..engine.cards import RANKS
from ..engine.round import Round
from ..teacher_v1 import action_key, ballot_problems
from .belief_contract import canonical_json_bytes
from .world_afterstate import (WorldAfterstateError, build_afterstate_audit,
                               build_afterstate_tensors,
                               materialize_complete_world,
                               replay_root_state, root_replay)
from .world_afterstate_label import (CONTINUATION_POLICY,
                                     continuation_identity,
                                     run_afterstate_continuation)
from .world_afterstate_model import (CAPACITY_SHAPES,
                                     WorldAfterstateShapeV0,
                                     new_world_afterstate_model)


CAPACITY_SCHEMA = "world-afterstate-capacity-receipt-v0"
CAPACITY_FIXTURE_SCHEMA = "world-afterstate-capacity-fixture-v0"
CAPACITY_SCHEDULE_SCHEMA = "world-afterstate-capacity-schedule-v0"
CAPACITY_SEED_START = 883_700_000
PRODUCTION_BALLOT_POLICY = "mc-s0-report-lcb"
CONTINUATION_FIXTURE_INDEX = 0
REQUIRED_ENVIRONMENT = {
    "SHENGJI_FAST": "1",
    "SHENGJI_REQUIRE_VOIDS": "1",
}
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


def _strict_runtime_binding() -> dict[str, Any]:
    """Bind the interpreter and the native engine that is actually routed."""
    observed = {key: os.environ.get(key) for key in REQUIRED_ENVIRONMENT}
    if observed != REQUIRED_ENVIRONMENT:
        raise WorldAfterstateCapacityError(
            "capacity requires the strict compiled environment")
    if not _safe_python_runtime():
        raise WorldAfterstateCapacityError(
            "capacity requires -P -B and no PYTHONPATH")
    native = getattr(fast, "_fast", None)
    native_path_raw = getattr(native, "__file__", None)
    if fast.HAVE_FAST is not True or native is None or not native_path_raw \
            or combos.decompose is not fast.decompose \
            or Round.play is not native.round_play:
        raise WorldAfterstateCapacityError(
            "capacity compiled engine is not actively routed")
    python_path = Path(sys.executable).resolve()
    native_path = Path(native_path_raw).resolve()
    router_path = Path(fast.__file__).resolve()
    if any(path.is_symlink() or not path.is_file()
           for path in (python_path, native_path, router_path)):
        raise WorldAfterstateCapacityError("capacity runtime binary drift")
    return {
        "environment": dict(REQUIRED_ENVIRONMENT),
        "python_executable": str(python_path),
        "python_executable_sha256": _sha256_file(python_path),
        "fast_router_path": str(router_path),
        "fast_router_sha256": _sha256_file(router_path),
        "native_path": str(native_path),
        "native_sha256": _sha256_file(native_path),
        "compiled_engine_active": True,
        "safe_path": True,
        "dont_write_bytecode": True,
        "pythonpath_absent": True,
    }


def _safe_python_runtime() -> bool:
    return bool(sys.flags.safe_path and sys.dont_write_bytecode
                and not os.environ.get("PYTHONPATH"))


def _capacity_memory_snapshot(
        *, proc_cgroup: Path = Path("/proc/self/cgroup"),
        cgroup_root: Path = Path("/sys/fs/cgroup")) -> dict[str, Any]:
    """Read the aggregate cgroup-v2 memory counters for this process tree.

    Perf capacity runs execute inside a fresh systemd unit, so this peak
    includes the parent, every tensor worker, and the model process.  A
    per-process RSS estimate would miss the exact failure mode this receipt is
    meant to size.
    """
    try:
        rows = proc_cgroup.read_text().splitlines()
    except OSError as exc:
        raise WorldAfterstateCapacityError(
            "capacity requires Linux cgroup-v2 memory accounting") from exc
    unified = [row.split(":", 2)[2] for row in rows
               if row.startswith("0::")]
    if len(unified) != 1:
        raise WorldAfterstateCapacityError(
            "capacity requires one unified cgroup-v2 path")
    root = cgroup_root / unified[0].lstrip("/")
    current_path = root / "memory.current"
    peak_path = root / "memory.peak"
    try:
        current = int(current_path.read_text().strip())
        peak = int(peak_path.read_text().strip())
    except (OSError, ValueError) as exc:
        raise WorldAfterstateCapacityError(
            "capacity cgroup-v2 memory counters are unavailable") from exc
    if current < 0 or peak <= 0 or peak < current:
        raise WorldAfterstateCapacityError(
            "capacity cgroup-v2 memory counters drifted")
    return {
        "method": "linux-cgroup-v2-memory.peak",
        "path": str(root),
        "current_bytes": current,
        "peak_bytes": peak,
    }


def _distribution(values: Sequence[int]) -> dict[str, Any]:
    if not values or any(isinstance(value, bool) or not isinstance(value, int)
                         or value <= 0 for value in values):
        raise WorldAfterstateCapacityError(
            "capacity distribution population drift")
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "minimum": ordered[0],
        "median_lower": ordered[(len(ordered) - 1) // 2],
        "maximum": ordered[-1],
        "total": sum(ordered),
    }


def _validate_distribution_record(value: object) -> None:
    if type(value) is not dict or set(value) != {
            "count", "minimum", "median_lower", "maximum", "total"} \
            or any(isinstance(value[key], bool)
                   or not isinstance(value[key], int) or value[key] <= 0
                   for key in value) \
            or not value["minimum"] <= value["median_lower"] \
            <= value["maximum"] \
            or value["total"] < value["count"] * value["minimum"] \
            or value["total"] > value["count"] * value["maximum"]:
        raise WorldAfterstateCapacityError(
            "capacity distribution receipt drift")


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


def _fixture_world(audit: Mapping[str, Any]) \
        -> tuple[Round, int, dict[int, list[str]], list[str]]:
    source = audit.get("source_state")
    world_payload = audit.get("complete_world_pre_action")
    root_seat = audit.get("root_seat")
    if type(source) is not dict or type(world_payload) is not dict \
            or set(world_payload) != {"hands", "buried"} \
            or type(world_payload["hands"]) is not dict \
            or set(world_payload["hands"]) != {"0", "1", "2", "3"} \
            or isinstance(root_seat, bool) or not isinstance(root_seat, int):
        raise WorldAfterstateCapacityError(
            "capacity fixture complete-world schema drift")
    rnd = replay_root_state(source)
    hands = {seat: list(world_payload["hands"][str(seat)])
             for seat in range(4)}
    buried = list(world_payload["buried"])
    materialize_complete_world(rnd, root_seat, hands, buried)
    return rnd, root_seat, hands, buried


def _composed_measurement(
        audits: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Measure the complete mechanical path used before model training.

    This covers public-state replay, the exact production ballot, strict
    complete-world materialization, engine application of every candidate,
    and one real actor-visible continuation.  The continuation's terminal
    result is deliberately discarded before this outcome-blind receipt is
    built.
    """
    if not audits or CONTINUATION_FIXTURE_INDEX >= len(audits):
        raise WorldAfterstateCapacityError(
            "capacity composed fixture population drift")
    started_wall = time.perf_counter_ns()
    started_cpu = time.process_time_ns()
    replay_wall = 0
    ballot_wall = 0
    materialization_wall = 0
    candidate_counts: list[int] = []
    candidate_byte_counts: list[int] = []
    world_row_byte_counts: list[int] = []
    candidate_digests: list[str] = []
    world_row_digests: list[str] = []
    materialization_attempts = 0
    materialization_accepts = 0
    ballot_digest: str | None = None
    continuation_audit: dict[str, Any] | None = None
    for index, audit in enumerate(audits):
        phase_started = time.perf_counter_ns()
        rnd, seat, hands, buried = _fixture_world(audit)
        replay_wall += time.perf_counter_ns() - phase_started
        materialization_attempts += 1
        materialization_accepts += 1

        phase_started = time.perf_counter_ns()
        policy = make_bot(PRODUCTION_BALLOT_POLICY,
                          seed=CAPACITY_SEED_START + 100_000 + index)
        candidates = [list(action_key(action))
                      for action in policy._candidates(rnd, seat)]
        problems = ballot_problems(rnd, seat, candidates)
        if problems:
            raise WorldAfterstateCapacityError(
                "capacity production ballot refused: " + "; ".join(problems))
        current_digest = mc_ballot(policy).digest
        if ballot_digest is None:
            ballot_digest = current_digest
        elif current_digest != ballot_digest:
            raise WorldAfterstateCapacityError(
                "capacity production ballot identity drift")
        ballot_wall += time.perf_counter_ns() - phase_started
        candidate_counts.append(len(candidates))
        candidate_raw = canonical_json_bytes({
            "fixture": index,
            "candidates": candidates,
        })
        candidate_byte_counts.append(len(candidate_raw))
        candidate_digests.append(_sha256_bytes(candidate_raw))

        phase_started = time.perf_counter_ns()
        for candidate_index, candidate in enumerate(candidates):
            materialization_attempts += 1
            row = build_afterstate_audit(
                audit["source_state"], hands, buried, candidate)
            materialization_accepts += 1
            if index == CONTINUATION_FIXTURE_INDEX \
                    and candidate_index == 0:
                continuation_audit = row
            raw = canonical_json_bytes(row)
            world_row_byte_counts.append(len(raw))
            world_row_digests.append(_sha256_bytes(raw))
        materialization_wall += time.perf_counter_ns() - phase_started
    if ballot_digest is None or continuation_audit is None \
            or materialization_attempts == 0 \
            or materialization_accepts != materialization_attempts:
        raise WorldAfterstateCapacityError(
            "capacity strict world materialization underfilled")

    identity = continuation_identity(
        experiment_id="world-afterstate-v0-capacity",
        state_group_id=(
            f"fixture-{CONTINUATION_FIXTURE_INDEX:03d}"),
        fold="score-free-capacity", world_occurrence=0, replicate=0)
    continuation_wall_started = time.perf_counter_ns()
    continuation_cpu_started = time.process_time_ns()
    continuation = run_afterstate_continuation(continuation_audit, identity)
    continuation_wall = time.perf_counter_ns() - continuation_wall_started
    continuation_cpu = time.process_time_ns() - continuation_cpu_started
    terminal = continuation.get("terminal_state", {})
    public = terminal.get("public", {}) if type(terminal) is dict else {}
    if public.get("phase") != "round_end" \
            or continuation.get("continuation_decisions", 0) <= 0:
        raise WorldAfterstateCapacityError(
            "capacity complete continuation did not terminate")
    if replay_wall <= 0 or ballot_wall <= 0 or materialization_wall <= 0 \
            or continuation_wall <= 0 or continuation_cpu <= 0:
        raise WorldAfterstateCapacityError(
            "capacity composed clock did not advance")
    result = {
        "production_ballot_policy": PRODUCTION_BALLOT_POLICY,
        "production_ballot_digest": ballot_digest,
        "protected_incumbent_index": 0,
        "fixture_count": len(audits),
        "state_reconstruction_elapsed_nanoseconds": replay_wall,
        "state_reconstruction_per_second_ppm": (
            len(audits) * 10**15 // replay_wall),
        "ballot_elapsed_nanoseconds": ballot_wall,
        "ballots_per_second_ppm": len(audits) * 10**15 // ballot_wall,
        "world_materialization_elapsed_nanoseconds": materialization_wall,
        "world_rows_per_second_ppm": (
            len(world_row_byte_counts) * 10**15 // materialization_wall),
        "candidate_count_distribution": _distribution(candidate_counts),
        "candidate_bytes_distribution": _distribution(candidate_byte_counts),
        "world_row_bytes_distribution": _distribution(world_row_byte_counts),
        "candidate_population_sha256": _sha256_bytes(
            canonical_json_bytes({"sha256s": candidate_digests})),
        "world_row_population_sha256": _sha256_bytes(
            canonical_json_bytes({"sha256s": world_row_digests})),
        "strict_world_materialization": {
            "attempts": materialization_attempts,
            "accepted": materialization_accepts,
            "failed": materialization_attempts - materialization_accepts,
            "accepted_rate_ppm": (
                materialization_accepts * 1_000_000
                // materialization_attempts),
        },
        "complete_continuation": {
            "policy": CONTINUATION_POLICY,
            "fixture_index": CONTINUATION_FIXTURE_INDEX,
            "wall_nanoseconds": continuation_wall,
            "cpu_nanoseconds": continuation_cpu,
            "decisions": continuation["continuation_decisions"],
            "rollouts": continuation["continuation_rollouts"],
            "searches": continuation["continuation_searches"],
            "terminal_result_discarded": True,
        },
        "elapsed_nanoseconds": time.perf_counter_ns() - started_wall,
        "cpu_nanoseconds": time.process_time_ns() - started_cpu,
    }
    if any(result[key] <= 0 for key in (
            "state_reconstruction_elapsed_nanoseconds",
            "ballot_elapsed_nanoseconds",
            "world_materialization_elapsed_nanoseconds",
            "elapsed_nanoseconds", "cpu_nanoseconds")):
        raise WorldAfterstateCapacityError(
            "capacity composed clock did not advance")
    return result


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
    runtime_binding = _strict_runtime_binding()
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
    schedule = {
        "schema": CAPACITY_SCHEDULE_SCHEMA,
        "fixture_count": fixture_count,
        "worker_counts": list(worker_counts),
        "worker_repetitions": worker_repetitions,
        "batch_sizes": list(batch_sizes),
        "model_steps": model_steps,
        "requested_device": device_name,
        "production_ballot_policy": PRODUCTION_BALLOT_POLICY,
        "continuation_policy": CONTINUATION_POLICY,
        "continuation_fixture_index": CONTINUATION_FIXTURE_INDEX,
    }
    memory_before = _capacity_memory_snapshot()
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
    composed = _composed_measurement(audits)
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
    server_root = source_root.parent
    source_files = {
        "capacity": Path(__file__).resolve(),
        "launcher": (
            server_root / "scripts" / "world_afterstate_v0_capacity.py"),
        "afterstate": Path(__file__).resolve().with_name(
            "world_afterstate.py"),
        "model": Path(__file__).resolve().with_name(
            "world_afterstate_model.py"),
        "continuation": Path(__file__).resolve().with_name(
            "world_afterstate_label.py"),
        "teacher_contract": source_root / "teacher_v1.py",
        "engine_round": source_root / "engine" / "round.py",
        "engine_legal": source_root / "engine" / "legal.py",
        "engine_fast": source_root / "engine" / "fast.py",
        "engine_ballot": source_root / "engine" / "ballot.py",
        "ai_mcbot": source_root / "ai" / "mcbot.py",
        "ai_registry": source_root / "ai" / "registry.py",
    }
    memory_after = _capacity_memory_snapshot()
    if memory_before["method"] != memory_after["method"] \
            or memory_before["path"] != memory_after["path"] \
            or memory_after["peak_bytes"] < memory_before["peak_bytes"]:
        raise WorldAfterstateCapacityError(
            "capacity aggregate memory accounting drift")
    result = {
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
            **runtime_binding,
        },
        "source_sha256s": {
            name: _sha256_file(path) for name, path in source_files.items()
        },
        "schedule": schedule,
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
        "composed_measurement": composed,
        "tensor_worker_scaling": tensor_scaling,
        "model_measurements": model_measurements,
        "aggregate_memory": {
            "method": memory_after["method"],
            "path": memory_after["path"],
            "start_current_bytes": memory_before["current_bytes"],
            "start_peak_bytes": memory_before["peak_bytes"],
            "finish_current_bytes": memory_after["current_bytes"],
            "finish_peak_bytes": memory_after["peak_bytes"],
        },
        "authority": dict(AUTHORITY),
    }
    validate_capacity_receipt(result)
    return result


def validate_capacity_receipt(value: Mapping[str, Any]) -> None:
    if type(value) is not dict or value.get("schema") != CAPACITY_SCHEMA:
        raise WorldAfterstateCapacityError("capacity receipt schema drift")
    required = {
        "schema", "git", "outcome_blind", "evidence_artifact", "runtime",
        "source_sha256s", "schedule", "fixtures", "tensor_worker_scaling",
        "composed_measurement", "model_measurements", "aggregate_memory",
        "authority",
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
                "capacity", "launcher", "afterstate", "model", "continuation",
                "teacher_contract", "engine_round", "engine_legal",
                "engine_fast", "engine_ballot", "ai_mcbot", "ai_registry"} \
            or any(type(digest) is not str or len(digest) != 64
                   or any(char not in "0123456789abcdef" for char in digest)
                   for digest in value["source_sha256s"].values()):
        raise WorldAfterstateCapacityError("capacity source identity drift")
    runtime = value["runtime"]
    if type(runtime) is not dict or set(runtime) != {
        "host", "platform", "python", "torch", "device", "cpu_count",
        "torch_threads", "torch_interop_threads", "max_rss_raw",
        "max_rss_unit", "environment", "python_executable",
        "python_executable_sha256", "fast_router_path",
        "fast_router_sha256", "native_path", "native_sha256",
        "compiled_engine_active", "safe_path", "dont_write_bytecode",
        "pythonpath_absent"}:
        raise WorldAfterstateCapacityError("capacity runtime schema drift")
    for key in ("cpu_count", "torch_threads", "torch_interop_threads"):
        if isinstance(runtime[key], bool) or not isinstance(runtime[key], int) \
                or runtime[key] <= 0:
            raise WorldAfterstateCapacityError(
                "capacity runtime resource drift")
    if runtime.get("environment") != REQUIRED_ENVIRONMENT \
            or runtime.get("compiled_engine_active") is not True \
            or runtime.get("safe_path") is not True \
            or runtime.get("dont_write_bytecode") is not True \
            or runtime.get("pythonpath_absent") is not True \
            or any(type(runtime.get(key)) is not str or not runtime[key]
                   for key in ("python_executable", "fast_router_path",
                               "native_path")) \
            or any(type(runtime.get(key)) is not str or len(runtime[key]) != 64
                   or any(char not in "0123456789abcdef"
                          for char in runtime[key])
                   for key in ("python_executable_sha256",
                               "fast_router_sha256", "native_sha256")):
        raise WorldAfterstateCapacityError(
            "capacity strict runtime identity drift")
    schedule = value["schedule"]
    if type(schedule) is not dict or set(schedule) != {
            "schema", "fixture_count", "worker_counts",
            "worker_repetitions", "batch_sizes", "model_steps",
            "requested_device", "production_ballot_policy",
            "continuation_policy", "continuation_fixture_index"} \
            or schedule.get("schema") != CAPACITY_SCHEDULE_SCHEMA \
            or isinstance(schedule.get("fixture_count"), bool) \
            or not isinstance(schedule.get("fixture_count"), int) \
            or not 13 <= schedule["fixture_count"] <= 256 \
            or type(schedule.get("worker_counts")) is not list \
            or not schedule["worker_counts"] \
            or any(isinstance(item, bool) or not isinstance(item, int)
                   or not 1 <= item <= 16
                   for item in schedule["worker_counts"]) \
            or len(set(schedule["worker_counts"])) \
            != len(schedule["worker_counts"]) \
            or isinstance(schedule.get("worker_repetitions"), bool) \
            or not isinstance(schedule.get("worker_repetitions"), int) \
            or not 1 <= schedule["worker_repetitions"] <= 64 \
            or type(schedule.get("batch_sizes")) is not list \
            or not schedule["batch_sizes"] \
            or any(isinstance(item, bool) or not isinstance(item, int)
                   or not 1 <= item <= 4096
                   for item in schedule["batch_sizes"]) \
            or len(set(schedule["batch_sizes"])) \
            != len(schedule["batch_sizes"]) \
            or isinstance(schedule.get("model_steps"), bool) \
            or not isinstance(schedule.get("model_steps"), int) \
            or not 1 <= schedule["model_steps"] <= 1000 \
            or schedule.get("requested_device") \
            not in ("auto", "cpu", "cuda", "mps") \
            or schedule.get("production_ballot_policy") \
            != PRODUCTION_BALLOT_POLICY \
            or schedule.get("continuation_policy") != CONTINUATION_POLICY \
            or schedule.get("continuation_fixture_index") \
            != CONTINUATION_FIXTURE_INDEX:
        raise WorldAfterstateCapacityError("capacity schedule drift")
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
    if fixtures["count"] != schedule["fixture_count"] \
            or sum(fixtures["trump_rank_counts"].values()) \
            != fixtures["count"] \
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
    composed = value["composed_measurement"]
    composed_keys = {
        "production_ballot_policy", "production_ballot_digest",
        "protected_incumbent_index", "fixture_count",
        "state_reconstruction_elapsed_nanoseconds",
        "state_reconstruction_per_second_ppm", "ballot_elapsed_nanoseconds",
        "ballots_per_second_ppm",
        "world_materialization_elapsed_nanoseconds",
        "world_rows_per_second_ppm",
        "candidate_count_distribution", "candidate_bytes_distribution",
        "world_row_bytes_distribution", "candidate_population_sha256",
        "world_row_population_sha256", "strict_world_materialization",
        "complete_continuation", "elapsed_nanoseconds", "cpu_nanoseconds",
    }
    if type(composed) is not dict or set(composed) != composed_keys \
            or composed.get("production_ballot_policy") \
            != PRODUCTION_BALLOT_POLICY \
            or type(composed.get("production_ballot_digest")) is not str \
            or len(composed["production_ballot_digest"]) != 12 \
            or any(char not in "0123456789abcdef"
                   for char in composed["production_ballot_digest"]) \
            or composed.get("protected_incumbent_index") != 0 \
            or composed.get("fixture_count") != fixtures["count"] \
            or any(isinstance(composed.get(key), bool)
                   or not isinstance(composed.get(key), int)
                   or composed[key] <= 0 for key in (
                       "state_reconstruction_elapsed_nanoseconds",
                       "state_reconstruction_per_second_ppm",
                       "ballot_elapsed_nanoseconds",
                       "ballots_per_second_ppm",
                       "world_materialization_elapsed_nanoseconds",
                       "world_rows_per_second_ppm",
                       "elapsed_nanoseconds", "cpu_nanoseconds")) \
            or any(type(composed.get(key)) is not str
                   or len(composed[key]) != 64
                   or any(char not in "0123456789abcdef"
                          for char in composed[key]) for key in (
                       "candidate_population_sha256",
                       "world_row_population_sha256")):
        raise WorldAfterstateCapacityError(
            "capacity composed measurement drift")
    for key in ("candidate_count_distribution",
                "candidate_bytes_distribution",
                "world_row_bytes_distribution"):
        _validate_distribution_record(composed[key])
    if composed["candidate_count_distribution"]["count"] \
            != fixtures["count"] \
            or composed["candidate_bytes_distribution"]["count"] \
            != fixtures["count"] \
            or composed["world_row_bytes_distribution"]["count"] \
            != composed["candidate_count_distribution"]["total"]:
        raise WorldAfterstateCapacityError(
            "capacity candidate/world-row accounting drift")
    if composed["state_reconstruction_per_second_ppm"] != (
            fixtures["count"] * 10**15
            // composed["state_reconstruction_elapsed_nanoseconds"]) \
            or composed["ballots_per_second_ppm"] != (
                fixtures["count"] * 10**15
                // composed["ballot_elapsed_nanoseconds"]) \
            or composed["world_rows_per_second_ppm"] != (
                composed["world_row_bytes_distribution"]["count"] * 10**15
                // composed["world_materialization_elapsed_nanoseconds"]):
        raise WorldAfterstateCapacityError(
            "capacity composed throughput derivation drift")
    materialization = composed["strict_world_materialization"]
    if type(materialization) is not dict or set(materialization) != {
            "attempts", "accepted", "failed", "accepted_rate_ppm"} \
            or any(isinstance(materialization.get(key), bool)
                   or not isinstance(materialization.get(key), int)
                   for key in materialization) \
            or materialization["attempts"] <= 0 \
            or materialization["accepted"] != materialization["attempts"] \
            or materialization["failed"] != 0 \
            or materialization["accepted_rate_ppm"] != 1_000_000 \
            or materialization["attempts"] != (
                fixtures["count"]
                + composed["candidate_count_distribution"]["total"]):
        raise WorldAfterstateCapacityError(
            "capacity strict world materialization drift")
    continuation = composed["complete_continuation"]
    if type(continuation) is not dict or set(continuation) != {
            "policy", "fixture_index", "wall_nanoseconds", "cpu_nanoseconds",
            "decisions", "rollouts", "searches",
            "terminal_result_discarded"} \
            or continuation.get("policy") != CONTINUATION_POLICY \
            or continuation.get("fixture_index") \
            != CONTINUATION_FIXTURE_INDEX \
            or continuation.get("terminal_result_discarded") is not True \
            or any(isinstance(continuation.get(key), bool)
                   or not isinstance(continuation.get(key), int)
                   or continuation[key] <= 0 for key in (
                       "wall_nanoseconds", "cpu_nanoseconds", "decisions",
                       "rollouts", "searches")):
        raise WorldAfterstateCapacityError(
            "capacity complete continuation receipt drift")
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
    if [row["workers"] for row in workers] != schedule["worker_counts"] \
            or any(row["tasks"] != schedule["fixture_count"]
                   * schedule["worker_repetitions"] for row in workers):
        raise WorldAfterstateCapacityError("capacity worker schedule drift")
    if len({row["output_population_sha256"] for row in workers}) != 1:
        raise WorldAfterstateCapacityError(
            "capacity parallel tensor output drift")
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
    expected_model_schedule = [
        (shape, batch_size)
        for shape in CAPACITY_SHAPES
        for batch_size in schedule["batch_sizes"]
    ]
    if [(row["shape"], row["batch_size"]) for row in measurements] \
            != expected_model_schedule \
            or any(row["steps"] != schedule["model_steps"]
                   for row in measurements) \
            or any(row["shape_values"] != {
                "public_hidden": CAPACITY_SHAPES[row["shape"]].public_hidden,
                "history_hidden": CAPACITY_SHAPES[row["shape"]].history_hidden,
                "world_hidden": CAPACITY_SHAPES[row["shape"]].world_hidden,
                "perspective_hidden":
                    CAPACITY_SHAPES[row["shape"]].perspective_hidden,
                "head_hidden": CAPACITY_SHAPES[row["shape"]].head_hidden,
            } for row in measurements):
        raise WorldAfterstateCapacityError("capacity model schedule drift")
    aggregate_memory = value["aggregate_memory"]
    if type(aggregate_memory) is not dict or set(aggregate_memory) != {
            "method", "path", "start_current_bytes", "start_peak_bytes",
            "finish_current_bytes", "finish_peak_bytes"} \
            or aggregate_memory.get("method") \
            != "linux-cgroup-v2-memory.peak" \
            or type(aggregate_memory.get("path")) is not str \
            or not (aggregate_memory["path"] == "/sys/fs/cgroup"
                    or aggregate_memory["path"].startswith(
                        "/sys/fs/cgroup/")) \
            or any(isinstance(aggregate_memory.get(key), bool)
                   or not isinstance(aggregate_memory.get(key), int)
                   or aggregate_memory[key] < 0 for key in (
                       "start_current_bytes", "start_peak_bytes",
                       "finish_current_bytes", "finish_peak_bytes")) \
            or aggregate_memory["start_peak_bytes"] \
            < aggregate_memory["start_current_bytes"] \
            or aggregate_memory["finish_peak_bytes"] \
            < aggregate_memory["finish_current_bytes"] \
            or aggregate_memory["finish_peak_bytes"] \
            < aggregate_memory["start_peak_bytes"] \
            or aggregate_memory["finish_peak_bytes"] <= 0:
        raise WorldAfterstateCapacityError(
            "capacity aggregate memory receipt drift")
    forbidden_tokens = ("attacker_points", "signed_level_category", "label",
                        "logit", "prediction", "proper_score")
    raw = canonical_json_bytes(dict(value)).decode("ascii")
    if any(token in raw for token in forbidden_tokens):
        raise WorldAfterstateCapacityError(
            "capacity receipt contains outcome-bearing vocabulary")

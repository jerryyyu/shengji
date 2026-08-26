#!/usr/bin/env python3
"""Score-free serial/parallel benchmark on the exact hard R4 projection.

The fixture is an opened-calibration regression artifact already committed to
the test tree.  This script never opens an evidence root, hidden test target,
or terminal result.  It proves output-byte parity before reporting speedup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import time
from pathlib import Path

import shengji.rl.belief_v2_r4_completion as R4
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.belief_model import MODEL_SCHEMA
from shengji.rl.belief_projection import RawCountWeightV1
from shengji.rl.belief_reopen import actor_observation_from_dict
from shengji.rl.belief_v2_execution_identity import (
    configure_numerical_runtime,
)
from shengji.rl.belief_v2_scoring import (
    _ProjectionTaskV1,
    _project_member_task,
    v2_scoring_actor,
)


FIXTURE = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures"
    / "belief_projection_r4_calibration_failure_late_endgame.json"
)


def _task() -> _ProjectionTaskV1:
    payload = json.loads(FIXTURE.read_text(encoding="ascii"))
    actor = v2_scoring_actor(actor_observation_from_dict(
        payload["source_actor"]))
    raw = tuple(RawCountWeightV1(
        card=row["card"], receiver=row["receiver"],
        count_weights=tuple(row["count_weights"]))
        for row in payload["raw_weights"])
    return _ProjectionTaskV1(
        actor=actor, raw_weights=raw,
        model_sha256=payload["model_sha256"],
        decision_key=payload["decision_key"],
        cohort_id=payload["cohort_id"],
        member_index=payload["member_index"])


def _digest(rows) -> str:
    digest = hashlib.sha256()
    for row in rows:
        raw = row.canonical_bytes()
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=int, default=32)
    args = parser.parse_args()
    if args.tasks <= 0:
        parser.error("--tasks must be positive")
    configure_numerical_runtime()
    task = _task()
    tasks = (task,) * args.tasks

    started = time.monotonic_ns()
    serial = tuple(_project_member_task(row) for row in tasks)
    serial_wall = time.monotonic_ns() - started

    started = time.monotonic_ns()
    with R4._projection_pool() as executor:
        R4._warm_projection_pool(executor)
        parallel = tuple(executor.map(
            _project_member_task, tasks, chunksize=1))
    parallel_wall = time.monotonic_ns() - started
    serial_sha = _digest(serial)
    parallel_sha = _digest(parallel)
    if serial_sha != parallel_sha or serial != parallel:
        raise SystemExit("parallel projection bytes differ from serial")
    print(canonical_json_bytes({
        "schema": "belief-r4-projection-pool-benchmark-v1",
        "hostname": platform.node(),
        "logical_cpu_count": __import__("os").cpu_count(),
        "worker_count": R4.R4_PROJECTION_WORKERS,
        "task_count": args.tasks,
        "fixture_sha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
        "result_population_sha256": serial_sha,
        "serial_wall_nanoseconds": serial_wall,
        "parallel_wall_nanoseconds": parallel_wall,
        "speedup_ppm": (serial_wall * 1_000_000) // parallel_wall,
        "byte_identical": True,
        "opens_evidence_root": False,
        "opens_test_split": False,
        "execution_authorized": False,
    }).decode("ascii"), end="")


if __name__ == "__main__":
    main()

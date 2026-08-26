"""Exact task-population witnesses for the R4 supervisor plan."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

import scripts.belief_v2_worker as WORKER

from shengji.rl.belief_v2_human_inventory import (
    H0_GROUP_SCHEMA,
    H0_SPLIT_NAMESPACE,
    H0_SPLIT_SCHEMA,
)
from shengji.rl.belief_v2_supervisor_plan import (
    BeliefV2SupervisorPlanError,
    V2SupervisorStageV1,
    build_supervisor_plan,
    validate_supervisor_plan,
)


def _group_digest(raw: bytes) -> str:
    source_sha256 = hashlib.sha256(raw).hexdigest()
    return hashlib.sha256(
        f"{H0_GROUP_SCHEMA}|{source_sha256}".encode("ascii")).hexdigest()


def _inputs(tmp_path, *, counts=(24, 3, 3)):
    sources = []
    digests = []
    for index in range(30):
        path = tmp_path / f"source-{index:02d}.jsonl"
        raw = f"private-source-{index}\n".encode("ascii")
        path.write_bytes(raw)
        sources.append(path)
        digests.append(_group_digest(raw))
    ordered = sorted(digests)
    train, calibration, test = counts
    populations = {
        "train": ordered[:train],
        "calibration": ordered[train:train + calibration],
        "test": ordered[train + calibration:train + calibration + test],
    }
    split = {
        "schema": H0_SPLIT_SCHEMA,
        "namespace": H0_SPLIT_NAMESPACE,
        "splits": {
            name: {"group_count": len(values),
                   "group_digests": values}
            for name, values in populations.items()
        },
    }
    return tuple(sources), split


def test_r4_plan_has_exact_cache_stage_and_non_cartesian_references(tmp_path):
    sources, split = _inputs(tmp_path)
    plan = build_supervisor_plan(
        human_source_paths=sources, group_split=split)
    validate_supervisor_plan(plan)
    summary = plan.summary()
    assert summary["stage_order"] == [
        "synthetic-capture", "human-capture", "training-input-index",
        "training-tensor-cache", "device-qualification", "references",
        "training", "calibration", "single-test-opening",
        "terminal-verification"]
    assert summary["stage_task_counts"] == [16, 30, 1, 1, 1, 25, 4, 1, 1, 1]
    assert summary["task_count"] == 81
    assert summary["execution_plan_sha256"] == plan.execution_sha256()
    assert summary["human_reference_replicate_counts"] == {
        "calibration-replicate-0": 3,
        "calibration-replicate-1": 3,
        "test-primary": 3,
    }
    assert summary["human_source_records_parsed"] is False
    assert summary["outcome_fields_opened"] is False
    assert summary["same_admission_process_resume_authorized"] is True
    assert summary["retry_authorized"] is False
    assert summary["test_split_open_authorized"] is False


def test_every_supervisor_task_parses_through_the_real_worker_cli(tmp_path):
    sources, split = _inputs(tmp_path, counts=(21, 4, 5))
    plan = build_supervisor_plan(
        human_source_paths=sources, group_split=split)
    parser = WORKER.parser()
    root = tmp_path / "evidence"

    parsed = []
    for stage in plan.stages:
        for task in stage.tasks:
            args = parser.parse_args([
                *task.arguments, "--root", str(root)])
            assert callable(args.function)
            parsed.append((stage.name, task.name, args.command))

    assert len(parsed) == 85
    assert {row[0] for row in parsed} == {
        "synthetic-capture", "human-capture", "training-input-index",
        "training-tensor-cache", "device-qualification", "references",
        "training", "calibration", "single-test-opening",
        "terminal-verification",
    }


def test_r4_plan_refuses_dropped_cache_and_old_cartesian_matrix(tmp_path):
    sources, split = _inputs(tmp_path)
    plan = build_supervisor_plan(
        human_source_paths=sources, group_split=split)

    without_cache = replace(plan, stages=tuple(
        stage for stage in plan.stages
        if stage.name != "training-tensor-cache"))
    with pytest.raises(BeliefV2SupervisorPlanError, match="plan identity"):
        validate_supervisor_plan(without_cache)

    references = plan.stages[5]
    extra = tuple(references.tasks[16:25]) * 9
    cartesian = replace(
        plan, stages=tuple(
            V2SupervisorStageV1(
                stage.name, stage.concurrency, stage.tasks + extra)
            if stage.name == "references" else stage
            for stage in plan.stages))
    with pytest.raises(BeliefV2SupervisorPlanError, match="plan identity"):
        validate_supervisor_plan(cartesian)


def test_r4_plan_derives_private_component_split_task_count(tmp_path):
    sources, split = _inputs(tmp_path, counts=(21, 4, 5))
    plan = build_supervisor_plan(
        human_source_paths=sources, group_split=split)
    summary = plan.summary()

    assert summary["human_split_counts"] == {
        "train": 21, "calibration": 4, "test": 5}
    assert summary["human_reference_replicate_counts"] == {
        "calibration-replicate-0": 4,
        "calibration-replicate-1": 4,
        "test-primary": 5,
    }
    assert summary["stage_task_counts"] == [
        16, 30, 1, 1, 1, 29, 4, 1, 1, 1]
    assert summary["task_count"] == 85


def test_r4_plan_refuses_source_or_split_population_drift(tmp_path):
    sources, split = _inputs(tmp_path)
    with pytest.raises(BeliefV2SupervisorPlanError,
                       match="source population"):
        build_supervisor_plan(
            human_source_paths=sources[:-1], group_split=split)

    split["splits"]["train"]["group_digests"].append("0" * 64)
    split["splits"]["train"]["group_count"] += 1
    with pytest.raises(BeliefV2SupervisorPlanError,
                       match="split (population|union)"):
        build_supervisor_plan(
            human_source_paths=sources, group_split=split)

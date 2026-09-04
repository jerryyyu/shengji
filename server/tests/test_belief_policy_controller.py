"""Capacity selection and fork-controller contract witnesses."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from shengji.rl import belief_policy_controller as C
from shengji.rl.belief_policy_models import R4PolicyModelsV1


def _models() -> R4PolicyModelsV1:
    # Capacity-selection tests replace the worker arm before model access.
    return R4PolicyModelsV1(
        freeze_sha256="a" * 64,
        admission_sha256="b" * 64,
        review_marker_sha256="c" * 64,
        common_calibration_sha256="d" * 64,
        primary_trained_manifest_sha256="e" * 64,
        control_trained_manifest_sha256="f" * 64,
        primary=None,  # type: ignore[arg-type]
        control=None,  # type: ignore[arg-type]
    )


def _arm(workers: int, *, passed: bool = True) -> dict:
    tasks = [{
        "coordinate_index": index,
        "qualified": True,
        "wall_nanoseconds": 10 + index,
        "cpu_nanoseconds": 9 + index,
        "max_rss_bytes": 1_000,
        "reference_worlds": 256,
        "selection_physical_rollouts": 60,
        "report_physical_rollouts": 600,
    } for index in range(workers)]
    return {
        "workers": workers,
        "task_count": workers,
        "tasks": tasks,
        "wall_nanoseconds": 20,
        "cpu_nanoseconds": 18 * workers,
        "aggregate_cpu_utilization_ppb": 900_000_000 * workers,
        "max_child_rss_bytes": 1_000,
        "projected_process_rss_bytes": 1_000 * workers,
        "host_memory_bytes": 1_000_000,
        "swap_used_bytes_before": 0,
        "swap_used_bytes_after": 0,
        "passed": passed,
    }


def test_capacity_selects_13_only_when_15_is_larger_passing_headroom(
        monkeypatch):
    monkeypatch.setattr(C.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(
        C, "_run_capacity_arm",
        lambda workers, models, heartbeat=None: _arm(workers))
    receipt = C.run_score_free_capacity(
        models=_models(), execution_git="1" * 40,
        source_manifest_sha256="2" * 64)
    assert receipt["selected_workers"] == 13
    assert receipt["headroom_workers"] == 15
    assert receipt["scientific_wall_estimate_nanoseconds"] == 22 * 8 * 2
    assert receipt["contains_actions"] is False
    assert receipt["contains_outcomes"] is False


def test_capacity_falls_back_to_largest_headroom_backed_arm(monkeypatch):
    monkeypatch.setattr(C.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(
        C, "_run_capacity_arm",
        lambda workers, models, heartbeat=None: _arm(
            workers, passed=workers not in {13, 15}))
    receipt = C.run_score_free_capacity(
        models=_models(), execution_git="1" * 40,
        source_manifest_sha256="2" * 64)
    assert receipt["selected_workers"] == 4
    assert receipt["headroom_workers"] == 8
    assert receipt["scientific_wall_estimate_nanoseconds"] == 13 * 8 * 4


def test_capacity_progress_reports_measured_work_and_resources(monkeypatch):
    monkeypatch.setattr(C.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(
        C, "_run_capacity_arm",
        lambda workers, models, heartbeat=None: _arm(workers))
    events = []
    C.run_score_free_capacity(
        models=_models(), execution_git="1" * 40,
        source_manifest_sha256="2" * 64, progress=events.append)
    assert events[0]["phase"] == "capacity-worker-arms"
    assert events[-1]["completed"] == len(C.CAPACITY_WORKER_ARMS)
    assert events[-1]["aggregate_cpu_utilization_ppb"] \
        == 900_000_000 * 15
    assert events[-1]["reference_worlds"] == 256 * 15
    assert events[-1]["memory_headroom_bytes"] == 985_000


def test_rank_resume_reopens_shards_without_rerunning_evaluation(
        monkeypatch, tmp_path: Path):
    coordinates = tuple(SimpleNamespace(
        trump_rank="2", rank_index=0, rank_ordinal=index,
        round_seed=100 + index) for index in range(8))
    monkeypatch.setattr(C, "policy_rank_coordinates",
                        lambda _rank: coordinates)
    def selected(coordinate):
        return SimpleNamespace(
            coordinate=coordinate,
            decision_index=20 + coordinate.rank_ordinal,
            actor_seat=coordinate.rank_ordinal % 4,
            actor=SimpleNamespace(
                sha256=lambda: f"{coordinate.round_seed:064x}"),
            selection_key=bytes([coordinate.rank_ordinal]) * 32,
            candidates=(("C2",), ("D2",)),
        )

    monkeypatch.setattr(C, "select_natural_policy_root", selected)
    def result_row(natural):
        coordinate = natural.coordinate
        return {
            "coordinate": {
                "trump_rank": coordinate.trump_rank,
                "rank_index": coordinate.rank_index,
                "rank_ordinal": coordinate.rank_ordinal,
                "round_seed": coordinate.round_seed,
            },
            "decision_index": natural.decision_index,
            "actor_seat": natural.actor_seat,
            "actor_sha256": natural.actor.sha256(),
            "selection_key_sha256": natural.selection_key.hex(),
            "candidates": [list(row) for row in natural.candidates],
            "folds": {
                "proposal_reference": {"attempts": 256},
                "selection": {"attempts": 30},
                "report": {"attempts": 300},
            },
            "work": {
                "reference_worlds": 256,
                "selection_worlds": 30,
                "report_worlds": 300,
                "selection_physical_rollouts": 60,
                "report_physical_rollouts": 600,
            },
        }

    monkeypatch.setattr(C, "evaluate_policy_root",
                        lambda natural, **_kwargs: natural)
    monkeypatch.setattr(C, "build_policy_root_result",
                        lambda natural, **_kwargs: result_row(natural))

    def publish(path, *_args, **_kwargs):
        path.write_bytes(b"{}\n")
        return "a" * 64

    monkeypatch.setattr(C, "publish_policy_root_result", publish)
    C._set_models(_models())
    root = tmp_path.resolve()
    first = C._rank_worker((0, str(root), 2**63 - 1, 1))
    assert len(first["selected_rounds"]) == 8

    monkeypatch.setattr(
        C, "evaluate_policy_root",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("resume must not rerun an existing shard")))
    def reopened(path):
        index = int(path.stem[-2:])
        coordinate = coordinates[index]
        natural = selected(coordinate)
        return result_row(natural)

    monkeypatch.setattr(C, "reopen_policy_root_result", reopened)
    second = C._rank_worker((0, str(root), 2**63 - 1, 1))
    assert second == first

    def forged(path):
        row = reopened(path)
        row["decision_index"] += 1
        return row

    monkeypatch.setattr(C, "reopen_policy_root_result", forged)
    with pytest.raises(
            C.BeliefPolicyControllerError,
            match="resumed shard natural-root drift"):
        C._rank_worker((0, str(root), 2**63 - 1, 1))


def test_rank_does_not_start_a_unit_that_cannot_fit_before_deadline(
        monkeypatch, tmp_path: Path):
    monkeypatch.setattr(C, "policy_rank_coordinates", lambda _rank: (
        SimpleNamespace(round_seed=1),))
    monkeypatch.setattr(
        C, "select_natural_policy_root",
        lambda _coordinate: (_ for _ in ()).throw(
            AssertionError("expired unit must not start")))
    monkeypatch.setattr(C.time, "time_ns", lambda: 1_000)
    with pytest.raises(
            C.BeliefPolicyControllerError,
            match="scientific deadline exhausted"):
        C._rank_worker((0, str(tmp_path.resolve()), 1_100, 101))


def test_scientific_shard_progress_has_capacity_derived_eta_before_rank_done(
        monkeypatch):
    monkeypatch.setattr(C.time, "monotonic_ns", lambda: 2_000_000_000)
    monkeypatch.setattr(C.time, "time_ns", lambda: 20_000_000_000)
    event = C._scientific_progress_event(
        phase="scientific-shard-published", completed=0, total=13,
        workers=13,
        rank_progress={0: {
            "scanned_rounds": 1,
            "selected_rounds": 1,
            "reference_attempts": 256,
            "selection_attempts": 30,
            "report_attempts": 300,
            "reference_worlds": 256,
            "selection_worlds": 30,
            "report_worlds": 300,
            "selection_physical_rollouts": 60,
            "report_physical_rollouts": 600,
        }},
        wall_started_monotonic_ns=1_000_000_000,
        scientific_wall_estimate_ns=11_000_000_000,
        deadline_unix_ns=40_000_000_000)
    assert event["completed"] == 0
    assert event["immutable_shards"] == 1
    assert event["estimated_remaining_seconds"] == 10

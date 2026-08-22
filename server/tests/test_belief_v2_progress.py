import io
import json

import pytest

from shengji.rl.belief_v2_progress import (
    BeliefV2ProgressError,
    PROGRESS_PREFIX,
    V2ProgressReporter,
)


def test_progress_is_canonical_monotonic_outcome_blind_and_exact():
    ticks = iter((100, 100, 200, 300))
    stream = io.StringIO()
    reporter = V2ProgressReporter(
        stage="training", worker="cohort-0", stream=stream,
        clock=lambda: next(ticks))
    reporter.update(0, 4, "epochs")
    reporter.update(2, 4, "epochs")
    reporter.update(4, 4, "complete")
    rows = []
    for line in stream.getvalue().splitlines():
        assert line.startswith(PROGRESS_PREFIX)
        rows.append(json.loads(line.removeprefix(PROGRESS_PREFIX)))
    assert [row["percent_basis_points"] for row in rows] == [0, 5000, 10000]
    assert [row["estimated_remaining_nanoseconds"] for row in rows] \
        == [None, 100, 0]
    assert [row["status"] for row in rows] \
        == ["running", "running", "complete"]
    assert all(row["outcome_blind"] is True
               and row["evidence_artifact"] is False
               and row["strength_claim_authorized"] is False
               and row["deployment_authorized"] is False for row in rows)
    assert not any("loss" in key or "score" in key or "result" in key
                   for row in rows for key in row)


def test_progress_refuses_regression_total_drift_and_invalid_identity():
    stream = io.StringIO()
    ticks = iter(range(1, 8))
    reporter = V2ProgressReporter(
        stage="capture", worker="lane-00", stream=stream,
        clock=lambda: next(ticks))
    reporter.update(1, 3, "rounds")
    with pytest.raises(BeliefV2ProgressError, match="population drift"):
        reporter.update(0, 3, "rounds")
    with pytest.raises(BeliefV2ProgressError, match="population drift"):
        reporter.update(2, 4, "rounds")
    with pytest.raises(BeliefV2ProgressError, match="population drift"):
        reporter.update(2, 3, [])  # type: ignore[arg-type]
    with pytest.raises(BeliefV2ProgressError, match="identity drift"):
        V2ProgressReporter(stage="bad stage", worker="lane-00")
    with pytest.raises(BeliefV2ProgressError, match="identity drift"):
        V2ProgressReporter(stage="capture", worker="lané-00")


def test_training_progress_tracks_epoch_and_batch_populations_independently():
    ticks = iter(range(100, 109))
    stream = io.StringIO()
    reporter = V2ProgressReporter(
        stage="training", worker="synthetic-primary", stream=stream,
        clock=lambda: next(ticks))

    # This is the production trainer's exact phase ordering.  The former
    # scalar total rejected the second call before epoch one could start.
    reporter.update(0, 12, "training-epochs")
    reporter.update(0, 240, "training-batches")
    reporter.update(20, 240, "training-batches")
    reporter.update(1, 12, "training-epochs")
    reporter.update(240, 240, "training-batches")
    reporter.update(12, 12, "training-epochs")

    rows = [json.loads(line.removeprefix(PROGRESS_PREFIX))
            for line in stream.getvalue().splitlines()]
    assert [(row["phase"], row["completed_units"], row["total_units"])
            for row in rows] == [
        ("training-epochs", 0, 12),
        ("training-batches", 0, 240),
        ("training-batches", 20, 240),
        ("training-epochs", 1, 12),
        ("training-batches", 240, 240),
        ("training-epochs", 12, 12),
    ]

    with pytest.raises(BeliefV2ProgressError, match="population drift"):
        reporter.update(11, 12, "training-epochs")
    with pytest.raises(BeliefV2ProgressError, match="population drift"):
        reporter.update(240, 241, "training-batches")


def test_human_stage_can_finish_with_a_one_unit_completion_phase():
    ticks = iter(range(20, 27))
    stream = io.StringIO()
    reporter = V2ProgressReporter(
        stage="human-capture", worker="source-group", stream=stream,
        clock=lambda: next(ticks))
    reporter.update(0, 4, "replay-human-decisions")
    for completed in range(1, 5):
        reporter.update(completed, 4, "publish-human-decisions")
    reporter.update(1, 1, "human-group-complete")
    rows = [json.loads(line.removeprefix(PROGRESS_PREFIX))
            for line in stream.getvalue().splitlines()]
    assert rows[-1]["phase"] == "human-group-complete"
    assert rows[-1]["status"] == "complete"
    assert rows[-1]["percent_basis_points"] == 10_000

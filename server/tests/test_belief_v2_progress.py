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
    ticks = iter((1, 1, 2, 3))
    reporter = V2ProgressReporter(
        stage="capture", worker="lane-00", stream=stream,
        clock=lambda: next(ticks))
    reporter.update(1, 3, "rounds")
    with pytest.raises(BeliefV2ProgressError, match="population drift"):
        reporter.update(0, 3, "rounds")
    with pytest.raises(BeliefV2ProgressError, match="population drift"):
        reporter.update(2, 4, "rounds")
    with pytest.raises(BeliefV2ProgressError, match="identity drift"):
        V2ProgressReporter(stage="bad stage", worker="lane-00")
    with pytest.raises(BeliefV2ProgressError, match="identity drift"):
        V2ProgressReporter(stage="capture", worker="lané-00")

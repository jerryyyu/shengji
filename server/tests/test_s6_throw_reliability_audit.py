"""Tests for the selected S6 report-world reliability diagnostic."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import s6_throw_reliability_audit as AUDIT  # noqa: E402


def test_wilson_interval_is_bounded_and_refuses_bad_inputs():
    low, high = AUDIT.wilson_interval(0, 300)
    assert low == 0.0
    assert 0 < high < 0.02
    low, high = AUDIT.wilson_interval(300, 300)
    assert 0.98 < low < 1
    assert high == pytest.approx(1.0)
    with pytest.raises(AUDIT.ReliabilityRefused):
        AUDIT.wilson_interval(2, 1)


def test_loss_witness_override_replays_before_scoring():
    rnd, _bot, seat, attempted, decision = AUDIT._capture_override(
        AUDIT.REPLAY.WITNESS_SEED, AUDIT.REPLAY.WITNESS_FLIP)
    assert len(rnd.history) == 6
    assert seat == 3
    assert attempted == ["S4", "S4", "S6", "S6"]
    assert decision["report_fold"]["worlds"] == AUDIT.REPORT_WORLDS
    assert decision["report_fold"]["complete"] is True

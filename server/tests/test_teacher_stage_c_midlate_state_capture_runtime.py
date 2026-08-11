from __future__ import annotations

import copy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import teacher_stage_c_midlate_state_capture_runtime as RUNTIME  # noqa: E402


def _source_state(seed: int, phase: str, role: str, surface: str) -> dict:
    return {
        "schema": "teacher-stage-c-replay-state-v1",
        "experiment_id": "old-experiment",
        "capture_packet_id": "old-packet",
        "split": "SCREEN",
        "surface_type": "play",
        "stratum": "ordinary_anchor",
        "cell_id": "old-cell",
        "seed": seed,
        "seat": 2,
        "state_id": f"SCREEN:{seed}:20:2",
        "actor_policy": "mc-strong",
        "actor_identity": {},
        "actor_streams": [],
        "setup": {},
        "plays": [],
        "ply": 20,
        "trick": 5 if phase == "mid" else 12,
        "phase": phase,
        "surface": surface,
        "role": role,
        "selection_priority": "old",
    }


def test_candidate_state_reuses_natural_capture_and_rebinds_namespace(
        monkeypatch) -> None:
    seen = []
    surface = RUNTIME._surface(10, "mid", "attacker")
    source = _source_state(10, "mid", "attacker", surface)
    monkeypatch.setattr(RUNTIME.CAPTURE, "_actor_identity", lambda: {"id": 1})

    def capture(seed, split, cell, actor):
        seen.append((seed, split, cell, actor))
        return copy.deepcopy(source), "eligible"

    monkeypatch.setattr(RUNTIME.CAPTURE, "capture_deal", capture)
    monkeypatch.setattr(
        RUNTIME.CAPTURE, "replay_state",
        lambda state: SimpleNamespace(
            history=[object()] * state["trick"],
            is_attacker=lambda _seat: True))
    state, reason = RUNTIME.candidate_state(
        10, "mid", "attacker", experiment_id="fresh-experiment",
        capture_packet_id="fresh-packet")
    assert reason == "eligible"
    assert state["experiment_id"] == "fresh-experiment"
    assert state["capture_packet_id"] == "fresh-packet"
    assert state["state_id"].startswith("fresh-experiment:SCREEN:10:")
    assert state["capture_adapter"]["source_identity"] == {
        "experiment_id": "old-experiment",
        "capture_packet_id": "old-packet",
        "state_id": "SCREEN:10:20:2",
        "split": "SCREEN",
        "cell_id": "old-cell",
    }
    assert state["capture_adapter"]["outcomes_opened"] is False
    assert seen[0][0:2] == (10, "SCREEN")
    assert seen[0][2]["surface"] == surface
    assert seen[0][3] == {"id": 1}
    assert source["experiment_id"] == "old-experiment"


def test_candidate_state_preserves_noneligible_disposition(monkeypatch) -> None:
    monkeypatch.setattr(RUNTIME.CAPTURE, "_actor_identity", lambda: {})
    monkeypatch.setattr(
        RUNTIME.CAPTURE, "capture_deal",
        lambda *_args: (None, "target_unreachable"))
    assert RUNTIME.candidate_state(
        11, "late", "defender", experiment_id="fresh",
        capture_packet_id="packet") == (None, "target_unreachable")


def test_candidate_state_refuses_shared_capture_or_replay_drift(
        monkeypatch) -> None:
    monkeypatch.setattr(RUNTIME.CAPTURE, "_actor_identity", lambda: {})

    def refuse(*_args):
        raise RUNTIME.CAPTURE.RuntimeRefused("bad actor")

    monkeypatch.setattr(RUNTIME.CAPTURE, "capture_deal", refuse)
    with pytest.raises(RUNTIME.MidlateCaptureRuntimeError,
                       match="shared Stage-C capture refused"):
        RUNTIME.candidate_state(
            12, "mid", "attacker", experiment_id="fresh",
            capture_packet_id="packet")

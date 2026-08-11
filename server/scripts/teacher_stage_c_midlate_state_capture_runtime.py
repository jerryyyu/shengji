#!/usr/bin/env python3
"""Replay-state candidate adapter for the mid/late protected screen.

This reuses the reviewed Stage-C natural-game actor and replay mechanics while
assigning a fresh experiment/state namespace.  It creates no candidate values,
model predictions or evaluation fold.  A controller must pin the experiment
ID, packet ID, seed range, actor identity and source hashes before execution.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import teacher_stage_c_capture_runtime as CAPTURE  # noqa: E402


SCHEMA = "teacher-stage-c-midlate-capture-adapter-v1"


class MidlateCaptureRuntimeError(RuntimeError):
    """The natural-state source or fresh namespace drifted."""


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def _surface(seed: int, phase: str, role: str) -> str:
    payload = [SCHEMA, "surface", seed, phase, role]
    ticket = int.from_bytes(
        hashlib.sha256(_canonical_json(payload)).digest()[:8], "big")
    # Natural tricks contain one lead and three follow decisions.  This is a
    # target-generation mixture, not a quota or an outcome-dependent choice.
    return "lead" if ticket % 4 == 0 else "follow"


def candidate_state(
    seed: int, phase: str, role: str, *,
    experiment_id: str, capture_packet_id: str,
) -> tuple[dict | None, str]:
    """Generate one natural mid/late replay state without opening outcomes."""
    if (isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
            or phase not in {"mid", "late"}
            or role not in {"attacker", "defender"}
            or not isinstance(experiment_id, str) or not experiment_id
            or not isinstance(capture_packet_id, str) or not capture_packet_id):
        raise MidlateCaptureRuntimeError("mid/late candidate input drift")
    surface = _surface(seed, phase, role)
    cell = {
        "cell_id": f"{phase}-{role}-{surface}",
        "surface_type": "play",
        "stratum": "ordinary_anchor",
        "phase": phase,
        "surface": surface,
        "role": role,
    }
    try:
        state, reason = CAPTURE.capture_deal(
            seed, "SCREEN", cell, CAPTURE._actor_identity())
    except CAPTURE.RuntimeRefused as exc:
        raise MidlateCaptureRuntimeError(
            f"shared Stage-C capture refused: {exc}") from exc
    if state is None:
        return None, reason
    source_identity = {
        "experiment_id": state["experiment_id"],
        "capture_packet_id": state["capture_packet_id"],
        "state_id": state["state_id"],
        "split": state["split"],
        "cell_id": state["cell_id"],
    }
    rebound = copy.deepcopy(state)
    rebound.update({
        "experiment_id": experiment_id,
        "capture_packet_id": capture_packet_id,
        "split": "SCREEN",
        "stratum": "midlate_protected_trigger_candidate",
        "cell_id": f"midlate-protected:{phase}:{role}:{surface}",
        "state_id": (
            f"{experiment_id}:SCREEN:{seed}:{state['ply']}:{state['seat']}"),
        "capture_adapter": {
            "schema": SCHEMA,
            "source_identity": source_identity,
            "target_surface_mixture": "sha256 one-lead-to-three-follow",
            "outcomes_opened": False,
            "model_predictions_opened": False,
            "evaluation_fold_opened": False,
        },
    })
    rebound["selection_priority"] = hashlib.sha256(_canonical_json([
        SCHEMA, experiment_id, "selection-priority", seed,
        rebound["state_id"],
    ])).hexdigest()
    try:
        replayed = CAPTURE.replay_state(rebound)
    except CAPTURE.RuntimeRefused as exc:
        raise MidlateCaptureRuntimeError(
            f"rebound Stage-C state did not replay: {exc}") from exc
    observed_role = (
        "attacker" if replayed.is_attacker(int(rebound["seat"]))
        else "defender")
    if (len(replayed.history) != rebound["trick"]
            or observed_role != role
            or rebound["phase"] != phase
            or rebound["surface"] != surface):
        raise MidlateCaptureRuntimeError(
            "rebound Stage-C state target drift")
    return rebound, "eligible"

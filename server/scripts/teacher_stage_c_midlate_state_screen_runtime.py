#!/usr/bin/env python3
"""Dependency adapter for the mid/late protected Stage-C state screen.

The reusable screen owns policy/fold semantics.  This adapter wires its final
three logical actions to the already-reviewed iid-with-replacement Stage-C
sampler and heuristic continuation.  Importing it performs no sampling and
publishes no artifact; a separately frozen controller must own population,
paths, source hashes, admission and execution.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import teacher_stage_c_label_runtime as LABEL  # noqa: E402
from shengji.rl import stage_c_state_screen as SCREEN  # noqa: E402


class MidlateScreenRuntimeError(RuntimeError):
    """The shared sampler/scorer failed the screen's exact fold contract."""


def evaluation_fold(rnd, seat: int, actions: Sequence[Sequence[str]],
                    seed: int) -> dict:
    """Score treatment/null/live logical slots on 300 fresh common worlds."""
    if (isinstance(seat, bool) or not isinstance(seat, int)
            or not 0 <= seat < 4
            or isinstance(seed, bool) or not isinstance(seed, int)
            or not isinstance(actions, (list, tuple)) or len(actions) != 3
            or any(not isinstance(action, (list, tuple)) or not action
                   or any(not isinstance(card, str) or not card
                          for card in action)
                   for action in actions)):
        raise MidlateScreenRuntimeError(
            "mid/late evaluation-fold input drift")
    state = {
        "surface_type": "play",
        "seat": seat,
        "candidates": [{"cards": list(action), "sources": [source]}
                       for action, source in zip(actions, (
                           "treatment_final", "matched_null_final",
                           "literal_live_final"), strict=True)],
    }
    ledger = LABEL.WorkLedger()
    try:
        bot, worlds, sampler = LABEL.draw_common_worlds(
            rnd, seat, SCREEN.EVALUATION_WORLDS, seed,
            fold="report", ledger=ledger)
        scored = LABEL.score_actions(
            bot, rnd, state, worlds, [0, 1, 2],
            fold="report", ledger=ledger)
    except LABEL.LabelRefused as exc:
        raise MidlateScreenRuntimeError(
            f"shared Stage-C evaluation fold refused: {exc}") from exc
    work = ledger.snapshot()
    expected = 3 * SCREEN.EVALUATION_WORLDS
    if (scored.get("candidate_worlds") != expected
            or work["total_candidate_worlds_attempted"] != expected
            or work["total_candidate_worlds_completed"] != expected
            or work["accounting_complete"] is not True):
        raise MidlateScreenRuntimeError(
            "mid/late evaluation-fold work drift")
    return {
        "schema": SCREEN.EVALUATION_FOLD_SCHEMA,
        "seed": seed,
        "worlds": scored["worlds"],
        "candidate_worlds": scored["candidate_worlds"],
        "actions": scored["actions"],
        "sampler": sampler,
        "work": work,
        "complete": True,
    }

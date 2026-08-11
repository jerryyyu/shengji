#!/usr/bin/env python3
"""Freeze the expanded-Teacher bury composition screen after REPORT PASS."""
from __future__ import annotations

import os
import sys


os.environ["SHENGJI_STAGE_C_COMPOSITION_PROFILE"] = "expanded-bury"
os.environ["SHENGJI_STAGE_C_REPORT_CONTROLLER"] = \
    "teacher_stage_c_expanded_report_controller"

import teacher_stage_c_composition_controller as BASE  # noqa: E402
from teacher_stage_c_composition_controller import *  # noqa: E402,F403


# The shared runtime deliberately verifies these private helpers as part of
# the frozen source/command contract.
_source_sha256s = BASE._source_sha256s
_commands = BASE._commands


if __name__ == "__main__":
    try:
        raise SystemExit(BASE.main())
    except (BASE.CompositionControllerRefused, BASE.NPNET.StageCNumpyError,
            BASE.TRAIN.StageCTrainingError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

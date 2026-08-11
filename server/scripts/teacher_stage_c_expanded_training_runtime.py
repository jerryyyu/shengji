#!/usr/bin/env python3
"""Run the reviewed expanded Stage-C A/B training packet."""
from __future__ import annotations

import os
import sys


os.environ["SHENGJI_STAGE_C_TRAINING_CONTROLLER"] = \
    "teacher_stage_c_expanded_training_controller"

import teacher_stage_c_training_runtime as BASE  # noqa: E402


if __name__ == "__main__":
    try:
        raise SystemExit(BASE.main())
    except BASE.TrainingRuntimeRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

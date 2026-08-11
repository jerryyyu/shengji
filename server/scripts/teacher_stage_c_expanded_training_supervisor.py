#!/usr/bin/env python3
"""Own the reviewed expanded Stage-C A/B training execution."""
from __future__ import annotations

import os
import sys


os.environ["SHENGJI_STAGE_C_TRAINING_CONTROLLER"] = \
    "teacher_stage_c_expanded_training_controller"

import teacher_stage_c_training_supervisor as BASE  # noqa: E402


if __name__ == "__main__":
    try:
        raise SystemExit(BASE.main())
    except BASE.TrainingSupervisorInterrupted as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(128 + exc.signum) from exc
    except (BASE.TrainingSupervisorRefused,
            BASE.RUNTIME.TrainingRuntimeRefused,
            BASE.CTRL.TrainingControllerRefused) as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc

#!/usr/bin/env python3
"""Run the reviewed protected uncertainty-Teacher composition screen."""
from __future__ import annotations

import os
import sys


os.environ["SHENGJI_STAGE_C_COMPOSITION_PROFILE"] = "expanded-uncertainty"
os.environ["SHENGJI_STAGE_C_REPORT_CONTROLLER"] = \
    "teacher_stage_c_expanded_uncertainty_report_controller"
os.environ["SHENGJI_STAGE_C_COMPOSITION_CONTROLLER"] = \
    "teacher_stage_c_expanded_uncertainty_composition_controller"

import teacher_stage_c_composition_runtime as BASE  # noqa: E402


if __name__ == "__main__":
    try:
        raise SystemExit(BASE.main())
    except BASE.CompositionSupervisorInterrupted as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(128 + exc.signum) from exc
    except (BASE.CompositionRuntimeRefused,
            BASE.SCREEN.StageCScreenError,
            BASE.COMPOSITION.StageCCompositionError,
            BASE.NPNET.StageCNumpyError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

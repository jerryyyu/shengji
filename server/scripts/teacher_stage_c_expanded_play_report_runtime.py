#!/usr/bin/env python3
"""Run the shared one-shot REPORT runtime for expanded normal play."""
from __future__ import annotations

import os
import sys


os.environ["SHENGJI_STAGE_C_REPORT_CONTROLLER"] = \
    "teacher_stage_c_expanded_play_report_controller"

import teacher_stage_c_report_runtime as BASE  # noqa: E402


if __name__ == "__main__":
    try:
        raise SystemExit(BASE.main())
    except (BASE.ReportRuntimeRefused,
            BASE.CTRL.ReportControllerRefused) as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc

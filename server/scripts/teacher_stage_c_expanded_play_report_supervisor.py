#!/usr/bin/env python3
"""Own the reviewed expanded normal-play sealed REPORT execution."""
from __future__ import annotations

import os
import sys


os.environ["SHENGJI_STAGE_C_REPORT_CONTROLLER"] = \
    "teacher_stage_c_expanded_play_report_controller"

import teacher_stage_c_report_supervisor as BASE  # noqa: E402


if __name__ == "__main__":
    try:
        raise SystemExit(BASE.main())
    except BASE.ReportSupervisorInterrupted as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(128 + exc.signum) from exc
    except (BASE.ReportSupervisorRefused,
            BASE.RUNTIME.ReportRuntimeRefused,
            BASE.CTRL.ReportControllerRefused) as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc

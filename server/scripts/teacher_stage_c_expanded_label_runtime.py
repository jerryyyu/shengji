#!/usr/bin/env python3
"""Execute the reviewed expanded Stage-C label packet.

All labeling primitives and finite-work semantics remain in
``teacher_stage_c_label_runtime``.  This narrow entry point selects the
expanded controller identity, paths and schedule without changing a label
recipe.
"""
from __future__ import annotations

import sys

import teacher_stage_c_expansion_controller as CTRL
import teacher_stage_c_label_runtime as BASE


BASE._ctrl = lambda: CTRL


if __name__ == "__main__":
    try:
        raise SystemExit(BASE.main())
    except BASE.LabelRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

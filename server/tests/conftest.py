"""Suite-wide switches.

SHENGJI_FAST=1 routes the whole suite (incl. golden histories) through the
Cython fast path — the differential gate for the PERF.md #2+#3 prototype:

    SHENGJI_FAST=1 uv run python -m pytest tests/ -q

Fails loudly if requested but not built (a silent pure fallback would
make the gate meaningless).
"""

import os
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
from review_ledger_guard import enforce_pr_head_extends_base

sys.path.insert(0, ".")

# Every required server CI invocation loads this file.  On pull-request jobs,
# compare the literal head SHA from the event payload with the literal base SHA;
# GitHub's synthetic merge checkout can otherwise mask a stale branch ledger.
enforce_pr_head_extends_base(Path(__file__).parents[2])

if os.environ.get("SHENGJI_FAST"):
    from shengji.engine import fast

    assert fast.activate(), (
        "SHENGJI_FAST=1 but shengji/engine/_fast is not built; run: "
        "uv run python setup.py build_ext --inplace"
    )

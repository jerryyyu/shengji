"""Suite-wide switches.

SHENGJI_FAST=1 routes the whole suite (incl. golden histories) through the
Cython fast path — the differential gate for the PERF.md #2+#3 prototype:

    SHENGJI_FAST=1 uv run python -m pytest tests/ -q

Fails loudly if requested but not built (a silent pure fallback would
make the gate meaningless).
"""

import os
import sys

sys.path.insert(0, ".")

if os.environ.get("SHENGJI_FAST"):
    from shengji.engine import fast

    assert fast.activate(), (
        "SHENGJI_FAST=1 but shengji/engine/_fast is not built; run: "
        "uv run python setup.py build_ext --inplace"
    )

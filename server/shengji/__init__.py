"""shengji package.

SHENGJI_FAST=1 routes the engine through the validated Cython kernels for
EVERYTHING in this process — duels, tournaments, generation, scripts —
not just pytest. Activation is here (package import) so multiprocessing
spawn children inherit it automatically. Fails LOUDLY: a silent fallback
would run 3.4x slower with no signal (Jerry, 2026-08-03).
"""
import os as _os

if _os.environ.get("SHENGJI_FAST") == "1":
    from .engine import fast as _fast

    assert _fast.activate(), (
        "SHENGJI_FAST=1 but shengji/engine/_fast is not built; run: "
        "uv run python setup.py build_ext --inplace")

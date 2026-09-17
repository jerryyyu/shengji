"""shengji package.

The validated Cython kernels are ON BY DEFAULT for EVERYTHING in this
process — duels, tournaments, generation, scripts — not just pytest.
Set SHENGJI_FAST=0 to opt out (pure-Python reference implementation).

Activation is here (package import) so multiprocessing spawn children
inherit it automatically. When the extension isn't built, default-on
warns once and falls back to pure Python (measured ~4.6x slower); an
explicit SHENGJI_FAST=<anything-but-0> still fails loudly, since a
silent fallback would run much slower with no signal (Jerry, 2026-08-03).
"""
import os as _os
import warnings as _warnings

if _os.environ.get("SHENGJI_FAST", "1") != "0":
    from .engine import fast as _fast

    if not _fast.activate():
        _msg = ("shengji/engine/_fast is not built; run: "
                "uv run python setup.py build_ext --inplace")
        if "SHENGJI_FAST" in _os.environ:
            raise AssertionError(
                f"SHENGJI_FAST={_os.environ['SHENGJI_FAST']} but {_msg}")
        _warnings.warn(
            f"SHENGJI_FAST is default-on but {_msg}; running pure Python "
            "(~4.6x slower). Set SHENGJI_FAST=0 to silence this warning.")

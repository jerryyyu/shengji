"""Build helper for optional engine/_fast, ai/_cwv_math, ai/_endgame_fast and train/_pv_fast Cython extensions.

The project's packaging backend stays hatchling (pyproject.toml); this file
only exists so the in-place extension build works:

    cd server && uv run python setup.py build_ext --inplace

Without built extensions everything still runs: engine/fast.py retains Python
implementations, ai/cwv_numpy.py uses the standard-library erf callback, and
ai/endgame_compact.py uses its pure-Python exact solver, and train/pv_native.py
leaves the served search on its Python reference paths.
"""

from Cython.Build import cythonize
from setuptools import setup

setup(
    name="shengji-fast-ext",
    packages=[],  # build_ext only; hatchling owns real packaging
    ext_modules=cythonize(
        ["shengji/engine/_fast.pyx", "shengji/ai/_cwv_math.pyx",
         "shengji/ai/_endgame_fast.pyx", "shengji/train/_pv_fast.pyx"],
        language_level=3,
        annotate=False,
    ),
)

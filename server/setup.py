"""Build helper for optional engine/_fast and ai/_cwv_math Cython extensions.

The project's packaging backend stays hatchling (pyproject.toml); this file
only exists so the in-place extension build works:

    cd server && uv run python setup.py build_ext --inplace

Without built extensions everything still runs: engine/fast.py retains Python
implementations, and ai/cwv_numpy.py uses the standard-library erf callback.
"""

from Cython.Build import cythonize
from setuptools import setup

setup(
    name="shengji-fast-ext",
    packages=[],  # build_ext only; hatchling owns real packaging
    ext_modules=cythonize(
        ["shengji/engine/_fast.pyx", "shengji/ai/_cwv_math.pyx"],
        language_level=3,
        annotate=False,
    ),
)

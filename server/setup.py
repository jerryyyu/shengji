"""Build helper for the optional Cython hot-path extension (engine/_fast).

The project's packaging backend stays hatchling (pyproject.toml); this file
only exists so the in-place extension build works:

    cd server && uv run python setup.py build_ext --inplace

Without the built extension everything still runs — shengji/engine/fast.py
falls back to the pure-Python implementations.
"""

from Cython.Build import cythonize
from setuptools import setup

setup(
    name="shengji-fast-ext",
    packages=[],  # build_ext only; hatchling owns real packaging
    ext_modules=cythonize(
        "shengji/engine/_fast.pyx",
        language_level=3,
        annotate=False,
    ),
)

"""Every module under ``shengji`` imports cleanly.

Safety witness for the 2026-09-05 code-lane cleanup: a module that still
imports a removed lane (belief, suphx, distill, the dead rl lineage, the
closed-campaign scripts) fails here with the offending import, instead of
failing lazily in whichever script first touches it.
"""
from __future__ import annotations

import importlib
import pkgutil

import pytest

import shengji


def _all_modules():
    return sorted(
        info.name for info in pkgutil.walk_packages(
            shengji.__path__, prefix="shengji."))


@pytest.mark.parametrize("name", _all_modules())
def test_module_imports(name):
    importlib.import_module(name)

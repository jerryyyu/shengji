"""A required production-package test may never skip (#633, #634, #993).

Loaded by ``tests/conftest.py``.  Every test that uses the hash-pinned
production package carries the ``production_package`` marker.  It is applied
automatically to any test whose fixture closure contains
``pinned_production_package``, or a fixture whose source names it (the
``request.getfixturevalue("pinned_production_package")`` shape that #993
broke), and can be applied by hand to any other test of the package.

Under ``SHENGJI_REQUIRE_PV_PACKAGE=1`` (CI's "Load the production package on
this tree" step) a skip of a marked test, in setup or call, is rewritten as a
failure.  Without the flag, skips are untouched, so the suite still runs where
the package is not provisioned.  Unmarked tests are never affected.
"""

from __future__ import annotations

import inspect
import os

import pytest

MARKER = "production_package"
FIXTURE = "pinned_production_package"
FLAG = "SHENGJI_REQUIRE_PV_PACKAGE"


def _fixture_mentions_package(fixturedef) -> bool:
    try:
        source = inspect.getsource(fixturedef.func)
    except (OSError, TypeError):
        return False
    return FIXTURE in source


def _uses_production_package(item) -> bool:
    names = getattr(item, "fixturenames", ())
    if FIXTURE in names:
        return True
    info = getattr(item, "_fixtureinfo", None)
    name2defs = getattr(info, "name2fixturedefs", {}) or {}
    return any(
        _fixture_mentions_package(fixturedef)
        for name in names
        for fixturedef in name2defs.get(name, ())
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        f"{MARKER}: uses the pinned production package; a skip FAILS under {FLAG}=1",
    )


def pytest_collection_modifyitems(config, items):
    for item in items:
        if item.get_closest_marker(MARKER) is None and _uses_production_package(item):
            item.add_marker(MARKER)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    if (
        report.skipped
        and not hasattr(report, "wasxfail")
        and os.environ.get(FLAG) == "1"
        and item.get_closest_marker(MARKER) is not None
    ):
        longrepr = report.longrepr
        reason = longrepr[2] if isinstance(longrepr, tuple) and len(longrepr) == 3 else str(longrepr)
        report.outcome = "failed"
        report.longrepr = (
            f"{FLAG}=1: required production-package test {item.nodeid} SKIPPED "
            f"in {report.when} ({reason}); a required gate may never skip (#633, #634, #993)"
        )
    return report

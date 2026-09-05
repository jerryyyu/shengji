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

import pytest

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


@pytest.fixture(autouse=True, scope="session")
def _session_seed_windows(tmp_path_factory):
    """No test may write the committed ``server/runs/seed_windows.json``:
    the whole session registers seed windows in a scratch registry (module-
    and session-scoped fixtures included, which run before any function-
    scoped fixture)."""
    scratch = tmp_path_factory.mktemp("seed-windows") / "seed_windows.json"
    previous = os.environ.get("SHENGJI_SEED_WINDOWS")
    os.environ["SHENGJI_SEED_WINDOWS"] = str(scratch)
    yield scratch
    if previous is None:
        os.environ.pop("SHENGJI_SEED_WINDOWS", None)
    else:
        os.environ["SHENGJI_SEED_WINDOWS"] = previous


@pytest.fixture(autouse=True)
def _scratch_seed_windows(tmp_path, monkeypatch):
    """Each test gets its own fresh scratch registry (read the real ledger
    explicitly through ``shengji.seeds.DEFAULT_REGISTRY`` when wanted)."""
    monkeypatch.setenv("SHENGJI_SEED_WINDOWS", str(tmp_path / "seed_windows.json"))

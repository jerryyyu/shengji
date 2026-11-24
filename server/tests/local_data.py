"""Untracked local data a few CI-excluded test modules read, and the skip they take without it.

Each path in `LOCAL_DATA` is gitignored, so a fresh worktree of clean ``main`` does
not have it; a test that needs one calls `require_local_data` and skips, naming the
file, instead of failing on a missing path.  A path outside `LOCAL_DATA` is the
repository's own input: it must exist, and its absence fails the test, so this helper
can never skip a test whose data the checkout is supposed to carry.

Paths are relative to ``server/``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1]

LOCAL_DATA = {
    "rl_data/highn_corpus_all.jsonl": "the mined high-N corpus (pilot_states SOURCES 'original')",
    "rl_data/highn_late_air.jsonl": "the late-trick corpus (pilot_states SOURCES 'late')",
    "snapshots_v7w/ep02.pt": "the v7w torch checkpoint behind the tracked ep02.npz",
}


def absent_local_data(*paths: str) -> list[str]:
    """The `LOCAL_DATA` entries among ``paths`` that are not on disk.  Any other path
    must exist (AssertionError otherwise)."""
    missing = []
    for path in paths:
        if (SERVER / path).exists():
            continue
        assert path in LOCAL_DATA, f"{path} is not untracked local data and is missing"
        missing.append(path)
    return missing


def require_local_data(*paths: str) -> None:
    """Skip the calling test when an untracked `LOCAL_DATA` input is absent."""
    missing = absent_local_data(*paths)
    if missing:
        pytest.skip("untracked local data absent: " + "; ".join(
            f"server/{p} ({LOCAL_DATA[p]})" for p in missing)
            + " - copy it from a checkout that has it to run this test")

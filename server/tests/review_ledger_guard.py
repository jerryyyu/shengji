"""Fail required PR tests when a branch rewrites the canonical review ledger."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _strict_sha(value: object) -> str:
    assert isinstance(value, str)
    assert len(value) == 40
    assert all(child in "0123456789abcdef" for child in value)
    return value


def assert_byte_prefix(base: bytes, head: bytes) -> None:
    """Require a PR head to preserve every merge-target ledger byte."""
    assert len(head) >= len(base), "PR head review ledger is shorter than base"
    assert head[:len(base)] == base, \
        "PR head review ledger rewrites merge-target bytes"


def _event_pr_shas() -> tuple[str, str] | None:
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not event_path:
        return None
    event = json.loads(Path(event_path).read_text())
    pull_request = event.get("pull_request")
    if pull_request is None:
        return None
    assert isinstance(pull_request, dict)
    base = pull_request.get("base")
    head = pull_request.get("head")
    assert isinstance(base, dict) and isinstance(head, dict)
    return _strict_sha(base.get("sha")), _strict_sha(head.get("sha"))


def _ensure_commit(repo: Path, commit: str) -> None:
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=repo,
        capture_output=True).returncode == 0
    if not exists:
        subprocess.run(
            ["git", "fetch", "--no-tags", "--depth=1", "origin", commit],
            cwd=repo, check=True, capture_output=True)


def _git_blob(repo: Path, commit: str, path: str) -> bytes:
    commit = _strict_sha(commit)
    return subprocess.run(
        ["git", "show", f"{commit}:{path}"], cwd=repo, check=True,
        capture_output=True).stdout


def enforce_pr_head_extends_base(
        repo: Path, *, base_sha: str | None = None,
        head_sha: str | None = None, fetch_missing: bool = True) -> None:
    """Bind the exact PR head ledger to the exact merge-target ledger."""
    if base_sha is None and head_sha is None:
        pair = _event_pr_shas()
        if pair is None:
            return
        base_sha, head_sha = pair
    assert base_sha is not None and head_sha is not None
    base_sha = _strict_sha(base_sha)
    head_sha = _strict_sha(head_sha)
    if fetch_missing:
        _ensure_commit(repo, base_sha)
        _ensure_commit(repo, head_sha)
    assert_byte_prefix(
        _git_blob(repo, base_sha, "HANDOFF_REVIEW.md"),
        _git_blob(repo, head_sha, "HANDOFF_REVIEW.md"),
    )

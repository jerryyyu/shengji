"""The workflow's unconditional review-ledger step guards docs-only PRs.

Docs-only PRs skip every pytest job, so conftest's ledger guard does not run
for them; the `changes` job runs the same guard instead.  These tests execute
that step's exact command from the workflow against synthetic repositories.
"""

from __future__ import annotations

import json
import re
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
WORKFLOW = TESTS.parents[1] / ".github" / "workflows" / "pr-checks.yml"


def _workflow() -> str:
    return WORKFLOW.read_text()


def _guard_command() -> str:
    match = re.search(
        r"\n      - name: Review ledger guard\n"
        r"        working-directory: server/tests\n"
        r"        run: (python3 .+)\n", _workflow())
    assert match, "the changes job has no review-ledger guard step"
    return match.group(1)


def _classifier() -> dict:
    match = re.search(r"python3 - <<'PY'\n(.*?)\n {10}PY\n", _workflow(), re.S)
    assert match, "the changes job has no classifier script"
    source = textwrap.dedent(match.group(1))
    namespace: dict = {}
    exec(source.split("\ntry:\n")[0], namespace)
    return namespace


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def _commit(repo: Path, files: dict[str, str], message: str) -> str:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    _git(repo, "add", *files)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def ledger_repo(tmp_path: Path) -> dict:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    guard = (TESTS / "review_ledger_guard.py").read_text()
    old = _commit(repo, {
        "HANDOFF_REVIEW.md": "REVIEW_A {}\n",
        "README.md": "readme\n",
        "server/tests/review_ledger_guard.py": guard,
    }, "old")
    base = _commit(repo, {"HANDOFF_REVIEW.md": "REVIEW_A {}\nREVIEW_B {}\n"}, "ledger append")
    _git(repo, "checkout", "-q", "-b", "stale", old)
    stale_head = _commit(repo, {"README.md": "readme, edited\n"}, "docs on a stale head")
    _git(repo, "checkout", "-q", "-b", "fresh", base)
    fresh_head = _commit(repo, {"README.md": "readme, edited\n"}, "docs on the current base")
    return {"repo": repo, "base": base, "stale": stale_head, "fresh": fresh_head}


def _changed_paths(repo: Path, base: str, head: str) -> list[str]:
    return _git(repo, "diff", "--name-only", "--no-renames", f"{base}...{head}").splitlines()


def _run_guard(repo: Path, tmp_path: Path, event: dict) -> subprocess.CompletedProcess:
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event))
    command = _guard_command().replace("python3 ", f"{sys.executable} ", 1)
    return subprocess.run(
        ["bash", "-c", command], cwd=repo / "server" / "tests", capture_output=True, text=True,
        env={**os.environ, "GITHUB_EVENT_PATH": str(event_path)})


def _pr_event(base: str, head: str) -> dict:
    return {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}}


def test_docs_only_pr_on_a_stale_head_is_rejected(ledger_repo, tmp_path):
    repo, base, head = ledger_repo["repo"], ledger_repo["base"], ledger_repo["stale"]
    classifier = _classifier()
    paths = _changed_paths(repo, base, head)
    assert paths == ["README.md"]
    assert all(classifier["is_doc"](path) for path in paths), "expected a docs-only classification"
    result = _run_guard(repo, tmp_path, _pr_event(base, head))
    assert result.returncode != 0
    assert "PR head review ledger is shorter than base" in result.stderr


def test_docs_only_pr_on_the_current_base_is_accepted(ledger_repo, tmp_path):
    repo, base, head = ledger_repo["repo"], ledger_repo["base"], ledger_repo["fresh"]
    classifier = _classifier()
    paths = _changed_paths(repo, base, head)
    assert paths == ["README.md"]
    assert all(classifier["is_doc"](path) for path in paths)
    result = _run_guard(repo, tmp_path, _pr_event(base, head))
    assert result.returncode == 0, result.stderr


def test_non_pull_request_events_return_without_checking(ledger_repo, tmp_path):
    result = _run_guard(ledger_repo["repo"], tmp_path, {"ref": "refs/heads/main"})
    assert result.returncode == 0, result.stderr


def test_ledger_rewrite_is_rejected(ledger_repo, tmp_path):
    repo, base = ledger_repo["repo"], ledger_repo["base"]
    _git(repo, "checkout", "-q", "-b", "rewrite", base)
    head = _commit(repo, {"HANDOFF_REVIEW.md": "REVIEW_A {}\nREVIEW_X {}\n"}, "rewrite")
    result = _run_guard(repo, tmp_path, _pr_event(base, head))
    assert result.returncode != 0
    assert "rewrites merge-target bytes" in result.stderr

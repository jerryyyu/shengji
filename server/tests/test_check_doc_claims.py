"""Tests for scripts/check_doc_claims.py."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_doc_claims.py"
_spec = importlib.util.spec_from_file_location("check_doc_claims", SCRIPT)
check = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = check
_spec.loader.exec_module(check)

CURRENT = 46


@pytest.mark.parametrize(
    "line, rule",
    [
        ("Noise is not the lever.", "absolute-claim"),
        ("Wider leads do not help; K=32 does not help either.", "absolute-claim"),
        ("The rerank had no effect on served play.", "absolute-claim"),
        ("This screen proves belief worlds are worthless.", "absolute-claim"),
        ("Search ALWAYS beats the head.", "absolute-claim"),
        ("A deeper horizon never helps.", "absolute-claim"),
        ("The value head matters, not the leads.", "absolute-claim"),
        ("The gain stopped at depth 4.", "absolute-claim"),
        ("Point +0.0168 (wide CI) shows no effect.", "absolute-claim"),
        ("New screens compare vs release 45 as served.", "stale-comparator"),
        ("The comparator is now release 44.", "stale-comparator"),
        ("**Production is release 45** (live).", "stale-comparator"),
        ("Screens currently run against release 38.", "stale-comparator"),
    ],
)
def test_flagged_lines(line, rule):
    assert rule in check.match_line(line, CURRENT)


@pytest.mark.parametrize(
    "line",
    [
        "Belief worlds read +0.0062 [−0.0118, +0.0243]; no effect is resolvable at this size.",
        "PUCT never helps here: −0.417 [-0.45, -0.38] vs release 36.",
        "Noise is not the lever. claim-ok: quoting the retracted sentence",
        "Release 46 read +0.2284 [+0.2046, +0.2521] vs release 45 as served.",
        "New screens compare against release 46 as served.",
        "The previous comparator was release 45.",
        "Release 45 is the rollback; production since release 29 uses pv-search.",
        "**Gen 5 retrains (2026-09-24 to 09-27).** Five retrains of the production head vs release 30.",
        "C12 was inconclusive vs release 42.",
        "Packets built against release 45 are rebuilt.",
        "A release 52 screen compares vs release 47 now.",
        "The kitty holds eight cards.",
        "The machine is always-on in fly.toml.",
    ],
)
def test_allowed_lines(line):
    assert check.match_line(line, CURRENT) == []


def test_escape_needs_a_reason():
    assert check.match_line("Noise is not the lever. claim-ok:", CURRENT) == ["absolute-claim"]


def test_current_release_reads_the_current_production_section():
    deploy = (
        "# Deploy\n\nproduction = release 12 in an old note\n\n## Current production\n\n"
        "**Release 46** (release 45 plus the combo).\n\n## Rollback\n\n**Release 45**\n"
    )
    assert check.current_release(deploy) == 46
    with pytest.raises(ValueError):
        check.current_release("# Deploy\n\n**Release 46**\n")
    with pytest.raises(ValueError):
        check.current_release("## Current production\n\nnone yet\n\n## Rollback\n\n**Release 45**\n")


def test_scan_source_reads_only_added_lines_outside_fences():
    src = "Noise is not the lever.\n```\nalways\n```\nIt does not help.\n"
    assert [(f.line, f.rule) for f in check.scan_source("RL_PLAN.md", src, {1, 2, 3, 4, 5}, CURRENT)] == [
        (1, "absolute-claim"),
        (5, "absolute-claim"),
    ]
    assert check.scan_source("RL_PLAN.md", src, {3}, CURRENT) == []


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_run_checks_only_lines_the_branch_adds(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "DEPLOY.md").write_text("## Current production\n\n**Release 46**\n")
    (repo / "RL_PLAN.md").write_text("Noise is not the lever.\n")
    (repo / "notes.md").write_text("")
    _git(repo, "add", "DEPLOY.md", "RL_PLAN.md", "notes.md")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "branch", "base")
    (repo / "RL_PLAN.md").write_text(
        "Noise is not the lever.\nScreens now compare vs release 45.\nRead +0.01 [-0.01, +0.03].\n"
    )
    (repo / "notes.md").write_text("This proves nothing is outside scope.\n")
    _git(repo, "commit", "-q", "-am", "branch")
    findings = check.run(repo, "base")
    assert [(f.path, f.line, f.rule) for f in findings] == [("RL_PLAN.md", 2, "stale-comparator")]
    assert {(f.path, f.line) for f in check.run(repo, "base", every_line=True)} == {
        ("RL_PLAN.md", 1),
        ("RL_PLAN.md", 2),
    }
    assert check.main(["--repo", str(repo), "--base", "base"]) == 1

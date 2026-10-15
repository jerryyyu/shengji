"""Tests for scripts/check_comment_provenance.py."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_comment_provenance.py"
_spec = importlib.util.spec_from_file_location("check_comment_provenance", SCRIPT)
check = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = check
_spec.loader.exec_module(check)


def rules(path: str, source: str, added: set[int] | None = None) -> list[tuple[int, str]]:
    lines = set(range(1, source.count("\n") + 2)) if added is None else added
    return [(f.line, f.rule) for f in check.scan_source(path, source, lines)]


@pytest.mark.parametrize(
    "comment, rule",
    [
        ("# keep the seed fixed (Codex HOLD on #812)", "attribution"),
        ("# widen the band (Jerry, 2026-08-03)", "attribution"),
        ("# per Codex review the bound is inclusive", "attribution"),
        ("# Jerry's P0 says so", "attribution"),
        ("# #373: joint net", "issue-label"),
        ("# see #707 S17 step 3", "issue-label"),
        ("#932: labels", "issue-label"),
        ("# this used to drop the kitty", "history"),
        ("# Previously the server sent both", "history"),
        ("# fixed until now", "history"),
        ("# decided 2026-09-28 with Jerry", "dated-name"),
        ("# ---- helpers ----", "banner"),
        ("# -- the harness hook ---------", "banner"),
        ("# =========================", "banner"),
    ],
)
def test_python_comment_rules(comment, rule):
    assert rule in [r for _, r in rules("server/shengji/x.py", f"x = 1  {comment}\n")]


@pytest.mark.parametrize(
    "comment",
    [
        "# the kitty holds eight cards because the deck is doubled",
        "# this mask is used to compute legal leads",
        "# values are used to rank candidates",
        "# trump colour wins ties; see test_trump_ties",
        "# released 2026-09-28 as release 45",
        "# the colour #333 matches the felt",
        "# Codex and Jerry share this checkout",
        "# --check exits nonzero on drift",
    ],
)
def test_present_tense_comments_pass(comment):
    assert rules("server/shengji/x.py", f"x = 1  {comment}\n") == []


def test_escape_hatch_on_the_same_line():
    src = "x = 1  # used to be 2 provenance-ok: documents the wire format change\n"
    assert rules("server/shengji/x.py", src) == []
    assert rules("server/shengji/x.py", "x = 1  # used to be 2 provenance-ok:\n") == [(1, "history")]


def test_python_docstrings_and_help_strings_are_checked():
    src = (
        '"""Module.\n'
        "\n"
        "This used to read v6.\n"
        '"""\n'
        "import argparse\n"
        "def f():\n"
        "    '''See #425: joint net.'''\n"
        "    return 'used to'\n"
        "p = argparse.ArgumentParser(description='Screen (Codex audit)')\n"
        "p.add_argument('--x', help=('first part '\n"
        "                            'previously off'))\n"
        "p.add_argument('--y', default='previously')\n"
        "msg = f'used to {p}'\n"
    )
    assert rules("server/scripts/x.py", src) == [
        (3, "history"),
        (7, "issue-label"),
        (9, "attribution"),
        (11, "history"),
    ]


def test_only_added_lines_count():
    src = "a = 1  # used to be 2\nb = 2  # fine\n"
    assert rules("server/shengji/x.py", src, {2}) == []
    assert rules("server/shengji/x.py", src, {1}) == [(1, "history")]


def test_python_fallback_when_tokenize_fails():
    src = 'x = """never closed\n# used to break\n'
    assert rules("server/shengji/x.py", src) == [(2, "history")]


def test_typescript_comments_but_not_strings_or_regex():
    src = (
        "// rejoin used to live here\n"
        "const url = 'http://host/used to';\n"
        "const re = /\\/\\/ used to/;\n"
        "const t = `previously ${url}`;\n"
        "/* first line\n"
        " * (Codex) second line\n"
        " */\n"
        "const half = a / b; // ratio (Jerry)\n"
        "// ---- section ----\n"
    )
    assert rules("web/src/x.ts", src) == [
        (1, "history"),
        (6, "attribution"),
        (8, "attribution"),
        (9, "banner"),
    ]


def test_css_block_comments():
    src = "/* GRID previously */\n.a { content: '//used to'; }\n/* ---- layout ---- */\n"
    assert rules("web/src/index.css", src) == [(1, "history"), (3, "banner")]


def test_shell_comments():
    src = 'echo "# used to"  # previously ran twice\necho ${#arr} # fine\n'
    assert rules("server/scripts/x.sh", src) == [(1, "history")]


def test_added_lines_from_diff():
    diff = (
        "diff --git a/server/shengji/a.py b/server/shengji/a.py\n"
        "--- a/server/shengji/a.py\n"
        "+++ b/server/shengji/a.py\n"
        "@@ -3,0 +4,2 @@ def f():\n"
        "+one\n"
        "+two\n"
        "@@ -10 +12 @@\n"
        "-old\n"
        "+new\n"
        "diff --git a/web/src/gone.ts b/web/src/gone.ts\n"
        "--- a/web/src/gone.ts\n"
        "+++ /dev/null\n"
        "@@ -1 +0,0 @@\n"
        "-x\n"
    )
    assert check.added_lines_from_diff(diff) == {"server/shengji/a.py": {4, 5, 12}}


def test_in_scope():
    assert check.in_scope("server/shengji/ai/x.py")
    assert check.in_scope("web/src/components/Lobby.tsx")
    assert check.in_scope("server/scripts/fleet_status.sh")
    assert not check.in_scope("server/tests/test_x.py")
    assert not check.in_scope("server/scripts/data.json")
    assert not check.in_scope("docs/x.py")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_run_reads_only_the_branch_delta(tmp_path, capsys):
    repo = tmp_path
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    target = repo / "server" / "shengji" / "m.py"
    target.parent.mkdir(parents=True)
    target.write_text("a = 1  # used to be 0 (Codex)\n")
    outside = repo / "server" / "tests" / "test_m.py"
    outside.parent.mkdir(parents=True)
    outside.write_text("")
    _git(repo, "add", "server")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "topic")
    assert check.main(["--repo", str(repo), "--base", "main"]) == 0

    target.write_text("a = 1  # used to be 0 (Codex)\nb = 2  # see #707: board\n")
    outside.write_text("# previously flaky\n")
    _git(repo, "commit", "-q", "-am", "topic")
    assert check.run(repo, "main") == [
        check.Finding("server/shengji/m.py", 2, "issue-label", "# see #707: board")
    ]
    assert check.main(["--repo", str(repo), "--base", "main"]) == 1
    assert "server/shengji/m.py:2: issue-label" in capsys.readouterr().out


def test_the_checker_source_passes_its_own_rules():
    source = SCRIPT.read_text()
    assert check.scan_source("server/scripts/check_comment_provenance.py", source, set(range(1, 10_000))) == []

#!/usr/bin/env python3
"""Refuse absolute claims and stale comparators in doc lines a branch adds.

An inconclusive read is written as its number and interval, not as a law; a
doc that names the champion names the current one.  The check reads only the
lines a branch ADDS (``git diff <base>...HEAD``) in ``DOC_FILES`` and refuses:

* ``absolute-claim``: a phrase from ``ABSOLUTE_PHRASES`` (case-insensitive,
  word-bounded) on a line that cites no confidence interval, i.e. no
  ``[<signed number>, <signed number>]`` such as ``[-0.0118, +0.0243]``.
* ``stale-comparator``: a line that presents release N as the comparator or
  production (``vs release N``, ``comparator ... release N``, ``production is
  release N``) with a present-tense word (``CURRENT_WORDS``) while N is below
  the current production release.  The current release is the ``**Release N**``
  line under ``## Current production`` in ``DEPLOY.md`` at HEAD.  A line with a
  past-tense marker or a date (``HISTORY_WORDS``) or a confidence interval is a
  historical read and keeps its original label.

A line that must keep such text carries ``claim-ok: <reason>`` on the same
line.  Fenced code blocks are skipped.

Usage: ``check_doc_claims.py [--base REF] [--repo DIR] [--all]``; ``--all``
scans every line of the doc files (informational).  Exit 1 lists every refused
line as ``path:line: rule: text``; exit 2 means git failed or the current
release could not be read.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DOC_FILES = ("AI_POLICIES.md", "RL_PLAN.md", "README.md", "DEPLOY.md")

ABSOLUTE_PHRASES = (
    "is not the lever",
    "does not help",
    "no effect",
    "proves",
    "always",
    "never helps",
    "matters, not",
    "stopped at",
)
ABSOLUTE = re.compile(
    r"(?<![\w-])(?:" + "|".join(re.escape(p) for p in ABSOLUTE_PHRASES) + r")(?![\w-])", re.IGNORECASE
)

SIGNED = r"[+\-−–]\s?\d+(?:\.\d+)?"
INTERVAL = re.compile(r"\[\s*" + SIGNED + r"\s*,\s*" + SIGNED + r"\s*\]")
ESCAPE = re.compile(r"claim-ok:\s*\S")

COMPARATOR_PATTERNS = (
    re.compile(r"\b(?:vs\.?|versus|against)\s+release\s+(\d+)", re.IGNORECASE),
    re.compile(r"\bcomparator\b[^.;|]{0,40}?\brelease\s+(\d+)", re.IGNORECASE),
    re.compile(
        r"\b(?:production|served release|current release)\b[\s:*=]*(?:is|remains|stays)?[\s:*=]*release\s+(\d+)",
        re.IGNORECASE,
    ),
)
CURRENT_WORDS = re.compile(r"\b(?:current|currently|now|today|production|served|live)\b", re.IGNORECASE)
HISTORY_WORDS = re.compile(
    r"\b(?:was|were|previous|previously|former|formerly|rollback|since|until|then|historical)\b|\b20\d\d-\d\d-\d\d\b",
    re.IGNORECASE,
)
CURRENT_RELEASE = re.compile(r"^\*\*Release\s+(\d+)\*\*", re.MULTILINE)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    text: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}: {self.text.strip()}"


def current_release(deploy_md: str) -> int:
    """The ``**Release N**`` line that opens ``## Current production``."""
    _, sep, rest = deploy_md.partition("## Current production")
    if not sep:
        raise ValueError("DEPLOY.md has no '## Current production' section")
    section = rest.split("\n## ", 1)[0]
    match = CURRENT_RELEASE.search(section)
    if match is None:
        raise ValueError("'## Current production' names no '**Release N**' line")
    return int(match.group(1))


def match_line(text: str, current: int) -> list[str]:
    """Rule names ``text`` violates against production release ``current``."""
    if ESCAPE.search(text):
        return []
    hits: list[str] = []
    cites_interval = bool(INTERVAL.search(text))
    if ABSOLUTE.search(text) and not cites_interval:
        hits.append("absolute-claim")
    if not cites_interval and CURRENT_WORDS.search(text) and not HISTORY_WORDS.search(text):
        stale = any(
            int(m.group(1)) < current for pattern in COMPARATOR_PATTERNS for m in pattern.finditer(text)
        )
        if stale:
            hits.append("stale-comparator")
    return hits


def _fenced(lines: list[str]) -> set[int]:
    inside, rows = False, set()
    for row, line in enumerate(lines, start=1):
        if line.lstrip().startswith(("```", "~~~")):
            inside = not inside
            rows.add(row)
        elif inside:
            rows.add(row)
    return rows


def scan_source(path: str, source: str, added: set[int], current: int) -> list[Finding]:
    lines = source.splitlines()
    skip = _fenced(lines)
    findings: list[Finding] = []
    for row in sorted(added):
        if row in skip or row - 1 >= len(lines):
            continue
        for rule in match_line(lines[row - 1], current):
            findings.append(Finding(path, row, rule, lines[row - 1]))
    return findings


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def added_lines_from_diff(diff: str) -> dict[str, set[int]]:
    """Map each new-side path in a ``--unified=0`` diff to its added line numbers."""
    added: dict[str, set[int]] = {}
    path: str | None = None
    lineno = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:]
            path = None if target == "/dev/null" else target[2:] if target.startswith("b/") else target
            continue
        if raw.startswith("--- ") or raw.startswith("diff --git "):
            continue
        hunk = _HUNK.match(raw)
        if hunk:
            lineno = int(hunk.group(1))
            continue
        if path is None:
            continue
        if raw.startswith("+"):
            added.setdefault(path, set()).add(lineno)
            lineno += 1
        elif raw.startswith(" "):
            lineno += 1
    return added


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def run(repo: Path, base: str, *, every_line: bool = False) -> list[Finding]:
    current = current_release(_git(repo, "show", "HEAD:DEPLOY.md"))
    if every_line:
        present = _git(repo, "ls-tree", "--name-only", "HEAD", "--", *DOC_FILES).split()
        targets = {
            path: set(range(1, len(_git(repo, "show", f"HEAD:{path}").splitlines()) + 1)) for path in present
        }
    else:
        diff = _git(
            repo, "diff", "--unified=0", "--no-color", "--no-ext-diff", "--diff-filter=AMR",
            f"{base}...HEAD", "--", *DOC_FILES,
        )
        targets = added_lines_from_diff(diff)
    findings: list[Finding] = []
    for path, added in sorted(targets.items()):
        if path not in DOC_FILES:
            continue
        findings.extend(scan_source(path, _git(repo, "show", f"HEAD:{path}"), added, current))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", default="origin/main", help="ref the branch is compared against (merge base)")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2], help="repository root")
    parser.add_argument("--all", action="store_true", help="scan every line of the doc files, not only added ones")
    args = parser.parse_args(argv)
    try:
        findings = run(args.repo, args.base, every_line=args.all)
    except subprocess.CalledProcessError as exc:
        print(f"check_doc_claims: git failed: {exc.stderr.strip()}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"check_doc_claims: cannot read the current release: {exc}", file=sys.stderr)
        return 2
    for finding in findings:
        print(finding.render())
    if findings:
        print(
            f"\n{len(findings)} doc line(s) state an absolute claim without an interval or name a stale"
            " comparator as current. Write the number and its interval, or name the current release; a"
            " line that must keep the wording takes 'claim-ok: <reason>'.",
            file=sys.stderr,
        )
        return 1
    print("check_doc_claims: no absolute claims or stale comparators in the scanned doc lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())

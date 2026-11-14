#!/usr/bin/env python3
"""Refuse a UI flow change that leaves the flow map untouched.

The player's flows are written down once, in ``docs/design/FLOWS.md`` and the
drawn mock ``docs/design/mocks/core.py``.  A branch changes a flow when it

* adds a non-test ``.tsx`` file under ``web/src/components/``,
  ``web/src/queue/`` or ``web/src/home/`` (a new component is where a new
  surface or path starts), or
* changes an entry of one of the literal lists in ``web/src/flows.test.ts``
  (``SURFACES``, ``LEAVE_SITES``, ``JOIN_SITES``, ``PANEL_VIEW_SITES``);
  rewording an entry's comment is not a change.

Such a branch must also touch ``docs/design/FLOWS.md`` or
``docs/design/mocks/core.py`` (``git diff <base>...HEAD``), so the review
reads the flow, not only the delta.  A line ``flow-ok: <reason>`` in the PR
body (``--body-env``, the name of an environment variable holding it) or in
any commit message on the branch waives the check.

Usage: ``check_flow_map.py [--base REF] [--repo DIR] [--body-env NAME]``;
exit 1 names each trigger.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

COMPONENT_ROOTS = ("web/src/components/", "web/src/queue/", "web/src/home/")
FLOWS_TEST = "web/src/flows.test.ts"
LITERALS = ("SURFACES", "LEAVE_SITES", "JOIN_SITES", "PANEL_VIEW_SITES")
FLOW_MAP = ("docs/design/FLOWS.md", "docs/design/mocks/core.py")
WAIVER = re.compile(r"^[ \t]*flow-ok:[ \t]*\S", re.MULTILINE)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def is_new_component(path: str) -> bool:
    return (
        path.startswith(COMPONENT_ROOTS)
        and path.endswith(".tsx")
        and not path.endswith(".test.tsx")
    )


def literal_entries(source: str, name: str) -> list[str] | None:
    """The string entries of ``const <name> = [...]``, comments ignored; None when absent."""
    match = re.search(r"\bconst\s+" + name + r"\b[^=]*=\s*\[(.*?)\];", source, re.DOTALL)
    if match is None:
        return None
    body = re.sub(r"//[^\n]*", "", match.group(1))
    return [a or b for a, b in re.findall(r"\"([^\"]*)\"|'([^']*)'", body)]


def changed_literals(before: str, after: str) -> list[str]:
    return [n for n in LITERALS if literal_entries(before, n) != literal_entries(after, n)]


def _show(repo: Path, rev: str, path: str) -> str:
    try:
        return _git(repo, "show", f"{rev}:{path}")
    except subprocess.CalledProcessError:
        return ""


def triggers(repo: Path, base: str) -> tuple[list[str], set[str]]:
    """What in the branch changes a flow, and every path the branch touches."""
    merge_base = _git(repo, "merge-base", base, "HEAD").strip()
    touched = set(_git(repo, "diff", "--name-only", "--no-renames", f"{merge_base}...HEAD").split())
    added = _git(repo, "diff", "--name-only", "--diff-filter=AC", "--no-renames", f"{merge_base}...HEAD").split()
    found = [f"new component {p}" for p in sorted(added) if is_new_component(p)]
    if FLOWS_TEST in touched:
        for name in changed_literals(_show(repo, merge_base, FLOWS_TEST), _show(repo, "HEAD", FLOWS_TEST)):
            found.append(f"{FLOWS_TEST}: {name} changed")
    return found, touched


def waived(repo: Path, base: str, body: str) -> bool:
    if WAIVER.search(body):
        return True
    log = _git(repo, "log", "--format=%B", f"{base}..HEAD")
    return bool(WAIVER.search(log))


def run(repo: Path, base: str, body: str = "") -> list[str]:
    """The triggers left unanswered: empty when the map is touched, waived, or nothing changed."""
    found, touched = triggers(repo, base)
    if not found or touched & set(FLOW_MAP) or waived(repo, base, body):
        return []
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", default="origin/main", help="ref the branch is compared against (merge base)")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2], help="repository root")
    parser.add_argument("--body-env", default="", help="environment variable holding the PR body")
    args = parser.parse_args(argv)
    body = os.environ.get(args.body_env, "") if args.body_env else ""
    try:
        unanswered = run(args.repo, args.base, body)
    except subprocess.CalledProcessError as exc:
        print(f"check_flow_map: git failed: {exc.stderr.strip()}", file=sys.stderr)
        return 2
    for item in unanswered:
        print(item)
    if unanswered:
        print(
            f"\nThis branch changes a player flow but touches neither {' nor '.join(FLOW_MAP)}. Edit the"
            " flow's line there (a reversal edits the old line), or add 'flow-ok: <reason>' to the PR"
            " body or a commit message.",
            file=sys.stderr,
        )
        return 1
    print("check_flow_map: flow map in step with the branch")
    return 0


if __name__ == "__main__":
    sys.exit(main())

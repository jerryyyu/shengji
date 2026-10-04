#!/usr/bin/env python3
"""Fail when a server test module is selected by no CI job.

CI selects Python tests by explicit paths in the GitHub workflow files (and in
shell scripts those workflows invoke).  A new ``tests/test_*.py`` file runs in
CI only if someone lists it, so this check is a ratchet: every
``server/tests/**/test_*.py`` file must either be selected by the workflow text
or be listed in ``server/tests/ci_selection_exclusions.txt``.

Detection (stdlib only, deliberately textual):

* Every ``.github/workflows/*.yml``/``*.yaml`` file is scanned after stripping
  ``#`` comments.  Tokens shaped like ``tests/<name>.py`` or
  ``server/tests/<name>.py`` select that file; tokens with ``*``, ``?`` or
  ``[...]`` are expanded as globs against the tree.  Workflow steps run with
  ``working-directory: server``, so ``tests/...`` resolves under ``server/``.
* A directory argument selects every test module under it: ``tests/`` anywhere,
  or bare ``tests`` on a line that also says ``pytest`` (so prose such as a step
  named "Run tests" does not count).
* Shell scripts referenced as ``scripts/<name>.sh`` or ``server/scripts/<name>.sh``
  are scanned the same way, recursively.  Python scripts are NOT scanned
  (their source would contain path-shaped strings that are not selections).

Not modelled: pytest ``-k``/``-m``/``--deselect``/``--ignore`` and skip markers
(a selected file may still run zero tests), shell brace expansion, and paths
built from variables at run time.

Failures:
  (a) a test module neither selected nor excluded;
  (b) a stale exclusion (the file is now selected, or no longer exists);
  (c) a workflow/script test reference that matches no file.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

EXCLUSIONS_REL = "server/tests/ci_selection_exclusions.txt"
SERVER_DIR = "server"

_PATH_CHARS = r"[A-Za-z0-9_.*?\[\]/-]"
TEST_TOKEN = re.compile(rf"(?<![A-Za-z0-9_./-])((?:server/)?tests/{_PATH_CHARS}*?\.py)(?![A-Za-z0-9_])")
TEST_DIR_TOKEN = re.compile(r"(?<![A-Za-z0-9_./-])((?:server/)?tests)/?(?=\s|$|[\"'])")
TEST_DIR_SLASH_TOKEN = re.compile(r"(?<![A-Za-z0-9_./-])((?:server/)?tests)/(?=\s|$|[\"'])")
SCRIPT_TOKEN = re.compile(r"(?<![A-Za-z0-9_./-])((?:server/)?scripts/[A-Za-z0-9_./-]+\.sh)(?![A-Za-z0-9_])")
GLOB_CHARS = set("*?[")


def strip_comments(text: str) -> str:
    """Remove YAML/shell ``#`` comments (whole-line and `` #`` inline)."""
    out = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        out.append(re.split(r"\s#", line, maxsplit=1)[0])
    return "\n".join(out)


def _server_rel(token: str) -> str:
    """Normalise a token to a path relative to ``server/``."""
    return token[len("server/") :] if token.startswith("server/") else token


def all_test_files(root: Path) -> set[str]:
    tests = root / SERVER_DIR / "tests"
    return {p.relative_to(root).as_posix() for p in tests.rglob("test_*.py") if p.is_file()}


def collect_selection(root: Path) -> tuple[set[str], list[str], list[str]]:
    """Return (selected repo-relative paths, scanned sources, dangling refs)."""
    server = root / SERVER_DIR
    selected: set[str] = set()
    dangling: list[str] = []
    scanned: list[str] = []
    wf_dir = root / ".github" / "workflows"
    queue = sorted([*wf_dir.glob("*.yml"), *wf_dir.glob("*.yaml")])
    seen: set[Path] = set()
    while queue:
        source = queue.pop(0).resolve()
        if source in seen:
            continue
        seen.add(source)
        scanned.append(source.relative_to(root.resolve()).as_posix())
        text = strip_comments(source.read_text(encoding="utf-8"))
        label = scanned[-1]
        for token in TEST_TOKEN.findall(text):
            rel = _server_rel(token)
            if GLOB_CHARS & set(rel):
                matches = [p for p in server.glob(rel) if p.is_file()]
            else:
                matches = [server / rel] if (server / rel).is_file() else []
            if not matches:
                dangling.append(f"{label}: {token}")
            selected.update(p.relative_to(root).as_posix() for p in matches)
        dir_tokens = set(TEST_DIR_SLASH_TOKEN.findall(text))
        for line in text.splitlines():
            if "pytest" in line:
                dir_tokens.update(TEST_DIR_TOKEN.findall(line))
        for token in sorted(dir_tokens):
            tests_dir = server / _server_rel(token)
            if tests_dir.is_dir():
                selected.update(
                    p.relative_to(root).as_posix() for p in tests_dir.rglob("test_*.py") if p.is_file()
                )
        for token in SCRIPT_TOKEN.findall(text):
            script = server / _server_rel(token)
            if script.is_file():
                queue.append(script)
            else:
                dangling.append(f"{label}: {token}")
    return selected, scanned, dangling


def read_exclusions(path: Path) -> list[str]:
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            entries.append(entry)
    return entries


def run(root: Path, *, print_unselected: bool = False) -> int:
    tests = all_test_files(root)
    selected, scanned, dangling = collect_selection(root)
    selected_tests = selected & tests
    exclusions = read_exclusions(root / EXCLUSIONS_REL)
    excluded = set(exclusions)

    unselected = sorted(tests - selected_tests)
    if print_unselected:
        print("\n".join(unselected))
        return 0

    missing = sorted(set(unselected) - excluded)
    stale_selected = sorted(excluded & selected_tests)
    stale_gone = sorted(excluded - tests)
    duplicates = sorted({e for e in exclusions if exclusions.count(e) > 1})

    ok = not (missing or stale_selected or stale_gone or duplicates or dangling)
    if missing:
        print(f"FAIL: {len(missing)} test file(s) selected by no CI job and not excluded:")
        for path in missing:
            print(f"  {path}")
        print(
            "  -> add each to a pytest step in .github/workflows/pr-checks.yml, or (with a reason)"
            f" to {EXCLUSIONS_REL}"
        )
    if stale_selected:
        print(f"FAIL: {len(stale_selected)} exclusion(s) are now selected by CI; delete these lines:")
        for path in stale_selected:
            print(f"  {path}")
    if stale_gone:
        print(f"FAIL: {len(stale_gone)} exclusion(s) name no existing test file; delete these lines:")
        for path in stale_gone:
            print(f"  {path}")
    if duplicates:
        print(f"FAIL: duplicate exclusion line(s): {', '.join(duplicates)}")
    if dangling:
        print(f"FAIL: {len(dangling)} CI reference(s) match no file:")
        for ref in dangling:
            print(f"  {ref}")
    print(
        f"ci-test-selection: {'OK' if ok else 'FAIL'} total={len(tests)} selected={len(selected_tests)}"
        f" excluded={len(excluded & tests)} unselected_unexcluded={len(missing)}"
        f" stale={len(stale_selected) + len(stale_gone)} sources={','.join(scanned)}"
    )
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    default_root = Path(__file__).resolve().parents[2]
    parser.add_argument("--root", type=Path, default=default_root, help="repository root")
    parser.add_argument(
        "--print-unselected", action="store_true", help="print every unselected test file and exit 0"
    )
    args = parser.parse_args(argv)
    return run(args.root, print_unselected=args.print_unselected)


if __name__ == "__main__":
    sys.exit(main())

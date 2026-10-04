#!/usr/bin/env python3
"""Fail when a server test module is selected by no CI job.

CI selects Python tests by explicit paths in the GitHub workflow files (and in
shell scripts those workflows invoke).  A new ``tests/test_*.py`` file runs in
CI only if someone lists it, so this check is a ratchet: every
``server/tests/**/test_*.py`` file must either be selected by the workflow text
or be listed in ``server/tests/ci_selection_exclusions.txt``.

Detection (stdlib only, no YAML library; an indentation-based extractor):

* Only EXECUTED text counts.  From every ``.github/workflows/*.yml``/``*.yaml``
  the check takes the value of each ``run:`` key (single-line, or a ``|``/``>``
  block scalar delimited by indentation).  Step names, ``on:`` path filters,
  ``env:``, ``if:`` and every other field are ignored.
* ``${{ matrix.<key> }}`` inside a ``run:`` value is replaced by every value of
  that job's ``strategy.matrix.<key>`` list.  A matrix key no ``run:`` value
  references selects nothing.
* Each run value is split into command lines (folded ``>`` blocks are one
  line, backslash continuations are joined, shell comments are stripped), and
  each line into simple commands at ``;``, ``&&``, ``||``, ``|``, ``&`` and
  parentheses, with shell quoting (``shlex``).  Only a simple command whose
  program is pytest selects tests: ``pytest``, ``python[3] [opts] -m pytest``,
  ``python[3] [opts] scripts/test_checkout.py [opts] -- <pytest args>``,
  optionally behind ``VAR=value`` prefixes, ``env [-u NAME] [VAR=value]`` and
  ``uv run [opts]``.  Only that command's own arguments after pytest count, so
  ``echo "pytest tests/x.py"`` or a sibling ``echo tests/x.py`` selects
  nothing.  An argument ``tests/<name>.py`` or ``server/tests/<name>.py``
  (optionally ``::node``) selects that file, one with ``*``, ``?`` or ``[...]``
  is expanded as a glob, and ``tests``/``tests/`` selects every module under
  it; the values of ``--ignore``/``--ignore-glob``/``--deselect`` select
  nothing.  Paths resolve under ``server/`` (the steps' working directory).
  A line that mentions pytest (or the wrapper) but cannot be tokenized fails
  the check.
* A shell script ``scripts/<name>.sh`` or ``server/scripts/<name>.sh`` is
  followed (recursively), and its command lines treated the same way, only
  when a simple command executes it: as the program (optionally ``./``), as
  the operand of ``bash``/``sh`` [options], or of ``source``/``.``.  A script
  path that is merely an argument (``echo scripts/x.sh``) is not followed.  Python scripts are NOT followed.

Not modelled: pytest ``-k``/``-m``/``--deselect``/``--ignore`` and skip markers
(a selected file may still run zero tests), step/job ``if:`` conditions,
``matrix.include``/``exclude``, shell brace expansion, and paths built from
shell variables at run time.

Failures:
  (a) a test module neither selected nor excluded;
  (b) a stale exclusion (the file is now selected, or no longer exists);
  (c) a workflow/script test reference that matches no file;
  (d) a command line mentioning pytest that cannot be tokenized.
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from pathlib import Path

EXCLUSIONS_REL = "server/tests/ci_selection_exclusions.txt"
SERVER_DIR = "server"

TEST_ARG = re.compile(r"((?:server/)?tests/[A-Za-z0-9_.*?\[\]/-]*\.py)(?:::.*)?")
TEST_DIR_ARG = re.compile(r"((?:server/)?tests)/?")
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")
SHELL_PUNCTUATION = ";&|()"
# Options whose value is the next argument, per wrapper.
ENV_VALUE_OPTS = {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}
UV_RUN_VALUE_OPTS = {
    "--with", "--with-editable", "--with-requirements", "--python", "-p", "--group", "--extra",
    "--package", "--directory", "--project", "--env-file", "--index", "--index-url", "--only-group",
}
PYTHON_VALUE_OPTS = {"-W", "-X"}
CHECKOUT_WRAPPER = "scripts/test_checkout.py"
PYTEST_NON_SELECTING_OPTS = {"--ignore", "--ignore-glob", "--deselect"}
SCRIPT_TOKEN = re.compile(r"(?<![A-Za-z0-9_./-])((?:server/)?scripts/[A-Za-z0-9_./-]+\.sh)(?![A-Za-z0-9_])")
PYTEST = re.compile(r"(?<![A-Za-z0-9_])pytest(?![A-Za-z0-9_])")
MATRIX_REF = re.compile(r"\$\{\{\s*matrix\.([A-Za-z0-9_-]+)\s*\}\}")
KEY_LINE = re.compile(r"^(\s*)(?:-\s+)?([A-Za-z0-9_-]+):(?:\s+(.*?))?\s*$")
BLOCK_INDICATOR = re.compile(r"^([|>])[+-]?[0-9]?\s*(?:#.*)?$")
GLOB_CHARS = set("*?[")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _key_column(line: str) -> int:
    """Column of the key on a ``key:`` or ``- key:`` line."""
    stripped = line.lstrip(" ")
    col = _indent(line)
    if stripped.startswith("- "):
        col += 2 + _indent(stripped[2:])
    return col


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _strip_yaml_comment(value: str) -> str:
    return re.split(r"\s#", value, maxsplit=1)[0].strip()


def _block_under(lines: list[str], i: int, col: int) -> tuple[list[str], int]:
    """Lines after index ``i`` indented deeper than ``col`` (blank lines kept)."""
    body = []
    j = i + 1
    while j < len(lines):
        line = lines[j]
        if line.strip() and _indent(line) <= col:
            break
        body.append(line)
        j += 1
    while body and not body[-1].strip():
        body.pop()
    return body, j


def _dedent(body: list[str]) -> list[str]:
    width = min((_indent(l) for l in body if l.strip()), default=0)
    return [l[width:] for l in body]


def _scalar(lines: list[str], i: int, col: int, inline: str) -> str:
    """Value of the key on line ``i`` whose inline text is ``inline``."""
    indicator = BLOCK_INDICATOR.match(inline)
    body, _ = _block_under(lines, i, col)
    if indicator:
        text = _dedent(body)
        if indicator.group(1) == ">":
            # Folded: lines at the base indentation join with spaces; blank and
            # more-indented lines keep their newlines.
            out, prev_plain = [], False
            for line in text:
                plain = bool(line.strip()) and not line.startswith((" ", "\t"))
                if out and plain and prev_plain:
                    out[-1] += " " + line
                else:
                    out.append(line)
                prev_plain = plain
            return "\n".join(out)
        return "\n".join(text)
    value = _strip_yaml_comment(inline)
    continuation = " ".join(l.strip() for l in body if l.strip())  # plain multi-line scalar
    return _unquote((value + " " + continuation).strip())


def _job_blocks(lines: list[str]) -> list[list[str]]:
    """Each job under the top-level ``jobs:`` key, as its own list of lines."""
    for i, line in enumerate(lines):
        if re.match(r"^jobs:\s*(#.*)?$", line):
            body, _ = _block_under(lines, i, 0)
            break
    else:
        return []
    jobs: list[list[str]] = []
    job_col = min((_indent(l) for l in body if l.strip() and not l.lstrip().startswith("#")), default=0)
    for line in body:
        if line.strip() and _indent(line) == job_col and not line.lstrip().startswith("#"):
            jobs.append([])
        if jobs:
            jobs[-1].append(line)
    return jobs


def _matrix_values(job: list[str]) -> dict[str, list[str]]:
    """``strategy.matrix.<key>`` list values of one job (inline or block lists)."""
    values: dict[str, list[str]] = {}
    for i, line in enumerate(job):
        m = KEY_LINE.match(line)
        if not (m and m.group(2) == "matrix" and not (m.group(3) or "").strip()):
            continue
        matrix_body, _ = _block_under(job, i, _key_column(line))
        child_col = min((_indent(l) for l in matrix_body if l.strip()), default=0)
        for k, child in enumerate(matrix_body):
            km = KEY_LINE.match(child)
            if not km or _indent(child) != child_col or child.lstrip().startswith("-"):
                continue
            inline = _strip_yaml_comment(km.group(3) or "")
            if inline.startswith("[") and inline.endswith("]"):
                items = [_unquote(v) for v in inline[1:-1].split(",") if v.strip()]
            elif inline:
                items = [_unquote(inline)]
            else:
                sub, _ = _block_under(matrix_body, k, child_col)
                items = [
                    _unquote(_strip_yaml_comment(l.strip()[2:]))
                    for l in sub
                    if l.strip().startswith("- ")
                ]
            values.setdefault(km.group(2), []).extend(items)
    return values


def run_values(workflow_text: str) -> list[str]:
    """Text of every ``run:`` value in the jobs, with matrix references expanded."""
    lines = workflow_text.splitlines()
    out: list[str] = []
    for job in _job_blocks(lines):
        matrix = _matrix_values(job)
        for i, line in enumerate(job):
            m = KEY_LINE.match(line)
            if not m or m.group(2) != "run" or line.lstrip().startswith("#"):
                continue
            text = _scalar(job, i, _key_column(line), m.group(3) or "")
            out.append(MATRIX_REF.sub(lambda r: " ".join(matrix.get(r.group(1), [r.group(0)])), text))
    return out


def command_lines(shell_text: str) -> list[str]:
    """Shell command lines: comments stripped, backslash continuations joined."""
    out: list[str] = []
    pending = ""
    for raw in shell_text.splitlines():
        line = raw if not raw.lstrip().startswith("#") else ""
        line = re.split(r"(?:^|\s)#", line, maxsplit=1)[0] if "#" in line else line
        if line.rstrip().endswith("\\"):
            pending += line.rstrip()[:-1] + " "
            continue
        out.append(pending + line)
        pending = ""
    if pending:
        out.append(pending)
    return [l for l in out if l.strip()]


def simple_commands(line: str) -> list[list[str]]:
    """Argument vectors of the simple commands on one shell line.

    Raises ``ValueError`` when the line cannot be tokenized (unbalanced quote).
    """
    lexer = shlex.shlex(line, posix=True, punctuation_chars=SHELL_PUNCTUATION)
    lexer.whitespace_split = True
    commands: list[list[str]] = [[]]
    for word in lexer:
        if word and set(word) <= set(SHELL_PUNCTUATION):
            commands.append([])
        else:
            commands[-1].append(word)
    return [c for c in commands if c]


def _skip_options(words: list[str], i: int, value_opts: set[str]) -> int:
    while i < len(words) and words[i].startswith("-") and words[i] != "-m":
        i += 2 if words[i] in value_opts else 1
    return i


def pytest_arguments(words: list[str]) -> list[str] | None:
    """Arguments after pytest when ``words`` runs pytest, else None."""
    i = 0
    while True:
        while i < len(words) and ASSIGNMENT.fullmatch(words[i]):
            i += 1
        if i < len(words) and words[i] == "env":
            i = _skip_options(words, i + 1, ENV_VALUE_OPTS)
            continue
        if words[i : i + 2] == ["uv", "run"]:
            i = _skip_options(words, i + 2, UV_RUN_VALUE_OPTS)
            continue
        break
    if i >= len(words):
        return None
    if words[i : i + 2] == ["-m", "pytest"]:  # uv run -m pytest
        return words[i + 2 :]
    program = words[i].rsplit("/", 1)[-1]
    if program == "pytest":
        return words[i + 1 :]
    if re.fullmatch(r"python(?:3(?:\.[0-9]+)?)?", program):
        j = i + 1
        while j < len(words) and words[j].startswith("-") and words[j] != "-m":
            if words[j] == "-c" or words[j] == "-" or words[j].startswith("-c"):
                return None  # -c / stdin end the interpreter's options; the rest is the program's argv
            j += 2 if words[j] in PYTHON_VALUE_OPTS else 1
        if words[j : j + 2] == ["-m", "pytest"]:
            return words[j + 2 :]
        if j < len(words) and words[j].endswith(CHECKOUT_WRAPPER):
            # The checkout-safe wrapper forwards everything after ``--`` to pytest.
            rest = words[j + 1 :]
            return rest[rest.index("--") + 1 :] if "--" in rest else []
    return None


def executed_script(words: list[str]) -> str | None:
    """The ``scripts/*.sh`` path this command executes, else None.

    Executed means the script is the program (``scripts/x.sh``,
    ``./scripts/x.sh``), the operand of ``bash``/``sh`` (after options), or of
    ``source``/``.``.  A path that is merely an argument (``echo scripts/x.sh``)
    is not followed.
    """
    i = 0
    while i < len(words) and ASSIGNMENT.fullmatch(words[i]):
        i += 1
    if i < len(words) and words[i] == "env":
        i = _skip_options(words, i + 1, ENV_VALUE_OPTS)
        while i < len(words) and ASSIGNMENT.fullmatch(words[i]):
            i += 1
    if i >= len(words):
        return None
    program = words[i]
    if program in ("bash", "sh", "source", "."):
        i = _skip_options(words, i + 1, set()) if program in ("bash", "sh") else i + 1
        if i >= len(words):
            return None
        program = words[i]
    program = program[2:] if program.startswith("./") else program
    m = SCRIPT_TOKEN.fullmatch(program)
    return m.group(1) if m else None


def _selecting_arguments(args: list[str]) -> list[str]:
    out: list[str] = []
    skip = False
    for arg in args:
        if skip:
            skip = False
        elif arg in PYTEST_NON_SELECTING_OPTS:
            skip = True
        elif not arg.startswith("-"):
            out.append(arg)
    return out


def _server_rel(token: str) -> str:
    """Normalise a token to a path relative to ``server/``."""
    return token[len("server/") :] if token.startswith("server/") else token


def all_test_files(root: Path) -> set[str]:
    tests = root / SERVER_DIR / "tests"
    return {p.relative_to(root).as_posix() for p in tests.rglob("test_*.py") if p.is_file()}


def collect_selection(root: Path) -> tuple[set[str], list[str], list[str], list[str]]:
    """Return (selected repo-relative paths, scanned sources, dangling refs, untokenizable lines)."""
    server = root / SERVER_DIR
    selected: set[str] = set()
    dangling: list[str] = []
    unparsed: list[str] = []
    scanned: list[str] = []
    wf_dir = root / ".github" / "workflows"
    queue = sorted([*wf_dir.glob("*.yml"), *wf_dir.glob("*.yaml")])
    seen: set[Path] = set()
    while queue:
        source = queue.pop(0).resolve()
        if source in seen:
            continue
        seen.add(source)
        label = source.relative_to(root.resolve()).as_posix()
        scanned.append(label)
        raw = source.read_text(encoding="utf-8")
        shell_texts = run_values(raw) if source.suffix in (".yml", ".yaml") else [raw]
        for shell_text in shell_texts:
            for line in command_lines(shell_text):
                mentions_script = bool(re.search(r"scripts/\S*\.sh", line))
                mentions_pytest = bool(PYTEST.search(line) or CHECKOUT_WRAPPER in line)
                if not (mentions_script or mentions_pytest):
                    continue
                try:
                    commands = simple_commands(line)
                except ValueError:
                    unparsed.append(f"{label}: {line.strip()}")
                    continue
                for words in commands:
                    token = executed_script(words)
                    if token is None:
                        continue
                    script = server / _server_rel(token)
                    if script.is_file():
                        queue.append(script)
                    else:
                        dangling.append(f"{label}: {token}")
                if not mentions_pytest:
                    continue
                for words in commands:
                    args = pytest_arguments(words)
                    for arg in _selecting_arguments(args or []):
                        if m := TEST_ARG.fullmatch(arg):
                            rel = _server_rel(m.group(1))
                            if GLOB_CHARS & set(rel):
                                matches = [p for p in server.glob(rel) if p.is_file()]
                            else:
                                matches = [server / rel] if (server / rel).is_file() else []
                            if not matches:
                                dangling.append(f"{label}: {arg}")
                            selected.update(p.relative_to(root).as_posix() for p in matches)
                        elif m := TEST_DIR_ARG.fullmatch(arg):
                            tests_dir = server / _server_rel(m.group(1))
                            if tests_dir.is_dir():
                                selected.update(
                                    p.relative_to(root).as_posix()
                                    for p in tests_dir.rglob("test_*.py")
                                    if p.is_file()
                                )
    return selected, scanned, dangling, unparsed


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
    selected, scanned, dangling, unparsed = collect_selection(root)
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

    ok = not (missing or stale_selected or stale_gone or duplicates or dangling or unparsed)
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
    if unparsed:
        print(f"FAIL: {len(unparsed)} pytest command line(s) could not be tokenized:")
        for ref in unparsed:
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

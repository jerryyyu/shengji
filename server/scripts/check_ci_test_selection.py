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

Engine modes (the two-engine rule, added after #888/#891):

A test module that imports the engine boundary must be selected by at least
one PURE-engine pytest command and at least one COMPILED-engine pytest command,
or be listed with a reason in ``server/tests/ci_engine_mode_exclusions.txt``
(a ratchet like the selection exclusions).  Modules already listed in
``ci_selection_exclusions.txt`` (selected by no job) are exempt here.

* The engine boundary is the core set ``shengji.engine.legal``,
  ``shengji.engine.fast`` and ``shengji.engine._fast`` (the modules
  ``SHENGJI_FAST=1`` reroutes through the Cython kernels), plus every
  ``shengji.luna.benchmark_*`` module whose own source imports a core module
  (today benchmark_games/legacy_evidence/policy/rollout_proof/rollouts; the set
  is derived, so a new benchmark module that calls engine legality joins it).
  ``shengji.engine.combos``/``cards`` are rerouted too but imported almost
  everywhere; they are deliberately outside the set.
* A test module imports the boundary when its AST contains ``import M``,
  ``from M import ...``, ``from P import name`` with ``P.name`` == M, or a call
  ``import_module("M")``/``importorskip("M")``/``__import__("M")`` with a
  string-literal M.  Transitive imports (through helpers or conftest) are not
  followed.
* Each pytest command gets an engine mode.  The base is the ``SHENGJI_FAST``
  value of the step ``env:``, else the job ``env:``, else the workflow
  ``env:`` (unset = pure; ``"1"`` = compiled, as in ``shengji/__init__.py``;
  any other ``${{ }}`` expression = unknown).  Then, in order through the run
  text: ``export SHENGJI_FAST=v``/``SHENGJI_FAST=v`` set it, ``unset
  SHENGJI_FAST`` clears it; per command, a ``SHENGJI_FAST=v`` prefix, ``env
  [-u SHENGJI_FAST] [SHENGJI_FAST=v]`` and ``scripts/test_checkout.py --engine
  pure|compiled`` (which wins) apply.  A followed script inherits the mode of
  the command that executes it.  Matrix jobs are expanded per combination of
  the matrix keys a step references, so ``if [ "<lit>" = "<lit>" ]; then ...
  else ... fi`` on substituted literals is decided; a branch not taken, or an
  undecidable condition, gives its commands no engine credit.  Heredoc bodies
  are skipped for mode tracking.  Unknown modes earn no credit (fail closed).

Failures:
  (a) a test module neither selected nor excluded;
  (b) a stale exclusion (the file is now selected, or no longer exists);
  (c) a workflow/script test reference that matches no file;
  (d) a command line mentioning pytest that cannot be tokenized;
  (e) an engine-boundary test module (not selection-excluded) that lacks a pure
      or a compiled selection and is not listed in the engine-mode exclusions;
  (f) a stale engine-mode exclusion (the file is gone, no longer imports the
      boundary, is selection-excluded, or is now selected in both modes);
  (g) a test module that cannot be parsed for its imports.
"""

from __future__ import annotations

import argparse
import ast
import itertools
import re
import shlex
import sys
from pathlib import Path

EXCLUSIONS_REL = "server/tests/ci_selection_exclusions.txt"
ENGINE_EXCLUSIONS_REL = "server/tests/ci_engine_mode_exclusions.txt"
SERVER_DIR = "server"

ENGINE_CORE_MODULES = frozenset({"shengji.engine.legal", "shengji.engine.fast", "shengji.engine._fast"})
BENCHMARK_PACKAGE = "shengji.luna"
BENCHMARK_GLOB = "benchmark_*.py"
DYNAMIC_IMPORTERS = {"import_module", "importorskip", "__import__"}
ENGINE_VAR = "SHENGJI_FAST"
PURE, COMPILED, UNKNOWN = "pure", "compiled", "unknown"
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

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


def _env_text(lines: list[str], col: int) -> str | None:
    """Raw ``SHENGJI_FAST`` text of the ``env:`` key at column ``col`` in ``lines``.

    Returns None when that ``env:`` does not name the variable, and the whole
    inline value when ``env:`` is an inline mapping that mentions it (which the
    caller cannot decide, so it classifies as unknown).
    """
    for i, line in enumerate(lines):
        m = KEY_LINE.match(line)
        if not m or m.group(2) != "env" or _key_column(line) != col or line.lstrip().startswith("#"):
            continue
        inline = _strip_yaml_comment(m.group(3) or "")
        if inline:
            return "${{ inline env }}" if ENGINE_VAR in inline else None
        body, _ = _block_under(lines, i, col)
        child_col = min((_indent(l) for l in body if l.strip()), default=0)
        for child in body:
            km = KEY_LINE.match(child)
            if km and _indent(child) == child_col and km.group(2) == ENGINE_VAR:
                return _unquote(_strip_yaml_comment(km.group(3) or ""))
        return None
    return None


def _step_lines(job: list[str], i: int, col: int) -> list[str]:
    """Lines of the step (``- ...`` list item) whose key at column ``col`` is on line ``i``."""
    dash_col = col - 2
    start = None
    for j in range(i, -1, -1):
        line = job[j]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if _indent(line) == dash_col and line.lstrip().startswith("- "):
            start = j
            break
        if _indent(line) < dash_col or (j < i and _indent(line) < col):
            return []
    if start is None:
        return []
    body, _ = _block_under(job, start, dash_col)
    return [job[start], *body]


def _engine_state(value: str | None) -> str:
    if value is None:
        return PURE
    if "$" in value or "`" in value:
        return UNKNOWN
    return COMPILED if value == "1" else PURE


def run_blocks(workflow_text: str) -> list[tuple[str, str]]:
    """``(run text, base engine state)`` for every ``run:`` value.

    Matrix jobs are expanded per combination of the matrix keys the step
    references (in its ``run:`` or ``env:``), so a run text holds literals.
    """
    lines = workflow_text.splitlines()
    workflow_env = _env_text(lines, 0)
    out: list[tuple[str, str]] = []
    for job in _job_blocks(lines):
        matrix = _matrix_values(job)
        child_col = min(
            (_indent(l) for l in job[1:] if l.strip() and not l.lstrip().startswith("#")), default=0
        )
        job_env = _env_text(job[1:], child_col)
        for i, line in enumerate(job):
            m = KEY_LINE.match(line)
            if not m or m.group(2) != "run" or line.lstrip().startswith("#"):
                continue
            col = _key_column(line)
            text = _scalar(job, i, col, m.group(3) or "")
            step = _step_lines(job, i, col)
            step_env = _env_text(step, col) if step else None
            env_value = next((v for v in (step_env, job_env, workflow_env) if v is not None), None)
            keys = sorted(
                {k for k in MATRIX_REF.findall(text + "\n" + (env_value or "")) if matrix.get(k)}
            )
            for combo in itertools.product(*(matrix[k] for k in keys)):
                values = dict(zip(keys, combo))

                def sub(raw: str) -> str:
                    return MATRIX_REF.sub(lambda r: values.get(r.group(1), r.group(0)), raw)

                out.append((sub(text), _engine_state(None if env_value is None else sub(env_value))))
    return out


def _decide_condition(words: list[str]) -> bool | None:
    """Value of ``[ a = b ]``/``[[ a == b ]]``/``test a != b`` on literals, else None."""
    if words and words[0] == "test":
        inner = words[1:]
    elif len(words) >= 2 and (words[0], words[-1]) in (("[", "]"), ("[[", "]]")):
        inner = words[1:-1]
    else:
        return None
    if len(inner) != 3 or inner[1] not in ("=", "==", "!="):
        return None
    a, op, b = inner
    if any(c in a + b for c in "$`*?["):
        return None
    return (a == b) if op != "!=" else (a != b)


def command_engine(words: list[str], state: str) -> str:
    """Engine mode of one simple command executed while the shell is in ``state``."""
    mode = state
    i = 0
    while True:
        while i < len(words) and ASSIGNMENT.fullmatch(words[i]):
            name, _, value = words[i].partition("=")
            if name == ENGINE_VAR:
                mode = _engine_state(value)
            i += 1
        if i < len(words) and words[i] == "env":
            i += 1
            while i < len(words) and words[i].startswith("-"):
                opt = words[i]
                if opt in ("-i", "--ignore-environment", "-", f"-u{ENGINE_VAR}", f"--unset={ENGINE_VAR}"):
                    mode = PURE
                elif opt in ("-u", "--unset") and words[i + 1 : i + 2] == [ENGINE_VAR]:
                    mode = PURE
                i += 2 if opt in ENV_VALUE_OPTS else 1
            continue
        if words[i : i + 2] == ["uv", "run"]:
            i = _skip_options(words, i + 2, UV_RUN_VALUE_OPTS)
            continue
        break
    for k, word in enumerate(words):
        if word.endswith(CHECKOUT_WRAPPER):
            rest = words[k + 1 :]
            rest = rest[: rest.index("--")] if "--" in rest else rest
            for n, arg in enumerate(rest):
                value = rest[n + 1] if arg == "--engine" and n + 1 < len(rest) else (
                    arg.split("=", 1)[1] if arg.startswith("--engine=") else None
                )
                if value is not None:
                    return value if value in (PURE, COMPILED) else UNKNOWN
            return UNKNOWN  # the wrapper requires --engine; without one it refuses to run
    return mode


def statement_engine(words: list[str], state: str) -> str:
    """Shell engine state after ``words`` runs as a statement (export/unset/assignment)."""
    if words and all(ASSIGNMENT.fullmatch(w) for w in words):
        targets = words
    elif words and words[0] in ("export", "declare", "typeset", "readonly"):
        targets = [w for w in words[1:] if not w.startswith("-")]
    elif words and words[0] == "unset":
        return PURE if ENGINE_VAR in words[1:] else state
    else:
        return state
    for word in targets:
        name, eq, value = word.partition("=")
        if name == ENGINE_VAR and eq:
            state = _engine_state(value)
    return state


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


def _select_files(server: Path, root: Path, label: str, args: list[str], dangling: list[str]) -> set[str]:
    """Repo-relative test files that one pytest argument vector selects."""
    out: set[str] = set()
    for arg in _selecting_arguments(args):
        if m := TEST_ARG.fullmatch(arg):
            rel = _server_rel(m.group(1))
            if GLOB_CHARS & set(rel):
                matches = [p for p in server.glob(rel) if p.is_file()]
            else:
                matches = [server / rel] if (server / rel).is_file() else []
            if not matches:
                dangling.append(f"{label}: {arg}")
            out.update(p.relative_to(root).as_posix() for p in matches)
        elif m := TEST_DIR_ARG.fullmatch(arg):
            tests_dir = server / _server_rel(m.group(1))
            if tests_dir.is_dir():
                out.update(p.relative_to(root).as_posix() for p in tests_dir.rglob("test_*.py") if p.is_file())
    return out


def scan_selection(root: Path) -> dict:
    """Selection plus engine modes.

    Keys: ``selected`` (set), ``scanned``/``dangling``/``unparsed`` (lists) and
    ``modes`` (repo path -> set of ``pure``/``compiled`` credits).
    """
    server = root / SERVER_DIR
    selected: set[str] = set()
    modes: dict[str, set[str]] = {}
    dangling: list[str] = []
    unparsed: list[str] = []
    scanned: list[str] = []
    wf_dir = root / ".github" / "workflows"
    queue: list[tuple[Path, str | None]] = [
        (p, None) for p in sorted([*wf_dir.glob("*.yml"), *wf_dir.glob("*.yaml")])
    ]
    seen: set[tuple[Path, str | None]] = set()
    while queue:
        path, inherited = queue.pop(0)
        source = path.resolve()
        if (source, inherited) in seen:
            continue
        seen.add((source, inherited))
        label = source.relative_to(root.resolve()).as_posix()
        if label not in scanned:
            scanned.append(label)
        raw = source.read_text(encoding="utf-8")
        blocks = run_blocks(raw) if source.suffix in (".yml", ".yaml") else [(raw, inherited or PURE)]
        for shell_text, base in blocks:
            state = base
            frames: list[dict] = []  # if/elif/else/fi: {"decided", "active", "taken", "mutated", "entry"}
            heredoc: str | None = None
            for line in command_lines(shell_text):
                if heredoc is not None:
                    if line.strip() == heredoc:
                        heredoc = None
                    continue
                if hd := HEREDOC.search(line):
                    heredoc = hd.group(2)
                mentions_script = bool(re.search(r"scripts/\S*\.sh", line))
                mentions_pytest = bool(PYTEST.search(line) or CHECKOUT_WRAPPER in line)
                try:
                    commands = simple_commands(line)
                except ValueError:
                    if mentions_pytest:
                        unparsed.append(f"{label}: {line.strip()}")
                    if ENGINE_VAR in line:
                        state = UNKNOWN
                    continue
                for words in commands:
                    while words and words[0] in ("then", "else", "do"):
                        if words[0] == "else" and frames:
                            f = frames[-1]
                            f["active"] = f["decided"] and not f["taken"]
                            f["taken"] = f["taken"] or f["active"]
                        words = words[1:]
                    if not words:
                        continue
                    if words[0] in ("if", "elif"):
                        if words[0] == "if":
                            frames.append({"decided": True, "active": False, "taken": False,
                                           "mutated": False, "entry": state})
                        if frames:
                            f = frames[-1]
                            value = _decide_condition(words[1:])
                            if value is None:
                                f["decided"] = False
                            f["active"] = bool(f["decided"] and value and not f["taken"])
                            f["taken"] = f["taken"] or f["active"]
                        continue
                    if words[0] == "fi":
                        if frames:
                            f = frames.pop()
                            if not f["decided"] and f["mutated"]:
                                state = UNKNOWN
                        continue
                    undecided = any(not f["decided"] for f in frames)
                    inactive = any(f["decided"] and not f["active"] for f in frames)
                    effective = UNKNOWN if (undecided or inactive) else state
                    mode = command_engine(words, effective)
                    if not inactive:
                        after = statement_engine(words, state)
                        if after != state and frames:
                            for f in frames:
                                f["mutated"] = True
                        state = after
                    if mentions_script and (token := executed_script(words)) is not None:
                        script = server / _server_rel(token)
                        if script.is_file():
                            queue.append((script, mode))
                        else:
                            dangling.append(f"{label}: {token}")
                    if not mentions_pytest:
                        continue
                    args = pytest_arguments(words)
                    if args is None:
                        continue
                    files = _select_files(server, root, label, args, dangling)
                    selected |= files
                    if mode in (PURE, COMPILED):
                        for f in files:
                            modes.setdefault(f, set()).add(mode)
    # A matrix step or a twice-followed script is scanned once per combination/mode.
    return {
        "selected": selected,
        "scanned": scanned,
        "dangling": list(dict.fromkeys(dangling)),
        "unparsed": list(dict.fromkeys(unparsed)),
        "modes": modes,
    }


def collect_selection(root: Path) -> tuple[set[str], list[str], list[str], list[str]]:
    """Return (selected repo-relative paths, scanned sources, dangling refs, untokenizable lines)."""
    scan = scan_selection(root)
    return scan["selected"], scan["scanned"], scan["dangling"], scan["unparsed"]


def imported_modules(source: str, package: str = "") -> set[str]:
    """Dotted names a module imports (AST; see the module docstring).

    Raises ``SyntaxError`` when ``source`` does not parse.
    """
    out: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            out.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".") if package else []
                base = parts[: len(parts) - (node.level - 1)] if node.level - 1 <= len(parts) else []
                module = ".".join([*base, *([node.module] if node.module else [])])
            else:
                module = node.module or ""
            if module:
                out.add(module)
            out.update(f"{module}.{alias.name}" if module else alias.name for alias in node.names)
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            first = node.args[0]
            if name in DYNAMIC_IMPORTERS and isinstance(first, ast.Constant) and isinstance(first.value, str):
                out.add(first.value)
    return out


def engine_boundary_modules(root: Path) -> set[str]:
    """The core engine modules plus every benchmark module that imports one."""
    boundary = set(ENGINE_CORE_MODULES)
    pkg_dir = root / SERVER_DIR / Path(*BENCHMARK_PACKAGE.split("."))
    for path in sorted(pkg_dir.glob(BENCHMARK_GLOB)):
        try:
            imports = imported_modules(path.read_text(encoding="utf-8"), BENCHMARK_PACKAGE)
        except SyntaxError:
            continue
        if imports & ENGINE_CORE_MODULES:
            boundary.add(f"{BENCHMARK_PACKAGE}.{path.stem}")
    return boundary


def boundary_tests(root: Path, tests: set[str], boundary: set[str]) -> tuple[dict[str, list[str]], list[str]]:
    """(test path -> boundary modules it imports, test paths that do not parse)."""
    hits: dict[str, list[str]] = {}
    broken: list[str] = []
    for rel in sorted(tests):
        try:
            imports = imported_modules((root / rel).read_text(encoding="utf-8"))
        except SyntaxError:
            broken.append(rel)
            continue
        if found := sorted(imports & boundary):
            hits[rel] = found
    return hits, broken


def read_exclusions(path: Path) -> list[str]:
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            entries.append(entry)
    return entries


def run(root: Path, *, print_unselected: bool = False, print_engine_modes: bool = False) -> int:
    tests = all_test_files(root)
    scan = scan_selection(root)
    selected, scanned, dangling, unparsed = scan["selected"], scan["scanned"], scan["dangling"], scan["unparsed"]
    selected_tests = selected & tests
    exclusions = read_exclusions(root / EXCLUSIONS_REL)
    excluded = set(exclusions)

    unselected = sorted(tests - selected_tests)
    if print_unselected:
        print("\n".join(unselected))
        return 0

    boundary = engine_boundary_modules(root)
    importers, broken = boundary_tests(root, tests, boundary)
    modes = scan["modes"]
    if print_engine_modes:
        for path, found in importers.items():
            got = ",".join(sorted(modes.get(path, set()))) or "-"
            print(f"{path}\tmodes={got}\timports={','.join(found)}")
        return 0

    missing = sorted(set(unselected) - excluded)
    stale_selected = sorted(excluded & selected_tests)
    stale_gone = sorted(excluded - tests)
    duplicates = sorted({e for e in exclusions if exclusions.count(e) > 1})

    engine_exclusions = read_exclusions(root / ENGINE_EXCLUSIONS_REL)
    engine_excluded = set(engine_exclusions)
    required = {path for path in importers if path not in excluded}
    one_engine = {path: {PURE, COMPILED} - modes.get(path, set()) for path in sorted(required)}
    one_engine = {path: lacks for path, lacks in one_engine.items() if lacks}
    engine_missing = sorted(set(one_engine) - engine_excluded)
    engine_stale = sorted(
        (path, reason)
        for path, reason in (
            *((p, "no longer exists") for p in engine_excluded - tests),
            *((p, "no longer imports the engine boundary") for p in (engine_excluded & tests) - set(importers)),
            *((p, "is selection-excluded (selected by no job)") for p in engine_excluded & set(importers) & excluded),
            *((p, "is now selected in both modes") for p in engine_excluded & required - set(one_engine)),
        )
    )
    engine_duplicates = sorted({e for e in engine_exclusions if engine_exclusions.count(e) > 1})
    engine_ok = not (engine_missing or engine_stale or engine_duplicates or broken)

    ok = engine_ok and not (missing or stale_selected or stale_gone or duplicates or dangling or unparsed)
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
    if engine_missing:
        print(
            f"FAIL: {len(engine_missing)} engine-boundary test file(s) not selected in both a pure and a"
            " compiled step:"
        )
        for path in engine_missing:
            print(f"  {path}  (no {' or '.join(sorted(one_engine[path]))} selection; imports {', '.join(importers[path])})")
        print(
            "  -> also select each in a compiled step (env SHENGJI_FAST: \"1\" or test_checkout.py --engine"
            f" compiled) and a pure step, or (with a reason) list it in {ENGINE_EXCLUSIONS_REL}"
        )
    if engine_stale:
        print(f"FAIL: {len(engine_stale)} engine-mode exclusion(s) are stale; delete these lines:")
        for path, reason in engine_stale:
            print(f"  {path}  ({reason})")
    if engine_duplicates:
        print(f"FAIL: duplicate engine-mode exclusion line(s): {', '.join(engine_duplicates)}")
    if broken:
        print(f"FAIL: {len(broken)} test file(s) could not be parsed for imports:")
        for path in broken:
            print(f"  {path}")
    print(
        f"ci-engine-modes: {'OK' if engine_ok else 'FAIL'} boundary_tests={len(required)}"
        f" both={len(required) - len(one_engine)} excluded={len(engine_excluded & set(one_engine))}"
        f" missing={len(engine_missing)} stale={len(engine_stale)} modules={','.join(sorted(boundary))}"
    )
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
    parser.add_argument(
        "--print-engine-modes",
        action="store_true",
        help="print each engine-boundary test file with its pure/compiled selections and exit 0",
    )
    args = parser.parse_args(argv)
    return run(args.root, print_unselected=args.print_unselected, print_engine_modes=args.print_engine_modes)


if __name__ == "__main__":
    sys.exit(main())

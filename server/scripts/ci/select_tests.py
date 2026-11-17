#!/usr/bin/env python3
"""Select the Python test modules a pull request's changed paths can reach.

A test module is selected when it depends, transitively, on a changed file.
The dependency graph covers every tracked ``.py`` and ``.sh`` file:

* ``import``/``from`` statements (relative ones resolved against the file's
  package), each also depending on the package ``__init__.py`` files on the
  way; a dotted name resolves to every tracked module whose path ends with
  it, so ``import affected_tests`` (a script on ``sys.path``) and
  ``from tests.test_x import y`` both resolve;
* string constants other than docstrings: a dotted module name (``importlib.import_module("m")``,
  ``monkeypatch.setattr("m.attr", ...)``, ``["-m", "m"]``) resolves like an
  import, and a path or file name (``"scripts/x.py"``, ``"golden.json"``)
  depends on every tracked file it names;
* directory reads: a file that calls ``glob``/``rglob``/``iterdir``/
  ``listdir``/``scandir``/``os.walk`` depends on every file a constant glob
  pattern it passes could match, and on every file when it passes a pattern
  that is not a constant or reads a directory without one;
* dynamic loading the AST cannot resolve (``import_module``/``__import__``/
  ``spec_from_file_location``/``runpy``/``exec`` of a non-constant) makes the
  file depend on every Python file;
* every module under ``server/tests`` depends on ``server/tests/conftest.py``.

Changed paths then select:

* everything, for a path in ``RUN_ALL`` (conftest files, the locked
  environment, the compiled-extension sources, the workflows and these CI
  scripts and data);
* nothing for documentation (``*.md``, ``docs/``, ``incidents/``) except the
  modules that name the file;
* for ``web/``, the server test modules that read web files
  (``affected_tests.web_reading_tests``) plus the modules that name the file;
* otherwise the modules that reach the file; a file no tracked code names
  (a fixture read in a way the graph cannot see) selects everything.

Usage::

    select_tests.py --base <sha> --head <sha>     # paths from git
    select_tests.py server/shengji/api/server.py  # explicit paths
    select_tests.py --github-output ...           # write `selected=` and per-job flags
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SCRIPTS = HERE.parent

DOC_PREFIXES = ("docs/", "docs_archive/", "incidents/")
WORKFLOW_DIR = ".github/workflows/"
RUN_ALL = (
    "*conftest.py",
    "server/pyproject.toml",
    "server/uv.lock",
    "server/setup.py",
    "server/setup.cfg",
    "server/pytest.ini",
    "server/*.pyx",
    "server/*.pxd",
    "server/*.c",
    "server/*.h",
    "server/*.cpp",
    ".github/*",
    "server/scripts/ci/*",
    "server/scripts/ci_*.sh",
    "server/scripts/test_checkout.py",
    "server/scripts/check_ci_test_selection.py",
    "server/scripts/affected_tests.py",
    "server/tests/ci_*",
)
DYNAMIC_CALLS = {"import_module", "__import__", "spec_from_file_location", "run_path", "run_module",
                 "exec", "execfile", "import_from_path"}
DIR_READS = {"glob", "rglob", "iglob", "iterdir", "listdir", "scandir", "walk"}
DOTTED = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+")
PATH_TOKEN = re.compile(r"[A-Za-z0-9_.*?/-]+\.[A-Za-z0-9]+")
SHELL_TOKEN = re.compile(r"[A-Za-z0-9_./-]+")
FILE_SUFFIXES = {"py", "pyc", "json", "jsonl", "toml", "txt", "md", "yml", "yaml", "sh", "npz", "npy", "pt",
                 "csv", "tsv", "lock", "cfg", "ini", "html", "js", "ts", "tsx", "css", "log", "gz", "pkl"}
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
ANCHOR = "__file__"
TEST_FILE = re.compile(r"test_[A-Za-z0-9_]*\.py")


def is_doc(path: str) -> bool:
    return path.endswith(".md") or path.startswith(DOC_PREFIXES)


def is_test_module(path: str) -> bool:
    name = PurePosixPath(path).name
    return bool(TEST_FILE.fullmatch(name)) and (path.startswith("server/tests/") or path.startswith("tools/"))


def runs_everything(path: str) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in RUN_ALL)


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=root, check=True, capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if line and (root / line).is_file()]


class Graph:
    """Dependency edges among tracked files (``deps[a]`` = files ``a`` uses)."""

    def __init__(self, root: Path, files: list[str] | None = None) -> None:
        self.root = root
        self.files = sorted(files if files is not None else tracked_files(root))
        self.file_set = set(self.files)
        self.by_name: dict[str, list[str]] = {}
        for path in self.files:
            self.by_name.setdefault(PurePosixPath(path).name, []).append(path)
        self.modules: dict[str, list[str]] = {}  # dotted suffix -> files
        for path in self.files:
            if path.endswith(".py"):
                parts = list(PurePosixPath(path).with_suffix("").parts)
                if parts[-1] == "__init__":
                    parts = parts[:-1]
                for k in range(len(parts)):
                    self.modules.setdefault(".".join(parts[k:]), []).append(path)
        self.deps: dict[str, set[str]] = {}
        self.opaque: dict[str, str] = {}  # file -> why it may load any Python file
        self.dynamic: dict[str, list[int]] = {}  # file -> lines of computed imports, mapped by constants
        self.directories = {str(parent) for path in self.files for parent in PurePosixPath(path).parents
                            if str(parent) != "."} | {"."}
        self.patterns: dict[str, list[str | None]] = {}  # file -> directory-read patterns (None = any)
        for path in self.files:
            if path.endswith(".py"):
                self._python(path)
            elif path.endswith(".sh"):
                self._shell(path)
        for path, targets in self.deps.items():
            # A file that runs everything when it changes needs no edges into it.
            targets.difference_update({t for t in targets if runs_everything(t)})
        for path in self.files:
            if path.startswith("server/tests/") and path.endswith(".py") and path != "server/tests/conftest.py":
                self.deps.setdefault(path, set()).add("server/tests/conftest.py")

    # resolution -------------------------------------------------------
    def resolve_dotted(self, name: str) -> set[str]:
        """Every tracked module the dotted name (or a prefix of it) can denote."""
        out: set[str] = set()
        parts = name.split(".")
        for k in range(len(parts), 0, -1):
            out.update(self.modules.get(".".join(parts[:k]), ()))
        return out

    def packages_of(self, path: str) -> set[str]:
        """The ``__init__.py`` files of the packages enclosing ``path``."""
        out = set()
        parent = PurePosixPath(path).parent
        while str(parent) not in ("", "."):
            init = f"{parent}/__init__.py"
            if init in self.file_set:
                out.add(init)
            parent = parent.parent
        return out

    def resolve_path_text(self, text: str) -> set[str]:
        out: set[str] = set()
        for token in PATH_TOKEN.findall(text):
            token = token.strip("./") if token.startswith(("./", "../")) else token
            parts = [p for p in token.split("/") if p not in ("", ".", "..")]
            if not parts:
                continue
            name = parts[-1]
            if any(c in name for c in "*?"):
                continue
            suffix = "/".join(parts)
            for path in self.by_name.get(name, ()):
                if path == suffix or path.endswith("/" + suffix):
                    out.add(path)
        return out

    def _relative(self, path: str, level: int, module: str | None) -> str:
        package = list(PurePosixPath(path).parent.parts)
        base = package[: len(package) - (level - 1)] if level - 1 <= len(package) else []
        return ".".join([*base, *([module] if module else [])])

    # file kinds -------------------------------------------------------
    def _python(self, path: str) -> None:
        deps = self.deps.setdefault(path, set())
        deps.update(self.packages_of(path))
        source = (self.root / path).read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            self.opaque[path] = "does not parse"
            return
        constants: list[str] = []
        dynamic: list[int] = []
        reads: list[ast.Call] = []
        docstrings = {id(body[0].value) for node in ast.walk(tree)
                      if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                      and (body := node.body) and isinstance(body[0], ast.Expr)
                      and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    deps.update(self.resolve_dotted(alias.name))
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    absolute = self._relative(path, node.level, node.module)
                    names = [absolute] + [f"{absolute}.{a.name}" if absolute else a.name for a in node.names]
                    for name in names:
                        target = name.replace(".", "/")
                        for candidate in (f"{target}.py", f"{target}/__init__.py"):
                            if candidate in self.file_set:
                                deps.add(candidate)
                                deps.update(self.packages_of(candidate))
                else:
                    module = node.module or ""
                    deps.update(self.resolve_dotted(module))
                    for alias in node.names:
                        deps.update(self.modules.get(f"{module}.{alias.name}", ()))
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
                if id(node) in docstrings or len(value) > 2000:
                    continue
                constants.append(value)
                named = self.resolve_path_text(value)
                deps.update(named)
                if DOTTED.fullmatch(value) and not named and value.rsplit(".", 1)[-1] not in FILE_SUFFIXES:
                    deps.update(self.resolve_dotted(value))
            elif isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if name in DYNAMIC_CALLS:
                    args = node.args[1:2] if name == "spec_from_file_location" else node.args[:1]
                    if not all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in args):
                        dynamic.append(node.lineno)
                elif name in DIR_READS:
                    reads.append(node)
        if dynamic:
            # A computed import or file load: the names it can be built from are
            # the file's own constants, so every module a constant names (a
            # dotted name, a file name, or a bare module name) is a dependency.
            self.dynamic[path] = dynamic
            for value in constants:
                if IDENTIFIER.fullmatch(value):
                    deps.update(self.modules.get(value, ()))
        if reads and (ANCHOR in source or any(v in self.directories for v in constants)):
            # Directory reads in a file that names a repository location: only
            # a read whose directory expression derives from the file's
            # location or a tracked directory name counts (a pytest tmp_path,
            # a journal root or /proc is not a repository input).
            tainted = self._tainted(tree)
            patterns = []
            for call in reads:
                if tainted is not None and not self._mentions(_read_target(call), tainted):
                    continue
                patterns.append(_read_pattern(call))
            if patterns:
                self.patterns[path] = patterns
        deps.discard(path)

    def _mentions(self, node, tainted: set[str]) -> bool:
        if node is None:
            return True
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and (sub.id in tainted or sub.id == ANCHOR):
                return True
            if isinstance(sub, ast.Attribute) and sub.attr in tainted:
                return True
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.value in self.directories:
                return True
        return False

    def _tainted(self, tree) -> set[str]:
        """Names (variables, attributes, functions, parameters with defaults)
        whose value derives from ``__file__`` or a tracked directory name."""
        tainted: set[str] = set()
        while True:
            before = len(tainted)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and node.value is not None:
                    if self._mentions_strict(node.value, tainted):
                        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                        for target in targets:
                            for sub in ast.walk(target):
                                if isinstance(sub, ast.Name):
                                    tainted.add(sub.id)
                                elif isinstance(sub, ast.Attribute):
                                    tainted.add(sub.attr)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if any(isinstance(sub, ast.Return) and sub.value is not None
                           and self._mentions_strict(sub.value, tainted) for sub in ast.walk(node)):
                        tainted.add(node.name)
                    arguments = node.args
                    positional = [*arguments.posonlyargs, *arguments.args]
                    for arg, default in zip(positional[len(positional) - len(arguments.defaults):], arguments.defaults):
                        if self._mentions_strict(default, tainted):
                            tainted.add(arg.arg)
                    for arg, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
                        if default is not None and self._mentions_strict(default, tainted):
                            tainted.add(arg.arg)
                elif isinstance(node, (ast.For, ast.comprehension)):
                    if self._mentions_strict(node.iter, tainted):
                        for sub in ast.walk(node.target):
                            if isinstance(sub, ast.Name):
                                tainted.add(sub.id)
                elif isinstance(node, ast.withitem) and node.optional_vars is not None:
                    if self._mentions_strict(node.context_expr, tainted):
                        for sub in ast.walk(node.optional_vars):
                            if isinstance(sub, ast.Name):
                                tainted.add(sub.id)
            if len(tainted) == before:
                return tainted

    def _mentions_strict(self, node, tainted: set[str]) -> bool:
        return node is not None and self._mentions(node, tainted)

    def _shell(self, path: str) -> None:
        deps = self.deps.setdefault(path, set())
        text = (self.root / path).read_text(encoding="utf-8", errors="replace")
        for token in SHELL_TOKEN.findall(text):
            if "." in token:
                named = self.resolve_path_text(token)
                deps.update(named)
                if DOTTED.fullmatch(token) and not named and token.rsplit(".", 1)[-1] not in FILE_SUFFIXES:
                    deps.update(self.resolve_dotted(token))
        for glob_token in re.findall(r"[A-Za-z0-9_./-]*\*[A-Za-z0-9_.*/-]*", text):
            leaf = glob_token.rsplit("/", 1)[-1]
            if leaf.strip("*") and ("." in leaf or "/" in glob_token):
                self.patterns.setdefault(path, []).append(glob_token)
        deps.discard(path)

    # selection --------------------------------------------------------
    def readers_of_directories(self, changed: str) -> set[str]:
        """Files whose directory reads could return ``changed``."""
        out = set()
        name = PurePosixPath(changed).name
        for path, patterns in self.patterns.items():
            for pattern in patterns:
                if pattern is None:
                    out.add(path)
                    break
                leaf = pattern.rsplit("/", 1)[-1]
                if fnmatch.fnmatchcase(name, leaf) or ("/" in pattern and fnmatch.fnmatchcase(changed, f"*{pattern.lstrip('*/')}")):
                    out.add(path)
                    break
        return out

    def dependents(self, seeds: set[str]) -> set[str]:
        """``seeds`` plus every file that depends on one of them, transitively."""
        reverse: dict[str, set[str]] = {}
        for a, targets in self.deps.items():
            for b in targets:
                reverse.setdefault(b, set()).add(a)
        everything_py = [p for p in self.opaque]
        seen = set(seeds)
        todo = list(seeds)
        while todo:
            node = todo.pop()
            users = set(reverse.get(node, ()))
            if node.endswith(".py"):
                users.update(everything_py)
            for user in users - seen:
                seen.add(user)
                todo.append(user)
        return seen

    def referenced(self, path: str) -> bool:
        return any(path in targets for targets in self.deps.values())


def _read_target(call: ast.Call):
    """The directory expression of a directory-read call."""
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr in ("glob", "rglob", "iterdir"):
        value = func.value
        if isinstance(value, ast.Name) and value.id == "glob":  # glob.glob(pattern)
            return call.args[0] if call.args else None
        return value
    return call.args[0] if call.args else None


def _read_pattern(call: ast.Call) -> str | None:
    """The constant file-name pattern of a read, or None when it may return any file."""
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    if name not in ("glob", "rglob", "iglob") or not call.args:
        return None
    pattern = call.args[0]
    if isinstance(pattern, ast.Constant) and isinstance(pattern.value, str):
        return pattern.value
    if isinstance(pattern, ast.JoinedStr):
        return _joined_pattern(pattern)
    return None


def _joined_pattern(node: ast.JoinedStr) -> str | None:
    out = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            out.append(value.value)
        else:
            out.append("*")
    return "".join(out)


def web_reading_tests(root: Path) -> set[str]:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import affected_tests
    return {f"server/tests/{name}.py" for name in affected_tests.web_reading_tests(root)}


def select(paths: list[str], root: Path = REPO, graph: Graph | None = None,
           membership: set[str] | None = None) -> tuple[set[str] | None, list[str]]:
    """``(selected test modules or None for every module, reasons)``.

    ``membership`` holds the paths the change adds or deletes (by default
    every changed path that is not tracked now)."""
    reasons: list[str] = []
    if not paths:
        return None, ["empty diff"]
    for path in paths:
        if runs_everything(path):
            return None, [f"{path} runs everything"]
    graph = graph or Graph(root)
    if membership is None:
        membership = {p for p in paths if p not in graph.file_set}
    seeds: set[str] = set()
    listing: set[str] = set()  # files whose directory reads can return a changed path
    for path in paths:
        exists = path in graph.file_set
        named = graph.referenced(path)
        if is_doc(path) and path != "HANDOFF_REVIEW.md":
            if named:
                seeds.add(path)
                reasons.append(f"{path}: documentation named by code")
            continue
        if path.startswith("web/"):
            readers = web_reading_tests(root)
            seeds |= readers
            seeds.add(path)
            reasons.append(f"{path}: web readers ({len(readers)})")
            continue
        seeds.add(path)
        readers = graph.readers_of_directories(path)
        listing |= readers if path in membership else {r for r in readers if is_test_module(r)}
        if path.endswith((".py", ".sh")) or named or is_test_module(path):
            continue
        if not exists and not named:
            reasons.append(f"{path}: deleted and named by no tracked code")
            continue
        return None, [f"{path}: named by no tracked code, runs everything"]
    reached = graph.dependents(seeds)
    # A directory listing changes what its reader returns: a test module whose
    # own reads can return a changed path is selected, and for an added or
    # deleted path so are the test modules that use such a reader directly
    # (not every module that merely imports something importing the reader).
    reached |= listing
    reached |= {p for p in graph.file_set if graph.deps.get(p, set()) & listing}
    return {p for p in reached if is_test_module(p) and p in graph.file_set}, reasons


def changed_paths(base: str, head: str, root: Path = REPO) -> tuple[list[str], set[str]]:
    """``(changed paths, the added or deleted ones)``."""
    out = subprocess.run(["git", "diff", "--name-status", "--no-renames", f"{base}...{head}"],
                         cwd=root, check=True, capture_output=True, text=True).stdout
    rows = [line.split("\t", 1) for line in out.splitlines() if "\t" in line]
    return [path for _, path in rows], {path for status, path in rows if status[:1] in ("A", "D")}


def job_universes(root: Path = REPO) -> dict[str, set[str]]:
    """Each workflow job's selected test modules (check_ci_test_selection's reading)."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import check_ci_test_selection as checker
    return checker.job_selection(root)


def outputs(paths: list[str] | None, root: Path = REPO, membership: set[str] | None = None) -> tuple[dict, list[str]]:
    """The changes job's outputs for a pull request's changed paths (None: not a
    pull request).  Any failure selects everything."""
    try:
        if paths is None:
            selected, reasons = None, ["not a pull request"]
        else:
            selected, reasons = select(paths, root, membership=membership)
            reasons.insert(0, f"{len(paths)} changed paths")
    except Exception as error:
        selected, reasons = None, [f"selection failed, running everything: {error!r}"]
    try:
        universes = job_universes(root)
    except Exception as error:  # the workflow runs every job on `selected=all`
        selected, universes = None, {}
        reasons.append(f"job selections unreadable, running everything: {error!r}")
    every = selected is None
    out = {
        "code": every if paths is None else any(not is_doc(p) for p in paths),
        "web": paths is None or any(p.startswith(WORKFLOW_DIR) or (p.startswith("web/") and not is_doc(p))
                                    for p in paths),
        "selected": None if every else sorted(selected),
        "jobs": {job: every or bool(modules & selected) for job, modules in sorted(universes.items()) if modules},
        "counts": {job: (len(modules) if every else len(modules & selected), len(modules))
                   for job, modules in sorted(universes.items()) if modules},
    }
    return out, reasons


def output_lines(out: dict) -> list[str]:
    selected = out["selected"]
    return [
        f"code={str(out['code']).lower()}",
        f"web={str(out['web']).lower()}",
        f"selected={'all' if selected is None else ' '.join(selected) or 'none'}",
        f"jobs={json.dumps(out['jobs'], sort_keys=True)}",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--all", action="store_true", help="select every module (a push or a dispatch)")
    parser.add_argument("--github-output", help="append the changes job's output lines to this file")
    args = parser.parse_args(argv)
    membership = None
    if args.all:
        paths = None
    elif args.paths:
        paths = args.paths
    else:
        try:
            paths, membership = changed_paths(args.base, args.head)
        except Exception as error:
            print(f"# git diff failed, running everything: {error!r}")
            paths = None
        else:
            if not paths:
                print("# empty diff, running everything")
                paths = None
    out, reasons = outputs(paths, membership=membership)
    for reason in reasons:
        print(f"# {reason}")
    selected = out["selected"]
    print("selected: all" if selected is None else f"selected: {len(selected)} test modules")
    for module in selected or ():
        print(f"  {module}")
    for job, runs in out["jobs"].items():
        chosen, total = out["counts"][job]
        print(f"job {job}: {'runs' if runs else 'skipped'} ({chosen} of {total} modules)")
    lines = output_lines(out)
    if args.github_output:
        with open(args.github_output, "a") as handle:
            handle.write("".join(f"{line}\n" for line in lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())

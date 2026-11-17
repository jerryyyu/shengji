"""CI pytest session controls, installed by ``server/tests/conftest.py``.

Environment (every variable optional; with none set the session is unchanged):

``SHENGJI_CI_SELECTED``
    ``all``, or the space-separated repo-relative test modules a pull request
    can reach (``select_tests.py``).  Modules on the command line outside it
    are not collected.
``SHENGJI_CI_SHARD``
    ``i/N``: keep piece ``i`` of the ``shard_plan.plan`` split of the selected
    command-line modules into ``N`` pieces, by recorded time in this session's
    engine mode.  Sessions given the same command line, selection and engine
    keep disjoint pieces whose union is the selection.
``SHENGJI_CI_DURATIONS_OUT``
    A directory; the session writes one JSON file there with each module's
    collection plus setup/call/teardown seconds (``update_durations.py``
    merges them into ``test_durations.json``).

A session whose piece is empty reports ``0 selected`` and exits 0 before
collection, instead of pytest's "no tests collected" status.  A planning error keeps every module
(a module may then run twice, never zero times).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shard_plan  # noqa: E402

REPO = shard_plan.REPO
REPO_TEXT = os.path.realpath(os.fspath(REPO))
SELECTED_ENV = "SHENGJI_CI_SELECTED"
SHARD_ENV = "SHENGJI_CI_SHARD"
DURATIONS_ENV = "SHENGJI_CI_DURATIONS_OUT"


def repo_relative(path) -> str:
    """The repo-relative path, or the absolute one outside the repository.

    Only ``os.path`` string functions: the hooks run while a test may have
    patched ``pathlib.Path`` methods (``resolve``, ``exists``, ...)."""
    resolved = os.path.realpath(os.fspath(path))
    relative = os.path.relpath(resolved, REPO_TEXT)
    return resolved if relative.startswith("..") else relative.replace(os.sep, "/")


def engine_mode() -> str:
    return "compiled" if os.environ.get("SHENGJI_FAST") == "1" else "pure"


def command_line_modules(args, invocation_dir: Path) -> list[Path]:
    """Test files the positional pytest arguments name (directories expanded)."""
    out: list[Path] = []
    for arg in args:
        path = (invocation_dir / str(arg).split("::", 1)[0]).resolve()
        if path.is_dir():
            out.extend(sorted(p.resolve() for p in path.rglob("test_*.py")))
        elif path.is_file() and path.suffix == ".py":
            out.append(path)
    return list(dict.fromkeys(out))


def selected_from_env(value: str | None) -> set[str] | None:
    """None means every module; otherwise the selected repo-relative paths."""
    if value is None or value.strip() == "all":
        return None
    return set(value.split())


class CiSession:
    def __init__(self, config: pytest.Config) -> None:
        self.config = config
        self.skip: set[str] = set()
        self.module_keys: dict[str, str] = {}
        self.kept: list[str] | None = None
        self.environment: dict[str, str | None] = {}
        self.out_dir: str | None = None
        self.root_text = os.fspath(config.rootpath)
        self.seconds: dict[str, float] = {}

    def say(self, line: str) -> None:
        reporter = self.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line(line)
        else:
            print(line, file=sys.__stderr__, flush=True)

    def plan(self) -> None:
        self.out_dir = self.environment.get(DURATIONS_ENV)
        selected = selected_from_env(self.environment.get(SELECTED_ENV))
        shard = self.environment.get(SHARD_ENV)
        if selected is None and not shard:
            return
        universe = command_line_modules(self.config.args, self.config.invocation_params.dir)
        names = {path: repo_relative(path) for path in universe}
        wanted = [p for p in universe if selected is None or names[p] in selected]
        mine = {names[p] for p in wanted}
        label = "all selected" if selected is None else f"{len(wanted)} of {len(universe)} selected"
        if shard:
            index, total = shard_plan.parse_shard(shard)
            modules = [names[p] for p in wanted]
            costs = shard_plan.module_costs(modules, engine_mode(), shard_plan.load_durations())
            mine = set(shard_plan.plan(modules, total, costs)[index - 1])
            predicted = sum(costs[m] for m in mine)
            label += f"; piece {index}/{total} ({engine_mode()}): {len(mine)} modules, predicted {predicted:.0f} s"
        self.skip = {os.path.realpath(os.fspath(p)) for p in universe if names[p] not in mine}
        self.kept = sorted(mine)
        self.say(f"ci-session: {label}")
        for module in self.kept:
            self.say(f"ci-session:   {module}")
        # Explicit file arguments are collected without consulting
        # pytest_ignore_collect, so a skipped file leaves the argument list;
        # files under a directory argument are skipped by the hook.
        invocation = self.config.invocation_params.dir
        self.config.args[:] = [
            arg for arg in self.config.args
            if os.path.realpath(os.path.join(os.fspath(invocation), str(arg).split("::", 1)[0])) not in self.skip
        ]

    @pytest.hookimpl(tryfirst=True)
    def pytest_ignore_collect(self, collection_path: Path, config):
        if self.skip and os.path.realpath(os.fspath(collection_path)) in self.skip:
            return True
        return None

    @pytest.hookimpl(wrapper=True)
    def pytest_make_collect_report(self, collector):
        start = time.perf_counter()
        report = yield
        if self.out_dir and isinstance(collector, pytest.Module) and collector.path.suffix == ".py":
            module = repo_relative(collector.path)
            self.seconds[module] = self.seconds.get(module, 0.0) + time.perf_counter() - start
        return report

    def pytest_runtest_logreport(self, report) -> None:
        if not self.out_dir:
            return
        prefix = report.nodeid.split("::", 1)[0]
        module = self.module_keys.get(prefix)
        if module is None:
            module = self.module_keys[prefix] = repo_relative(os.path.join(self.root_text, prefix))
        self.seconds[module] = self.seconds.get(module, 0.0) + float(report.duration)

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session, exitstatus) -> None:
        if self.out_dir and self.seconds:
            os.makedirs(self.out_dir, exist_ok=True)
            record = {"engine": engine_mode(), "shard": self.environment.get(SHARD_ENV),
                      "exitstatus": int(session.exitstatus), "modules": self.seconds}
            name = f"{engine_mode()}-{os.getpid()}-{time.time_ns()}.json"
            with open(os.path.join(self.out_dir, name), "w") as handle:
                handle.write(json.dumps(record, indent=1, sort_keys=True))


def install(session: pytest.Session) -> None:
    """Register the session controls when any CI variable is set."""
    if not any(os.environ.get(name) for name in (SELECTED_ENV, SHARD_ENV, DURATIONS_ENV)):
        return
    controls = CiSession(session.config)
    # Read once, then hidden from child processes: a test that runs its own
    # pytest session must not inherit this session's selection or piece.
    environment = {name: os.environ.pop(name, None) for name in (SELECTED_ENV, SHARD_ENV, DURATIONS_ENV)}
    controls.environment = environment
    try:
        controls.plan()
    except Exception as error:  # a broken plan keeps every module
        controls.skip, controls.kept = set(), None
        controls.say(f"ci-session: planning failed, running every module: {error!r}")
    session.config.pluginmanager.register(controls, "shengji-ci-session")
    if controls.kept == []:
        # Stop before collection: an empty argument list would mean the rootdir.
        pytest.exit("ci-session: 0 selected", returncode=pytest.ExitCode.OK)

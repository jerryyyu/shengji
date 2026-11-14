#!/usr/bin/env python3
"""Map changed paths to the gates a branch must pass before review.

Some tests guard files they do not import: the offline-server parity fixture
holds ``server/shengji/api/server.py`` to what the web client replays, and the
release-identity tests read ``fly.toml``.  Running only the touched module's
own tests misses them, so this script turns a diff into the full command list.

Usage::

    affected_tests.py --base origin/main          # paths from the branch diff
    affected_tests.py fly.toml server/shengji/api/server.py
    affected_tests.py --base origin/main --json   # [{"cwd": ..., "argv": [...]}]
    affected_tests.py --base origin/main --run    # run each, print its rc

``--run`` runs every command even after a failure, prints ``rc=<n>`` per
command and exits 1 when any command failed (0 when all passed or none
applied), and 2 when no checkout virtualenv is found (see
``resolve_python``).  The rules live in ``RULES`` below; each rule names path globs
(``fnmatch``, so ``*`` also crosses ``/``) and what they require.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import fnmatch
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys


@dataclass(frozen=True)
class Rule:
    """Paths matching ``globs`` require these gates.

    ``pure``/``compiled`` are server test modules (``tests/<name>.py``) run
    through ``scripts/test_checkout.py`` in that engine mode; ``web`` names
    entries of ``WEB_COMMANDS``; ``checks`` names entries of ``CHECKS``."""

    why: str
    globs: tuple[str, ...]
    pure: tuple[str, ...] = ()
    compiled: tuple[str, ...] = ()
    web: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()


# The encoder and engine closure: these files are hashed into checkpoint
# identities (rl/encoder_identity.py SOURCE_PATHS, ai/cwv_policy.py
# AFTERSTATE_SOURCE_PATHS) and rerouted by SHENGJI_FAST=1, so both engines
# and the production-package compatibility tests must run.
ENGINE_CLOSURE = (
    "server/shengji/engine/*",
    "server/shengji/rl/encode*.py",
    "server/shengji/rl/public_history.py",
    "server/shengji/rl/douzero_micro.py",
    "server/shengji/rl/value_afterstate*.py",
    "server/shengji/ai/memory.py",
    "server/shengji/harvest/rebuild.py",
    "server/shengji/teacher_v1.py",
)
ENGINE_TESTS = (
    "test_engine", "test_engine_parity", "test_fast_parity", "test_game",
    "test_action_semantics", "test_offline_fixture_gen", "test_offline_server_fixture_gen",
    "test_encoder_round_compat",
)
RELEASE_IDENTITY_TESTS = (
    "test_release_manifests", "test_release51_fly_config", "test_release52_fly_config",
    "test_served_config", "test_bury_fly_config", "test_deploy_web_only",
)

RULES: tuple[Rule, ...] = (
    Rule("the API server's frames are replayed by the offline web server through a fixture",
         ("server/shengji/api/*",),
         pure=("test_offline_server_fixture_gen", "test_server_ws", "test_health_activity"),
         web=("vitest-offline",)),
    Rule("matchmaking frames reach the queue client and the server socket tests",
         ("server/shengji/api/matchmaking.py",),
         pure=("test_matchmaking", "test_server_ws", "test_client_server_constants")),
    Rule("the web client mirrors server timers and limits by hand",
         ("server/shengji/api/server.py", "server/shengji/api/accounts.py",
          "web/src/useMoveClock.ts", "web/src/auth.ts", "web/src/queue/*",
          "web/src/components/Table.tsx", "web/src/components/ChatPanel.tsx",
          "web/src/components/LeaveAlert.tsx", "web/src/offline/server/server.ts"),
         pure=("test_client_server_constants",)),
    Rule("fly.toml is the served release's configuration and identity",
         ("fly.toml",),
         pure=RELEASE_IDENTITY_TESTS,
         compiled=("test_release_manifests", "test_release51_fly_config", "test_release52_fly_config")),
    Rule("engine and encoder closure files run under both engines and bind checkpoint identity",
         ENGINE_CLOSURE,
         pure=ENGINE_TESTS, compiled=ENGINE_TESTS, web=("vitest-offline",)),
    Rule("the offline web server and its fixtures are held to the Python server",
         ("web/src/offline/server/*", "web/src/offline/fixtures/*",
          "server/scripts/gen_offline_server_fixtures.py"),
         pure=("test_offline_server_fixture_gen",), web=("vitest-offline",)),
    Rule("any web source change runs the web suite, the type check and the linter",
         ("web/src/*",),
         web=("vitest", "tsc", "oxlint"), checks=("comment-provenance",)),
    Rule("CI workflow edits must keep every test module selected",
         (".github/workflows/*",),
         pure=("test_check_ci_test_selection", "test_ci_path_classifier", "test_ci_review_ledger_step"),
         checks=("ci-test-selection",)),
    Rule("any server change keeps comments present-tense and every test selected by CI",
         ("server/*",),
         checks=("comment-provenance", "ci-test-selection")),
)

# Web commands run in web/; a full vitest run makes the offline subset redundant.
WEB_COMMANDS: dict[str, tuple[str, ...]] = {
    "vitest-offline": ("npx", "vitest", "run", "src/offline"),
    "vitest": ("npx", "vitest", "run"),
    "tsc": ("npx", "tsc", "--noEmit", "-p", "tsconfig.app.json"),
    "oxlint": ("npx", "oxlint"),
}
WEB_SUBSUMED_BY = {"vitest-offline": "vitest"}

# Repository checks run from the repo root; ``{base}`` is the diff base.
CHECKS: dict[str, tuple[str, ...]] = {
    "comment-provenance": ("server/scripts/check_comment_provenance.py", "--base", "{base}"),
    "ci-test-selection": ("server/scripts/check_ci_test_selection.py",),
}

REPO = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Command:
    cwd: str          # relative to the repo root
    argv: tuple[str, ...]

    def shell(self) -> str:
        line = shlex.join(self.argv)
        return line if self.cwd == "." else f"cd {self.cwd} && {line}"


@dataclass
class Plan:
    pure: list[str]
    compiled: list[str]
    web: list[str]
    checks: list[str]
    reasons: list[str]


def _add(target: list[str], items) -> None:
    for item in items:
        if item not in target:
            target.append(item)


def _own_tests(path: str, repo: Path) -> list[str]:
    """A module's own test file, ``tests/test_<stem>.py``, when it exists; a
    changed server test module is its own test."""
    p = Path(path)
    if path.startswith("server/tests/") and p.name.startswith("test_") and p.suffix == ".py":
        return [p.stem] if (repo / path).exists() else []
    if path.startswith(("server/shengji/", "server/scripts/")) and p.suffix in (".py", ".sh"):
        own = f"test_{p.stem}"
        if (repo / "server" / "tests" / f"{own}.py").exists():
            return [own]
    return []


def plan_for(paths: list[str], repo: Path = REPO) -> Plan:
    plan = Plan([], [], [], [], [])
    for path in paths:
        for rule in RULES:
            if any(fnmatch.fnmatchcase(path, glob) for glob in rule.globs):
                _add(plan.pure, rule.pure)
                _add(plan.compiled, rule.compiled)
                _add(plan.web, rule.web)
                _add(plan.checks, rule.checks)
                _add(plan.reasons, [rule.why])
        _add(plan.pure, _own_tests(path, repo))
    plan.web = [w for w in plan.web if WEB_SUBSUMED_BY.get(w) not in plan.web]
    return plan


class NoInterpreter(RuntimeError):
    """No Python with the checkout's dependencies was found."""


VENV_PYTHON = Path("server") / ".venv" / "bin" / "python"


def resolve_python(repo: Path = REPO, env: dict[str, str] | None = None) -> str:
    """The interpreter every Python gate runs under.

    ``$SHENGJI_PY`` wins; then this work tree's ``server/.venv``; then the main
    work tree's, found through ``git rev-parse --git-common-dir`` (a linked
    worktree usually has no venv of its own).  A system python is never used:
    without pytest, test_checkout.py refuses and every gate would fail."""
    env = os.environ if env is None else env
    if env.get("SHENGJI_PY"):
        return env["SHENGJI_PY"]
    tried = [repo / VENV_PYTHON]
    if os.access(tried[0], os.X_OK):
        return str(tried[0])
    common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=repo,
                            capture_output=True, text=True)
    if common.returncode == 0 and common.stdout.strip():
        common_dir = Path(common.stdout.strip())
        if not common_dir.is_absolute():
            common_dir = repo / common_dir
        candidate = common_dir.resolve().parent / VENV_PYTHON
        tried.append(candidate)
        if os.access(candidate, os.X_OK):
            return str(candidate)
    raise NoInterpreter("no checkout virtualenv found (tried "
                        + ", ".join(str(t) for t in tried)
                        + "); set SHENGJI_PY or run `uv sync --group dev` in server/")


def commands_for(plan: Plan, base: str, repo: Path = REPO) -> list[Command]:
    if not (plan.pure or plan.compiled or plan.checks):
        return [Command("web", WEB_COMMANDS[key]) for key in plan.web]
    python = resolve_python(repo)
    out: list[Command] = []
    for engine, names in (("pure", plan.pure), ("compiled", plan.compiled)):
        if names:
            out.append(Command("server", (python, "scripts/test_checkout.py", "--engine", engine, "--", "-q",
                                          *(f"tests/{name}.py" for name in names))))
    out.extend(Command("web", WEB_COMMANDS[key]) for key in plan.web)
    for key in plan.checks:
        out.append(Command(".", (python, *(word.format(base=base) for word in CHECKS[key]))))
    return out


def changed_paths(base: str, repo: Path = REPO) -> list[str]:
    """Paths the branch changes against ``base``, plus uncommitted and
    untracked ones, so a check before the commit sees the same set."""
    def git(*args: str) -> list[str]:
        out = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout
        return [line for line in out.splitlines() if line]
    paths = git("diff", "--name-only", "--no-renames", f"{base}...HEAD")
    paths += git("diff", "--name-only", "--no-renames", "HEAD")
    paths += git("ls-files", "--others", "--exclude-standard")
    return sorted(set(paths))


def run(commands: list[Command], repo: Path = REPO) -> int:
    failed = 0
    for command in commands:
        print(f"$ {command.shell()}", flush=True)
        rc = subprocess.run(list(command.argv), cwd=repo / command.cwd).returncode
        print(f"rc={rc} {command.shell()}", flush=True)
        failed += rc != 0
    print(f"affected_tests: {len(commands) - failed}/{len(commands)} commands passed", flush=True)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("paths", nargs="*", help="changed paths, relative to the repo root")
    parser.add_argument("--base", help="diff base ref; the changed paths come from git when no paths are given")
    parser.add_argument("--repo", type=Path, default=REPO)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="print the commands as JSON")
    mode.add_argument("--run", action="store_true", help="run every command and report each rc")
    args = parser.parse_args(argv)
    if not args.paths and not args.base:
        parser.error("give changed paths or --base")
    base = args.base or "origin/main"
    paths = args.paths or changed_paths(base, args.repo)
    plan = plan_for(paths, args.repo)
    try:
        commands = commands_for(plan, base, args.repo)
    except NoInterpreter as exc:
        print(f"affected_tests: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps([{"cwd": c.cwd, "argv": list(c.argv)} for c in commands], indent=2))
        return 0
    if args.run:
        return run(commands, args.repo)
    print(f"# {len(paths)} changed paths")
    for reason in plan.reasons:
        print(f"# because {reason}")
    for command in commands:
        print(command.shell())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""affected_tests.py maps changed paths to the gates that guard them."""

from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import affected_tests as at  # noqa: E402

REPO = at.REPO


def shell_lines(*paths: str) -> list[str]:
    return [c.shell() for c in at.commands_for(at.plan_for(list(paths)), "origin/main")]


def test_every_rule_names_existing_tests_and_known_commands():
    for rule in at.RULES:
        assert rule.globs and rule.why
        for name in (*rule.pure, *rule.compiled):
            assert (REPO / "server" / "tests" / f"{name}.py").exists(), f"{rule.why}: tests/{name}.py is missing"
        for key in rule.web:
            assert key in at.WEB_COMMANDS
        for key in rule.checks:
            assert key in at.CHECKS
            assert (REPO / at.CHECKS[key][0]).exists()


def test_every_glob_matches_a_tracked_file():
    tracked = subprocess.run(["git", "ls-files"], cwd=REPO, check=True, capture_output=True,
                             text=True).stdout.splitlines()
    for rule in at.RULES:
        for glob in rule.globs:
            assert any(fnmatch.fnmatchcase(path, glob) for path in tracked), f"{glob} matches no tracked file"


def test_web_commands_exist_in_the_web_toolchain():
    package = json.loads((REPO / "web" / "package.json").read_text())
    tools = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
    for tool in ("vitest", "typescript", "oxlint"):
        assert tool in tools
    assert (REPO / "web" / "tsconfig.app.json").exists()


def test_a_server_state_change_requires_the_offline_parity_fixture():
    plan = at.plan_for(["server/shengji/api/server.py"])
    assert "test_offline_server_fixture_gen" in plan.pure
    assert {"test_server_ws", "test_client_server_constants"} <= set(plan.pure)
    assert plan.web == ["vitest-offline"]
    assert {"comment-provenance", "ci-test-selection"} <= set(plan.checks)


def test_a_matchmaking_change_runs_its_own_tests():
    plan = at.plan_for(["server/shengji/api/matchmaking.py"])
    assert {"test_matchmaking", "test_offline_server_fixture_gen"} <= set(plan.pure)


def test_fly_toml_requires_the_release_identity_tests():
    plan = at.plan_for(["fly.toml"])
    assert {"test_release_manifests", "test_release51_fly_config", "test_release52_fly_config"} <= set(plan.pure)
    assert "test_release_manifests" in plan.compiled
    assert plan.web == [] and plan.checks == []


@pytest.mark.parametrize("path", ["server/shengji/engine/combos.py", "server/shengji/rl/encode.py",
                                  "server/shengji/ai/memory.py", "server/shengji/teacher_v1.py"])
def test_engine_closure_runs_both_engines_and_the_encoder_compat_test(path):
    plan = at.plan_for([path])
    for engine in (plan.pure, plan.compiled):
        assert {"test_encoder_round_compat", "test_engine_parity", "test_offline_fixture_gen"} <= set(engine)


def test_offline_web_server_runs_the_offline_suite_and_the_server_fixture():
    plan = at.plan_for(["web/src/offline/server/server.ts"])
    assert {"test_offline_server_fixture_gen", "test_client_server_constants"} <= set(plan.pure)
    # Any web change runs the full vitest suite, which covers src/offline.
    assert plan.web == ["vitest", "tsc", "oxlint"]


def test_offline_subset_stands_alone_without_a_web_change():
    assert at.plan_for(["server/scripts/gen_offline_server_fixtures.py"]).web == ["vitest-offline"]


def test_own_tests_are_derived():
    assert "test_receipt_summary" in at.plan_for(["server/scripts/receipt_summary.py"]).pure
    assert at.plan_for(["server/tests/test_engine.py"]).pure == ["test_engine"]
    assert at.plan_for(["README.md"]).pure == []


def test_unrelated_paths_need_nothing():
    plan = at.plan_for(["docs/notes.md"])
    assert at.commands_for(plan, "origin/main") == []


def test_commands_are_grouped_per_engine_and_tool():
    lines = shell_lines("fly.toml", "server/shengji/api/server.py")
    pure = [line for line in lines if "--engine pure" in line]
    assert len(pure) == 1 and pure[0].startswith("cd server && ")
    assert "tests/test_offline_server_fixture_gen.py" in pure[0] and "tests/test_release52_fly_config.py" in pure[0]
    assert "cd web && npx vitest run src/offline" in lines
    assert any(line.endswith("server/scripts/check_comment_provenance.py --base origin/main") for line in lines)


def test_cli_json_and_explicit_paths():
    out = subprocess.run([sys.executable, str(REPO / "server/scripts/affected_tests.py"), "--json", "fly.toml"],
                         check=True, capture_output=True, text=True).stdout
    commands = json.loads(out)
    assert {c["cwd"] for c in commands} == {"server"}
    assert all(c["argv"][1] == "scripts/test_checkout.py" for c in commands)


def test_cli_needs_paths_or_base():
    done = subprocess.run([sys.executable, str(REPO / "server/scripts/affected_tests.py")],
                          capture_output=True, text=True)
    assert done.returncode == 2


def test_run_reports_each_rc_and_fails_on_any(tmp_path, capsys):
    ok = at.Command(".", (sys.executable, "-c", "pass"))
    bad = at.Command(".", (sys.executable, "-c", "raise SystemExit(3)"))
    assert at.run([bad, ok], repo=tmp_path) == 1
    out = capsys.readouterr().out
    assert "rc=3 " in out and "rc=0 " in out and "1/2 commands passed" in out
    assert at.run([], repo=tmp_path) == 0


def test_changed_paths_include_branch_uncommitted_and_untracked(tmp_path):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    (tmp_path / "a.txt").write_text("a")
    git("add", "a.txt")
    git("commit", "-q", "-m", "a")
    git("switch", "-q", "-c", "topic")
    (tmp_path / "fly.toml").write_text("x")
    git("add", "fly.toml")
    git("commit", "-q", "-m", "fly")
    (tmp_path / "a.txt").write_text("changed")
    (tmp_path / "new.txt").write_text("n")
    assert at.changed_paths("main", tmp_path) == ["a.txt", "fly.toml", "new.txt"]


def _fake_venv(root: Path) -> Path:
    python = root / "server" / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)
    return python


@pytest.fixture
def main_and_worktree(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    def git(*args, cwd=main):
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    (main / "a.txt").write_text("a")
    git("add", "a.txt")
    git("commit", "-q", "-m", "a")
    worktree = tmp_path / "wt"
    git("worktree", "add", "-q", "-b", "topic", str(worktree))
    return main, worktree


def test_a_worktree_without_a_venv_uses_the_main_worktree_venv(main_and_worktree):
    main, worktree = main_and_worktree
    expected = _fake_venv(main)
    assert Path(at.resolve_python(worktree, env={})).resolve() == expected.resolve()


def test_the_worktree_venv_wins_over_the_main_one(main_and_worktree):
    main, worktree = main_and_worktree
    _fake_venv(main)
    own = _fake_venv(worktree)
    assert at.resolve_python(worktree, env={}) == str(own)


def test_shengji_py_wins(main_and_worktree):
    main, worktree = main_and_worktree
    _fake_venv(main)
    _fake_venv(worktree)
    assert at.resolve_python(worktree, env={"SHENGJI_PY": "/opt/py"}) == "/opt/py"


def test_no_venv_anywhere_is_a_clear_error(main_and_worktree, capsys):
    _, worktree = main_and_worktree
    with pytest.raises(at.NoInterpreter, match="SHENGJI_PY"):
        at.resolve_python(worktree, env={})
    done = subprocess.run([sys.executable, str(REPO / "server/scripts/affected_tests.py"),
                           "--repo", str(worktree), "fly.toml"],
                          env={k: v for k, v in os.environ.items() if k != "SHENGJI_PY"},
                          capture_output=True, text=True)
    assert done.returncode == 2 and "no checkout virtualenv found" in done.stderr


def test_checks_use_the_resolved_interpreter_too(main_and_worktree, monkeypatch):
    _, worktree = main_and_worktree
    monkeypatch.setenv("SHENGJI_PY", "/opt/py")
    commands = at.commands_for(at.plan_for(["server/shengji/api/server.py"]), "origin/main", worktree)
    pythons = {c.argv[0] for c in commands if c.cwd != "web"}
    assert pythons == {"/opt/py"} and len([c for c in commands if c.cwd == "."]) == 2


def test_a_plan_without_python_gates_needs_no_interpreter(tmp_path):
    plan = at.Plan([], [], ["vitest"], [], [])
    assert [c.cwd for c in at.commands_for(plan, "origin/main", tmp_path)] == ["web"]

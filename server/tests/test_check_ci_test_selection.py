"""Synthetic-tree tests for scripts/check_ci_test_selection.py."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_ci_test_selection.py"
_spec = importlib.util.spec_from_file_location("check_ci_test_selection", SCRIPT)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


def make_tree(tmp_path: Path, *, workflow: str, tests: list[str], exclusions: str = "", scripts=None) -> Path:
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "pr-checks.yml").write_text(workflow)
    tests_dir = tmp_path / "server" / "tests"
    tests_dir.mkdir(parents=True)
    for name in tests:
        (tests_dir / name).write_text("def test_ok():\n    pass\n")
    (tests_dir / "ci_selection_exclusions.txt").write_text(exclusions)
    for rel, body in (scripts or {}).items():
        path = tmp_path / "server" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    return tmp_path


def wf(run: str) -> str:
    return (
        "jobs:\n  server:\n    defaults:\n      run:\n        working-directory: server\n"
        "    steps:\n      - name: Run\n        run: >-\n          " + run + "\n"
    )


def test_listed_file_passes(tmp_path, capsys):
    root = make_tree(tmp_path, workflow=wf("uv run pytest tests/test_a.py"), tests=["test_a.py"])
    assert check.run(root) == 0
    assert "OK total=1 selected=1 excluded=0" in capsys.readouterr().out


def test_glob_selected_file_passes(tmp_path):
    root = make_tree(tmp_path, workflow=wf("uv run pytest tests/test_*cwv*.py"), tests=["test_x_cwv_y.py"])
    assert check.run(root) == 0


def test_unselected_file_fails(tmp_path, capsys):
    root = make_tree(tmp_path, workflow=wf("uv run pytest tests/test_a.py"), tests=["test_a.py", "test_new.py"])
    assert check.run(root) == 1
    out = capsys.readouterr().out
    assert "selected by no CI job" in out and "server/tests/test_new.py" in out


def test_commented_reference_does_not_select(tmp_path):
    workflow = wf("uv run pytest tests/test_a.py") + "      # tests/test_new.py is slow\n"
    root = make_tree(tmp_path, workflow=workflow, tests=["test_a.py", "test_new.py"])
    assert check.run(root) == 1


def test_excluded_file_passes(tmp_path):
    root = make_tree(
        tmp_path,
        workflow=wf("uv run pytest tests/test_a.py"),
        tests=["test_a.py", "test_slow.py"],
        exclusions="# header\nserver/tests/test_slow.py  # needs a GPU\n",
    )
    assert check.run(root) == 0


def test_stale_exclusion_of_selected_file_fails(tmp_path, capsys):
    root = make_tree(
        tmp_path,
        workflow=wf("uv run pytest tests/test_a.py"),
        tests=["test_a.py"],
        exclusions="server/tests/test_a.py\n",
    )
    assert check.run(root) == 1
    assert "now selected by CI" in capsys.readouterr().out


def test_stale_exclusion_of_missing_file_fails(tmp_path, capsys):
    root = make_tree(
        tmp_path,
        workflow=wf("uv run pytest tests/test_a.py"),
        tests=["test_a.py"],
        exclusions="server/tests/test_gone.py\n",
    )
    assert check.run(root) == 1
    assert "name no existing test file" in capsys.readouterr().out


def test_script_invoked_by_workflow_selects_by_glob(tmp_path):
    root = make_tree(
        tmp_path,
        workflow=wf("bash scripts/ci_modes.sh"),
        tests=["test_one_cwv.py", "test_two_cwv.py"],
        scripts={"scripts/ci_modes.sh": "#!/bin/sh\nuv run pytest -q tests/test_*cwv*.py\n"},
    )
    assert check.run(root) == 0


def test_dangling_reference_fails(tmp_path, capsys):
    root = make_tree(tmp_path, workflow=wf("uv run pytest tests/test_a.py tests/test_missing.py"), tests=["test_a.py"])
    assert check.run(root) == 1
    assert "match no file" in capsys.readouterr().out


def test_prose_word_tests_does_not_select_directory(tmp_path):
    workflow = wf("uv run pytest tests/test_a.py") + "      - name: Run server tests\n        run: echo hi\n"
    root = make_tree(tmp_path, workflow=workflow, tests=["test_a.py", "test_b.py"])
    assert check.run(root) == 1


def test_pytest_directory_argument_selects_all(tmp_path):
    root = make_tree(tmp_path, workflow=wf("uv run pytest -q tests"), tests=["test_a.py", "test_b.py"])
    assert check.run(root) == 0


# --- Only executed configuration selects tests (#764 review) -----------------
# The first two cases reproduce Codex's HOLD witnesses verbatim.


def test_non_execution_reference_cannot_select_tests(tmp_path):
    workflow = """jobs:
  smoke:
    steps:
      - name: Inspect tests/
        run: echo no-tests-executed
"""
    root = make_tree(tmp_path, workflow=workflow, tests=["test_new.py"])
    assert check.run(root) == 1


def test_paths_filter_is_not_execution(tmp_path):
    workflow = """on:
  pull_request:
    paths:
      - server/tests/test_new.py
jobs:
  smoke:
    steps:
      - run: echo no-tests-executed
"""
    root = make_tree(tmp_path, workflow=workflow, tests=["test_new.py"])
    assert check.run(root) == 1


def test_env_and_if_fields_do_not_select(tmp_path):
    workflow = """jobs:
  smoke:
    steps:
      - name: Smoke
        if: contains('tests/test_new.py pytest', 'x')
        env:
          TARGET: pytest tests/test_new.py
        run: echo pytest-free
"""
    root = make_tree(tmp_path, workflow=workflow, tests=["test_new.py"])
    assert check.run(root) == 1


def test_unreferenced_matrix_value_does_not_select(tmp_path):
    workflow = """jobs:
  smoke:
    strategy:
      matrix:
        tests:
          - "tests/test_a.py"
        unused: ["tests/test_new.py"]
    steps:
      - run: uv run pytest -q ${{ matrix.tests }}
"""
    root = make_tree(tmp_path, workflow=workflow, tests=["test_a.py", "test_new.py"])
    assert check.run(root) == 1
    selected, _, _, _ = check.collect_selection(root)
    assert selected == {"server/tests/test_a.py"}


def test_referenced_matrix_values_select(tmp_path):
    workflow = """jobs:
  smoke:
    strategy:
      fail-fast: false
      matrix:
        tests:
          - "tests/test_a.py tests/test_b.py"
          - "tests/test_c.py"
        engine: [pure, compiled]
    steps:
      - name: Run
        if: matrix.tests == 'tests/test_a.py tests/test_b.py'
        run: uv run pytest -q ${{ matrix.tests }}
"""
    root = make_tree(tmp_path, workflow=workflow, tests=["test_a.py", "test_b.py", "test_c.py"])
    assert check.run(root) == 0


def test_matrix_of_another_job_is_not_used(tmp_path):
    workflow = """jobs:
  one:
    strategy:
      matrix:
        tests: ["tests/test_new.py"]
    steps:
      - run: echo ${{ matrix.tests }}
  two:
    steps:
      - run: uv run pytest -q ${{ matrix.tests }}
"""
    root = make_tree(tmp_path, workflow=workflow, tests=["test_new.py"])
    assert check.run(root) == 1


def test_literal_block_with_continuations_selects(tmp_path):
    workflow = """jobs:
  smoke:
    steps:
      - run: |
          # tests/test_commented.py is not run
          uv run python -m pytest -q \\
            tests/test_a.py \\
            tests/test_b.py
          echo tests/test_echoed.py
      - name: after
        run: echo done
"""
    root = make_tree(
        tmp_path,
        workflow=workflow,
        tests=["test_a.py", "test_b.py"],
        exclusions="server/tests/test_commented.py\nserver/tests/test_echoed.py\n",
    )
    # The two excluded names do not exist as files, so they are stale, but the
    # selection itself must be exactly the pytest arguments.
    selected, _, _, _ = check.collect_selection(root)
    assert selected == {"server/tests/test_a.py", "server/tests/test_b.py"}


def test_directory_token_needs_pytest_on_the_same_line(tmp_path):
    workflow = """jobs:
  smoke:
    steps:
      - run: |
          ls tests/
          uv run pytest -q tests/test_a.py
"""
    root = make_tree(tmp_path, workflow=workflow, tests=["test_a.py", "test_new.py"])
    assert check.run(root) == 1


def test_script_comment_does_not_select(tmp_path):
    root = make_tree(
        tmp_path,
        workflow=wf("bash scripts/ci_modes.sh"),
        tests=["test_a.py", "test_new.py"],
        scripts={"scripts/ci_modes.sh": "# uv run pytest tests/test_new.py\nuv run pytest tests/test_a.py\n"},
    )
    assert check.run(root) == 1


def test_script_named_outside_run_is_not_followed(tmp_path):
    workflow = """jobs:
  smoke:
    steps:
      - name: bash scripts/ci_modes.sh
        run: echo nothing
"""
    root = make_tree(
        tmp_path,
        workflow=workflow,
        tests=["test_a.py"],
        scripts={"scripts/ci_modes.sh": "uv run pytest tests/test_a.py\n"},
    )
    assert check.run(root) == 1


def test_quoted_pytest_in_echo_does_not_select(tmp_path):
    root = make_tree(
        tmp_path,
        workflow=wf('uv run pytest tests/test_a.py; echo "pytest tests/test_new.py"'),
        tests=["test_a.py", "test_new.py"],
    )
    assert check.run(root) == 1


def test_sibling_command_path_does_not_select(tmp_path):
    root = make_tree(
        tmp_path,
        workflow=wf("uv run pytest tests/test_a.py; echo tests/test_new.py"),
        tests=["test_a.py", "test_new.py"],
    )
    assert check.run(root) == 1


def test_echo_of_pytest_alone_selects_nothing(tmp_path):
    root = make_tree(tmp_path, workflow=wf('echo "pytest tests/test_new.py"'), tests=["test_new.py"])
    assert check.run(root) == 1


def test_supported_pytest_invocations_select(tmp_path):
    forms = [
        "pytest tests/test_a.py",
        "env -u SHENGJI_FAST uv run pytest -q tests/test_b.py",
        "SHENGJI_FAST=1 uv run python -B -m pytest -q tests/test_c.py::test_ok",
        "uv run python -P -B -m pytest -q tests/test_d.py",
        "uv run -m pytest tests/test_e.py",
        "(uv run python -m pytest -q tests/test_f.py 2>&1 | sed -u 's/^/x /') &",
        "python3 -m pytest server/tests/test_g.py",
        "uv run python scripts/test_checkout.py --engine pure -- -q --durations=10 tests/test_h.py",
    ]
    names = [f"test_{c}.py" for c in "abcdefgh"]
    for k, form in enumerate(forms):
        root = make_tree(tmp_path / str(k), workflow=wf(form), tests=[names[k]])
        assert check.run(root) == 0, form


def test_ignored_and_deselected_paths_do_not_select(tmp_path):
    root = make_tree(
        tmp_path,
        workflow=wf("uv run pytest tests --ignore tests/test_new.py --deselect tests/test_a.py::test_ok"),
        tests=["test_a.py", "test_new.py"],
    )
    selected, _, _, _ = check.collect_selection(root)
    assert selected == {"server/tests/test_a.py", "server/tests/test_new.py"}  # the directory still selects
    root2 = make_tree(
        tmp_path / "b",
        workflow=wf("uv run pytest tests/test_a.py --ignore tests/test_new.py"),
        tests=["test_a.py", "test_new.py"],
    )
    assert check.run(root2) == 1


def test_checkout_wrapper_selects_only_after_double_dash(tmp_path):
    root = make_tree(
        tmp_path,
        workflow=wf("uv run python scripts/test_checkout.py --engine pure tests/test_new.py -- tests/test_a.py"),
        tests=["test_a.py", "test_new.py"],
    )
    selected, _, _, _ = check.collect_selection(root)
    assert selected == {"server/tests/test_a.py"}


def test_script_named_as_an_argument_is_not_followed(tmp_path):
    scripts = {"scripts/fake.sh": "uv run pytest tests/test_new.py\n"}
    for k, run in enumerate(["echo scripts/fake.sh", 'printf "%s" "bash scripts/fake.sh"', "cat scripts/fake.sh"]):
        root = make_tree(
            tmp_path / str(k),
            workflow=wf("uv run pytest tests/test_a.py; " + run),
            tests=["test_a.py", "test_new.py"],
            scripts=scripts,
        )
        assert check.run(root) == 1, run


def test_executed_script_forms_are_followed(tmp_path):
    scripts = {"scripts/real.sh": "uv run pytest tests/test_new.py\n"}
    forms = ["bash scripts/real.sh", "bash -eu scripts/real.sh", "sh scripts/real.sh", "./scripts/real.sh",
             "scripts/real.sh", "source scripts/real.sh", ". scripts/real.sh", "X=1 bash server/scripts/real.sh"]
    for k, run in enumerate(forms):
        root = make_tree(tmp_path / str(k), workflow=wf(run), tests=["test_new.py"], scripts=scripts)
        assert check.run(root) == 0, run


def test_python_dash_c_is_not_pytest(tmp_path):
    for k, run in enumerate(["python -c pass -m pytest tests/test_new.py", "python -B -c 'import x' -m pytest tests/test_new.py"]):
        root = make_tree(tmp_path / str(k), workflow=wf(run), tests=["test_new.py"])
        assert check.run(root) == 1, run


def test_untokenizable_pytest_line_fails_closed(tmp_path, capsys):
    root = make_tree(tmp_path, workflow=wf("uv run pytest tests/test_a.py 'unclosed"), tests=["test_a.py"])
    assert check.run(root) == 1
    assert "could not be tokenized" in capsys.readouterr().out


def test_repository_selection_is_clean():
    proc = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --- Engine modes: boundary tests run under both engines (#888, #891) --------

BOUNDARY = "from shengji.engine import legal\n\ndef test_ok():\n    pass\n"


def make_engine_tree(tmp_path, *, workflow, bodies, exclusions="", engine_exclusions="", scripts=None):
    root = make_tree(tmp_path, workflow=workflow, tests=[], exclusions=exclusions, scripts=scripts)
    for name, body in bodies.items():
        (root / "server" / "tests" / name).write_text(body)
    (root / "server" / "tests" / "ci_engine_mode_exclusions.txt").write_text(engine_exclusions)
    return root


def two_steps(pure: str, compiled: str) -> str:
    return (
        "jobs:\n  server:\n    steps:\n"
        "      - name: Pure\n        run: uv run python scripts/test_checkout.py --engine pure -- -q " + pure + "\n"
        "      - name: Compiled\n        env:\n          SHENGJI_FAST: \"1\"\n"
        "        run: uv run pytest -q " + compiled + "\n"
    )


def modes_of(root, name="test_b.py"):
    return check.scan_selection(root)["modes"].get(f"server/tests/{name}", set())


def test_boundary_test_in_both_engines_passes(tmp_path, capsys):
    root = make_engine_tree(tmp_path, workflow=two_steps("tests/test_b.py", "tests/test_b.py"), bodies={"test_b.py": BOUNDARY})
    assert check.run(root) == 0
    out = capsys.readouterr().out
    assert "ci-engine-modes: OK boundary_tests=1 both=1" in out
    assert "ci-test-selection: OK total=1 selected=1 excluded=0" in out


def test_boundary_test_in_pure_only_fails(tmp_path, capsys):
    """The #888 shape: selected by the pure job, never under SHENGJI_FAST=1."""
    root = make_engine_tree(
        tmp_path,
        workflow=two_steps("tests/test_b.py tests/test_c.py", "tests/test_c.py"),
        bodies={"test_b.py": BOUNDARY, "test_c.py": "def test_ok():\n    pass\n"},
    )
    assert check.run(root) == 1
    out = capsys.readouterr().out
    assert "server/tests/test_b.py  (no compiled selection; imports shengji.engine.legal)" in out
    assert "ci-engine-modes: FAIL" in out and "ci-test-selection: FAIL" in out


def test_boundary_test_in_compiled_only_fails(tmp_path, capsys):
    root = make_engine_tree(
        tmp_path,
        workflow=two_steps("tests/test_c.py", "tests/test_b.py tests/test_c.py"),
        bodies={"test_b.py": BOUNDARY, "test_c.py": "def test_ok():\n    pass\n"},
    )
    assert check.run(root) == 1
    assert "(no pure selection" in capsys.readouterr().out


def test_non_boundary_test_needs_one_engine_only(tmp_path):
    body = '"""Mentions shengji.engine.legal in prose only."""\nimport shengji.engine.combos\n# from shengji.engine import legal\n\ndef test_ok():\n    pass\n'
    root = make_engine_tree(tmp_path, workflow=two_steps("tests/test_b.py", "tests/test_c.py"),
                            bodies={"test_b.py": body, "test_c.py": "def test_ok():\n    pass\n"})
    assert check.run(root) == 0


def test_engine_mode_exclusion_passes(tmp_path):
    root = make_engine_tree(
        tmp_path,
        workflow=two_steps("tests/test_b.py", "tests/test_c.py"),
        bodies={"test_b.py": BOUNDARY, "test_c.py": "def test_ok():\n    pass\n"},
        engine_exclusions="# header\nserver/tests/test_b.py  # compiled run needs a GPU\n",
    )
    assert check.run(root) == 0


def test_stale_engine_mode_exclusions_fail(tmp_path, capsys):
    plain = "def test_ok():\n    pass\n"
    cases = {
        "now selected in both": ({"test_b.py": BOUNDARY}, "test_b.py", "is now selected in both modes"),
        "gone": ({"test_b.py": BOUNDARY}, "test_gone.py", "no longer exists"),
        "no import": ({"test_b.py": BOUNDARY, "test_p.py": plain}, "test_p.py", "no longer imports the engine boundary"),
    }
    for k, (bodies, listed, reason) in enumerate(cases.values()):
        names = " ".join(f"tests/{n}" for n in bodies)
        root = make_engine_tree(tmp_path / str(k), workflow=two_steps(names, names), bodies=bodies,
                                engine_exclusions=f"server/tests/{listed}\n")
        assert check.run(root) == 1, listed
        out = capsys.readouterr().out
        assert "engine-mode exclusion(s) are stale" in out and reason in out, out


def test_selection_excluded_boundary_test_is_exempt_and_double_listing_is_stale(tmp_path, capsys):
    workflow = two_steps("tests/test_c.py", "tests/test_c.py")
    bodies = {"test_b.py": BOUNDARY, "test_c.py": "def test_ok():\n    pass\n"}
    root = make_engine_tree(tmp_path / "a", workflow=workflow, bodies=bodies, exclusions="server/tests/test_b.py\n")
    assert check.run(root) == 0
    root = make_engine_tree(tmp_path / "b", workflow=workflow, bodies=bodies, exclusions="server/tests/test_b.py\n",
                            engine_exclusions="server/tests/test_b.py\n")
    assert check.run(root) == 1
    assert "is selection-excluded" in capsys.readouterr().out


def test_boundary_import_forms_are_detected(tmp_path):
    forms = [
        "from shengji.engine import legal",
        "from shengji.engine.legal import validate_follow",
        "import shengji.engine.fast as F",
        "from shengji.engine import cards, fast",
        "import pytest\n_fast = pytest.importorskip('shengji.engine._fast')",
        "import importlib\nL = importlib.import_module('shengji.engine.legal')",
        "def helper():\n    from shengji.luna.benchmark_games import play",
        "from shengji.luna import benchmark_games",
    ]
    luna = {"shengji/luna/benchmark_games.py": "from shengji.engine.legal import IllegalPlay\n",
            "shengji/luna/benchmark_recipes.py": "from .canonical import x\n"}
    for k, form in enumerate(forms):
        root = make_engine_tree(tmp_path / str(k), workflow=two_steps("tests/test_b.py", "tests/test_c.py"),
                                bodies={"test_b.py": form + "\n", "test_c.py": "def test_ok():\n    pass\n"},
                                scripts=luna)
        assert check.run(root) == 1, form
    # A benchmark module that does not import a core engine module is outside the boundary.
    root = make_engine_tree(tmp_path / "r", workflow=two_steps("tests/test_b.py", "tests/test_c.py"),
                            bodies={"test_b.py": "from shengji.luna import benchmark_recipes\n",
                                    "test_c.py": "def test_ok():\n    pass\n"}, scripts=luna)
    assert check.run(root) == 0
    assert check.engine_boundary_modules(root) == set(check.ENGINE_CORE_MODULES) | {"shengji.luna.benchmark_games"}


def test_relative_import_in_benchmark_module_resolves(tmp_path):
    luna = {"shengji/luna/benchmark_x.py": "from ..engine.legal import IllegalPlay\n"}
    root = make_engine_tree(tmp_path, workflow=two_steps("tests/test_c.py", "tests/test_c.py"),
                            bodies={"test_c.py": "def test_ok():\n    pass\n"}, scripts=luna)
    assert "shengji.luna.benchmark_x" in check.engine_boundary_modules(root)


def test_engine_mode_classification(tmp_path):
    cases = [
        # (workflow run text, step env SHENGJI_FAST or None, expected modes)
        ("uv run pytest tests/test_b.py", None, {"pure"}),
        ("uv run pytest tests/test_b.py", '"0"', {"pure"}),
        ("uv run pytest tests/test_b.py", '"1"', {"compiled"}),
        ("uv run pytest tests/test_b.py", "${{ matrix.fast }}", set()),
        ("SHENGJI_FAST=1 uv run python -m pytest tests/test_b.py", None, {"compiled"}),
        ("env -u SHENGJI_FAST uv run pytest tests/test_b.py", '"1"', {"pure"}),
        ("env SHENGJI_FAST=1 uv run pytest tests/test_b.py", None, {"compiled"}),
        ("uv run python scripts/test_checkout.py --engine compiled -- tests/test_b.py", None, {"compiled"}),
        ("uv run python scripts/test_checkout.py --engine=pure -- tests/test_b.py", '"1"', {"pure"}),
        ("export SHENGJI_FAST=1; uv run pytest tests/test_b.py", None, {"compiled"}),
        ("unset SHENGJI_FAST && uv run pytest tests/test_b.py", '"1"', {"pure"}),
        ("uv run pytest tests/test_b.py; export SHENGJI_FAST=1", None, {"pure"}),
        ('if [ "$X" = "y" ]; then export SHENGJI_FAST=1; fi; uv run pytest tests/test_b.py', None, set()),
    ]
    for k, (run, env, expected) in enumerate(cases):
        env_block = f"        env:\n          SHENGJI_FAST: {env}\n" if env else ""
        workflow = "jobs:\n  j:\n    steps:\n      - name: s\n" + env_block + "        run: " + run + "\n"
        root = make_engine_tree(tmp_path / str(k), workflow=workflow, bodies={"test_b.py": BOUNDARY})
        assert modes_of(root) == expected, (run, env)


def test_job_and_workflow_env_apply_and_step_env_wins(tmp_path):
    workflow = """env:
  SHENGJI_FAST: "1"
jobs:
  a:
    steps:
      - run: uv run pytest tests/test_b.py
  b:
    env:
      SHENGJI_FAST: "0"
    steps:
      - run: uv run pytest tests/test_c.py
      - env:
          SHENGJI_FAST: "1"
        run: uv run pytest tests/test_d.py
"""
    root = make_engine_tree(tmp_path, workflow=workflow,
                            bodies={"test_b.py": BOUNDARY, "test_c.py": BOUNDARY, "test_d.py": BOUNDARY})
    assert modes_of(root, "test_b.py") == {"compiled"}
    assert modes_of(root, "test_c.py") == {"pure"}
    assert modes_of(root, "test_d.py") == {"compiled"}


def test_engine_matrix_with_shell_branch_runs_both(tmp_path):
    """The search-regression shape: one step, matrix engine [pure, compiled]."""
    workflow = """jobs:
  search:
    strategy:
      matrix:
        engine: [pure, compiled]
    steps:
      - name: Test
        run: |
          if [ "${{ matrix.engine }}" = "pure" ]; then
            unset SHENGJI_FAST
          else
            export SHENGJI_FAST=1
          fi
          uv run python -B - <<'PY'
          if True:
              import os
          PY
          uv run python -B -m pytest -q \\
            tests/test_b.py
"""
    root = make_engine_tree(tmp_path, workflow=workflow, bodies={"test_b.py": BOUNDARY})
    assert modes_of(root) == {"pure", "compiled"}
    assert check.run(root) == 0
    one = workflow.replace("[pure, compiled]", "[compiled]")
    root = make_engine_tree(tmp_path / "one", workflow=one, bodies={"test_b.py": BOUNDARY})
    assert modes_of(root) == {"compiled"}
    assert check.run(root) == 1


def test_script_inherits_and_overrides_engine_mode(tmp_path):
    """The ci_cwv_modes.sh shape, plus a script invoked from a compiled step."""
    scripts = {
        "scripts/modes.sh": "(env -u SHENGJI_FAST uv run python -m pytest tests/test_b.py 2>&1 | sed 's/^/x/') &\n"
                            "(SHENGJI_FAST=1 uv run python -m pytest tests/test_b.py 2>&1 | sed 's/^/y/') &\n",
        "scripts/plain.sh": "uv run pytest tests/test_c.py\n",
    }
    workflow = """jobs:
  j:
    steps:
      - run: bash scripts/modes.sh
      - env:
          SHENGJI_FAST: "1"
        run: bash scripts/plain.sh
      - run: bash scripts/plain.sh
"""
    root = make_engine_tree(tmp_path, workflow=workflow, bodies={"test_b.py": BOUNDARY, "test_c.py": BOUNDARY},
                            scripts=scripts)
    assert modes_of(root, "test_b.py") == {"pure", "compiled"}
    assert modes_of(root, "test_c.py") == {"pure", "compiled"}
    assert check.run(root) == 0

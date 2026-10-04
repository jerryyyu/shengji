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
    selected, _, _ = check.collect_selection(root)
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
    selected, _, _ = check.collect_selection(root)
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


def test_repository_selection_is_clean():
    proc = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr

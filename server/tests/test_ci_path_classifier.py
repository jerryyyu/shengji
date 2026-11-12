"""The workflow's path classifier: which changes run the training suites.

The ``changes`` job's classify step decides the ``code``, ``luna`` and
``train`` outputs. These tests load that step's exact Python from the workflow
and call its functions on this checkout, so a change to the rule, to the
train-* job selections or to the web fixtures they read is checked here.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "pr-checks.yml"


@pytest.fixture(scope="module")
def rules():
    text = WORKFLOW.read_text()
    step = re.search(r"\n      - name: Classify changed paths\n(.*?)\n          PY\n", text, re.S)
    assert step, "classify step not found"
    body = step.group(1).split("<<'PY'\n", 1)[1]
    source = "\n".join(line[10:] for line in body.splitlines())
    # the functions only; the trailing block runs the classification
    functions = source.split("\ntry:\n", 1)[0]
    namespace: dict = {}
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        exec(compile(functions, str(WORKFLOW), "exec"), namespace)
        tests, web = namespace["train_inputs"]()
    finally:
        os.chdir(cwd)
    return namespace["reaches_train"], tests, web


@pytest.mark.parametrize("path, runs", [
    ("web/src/App.tsx", False),
    ("web/src/index.css", False),
    ("web/ios/App/App/ShellViewController.swift", False),
    ("web/package.json", False),
    ("docs/atlas_v2/registry.json", False),
    ("PROTOCOL.md", False),
    ("server/tests/test_matchmaking.py", False),
    ("server/shengji/api/server.py", True),
    ("server/shengji/train/cwv_train.py", True),
    ("server/scripts/ci_cwv_modes.sh", True),
    ("server/tests/conftest.py", True),
    ("server/tests/test_cwv_pack.py", True),
    ("server/tests/test_screen_deadline_child.py", True),
    ("fly.toml", True),
    (".github/workflows/pr-checks.yml", True),
])
def test_which_paths_run_the_training_suites(rules, path, runs):
    reaches_train, tests, web = rules
    assert reaches_train(path, tests, web) is runs


def test_every_web_file_a_training_suite_names_runs_them(rules):
    reaches_train, tests, web = rules
    assert "web/src/components/xray-shortlist.fixture.json" in web
    for path in web:
        assert (ROOT / path).exists(), path
        assert reaches_train(path, tests, web)


def test_the_training_selection_covers_both_scripts_and_their_helpers(rules):
    _, tests, _ = rules
    assert "server/tests/test_screen_deadline_child.py" in tests
    assert "server/tests/test_policy_prior.py" in tests
    # imported by test_cwv_archive_read, selected by no glob of its own
    assert "server/tests/test_cwv_loader_timing.py" in tests
    assert len(tests) > 100

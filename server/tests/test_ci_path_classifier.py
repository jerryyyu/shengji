"""The workflow's path classifier: which changes run which heavy jobs.

The ``changes`` job's classify step decides the ``code``, ``luna``,
``train``, ``search`` and ``server_*`` outputs. These tests load that step's exact Python from the workflow
and call its functions on this checkout, so a change to the rule, to the
train-* job selections or to the web fixtures they read is checked here.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "pr-checks.yml"


@pytest.fixture(scope="module")
def classifier():
    """The classify step's namespace, its functions defined on this checkout."""
    text = WORKFLOW.read_text()
    step = re.search(r"\n      - name: Classify changed paths\n(.*?)\n          PY\n", text, re.S)
    assert step, "classify step not found"
    body = step.group(1).split("<<'PY'\n", 1)[1]
    source = "\n".join(line[10:] for line in body.splitlines())
    # the functions only; the trailing block runs the classification
    functions = source.rsplit("\ntry:\n", 1)[0]
    namespace: dict = {}
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        exec(compile(functions, str(WORKFLOW), "exec"), namespace)
    finally:
        os.chdir(cwd)
    return namespace


def in_root(function, *args):
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        return function(*args)
    finally:
        os.chdir(cwd)


@pytest.fixture(scope="module")
def rules(classifier):
    tests, web = in_root(classifier["train_inputs"])
    return classifier["reaches_train"], tests, web


@pytest.mark.parametrize("path, runs", [
    ("web/src/App.tsx", False),
    ("web/src/index.css", False),
    ("web/ios/App/App/ShellViewController.swift", False),
    ("web/package.json", False),
    ("docs/atlas_v2/registry.json", False),
    ("PROTOCOL.md", False),
    ("server/tests/test_matchmaking.py", False),
    ("server/tests/test_server_ws.py", False),
    ("server/shengji/api/server.py", True),
    ("server/shengji/train/cwv_train.py", True),
    ("server/scripts/ci_cwv_modes.sh", True),
    ("server/tests/conftest.py", True),
    ("server/tests/test_cwv_pack.py", True),
    ("server/tests/test_screen_deadline_child.py", True),
    # helpers selected modules import as `from tests.test_x import ...`
    ("server/tests/test_world_shortlist.py", True),
    ("server/tests/test_debug_xray.py", True),
    ("server/tests/test_screen_deadline.py", True),
    ("server/tests/test_bot_scheduler.py", True),
    # reached only through another helper (test_pv_adaptive_worlds)
    ("server/tests/test_panel_rank_root.py", True),
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
    # package-qualified imports: test_screen_deadline_child imports
    # `from tests.test_screen_deadline import ...`
    assert "server/tests/test_screen_deadline.py" in tests
    assert len(tests) > 100


def test_helper_discovery_reads_every_import_form(rules, tmp_path, monkeypatch):
    reaches_train, _tests, _web = rules
    namespace = reaches_train.__globals__
    tests = tmp_path / "server" / "tests"
    tests.mkdir(parents=True)
    for name in ("test_a", "test_b", "test_c", "test_d", "test_e", "test_f"):
        (tests / f"{name}.py").write_text("")
    (tests / "test_root.py").write_text(
        "import test_a\n"
        "from test_b import x\n"
        "import tests.test_c\n"
        "from tests.test_d import y\n"
        "from tests import test_e\n"
        "from . import test_f\n"          # relative: not this layout's form
        "import os, tests.conftest\n")
    (tests / "test_a.py").write_text("from tests.test_f import z\n")   # transitive
    monkeypatch.chdir(tmp_path)
    assert namespace["imported_test_modules"]("test_root") == {
        "test_a", "test_b", "test_c", "test_d", "test_e"}
    assert namespace["with_helpers"]({"test_root"}) == {
        "test_root", "test_a", "test_b", "test_c", "test_d", "test_e", "test_f"}


@pytest.fixture(scope="module")
def classify(classifier):
    return lambda *paths: in_root(classifier["classify_paths"], list(paths))


WEB_READERS = {"test_client_server_constants", "test_offline_server_fixture_gen", "test_server_ws",
               "test_support", "test_web_cache_headers", "test_ci_path_classifier"}


def test_a_web_only_change_runs_only_the_web_reading_server_modules(classify):
    out = classify("web/src/index.css", "web/src/App.tsx", "docs/design/FLOWS.md")
    assert out["code"] and out["server_web_only"]
    assert not out["server_full"] and not out["search"] and not out["luna"] and not out["train"]
    assert WEB_READERS <= set(out["server_web_pure"])
    # the offline fixture tests run in both engine modes, as in the server job
    assert {"test_offline_fixture_gen", "test_offline_server_fixture_gen"} <= set(out["server_web_compiled"])
    # a module no server step names runs in pure mode
    assert "test_cwv_debug_xray" in out["server_web_pure"]
    assert "test_matchmaking" not in out["server_web_pure"] + out["server_web_compiled"]


def test_the_web_selection_is_the_local_gate_scripts(classify):
    sys.path.insert(0, str(ROOT / "server" / "scripts"))
    import affected_tests
    out = classify("web/src/queue/store.ts")
    plan = affected_tests.plan_for(["web/src/queue/store.ts"])
    assert set(out["server_web_pure"]) | set(out["server_web_compiled"]) == set(plan.pure) | set(plan.compiled)
    assert affected_tests.web_reading_tests() <= set(plan.pure)


def test_a_web_fixture_a_training_suite_names_still_runs_it(classify):
    out = classify("web/src/components/xray-shortlist.fixture.json")
    assert out["train"] and out["server_web_only"] and not out["search"]


@pytest.mark.parametrize("paths, full, web_only, search", [
    # API source: the served-bot search witnesses import shengji.api.server
    (("server/shengji/api/server.py", "web/src/App.tsx"), True, False, True),
    (("server/shengji/api/matchmaking.py",), True, False, True),
    # API tests the search job does not select, with a web change
    (("server/tests/test_server_ws.py", "web/src/App.tsx"), True, False, False),
    (("server/tests/test_table_frame.py",), True, False, False),
    # a search module, the engine, the workflow, configuration
    (("server/tests/test_pv_search_serving.py",), True, False, True),
    (("server/shengji/engine/legal.py",), True, False, True),
    ((".github/workflows/pr-checks.yml",), True, False, True),
    (("fly.toml",), True, False, True),
    (("server/tests/conftest.py",), True, False, True),
    # documentation only
    (("docs/notes.md", "PROTOCOL.md"), False, False, False),
])
def test_server_and_search_classification(classify, paths, full, web_only, search):
    out = classify(*paths)
    assert (out["server_full"], out["server_web_only"], out["search"]) == (full, web_only, search)
    if not web_only:
        assert out["server_web_pure"] == [] and out["server_web_compiled"] == []


def test_the_search_rule_follows_its_imports(classifier):
    tests, reads_web, api = in_root(classifier["search_inputs"])
    assert "server/tests/test_pv_search_serving.py" in tests
    assert not reads_web
    assert api
    reaches = classifier["reaches_search"]
    assert not reaches("server/shengji/api/server.py", tests, False, False)
    assert reaches("server/shengji/api/server.py", tests, False, True)
    assert reaches("web/src/App.tsx", tests, True, False)


def test_any_error_runs_everything(classifier, monkeypatch):
    def broken():
        raise ImportError("broken")
    monkeypatch.setitem(classifier, "shared", broken)
    with pytest.raises(ImportError):
        in_root(classifier["classify_paths"], ["web/src/App.tsx"])
    everything = classifier["EVERYTHING"]
    assert everything["server_full"] and everything["search"] and not everything["server_web_only"]
    lines = classifier["output_lines"]({**everything, "server_web_pure": ["test_a", "test_b"]})
    assert "server_full=true" in lines and "server_web_pure=tests/test_a.py tests/test_b.py" in lines

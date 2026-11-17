"""The workflow's path classifier: which changes run which heavy jobs.

The ``changes`` job runs ``server/scripts/ci/select_tests.py``, which maps a
pull request's changed paths through the import graph to the test modules
they reach, and each job to whether it runs any of them.  These tests call
the selector on this checkout, so a change to the rule, to a job's selection
or to the files the suites read is checked here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "pr-checks.yml"
sys.path.insert(0, str(ROOT / "server" / "scripts" / "ci"))
import select_tests  # noqa: E402


# Built at run time so no constant in this module names them.
UNNAMED_DOC = "docs/" + "zz" + "_unnamed.md"
UNNAMED_INCIDENT = "incidents/" + "zz" + "_unnamed.md"


@pytest.fixture(scope="module")
def graph():
    return select_tests.Graph(ROOT)


@pytest.fixture(scope="module")
def universes():
    return select_tests.job_universes(ROOT)


@pytest.fixture(scope="module")
def classify(graph, universes, monkeypatch_module):
    monkeypatch_module.setattr(select_tests, "job_universes", lambda root=ROOT: universes)
    real_select = select_tests.select
    monkeypatch_module.setattr(select_tests, "select",
                               lambda paths, root=ROOT, graph_=None, membership=None: real_select(paths, root, graph, membership))
    return lambda *paths: select_tests.outputs(list(paths), ROOT)[0]


@pytest.fixture(scope="module")
def monkeypatch_module():
    patch = pytest.MonkeyPatch()
    yield patch
    patch.undo()


def test_the_changes_job_runs_the_selector():
    text = WORKFLOW.read_text()
    assert "python3 server/scripts/ci/select_tests.py --base" in text
    assert "python3 server/scripts/ci/select_tests.py --all" in text


@pytest.mark.parametrize("path, runs", [
    ("docs/atlas_v2/registry.json", False),
    ("PROTOCOL.md", False),
    ("server/shengji/train/cwv_train.py", True),
    ("server/scripts/ci_cwv_modes.sh", True),
    ("server/tests/conftest.py", True),
    ("server/tests/test_cwv_pack.py", True),
    ("server/tests/test_screen_deadline_child.py", True),
    # helpers selected modules import as `from tests.test_x import ...`
    ("server/tests/test_world_shortlist.py", True),
    ("server/tests/test_screen_deadline.py", True),
    ("fly.toml", True),
    (".github/workflows/pr-checks.yml", True),
    ("server/uv.lock", True),
    ("server/shengji/engine/_fast.pyx", True),
])
def test_which_paths_run_the_training_suites(classify, path, runs):
    jobs = classify(path)["jobs"]
    assert (jobs["train-cwv"] or jobs["train-policy"] or jobs["train-deadline"]) is runs


def test_a_web_change_reaches_no_search_or_deadline_suite(classify):
    jobs = classify("web/src/App.tsx")["jobs"]
    assert not jobs["train-deadline"] and not jobs["search-regression"] and not jobs["luna-profiles"]


def test_a_web_fixture_a_training_suite_names_still_runs_it(classify):
    out = classify("web/src/components/xray-shortlist.fixture.json")
    assert out["jobs"]["train-cwv"]
    assert "server/tests/test_cwv_debug_xray.py" in out["selected"]


WEB_READERS = {"test_client_server_constants", "test_offline_server_fixture_gen", "test_server_ws",
               "test_support", "test_web_cache_headers"}


def test_a_web_only_change_runs_only_the_web_reading_server_modules(classify):
    out = classify("web/src/index.css", "web/src/App.tsx", "docs/design/FLOWS.md")
    assert out["code"] and out["web"]
    selected = set(out["selected"])
    assert {f"server/tests/{name}.py" for name in WEB_READERS} <= selected
    assert "server/tests/test_engine.py" not in selected
    assert not out["jobs"]["search-regression"] and not out["jobs"]["luna-profiles"]
    assert out["jobs"]["server"]


def test_the_web_selection_includes_the_local_gate_web_readers(classify):
    sys.path.insert(0, str(ROOT / "server" / "scripts"))
    import affected_tests
    out = classify("web/src/queue/store.ts")
    readers = {f"server/tests/{name}.py" for name in affected_tests.web_reading_tests()}
    assert readers <= set(out["selected"])


@pytest.mark.parametrize("paths, server, search", [
    # API source: the served-bot search witnesses import shengji.api.server
    (("server/shengji/api/server.py", "web/src/App.tsx"), True, True),
    (("server/shengji/api/matchmaking.py",), True, True),
    # a search module, the engine, the workflow, configuration
    (("server/tests/test_pv_search_serving.py",), True, True),
    (("server/shengji/engine/legal.py",), True, True),
    ((".github/workflows/pr-checks.yml",), True, True),
    (("fly.toml",), True, True),
    (("server/tests/conftest.py",), True, True),
    # documentation only
    ((UNNAMED_DOC, UNNAMED_INCIDENT), False, False),
])
def test_server_and_search_classification(classify, paths, server, search):
    jobs = classify(*paths)["jobs"]
    assert (jobs["server"], jobs["search-regression"]) == (server, search)


def test_a_test_module_change_selects_itself_and_its_users(classify):
    selected = set(classify("server/tests/test_table_frame.py")["selected"])
    assert "server/tests/test_table_frame.py" in selected
    assert "server/tests/test_engine.py" not in selected


def test_an_api_change_selects_its_importers_and_not_the_whole_suite(classify, graph):
    out = classify("server/shengji/api/server.py")
    selected = set(out["selected"])
    assert "server/tests/test_server_ws.py" in selected
    assert "server/tests/test_pv_search_serving.py" in selected
    assert "server/tests/test_engine.py" not in selected
    assert len(selected) < len([p for p in graph.files if select_tests.is_test_module(p)])


@pytest.mark.parametrize("paths, web", [
    (("web/src/App.tsx",), True),
    (("web/e2e/known.json",), True),
    (("web/package-lock.json", "server/shengji/api/server.py"), True),
    ((".github/workflows/pr-checks.yml",), True),
    (("web/README.md",), False),
    (("server/shengji/api/server.py",), False),
    (("docs/notes.md",), False),
])
def test_which_paths_run_the_interaction_suites(classify, paths, web):
    assert classify(*paths)["web"] is web


def test_documentation_only_runs_nothing(classify):
    out = classify(UNNAMED_DOC, UNNAMED_INCIDENT)
    assert not out["code"] and out["selected"] == [] and not any(out["jobs"].values())
    assert "selected=none" in select_tests.output_lines(out)


def test_any_error_runs_everything(monkeypatch):
    def broken(*args, **kwargs):
        raise ImportError("broken")
    monkeypatch.setattr(select_tests, "select", broken)
    monkeypatch.setattr(select_tests, "job_universes", lambda root=ROOT: {"server": {"server/tests/test_x.py"}})
    out, reasons = select_tests.outputs(["server/shengji/api/server.py"], ROOT)
    assert out["selected"] is None and out["jobs"] == {"server": True}
    assert "selection failed" in reasons[0]
    lines = select_tests.output_lines(out)
    assert "selected=all" in lines and 'jobs={"server": true}' in lines


def test_a_push_runs_everything(universes, monkeypatch):
    monkeypatch.setattr(select_tests, "job_universes", lambda root=ROOT: universes)
    out, _ = select_tests.outputs(None, ROOT)
    assert out["selected"] is None and out["code"] and out["web"]
    assert all(out["jobs"].values()) and {"server", "train-cwv", "search-regression"} <= set(out["jobs"])

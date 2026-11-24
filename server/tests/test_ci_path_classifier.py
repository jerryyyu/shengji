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

# The `classify` fixture patches `select_tests.select` onto the live graph for the module.
SELECT = select_tests.select


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


def _importers(graph, path):
    """The test modules whose own imports (not transitive) reach ``path``."""
    return {p for p, targets in graph.deps.items() if path in targets and select_tests.is_test_module(p)}


def test_a_test_module_change_selects_itself_and_its_users(classify, graph):
    path = "server/tests/test_table_frame.py"
    selected = set(classify(path)["selected"])
    assert {path} | _importers(graph, path) <= selected


def test_an_api_change_selects_its_importers_and_not_the_whole_suite(classify, graph):
    path = "server/shengji/api/server.py"
    selected = set(classify(path)["selected"])
    importers = _importers(graph, path)
    assert {"server/tests/test_server_ws.py", "server/tests/test_pv_search_serving.py"} <= importers
    assert importers <= selected
    assert len(selected) < len([p for p in graph.files if select_tests.is_test_module(p)])


def _cone(graph, start):
    """``start`` and every file it uses, transitively."""
    seen, todo = {start}, [start]
    while todo:
        for target in graph.deps.get(todo.pop(), ()):
            if target not in seen:
                seen.add(target)
                todo.append(target)
    return seen


def test_nothing_the_shared_conftest_imports_lists_every_source_file(graph):
    # A file whose directory read the selector cannot bound is a reader of every
    # source file; inside conftest's import cone it makes every change select every
    # server test module.  The selector bounds a read unless the file names a
    # tracked directory in a string constant ("web", "server", ...) or `__file__`.
    probe = "server/shengji/" + "zz" + "_unnamed.py"
    readers = graph.readers_of_directories(probe) & _cone(graph, "server/tests/conftest.py")
    assert not readers, (
        f"{sorted(readers)} are imported by server/tests/conftest.py and read a directory the "
        "selector treats as the repository, so every change selects the whole server suite; "
        "keep tracked directory names out of their string constants or bound the read")


def _fixture_graph(root, sources):
    for path, text in sources.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    return select_tests.Graph(root, files=sorted(sources))


FIXTURE_REPO = {
    "web/src/App.tsx": "",
    "server/shengji/__init__.py": "",
    "server/shengji/engine/__init__.py": "",
    "server/shengji/engine/rules.py": "RANKS = 13\n",
    "server/shengji/api/__init__.py": "",
    "server/shengji/api/limits.py": "LIMIT = 1\n",
    "server/shengji/api/server.py": "from shengji.engine.rules import RANKS\n",
    "server/tests/conftest.py": "import shengji.api.limits\n",
    "server/tests/test_engine.py": "from shengji.engine.rules import RANKS\n",
    "server/tests/test_server_ws.py": "import shengji.api.server\n",
    "server/tests/test_table_frame.py": "FRAME = 1\n",
    "server/tests/test_frame_users.py": "from tests.test_table_frame import FRAME\n",
}


def test_the_selection_follows_imports_on_a_fixed_tree(tmp_path):
    graph = _fixture_graph(tmp_path, FIXTURE_REPO)
    def selected(*paths):
        chosen, _ = SELECT(list(paths), tmp_path, graph)
        return chosen
    assert selected("server/shengji/api/server.py") == {"server/tests/test_server_ws.py"}
    assert selected("server/tests/test_table_frame.py") == {
        "server/tests/test_table_frame.py", "server/tests/test_frame_users.py"}
    assert selected("server/shengji/engine/rules.py") == {
        "server/tests/test_engine.py", "server/tests/test_server_ws.py"}
    # conftest's imports reach every server test module
    assert selected("server/shengji/api/limits.py") == {
        p for p in FIXTURE_REPO if select_tests.is_test_module(p)}


def test_an_unbounded_read_in_the_conftest_cone_selects_every_test_on_a_fixed_tree(tmp_path):
    sources = dict(FIXTURE_REPO)
    sources["server/shengji/api/limits.py"] = (
        "import os\nPLATFORMS = {\"web\"}\n\ndef prune():\n    directory = min(PLATFORMS)\n    return os.listdir(directory)\n")
    graph = _fixture_graph(tmp_path, sources)
    chosen, _ = SELECT(["server/shengji/api/server.py"], tmp_path, graph)
    assert "server/tests/test_engine.py" in chosen
    probe = "server/shengji/" + "zz" + "_unnamed.py"
    assert graph.readers_of_directories(probe) & _cone(graph, "server/tests/conftest.py") == {
        "server/shengji/api/limits.py"}


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

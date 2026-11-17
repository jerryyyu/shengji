"""The CI test selector, the shard planner and the session controls.

``scripts/ci/select_tests.py`` must be conservative: a module that imports a
changed file (directly or through others) is always selected, and paths it
cannot place select everything.  ``shard_plan.py`` must put every module in
exactly one piece, and ``pytest_session.py`` must run exactly that piece.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / "server" / "scripts" / "ci"
sys.path.insert(0, str(CI))
import select_tests  # noqa: E402
import shard_plan  # noqa: E402
import update_durations  # noqa: E402


def make_tree(tmp_path: Path, files: dict[str, str]) -> select_tests.Graph:
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return select_tests.Graph(tmp_path, sorted(files))


def chosen(graph, *paths, membership=None):
    selected, _ = select_tests.select(list(paths), graph.root, graph, membership=membership)
    return None if selected is None else sorted(selected)


# the graph resolver ---------------------------------------------------------

def test_relative_imports_and_package_inits_resolve(tmp_path):
    graph = make_tree(tmp_path, {
        "server/shengji/__init__.py": "",
        "server/shengji/a/__init__.py": "from . import b\n",
        "server/shengji/a/b.py": "from ..c import d\n",
        "server/shengji/c/__init__.py": "",
        "server/shengji/c/d.py": "X = 1\n",
        "server/shengji/e.py": "",
        "server/tests/conftest.py": "",
        "server/tests/test_b.py": "from shengji.a.b import y\n",
        "server/tests/test_e.py": "import shengji.e\n",
    })
    assert "server/shengji/c/d.py" in graph.deps["server/shengji/a/b.py"]
    assert "server/shengji/c/__init__.py" in graph.deps["server/shengji/a/b.py"]
    assert "server/shengji/a/__init__.py" in graph.deps["server/tests/test_b.py"]
    assert chosen(graph, "server/shengji/c/d.py") == ["server/tests/test_b.py"]
    # a package __init__ runs for every import below it
    assert chosen(graph, "server/shengji/__init__.py") == ["server/tests/test_b.py", "server/tests/test_e.py"]
    assert chosen(graph, "server/shengji/e.py") == ["server/tests/test_e.py"]


def test_scripts_helpers_and_string_references_resolve(tmp_path):
    graph = make_tree(tmp_path, {
        "server/scripts/tool.py": "import json\n",
        "server/scripts/run.sh": "python3 scripts/worker.py \"$@\"\n",
        "server/scripts/worker.py": "",
        "server/shengji/__init__.py": "",
        "server/shengji/m.py": "",
        "server/tests/conftest.py": "",
        "server/tests/helper.py": "",
        "server/tests/test_tool.py": "import tool\nimport helper\n",
        "server/tests/test_shell.py": "CMD = ['bash', 'scripts/run.sh']\n",
        "server/tests/test_dotted.py": "def t(monkeypatch):\n    monkeypatch.setattr('shengji.m.f', 1)\n",
        "server/tests/test_uses_helper.py": "from test_tool import x\n",
    })
    assert chosen(graph, "server/scripts/tool.py") == ["server/tests/test_tool.py", "server/tests/test_uses_helper.py"]
    assert chosen(graph, "server/scripts/worker.py") == ["server/tests/test_shell.py"]
    assert chosen(graph, "server/shengji/m.py") == ["server/tests/test_dotted.py"]
    assert chosen(graph, "server/tests/helper.py") == ["server/tests/test_tool.py", "server/tests/test_uses_helper.py"]


def test_docstrings_are_not_references(tmp_path):
    graph = make_tree(tmp_path, {
        "server/shengji/__init__.py": "",
        "server/shengji/m.py": "",
        "server/tests/conftest.py": "",
        "server/tests/test_doc.py": '"""See shengji/m.py and shengji.m."""\n',
    })
    assert chosen(graph, "server/shengji/m.py") == []


def test_computed_imports_map_through_the_files_constants(tmp_path):
    graph = make_tree(tmp_path, {
        "server/scripts/alpha.py": "",
        "server/scripts/beta.py": "",
        "server/tests/conftest.py": "",
        "server/tests/test_loader.py": (
            "import importlib.util\n"
            "def load(name):\n"
            "    return importlib.util.spec_from_file_location(name, f'scripts/{name}.py')\n"
            "A = load('alpha')\n"),
    })
    assert graph.dynamic["server/tests/test_loader.py"]
    assert chosen(graph, "server/scripts/alpha.py") == ["server/tests/test_loader.py"]
    assert chosen(graph, "server/scripts/beta.py") == []


@pytest.mark.parametrize("path", [
    "server/tests/conftest.py", "server/pyproject.toml", "server/uv.lock", "server/setup.py",
    "server/shengji/engine/_fast.pyx", ".github/workflows/pr-checks.yml", "server/scripts/ci/shard_plan.py",
    "server/scripts/ci/test_durations.json", "server/scripts/ci_cwv_modes.sh", "server/scripts/test_checkout.py",
])
def test_environment_and_ci_paths_run_everything(tmp_path, path):
    graph = make_tree(tmp_path, {"server/tests/conftest.py": "", "server/tests/test_a.py": ""})
    assert chosen(graph, path) is None


def test_every_test_module_depends_on_conftest(tmp_path):
    graph = make_tree(tmp_path, {
        "server/shengji/__init__.py": "",
        "server/shengji/fast.py": "",
        "server/tests/conftest.py": "import shengji.fast\n",
        "server/tests/test_a.py": "",
        "server/tests/test_b.py": "",
    })
    assert chosen(graph, "server/shengji/fast.py") == ["server/tests/test_a.py", "server/tests/test_b.py"]


def test_fixtures_select_their_readers_or_everything(tmp_path):
    graph = make_tree(tmp_path, {
        "server/tests/conftest.py": "",
        "server/tests/fixtures/golden.json": "{}",
        "server/tests/fixtures/orphan.bin": "",
        "server/shengji/__init__.py": "",
        "server/shengji/data.py": "PATH = 'tests/fixtures/golden.json'\n",
        "server/tests/test_data.py": "import shengji.data\n",
        "server/tests/test_other.py": "",
        "docs/notes.md": "",
    })
    assert chosen(graph, "server/tests/fixtures/golden.json") == ["server/tests/test_data.py"]
    assert chosen(graph, "server/tests/fixtures/orphan.bin") is None
    assert chosen(graph, "docs/notes.md") == []


def test_directory_reads_select_their_readers(tmp_path):
    graph = make_tree(tmp_path, {
        "server/tests/conftest.py": "",
        "server/tests/data/a.json": "",
        "server/tests/test_scan.py": (
            "from pathlib import Path\n"
            "HERE = Path(__file__).parent\n"
            "FILES = sorted((HERE / 'data').glob('*.json'))\n"),
        "server/tests/test_tmp.py": "def t(tmp_path):\n    return list(tmp_path.glob('*.json'))\n",
        "server/tests/test_named.py": "X = 'data/a.json'\n",
    })
    # a.json is named by test_named; the glob of test_scan can return it too
    assert chosen(graph, "server/tests/data/a.json") == ["server/tests/test_named.py", "server/tests/test_scan.py"]
    # an added file no module names is still listed by the anchored glob
    assert chosen(graph, "server/tests/data/new.json", membership={"server/tests/data/new.json"}) == [
        "server/tests/test_scan.py"]


def test_a_deleted_script_selects_its_subprocess_consumer(tmp_path):
    graph = make_tree(tmp_path, {
        "server/tests/conftest.py": "",
        "server/tests/test_deleted.py": (
            "import subprocess, sys\n"
            "def test_command():\n"
            "    assert subprocess.run([sys.executable, 'server/scripts/removed.py']).returncode == 0\n"),
        "server/tests/test_other.py": "",
    })
    assert chosen(graph, "server/scripts/removed.py") == ["server/tests/test_deleted.py"]


def test_a_deleted_module_selects_its_importers(tmp_path):
    graph = make_tree(tmp_path, {
        "server/shengji/__init__.py": "",
        "server/shengji/user.py": "from shengji import gone\n",
        "server/tests/conftest.py": "",
        "server/tests/test_user.py": "import shengji.user\n",
        "server/tests/test_script.py": "import helper_gone\n",
        "server/tests/test_other.py": "",
    })
    assert chosen(graph, "server/shengji/gone.py") == ["server/tests/test_user.py"]
    assert chosen(graph, "server/scripts/helper_gone.py") == ["server/tests/test_script.py"]


def test_a_deleted_file_nothing_names_runs_everything(tmp_path):
    graph = make_tree(tmp_path, {"server/tests/conftest.py": "", "server/tests/test_a.py": ""})
    assert chosen(graph, "server/scripts/orphan.py") is None
    assert chosen(graph, "server/tests/fixtures/orphan.json") is None


LOADER_TREE = {
    "server/pkg/__init__.py": "",
    "server/pkg/loader.py": (
        "from pathlib import Path\n"
        "ROOT = Path(__file__).parent\n"
        "def load():\n"
        "    return [p.read_text() for p in ROOT.glob('plugin*.py')]\n"),
    "server/pkg/service.py": "from pkg.loader import load\n",
    "server/pkg/plugin_a.py": "",
    "server/tests/conftest.py": "",
    "server/tests/test_service.py": "from pkg.service import load\n",
    "server/tests/test_other.py": "",
}


@pytest.mark.parametrize("change, added", [
    ("server/pkg/plugin_b.py", True),    # a new plugin the loader will list
    ("server/pkg/plugin_a.py", False),   # a plugin whose content the loader reads
])
def test_a_plugin_read_through_a_loader_selects_the_consumer_two_hops_away(tmp_path, change, added):
    graph = make_tree(tmp_path, dict(LOADER_TREE))
    membership = {change} if added else set()
    assert chosen(graph, change, membership=membership) == ["server/tests/test_service.py"]


@pytest.mark.parametrize("target", [
    "(ROOT / 'plugins').parent",
    "ROOT / 'plugins' / '..'",
    "(ROOT / 'plugins' / '..').resolve()",
])
def test_a_read_whose_path_leaves_a_named_directory_still_selects(tmp_path, target):
    # a directory named in a read's expression says nothing about where the read
    # lands: .parent, '..' and resolve() can leave it, so every read counts as
    # unrestricted
    graph = make_tree(tmp_path, {
        "server/tests/conftest.py": "",
        "server/pkg/__init__.py": "",
        "server/pkg/plugin_a.py": "",
        "server/pkg/loader.py": (
            "from pathlib import Path\n"
            "ROOT = Path(__file__).parent\n"
            f"FOUND = sorted(({target}).glob('plugin*.py'))\n"),
        "server/pkg/service.py": "from pkg import loader\n",
        "server/tests/test_service.py": "from pkg import service\n",
    })
    assert chosen(graph, "server/pkg/plugin_a.py") == ["server/tests/test_service.py"]


def test_selected_consumers_actually_fail_without_the_deleted_producer(tmp_path):
    graph = make_tree(tmp_path, {
        "server/tests/conftest.py": "",
        "server/tests/test_deleted.py": (
            "import subprocess, sys\n"
            "def test_command():\n"
            "    assert subprocess.run([sys.executable, 'server/scripts/removed.py']).returncode == 0\n"),
    })
    selected = chosen(graph, "server/scripts/removed.py")
    run = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *selected],
                         cwd=tmp_path, capture_output=True, text=True,
                         env={k: v for k, v in os.environ.items() if not k.startswith("SHENGJI_CI_")})
    # the consumer is selected and its failure is what the PR run reports
    assert selected == ["server/tests/test_deleted.py"] and run.returncode == 1


# real diffs -----------------------------------------------------------------

# Changed Python files of recent merged pull requests (squash merges on main).
RECENT_DIFFS = {
    "1569": [
        "server/shengji/api/server.py",
        "server/tests/test_server_ws.py",
    ],
    "1566": [
        "server/scripts/suspend_account.py",
        "server/shengji/api/accounts.py",
        "server/shengji/api/apple_auth.py",
        "server/tests/test_accounts.py",
        "server/tests/test_apple_signin.py",
    ],
    "1565": [
        "server/shengji/api/ratings.py",
        "server/tests/test_matchmaking_golden.py",
    ],
    "1564": [
        "server/tests/test_ci_cwv_modes.py",
    ],
    "1561": [
        "server/shengji/api/server.py",
        "server/tests/test_server_ws.py",
    ],
    "1563": [
        "server/shengji/api/server.py",
        "server/tests/test_server_ws.py",
    ],
    "1553": [
        "server/scripts/gen_offline_server_fixtures.py",
        "server/shengji/api/limits.py",
        "server/shengji/api/matchmaking.py",
        "server/shengji/api/server.py",
        "server/tests/conftest.py",
        "server/tests/test_matchmaking.py",
        "server/tests/test_server_ws.py",
    ],
    "1552": [
        "server/scripts/gen_offline_server_fixtures.py",
        "server/shengji/api/debug.py",
        "server/shengji/api/server.py",
        "server/tests/test_cwv_debug_xray.py",
        "server/tests/test_matchmaking.py",
        "server/tests/test_server_ws.py",
    ],
    "1550": [
        "server/shengji/api/server.py",
        "server/tests/test_matchmaking.py",
        "server/tests/test_server_ws.py",
    ],
    "1551": [
        "server/tests/test_ci_path_classifier.py",
    ],
    "1554": [
        "server/scripts/ops_dashboard/backfill_botspeed.py",
        "server/scripts/ops_dashboard/collector.py",
        "server/scripts/ops_dashboard/query.py",
        "server/scripts/ops_dashboard/serve.py",
        "server/tests/test_ops_dashboard.py",
    ],
    "1549": [
        "server/shengji/api/reports.py",
        "server/shengji/api/telemetry.py",
        "server/tests/test_client_server_constants.py",
        "server/tests/test_player_reports.py",
        "server/tests/test_telemetry.py",
    ],
    "1548": [
        "server/shengji/api/server.py",
        "server/tests/test_server_ws.py",
    ],
    "1546": [
        "server/shengji/api/server.py",
        "server/tests/test_server_ws.py",
    ],
    "1545": [
        "server/shengji/api/accounts.py",
        "server/shengji/api/chat_filter.py",
        "server/shengji/api/matchmaking.py",
        "server/shengji/api/server.py",
        "server/shengji/api/support.py",
        "server/tests/test_accounts.py",
        "server/tests/test_chat_filter.py",
        "server/tests/test_matchmaking.py",
        "server/tests/test_server_ws.py",
        "server/tests/test_support.py",
    ],
    "1543": [
        "server/shengji/api/ratings.py",
        "server/tests/test_ratings.py",
    ],
    "1539": [
        "server/tests/test_table_frame.py",
    ],
    "1538": [
        "server/shengji/api/saved_games.py",
    ],
    "1535": [
        "server/scripts/check_ci_test_selection.py",
        "server/tests/test_check_ci_test_selection.py",
    ],
    "1534": [
        "server/tests/test_client_server_constants.py",
    ],
    "1531": [
        "server/shengji/api/human_eval.py",
        "server/shengji/api/ratings.py",
        "server/shengji/api/room_experiments.py",
        "server/shengji/api/saved_games.py",
        "server/shengji/api/server.py",
        "server/shengji/api/telemetry.py",
        "server/shengji/releases.py",
        "server/shengji/rl/human_shards.py",
        "server/tests/test_bot_scheduler.py",
        "server/tests/test_ci_path_classifier.py",
        "server/tests/test_cwv_room_experiments.py",
        "server/tests/test_health_activity.py",
        "server/tests/test_human_eval_contract.py",
        "server/tests/test_matchmaking.py",
    ],
    "1529": [
        "server/shengji/train/unified_seq.py",
        "server/tests/test_unified_seq.py",
    ],
    "1526": [
        "server/scripts/s134_v1_read.py",
        "server/shengji/ai/unified_numpy.py",
        "server/shengji/train/suit_perm.py",
        "server/shengji/train/unified_seq.py",
        "server/tests/test_s134_v1_read.py",
        "server/tests/test_unified_seq.py",
    ],
    "1521": [
        "server/shengji/api/matchmaking.py",
        "server/shengji/api/server.py",
        "server/shengji/api/tables.py",
        "server/tests/test_matchmaking.py",
        "server/tests/test_server_ws.py",
    ],
}


def direct_importers(path: str, tests: list[str]) -> set[str]:
    """Test modules whose source imports ``path`` by its module name or names
    its file: an oracle independent of the graph code."""
    p = Path(path)
    if path.startswith("server/tests/") and p.name.startswith("test_"):
        return {path}
    if path.startswith("server/shengji/"):
        dotted = ".".join(p.with_suffix("").parts[1:]).removesuffix(".__init__")
        head, _, leaf = dotted.rpartition(".")
        pattern = re.compile(rf"(?:import|from)\s+{re.escape(dotted)}\b|from\s+{re.escape(head)}\s+import\s+[^\n]*\b{leaf}\b")
    else:
        pattern = re.compile(rf"(?:import|from)\s+{re.escape(p.stem)}\b|{re.escape(p.name)}")
    return {t for t in tests if pattern.search((ROOT / t).read_text(errors="replace"))}


@pytest.fixture(scope="module")
def real_graph():
    return select_tests.Graph(ROOT)


@pytest.mark.parametrize("pr", sorted(RECENT_DIFFS))
def test_selection_covers_the_direct_importers_of_real_diffs(real_graph, pr):
    paths = [p for p in RECENT_DIFFS[pr]]
    tests = [p for p in real_graph.files if select_tests.is_test_module(p)]
    selected, _ = select_tests.select(paths, ROOT, real_graph)
    if selected is None:
        return
    for path in paths:
        if not (ROOT / path).exists():
            continue
        missing = direct_importers(path, tests) - selected
        assert not missing, f"#{pr}: {path} is imported by unselected {sorted(missing)}"


def test_an_api_only_change_selects_a_strict_subset(real_graph):
    selected, _ = select_tests.select(["server/shengji/api/server.py"], ROOT, real_graph)
    tests = {p for p in real_graph.files if select_tests.is_test_module(p)}
    assert selected is not None and selected < tests
    assert "server/tests/test_server_ws.py" in selected


# the planner ----------------------------------------------------------------

def test_the_plan_puts_every_module_in_exactly_one_piece():
    modules = [f"server/tests/test_{i}.py" for i in range(23)]
    costs = {m: float((i * 7) % 11 + 1) for i, m in enumerate(modules)}
    for pieces in (1, 2, 3, 4, 7, 30):
        plan = shard_plan.plan(modules + modules[:3], pieces, costs)
        flat = [m for piece in plan for m in piece]
        assert len(plan) == pieces and sorted(flat) == sorted(modules)
        assert plan == shard_plan.plan(list(reversed(modules)), pieces, costs)


def test_the_plan_balances_by_time():
    costs = {"a": 10.0, "b": 9.0, "c": 4.0, "d": 3.0, "e": 3.0, "f": 1.0, "g": 6.0, "h": 2.0}
    for pieces in (2, 3):
        loads = [sum(costs[m] for m in piece) for piece in shard_plan.plan(costs, pieces, costs)]
        # longest-first greedy: no piece exceeds another by more than one module's time
        assert max(loads) - min(loads) <= max(costs.values())
        assert sum(loads) == sum(costs.values())


def test_unknown_modules_cost_the_median():
    table = {"pure": {"a": 1.0, "b": 3.0, "c": 100.0}}
    costs = shard_plan.module_costs(["a", "z"], "pure", table)
    assert costs == {"a": 1.0, "z": 3.0}
    assert shard_plan.module_costs(["z"], "compiled", table) == {"z": shard_plan.FALLBACK_SECONDS}


@pytest.mark.parametrize("value", ["0/2", "3/2", "2", "a/b"])
def test_bad_shards_are_refused(value):
    with pytest.raises(ValueError):
        shard_plan.parse_shard(value)


def test_the_committed_durations_load_and_name_existing_modules():
    table = shard_plan.load_durations()
    for engine, modules in table.items():
        assert engine in ("pure", "compiled")
        for module in modules:
            assert (ROOT / module).is_file(), module


def test_update_durations_merges_by_maximum(tmp_path):
    (tmp_path / "r").mkdir()
    for n, seconds in enumerate((2.0, 5.0)):
        (tmp_path / "r" / f"{n}.json").write_text(json.dumps(
            {"engine": "pure", "modules": {"server/tests/test_ci_selection_planner.py": seconds}}))
    found = update_durations.read_records([tmp_path / "r"])
    merged = update_durations.merge({"pure": {"server/tests/gone.py": 1.0}}, found)
    assert merged == {"pure": {"server/tests/test_ci_selection_planner.py": 5.0}}


# the session controls -------------------------------------------------------

@pytest.fixture
def suite(tmp_path):
    root = tmp_path / "suite"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "conftest.py").write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(CI)!r})\n"
        "import pytest_session\n"
        "def pytest_sessionstart(session):\n"
        "    pytest_session.install(session)\n")
    for k in range(5):
        (root / "tests" / f"test_m{k}.py").write_text(
            "import os\n"
            f"def test_one():\n    assert os.environ.get('SHENGJI_CI_SHARD') is None\n")
    return root


def run_suite(root, env, *args):
    full = {k: v for k, v in os.environ.items() if not k.startswith("SHENGJI_CI_")}
    full.update(env)
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
                          cwd=root, env=full, capture_output=True, text=True)


def test_pieces_partition_the_command_line(suite):
    modules = [f"tests/test_m{k}.py" for k in range(5)]
    passed = 0
    for i in (1, 2, 3):
        result = run_suite(suite, {"SHENGJI_CI_SHARD": f"{i}/3"}, *modules)
        assert result.returncode == 0, result.stdout + result.stderr
        passed += int(re.search(r"(\d+) passed", result.stdout).group(1))
        assert f"piece {i}/3" in result.stdout
    assert passed == 5


def test_an_empty_piece_or_selection_exits_zero(suite):
    result = run_suite(suite, {"SHENGJI_CI_SHARD": "2/2"}, "tests/test_m0.py")
    assert result.returncode == 0 and "0 selected" in result.stdout + result.stderr
    result = run_suite(suite, {"SHENGJI_CI_SELECTED": "none"}, "tests/test_m0.py", "tests/test_m1.py")
    assert result.returncode == 0 and "0 of 2 selected" in result.stdout


def test_the_selection_filters_and_durations_are_recorded(suite, tmp_path):
    out = tmp_path / "durations"
    keep = str((suite / "tests" / "test_m3.py").resolve())
    result = run_suite(suite, {"SHENGJI_CI_SELECTED": keep, "SHENGJI_CI_DURATIONS_OUT": str(out)},
                       *(f"tests/test_m{k}.py" for k in range(5)))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
    record = json.loads(next(out.glob("*.json")).read_text())
    assert record["engine"] == "pure" and keep in record["modules"]


def test_parallel_runs_every_session_and_reports_failure():
    script = str(CI / "parallel.py")
    probe = "import os, sys; print(os.environ['SHENGJI_CI_SHARD']); sys.exit(os.environ['SHENGJI_CI_SHARD'] == '4/6')"
    ok = subprocess.run([sys.executable, script, "--sessions", "2", "--shard", "1", "--shards", "3", "--",
                         sys.executable, "-c", probe], capture_output=True, text=True)
    assert ok.returncode == 0 and "[1.1] 1/6" in ok.stdout and "[1.2] 2/6" in ok.stdout
    bad = subprocess.run([sys.executable, script, "--sessions", "2", "--shard", "2", "--shards", "3", "--",
                          sys.executable, "-c", probe], capture_output=True, text=True)
    assert bad.returncode == 1 and "[2.1] 3/6" in bad.stdout and "[2.2] 4/6" in bad.stdout

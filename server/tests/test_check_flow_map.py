"""Tests for scripts/check_flow_map.py."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_flow_map.py"
_spec = importlib.util.spec_from_file_location("check_flow_map", SCRIPT)
check = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = check
_spec.loader.exec_module(check)

FLOWS_TEST = """const SURFACES = [
  "components/LeaveSheet.tsx", // the one Leave sheet
  "queue/Sheet.tsx", // the sheet frame
];
const LEAVE_SITES = ["queue/TablePanel.tsx"];
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def _write(repo: Path, path: str, text: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    _write(tmp_path, "web/src/flows.test.ts", FLOWS_TEST)
    _write(tmp_path, "web/src/components/Lobby.tsx", "export {};\n")
    _write(tmp_path, "docs/design/FLOWS.md", "# flows\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "checkout", "-q", "-b", "topic")
    return tmp_path


def _commit(repo: Path, message: str = "topic") -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


@pytest.mark.parametrize("path", ["web/src/components/Popup.tsx", "web/src/queue/Bar.tsx", "web/src/home/Tab.tsx"])
def test_a_new_component_without_the_flow_map_is_refused(repo, path):
    _write(repo, path, "export {};\n")
    _commit(repo)
    assert check.run(repo, "main") == [f"new component {path}"]


@pytest.mark.parametrize(
    "path",
    ["web/src/components/Popup.test.tsx", "web/src/components/util.ts", "web/src/replay/View.tsx",
     "web/src/components/Lobby.css"],
)
def test_tests_helpers_and_other_roots_are_not_components(repo, path):
    _write(repo, path, "export {};\n")
    _commit(repo)
    assert check.run(repo, "main") == []


def test_editing_an_existing_component_does_not_trigger(repo):
    _write(repo, "web/src/components/Lobby.tsx", "export const x = 1;\n")
    _commit(repo)
    assert check.run(repo, "main") == []


@pytest.mark.parametrize("touch", ["docs/design/FLOWS.md", "docs/design/mocks/core.py"])
def test_touching_the_flow_map_answers_it(repo, touch):
    _write(repo, "web/src/components/Popup.tsx", "export {};\n")
    _write(repo, touch, "# changed\n")
    _commit(repo)
    assert check.run(repo, "main") == []


def test_an_allowlist_entry_added_is_refused(repo):
    _write(repo, "web/src/flows.test.ts",
           FLOWS_TEST.replace('  "queue/Sheet.tsx",', '  "components/Popup.tsx", // a popup\n  "queue/Sheet.tsx",'))
    _commit(repo)
    assert check.run(repo, "main") == ["web/src/flows.test.ts: SURFACES changed"]


def test_an_entry_removed_from_an_inventory_list_is_refused(repo):
    _write(repo, "web/src/flows.test.ts", FLOWS_TEST.replace('"queue/TablePanel.tsx"', ""))
    _commit(repo)
    assert check.run(repo, "main") == ["web/src/flows.test.ts: LEAVE_SITES changed"]


def test_rewording_an_entry_comment_is_not_a_change(repo):
    _write(repo, "web/src/flows.test.ts", FLOWS_TEST.replace("// the sheet frame", "// the queue's sheet frame"))
    _commit(repo)
    assert check.run(repo, "main") == []


def test_a_pr_body_waiver_passes(repo):
    _write(repo, "web/src/components/Popup.tsx", "export {};\n")
    _commit(repo)
    assert check.run(repo, "main", "Summary\n\nflow-ok: a rename, no new surface\n") == []
    assert check.run(repo, "main", "flow-ok:\n") != []          # a waiver names its reason


def test_a_commit_message_waiver_passes(repo):
    _write(repo, "web/src/components/Popup.tsx", "export {};\n")
    _commit(repo, "split Lobby\n\nflow-ok: moves code, same surfaces")
    assert check.run(repo, "main") == []


def test_main_reports_and_exits_1(repo, capsys, monkeypatch):
    _write(repo, "web/src/components/Popup.tsx", "export {};\n")
    _commit(repo)
    assert check.main(["--repo", str(repo), "--base", "main"]) == 1
    assert "new component web/src/components/Popup.tsx" in capsys.readouterr().out
    monkeypatch.setenv("PR_BODY", "flow-ok: only a test fixture")
    assert check.main(["--repo", str(repo), "--base", "main", "--body-env", "PR_BODY"]) == 0


def test_literal_entries_reads_the_real_list():
    source = (Path(__file__).resolve().parents[2] / "web" / "src" / "flows.test.ts").read_text()
    for name in check.LITERALS:
        entries = check.literal_entries(source, name)
        assert entries, name
        assert all(e.endswith((".ts", ".tsx")) for e in entries), name

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
SERVER = Path(__file__).parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SERVER))

PORTABILITY_PATH = SCRIPTS / "s5_final_champion_x86_portability.py"
PORTABILITY_SPEC = importlib.util.spec_from_file_location(
    "s5_final_champion_x86_portability", PORTABILITY_PATH)
assert PORTABILITY_SPEC and PORTABILITY_SPEC.loader
port = importlib.util.module_from_spec(PORTABILITY_SPEC)
PORTABILITY_SPEC.loader.exec_module(port)

S5_PATH = SCRIPTS / "s5_final_champion_replay.py"
S5_SPEC = importlib.util.spec_from_file_location(
    "s5_final_champion_replay_for_portability_test", S5_PATH)
assert S5_SPEC and S5_SPEC.loader
s5 = importlib.util.module_from_spec(S5_SPEC)
S5_SPEC.loader.exec_module(s5)


def test_portable_fixture_replays_live_champion_ballot_and_actions() -> None:
    frozen = json.loads(port.FIXTURE_PATH.read_bytes())
    assert port.sha256_file(port.FIXTURE_PATH) == port.FIXTURE_FILE_SHA256
    assert port.require_fixture(s5) == frozen
    assert frozen["fixture_sha256"] == port.FIXTURE_PAYLOAD_SHA256
    assert [row["follow_position"] for row in frozen["cases"]] == [1, 2]
    assert frozen["cases"][0]["reason"] == "report_lcb_override"
    assert frozen["cases"][1]["reason"] == "report_lcb_below_min_gain"
    assert all(row["work"]["complete"] is True for row in frozen["cases"])


def test_fixture_file_and_live_replay_both_fail_closed(
        tmp_path: Path, monkeypatch) -> None:
    frozen = json.loads(port.FIXTURE_PATH.read_bytes())
    changed = copy.deepcopy(frozen)
    changed["cases"][0]["played"] = ["DA"]
    changed_without_hash = dict(changed)
    changed_without_hash.pop("fixture_sha256")
    changed["fixture_sha256"] = port.sha256_bytes(
        port.canonical_json(changed_without_hash))
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(changed, sort_keys=True))
    monkeypatch.setattr(port, "FIXTURE_PATH", path)
    monkeypatch.setattr(port, "FIXTURE_FILE_SHA256", port.sha256_file(path))
    monkeypatch.setattr(
        port, "FIXTURE_PAYLOAD_SHA256", changed["fixture_sha256"])
    with pytest.raises(port.PortabilityRefused, match="ballot/action replay"):
        port.require_fixture(s5)

    monkeypatch.setattr(port, "FIXTURE_FILE_SHA256", "0" * 64)
    with pytest.raises(port.PortabilityRefused, match="file identity"):
        port.require_fixture(s5)


def test_historical_arm_parent_remains_distinct_from_x86_contract() -> None:
    parent = s5.LIVE_PARENT.expected_parent()
    assert parent["fast_binary_sha256"] == \
        port.HISTORICAL_FAST_BINARY_SHA256
    assert parent["policy_contract_sha256"] == \
        port.HISTORICAL_POLICY_CONTRACT_SHA256
    assert parent["fast_binary_sha256"] != port.X86_FAST_BINARY_SHA256
    assert parent["policy_contract_sha256"] != \
        port.X86_POLICY_CONTRACT_SHA256


def test_gameplay_module_provenance_is_bound_to_base(tmp_path: Path) -> None:
    assert port._module_provenance_problems(s5) == []
    problems = port._module_provenance_problems(
        SimpleNamespace(REPO=tmp_path))
    assert any("loaded outside base" in problem for problem in problems)


def test_x86_parent_checks_runtime_binary_and_preserves_historical_parent(
        monkeypatch) -> None:
    from shengji.engine import fast

    binary_sha = port.sha256_file(fast._fast.__file__)
    fixture = json.loads(port.FIXTURE_PATH.read_bytes())
    monkeypatch.setattr(port, "_sealed_parent_problems", lambda _parent: [])
    monkeypatch.setattr(port, "_x86_policy_problems", lambda _s5: [])
    monkeypatch.setattr(port, "require_fixture", lambda _s5: fixture)
    monkeypatch.setattr(port.platform, "system", lambda: "Linux")
    monkeypatch.setattr(port.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(port.platform, "python_version", lambda: "3.14.4")
    monkeypatch.setattr(port, "X86_FAST_BINARY_SHA256", binary_sha)
    monkeypatch.setenv("SHENGJI_FAST", "1")
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")

    binding = port.require_x86_parent(s5)
    assert binding["historical_parent"] == s5.LIVE_PARENT.expected_parent()
    assert binding["compatible_x86"]["fast_binary_sha256"] == binary_sha
    assert binding["authority"]["new_diagnostic_execution_authorized"] is False
    assert binding["authority"]["retry_authorized"] is False

    monkeypatch.setattr(port.platform, "machine", lambda: "arm64")
    with pytest.raises(port.PortabilityRefused, match="runtime identity"):
        port.require_x86_parent(s5)
    monkeypatch.setattr(port.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(port, "X86_FAST_BINARY_SHA256", "0" * 64)
    with pytest.raises(port.PortabilityRefused, match="compiled binary"):
        port.require_x86_parent(s5)


def test_policy_contract_normalises_only_binary_ballot_and_pins_heuristic(
        monkeypatch) -> None:
    monkeypatch.setattr(port, "_module_provenance_problems", lambda _s5: [])
    monkeypatch.setattr(port, "X86_BALLOT", port.HISTORICAL_BALLOT)
    monkeypatch.setattr(
        port, "X86_POLICY_CONTRACT_SHA256",
        port.HISTORICAL_POLICY_CONTRACT_SHA256)
    assert port._x86_policy_problems(s5) == []

    monkeypatch.setattr(port, "BASE_HEURISTIC_SHA256", "0" * 64)
    problems = port._x86_policy_problems(s5)
    assert "champion rollout heuristic drift/PR71 substitution" in problems


def _fake_base(tmp_path: Path) -> Path:
    base = tmp_path / "base"
    base.mkdir(parents=True)
    (base / ".git").write_text("gitdir: /nonexistent/test-only\n")
    for relative in (
            port.BASE_SCRIPT_RELATIVE,
            port.BASE_PARENT_RELATIVE,
            port.BASE_CENSUS_RELATIVE,
            port.BASE_HEURISTIC_RELATIVE):
        target = base / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(port.REPO / relative, target)
    return base


def test_base_worktree_requires_exact_git_clean_tree_and_sources(
        tmp_path: Path, monkeypatch) -> None:
    base = _fake_base(tmp_path)

    def clean_git(_repo, *args):
        return port.BASE_GIT if args == ("rev-parse", "HEAD") else ""

    monkeypatch.setattr(port, "_git", clean_git)
    assert port.validate_base_worktree(base) == base.resolve()

    (base / port.BASE_HEURISTIC_RELATIVE).write_text("PR71 substitution")
    with pytest.raises(port.PortabilityRefused, match="heuristic"):
        port.validate_base_worktree(base)

    shutil.copy2(
        port.REPO / port.BASE_HEURISTIC_RELATIVE,
        base / port.BASE_HEURISTIC_RELATIVE)
    monkeypatch.setattr(
        port, "_git",
        lambda _repo, *args: "1" * 40 if args == ("rev-parse", "HEAD") else "")
    with pytest.raises(port.PortabilityRefused, match="exact f8083cf"):
        port.validate_base_worktree(base)


def test_review_marker_is_exact_and_adds_no_second_diagnostic(
        tmp_path: Path) -> None:
    git = "a" * 40
    claim = port.review_claim(wrapper_git=git)
    assert claim["existing_one_diagnostic_may_execute_on_x86"] is True
    assert claim["new_diagnostic_execution_authorized"] is False
    assert claim["retry_authorized"] is False
    assert claim["strength_execution_authorized"] is False
    assert claim["production_deployment"] is False
    line = port.REVIEW_PREFIX + json.dumps(
        claim, sort_keys=True, separators=(",", ":")) + "\n"
    record = tmp_path / "review.md"
    record.write_text(line)
    assert port.require_review_marker(record, wrapper_git=git) == claim

    changed = copy.deepcopy(claim)
    changed["retry_authorized"] = True
    record.write_text(port.REVIEW_PREFIX + json.dumps(
        changed, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(port.PortabilityRefused, match="differs"):
        port.require_review_marker(record, wrapper_git=git)
    record.write_text(line + line)
    with pytest.raises(port.PortabilityRefused, match="exactly one"):
        port.require_review_marker(record, wrapper_git=git)


def test_admission_is_canonical_score_free_and_one_shot(
        tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(port, "ADMISSION_RELATIVE", Path("locks/slot.json"))
    marker = port.review_claim(wrapper_git="a" * 40)
    path = port._consume_admission(
        tmp_path, wrapper_git="a" * 40, marker=marker)
    payload = json.loads(path.read_bytes())
    assert set(payload) == {
        "schema", "base_git", "wrapper_git", "review_marker_sha256",
        "retry_authorized", "strength_execution_authorized",
        "production_deployment",
    }
    assert payload["retry_authorized"] is False
    assert payload["strength_execution_authorized"] is False
    with pytest.raises(port.PortabilityRefused, match="already consumed"):
        port._consume_admission(
            tmp_path, wrapper_git="a" * 40, marker=marker)


def test_source_and_fixture_hashes_are_literal() -> None:
    assert port.sha256_file(PORTABILITY_PATH) == port.review_claim(
        wrapper_git="a" * 40)["wrapper_sha256"]
    assert port.sha256_file(S5_PATH) == port.BASE_SCRIPT_SHA256
    assert port.sha256_file(SCRIPTS / "s5_point_protection_census.py") == \
        port.BASE_CENSUS_SHA256
    assert port.sha256_file(SERVER / "shengji/ai/heuristic.py") == \
        port.BASE_HEURISTIC_SHA256
    assert port.sha256_file(port.FIXTURE_PATH) == port.FIXTURE_FILE_SHA256

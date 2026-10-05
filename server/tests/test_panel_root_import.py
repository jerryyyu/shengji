"""Root import qualification on temporary, setup-only test fixtures."""
import json
from copy import deepcopy

import pytest

from scripts import prepare_llm_panel_roots as producer
from scripts import w32_llm_benchmark as runner
from shengji.engine.game import Game
from shengji.luna.canonical import canonical_json_bytes


@pytest.fixture
def roots(tmp_path):
    path = tmp_path / "roots"
    producer.prepare_roots(output=path, seeds=[7123, 7124])
    return path


def load(path, **kwargs):
    return runner._load_prepared_roots(path, seeds=(7123, 7124),
                                       game_factory=Game, **kwargs)


def replace(path, value):
    # Only this test owns these synthetic immutable fixtures.
    path.chmod(0o600)
    path.write_bytes(canonical_json_bytes(value))


def test_authenticated_restore_without_dealing(roots, monkeypatch):
    digest = runner._sha_bytes((roots / "result.json").read_bytes())
    def forbidden(*args, **kwargs):
        raise AssertionError("import must not prepare another round")
    monkeypatch.setattr(producer.env, "prepare_round", forbidden)
    # Identity is captured before the synthetic sentinel replaces setup.
    setup = json.loads((roots / "result.json").read_bytes())["setup"]
    monkeypatch.setattr(runner, "_panel_setup_identity", lambda: setup)
    result = load(roots, expected_result_sha256=digest)
    assert result["result_sha256"] == digest
    assert set(result["games"]) == {7123, 7124}
    for seed, game in result["games"].items():
        root = result["roots"][seed]
        assert runner._state_snapshot(game.round) == root["round"]
        assert game.level_idx == root["level_idx"]


def test_wrong_report_pin_refused(roots):
    with pytest.raises(runner.BenchmarkRefusal, match="SHA256"):
        load(roots, expected_result_sha256="0" * 64)


@pytest.mark.parametrize("change", ["roster", "setup", "recycled", "coverage"])
def test_report_tampering_refused(roots, change):
    path = roots / "result.json"
    report = json.loads(path.read_bytes())
    if change == "roster":
        report["policies"] = ["smart"]
    elif change == "setup":
        report["setup"]["engine"]["sha256"] = "0" * 64
        report["config"]["setup"] = report["setup"]
    elif change == "recycled":
        report["config"]["continue_from"] = "elsewhere"
    else:
        report["roots"].pop("7124")
    replace(path, report)
    with pytest.raises(runner.BenchmarkRefusal):
        load(roots)


@pytest.mark.parametrize("change", ["hash", "seed", "phase"])
def test_root_tampering_refused(roots, change):
    path = roots / "root-7123.json"
    root = json.loads(path.read_bytes())
    if change == "hash":
        root["extra"] = "not authenticated"
    elif change == "seed":
        root["seed"] = True
    else:
        root["round"]["phase"] = "bury"
    replace(path, root)
    with pytest.raises(runner.BenchmarkRefusal):
        load(roots)


def test_setup_paths_are_nonsemantic_but_source_hashes_are_bound():
    identity = runner._panel_setup_identity()
    for key in ("engine", "prepare_round", "smartbot", "snapshot"):
        identity[key]["path"] = "/different/checkout.py"
    assert runner._compatible_panel_setup(identity, report_sha256="0" * 64)
    identity["snapshot"]["sha256"] = "0" * 64
    assert not runner._compatible_panel_setup(identity, report_sha256="0" * 64)


@pytest.mark.parametrize("change", [None, "mode", "recycled", "seeds", "coverage"])
def test_legacy_report_import(roots, change):
    path = roots / "result.json"
    original = json.loads(path.read_bytes())
    report = {"schema": runner.SCHEMA, "mode": "run",
              "config": {"seeds": [7123, 7124]}, "roots": original["roots"]}
    if change == "mode":
        report["mode"] = "dry-run"
    elif change == "recycled":
        report["config"]["prepared_roots_from"] = "another-source"
    elif change == "seeds":
        report["config"]["seeds"].reverse()
    elif change == "coverage":
        report["roots"].pop("7124")
    replace(path, report)
    if change is not None:
        with pytest.raises(runner.BenchmarkRefusal):
            load(roots)
    else:
        digest = runner._sha_bytes(path.read_bytes())
        restored = load(roots, expected_result_sha256=digest)
        assert restored["root_hashes"] == original["roots"]
        assert restored["result_sha256"] == digest


@pytest.mark.parametrize("legacy", [False, True])
def test_restore_mismatch_refused_in_both_schemas(roots, monkeypatch, legacy):
    if legacy:
        path = roots / "result.json"
        original = json.loads(path.read_bytes())
        replace(path, {"schema": runner.SCHEMA, "mode": "run",
                       "config": {"seeds": [7123, 7124]}, "roots": original["roots"]})
    restore = runner._restore_game
    def corrupt(*args):
        game = restore(*args)
        game.level_idx = [12, 12]
        return game
    monkeypatch.setattr(runner, "_restore_game", corrupt)
    with pytest.raises(runner.BenchmarkRefusal, match="restored game state mismatch"):
        load(roots)


@pytest.mark.parametrize("drift", [None, "report", "snapshot", "old_env", "new_env",
                                   "engine", "definition", "serializer"])
def test_historical_exception_requires_every_pin(monkeypatch, drift):
    # Synthetic identity fixtures exercise the exception, not real old artifacts.
    # Actual helper definition hashes remain checked, except in the drift case.
    current = runner._panel_setup_identity()
    current["prepare_round"]["sha256"] = (
        "fe434d5a30e32d38c4c3aa3c4812e11c10c8534b31a4a23da9155c34428ecd87")
    recorded = deepcopy(current)
    recorded["prepare_round"]["sha256"] = (
        "c61f7cebf2133ad1cc6daaad8698f246178d6ebf41a4b6e569888a7b373a6d26")
    recorded["snapshot"]["sha256"] = (
        "bd52ee31cb2d07345b4a2de1063c659dd1558313ba4605572f1e6a397ac90700")
    report = "8ed56de254e7c7ff4341905a02a9a3dd2346412db04b6902f2098b0b839c5f5e"
    if drift == "report":
        report = "0" * 64
    elif drift in ("snapshot", "engine"):
        recorded[drift]["sha256"] = "0" * 64
    elif drift == "old_env":
        recorded["prepare_round"]["sha256"] = "0" * 64
    elif drift == "new_env":
        current["prepare_round"]["sha256"] = "0" * 64
    elif drift == "definition":
        monkeypatch.setattr(runner.inspect, "getsource", lambda fn: "changed definition")
    monkeypatch.setattr(runner, "_panel_setup_identity", lambda: current)
    monkeypatch.setattr(runner, "_callable_source_identity", lambda fn: {
        "sha256": "0" * 64 if drift == "serializer" else
        "03c8569ca8232c49218264047d7221c310288701e7bc6ca1cd81b08e8064787f"})
    assert runner._compatible_panel_setup(recorded, report_sha256=report) is (drift is None)

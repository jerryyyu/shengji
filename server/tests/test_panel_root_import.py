"""Root import qualification on temporary, setup-only test fixtures."""
import json

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

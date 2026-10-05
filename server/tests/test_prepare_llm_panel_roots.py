"""Temporary synthetic setup artifacts only; never enter gameplay."""
import json
import stat

import pytest

from scripts import prepare_llm_panel_roots as producer
from scripts import w32_llm_benchmark as benchmark


def test_roots_are_deterministic_private_and_setup_only(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("gameplay must not run")
    monkeypatch.setattr(producer.env, "play_prepared_round", forbidden)
    first, second = tmp_path / "first", tmp_path / "second"
    a = producer.prepare_roots(output=first, seeds=[7123, 7124])
    b = producer.prepare_roots(output=second, seeds=[7123, 7124])
    assert a == b
    assert a["config"]["seed_order"] == [7123, 7124]
    assert a["policies"] == list(benchmark.PANEL_POLICIES)
    assert a["gameplay"] is False
    assert a["provider_calls"] == a["model_calls"] == 0
    assert a["setup"] == benchmark._panel_setup_identity()
    assert stat.S_IMODE(first.stat().st_mode) == 0o700
    for seed in (7123, 7124):
        path = first / f"root-{seed}.json"
        raw = path.read_bytes()
        assert raw == (second / path.name).read_bytes()
        assert benchmark._sha(json.loads(raw)) == a["roots"][str(seed)]
        assert stat.S_IMODE(path.stat().st_mode) == 0o400
    assert json.loads((first / "result.json").read_bytes()) == a
    with pytest.raises(producer.RootPreparationRefusal, match="fresh"):
        producer.prepare_roots(output=first, seeds=[7123])


@pytest.mark.parametrize("seeds", [[], [1, 1], ["bad"]])
def test_invalid_seeds_fail_before_setup(tmp_path, monkeypatch, seeds):
    def forbidden(*args, **kwargs):
        raise AssertionError("setup must not run")
    monkeypatch.setattr(producer.env, "prepare_round", forbidden)
    output = tmp_path / "roots"
    with pytest.raises(producer.RootPreparationRefusal):
        producer.prepare_roots(output=output, seeds=seeds)
    assert not output.exists()


def test_publication_failure_preserves_partial_without_result(tmp_path, monkeypatch):
    publish = producer._publish
    calls = []
    def fail_second(path, value):
        calls.append(path.name)
        if len(calls) == 2:
            raise OSError("synthetic publication failure")
        publish(path, value)
    monkeypatch.setattr(producer, "_publish", fail_second)
    output = tmp_path / "partial"
    with pytest.raises(OSError, match="synthetic"):
        producer.prepare_roots(output=output, seeds=[7123, 7124])
    assert (output / "root-7123.json").is_file()
    assert not (output / "result.json").exists()
    with pytest.raises(producer.RootPreparationRefusal, match="fresh"):
        producer.prepare_roots(output=output, seeds=[7123])


def test_setup_identity_fails_when_source_unavailable(monkeypatch):
    monkeypatch.setattr(benchmark.inspect, "getsourcefile", lambda value: None)
    with pytest.raises(benchmark.BenchmarkRefusal, match="unavailable"):
        benchmark._panel_setup_identity()

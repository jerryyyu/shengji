"""Focused checks for the session cache behind the CWV module fixtures."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from tests import conftest


def _isolated_factory(tmp_path_factory):
    # Keep synthetic generators out of the real session fixture cache.  The
    # fixture body is deliberately exercised, with a fresh cache root.
    return conftest.cwv_corpus_factory.__wrapped__(tmp_path_factory)


def test_cwv_factory_generates_once_and_copies_are_independent(tmp_path_factory):
    factory = _isolated_factory(tmp_path_factory)
    calls = []
    incoming_seed_windows = os.environ.get("SHENGJI_SEED_WINDOWS")

    def generate(source):
        calls.append(source)
        (source / "shards").mkdir(parents=True)
        (source / "shards" / "part.jsonl").write_bytes(b"one\ntwo\n")
        (source / "manifest.json").write_text(json.dumps({
            "shards": [{"path": "shards/part.jsonl"}],
        }))

    recipe = ("synthetic", 6, 4_100_000)
    source = factory(recipe, generate)
    assert factory(recipe, lambda _source: pytest.fail("generated twice")) == source
    assert len(calls) == 1
    assert os.environ.get("SHENGJI_SEED_WINDOWS") == incoming_seed_windows
    other_source = factory(("synthetic-other", 2, 4_107_777), generate)
    assert other_source != source and len(calls) == 2

    first = tmp_path_factory.mktemp("cwv-copy") / "first"
    second = tmp_path_factory.mktemp("cwv-copy") / "second"
    shutil.copytree(source, first)
    shutil.copytree(source, second)
    assert first.joinpath("manifest.json").read_bytes() == second.joinpath(
        "manifest.json").read_bytes()
    assert first.joinpath("shards/part.jsonl").read_bytes() == second.joinpath(
        "shards/part.jsonl").read_bytes()

    first.joinpath("shards/part.jsonl").write_bytes(b"mutated\n")
    assert second.joinpath("shards/part.jsonl").read_bytes() == b"one\ntwo\n"
    assert source.joinpath("shards/part.jsonl").read_bytes() == b"one\ntwo\n"

    manifest = json.loads(second.joinpath("manifest.json").read_text())
    relative = Path(manifest["shards"][0]["path"])
    assert not relative.is_absolute()
    assert second.joinpath(relative).is_file()


def test_cwv_factory_restores_seed_window_environment_on_failure(
        tmp_path_factory, monkeypatch):
    factory = _isolated_factory(tmp_path_factory)
    monkeypatch.setenv("SHENGJI_SEED_WINDOWS", "/tmp/original-seed-windows.json")
    seen = []
    failed_sources = []

    def fail(source):
        seen.append(os.environ["SHENGJI_SEED_WINDOWS"])
        failed_sources.append(source)
        (source / "partial").mkdir(parents=True)
        raise RuntimeError("synthetic generator failure")

    with pytest.raises(RuntimeError, match="synthetic generator failure"):
        factory(("failure",), fail)
    assert seen and seen[0] != "/tmp/original-seed-windows.json"
    assert failed_sources[0].joinpath("partial").is_dir()
    assert os.environ["SHENGJI_SEED_WINDOWS"] == "/tmp/original-seed-windows.json"

    # Also cover restoration when the variable was absent at entry.
    monkeypatch.delenv("SHENGJI_SEED_WINDOWS")
    with pytest.raises(RuntimeError):
        factory(("failure-absent",), fail)
    assert "SHENGJI_SEED_WINDOWS" not in os.environ

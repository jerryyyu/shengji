"""Cheap witnesses for the TEST-ONLY shared checkpoint fixtures.

The fixture shares immutable checkpoint bytes, not a path or mutable model.
Each consumer gets an exclusive private file, and the training helper's
intentional ``torch.manual_seed`` side effect is isolated with ``fork_rng``.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import torch

from tests import conftest


def _isolated_factory(tmp_path_factory, architecture):
    # Exercise the fixture body with a fresh cache for each synthetic test.
    fixture = getattr(conftest, f"cwv_{architecture}_checkpoint_factory")
    return fixture.__wrapped__(tmp_path_factory)


@pytest.mark.parametrize("architecture", ["gru", "mlp"])
def test_factory_builds_once_and_gives_exclusive_independent_files(
        tmp_path_factory, architecture):
    factory = _isolated_factory(tmp_path_factory, architecture)
    calls = []

    def build(path, **recipe):
        calls.append((path, recipe))
        Path(path).write_bytes(b"checkpoint-bytes")

    first = tmp_path_factory.mktemp("consumer") / "first.pt"
    second = tmp_path_factory.mktemp("consumer") / "second.pt"
    assert factory(first, build) == str(first)
    assert factory(second, lambda *_args, **_kwargs: pytest.fail("built twice")) == str(second)

    assert len(calls) == 1
    assert calls[0][1] == {
        "seed0": 4_200_000,
        "rounds": 2,
        "architecture": architecture,
        "width": 16,
        "max_epochs": 2,
        "patience": 4,
        "seed": 0,
        "quiet": True,
    }
    assert first.read_bytes() == second.read_bytes() == b"checkpoint-bytes"

    first.write_bytes(b"mutated-consumer")
    assert second.read_bytes() == b"checkpoint-bytes"
    with pytest.raises(FileExistsError):
        factory(second, build)
    assert second.read_bytes() == b"checkpoint-bytes"


@pytest.mark.parametrize("architecture", ["gru", "mlp"])
def test_factory_does_not_cache_failure_and_preserves_torch_rng(
        tmp_path_factory, architecture):
    factory = _isolated_factory(tmp_path_factory, architecture)
    calls = []

    def fail(path, **_recipe):
        calls.append("failure")
        torch.manual_seed(123456)
        Path(path).write_bytes(b"partial")
        raise RuntimeError("synthetic build failure")

    before_failure = torch.random.get_rng_state().clone()
    failed = tmp_path_factory.mktemp("consumer") / "failed.pt"
    with pytest.raises(RuntimeError, match="synthetic build failure"):
        factory(failed, fail)
    assert torch.equal(torch.random.get_rng_state(), before_failure)
    assert not failed.exists()

    def succeed(path, **_recipe):
        calls.append("success")
        torch.manual_seed(654321)
        Path(path).write_bytes(b"success")

    before_success = torch.random.get_rng_state().clone()
    successful = tmp_path_factory.mktemp("consumer") / "successful.pt"
    factory(successful, succeed)
    assert successful.read_bytes() == b"success"
    assert calls == ["failure", "success"]
    assert torch.equal(torch.random.get_rng_state(), before_success)


def test_architectures_have_separate_caches(tmp_path_factory):
    calls = []

    def build(path, **recipe):
        calls.append(recipe["architecture"])
        Path(path).write_bytes(recipe["architecture"].encode())

    for architecture in ("gru", "mlp"):
        factory = _isolated_factory(tmp_path_factory, architecture)
        for index in range(2):
            destination = tmp_path_factory.mktemp("consumer") / f"{index}.pt"
            factory(destination, build)
            assert destination.read_bytes() == architecture.encode()
    assert calls == ["gru", "mlp"]

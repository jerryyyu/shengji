"""Durability boundary for the versioned transitive RL encoder identity."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from shengji.engine.cards import Ordering
from shengji.engine.combos import Decomposition
from shengji.rl import encoder_identity as IDENTITY
from shengji.rl.encode import (ENCODER_IMPLEMENTATION_SHA256,
                               ENCODER_SOURCE_SHA256S, encode_action)


EXPECTED = {
    "identity_schema": "rl-encoder-transitive-source-contract-v1",
    "schema": "rl-observation-v1-public-no-private-kitty",
    "layout_version": 1,
    "implementation_sha256": (
        "56b8f92435b22a57712a4e59b1d3d9fc6639fd613ec2a54da5ec730e171d1d25"
    ),
    "source_sha256s": {
        "cards": (
            "42452b157818da1792f4490c3a50c10060eda1a02bb6b2c91544a62fbc0d000a"
        ),
        "combos": (
            "2b0b0acceb0786b4ce781475c0f3e3d656ebe349fdf00bfffd668d6847885486"
        ),
        "encode": (
            "819fe2b2fc3cb9f0dd18cfd1c916b2387e92d97345f6dda212b2f149c7e7408b"
        ),
        "memory": (
            "905873b332fd54471070b25ce24f100b813c9a9f234c1b50254d00895140cf51"
        ),
    },
}


def test_transitive_contract_is_pinned_without_rewriting_legacy_identity():
    assert IDENTITY.encoder_contract() == EXPECTED
    assert set(IDENTITY.SOURCE_PATHS) == {
        "cards", "combos", "encode", "memory"}
    # The two-file identity is frozen into the live cde0fec V11-v2 parent.
    assert set(ENCODER_SOURCE_SHA256S) == {"encode", "memory"}
    assert ENCODER_IMPLEMENTATION_SHA256 == \
        "a55cba182152fa51f2d304fb1b9adb02b6e23f4073f7bad37fe2d6ca1ab31afa"


@pytest.mark.parametrize("dependency", ["cards", "combos"])
def test_transitive_contract_changes_when_engine_dependency_bytes_change(
        monkeypatch, dependency):
    real_sha256 = IDENTITY.sha256_file
    target = IDENTITY.SOURCE_PATHS[dependency].resolve()

    def changed(path):
        return "0" * 64 if path.resolve() == target else real_sha256(path)

    monkeypatch.setattr(IDENTITY, "sha256_file", changed)
    observed = IDENTITY.encoder_contract()
    assert observed["source_sha256s"][dependency] == "0" * 64
    assert observed["implementation_sha256"] != \
        EXPECTED["implementation_sha256"]


def test_pair_run_mutant_changes_a_pinned_action_vector(monkeypatch):
    rnd = SimpleNamespace(ordering=Ordering("H", "7"))
    baseline = encode_action(["C3", "C3"], rnd)
    digest = hashlib.sha256(json.dumps(
        baseline, separators=(",", ":")).encode()).hexdigest()
    assert baseline[56] == 0.25
    assert digest == \
        "ba6553779589a4b3d90ccc5b90a420f9480656b3922d1f340b944edcc3d7742b"

    monkeypatch.setattr(Decomposition, "max_pair_run", lambda _self: 0)
    mutated = encode_action(["C3", "C3"], rnd)
    assert mutated[56] == 0.0
    assert mutated != baseline


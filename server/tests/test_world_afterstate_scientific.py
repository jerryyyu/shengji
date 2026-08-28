from __future__ import annotations

import shutil

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_scientific import (
    WorldAfterstateScientificError, consume_stage_attempt,
    initialize_scientific_root, lock_root_for, reopen_scientific_root)


def test_sibling_lock_survives_root_loss_and_spends_each_stage_once(
        monkeypatch, tmp_path):
    freeze = {"freeze_sha256": "f" * 64}
    capacity = {"capacity": True}
    packet = {"packet": True}
    admission = {"admission_sha256": "a" * 64}
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_scientific."
        "validate_experiment_freeze", lambda *_args: None)
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_scientific.build_admission",
        lambda *_args, **_kwargs: admission)
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_scientific.reauthenticate_admission",
        lambda *_args, **_kwargs: b"marker\n")
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_scientific.validate_admission",
        lambda *_args, **_kwargs: None)
    root = tmp_path / "scientific"
    initialize_scientific_root(
        root, freeze_raw=canonical_json_bytes(freeze),
        capacity_raw=canonical_json_bytes(capacity),
        population_packet_raw=canonical_json_bytes(packet),
        repo=tmp_path, review_commit="b" * 40)
    reopened = reopen_scientific_root(root, repo=tmp_path)
    assert reopened[0] == freeze
    attempt = consume_stage_attempt(
        root, stage="dataset", freeze_sha256="f" * 64,
        admission_sha256="a" * 64, inputs={"workers": 16})
    assert attempt["retry_authorized"] is False
    with pytest.raises(WorldAfterstateScientificError,
                       match="already consumed"):
        consume_stage_attempt(
            root, stage="dataset", freeze_sha256="f" * 64,
            admission_sha256="a" * 64, inputs={"workers": 16})

    lock = lock_root_for(root)
    for path in root.rglob("*"):
        if path.is_dir():
            path.chmod(0o700)
        else:
            path.chmod(0o600)
    root.chmod(0o700)
    shutil.rmtree(root)
    assert lock.is_dir()
    with pytest.raises(WorldAfterstateScientificError,
                       match="namespace occupied"):
        initialize_scientific_root(
            root, freeze_raw=canonical_json_bytes(freeze),
            capacity_raw=canonical_json_bytes(capacity),
            population_packet_raw=canonical_json_bytes(packet),
            repo=tmp_path, review_commit="b" * 40)

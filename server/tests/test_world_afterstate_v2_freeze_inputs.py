"""Focused tests for inert Value V2 freeze-input derivation."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl import world_afterstate_v2_freeze_inputs as inputs
from shengji.rl.world_afterstate_v2_freeze_inputs import (
    FreezeInputsError, build_continuation_policy_v2, build_early_stage_config_v2,
    build_population_adapter_input_v2, build_seed_registry_v2, protocol_bytes,
    reopen_early_stage_config_v2_bytes,
    publish_inputs_v2, reopen_continuation_policy_v2_bytes,
    reopen_population_adapter_input_v2_bytes, reopen_protocol_bytes,
)
from shengji.rl.world_afterstate_v2_protocol import D256_MAX_ATTEMPTS_PER_SLOT


SOURCE = "a" * 40
PROTOCOL = hashlib.sha256(protocol_bytes()).hexdigest()
CAPACITY = "b" * 64


def test_protocol_is_authoritative_and_canonical():
    raw = protocol_bytes()
    assert raw == canonical_json_bytes(reopen_protocol_bytes(raw))


def test_population_input_is_deterministic_and_strict():
    value = build_population_adapter_input_v2(
        source_git=SOURCE, protocol_sha256=PROTOCOL, capacity_sha256=CAPACITY,
        selected_tier="D256", workers=4, deadline_seconds=100,
        heartbeat_seconds=10,
        max_attempts_per_slot=D256_MAX_ATTEMPTS_PER_SLOT)
    raw = canonical_json_bytes(value)
    assert reopen_population_adapter_input_v2_bytes(raw,
        expected_workers=4, expected_deadline=100)["workers"] == 4
    legacy = dict(value)
    legacy["schema"] = "world-afterstate-v2-population-adapter-input-v2"
    with pytest.raises(FreezeInputsError, match="schema"):
        reopen_population_adapter_input_v2_bytes(canonical_json_bytes(legacy))
    with pytest.raises(FreezeInputsError, match="duplicate"):
        reopen_population_adapter_input_v2_bytes(
            b'{"schema":"x","schema":"y"}')


@pytest.mark.parametrize("attempt_cap", (127, 129))
def test_population_input_refuses_any_non_d256_attempt_cap(attempt_cap):
    with pytest.raises(FreezeInputsError,
                       match="D256 population attempt cap drift"):
        build_population_adapter_input_v2(
            source_git=SOURCE, protocol_sha256=PROTOCOL,
            capacity_sha256=CAPACITY, selected_tier="D256", workers=4,
            deadline_seconds=100, heartbeat_seconds=10,
            max_attempts_per_slot=attempt_cap)

    valid = build_population_adapter_input_v2(
        source_git=SOURCE, protocol_sha256=PROTOCOL,
        capacity_sha256=CAPACITY, selected_tier="D256", workers=4,
        deadline_seconds=100, heartbeat_seconds=10,
        max_attempts_per_slot=D256_MAX_ATTEMPTS_PER_SLOT)
    forged = dict(valid, max_attempts_per_slot=attempt_cap)
    with pytest.raises(FreezeInputsError,
                       match="D256 population attempt cap drift"):
        reopen_population_adapter_input_v2_bytes(
            canonical_json_bytes(forged))


def test_32_worker_state_and_continuation_inputs_round_trip_but_33_refuses():
    population = build_population_adapter_input_v2(
        source_git=SOURCE, protocol_sha256=PROTOCOL, capacity_sha256=CAPACITY,
        selected_tier="D256", workers=32, deadline_seconds=100,
        heartbeat_seconds=10,
        max_attempts_per_slot=D256_MAX_ATTEMPTS_PER_SLOT)
    assert reopen_population_adapter_input_v2_bytes(
        canonical_json_bytes(population), expected_workers=32)["workers"] == 32
    config = build_early_stage_config_v2(
        source_git=SOURCE, protocol_sha256=PROTOCOL,
        capacity_sha256=CAPACITY, selected_tier="D256", label_workers=32,
        evidence_root="/unused", deadline_seconds=100)
    assert reopen_early_stage_config_v2_bytes(
        canonical_json_bytes(config), expected_label_workers=32)["label_workers"] == 32
    legacy_config = dict(config)
    legacy_config["schema"] = "world-afterstate-v2-early-stage-adapters-input-v1"
    with pytest.raises(FreezeInputsError, match="schema"):
        reopen_early_stage_config_v2_bytes(canonical_json_bytes(legacy_config))
    with pytest.raises(FreezeInputsError, match="workers"):
        build_population_adapter_input_v2(
            source_git=SOURCE, protocol_sha256=PROTOCOL,
            capacity_sha256=CAPACITY, selected_tier="D256", workers=33,
            deadline_seconds=100, heartbeat_seconds=10,
            max_attempts_per_slot=D256_MAX_ATTEMPTS_PER_SLOT)
    with pytest.raises(FreezeInputsError, match="workers"):
        build_early_stage_config_v2(
            source_git=SOURCE, protocol_sha256=PROTOCOL,
            capacity_sha256=CAPACITY, selected_tier="D256", label_workers=33,
            evidence_root="/unused", deadline_seconds=100)


def test_all_typed_derivations_share_namespace():
    population = build_population_adapter_input_v2(
        source_git=SOURCE, protocol_sha256=PROTOCOL, capacity_sha256=CAPACITY,
        selected_tier="D256", workers=1, deadline_seconds=20,
        heartbeat_seconds=1,
        max_attempts_per_slot=D256_MAX_ATTEMPTS_PER_SLOT)
    config = build_early_stage_config_v2(
        source_git=SOURCE, protocol_sha256=PROTOCOL, capacity_sha256=CAPACITY,
        selected_tier="D256", label_workers=2, evidence_root="/unused",
        deadline_seconds=20)
    seed = build_seed_registry_v2(source_git=SOURCE, protocol_sha256=PROTOCOL,
        capacity_sha256=CAPACITY, selected_tier="D256")
    policy = build_continuation_policy_v2(source_git=SOURCE,
        protocol_sha256=PROTOCOL, capacity_sha256=CAPACITY, selected_tier="D256")
    namespace = population["population_namespace_sha256"]
    assert config["population_namespace_sha256"] == namespace
    assert seed["population_namespace_sha256"] == namespace
    assert policy["population_namespace_sha256"] == namespace
    with pytest.raises(FreezeInputsError, match="authoritative"):
        wrong = dict(policy)
        wrong["continuation_policy"] = "wrong"
        reopen_continuation_policy_v2_bytes(canonical_json_bytes(wrong),
            source_git=SOURCE, protocol_sha256=PROTOCOL,
            capacity_sha256=CAPACITY, selected_tier="D256")


def test_measured_twelve_worker_continuation_arm_is_freezeable():
    config = build_early_stage_config_v2(
        source_git=SOURCE, protocol_sha256=PROTOCOL,
        capacity_sha256=CAPACITY, selected_tier="D256", label_workers=12,
        evidence_root="/unused", deadline_seconds=20)
    from shengji.rl.world_afterstate_v2_freeze_inputs import (
        reopen_early_stage_config_v2_bytes,
    )
    reopened = reopen_early_stage_config_v2_bytes(
        canonical_json_bytes(config), expected_label_workers=12)
    assert reopened["label_workers"] == 12


def test_publication_is_exclusive(tmp_path: Path):
    population = build_population_adapter_input_v2(
        source_git=SOURCE, protocol_sha256=PROTOCOL, capacity_sha256=CAPACITY,
        selected_tier="D256", workers=1, deadline_seconds=20,
        heartbeat_seconds=1,
        max_attempts_per_slot=D256_MAX_ATTEMPTS_PER_SLOT)
    config = build_early_stage_config_v2(
        source_git=SOURCE, protocol_sha256=PROTOCOL, capacity_sha256=CAPACITY,
        selected_tier="D256", label_workers=1, evidence_root="/unused",
        deadline_seconds=20)
    seed = build_seed_registry_v2(source_git=SOURCE, protocol_sha256=PROTOCOL,
        capacity_sha256=CAPACITY, selected_tier="D256")
    policy = build_continuation_policy_v2(source_git=SOURCE,
        protocol_sha256=PROTOCOL, capacity_sha256=CAPACITY, selected_tier="D256")
    paths = publish_inputs_v2(tmp_path / "inputs", protocol=protocol_bytes(),
        population=population, config=config, seed=seed,
        continuation_policy=policy)
    assert len(paths) == 5
    assert all(path.stat().st_mode & 0o777 == 0o400
               and path.stat().st_nlink == 1 for path in paths)
    with pytest.raises(FreezeInputsError, match="occupied"):
        publish_inputs_v2(tmp_path / "inputs", protocol=protocol_bytes(),
            population=population, config=config, seed=seed,
            continuation_policy=policy)


def test_publication_refuses_mixed_bundle_before_creating_directory(tmp_path: Path):
    population = build_population_adapter_input_v2(
        source_git=SOURCE, protocol_sha256=PROTOCOL, capacity_sha256=CAPACITY,
        selected_tier="D256", workers=1, deadline_seconds=20,
        heartbeat_seconds=1,
        max_attempts_per_slot=D256_MAX_ATTEMPTS_PER_SLOT)
    config = build_early_stage_config_v2(
        source_git=SOURCE, protocol_sha256=PROTOCOL, capacity_sha256=CAPACITY,
        selected_tier="D256", label_workers=1, evidence_root="/unused",
        deadline_seconds=20)
    seed = build_seed_registry_v2(
        source_git=SOURCE, protocol_sha256=PROTOCOL,
        capacity_sha256=CAPACITY, selected_tier="D256")
    foreign_policy = build_continuation_policy_v2(
        source_git=SOURCE, protocol_sha256=PROTOCOL,
        capacity_sha256="c" * 64, selected_tier="D256")
    root = tmp_path / "mixed"
    with pytest.raises(FreezeInputsError, match="bundle binding"):
        publish_inputs_v2(root, protocol=protocol_bytes(),
            population=population, config=config, seed=seed,
            continuation_policy=foreign_policy)
    assert not root.exists()


def test_mid_bundle_failure_leaves_no_published_prefix(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    population = build_population_adapter_input_v2(
        source_git=SOURCE, protocol_sha256=PROTOCOL, capacity_sha256=CAPACITY,
        selected_tier="D256", workers=1, deadline_seconds=20,
        heartbeat_seconds=1,
        max_attempts_per_slot=D256_MAX_ATTEMPTS_PER_SLOT)
    config = build_early_stage_config_v2(
        source_git=SOURCE, protocol_sha256=PROTOCOL, capacity_sha256=CAPACITY,
        selected_tier="D256", label_workers=1, evidence_root="/unused",
        deadline_seconds=20)
    seed = build_seed_registry_v2(
        source_git=SOURCE, protocol_sha256=PROTOCOL,
        capacity_sha256=CAPACITY, selected_tier="D256")
    policy = build_continuation_policy_v2(
        source_git=SOURCE, protocol_sha256=PROTOCOL,
        capacity_sha256=CAPACITY, selected_tier="D256")
    original = inputs._publish_one
    calls = 0

    def interrupted(path: Path, raw: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("injected publication interruption")
        original(path, raw)

    monkeypatch.setattr(inputs, "_publish_one", interrupted)
    root = tmp_path / "interrupted"
    with pytest.raises(OSError, match="injected"):
        publish_inputs_v2(root, protocol=protocol_bytes(),
            population=population, config=config, seed=seed,
            continuation_policy=policy)
    assert not root.exists()
    assert not (tmp_path / ".interrupted.partial").exists()

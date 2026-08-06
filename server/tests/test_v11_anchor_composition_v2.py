"""Falsification tests for the corrected-v2 protected composition parent."""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import v11_anchor_composition as V1  # noqa: E402
import v11_anchor_composition_v2 as COMP  # noqa: E402
import v11_revalidate_v2 as DIRECT  # noqa: E402


DIRECT_SOURCES = {
    "runner": "9bc265ad3be7e7de40bd70b8c8446c4d2d163918d342ffd56f50173d22d23da2",
    "evaluation": "f579918ad8594c895a1b02f6b2d3cb17dc56ba50092c703f23cc4534a11349c9",
    "registry": "7ed839b75578245e2226ba385a91ced0117a8ee05207b8c5782354316a1f99da",
    "mcbot": "4a268ba1277ab0267974b7cd10d2b69daf52d90cc80917d5b492da27037fce0c",
    "smart": "facfb6a9bb67f82d1bddb855f01ce49adf5f0caaca92bfb5da09ba343c29512c",
    "memory": "905873b332fd54471070b25ce24f100b813c9a9f234c1b50254d00895140cf51",
    "env": "04b1d18e2ad4783c5160913b66c2adf568625de1aaf6bdf300c6a4b00c2f0d8b",
    "ballot": "63e2e94ca12f9ebf8dce30c1a1bdbe3fe9cf6223603677173d4eb75e334845d5",
    "round": "7a91b3573ecb34c488e3960008d21ebfda283e01003f6454a1ffd62c41b9b679",
    "game": "613c5dd72a1cbd3b50a96eef6e0b84746052dc2b0b28fb08005ff34455359e43",
    "torch_policy": "3fcd60a69097ef29d64a0de2f08548c42f6e9ae6ad1be5ad49cc9cc99d068720",
    "encoder": "819fe2b2fc3cb9f0dd18cfd1c916b2387e92d97345f6dda212b2f149c7e7408b",
    "npnet": "0ee6e5e3387c6ce834c9209ebb9ab95421228807c1b4713ca8d34374facd9cbb",
    "parity_fixture": "10af64758fd0a4afb2d647a2a648ca6109195ca47480403a52ba8b5903203a97",
    "fast_router": "f2506d5c51b8ad37303f04dce59899de0d7c1179633b08ce61f48eb86cec1a3e",
    "checkpoint": COMP.CHECKPOINT_SHA256,
}


def _counter(search: bool) -> dict:
    values = {field: 0 for field in DIRECT.COUNTER_FIELDS}
    if search:
        values.update({
            "rollouts": 600,
            "searches": 10,
            "search_secs": 1.0,
            "sample_attempts": 300,
            "accepted_worlds": 300,
        })
    return values


def _counter_totals() -> dict:
    return {
        label: {
            side: _counter(not (label == "arm" and side == "arm"))
            for side in ("arm", "opp")
        }
        for label in DIRECT.LABELS
    }


def _contrast(a: str, b: str, mean: float, half: float) -> dict:
    return {
        "a": a, "b": b, "mean": mean, "half_width_95": half,
        "clusters": DIRECT.TOTAL_CLUSTERS,
    }


def direct_aggregate(*, compatible: bool = False,
                     null_sane: bool = True) -> dict:
    effect = 0.30 if compatible else 0.10
    stats = {
        "arm-reference": _contrast("arm", "reference", effect, 0.20),
        "arm-null": _contrast("arm", "null", effect, 0.20),
        "null-reference": _contrast(
            "null", "reference", 0.01 if null_sane else 0.20, 0.10),
    }
    counters = _counter_totals()
    dose = COMP._direct_accepted_dose_from_totals(counters)
    criteria = DIRECT.gate_criteria(stats, dose)
    runtime = {
        "host": "sealed-host",
        "python": "3.14.6",
        "fast_engine": True,
        "require_voids": True,
        "experimental_sampler_flags": [],
        "encoder_contract": DIRECT.EXPECTED_ENCODER_CONTRACT,
        "digests": {**DIRECT_SOURCES, "fast_binary": "f" * 64},
    }
    return {
        "schema": DIRECT.AGGREGATE_SCHEMA,
        "claim": DIRECT.CLAIM,
        "complete": True,
        "git_sha": COMP.DIRECT_GIT_SHA,
        "runtime_identity": runtime,
        "encoder_contract": DIRECT.EXPECTED_ENCODER_CONTRACT,
        "invalidated_v1": DIRECT.INVALIDATED_V1,
        "clusters": DIRECT.TOTAL_CLUSTERS,
        "seed0": DIRECT.SEED0,
        "seed_hi": DIRECT.SEED_HI,
        "labels": DIRECT.LABELS,
        "checkpoint_sha256": COMP.CHECKPOINT_SHA256,
        "selection_rule": DIRECT.SELECTION_RULE,
        "input_shards": [
            {
                "manifest_path": f"direct-{index}.manifest.json",
                "manifest_sha256": COMP.stable_digest(["manifest", index]),
                "records_path": f"direct-{index}.jsonl",
                "records_sha256": COMP.stable_digest(["records", index]),
                "shard_index": index,
            }
            for index in range(DIRECT.SHARD_COUNT)
        ],
        "record_counts": {
            label: 2 * DIRECT.TOTAL_CLUSTERS for label in DIRECT.LABELS},
        "counter_totals": counters,
        "accepted_dose": dose,
        "stats": stats,
        "criteria": criteria,
        "checkpoint_compatible_with_restored_v1": criteria["all"],
        "protected_composition_authorized": False,
        "production_promotion": False,
    }


def _write_parent(tmp_path, payload, monkeypatch):
    path = tmp_path / "direct-v2.aggregate.json"
    path.write_text(json.dumps(payload, sort_keys=True) + "\n")
    digest = COMP.sha256(path)
    monkeypatch.setattr(COMP, "DIRECT_AGGREGATE_SHA256", digest)
    return path, digest


def test_v2_binds_exact_cde0fec_direct_protocol_and_preserves_estimand():
    assert COMP.SCHEMA == "v11-anchor-composition-shard-v2"
    assert COMP.AGGREGATE_SCHEMA == "v11-anchor-composition-aggregate-v2"
    assert COMP.DIRECT_GIT_SHA == \
        "cde0fecf4151685e7174be8a7aa64b0ee6478edd"
    assert COMP.DIRECT_SOURCE_SHA256 == DIRECT_SOURCES
    assert DIRECT.SEED0 == 142_000_000
    assert DIRECT.SEED_HI == 142_002_047
    assert DIRECT.AGGREGATE_SCHEMA == "v11-current-revalidation-aggregate-v2"
    assert DIRECT.EXPECTED_ENCODER_CONTRACT["source_sha256s"] == {
        "encode": DIRECT_SOURCES["encoder"],
        "memory": DIRECT_SOURCES["memory"],
    }

    assert COMP.PROTOCOLS == V1.PROTOCOLS
    assert COMP.CHAMPION_LANES == V1.CHAMPION_LANES
    assert COMP.SELECTION_RULE == V1.SELECTION_RULE
    assert COMP.DIRECT_USAGE == V1.DIRECT_USAGE
    for champion in COMP.CHAMPION_LANES:
        assert COMP.labels_for(champion) == V1.labels_for(champion)
        assert COMP.protocol_problems(champion) == []


def test_v2_refuses_any_caller_chosen_parent_until_sealed_hash_is_frozen(
        tmp_path):
    path = tmp_path / "plausible.json"
    path.write_text(json.dumps(direct_aggregate()) + "\n")
    assert COMP.DIRECT_AGGREGATE_SHA256 is None
    with pytest.raises(COMP.ProtocolRefused, match="not frozen yet"):
        COMP.load_direct_parent(path, COMP.sha256(path))


@pytest.mark.parametrize("compatible", [False, True])
def test_v2_parent_preserves_but_does_not_use_standalone_verdict(
        tmp_path, monkeypatch, compatible):
    payload = direct_aggregate(compatible=compatible)
    path, digest = _write_parent(tmp_path, payload, monkeypatch)
    parent = COMP.load_direct_parent(path, digest)
    assert parent["checkpoint_compatible_with_restored_v1"] is compatible
    assert parent["criteria"] == payload["criteria"]
    assert parent["standalone_superiority_required"] is False
    assert parent["matched_null_sanity_required"] is True
    assert parent["exact_accepted_dose_required"] is True
    assert parent["protected_composition_authorized"] is False


@pytest.mark.parametrize(("mutation", "message"), [
    (lambda p: p.__setitem__("schema", "v11-current-revalidation-aggregate-v1"),
     "schema"),
    (lambda p: p.__setitem__("complete", False), "incomplete"),
    (lambda p: p.__setitem__("seed0", 121_000_000), "142M coverage"),
    (lambda p: p.__setitem__("git_sha", "e66b90bc3a50d514472670ea99909add5ea30d19"),
     "git identity"),
    (lambda p: p["runtime_identity"]["digests"].__setitem__(
        "encoder", "1" * 64), "runtime/source"),
    (lambda p: p.__setitem__("encoder_contract", {}), "encoder/v1 refusal"),
    (lambda p: p.__setitem__("invalidated_v1", {}), "encoder/v1 refusal"),
    (lambda p: p["input_shards"].__setitem__(7, p["input_shards"][0]),
     "shard population"),
    (lambda p: p["accepted_dose"].__setitem__("all", False),
     "accepted dose"),
    (lambda p: p.__setitem__("protected_composition_authorized", True),
     "composition/production"),
])
def test_v2_parent_refuses_legacy_or_self_consistent_identity_drift(
        tmp_path, monkeypatch, mutation, message):
    payload = direct_aggregate()
    mutation(payload)
    path, digest = _write_parent(tmp_path, payload, monkeypatch)
    with pytest.raises(COMP.ProtocolRefused, match=message):
        COMP.load_direct_parent(path, digest)


def test_v2_parent_requires_sane_null_and_counter_derived_exact_dose(
        tmp_path, monkeypatch):
    unsane = direct_aggregate(null_sane=False)
    path, digest = _write_parent(tmp_path, unsane, monkeypatch)
    with pytest.raises(COMP.ProtocolRefused, match="matched-null"):
        COMP.load_direct_parent(path, digest)

    wrong_dose = direct_aggregate()
    wrong_dose["counter_totals"]["null"]["arm"]["accepted_worlds"] -= 1
    # Make the stored receipt agree with the tampered total.  The exact N=30
    # counter contract still refuses; merely moving both metadata fields cannot
    # manufacture an admissible parent.
    wrong_dose["accepted_dose"] = COMP._direct_accepted_dose_from_totals(
        wrong_dose["counter_totals"])
    wrong_dose["criteria"] = DIRECT.gate_criteria(
        wrong_dose["stats"], wrong_dose["accepted_dose"])
    wrong_dose["checkpoint_compatible_with_restored_v1"] = \
        wrong_dose["criteria"]["all"]
    path, digest = _write_parent(tmp_path, wrong_dose, monkeypatch)
    with pytest.raises(COMP.ProtocolRefused, match="accepted dose"):
        COMP.load_direct_parent(path, digest)


def test_v2_screen_reopens_exact_direct_parent_and_carries_it_to_confirmation(
        tmp_path, monkeypatch):
    direct_path, direct_sha = _write_parent(
        tmp_path, direct_aggregate(), monkeypatch)
    direct_parent = COMP.load_direct_parent(direct_path, direct_sha)
    s0_parent = {
        "terminal_state": "S0_COMPLETE_SELECT_NONE",
        "champion_policy": "mc-strong",
        "packet_sha256": "a" * 64,
        "closeout_sha256": "b" * 64,
        "phases": {},
        "verification_boundary": "test exact terminal bytes",
    }
    labels = COMP.labels_for("mc-strong")
    stats = {
        "anchor-champion": {
            "a": "anchor", "b": "champion", "mean": 0.30,
            "half_width_95": 0.20, "clusters": 2_048},
        "anchor-random": {
            "a": "anchor", "b": "random", "mean": 0.31,
            "half_width_95": 0.20, "clusters": 2_048},
        "anchor-null": {
            "a": "anchor", "b": "null", "mean": 0.29,
            "half_width_95": 0.20, "clusters": 2_048},
        "null-champion": {
            "a": "null", "b": "champion", "mean": 0.01,
            "half_width_95": 0.10, "clusters": 2_048},
    }
    criteria = COMP.gate_criteria(stats)
    screen = {
        "schema": COMP.AGGREGATE_SCHEMA,
        "phase": "screen",
        "claim": COMP.PROTOCOLS["screen"]["claim"],
        "complete": True,
        "confirmation_authorized": True,
        "production_promotion": False,
        "seed0": 137_000_000,
        "seed_hi": 137_002_047,
        "clusters": 2_048,
        "git_sha": "c" * 40,
        "runtime_identity": {"host": "screen-host", "python": "3.14.6"},
        "champion_policy": "mc-strong",
        "s0_parent": s0_parent,
        "labels": labels,
        "selection_rule": COMP.SELECTION_RULE,
        "checkpoint_sha256": COMP.CHECKPOINT_SHA256,
        "policy_contracts": {
            name: COMP.policy_contract(name) for name in labels.values()},
        "ballots": COMP.arm_ballots(labels.values()),
        "input_shards": [
            {
                "manifest_path": f"screen-{index}.manifest.json",
                "manifest_sha256": COMP.stable_digest(["manifest", index]),
                "records_path": f"screen-{index}.jsonl",
                "records_sha256": COMP.stable_digest(["records", index]),
                "shard_index": index,
            }
            for index in range(COMP.SHARD_COUNT)
        ],
        "stats": stats,
        "criteria": criteria,
        "direct_v11_parent": direct_parent,
        "direct_v11_usage": COMP.DIRECT_USAGE,
    }
    screen_path = tmp_path / "screen-v2.aggregate.json"
    screen_path.write_text(json.dumps(screen, sort_keys=True) + "\n")
    monkeypatch.setattr(COMP, "revalidate_screen_evidence", lambda *_args: [])
    admitted = COMP.load_screen_parent(
        screen_path, COMP.sha256(screen_path), s0_parent)
    assert admitted["direct_v11_parent"] == direct_parent
    assert admitted["confirmation_authorized"] is True

    screen["direct_v11_parent"] = {
        **direct_parent, "accepted_dose_sha256": "not-a-digest"}
    screen_path.write_text(json.dumps(screen, sort_keys=True) + "\n")
    with pytest.raises(COMP.ProtocolRefused, match="identity/sanity"):
        COMP.load_screen_parent(screen_path, COMP.sha256(screen_path), s0_parent)


def test_v2_keeps_s0_raw_reopening_and_champion_validation_code_exact():
    for name in (
        "load_s0_parent",
        "load_bound_screen_inputs",
        "revalidate_screen_evidence",
        "require_screen_execution_identity",
        "record_problems",
        "validate_population",
        "gate_criteria",
        "_parent_args",
    ):
        assert inspect.getsource(getattr(COMP, name)) == \
            inspect.getsource(getattr(V1, name))

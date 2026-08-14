"""Frozen live-decision replay asset and semantic benchmark contracts."""
from __future__ import annotations

import copy
import math
import random

import pytest

from scripts import report_lcb_replay_benchmark as bench


ASSET = (
    bench.SERVER / "tests" / "data" / "report_lcb_caxi_replay.v1.b85"
)
AIR_RESULT = (
    bench.SERVER / "tests" / "data" /
    "report_lcb_caxi_replay.air-9acafb1.result.json"
)
EXPECTED_PAYLOAD_SHA256 = (
    "91354e3391a1ccbd65d758d011416f135ba8b212aacec40195c7a03fc3e70a40"
)
EXPECTED_SOURCE_SHA256 = (
    "3ed2d1fbb80733671663aef4dd81acdb34bb9a40042a84474422a5575c63af3a"
)
EXPECTED_AIR_RESULT_SHA256 = (
    "2623def50a91d96a9dc97bd63139ef28532c2ee389c1a0cc9b4631842c6dcd57"
)
CURRENT_MCBOT_SOURCE_SHA256 = (
    "2e5fff35903bb9a9c36ac4b7e2af953fca982590126ded0bb012a0b1e70d6888"
)


def _asset() -> dict:
    return bench._load(ASSET)


def _first_benchmark(asset: dict) -> dict:
    return next(
        play["benchmark"]
        for round_asset in asset["rounds"]
        for play in round_asset["plays"]
        if "benchmark" in play
    )


def test_frozen_asset_identity_inventory_and_sanitization():
    asset = _asset()
    assert bench.asset_problems(asset) == []
    assert asset["payload_sha256"] == EXPECTED_PAYLOAD_SHA256
    assert asset["source"] == {
        "mcbot_sha256": bench.EXPECTED_MCBOT_SHA256,
        "searched_decisions": 109,
        "sha256": EXPECTED_SOURCE_SHA256,
    }
    assert asset["selection"]["target"] == 100
    assert asset["selection"]["selected"]["decisions"] == 100
    assert len(asset["selection"]["selected_ordinals"]) == 100
    assert asset["post_rng_witness_counts"] == {
        "logged-next-pre": 81,
        "source-replay-derived": 19,
    }
    assert [item["round"] for item in asset["rounds"]] == [1, 2, 3]
    assert not (bench.BANNED_ASSET_KEYS & set(bench._walk_keys(asset)))


def test_frozen_air_result_passes_the_full_exact_latency_gate():
    result = bench._load(AIR_RESULT)
    assert bench.sha256(AIR_RESULT) == EXPECTED_AIR_RESULT_SHA256
    assert result["schema"] == bench.RESULT_SCHEMA
    assert result["asset_payload_sha256"] == EXPECTED_PAYLOAD_SHA256
    assert result["decisions"] == 100
    assert result["semantic_mismatches"] == []
    assert result["exact_semantic_replay"] is True
    assert result["gate"] == {
        "all": True,
        "compiled_fast_active": True,
        "decisions_at_least_100": True,
        "identical_replay": True,
        "max_le_8_0": True,
        "p50_le_1_5": True,
        "p95_le_4_0": True,
    }
    assert result["runtime"]["git_head"] \
        == "9acafb1bdcf69c99fa1ff455b0e881e65fd09977"
    assert result["runtime"]["git_dirty"] is False
    assert result["runtime"]["python"] == "3.14.6"
    assert result["runtime"]["fast_active"] is True
    assert result["timing"]["search"]["p50"] < 0.18
    assert result["timing"]["search"]["p95"] < 0.36
    assert result["timing"]["search"]["max"] < 0.43
    assert len(result["decisions_detail"]) == 100


def test_rng_state_encoding_is_lossless_and_digest_addressed():
    state = random.Random(912_345).getstate()
    encoded = bench.encode_rng_state(state)
    decoded = bench.decode_rng_state(encoded)
    assert decoded == list((state[0], list(state[1]), state[2]))
    assert bench.rng_state_ref(encoded) == bench.rng_state_ref(
        bench.encode_rng_state(decoded))
    rng = random.Random()
    rng.setstate((decoded[0], tuple(decoded[1]), decoded[2]))
    expected = random.Random()
    expected.setstate(state)
    assert [rng.random() for _ in range(10)] == [
        expected.random() for _ in range(10)
    ]


def test_semantic_projection_normalizes_only_known_volatile_fields():
    stored = copy.deepcopy(_first_benchmark(_asset())["record"])
    cumulative = copy.deepcopy(stored)
    delta = stored["sampler_counters"]
    cumulative["sampler_counters"] = {
        "before": {key: 1000 for key in delta},
        "after": {key: 1000 + value for key, value in delta.items()},
        "delta": delta,
    }
    cumulative["ballot"]["digest"] = "build-specific-compiled-byte-digest"
    cumulative["search_secs"] = 999.0
    cumulative["code"] = {"mcbot_sha256": bench.EXPECTED_MCBOT_SHA256}
    assert bench.semantic_record(cumulative) == stored

    cumulative["unclassified_new_field"] = True
    with pytest.raises(bench.ReplayRefused, match="unclassified"):
        bench.semantic_record(cumulative)


def test_semantic_comparison_allows_only_tiny_float_roundoff():
    expected = {"x": 1.0, "nested": [0.25, "same"]}
    one_ulp = {"x": math.nextafter(1.0, 2.0),
               "nested": [math.nextafter(0.25, 1.0), "same"]}
    assert bench.semantic_differences(expected, one_ulp) == []
    assert bench.semantic_differences(expected, {**one_ulp, "x": 1.000001}) \
        == ["$.x"]
    assert bench.semantic_differences(expected, {**one_ulp, "extra": 1}) \
        == ["$.__keys__"]

    def step(value: float, toward: float, count: int) -> float:
        for _ in range(count):
            value = math.nextafter(value, toward)
        return value

    for value, toward in ((0.25, 1.0), (-0.25, -1.0)):
        assert bench.semantic_differences(
            {"x": value}, {"x": step(value, toward, 8)}) == []
        assert bench.semantic_differences(
            {"x": value}, {"x": step(value, toward, 9)}) == ["$.x"]


def test_asset_validator_rejects_identity_and_play_mutations():
    asset = _asset()
    asset["rounds"][0]["players"] = ["private identity"]
    asset["payload_sha256"] = bench.stable_digest({
        key: value for key, value in asset.items() if key != "payload_sha256"
    })
    assert any("sensitive" in problem for problem in bench.asset_problems(asset))

    asset = _asset()
    first_play = next(
        play for round_asset in asset["rounds"]
        for play in round_asset["plays"] if "benchmark" in play
    )
    first_play["benchmark"]["record"]["played"] = ["BJ"]
    asset["payload_sha256"] = bench.stable_digest({
        key: value for key, value in asset.items() if key != "payload_sha256"
    })
    assert "stored decision/play mismatch" in bench.asset_problems(asset)


def test_first_frozen_decision_refuses_only_current_source_identity_drift():
    result = bench.replay_asset(_asset(), limit=1, emit_progress=False)
    assert result["decisions"] == 1
    # This historical asset deliberately pins the old MCBot source. The
    # optimized implementation must not weaken that gate or relabel itself as
    # the historical source. Exact equality to this sole mismatch also proves
    # the played cards did not drift; a play mismatch would add another row.
    assert result["semantic_mismatches"] == [{
        "round": 1,
        "ply": 2,
        "error": (
            "record: ReplayRefused: live decision MCBot source identity "
            "drifted"
        ),
    }]
    assert result["exact_semantic_replay"] is False
    assert result["runtime"]["fast_active"] is bench.fast_active()
    assert result["runtime"]["mcbot_source_sha256"] \
        == CURRENT_MCBOT_SOURCE_SHA256
    assert CURRENT_MCBOT_SOURCE_SHA256 != bench.EXPECTED_MCBOT_SHA256
    assert all(len(result["runtime"][key]) == 64 for key in (
        "benchmark_source_sha256", "scheduler_source_sha256",
        "mcbot_source_sha256",
    ))
    # A limited smoke replay is intentionally not allowed to satisfy the
    # production timing gate.
    assert result["gate"]["decisions_at_least_100"] is False
    assert result["gate"]["all"] is False

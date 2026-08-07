"""Frozen live-decision replay asset and semantic benchmark contracts."""
from __future__ import annotations

import copy
import random

import pytest

from scripts import report_lcb_replay_benchmark as bench


ASSET = (
    bench.SERVER / "tests" / "data" / "report_lcb_caxi_replay.v1.b85"
)
EXPECTED_PAYLOAD_SHA256 = (
    "1adf81658712ae1c3a0c3677cb8735b9981abfc359bbc5b5598c42d9abdc7ec4"
)
EXPECTED_SOURCE_SHA256 = (
    "3ed2d1fbb80733671663aef4dd81acdb34bb9a40042a84474422a5575c63af3a"
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
    assert [item["round"] for item in asset["rounds"]] == [1, 2, 3]
    assert not (bench.BANNED_ASSET_KEYS & set(bench._walk_keys(asset)))


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


def test_first_frozen_decision_replays_cards_record_and_rng_exactly():
    result = bench.replay_asset(_asset(), limit=1, emit_progress=False)
    assert result["decisions"] == 1
    assert result["semantic_mismatches"] == []
    assert result["exact_semantic_replay"] is True
    assert result["runtime"]["fast_active"] is bench.fast_active()
    # A limited smoke replay is intentionally not allowed to satisfy the
    # production timing gate.
    assert result["gate"]["decisions_at_least_100"] is False
    assert result["gate"]["all"] is False

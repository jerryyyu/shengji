"""Executable protocol boundary for the S3b mechanics challenge."""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import s3b_endgame_challenge as S3B                              # noqa: E402
from shengji.ai.endgame import exhaustive_legal_actions          # noqa: E402
from shengji.engine import combos, fast                          # noqa: E402


ASSET = os.path.join(ROOT, "tests", "data",
                     "s3b_endgame_challenge.v1.json")


def _runtime():
    return {
        "git_sha": "a" * 40,
        "tree_clean": True,
        "host": "test-host",
        "python": sys.version.split()[0],
        "fast_engine": True,
        "require_voids": True,
        "experimental_sampler_flags": [],
        "source_sha256": {"runner": "b" * 64,
                          "state_asset": S3B.EXPECTED_STATE_ASSET_SHA256},
    }


@pytest.fixture(scope="module")
def frozen_asset():
    asset, digest = S3B.load_state_asset(
        ASSET, S3B.EXPECTED_STATE_ASSET_SHA256)
    return asset, digest


@pytest.fixture(scope="module")
def challenge_records(frozen_asset):
    asset, _ = frozen_asset
    return [S3B.run_state(state) for state in asset["states"]]


@pytest.fixture(scope="module")
def passing_shards(frozen_asset, challenge_records):
    asset, digest = frozen_asset
    by_id = {record["state_id"]: record for record in challenge_records}
    return [S3B.build_shard_payload(
        asset, digest, _runtime(), index,
        [copy.deepcopy(by_id[asset["states"][index]["state_id"]])])
        for index in range(S3B.SHARD_COUNT)]


def test_frozen_asset_replays_exact_states_and_candidates(frozen_asset):
    asset, digest = frozen_asset
    assert digest == S3B.sha256_file(ASSET)
    assert digest == S3B.EXPECTED_STATE_ASSET_SHA256
    assert asset["protocol"] == S3B.protocol_contract()
    assert asset["protocol"]["full_game_reference"] is None
    assert asset["protocol"]["strength_evidence"] is False
    assert asset["protocol"]["promotion"] is False
    assert S3B.CLAIM == (
        "exact perfect-information oracle inside a sampled determinization; "
        "not exact imperfect-information Shengji")

    seen_tags = set()
    for state in asset["states"]:
        rnd = S3B.replay_state(state)
        assert max(len(hand) for hand in rnd.hands) <= S3B.MAX_HAND_CARDS
        assert S3B.stable_digest(S3B.round_snapshot(rnd)) == \
            state["expected_state_sha256"]
        candidates = exhaustive_legal_actions(
            rnd, rnd.turn, max_hand_cards=S3B.MAX_HAND_CARDS)
        assert len(candidates) == state["expected_candidate_count"]
        assert S3B.stable_digest(candidates) == \
            state["expected_candidates_sha256"]
        seen_tags.update(state["tags"])
    assert {"attacker", "defender", "lead", "follow", "pair-lead",
            "attempted-throws"} <= seen_tags


def test_real_challenge_records_close_exact_work_contract(
        frozen_asset, challenge_records):
    asset, _ = frozen_asset
    summary = S3B.summarize_records(challenge_records)
    expected_work = sum(state["expected_candidate_count"]
                        * S3B.WORLDS_PER_STATE for state in asset["states"])
    assert summary["problems"] == []
    assert summary["work"] == {
        "states": 4,
        "worlds": 16,
        "candidate_world_work_planned": expected_work,
        "candidate_world_work_completed": expected_work,
        "max_session_nodes": summary["work"]["max_session_nodes"],
    }
    assert summary["work"]["max_session_nodes"] <= \
        S3B.MAX_NODES_PER_WORLD
    assert summary["exact"]["attempts"] == expected_work
    assert summary["exact"]["successes"] == expected_work
    assert summary["exact"]["sessions"] == 16
    assert summary["exact"]["refusals"] == 0
    assert summary["exact"]["budget_overflows"] == 0
    assert summary["exact"]["nodes"] > 0
    assert summary["exact"]["cache_hits"] > 0
    for record in challenge_records:
        assert record["problems"] == []
        for world in record["worlds"]:
            assert world["problems"] == []
            assert world["session"]["frontiers"] == \
                world["candidate_count"]
            assert world["session"]["max_hand_cards"] == 4
            assert world["session"]["max_nodes"] == 250_000
            assert world["session"]["nodes"] <= \
                S3B.MAX_NODES_PER_WORLD


def test_each_valid_shard_is_nonterminal_and_self_consistent(
        frozen_asset, passing_shards):
    asset, digest = frozen_asset
    for index, shard in enumerate(passing_shards):
        assert shard["status"] == "SHARD_PASS"
        assert shard["shard_pass"] is True
        assert shard["challenge_pass"] is False
        assert shard["shard"]["index"] == index
        assert S3B.validate_shard_payload(
            shard, asset, digest, _runtime()) == []


def test_only_complete_four_shard_population_can_claim_terminal_pass(
        frozen_asset, passing_shards):
    asset, digest = frozen_asset
    hashes = [S3B.stable_digest(shard) for shard in passing_shards]
    aggregate = S3B.build_aggregate_payload(
        passing_shards, hashes, asset, digest, _runtime())
    assert aggregate["status"] == "PASS"
    assert aggregate["challenge_pass"] is True
    assert aggregate["problems"] == []
    assert aggregate["exact"]["refusals"] == 0
    assert aggregate["exact"]["budget_overflows"] == 0
    assert aggregate["exact"]["attempts"] == \
        aggregate["work"]["candidate_world_work_planned"]
    assert aggregate["exact"]["successes"] == \
        aggregate["work"]["candidate_world_work_completed"]
    assert aggregate["exact"]["sessions"] == aggregate["work"]["worlds"]
    assert aggregate["full_game_reference"] is None
    assert aggregate["strength_evidence"] is False
    assert aggregate["promotion"] is False

    missing = S3B.build_aggregate_payload(
        passing_shards[:-1], hashes[:-1], asset, digest, _runtime())
    assert missing["status"] == "HOLD"
    assert missing["challenge_pass"] is False
    assert any("shard index" in problem or "coverage" in problem
               for problem in missing["problems"])


def test_refusal_or_cumulative_cap_overflow_forces_hold(
        frozen_asset, passing_shards):
    asset, digest = frozen_asset
    broken = copy.deepcopy(passing_shards)
    world = broken[0]["records"][0]["worlds"][0]
    world["exact"]["refusals"] = 1
    world["exact"]["budget_overflows"] = 1
    world["session"]["nodes"] = S3B.MAX_NODES_PER_WORLD + 1
    world["problems"] = S3B.world_problems(world)
    state = broken[0]["records"][0]
    state["problems"] = [
        f"world {world['world_seed']}: {problem}"
        for problem in world["problems"]]
    broken[0] = S3B.build_shard_payload(
        asset, digest, _runtime(), 0, broken[0]["records"])
    aggregate = S3B.build_aggregate_payload(
        broken, [S3B.stable_digest(shard) for shard in broken],
        asset, digest, _runtime())
    assert aggregate["status"] == "HOLD"
    assert aggregate["challenge_pass"] is False
    assert aggregate["exact"]["refusals"] == 1
    assert aggregate["exact"]["budget_overflows"] == 1
    assert any("overflow" in problem or "over-cap" in problem
               for problem in aggregate["problems"])


def test_aggregate_reopens_frozen_world_bindings_after_summary_rewrite(
        frozen_asset, passing_shards):
    asset, digest = frozen_asset
    broken = copy.deepcopy(passing_shards)
    records = broken[0]["records"]
    records[0]["worlds"][0]["world_sha256"] = "0" * 64

    # Rebuild every shard-level digest, total and PASS bit.  The independent
    # aggregate must still reject bytes that no longer match the frozen asset.
    broken[0] = S3B.build_shard_payload(
        asset, digest, _runtime(), 0, records)
    assert broken[0]["status"] == "SHARD_PASS"
    assert broken[0]["problems"] == []

    aggregate = S3B.build_aggregate_payload(
        broken, [S3B.stable_digest(shard) for shard in broken],
        asset, digest, _runtime())
    assert aggregate["status"] == "HOLD"
    assert aggregate["challenge_pass"] is False
    assert any("resolved digest" in problem
               for problem in aggregate["problems"])


def test_asset_and_shard_drift_refuse_before_a_run(frozen_asset, tmp_path):
    asset, _ = frozen_asset
    with pytest.raises(S3B.ChallengeProtocolError, match="frozen protocol"):
        S3B.load_state_asset(ASSET, "0" * 64)

    drifted = copy.deepcopy(asset)
    drifted["protocol"]["max_hand_cards"] = 5
    assert "embedded protocol contract" in S3B.asset_problems(drifted)
    with pytest.raises(S3B.ChallengeProtocolError, match="shard count"):
        S3B.assigned_states(asset, 0, 2)
    with pytest.raises(S3B.ChallengeProtocolError, match="shard index"):
        S3B.assigned_states(asset, 4, 4)


def test_atomic_output_is_exclusive_and_complete(tmp_path):
    out = str(tmp_path / "challenge.json")
    payload = {"schema": "test", "complete": True}
    S3B.write_exclusive_atomic(out, payload)
    assert json.load(open(out)) == payload
    assert not os.path.exists(out + ".partial")
    with pytest.raises(S3B.ChallengeProtocolError, match="overwrite"):
        S3B.write_exclusive_atomic(out, payload)


@pytest.mark.parametrize("missing", ["SHENGJI_FAST", "SHENGJI_REQUIRE_VOIDS"])
def test_runtime_refuses_missing_strict_flag(monkeypatch, missing):
    monkeypatch.setenv("SHENGJI_FAST", "1")
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.delenv(missing, raising=False)
    with pytest.raises(S3B.ChallengeProtocolError, match=missing):
        S3B.runtime_contract(ASSET)


def test_runtime_refuses_experimental_sampler_flags(monkeypatch):
    monkeypatch.setenv("SHENGJI_FAST", "1")
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setenv(S3B.SAMPLER_FLAGS[0], "1")
    with pytest.raises(S3B.ChallengeProtocolError, match="sampler flags"):
        S3B.runtime_contract(ASSET)


@pytest.mark.skipif(
    not fast.HAVE_FAST or combos.decompose is not fast.decompose,
    reason="compiled engine inactive; strict good-runtime case is compiled-only")
def test_good_runtime_binds_clean_compiled_sources(monkeypatch):
    monkeypatch.setenv("SHENGJI_FAST", "1")
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    for name in S3B.SAMPLER_FLAGS:
        monkeypatch.delenv(name, raising=False)

    def fake_git(*args):
        return "" if args == ("status", "--porcelain") else "c" * 40

    monkeypatch.setattr(S3B, "git_output", fake_git)
    runtime = S3B.runtime_contract(ASSET)
    assert runtime["tree_clean"] is True
    assert runtime["fast_engine"] is True
    assert runtime["require_voids"] is True
    assert runtime["experimental_sampler_flags"] == []
    required = {"runner", "state_asset", "exact_solver", "mcbot", "memory",
                "heuristic", "game", "round", "legal", "combos", "cards",
                "fast_router", "compiled_engine"}
    assert set(runtime["source_sha256"]) == required
    assert all(len(value) == 64 for value in runtime["source_sha256"].values())


@pytest.mark.skipif(
    not fast.HAVE_FAST or combos.decompose is not fast.decompose,
    reason="compiled engine inactive; clean-tree case is compiled-only")
def test_runtime_refuses_dirty_tree(monkeypatch):
    monkeypatch.setenv("SHENGJI_FAST", "1")
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    for name in S3B.SAMPLER_FLAGS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        S3B, "git_output",
        lambda *args: " M shengji/ai/endgame.py"
        if args == ("status", "--porcelain") else "d" * 40)
    with pytest.raises(S3B.ChallengeProtocolError, match="dirty tree"):
        S3B.runtime_contract(ASSET)


def test_run_command_writes_one_exclusive_nonterminal_shard(
        monkeypatch, tmp_path, frozen_asset):
    out = str(tmp_path / "shard.json")
    monkeypatch.setattr(S3B, "runtime_contract", lambda _path: _runtime())
    args = argparse.Namespace(
        states=ASSET,
        expected_state_asset_sha256=S3B.EXPECTED_STATE_ASSET_SHA256,
        shard_index=2,
        shard_count=S3B.SHARD_COUNT,
        out=out,
    )
    payload = S3B.run_command(args)
    assert payload["status"] == "SHARD_PASS"
    assert payload["challenge_pass"] is False
    assert json.load(open(out)) == payload
    with pytest.raises(S3B.ChallengeProtocolError, match="overwrite"):
        S3B.run_command(args)

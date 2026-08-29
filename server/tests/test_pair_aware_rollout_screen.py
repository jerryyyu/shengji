"""Focused contracts for the powered pair-aware whole-round screen."""
from __future__ import annotations

import math
import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import pair_aware_rollout_screen as SCREEN  # noqa: E402


def test_fixed_screen_is_powered_and_within_reviewed_capacity():
    planning = SCREEN.planning_contract(503.0909939999692)
    assert planning["clusters"] == 7168
    assert planning["clusters_per_shard"] == 896
    assert planning["minimum_detectable_effect_80pct"] < 0.047
    assert planning["power_at_target_effect"] > 0.84
    assert planning["projected_fleet_hours"] < 501
    assert planning["projected_max_shard_hours"] < 63
    assert planning["within_reviewed_capacity"] is True


def test_capacity_result_is_hash_pinned_but_cannot_authorize_execution(tmp_path):
    assert SCREEN.sha256(SCREEN.CAPACITY_RESULT_PATH) == (
        SCREEN.CAPACITY_RESULT_SHA256)
    with pytest.raises(SCREEN.ScreenRefused, match="review"):
        SCREEN.capacity_evidence(
            result_path=SCREEN.CAPACITY_RESULT_PATH,
            capacity_review_record=tmp_path / "missing-review.md")


def test_packet_review_claim_is_bounded_to_one_screen():
    packet = {"git": "a" * 40}
    claim = SCREEN.packet_review_claim(packet, "b" * 64)
    assert claim["one_screen_execution_authorized"] is True
    assert claim["retry_or_extension_authorized"] is False
    assert claim["strength_claim"] is False
    assert claim["production_deployment"] is False


def test_paired_stats_and_screen_gate_use_level_utility():
    stats = SCREEN.paired_stats([1.0, 1.0, 0.0, 2.0])
    assert stats["n"] == 4
    assert stats["mean"] == 1.0
    assert stats["wins"] == 3
    assert stats["ties"] == 1
    assert math.isfinite(stats["lcb_one_sided_95"])


def test_metric_pair_validation_refuses_bools_and_out_of_bounds():
    assert SCREEN._integer_pair([1, -101], range(-101, 102))
    assert not SCREEN._integer_pair([True, 0], range(-101, 102))
    assert not SCREEN._integer_pair([102, 0], range(-101, 102))


def test_cluster_count_divides_exactly_across_shards():
    assert SCREEN.SCREEN_CLUSTERS == (
        SCREEN.SHARD_COUNT * SCREEN.CLUSTERS_PER_SHARD)
    starts = [index * SCREEN.CLUSTERS_PER_SHARD
              for index in range(SCREEN.SHARD_COUNT)]
    assert starts == [0, 896, 1792, 2688, 3584, 4480, 5376, 6272]


def test_reviewed_capacity_can_freeze_design_but_not_execution(
        tmp_path, monkeypatch):
    result = json.loads(SCREEN.CAPACITY_RESULT_PATH.read_bytes())
    claim = SCREEN.CAPACITY.capacity_review_claim(
        result=result, result_sha256=SCREEN.CAPACITY_RESULT_SHA256,
        packet_sha256=SCREEN.CAPACITY_PACKET_SHA256)
    review = tmp_path / "capacity-review.md"
    review.write_text(
        SCREEN.CAPACITY.CAPACITY_REVIEW_PREFIX
        + json.dumps(claim, sort_keys=True, separators=(",", ":")) + "\n")
    monkeypatch.setattr(
        SCREEN.CAPACITY, "require_air_runtime", lambda: {"exact": "air"})
    monkeypatch.setattr(SCREEN, "source_sha256s", lambda: {"screen": "x"})
    monkeypatch.setattr(
        SCREEN.CAPACITY, "policy_contracts", lambda: {"exact": "arms"})
    packet = SCREEN.packet_payload(
        expected_git=SCREEN.git("rev-parse", "HEAD"),
        result_path=SCREEN.CAPACITY_RESULT_PATH,
        capacity_review_record=review)
    assert packet["planning"]["within_reviewed_capacity"] is True
    assert packet["authority"] == {
        "screen_execution_authorized": False,
        "aggregate_execution_authorized": False,
        "confirmation_packet_design_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
    }


def _pair_telemetry(mode):
    return SCREEN.CORE.empty_pair_aware_telemetry(mode=mode)


def _plain_counters():
    return dict(SCREEN.CORE.counters([]))


def _counts(clusters):
    value = {}
    for label, mode in (("treatment", "treatment"),
                        ("matched_null", "matched_null"),
                        ("champion", "off")):
        value[label] = {
            "records": 2 * clusters,
            "arm": _plain_counters(),
            "opp": _plain_counters(),
            "arm_pair": _pair_telemetry(mode),
            "opp_pair": _pair_telemetry("off"),
        }
    return value


def _dose(role):
    return {
        "shared_prefix_plays": 1,
        "root_action_changed": True,
        "change_play_index": 1,
        "change_phase": "early",
        "change_role": role,
    }


def _shard(packet, packet_sha, receipt_sha, index, treatment_utility, role):
    cluster_index = index
    row = {
        "cluster_index": cluster_index,
        "seed": SCREEN.SCREEN_SEED0 + SCREEN.STREAM_STRIDE * cluster_index,
        "level_utility": {
            "treatment": list(treatment_utility),
            "matched_null": [0, 0],
            "champion": [0, 0],
        },
        "won": {
            "treatment": [1, 1],
            "matched_null": [0, 0],
            "champion": [0, 0],
        },
        "natural_dose": [_dose(role), _dose(role)],
    }
    value = {
        "schema": SCREEN.SHARD_SCHEMA,
        "run_id": SCREEN.RUN_ID,
        "git": packet["git"],
        "packet_sha256": packet_sha,
        "packet_internal_sha256": packet["internal_sha256"],
        "receipt_sha256": receipt_sha,
        "shard_index": index,
        "cluster_index_start": cluster_index,
        "clusters": 1,
        "seed0": row["seed"],
        "stream_stride": SCREEN.STREAM_STRIDE,
        "elapsed_seconds": 1.0,
        "cluster_rows": [row],
        "counts": _counts(1),
        "natural_dose": SCREEN._dose_summary([row]),
        "exact_work_complete": True,
        "aggregate_execution_authorized": False,
        "strength_claim": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    value["internal_sha256"] = SCREEN.stable_digest(value)
    return value


def test_aggregate_gate_uses_level_utility_and_both_roles(monkeypatch):
    monkeypatch.setattr(SCREEN, "SCREEN_CLUSTERS", 2)
    monkeypatch.setattr(SCREEN, "SHARD_COUNT", 2)
    monkeypatch.setattr(SCREEN, "CLUSTERS_PER_SHARD", 1)
    packet = {"git": "a" * 40, "internal_sha256": "b" * 64}
    packet_sha = "c" * 64
    receipt_sha = "d" * 64
    shards = [
        _shard(packet, packet_sha, receipt_sha, 0, [1, 1], "attacker"),
        _shard(packet, packet_sha, receipt_sha, 1, [1, 1], "defender"),
    ]
    value = SCREEN.aggregate_payload(
        packet=packet, packet_sha256=packet_sha,
        receipt_sha256=receipt_sha, shard_values=shards,
        shard_sha256s=["e" * 64, "f" * 64],
        supervisor_final_sha256="1" * 64,
        supervisor_review={"sha256": "2" * 64, "marker": "review"})
    assert value["status"] == "PASS_SCREEN"
    assert value["screen_passed"] is True
    assert value["primary_level_utility"][
        "treatment_minus_champion"]["mean"] == 1.0
    assert value["confirmation_packet_design_authorized"] is True
    assert value["strength_claim"] is False


def test_aggregate_refuses_matched_null_champion_drift(monkeypatch):
    monkeypatch.setattr(SCREEN, "SCREEN_CLUSTERS", 2)
    monkeypatch.setattr(SCREEN, "SHARD_COUNT", 2)
    monkeypatch.setattr(SCREEN, "CLUSTERS_PER_SHARD", 1)
    packet = {"git": "a" * 40, "internal_sha256": "b" * 64}
    shards = [
        _shard(packet, "c" * 64, "d" * 64, 0, [1, 1], "attacker"),
        _shard(packet, "c" * 64, "d" * 64, 1, [1, 1], "defender"),
    ]
    shards[0]["cluster_rows"][0]["level_utility"]["matched_null"] = [1, 0]
    shards[0]["internal_sha256"] = SCREEN.stable_digest({
        key: item for key, item in shards[0].items()
        if key != "internal_sha256"
    })
    with pytest.raises(SCREEN.ScreenRefused, match="cluster-row drift"):
        SCREEN.aggregate_payload(
            packet=packet, packet_sha256="c" * 64,
            receipt_sha256="d" * 64, shard_values=shards,
            shard_sha256s=["e" * 64, "f" * 64],
            supervisor_final_sha256="1" * 64,
            supervisor_review={"sha256": "2" * 64, "marker": "review"})

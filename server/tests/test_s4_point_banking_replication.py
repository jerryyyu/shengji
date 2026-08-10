"""Protocol tests for the cheaper fixed-size S4 Air replication."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import s4_point_banking_duel as DUEL  # noqa: E402
import s4_point_banking_replication as REP  # noqa: E402


def _telemetry(mode: str, *, role: str | None = None) -> dict:
    values = DUEL.empty_point_banking_telemetry(mode=mode)
    if mode == "off":
        return values
    values.update({
        "follow_calls": 1,
        "single_follow_calls": 1,
        "candidate_checks": 2,
        "legal_winning_actions": 2,
        "opportunities": 1,
        "triggers": 1,
        "changes": int(mode == "treatment"),
        "matched_noops": int(mode == "matched_null"),
        "attacker_triggers": int(role == "attacker"),
        "defender_triggers": int(role == "defender"),
        "point_gain": 5,
    })
    return values


def _counter(mode: str, *, role: str | None = None) -> dict:
    values = DUEL.counters([])
    values["point_banking"] = _telemetry(mode, role=role)
    return values


def _record(label: str, seed: int, flip: int, utility: int,
            role: str) -> dict:
    mode = {"treatment": "treatment", "matched_null": "matched_null",
            "champion": "off"}[label]
    policy_team = 0 if flip == 0 else 1
    winner_team = policy_team if utility > 0 else 1 - policy_team
    banker = 0
    gain = abs(utility)
    if winner_team == banker % 2:
        attacker_points = {1: 50, 2: 20, 3: 0}[gain]
    else:
        attacker_points = 80 + 40 * gain
    expected_winner, level_change = DUEL.expected_round_outcome(
        banker=banker, attacker_points=attacker_points)
    assert expected_winner == winner_team and level_change == gain
    return {
        "run": REP.RUN_ID,
        "label": label,
        "policy": DUEL.LABELS[label],
        "opponent": DUEL.OPPONENT,
        "seed": seed,
        "flip": flip,
        "banker": banker,
        "attacker_points": attacker_points,
        "winner_team": winner_team,
        "level_change": level_change,
        "won": int(utility > 0),
        "level_utility": utility,
        "arm": _counter(mode, role=role),
        "opp": _counter("off"),
    }


def _records(monkeypatch, *, treatment_utility: int = 2,
             corrupt_null: bool = False) -> list[dict]:
    monkeypatch.setattr(REP, "CLUSTERS", 4)
    monkeypatch.setattr(REP, "SHARD_COUNT", 2)
    monkeypatch.setattr(REP, "CLUSTERS_PER_SHARD", 2)
    monkeypatch.setattr(REP, "NULL_SENTINEL_STRIDE", 2)
    monkeypatch.setattr(REP, "NULL_SENTINEL_CLUSTERS", 2)
    records = []
    for cluster_index in range(REP.CLUSTERS):
        seed = REP.cluster_seed(cluster_index)
        role = "attacker" if cluster_index % 2 == 0 else "defender"
        for label in REP.labels_for_cluster(cluster_index):
            utility = treatment_utility if label == "treatment" else 1
            for flip in (0, 1):
                row = _record(label, seed, flip, utility, role)
                if (corrupt_null and label == "matched_null"
                        and cluster_index == 1 and flip == 1):
                    # 50 and 55 are the same bracket but not the same outcome.
                    row["attacker_points"] = 55
                records.append(row)
    return records


def test_schedule_is_fixed_smaller_and_balanced():
    assert REP.CLUSTERS == 2_048
    assert REP.NULL_SENTINEL_CLUSTERS == 256
    assert REP.schedule()["records"] == 8_704
    assert len(REP.sentinel_indexes()) == 256
    assert [sum(REP.is_null_sentinel(index)
                for index in REP.shard_indexes(shard))
            for shard in range(REP.SHARD_COUNT)] == [32] * 8
    assert all(REP.labels_for_cluster(index) ==
               ("treatment", "matched_null", "champion")
               for index in REP.sentinel_indexes())


def test_new_preflight_and_replication_streams_are_globally_disjoint():
    assert REP.stream_problems() == []


def test_record_validation_reuses_exact_s4_semantics():
    row = _record("treatment", REP.SEED0, 0, 2, "attacker")
    assert REP.record_problems(
        row, expected_seed=REP.SEED0, expected_label="treatment",
        expected_flip=0) == []
    row["run"] = "wrong"
    assert "record identity" in REP.record_problems(
        row, expected_seed=REP.SEED0, expected_label="treatment",
        expected_flip=0)


def test_fixed_replication_can_confirm_or_select_none(monkeypatch):
    records = _records(monkeypatch)
    result = REP.build_aggregate(
        shards=[{"records": records}], inputs=[{"sha256": "a" * 64}],
        parent={"champion_policy": DUEL.CHAMPION}, runtime={"frozen": True},
        screen_parent={"status": "AUTHORIZE_CONFIRM_PACKET_REVIEW"})
    assert result["status"] == "CONFIRM_S4_POINT_BANKING_REPLICATION"
    assert result["strength_claim"] is True
    assert result["stats"]["treatment_champion"]["clusters"] == 4
    assert result["stats"]["treatment_champion"]["lcb95"] > 0
    assert all(result["criteria"].values())

    rejected_records = _records(monkeypatch, treatment_utility=-1)
    rejected = REP.build_aggregate(
        shards=[{"records": rejected_records}],
        inputs=[{"sha256": "b" * 64}],
        parent={"champion_policy": DUEL.CHAMPION}, runtime={"frozen": True},
        screen_parent={"status": "AUTHORIZE_CONFIRM_PACKET_REVIEW"})
    assert rejected["status"] == "SELECT_NONE"
    assert rejected["strength_claim"] is False
    assert rejected["criteria"]["treatment_champion_lcb_gt_zero"] is False


def test_null_sentinel_checks_raw_outcome_not_only_utility(monkeypatch):
    records = _records(monkeypatch, corrupt_null=True)
    result = REP.build_aggregate(
        shards=[{"records": records}], inputs=[{"sha256": "c" * 64}],
        parent={"champion_policy": DUEL.CHAMPION}, runtime={},
        screen_parent={"status": "AUTHORIZE_CONFIRM_PACKET_REVIEW"})
    assert result["status"] == "SELECT_NONE"
    assert result["criteria"][
        "matched_null_champion_sentinel_exact_outcomes"] is False


def test_null_never_reenters_nonsentinel_clusters(monkeypatch):
    monkeypatch.setattr(REP, "CLUSTERS", 16)
    monkeypatch.setattr(REP, "SHARD_COUNT", 2)
    monkeypatch.setattr(REP, "NULL_SENTINEL_STRIDE", 4)
    sentinels = set(REP.sentinel_indexes())
    assert sentinels
    for index in range(REP.CLUSTERS):
        assert ("matched_null" in REP.labels_for_cluster(index)) == \
            (index in sentinels)


def test_preflight_is_score_free_and_has_finite_caps():
    assert REP.PREFLIGHT_CLUSTERS == 8
    assert REP.THROUGHPUT_SAFETY_FACTOR == 2.0
    assert REP.MAX_PROJECTED_FLEET_HOURS == 100.0
    assert REP.MAX_PROJECTED_SHARD_HOURS == 15.0
    assert "fixed-look" in REP.CLAIM_BOUNDARY
    assert "no retry or extension" in REP.SELECTION_RULE.lower()


def test_exclusive_publication_refuses_collisions(tmp_path):
    out = tmp_path / "artifact.json"
    REP.write_exclusive(out, {"first": True})
    with pytest.raises(REP.ProtocolRefused, match="refusing to overwrite"):
        REP.write_exclusive(out, {"second": True})

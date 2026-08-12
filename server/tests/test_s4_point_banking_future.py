"""Protocol tests for the future-only sequential S4 runtime."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import s4_point_banking_duel as DUEL  # noqa: E402
import s4_point_banking_future as CORE  # noqa: E402


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
    policy_team = flip
    winner_team = policy_team if utility > 0 else 1 - policy_team
    gain = abs(utility)
    banker = 0
    if winner_team == banker % 2:
        attacker_points = {1: 50, 2: 20, 3: 0}[gain]
    else:
        attacker_points = 80 + 40 * gain
    return {
        "run": CORE.RUN_ID,
        "label": label,
        "policy": DUEL.LABELS[label],
        "opponent": DUEL.OPPONENT,
        "seed": seed,
        "flip": flip,
        "banker": banker,
        "attacker_points": attacker_points,
        "winner_team": winner_team,
        "level_change": gain,
        "won": int(utility > 0),
        "level_utility": utility,
        "arm": _counter(mode, role=role),
        "opp": _counter("off"),
    }


def _small_contract(monkeypatch) -> None:
    monkeypatch.setattr(CORE, "LOOK_CLUSTERS", (4, 8))
    monkeypatch.setattr(CORE, "LOOK1_CLUSTERS", 4)
    monkeypatch.setattr(CORE, "MAX_CLUSTERS", 8)
    monkeypatch.setattr(CORE, "SHARD_COUNT", 2)
    monkeypatch.setattr(CORE, "CLUSTERS_PER_SHARD", 4)
    monkeypatch.setattr(CORE, "TRANCHE_CLUSTERS_PER_SHARD", 2)
    monkeypatch.setattr(CORE, "NULL_SENTINEL_STRIDE", 2)
    monkeypatch.setattr(CORE, "NULL_SENTINEL_CLUSTERS", 4)


def _records(monkeypatch, *, look: int, treatment_utility: int = 2,
             corrupt_null: bool = False) -> list[dict]:
    _small_contract(monkeypatch)
    clusters = CORE.LOOK_CLUSTERS[look - 1]
    rows = []
    for cluster_index in range(clusters):
        seed = CORE.cluster_seed(cluster_index)
        role = "attacker" if cluster_index % 2 == 0 else "defender"
        for label in CORE.labels_for_cluster(cluster_index):
            utility = treatment_utility if label == "treatment" else 1
            for flip in (0, 1):
                row = _record(label, seed, flip, utility, role)
                if (corrupt_null and label == "matched_null"
                        and cluster_index == 1 and flip == 1):
                    row["attacker_points"] = 55
                rows.append(row)
    return rows


def _aggregate(monkeypatch, *, look: int, treatment_utility: int = 2,
               corrupt_null: bool = False) -> dict:
    rows = _records(
        monkeypatch, look=look, treatment_utility=treatment_utility,
        corrupt_null=corrupt_null)
    return CORE.build_aggregate(
        shards=[{"records": rows}], inputs=[{"sha256": "a" * 64}],
        parent={"champion_policy": DUEL.CHAMPION}, runtime={"frozen": True},
        look=look)


def test_schedule_has_two_exact_balanced_tranches():
    schedule = CORE.schedule()
    assert schedule["looks"] == [8_192, 16_384]
    assert schedule["maximum_clusters"] == 16_384
    assert schedule["tranche_clusters"] == 8_192
    assert schedule["maximum_records"] == 69_632
    assert schedule["look_1_transition"] == CORE.LOOK1_TRANSITION
    assert schedule["final_transition"] == CORE.FINAL_TRANSITION
    assert len(CORE.sentinel_indexes(clusters=8_192)) == 1_024
    assert len(CORE.sentinel_indexes()) == 2_048
    assert [sum(CORE.is_null_sentinel(value)
                for value in CORE.shard_indexes(shard, tranche=1))
            for shard in range(CORE.SHARD_COUNT)] == [128] * 8
    assert [sum(CORE.is_null_sentinel(value)
                for value in CORE.shard_indexes(shard, tranche=2))
            for shard in range(CORE.SHARD_COUNT)] == [128] * 8


def test_future_streams_are_fresh_and_design_valid():
    assert CORE.stream_problems() == []
    assert max(CORE.shard_indexes(7, tranche=1)) < \
        min(CORE.shard_indexes(0, tranche=2))


def test_record_validation_reuses_exact_s4_semantics():
    row = _record("treatment", CORE.SEED0, 0, 2, "attacker")
    assert CORE.record_problems(
        row, expected_seed=CORE.SEED0, expected_label="treatment",
        expected_flip=0) == []
    row["run"] = "wrong"
    assert "record identity" in CORE.record_problems(
        row, expected_seed=CORE.SEED0, expected_label="treatment",
        expected_flip=0)


def test_look_one_passes_or_continues_mechanically(monkeypatch):
    passed = _aggregate(monkeypatch, look=1, treatment_utility=2)
    assert passed["status"] == "STOP_PASS"
    assert passed["efficacy_pass"] is True
    assert passed["strength_claim"] is True

    continued = _aggregate(monkeypatch, look=1, treatment_utility=-1)
    assert continued["status"] == "CONTINUE_AUTOMATICALLY"
    assert continued["integrity"]["all"] is True
    assert continued["strength_claim"] is False


def test_final_look_passes_or_selects_none(monkeypatch):
    assert _aggregate(
        monkeypatch, look=2, treatment_utility=2)["status"] == "PASS"
    assert _aggregate(
        monkeypatch, look=2, treatment_utility=-1)["status"] == "SELECT_NONE"


def test_integrity_failure_holds_instead_of_continuing(monkeypatch):
    result = _aggregate(
        monkeypatch, look=1, treatment_utility=2, corrupt_null=True)
    assert result["status"] == "STOP_HOLD"
    assert result["strength_claim"] is False
    assert result["integrity"][
        "matched_null_champion_sentinel_exact_outcomes"] is False


def test_each_look_uses_its_registered_alpha_and_exact_critical(monkeypatch):
    first = _aggregate(monkeypatch, look=1)["stats"]["treatment_champion"]
    final = _aggregate(monkeypatch, look=2)["stats"]["treatment_champion"]
    assert first["alpha"] == final["alpha"] == 0.025
    assert first["critical"] == final["critical"] == pytest.approx(
        1.959963984540054)
    assert first["family_alpha_bound"] == 0.05


def test_preflight_is_score_free_and_sized_for_maximum():
    assert CORE.PREFLIGHT_CLUSTERS == 4
    assert CORE.THROUGHPUT_SAFETY_FACTOR == 2.0
    assert CORE.MAX_PROJECTED_FLEET_HOURS == 768.0
    assert CORE.MAX_PROJECTED_SHARD_HOURS == 96.0
    assert "future-only two-look" in CORE.CLAIM_BOUNDARY
    assert "historical" in CORE.CLAIM_BOUNDARY.lower()


def test_exclusive_publication_refuses_collisions(tmp_path):
    out = tmp_path / "artifact.json"
    CORE.write_exclusive(out, {"first": True})
    with pytest.raises(CORE.ProtocolRefused, match="refusing to overwrite"):
        CORE.write_exclusive(out, {"second": True})

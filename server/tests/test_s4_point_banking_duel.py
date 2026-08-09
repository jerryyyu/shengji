"""Protocol tests for the complete-round S4 point-banking challenger."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import s4_point_banking_duel as S4D  # noqa: E402


def _telemetry(mode: str, *, role: str | None = None) -> dict:
    values = S4D.empty_point_banking_telemetry(mode=mode)
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
    values = S4D.counters([])
    values["point_banking"] = _telemetry(mode, role=role)
    return values


def _record(label: str, seed: int, flip: int, utility: int, role: str) -> dict:
    mode = {"treatment": "treatment", "matched_null": "matched_null",
            "champion": "off"}[label]
    return {
        "run": S4D.PHASES["screen"]["run_id"],
        "label": label,
        "policy": S4D.LABELS[label],
        "opponent": S4D.OPPONENT,
        "seed": seed,
        "flip": flip,
        "won": int(utility > 0),
        "level_utility": utility,
        "arm": _counter(mode, role=role),
        "opp": _counter("off"),
    }


def _shards(*, treatment_utility: int = 2,
            corrupt_null: bool = False) -> list[dict]:
    records = []
    for cluster in range(2):
        seed = S4D.PHASES["screen"]["seed0"] + \
            S4D.STREAM_STRIDE * cluster
        role = "attacker" if cluster == 0 else "defender"
        for label in S4D.LABEL_ORDER:
            utility = treatment_utility if label == "treatment" else 1
            for flip in (0, 1):
                row = _record(label, seed, flip, utility, role)
                if corrupt_null and label == "matched_null" \
                        and cluster == 1 and flip == 1:
                    row["level_utility"] = -1
                    row["won"] = 0
                records.append(row)
    return [{"records": records}]


def test_frozen_population_and_streams_are_disjoint():
    assert S4D.SHARD_COUNT == 8
    assert S4D.STREAM_STRIDE == 3_000_017
    assert S4D.PREFLIGHT_SEED0 == 40_000_000_000
    assert S4D.PHASES == {
        "screen": {
            "run_id": "s4-point-banking-duel-screen-50b-v1",
            "seed0": 50_000_000_000,
            "clusters": 2_048,
            "clusters_per_shard": 256,
            "claim": "non_promotable_s4_complete_round_screen",
        },
        "confirm": {
            "run_id": "s4-point-banking-duel-confirm-70b-v1",
            "seed0": 70_000_000_000,
            "clusters": 8_192,
            "clusters_per_shard": 1_024,
            "claim": "independent_s4_complete_round_confirmation",
        },
    }
    assert S4D.global_stream_problems() == []


def test_arms_share_root_contract_ballot_and_rng_but_not_rollout_mode():
    parent = {"champion_policy": S4D.CHAMPION}
    assert S4D.protocol_problems(parent) == []
    contracts = {label: S4D.policy_contract(label)
                 for label in S4D.LABEL_ORDER}
    assert len({value["root_ballot_digest"]
                for value in contracts.values()}) == 1
    assert contracts["treatment"]["uppercase"] == \
        contracts["matched_null"]["uppercase"] == \
        contracts["champion"]["uppercase"]
    assert contracts["treatment"]["rollout_mode"] == "treatment"
    assert contracts["matched_null"]["rollout_mode"] == "matched_null"
    assert contracts["champion"]["rollout_mode"] == "off"


@pytest.mark.parametrize("mode", ["treatment", "matched_null", "off"])
def test_telemetry_validator_accepts_exact_modes_and_rejects_dose_drift(mode):
    role = None if mode == "off" else "attacker"
    record = _telemetry(mode, role=role)
    assert S4D.telemetry_problems(record, expected_mode=mode) == []
    if mode == "treatment":
        record["changes"] = 0
    elif mode == "matched_null":
        record["matched_noops"] = 0
    else:
        record["triggers"] = 1
    assert S4D.telemetry_problems(record, expected_mode=mode)


def test_record_validation_binds_policy_identity_and_feature_off_opponent():
    row = _record("treatment", 50_000_000_000, 0, 2, "attacker")
    assert S4D.record_problems(
        row, phase="screen", expected_seed=50_000_000_000,
        expected_label="treatment", expected_flip=0) == []
    row["opp"]["point_banking"]["triggers"] = 1
    problems = S4D.record_problems(
        row, phase="screen", expected_seed=50_000_000_000,
        expected_label="treatment", expected_flip=0)
    assert any("feature-off" in problem for problem in problems)


def test_complete_round_gate_can_advance_or_select_none(monkeypatch):
    monkeypatch.setitem(S4D.PHASES["screen"], "clusters", 2)
    parent = {"champion_policy": S4D.CHAMPION}
    runtime = {"frozen": True}
    passed = S4D.build_aggregate(
        phase="screen", shards=_shards(), inputs=[{"sha256": "a" * 64}],
        parent=parent, runtime=runtime, screen_parent=None)
    assert passed["status"] == "AUTHORIZE_CONFIRM_PACKET_REVIEW"
    assert all(passed["criteria"].values())
    assert passed["stats"]["treatment_champion"]["lcb95"] > 0
    assert passed["strength_claim"] is False
    assert passed["production_promotion"] is False

    rejected = S4D.build_aggregate(
        phase="screen", shards=_shards(treatment_utility=-1),
        inputs=[{"sha256": "b" * 64}], parent=parent, runtime=runtime,
        screen_parent=None)
    assert rejected["status"] == "SELECT_NONE"
    assert rejected["criteria"]["treatment_champion_lcb_gt_zero"] is False


def test_matched_null_must_be_outcome_identical_to_champion(monkeypatch):
    monkeypatch.setitem(S4D.PHASES["screen"], "clusters", 2)
    result = S4D.build_aggregate(
        phase="screen", shards=_shards(corrupt_null=True),
        inputs=[{"sha256": "c" * 64}],
        parent={"champion_policy": S4D.CHAMPION}, runtime={},
        screen_parent=None)
    assert result["status"] == "SELECT_NONE"
    assert result["criteria"]["matched_null_champion_exact_outcomes"] is False


def test_exclusive_publication_refuses_final_and_partial_collisions(tmp_path):
    final = tmp_path / "artifact.json"
    S4D.write_exclusive(final, {"first": True})
    first = final.read_bytes()
    with pytest.raises(S4D.ProtocolRefused, match="refusing to overwrite"):
        S4D.write_exclusive(final, {"second": True})
    assert final.read_bytes() == first

    partial_target = tmp_path / "partial.json"
    Path(str(partial_target) + ".partial").write_text(
        json.dumps({"interrupted": True}))
    with pytest.raises(S4D.ProtocolRefused, match="refusing to overwrite"):
        S4D.write_exclusive(partial_target, {"second": True})


def test_full_game_packet_binds_load_bearing_s4_mechanism_source():
    # Keep the full-game packet transitively dependent on the load-bearing
    # mechanism tests rather than accepting a telemetry-only no-op wrapper.
    source = (Path(__file__).parents[1] / "shengji/ai/point_banking.py")
    body = source.read_text()
    assert "if not has_higher_reserve:" in body
    assert "return [proposed]" in body
    assert S4D.sha256(source) == S4D.source_sha256s()["point_banking"]

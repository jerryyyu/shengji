"""Protocol tests for the complete-round S4 point-banking challenger."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

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


def _searched_counter(mode: str) -> dict:
    values = _counter(mode)
    values.update({
        "rollouts": 630,
        "searches": 1,
        "sample_attempts": S4D.ROOT_WORLDS + S4D.REPORT_WORLDS,
        "accepted_worlds": S4D.ROOT_WORLDS + S4D.REPORT_WORLDS,
    })
    return values


def _authority_chain(tmp_path: Path, monkeypatch, *,
                     admission_strength: bool = False,
                     duplicate_marker: bool = False) -> tuple[Path, str]:
    monkeypatch.setattr(S4D, "REPO", tmp_path)
    run_id = S4D.PHASES["screen"]["run_id"]
    namespace = tmp_path / "server/runs/logs" / run_id
    namespace.mkdir(parents=True)
    git = "a" * 40
    preflight_sha = "2" * 64
    mechanism_sha = "3" * 64
    packet = {
        "schema": S4D.PACKET_SCHEMA,
        "run_id": run_id,
        "git": git,
        "runner": {
            "path": "server/scripts/s4_point_banking_duel.py",
            "sha256": S4D.sha256(S4D.SCRIPT),
        },
        "controller": {"path": "controller.py", "sha256": "4" * 64},
        "runtime": {},
        "parent": {},
        "mechanism_parent": {"screen": {"sha256": mechanism_sha}},
        "score_free_preflight": {
            "sha256": preflight_sha,
            "score_free": True,
            "outcomes_published": False,
        },
        "phase_identity": S4D.phase_identity("screen"),
        "namespace": str(Path("server/runs/logs") / run_id),
        "jobs": [],
        "aggregate_command_template": [],
        "aggregate_output": str(
            Path("server/runs/logs") / run_id / "aggregate.json"),
        "heartbeat_seconds": 30.0,
        "screen_clusters": S4D.PHASES["screen"]["clusters"],
        "shard_count": S4D.SHARD_COUNT,
        "selection_rule": S4D.SELECTION_RULE,
        "claim_boundary": S4D.CLAIM_BOUNDARY,
        "packet_review_authorized": True,
        "screen_launch_authorized": False,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "retry_or_extension_authorized": False,
    }
    packet_path = namespace / "launch_packet.json"
    packet_path.write_text(json.dumps(packet, sort_keys=True))
    packet_sha = S4D.sha256(packet_path)
    claim = {
        "schema": S4D.PACKET_REVIEW_SCHEMA,
        "git": git,
        "run_id": run_id,
        "packet_sha256": packet_sha,
        "preflight_sha256": preflight_sha,
        "mechanism_screen_sha256": mechanism_sha,
        "independent_review": True,
        "screen_launch_authorized": True,
        "confirmation_launch_authorized": False,
        "strength_claim": admission_strength,
        "training_authorized": False,
        "production_promotion": False,
        "verdict": "PASS",
    }
    marker = S4D.PACKET_REVIEW_MARKER + json.dumps(claim, sort_keys=True) + "\n"
    if duplicate_marker:
        marker += marker
    review_path = namespace / "review_record.txt"
    review_path.write_text(marker)
    admission = {
        "schema": S4D.ADMISSION_SCHEMA,
        "run_id": run_id,
        "packet": {
            "path": str(Path("server/runs/logs") / run_id
                        / "launch_packet.json"),
            "sha256": packet_sha,
        },
        "review": {
            "path": str(Path("server/runs/logs") / run_id
                        / "review_record.txt"),
            "sha256": S4D.sha256(review_path),
        },
        "review_claim": claim,
        "operator_asserted_independent_review": True,
        "screen_launch_authorized": True,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
    }
    admission_path = namespace / "review_admission.json"
    admission_path.write_text(json.dumps(admission, sort_keys=True))
    receipt = {
        "schema": S4D.EXECUTION_RECEIPT_SCHEMA,
        "run_id": run_id,
        "phase": "screen",
        "complete": True,
        "git": git,
        "runner_sha256": S4D.sha256(S4D.SCRIPT),
        "created_time_ns": 1,
        "nonce": "5" * 64,
        "packet_sha256": packet_sha,
        "admission_sha256": S4D.sha256(admission_path),
        "preflight_sha256": preflight_sha,
        "mechanism_screen_sha256": mechanism_sha,
        "screen_launch_authorized": True,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "retry_or_resume_authorized": False,
    }
    receipt_path = namespace / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True))
    return receipt_path, git


def _record(label: str, seed: int, flip: int, utility: int, role: str) -> dict:
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
    expected_winner, level_change = S4D.expected_round_outcome(
        banker=banker, attacker_points=attacker_points)
    assert expected_winner == winner_team and level_change == gain
    return {
        "run": S4D.PHASES["screen"]["run_id"],
        "label": label,
        "policy": S4D.LABELS[label],
        "opponent": S4D.OPPONENT,
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
                    row = _record(label, seed, flip, -1, role)
                records.append(row)
    return [{"records": records}]


def test_frozen_population_and_streams_are_disjoint():
    assert S4D.SHARD_COUNT == 8
    assert S4D.STREAM_STRIDE == 3_000_017
    assert S4D.PREFLIGHT_SEED0 == 96_000_000_000
    assert S4D.PHASES == {
        "screen": {
            "run_id": "s4-point-banking-duel-screen-100b-v2",
            "seed0": 100_000_000_000,
            "clusters": 2_048,
            "clusters_per_shard": 256,
            "claim": "non_promotable_s4_complete_round_screen",
        },
        "confirm": {
            "run_id": "s4-point-banking-duel-confirm-120b-v2",
            "seed0": 120_000_000_000,
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
    row = _record("treatment", 100_000_000_000, 0, 2, "attacker")
    assert S4D.record_problems(
        row, phase="screen", expected_seed=100_000_000_000,
        expected_label="treatment", expected_flip=0) == []
    row["opp"]["point_banking"]["triggers"] = 1
    problems = S4D.record_problems(
        row, phase="screen", expected_seed=100_000_000_000,
        expected_label="treatment", expected_flip=0)
    assert any("feature-off" in problem for problem in problems)


def test_record_validation_recomputes_sign_and_binds_physical_utility():
    seed = S4D.PHASES["screen"]["seed0"]
    base = _record("champion", seed, 0, 2, "attacker")
    assert S4D.record_problems(
        base, phase="screen", expected_seed=seed,
        expected_label="champion", expected_flip=0) == []

    wrong_sign = dict(base, won=0)
    problems = S4D.record_problems(
        wrong_sign, phase="screen", expected_seed=seed,
        expected_label="champion", expected_flip=0)
    assert "record win value" in problems
    assert "record signed/bounded level utility" in problems

    impossible_utility = dict(base, level_utility=999)
    problems = S4D.record_problems(
        impossible_utility, phase="screen", expected_seed=seed,
        expected_label="champion", expected_flip=0)
    assert "record signed/bounded level utility" in problems

    impossible_points = dict(base, attacker_points=base["attacker_points"] + 1)
    problems = S4D.record_problems(
        impossible_points, phase="screen", expected_seed=seed,
        expected_label="champion", expected_flip=0)
    assert "attacker points outside physical house bound" in problems


def test_counter_validation_refuses_one_world_for_report_lcb_search():
    complete = _searched_counter("off")
    assert S4D.counter_problems(complete, expected_mode="off") == []
    underfilled = dict(complete, accepted_worlds=1, sample_attempts=1)
    problems = S4D.counter_problems(underfilled, expected_mode="off")
    assert any("accepted report-LCB dose 1 != 330" in p for p in problems)


def test_round_outcome_recomputation_covers_house_bounds():
    assert S4D.expected_round_outcome(banker=0, attacker_points=0) == (0, 3)
    assert S4D.expected_round_outcome(banker=1, attacker_points=20) == (1, 2)
    assert S4D.expected_round_outcome(banker=2, attacker_points=50) == (0, 1)
    assert S4D.expected_round_outcome(banker=3, attacker_points=80) == (0, 0)
    assert S4D.expected_round_outcome(banker=0, attacker_points=120) == (1, 1)
    assert S4D.expected_round_outcome(
        banker=0, attacker_points=S4D.MAX_ATTACKER_POINTS) == (1, 101)
    for bad in (-5, 1, S4D.MAX_ATTACKER_POINTS + 5, True):
        with pytest.raises(ValueError, match="physical house bound"):
            S4D.expected_round_outcome(banker=0, attacker_points=bad)


def test_execution_receipt_reopens_entire_review_authority_chain(
        tmp_path, monkeypatch):
    receipt_path, git = _authority_chain(tmp_path, monkeypatch)
    digest = S4D.sha256(receipt_path)
    assert S4D.require_execution_receipt(
        receipt_path, digest, expected_git=git, phase="screen") == {
            "path": str(receipt_path.relative_to(tmp_path)),
            "sha256": digest,
        }


@pytest.mark.parametrize("admission_strength,duplicate_marker", [
    (True, False),
    (False, True),
])
def test_execution_receipt_refuses_broadened_or_ambiguous_review(
        tmp_path, monkeypatch, admission_strength, duplicate_marker):
    receipt_path, git = _authority_chain(
        tmp_path, monkeypatch, admission_strength=admission_strength,
        duplicate_marker=duplicate_marker)
    with pytest.raises(S4D.ProtocolRefused):
        S4D.require_execution_receipt(
            receipt_path, S4D.sha256(receipt_path),
            expected_git=git, phase="screen")


def test_confirmation_and_unauthorized_screen_refuse_before_compute(
        tmp_path, monkeypatch):
    with pytest.raises(S4D.ProtocolRefused, match="future reviewed controller"):
        S4D.require_execution_receipt(
            tmp_path / "missing.json", "0" * 64,
            expected_git="a" * 40, phase="confirm")

    monkeypatch.setattr(S4D, "REPO", tmp_path)
    monkeypatch.setattr(S4D, "require_runtime", lambda _git: ({}, {}))
    called = []
    monkeypatch.setattr(
        S4D, "play_arm_cluster",
        lambda *args, **kwargs: called.append((args, kwargs)))
    canonical_receipt = (tmp_path / "server/runs/logs"
                         / S4D.PHASES["screen"]["run_id"] / "receipt.json")
    args = SimpleNamespace(
        expected_git="a" * 40, phase="screen", shard_index=0,
        execution_receipt=str(canonical_receipt),
        expected_execution_receipt_sha256="0" * 64,
        progress_every=1, out=str(canonical_receipt.parent / "shard-00.json"))
    with pytest.raises(S4D.ProtocolRefused, match="receipt is missing"):
        S4D.run_shard(args)
    assert called == []


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


def test_matched_null_requires_raw_points_not_only_same_score_bracket(
        monkeypatch):
    monkeypatch.setitem(S4D.PHASES["screen"], "clusters", 2)
    shards = _shards()
    row = next(record for record in shards[0]["records"]
               if record["label"] == "matched_null"
               and record["flip"] == 0)
    # 50 and 55 are both one-level banker wins, so the derived win/utility
    # remain equal while the complete-round result is not behavior-identical.
    assert row["attacker_points"] == 50
    row["attacker_points"] = 55
    assert S4D.record_problems(
        row, phase="screen", expected_seed=row["seed"],
        expected_label="matched_null", expected_flip=0) == []
    result = S4D.build_aggregate(
        phase="screen", shards=shards, inputs=[{"sha256": "d" * 64}],
        parent={"champion_policy": S4D.CHAMPION}, runtime={},
        screen_parent=None)
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

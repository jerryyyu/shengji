"""Fail-closed boundaries for the score-free S4 capture/exact screen."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import s4_point_banking_screen as S4  # noqa: E402


def _real_trigger_row():
    found = S4._drive_to_trigger(90_000_218)
    assert found is not None, "named mechanism witness disappeared"
    rnd, seat, null_action, treatment_action, telemetry = found
    return S4.state_record(
        rnd, seat, 90_000_218, null_action, treatment_action, telemetry)


def test_frozen_population_and_exact_boundary_constants():
    assert S4.RUN_ID == "s4-point-banking-state-screen-161m-v2"
    assert S4.SEED0 == 161_000_000
    assert S4.MAX_DEALS == 200_000
    assert S4.ROLE_QUOTA == {"attacker": 32, "defender": 32}
    assert S4.HAND_CARDS_AT_DECISION == 3
    assert S4.EXACT_MAX_HAND_CARDS == 2
    assert S4.EXACT_MAX_NODES == 50_000
    assert S4.T_CRITICAL_OVERALL == 1.669
    assert S4.T_CRITICAL_ROLE == 1.696


@pytest.mark.parametrize("points,attacker,defender", [
    (0, -3.5, 3.5),
    (39, -2.5, 2.5),
    (40, -1.5, 1.5),
    (79, -1.5, 1.5),
    (80, 0.5, -0.5),
    (119, 0.5, -0.5),
    (120, 1.5, -1.5),
    (160, 2.5, -2.5),
])
def test_secondary_level_utility_matches_house_brackets(
        points, attacker, defender):
    assert S4._round_team_level_value(points, True) == attacker
    assert S4._round_team_level_value(points, False) == defender


def test_named_real_state_round_trips_full_physical_deck_and_exact_scores():
    row = _real_trigger_row()
    rnd = S4.replay_state(row)
    assert row["role"] == "defender"
    assert row["null_action"] != row["treatment_action"]
    assert row["trigger_delta"]["triggers"] == 1
    assert [len(hand) for hand in rnd.hands] == [2, 2, 2, 3]

    result = S4.score_state(row)
    assert result["state_id"] == row["state_id"]
    assert set(result["exact_nodes"]) == {"null", "treatment"}
    assert all(0 < nodes <= S4.EXACT_MAX_NODES
               for nodes in result["exact_nodes"].values())


@pytest.mark.parametrize("mutation,match", [
    (lambda row: row["hands"][0].__setitem__(0, "BJ"), "digest mismatch"),
    (lambda row: row.update(state_sha256="0" * 64), "digest mismatch"),
])
def test_state_tampering_refuses_before_scoring(mutation, match):
    row = _real_trigger_row()
    mutation(row)
    with pytest.raises(S4.S4ProtocolError, match=match):
        S4.replay_state(row)


def _aggregate_rows(delta: int, level_delta: int = 0):
    rows = []
    for role in S4.ROLE_QUOTA:
        for i in range(S4.ROLE_QUOTA[role]):
            rows.append({
                "deal_seed": (1_000_000 if role == "attacker" else 2_000_000) + i,
                "role": role,
                "signed_point_delta": delta,
                "signed_level_utility_delta": level_delta,
            })
    return rows


def test_gate_can_authorize_review_or_select_none_but_never_launch():
    passed = S4.aggregate(_aggregate_rows(10, 1))
    assert passed["verdict"] == "AUTHORIZE_FULL_GAME_PACKET_REVIEW"
    assert all(passed["criteria"].values())
    assert passed["strength_claim"] is False
    assert passed["full_game_launch_authorized"] is False
    assert passed["production_promotion"] is False

    rejected = S4.aggregate(_aggregate_rows(-10, -1))
    assert rejected["verdict"] == "SELECT_NONE"
    assert not all(rejected["criteria"].values())


def test_aggregate_refuses_role_shortfall_and_duplicate_deals():
    rows = _aggregate_rows(1)
    with pytest.raises(S4.S4ProtocolError, match="row count"):
        S4.aggregate(rows[:-1])
    duplicate = copy.deepcopy(rows)
    duplicate[-1]["deal_seed"] = duplicate[0]["deal_seed"]
    with pytest.raises(S4.S4ProtocolError, match="not independent"):
        S4.aggregate(duplicate)


def test_review_admission_is_exactly_bound_to_git_and_state_asset(tmp_path):
    path = tmp_path / "admission.json"
    record = S4.expected_admission(git="a" * 40, states_sha256="b" * 64)
    path.write_text(json.dumps(record))
    assert S4.verify_admission(
        str(path), git="a" * 40, states_sha256="b" * 64) == record
    record["training_authorized"] = True
    path.write_text(json.dumps(record))
    with pytest.raises(S4.S4ProtocolError, match="admission mismatch"):
        S4.verify_admission(
            str(path), git="a" * 40, states_sha256="b" * 64)

    record = S4.expected_admission(git="a" * 40, states_sha256="b" * 64)
    record["unexpected_authority"] = True
    path.write_text(json.dumps(record))
    with pytest.raises(S4.S4ProtocolError, match="admission mismatch"):
        S4.verify_admission(
            str(path), git="a" * 40, states_sha256="b" * 64)


def test_screen_receipt_consumes_exactly_one_namespace(tmp_path):
    receipt = S4.screen_receipt(
        git="a" * 40, states_sha256="b" * 64,
        admission_sha256="c" * 64)
    assert receipt["screen_namespace_consumed"] is True
    assert receipt["retry_or_extension_authorized"] is False
    assert receipt["full_game_launch_authorized"] is False
    path = tmp_path / "screen_receipt.json"
    S4.publish_exclusive(path, receipt)
    with pytest.raises(S4.S4ProtocolError, match="refusing existing"):
        S4.publish_exclusive(path, receipt)


def test_real_namespace_paths_are_closed():
    root = Path("/tmp") / S4.RUN_ID
    paths = S4._real_screen_paths(
        root / "states.json", root / "review_admission.json",
        root / "screen.json")
    assert paths[-1].name == "screen_receipt.json"
    with pytest.raises(S4.S4ProtocolError, match="canonical namespace"):
        S4._real_screen_paths(
            root / "states.json", root / "review_admission.json",
            root / "screen-copy.json")


def test_exclusive_publish_never_overwrites_or_resumes(tmp_path):
    path = tmp_path / "artifact.json"
    S4.publish_exclusive(path, {"first": True})
    first = path.read_bytes()
    with pytest.raises(S4.S4ProtocolError, match="refusing existing"):
        S4.publish_exclusive(path, {"second": True})
    assert path.read_bytes() == first

    partial_target = tmp_path / "partial-collision.json"
    Path(str(partial_target) + ".partial").write_text("stale")
    with pytest.raises(S4.S4ProtocolError, match="refusing existing"):
        S4.publish_exclusive(partial_target, {"second": True})
    assert not partial_target.exists()


def test_artifact_verifier_rejects_symlinks_and_partials(tmp_path):
    target = tmp_path / "target.json"
    target.write_text("{}")
    linked = tmp_path / "linked.json"
    linked.symlink_to(target)
    with pytest.raises(S4.S4ProtocolError, match="linked, nonregular"):
        S4.require_regular_unlinked(linked)

    Path(str(target) + ".partial").write_text("stale")
    with pytest.raises(S4.S4ProtocolError, match="has a partial"):
        S4.require_regular_unlinked(target)

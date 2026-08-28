from __future__ import annotations

import copy
import hashlib
import json
import random

import pytest

from shengji.ai.registry import make_bot
from shengji.engine.round import Round
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate import canonical_successor
from shengji.rl.world_afterstate_sources import (
    WorldAfterstateSourceError, actor_seed_identity,
    build_round_source_schedule, build_state_group_material,
    capture_production_round_materials, normalize_pt_sol_observation,
    production_ballot_from_snapshot, pt_sol_state_materials,
    reopen_pt_sol_private_evidence, validate_round_source_schedule,
)


def _round() -> Round:
    seed = 884_400_011
    rnd = Round("7", 0, random.Random(seed))
    bot = make_bot("smart", seed=seed + 1)
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    burial = bot.decide_bury(rnd, rnd.banker)
    rnd.bury(rnd.banker, burial)
    for _ in range(7):
        seat = rnd.turn
        rnd.play(seat, bot.decide_play(rnd, seat))
    assert rnd.turn is not None
    return rnd


def _absolute_trick(value):
    if value is None:
        return None
    return copy.deepcopy(value)


def _response(rnd: Round):
    root = rnd.turn
    successor = canonical_successor(rnd, root)
    public = successor["public"]
    # The fixture has root 0 in the canonical view; translate back to the
    # original absolute Round exactly as the real PT tool response does.
    response = {
        "acting_seat": root,
        "attacker_points": rnd.attacker_points,
        "available_continuations": ["smart-all"],
        "banker": rnd.banker,
        "budget": {},
        "candidate_zero_is_production_prior": True,
        "candidates": [],
        "completed_tricks": [
            {"leader": trick.leader,
             "plays": [{"seat": play.seat, "cards": list(play.cards)}
                       for play in trick.plays],
             "winner": trick.winner, "points": trick.points}
            for trick in rnd.history],
        "current_trick": {
            "leader": rnd.trick.leader,
            "plays": [{"seat": play.seat, "cards": list(play.cards)}
                      for play in rnd.trick.plays],
            "winner": rnd.trick.winner, "points": rnd.trick.points},
        "decision_sha256": "1" * 64,
        "hands_by_seat": [list(hand) for hand in rnd.hands],
        "hidden_burial": list(rnd.buried),
        "kitty_bonus_so_far": rnd.kitty_bonus,
        "objective": {},
        "remaining_points_by_seat": [0, 0, 0, 0],
        "role": "attacker-team" if rnd.is_attacker(root)
                else "banker-team",
        "schema": "privileged-teacher-sol0-tool-response-v1",
        "status": "decision",
        "team_is_attacker": rnd.is_attacker(root),
        "treatment_team": root % 2,
        "trump_is_nt": rnd.trump_is_nt,
        "trump_rank": rnd.trump_rank,
        "trump_suit": rnd.trump_suit,
    }
    return response, successor


def test_pt_observation_rebases_and_replays_every_mechanical_field():
    response, expected = _response(_round())
    snapshot = normalize_pt_sol_observation(response)
    # PT does not retain declaration/message bytes; neither is a V0 input.
    expected["public"]["declaration"] = None
    expected["public"]["message"] = None
    expected["public"]["first_round"] = False
    assert snapshot == expected
    identity, audits, digest = production_ballot_from_snapshot(
        snapshot, policy_seed=998_001)
    assert identity["ordered_candidates"]
    assert len(audits) == len(identity["ordered_candidates"])
    assert len(digest) == 12

    forged = copy.deepcopy(response)
    forged["attacker_points"] += 10
    with pytest.raises(WorldAfterstateSourceError):
        normalize_pt_sol_observation(forged)


def _sealed_private(response, public):
    transcript = {
        "schema": "privileged-teacher-sol0-private-transcript-v1",
        "coordinate": [public["trump_rank"], public["banker"], 0],
        "role": public["role"],
        "treatment_team": public["treatment_team"],
        "events": [{"index": 0, "operation": "observe",
                    "request": {"op": "observe"},
                    "response": response}],
        "status": {"status": "round_end", "attacker_points": 80,
                   "signed_level_utility": -1},
    }
    transcript["transcript_sha256"] = hashlib.sha256(
        canonical_json_bytes(transcript)).hexdigest()
    evidence = {
        "schema": "privileged-teacher-sol0-private-evidence-v1",
        "transcript": transcript,
        "process_returncode": 0,
        "process_error": None,
        "model_final_base64": "",
        "model_stdout_base64": "",
    }
    evidence["evidence_sha256"] = hashlib.sha256(
        canonical_json_bytes(evidence)).hexdigest()
    raw = canonical_json_bytes(evidence)
    public["private_evidence_sha256"] = hashlib.sha256(raw).hexdigest()
    return raw


def test_private_evidence_is_cross_bound_before_observations_are_returned():
    response, _expected = _response(_round())
    public = {
        "trump_rank": "7", "banker": 0, "replicate": 0,
        "role": response["role"], "treatment_team": response["treatment_team"],
        "sol0": {"attacker_points": 80, "signed_level_utility": -1},
    }
    raw = _sealed_private(response, public)
    assert len(reopen_pt_sol_private_evidence(raw, public)) == 1
    forged = json.loads(raw)
    forged["transcript"]["events"][0]["response"]["attacker_points"] += 10
    with pytest.raises(WorldAfterstateSourceError,
                       match="private evidence drift"):
        reopen_pt_sol_private_evidence(canonical_json_bytes(forged), public)


def test_state_material_keeps_hidden_world_private_from_selection_identity():
    seed = 884_400_051
    rnd = Round("7", 0, random.Random(seed))
    bot = make_bot("smart", seed=seed + 1)
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    snapshot = canonical_successor(rnd, rnd.turn)
    deal = hashlib.sha256(b"teacher-root").hexdigest()
    first = build_state_group_material(
        snapshot, deal_group_sha256=deal, source="reviewed-pt-sol0",
        policy_seed=881)
    hidden_twin = copy.deepcopy(snapshot)
    left = hidden_twin["complete_world"]["hands"][1]
    right = hidden_twin["complete_world"]["hands"][2]
    left_card = next(card for card in left if card not in right)
    right_card = next(card for card in right if card not in left)
    left[left.index(left_card)] = right_card
    right[right.index(right_card)] = left_card
    left.sort()
    right.sort()
    second = build_state_group_material(
        hidden_twin, deal_group_sha256=hashlib.sha256(
            b"teacher-hidden-twin").hexdigest(),
        source="reviewed-pt-sol0", policy_seed=881)
    assert actor_seed_identity(snapshot) == actor_seed_identity(hidden_twin)
    assert first.group["decision_sha256"] == second.group["decision_sha256"]
    assert first.group["selection_priority_sha256"] \
        == second.group["selection_priority_sha256"]
    assert first.group["candidates"] != second.group["candidates"]


def test_production_capture_and_pt_import_emit_reopenable_materials():
    captured = capture_production_round_materials(
        deal_seed=884_400_099, trump_rank="A", initial_banker=2,
        max_decisions=1)
    assert len(captured) == 1
    captured[0].validate()
    assert captured[0].group["source"] == "production-policy"

    response, _expected = _response(_round())
    public = {
        "root_sha256": hashlib.sha256(b"pt-sol-root").hexdigest(),
        "trump_rank": "7", "banker": 0, "replicate": 0,
        "role": response["role"],
        "treatment_team": response["treatment_team"],
        "sol0": {"attacker_points": 80, "signed_level_utility": -1},
    }
    raw = _sealed_private(response, public)
    materials = pt_sol_state_materials(raw, public)
    assert len(materials) == 1
    materials[0].validate()
    assert materials[0].group["source"] == "reviewed-pt-sol0"

    repeated = json.loads(raw)
    duplicate = copy.deepcopy(repeated["transcript"]["events"][0])
    duplicate["index"] = 1
    repeated["transcript"]["events"].append(duplicate)
    repeated["transcript"].pop("transcript_sha256")
    repeated["transcript"]["transcript_sha256"] = hashlib.sha256(
        canonical_json_bytes(repeated["transcript"])).hexdigest()
    repeated.pop("evidence_sha256")
    repeated["evidence_sha256"] = hashlib.sha256(
        canonical_json_bytes(repeated)).hexdigest()
    repeated_raw = canonical_json_bytes(repeated)
    public["private_evidence_sha256"] = hashlib.sha256(
        repeated_raw).hexdigest()
    assert len(pt_sol_state_materials(repeated_raw, public)) == 1


def test_round_source_schedule_covers_every_rank_mode_and_fold():
    schedule = build_round_source_schedule("production-policy")
    validate_round_source_schedule(schedule)
    rows = schedule["rows"]
    for fold in ("train", "calibration", "report", "provider-audit"):
        assert {row["trump_rank"] for row in rows
                if row["fold"] == fold and row["purpose"] == "rank-anchor"} \
            == {"2", "3", "4", "5", "6", "7", "8", "9", "10",
                "J", "Q", "K", "A"}
        assert {row["observed_trump_mode"] for row in rows
                if row["fold"] == fold and row["purpose"] == "mode-anchor"} \
            == {"C", "D", "H", "S", "NT"}
    forged = copy.deepcopy(schedule)
    forged["rows"][0]["deal_seed"] += 1
    with pytest.raises(WorldAfterstateSourceError,
                       match="reconstruction drift"):
        validate_round_source_schedule(forged)

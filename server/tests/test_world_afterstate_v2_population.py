from __future__ import annotations

import copy
import hashlib
import json
from types import SimpleNamespace
import random

import pytest

from shengji.ai.registry import make_bot
from shengji.engine.cards import RANKS
from shengji.engine.round import Round
from shengji.rl import world_afterstate_v2_population as population
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate import canonical_successor
from shengji.rl.world_afterstate_v2_population import (
    WorldAfterstateV2PopulationError, build_population_material_v2,
    select_one_material_per_deal,
)
from shengji.rl.world_afterstate_v2_label import _candidate_set_sha256
from shengji.rl.actions import enumerate_actions
from shengji.rl.world_afterstate import replay_canonical_successor
from shengji.rl.world_afterstate_v2_protocol import (
    TIER_SPECS, attempted_deal_identity, build_population_slot_ledger,
)


def _snapshot(seed: int = 918_400_017) -> dict:
    rnd = Round("2", None, random.Random(seed))
    bots = [make_bot("smart", seed=seed + 10 + seat) for seat in range(4)]
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bots[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = bots[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    assert rnd.banker is not None
    rnd.bury(rnd.banker, bots[rnd.banker].decide_bury(rnd, rnd.banker))
    # A root-relative snapshot is canonical regardless of the absolute actor.
    return canonical_successor(rnd, rnd.turn)


def _slot_and_attempt(snapshot: dict, ordinal: int = 0):
    slots = [slot for slot in build_population_slot_ledger(TIER_SPECS[0])
             if slot.group == "natural-fit"]
    public = snapshot["public"]
    cell = (
        "early" if not public["completed_tricks"] else
        ("middle" if len(public["completed_tricks"]) < 14 else "late"),
        "lead" if not public["current_trick"]["plays"] else "follow",
        snapshot["root_role"],
    )
    mode = "NT" if public["trump_is_nt"] else public["trump_suit"]
    slot = next(slot for slot in slots
                if slot.cell == cell and slot.trump_rank == public["trump_rank"]
                and slot.trump_mode == mode)
    attempt = attempted_deal_identity("a" * 64, slot, ordinal)
    return slot, attempt


def _case(seed: int = 918_400_017):
    for candidate_seed in range(seed, seed + 80):
        snapshot = _snapshot(candidate_seed)
        try:
            slot, attempt = _slot_and_attempt(snapshot)
        except StopIteration:
            continue
        return snapshot, slot, attempt
    raise AssertionError("could not witness a frozen slot stratum")


def _material():
    snapshot, slot, attempt = _case()
    return build_population_material_v2(attempt, slot, snapshot)


def test_real_snapshot_derives_state_and_candidate_contract():
    material = _material()
    material.validate()
    assert material.state.state_sha256 == hashlib.sha256(
        canonical_json_bytes(material.prestate)).hexdigest()
    assert material.candidates[0].protected_incumbent is True
    assert len(material.candidates) == material.state.legal_candidate_count
    assert material.candidate_set_sha256 == _candidate_set_sha256(
        material.state_sha256, material.successor_sha256s)
    assert all(candidate.origin in ("production-ballot", "legal-tail")
               for candidate in material.candidates)


def test_protected_incumbent_is_production_play_not_first_ballot(
        monkeypatch):
    snapshot, slot, attempt = _case()
    _identity, ballot, _digest = population.production_ballot_identity_from_snapshot(
        snapshot, policy_seed=population._seed_for_deal(attempt["deal_sha256"]))
    assert len(ballot) > 1
    selected = list(ballot[1])
    monkeypatch.setattr(population, "make_bot", lambda *_args, **_kwargs:
                        SimpleNamespace(decide_play=lambda *_: selected))
    material = build_population_material_v2(attempt, slot, snapshot)
    first = json.loads(material.audit_raws[0].decode("ascii"))
    assert tuple(first["attempted_action"]) == tuple(selected)
    assert material.candidates[0].protected_incumbent is True


def test_slot_rank_mode_and_witness_mismatches_refuse():
    snapshot, slot, attempt = _case()
    wrong_rank = next(slot for slot in build_population_slot_ledger(TIER_SPECS[0])
                      if slot.group == "natural-fit"
                      and slot.cell == slot.cell
                      and slot.trump_rank != snapshot["public"]["trump_rank"])
    wrong_attempt = attempted_deal_identity("a" * 64, wrong_rank, 0)
    with pytest.raises(WorldAfterstateV2PopulationError):
        build_population_material_v2(wrong_attempt, wrong_rank, snapshot)
    wrong_slot = copy.copy(slot)
    # The slot's fixed stratum cannot be replaced by a caller witness.
    object.__setattr__(wrong_slot, "phase", "late")
    with pytest.raises(Exception):
        build_population_material_v2(attempt, wrong_slot, snapshot)


def test_candidate_tail_is_legal_and_natural_source_rejects_played_metadata():
    snapshot, slot, attempt = _case(918_400_019)
    material = build_population_material_v2(attempt, slot, snapshot)
    first_audit = json.loads(material.audit_raws[0].decode("ascii"))
    played = first_audit["attempted_action"]
    with pytest.raises(WorldAfterstateV2PopulationError,
                       match="presence drift"):
        build_population_material_v2(
            attempt, slot, snapshot, played_action=played, source="natural")
    assert all(audit["successor_sha256"] for audit in map(
        lambda raw: json.loads(raw.decode("ascii")), material.audit_raws))


def test_diverse_played_action_is_appended_only_when_legal_and_nonduplicate():
    for seed in range(918_400_100, 918_400_180):
        snapshot = _snapshot(seed)
        public = snapshot["public"]
        cell = (
            "early" if len(public["completed_tricks"]) < 6 else
            ("middle" if len(public["completed_tricks"]) < 14 else "late"),
            "lead" if not public["current_trick"]["plays"] else "follow",
            snapshot["root_role"],
        )
        mode = "NT" if public["trump_is_nt"] else public["trump_suit"]
        slot = next((candidate for candidate in build_population_slot_ledger(
            TIER_SPECS[1]) if candidate.group == "diverse-fit-sol"
            and candidate.cell == cell and candidate.trump_rank == public["trump_rank"]
            and candidate.trump_mode == mode), None)
        if slot is None:
            continue
        attempt = attempted_deal_identity("a" * 64, slot, 0)
        # A diverse source must bind its played action even when that action
        # deduplicates against the production ballot.
        natural_slot = next(candidate for candidate in build_population_slot_ledger(
            TIER_SPECS[0]) if candidate.group == "natural-fit"
            and candidate.cell == cell and candidate.trump_rank == public["trump_rank"]
            and candidate.trump_mode == mode)
        natural_attempt = attempted_deal_identity("a" * 64, natural_slot, 0)
        natural = build_population_material_v2(
            natural_attempt, natural_slot, snapshot)
        incumbent = json.loads(natural.audit_raws[0].decode("ascii"))[
            "attempted_action"]
        base = build_population_material_v2(
            attempt, slot, snapshot, source="pt-sol", played_action=incumbent)
        existing = {tuple(json.loads(raw.decode("ascii"))["attempted_action"])
                    for raw in base.audit_raws}
        legal = enumerate_actions(replay_canonical_successor(snapshot), 0)
        played = next((action for action in legal
                       if tuple(sorted(action)) not in
                       {tuple(sorted(item)) for item in existing}), None)
        if played is None:
            continue
        diverse = build_population_material_v2(
            attempt, slot, snapshot, source="pt-sol", played_action=played)
        assert diverse.candidates[-1].origin == "played-action"
        assert len(diverse.candidates) == len(base.candidates) + 1
        with pytest.raises(WorldAfterstateV2PopulationError,
                           match="played action is not legal"):
            build_population_material_v2(
                attempt, slot, snapshot, source="pt-sol",
                played_action=["ZZ"])
        with pytest.raises(WorldAfterstateV2PopulationError,
                           match="presence drift"):
            build_population_material_v2(
                attempt, slot, snapshot, source="pt-sol")
        return
    raise AssertionError("could not witness a diverse-source legal action")


def test_candidate_set_tamper_and_reopen_are_refused():
    material = _material()
    forged = copy.copy(material)
    object.__setattr__(forged, "candidate_set_sha256", "0" * 64)
    with pytest.raises(WorldAfterstateV2PopulationError, match="candidate-set"):
        forged.validate()
    raws = list(material.audit_raws)
    audit = json.loads(raws[0].decode("ascii"))
    audit["successor"]["public"]["attacker_points"] += 1
    raws[0] = canonical_json_bytes(audit)
    object.__setattr__(forged, "candidate_set_sha256", material.candidate_set_sha256)
    object.__setattr__(forged, "audit_raws", tuple(raws))
    with pytest.raises(WorldAfterstateV2PopulationError):
        forged.validate()


def test_selection_returns_matching_full_material_and_rejects_unassigned():
    snapshot, slot, attempt = _case()
    material = build_population_material_v2(attempt, slot, snapshot)
    selected = select_one_material_per_deal(
        [material], required_slots={attempt["deal_sha256"]: slot})
    assert selected == (material,)
    forged = copy.copy(material)
    object.__setattr__(forged, "state", copy.copy(material.state))
    object.__setattr__(forged.state, "deal_sha256", "b" * 64)
    with pytest.raises(WorldAfterstateV2PopulationError):
        select_one_material_per_deal(
            [forged], required_slots={attempt["deal_sha256"]: slot})


def test_closed_material_has_no_outcome_or_prediction_fields():
    material = _material()
    assert not {"utility", "prediction", "label", "continuation"} & set(
        vars(material))
    assert all("signed_level" not in raw.decode("ascii")
               for raw in material.audit_raws)

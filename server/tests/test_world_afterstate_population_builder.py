from __future__ import annotations

import hashlib
import json
import os
import random
from collections import Counter

import pytest

from shengji.ai.registry import make_bot
from shengji.engine.cards import RANKS
from shengji.engine.round import Round
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate import build_afterstate_audit, root_replay
from shengji.rl.world_afterstate_experiment import SOURCE_FOLD_COUNTS
from shengji.rl.world_afterstate_population import (
    GROUP_SCHEMA, MANIFEST_SCHEMA, build_population_audit_manifest,
    build_population_manifest, fold_for_deal_group)
from shengji.rl.world_afterstate_population_builder import (
    PopulationBuildV0, WorldAfterstatePopulationBuildError,
    publish_population_build, reopen_population_build)
from shengji.rl.world_afterstate_population_packet import (
    build_population_packet)
from shengji.rl.world_afterstate_sources import (
    StateGroupMaterialV0, build_round_source_schedule)


def _sha(value) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _deal_group(fold: str, index: int) -> str:
    while True:
        value = hashlib.sha256(f"builder-{fold}-{index}".encode()).hexdigest()
        if fold_for_deal_group(value) == fold:
            return value
        index += 1


def _pair_audit_raw() -> bytes:
    seed = 884_920_001
    rnd = Round("7", 0, random.Random(seed))
    bot = make_bot("smart", seed=seed + 1)
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    burial = bot.decide_bury(rnd, rnd.banker)
    rnd.bury(rnd.banker, burial)
    pair = next(card for card, count in Counter(rnd.hands[rnd.turn]).items()
                if count >= 2)
    source = root_replay(
        deal_seed=seed, initial_banker=0, trump_rank="7",
        declarations=[], buried=burial, plays=[], root_seat=rnd.turn)
    return canonical_json_bytes(build_afterstate_audit(
        source, {seat: list(rnd.hands[seat]) for seat in range(4)},
        rnd.buried, [pair, pair]))


def _build() -> PopulationBuildV0:
    raw = _pair_audit_raw()
    audit = json.loads(raw)
    audit_sha = hashlib.sha256(raw).hexdigest()
    fold_sources = [
        (fold, source)
        for fold, counts in SOURCE_FOLD_COUNTS.items()
        for source, count in counts.items()
        for _ in range(count)
    ]
    groups = []
    for index, (fold, source) in enumerate(fold_sources):
        deal = _deal_group(fold, index + 90_000)
        decision = hashlib.sha256(
            f"builder-decision-{index}".encode()).hexdigest()
        body = {
            "schema": GROUP_SCHEMA,
            "state_group_id": _sha({
                "deal_group_sha256": deal, "decision_sha256": decision}),
            "deal_group_sha256": deal, "decision_sha256": decision,
            "selection_priority_sha256": _sha({
                "namespace": MANIFEST_SCHEMA,
                "decision_sha256": decision}),
            "source": source, "fold": fold,
            "trump_rank": RANKS[index % len(RANKS)],
            "trump_mode": ("C", "D", "H", "S", "NT")[index % 5],
            "root_role": ("attacker", "defender")[index % 2],
            "play_phase": ("early", "middle", "late")[index % 3],
            "position": ("lead", "follow")[index % 2],
            "points_bucket": (
                "0-39", "40-79", "80-119", "120-159",
                "160+")[index % 5],
            "mechanics_hard_reasons": (
                ["multi-card-action"] if source == "mechanics-hard" else []),
            "candidate_count": 1,
            "candidates": [{
                "candidate_index": 0,
                "action_sha256": _sha(audit["attempted_action"]),
                "audit_sha256": audit_sha,
                "successor_sha256": audit["successor_sha256"],
                "protected_incumbent": True}],
            "complete_ballot": True, "protected_incumbent_index": 0,
            "outcome_opened": False,
            "model_input_contains_metadata": False,
        }
        groups.append({**body, "group_sha256": _sha(body)})
    public = build_population_manifest(groups)
    materials = tuple(StateGroupMaterialV0(
        group=group, audit_raws=(raw,)) for group in public["groups"])
    private = build_population_audit_manifest(
        public, tuple((row.group, row.audit_raws) for row in materials))
    production = build_round_source_schedule("production-policy")
    mechanics = build_round_source_schedule("mechanics-hard")
    packet = build_population_packet(
        source_git="1" * 40,
        population_manifest_raw=canonical_json_bytes(public),
        audit_manifest_raw=canonical_json_bytes(private),
        production_schedule_raw=canonical_json_bytes(production),
        mechanics_schedule_raw=canonical_json_bytes(mechanics),
        pt_sol0_external_sha256="2" * 64,
        pt_sol0_report_sha256="3" * 64,
        pt_sol0_execution_git="4" * 40)
    return PopulationBuildV0(
        population_manifest=public, audit_manifest=private,
        production_schedule=production, mechanics_schedule=mechanics,
        packet=packet, materials=materials)


def test_population_publication_reopens_every_exact_private_byte(tmp_path):
    build = _build()
    root = tmp_path / "population"
    publish_population_build(root, build)
    receipt = reopen_population_build(root)
    assert receipt["group_count"] == 520
    assert receipt["private_group_count"] == 520
    assert receipt["outcome_opened"] is False
    assert oct((root / "packet.json").stat().st_mode & 0o777) == "0o400"

    first = next((root / "audits").rglob("*.json"))
    os.chmod(first, 0o600)
    with pytest.raises(Exception, match="mutable"):
        reopen_population_build(root)


def test_population_publication_refuses_occupied_namespace(tmp_path):
    root = tmp_path / "population"
    root.mkdir()
    with pytest.raises(WorldAfterstatePopulationBuildError,
                       match="namespace occupied"):
        publish_population_build(root, _build())

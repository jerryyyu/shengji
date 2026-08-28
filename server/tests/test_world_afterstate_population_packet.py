from __future__ import annotations

import copy
import hashlib

import pytest

from shengji.engine.cards import RANKS
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_experiment import (
    SOURCE_FOLD_COUNTS)
from shengji.rl.world_afterstate_population import (
    AUDIT_MANIFEST_SCHEMA, GROUP_SCHEMA, MANIFEST_SCHEMA,
    POPULATION_AUTHORITY, build_population_manifest, fold_for_deal_group)
from shengji.rl.world_afterstate_population_packet import (
    WorldAfterstatePopulationPacketError, build_population_packet,
    validate_population_packet)
from shengji.rl.world_afterstate_sources import build_round_source_schedule


def _sha(value) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _deal_group(fold: str, index: int) -> str:
    while True:
        value = hashlib.sha256(f"packet-{fold}-{index}".encode()).hexdigest()
        if fold_for_deal_group(value) == fold:
            return value
        index += 1


def _group(index: int, fold: str, source: str):
    deal = _deal_group(fold, index + 70_000)
    decision = hashlib.sha256(f"packet-decision-{index}".encode()).hexdigest()
    audit = hashlib.sha256(f"packet-audit-{index}".encode()).hexdigest()
    candidate = {
        "candidate_index": 0,
        "action_sha256": hashlib.sha256(
            f"packet-action-{index}".encode()).hexdigest(),
        "audit_sha256": audit,
        "successor_sha256": hashlib.sha256(
            f"packet-successor-{index}".encode()).hexdigest(),
        "protected_incumbent": True,
    }
    body = {
        "schema": GROUP_SCHEMA,
        "state_group_id": _sha({
            "deal_group_sha256": deal, "decision_sha256": decision}),
        "deal_group_sha256": deal,
        "decision_sha256": decision,
        "selection_priority_sha256": _sha({
            "namespace": MANIFEST_SCHEMA, "decision_sha256": decision}),
        "source": source, "fold": fold,
        "trump_rank": RANKS[index % len(RANKS)],
        "trump_mode": ("C", "D", "H", "S", "NT")[index % 5],
        "root_role": ("attacker", "defender")[index % 2],
        "play_phase": ("early", "middle", "late")[index % 3],
        "position": ("lead", "follow")[index % 2],
        "points_bucket": (
            "0-39", "40-79", "80-119", "120-159", "160+")[index % 5],
        "mechanics_hard_reasons": (
            ["wide-ballot"] if source == "mechanics-hard" else []),
        "candidate_count": 1, "candidates": [candidate],
        "complete_ballot": True, "protected_incumbent_index": 0,
        "outcome_opened": False, "model_input_contains_metadata": False,
    }
    return {**body, "group_sha256": _sha(body)}


def _inputs():
    fold_sources = [
        (fold, source)
        for fold, counts in SOURCE_FOLD_COUNTS.items()
        for source, count in counts.items()
        for _ in range(count)
    ]
    groups = [_group(index, fold, source)
              for index, (fold, source) in enumerate(fold_sources)]
    population = build_population_manifest(groups)
    rows = [{
        "state_group_id": group["state_group_id"],
        "candidate_index": 0,
        "relative_path": f"{group['state_group_id']}/000.json",
        "byte_count": index + 1,
        "audit_sha256": group["candidates"][0]["audit_sha256"],
    } for index, group in enumerate(population["groups"])]
    audit_body = {
        "schema": AUDIT_MANIFEST_SCHEMA,
        "population_manifest_sha256": population["manifest_sha256"],
        "group_count": len(groups), "audit_count": len(rows),
        "total_bytes": sum(row["byte_count"] for row in rows),
        "rows": rows, "contains_private_complete_worlds": True,
        "outcome_opened": False, "authority": dict(POPULATION_AUTHORITY),
    }
    audit = {**audit_body, "manifest_sha256": _sha(audit_body)}
    return tuple(canonical_json_bytes(value) for value in (
        population, audit, build_round_source_schedule("production-policy"),
        build_round_source_schedule("mechanics-hard")))


def test_packet_binds_every_outcome_blind_population_input():
    population, audit, production, mechanics = _inputs()
    packet = build_population_packet(
        source_git="1" * 40, population_manifest_raw=population,
        audit_manifest_raw=audit, production_schedule_raw=production,
        mechanics_schedule_raw=mechanics,
        pt_sol0_external_sha256="2" * 64,
        pt_sol0_report_sha256="3" * 64,
        pt_sol0_execution_git="4" * 40)
    validate_population_packet(
        packet, population_manifest_raw=population,
        audit_manifest_raw=audit, production_schedule_raw=production,
        mechanics_schedule_raw=mechanics)
    assert packet["population_manifest"]["group_count"] == 520
    assert packet["selection_outcome_blind"] is True
    assert set(packet["authority"].values()) == {False}

    forged = copy.deepcopy(packet)
    forged["population_manifest"]["external_sha256"] = "5" * 64
    with pytest.raises(WorldAfterstatePopulationPacketError,
                       match="digest drift"):
        validate_population_packet(
            forged, population_manifest_raw=population,
            audit_manifest_raw=audit, production_schedule_raw=production,
            mechanics_schedule_raw=mechanics)

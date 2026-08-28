"""Closed binding over the exact outcome-blind E3/E4 population.

This artifact joins the public selection manifest, private audit inventory,
both deterministic simulator schedules, and the already-reviewed PT-Sol
report identity.  It contains no continuation outcome and authorizes nothing.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .belief_contract import canonical_json_bytes
from .world_afterstate_population import (
    validate_population_audit_manifest, validate_population_manifest)
from .world_afterstate_sources import validate_round_source_schedule


PACKET_SCHEMA = "world-afterstate-e3-population-packet-v0"
PACKET_AUTHORITY = {
    "continuation_dataset_generation_authorized": False,
    "scientific_training_authorized": False,
    "report_opening_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "deployment_authorized": False,
}


class WorldAfterstatePopulationPacketError(ValueError):
    """A bound population input, provenance identity, or digest drifted."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _digest(value: object, label: str, *, length: int = 64) -> str:
    if type(value) is not str or len(value) != length \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstatePopulationPacketError(f"{label} drift")
    return value


def _canonical(raw: bytes, label: str) -> dict[str, Any]:
    if type(raw) is not bytes:
        raise WorldAfterstatePopulationPacketError(
            f"{label} byte type drift")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstatePopulationPacketError(
            f"{label} is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstatePopulationPacketError(
            f"{label} is not canonical JSON")
    return value


def build_population_packet(
        *, source_git: str, population_manifest_raw: bytes,
        audit_manifest_raw: bytes, production_schedule_raw: bytes,
        mechanics_schedule_raw: bytes,
        pt_sol0_external_sha256: str, pt_sol0_report_sha256: str,
        pt_sol0_execution_git: str) -> dict[str, Any]:
    _digest(source_git, "population packet source Git", length=40)
    population = _canonical(
        population_manifest_raw, "population manifest")
    audit = _canonical(audit_manifest_raw, "population audit manifest")
    production = _canonical(
        production_schedule_raw, "production source schedule")
    mechanics = _canonical(
        mechanics_schedule_raw, "mechanics source schedule")
    validate_population_manifest(population)
    validate_population_audit_manifest(audit, population)
    validate_round_source_schedule(production)
    validate_round_source_schedule(mechanics)
    if production.get("source") != "production-policy" \
            or mechanics.get("source") != "mechanics-hard":
        raise WorldAfterstatePopulationPacketError(
            "population schedule source drift")
    _digest(pt_sol0_external_sha256, "PT-Sol external SHA-256")
    _digest(pt_sol0_report_sha256, "PT-Sol report SHA-256")
    _digest(pt_sol0_execution_git, "PT-Sol execution Git", length=40)
    body = {
        "schema": PACKET_SCHEMA,
        "source_git": source_git,
        "population_manifest": {
            "external_sha256": _sha_bytes(population_manifest_raw),
            "manifest_sha256": population["manifest_sha256"],
            "group_count": population["group_count"],
            "candidate_count": population["candidate_count"],
            "fold_counts": population["fold_counts"],
            "source_counts": population["source_counts"],
            "source_fold_counts": population["source_fold_counts"],
        },
        "audit_manifest": {
            "external_sha256": _sha_bytes(audit_manifest_raw),
            "manifest_sha256": audit["manifest_sha256"],
            "audit_count": audit["audit_count"],
            "total_bytes": audit["total_bytes"],
        },
        "source_schedules": {
            "production_policy": {
                "external_sha256": _sha_bytes(production_schedule_raw),
                "schedule_sha256": production["schedule_sha256"],
                "round_count": production["round_count"],
            },
            "mechanics_hard": {
                "external_sha256": _sha_bytes(mechanics_schedule_raw),
                "schedule_sha256": mechanics["schedule_sha256"],
                "round_count": mechanics["round_count"],
            },
        },
        "pt_sol0": {
            "external_sha256": pt_sol0_external_sha256,
            "report_sha256": pt_sol0_report_sha256,
            "execution_git": pt_sol0_execution_git,
            "state_source_only": True,
            "numeric_label_authority": False,
        },
        "selection_outcome_blind": True,
        "outcome_opened": False,
        "contains_private_complete_worlds": True,
        "world_occurrences_per_state_group": 1,
        "authority": dict(PACKET_AUTHORITY),
    }
    return {**body, "packet_sha256": _sha(body)}


def validate_population_packet_identity(value: Mapping[str, Any]) -> None:
    """Validate the closed packet and its internal digest without source I/O."""
    required = {
        "schema", "source_git", "population_manifest", "audit_manifest",
        "source_schedules", "pt_sol0", "selection_outcome_blind",
        "outcome_opened", "contains_private_complete_worlds",
        "world_occurrences_per_state_group", "authority", "packet_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != PACKET_SCHEMA \
            or value.get("authority") != PACKET_AUTHORITY \
            or value.get("selection_outcome_blind") is not True \
            or value.get("outcome_opened") is not False \
            or value.get("contains_private_complete_worlds") is not True \
            or value.get("world_occurrences_per_state_group") != 1:
        raise WorldAfterstatePopulationPacketError(
            "population packet identity drift")
    _digest(value.get("source_git"), "population packet source Git", length=40)
    population = value.get("population_manifest")
    audit = value.get("audit_manifest")
    schedules = value.get("source_schedules")
    teacher = value.get("pt_sol0")
    if type(population) is not dict or set(population) != {
            "external_sha256", "manifest_sha256", "group_count",
            "candidate_count", "fold_counts", "source_counts",
            "source_fold_counts"} \
            or type(audit) is not dict or set(audit) != {
                "external_sha256", "manifest_sha256", "audit_count",
                "total_bytes"} \
            or type(schedules) is not dict or set(schedules) != {
                "production_policy", "mechanics_hard"} \
            or type(teacher) is not dict or set(teacher) != {
                "external_sha256", "report_sha256", "execution_git",
                "state_source_only", "numeric_label_authority"} \
            or teacher.get("state_source_only") is not True \
            or teacher.get("numeric_label_authority") is not False:
        raise WorldAfterstatePopulationPacketError(
            "population packet binding schema drift")
    for binding in (population, audit):
        for key in ("external_sha256", "manifest_sha256"):
            _digest(binding.get(key), f"population packet {key}")
    for key in ("group_count", "candidate_count"):
        if isinstance(population.get(key), bool) \
                or not isinstance(population.get(key), int) \
                or population[key] <= 0:
            raise WorldAfterstatePopulationPacketError(
                "population packet count drift")
    for key in ("audit_count", "total_bytes"):
        if isinstance(audit.get(key), bool) \
                or not isinstance(audit.get(key), int) or audit[key] <= 0:
            raise WorldAfterstatePopulationPacketError(
                "population packet audit count drift")
    if audit["audit_count"] != population["candidate_count"]:
        raise WorldAfterstatePopulationPacketError(
            "population packet candidate/audit drift")
    for name, schedule in schedules.items():
        if type(schedule) is not dict or set(schedule) != {
                "external_sha256", "schedule_sha256", "round_count"}:
            raise WorldAfterstatePopulationPacketError(
                "population packet schedule schema drift")
        _digest(schedule.get("external_sha256"), f"{name} external SHA-256")
        _digest(schedule.get("schedule_sha256"), f"{name} schedule SHA-256")
        if isinstance(schedule.get("round_count"), bool) \
                or not isinstance(schedule.get("round_count"), int) \
                or schedule["round_count"] <= 0:
            raise WorldAfterstatePopulationPacketError(
                "population packet schedule count drift")
    _digest(teacher.get("external_sha256"), "PT-Sol external SHA-256")
    _digest(teacher.get("report_sha256"), "PT-Sol report SHA-256")
    _digest(teacher.get("execution_git"), "PT-Sol execution Git", length=40)
    _digest(value.get("packet_sha256"), "population packet SHA-256")
    body = {key: item for key, item in value.items()
            if key != "packet_sha256"}
    if value["packet_sha256"] != _sha(body):
        raise WorldAfterstatePopulationPacketError(
            "population packet digest drift")


def validate_population_packet(
        value: Mapping[str, Any], *, population_manifest_raw: bytes,
        audit_manifest_raw: bytes, production_schedule_raw: bytes,
        mechanics_schedule_raw: bytes) -> None:
    validate_population_packet_identity(value)
    teacher = value.get("pt_sol0", {})
    expected = build_population_packet(
        source_git=value.get("source_git"),
        population_manifest_raw=population_manifest_raw,
        audit_manifest_raw=audit_manifest_raw,
        production_schedule_raw=production_schedule_raw,
        mechanics_schedule_raw=mechanics_schedule_raw,
        pt_sol0_external_sha256=teacher.get("external_sha256"),
        pt_sol0_report_sha256=teacher.get("report_sha256"),
        pt_sol0_execution_git=teacher.get("execution_git"))
    if canonical_json_bytes(dict(value)) != canonical_json_bytes(expected):
        raise WorldAfterstatePopulationPacketError(
            "population packet reconstruction drift")


__all__ = [
    "PACKET_AUTHORITY", "PACKET_SCHEMA",
    "WorldAfterstatePopulationPacketError", "build_population_packet",
    "validate_population_packet", "validate_population_packet_identity",
]

"""Outcome-blind population and capacity protocol for Value-Afterstate V2.

This module contains no engine driver, labels, model, filesystem writer, audit
reader, or execution authority.  It makes the design's independent-deal
arithmetic and capacity-selected tier a small typed contract that can be
witnessed before the expensive pipeline exists.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Mapping, Sequence

from .belief_contract import canonical_json_bytes


PROTOCOL_SCHEMA = "world-afterstate-v2-protocol-v1"
STATE_SCHEMA = "world-afterstate-v2-state-candidate-v1"
CAPACITY_SCHEMA = "world-afterstate-v2-capacity-tier-v1"
P0_DEALS = 96
P0_PER_CELL = 8
P0_CELLS = tuple(
    (phase, position, role)
    for phase in ("early", "middle", "late")
    for position in ("lead", "follow")
    for role in ("attacker", "defender")
)
CAPACITY_HOST_LOGICAL_CPUS = 16
LABEL_WALL_SECONDS_MAX = 3 * 60 * 60
LABEL_CPU_SECONDS_MAX = 48 * 60 * 60
COMPLETE_DAG_WALL_SECONDS_MAX = 6 * 60 * 60
SCIENTIFIC_SERVICE_SECONDS = 12 * 60 * 60
MEMORY_PERCENT_MAX = 85
DISK_RETAIN_PERCENT_MIN = 25

AUTHORITY = {
    "data_collection_authorized": False,
    "capacity_execution_authorized": False,
    "training_authorized": False,
    "audit_opening_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
}


class WorldAfterstateV2ProtocolError(ValueError):
    """A tier, state selection, capacity receipt, or authority drifted."""


def _digest(value: object, label: str) -> str:
    if (type(value) is not str or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise WorldAfterstateV2ProtocolError(f"{label} drift")
    return value


def _strict_int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise WorldAfterstateV2ProtocolError(f"{label} drift")
    return value


@dataclass(frozen=True)
class TierSpecV2:
    name: str
    natural_fit: int
    diverse_fit: int
    mechanics_fit: int
    select: int
    audit: int

    def validate(self) -> None:
        if self.name not in ("D256", "D512", "D1024"):
            raise WorldAfterstateV2ProtocolError("tier name drift")
        for label, value in (
                ("natural fit", self.natural_fit),
                ("diverse fit", self.diverse_fit),
                ("mechanics fit", self.mechanics_fit),
                ("select", self.select), ("audit", self.audit)):
            _strict_int(value, f"tier {label}")
        expected = {
            "D256": (128, 0, 32, 48, 48),
            "D512": (256, 64, 64, 64, 64),
            "D1024": (512, 128, 128, 128, 128),
        }[self.name]
        if (self.natural_fit, self.diverse_fit, self.mechanics_fit,
                self.select, self.audit) != expected:
            raise WorldAfterstateV2ProtocolError("tier population drift")

    @property
    def fit(self) -> int:
        self.validate()
        return self.natural_fit + self.diverse_fit + self.mechanics_fit

    @property
    def total(self) -> int:
        self.validate()
        return self.fit + self.select + self.audit

    def payload(self) -> dict[str, object]:
        self.validate()
        return {
            "name": self.name, "natural_fit": self.natural_fit,
            "diverse_fit": self.diverse_fit,
            "mechanics_fit": self.mechanics_fit, "fit": self.fit,
            "select": self.select, "audit": self.audit,
            "total": self.total,
        }


TIER_SPECS = tuple(
    TierSpecV2(*values) for values in (
        ("D256", 128, 0, 32, 48, 48),
        ("D512", 256, 64, 64, 64, 64),
        ("D1024", 512, 128, 128, 128, 128),
    )
)
for _tier in TIER_SPECS:
    _tier.validate()


@dataclass(frozen=True)
class StateCandidateV2:
    deal_sha256: str
    state_sha256: str
    source: str
    split: str
    phase: str
    position: str
    role: str
    legal_candidate_count: int
    schema: str = STATE_SCHEMA

    def validate(self) -> None:
        _digest(self.deal_sha256, "state deal SHA-256")
        _digest(self.state_sha256, "state SHA-256")
        if self.schema != STATE_SCHEMA \
                or self.source not in ("natural", "diverse", "mechanics") \
                or self.split not in ("fit", "select", "audit") \
                or self.phase not in ("early", "middle", "late") \
                or self.position not in ("lead", "follow") \
                or self.role not in ("attacker", "defender"):
            raise WorldAfterstateV2ProtocolError("state stratum drift")
        if _strict_int(
                self.legal_candidate_count,
                "state legal candidate count") < 2:
            raise WorldAfterstateV2ProtocolError(
                "state lacks two legal comparison actions")
        if self.split != "fit" and self.source != "natural":
            raise WorldAfterstateV2ProtocolError(
                "select and audit states must be natural")

    @property
    def cell(self) -> tuple[str, str, str]:
        self.validate()
        return (self.phase, self.position, self.role)


def select_one_state_per_deal(
        candidates: Sequence[StateCandidateV2], *,
        required_cells: Mapping[str, tuple[str, str, str]]) \
        -> tuple[StateCandidateV2, ...]:
    """Choose the smallest state hash in each preassigned deal stratum.

    The closed input type intentionally has no label, continuation result,
    action utility, model prediction, or terminal-outcome field.
    """
    if type(candidates) not in (list, tuple) or not candidates \
            or type(required_cells) is not dict or not required_cells:
        raise WorldAfterstateV2ProtocolError("state selection request drift")
    normalized_cells: dict[str, tuple[str, str, str]] = {}
    for deal, cell in required_cells.items():
        _digest(deal, "assigned deal SHA-256")
        if type(cell) is not tuple or len(cell) != 3 or cell not in P0_CELLS:
            raise WorldAfterstateV2ProtocolError("assigned state cell drift")
        normalized_cells[deal] = cell
    by_deal: dict[str, list[StateCandidateV2]] = {
        deal: [] for deal in normalized_cells}
    seen_states = set()
    for candidate in candidates:
        if type(candidate) is not StateCandidateV2:
            raise WorldAfterstateV2ProtocolError(
                "state selection candidate type drift")
        candidate.validate()
        if candidate.state_sha256 in seen_states:
            raise WorldAfterstateV2ProtocolError("duplicate state candidate")
        seen_states.add(candidate.state_sha256)
        if candidate.deal_sha256 not in by_deal:
            raise WorldAfterstateV2ProtocolError(
                "unassigned deal entered state selection")
        if candidate.cell == normalized_cells[candidate.deal_sha256]:
            by_deal[candidate.deal_sha256].append(candidate)
    result = []
    for deal in sorted(by_deal):
        eligible = by_deal[deal]
        if not eligible:
            raise WorldAfterstateV2ProtocolError(
                "assigned deal has no eligible state")
        result.append(min(eligible, key=lambda value: value.state_sha256))
    if len({value.deal_sha256 for value in result}) != len(result):
        raise WorldAfterstateV2ProtocolError("multiple states selected per deal")
    return tuple(result)


def validate_p0_population(states: Sequence[StateCandidateV2]) -> None:
    if type(states) not in (list, tuple) or len(states) != P0_DEALS:
        raise WorldAfterstateV2ProtocolError("P0 deal population drift")
    deals = set()
    counts = {cell: 0 for cell in P0_CELLS}
    for state in states:
        if type(state) is not StateCandidateV2:
            raise WorldAfterstateV2ProtocolError("P0 state type drift")
        state.validate()
        if state.source != "natural" or state.split != "fit" \
                or state.deal_sha256 in deals:
            raise WorldAfterstateV2ProtocolError("P0 identity drift")
        deals.add(state.deal_sha256)
        counts[state.cell] += 1
    if any(count != P0_PER_CELL for count in counts.values()):
        raise WorldAfterstateV2ProtocolError("P0 cell balance drift")


@dataclass(frozen=True)
class CapacityTierReceiptV2:
    tier: str
    host_logical_cpus: int
    exact_source_supply: bool
    byte_identical: bool
    outcomes_opened: bool
    all_core_gate_passed: bool
    label_wall_seconds: int
    label_cpu_seconds: int
    complete_dag_wall_seconds: int
    service_wall_seconds: int
    peak_memory_bytes: int
    memory_limit_bytes: int
    composed_artifact_bytes: int
    free_disk_bytes_before: int
    schema: str = CAPACITY_SCHEMA

    def validate(self) -> None:
        if self.schema != CAPACITY_SCHEMA \
                or self.tier not in {tier.name for tier in TIER_SPECS} \
                or self.host_logical_cpus != CAPACITY_HOST_LOGICAL_CPUS \
                or type(self.exact_source_supply) is not bool \
                or type(self.byte_identical) is not bool \
                or type(self.outcomes_opened) is not bool \
                or type(self.all_core_gate_passed) is not bool:
            raise WorldAfterstateV2ProtocolError("capacity identity drift")
        for label, value in (
                ("label wall", self.label_wall_seconds),
                ("label CPU", self.label_cpu_seconds),
                ("complete DAG wall", self.complete_dag_wall_seconds),
                ("service wall", self.service_wall_seconds),
                ("peak memory", self.peak_memory_bytes),
                ("memory limit", self.memory_limit_bytes),
                ("artifact bytes", self.composed_artifact_bytes),
                ("free disk", self.free_disk_bytes_before)):
            _strict_int(value, f"capacity {label}", minimum=1)
        if self.service_wall_seconds != SCIENTIFIC_SERVICE_SECONDS:
            raise WorldAfterstateV2ProtocolError("capacity service cap drift")

    @property
    def eligible(self) -> bool:
        self.validate()
        label_economics = self.tier != "D256" or (
            self.label_wall_seconds <= LABEL_WALL_SECONDS_MAX
            and self.label_cpu_seconds <= LABEL_CPU_SECONDS_MAX)
        return (
            self.exact_source_supply
            and self.byte_identical
            and not self.outcomes_opened
            and self.all_core_gate_passed
            and label_economics
            and self.complete_dag_wall_seconds <= COMPLETE_DAG_WALL_SECONDS_MAX
            and self.complete_dag_wall_seconds * 2
            <= self.service_wall_seconds
            and self.peak_memory_bytes * 100
            <= self.memory_limit_bytes * MEMORY_PERCENT_MAX
            and self.composed_artifact_bytes * 100
            <= self.free_disk_bytes_before * (100 - DISK_RETAIN_PERCENT_MIN)
        )


def choose_capacity_tier(
        receipts: Sequence[CapacityTierReceiptV2]) -> TierSpecV2:
    if type(receipts) not in (list, tuple) or len(receipts) != len(TIER_SPECS) \
            or any(type(receipt) is not CapacityTierReceiptV2
                   for receipt in receipts):
        raise WorldAfterstateV2ProtocolError("capacity receipt population drift")
    by_name = {receipt.tier: receipt for receipt in receipts}
    if set(by_name) != {tier.name for tier in TIER_SPECS}:
        raise WorldAfterstateV2ProtocolError("capacity tier population drift")
    if any(receipt.outcomes_opened for receipt in receipts):
        raise WorldAfterstateV2ProtocolError(
            "capacity selection refuses opened outcomes")
    eligible = [tier for tier in TIER_SPECS if by_name[tier.name].eligible]
    if not eligible or not by_name["D256"].eligible:
        raise WorldAfterstateV2ProtocolError("D256 capacity minimum did not fit")
    return eligible[-1]


def protocol_payload() -> dict[str, object]:
    body = {
        "schema": PROTOCOL_SCHEMA,
        "tiers": [tier.payload() for tier in TIER_SPECS],
        "p0_deals": P0_DEALS,
        "p0_per_cell": P0_PER_CELL,
        "p0_cells": [list(cell) for cell in P0_CELLS],
        "capacity_host_logical_cpus": CAPACITY_HOST_LOGICAL_CPUS,
        "label_wall_seconds_max": LABEL_WALL_SECONDS_MAX,
        "label_cpu_seconds_max": LABEL_CPU_SECONDS_MAX,
        "complete_dag_wall_seconds_max": COMPLETE_DAG_WALL_SECONDS_MAX,
        "scientific_service_seconds": SCIENTIFIC_SERVICE_SECONDS,
        "memory_percent_max": MEMORY_PERCENT_MAX,
        "disk_retain_percent_min": DISK_RETAIN_PERCENT_MIN,
        "authority": dict(AUTHORITY),
    }
    return {**body, "protocol_sha256": hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()}


__all__ = [
    "AUTHORITY", "CAPACITY_HOST_LOGICAL_CPUS", "CapacityTierReceiptV2",
    "P0_CELLS", "P0_DEALS", "P0_PER_CELL", "STATE_SCHEMA", "TIER_SPECS",
    "StateCandidateV2", "TierSpecV2", "WorldAfterstateV2ProtocolError",
    "choose_capacity_tier", "protocol_payload", "select_one_state_per_deal",
    "validate_p0_population",
]

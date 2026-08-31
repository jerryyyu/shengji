"""Outcome-blind population and capacity protocol for Value-Afterstate V2.

This module contains no engine driver, labels, model, filesystem writer, audit
reader, or execution authority.  It makes the design's independent-deal
arithmetic and capacity-selected tier a small typed contract that can be
witnessed before the expensive pipeline exists.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
import hashlib
from typing import Mapping, Sequence

from ..engine.cards import RANKS
from .belief_contract import canonical_json_bytes


PROTOCOL_SCHEMA = "world-afterstate-v2-protocol-v1"
STATE_SCHEMA = "world-afterstate-v2-state-candidate-v1"
CAPACITY_SCHEMA = "world-afterstate-v2-capacity-tier-v1"
SLOT_SCHEMA = "world-afterstate-v2-population-slot-v1"
ATTEMPT_SCHEMA = "world-afterstate-v2-attempted-deal-v1"
P0_DEALS = 96
P0_PER_CELL = 8
P0_SUBSET_SCHEMA = "world-afterstate-v2-p0-canonical-subset-v1"
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
TRUMP_MODES = ("S", "H", "D", "C", "NT")
MECHANICS_SURFACES = ("multi-card", "wide-ballot", "late/high-point")
SELECT_SUBFOLDS = ("epoch-select", "precision-select")
STATE_SOURCES = ("natural", "pt-sol", "pt-luna", "human", "mechanics")
PRIOR_POINTS_BUCKETS = ("0-39", "40-79", "80+")

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


def prior_points_bucket(attacker_points: object) -> str:
    """Return the reviewed natural-fit-prior bucket from public points."""
    points = _strict_int(attacker_points, "public attacker points")
    return "0-39" if points < 40 else ("40-79" if points < 80 else "80+")


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


def _tier_groups(tier: TierSpecV2) \
        -> tuple[tuple[str, str, str, int], ...]:
    """Return the literal split/source slot groups in frozen order."""
    tier.validate()
    diverse = {
        "D256": (),
        "D512": (
            ("diverse-fit-sol", "fit", "pt-sol", 32),
            ("diverse-fit-luna", "fit", "pt-luna", 16),
            ("diverse-fit-human", "fit", "human", 16),
        ),
        "D1024": (
            ("diverse-fit-sol", "fit", "pt-sol", 64),
            ("diverse-fit-luna", "fit", "pt-luna", 32),
            ("diverse-fit-human", "fit", "human", 32),
        ),
    }[tier.name]
    return (
        ("natural-fit", "fit", "natural", tier.natural_fit),
        *diverse,
        ("mechanics-fit", "fit", "mechanics", tier.mechanics_fit),
        ("natural-select", "select", "natural", tier.select),
        ("natural-audit", "audit", "natural", tier.audit),
    )


@dataclass(frozen=True)
class PopulationSlotV2:
    """One pre-play split/source/stratum slot in the immutable population."""

    tier: str
    group: str
    split: str
    source: str
    ordinal: int
    phase: str | None
    position: str | None
    role: str | None
    mechanics_surface: str | None
    trump_rank: str
    trump_mode: str
    select_subfold: str | None
    schema: str = SLOT_SCHEMA

    def validate(self) -> None:
        tiers = {tier.name: tier for tier in TIER_SPECS}
        if self.schema != SLOT_SCHEMA or self.tier not in tiers \
                or self.split not in ("fit", "select", "audit") \
                or self.source not in STATE_SOURCES \
                or self.trump_rank not in RANKS \
                or self.trump_mode not in TRUMP_MODES:
            raise WorldAfterstateV2ProtocolError("population slot identity drift")
        _strict_int(self.ordinal, "population slot ordinal")
        group_rows = {
            group: (split, source, count)
            for group, split, source, count in _tier_groups(tiers[self.tier])
        }
        if self.group not in group_rows \
                or group_rows[self.group][:2] != (self.split, self.source) \
                or self.ordinal >= group_rows[self.group][2]:
            raise WorldAfterstateV2ProtocolError(
                "population slot group drift")
        if self.source == "mechanics":
            if (self.group != "mechanics-fit" or self.split != "fit"
                    or self.mechanics_surface not in MECHANICS_SURFACES
                    or any(value is not None for value in (
                        self.phase, self.position, self.role,
                        self.select_subfold))):
                raise WorldAfterstateV2ProtocolError(
                    "mechanics slot stratum drift")
        else:
            cell = (self.phase, self.position, self.role)
            if cell not in P0_CELLS or self.mechanics_surface is not None:
                raise WorldAfterstateV2ProtocolError(
                    "population slot cell drift")
            expected_subfold = self.split == "select"
            if expected_subfold != (self.select_subfold in SELECT_SUBFOLDS):
                raise WorldAfterstateV2ProtocolError(
                    "population select subfold drift")
        if self.split != "fit" and self.source != "natural":
            raise WorldAfterstateV2ProtocolError(
                "select and audit slots must be natural")

    @property
    def cell(self) -> tuple[str, str, str] | None:
        self.validate()
        return (None if self.phase is None else
                (self.phase, self.position, self.role))  # type: ignore[return-value]

    @property
    def fit_pair_id(self) -> str:
        """Return the frozen adjacent-pair identity for a fit slot.

        Pair identity is deliberately derived only from the canonical slot
        ledger.  Select and audit slots have separate construction rules and
        therefore cannot be used as world-control pair members.
        """
        self.validate()
        if self.split != "fit":
            raise WorldAfterstateV2ProtocolError(
                "fit pair identity requires a fit slot")
        return f"{self.tier}:{self.group}:{self.ordinal // 2}"

    @property
    def pair_id(self) -> str:
        """Stable short alias for callers serializing slot pair identity."""
        return self.fit_pair_id

    def payload(self) -> dict[str, object]:
        self.validate()
        return {
            "schema": self.schema, "tier": self.tier, "group": self.group,
            "split": self.split, "source": self.source,
            "ordinal": self.ordinal, "phase": self.phase,
            "position": self.position, "role": self.role,
            "mechanics_surface": self.mechanics_surface,
            "trump_rank": self.trump_rank, "trump_mode": self.trump_mode,
            "select_subfold": self.select_subfold,
        }

    @property
    def slot_sha256(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.payload())).hexdigest()


def _raw_slot_ledger(tier: TierSpecV2) -> tuple[PopulationSlotV2, ...]:
    result = []
    for group, split, source, count in _tier_groups(tier):
        for ordinal in range(count):
            if split == "select":
                pair = ordinal // 2
                cell = P0_CELLS[pair % len(P0_CELLS)]
                rank = RANKS[pair % len(RANKS)]
                mode = TRUMP_MODES[pair % len(TRUMP_MODES)]
                subfold = SELECT_SUBFOLDS[ordinal % 2]
                surface = None
            elif source == "mechanics":
                cell = (None, None, None)
                pair = ordinal // 2
                rank = RANKS[pair % len(RANKS)]
                mode = TRUMP_MODES[pair % len(TRUMP_MODES)]
                subfold = None
                surface = MECHANICS_SURFACES[
                    pair % len(MECHANICS_SURFACES)]
            else:
                pair = ordinal // 2
                cell = P0_CELLS[pair % len(P0_CELLS)]
                rank = RANKS[pair % len(RANKS)]
                mode = TRUMP_MODES[pair % len(TRUMP_MODES)]
                subfold = None
                surface = None
            result.append(PopulationSlotV2(
                tier=tier.name, group=group, split=split, source=source,
                ordinal=ordinal, phase=cell[0], position=cell[1], role=cell[2],
                mechanics_surface=surface, trump_rank=rank, trump_mode=mode,
                select_subfold=subfold))
    return tuple(result)


def build_population_slot_ledger(tier: TierSpecV2) \
        -> tuple[PopulationSlotV2, ...]:
    if type(tier) is not TierSpecV2:
        raise WorldAfterstateV2ProtocolError("population tier type drift")
    result = _raw_slot_ledger(tier)
    validate_population_slot_ledger(result, tier=tier)
    return result


def validate_population_slot_ledger(
        slots: Sequence[PopulationSlotV2], *, tier: TierSpecV2) -> None:
    if type(tier) is not TierSpecV2 or type(slots) not in (list, tuple) \
            or len(slots) != tier.total \
            or any(type(slot) is not PopulationSlotV2 for slot in slots):
        raise WorldAfterstateV2ProtocolError("population slot ledger drift")
    expected = _raw_slot_ledger(tier)
    for slot in slots:
        slot.validate()
    if tuple(slots) != expected \
            or len({slot.slot_sha256 for slot in slots}) != len(slots):
        raise WorldAfterstateV2ProtocolError("population slot derivation drift")
    # Fit slots are an explicit adjacent-pair design.  Keep this check
    # separate from equality with the derivation so a mutated ordinal/axis
    # cannot silently become a new valid geometry.
    for group, split, _source, count in _tier_groups(tier):
        if split != "fit":
            continue
        if count % 2:
            raise WorldAfterstateV2ProtocolError(
                "fit slot group count is not even")
        members = [slot for slot in slots if slot.group == group]
        if len(members) != count:
            raise WorldAfterstateV2ProtocolError("fit slot group coverage drift")
        for index in range(0, count, 2):
            left, right = members[index:index + 2]
            if left.fit_pair_id != right.fit_pair_id:
                raise WorldAfterstateV2ProtocolError("fit slot pair drift")
            if left.source == "mechanics":
                axes = (left.mechanics_surface, left.trump_rank,
                        left.trump_mode)
                right_axes = (right.mechanics_surface, right.trump_rank,
                              right.trump_mode)
            else:
                axes = (left.cell, left.trump_rank, left.trump_mode)
                right_axes = (right.cell, right.trump_rank, right.trump_mode)
            if axes != right_axes or left.slot_sha256 == right.slot_sha256:
                raise WorldAfterstateV2ProtocolError("fit slot pair geometry drift")
    select = [slot for slot in slots if slot.split == "select"]
    censuses = {}
    for subfold in SELECT_SUBFOLDS:
        censuses[subfold] = Counter(
            (slot.cell, slot.trump_rank, slot.trump_mode)
            for slot in select if slot.select_subfold == subfold)
    if censuses[SELECT_SUBFOLDS[0]] != censuses[SELECT_SUBFOLDS[1]] \
            or sum(censuses[SELECT_SUBFOLDS[0]].values()) * 2 != tier.select:
        raise WorldAfterstateV2ProtocolError(
            "population select census mismatch")


def attempted_deal_identity(
        population_namespace_sha256: str, slot: PopulationSlotV2,
        attempt_index: int) -> dict[str, object]:
    """Derive an outcome-blind deal identity inside one immutable slot."""
    _digest(population_namespace_sha256, "population namespace SHA-256")
    if type(slot) is not PopulationSlotV2:
        raise WorldAfterstateV2ProtocolError("attempted deal slot type drift")
    slot.validate()
    _strict_int(attempt_index, "attempted deal index")
    body = {
        "schema": ATTEMPT_SCHEMA,
        "population_namespace_sha256": population_namespace_sha256,
        "slot_sha256": slot.slot_sha256,
        "attempt_index": attempt_index,
    }
    digest = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    return {**body, "deal_sha256": digest,
            "engine_seed": int(digest[:16], 16) & ((1 << 63) - 1)}


@lru_cache(maxsize=1)
def _canonical_fit_slot_index() -> dict[str, tuple[PopulationSlotV2, ...]]:
    index: dict[str, list[PopulationSlotV2]] = {}
    for tier in TIER_SPECS:
        for slot in build_population_slot_ledger(tier):
            if slot.split == "fit":
                index.setdefault(slot.slot_sha256, []).append(slot)
    return {digest: tuple(slots) for digest, slots in index.items()}


def fit_slot_from_slot_sha256(slot_sha256: object) -> PopulationSlotV2:
    """Resolve the complete canonical fit slot, not only its pair label."""
    _digest(slot_sha256, "fit slot SHA-256")
    matches = _canonical_fit_slot_index().get(slot_sha256, ())
    if len(matches) != 1:
        raise WorldAfterstateV2ProtocolError("unknown canonical fit slot")
    return matches[0]


def fit_pair_id_from_slot_sha256(slot_sha256: object) -> str:
    """Resolve a fit pair ID through the immutable canonical slot ledgers."""
    return fit_slot_from_slot_sha256(slot_sha256).fit_pair_id


def fit_pair_id(slot: PopulationSlotV2) -> str:
    """Resolve a fit pair ID from a validated canonical slot object."""
    if type(slot) is not PopulationSlotV2:
        raise WorldAfterstateV2ProtocolError("fit pair slot type drift")
    return fit_pair_id_from_slot_sha256(slot.slot_sha256)


@dataclass(frozen=True)
class StateCandidateV2:
    deal_sha256: str
    slot_sha256: str
    state_sha256: str
    source: str
    split: str
    phase: str
    position: str
    role: str
    trump_rank: str
    trump_mode: str
    select_subfold: str | None
    mechanics_surfaces: tuple[str, ...]
    legal_candidate_count: int
    schema: str = STATE_SCHEMA

    def validate(self) -> None:
        _digest(self.deal_sha256, "state deal SHA-256")
        _digest(self.slot_sha256, "state slot SHA-256")
        _digest(self.state_sha256, "state SHA-256")
        if self.schema != STATE_SCHEMA \
                or self.source not in STATE_SOURCES \
                or self.split not in ("fit", "select", "audit") \
                or self.phase not in ("early", "middle", "late") \
                or self.position not in ("lead", "follow") \
                or self.role not in ("attacker", "defender") \
                or self.trump_rank not in RANKS \
                or self.trump_mode not in TRUMP_MODES:
            raise WorldAfterstateV2ProtocolError("state stratum drift")
        if (self.split == "select") != (
                self.select_subfold in SELECT_SUBFOLDS) \
                or self.split != "select" and self.select_subfold is not None:
            raise WorldAfterstateV2ProtocolError(
                "state select subfold drift")
        if type(self.mechanics_surfaces) is not tuple \
                or len(set(self.mechanics_surfaces)) \
                != len(self.mechanics_surfaces) \
                or any(surface not in MECHANICS_SURFACES
                       for surface in self.mechanics_surfaces):
            raise WorldAfterstateV2ProtocolError(
                "state mechanics surface drift")
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
        required_slots: Mapping[str, PopulationSlotV2]) \
        -> tuple[StateCandidateV2, ...]:
    """Choose the smallest state hash satisfying each pre-play slot.

    The closed input type intentionally has no label, continuation result,
    action utility, model prediction, or terminal-outcome field.
    """
    if type(candidates) not in (list, tuple) or not candidates \
            or type(required_slots) is not dict or not required_slots:
        raise WorldAfterstateV2ProtocolError("state selection request drift")
    normalized_slots: dict[str, PopulationSlotV2] = {}
    for deal, slot in required_slots.items():
        _digest(deal, "assigned deal SHA-256")
        if type(slot) is not PopulationSlotV2:
            raise WorldAfterstateV2ProtocolError("assigned state slot drift")
        slot.validate()
        normalized_slots[deal] = slot
    if len({slot.slot_sha256 for slot in normalized_slots.values()}) \
            != len(normalized_slots) \
            or len({slot.tier for slot in normalized_slots.values()}) != 1:
        raise WorldAfterstateV2ProtocolError(
            "assigned state slot population drift")
    by_deal: dict[str, list[StateCandidateV2]] = {
        deal: [] for deal in normalized_slots}
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
        slot = normalized_slots[candidate.deal_sha256]
        if candidate.slot_sha256 != slot.slot_sha256 \
                or candidate.source != slot.source \
                or candidate.split != slot.split \
                or candidate.select_subfold != slot.select_subfold \
                or candidate.trump_rank != slot.trump_rank \
                or candidate.trump_mode != slot.trump_mode:
            raise WorldAfterstateV2ProtocolError(
                "state candidate slot binding drift")
        eligible = (
            slot.mechanics_surface in candidate.mechanics_surfaces
            if slot.mechanics_surface is not None
            else candidate.cell == slot.cell
        )
        if eligible:
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


def _state_candidate(value: object) -> StateCandidateV2:
    """Accept a state row or a validated-material carrier without importing it."""
    if type(value) is StateCandidateV2:
        return value
    state = getattr(value, "state", None)
    if type(state) is StateCandidateV2:
        return state
    raise WorldAfterstateV2ProtocolError(
        "canonical P0 subset state type drift")


def _validate_complete_natural_fit_population(
        population: Sequence[StateCandidateV2], *, tier: TierSpecV2) \
        -> dict[str, StateCandidateV2]:
    """Validate the complete pre-label natural-fit slot population."""
    if type(tier) is not TierSpecV2:
        raise WorldAfterstateV2ProtocolError(
            "canonical P0 subset requires exact tier")
    tier.validate()
    if type(population) not in (list, tuple) \
            or len(population) != tier.natural_fit:
        raise WorldAfterstateV2ProtocolError(
            "canonical P0 subset requires complete natural-fit population")
    ledger = tuple(slot for slot in build_population_slot_ledger(tier)
                   if slot.group == "natural-fit")
    by_slot = {slot.slot_sha256: slot for slot in ledger}
    if len(by_slot) != tier.natural_fit:
        raise WorldAfterstateV2ProtocolError(
            "canonical P0 subset natural-fit slot ledger drift")
    by_deal: dict[str, StateCandidateV2] = {}
    seen_slots: set[str] = set()
    for value in population:
        state = _state_candidate(value)
        state.validate()
        if state.source != "natural" or state.split != "fit":
            raise WorldAfterstateV2ProtocolError(
                "canonical P0 subset requires natural fit states")
        if state.deal_sha256 in by_deal:
            raise WorldAfterstateV2ProtocolError(
                "canonical P0 subset duplicate deal")
        slot = by_slot.get(state.slot_sha256)
        if slot is None or state.slot_sha256 in seen_slots:
            raise WorldAfterstateV2ProtocolError(
                "canonical P0 subset must cover exact natural-fit slots")
        if (state.cell != slot.cell or state.trump_rank != slot.trump_rank
                or state.trump_mode != slot.trump_mode):
            raise WorldAfterstateV2ProtocolError(
                "canonical P0 subset slot binding drift")
        seen_slots.add(state.slot_sha256)
        by_deal[state.deal_sha256] = state
    if seen_slots != set(by_slot):
        raise WorldAfterstateV2ProtocolError(
            "canonical P0 subset must cover exact natural-fit slots")
    return by_deal


def select_p0_population(
        natural_fit_population: Sequence[StateCandidateV2], *,
        tier: TierSpecV2) -> tuple[StateCandidateV2, ...]:
    """Select exactly the eight smallest deal identities in every P0 cell.

    This selector is outcome-blind: it consumes only pre-label state identity
    and the exact tier's immutable natural-fit slot ledger.
    """
    by_deal = _validate_complete_natural_fit_population(
        natural_fit_population, tier=tier)
    by_cell: dict[tuple[str, str, str], list[StateCandidateV2]] = {
        cell: [] for cell in P0_CELLS}
    for state in by_deal.values():
        by_cell[state.cell].append(state)
    if any(len(values) < P0_PER_CELL for values in by_cell.values()):
        raise WorldAfterstateV2ProtocolError(
            "canonical P0 subset cell lacks eight natural-fit deals")
    selected = []
    for cell in P0_CELLS:
        selected.extend(sorted(by_cell[cell], key=lambda state: state.deal_sha256)
                        [:P0_PER_CELL])
    if len(selected) != P0_DEALS or len({s.deal_sha256 for s in selected}) != P0_DEALS:
        raise WorldAfterstateV2ProtocolError(
            "canonical P0 subset selection drift")
    return tuple(selected)


def validate_p0_population(
        states: Sequence[StateCandidateV2], *,
        natural_fit_population: Sequence[StateCandidateV2] | None = None,
        tier: TierSpecV2 | None = None) -> None:
    """Validate that ``states`` is the exact canonical pre-label P0 subset."""
    if natural_fit_population is None or tier is None:
        raise WorldAfterstateV2ProtocolError(
            "canonical P0 subset requires full population and exact tier")
    expected = select_p0_population(natural_fit_population, tier=tier)
    if type(states) not in (list, tuple) or len(states) != P0_DEALS:
        raise WorldAfterstateV2ProtocolError("canonical P0 subset population drift")
    if tuple(sorted(states, key=lambda state: state.deal_sha256)) != tuple(
            sorted(expected, key=lambda state: state.deal_sha256)):
        raise WorldAfterstateV2ProtocolError(
            "canonical P0 subset mismatch")


# Explicit names for callers that keep the subset operation separate from
# the legacy P0 validator.
select_canonical_p0_subset = select_p0_population
validate_canonical_p0_subset = validate_p0_population


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
    slot_ledger_sha256s = {
        tier.name: hashlib.sha256(canonical_json_bytes([
            slot.payload() for slot in build_population_slot_ledger(tier)
        ])).hexdigest()
        for tier in TIER_SPECS
    }
    body = {
        "schema": PROTOCOL_SCHEMA,
        "tiers": [tier.payload() for tier in TIER_SPECS],
        "p0_deals": P0_DEALS,
        "p0_per_cell": P0_PER_CELL,
        "p0_subset_schema": P0_SUBSET_SCHEMA,
        "p0_cells": [list(cell) for cell in P0_CELLS],
        "slot_schema": SLOT_SCHEMA,
        "attempt_schema": ATTEMPT_SCHEMA,
        "trump_ranks": list(RANKS),
        "trump_modes": list(TRUMP_MODES),
        "mechanics_surfaces": list(MECHANICS_SURFACES),
        "select_subfolds": list(SELECT_SUBFOLDS),
        "prior_points_buckets": list(PRIOR_POINTS_BUCKETS),
        "population_slot_ledger_sha256s": slot_ledger_sha256s,
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
    "ATTEMPT_SCHEMA", "AUTHORITY", "CAPACITY_HOST_LOGICAL_CPUS",
    "CapacityTierReceiptV2", "MECHANICS_SURFACES", "P0_CELLS", "P0_DEALS",
    "P0_PER_CELL", "P0_SUBSET_SCHEMA", "PRIOR_POINTS_BUCKETS",
    "PopulationSlotV2", "SELECT_SUBFOLDS", "SLOT_SCHEMA",
    "STATE_SCHEMA", "STATE_SOURCES", "TIER_SPECS", "TRUMP_MODES",
    "StateCandidateV2", "TierSpecV2", "WorldAfterstateV2ProtocolError",
    "attempted_deal_identity", "build_population_slot_ledger",
    "choose_capacity_tier", "protocol_payload", "select_one_state_per_deal",
    "fit_pair_id", "fit_pair_id_from_slot_sha256",
    "fit_slot_from_slot_sha256",
    "prior_points_bucket",
    "select_p0_population",
    "select_canonical_p0_subset", "validate_canonical_p0_subset",
    "validate_p0_population", "validate_population_slot_ledger",
]

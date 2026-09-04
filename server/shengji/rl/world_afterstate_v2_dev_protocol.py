"""Outcome-blind, authority-free D64 development subset for Value V2.

The input is the already materialized canonical D256 population.  This module
only authenticates its slot order and derives a fixed prefix from each frozen
group; it never opens an outcome or writes an artifact.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_population import PopulationMaterialV2
from .world_afterstate_v2_population_artifacts import material_sha256
from .world_afterstate_v2_protocol import (
    TIER_SPECS,
    PopulationSlotV2,
    build_population_slot_ledger,
)


DEV_SUBSET_SCHEMA = "world-afterstate-v2-dev-d64-subset-v1"
DEV_PARTIAL_SUBSET_SCHEMA = "world-afterstate-v2-dev-d64-partial-coverage-v1"
D256_TIER = "D256"
D64_TOTAL = 64
DEV_GROUP_COUNTS = (
    ("natural-fit", 32),
    ("mechanics-fit", 8),
    ("natural-select", 12),
    ("natural-audit", 12),
)
DEV_SUBFOLD_COUNTS = (("epoch-select", 6), ("precision-select", 6))


class WorldAfterstateV2DevProtocolError(ValueError):
    """A canonical D256 input or deterministic D64 subset drifted."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2DevProtocolError(f"{label} drift")
    return value


def _population_sha256(materials: Sequence[PopulationMaterialV2]) -> str:
    return _sha({
        "schema": DEV_SUBSET_SCHEMA,
        "tier": D256_TIER,
        "materials": [
            {
                "slot_sha256": material.slot_sha256,
                "deal_sha256": material.deal_sha256,
                "state_sha256": material.state_sha256,
                # Bind the complete canonical material, including prestate
                # and private afterstate audits, without copying those bytes
                # into the score-free subset receipt.
                "material_sha256": material_sha256(material),
            }
            for material in materials
        ],
    })


def _slot_state_matches(material: PopulationMaterialV2,
                        slot: PopulationSlotV2) -> None:
    state = material.state
    if (state.slot_sha256 != slot.slot_sha256
            or state.source != slot.source
            or state.split != slot.split
            or state.trump_rank != slot.trump_rank
            or state.trump_mode != slot.trump_mode
            or state.select_subfold != slot.select_subfold):
        raise WorldAfterstateV2DevProtocolError(
            "D256 material slot identity or axes drift")
    if slot.source == "mechanics":
        if slot.mechanics_surface not in state.mechanics_surfaces:
            raise WorldAfterstateV2DevProtocolError(
                "D256 mechanics surface drift")
    elif state.cell != slot.cell:
        raise WorldAfterstateV2DevProtocolError("D256 material cell drift")


def _validate_d256_population(
        materials: Sequence[PopulationMaterialV2],
        *,
        ledger: tuple[PopulationSlotV2, ...] | None = None,
        ) -> tuple[PopulationMaterialV2, ...]:
    if type(materials) not in (tuple, list) or len(materials) != 256:
        raise WorldAfterstateV2DevProtocolError(
            "D256 input must contain exactly 256 materials")
    if ledger is None:
        ledger = build_population_slot_ledger(TIER_SPECS[0])
    if len(ledger) != 256:
        raise WorldAfterstateV2DevProtocolError("D256 slot ledger drift")
    for index, (material, slot) in enumerate(zip(materials, ledger, strict=True)):
        if type(material) is not PopulationMaterialV2:
            raise WorldAfterstateV2DevProtocolError(
                f"D256 material type drift at index {index}")
        try:
            material.validate()
        except (TypeError, ValueError) as exc:
            raise WorldAfterstateV2DevProtocolError(
                f"D256 material validation refused at index {index}") from exc
        _slot_state_matches(material, slot)
    return tuple(materials)


def _selected_positions() -> tuple[tuple[str, int, int], ...]:
    offsets = {
        "natural-fit": 0,
        "mechanics-fit": 128,
        "natural-select": 160,
        "natural-audit": 208,
    }
    return tuple(
        (group, offsets[group], count)
        for group, count in DEV_GROUP_COUNTS
    )


@dataclass(frozen=True)
class DevSelectedIdentityV2:
    """One ordered slot/material identity in the D64 plan."""

    group: str
    split: str
    source: str
    ordinal: int
    select_subfold: str | None
    slot_sha256: str
    material_sha256: str
    state_sha256: str
    deal_sha256: str

    def payload(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class ValueV2DevProtocolReceipt:
    """Frozen identity manifest for the deterministic, target-free D64 plan."""

    input_d256_population_sha256: str
    selected_identities: tuple[DevSelectedIdentityV2, ...]
    per_group_counts: tuple[tuple[str, int], ...]
    per_subfold_counts: tuple[tuple[str, int], ...]
    materials: tuple[PopulationMaterialV2, ...]
    schema: str = DEV_SUBSET_SCHEMA

    @property
    def input_population_sha256(self) -> str:
        return self.input_d256_population_sha256

    @property
    def selected_slot_sha256s(self) -> tuple[str, ...]:
        return tuple(item.slot_sha256 for item in self.selected_identities)

    @property
    def selected_material_sha256s(self) -> tuple[str, ...]:
        return tuple(item.material_sha256 for item in self.selected_identities)

    @property
    def selected_materials(self) -> tuple[PopulationMaterialV2, ...]:
        return self.materials

    @property
    def subset(self) -> tuple[PopulationMaterialV2, ...]:
        return self.materials

    @property
    def canonical_sha256(self) -> str:
        return _sha(self.payload())

    @property
    def manifest_sha256(self) -> str:
        return self.canonical_sha256

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema,
            "input_d256_population_sha256": self.input_d256_population_sha256,
            "selected_identities": [item.payload()
                                     for item in self.selected_identities],
            "per_group_counts": [list(item) for item in self.per_group_counts],
            "per_subfold_counts": [list(item)
                                    for item in self.per_subfold_counts],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.payload())

    def validate(self) -> None:
        if self.schema != DEV_SUBSET_SCHEMA:
            raise WorldAfterstateV2DevProtocolError("D64 schema drift")
        _digest(self.input_d256_population_sha256,
                "D256 input population SHA-256")
        if type(self.selected_identities) is not tuple \
                or len(self.selected_identities) != D64_TOTAL \
                or type(self.materials) is not tuple \
                or len(self.materials) != D64_TOTAL \
                or any(type(item) is not DevSelectedIdentityV2
                       for item in self.selected_identities):
            raise WorldAfterstateV2DevProtocolError("D64 identity population drift")
        if self.per_group_counts != DEV_GROUP_COUNTS \
                or self.per_subfold_counts != DEV_SUBFOLD_COUNTS:
            raise WorldAfterstateV2DevProtocolError("D64 count manifest drift")
        ledger = build_population_slot_ledger(TIER_SPECS[0])
        expected_slots = tuple(
            ledger[index]
            for _group, start, count in _selected_positions()
            for index in range(start, start + count)
        )
        observed_group_counts: dict[str, int] = {}
        observed_subfold_counts: dict[str, int] = {}
        for material, identity, slot in zip(
                self.materials, self.selected_identities, expected_slots,
                strict=True):
            if (identity.group != slot.group
                    or identity.split != slot.split
                    or identity.source != slot.source
                    or identity.ordinal != slot.ordinal
                    or identity.select_subfold != slot.select_subfold
                    or identity.slot_sha256 != slot.slot_sha256):
                raise WorldAfterstateV2DevProtocolError(
                    "D64 selected slot identity drift")
            if type(material) is not PopulationMaterialV2:
                raise WorldAfterstateV2DevProtocolError("D64 material type drift")
            material.validate()
            if (material_sha256(material) != identity.material_sha256
                    or material.state_sha256 != identity.state_sha256
                    or material.slot_sha256 != identity.slot_sha256
                    or material.deal_sha256 != identity.deal_sha256):
                raise WorldAfterstateV2DevProtocolError(
                    "D64 selected material identity drift")
            observed_group_counts[identity.group] = \
                observed_group_counts.get(identity.group, 0) + 1
            if identity.select_subfold is not None:
                observed_subfold_counts[identity.select_subfold] = \
                    observed_subfold_counts.get(identity.select_subfold, 0) + 1
        if tuple(observed_group_counts.items()) != DEV_GROUP_COUNTS \
                or tuple(observed_subfold_counts.items()) != DEV_SUBFOLD_COUNTS:
            raise WorldAfterstateV2DevProtocolError("D64 selected count drift")
        if len({item.slot_sha256 for item in self.selected_identities}) != D64_TOTAL:
            raise WorldAfterstateV2DevProtocolError("D64 duplicate slot identity")


@dataclass(frozen=True)
class ValueV2DevPartialCoverageReceipt:
    """D64 identity artifact backed by incomplete, retained D256 coverage."""

    freeze_sha256: str
    population_namespace_sha256: str
    admission_sha256: str
    config_sha256: str
    accepted_slots: int
    missing_slots: tuple[dict[str, Any], ...]
    selected_identities: tuple[DevSelectedIdentityV2, ...]
    selected_shard_rows: tuple[dict[str, Any], ...]
    materials: tuple[PopulationMaterialV2, ...]
    orphan_started: tuple[dict[str, Any], ...] = ()
    schema: str = DEV_PARTIAL_SUBSET_SCHEMA

    @property
    def selected_materials(self) -> tuple[PopulationMaterialV2, ...]:
        return self.materials

    @property
    def manifest_sha256(self) -> str:
        return self.canonical_sha256

    @property
    def canonical_sha256(self) -> str:
        return _sha(self.payload())

    def payload(self) -> dict[str, Any]:
        self.validate()
        body = {
            "schema": self.schema, "coverage_complete": False,
            "tier": D256_TIER, "accepted_slots": self.accepted_slots,
            "missing_slot_count": len(self.missing_slots),
            "missing_slots": [dict(item) for item in self.missing_slots],
            "freeze_sha256": self.freeze_sha256,
            "population_namespace_sha256": self.population_namespace_sha256,
            "admission_sha256": self.admission_sha256,
            "config_sha256": self.config_sha256,
            "selected_identities": [item.payload() for item in self.selected_identities],
            "selected_shard_rows": [dict(item) for item in self.selected_shard_rows],
            "orphan_started": [dict(item) for item in self.orphan_started],
        }
        return body

    def validate(self) -> None:
        if self.schema != DEV_PARTIAL_SUBSET_SCHEMA \
                or self.accepted_slots != 255:
            raise WorldAfterstateV2DevProtocolError(
                "partial D256 coverage accounting drift")
        for value, label in ((self.freeze_sha256, "partial freeze SHA-256"),
                             (self.population_namespace_sha256,
                              "partial namespace SHA-256"),
                             (self.admission_sha256, "partial admission SHA-256"),
                             (self.config_sha256, "partial config SHA-256")):
            _digest(value, label)
        ledger = build_population_slot_ledger(TIER_SPECS[0])
        selected_positions = tuple(index for _group, start, count in
                                    _selected_positions()
                                    for index in range(start, start + count))
        expected_slots = tuple(ledger[index] for index in selected_positions)
        expected_by_sha = {slot.slot_sha256: {**slot.payload(),
                                              "slot_sha256": slot.slot_sha256}
                           for slot in ledger}
        observed = {item.get("slot_sha256") if type(item) is dict else None
                    for item in self.missing_slots}
        if any(type(item) is not dict or expected_by_sha.get(
                item.get("slot_sha256")) != item for item in self.missing_slots) \
                or len(observed) != len(self.missing_slots) \
                or observed.intersection({slot.slot_sha256 for slot in expected_slots}):
            raise WorldAfterstateV2DevProtocolError(
                "partial missing slot identity drift")
        if len(self.missing_slots) != 1:
            raise WorldAfterstateV2DevProtocolError(
                "partial missing slot count drift")
        if not (type(self.selected_identities) is tuple
                and len(self.selected_identities) == D64_TOTAL
                and type(self.selected_shard_rows) is tuple
                and len(self.selected_shard_rows) == D64_TOTAL
                and type(self.materials) is tuple
                and len(self.materials) == D64_TOTAL):
            raise WorldAfterstateV2DevProtocolError("partial selected population drift")
        for material, identity, row, slot in zip(
                self.materials, self.selected_identities,
                self.selected_shard_rows, expected_slots, strict=True):
            if type(identity) is not DevSelectedIdentityV2 \
                    or type(row) is not dict:
                raise WorldAfterstateV2DevProtocolError(
                    "partial selected row schema drift")
            if set(row) != {"schema", "relative_path", "tier", "split",
                            "source", "ordinal", "deal_sha256", "slot_sha256",
                            "state_sha256", "candidate_set_sha256", "byte_count",
                            "sha256", "material_sha256"}:
                raise WorldAfterstateV2DevProtocolError(
                    "partial selected row schema drift")
            if (row["tier"], row["split"], row["source"], row["ordinal"]) != (
                    slot.tier, slot.split, slot.source, slot.ordinal):
                raise WorldAfterstateV2DevProtocolError(
                    "partial selected shard row identity drift")
            for key in ("deal_sha256", "slot_sha256", "state_sha256",
                        "candidate_set_sha256", "sha256", "material_sha256"):
                _digest(row[key], f"partial selected {key}")
            if type(row["byte_count"]) is not int or isinstance(
                    row["byte_count"], bool) or row["byte_count"] <= 0:
                raise WorldAfterstateV2DevProtocolError(
                    "partial selected shard byte count drift")
            if (identity.group, identity.split, identity.source, identity.ordinal,
                    identity.select_subfold, identity.slot_sha256) != (
                        slot.group, slot.split, slot.source, slot.ordinal,
                        slot.select_subfold, slot.slot_sha256):
                raise WorldAfterstateV2DevProtocolError(
                    "partial selected slot identity drift")
            material.validate()
            if (material_sha256(material), material.state_sha256,
                    material.slot_sha256, material.deal_sha256) != (
                        identity.material_sha256, identity.state_sha256,
                        identity.slot_sha256, identity.deal_sha256):
                raise WorldAfterstateV2DevProtocolError(
                    "partial selected material identity drift")
            for key in ("slot_sha256", "state_sha256", "deal_sha256",
                        "material_sha256"):
                if row.get(key) != getattr(identity, key):
                    raise WorldAfterstateV2DevProtocolError(
                        "partial selected shard row drift")
        if len({item.slot_sha256 for item in self.selected_identities}) != D64_TOTAL:
            raise WorldAfterstateV2DevProtocolError(
                "partial duplicate selected slot identity")


def build_value_v2_dev_partial_protocol(
        coverage: Any) -> ValueV2DevPartialCoverageReceipt:
    """Build the fixed D64 subset from controller-authenticated shard bytes."""
    try:
        result = ValueV2DevPartialCoverageReceipt(
            freeze_sha256=coverage.freeze_sha256,
            population_namespace_sha256=coverage.population_namespace_sha256,
            admission_sha256=coverage.admission_sha256,
            config_sha256=coverage.config_sha256,
            accepted_slots=coverage.accepted_slots,
            missing_slots=tuple(dict(item) for item in coverage.missing_slots),
            selected_identities=tuple(
                DevSelectedIdentityV2(**dict(item))
                for item in coverage.selected_identities),
            selected_shard_rows=tuple(
                dict(item) for item in coverage.selected_shard_rows),
            materials=tuple(coverage.selected_materials),
            orphan_started=tuple(dict(item) for item in coverage.orphan_started))
        result.validate()
        return result
    except WorldAfterstateV2DevProtocolError:
        raise
    except Exception as exc:
        raise WorldAfterstateV2DevProtocolError(
            "partial coverage protocol construction refused") from exc


build_value_v2_dev_partial_subset = build_value_v2_dev_partial_protocol


def build_value_v2_dev_protocol(
        d256_population: Sequence[PopulationMaterialV2],
        ) -> ValueV2DevProtocolReceipt:
    """Validate canonical D256 and return its deterministic 64-material plan."""
    ledger = build_population_slot_ledger(TIER_SPECS[0])
    materials = _validate_d256_population(d256_population, ledger=ledger)
    selected: list[PopulationMaterialV2] = []
    selected_slots: list[PopulationSlotV2] = []
    for group, start, count in _selected_positions():
        selected.extend(materials[start:start + count])
        selected_slots.extend(ledger[start:start + count])
    if len(selected) != D64_TOTAL:
        raise WorldAfterstateV2DevProtocolError("D64 selection count drift")
    identities = tuple(
        DevSelectedIdentityV2(
            group=slot.group, split=slot.split, source=slot.source,
            ordinal=slot.ordinal, select_subfold=slot.select_subfold,
            slot_sha256=slot.slot_sha256,
            material_sha256=material_sha256(material),
            state_sha256=material.state_sha256, deal_sha256=material.deal_sha256)
        for material, slot in zip(selected, selected_slots, strict=True)
    )
    receipt = ValueV2DevProtocolReceipt(
        input_d256_population_sha256=_population_sha256(materials),
        selected_identities=identities,
        per_group_counts=DEV_GROUP_COUNTS,
        per_subfold_counts=DEV_SUBFOLD_COUNTS,
        materials=tuple(selected))
    receipt.validate()
    return receipt


def validate_value_v2_dev_protocol(
        d256_population: Sequence[PopulationMaterialV2],
        receipt: ValueV2DevProtocolReceipt,
        ) -> None:
    """Re-authenticate a receipt against the exact canonical D256 input."""
    if type(receipt) is not ValueV2DevProtocolReceipt:
        raise WorldAfterstateV2DevProtocolError("D64 receipt type drift")
    expected = build_value_v2_dev_protocol(d256_population)
    receipt.validate()
    if receipt.payload() != expected.payload() \
            or receipt.materials != expected.materials:
        raise WorldAfterstateV2DevProtocolError("D64 receipt selection drift")


# Concise aliases for callers that use "subset" rather than "protocol".
build_value_v2_dev_subset = build_value_v2_dev_protocol
derive_value_v2_dev_subset = build_value_v2_dev_protocol
validate_value_v2_dev_subset = validate_value_v2_dev_protocol


def select_value_v2_dev_subset(
        d256_population: Sequence[PopulationMaterialV2],
        ) -> tuple[PopulationMaterialV2, ...]:
    """Return just the selected materials for sequence-oriented callers."""
    return build_value_v2_dev_protocol(d256_population).materials


__all__ = [
    "D256_TIER", "D64_TOTAL", "DEV_GROUP_COUNTS", "DEV_SUBFOLD_COUNTS",
    "DEV_SUBSET_SCHEMA", "DEV_PARTIAL_SUBSET_SCHEMA", "DevSelectedIdentityV2",
    "ValueV2DevProtocolReceipt", "WorldAfterstateV2DevProtocolError",
    "build_value_v2_dev_protocol", "build_value_v2_dev_subset",
    "derive_value_v2_dev_subset",
    "select_value_v2_dev_subset",
    "validate_value_v2_dev_protocol", "validate_value_v2_dev_subset",
    "ValueV2DevPartialCoverageReceipt", "build_value_v2_dev_partial_protocol",
    "build_value_v2_dev_partial_subset",
]

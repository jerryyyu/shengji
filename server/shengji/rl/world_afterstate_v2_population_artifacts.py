"""Strict filesystem boundary for Value-Afterstate V2 population material.

The population material itself is deliberately score free.  This adapter only
serializes that closed type and seals it in immutable, content-addressed files;
it does not select, execute, label, or open any terminal result.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .belief_artifacts import publish_exclusive_bytes, stable_read_bytes
from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_population import (
    PopulationCandidateV2, PopulationMaterialV2,
)
from .world_afterstate_v2_protocol import (
    PopulationSlotV2, TIER_SPECS, build_population_slot_ledger,
)


MATERIAL_ARTIFACT_SCHEMA = "world-afterstate-v2-population-material-artifact-v1"
MANIFEST_SCHEMA = "world-afterstate-v2-population-manifest-v1"
POPULATION_MANIFEST_SCHEMA = MANIFEST_SCHEMA
POPULATION_MATERIAL_SCHEMA = MATERIAL_ARTIFACT_SCHEMA
MATERIAL_MAGIC = MATERIAL_ARTIFACT_SCHEMA
POPULATION_DIRNAME = "population"
MATERIAL_DIRNAME = "materials"
MANIFEST_NAME = "manifest.json"
PARTIAL_COVERAGE_SCHEMA = "world-afterstate-v2-population-partial-coverage-v1"
PARTIAL_COVERAGE_NAME = "partial-coverage.json"
PARTIAL_COVERAGE_DIRNAME = "population-controller"
COMMITMENT_NAME = "population.commitment"

AUTHORITY = {
    "data_collection_authorized": False,
    "audit_opening_authorized": False,
    "training_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "writer_authorized": False,
    "terminal_reconstruction_authorized": False,
}


class WorldAfterstateV2PopulationArtifactError(ValueError):
    """A material, manifest, path, or immutable publication drifted."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2PopulationArtifactError(f"{label} drift")
    return value


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WorldAfterstateV2PopulationArtifactError(
                "artifact JSON has duplicate key")
        result[key] = value
    return result


def _reject_number(value: str) -> None:
    raise WorldAfterstateV2PopulationArtifactError(
        f"artifact JSON contains invalid number {value}")


def _strict_json(raw: bytes, label: str) -> dict[str, Any]:
    if type(raw) is not bytes or not raw:
        raise WorldAfterstateV2PopulationArtifactError(f"{label} is empty")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_strict_object,
                           parse_float=_reject_number,
                           parse_constant=_reject_number)
    except WorldAfterstateV2PopulationArtifactError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorldAfterstateV2PopulationArtifactError(
            f"{label} is not strict JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstateV2PopulationArtifactError(
            f"{label} is not canonical JSON")
    return value


def _state_payload(material: PopulationMaterialV2) -> dict[str, Any]:
    state = material.state
    return {
        "schema": state.schema, "deal_sha256": state.deal_sha256,
        "slot_sha256": state.slot_sha256, "state_sha256": state.state_sha256,
        "source": state.source, "split": state.split, "phase": state.phase,
        "position": state.position, "role": state.role,
        "trump_rank": state.trump_rank, "trump_mode": state.trump_mode,
        "select_subfold": state.select_subfold,
        "mechanics_surfaces": list(state.mechanics_surfaces),
        "legal_candidate_count": state.legal_candidate_count,
    }


def _candidate_payload(candidate: PopulationCandidateV2) -> dict[str, Any]:
    return {
        "schema": candidate.schema, "candidate_index": candidate.candidate_index,
        "action_sha256": candidate.action_sha256,
        "audit_sha256": candidate.audit_sha256,
        "successor_sha256": candidate.successor_sha256,
        "origin": candidate.origin,
        "protected_incumbent": candidate.protected_incumbent,
    }


def population_material_bytes(material: PopulationMaterialV2) -> bytes:
    """Return the exact canonical bytes for one closed population material."""
    if type(material) is not PopulationMaterialV2:
        raise WorldAfterstateV2PopulationArtifactError("material type drift")
    try:
        material.validate()
    except (ValueError, TypeError) as exc:
        raise WorldAfterstateV2PopulationArtifactError(
            "material validation refused") from exc
    # Base64 is an unambiguous ASCII transport for arbitrary audit bytes.  The
    # decoded bytes are still independently checked by PopulationMaterialV2.
    value = {
        "schema": MATERIAL_ARTIFACT_SCHEMA,
        "material_schema": material.schema,
        "state": _state_payload(material),
        "candidate_set_sha256": material.candidate_set_sha256,
        "candidates": [_candidate_payload(candidate)
                       for candidate in material.candidates],
        "audit_raws_base64": [base64.b64encode(raw).decode("ascii")
                              for raw in material.audit_raws],
        "prestate": material.prestate,
    }
    return canonical_json_bytes(value)


def serialize_population_material_v2(material: PopulationMaterialV2) -> bytes:
    return population_material_bytes(material)


def _decode_b64(value: object) -> bytes:
    if type(value) is not str or not value or len(value) % 4 \
            or any(char not in
                   "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
                   for char in value):
        raise WorldAfterstateV2PopulationArtifactError(
            "material audit encoding drift")
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise WorldAfterstateV2PopulationArtifactError(
            "material audit encoding drift") from exc
    if base64.b64encode(raw).decode("ascii") != value:
        raise WorldAfterstateV2PopulationArtifactError(
            "material audit encoding drift")
    return raw


def reopen_population_material(raw: bytes) -> PopulationMaterialV2:
    """Strictly reconstruct and validate one serialized material."""
    value = _strict_json(raw, "population material")
    expected = {"schema", "material_schema", "state", "candidate_set_sha256",
                "candidates", "audit_raws_base64", "prestate"}
    if set(value) != expected or value["schema"] != MATERIAL_ARTIFACT_SCHEMA:
        raise WorldAfterstateV2PopulationArtifactError(
            "population material schema drift")
    state_value = value["state"]
    state_keys = {"schema", "deal_sha256", "slot_sha256", "state_sha256",
                  "source", "split", "phase", "position", "role",
                  "trump_rank", "trump_mode", "select_subfold",
                  "mechanics_surfaces", "legal_candidate_count"}
    if type(state_value) is not dict or set(state_value) != state_keys:
        raise WorldAfterstateV2PopulationArtifactError("material state drift")
    try:
        from .world_afterstate_v2_protocol import StateCandidateV2
        state = StateCandidateV2(
            deal_sha256=state_value["deal_sha256"],
            slot_sha256=state_value["slot_sha256"],
            state_sha256=state_value["state_sha256"],
            source=state_value["source"], split=state_value["split"],
            phase=state_value["phase"], position=state_value["position"],
            role=state_value["role"], trump_rank=state_value["trump_rank"],
            trump_mode=state_value["trump_mode"],
            select_subfold=state_value["select_subfold"],
            mechanics_surfaces=tuple(state_value["mechanics_surfaces"]),
            legal_candidate_count=state_value["legal_candidate_count"],
            schema=state_value["schema"])
    except (KeyError, TypeError, ValueError) as exc:
        raise WorldAfterstateV2PopulationArtifactError(
            "material state reconstruction drift") from exc
    candidate_values = value["candidates"]
    raws_value = value["audit_raws_base64"]
    if type(candidate_values) is not list or type(raws_value) is not list \
            or len(candidate_values) != len(raws_value):
        raise WorldAfterstateV2PopulationArtifactError(
            "material candidate population drift")
    candidates = []
    try:
        for candidate_value in candidate_values:
            candidate_keys = {"schema", "candidate_index", "action_sha256",
                              "audit_sha256", "successor_sha256", "origin",
                              "protected_incumbent"}
            if type(candidate_value) is not dict \
                    or set(candidate_value) != candidate_keys:
                raise WorldAfterstateV2PopulationArtifactError(
                    "material candidate schema drift")
            candidates.append(PopulationCandidateV2(**candidate_value))
        audit_raws = tuple(_decode_b64(item) for item in raws_value)
        material = PopulationMaterialV2(
            state=state,
            candidate_set_sha256=value["candidate_set_sha256"],
            candidates=tuple(candidates), audit_raws=audit_raws,
            prestate=value["prestate"], schema=value["material_schema"])
    except WorldAfterstateV2PopulationArtifactError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise WorldAfterstateV2PopulationArtifactError(
            "material reconstruction drift") from exc
    try:
        material.validate()
    except (ValueError, TypeError) as exc:
        raise WorldAfterstateV2PopulationArtifactError(
            "material typed reopen refused") from exc
    if population_material_bytes(material) != raw:
        raise WorldAfterstateV2PopulationArtifactError(
            "material byte-identical round trip drift")
    return material


reopen_serialized_population_material_v2 = reopen_population_material
reopen_population_material_artifact = reopen_population_material


def material_sha256(material: PopulationMaterialV2) -> str:
    return _sha(population_material_bytes(material))


def _root(root: Path) -> Path:
    if not isinstance(root, Path) or root.is_symlink() or not root.is_dir():
        raise WorldAfterstateV2PopulationArtifactError("artifact root drift")
    return root


def _directory(path: Path, *, create: bool = False) -> Path:
    if path.is_symlink():
        raise WorldAfterstateV2PopulationArtifactError(
            "artifact directory is a symlink")
    if create:
        try:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as exc:
            raise WorldAfterstateV2PopulationArtifactError(
                "artifact directory creation refused") from exc
    if path.is_symlink() or not path.is_dir():
        raise WorldAfterstateV2PopulationArtifactError(
            "artifact directory drift")
    return path


def _parent(root: Path, path: Path, *, create: bool = False) -> None:
    try:
        parts = path.relative_to(root).parts
    except ValueError as exc:
        raise WorldAfterstateV2PopulationArtifactError(
            "artifact path escapes root") from exc
    cursor = root
    for part in parts:
        cursor = cursor / part
        _directory(cursor, create=create)


def _material_path(root: Path, state_sha256: str) -> Path:
    _root(root)
    _digest(state_sha256, "state SHA-256")
    return root / POPULATION_DIRNAME / MATERIAL_DIRNAME \
        / f"state-{state_sha256}.json"


def population_material_path(root: Path, state_sha256: str) -> Path:
    return _material_path(root, state_sha256)


def _slot_for(material: PopulationMaterialV2, tier: str) -> PopulationSlotV2:
    tiers = {item.name: item for item in TIER_SPECS}
    if type(tier) is not str or tier not in tiers:
        raise WorldAfterstateV2PopulationArtifactError("tier identity drift")
    matches = tuple(slot for slot in build_population_slot_ledger(tiers[tier])
                   if slot.slot_sha256 == material.slot_sha256)
    if len(matches) != 1:
        raise WorldAfterstateV2PopulationArtifactError(
            "material slot/tier identity drift")
    slot = matches[0]
    if (slot.split, slot.source) != (material.state.split, material.state.source):
        raise WorldAfterstateV2PopulationArtifactError(
            "material split/source identity drift")
    return slot


def _infer_tier(material: PopulationMaterialV2) -> str:
    matches = []
    for tier in TIER_SPECS:
        try:
            matches.append(_slot_for(material, tier.name))
        except WorldAfterstateV2PopulationArtifactError:
            continue
    if len(matches) != 1:
        raise WorldAfterstateV2PopulationArtifactError(
            "material tier identity is ambiguous")
    return matches[0].tier


@dataclass(frozen=True)
class PopulationMaterialShardV2:
    relative_path: str
    tier: str
    split: str
    source: str
    ordinal: int
    deal_sha256: str
    slot_sha256: str
    state_sha256: str
    candidate_set_sha256: str
    byte_count: int
    sha256: str
    material_sha256: str
    schema: str = MATERIAL_ARTIFACT_SCHEMA

    def row(self) -> dict[str, Any]:
        return {"schema": self.schema, "relative_path": self.relative_path,
                "tier": self.tier, "split": self.split, "source": self.source,
                "ordinal": self.ordinal,
                "deal_sha256": self.deal_sha256, "slot_sha256": self.slot_sha256,
                "state_sha256": self.state_sha256,
                "candidate_set_sha256": self.candidate_set_sha256,
                "byte_count": self.byte_count, "sha256": self.sha256,
                "material_sha256": self.material_sha256}


def _shard_from_material(root: Path, material: PopulationMaterialV2,
                         *, tier: str) -> PopulationMaterialShardV2:
    if type(material) is not PopulationMaterialV2:
        raise WorldAfterstateV2PopulationArtifactError("material type drift")
    material.validate()
    slot = _slot_for(material, tier)
    raw = population_material_bytes(material)
    target = _material_path(root, material.state_sha256)
    _parent(root, target.parent, create=True)
    try:
        digest = publish_exclusive_bytes(target, raw)
        reread = stable_read_bytes(target)
    except (OSError, ValueError) as exc:
        raise WorldAfterstateV2PopulationArtifactError(
            "material shard publication refused") from exc
    if reread != raw or digest != _sha(raw):
        raise WorldAfterstateV2PopulationArtifactError(
            "material shard byte drift")
    return PopulationMaterialShardV2(
        relative_path=target.relative_to(root).as_posix(), tier=slot.tier,
        split=slot.split, source=slot.source, ordinal=slot.ordinal,
        deal_sha256=material.deal_sha256, slot_sha256=material.slot_sha256,
        state_sha256=material.state_sha256,
        candidate_set_sha256=material.candidate_set_sha256,
        byte_count=len(raw), sha256=digest, material_sha256=digest)


def publish_population_material(
        root: Path, material: PopulationMaterialV2, *, tier: str | None = None,
        freeze_sha256: str | None = None,
        population_namespace_sha256: str | None = None
        ) -> PopulationMaterialShardV2:
    # Freeze and namespace are manifest-level identities.  Accepting them at
    # shard publication is convenient for callers, but they are deliberately
    # not copied into the closed material payload.
    if freeze_sha256 is not None:
        _digest(freeze_sha256, "external freeze SHA-256")
    if population_namespace_sha256 is not None:
        _digest(population_namespace_sha256, "population namespace SHA-256")
    return _shard_from_material(_root(root), material,
                                tier=tier if tier is not None
                                else _infer_tier(material))


publish_population_material_shard = publish_population_material
publish_population_material_artifact = publish_population_material


def population_partial_coverage_path(root: Path) -> Path:
    """Return the separately named immutable incomplete-coverage artifact."""
    root = _root(root)
    return root / PARTIAL_COVERAGE_DIRNAME / PARTIAL_COVERAGE_NAME


def _partial_coverage_value(value: object) -> dict[str, Any]:
    if type(value) is not dict or value.get("schema") != PARTIAL_COVERAGE_SCHEMA:
        raise WorldAfterstateV2PopulationArtifactError(
            "partial coverage schema drift")
    expected = {"schema", "freeze_sha256", "population_namespace_sha256",
                "admission_sha256", "config_sha256", "tier",
                "coverage_complete", "accepted_slots", "missing_slot_count",
                "missing_slots", "selected_identities", "selected_shard_rows",
                "orphan_started", "coverage_sha256"}
    if set(value) != expected:
        raise WorldAfterstateV2PopulationArtifactError(
            "partial coverage field drift")
    if value.get("tier") != "D256" or value.get("coverage_complete") is not False \
            or type(value.get("accepted_slots")) is not int \
            or isinstance(value.get("accepted_slots"), bool) \
            or value["accepted_slots"] != 255 \
            or value.get("missing_slot_count") != 1 \
            or type(value.get("missing_slots")) is not list \
            or len(value["missing_slots"]) != 1 \
            or type(value.get("selected_identities")) is not list \
            or len(value["selected_identities"]) != 64 \
            or "population_sha256" in value or "manifest_sha256" in value:
        raise WorldAfterstateV2PopulationArtifactError(
            "partial coverage completion drift")
    if "coverage_sha256" not in value:
        raise WorldAfterstateV2PopulationArtifactError(
            "partial coverage hash missing")
    _digest(value["coverage_sha256"], "partial coverage SHA-256")
    body = {key: item for key, item in value.items()
            if key != "coverage_sha256"}
    if value["coverage_sha256"] != _sha(canonical_json_bytes(body)):
        raise WorldAfterstateV2PopulationArtifactError(
            "partial coverage hash drift")
    return dict(value)


def _validate_partial_rows(root: Path, value: dict[str, Any]) -> None:
    rows = value.get("selected_shard_rows")
    if type(rows) is not list or len(rows) != 64:
        raise WorldAfterstateV2PopulationArtifactError(
            "partial selected row population drift")
    required = {"schema", "relative_path", "tier", "split", "source",
                "ordinal", "deal_sha256", "slot_sha256", "state_sha256",
                "candidate_set_sha256", "byte_count", "sha256",
                "material_sha256"}
    seen: set[str] = set()
    selected_positions = tuple(range(0, 32)) + tuple(range(128, 136)) \
        + tuple(range(160, 172)) + tuple(range(208, 220))
    ledger = build_population_slot_ledger(TIER_SPECS[0])
    for row in rows:
        if type(row) is not dict or set(row) != required \
                or row["schema"] != MATERIAL_ARTIFACT_SCHEMA:
            raise WorldAfterstateV2PopulationArtifactError(
                "partial selected row schema drift")
        for key in ("deal_sha256", "slot_sha256", "state_sha256",
                    "candidate_set_sha256", "sha256", "material_sha256"):
            _digest(row[key], f"partial selected {key}")
        if type(row["byte_count"]) is not int or isinstance(
                row["byte_count"], bool) or row["byte_count"] <= 0:
            raise WorldAfterstateV2PopulationArtifactError(
                "partial selected row byte count drift")
        slot = ledger[selected_positions[len(seen)]]
        if (row["tier"], row["split"], row["source"], row["ordinal"],
                row["slot_sha256"]) != (
                    slot.tier, slot.split, slot.source, slot.ordinal,
                    slot.slot_sha256):
            raise WorldAfterstateV2PopulationArtifactError(
                "partial selected row order drift")
        path = _material_path(root, row["state_sha256"])
        if row["relative_path"] != path.relative_to(root).as_posix() \
                or row["relative_path"] in seen:
            raise WorldAfterstateV2PopulationArtifactError(
                "partial selected row path drift")
        seen.add(row["relative_path"])
        try:
            raw = stable_read_bytes(path)
            material = reopen_population_material(raw)
        except Exception as exc:
            raise WorldAfterstateV2PopulationArtifactError(
                "partial selected shard reopen refused") from exc
        if len(raw) != row["byte_count"] or _sha(raw) != row["sha256"] \
                or _sha(raw) != row["material_sha256"] \
                or (material.deal_sha256, material.slot_sha256,
                    material.state_sha256, material.candidate_set_sha256) != (
                        row["deal_sha256"], row["slot_sha256"],
                        row["state_sha256"], row["candidate_set_sha256"]):
            raise WorldAfterstateV2PopulationArtifactError(
                "partial selected shard identity drift")


def publish_population_partial_coverage(root: Path, value: dict[str, Any]) \
        -> dict[str, Any]:
    """Publish one immutable, explicitly incomplete D256 coverage record."""
    root = _root(root)
    checked = _partial_coverage_value(value)
    _validate_partial_rows(root, checked)
    path = population_partial_coverage_path(root)
    _parent(root, path.parent, create=True)
    try:
        publish_exclusive_bytes(path, canonical_json_bytes(checked))
        raw = stable_read_bytes(path)
    except (OSError, ValueError) as exc:
        raise WorldAfterstateV2PopulationArtifactError(
            "partial coverage publication refused") from exc
    if raw != canonical_json_bytes(checked):
        raise WorldAfterstateV2PopulationArtifactError(
            "partial coverage byte drift")
    return _partial_coverage_value(_strict_json(raw, "partial coverage"))


def reopen_population_partial_coverage(root: Path) -> dict[str, Any]:
    """Reopen the immutable incomplete-coverage record without completing D256."""
    try:
        raw = stable_read_bytes(population_partial_coverage_path(root))
        value = _partial_coverage_value(_strict_json(raw, "partial coverage"))
        _validate_partial_rows(_root(root), value)
        return value
    except WorldAfterstateV2PopulationArtifactError:
        raise
    except (OSError, ValueError) as exc:
        raise WorldAfterstateV2PopulationArtifactError(
            "partial coverage reopen refused") from exc


def _manifest_bytes(*, freeze_sha256: str, namespace_sha256: str,
                    tier: str, split: str, source: str,
                    rows: Sequence[dict[str, Any]]) -> bytes:
    body = {"schema": MANIFEST_SCHEMA, "authority": dict(AUTHORITY),
            "freeze_sha256": freeze_sha256,
            "population_namespace_sha256": namespace_sha256,
            "tier": tier, "split": split, "source": source,
            "rows": list(rows)}
    population_sha256 = _sha(canonical_json_bytes(body))
    sealed = {**body, "population_sha256": population_sha256}
    return canonical_json_bytes({**sealed, "manifest_sha256":
        _sha(canonical_json_bytes(sealed))})


def publish_population_manifest(
        root: Path, shards: Sequence[PopulationMaterialShardV2], *,
        freeze_sha256: str, population_namespace_sha256: str,
        tier: str | None = None, split: str | None = None,
        source: str | None = None) -> dict[str, Any]:
    """Seal the exact ordered shard population in one immutable manifest."""
    root = _root(root)
    if type(shards) not in (tuple, list) or not shards:
        raise WorldAfterstateV2PopulationArtifactError(
            "manifest population drift")
    _digest(freeze_sha256, "external freeze SHA-256")
    _digest(population_namespace_sha256, "population namespace SHA-256")
    rows = []
    for shard in shards:
        if type(shard) is not PopulationMaterialShardV2:
            raise WorldAfterstateV2PopulationArtifactError("manifest row type drift")
        row = shard.row()
        if tier is not None and shard.tier != tier:
            raise WorldAfterstateV2PopulationArtifactError("manifest tier drift")
        if split is not None and shard.split != split:
            raise WorldAfterstateV2PopulationArtifactError("manifest split drift")
        if source is not None and shard.source != source:
            raise WorldAfterstateV2PopulationArtifactError("manifest source drift")
        canonical_path = _material_path(root, shard.state_sha256)
        if shard.relative_path != canonical_path.relative_to(root).as_posix():
            raise WorldAfterstateV2PopulationArtifactError(
                "manifest material path drift")
        raw = stable_read_bytes(canonical_path)
        if len(raw) != shard.byte_count or _sha(raw) != shard.sha256 \
                or _sha(raw) != shard.material_sha256 \
                or reopen_population_material(raw).state_sha256 != shard.state_sha256:
            raise WorldAfterstateV2PopulationArtifactError(
                "manifest shard record drift")
        rows.append(row)
    identities = [(row["tier"], row["split"], row["source"], row["ordinal"],
                   row["deal_sha256"])
                  for row in rows]
    if len(set(identities)) != len(identities) \
            or len({row["relative_path"] for row in rows}) != len(rows):
        raise WorldAfterstateV2PopulationArtifactError(
            "manifest duplicate population")
    if identities != sorted(identities):
        raise WorldAfterstateV2PopulationArtifactError("manifest row order drift")
    tier_value = tier if tier is not None else (rows[0]["tier"] if
        len({row["tier"] for row in rows}) == 1 else "mixed")
    tiers = {item.name: item for item in TIER_SPECS}
    if tier_value not in tiers or any(row["tier"] != tier_value for row in rows):
        raise WorldAfterstateV2PopulationArtifactError(
            "manifest tier population drift")
    expected_slots = build_population_slot_ledger(tiers[tier_value])
    if (len(rows) != len(expected_slots)
            or {row["slot_sha256"] for row in rows}
            != {slot.slot_sha256 for slot in expected_slots}):
        raise WorldAfterstateV2PopulationArtifactError(
            "manifest slot population drift")
    split_value = split if split is not None else (rows[0]["split"] if
        len({row["split"] for row in rows}) == 1 else "mixed")
    source_value = source if source is not None else (rows[0]["source"] if
        len({row["source"] for row in rows}) == 1 else "mixed")
    raw = _manifest_bytes(freeze_sha256=freeze_sha256,
                          namespace_sha256=population_namespace_sha256,
                          tier=tier_value, split=split_value,
                          source=source_value, rows=rows)
    path = root / POPULATION_DIRNAME / MANIFEST_NAME
    commitment_path = root / POPULATION_DIRNAME / COMMITMENT_NAME
    _parent(root, path.parent, create=True)
    try:
        # Keep an immutable population commitment outside the mutable JSON
        # manifest.  This is what makes a coordinated row+manifest rehash
        # fail even when the caller does not retain population_sha256.
        publish_exclusive_bytes(
            commitment_path, (json.loads(raw.decode("ascii"))[
                "population_sha256"] + "\n").encode("ascii"))
        publish_exclusive_bytes(path, raw)
    except (OSError, ValueError) as exc:
        raise WorldAfterstateV2PopulationArtifactError(
            "manifest publication refused") from exc
    return _strict_json(raw, "population manifest")


def _parse_manifest(raw: bytes) -> dict[str, Any]:
    value = _strict_json(raw, "population manifest")
    expected = {"schema", "authority", "freeze_sha256",
                "population_namespace_sha256", "tier", "split", "source",
                "rows", "population_sha256", "manifest_sha256"}
    if set(value) != expected or value["schema"] != MANIFEST_SCHEMA \
            or value["authority"] != AUTHORITY or type(value["rows"]) is not list:
        raise WorldAfterstateV2PopulationArtifactError("manifest schema drift")
    _digest(value["freeze_sha256"], "external freeze SHA-256")
    _digest(value["population_namespace_sha256"],
            "population namespace SHA-256")
    _digest(value["population_sha256"], "population SHA-256")
    _digest(value["manifest_sha256"], "manifest SHA-256")
    body = {key: item for key, item in value.items()
            if key not in ("population_sha256", "manifest_sha256")}
    if value["population_sha256"] != _sha(canonical_json_bytes(body)):
        raise WorldAfterstateV2PopulationArtifactError("manifest hash drift")
    sealed = {**body, "population_sha256": value["population_sha256"]}
    if value["manifest_sha256"] != _sha(canonical_json_bytes(sealed)):
        raise WorldAfterstateV2PopulationArtifactError("manifest hash drift")
    if not value["rows"]:
        raise WorldAfterstateV2PopulationArtifactError("manifest population drift")
    return value


def _row(value: object) -> PopulationMaterialShardV2:
    if type(value) is not dict:
        raise WorldAfterstateV2PopulationArtifactError("manifest row schema drift")
    expected = {"schema", "relative_path", "tier", "split", "source", "ordinal",
                "deal_sha256", "slot_sha256", "state_sha256",
                "candidate_set_sha256", "byte_count", "sha256",
                "material_sha256"}
    if set(value) != expected or value["schema"] != MATERIAL_ARTIFACT_SCHEMA \
            or type(value["relative_path"]) is not str \
            or not value["relative_path"] or "/" not in value["relative_path"]:
        raise WorldAfterstateV2PopulationArtifactError("manifest row schema drift")
    for key in ("deal_sha256", "slot_sha256", "state_sha256",
                "candidate_set_sha256", "sha256", "material_sha256"):
        _digest(value[key], f"manifest {key}")
    if type(value["byte_count"]) is not int or isinstance(value["byte_count"], bool) \
            or value["byte_count"] <= 0:
        raise WorldAfterstateV2PopulationArtifactError("manifest byte count drift")
    if type(value["ordinal"]) is not int or isinstance(value["ordinal"], bool) \
            or value["ordinal"] < 0:
        raise WorldAfterstateV2PopulationArtifactError("manifest ordinal drift")
    return PopulationMaterialShardV2(**value)


def _open_manifest(root: Path, *, expected_freeze_sha256: str,
                   expected_population_namespace_sha256: str,
                   expected_tier: str | None, expected_split: str | None,
                   expected_source: str | None,
                   expected_population_sha256: str | None = None
                   ) -> tuple[dict[str, Any], tuple[PopulationMaterialShardV2, ...]]:
    root = _root(root)
    _digest(expected_freeze_sha256, "expected external freeze SHA-256")
    _digest(expected_population_namespace_sha256,
            "expected population namespace SHA-256")
    if expected_population_sha256 is not None:
        _digest(expected_population_sha256, "expected population SHA-256")
    _directory(root / POPULATION_DIRNAME)
    manifest_path = root / POPULATION_DIRNAME / MANIFEST_NAME
    commitment_path = root / POPULATION_DIRNAME / COMMITMENT_NAME
    try:
        value = _parse_manifest(stable_read_bytes(manifest_path))
    except (OSError, ValueError) as exc:
        if isinstance(exc, WorldAfterstateV2PopulationArtifactError):
            raise
        raise WorldAfterstateV2PopulationArtifactError(
            "manifest read refused") from exc
    if value["freeze_sha256"] != expected_freeze_sha256 \
            or value["population_namespace_sha256"] \
            != expected_population_namespace_sha256:
        raise WorldAfterstateV2PopulationArtifactError(
            "manifest external identity drift")
    if expected_population_sha256 is not None \
            and value["population_sha256"] != expected_population_sha256:
        raise WorldAfterstateV2PopulationArtifactError(
            "manifest population identity drift")
    try:
        commitment = stable_read_bytes(commitment_path)
    except (OSError, ValueError) as exc:
        raise WorldAfterstateV2PopulationArtifactError(
            "population commitment read refused") from exc
    if commitment != (value["population_sha256"] + "\n").encode("ascii"):
        raise WorldAfterstateV2PopulationArtifactError(
            "population commitment drift")
    rows = tuple(_row(item) for item in value["rows"])
    tiers = {item.name: item for item in TIER_SPECS}
    if value["tier"] not in tiers:
        raise WorldAfterstateV2PopulationArtifactError("manifest tier drift")
    expected_slots = build_population_slot_ledger(tiers[value["tier"]])
    if (len(rows) != len(expected_slots)
            or {row.slot_sha256 for row in rows}
            != {slot.slot_sha256 for slot in expected_slots}):
        raise WorldAfterstateV2PopulationArtifactError(
            "manifest slot population drift")
    if expected_tier is not None and value["tier"] != expected_tier:
        raise WorldAfterstateV2PopulationArtifactError("manifest tier drift")
    if expected_split is not None and value["split"] not in (expected_split, "mixed"):
        raise WorldAfterstateV2PopulationArtifactError("manifest split drift")
    if expected_source is not None and value["source"] not in (expected_source, "mixed"):
        raise WorldAfterstateV2PopulationArtifactError("manifest source drift")
    if expected_split is not None and value["split"] == expected_split \
            and any(row.split != expected_split for row in rows):
        raise WorldAfterstateV2PopulationArtifactError("manifest split drift")
    if expected_source is not None and value["source"] == expected_source \
            and any(row.source != expected_source for row in rows):
        raise WorldAfterstateV2PopulationArtifactError("manifest source drift")
    identities = [(row.tier, row.split, row.source, row.ordinal,
                   row.deal_sha256) for row in rows]
    if len(set(identities)) != len(rows) or identities != sorted(identities):
        raise WorldAfterstateV2PopulationArtifactError(
            "manifest row order/population drift")
    for row in rows:
        if expected_tier is not None and row.tier != expected_tier:
            raise WorldAfterstateV2PopulationArtifactError("manifest tier drift")
        if expected_split is not None and row.split != expected_split:
            continue
        if expected_source is not None and row.source != expected_source:
            raise WorldAfterstateV2PopulationArtifactError("manifest source drift")
        canonical_path = _material_path(root, row.state_sha256)
        if row.relative_path != canonical_path.relative_to(root).as_posix():
            raise WorldAfterstateV2PopulationArtifactError(
                "manifest material path drift")
    expected_paths = {manifest_path, commitment_path,
                      *(root / Path(row.relative_path) for row in rows)}
    observed_paths = tuple((root / POPULATION_DIRNAME).rglob("*"))
    if any(path.is_symlink() for path in observed_paths):
        raise WorldAfterstateV2PopulationArtifactError(
            "manifest contains symlink")
    observed = {path for path in observed_paths if path.is_file()}
    if observed != expected_paths:
        raise WorldAfterstateV2PopulationArtifactError(
            "manifest file population drift")
    return value, rows


def reopen_population_manifest(
        root: Path, *, expected_freeze_sha256: str,
        expected_population_namespace_sha256: str,
        expected_tier: str | None = None, expected_split: str | None = "audit",
        expected_source: str | None = "natural",
        expected_population_sha256: str | None = None
        ) -> tuple[PopulationMaterialV2, ...]:
    """Reopen typed materials from the sealed manifest, never caller inputs."""
    _manifest, rows = _open_manifest(
        root, expected_freeze_sha256=expected_freeze_sha256,
        expected_population_namespace_sha256=expected_population_namespace_sha256,
        expected_tier=expected_tier, expected_split=expected_split,
        expected_source=expected_source,
        expected_population_sha256=expected_population_sha256)
    result = []
    for row in rows:
        if expected_split is not None and row.split != expected_split:
            continue
        raw = stable_read_bytes(_root(root) / Path(row.relative_path))
        if len(raw) != row.byte_count or _sha(raw) != row.sha256 \
                or _sha(raw) != row.material_sha256:
            raise WorldAfterstateV2PopulationArtifactError(
                "material shard hash drift")
        material = reopen_population_material(raw)
        if (material.deal_sha256, material.slot_sha256, material.state_sha256,
                material.candidate_set_sha256) != (
                    row.deal_sha256, row.slot_sha256, row.state_sha256,
                    row.candidate_set_sha256):
            raise WorldAfterstateV2PopulationArtifactError(
                "material shard semantic identity drift")
        if material.state.split != row.split or material.state.source != row.source:
            raise WorldAfterstateV2PopulationArtifactError(
                "material split/source drift")
        _slot_for(material, row.tier)
        result.append(material)
    if not result:
        raise WorldAfterstateV2PopulationArtifactError(
            "manifest expected split has no materials")
    return tuple(result)


reopen_population_audit_subset = reopen_population_manifest
reopen_population_material_manifest = reopen_population_manifest
publish_population_artifact_manifest = publish_population_manifest
reopen_population_artifact_manifest = reopen_population_manifest


__all__ = [
    "AUTHORITY", "MANIFEST_SCHEMA", "MATERIAL_ARTIFACT_SCHEMA",
    "POPULATION_MANIFEST_SCHEMA", "POPULATION_MATERIAL_SCHEMA",
    "COMMITMENT_NAME",
    "PARTIAL_COVERAGE_SCHEMA", "PARTIAL_COVERAGE_NAME",
    "population_partial_coverage_path", "publish_population_partial_coverage",
    "reopen_population_partial_coverage",
    "PopulationMaterialShardV2",
    "WorldAfterstateV2PopulationArtifactError",
    "population_material_bytes", "serialize_population_material_v2",
    "population_material_artifact_bytes",
    "reopen_population_material", "reopen_serialized_population_material_v2",
    "reopen_population_material_artifact",
    "material_sha256", "population_material_path",
    "publish_population_material", "publish_population_material_shard",
    "publish_population_material_artifact",
    "publish_population_manifest", "reopen_population_manifest",
    "publish_population_artifact_manifest", "reopen_population_artifact_manifest",
    "reopen_population_audit_subset", "reopen_population_material_manifest",
]


population_material_artifact_bytes = population_material_bytes

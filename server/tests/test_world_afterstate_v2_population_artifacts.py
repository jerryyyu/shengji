from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from shengji.rl import world_afterstate_v2_population_artifacts as artifacts
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v2_population_artifacts import (
    WorldAfterstateV2PopulationArtifactError,
    material_sha256, population_material_bytes, publish_population_manifest,
    publish_population_material, reopen_population_manifest,
    reopen_population_material,
)

from test_world_afterstate_v2_population import _case
from shengji.rl.world_afterstate_v2_population import build_population_material_v2
from shengji.rl.world_afterstate_v2_protocol import (
    TIER_SPECS, build_population_slot_ledger,
)


def _material():
    snapshot, slot, attempt = _case()
    return build_population_material_v2(attempt, slot, snapshot)


def _sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    material = _material()
    shard = publish_population_material(tmp_path, material, tier="D256")
    slot = next(slot for slot in build_population_slot_ledger(TIER_SPECS[0])
                if slot.slot_sha256 == material.slot_sha256)
    # Exercise the exact-population contract with a one-slot test tier while
    # retaining a real, fully validated D256 material and slot.
    monkeypatch.setattr(
        artifacts, "build_population_slot_ledger", lambda _tier: (slot,))
    manifest = publish_population_manifest(
        tmp_path, [shard], freeze_sha256="f" * 64,
        population_namespace_sha256="e" * 64, tier="D256", split="fit",
        source="natural")
    return material, shard, manifest


def test_material_exact_round_trip_and_safe_audit_encoding():
    material = _material()
    raw = population_material_bytes(material)
    reopened = reopen_population_material(raw)
    assert reopened == material
    assert material_sha256(material) == hashlib.sha256(raw).hexdigest()
    payload = json.loads(raw)
    assert all(isinstance(value, str) for value in payload["audit_raws_base64"])
    assert "outcome" not in raw.decode("ascii")
    assert "prediction" not in raw.decode("ascii")


def test_material_unknown_field_and_changed_audit_bytes_refuse():
    raw = population_material_bytes(_material())
    value = json.loads(raw)
    value["unknown"] = False
    with pytest.raises(WorldAfterstateV2PopulationArtifactError):
        reopen_population_material(canonical_json_bytes(value))
    value = json.loads(raw)
    encoded = value["audit_raws_base64"][0]
    value["audit_raws_base64"][0] = encoded[:-4] + "AAAA"
    with pytest.raises(WorldAfterstateV2PopulationArtifactError):
        reopen_population_material(canonical_json_bytes(value))


def test_manifest_cannot_seal_a_valid_subset_as_the_tier_population(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    material = _material()
    shard = publish_population_material(tmp_path, material, tier="D256")
    slots = build_population_slot_ledger(TIER_SPECS[0])
    own = next(slot for slot in slots
               if slot.slot_sha256 == material.slot_sha256)
    missing = next(slot for slot in slots
                   if slot.slot_sha256 != material.slot_sha256)
    monkeypatch.setattr(
        artifacts, "build_population_slot_ledger",
        lambda _tier: (own, missing))
    with pytest.raises(WorldAfterstateV2PopulationArtifactError,
                       match="slot population"):
        publish_population_manifest(
            tmp_path, [shard], freeze_sha256="f" * 64,
            population_namespace_sha256="e" * 64, tier="D256")


def test_manifest_reopens_exact_typed_material_and_refuses_identity_drift(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    material, shard, manifest = _sealed(tmp_path, monkeypatch)
    reopened = reopen_population_manifest(
        tmp_path, expected_freeze_sha256="f" * 64,
        expected_population_namespace_sha256="e" * 64, expected_tier="D256",
        expected_split="fit", expected_source="natural",
        expected_population_sha256=manifest["population_sha256"])
    assert reopened == (material,)
    with pytest.raises(WorldAfterstateV2PopulationArtifactError):
        reopen_population_manifest(
            tmp_path, expected_freeze_sha256="0" * 64,
            expected_population_namespace_sha256="e" * 64,
            expected_tier="D256", expected_split="fit",
            expected_source="natural")


def test_manifest_changed_shard_extra_file_and_coordinated_rehash_refuse(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _material_value, shard, manifest = _sealed(tmp_path, monkeypatch)
    target = tmp_path / shard.relative_path
    target.chmod(0o600)
    target.write_bytes(target.read_bytes()[:-1] + b"x")
    target.chmod(0o400)
    with pytest.raises(WorldAfterstateV2PopulationArtifactError):
        reopen_population_manifest(
            tmp_path, expected_freeze_sha256="f" * 64,
            expected_population_namespace_sha256="e" * 64,
            expected_tier="D256", expected_split="fit",
            expected_source="natural", expected_population_sha256=
            manifest["population_sha256"])
    target.chmod(0o600)
    target.write_bytes(population_material_bytes(_material_value))
    target.chmod(0o400)
    extra = target.parent / "extra.json"
    extra.write_bytes(b"{}\n")
    extra.chmod(0o400)
    with pytest.raises(WorldAfterstateV2PopulationArtifactError):
        reopen_population_manifest(
            tmp_path, expected_freeze_sha256="f" * 64,
            expected_population_namespace_sha256="e" * 64,
            expected_tier="D256", expected_split="fit",
            expected_source="natural")
    extra.unlink()
    # A caller cannot make a changed material acceptable by rehashing the
    # manifest: the externally retained population commitment remains fixed.
    manifest_path = tmp_path / "population" / "manifest.json"
    value = json.loads(manifest_path.read_bytes())
    value["rows"][0]["material_sha256"] = "0" * 64
    body = {key: item for key, item in value.items()
            if key != "population_sha256"}
    value["population_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()
    manifest_path.chmod(0o600)
    manifest_path.write_bytes(canonical_json_bytes(value))
    manifest_path.chmod(0o400)
    with pytest.raises(WorldAfterstateV2PopulationArtifactError):
        reopen_population_manifest(
            tmp_path, expected_freeze_sha256="f" * 64,
            expected_population_namespace_sha256="e" * 64,
            expected_tier="D256", expected_split="fit",
            expected_source="natural", expected_population_sha256=
            manifest["population_sha256"])

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v2_artifacts import (
    WorldAfterstateV2ArtifactError,
    checkpoint_shard_path,
    publish_checkpoint_manifest,
    publish_checkpoint_shard,
    publish_continuation_manifest,
    publish_continuation_shard,
    reopen_checkpoint_manifest,
    reopen_checkpoint_shard,
    reopen_continuation_manifest,
)
from shengji.rl.world_afterstate_v2_checkpoint import checkpoint_bytes
from shengji.rl.world_afterstate_v2_checkpoint import reopen_checkpoint
from shengji.rl.world_afterstate import build_outcome
from shengji.rl.world_afterstate_v2_label import _candidate_set_sha256
from shengji.rl.world_afterstate_v2_model import new_world_afterstate_v2_model
from shengji.rl.world_afterstate_v2_population import (
    PopulationCandidateV2, PopulationMaterialV2,
)
from shengji.rl.world_afterstate_v2_protocol import StateCandidateV2
from shengji.rl import world_afterstate_v2_continuation as continuation


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture(scope="module")
def checkpoint_raws():
    model = new_world_afterstate_v2_model(7101)
    return tuple(checkpoint_bytes(
        model, seed_block=1, member_index=member, control_name="natural",
        init_seed=7101, selected_epoch=3, freeze_sha256=_hash("freeze"),
        config_sha256=_hash("config"), population_sha256=_hash("population"),
        schedule_sha256=_hash("schedule"), common_epoch_sha256=_hash("common"))
        for member in range(4))


def _publish_cohort(tmp_path: Path, raws: tuple[bytes, ...]):
    shards = tuple(publish_checkpoint_shard(
        tmp_path, raw, cohort="natural", seed_block=1,
        member_index=member, epoch=3) for member, raw in enumerate(raws))
    publish_checkpoint_manifest(tmp_path, shards)
    return shards


def _checkpoint_shards(tmp_path: Path, raws: tuple[bytes, ...]):
    return tuple(publish_checkpoint_shard(
        tmp_path, raw, cohort="natural", seed_block=1,
        member_index=member, epoch=3) for member, raw in enumerate(raws))


@pytest.fixture
def continuation_pair(monkeypatch):
    successors = (_hash("successor-0"), _hash("successor-1"))
    state = StateCandidateV2(
        deal_sha256=_hash("deal"), slot_sha256=_hash("slot"),
        state_sha256=_hash("state"), source="natural", split="fit",
        phase="early", position="lead", role="attacker", trump_rank="2",
        trump_mode="S", select_subfold=None, mechanics_surfaces=(),
        legal_candidate_count=2)
    candidates = tuple(PopulationCandidateV2(
        candidate_index=index, action_sha256=_hash(f"action-{index}"),
        audit_sha256=_hash(f"audit-{index}"),
        successor_sha256=successor, origin="production-ballot",
        protected_incumbent=index == 0)
        for index, successor in enumerate(successors))
    material = PopulationMaterialV2(
        state=state,
        candidate_set_sha256=_candidate_set_sha256(
            state.state_sha256, successors),
        candidates=candidates, audit_raws=(b"audit-0", b"audit-1"),
        prestate={"public": {"attacker_points": 41}})
    monkeypatch.setattr(PopulationMaterialV2, "validate", lambda self: None)
    monkeypatch.setattr(continuation, "_audit", lambda raw: {
        "successor_sha256": successors[0 if raw == b"audit-0" else 1],
        "root_seat": 0,
    })

    class FakeRound:
        def is_attacker(self, _seat):
            return True

    monkeypatch.setattr(
        continuation, "reopen_afterstate_audit", lambda _audit: FakeRound())

    def run(audit, identity):
        return {
            "schema": "fixture-label",
            "successor_sha256": audit["successor_sha256"],
            "continuation_identity": dict(identity),
            "outcome": build_outcome(audit["successor_sha256"], 120, True),
        }

    monkeypatch.setattr(continuation, "run_afterstate_continuation", run)
    monkeypatch.setattr(
        continuation, "reopen_afterstate_continuation",
        lambda _audit, value: value)
    return material, continuation.build_continuation_bundle_v2(material)


def test_checkpoint_shard_and_exact_aggregate_round_trip(
        tmp_path: Path, checkpoint_raws):
    shards = _publish_cohort(tmp_path, checkpoint_raws)
    model, metadata = reopen_checkpoint_shard(
        tmp_path, cohort="natural", seed_block=1, member_index=2, epoch=3)
    assert metadata["member_index"] == 2
    assert metadata["selected_epoch"] == 3
    assert model is not None
    reopened = reopen_checkpoint_manifest(
        tmp_path, cohort="natural", seed_block=1, epoch=3)
    assert tuple(item[1]["member_index"] for item in reopened) == tuple(range(4))
    manifest = json.loads((tmp_path / "checkpoints" / "natural" / "block-1"
                           / "epoch-3" / "manifest.json").read_bytes())
    assert all(not Path(row["relative_path"]).is_absolute()
               for row in manifest["rows"])
    assert all(value is False for value in manifest["authority"].values())
    assert shards[0].relative_path == (
        "checkpoints/natural/block-1/epoch-3/member-0.bin")


def test_checkpoint_metadata_schedule_epoch_and_member_mismatches_refuse(
        tmp_path: Path, checkpoint_raws):
    with pytest.raises(WorldAfterstateV2ArtifactError, match="binding"):
        publish_checkpoint_shard(
            tmp_path, checkpoint_raws[0], cohort="natural", seed_block=1,
            member_index=0, epoch=4)
    publish_checkpoint_shard(
        tmp_path, checkpoint_raws[0], cohort="natural", seed_block=1,
            member_index=0, epoch=3)
    with pytest.raises(WorldAfterstateV2ArtifactError):
        reopen_checkpoint_shard(
            tmp_path, cohort="natural", seed_block=1, member_index=1, epoch=3)


def test_checkpoint_manifest_requires_canonical_complete_member_population(
        tmp_path: Path, checkpoint_raws):
    shards = _checkpoint_shards(tmp_path, checkpoint_raws)
    with pytest.raises(WorldAfterstateV2ArtifactError, match="population"):
        publish_checkpoint_manifest(tmp_path, shards[:-1])
    with pytest.raises(WorldAfterstateV2ArtifactError, match="order"):
        publish_checkpoint_manifest(tmp_path, tuple(reversed(shards)))
    assert not (tmp_path / "checkpoints" / "natural" / "block-1"
                / "epoch-3" / "manifest.json").exists()


def test_continuation_shard_and_manifest_round_trip(
        tmp_path: Path, continuation_pair):
    material, bundle = continuation_pair
    shard = publish_continuation_shard(tmp_path, material, bundle)
    manifest = publish_continuation_manifest(tmp_path, (shard,))
    reopened = reopen_continuation_manifest(
        tmp_path, {material.deal_sha256: material})
    assert reopened == (bundle,)
    assert manifest["rows"][0]["bundle_sha256"] == bundle.bundle_sha256
    assert all(value is False for value in manifest["authority"].values())


def test_continuation_manifest_refuses_semantic_rebind_before_sealing(
        tmp_path: Path, continuation_pair):
    material, bundle = continuation_pair
    shard = publish_continuation_shard(tmp_path, material, bundle)
    forged = replace(shard, slot_sha256=_hash("foreign-slot"))
    with pytest.raises(WorldAfterstateV2ArtifactError, match="semantic"):
        publish_continuation_manifest(tmp_path, (forged,))
    assert not (tmp_path / "continuations" / "manifest.json").exists()


def test_continuation_manifest_refuses_changed_bytes_and_extra_file(
        tmp_path: Path, continuation_pair):
    material, bundle = continuation_pair
    shard = publish_continuation_shard(tmp_path, material, bundle)
    publish_continuation_manifest(tmp_path, (shard,))
    target = tmp_path / shard.relative_path
    target.chmod(0o600)
    target.write_bytes(target.read_bytes()[:-1] + b"x")
    target.chmod(0o400)
    with pytest.raises(WorldAfterstateV2ArtifactError):
        reopen_continuation_manifest(
            tmp_path, {material.deal_sha256: material})
    target.chmod(0o600)
    target.write_bytes(bundle.canonical_bytes)
    target.chmod(0o400)
    extra = target.parent / "extra.bin"
    extra.write_bytes(b"extra")
    extra.chmod(0o400)
    with pytest.raises(WorldAfterstateV2ArtifactError, match="population"):
        reopen_continuation_manifest(
            tmp_path, {material.deal_sha256: material})


def test_manifest_changed_bytes_drop_extra_and_aliases_refuse(
        tmp_path: Path, checkpoint_raws):
    shards = _publish_cohort(tmp_path, checkpoint_raws)
    target = checkpoint_shard_path(tmp_path, "natural", 1, 0, 3)
    os.chmod(target, 0o600)
    target.write_bytes(target.read_bytes()[:-1] + b"x")
    os.chmod(target, 0o400)
    with pytest.raises(WorldAfterstateV2ArtifactError):
        reopen_checkpoint_manifest(
            tmp_path, cohort="natural", seed_block=1, epoch=3)

    # Rehashing both a file and its manifest still cannot swap a member's
    # semantic checkpoint into another member's path.
    target.chmod(0o600)
    target.write_bytes(checkpoint_raws[1])
    target.chmod(0o400)
    manifest_path = target.parent / "manifest.json"
    value = json.loads(manifest_path.read_bytes())
    row = value["rows"][0]
    _model, metadata = reopen_checkpoint(checkpoint_raws[1])
    row.update({
        "byte_count": len(checkpoint_raws[1]),
        "sha256": hashlib.sha256(checkpoint_raws[1]).hexdigest(),
        "checkpoint_sha256": metadata["checkpoint_sha256"],
        "model_state_sha256": metadata["model_state_sha256"],
    })
    body = {key: item for key, item in value.items()
            if key != "manifest_sha256"}
    value["manifest_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()
    manifest_path.chmod(0o600)
    manifest_path.write_bytes(canonical_json_bytes(value))
    manifest_path.chmod(0o400)
    with pytest.raises(WorldAfterstateV2ArtifactError, match="semantic"):
        reopen_checkpoint_manifest(
            tmp_path, cohort="natural", seed_block=1, epoch=3)

    # Stable reads reject writable files, symlinks, and hardlinks.
    target.unlink()
    publish_checkpoint_shard(
        tmp_path, checkpoint_raws[0], cohort="natural", seed_block=1,
        member_index=0, epoch=3)
    target.chmod(0o600)
    with pytest.raises(WorldAfterstateV2ArtifactError):
        reopen_checkpoint_manifest(
            tmp_path, cohort="natural", seed_block=1, epoch=3)
    target.chmod(0o400)
    target.unlink()
    target.symlink_to(checkpoint_shard_path(tmp_path, "natural", 1, 1, 3))
    with pytest.raises(WorldAfterstateV2ArtifactError):
        reopen_checkpoint_manifest(
            tmp_path, cohort="natural", seed_block=1, epoch=3)
    target.unlink()
    os.link(checkpoint_shard_path(tmp_path, "natural", 1, 1, 3), target)
    with pytest.raises(WorldAfterstateV2ArtifactError):
        reopen_checkpoint_manifest(
            tmp_path, cohort="natural", seed_block=1, epoch=3)
    target.unlink()
    publish_checkpoint_shard(
        tmp_path, checkpoint_raws[0], cohort="natural", seed_block=1,
        member_index=0, epoch=3)

    # Restore the valid shard and exercise exact file-set checks.
    manifest_path.unlink()
    publish_checkpoint_manifest(tmp_path, shards)
    extra = target.parent / "extra.bin"
    extra.write_bytes(b"extra")
    os.chmod(extra, 0o400)
    with pytest.raises(WorldAfterstateV2ArtifactError, match="population"):
        reopen_checkpoint_manifest(
            tmp_path, cohort="natural", seed_block=1, epoch=3)

    # A coordinated manifest rehash cannot turn a missing member into a valid
    # four-member cohort; semantic population is fixed by the adapter.
    extra.unlink()
    manifest_path = target.parent / "manifest.json"
    value = json.loads(manifest_path.read_bytes())
    value["rows"].pop()
    body = {key: item for key, item in value.items()
            if key != "manifest_sha256"}
    value["manifest_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()
    os.chmod(manifest_path, 0o600)
    manifest_path.write_bytes(canonical_json_bytes(value))
    os.chmod(manifest_path, 0o400)
    with pytest.raises(WorldAfterstateV2ArtifactError, match="member"):
        reopen_checkpoint_manifest(
            tmp_path, cohort="natural", seed_block=1, epoch=3)


@pytest.mark.parametrize("bad", ("../escape", "/absolute", "a\\b"))
def test_path_traversal_is_rejected(tmp_path: Path, bad: str):
    with pytest.raises(WorldAfterstateV2ArtifactError):
        # The path helper validates the semantic digest before constructing a
        # path, so no caller-controlled path component is ever joined.
        checkpoint_shard_path(tmp_path, bad, 1, 0, 3)

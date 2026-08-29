from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace

import numpy as np
import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.douzero_micro import HISTORY_EVENT_DIM
from shengji.rl.encode import N_CARDS
from shengji.rl.world_afterstate import (
    PERSPECTIVE_DIM, PUBLIC_DIM, WORLD_RECEIVERS, WorldAfterstateTensorsV0,
    build_outcome,
)
from shengji.rl.world_afterstate_v2_continuation import (
    build_continuation_bundle_v2,
)
from shengji.rl.world_afterstate_v2_population import (
    PopulationCandidateV2, PopulationMaterialV2,
)
from shengji.rl.world_afterstate_v2_protocol import StateCandidateV2
from shengji.rl import world_afterstate_v2_continuation as continuation
from shengji.rl import world_afterstate_v2_dataset as dataset


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _material() -> PopulationMaterialV2:
    successors = (_sha("successor-0"), _sha("successor-1"))
    state = StateCandidateV2(
        deal_sha256=_sha("deal"), slot_sha256=_sha("slot"),
        state_sha256=_sha("state"), source="natural", split="fit",
        phase="early", position="lead", role="attacker", trump_rank="2",
        trump_mode="S", mechanics_surfaces=(), legal_candidate_count=2)
    candidates = tuple(PopulationCandidateV2(
        candidate_index=i, action_sha256=_sha(("action", i)),
        audit_sha256=hashlib.sha256(f"audit-{i}".encode()).hexdigest(),
        successor_sha256=successor,
        origin="production-ballot", protected_incumbent=i == 0)
                      for i, successor in enumerate(successors))
    return PopulationMaterialV2(
        state=state,
        candidate_set_sha256=_sha({
            "schema": "world-afterstate-v2-candidate-set-v1",
            "state_sha256": state.state_sha256,
            "successor_sha256s": list(successors)}),
        candidates=candidates, audit_raws=(b"audit-0", b"audit-1"),
        prestate={"public": {"attacker_points": 41}})


@pytest.fixture
def source_fixture(monkeypatch):
    material = _material()
    monkeypatch.setattr(PopulationMaterialV2, "validate", lambda self: None)
    monkeypatch.setattr(continuation, "_audit", lambda raw: {
        "successor_sha256": material.candidates[
            0 if raw == b"audit-0" else 1].successor_sha256,
        "root_seat": 0})
    class FakeRound:
        def is_attacker(self, seat):
            return True
    monkeypatch.setattr(continuation, "reopen_afterstate_audit",
                        lambda audit: FakeRound())
    def run(audit, identity):
        return {
            "schema": "fixture-label",
            "successor_sha256": audit["successor_sha256"],
            "continuation_identity": copy.deepcopy(identity),
            "outcome": build_outcome(audit["successor_sha256"], 120, True),
        }
    monkeypatch.setattr(continuation, "run_afterstate_continuation", run)
    monkeypatch.setattr(continuation, "reopen_afterstate_continuation",
                        lambda audit, value: copy.deepcopy(value))
    monkeypatch.setattr(dataset, "_canonical_audit", lambda raw: {
        "successor_sha256": material.candidates[
            0 if raw == b"audit-0" else 1].successor_sha256,
        "root_seat": 0})
    tensors = WorldAfterstateTensorsV0(
        public=np.zeros(PUBLIC_DIM, dtype=np.float32),
        history=np.zeros((1, HISTORY_EVENT_DIM), dtype=np.float32),
        world=np.zeros((WORLD_RECEIVERS, N_CARDS), dtype=np.float32),
        perspective=np.asarray([1., 0.], dtype=np.float32))
    monkeypatch.setattr(dataset, "build_afterstate_tensors",
                        lambda audit: tensors)
    return material, build_continuation_bundle_v2(material)


def test_bridge_emits_complete_candidate_replica_examples_without_runner(
        source_fixture, monkeypatch):
    material, bundle = source_fixture
    monkeypatch.setattr(continuation, "run_afterstate_continuation",
                        lambda *_: (_ for _ in ()).throw(AssertionError(
                            "continuation rerun")))
    rows = dataset.build_training_examples_v2(material, bundle)
    assert len(rows) == 16
    assert {(row.candidate_index, row.replica) for row in rows} == {
        (candidate, replica) for candidate in range(2) for replica in range(8)}
    assert rows[0].protected_incumbent is True
    assert rows[8].protected_incumbent is False
    assert all(row.split == "fit" for row in rows)


def test_manifest_is_target_free_and_hash_bound(source_fixture):
    material, bundle = source_fixture
    manifest = dataset.build_dataset_manifest_row_v2(material, bundle)
    manifest.validate()
    raw = json.dumps(manifest.to_dict())
    assert not any(token in raw for token in (
        "signed_level", "attacker_points", "outcome", "terminal",
        "tensor_data", "audit_data", "label_bytes"))
    assert manifest.row_sha256 == dataset.manifest_row_sha256(manifest)


@pytest.mark.parametrize("mutation", [
    lambda material, bundle: (material, replace(
        bundle, state_sha256=_sha("foreign"))),
    lambda material, bundle: (material, replace(
        bundle, candidates=bundle.candidates[:8] + bundle.candidates[9:])),
    lambda material, bundle: (replace(material, state=replace(
        material.state, split="select")), bundle),
])
def test_cross_binding_and_non_fit_inputs_refuse(source_fixture, mutation):
    material, bundle = source_fixture
    forged_material, forged_bundle = mutation(material, bundle)
    with pytest.raises(dataset.WorldAfterstateV2DatasetError):
        dataset.build_training_examples_v2(forged_material, forged_bundle)

from __future__ import annotations

import copy
import hashlib
import inspect
import json
from dataclasses import replace

import numpy as np
import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate import build_outcome
from shengji.rl.world_afterstate_v2_label import _candidate_set_sha256
from shengji.rl.world_afterstate_v2_population import (
    PopulationCandidateV2, PopulationMaterialV2,
)
from shengji.rl.world_afterstate_v2_protocol import StateCandidateV2
from shengji.rl import world_afterstate_v2_continuation as continuation
from shengji.rl import world_afterstate_v2_p0_mechanics as mechanics


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _material() -> PopulationMaterialV2:
    successors = (_sha("successor-0"), _sha("successor-1"))
    state = StateCandidateV2(
        deal_sha256=_sha("deal"), slot_sha256=_sha("slot"),
        state_sha256=_sha("state"), source="natural", split="fit",
        phase="early", position="lead", role="attacker", trump_rank="2",
        trump_mode="S", select_subfold=None, mechanics_surfaces=(),
        legal_candidate_count=2)
    candidates = tuple(PopulationCandidateV2(
        candidate_index=i, action_sha256=_sha(("action", i)),
        audit_sha256=_sha(("audit", i)), successor_sha256=successor,
        origin="production-ballot", protected_incumbent=i == 0)
                      for i, successor in enumerate(successors))
    return PopulationMaterialV2(
        state=state, candidate_set_sha256=_candidate_set_sha256(
            state.state_sha256, successors), candidates=candidates,
        audit_raws=(b"audit-0", b"audit-1"),
        prestate={"public": {"attacker_points": 41}})


class _Round:
    # Deliberately differs from the terminal continuation score.  Perspective
    # reconstruction must not mistake the successor's partial score for the
    # eventual label.
    attacker_points = 41

    def is_attacker(self, seat):
        return True


class _Tensor:
    def __init__(self):
        self.public = np.zeros(2, dtype=np.float32)
        self.history = np.zeros((1, 2), dtype=np.float32)
        self.world = np.zeros((1, 2), dtype=np.float32)
        self.perspective = np.asarray([1., 0.], dtype=np.float32)

    def validate(self):
        return None


@pytest.fixture
def source_pair(monkeypatch):
    material = _material()
    monkeypatch.setattr(PopulationMaterialV2, "validate", lambda self: None)
    monkeypatch.setattr(continuation, "_audit", lambda raw: {
        "successor_sha256": material.candidates[
            0 if raw == b"audit-0" else 1].successor_sha256,
        "root_seat": 0})
    monkeypatch.setattr(continuation, "reopen_afterstate_audit",
                        lambda audit: _Round())

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
    bundle = continuation.build_continuation_bundle_v2(material)

    monkeypatch.setattr(mechanics, "_audit", continuation._audit)
    monkeypatch.setattr(mechanics, "reopen_afterstate_audit",
                        lambda audit: _Round())
    monkeypatch.setattr(mechanics, "canonical_successor",
                        lambda rnd, root: {"successor": "canonical"})
    monkeypatch.setattr(mechanics, "build_afterstate_tensors",
                        lambda audit: _Tensor())
    monkeypatch.setattr(mechanics, "build_root_rotated_afterstate_tensors",
                        lambda audit, offset: _Tensor())
    monkeypatch.setattr(mechanics, "run_afterstate_continuation", run)
    return material, bundle


def test_engine_checks_are_exact_and_fixed_rerun_is_one_per_material(
        source_pair, monkeypatch):
    material, bundle = source_pair
    calls = []
    original = continuation.run_afterstate_continuation

    def count(audit, identity):
        calls.append((audit["successor_sha256"], identity["replicate"]))
        return original(audit, identity)

    monkeypatch.setattr(mechanics, "run_afterstate_continuation", count)
    first = mechanics.derive_p0_engine_mechanics_checks([material], [bundle])
    second = mechanics.derive_p0_engine_mechanics_checks([material], [bundle])
    assert first == second
    assert calls == [(material.candidates[0].successor_sha256, 0)] * 2
    assert {key for key in first} == {
        "transition", "continuation", "perspective", "symmetry"}
    assert len(first["continuation"]) == 1
    assert all(observed == expected for observed, expected
               in first["perspective"])
    assert len(first["symmetry"]) == 2 * 3


def test_material_reordering_is_canonical_and_cross_binding_refused(
        source_pair):
    material, bundle = source_pair
    checks = mechanics.derive_p0_engine_mechanics_checks(
        [material], [bundle])
    assert checks == mechanics.derive_p0_engine_mechanics_checks(
        [material], [bundle])
    with pytest.raises(mechanics.WorldAfterstateV2P0MechanicsError):
        mechanics.derive_p0_engine_mechanics_checks(
            [material, material], [bundle, bundle])


def test_no_caller_check_injection_and_continuation_mismatch_is_visible(
        source_pair, monkeypatch):
    material, bundle = source_pair
    assert "checks" not in inspect.signature(
        mechanics.build_engine_p0_mechanics_evidence).parameters

    def altered(audit, identity):
        value = continuation.run_afterstate_continuation(audit, identity)
        value["outcome"] = build_outcome(
            audit["successor_sha256"], 121, True)
        return value

    monkeypatch.setattr(mechanics, "run_afterstate_continuation", altered)
    checks = mechanics.derive_p0_engine_mechanics_checks([material], [bundle])
    assert any(observed != expected for observed, expected
               in checks["continuation"])

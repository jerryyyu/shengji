from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate import build_outcome
from shengji.rl.world_afterstate_v2_label import _candidate_set_sha256
from shengji.rl.world_afterstate_v2_population import (
    PopulationCandidateV2, PopulationMaterialV2,
)
from shengji.rl.world_afterstate_v2_protocol import StateCandidateV2
from shengji.rl import world_afterstate_v2_continuation as source


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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
        state=state,
        candidate_set_sha256=_candidate_set_sha256(
            state.state_sha256, successors),
        candidates=candidates, audit_raws=(b"audit-0", b"audit-1"),
        prestate={"public": {"attacker_points": 41}})


@pytest.fixture
def fake_engine(monkeypatch):
    material = _material()
    monkeypatch.setattr(PopulationMaterialV2, "validate", lambda self: None)
    monkeypatch.setattr(source, "_audit", lambda raw: {
        "successor_sha256": material.candidates[0 if raw == b"audit-0" else 1].successor_sha256,
        "root_seat": 0,
    })
    class FakeRound:
        def is_attacker(self, seat):
            return True
    monkeypatch.setattr(source, "reopen_afterstate_audit", lambda audit: FakeRound())

    def run(audit, identity):
        outcome = build_outcome(audit["successor_sha256"], 120, True)
        return {
            "schema": "fixture-label",
            "successor_sha256": audit["successor_sha256"],
            "continuation_identity": copy.deepcopy(identity),
            "outcome": outcome,
        }

    monkeypatch.setattr(source, "run_afterstate_continuation", run)
    monkeypatch.setattr(source, "reopen_afterstate_continuation",
                        lambda audit, value: copy.deepcopy(value))
    return material


def test_crn_identity_is_shared_by_siblings_and_distinct_by_replica(fake_engine):
    bundle = source.build_continuation_bundle_v2(fake_engine)
    by_replica = {}
    for receipt in bundle.labels:
        identity = receipt.continuation_identity
        by_replica.setdefault(receipt.replica, set()).add(
            json.dumps(identity, sort_keys=True))
    assert all(len(values) == 1 for values in by_replica.values())
    assert len({next(iter(values)) for values in by_replica.values()}) == 8
    assert len({row.continuation_sha256 for row in bundle.outcomes}) == 8


def test_capacity_probe_runs_one_real_continuation_and_discards_population(
        fake_engine, monkeypatch):
    calls = []
    original = source.run_afterstate_continuation

    def counted(audit, identity):
        calls.append((audit, identity))
        return original(audit, identity)

    monkeypatch.setattr(source, "run_afterstate_continuation", counted)
    digest = source.run_continuation_capacity_probe_v2(fake_engine)
    assert len(digest) == 64
    assert len(calls) == 1
    assert calls[0][1]["replicate"] == 0


def test_bundle_reconstructs_and_cross_binds_raw_label(fake_engine):
    bundle = source.build_continuation_bundle_v2(fake_engine)
    assert bundle.bundle_sha256 == _sha_bytes(bundle.canonical_bytes)
    assert source.reopen_continuation_bundle_v2(
        bundle.canonical_bytes, fake_engine) == bundle
    forged = copy.copy(bundle)
    labels = list(bundle.labels)
    labels[0] = replace(labels[0], raw_sha256=_sha_bytes(b"forged"))
    object.__setattr__(forged, "labels", tuple(labels))
    with pytest.raises(source.WorldAfterstateV2ContinuationError):
        forged.validate()


def test_reopen_never_repeats_engine_continuations(fake_engine, monkeypatch):
    bundle = source.build_continuation_bundle_v2(fake_engine)
    monkeypatch.setattr(source, "run_afterstate_continuation",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(
                            AssertionError("reopen repeated continuation")))
    assert source.reopen_continuation_bundle_v2(
        bundle.canonical_bytes, fake_engine).bundle_sha256 == bundle.bundle_sha256


def test_drop_duplicate_and_seed_drift_are_refused(fake_engine):
    bundle = source.build_continuation_bundle_v2(fake_engine)
    for labels in (bundle.labels[:-1], bundle.labels + (bundle.labels[0],)):
        forged = copy.copy(bundle)
        object.__setattr__(forged, "labels", labels)
        with pytest.raises(source.WorldAfterstateV2ContinuationError):
            forged.validate()
    labels = list(bundle.labels)
    identity = labels[0].continuation_identity
    identity["replicate"] = 1
    label = json.loads(labels[0].raw.decode("ascii"))
    label["continuation_identity"] = identity
    labels[0] = replace(labels[0], raw=canonical_json_bytes(label),
                        raw_sha256=_sha_bytes(canonical_json_bytes(label)),
                        continuation_sha256=_sha(identity))
    forged = copy.copy(bundle)
    object.__setattr__(forged, "labels", tuple(labels))
    with pytest.raises(source.WorldAfterstateV2ContinuationError):
        forged.validate()


def test_successor_candidate_set_and_category_perspective_tamper_refused(fake_engine):
    bundle = source.build_continuation_bundle_v2(fake_engine)
    forged = copy.copy(bundle)
    rows = list(bundle.outcomes)
    rows[0] = replace(rows[0], successor_sha256=_sha("foreign"))
    object.__setattr__(forged, "candidates", tuple(rows))
    with pytest.raises(source.WorldAfterstateV2ContinuationError):
        forged.validate()
    labels = list(bundle.labels)
    label = json.loads(labels[0].raw.decode("ascii"))
    label["outcome"] = build_outcome(
        label["successor_sha256"], 120, False)
    raw = canonical_json_bytes(label)
    labels[0] = replace(labels[0], raw=raw, raw_sha256=_sha_bytes(raw))
    forged = copy.copy(bundle)
    object.__setattr__(forged, "labels", tuple(labels))
    with pytest.raises(source.WorldAfterstateV2ContinuationError):
        forged.validate()

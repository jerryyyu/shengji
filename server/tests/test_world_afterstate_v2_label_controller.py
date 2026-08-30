from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace
from pathlib import Path

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate import build_outcome
from shengji.rl.world_afterstate_v2_label import _candidate_set_sha256
from shengji.rl.world_afterstate_v2_population import (
    PopulationCandidateV2, PopulationMaterialV2,
)
from shengji.rl.world_afterstate_v2_protocol import StateCandidateV2
from shengji.rl import world_afterstate_v2_continuation as continuation
from shengji.rl import world_afterstate_v2_label_controller as controller


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _second_material(material: PopulationMaterialV2,
                     label: str = "2") -> PopulationMaterialV2:
    """Make a second fixture deal while retaining the patched engine seam."""
    state = replace(
        material.state, deal_sha256=_sha(f"deal-{label}"),
        slot_sha256=_sha(f"slot-{label}"), state_sha256=_sha(f"state-{label}"))
    successors = tuple(candidate.successor_sha256
                       for candidate in material.candidates)
    return replace(
        material, state=state,
        candidate_set_sha256=_candidate_set_sha256(
            state.state_sha256, successors))


@pytest.fixture
def material_and_bundle(monkeypatch):
    successors = (_sha("successor-0"), _sha("successor-1"))
    state = StateCandidateV2(
        deal_sha256=_sha("deal"), slot_sha256=_sha("slot"),
        state_sha256=_sha("state"), source="natural", split="fit",
        phase="early", position="lead", role="attacker", trump_rank="2",
        trump_mode="S", select_subfold=None, mechanics_surfaces=(),
        legal_candidate_count=2)
    candidates = tuple(PopulationCandidateV2(
        candidate_index=index, action_sha256=_sha(("action", index)),
        audit_sha256=_sha(("audit", index)), successor_sha256=successor,
        origin="production-ballot", protected_incumbent=index == 0)
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
        "root_seat": 0})

    class FakeRound:
        def is_attacker(self, _seat):
            return True

    monkeypatch.setattr(
        continuation, "reopen_afterstate_audit", lambda _audit: FakeRound())
    monkeypatch.setattr(continuation, "run_afterstate_continuation",
        lambda audit, identity, **_kwargs: {
            "schema": "fixture-label",
            "successor_sha256": audit["successor_sha256"],
            "continuation_identity": dict(identity),
            "outcome": build_outcome(audit["successor_sha256"], 120, True)})
    monkeypatch.setattr(
        continuation, "reopen_afterstate_continuation",
        lambda _audit, value: value)
    return material, continuation.build_continuation_bundle_v2(material)


def test_label_stage_seals_reopens_and_resume_does_not_recompute(
        tmp_path: Path, material_and_bundle, monkeypatch):
    material, bundle = material_and_bundle
    calls = []
    monkeypatch.setattr(controller, "_build_one",
                        lambda value: calls.append(value.deal_sha256) or bundle)
    progress = []
    first = controller.build_continuation_population_v2(
        tmp_path / "fit-select", (material,), split="fit-select", workers=1,
        deadline_monotonic_ns=time.monotonic_ns() + 10**12,
        progress=progress.append)
    assert first.material_count == first.built_shard_count == 1
    assert first.reused_shard_count == 0
    assert first.continuation_outcome_count == 16
    assert calls == [material.deal_sha256]
    assert progress[-1]["completed_deals"] == 1
    controller.reopen_label_stage_receipt(first.payload())

    monkeypatch.setattr(controller, "_build_one", lambda _value: (_ for _ in ()).throw(
        AssertionError("verified continuation was recomputed")))
    second = controller.build_continuation_population_v2(
        tmp_path / "fit-select", (material,), split="fit-select", workers=1,
        deadline_monotonic_ns=time.monotonic_ns() + 10**12)
    assert second.reused_shard_count == 1
    assert second.built_shard_count == 0
    assert second.manifest_sha256 == first.manifest_sha256


def test_label_stage_refuses_wrong_split_before_engine(
        tmp_path: Path, material_and_bundle, monkeypatch):
    material, _bundle = material_and_bundle
    monkeypatch.setattr(controller, "_build_one", lambda _value: (_ for _ in ()).throw(
        AssertionError("wrong split reached engine")))
    with pytest.raises(controller.WorldAfterstateV2LabelControllerError,
                       match="split"):
        controller.build_continuation_population_v2(
            tmp_path / "audit", (material,), split="audit", workers=1,
            deadline_monotonic_ns=time.monotonic_ns() + 10**12)


def test_fit_select_reuses_sealed_source_without_engine_recomputation(
        tmp_path: Path, material_and_bundle, monkeypatch):
    material, bundle = material_and_bundle
    source = tmp_path / "p0-continuations"
    target = tmp_path / "fit-select-continuations"
    monkeypatch.setattr(controller, "_build_one", lambda _value: bundle)
    controller.build_continuation_population_v2(
        source, (material,), split="fit-select", workers=1,
        deadline_monotonic_ns=time.monotonic_ns() + 10**12)

    monkeypatch.setattr(controller, "_build_one", lambda _value: (_ for _ in ()).throw(
        AssertionError("sealed P0 continuation was recomputed")))
    receipt = controller.build_continuation_population_v2(
        target, (material,), split="fit-select", workers=1,
        deadline_monotonic_ns=time.monotonic_ns() + 10**12,
        reuse_root=source, reuse_materials=(material,))
    assert receipt.reused_shard_count == 1
    assert receipt.built_shard_count == 0
    assert receipt.material_count == 1


def test_partial_copied_prefix_resumes_source_without_rebuilding_it(
        tmp_path: Path, material_and_bundle, monkeypatch):
    material, bundle = material_and_bundle
    second = _second_material(material)
    second_bundle = continuation.build_continuation_bundle_v2(second)
    bundles = {material.deal_sha256: bundle,
               second.deal_sha256: second_bundle}
    monkeypatch.setattr(controller, "_build_one",
                        lambda value: bundles[value.deal_sha256])
    source = tmp_path / "p0"
    controller.build_continuation_population_v2(
        source, (material,), split="fit-select", workers=1,
        deadline_monotonic_ns=time.monotonic_ns() + 10**12)

    calls = []
    def interrupted(value):
        calls.append(value.deal_sha256)
        if value.deal_sha256 == second.deal_sha256:
            raise RuntimeError("simulated interruption")
        return bundles[value.deal_sha256]
    monkeypatch.setattr(controller, "_build_one", interrupted)
    target = tmp_path / "partial"
    with pytest.raises(RuntimeError, match="interruption"):
        controller.build_continuation_population_v2(
            target, (material, second), split="fit-select", workers=1,
            deadline_monotonic_ns=time.monotonic_ns() + 10**12,
            reuse_root=source, reuse_materials=(material,))
    assert calls == [second.deal_sha256]

    calls.clear()
    monkeypatch.setattr(controller, "_build_one",
                        lambda value: calls.append(value.deal_sha256) or
                        bundles[value.deal_sha256])
    receipt = controller.build_continuation_population_v2(
        target, (material, second), split="fit-select", workers=1,
        deadline_monotonic_ns=time.monotonic_ns() + 10**12,
        reuse_root=source, reuse_materials=(material,))
    assert calls == [second.deal_sha256]
    assert receipt.reused_shard_count == 1
    assert receipt.built_shard_count == 1


def test_tampered_later_target_shard_refuses_before_source_copy(
        tmp_path: Path, material_and_bundle, monkeypatch):
    material, bundle = material_and_bundle
    second = _second_material(material)
    second_bundle = continuation.build_continuation_bundle_v2(second)
    bundles = {material.deal_sha256: bundle,
               second.deal_sha256: second_bundle}
    source_one = tmp_path / "p0-one"
    source_two = tmp_path / "p0-two"
    monkeypatch.setattr(controller, "_build_one",
                        lambda value: bundles[value.deal_sha256])
    controller.build_continuation_population_v2(
        source_one, (material,), split="fit-select", workers=1,
        deadline_monotonic_ns=time.monotonic_ns() + 10**12)
    controller.build_continuation_population_v2(
        source_two, (material, second), split="fit-select", workers=1,
        deadline_monotonic_ns=time.monotonic_ns() + 10**12)

    target = tmp_path / "tampered"
    original_publish = controller.publish_continuation_manifest
    monkeypatch.setattr(controller, "publish_continuation_manifest",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(
                            RuntimeError("simulated publication crash")))
    with pytest.raises(RuntimeError, match="publication crash"):
        controller.build_continuation_population_v2(
            target, (material, second), split="fit-select", workers=1,
            deadline_monotonic_ns=time.monotonic_ns() + 10**12,
            reuse_root=source_one, reuse_materials=(material,))
    monkeypatch.setattr(controller, "publish_continuation_manifest",
                        original_publish)
    second_path = controller.continuation_shard_path(
        target, second.deal_sha256)
    second_path.chmod(0o600)
    second_path.write_bytes(second_path.read_bytes() + b"tampered")
    second_path.chmod(0o400)

    copied = []
    monkeypatch.setattr(controller, "publish_continuation_shard",
                        lambda *args, **kwargs: copied.append(args[1]) or
                        original_publish(*args, **kwargs))
    monkeypatch.setattr(controller, "_build_one", lambda _value: (_ for _ in ()).throw(
        AssertionError("tampered target reached engine")))
    with pytest.raises(controller.WorldAfterstateV2LabelControllerError,
                       match="continuation|reopen|byte|target"):
        controller.build_continuation_population_v2(
            target, (material, second, _second_material(material, "3")),
            split="fit-select", workers=1,
            deadline_monotonic_ns=time.monotonic_ns() + 10**12,
            reuse_root=source_two, reuse_materials=(material, second))
    assert copied == []
    assert not (target / "continuations" /
                f"deal-{_second_material(material, '3').deal_sha256}.bin").exists()


def test_source_material_mismatch_refuses_before_target_publication(
        tmp_path: Path, material_and_bundle, monkeypatch):
    material, bundle = material_and_bundle
    source = tmp_path / "p0"
    monkeypatch.setattr(controller, "_build_one", lambda _value: bundle)
    controller.build_continuation_population_v2(
        source, (material,), split="fit-select", workers=1,
        deadline_monotonic_ns=time.monotonic_ns() + 10**12)
    mismatch = replace(material, prestate={"public": {"attacker_points": 42}})
    target = tmp_path / "mismatch"
    with pytest.raises(controller.WorldAfterstateV2LabelControllerError,
                       match="source/material"):
        controller.build_continuation_population_v2(
            target, (material,), split="fit-select", workers=1,
            deadline_monotonic_ns=time.monotonic_ns() + 10**12,
            reuse_root=source, reuse_materials=(mismatch,))
    assert not (target / "continuations").exists()


def test_label_stage_deadline_cannot_publish_manifest(
        tmp_path: Path, material_and_bundle, monkeypatch):
    material, bundle = material_and_bundle
    monkeypatch.setattr(controller, "_build_one", lambda _value: bundle)
    root = tmp_path / "expired"
    with pytest.raises(controller.WorldAfterstateV2LabelControllerError,
                       match="deadline"):
        controller.build_continuation_population_v2(
            root, (material,), split="fit-select", workers=1,
            deadline_monotonic_ns=1)
    assert not (root / "continuations" / "manifest.json").exists()


def test_public_receipt_contains_no_labels_or_outcomes(
        tmp_path: Path, material_and_bundle, monkeypatch):
    material, bundle = material_and_bundle
    monkeypatch.setattr(controller, "_build_one", lambda _value: bundle)
    receipt = controller.build_continuation_population_v2(
        tmp_path / "closed", (material,), split="fit-select", workers=1,
        deadline_monotonic_ns=time.monotonic_ns() + 10**12).payload()
    raw = canonical_json_bytes(receipt)
    assert b"signed_level_category" not in raw
    assert b"raw_label" not in raw
    assert b"candidate_index" not in raw
    assert json.loads(raw)["authority"] == controller.AUTHORITY

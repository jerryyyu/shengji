"""Wiring witnesses for receipt-driven V2 freeze construction."""

from __future__ import annotations

from dataclasses import replace

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.belief_v2_execution_identity import (
    V2InstalledDistributionV1,
    V2RuntimeProfileV1,
    V2SourceBindingV1,
)
from shengji.rl.belief_v2_freeze import (
    CAP_SCHEMA,
    V2ResourceCapsV1,
)
from shengji.rl.belief_v2_freeze_builder import (
    BeliefV2FreezeBuilderError,
    build_execution_freeze_from_receipts,
    resource_caps_from_bytes,
    standard_cohort_plans,
)
from shengji.rl.belief_v2_human_inventory import (
    build_h0_group_split,
    group_split_bytes,
    inventory_bytes,
)


def _sha(char: str) -> str:
    return char * 64


def _bindings():
    paths = (
        "BELIEF_V1_SPEC.md", "BELIEF_V1_V2_DESIGN.md",
        "server/pyproject.toml", "server/setup.py", "server/uv.lock",
        "server/scripts/belief_v2_worker.py",
        "server/shengji/rl/belief_v2_freeze_builder.py",
    )
    return tuple(sorted((V2SourceBindingV1(
        path=path, byte_count=index + 1, sha256=f"{index + 1:x}" * 64)
        for index, path in enumerate(paths)), key=lambda row: row.path))


def _distribution(name: str, char: str):
    return V2InstalledDistributionV1(
        name=name, version="1.0", root=f"/runtime/{name}",
        file_count=1, payload_sha256=_sha(char))


def _runtime():
    return V2RuntimeProfileV1(
        hostname="host", operating_system="system", machine="machine",
        cpu_count=16, memory_bytes=32 * 1024**3,
        boot_identity=_sha("8"), python_executable="/runtime/python",
        python_executable_sha256=_sha("9"), python_version="3.14.4",
        torch=_distribution("torch", "a"),
        torch_config_sha256=_sha("b"),
        numpy=_distribution("numpy", "c"),
        native_path="/runtime/_fast.so", native_sha256=_sha("d"),
        required_environment=(
            ("PYTHONDONTWRITEBYTECODE", "1"),
            ("PYTHONHASHSEED", "0"),
            ("SHENGJI_FAST", "1"),
            ("SHENGJI_REQUIRE_VOIDS", "1")))


def _inventory():
    groups = []
    for index in range(10):
        groups.append({
            "group_digest": f"{index + 1:x}" * 64,
            "source_bytes": 100 + index,
            "complete_rounds": 1, "incomplete_rounds": 0,
            "human_play_decisions": 10,
            "trump_rank_counts": {"2": 1},
            "attempted_channel_counts": {"absent": 10},
        })
    groups.sort(key=lambda row: row["group_digest"])
    return {
        "schema": "belief-v1-v2-human-h0-inventory-v1",
        "source_manifest_sha256": _sha("1"),
        "source_file_count": 10,
        "source_digest_population_sha256": _sha("2"),
        "group_count": 10, "groups": groups,
        "rounds_seen": 10, "complete_rounds": 10,
        "incomplete_rounds": 0, "human_play_decisions": 100,
        "trump_rank_counts": {"2": 10},
        "attempted_channel_counts": {"absent": 100},
        "hidden_ownership_labels_reconstructable_for_complete_rounds": True,
        "group_split_unit": "source-log-session-digest",
        "raw_player_identity_published": False,
        "model_rows_published": False,
        "training_authorized": False, "test_open_authorized": False,
        "strength_claim_authorized": False,
    }


def _v1_report(decision="PASS_TO_B3_SAMPLER_IMPLEMENTATION_REVIEW"):
    return {
        "schema": "belief-v1-b2-terminal-report-v1",
        "protocol_sha256": _sha("3"), "design_sha256": _sha("4"),
        "admission_sha256": _sha("5"),
        "evidence": {"resources": {
            "schema": "belief-v1-b2-resource-receipt-v1",
            "within_frozen_caps": True}},
        "terminal": {"decision": decision},
        "test_split_open_count": 1,
        "terminal_reproducibility_review_required": True,
        "b3_sampler_implementation_authorized": False,
        "sampler_run_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "promotion_authorized": False, "deployment_authorized": False,
    }


def _caps():
    return V2ResourceCapsV1(
        capture_core_hours=64, capture_wall_seconds=14_400,
        capture_bytes=16 * 1024**3,
        reference_core_hours=16, reference_wall_seconds=7_200,
        reference_bytes=16 * 1024**3,
        training_device_hours=128, training_wall_seconds=86_400,
        training_bytes=32 * 1024**3,
        training_host_memory_bytes=24 * 1024**3,
        training_device_memory_bytes=12 * 1024**3)


def _patch_receipt_boundaries(monkeypatch):
    monkeypatch.setattr(
        "shengji.rl.belief_v2_freeze_builder.build_source_bindings",
        lambda repo, expected_git: _bindings())
    monkeypatch.setattr(
        "shengji.rl.belief_v2_freeze_builder.build_runtime_profile",
        _runtime)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_freeze_builder.require_training_device",
        lambda value: value)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_freeze_builder.preflight_result_bytes",
        canonical_json_bytes)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_freeze_builder.seed_scan_bytes",
        canonical_json_bytes)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_freeze_builder.seed_registry_bytes",
        lambda registry, scan: canonical_json_bytes(registry))


def _build(tmp_path, monkeypatch, *, decision=None, rationale=None,
           scan_git="a" * 40):
    _patch_receipt_boundaries(monkeypatch)
    inventory = _inventory()
    split = build_h0_group_split(inventory)
    report = _v1_report() if decision is None else _v1_report(decision)
    return build_execution_freeze_from_receipts(
        repo=tmp_path.resolve(), expected_git="a" * 40,
        source_review_commit="b" * 40,
        v1_terminal_report_raw=canonical_json_bytes(report),
        v2_reentry_rationale_raw=rationale,
        inventory_raw=inventory_bytes(inventory),
        group_split_raw=group_split_bytes(split, inventory=inventory),
        preflight_raw=canonical_json_bytes({"runtime": {"host": "x"}}),
        seed_scan_raw=canonical_json_bytes({"git_commit": scan_git}),
        seed_registry_raw=canonical_json_bytes({
            "candidate_report_sha256": _sha("6")}),
        training_candidate_device="mps", resource_caps=_caps(),
        evidence_root=(tmp_path / "evidence").resolve())


def test_builder_derives_one_closed_gpu_capable_freeze(monkeypatch, tmp_path):
    freeze = _build(tmp_path, monkeypatch)
    assert freeze.v1_terminal_route == "v1-pass-to-b3"
    assert freeze.v2_reentry_rationale_sha256 is None
    assert freeze.training_candidate_device == "mps"
    assert [row.cohort_id for row in freeze.cohorts] == [
        "synthetic-primary", "hard-geometry-label-permutation",
        "human-mixture", "synthetic-scale-50"]
    assert freeze.human_group_count == 10
    assert (freeze.human_train_group_count,
            freeze.human_calibration_group_count,
            freeze.human_test_group_count) == (8, 1, 1)
    assert freeze.human_eligible_decision_count == 100
    assert freeze.resource_caps == _caps()


def test_builder_derives_named_select_none_reentry_and_refuses_v1_failure(
        monkeypatch, tmp_path):
    freeze = _build(
        tmp_path, monkeypatch,
        decision="SELECT_NONE_NO_CALIBRATION_LIFT",
        rationale=b"named multi-rank and human-domain reentry\n")
    assert freeze.v1_terminal_route \
        == "v1-select-none-with-named-domain-shift-reentry"
    assert freeze.v2_reentry_rationale_sha256 is not None
    with pytest.raises(BeliefV2FreezeBuilderError,
                       match="cannot freeze after a V1 refusal"):
        _build(
            tmp_path, monkeypatch,
            decision="REFUSE_INCOMPLETE_COHORT_OR_ARTIFACT")


def test_builder_refuses_stale_seed_registry_or_cpu_candidate(
        monkeypatch, tmp_path):
    with pytest.raises(BeliefV2FreezeBuilderError,
                       match="source-head reconstruction"):
        _build(tmp_path, monkeypatch, scan_git="c" * 40)
    freeze = _build(tmp_path, monkeypatch)
    with pytest.raises(BeliefV2FreezeBuilderError,
                       match="qualification candidate"):
        build_execution_freeze_from_receipts(
            repo=tmp_path.resolve(), expected_git="a" * 40,
            source_review_commit="b" * 40,
            v1_terminal_report_raw=canonical_json_bytes(_v1_report()),
            v2_reentry_rationale_raw=None,
            inventory_raw=inventory_bytes(_inventory()),
            group_split_raw=group_split_bytes(
                build_h0_group_split(_inventory()), inventory=_inventory()),
            preflight_raw=canonical_json_bytes({"runtime": {"host": "x"}}),
            seed_scan_raw=canonical_json_bytes({"git_commit": "a" * 40}),
            seed_registry_raw=canonical_json_bytes({
                "candidate_report_sha256": _sha("6")}),
            training_candidate_device="cpu",
            resource_caps=replace(
                freeze.resource_caps, training_device_hours=64),
            evidence_root=(tmp_path / "other").resolve())


def test_resource_caps_require_canonical_positive_integer_schema():
    caps = _caps()
    assert resource_caps_from_bytes(canonical_json_bytes(caps.to_dict())) \
        == caps
    payload = caps.to_dict()
    payload["training_device_memory_bytes"] = 0
    with pytest.raises(BeliefV2FreezeBuilderError, match="value drift"):
        resource_caps_from_bytes(canonical_json_bytes(payload))
    with pytest.raises(BeliefV2FreezeBuilderError, match="not canonical"):
        resource_caps_from_bytes(
            canonical_json_bytes({**caps.to_dict(), "schema": CAP_SCHEMA})
            + b" ")


def test_standard_cohort_factory_is_stable():
    assert standard_cohort_plans() == standard_cohort_plans()
    assert len(standard_cohort_plans()) == 4

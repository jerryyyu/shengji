"""Wiring witnesses for receipt-driven V2 freeze construction."""

from __future__ import annotations

import hashlib
import math
import subprocess
from dataclasses import replace

import pytest
import shengji.rl.belief_v2_freeze_builder as FREEZE_BUILDER

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.belief_v2_execution_identity import (
    V2InstalledDistributionV1,
    V2RuntimeProfileV1,
    V2SourceBindingV1,
)
from shengji.rl.belief_v2_deadline_estimate import (
    DEADLINE_ESTIMATE_SCHEMA,
    DEADLINE_PROBE_ROUND_COUNT,
    DEADLINE_TRAINING_REPEAT_COUNT,
    MINIMUM_SAFETY_RESERVE_NANOSECONDS,
    TRAINING_PROJECTION_MARGIN_DENOMINATOR,
    TRAINING_PROJECTION_MARGIN_NUMERATOR,
    deadline_probe_schedule_sha256,
)
from shengji.rl.belief_v2_freeze import (
    CAP_SCHEMA,
    V2ResourceCapsV1,
)
from shengji.rl.belief_v2_accelerator import V2TrainingDeviceProfileV1
from shengji.rl.belief_v2_freeze_builder import (
    BeliefV2FreezeBuilderError,
    build_execution_freeze_from_receipts,
    resource_caps_from_bytes,
    standard_cohort_plans,
)
from shengji.rl.belief_v2_human_inventory import (
    H0_INVENTORY_SCHEMA,
    _component_digest,
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


def _device_profile():
    return V2TrainingDeviceProfileV1(
        requested_device="mps", device_type="mps", device_index=None,
        hardware_name="Apple-arm64-test", total_memory_bytes=12 * 1024**3,
        runtime_version="macOS-test", compute_capability_major=None,
        compute_capability_minor=None)


def _cpu_profile():
    return V2TrainingDeviceProfileV1(
        requested_device="cpu", device_type="cpu", device_index=None,
        hardware_name="CPU-x86_64-test", total_memory_bytes=32 * 1024**3,
        runtime_version="Linux-test", compute_capability_major=None,
        compute_capability_minor=None)


def _inventory():
    groups = []
    components = []
    for index in range(10):
        group = {
            "group_digest": f"{index + 1:x}" * 64,
            "source_bytes": 100 + index,
            "complete_rounds": 1, "incomplete_rounds": 0,
            "human_play_decisions": 10,
            "trump_rank_counts": {"2": 1},
            "attempted_channel_counts": {"absent": 10},
        }
        component_digest = _component_digest((group["group_digest"],))
        group["component_digest"] = component_digest
        groups.append(group)
        components.append({
            "component_digest": component_digest,
            "group_digests": [group["group_digest"]],
        })
    groups.sort(key=lambda row: row["group_digest"])
    return {
        "schema": H0_INVENTORY_SCHEMA,
        "source_manifest_sha256": _sha("1"),
        "source_file_count": 10,
        "source_digest_population_sha256": _sha("2"),
        "group_count": 10, "groups": groups,
        "component_count": 10,
        "components": sorted(
            components, key=lambda row: row["component_digest"]),
        "rounds_seen": 10, "complete_rounds": 10,
        "incomplete_rounds": 0, "human_play_decisions": 100,
        "trump_rank_counts": {"2": 10},
        "attempted_channel_counts": {"absent": 100},
        "hidden_ownership_labels_reconstructable_for_complete_rounds": True,
        "group_split_unit": "cross-file-human-player-component",
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


def _preflight():
    runtime = _runtime()
    return {
        "runtime": {
            "hostname": runtime.hostname,
            "platform": runtime.operating_system,
            "machine": runtime.machine,
            "logical_cpu_count": runtime.cpu_count,
            "memory_bytes": runtime.memory_bytes,
            "boot_identity": runtime.boot_identity,
            "python_version": runtime.python_version,
            "python_executable_sha256": runtime.python_executable_sha256,
            "native_extension_sha256": runtime.native_sha256,
        },
        "lanes": [{"rounds": [
            {"wall_nanoseconds": 20_000_000_000},
            {"wall_nanoseconds": 20_000_000_000},
        ]} for _ in range(16)],
    }


def _caps():
    training_estimate = _training_epoch_estimate()
    return V2ResourceCapsV1(
        capture_core_hours=64, capture_wall_seconds=14_400,
        capture_bytes=16 * 1024**3,
        reference_core_hours=16, reference_wall_seconds=7_200,
        reference_bytes=16 * 1024**3,
        training_device_hours=128, training_wall_seconds=86_400,
        training_bytes=32 * 1024**3,
        training_host_memory_bytes=24 * 1024**3,
        training_device_memory_bytes=12 * 1024**3,
        capture_next_unit_wall_estimate_nanoseconds=20_000_000_000,
        reference_next_unit_wall_estimate_nanoseconds=5_000_000_000,
        training_next_epoch_wall_estimate_nanoseconds=training_estimate,
        deadline_safety_reserve_nanoseconds=max(
            MINIMUM_SAFETY_RESERVE_NANOSECONDS,
            math.ceil(training_estimate / 20)))


def _training_epoch_estimate():
    numerator = (144_000_000 * 10_647
                 * TRAINING_PROJECTION_MARGIN_NUMERATOR)
    denominator = (DEADLINE_PROBE_ROUND_COUNT
                   * TRAINING_PROJECTION_MARGIN_DENOMINATOR)
    return (numerator + denominator - 1) // denominator


def _deadline_estimate(training_device="mps"):
    caps = _caps()
    return {
        "schema": DEADLINE_ESTIMATE_SCHEMA,
        "execution_git": "a" * 40,
        "runtime_profile_sha256": __import__("hashlib").sha256(
            canonical_json_bytes(_runtime().to_dict())).hexdigest(),
        "training_device": training_device,
        "capture_preflight_result_sha256": hashlib.sha256(
            canonical_json_bytes(_preflight())).hexdigest(),
        "capture_sample_count": 32,
        "capture_wall_nanoseconds": [20_000_000_000] * 32,
        "capture_p95_wall_nanoseconds": (
            caps.capture_next_unit_wall_estimate_nanoseconds),
        "probe_schedule_sha256": deadline_probe_schedule_sha256(),
        "reference_sample_count": 32,
        "reference_wall_nanoseconds": [5_000_000_000] * 32,
        "reference_worker_process_ids": [
            10_000 + index % 16 for index in range(32)],
        "reference_started_monotonic_nanoseconds": [
            100 + index // 16 * 10_000_000_000 for index in range(32)],
        "reference_finished_monotonic_nanoseconds": [
            5_000_000_100 + index // 16 * 10_000_000_000
            for index in range(32)],
        "reference_worker_count": 16,
        "reference_common_overlap_nanoseconds": 5_000_000_000,
        "reference_manifest_population_sha256s": [_sha("f")] * 32,
        "reference_p95_wall_nanoseconds": (
            caps.reference_next_unit_wall_estimate_nanoseconds),
        "training_probe_round_count": DEADLINE_PROBE_ROUND_COUNT,
        "training_probe_repeat_count": DEADLINE_TRAINING_REPEAT_COUNT,
        "training_probe_wall_nanoseconds": [144_000_000] * 2,
        "training_probe_receipt_sha256s": [_sha("1")] * 2,
        "training_epoch_sample_count": DEADLINE_TRAINING_REPEAT_COUNT,
        "training_epoch_wall_estimate_nanoseconds": [
            _training_epoch_estimate()] * 2,
        "training_epoch_p95_wall_nanoseconds": (
            caps.training_next_epoch_wall_estimate_nanoseconds),
        "training_epoch_projection": {
            "train_round_count": 10_647,
            "one_probe_round_per_batch": True,
            "production_may_pack_rounds": True,
            "margin_numerator": TRAINING_PROJECTION_MARGIN_NUMERATOR,
            "margin_denominator": TRAINING_PROJECTION_MARGIN_DENOMINATOR,
        },
        "safety_reserve_nanoseconds": (
            caps.deadline_safety_reserve_nanoseconds),
        "captured_rows_retained": False,
        "sampled_worlds_retained": False,
        "model_or_loss_artifacts_retained": False,
        "production_seed_opened": False,
        "test_split_opened": False,
        "pipeline_execution_authorized": False,
        "retry_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def _v1_resource_failure():
    return {
        "schema": "belief-v1-b2-operator-stopped-resource-failure-v1",
        "v1_execution_git": "1" * 40,
        "v1_design_sha256": _sha("2"),
        "v1_admission_sha256": _sha("3"),
        "v1_source_review_commit": "4" * 40,
        "termination_review_commit": "5" * 40,
        "closeout_ledger_commit": "6" * 40,
        "closeout_ledger_sha256": _sha("7"),
        "termination_route": "operator-stopped-after-frozen-cap",
        "frozen_training_wall_seconds": 28_800,
        "observed_training_wall_nanoseconds_at_stop": 39_000_000_000_000,
        "candidate_exit_status": 143, "control_exit_status": 143,
        "supervisor_log_sha256": _sha("8"),
        "training_partial_slots": [
            "candidate.partial", "hard-geometry-label-permutation.partial"],
        "training_final_artifacts_absent": True,
        "calibration_artifacts_absent": True,
        "test_split_artifacts_absent": True,
        "terminal_artifacts_absent": True,
        "test_split_decision_open_count": 0,
        "admission_spent": True, "retry_authorized": False,
        "model_result_exists": False, "calibration_result_exists": False,
        "strength_result_exists": False,
        "sampler_implementation_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def _git(repo, *args, env=None):
    return subprocess.run(
        ("git", *args), cwd=repo, env=env, check=True,
        capture_output=True, text=True).stdout.strip()


def test_resource_failure_receipt_authenticates_exact_canonical_ledger(
        tmp_path, monkeypatch):
    repo = (tmp_path / "repo").resolve()
    repo.mkdir()
    _git(repo, "init", "-q")
    ledger = repo / "HANDOFF_REVIEW.md"
    ledger.write_text("base\n")
    _git(repo, "add", "HANDOFF_REVIEW.md")
    _git(repo, "-c", "user.name=Claude", "-c",
         "user.email=noreply@anthropic.com", "commit", "-qm", "source")
    source = _git(repo, "rev-parse", "HEAD")
    execution_git = "1" * 40
    with ledger.open("a") as handle:
        handle.write(f"SAFE_TO_TERMINATE exact {execution_git}\n")
    _git(repo, "add", "HANDOFF_REVIEW.md")
    _git(repo, "-c", "user.name=Claude", "-c",
         "user.email=noreply@anthropic.com", "commit", "-qm",
         "termination\n\nClaude-Session: https://claude.ai/code/session_test")
    termination = _git(repo, "rev-parse", "HEAD")
    with ledger.open("a") as handle:
        handle.write("operator-stopped-after-frozen-cap\n")
    _git(repo, "add", "HANDOFF_REVIEW.md")
    _git(repo, "-c", "user.name=Codex", "-c",
         "user.email=codex@example.com", "commit", "-qm", "closeout")
    closeout = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", closeout)
    monkeypatch.setattr(
        FREEZE_BUILDER, "_canonical_remote_tip", lambda value: closeout)
    receipt = {
        **_v1_resource_failure(),
        "v1_execution_git": execution_git,
        "v1_source_review_commit": source,
        "termination_review_commit": termination,
        "closeout_ledger_commit": closeout,
        "closeout_ledger_sha256": hashlib.sha256(
            ledger.read_bytes()).hexdigest(),
    }
    FREEZE_BUILDER._authenticate_v1_resource_failure_receipt(repo, receipt)
    with pytest.raises(BeliefV2FreezeBuilderError,
                       match="canonical ledger binding"):
        FREEZE_BUILDER._authenticate_v1_resource_failure_receipt(
            repo, {**receipt, "closeout_ledger_sha256": _sha("0")})


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
        "shengji.rl.belief_v2_freeze_builder.build_training_device_profile",
        lambda value: _cpu_profile() if value == "cpu"
        else _device_profile())
    monkeypatch.setattr(
        "shengji.rl.belief_v2_freeze_builder.preflight_result_bytes",
        canonical_json_bytes)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_freeze_builder.seed_scan_bytes",
        canonical_json_bytes)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_freeze_builder.seed_registry_bytes",
        lambda registry, scan: canonical_json_bytes(registry))
    monkeypatch.setattr(
        "shengji.rl.belief_v2_freeze_builder."
        "_authenticate_v1_resource_failure_receipt",
        lambda repo, receipt: None)


def _build(tmp_path, monkeypatch, *, decision=None, rationale=None,
           resource_failure=None, scan_git="a" * 40,
           training_candidate_device="mps"):
    _patch_receipt_boundaries(monkeypatch)
    inventory = _inventory()
    split = build_h0_group_split(inventory)
    report = (_v1_report() if decision is None else _v1_report(decision)) \
        if resource_failure is None else None
    return build_execution_freeze_from_receipts(
        repo=tmp_path.resolve(), expected_git="a" * 40,
        source_review_commit="b" * 40,
        v1_terminal_report_raw=(
            None if report is None else canonical_json_bytes(report)),
        v1_resource_failure_receipt_raw=(
            None if resource_failure is None
            else canonical_json_bytes(resource_failure)),
        v2_reentry_rationale_raw=rationale,
        inventory_raw=inventory_bytes(inventory),
        group_split_raw=group_split_bytes(split, inventory=inventory),
        preflight_raw=canonical_json_bytes(_preflight()),
        seed_scan_raw=canonical_json_bytes({"git_commit": scan_git}),
        seed_registry_raw=canonical_json_bytes({
            "candidate_report_sha256": _sha("6")}),
        training_candidate_device=training_candidate_device,
        resource_caps=_caps(),
        deadline_estimate_raw=canonical_json_bytes(_deadline_estimate(
            training_candidate_device)),
        evidence_root=(tmp_path / "evidence").resolve())


def test_builder_derives_one_closed_gpu_capable_freeze(monkeypatch, tmp_path):
    freeze = _build(tmp_path, monkeypatch)
    assert freeze.v1_terminal_route == "v1-pass-to-b3"
    assert freeze.v2_reentry_rationale_sha256 is None
    assert freeze.training_candidate_device == "mps"
    assert freeze.training_device_profile == _device_profile()
    assert [row.cohort_id for row in freeze.cohorts] == [
        "synthetic-primary", "hard-geometry-label-permutation",
        "human-mixture", "synthetic-scale-50"]
    assert freeze.human_group_count == 10
    assert (freeze.human_train_group_count,
            freeze.human_calibration_group_count,
            freeze.human_test_group_count) == (8, 1, 1)
    assert freeze.human_eligible_decision_count == 100
    assert freeze.resource_caps == _caps()


def test_builder_derives_named_select_none_and_exact_resource_failure_reentry(
        monkeypatch, tmp_path):
    freeze = _build(
        tmp_path, monkeypatch,
        decision="SELECT_NONE_NO_CALIBRATION_LIFT",
        rationale=b"named multi-rank and human-domain reentry\n")
    assert freeze.v1_terminal_route \
        == "v1-select-none-with-named-domain-shift-reentry"
    assert freeze.v2_reentry_rationale_sha256 is not None
    failure = _build(
        tmp_path, monkeypatch, resource_failure=_v1_resource_failure(),
        rationale=b"resource defect repaired only in new V2 freeze\n")
    assert failure.v1_terminal_route \
        == "RESOURCE_FAILURE_REPAIRED_FOR_NEW_V2_FREEZE_REVIEW"
    assert failure.v1_terminal_result_sha256 is None
    assert failure.v1_resource_receipt_sha256 is None
    assert failure.v1_resource_failure_receipt_sha256 is not None
    assert failure.v2_reentry_rationale_sha256 is not None
    forged = {**_v1_resource_failure(), "test_split_decision_open_count": 1}
    with pytest.raises(BeliefV2FreezeBuilderError,
                       match="resource failure receipt drift"):
        _build(
            tmp_path, monkeypatch, resource_failure=forged,
            rationale=b"resource defect repaired only in new V2 freeze\n")


def test_builder_refuses_stale_seed_registry_and_accepts_cpu_only_host(
        monkeypatch, tmp_path):
    with pytest.raises(BeliefV2FreezeBuilderError,
                       match="source-head reconstruction"):
        _build(tmp_path, monkeypatch, scan_git="c" * 40)
    freeze = _build(
        tmp_path, monkeypatch, training_candidate_device="cpu")
    assert freeze.training_candidate_device == "cpu"
    assert freeze.training_device_profile == _cpu_profile()


def test_deadline_estimate_receipt_binds_runtime_counts_and_caps(
        monkeypatch, tmp_path):
    _patch_receipt_boundaries(monkeypatch)
    inventory = _inventory()
    split = build_h0_group_split(inventory)

    def build_with(receipt):
        return build_execution_freeze_from_receipts(
            repo=tmp_path.resolve(), expected_git="a" * 40,
            source_review_commit="b" * 40,
            v1_terminal_report_raw=canonical_json_bytes(_v1_report()),
            v1_resource_failure_receipt_raw=None,
            v2_reentry_rationale_raw=None,
            inventory_raw=inventory_bytes(inventory),
            group_split_raw=group_split_bytes(split, inventory=inventory),
            preflight_raw=canonical_json_bytes(_preflight()),
            seed_scan_raw=canonical_json_bytes({"git_commit": "a" * 40}),
            seed_registry_raw=canonical_json_bytes({
                "candidate_report_sha256": _sha("6")}),
            training_candidate_device="mps",
            deadline_estimate_raw=canonical_json_bytes(receipt),
            resource_caps=_caps(),
            evidence_root=(tmp_path / "deadline-evidence").resolve())

    for receipt in (
            {**_deadline_estimate(), "runtime_profile_sha256": _sha("0")},
            {**_deadline_estimate(), "capture_wall_nanoseconds":
             [20_000_000_000] * 31},
            {**_deadline_estimate(), "capture_wall_nanoseconds":
             [19_000_000_000] + [20_000_000_000] * 31},
            {**_deadline_estimate(),
             "training_epoch_p95_wall_nanoseconds":
             _training_epoch_estimate() - 1}):
        with pytest.raises(BeliefV2FreezeBuilderError,
                           match="deadline estimate"):
            build_with(receipt)


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

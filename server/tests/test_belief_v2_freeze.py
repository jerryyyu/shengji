"""Exact packet-shape and causal-attribution tests for the V2 freeze."""

from __future__ import annotations

import copy
import subprocess
from dataclasses import replace

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.belief_v2_freeze import (
    ALL_HUMAN_TRAIN_DECISIONS,
    ALL_SYNTHETIC_TRAIN_DECISIONS,
    BeliefV2FreezeError,
    MIXED_SYNTHETIC_TRAIN_DECISIONS,
    MIXED_WORK_RULE,
    NO_HUMAN_DECISIONS,
    PRIMARY_WORK_RULE,
    SCALE_SYNTHETIC_TRAIN_DECISIONS,
    SCALE_WORK_RULE,
    V2CohortPlanV1,
    V2ExecutionFreezeV1,
    V2ResourceCapsV1,
    authenticate_execution_review,
    build_pipeline_admission,
    execution_freeze_from_bytes,
    expected_execution_review_claim,
    pipeline_consumption_tombstone_bytes,
    reauthenticate_pipeline_admission,
    validate_execution_freeze,
)
from shengji.rl.belief_v2_execution_identity import (
    V2InstalledDistributionV1,
    V2RuntimeProfileV1,
    V2SourceBindingV1,
    source_manifest_sha256,
)
from shengji.rl.belief_v2_device_qualification import (
    qualification_protocol_sha256,
)


def _sha(char: str) -> str:
    return char * 64


def _source_bindings():
    paths = (
        "BELIEF_V1_SPEC.md", "BELIEF_V1_V2_DESIGN.md",
        "server/pyproject.toml", "server/setup.py", "server/uv.lock",
        "server/scripts/belief_v2_worker.py",
        "server/shengji/__init__.py",
    )
    return tuple(sorted((V2SourceBindingV1(
        path=path, byte_count=index + 1,
        sha256=f"{index + 1:x}" * 64)
        for index, path in enumerate(paths)), key=lambda row: row.path))


def _distribution(name: str, char: str):
    return V2InstalledDistributionV1(
        name=name, version="1.0", root=f"/runtime/{name}",
        file_count=10, payload_sha256=_sha(char))


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


def _cohorts():
    primary = V2CohortPlanV1(
        cohort_id="synthetic-primary", kind="synthetic-primary",
        synthetic_selection_rule=ALL_SYNTHETIC_TRAIN_DECISIONS,
        synthetic_fraction_numerator=1, synthetic_fraction_denominator=1,
        human_selection_rule=NO_HUMAN_DECISIONS,
        work_match_rule=PRIMARY_WORK_RULE, comparator_cohort_id=None)
    return (
        primary,
        V2CohortPlanV1(
            cohort_id="hard-geometry-label-permutation",
            kind="hard-geometry-label-permutation",
            synthetic_selection_rule=ALL_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=1,
            human_selection_rule=NO_HUMAN_DECISIONS,
            work_match_rule=PRIMARY_WORK_RULE,
            comparator_cohort_id="synthetic-primary"),
        V2CohortPlanV1(
            cohort_id="human-mixture", kind="human-mixture",
            synthetic_selection_rule=MIXED_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=1,
            human_selection_rule=ALL_HUMAN_TRAIN_DECISIONS,
            work_match_rule=MIXED_WORK_RULE,
            comparator_cohort_id="synthetic-primary"),
        V2CohortPlanV1(
            cohort_id="synthetic-scale-50", kind="synthetic-scale",
            synthetic_selection_rule=SCALE_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=2,
            human_selection_rule=NO_HUMAN_DECISIONS,
            work_match_rule=SCALE_WORK_RULE,
            comparator_cohort_id="synthetic-primary"),
    )


def _freeze():
    bindings = _source_bindings()
    return V2ExecutionFreezeV1(
        execution_git="a" * 40,
        source_manifest_sha256=source_manifest_sha256("a" * 40, bindings),
        source_bindings=bindings, runtime=_runtime(),
        source_review_commit="b" * 40,
        v1_terminal_route="v1-pass-to-b3",
        v1_terminal_result_sha256=_sha("b"),
        v1_resource_receipt_sha256=_sha("c"),
        v2_reentry_rationale_sha256=None,
        h0_inventory_sha256=_sha("d"),
        h0_source_manifest_sha256=_sha("e"),
        h0_source_digest_population_sha256=_sha("f"),
        human_group_split_sha256=_sha("0"),
        human_group_count=30, human_train_group_count=24,
        human_calibration_group_count=3, human_test_group_count=3,
        human_complete_round_count=122,
        human_eligible_decision_count=2830,
        human_train_eligible_decision_count=2240,
        human_calibration_eligible_decision_count=416,
        human_test_eligible_decision_count=174,
        preflight_result_sha256=_sha("1"),
        preflight_runtime_sha256=_sha("2"),
        seed_registry_sha256=_sha("3"),
        seed_candidate_report_sha256=_sha("4"),
        training_candidate_device="mps",
        device_qualification_protocol_sha256=(
            qualification_protocol_sha256("mps")),
        cohorts=_cohorts(),
        resource_caps=V2ResourceCapsV1(
            capture_core_hours=64, capture_wall_seconds=14_400,
            capture_bytes=16 * 1024**3,
            reference_core_hours=16, reference_wall_seconds=7_200,
            reference_bytes=16 * 1024**3,
            training_device_hours=128, training_wall_seconds=86_400,
            training_bytes=32 * 1024**3,
            training_host_memory_bytes=24 * 1024**3,
            training_device_memory_bytes=12 * 1024**3),
        evidence_root="/tmp/belief-v2-evidence")


def test_freeze_round_trips_and_review_claim_is_bounded():
    freeze = _freeze()
    validate_execution_freeze(freeze)
    reopened = execution_freeze_from_bytes(freeze.canonical_bytes())
    assert reopened == freeze
    claim = expected_execution_review_claim(freeze)
    assert claim["bounded_capture_reference_training_and_one_test_open_authorized"] is True
    assert claim["training_candidate_device"] == "mps"
    assert claim["device_qualification_protocol_sha256"] \
        == qualification_protocol_sha256("mps")
    assert claim["retry_authorized"] is False
    assert claim["gameplay_strength_screen_authorized"] is False
    assert claim["deployment_authorized"] is False
    cohort_payload = freeze.to_dict()["cohorts"]
    assert all("optimizer_decisions_per_epoch" not in row
               for row in cohort_payload)
    assert all("synthetic_decision_manifest_sha256" not in row
               for row in cohort_payload)
    assert cohort_payload[0]["synthetic_selection_rule"] \
        == ALL_SYNTHETIC_TRAIN_DECISIONS


@pytest.mark.parametrize(("mutation", "message"), [
    (lambda freeze: replace(
        freeze, cohorts=tuple(row for row in freeze.cohorts
                              if row.kind != "synthetic-scale")),
     "cohort kind population"),
    (lambda freeze: replace(
        freeze, cohorts=tuple(
            replace(row, work_match_rule=PRIMARY_WORK_RULE)
            if row.kind == "human-mixture" else row
            for row in freeze.cohorts)), "comparison/work binding"),
    (lambda freeze: replace(
        freeze, human_eligible_decision_count=10_590,
        human_train_eligible_decision_count=10_000),
     "human mixture fraction"),
    (lambda freeze: replace(
        freeze, cohorts=tuple(
            replace(row, synthetic_fraction_numerator=1,
                    synthetic_fraction_denominator=1)
            if row.kind == "synthetic-scale" else row
            for row in freeze.cohorts)), "scale cohort binding"),
    (lambda freeze: replace(
        freeze, v1_terminal_route=(
            "v1-select-none-with-named-domain-shift-reentry")),
     "lacks named reentry"),
    (lambda freeze: replace(freeze, human_test_group_count=2),
     "identity drift"),
    (lambda freeze: replace(freeze, training_candidate_device="cpu"),
     "device qualification protocol drift"),
    (lambda freeze: replace(
        freeze, device_qualification_protocol_sha256=_sha("7")),
     "device qualification protocol drift"),
    (lambda freeze: replace(
        freeze, resource_caps=replace(
            freeze.resource_caps, training_device_memory_bytes=0)),
     "resource cap identity drift"),
])
def test_freeze_refuses_named_scientific_and_population_mutations(
        mutation, message):
    with pytest.raises(BeliefV2FreezeError, match=message):
        validate_execution_freeze(mutation(_freeze()))


def test_canonical_reopen_refuses_gate_or_authority_rewrite():
    payload = _freeze().to_dict()
    payload["gates"]["rank_material_regression_tolerance_ppb"] = 6_000_000
    with pytest.raises(BeliefV2FreezeError, match="reconstruction"):
        execution_freeze_from_bytes(canonical_json_bytes(payload))

    payload = _freeze().to_dict()
    payload["training_device_qualification"][
        "fallback_on_integrity_failure"] = True
    with pytest.raises(BeliefV2FreezeError, match="device qualification"):
        execution_freeze_from_bytes(canonical_json_bytes(payload))

    payload = _freeze().to_dict()
    payload["training_device_qualification"]["candidate_device"] = "cuda:0"
    with pytest.raises(BeliefV2FreezeError, match="device qualification"):
        execution_freeze_from_bytes(canonical_json_bytes(payload))

    payload = _freeze().to_dict()
    payload["authority"]["gameplay_strength_screen_authorized"] = True
    with pytest.raises(BeliefV2FreezeError, match="reconstruction"):
        execution_freeze_from_bytes(canonical_json_bytes(payload))


def test_select_none_requires_and_preserves_named_reentry_evidence():
    freeze = replace(
        _freeze(),
        v1_terminal_route="v1-select-none-with-named-domain-shift-reentry",
        v2_reentry_rationale_sha256=_sha("5"))
    validate_execution_freeze(freeze)
    assert execution_freeze_from_bytes(freeze.canonical_bytes()) == freeze


def _git(repo, *args):
    return subprocess.run(
        ("git", *args), cwd=repo, check=True,
        capture_output=True, text=True).stdout.strip()


def _review_repo(tmp_path, freeze, monkeypatch):
    repo = (tmp_path / "repo").resolve()
    remote = (tmp_path / "remote.git").resolve()
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "HANDOFF_REVIEW.md").write_text("ledger\n")
    _git(repo, "add", "HANDOFF_REVIEW.md")
    _git(repo, "-c", "user.name=Base", "-c",
         "user.email=base@example.com", "commit", "-qm", "base")
    marker = (
        "BELIEF_V1_V2_OFFLINE_EXECUTION_V1_REVIEW ".encode()
        + canonical_json_bytes(expected_execution_review_claim(freeze)))
    with (repo / "HANDOFF_REVIEW.md").open("ab") as handle:
        handle.write(marker)
    _git(repo, "add", "HANDOFF_REVIEW.md")
    _git(repo, "-c", "user.name=Claude", "-c",
         "user.email=noreply@anthropic.com", "commit", "-qm",
         "PASS\n\nClaude-Session: https://claude.ai/code/session_test")
    review = _git(repo, "rev-parse", "HEAD")
    subprocess.run(("git", "init", "--bare", "-q", str(remote)),
                   check=True)
    _git(repo, "branch", "-M", "main")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-qu", "origin", "main")
    monkeypatch.setattr(
        "shengji.rl.belief_v2_freeze.CANONICAL_REMOTE_URL", str(remote))
    return repo, review, marker


def test_review_and_admission_require_actual_remote_append_only_marker(
        tmp_path, monkeypatch):
    freeze = _freeze()
    repo, review, marker = _review_repo(tmp_path, freeze, monkeypatch)
    authenticated, remote_tip = authenticate_execution_review(
        freeze, repo=repo, review_commit=review)
    assert authenticated == marker
    assert remote_tip == review
    admission, built_marker = build_pipeline_admission(
        freeze, repo=repo, review_commit=review)
    assert built_marker == marker
    reauthenticate_pipeline_admission(
        freeze, admission, repo=repo, review_marker=marker)
    tombstone = pipeline_consumption_tombstone_bytes(admission)
    assert b'"retry_authorized":false' in tombstone


def test_review_refuses_local_remote_tracking_forgery(tmp_path, monkeypatch):
    freeze = _freeze()
    repo, review, _ = _review_repo(tmp_path, freeze, monkeypatch)
    base = _git(repo, "rev-parse", "HEAD^")
    _git(repo, "update-ref", "refs/remotes/origin/main", base)
    with pytest.raises(BeliefV2FreezeError,
                       match="differs from real remote"):
        authenticate_execution_review(
            freeze, repo=repo, review_commit=review)

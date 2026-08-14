"""One-review BELIEF-V1 B2 execution-design tests."""

from __future__ import annotations

from dataclasses import replace
import subprocess

import pytest
import torch

from shengji.rl.belief_b2_execution import (
    REQUIRED_ENVIRONMENT,
    REQUIRED_EXACT_PATHS,
    B2ExecutionDesignV1,
    BeliefB2ExecutionError,
    RuntimeProfileV1,
    SourceBindingV1,
    REVIEW_PREFIX,
    authenticate_review_commit,
    build_runtime_profile,
    build_pipeline_admission,
    execution_design_from_bytes,
    expected_review_claim,
    pipeline_admission_from_bytes,
    pipeline_admission_review_commit,
    validate_execution_design,
)
from shengji.rl.belief_contract import canonical_json_bytes


def _sha(label: str) -> str:
    import hashlib
    return hashlib.sha256(label.encode()).hexdigest()


def _runtime() -> RuntimeProfileV1:
    return RuntimeProfileV1(
        hostname="opened-dev-host", operating_system="test-os",
        machine="x86_64", cpu_count=16, memory_bytes=32 << 30,
        python_executable="/runtime/python",
        python_resolved_executable="/runtime/python3.14",
        python_executable_sha256=_sha("python"),
        python_version="3.14.0", torch_version="2.9.0",
        torch_config_sha256=_sha("torch-config"),
        numpy_version="2.3.0", native_path="/runtime/_fast.so",
        native_sha256=_sha("native"),
        required_environment=REQUIRED_ENVIRONMENT)


def _design() -> B2ExecutionDesignV1:
    paths = (*REQUIRED_EXACT_PATHS,
             "server/shengji/rl/belief_b2_execution.py")
    bindings = tuple(SourceBindingV1(
        path=path, byte_count=index + 1, sha256=_sha(path))
                     for index, path in enumerate(sorted(paths)))
    return B2ExecutionDesignV1(
        execution_git="a" * 40, source_bindings=bindings,
        runtime=_runtime(), evidence_root="/evidence/belief-v1-b2")


def test_one_design_binds_every_stage_and_only_one_external_review():
    design = _design()
    validate_execution_design(design)
    assert execution_design_from_bytes(design.canonical_bytes()) == design
    payload = design.to_dict()
    claim = expected_review_claim(design)
    assert payload["population"] == {
        "round_count": 4096, "capture_lanes": 16,
        "retry_count": 0, "drop_count": 0}
    assert set(payload["review"]) == {
        "one_consolidated_external_review_required", "review_schema",
        "review_prefix"}
    assert claim["design_sha256"] == design.sha256()
    assert claim[
        "capture_reference_training_and_one_test_open_authorized"] is True
    assert not any(claim[key] for key in (
        "retry_authorized", "sampler_implementation_authorized",
        "gameplay_strength_screen_authorized", "strength_claim_authorized",
        "promotion_authorized", "deployment_authorized"))


def test_design_refuses_missing_sources_runtime_and_authority_drift():
    design = _design()
    with pytest.raises(BeliefB2ExecutionError, match="source closure"):
        validate_execution_design(replace(
            design, source_bindings=design.source_bindings[1:]))
    with pytest.raises(BeliefB2ExecutionError, match="runtime profile"):
        validate_execution_design(replace(
            design, runtime=replace(design.runtime, torch_num_threads=2)))
    with pytest.raises(BeliefB2ExecutionError, match="drift"):
        validate_execution_design(replace(
            design, evidence_root="relative/evidence"))
    with pytest.raises(BeliefB2ExecutionError, match="source binding"):
        validate_execution_design(replace(
            design, source_bindings=(replace(
                design.source_bindings[0], byte_count=-1),
                                     *design.source_bindings[1:])))
    changed = replace(
        design.source_bindings[-1], sha256="F" * 64)
    with pytest.raises(BeliefB2ExecutionError, match="source binding"):
        validate_execution_design(replace(
            design, source_bindings=(*design.source_bindings[:-1], changed)))


def test_runtime_profile_refuses_declared_mode_without_live_mode(monkeypatch):
    monkeypatch.setattr(torch, "get_num_threads", lambda: 2)
    with pytest.raises(BeliefB2ExecutionError, match="numerical mode"):
        build_runtime_profile()


def test_design_digest_changes_for_source_runtime_and_root():
    design = _design()
    changed_source = replace(
        design.source_bindings[-1], sha256=_sha("changed"))
    variants = (
        replace(design, source_bindings=(
            *design.source_bindings[:-1], changed_source)),
        replace(design, runtime=replace(
            design.runtime, native_sha256=_sha("other-native"))),
        replace(design, evidence_root="/other/evidence"),
    )
    assert all(item.sha256() != design.sha256() for item in variants)


def test_design_reopen_refuses_duplicate_noncanonical_and_derived_drift():
    raw = _design().canonical_bytes()
    with pytest.raises(BeliefB2ExecutionError, match="duplicate"):
        execution_design_from_bytes(raw.replace(
            b'{"authority":', b'{"authority":{},"authority":', 1))
    with pytest.raises(BeliefB2ExecutionError, match="canonical"):
        execution_design_from_bytes(raw.replace(b'"cpu_count":16',
                                                b'"cpu_count": 16'))
    with pytest.raises(BeliefB2ExecutionError, match="reconstruction"):
        execution_design_from_bytes(raw.replace(
            b'"capture_lanes":16', b'"capture_lanes":15'))


def _git(repo, *args, env=None):
    return subprocess.run(
        ("git", *args), cwd=repo, check=True, capture_output=True,
        text=True, env=env).stdout.strip()


def test_one_canonical_claude_marker_authorizes_the_whole_offline_pipeline(
        tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Jerry")
    _git(repo, "config", "user.email", "jerry@example.com")
    ledger = repo / "HANDOFF_REVIEW.md"
    ledger.write_text("# Review ledger\n")
    _git(repo, "add", "HANDOFF_REVIEW.md")
    _git(repo, "commit", "-qm", "Initialize ledger")
    design = _design()
    marker = REVIEW_PREFIX.encode() + canonical_json_bytes(
        expected_review_claim(design))
    with ledger.open("ab") as handle:
        handle.write(marker)
    _git(repo, "add", "HANDOFF_REVIEW.md")
    _git(repo, "-c", "user.name=Claude",
         "-c", "user.email=noreply@anthropic.com", "commit", "-qm",
         "Review Belief V1 B2\n\n"
         "Claude-Session: https://claude.ai/code/session_fixture")
    commit = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", commit)
    assert authenticate_review_commit(
        design, repo=repo.resolve(), review_commit=commit) == marker
    admission = build_pipeline_admission(
        design, review_commit=commit, review_marker=marker)
    assert pipeline_admission_from_bytes(
        admission.canonical_bytes(), design=design,
        review_marker=marker) == admission
    assert pipeline_admission_review_commit(
        admission.canonical_bytes()) == commit
    assert admission.to_dict()["authority"] == {
        "capture_authorized": True,
        "reference_generation_authorized": True,
        "training_authorized": True,
        "one_test_split_open_authorized": True,
        "terminal_reconstruction_authorized": True,
        "retry_authorized": False,
        "sampler_implementation_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "promotion_authorized": False,
        "deployment_authorized": False,
    }

    changed = replace(design, evidence_root="/different/evidence")
    with pytest.raises(BeliefB2ExecutionError, match="marker"):
        authenticate_review_commit(
            changed, repo=repo.resolve(), review_commit=commit)
    with pytest.raises(BeliefB2ExecutionError, match="drift"):
        pipeline_admission_from_bytes(
            admission.canonical_bytes().replace(
                b'"retry_authorized":false',
                b'"retry_authorized":true'),
            design=design, review_marker=marker)
    with pytest.raises(BeliefB2ExecutionError, match="duplicate"):
        pipeline_admission_review_commit(
            admission.canonical_bytes().replace(
                b'{"authority":', b'{"authority":{},"authority":', 1))

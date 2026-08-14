"""One-review BELIEF-V1 B2 execution-design tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from shengji.rl.belief_b2_execution import (
    REQUIRED_ENVIRONMENT,
    REQUIRED_EXACT_PATHS,
    B2ExecutionDesignV1,
    BeliefB2ExecutionError,
    RuntimeProfileV1,
    SourceBindingV1,
    expected_review_claim,
    validate_execution_design,
)


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
    with pytest.raises(BeliefB2ExecutionError, match="identity"):
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

"""Durable exact-lane tests for the BELIEF-V1 B2 controller."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

import shengji.rl.belief_b2_controller as controller
from shengji.rl.belief_b2_controller import (
    BeliefB2ControllerError,
    reference_lane_jobs,
    reopen_capture_lane,
    reopen_reference_lane,
    run_capture_lane,
    run_reference_lane,
)
from shengji.rl.belief_b2_execution import (
    REQUIRED_ENVIRONMENT,
    REQUIRED_EXACT_PATHS,
    REVIEW_PREFIX,
    B2ExecutionDesignV1,
    RuntimeProfileV1,
    SourceBindingV1,
    build_pipeline_admission,
    expected_review_claim,
)
from shengji.rl.belief_contract import canonical_json_bytes


@dataclass(frozen=True)
class _FakeCaptured:
    round_seed: int

    def manifest_sha256(self):
        return _sha(f"capture-manifest-{self.round_seed}")


@dataclass(frozen=True)
class _FakeReference:
    captured: _FakeCaptured
    replicate: str

    def manifest_dict(self):
        return {
            "decision_count": 1,
            "accepted_world_count": 256,
            "attempt_count": 256,
        }

    def manifest_sha256(self):
        return _sha(f"reference-{self.captured.round_seed}-{self.replicate}")


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _design(root) -> B2ExecutionDesignV1:
    paths = (*REQUIRED_EXACT_PATHS,
             "server/shengji/rl/belief_b2_controller.py")
    bindings = tuple(SourceBindingV1(
        path=path, byte_count=index, sha256=_sha(path))
                     for index, path in enumerate(sorted(paths)))
    runtime = RuntimeProfileV1(
        hostname="test", operating_system="test", machine="x86_64",
        cpu_count=16, memory_bytes=32 << 30,
        python_executable="/runtime/python",
        python_resolved_executable="/runtime/python",
        python_executable_sha256=_sha("python"), python_version="3.14",
        torch_version="2.9", torch_config_sha256=_sha("torch"),
        numpy_version="2.3", native_path="/runtime/_fast.so",
        native_sha256=_sha("fast"),
        required_environment=REQUIRED_ENVIRONMENT)
    return B2ExecutionDesignV1(
        execution_git="a" * 40, source_bindings=bindings,
        runtime=runtime, evidence_root=str(root))


def test_exact_capture_lane_publishes_and_reopens_all_256_rounds(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    design = _design(root)
    marker = REVIEW_PREFIX.encode() + canonical_json_bytes(
        expected_review_claim(design))
    admission = build_pipeline_admission(
        design, review_commit="b" * 40, review_marker=marker)

    def binding(seed):
        return SimpleNamespace(
            capture_manifest_sha256=_sha(f"manifest-{seed}"),
            public_transcript_sha256=_sha(f"transcript-{seed}"),
            actor_stream_sha256=_sha(f"actor-{seed}"),
            privileged_target_stream_sha256=_sha(f"target-{seed}"),
            decision_count=1)

    monkeypatch.setattr(
        controller, "capture_champion_round",
        lambda seed, _policy_seeds: _FakeCaptured(seed))
    monkeypatch.setattr(
        controller, "captured_round_artifacts", lambda captured: captured)
    monkeypatch.setattr(
        controller, "capture_bundle_bytes",
        lambda artifacts: str(artifacts.round_seed).encode("ascii"))
    monkeypatch.setattr(
        controller, "population_round_from_artifacts",
        lambda artifacts: binding(artifacts.round_seed))
    monkeypatch.setattr(
        controller, "reopen_capture_bundle",
        lambda raw: _FakeCaptured(int(raw)))
    monkeypatch.setattr(
        controller, "reopen_captured_round_artifacts",
        lambda artifacts: artifacts)
    result = run_capture_lane(
        root, design, admission, lane=0, review_marker=marker)
    directory = root / "capture/lane-00"
    assert result["round_count"] == 256
    assert len(result["rounds"]) == 256
    assert not (root / "capture/lane-00.partial").exists()
    assert reopen_capture_lane(
        directory, design=design, admission=admission, lane=0) == result
    assert all(not path.stat().st_mode & 0o222 and path.stat().st_nlink == 1
               for path in directory.iterdir())

    foreign = directory / "foreign"
    foreign.write_bytes(b"x")
    with pytest.raises(BeliefB2ControllerError, match="population"):
        reopen_capture_lane(
            directory, design=design, admission=admission, lane=0)
    foreign.unlink()

    assert sum(len(reference_lane_jobs(lane)) for lane in range(16)) == 1224
    monkeypatch.setattr(
        controller, "capture_champion_round_with_ref_c",
        lambda seed, replicate: _FakeReference(
            _FakeCaptured(seed), replicate))
    monkeypatch.setattr(
        controller, "reference_round_bundle_bytes",
        lambda result: (
            f"{result.captured.round_seed}|{result.replicate}".encode()))

    def reopen_reference(raw):
        seed, replicate = raw.decode().split("|", 1)
        return _FakeReference(_FakeCaptured(int(seed)), replicate)

    monkeypatch.setattr(
        controller, "reopen_reference_round_bundle", reopen_reference)
    reference = run_reference_lane(
        root, design, admission, lane=0, review_marker=marker)
    reference_directory = root / "reference/lane-00"
    assert reference["job_count"] == len(reference_lane_jobs(0))
    assert reopen_reference_lane(
        reference_directory, capture_directory=directory,
        design=design, admission=admission, lane=0) == reference

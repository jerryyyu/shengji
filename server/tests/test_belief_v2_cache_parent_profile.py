"""Wiring and tamper witnesses for the bounded R5 parent profiler."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from tests.test_belief_v2_parallel_cache import _fixture


SCRIPT = (Path(__file__).parents[1] / "scripts"
          / "belief_v2_cache_parent_profile.py")
SPEC = importlib.util.spec_from_file_location("cache_parent_profile", SCRIPT)
PROFILE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PROFILE)


def test_quantile_sample_is_exact_distinct_and_endpoint_bound():
    assert PROFILE._sample_indices(10, 4) == (0, 3, 6, 9)
    assert PROFILE._sample_indices(65, 64)[0] == 0
    assert PROFILE._sample_indices(65, 64)[-1] == 64
    assert len(set(PROFILE._sample_indices(65, 64))) == 64
    with pytest.raises(PROFILE.BeliefV2CacheParentProfileError,
                       match="sample inputs"):
        PROFILE._sample_indices(10, 11)


def test_profile_run_reopens_and_summary_tamper_refuses(
        tmp_path, monkeypatch):
    (index, realization, _batches, freeze, admission,
     binding) = _fixture(tmp_path, monkeypatch)
    root = (tmp_path / "profile-evidence").resolve()
    root.mkdir()
    inputs = SimpleNamespace(index=index)
    context = (
        freeze, admission, {"index_sha256": "a" * 64}, inputs,
        realization, realization, (0,), binding)
    monkeypatch.setattr(PROFILE, "_clean_git_head", lambda _expected: None)
    monkeypatch.setattr(
        PROFILE, "_context_and_sample",
        lambda _root, _count: context)
    monkeypatch.setattr(
        PROFILE, "parallel_cache_worker_count", lambda *_args: 2)

    args = SimpleNamespace(
        root=str(root), scratch=str(tmp_path / "profile-scratch"),
        out=str(tmp_path / "profile-receipt.json"),
        expected_source_git="f" * 40,
        expected_failed_freeze_sha256=freeze.sha256(),
        expected_failed_admission_sha256=admission.sha256(),
        expected_index_sha256="a" * 64,
        expected_worker_count=2, sample_batch_count=1)
    result = PROFILE.run(args)
    receipt = result["receipt"]
    assert receipt["sample_batch_count"] == 1
    assert receipt["sample_cache_reopened"] is True
    assert receipt["quantile_sample_is_not_full_capacity_evidence"] is True
    assert receipt["synthetic_test_targets_opened"] is False
    assert receipt["human_test_targets_opened"] is False
    assert receipt["outcome_fields_opened"] is False
    assert all(value is False for value in receipt["authority"].values())

    verify_args = SimpleNamespace(
        root=str(root), scratch=str(tmp_path / "profile-scratch"),
        receipt=str(tmp_path / "profile-receipt.json"),
        expected_source_git="f" * 40)
    assert PROFILE.verify(verify_args)["status"] \
        == "VERIFIED_SCORE_FREE_PARENT_PROFILE"

    path = tmp_path / "profile-receipt.json"
    path.chmod(0o600)
    tampered = json.loads(path.read_bytes())
    tampered["phase_summary"][0]["wall_nanoseconds"] += 1
    path.write_bytes(canonical_json_bytes(tampered))
    path.chmod(0o400)
    with pytest.raises(PROFILE.BeliefV2CacheParentProfileError,
                       match="summary reconstruction"):
        PROFILE.verify(verify_args)

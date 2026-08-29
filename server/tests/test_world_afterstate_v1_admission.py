from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v1_admission import (
    ADMISSION_AUTHORITY, WorldAfterstateV1AdmissionError,
    build_admission, expected_review_claim, validate_admission)
from shengji.rl.world_afterstate_v1_experiment import (
    build_experiment_freeze)

import shengji.rl.world_afterstate_v1_admission as admission
from test_world_afterstate_v1_experiment import _inputs


def _freeze():
    capacity, runtime, sources = _inputs()
    return build_experiment_freeze(
        capacity, source_git="a" * 40,
        source_sha256s=sources, experiment_runtime=runtime)


def _git_fixture(monkeypatch, freeze):
    review = "b" * 40
    parent = "c" * 40
    remote = "d" * 40
    previous = b"# ledger\n"
    marker = admission.REVIEW_PREFIX.encode("ascii") \
        + canonical_json_bytes(expected_review_claim(freeze))
    current = previous + marker
    monkeypatch.setattr(
        admission, "_canonical_remote_tip", lambda _repo: remote)

    def fake_git(_repo, *arguments, binary=False):
        if arguments == ("rev-parse", "origin/main"):
            return remote
        if arguments == ("show", "-s", "--format=%P", review):
            return parent
        if arguments[:3] == ("show", "-s", "--format=%an"):
            return admission.REVIEWER_NAME
        if arguments[:3] == ("show", "-s", "--format=%ae"):
            return admission.REVIEWER_EMAIL
        if arguments[:3] == ("show", "-s", "--format=%cn"):
            return admission.REVIEWER_NAME
        if arguments[:3] == ("show", "-s", "--format=%ce"):
            return admission.REVIEWER_EMAIL
        if arguments == ("show", "-s", "--format=%B", review):
            return admission.REVIEWER_SESSION_TRAILER + "fixture"
        if arguments[:5] == (
                "diff-tree", "--no-commit-id", "--name-only", "-r",
                review):
            return admission.REVIEW_LEDGER
        if arguments == (
                "show", f"{review}:{admission.REVIEW_LEDGER}"):
            return current
        if arguments == (
                "show", f"{parent}:{admission.REVIEW_LEDGER}"):
            return previous
        raise AssertionError(arguments)

    monkeypatch.setattr(admission, "_git", fake_git)
    subprocess_calls = []

    def fake_run(*args, **kwargs):
        subprocess_calls.append(args[0])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(admission.subprocess, "run", fake_run)
    return review, marker, subprocess_calls


def test_scientific_review_grants_only_p1_train_calibration_and_reconstruct(
        monkeypatch):
    freeze = _freeze()
    review, marker, subprocess_calls = _git_fixture(monkeypatch, freeze)
    value = build_admission(
        freeze, repo=Path.cwd().parent.resolve(), review_commit=review)
    validate_admission(value, freeze=freeze, review_marker=marker)
    assert subprocess_calls[0] == (
        "git", "fetch", "--quiet", "origin", "main")
    assert value["authority"] == ADMISSION_AUTHORITY
    assert value["authority"]["scientific_p1_training_authorized"] is True
    assert value["authority"][
        "v0_calibration_label_opening_authorized"] is True
    for key in (
            "report_row_opening_authorized",
            "provider_audit_row_opening_authorized", "p2_execution_authorized",
            "gameplay_authorized", "strength_claim_authorized",
            "merge_authorized", "promotion_authorized",
            "deployment_authorized", "retry_authorized", "r5_authorized"):
        assert value["authority"][key] is False


def test_scientific_review_marker_and_claim_mutations_refuse(monkeypatch):
    freeze = _freeze()
    review, marker, _subprocess_calls = _git_fixture(monkeypatch, freeze)
    value = build_admission(
        freeze, repo=Path.cwd().parent.resolve(), review_commit=review)
    with pytest.raises(WorldAfterstateV1AdmissionError,
                       match="admission identity drift"):
        validate_admission(
            value, freeze=freeze,
            review_marker=marker.replace(b"scientific", b"SCI"))

    forged = copy.deepcopy(value)
    forged["authority"]["report_row_opening_authorized"] = True
    body = {key: item for key, item in forged.items()
            if key != "admission_sha256"}
    forged["admission_sha256"] = admission._sha(body)
    with pytest.raises(WorldAfterstateV1AdmissionError,
                       match="admission identity drift"):
        validate_admission(forged, freeze=freeze, review_marker=marker)

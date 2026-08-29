from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v1_admission import (
    ADMISSION_AUTHORITY, WorldAfterstateV1AdmissionError,
    authenticate_capacity_operator_reentry,
    authenticate_capacity_operator_reentry_v2, build_admission,
    expected_capacity_operator_reentry_claim, expected_review_claim,
    expected_capacity_operator_reentry_v2_claim,
    validate_admission, validate_capacity_operator_reentry,
    validate_capacity_operator_reentry_v2)
from shengji.rl.world_afterstate_v1_experiment import (
    build_experiment_freeze)

import shengji.rl.world_afterstate_v1_admission as admission
from test_world_afterstate_v1_experiment import _inputs


def _freeze():
    capacity, runtime, sources, reentry, reentry_v2 = _inputs()
    return build_experiment_freeze(
        capacity, source_git="a" * 40,
        source_sha256s=sources, experiment_runtime=runtime,
        scientific_root="/opt/value-afterstate-v1-p1-scientific-test",
        capacity_operator_reentry=reentry,
        capacity_operator_reentry_v2=reentry_v2)


def _git_fixture(monkeypatch, freeze, *, marker_mode="append"):
    review = "b" * 40
    parent = "c" * 40
    remote = "d" * 40
    prior_claim = copy.deepcopy(expected_review_claim(freeze))
    prior_claim["source_git"] = "e" * 40
    prior_marker = admission.REVIEW_PREFIX.encode("ascii") \
        + canonical_json_bytes(prior_claim)
    previous = b"# ledger\n" + prior_marker
    marker = admission.REVIEW_PREFIX.encode("ascii") \
        + canonical_json_bytes(expected_review_claim(freeze))
    if marker_mode == "append":
        current = previous + marker
    elif marker_mode == "missing":
        current = previous
    elif marker_mode == "duplicate":
        current = previous + marker + marker
    elif marker_mode == "replay":
        previous += marker
        current = previous + marker
    else:
        raise AssertionError(marker_mode)
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


def test_scientific_review_appends_after_prior_marker_and_grants_only_p1(
        monkeypatch):
    freeze = _freeze()
    review, marker, subprocess_calls = _git_fixture(monkeypatch, freeze)
    value = build_admission(
        freeze, repo=Path.cwd().parent.resolve(), review_commit=review)
    validate_admission(value, freeze=freeze, review_marker=marker)
    assert subprocess_calls[0] == (
        "git", "fetch", "--quiet", admission.CANONICAL_REMOTE_URL,
        f"{admission.CANONICAL_REMOTE_REF}:refs/remotes/origin/main")
    assert value["authority"] == ADMISSION_AUTHORITY
    assert expected_review_claim(freeze)["scientific_root"] \
        == freeze["scientific_root"]
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


@pytest.mark.parametrize("marker_mode", ("missing", "duplicate", "replay"))
def test_scientific_review_refuses_missing_duplicate_or_replayed_marker(
        monkeypatch, marker_mode):
    freeze = _freeze()
    review, _marker, _subprocess_calls = _git_fixture(
        monkeypatch, freeze, marker_mode=marker_mode)
    with pytest.raises(WorldAfterstateV1AdmissionError,
                       match="review marker introduction drift"):
        build_admission(
            freeze, repo=Path.cwd().parent.resolve(), review_commit=review)


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


def test_capacity_operator_reentry_is_exact_external_command_authority(
        monkeypatch):
    review = "1" * 40
    parent = "2" * 40
    remote = "3" * 40
    claim = expected_capacity_operator_reentry_claim()
    marker = admission.CAPACITY_REENTRY_PREFIX.encode("ascii") \
        + canonical_json_bytes(claim)
    prior_claim = copy.deepcopy(claim)
    prior_claim["failed_service"] = "prior-capacity-attempt.service"
    prior_marker = admission.CAPACITY_REENTRY_PREFIX.encode("ascii") \
        + canonical_json_bytes(prior_claim)
    previous = b"# ledger\n" + prior_marker
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
    monkeypatch.setattr(
        admission.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0))
    value = authenticate_capacity_operator_reentry(
        repo=Path.cwd().parent.resolve(), review_commit=review)
    validate_capacity_operator_reentry(value)
    assert value["claim"] == claim
    assert value["claim"]["train_row_bytes_opened"] is False
    assert value["claim"]["authority"] \
        ["train_only_corrected_capacity_execution_authorized"] is True
    assert all(item is False for key, item in value["claim"][
        "authority"].items()
               if key != "train_only_corrected_capacity_execution_authorized")

    forged = copy.deepcopy(value)
    forged["claim"]["train_row_bytes_opened"] = True
    body = {key: item for key, item in forged.items()
            if key != "authentication_sha256"}
    forged["authentication_sha256"] = admission._sha(body)
    with pytest.raises(WorldAfterstateV1AdmissionError,
                       match="identity drift"):
        validate_capacity_operator_reentry(forged)

    def duplicate_git(_repo, *arguments, binary=False):
        if arguments == (
                "show", f"{parent}:{admission.REVIEW_LEDGER}"):
            return previous + marker
        return fake_git(_repo, *arguments, binary=binary)

    monkeypatch.setattr(admission, "_git", duplicate_git)
    with pytest.raises(WorldAfterstateV1AdmissionError,
                       match="marker introduction drift"):
        authenticate_capacity_operator_reentry(
            repo=Path.cwd().parent.resolve(), review_commit=review)


def test_second_capacity_operator_reentry_binds_stale_ref_failure(
        monkeypatch):
    review = "4" * 40
    parent = "5" * 40
    remote = "6" * 40
    first_claim = expected_capacity_operator_reentry_claim()
    first_marker = admission.CAPACITY_REENTRY_PREFIX.encode("ascii") \
        + canonical_json_bytes(first_claim)
    previous = b"# ledger\n" + first_marker
    claim = expected_capacity_operator_reentry_v2_claim()
    marker = admission.CAPACITY_REENTRY_V2_PREFIX.encode("ascii") \
        + canonical_json_bytes(claim)
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
    monkeypatch.setattr(
        admission.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0))
    value = authenticate_capacity_operator_reentry_v2(
        repo=Path.cwd().parent.resolve(), review_commit=review)
    validate_capacity_operator_reentry_v2(value)
    assert value["claim"] == claim
    assert value["claim"]["progress_records_emitted"] == 0
    assert value["claim"]["prelaunch_canonical_ref_refresh_required"] \
        is True
    assert value["claim"]["authority"] \
        ["train_only_second_corrected_capacity_execution_authorized"] is True

    forged = copy.deepcopy(value)
    forged["claim"]["prelaunch_canonical_ref_refresh_required"] = False
    body = {key: item for key, item in forged.items()
            if key != "authentication_sha256"}
    forged["authentication_sha256"] = admission._sha(body)
    with pytest.raises(WorldAfterstateV1AdmissionError,
                       match="identity drift"):
        validate_capacity_operator_reentry_v2(forged)

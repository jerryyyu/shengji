from __future__ import annotations

import hashlib
import subprocess

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_admission import (
    ADMISSION_AUTHORITY, ADMISSION_SCHEMA, REVIEW_PREFIX,
    WorldAfterstateAdmissionError, authenticate_review_commit, build_admission,
    expected_review_claim, reauthenticate_admission, validate_admission)


def _freeze():
    return {
        "source_git": "a" * 40,
        "freeze_sha256": "f" * 64,
        "capacity": {"external_sha256": "c" * 64},
        "population_packet": {
            "external_sha256": "d" * 64,
            "population_manifest_sha256": "e" * 64,
        },
    }


def test_admission_marker_and_authority_are_exact():
    freeze = _freeze()
    claim = expected_review_claim(freeze)
    marker = REVIEW_PREFIX.encode("ascii") + canonical_json_bytes(claim)
    body = {
        "schema": ADMISSION_SCHEMA,
        "source_git": freeze["source_git"],
        "freeze_sha256": freeze["freeze_sha256"],
        "review_commit": "b" * 40,
        "canonical_remote_tip_at_admission": "b" * 40,
        "review_marker_sha256": hashlib.sha256(marker).hexdigest(),
        "authority": dict(ADMISSION_AUTHORITY),
    }
    admission = {**body, "admission_sha256": hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()}
    validate_admission(admission, freeze=freeze, review_marker=marker)

    forged = dict(admission)
    forged["authority"] = {**ADMISSION_AUTHORITY,
                           "deployment_authorized": True}
    with pytest.raises(WorldAfterstateAdmissionError,
                       match="identity drift"):
        validate_admission(forged, freeze=freeze, review_marker=marker)


def test_review_commit_must_be_one_append_only_authenticated_marker(
        monkeypatch, tmp_path):
    freeze = _freeze()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(("git", "init", "-q"), cwd=repo, check=True)
    subprocess.run(("git", "config", "user.name", "Owner"),
                   cwd=repo, check=True)
    subprocess.run(("git", "config", "user.email", "owner@example.com"),
                   cwd=repo, check=True)
    ledger = repo / "HANDOFF_REVIEW.md"
    ledger.write_text("# Reviews\n", encoding="ascii")
    subprocess.run(("git", "add", "HANDOFF_REVIEW.md"), cwd=repo,
                   check=True)
    subprocess.run(("git", "commit", "-q", "-m", "base"), cwd=repo,
                   check=True)
    marker = REVIEW_PREFIX.encode("ascii") + canonical_json_bytes(
        expected_review_claim(freeze))
    with ledger.open("ab") as handle:
        handle.write(marker)
    subprocess.run(("git", "add", "HANDOFF_REVIEW.md"), cwd=repo,
                   check=True)
    env = {
        **__import__("os").environ,
        "GIT_AUTHOR_NAME": "Claude",
        "GIT_AUTHOR_EMAIL": "noreply@anthropic.com",
        "GIT_COMMITTER_NAME": "Claude",
        "GIT_COMMITTER_EMAIL": "noreply@anthropic.com",
    }
    subprocess.run((
        "git", "commit", "-q", "-m", "review\n\n"
        "Claude-Session: https://claude.ai/code/session_test"),
        cwd=repo, check=True, env=env)
    review = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=repo, check=True,
        capture_output=True, text=True).stdout.strip()
    subprocess.run(("git", "update-ref", "refs/remotes/origin/main",
                    review), cwd=repo, check=True)
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_admission._canonical_remote_tip",
        lambda _repo: review)
    observed, remote = authenticate_review_commit(
        freeze, repo=repo.resolve(), review_commit=review)
    assert observed == marker
    assert remote == review

    ledger.write_text(ledger.read_text() + "extra\n", encoding="ascii")
    subprocess.run(("git", "add", "HANDOFF_REVIEW.md"), cwd=repo,
                   check=True)
    subprocess.run(("git", "commit", "-q", "-m", "second marker"),
                   cwd=repo, check=True)
    second = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=repo, check=True,
        capture_output=True, text=True).stdout.strip()
    subprocess.run(("git", "update-ref", "refs/remotes/origin/main",
                    second), cwd=repo, check=True)
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_admission._canonical_remote_tip",
        lambda _repo: second)
    with pytest.raises(WorldAfterstateAdmissionError):
        authenticate_review_commit(
            freeze, repo=repo.resolve(), review_commit=second)


def test_admission_survives_linear_main_advance_but_refuses_rollback(
        monkeypatch, tmp_path):
    freeze = _freeze()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(("git", "init", "-q"), cwd=repo, check=True)
    subprocess.run(("git", "config", "user.name", "Owner"),
                   cwd=repo, check=True)
    subprocess.run(("git", "config", "user.email", "owner@example.com"),
                   cwd=repo, check=True)
    ledger = repo / "HANDOFF_REVIEW.md"
    ledger.write_text("# Reviews\n", encoding="ascii")
    subprocess.run(("git", "add", "HANDOFF_REVIEW.md"), cwd=repo,
                   check=True)
    subprocess.run(("git", "commit", "-q", "-m", "base"), cwd=repo,
                   check=True)
    marker = REVIEW_PREFIX.encode("ascii") + canonical_json_bytes(
        expected_review_claim(freeze))
    with ledger.open("ab") as handle:
        handle.write(marker)
    subprocess.run(("git", "add", "HANDOFF_REVIEW.md"), cwd=repo,
                   check=True)
    env = {
        **__import__("os").environ,
        "GIT_AUTHOR_NAME": "Claude",
        "GIT_AUTHOR_EMAIL": "noreply@anthropic.com",
        "GIT_COMMITTER_NAME": "Claude",
        "GIT_COMMITTER_EMAIL": "noreply@anthropic.com",
    }
    subprocess.run((
        "git", "commit", "-q", "-m", "review\n\n"
        "Claude-Session: https://claude.ai/code/session_advance"),
        cwd=repo, check=True, env=env)
    review = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=repo, check=True,
        capture_output=True, text=True).stdout.strip()
    subprocess.run(("git", "update-ref", "refs/remotes/origin/main",
                    review), cwd=repo, check=True)
    remote = [review]
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_admission._canonical_remote_tip",
        lambda _repo: remote[0])
    admission = build_admission(
        freeze, repo=repo.resolve(), review_commit=review)

    (repo / "README.md").write_text("later work\n", encoding="ascii")
    subprocess.run(("git", "add", "README.md"), cwd=repo, check=True)
    subprocess.run(("git", "commit", "-q", "-m", "advance"), cwd=repo,
                   check=True)
    advanced = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=repo, check=True,
        capture_output=True, text=True).stdout.strip()
    subprocess.run(("git", "update-ref", "refs/remotes/origin/main",
                    advanced), cwd=repo, check=True)
    remote[0] = advanced
    assert reauthenticate_admission(
        admission, freeze=freeze, repo=repo.resolve()) == marker

    # A canonical rollback is rejected even though the original review commit
    # and marker are still locally present.
    subprocess.run(("git", "update-ref", "refs/remotes/origin/main",
                    review), cwd=repo, check=True)
    remote[0] = review
    forged = dict(admission)
    forged["canonical_remote_tip_at_admission"] = advanced
    body = {key: value for key, value in forged.items()
            if key != "admission_sha256"}
    forged["admission_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()
    with pytest.raises(WorldAfterstateAdmissionError,
                       match="remote rollback drift"):
        reauthenticate_admission(
            forged, freeze=freeze, repo=repo.resolve())

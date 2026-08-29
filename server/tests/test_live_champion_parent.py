"""Mutation boundary for the reusable post-S0 live champion parent."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import live_champion_parent as LIVE  # noqa: E402


def _confirmation_closeout() -> dict:
    return {
        "schema": LIVE.RLCB_CLOSEOUT.SCHEMA,
        "state": "FORMAL_CONFIRMATION_CONFIRMED_ARTIFACT_ONLY",
        "complete": True,
        "artifact_only": True,
        "original_git": LIVE.RLCB_ORIGINAL_GIT,
        "production_promotion": False,
        "automatic_deployment": False,
        "s0c_reopened": False,
        "aggregate": {
            "path": str(LIVE.RLCB_AGGREGATE_PATH),
            "sha256": LIVE.RLCB_AGGREGATE_SHA256,
            "decision": "CONFIRM_REPORT_LCB",
            "formal_confirmation": True,
        },
        "freeze_receipt": {
            "path": str(LIVE.RLCB_FREEZE_PATH),
            "sha256": LIVE.RLCB_FREEZE_SHA256,
        },
        "closeout_executable": {
            "git": LIVE.RLCB_CLOSEOUT_GIT,
            "script_sha256": LIVE.RLCB_CLOSEOUT_SCRIPT_SHA256,
        },
        "runtime": {
            "fast_binary_sha256": LIVE.FAST_BINARY_SHA256,
            "selection_digest": LIVE.RLCB_SELECTION_DIGEST,
            "policy_contract_sha256s": {
                LIVE.CHAMPION_POLICY:
                LIVE.CHAMPION_POLICY_CONTRACT_SHA256,
            },
            "source_sha256s": dict(LIVE.CHAMPION_SOURCE_SHA256S),
        },
    }


def _confirmation_aggregate() -> dict:
    return {
        "git_sha": LIVE.RLCB_ORIGINAL_GIT,
        "complete": True,
        "decision": "CONFIRM_REPORT_LCB",
        "formal_confirmation": True,
        "production_promotion": False,
        "automatic_deployment": False,
        "selection_digest": LIVE.RLCB_SELECTION_DIGEST,
    }


def test_exact_live_parent_is_report_lcb_and_never_formal_s0():
    parent = LIVE.expected_parent()
    assert LIVE.parent_problems(parent) == []
    assert LIVE.require_parent_payload(parent) == parent
    assert parent["champion_policy"] == "mc-s0-report-lcb"
    assert parent["forbidden_parent_policy"] == "mc-strong"
    assert not any(key.startswith("s0") for key in parent)


@pytest.mark.parametrize(("mutation", "needle"), [
    (lambda parent: parent.__setitem__("champion_policy", "mc-strong"),
     "stale formal-S0"),
    (lambda parent: parent["source_sha256s"].__setitem__(
        "registry", "0" * 64), "frozen v1"),
    (lambda parent: parent.__setitem__(
        "policy_contract_sha256", "0" * 64), "frozen v1"),
    (lambda parent: parent["confirmation"].__setitem__(
        "aggregate_sha256", "0" * 64), "confirmation identity"),
    (lambda parent: parent.__setitem__(
        "s0_parent", {"champion_policy": "mc-strong"}),
     "must not derive authority from formal S0"),
])
def test_parent_mutations_fail_closed(mutation, needle):
    parent = LIVE.expected_parent()
    mutation(parent)
    problems = LIVE.parent_problems(parent)
    assert any(needle in problem for problem in problems)
    with pytest.raises(LIVE.ProtocolRefused):
        LIVE.require_parent_payload(parent)


def test_confirmation_reopener_binds_exact_authority_and_sources():
    closeout = _confirmation_closeout()
    assert LIVE._confirmation_problems(closeout) == []

    for path in (
            ("aggregate", "decision"),
            ("runtime", "fast_binary_sha256"),
            ("runtime", "selection_digest"),
            ("runtime", "policy_contract_sha256s", LIVE.CHAMPION_POLICY),
            ("runtime", "source_sha256s", "registry")):
        broken = copy.deepcopy(closeout)
        target = broken
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = "drift"
        assert LIVE._confirmation_problems(broken)


def test_portable_reopener_binds_sealed_authority_not_historical_paths():
    closeout = _confirmation_closeout()
    aggregate = _confirmation_aggregate()
    # Historical absolute paths are authenticated by the fixed closeout hash,
    # but must not be interpreted as the current execution root on Air.
    closeout["aggregate"]["path"] = \
        "/historical/mini/server/runs/logs/rlcb-c1-150m-v1/aggregate.json"
    closeout["freeze_receipt"]["path"] = \
        "/historical/mini/server/scripts/rlcb_c1_freeze.v1.json"
    assert LIVE._portable_confirmation_problems(closeout, aggregate) == []

    for mutation in (
            lambda c, a: c["aggregate"].__setitem__("decision", "SELECT_NONE"),
            lambda c, a: c["runtime"].__setitem__(
                "fast_binary_sha256", "0" * 64),
            lambda c, a: a.__setitem__("formal_confirmation", False),
            lambda c, a: a.__setitem__("selection_digest", "0" * 64)):
        broken_closeout = copy.deepcopy(closeout)
        broken_aggregate = copy.deepcopy(aggregate)
        mutation(broken_closeout, broken_aggregate)
        assert LIVE._portable_confirmation_problems(
            broken_closeout, broken_aggregate)


def test_parent_payload_copy_cannot_mutate_frozen_constants():
    first = LIVE.expected_parent()
    first["source_sha256s"]["registry"] = "mutated"
    first["production_attestation"]["required_health"]["bot"] = "mc-strong"
    second = LIVE.expected_parent()
    assert second["source_sha256s"] == LIVE.CHAMPION_SOURCE_SHA256S
    assert second["production_attestation"]["required_health"]["bot"] == \
        LIVE.CHAMPION_POLICY


def test_compatible_fast_receipt_replays_exact_histories(
        tmp_path, monkeypatch):
    receipt = LIVE.expected_fast_compatibility_receipt()
    histories = {
        name: [[seat, [f"C{seat}"]]
               for seat in range(count)]
        for name, count in receipt["golden_histories"][
            "case_play_counts"].items()
    }
    receipt_path = tmp_path / "receipt.json"
    golden_path = tmp_path / "golden.json"
    binary_path = tmp_path / "_fast.so"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True))
    golden_path.write_text(json.dumps(histories, sort_keys=True))
    binary_path.write_bytes(b"compatible native binary")

    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(LIVE, "FAST_COMPATIBILITY_RECEIPT_PATH", receipt_path)
    monkeypatch.setattr(
        LIVE, "FAST_COMPATIBILITY_RECEIPT_SHA256", digest(receipt_path))
    monkeypatch.setattr(LIVE, "GOLDEN_HISTORIES_PATH", golden_path)
    monkeypatch.setattr(LIVE, "GOLDEN_HISTORIES_SHA256", digest(golden_path))
    monkeypatch.setattr(
        LIVE, "COMPATIBLE_FAST_BINARY_SHA256", digest(binary_path))
    monkeypatch.setattr(LIVE.platform, "system", lambda: "Linux")
    monkeypatch.setattr(LIVE.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(LIVE.platform, "python_version", lambda: "3.14.4")
    monkeypatch.setattr(LIVE, "_current_engine_histories", lambda: histories)
    monkeypatch.setattr(
        LIVE.C1, "policy_contract", lambda _name: {
            "ballot": LIVE.COMPATIBLE_BALLOT_IDENTITY,
            "semantic": "fixed",
        })
    monkeypatch.setattr(
        LIVE.C1, "stable_digest",
        lambda value: LIVE.POLICY_CONTRACT_WITHOUT_BALLOT_SHA256)
    monkeypatch.setattr(
        LIVE.C1, "policy_contract_sha256s", lambda: {
            LIVE.CHAMPION_POLICY: LIVE.COMPATIBLE_POLICY_CONTRACT_SHA256,
        })
    fast = SimpleNamespace(_fast=SimpleNamespace(__file__=str(binary_path)))

    # The expected receipt is built from the patched constants, so preserve it
    # again after installing the test binary and golden identities.
    receipt = LIVE.expected_fast_compatibility_receipt()
    receipt_path.write_text(json.dumps(receipt, sort_keys=True))
    monkeypatch.setattr(
        LIVE, "FAST_COMPATIBILITY_RECEIPT_SHA256", digest(receipt_path))
    assert LIVE._compatible_fast_problems(fast) == []

    broken = copy.deepcopy(receipt)
    broken["historical_fast_binary_sha256"] = "0" * 64
    receipt_path.write_text(json.dumps(broken, sort_keys=True))
    monkeypatch.setattr(
        LIVE, "FAST_COMPATIBILITY_RECEIPT_SHA256", digest(receipt_path))
    assert "compatible fast receipt contract drifted" in \
        LIVE._compatible_fast_problems(fast)

    receipt_path.write_text(json.dumps(receipt, sort_keys=True))
    monkeypatch.setattr(
        LIVE, "FAST_COMPATIBILITY_RECEIPT_SHA256", digest(receipt_path))
    monkeypatch.setattr(
        LIVE, "_current_engine_histories", lambda: {**histories, "mc-13": []})
    assert "compatible fast full-round replay drifted" in \
        LIVE._compatible_fast_problems(fast)

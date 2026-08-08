"""Mutation boundary for the reusable post-S0 live champion parent."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

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


def test_parent_payload_copy_cannot_mutate_frozen_constants():
    first = LIVE.expected_parent()
    first["source_sha256s"]["registry"] = "mutated"
    first["production_attestation"]["required_health"]["bot"] = "mc-strong"
    second = LIVE.expected_parent()
    assert second["source_sha256s"] == LIVE.CHAMPION_SOURCE_SHA256S
    assert second["production_attestation"]["required_health"]["bot"] == \
        LIVE.CHAMPION_POLICY

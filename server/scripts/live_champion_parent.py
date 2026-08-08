#!/usr/bin/env python3
"""Fail-closed parent authority for post-S0 strength experiments.

Formal S0 selected no policy and therefore resolves to ``mc-strong``.  That is
historically correct, but it is not the policy currently deployed or the
reference that a new strength mechanism must beat.  This module deliberately
does not read the S0 packet.  It authenticates the independently confirmed
``mc-s0-report-lcb`` decision rule against the complete RLCB-C1 artifact
closeout, its frozen source/registry contract, and the compiled ballot binary.

Consumers persist :func:`expected_parent` verbatim and reopen it with
:func:`require_parent_payload`.  A changed champion, stale S0 fallback,
self-consistent evidence rewrite, policy/source drift, or compiled-ballot
drift therefore fails closed before experiment work begins.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import tomllib
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import rlcb_c1 as C1  # noqa: E402
import rlcb_c1_artifact_closeout as RLCB_CLOSEOUT  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402


SCHEMA = "live-champion-parent-v1"
CHAMPION_POLICY = "mc-s0-report-lcb"
FORBIDDEN_STALE_POLICY = "mc-strong"
RLCB_ROOT = SERVER / "runs" / "logs" / "rlcb-c1-150m-v1"
RLCB_CLOSEOUT_PATH = RLCB_ROOT / "artifact_closeout.json"
RLCB_AGGREGATE_PATH = RLCB_ROOT / "aggregate.json"
RLCB_FREEZE_PATH = SERVER / "scripts" / "rlcb_c1_freeze.v1.json"

RLCB_CLOSEOUT_SHA256 = (
    "06dd487de5389bb6ddbad38af39a1150fc98f52e6e6418c482e97ac8f3b7aae5"
)
RLCB_AGGREGATE_SHA256 = (
    "83f5a9df2f1db1fa45d50fb005b941b776d9ecc2c9f8703d3d62efff8f5ef5ea"
)
RLCB_FREEZE_SHA256 = (
    "02c286ed6e431ec807c4fe4040244e11c790c4a5b0ac5dd8f2ba186d275d39d0"
)
RLCB_ORIGINAL_GIT = "ced1033e47bcb27b82136f72c757de40387a94f0"
RLCB_CLOSEOUT_GIT = "57f4e1b4d2d17bac907fd899f44d52cbdc0b4db1"
RLCB_CLOSEOUT_SCRIPT_SHA256 = (
    "82c296cd065c101be5657c7b9bebd64b39c15d8d573c43ed4314d17a08d345f7"
)
RLCB_SELECTION_DIGEST = (
    "e0f758bba627860225debc9a43493f5c7e51ded90256c15961435c6376a33d31"
)
CHAMPION_POLICY_CONTRACT_SHA256 = (
    "59fa033dc22d8a055b5d7f3fbcbaf9d7fb0b71993b74c4d9bb7587e3d90dc72b"
)
FAST_BINARY_SHA256 = (
    "9c9e77fbdc4c6caceec195465155f37ec6369e409462fd838bc142bf8a0be4c1"
)

# These are the transitive source identities used by RLCB-C1 itself.  The
# runner digest is excluded: it establishes the old evaluation, not the live
# champion's gameplay semantics.  All policy, ballot and round sources remain.
CHAMPION_SOURCE_SHA256S = {
    "evaluation": "ae4739a19767391cb9734a59f7b6cf5f4143d44d8de4beb00dcc3c2c96fcbb4c",
    "registry": "dbb2848535eda766df737cda8decffe56e00d514b12ba5fa5c9386ff9d86fd1a",
    "mcbot": "45a82f44b95d1bce5126c63b1a5af6baaed54270aca9d55677b2e0bbb9c9d957",
    "smart": "facfb6a9bb67f82d1bddb855f01ce49adf5f0caaca92bfb5da09ba343c29512c",
    "memory": "905873b332fd54471070b25ce24f100b813c9a9f234c1b50254d00895140cf51",
    "env": "04b1d18e2ad4783c5160913b66c2adf568625de1aaf6bdf300c6a4b00c2f0d8b",
    "ballot": "63e2e94ca12f9ebf8dce30c1a1bdbe3fe9cf6223603677173d4eb75e334845d5",
    "round": "7a91b3573ecb34c488e3960008d21ebfda283e01003f6454a1ffd62c41b9b679",
    "game": "613c5dd72a1cbd3b50a96eef6e0b84746052dc2b0b28fb08005ff34455359e43",
}

PRODUCTION_ATTESTATION = {
    "release": 17,
    "image": "registry.fly.io/shengji:latency-cd6789e",
    "manifest_sha256": (
        "047bcfe4d4573961734a5536ad549605fd0df5e1477d7480cdf322282955b300"
    ),
    "required_health": {"bot": CHAMPION_POLICY, "fast": True},
    "boundary": (
        "Operator-observed deployment identity only. Strength authority comes "
        "from the independently reopened RLCB-C1 confirmation below."
    ),
}


class ProtocolRefused(RuntimeError):
    """The supplied state cannot authenticate the live champion parent."""


def sha256(path: os.PathLike | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while block := fh.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def expected_parent() -> dict:
    """Portable, versioned payload embedded in every descendant artifact."""
    return {
        "schema": SCHEMA,
        "champion_policy": CHAMPION_POLICY,
        "policy_contract_sha256": CHAMPION_POLICY_CONTRACT_SHA256,
        "source_sha256s": dict(CHAMPION_SOURCE_SHA256S),
        "fast_binary_sha256": FAST_BINARY_SHA256,
        "confirmation": {
            "schema": RLCB_CLOSEOUT.SCHEMA,
            "state": "FORMAL_CONFIRMATION_CONFIRMED_ARTIFACT_ONLY",
            "decision": "CONFIRM_REPORT_LCB",
            "artifact_closeout_sha256": RLCB_CLOSEOUT_SHA256,
            "aggregate_sha256": RLCB_AGGREGATE_SHA256,
            "freeze_receipt_sha256": RLCB_FREEZE_SHA256,
            "selection_digest": RLCB_SELECTION_DIGEST,
            "original_git": RLCB_ORIGINAL_GIT,
            "closeout_git": RLCB_CLOSEOUT_GIT,
            "closeout_script_sha256": RLCB_CLOSEOUT_SCRIPT_SHA256,
        },
        "production_attestation": copy.deepcopy(PRODUCTION_ATTESTATION),
        "forbidden_parent_policy": FORBIDDEN_STALE_POLICY,
        "authority": (
            "reference identity for fresh post-S0 experiments only; does not "
            "reopen S0c, promote a treatment, deploy, or prove multi-round strength"
        ),
    }


def parent_problems(parent: object) -> list[str]:
    """Validate a persisted parent without trusting its self-description."""
    if not isinstance(parent, dict):
        return ["live champion parent is not an object"]
    problems = []
    expected = expected_parent()
    if parent != expected:
        problems.append("live champion parent differs from frozen v1 contract")
    if parent.get("champion_policy") != CHAMPION_POLICY:
        problems.append("live champion policy is not exact report-LCB")
    if parent.get("champion_policy") == FORBIDDEN_STALE_POLICY:
        problems.append("stale formal-S0 mc-strong fallback is forbidden")
    if any(key in parent for key in (
            "s0_parent", "terminal_state", "s0_packet", "s0_closeout")):
        problems.append("live parent must not derive authority from formal S0")
    confirmation = parent.get("confirmation")
    if not isinstance(confirmation, dict) or confirmation != expected[
            "confirmation"]:
        problems.append("RLCB-C1 confirmation identity drifted")
    return sorted(set(problems))


def require_parent_payload(parent: object) -> dict:
    problems = parent_problems(parent)
    if problems:
        raise ProtocolRefused("; ".join(problems))
    return dict(parent)


def _confirmation_problems(closeout: dict) -> list[str]:
    problems = []
    aggregate = closeout.get("aggregate", {})
    executable = closeout.get("closeout_executable", {})
    runtime = closeout.get("runtime", {})
    freeze = closeout.get("freeze_receipt", {})
    fixed = {
        "schema": RLCB_CLOSEOUT.SCHEMA,
        "state": "FORMAL_CONFIRMATION_CONFIRMED_ARTIFACT_ONLY",
        "complete": True,
        "artifact_only": True,
        "original_git": RLCB_ORIGINAL_GIT,
        "production_promotion": False,
        "automatic_deployment": False,
        "s0c_reopened": False,
    }
    for key, value in fixed.items():
        if closeout.get(key) != value:
            problems.append(f"RLCB-C1 closeout field drift: {key}")
    if aggregate != {
            "path": str(RLCB_AGGREGATE_PATH),
            "sha256": RLCB_AGGREGATE_SHA256,
            "decision": "CONFIRM_REPORT_LCB",
            "formal_confirmation": True,
    }:
        problems.append("RLCB-C1 aggregate authority drifted")
    if freeze != {
            "path": str(RLCB_FREEZE_PATH), "sha256": RLCB_FREEZE_SHA256}:
        problems.append("RLCB-C1 freeze authority drifted")
    if executable != {
            "git": RLCB_CLOSEOUT_GIT,
            "script_sha256": RLCB_CLOSEOUT_SCRIPT_SHA256,
    }:
        problems.append("RLCB-C1 closeout executable drifted")
    if runtime.get("fast_binary_sha256") != FAST_BINARY_SHA256:
        problems.append("RLCB-C1 compiled binary identity drifted")
    if runtime.get("selection_digest") != RLCB_SELECTION_DIGEST:
        problems.append("RLCB-C1 selection identity drifted")
    contracts = runtime.get("policy_contract_sha256s", {})
    if contracts.get(CHAMPION_POLICY) != CHAMPION_POLICY_CONTRACT_SHA256:
        problems.append("RLCB-C1 champion policy contract drifted")
    sources = runtime.get("source_sha256s", {})
    if {name: sources.get(name) for name in CHAMPION_SOURCE_SHA256S} != \
            CHAMPION_SOURCE_SHA256S:
        problems.append("RLCB-C1 champion source contract drifted")
    return sorted(set(problems))


def _current_policy_problems(fast) -> list[str]:
    problems = C1.protocol_problems(require_receipt=False)
    sources = C1.source_sha256s()
    current_sources = {
        name: sources.get(name) for name in CHAMPION_SOURCE_SHA256S}
    if current_sources != CHAMPION_SOURCE_SHA256S:
        problems.append("current champion transitive source drifted")
    contracts = C1.policy_contract_sha256s()
    if contracts.get(CHAMPION_POLICY) != CHAMPION_POLICY_CONTRACT_SHA256:
        problems.append("current champion policy/registry contract drifted")
    if sha256(fast._fast.__file__) != FAST_BINARY_SHA256:
        problems.append("current compiled ballot binary drifted")
    try:
        bot = make_bot(CHAMPION_POLICY, seed=7)
    except Exception as exc:
        problems.append(
            f"current champion cannot be constructed: {type(exc).__name__}: {exc}")
    else:
        if any(getattr(bot, name, False) for name in (
                "MC_BURY", "STRUCTURED_BURY", "EXACT_ENDGAME",
                "ADAPTIVE_ALLOCATION", "RANDOM_ALLOCATION")):
            problems.append("current champion enables a descendant treatment")
        if (bot.N_DETERMINIZATIONS != 30
                or bot.REPORT_FOLD_WORLDS != 300
                or bot.REPORT_RULE != "lcb"
                or bot.REQUIRE_EXACT_WORK is not True):
            problems.append("current report-LCB decision semantics drifted")
    try:
        fly = tomllib.loads((REPO / "fly.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        problems.append(f"fly policy config unreadable: {exc}")
    else:
        if fly.get("env", {}).get("SHENGJI_BOT") != CHAMPION_POLICY:
            problems.append("fly policy config no longer names live report-LCB")
    return sorted(set(problems))


def require_live_champion_parent() -> dict:
    """Reopen raw confirmation and current semantics, then return the parent."""
    if os.environ.get("SHENGJI_FAST") != "1" or \
            os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise ProtocolRefused("set SHENGJI_FAST=1 and SHENGJI_REQUIRE_VOIDS=1")
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise ProtocolRefused("compiled engine requested but not active")
    if (not RLCB_CLOSEOUT_PATH.is_file()
            or sha256(RLCB_CLOSEOUT_PATH) != RLCB_CLOSEOUT_SHA256):
        raise ProtocolRefused("RLCB-C1 artifact closeout digest mismatch")
    if (not RLCB_AGGREGATE_PATH.is_file()
            or sha256(RLCB_AGGREGATE_PATH) != RLCB_AGGREGATE_SHA256):
        raise ProtocolRefused("RLCB-C1 aggregate digest mismatch")
    try:
        closeout = RLCB_CLOSEOUT.verify(RLCB_ROOT)
    except Exception as exc:
        raise ProtocolRefused(
            f"independent RLCB-C1 reopening failed: {type(exc).__name__}: {exc}") \
            from exc
    problems = _confirmation_problems(closeout)
    problems += _current_policy_problems(fast)
    if problems:
        raise ProtocolRefused("; ".join(sorted(set(problems))))
    return expected_parent()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("verify",))
    parser.parse_args()
    parent = require_live_champion_parent()
    print(json.dumps(parent, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except ProtocolRefused as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc

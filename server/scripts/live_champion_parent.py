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
import platform
import random
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
COMPATIBLE_FAST_BINARY_SHA256 = (
    "a22789a6472de34586176851040bd7ad062440063eb4078e313e95d2dea94509"
)
COMPATIBLE_POLICY_CONTRACT_SHA256 = (
    "0bc5876307c2c060f383817ebbdcd32a5905ce0430a8a42857d6b33471e71cb0"
)
POLICY_CONTRACT_WITHOUT_BALLOT_SHA256 = (
    "6898c2e42f42502e8cebe6b74543a4c3fdbba33f0286a7cc3969bab1ca8c2e05"
)
HISTORICAL_BALLOT_IDENTITY = "mc_candidates@v1[a68f7b8bced6]"
COMPATIBLE_BALLOT_IDENTITY = "mc_candidates@v1[be864762a3fa]"
FAST_COMPATIBILITY_RECEIPT_PATH = (
    SERVER / "scripts" / "live_champion_fast_compatibility.cloud-x86-v1.json"
)
FAST_COMPATIBILITY_RECEIPT_SHA256 = (
    "db72ff2a18ed7e78ceaeba95799d1c677a5e445ba0c3b7f55559260f3afe7dd6"
)
GOLDEN_HISTORIES_PATH = SERVER / "tests" / "golden_histories.json"
GOLDEN_HISTORIES_SHA256 = (
    "7784d0a3c908ac3b51a66ece0b29d4d9fe5501a38d08ad43c83b81b0dc914d8c"
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


def _portable_confirmation_problems(closeout: object,
                                    aggregate: object) -> list[str]:
    """Authenticate sealed RLCB-C1 evidence without replaying its old host.

    ``RLCB_CLOSEOUT.verify`` deliberately reconstructs the original aggregate
    under its immutable Mini hostname, Python version, and absolute execution
    root.  That is the right closeout check on the original machine, but it is
    impossible for a descendant experiment in a clean worktree or on Air.

    The portable boundary is different and narrower: exact SHA-256 identities
    authenticate the already-reviewed closeout and aggregate bytes, this
    function independently checks their authority-bearing fields, and the
    caller separately reopens *current* champion source/policy/native bytes.
    It does not claim to rerun the historical aggregate on a new host.
    """
    if not isinstance(closeout, dict):
        return ["portable RLCB-C1 closeout is not an object"]
    if not isinstance(aggregate, dict):
        return ["portable RLCB-C1 aggregate is not an object"]
    problems = []
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
            problems.append(f"portable closeout field drift: {key}")
    closeout_aggregate = closeout.get("aggregate")
    if (not isinstance(closeout_aggregate, dict)
            or closeout_aggregate.get("sha256") != RLCB_AGGREGATE_SHA256
            or closeout_aggregate.get("decision") != "CONFIRM_REPORT_LCB"
            or closeout_aggregate.get("formal_confirmation") is not True):
        problems.append("portable closeout aggregate authority drifted")
    freeze = closeout.get("freeze_receipt")
    if (not isinstance(freeze, dict)
            or freeze.get("sha256") != RLCB_FREEZE_SHA256):
        problems.append("portable closeout freeze authority drifted")
    if closeout.get("closeout_executable") != {
            "git": RLCB_CLOSEOUT_GIT,
            "script_sha256": RLCB_CLOSEOUT_SCRIPT_SHA256,
    }:
        problems.append("portable closeout executable drifted")
    runtime = closeout.get("runtime")
    if not isinstance(runtime, dict):
        problems.append("portable closeout runtime missing")
    else:
        if runtime.get("fast_binary_sha256") != FAST_BINARY_SHA256:
            problems.append("portable closeout compiled identity drifted")
        if runtime.get("selection_digest") != RLCB_SELECTION_DIGEST:
            problems.append("portable closeout selection identity drifted")
        contracts = runtime.get("policy_contract_sha256s")
        if (not isinstance(contracts, dict)
                or contracts.get(CHAMPION_POLICY) !=
                CHAMPION_POLICY_CONTRACT_SHA256):
            problems.append("portable closeout champion contract drifted")
        sources = runtime.get("source_sha256s")
        if (not isinstance(sources, dict)
                or {name: sources.get(name)
                    for name in CHAMPION_SOURCE_SHA256S} !=
                CHAMPION_SOURCE_SHA256S):
            problems.append("portable closeout champion sources drifted")
    aggregate_fixed = {
        "git_sha": RLCB_ORIGINAL_GIT,
        "complete": True,
        "decision": "CONFIRM_REPORT_LCB",
        "formal_confirmation": True,
        "production_promotion": False,
        "automatic_deployment": False,
    }
    for key, value in aggregate_fixed.items():
        if aggregate.get(key) != value:
            problems.append(f"portable aggregate field drift: {key}")
    if aggregate.get("selection_digest") != RLCB_SELECTION_DIGEST:
        problems.append("portable aggregate selection identity drifted")
    return sorted(set(problems))


def _json_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ProtocolRefused(f"cannot reopen {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProtocolRefused(f"{label} is not an object")
    return value


def _current_policy_problems(
        fast, *, expected_fast_binary_sha256: str = FAST_BINARY_SHA256,
        expected_policy_contract_sha256: str =
        CHAMPION_POLICY_CONTRACT_SHA256,
) -> list[str]:
    problems = C1.protocol_problems(require_receipt=False)
    sources = C1.source_sha256s()
    current_sources = {
        name: sources.get(name) for name in CHAMPION_SOURCE_SHA256S}
    if current_sources != CHAMPION_SOURCE_SHA256S:
        problems.append("current champion transitive source drifted")
    contracts = C1.policy_contract_sha256s()
    if contracts.get(CHAMPION_POLICY) != expected_policy_contract_sha256:
        problems.append("current champion policy/registry contract drifted")
    if sha256(fast._fast.__file__) != expected_fast_binary_sha256:
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


def expected_fast_compatibility_receipt() -> dict:
    """Exact reviewed contract for the Linux/x86 native build.

    The historical RLCB-C1 receipt remains immutable and continues to bind its
    original ARM binary.  This separate receipt permits one additional native
    build only after it reproduces the repository's byte-pinned full-round
    behavior contract at runtime.
    """
    return {
        "schema": "live-champion-fast-compatibility-v1",
        "historical_fast_binary_sha256": FAST_BINARY_SHA256,
        "compatible_fast_binary_sha256": COMPATIBLE_FAST_BINARY_SHA256,
        "compatible_runtime": {
            "system": "Linux",
            "machine": "x86_64",
            "python": "3.14.4",
        },
        "golden_histories": {
            "path": "server/tests/golden_histories.json",
            "sha256": GOLDEN_HISTORIES_SHA256,
            "case_play_counts": {
                "heuristic-11": 80,
                "smart-12": 80,
                "mc-13": 80,
            },
        },
        "policy_contract": {
            "historical_sha256": CHAMPION_POLICY_CONTRACT_SHA256,
            "compatible_sha256": COMPATIBLE_POLICY_CONTRACT_SHA256,
            "contract_without_ballot_sha256":
                POLICY_CONTRACT_WITHOUT_BALLOT_SHA256,
            "historical_ballot": HISTORICAL_BALLOT_IDENTITY,
            "compatible_ballot": COMPATIBLE_BALLOT_IDENTITY,
        },
        "comparison": (
            "exact full-round ordered play histories under the active "
            "compiled engine versus the byte-pinned historical goldens"
        ),
        "authority": {
            "historical_confirmation_rewritten": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }


def _current_engine_histories() -> dict[str, list]:
    """Replay the same complete-round cases used by engine parity tests."""
    from shengji.ai.env import play_round
    from shengji.ai.heuristic import HeuristicBot
    from shengji.ai.mcbot import MCBot
    from shengji.ai.smart import SmartBot
    from shengji.engine.game import Game

    class _FastMC(MCBot):
        N_DETERMINIZATIONS = 3

    def play(bot_factory, seed: int) -> list:
        game = Game(random.Random(seed))
        play_round(game, [bot_factory(index) for index in range(4)])
        return [[move.seat, sorted(move.cards)]
                for trick in game.round.history for move in trick.plays]

    return {
        "heuristic-11": play(lambda _index: HeuristicBot(), 11),
        "smart-12": play(lambda _index: SmartBot(), 12),
        "mc-13": play(lambda index: _FastMC(seed=index), 13),
    }


def _compatible_fast_problems(fast) -> list[str]:
    """Authenticate and replay the reviewed cross-architecture witness."""
    problems = []
    path = FAST_COMPATIBILITY_RECEIPT_PATH
    if path.is_symlink() or not path.is_file():
        return ["compatible fast receipt missing/non-regular"]
    if sha256(path) != FAST_COMPATIBILITY_RECEIPT_SHA256:
        problems.append("compatible fast receipt digest drifted")
    try:
        receipt = _json_object(path, "compatible fast receipt")
    except ProtocolRefused as exc:
        return [str(exc)]
    if receipt != expected_fast_compatibility_receipt():
        problems.append("compatible fast receipt contract drifted")
    if platform.system() != "Linux" or platform.machine() != "x86_64" \
            or platform.python_version() != "3.14.4":
        problems.append("compatible fast runtime identity drifted")
    if sha256(fast._fast.__file__) != COMPATIBLE_FAST_BINARY_SHA256:
        problems.append("compatible compiled ballot binary drifted")
    try:
        policy_contract = C1.policy_contract(CHAMPION_POLICY)
        current_ballot = policy_contract.pop("ballot", None)
        contract_without_ballot = C1.stable_digest(policy_contract)
        current_contract = C1.policy_contract_sha256s().get(CHAMPION_POLICY)
    except Exception as exc:
        problems.append(
            "compatible policy contract replay failed: "
            f"{type(exc).__name__}: {exc}")
    else:
        if current_ballot != COMPATIBLE_BALLOT_IDENTITY:
            problems.append("compatible ballot identity drifted")
        if contract_without_ballot != POLICY_CONTRACT_WITHOUT_BALLOT_SHA256:
            problems.append("compatible policy contract semantics drifted")
        if current_contract != COMPATIBLE_POLICY_CONTRACT_SHA256:
            problems.append("compatible full policy contract drifted")
    if (GOLDEN_HISTORIES_PATH.is_symlink()
            or not GOLDEN_HISTORIES_PATH.is_file()
            or sha256(GOLDEN_HISTORIES_PATH) != GOLDEN_HISTORIES_SHA256):
        problems.append("compatible fast golden histories drifted")
    else:
        try:
            golden = _json_object(
                GOLDEN_HISTORIES_PATH, "compatible fast golden histories")
            current = _current_engine_histories()
        except Exception as exc:
            problems.append(
                "compatible fast replay failed: "
                f"{type(exc).__name__}: {exc}")
        else:
            if current != golden:
                problems.append("compatible fast full-round replay drifted")
            expected_counts = receipt.get("golden_histories", {}).get(
                "case_play_counts", {})
            if {name: len(history) for name, history in current.items()} != \
                    expected_counts:
                problems.append("compatible fast replay case counts drifted")
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


def _require_portable_live_champion_parent(*, compatible_fast: bool) -> dict:
    """Reopen sealed confirmation bytes and current semantics on this host.

    This is for fresh descendant experiments.  It preserves the original
    strict :func:`require_live_champion_parent` unchanged for protocols that
    intentionally require the historical Mini runtime.
    """
    if os.environ.get("SHENGJI_FAST") != "1" or \
            os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise ProtocolRefused("set SHENGJI_FAST=1 and SHENGJI_REQUIRE_VOIDS=1")
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise ProtocolRefused("compiled engine requested but not active")
    artifacts = (
        (RLCB_CLOSEOUT_PATH, RLCB_CLOSEOUT_SHA256,
         "RLCB-C1 artifact closeout"),
        (RLCB_AGGREGATE_PATH, RLCB_AGGREGATE_SHA256,
         "RLCB-C1 aggregate"),
        (RLCB_FREEZE_PATH, RLCB_FREEZE_SHA256,
         "RLCB-C1 freeze receipt"),
    )
    problems = []
    for path, expected_sha256, label in artifacts:
        if path.is_symlink() or not path.is_file():
            problems.append(f"{label} missing/non-regular")
        elif sha256(path) != expected_sha256:
            problems.append(f"{label} digest mismatch")
    if problems:
        raise ProtocolRefused("; ".join(sorted(set(problems))))
    closeout = _json_object(RLCB_CLOSEOUT_PATH, "RLCB-C1 artifact closeout")
    aggregate = _json_object(RLCB_AGGREGATE_PATH, "RLCB-C1 aggregate")
    problems = _portable_confirmation_problems(closeout, aggregate)
    if compatible_fast:
        problems += _compatible_fast_problems(fast)
        problems += _current_policy_problems(
            fast,
            expected_fast_binary_sha256=COMPATIBLE_FAST_BINARY_SHA256,
            expected_policy_contract_sha256=
                COMPATIBLE_POLICY_CONTRACT_SHA256,
        )
    else:
        problems += _current_policy_problems(fast)
    if problems:
        raise ProtocolRefused("; ".join(sorted(set(problems))))
    return expected_parent()


def require_portable_live_champion_parent() -> dict:
    """Reopen on a host carrying the historical compiled binary exactly."""
    return _require_portable_live_champion_parent(compatible_fast=False)


def require_compatible_live_champion_parent() -> dict:
    """Reopen on the one separately reviewed Linux/x86 native build.

    This does not rewrite the historical confirmation or its ARM binary
    identity.  It adds a second, exact runtime check whose complete-round
    behavior is replayed against byte-pinned historical goldens.
    """
    return _require_portable_live_champion_parent(compatible_fast=True)


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

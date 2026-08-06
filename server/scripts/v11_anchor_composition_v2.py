"""Corrected-v2 blind, champion-matched screen for the V11 anchor.

The screen requires the exact frozen ``v11_revalidate_v2.py`` aggregate from
commit cde0fec as a protocol, accepted-dose and matched-null sanity parent.  It
preserves that aggregate's corrected-encoder compatibility verdict verbatim but
does not require it to be true: a direct policy can be weaker than a search
policy while still providing a useful protected proposal.  The policy reference
comes only from the independently verified terminal S0 packet.  Historical
121M/v1 bytes are inadmissible and are never reinterpreted here.

``screen`` is a non-promotable 8x256 mechanism screen on seeds 137M.  It may
authorize exactly one ``confirm`` population: 8x1024 fresh clusters on seeds
138M.  Neither command changes production and even a passing confirmation is
only evidence for a separate deployment review.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import time
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SERVER / "scripts"))

import s0_closeout as S0_CLOSEOUT  # noqa: E402
import v11_revalidate_v2 as DIRECT  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.evaluation import arm_ballots, paired_by_seed, run_arm  # noqa: E402


SCHEMA = "v11-anchor-composition-shard-v2"
AGGREGATE_SCHEMA = "v11-anchor-composition-aggregate-v2"
SHARD_COUNT = 8
EXPECTED_V11_THRESHOLD = 0.02
CHECKPOINT = SERVER / "snapshots_v11pair" / "ep07.npz"
CHECKPOINT_SHA256 = (
    "cd89d6ed7e9d5f798d69ce546107c4dfbef682c5385de39af527026e39e1c003"
)
# The direct block was already running from this clean frozen commit when this
# blind composition question was registered.  A caller-supplied aggregate may
# not substitute another implementation merely by supplying its own hash.
DIRECT_GIT_SHA = "cde0fecf4151685e7174be8a7aa64b0ee6478edd"
# Filled only after all eight cde0fec shards and their independently rebuilt
# aggregate seal.  Until then this versioned consumer is deliberately unable to
# admit a caller-chosen, merely plausible aggregate.  Freezing the SHA needs no
# inspection of its effect values.
DIRECT_AGGREGATE_SHA256: str | None = None
DIRECT_SOURCE_SHA256 = {
    "runner": "9bc265ad3be7e7de40bd70b8c8446c4d2d163918d342ffd56f50173d22d23da2",
    "evaluation": "f579918ad8594c895a1b02f6b2d3cb17dc56ba50092c703f23cc4534a11349c9",
    "registry": "7ed839b75578245e2226ba385a91ced0117a8ee05207b8c5782354316a1f99da",
    "mcbot": "4a268ba1277ab0267974b7cd10d2b69daf52d90cc80917d5b492da27037fce0c",
    "smart": "facfb6a9bb67f82d1bddb855f01ce49adf5f0caaca92bfb5da09ba343c29512c",
    "memory": "905873b332fd54471070b25ce24f100b813c9a9f234c1b50254d00895140cf51",
    "env": "04b1d18e2ad4783c5160913b66c2adf568625de1aaf6bdf300c6a4b00c2f0d8b",
    "ballot": "63e2e94ca12f9ebf8dce30c1a1bdbe3fe9cf6223603677173d4eb75e334845d5",
    "round": "7a91b3573ecb34c488e3960008d21ebfda283e01003f6454a1ffd62c41b9b679",
    "game": "613c5dd72a1cbd3b50a96eef6e0b84746052dc2b0b28fb08005ff34455359e43",
    "torch_policy": "3fcd60a69097ef29d64a0de2f08548c42f6e9ae6ad1be5ad49cc9cc99d068720",
    "encoder": "819fe2b2fc3cb9f0dd18cfd1c916b2387e92d97345f6dda212b2f149c7e7408b",
    "npnet": "0ee6e5e3387c6ce834c9209ebb9ab95421228807c1b4713ca8d34374facd9cbb",
    "parity_fixture": "10af64758fd0a4afb2d647a2a648ca6109195ca47480403a52ba8b5903203a97",
    "fast_router": "f2506d5c51b8ad37303f04dce59899de0d7c1179633b08ce61f48eb86cec1a3e",
    "checkpoint": CHECKPOINT_SHA256,
}
SAMPLER_FLAGS = (
    "SHENGJI_WEIGHTED_SPLITS",
    "SHENGJI_UNIFORM_DEAL",
    "SHENGJI_PHYSICAL_FILLS",
    "SHENGJI_ALLOW_BALLOT_MISMATCH",
)
PROTOCOLS = {
    "screen": {
        "seed0": 137_000_000,
        "clusters": 2_048,
        "clusters_per_shard": 256,
        "claim": "blind_non_promotable_protected_composition_screen",
    },
    "confirm": {
        "seed0": 138_000_000,
        "clusters": 8_192,
        "clusters_per_shard": 1_024,
        "claim": "independent_protected_composition_strength_confirmation",
    },
}
CHAMPION_LANES = {
    "mc-strong": {
        "anchor": "mc-v11anchor",
        "random": "mc-v11anchor-random",
        "null": "mc-strong-null",
    },
    "mc-s0-report-lcb": {
        "anchor": "mc-v11anchor-s0-report-lcb",
        "random": "mc-v11anchor-s0-report-lcb-random",
        "null": "mc-s0-report-lcb-null",
    },
    "mc-s0-adaptive": {
        "anchor": "mc-v11anchor-s0-adaptive",
        "random": "mc-v11anchor-s0-adaptive-random",
        "null": "mc-s0-adaptive-null",
    },
}
SELECTION_RULE = (
    "AUTHORIZE the independent 8x1024 confirmation only if the paired "
    "two-sided 95% lower bounds for anchor-minus-champion, anchor-minus-"
    "same-trigger-random and anchor-minus-champion-matched-null are all >0, "
    "and the champion-matched-null minus champion interval contains zero, "
    "over exactly 2,048 fresh screen clusters. Apply the identical rule to "
    "the 8,192-cluster confirmation. The screen is non-promotable and neither "
    "phase changes production automatically."
)
DIRECT_USAGE = {
    "required_protocol_parent": True,
    "matched_null_sanity_used": True,
    "standalone_authorization_used": False,
    "standalone_superiority_required": False,
}


class ProtocolRefused(RuntimeError):
    pass


def sha256(path: os.PathLike | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while block := fh.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def stable_digest(value) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=list,
    ).encode()).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=SERVER.parent, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _is_sha256(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def write_exclusive_atomic(path: os.PathLike | str, payload: dict) -> None:
    path = Path(path)
    partial = Path(str(path) + ".partial")
    if path.exists() or partial.exists():
        raise ProtocolRefused(f"refusing to overwrite {path} or {partial}")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with partial.open("x") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        publish_partial_exclusive(partial, path)
    except Exception:
        if partial.exists():
            partial.unlink()
        raise


def publish_partial_exclusive(partial: os.PathLike | str,
                              final: os.PathLike | str) -> None:
    """Publish completed bytes without ever replacing a competing result.

    In particular, this is used for the multi-hour shard output.  An existence
    check before the run cannot close the race with another writer at the end;
    ``link`` is the atomic no-clobber operation on the evidence filesystem.
    The partial is deliberately retained when publication loses that race.
    """
    partial = Path(partial)
    final = Path(final)
    if not partial.is_file():
        raise ProtocolRefused(f"completed partial is missing: {partial}")
    try:
        os.link(partial, final)
    except FileExistsError as exc:
        raise ProtocolRefused(
            f"refusing to overwrite concurrently published {final}") from exc
    partial.unlink()


def runtime_identity(fast) -> dict:
    return {
        "host": os.uname().nodename,
        "python": platform.python_version(),
        "fast_engine": True,
        "require_voids": True,
        "experimental_sampler_flags": [],
        "digests": {
            "runner": sha256(__file__),
            "evaluation": sha256(SERVER / "shengji" / "evaluation.py"),
            "registry": sha256(SERVER / "shengji" / "ai" / "registry.py"),
            "mcbot": sha256(SERVER / "shengji" / "ai" / "mcbot.py"),
            "ballot": sha256(SERVER / "shengji" / "engine" / "ballot.py"),
            "torch_policy": sha256(
                SERVER / "shengji" / "rl" / "torch_policy.py"),
            "encoder": sha256(SERVER / "shengji" / "rl" / "encode.py"),
            "npnet": sha256(SERVER / "shengji" / "rl" / "npnet.py"),
            "s0_closeout": sha256(SERVER / "scripts" / "s0_closeout.py"),
            "v11_direct_runner": sha256(
                SERVER / "scripts" / "v11_revalidate_v2.py"),
            "fast_router": sha256(fast.__file__),
            "fast_binary": sha256(fast._fast.__file__),
            "checkpoint": sha256(CHECKPOINT),
        },
    }


def require_runtime() -> tuple[object, dict]:
    if (os.environ.get("SHENGJI_FAST") != "1"
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1"):
        raise ProtocolRefused(
            "set SHENGJI_FAST=1 and SHENGJI_REQUIRE_VOIDS=1")
    enabled = [name for name in SAMPLER_FLAGS if name in os.environ]
    if enabled:
        raise ProtocolRefused(
            f"experimental sampler/ballot flags must be unset: {enabled}")
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise ProtocolRefused("compiled engine requested but not active")
    return fast, runtime_identity(fast)


def _uppercase_contract(bot) -> dict:
    contract = {}
    for name in dir(bot):
        if not name.isupper():
            continue
        value = getattr(bot, name)
        if not isinstance(value, (bool, int, float, str, type(None))):
            raise ProtocolRefused(
                f"non-serializable policy contract {name}={value!r}")
        contract[name] = value
    return contract


def policy_contract(name: str) -> dict:
    bot = make_bot(name, seed=7)
    return {
        "policy": name,
        "class": type(bot).__name__,
        "uppercase": _uppercase_contract(bot),
        "rollout_policy_class": type(bot.rollout_policy).__name__,
        "anchor_mode": getattr(bot, "ANCHOR_MODE", None),
        "anchor_search_base_policy": getattr(
            bot, "anchor_search_base_policy", None),
        "anchor_search_contract_sha256": stable_digest(
            getattr(bot, "anchor_search_contract", None)),
        "checkpoint_path": getattr(bot, "checkpoint_path", None),
        "checkpoint_sha256": getattr(bot, "checkpoint_sha256", None),
    }


def labels_for(champion: str) -> dict[str, str]:
    try:
        lane = CHAMPION_LANES[champion]
    except KeyError as exc:
        raise ProtocolRefused(
            f"terminal S0 policy {champion!r} has no frozen V11 lane") from exc
    return {
        "anchor": lane["anchor"],
        "random": lane["random"],
        "champion": champion,
        "null": lane["null"],
    }


def protocol_problems(champion: str) -> list[str]:
    problems = []
    exact_protocols = {
        "screen": {"seed0": 137_000_000, "clusters": 2_048,
                   "clusters_per_shard": 256,
                   "claim": "blind_non_promotable_protected_composition_screen"},
        "confirm": {"seed0": 138_000_000, "clusters": 8_192,
                    "clusters_per_shard": 1_024,
                    "claim": "independent_protected_composition_strength_confirmation"},
    }
    if SHARD_COUNT != 8 or PROTOCOLS != exact_protocols:
        problems.append("registered phase geometry/seed blocks drifted")
    exact_lanes = {
        "mc-strong": {
            "anchor": "mc-v11anchor", "random": "mc-v11anchor-random",
            "null": "mc-strong-null",
        },
        "mc-s0-report-lcb": {
            "anchor": "mc-v11anchor-s0-report-lcb",
            "random": "mc-v11anchor-s0-report-lcb-random",
            "null": "mc-s0-report-lcb-null",
        },
        "mc-s0-adaptive": {
            "anchor": "mc-v11anchor-s0-adaptive",
            "random": "mc-v11anchor-s0-adaptive-random",
            "null": "mc-s0-adaptive-null",
        },
    }
    if CHAMPION_LANES != exact_lanes:
        problems.append("registered champion composition lanes drifted")
    if not CHECKPOINT.is_file() or sha256(CHECKPOINT) != CHECKPOINT_SHA256:
        problems.append("frozen v11pair checkpoint unavailable or drifted")
    try:
        labels = labels_for(champion)
        bots = {label: make_bot(name, seed=7)
                for label, name in labels.items()}
        contracts = {label: _uppercase_contract(bot)
                     for label, bot in bots.items()}
    except Exception as exc:
        problems.append(f"policy construction failed: {type(exc).__name__}: {exc}")
        return sorted(set(problems))

    anchor_only = {"ANCHOR_MODE", "V11_NPZ_SHA256", "V11_THRESHOLD"}
    base = contracts["champion"]
    for label in ("anchor", "random"):
        comparable = {key: value for key, value in contracts[label].items()
                      if key not in anchor_only}
        if comparable != base:
            problems.append(f"{label} search contract differs from champion")
        bot = bots[label]
        if getattr(bot, "anchor_search_base_policy", None) != champion:
            problems.append(f"{label} names the wrong search base")
        if getattr(bot, "checkpoint_sha256", None) != CHECKPOINT_SHA256:
            problems.append(f"{label} checkpoint identity drifted")
    if getattr(bots["anchor"], "ANCHOR_MODE", None) != "v11":
        problems.append("anchor mode is not v11")
    if getattr(bots["random"], "ANCHOR_MODE", None) != \
            "same_trigger_random":
        problems.append("random control is not same-trigger random")
    if getattr(bots["anchor"], "V11_THRESHOLD", None) != \
            EXPECTED_V11_THRESHOLD:
        problems.append("anchor v11 trigger threshold drifted")
    if getattr(bots["random"], "V11_THRESHOLD", None) != \
            EXPECTED_V11_THRESHOLD:
        problems.append("random control v11 trigger threshold drifted")
    if contracts["null"] != base:
        problems.append("champion-matched null contract differs from champion")
    if type(bots["null"].rollout_policy) is not \
            type(bots["champion"].rollout_policy):
        problems.append("champion-matched null rollout policy differs")
    if bots["null"].rng.getstate() == bots["champion"].rng.getstate():
        problems.append("champion-matched null does not shift its RNG stream")
    for label, bot in bots.items():
        if any(getattr(bot, field, False) for field in
               ("MC_BURY", "STRUCTURED_BURY", "EXACT_ENDGAME")):
            problems.append(f"{label} enables an out-of-scope S3 feature")
    try:
        ballots = arm_ballots(labels.values())
        if len(set(ballots.values())) != 1:
            problems.append(f"composition arms use different ballots: {ballots}")
    except Exception as exc:
        problems.append(f"ballot preflight failed: {type(exc).__name__}: {exc}")
    return sorted(set(problems))


def _terminal_decision(packet_text: str, status: str) -> str:
    prefix = "Final production decision from registered rule: "
    decisions = [line.removeprefix(prefix) for line in packet_text.splitlines()
                 if line.startswith(prefix)]
    if len(decisions) != 1:
        raise ProtocolRefused(
            f"terminal S0 packet has {len(decisions)} production decisions")
    decision = decisions[0]
    if status == "S0_COMPLETE_SELECT_NONE":
        if decision != "SELECT NONE; production remains mc-strong":
            raise ProtocolRefused(
                f"SELECT-NONE packet names a different decision: {decision!r}")
        return "mc-strong"
    if status != "S0_COMPLETE_PROMOTE" or not decision.startswith("PROMOTE "):
        raise ProtocolRefused(
            f"terminal S0 state/decision mismatch: {status!r}, {decision!r}")
    champion = decision.removeprefix("PROMOTE ")
    if champion not in CHAMPION_LANES or champion == "mc-strong":
        raise ProtocolRefused(f"unregistered promoted S0 champion {champion!r}")
    return champion


def load_s0_parent(packet_path: os.PathLike | str, packet_sha256: str,
                   closeout_path: os.PathLike | str,
                   closeout_sha256: str) -> dict:
    packet_path = Path(packet_path)
    closeout_path = Path(closeout_path)
    if not _is_sha256(packet_sha256) or not _is_sha256(closeout_sha256):
        raise ProtocolRefused("terminal S0 expected hashes must be SHA-256")
    if not packet_path.is_file() or sha256(packet_path) != packet_sha256:
        raise ProtocolRefused("terminal S0 packet digest mismatch")
    if not closeout_path.is_file() or sha256(closeout_path) != closeout_sha256:
        raise ProtocolRefused("terminal S0 closeout digest mismatch")
    try:
        packet_text = packet_path.read_text()
        closeout = json.loads(closeout_path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolRefused(f"terminal S0 parent unreadable: {exc}") from exc
    if closeout.get("schema") != "s0-terminal-closeout-v1":
        raise ProtocolRefused("terminal S0 closeout schema")
    status = closeout.get("state")
    if status not in S0_CLOSEOUT.TERMINAL_STATES:
        raise ProtocolRefused(f"S0 closeout is not terminal: {status!r}")
    if closeout.get("packet_sha256") != packet_sha256:
        raise ProtocolRefused("S0 closeout is not bound to the supplied packet")
    phases = S0_CLOSEOUT.packet_phases(packet_text)
    if closeout.get("phases") != phases:
        raise ProtocolRefused("S0 closeout/packet phase coverage differs")
    problems = S0_CLOSEOUT.packet_problems(packet_text, status)
    if problems:
        raise ProtocolRefused(
            "terminal S0 packet contract: " + "; ".join(problems))
    champion = _terminal_decision(packet_text, status)
    return {
        "terminal_state": status,
        "champion_policy": champion,
        "packet_sha256": packet_sha256,
        "closeout_sha256": closeout_sha256,
        "phases": phases,
        "verification_boundary": (
            "exact bytes from independently regenerated terminal S0 closeout"
        ),
    }


def _direct_accepted_dose_from_totals(counters: object) -> dict | None:
    """Rebuild the v2 accepted-dose receipt without trusting stored booleans."""
    if not isinstance(counters, dict) or set(counters) != set(DIRECT.LABELS):
        return None
    cells = {}
    for label in DIRECT.LABELS:
        sides = counters.get(label)
        if not isinstance(sides, dict) or set(sides) != {"arm", "opp"}:
            return None
        cells[label] = {}
        for side in ("arm", "opp"):
            values = sides.get(side)
            if not isinstance(values, dict):
                return None
            searches = values.get("searches")
            accepted = values.get("accepted_worlds")
            if (isinstance(searches, bool) or not isinstance(searches, int)
                    or isinstance(accepted, bool)
                    or not isinstance(accepted, int)):
                return None
            expected_n = DIRECT._expected_n(label, side)
            expected = 0 if expected_n is None else expected_n * searches
            cells[label][side] = {
                "policy_kind": (
                    "direct_no_search" if expected_n is None else "mc_n30"),
                "searches": searches,
                "accepted_worlds": accepted,
                "expected_accepted_worlds": expected,
                "exact": accepted == expected,
            }
    return {
        "schema": "v11-current-accepted-dose-v2",
        "cells": cells,
        "all": all(cell["exact"] for sides in cells.values()
                   for cell in sides.values()),
    }


def direct_aggregate_problems(payload: dict) -> list[str]:
    """Re-derive the frozen direct protocol without using superiority as a bar."""
    problems = []
    current_protocol_problems = DIRECT.protocol_problems()
    if current_protocol_problems:
        problems.extend(
            f"direct protocol: {problem}"
            for problem in current_protocol_problems)
    if payload.get("schema") != DIRECT.AGGREGATE_SCHEMA:
        problems.append("direct aggregate schema")
    if payload.get("complete") is not True:
        problems.append("direct aggregate is incomplete")
    if (payload.get("clusters") != DIRECT.TOTAL_CLUSTERS
            or payload.get("seed0") != DIRECT.SEED0
            or payload.get("seed_hi") != DIRECT.SEED_HI):
        problems.append("direct aggregate exact 142M coverage")
    if (payload.get("claim") != DIRECT.CLAIM
            or payload.get("labels") != DIRECT.LABELS
            or payload.get("selection_rule") != DIRECT.SELECTION_RULE):
        problems.append("direct aggregate corrected-v2 protocol identity")
    if (payload.get("encoder_contract") != DIRECT.EXPECTED_ENCODER_CONTRACT
            or payload.get("invalidated_v1") != DIRECT.INVALIDATED_V1):
        problems.append("direct aggregate corrected encoder/v1 refusal identity")
    if payload.get("checkpoint_sha256") != CHECKPOINT_SHA256:
        problems.append("direct aggregate checkpoint")
    if payload.get("git_sha") != DIRECT_GIT_SHA:
        problems.append("direct aggregate frozen git identity")
    runtime = payload.get("runtime_identity", {})
    digests = runtime.get("digests", {}) if isinstance(runtime, dict) else {}
    if (not isinstance(runtime, dict)
            or runtime.get("fast_engine") is not True
            or runtime.get("require_voids") is not True
            or runtime.get("experimental_sampler_flags") != []
            or runtime.get("encoder_contract") !=
            DIRECT.EXPECTED_ENCODER_CONTRACT
            or not isinstance(runtime.get("host"), str)
            or not runtime.get("host")
            or not isinstance(runtime.get("python"), str)
            or not runtime.get("python")
            or not isinstance(digests, dict)
            or set(digests) != set(DIRECT_SOURCE_SHA256) | {"fast_binary"}
            or any(digests.get(name) != expected
                   for name, expected in DIRECT_SOURCE_SHA256.items())
            or not _is_sha256(digests.get("fast_binary"))):
        problems.append("direct aggregate runtime/source identity")
    shards = payload.get("input_shards", [])
    if not isinstance(shards, list):
        shards = []
    indices = [item.get("shard_index") for item in shards
               if isinstance(item, dict)]
    manifest_paths = [item.get("manifest_path") for item in shards
                      if isinstance(item, dict)]
    records_paths = [item.get("records_path") for item in shards
                     if isinstance(item, dict)]
    manifest_hashes = [item.get("manifest_sha256") for item in shards
                       if isinstance(item, dict)]
    records_hashes = [item.get("records_sha256") for item in shards
                      if isinstance(item, dict)]
    if (len(shards) != DIRECT.SHARD_COUNT
            or len(indices) != DIRECT.SHARD_COUNT
            or sorted(indices) != list(range(DIRECT.SHARD_COUNT))
            or len(set(manifest_paths)) != DIRECT.SHARD_COUNT
            or len(set(records_paths)) != DIRECT.SHARD_COUNT
            or len(set(manifest_hashes)) != DIRECT.SHARD_COUNT
            or len(set(records_hashes)) != DIRECT.SHARD_COUNT
            or any(not _is_sha256(item.get("manifest_sha256"))
                   or not _is_sha256(item.get("records_sha256"))
                   or not isinstance(item.get("manifest_path"), str)
                   or not isinstance(item.get("records_path"), str)
                   for item in shards if isinstance(item, dict))):
        problems.append("direct aggregate shard population")
    expected_records = {
        label: 2 * DIRECT.TOTAL_CLUSTERS for label in DIRECT.LABELS
    }
    if payload.get("record_counts") != expected_records:
        problems.append("direct aggregate record counts")

    stats = payload.get("stats", {})
    expected_stats = {
        "arm-reference": ("arm", "reference"),
        "arm-null": ("arm", "null"),
        "null-reference": ("null", "reference"),
    }
    if set(stats) != set(expected_stats):
        problems.append("direct aggregate contrast population")
    else:
        for key, (a, b) in expected_stats.items():
            value = stats[key]
            numbers = (value.get("mean"), value.get("half_width_95")) \
                if isinstance(value, dict) else (None, None)
            if (not isinstance(value, dict) or value.get("a") != a
                    or value.get("b") != b
                    or value.get("clusters") != DIRECT.TOTAL_CLUSTERS
                    or any(not isinstance(number, (int, float))
                           or not math.isfinite(number) for number in numbers)
                    or numbers[1] < 0):
                problems.append(f"direct aggregate contrast {key}")
    counters = payload.get("counter_totals", {})
    accepted_dose = payload.get("accepted_dose")
    recomputed_dose = _direct_accepted_dose_from_totals(counters)
    if accepted_dose != recomputed_dose:
        problems.append("direct aggregate stored/recomputed accepted dose")
    try:
        derived = DIRECT.gate_criteria(stats, recomputed_dose or {})
    except (KeyError, TypeError, ValueError) as exc:
        problems.append(f"direct aggregate criteria malformed: {exc}")
        derived = None
    criteria = payload.get("criteria")
    if criteria != derived:
        problems.append("direct aggregate stored/derived criteria")
    if not isinstance(
            payload.get("checkpoint_compatible_with_restored_v1"), bool) \
            or (derived is not None and
                payload.get("checkpoint_compatible_with_restored_v1")
                is not derived["all"]):
        problems.append("direct aggregate corrected-v2 authorization verdict")
    if not isinstance(criteria, dict) or \
            criteria.get("null_current_interval_contains_0") is not True:
        problems.append("direct aggregate matched-null interval excludes zero")
    if (not isinstance(accepted_dose, dict)
            or accepted_dose.get("schema") !=
            "v11-current-accepted-dose-v2"
            or accepted_dose.get("all") is not True
            or not isinstance(criteria, dict)
            or criteria.get("exact_accepted_dose") is not True):
        problems.append("direct aggregate exact accepted-dose gate")
    if (payload.get("protected_composition_authorized") is not False
            or payload.get("production_promotion") is not False):
        problems.append("direct aggregate claims composition/production authority")

    if not isinstance(counters, dict) or set(counters) != set(DIRECT.LABELS):
        problems.append("direct aggregate counter labels")
    else:
        for label, sides in counters.items():
            if not isinstance(sides, dict) or set(sides) != {"arm", "opp"}:
                problems.append(f"direct aggregate {label} counter sides")
                continue
            for side, values in sides.items():
                problems.extend(
                    f"direct aggregate {problem}"
                    for problem in DIRECT._counter_problems(label, side, values)
                )
    return sorted(set(problems))


def load_direct_parent(path: os.PathLike | str,
                       expected_sha256: str) -> dict:
    path = Path(path).resolve()
    if not _is_sha256(DIRECT_AGGREGATE_SHA256):
        raise ProtocolRefused(
            "corrected-v2 direct aggregate SHA-256 is not frozen yet")
    if expected_sha256 != DIRECT_AGGREGATE_SHA256:
        raise ProtocolRefused(
            "direct V11 aggregate is not the registered sealed cde0fec result")
    if (not _is_sha256(expected_sha256) or not path.is_file()
            or sha256(path) != expected_sha256):
        raise ProtocolRefused("direct V11 aggregate digest mismatch")
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ProtocolRefused(f"direct V11 aggregate unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProtocolRefused("direct V11 aggregate must be a JSON object")
    problems = direct_aggregate_problems(payload)
    if problems:
        raise ProtocolRefused(
            "direct V11 aggregate protocol: " + "; ".join(problems))
    return {
        "path": str(path),
        "sha256": expected_sha256,
        "schema": payload["schema"],
        "claim": payload["claim"],
        "git_sha": payload["git_sha"],
        "runtime_identity": payload["runtime_identity"],
        "encoder_contract": payload["encoder_contract"],
        "invalidated_v1": payload["invalidated_v1"],
        "clusters": payload["clusters"],
        "seed0": payload["seed0"],
        "seed_hi": payload["seed_hi"],
        "checkpoint_sha256": payload["checkpoint_sha256"],
        # Preserve both fields exactly.  Only the null-sanity member is an
        # admission condition; the original standalone superiority verdict is
        # carried for audit and deliberately ignored by this composition.
        "criteria": payload["criteria"],
        "checkpoint_compatible_with_restored_v1":
            payload["checkpoint_compatible_with_restored_v1"],
        "protected_composition_authorized":
            payload["protected_composition_authorized"],
        "accepted_dose_sha256": stable_digest(payload["accepted_dose"]),
        "stats_sha256": stable_digest(payload["stats"]),
        "standalone_superiority_required": False,
        "matched_null_sanity_required": True,
        "exact_accepted_dose_required": True,
    }


def load_screen_parent(path: os.PathLike | str, expected_sha256: str,
                       s0_parent: dict) -> dict:
    path = Path(path).resolve()
    if (not _is_sha256(expected_sha256) or not path.is_file()
            or sha256(path) != expected_sha256):
        raise ProtocolRefused("screen aggregate digest mismatch")
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ProtocolRefused(f"screen aggregate unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProtocolRefused("screen aggregate must be a JSON object")
    expected = PROTOCOLS["screen"]
    if (payload.get("schema") != AGGREGATE_SCHEMA
            or payload.get("phase") != "screen"
            or payload.get("complete") is not True
            or payload.get("confirmation_authorized") is not True
            or payload.get("production_promotion") is not False
            or payload.get("seed0") != expected["seed0"]
            or payload.get("seed_hi") !=
            expected["seed0"] + expected["clusters"] - 1
            or payload.get("clusters") != expected["clusters"]):
        raise ProtocolRefused(
            "screen parent is not the complete authorizing frozen screen")
    if payload.get("s0_parent") != s0_parent:
        raise ProtocolRefused("screen and confirmation S0 parents differ")
    if payload.get("champion_policy") != s0_parent["champion_policy"]:
        raise ProtocolRefused("screen aggregate names a different champion")
    labels = labels_for(s0_parent["champion_policy"])
    if payload.get("labels") != labels:
        raise ProtocolRefused("screen aggregate policy labels drifted")
    if payload.get("selection_rule") != SELECTION_RULE:
        raise ProtocolRefused("screen aggregate selection rule drifted")
    if payload.get("checkpoint_sha256") != CHECKPOINT_SHA256:
        raise ProtocolRefused("screen aggregate checkpoint drifted")
    expected_contracts = {
        name: policy_contract(name) for name in labels.values()
    }
    if payload.get("policy_contracts") != expected_contracts:
        raise ProtocolRefused("screen aggregate policy contracts drifted")
    if payload.get("ballots") != arm_ballots(labels.values()):
        raise ProtocolRefused("screen aggregate ballot contracts drifted")
    inputs = payload.get("input_shards", [])
    indices = [item.get("shard_index") for item in inputs
               if isinstance(item, dict)]
    if (len(inputs) != SHARD_COUNT or sorted(indices) != list(range(SHARD_COUNT))
            or any(not _is_sha256(item.get("manifest_sha256"))
                   or not _is_sha256(item.get("records_sha256"))
                   for item in inputs if isinstance(item, dict))):
        raise ProtocolRefused("screen aggregate input-shard identity")
    try:
        derived_criteria = gate_criteria(payload["stats"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProtocolRefused(f"screen aggregate criteria malformed: {exc}") from exc
    if payload.get("criteria") != derived_criteria or not derived_criteria["all"]:
        raise ProtocolRefused("screen authorization is not supported by its stats")
    direct_parent = payload.get("direct_v11_parent")
    if (not isinstance(direct_parent, dict)
            or direct_parent.get("schema") != DIRECT.AGGREGATE_SCHEMA
            or direct_parent.get("clusters") != DIRECT.TOTAL_CLUSTERS
            or direct_parent.get("seed0") != DIRECT.SEED0
            or direct_parent.get("seed_hi") != DIRECT.SEED_HI
            or direct_parent.get("checkpoint_sha256") != CHECKPOINT_SHA256
            or not _is_sha256(direct_parent.get("sha256"))
            or not _is_sha256(direct_parent.get("stats_sha256"))
            or not isinstance(direct_parent.get("git_sha"), str)
            or len(direct_parent.get("git_sha", "")) != 40
            or not isinstance(direct_parent.get("runtime_identity"), dict)
            or direct_parent.get("standalone_superiority_required") is not False
            or direct_parent.get("matched_null_sanity_required") is not True
            or direct_parent.get("exact_accepted_dose_required") is not True
            or direct_parent.get("encoder_contract") !=
            DIRECT.EXPECTED_ENCODER_CONTRACT
            or direct_parent.get("invalidated_v1") != DIRECT.INVALIDATED_V1
            or direct_parent.get("protected_composition_authorized") is not False
            or not _is_sha256(direct_parent.get("accepted_dose_sha256"))
            or not isinstance(direct_parent.get(
                "checkpoint_compatible_with_restored_v1"), bool)
            or not isinstance(direct_parent.get("criteria"), dict)
            or direct_parent["criteria"].get(
                "null_current_interval_contains_0") is not True
            or direct_parent["criteria"].get("exact_accepted_dose") is not True
            or direct_parent.get("checkpoint_compatible_with_restored_v1") is not
            direct_parent["criteria"].get("all")):
        raise ProtocolRefused("screen aggregate direct-parent identity/sanity")
    if payload.get("direct_v11_usage") != DIRECT_USAGE:
        raise ProtocolRefused("screen aggregate changed direct-result usage")
    try:
        reloaded_direct_parent = load_direct_parent(
            direct_parent["path"], direct_parent["sha256"])
    except (KeyError, ProtocolRefused) as exc:
        raise ProtocolRefused(
            f"screen aggregate direct parent cannot be reopened: {exc}") \
            from exc
    if reloaded_direct_parent != direct_parent:
        raise ProtocolRefused(
            "screen aggregate direct-parent summary differs from source bytes")
    evidence_problems = revalidate_screen_evidence(
        path, payload, s0_parent, direct_parent)
    if evidence_problems:
        raise ProtocolRefused(
            "screen parent evidence: " + "; ".join(evidence_problems))
    return {
        "path": str(path), "sha256": expected_sha256,
        "schema": payload["schema"], "git_sha": payload.get("git_sha"),
        "runtime_identity": payload.get("runtime_identity"),
        "champion_policy": payload.get("champion_policy"),
        "direct_v11_parent": direct_parent,
        "direct_v11_usage": DIRECT_USAGE,
        "confirmation_authorized": True,
    }


def _resolve_evidence_path(aggregate_path: Path, raw_path) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise ProtocolRefused("screen input has an invalid evidence path")
    path = Path(raw_path)
    if path.is_absolute():
        raise ProtocolRefused("screen input evidence paths must be relative")
    return (aggregate_path.parent / path).resolve()


def load_bound_screen_inputs(aggregate_path: os.PathLike | str,
                             inputs: list) -> tuple[list, dict[str, list]]:
    """Reopen the exact raw screen evidence named by its aggregate.

    The caller-provided aggregate digest identifies the decision artifact, but
    is not treated as a verifier receipt.  Every manifest and JSONL is opened,
    rehashed and reparsed here before confirmation can start.
    """
    aggregate_path = Path(aggregate_path).resolve()
    manifests = []
    records: dict[str, list] = {}
    seen_manifests = set()
    seen_records = set()
    required = {
        "manifest_path", "manifest_sha256", "records_path",
        "records_sha256", "shard_index",
    }
    if not isinstance(inputs, list) or len(inputs) != SHARD_COUNT:
        raise ProtocolRefused("screen aggregate input-shard population")
    for item in inputs:
        if not isinstance(item, dict) or set(item) != required:
            raise ProtocolRefused("screen aggregate input-shard schema")
        manifest_path = _resolve_evidence_path(
            aggregate_path, item["manifest_path"])
        records_path = _resolve_evidence_path(
            aggregate_path, item["records_path"])
        if manifest_path in seen_manifests or records_path in seen_records:
            raise ProtocolRefused("screen aggregate repeats an input path")
        seen_manifests.add(manifest_path)
        seen_records.add(records_path)
        if (not _is_sha256(item["manifest_sha256"])
                or not manifest_path.is_file()
                or sha256(manifest_path) != item["manifest_sha256"]):
            raise ProtocolRefused(
                f"screen shard manifest digest mismatch: {manifest_path}")
        if (not _is_sha256(item["records_sha256"])
                or not records_path.is_file()
                or sha256(records_path) != item["records_sha256"]):
            raise ProtocolRefused(
                f"screen shard records digest mismatch: {records_path}")
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ProtocolRefused(
                f"screen shard manifest unreadable: {manifest_path}: {exc}") \
                from exc
        if not isinstance(manifest, dict):
            raise ProtocolRefused(
                f"screen shard manifest is not an object: {manifest_path}")
        if (manifest.get("records_sha256") != item["records_sha256"]
                or manifest.get("shard_index") != item["shard_index"]):
            raise ProtocolRefused(
                f"screen input entry/manifest identity drift: {manifest_path}")
        manifests.append((manifest_path, manifest))
        try:
            with records_path.open() as fh:
                for line_number, line in enumerate(fh, 1):
                    if not line.strip():
                        raise ProtocolRefused(
                            f"blank screen record at {records_path}:"
                            f"{line_number}")
                    row = json.loads(line)
                    if not isinstance(row, dict) or not isinstance(
                            row.get("label"), str):
                        raise ProtocolRefused(
                            f"malformed screen record at {records_path}:"
                            f"{line_number}")
                    row["_source"] = str(records_path)
                    records.setdefault(row["label"], []).append(row)
        except (OSError, json.JSONDecodeError) as exc:
            raise ProtocolRefused(
                f"screen shard records unreadable: {records_path}: {exc}") \
                from exc
    return manifests, records


def revalidate_screen_evidence(aggregate_path: os.PathLike | str,
                               payload: dict, s0_parent: dict,
                               direct_parent: dict) -> list[str]:
    """Independently reproduce the screen aggregate from its raw inputs."""
    try:
        manifests, records = load_bound_screen_inputs(
            aggregate_path, payload.get("input_shards"))
    except ProtocolRefused as exc:
        return [str(exc)]
    runtime = payload.get("runtime_identity")
    head = payload.get("git_sha")
    if (not isinstance(runtime, dict) or not isinstance(head, str)
            or len(head) != 40):
        return ["screen aggregate executable identity"]
    problems = validate_population(
        "screen", manifests, records, runtime, head,
        s0_parent, direct_parent, None,
    )
    if problems:
        return problems
    recomputed_stats = all_contrasts(records)
    recomputed_criteria = gate_criteria(recomputed_stats)
    if payload.get("record_counts") != {
            label: len(rows) for label, rows in records.items()}:
        problems.append("screen aggregate/raw record counts differ")
    if payload.get("counter_totals") != counter_totals(records):
        problems.append("screen aggregate/raw counter totals differ")
    if payload.get("stats") != recomputed_stats:
        problems.append("screen aggregate/raw paired statistics differ")
    if payload.get("criteria") != recomputed_criteria:
        problems.append("screen aggregate/raw criteria differ")
    if payload.get("confirmation_authorized") is not recomputed_criteria["all"]:
        problems.append("screen aggregate/raw authorization differs")
    return sorted(set(problems))


def require_screen_execution_identity(screen_parent: dict | None,
                                      current_head: str,
                                      current_runtime: dict) -> None:
    if screen_parent is None:
        return
    if screen_parent.get("git_sha") != current_head:
        raise ProtocolRefused(
            "confirmation executable git SHA differs from frozen screen")
    parent_runtime = screen_parent.get("runtime_identity")
    if (not isinstance(parent_runtime, dict)
            or _runtime_without_host(parent_runtime) !=
            _runtime_without_host(current_runtime)):
        raise ProtocolRefused(
            "confirmation executable runtime/source differs from frozen screen")


def record_problems(records: dict[str, list]) -> list[str]:
    problems = []
    expected = None
    forbidden = (
        "failed_worlds", "rejected_worlds", "short_searches", "zero_world",
        "void_fallbacks", "exact_endgames", "exact_endgame_attempts",
        "exact_endgame_refusals", "exact_endgame_budget_exceeded",
        "exact_endgame_sessions", "exact_endgame_nodes",
        "exact_endgame_cache_hits",
    )
    for label, rows in records.items():
        keys = [(row.get("seed"), row.get("flip")) for row in rows]
        if len(keys) != len(set(keys)):
            problems.append(f"{label}: duplicate seed/flip record")
        if expected is None:
            expected = set(keys)
        elif set(keys) != expected:
            problems.append(f"{label}: seed/flip coverage differs")
        for row in rows:
            for side in ("arm", "opp"):
                counters = row.get(side, {})
                attempts = int(counters.get("sample_attempts", 0))
                accepted = int(counters.get("accepted_worlds", 0))
                failed = int(counters.get("failed_worlds", 0))
                if attempts != accepted + failed:
                    problems.append(
                        f"{label}/{side}: sampler counters do not reconcile")
                for field in forbidden:
                    if int(counters.get(field, 0)):
                        problems.append(f"{label}/{side}: nonzero {field}")
    return sorted(set(problems))


def contrast(records: dict[str, list], a: str, b: str) -> dict:
    mean, half, clusters = paired_by_seed(records[a], records[b])
    return {"a": a, "b": b, "mean": mean,
            "half_width_95": half, "clusters": clusters}


def all_contrasts(records: dict[str, list]) -> dict:
    return {
        "anchor-champion": contrast(records, "anchor", "champion"),
        "anchor-random": contrast(records, "anchor", "random"),
        "anchor-null": contrast(records, "anchor", "null"),
        "null-champion": contrast(records, "null", "champion"),
    }


def gate_criteria(stats: dict) -> dict[str, bool]:
    criteria = {
        "anchor_champion_lcb_gt_0": (
            stats["anchor-champion"]["mean"] -
            stats["anchor-champion"]["half_width_95"] > 0),
        "anchor_random_lcb_gt_0": (
            stats["anchor-random"]["mean"] -
            stats["anchor-random"]["half_width_95"] > 0),
        "anchor_null_lcb_gt_0": (
            stats["anchor-null"]["mean"] -
            stats["anchor-null"]["half_width_95"] > 0),
        "null_champion_interval_contains_0": (
            abs(stats["null-champion"]["mean"]) <=
            stats["null-champion"]["half_width_95"]),
    }
    criteria["all"] = all(criteria.values())
    return criteria


def counter_totals(records: dict[str, list]) -> dict:
    fields = (
        "rollouts", "searches", "sample_attempts", "accepted_worlds",
        "failed_worlds", "rejected_worlds", "short_searches", "zero_world",
        "void_fallbacks", "exact_endgames", "exact_endgame_attempts",
        "exact_endgame_refusals", "exact_endgame_budget_exceeded",
        "exact_endgame_sessions", "exact_endgame_nodes",
        "exact_endgame_cache_hits",
    )
    return {
        label: {
            side: {field: sum(int(row[side].get(field, 0)) for row in rows)
                   for field in fields}
            for side in ("arm", "opp")
        }
        for label, rows in records.items()
    }


def _parent_args(args) -> tuple[dict, dict, dict | None]:
    s0_parent = load_s0_parent(
        args.s0_packet, args.expected_s0_packet_sha256,
        args.s0_closeout, args.expected_s0_closeout_sha256,
    )
    screen_parent = None
    direct_parent = None
    if args.phase == "confirm":
        if not args.screen_parent or not args.expected_screen_parent_sha256:
            raise ProtocolRefused(
                "confirmation requires the exact authorizing screen parent")
        screen_parent = load_screen_parent(
            args.screen_parent, args.expected_screen_parent_sha256, s0_parent)
        if args.direct_aggregate or args.expected_direct_aggregate_sha256:
            raise ProtocolRefused(
                "confirmation inherits direct provenance only through screen")
        direct_parent = screen_parent["direct_v11_parent"]
    elif args.screen_parent or args.expected_screen_parent_sha256:
        raise ProtocolRefused("screen may not accept a screen-result parent")
    else:
        if not args.direct_aggregate or not args.expected_direct_aggregate_sha256:
            raise ProtocolRefused(
                "screen requires the exact frozen direct-V11 aggregate")
        direct_parent = load_direct_parent(
            args.direct_aggregate, args.expected_direct_aggregate_sha256)
    return s0_parent, direct_parent, screen_parent


def run_shard(args) -> None:
    _, runtime = require_runtime()
    spec = PROTOCOLS[args.phase]
    if not 0 <= args.shard_index < SHARD_COUNT:
        raise ProtocolRefused(f"shard-index must satisfy 0 <= i < {SHARD_COUNT}")
    s0_parent, direct_parent, screen_parent = _parent_args(args)
    champion = s0_parent["champion_policy"]
    problems = protocol_problems(champion)
    if problems:
        raise ProtocolRefused(
            "composition protocol drift:\n  - " + "\n  - ".join(problems))
    head = git("rev-parse", "HEAD")
    dirty = git("status", "--porcelain")
    if dirty and not args.smoke:
        raise ProtocolRefused("full composition shard refuses a dirty tree")
    require_screen_execution_identity(screen_parent, head, runtime)

    clusters = 2 if args.smoke else spec["clusters_per_shard"]
    seed0 = spec["seed0"] + args.shard_index * spec["clusters_per_shard"]
    run_id = (f"{SCHEMA}_{args.phase}_shard{args.shard_index:02d}_"
              f"{head[:10]}" + ("_SMOKE" if args.smoke else ""))
    out = Path(args.out or f"runs/logs/{run_id}.jsonl")
    manifest_path = Path(str(out) + ".manifest.json")
    for path in (out, Path(str(out) + ".partial"), manifest_path,
                 Path(str(manifest_path) + ".partial")):
        if path.exists():
            raise ProtocolRefused(f"refusing to overwrite {path}")
    out.parent.mkdir(parents=True, exist_ok=True)

    labels = labels_for(champion)
    contracts = {name: policy_contract(name) for name in labels.values()}
    manifest = {
        "schema": SCHEMA,
        "phase": args.phase,
        "claim": spec["claim"],
        "run_id": run_id,
        "evidence_grade": not args.smoke,
        "screen_only": args.phase == "screen",
        "production_promotion": False,
        "git_sha": head,
        "tree_dirty": bool(dirty),
        "dirty_files": dirty.splitlines() if dirty else [],
        **runtime,
        "shard_index": args.shard_index,
        "shard_count": SHARD_COUNT,
        "total_clusters": spec["clusters"],
        "clusters": clusters,
        "seed0": seed0,
        "seed_hi": seed0 + clusters - 1,
        "opponent": champion,
        "champion_policy": champion,
        "labels": labels,
        "selection_rule": SELECTION_RULE,
        "s0_parent": s0_parent,
        "screen_parent": screen_parent,
        "direct_v11_parent": direct_parent,
        "direct_v11_usage": DIRECT_USAGE,
        "checkpoint": str(CHECKPOINT.relative_to(SERVER)),
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "policy_contracts": contracts,
        "ballots": arm_ballots(labels.values()),
        "started": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
    }
    manifest_partial = Path(str(manifest_path) + ".partial")
    records_partial = Path(str(out) + ".partial")
    with manifest_partial.open("x") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)

    records = {}
    with records_partial.open("x") as fh:
        for label, policy in labels.items():
            print(f"\n{label}: {policy} vs {champion}", flush=True)
            records[label] = run_arm(
                label, policy, champion, clusters, seed0, fh, run_id,
                progress_scores=False)

    problems = record_problems(records)
    manifest["records_sha256"] = sha256(records_partial)
    manifest["record_counts"] = {
        label: len(rows) for label, rows in records.items()
    }
    manifest["counter_totals"] = counter_totals(records)
    manifest["completed"] = time.strftime("%Y-%m-%d %H:%M:%S %Z")
    manifest["problems"] = problems
    manifest["complete"] = not problems
    with manifest_partial.open("w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)

    suffix = "" if not problems else ".FAILED"
    publish_partial_exclusive(
        records_partial, Path(str(out) + suffix))
    publish_partial_exclusive(
        manifest_partial, Path(str(manifest_path) + suffix))
    if problems:
        raise ProtocolRefused(
            "composition shard failed closed:\n  - " + "\n  - ".join(problems))
    print(f"\nrecords: {out}\nmanifest: {manifest_path}")


def _load(pattern: str, phase: str):
    manifests = []
    records: dict[str, list] = {}
    for raw_path in sorted(glob.glob(pattern)):
        path = Path(raw_path)
        try:
            manifest = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if (manifest.get("schema") != SCHEMA
                or manifest.get("phase") != phase
                or manifest.get("evidence_grade") is not True):
            continue
        record_path = Path(str(path).removesuffix(".manifest.json"))
        if not record_path.is_file():
            raise ProtocolRefused(f"manifest has no records: {path}")
        if manifest.get("records_sha256") != sha256(record_path):
            raise ProtocolRefused(f"manifest/record digest drift: {path}")
        manifests.append((path, manifest))
        for line in record_path.read_text().splitlines():
            row = json.loads(line)
            row["_source"] = str(record_path)
            records.setdefault(row["label"], []).append(row)
    return manifests, records


def _runtime_without_host(runtime: dict) -> dict:
    return {key: value for key, value in runtime.items() if key != "host"}


def validate_population(phase: str, manifests, records,
                        current_runtime: dict, current_head: str,
                        s0_parent: dict, direct_parent: dict,
                        screen_parent: dict | None) -> list[str]:
    spec = PROTOCOLS[phase]
    champion = s0_parent["champion_policy"]
    labels = labels_for(champion)
    problems = []
    if len(manifests) != SHARD_COUNT:
        problems.append(f"found {len(manifests)} shards, expected {SHARD_COUNT}")
    indices = [manifest.get("shard_index") for _, manifest in manifests]
    if sorted(i for i in indices if isinstance(i, int)) != list(range(SHARD_COUNT)):
        problems.append(f"shard indices are {indices}")
    stable_fields = (
        "git_sha", "host", "python", "fast_engine", "require_voids",
        "experimental_sampler_flags", "digests", "labels", "ballots",
        "policy_contracts", "checkpoint_sha256", "selection_rule", "claim",
        "shard_count", "total_clusters", "champion_policy", "opponent",
        "s0_parent", "screen_parent", "direct_v11_parent",
        "direct_v11_usage", "production_promotion",
    )
    for key in stable_fields:
        values = {json.dumps(manifest.get(key), sort_keys=True)
                  for _, manifest in manifests}
        if len(values) > 1:
            problems.append(f"shards disagree on {key}")
    for path, manifest in manifests:
        if not manifest.get("complete") or manifest.get("problems"):
            problems.append(f"incomplete/failed manifest {path}")
        if manifest.get("tree_dirty") or not manifest.get("evidence_grade"):
            problems.append(f"dirty/non-evidence manifest {path}")
        if manifest.get("production_promotion") is not False:
            problems.append(f"manifest claims production promotion {path}")
        if manifest.get("screen_only") is not (phase == "screen"):
            problems.append(f"manifest screen/confirmation identity {path}")
        if manifest.get("git_sha") != current_head:
            problems.append(f"{path}: git SHA differs from verifier")
        observed_runtime = {key: manifest.get(key) for key in current_runtime}
        if _runtime_without_host(observed_runtime) != \
                _runtime_without_host(current_runtime):
            problems.append(f"{path}: executable runtime differs from verifier")
        if manifest.get("s0_parent") != s0_parent:
            problems.append(f"{path}: terminal S0 parent drift")
        if manifest.get("screen_parent") != screen_parent:
            problems.append(f"{path}: screen parent drift")
        if manifest.get("direct_v11_parent") != direct_parent:
            problems.append(f"{path}: direct V11 protocol parent drift")
        if manifest.get("direct_v11_usage") != DIRECT_USAGE:
            problems.append(f"{path}: direct V11 superiority entered composition")
        index = manifest.get("shard_index")
        if isinstance(index, int):
            want = spec["seed0"] + index * spec["clusters_per_shard"]
            if (manifest.get("seed0") != want
                    or manifest.get("seed_hi") !=
                    want + spec["clusters_per_shard"] - 1):
                problems.append(f"shard {index}: seed block drift")
        if manifest.get("clusters") != spec["clusters_per_shard"]:
            problems.append(f"{path}: cluster count drift")
        source = str(path).removesuffix(".manifest.json")
        source_rows = [row for rows in records.values() for row in rows
                       if row.get("_source") == source]
        by_label = {
            label: [row for row in rows if row.get("_source") == source]
            for label, rows in records.items()
        }
        if manifest.get("record_counts") != {
                label: len(rows) for label, rows in by_label.items()}:
            problems.append(f"{path}: record counts differ from records")
        if manifest.get("counter_totals") != counter_totals(by_label):
            problems.append(f"{path}: counter totals differ from records")
        if not source_rows:
            problems.append(f"{path}: no bound records")
        local_index = manifest.get("shard_index")
        if isinstance(local_index, int) and 0 <= local_index < SHARD_COUNT:
            expected_local_keys = {
                (seed, flip)
                for seed in range(
                    spec["seed0"] + local_index * spec["clusters_per_shard"],
                    spec["seed0"] + (local_index + 1) *
                    spec["clusters_per_shard"],
                )
                for flip in (0, 1)
            }
            for label, rows in by_label.items():
                keys = {(row.get("seed"), row.get("flip")) for row in rows}
                if (keys != expected_local_keys
                        or len(rows) != len(expected_local_keys)):
                    problems.append(f"{path}: {label} local shard coverage")

    if set(records) != set(labels):
        problems.append(f"record labels {sorted(records)} != {sorted(labels)}")
    expected_keys = {(seed, flip)
                     for seed in range(spec["seed0"],
                                       spec["seed0"] + spec["clusters"])
                     for flip in (0, 1)}
    run_by_source = {
        str(path).removesuffix(".manifest.json"): manifest.get("run_id")
        for path, manifest in manifests
    }
    for label, rows in records.items():
        keys = [(row.get("seed"), row.get("flip")) for row in rows]
        if len(rows) != 2 * spec["clusters"]:
            problems.append(f"{label}: {len(rows)} records")
        if len(keys) != len(set(keys)):
            problems.append(f"{label}: duplicate seed/flip records")
        if set(keys) != expected_keys:
            problems.append(f"{label}: exact seed/flip coverage differs")
        if any(row.get("policy") != labels[label] for row in rows):
            problems.append(f"{label}: policy identity drift")
        if any(row.get("run") != run_by_source.get(row.get("_source"))
               for row in rows):
            problems.append(f"{label}: record/run identity drift")
    problems += record_problems(records)
    problems += protocol_problems(champion)
    return sorted(set(problems))


def aggregate(args) -> None:
    _, runtime = require_runtime()
    dirty = git("status", "--porcelain")
    if dirty:
        raise ProtocolRefused("composition aggregate refuses a dirty tree")
    head = git("rev-parse", "HEAD")
    s0_parent, direct_parent, screen_parent = _parent_args(args)
    require_screen_execution_identity(screen_parent, head, runtime)
    manifests, records = _load(args.pattern, args.phase)
    problems = validate_population(
        args.phase, manifests, records, runtime, head,
        s0_parent, direct_parent, screen_parent,
    )
    if problems:
        raise ProtocolRefused(
            "composition aggregation refused:\n  - " +
            "\n  - ".join(problems))

    stats = all_contrasts(records)
    criteria = gate_criteria(stats)
    spec = PROTOCOLS[args.phase]
    champion = s0_parent["champion_policy"]
    labels = labels_for(champion)
    aggregate_dir = Path(args.out).resolve().parent

    def evidence_path(path: os.PathLike | str) -> str:
        return os.path.relpath(Path(path).resolve(), aggregate_dir)

    result = {
        "schema": AGGREGATE_SCHEMA,
        "phase": args.phase,
        "claim": spec["claim"],
        "complete": True,
        "git_sha": head,
        "runtime_identity": runtime,
        "clusters": spec["clusters"],
        "seed0": spec["seed0"],
        "seed_hi": spec["seed0"] + spec["clusters"] - 1,
        "champion_policy": champion,
        "labels": labels,
        "selection_rule": SELECTION_RULE,
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "policy_contracts": {
            name: policy_contract(name) for name in labels.values()
        },
        "ballots": arm_ballots(labels.values()),
        "s0_parent": s0_parent,
        "screen_parent": screen_parent,
        "direct_v11_parent": direct_parent,
        "direct_v11_usage": DIRECT_USAGE,
        "input_shards": [
            {"manifest_path": evidence_path(path),
             "manifest_sha256": sha256(path),
             "records_path": evidence_path(
                 str(path).removesuffix(".manifest.json")),
             "records_sha256": manifest["records_sha256"],
             "shard_index": manifest["shard_index"]}
            for path, manifest in sorted(
                manifests, key=lambda item: item[1]["shard_index"])
        ],
        "record_counts": {label: len(rows) for label, rows in records.items()},
        "counter_totals": counter_totals(records),
        "stats": stats,
        "criteria": criteria,
        "confirmation_authorized": (
            criteria["all"] if args.phase == "screen" else None),
        "strength_confirmed": (
            criteria["all"] if args.phase == "confirm" else None),
        "production_promotion": False,
        "note": (
            "Non-promotable blind screen; PASS authorizes only the frozen "
            "138M confirmation."
            if args.phase == "screen" else
            "Independent strength confirmation; no automatic production "
            "promotion or deployment is authorized."
        ),
    }
    write_exclusive_atomic(args.out, result)
    print(json.dumps(result, indent=2, sort_keys=True))


def _add_parent_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--s0-packet", required=True)
    parser.add_argument("--expected-s0-packet-sha256", required=True)
    parser.add_argument("--s0-closeout", required=True)
    parser.add_argument("--expected-s0-closeout-sha256", required=True)
    parser.add_argument("--direct-aggregate")
    parser.add_argument("--expected-direct-aggregate-sha256")
    parser.add_argument("--screen-parent")
    parser.add_argument("--expected-screen-parent-sha256")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("phase", choices=tuple(PROTOCOLS))
    run.add_argument("--shard-index", type=int, required=True)
    run.add_argument("--smoke", action="store_true")
    run.add_argument("--out")
    _add_parent_arguments(run)
    agg = sub.add_parser("aggregate")
    agg.add_argument("phase", choices=tuple(PROTOCOLS))
    agg.add_argument("--pattern", required=True)
    agg.add_argument("--out", required=True)
    _add_parent_arguments(agg)
    args = parser.parse_args()
    if args.command == "run":
        run_shard(args)
    else:
        aggregate(args)


if __name__ == "__main__":
    try:
        main()
    except ProtocolRefused as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc

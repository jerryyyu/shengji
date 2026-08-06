"""Blinded complete-round strength gate for sampled exact endgame search.

The treatment changes one thing on the terminal S0 champion: inside each
accepted, fully determinized MC world, heuristic continuation is replaced by
partnership-minimax once every hand has at most four cards.  It is therefore a
sampled perfect-information continuation, not exact imperfect-information
Shengji.

``screen`` is a non-promotable 8x256 paired screen on seeds 139M.  Each flip is
one complete Shengji deal/round and the primary outcome is signed level
utility; this is not a multi-round progression match.  A PASS may
authorize only the frozen ``confirm`` population: 8x1024 disjoint clusters on
seeds 140M.  Confirmation reopens and independently recomputes every raw
screen record before it can start.  Neither phase changes production.
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
import tempfile
import time
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SERVER / "scripts"))

import s0_closeout as S0_CLOSEOUT  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.evaluation import arm_ballots, paired_by_seed, run_arm  # noqa: E402


SCHEMA = "s3b-endgame-strength-shard-v1"
AGGREGATE_SCHEMA = "s3b-endgame-strength-aggregate-v1"
PREFLIGHT_SCHEMA = "s3b-endgame-throughput-preflight-v1"
SHARD_COUNT = 8
PREFLIGHT_CLUSTERS = 2
PREFLIGHT_SEED0 = 141_000_000
THROUGHPUT_SAFETY_FACTOR = 2.0
SCREEN_TO_CONFIRM_SAFETY_FACTOR = 1.25
BUDGET_ROLE = (
    "operator-precommitted operational capacity only; changing this cap does "
    "not change policies, seeds, sample sizes, contrasts or strength bars, "
    "and the score-free preflight exposes no strength effect"
)
MECHANICS_COMMIT = "2370a277fe694d952c3b6fb80e31f319d7dfad36"
MECHANICS_ASSET = SERVER / "tests" / "data" / \
    "s3b_endgame_challenge.v1.json"
MECHANICS_ASSET_SHA256 = (
    "03f54de951528821a0f726fd23515cf6945fac87fdbf12f7847b43699bbbf8e2"
)
SAMPLER_FLAGS = (
    "SHENGJI_WEIGHTED_SPLITS",
    "SHENGJI_UNIFORM_DEAL",
    "SHENGJI_PHYSICAL_FILLS",
    "SHENGJI_ALLOW_BALLOT_MISMATCH",
)
PROTOCOLS = {
    "screen": {
        "seed0": 139_000_000,
        "clusters": 2_048,
        "clusters_per_shard": 256,
        "claim": "non_promotable_complete_round_exact_endgame_screen",
    },
    "confirm": {
        "seed0": 140_000_000,
        "clusters": 8_192,
        "clusters_per_shard": 1_024,
        "claim": "independent_complete_round_exact_endgame_confirmation",
    },
}
CHAMPION_LANES = {
    "mc-strong": {
        "exact": "mc-exact-endgame",
        "null": "mc-strong-null",
    },
    "mc-s0-report-lcb": {
        "exact": "mc-s0-report-lcb-exact-endgame",
        "null": "mc-s0-report-lcb-null",
    },
    "mc-s0-adaptive": {
        "exact": "mc-s0-adaptive-exact-endgame",
        "null": "mc-s0-adaptive-null",
    },
}
SELECTION_RULE = (
    "AUTHORIZE the disjoint 8x1024 confirmation only if, over exactly 2,048 "
    "fresh seed clusters, the paired two-sided 95% lower bounds for sampled-"
    "exact minus terminal champion and sampled-exact minus champion-matched "
    "null are both >0; the champion-matched-null minus champion interval "
    "contains zero; sampled-exact use is >0; and exact refusal and budget-"
    "overflow counters are zero. Apply the identical rule to the 8,192-"
    "cluster confirmation. The unit is one complete deal/round with signed "
    "level utility, not multi-round progression. The screen is non-promotable "
    "and neither phase changes production automatically."
)
COUNTER_FIELDS = (
    "rollouts", "searches", "search_secs", "void_fallbacks",
    "rejected_worlds", "sample_attempts", "accepted_worlds",
    "failed_worlds", "short_searches", "zero_world", "exact_endgames",
    "exact_endgame_attempts", "exact_endgame_refusals",
    "exact_endgame_budget_exceeded", "exact_endgame_sessions",
    "exact_endgame_nodes", "exact_endgame_cache_hits",
)
INTEGER_COUNTER_FIELDS = tuple(
    field for field in COUNTER_FIELDS if field != "search_secs"
)
EXACT_COUNTER_FIELDS = (
    "exact_endgames", "exact_endgame_attempts",
    "exact_endgame_refusals", "exact_endgame_budget_exceeded",
    "exact_endgame_sessions", "exact_endgame_nodes",
    "exact_endgame_cache_hits",
)
FORBIDDEN_WORK_FIELDS = (
    "failed_worlds", "rejected_worlds", "short_searches", "zero_world",
    "void_fallbacks", "exact_endgame_refusals",
    "exact_endgame_budget_exceeded",
)


class ProtocolRefused(RuntimeError):
    """The requested artifact cannot support the registered claim."""


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


def is_sha256(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def publish_partial_exclusive(partial: os.PathLike | str,
                              final: os.PathLike | str) -> None:
    """Atomically publish without replacing a competing evidence artifact."""
    partial = Path(partial)
    final = Path(final)
    if not partial.is_file():
        raise ProtocolRefused(f"completed partial is missing: {partial}")
    try:
        os.link(partial, final)
    except FileExistsError as exc:
        # Keep the completed partial for diagnosis/recovery.  It must never
        # replace bytes another worker published under the registered name.
        raise ProtocolRefused(
            f"refusing to overwrite concurrently published {final}") from exc
    partial.unlink()


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
        if partial.exists() and not path.exists():
            partial.unlink()
        raise


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
            "endgame": sha256(SERVER / "shengji" / "ai" / "endgame.py"),
            "ballot": sha256(SERVER / "shengji" / "engine" / "ballot.py"),
            "s0_closeout": sha256(SERVER / "scripts" / "s0_closeout.py"),
            "mechanics_asset": sha256(MECHANICS_ASSET),
            "fast_router": sha256(fast.__file__),
            "fast_binary": sha256(fast._fast.__file__),
        },
    }


def require_runtime() -> tuple[object, dict]:
    if (os.environ.get("SHENGJI_FAST") != "1"
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1"):
        raise ProtocolRefused(
            "set SHENGJI_FAST=1 and SHENGJI_REQUIRE_VOIDS=1")
    enabled = [name for name in SAMPLER_FLAGS if os.environ.get(name)]
    if enabled:
        raise ProtocolRefused(
            f"experimental sampler/ballot flags must be unset: {enabled}")
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise ProtocolRefused("compiled engine requested but not active")
    return fast, runtime_identity(fast)


def uppercase_contract(bot) -> dict:
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
        "uppercase": uppercase_contract(bot),
        "rollout_policy_class": type(bot.rollout_policy).__name__,
        "exact_endgame_base_policy": getattr(
            bot, "exact_endgame_base_policy", None),
    }


def labels_for(champion: str) -> dict[str, str]:
    try:
        lane = CHAMPION_LANES[champion]
    except KeyError as exc:
        raise ProtocolRefused(
            f"terminal S0 policy {champion!r} has no frozen S3b lane") from exc
    return {
        "exact": lane["exact"],
        "champion": champion,
        "null": lane["null"],
    }


def protocol_problems(champion: str) -> list[str]:
    problems = []
    exact_protocols = {
        "screen": {
            "seed0": 139_000_000, "clusters": 2_048,
            "clusters_per_shard": 256,
            "claim": "non_promotable_complete_round_exact_endgame_screen",
        },
        "confirm": {
            "seed0": 140_000_000, "clusters": 8_192,
            "clusters_per_shard": 1_024,
            "claim": "independent_complete_round_exact_endgame_confirmation",
        },
    }
    exact_lanes = {
        "mc-strong": {
            "exact": "mc-exact-endgame", "null": "mc-strong-null"},
        "mc-s0-report-lcb": {
            "exact": "mc-s0-report-lcb-exact-endgame",
            "null": "mc-s0-report-lcb-null"},
        "mc-s0-adaptive": {
            "exact": "mc-s0-adaptive-exact-endgame",
            "null": "mc-s0-adaptive-null"},
    }
    if SHARD_COUNT != 8 or PROTOCOLS != exact_protocols:
        problems.append("registered phase geometry/seed blocks drifted")
    if CHAMPION_LANES != exact_lanes:
        problems.append("registered champion S3b lanes drifted")
    if (not MECHANICS_ASSET.is_file()
            or sha256(MECHANICS_ASSET) != MECHANICS_ASSET_SHA256):
        problems.append("frozen mechanics challenge asset unavailable/drifted")
    try:
        if subprocess.run(
                ["git", "merge-base", "--is-ancestor",
                 MECHANICS_COMMIT, "HEAD"], cwd=SERVER.parent).returncode:
            problems.append("mechanics challenge commit is not an ancestor")
    except OSError as exc:
        problems.append(f"cannot verify mechanics ancestry: {exc}")

    try:
        labels = labels_for(champion)
        bots = {label: make_bot(name, seed=7)
                for label, name in labels.items()}
        contracts = {label: uppercase_contract(bot)
                     for label, bot in bots.items()}
    except Exception as exc:
        problems.append(f"policy construction failed: {type(exc).__name__}: {exc}")
        return sorted(set(problems))

    base = contracts["champion"]
    treatment = dict(contracts["exact"])
    treatment["EXACT_ENDGAME"] = False
    if treatment != base:
        problems.append("sampled-exact policy differs beyond EXACT_ENDGAME")
    if contracts["exact"].get("EXACT_ENDGAME") is not True:
        problems.append("sampled-exact policy did not enable exact endgames")
    if (contracts["exact"].get("EXACT_ENDGAME_MAX_CARDS") != 4
            or contracts["exact"].get("EXACT_ENDGAME_MAX_NODES") != 250_000):
        problems.append("sampled-exact completeness/work bound drifted")
    if getattr(bots["exact"], "exact_endgame_base_policy", None) != champion:
        problems.append("sampled-exact policy names the wrong champion base")
    if bots["exact"].rng.getstate() != bots["champion"].rng.getstate():
        problems.append("sampled-exact policy changed the champion RNG stream")
    if type(bots["exact"].rollout_policy) is not \
            type(bots["champion"].rollout_policy):
        problems.append("sampled-exact rollout policy differs from champion")
    if contracts["null"] != base:
        problems.append("champion-matched null contract differs from champion")
    if bots["null"].rng.getstate() == bots["champion"].rng.getstate():
        problems.append("champion-matched null does not shift its RNG stream")
    for label in ("champion", "null"):
        if any(getattr(bots[label], field, False) for field in
               ("MC_BURY", "STRUCTURED_BURY", "EXACT_ENDGAME")):
            problems.append(f"{label} enables an out-of-scope S3 feature")
    try:
        ballots = arm_ballots(labels.values())
        if len(set(ballots.values())) != 1:
            problems.append(f"S3b arms use different ballots: {ballots}")
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
    if not is_sha256(packet_sha256) or not is_sha256(closeout_sha256):
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
    return {
        "terminal_state": status,
        "champion_policy": _terminal_decision(packet_text, status),
        "packet_sha256": packet_sha256,
        "closeout_sha256": closeout_sha256,
        "phases": phases,
        "verification_boundary": (
            "exact bytes from independently regenerated terminal S0 closeout"
        ),
    }


def _positive_finite(value, name: str) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value <= 0):
        raise ProtocolRefused(f"{name} must be a positive finite number")
    return float(value)


def throughput_projection(total_seconds: float) -> dict:
    """Conservative whole-population compute from a two-cluster preflight."""
    total_seconds = _positive_finite(total_seconds, "preflight wall seconds")
    seconds_per_cluster = total_seconds / PREFLIGHT_CLUSTERS

    def phase_projection(phase: str) -> dict:
        spec = PROTOCOLS[phase]
        fleet_hours = (seconds_per_cluster * spec["clusters"] *
                       THROUGHPUT_SAFETY_FACTOR / 3_600)
        shard_wall_hours = (seconds_per_cluster *
                            spec["clusters_per_shard"] *
                            THROUGHPUT_SAFETY_FACTOR / 3_600)
        return {
            "fleet_hours": fleet_hours,
            "max_shard_wall_hours": shard_wall_hours,
        }

    return {
        "safety_factor": THROUGHPUT_SAFETY_FACTOR,
        "seconds_per_cluster": seconds_per_cluster,
        "screen": phase_projection("screen"),
        "confirm": phase_projection("confirm"),
    }


def throughput_criteria(projections: dict, budgets: dict) -> dict[str, bool]:
    criteria = {
        "screen_fleet_hours_within_cap": (
            projections["screen"]["fleet_hours"] <=
            budgets["screen_fleet_hours"]),
        "screen_shard_wall_within_cap": (
            projections["screen"]["max_shard_wall_hours"] <=
            budgets["screen_max_shard_wall_hours"]),
        "confirm_fleet_hours_within_cap": (
            projections["confirm"]["fleet_hours"] <=
            budgets["confirm_fleet_hours"]),
        "confirm_shard_wall_within_cap": (
            projections["confirm"]["max_shard_wall_hours"] <=
            budgets["confirm_max_shard_wall_hours"]),
    }
    criteria["all"] = all(criteria.values())
    return criteria


def run_throughput_preflight(args) -> None:
    """Measure the exact registered policies without retaining any scores.

    Budget caps are supplied on the command line before play begins.  The
    receipt persists only elapsed work/counters, never wins, utilities or raw
    records, so this operational gate cannot become a strength screen.
    """
    _, runtime = require_runtime()
    head = git("rev-parse", "HEAD")
    dirty = git("status", "--porcelain")
    if dirty:
        raise ProtocolRefused("throughput preflight refuses a dirty tree")
    s0_parent = load_s0_parent(
        args.s0_packet, args.expected_s0_packet_sha256,
        args.s0_closeout, args.expected_s0_closeout_sha256,
    )
    champion = s0_parent["champion_policy"]
    problems = protocol_problems(champion)
    if problems:
        raise ProtocolRefused(
            "S3b throughput protocol drift:\n  - " + "\n  - ".join(problems))
    budgets = {
        "screen_fleet_hours": _positive_finite(
            args.screen_fleet_hour_cap, "screen fleet-hour cap"),
        "screen_max_shard_wall_hours": _positive_finite(
            args.screen_shard_wall_hour_cap, "screen shard-wall cap"),
        "confirm_fleet_hours": _positive_finite(
            args.confirm_fleet_hour_cap, "confirmation fleet-hour cap"),
        "confirm_max_shard_wall_hours": _positive_finite(
            args.confirm_shard_wall_hour_cap,
            "confirmation shard-wall cap"),
    }
    labels = labels_for(champion)
    records = {}
    elapsed_by_label = {}
    started = time.perf_counter()
    # TemporaryFile is unlinked by the OS and never becomes an evidence asset.
    # run_arm needs a sink because the exact production evaluation path is the
    # thing whose throughput must be measured.
    with tempfile.TemporaryFile(mode="w+") as sink:
        for label, policy in labels.items():
            print(
                f"throughput-only {label}: starting {PREFLIGHT_CLUSTERS} "
                "clusters; strength scores hidden",
                flush=True,
            )
            label_started = time.perf_counter()
            records[label] = []
            for offset in range(PREFLIGHT_CLUSTERS):
                records[label].extend(run_arm(
                    label, policy, champion, 1,
                    PREFLIGHT_SEED0 + offset, sink,
                    "S3B_THROUGHPUT_ONLY",
                    progress=False, progress_scores=False))
                print(
                    f"throughput-only {label}: {offset + 1}/"
                    f"{PREFLIGHT_CLUSTERS} clusters complete; "
                    "strength scores hidden",
                    flush=True,
                )
            elapsed_by_label[label] = time.perf_counter() - label_started
    total_seconds = time.perf_counter() - started
    problems = record_problems(records)
    if problems:
        raise ProtocolRefused(
            "throughput preflight work failed:\n  - " + "\n  - ".join(problems))
    projections = throughput_projection(total_seconds)
    criteria = throughput_criteria(projections, budgets)
    receipt = {
        "schema": PREFLIGHT_SCHEMA,
        "complete": True,
        "evidence_grade": False,
        "strength_scores_persisted": False,
        "raw_records_persisted": False,
        "evaluation_unit": "one_complete_round",
        "primary_outcome": "signed_level_utility",
        "multi_round_progression_tested": False,
        "git_sha": head,
        "runtime_identity": runtime,
        "mechanics_commit": MECHANICS_COMMIT,
        "mechanics_asset_sha256": MECHANICS_ASSET_SHA256,
        "s0_parent": s0_parent,
        "champion_policy": champion,
        "labels": labels,
        "clusters": PREFLIGHT_CLUSTERS,
        "seed0": PREFLIGHT_SEED0,
        "seed_hi": PREFLIGHT_SEED0 + PREFLIGHT_CLUSTERS - 1,
        "wall_seconds": total_seconds,
        "wall_seconds_by_label": elapsed_by_label,
        "counter_totals": counter_totals(records),
        "budgets": budgets,
        "budget_role": BUDGET_ROLE,
        "strength_estimand_locked": True,
        "projections": projections,
        "criteria": criteria,
        "launch_authorized": criteria["all"],
        "note": (
            "Operational throughput only. No wins, utilities or raw outcome "
            "records were retained. Caps were command inputs before timing."
        ),
    }
    write_exclusive_atomic(args.out, receipt)
    # Safe to print: the receipt contains timing/work only, never strength.
    print(json.dumps(receipt, indent=2, sort_keys=True))


def load_throughput_parent(path: os.PathLike | str, expected_sha256: str,
                           s0_parent: dict) -> dict:
    """Recompute the score-free preflight's projections and budget decision."""
    path = Path(path).resolve()
    if (not is_sha256(expected_sha256) or not path.is_file()
            or sha256(path) != expected_sha256):
        raise ProtocolRefused("throughput receipt digest mismatch")
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ProtocolRefused(f"throughput receipt unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProtocolRefused("throughput receipt is not an object")
    champion = s0_parent["champion_policy"]
    labels = labels_for(champion)
    fixed = (
        payload.get("schema") == PREFLIGHT_SCHEMA
        and payload.get("complete") is True
        and payload.get("evidence_grade") is False
        and payload.get("strength_scores_persisted") is False
        and payload.get("raw_records_persisted") is False
        and payload.get("evaluation_unit") == "one_complete_round"
        and payload.get("primary_outcome") == "signed_level_utility"
        and payload.get("multi_round_progression_tested") is False
        and payload.get("budget_role") == BUDGET_ROLE
        and payload.get("strength_estimand_locked") is True
        and payload.get("mechanics_commit") == MECHANICS_COMMIT
        and payload.get("mechanics_asset_sha256") == MECHANICS_ASSET_SHA256
        and payload.get("s0_parent") == s0_parent
        and payload.get("champion_policy") == champion
        and payload.get("labels") == labels
        and payload.get("clusters") == PREFLIGHT_CLUSTERS
        and payload.get("seed0") == PREFLIGHT_SEED0
        and payload.get("seed_hi") ==
        PREFLIGHT_SEED0 + PREFLIGHT_CLUSTERS - 1
    )
    if not fixed:
        raise ProtocolRefused("throughput receipt protocol identity")
    elapsed_by_label = payload.get("wall_seconds_by_label")
    wall_seconds = payload.get("wall_seconds")
    if (isinstance(wall_seconds, bool)
            or not isinstance(wall_seconds, (int, float))
            or not math.isfinite(wall_seconds) or wall_seconds <= 0
            or not isinstance(elapsed_by_label, dict)
            or set(elapsed_by_label) != set(labels)
            or any(isinstance(value, bool)
                   or not isinstance(value, (int, float))
                   or not math.isfinite(value) or value <= 0
                   for value in elapsed_by_label.values())
            or sum(elapsed_by_label.values()) > wall_seconds * 1.001):
        raise ProtocolRefused("throughput receipt wall-time accounting")
    work_problems = aggregate_work_problems(payload.get("counter_totals"))
    if work_problems:
        raise ProtocolRefused(
            "throughput receipt counter contract: " +
            "; ".join(work_problems))
    budgets = payload.get("budgets")
    if not isinstance(budgets, dict) or set(budgets) != {
            "screen_fleet_hours", "screen_max_shard_wall_hours",
            "confirm_fleet_hours", "confirm_max_shard_wall_hours"}:
        raise ProtocolRefused("throughput receipt budget schema")
    for name, value in budgets.items():
        _positive_finite(value, f"throughput budget {name}")
    projections = throughput_projection(wall_seconds)
    criteria = throughput_criteria(projections, budgets)
    if (payload.get("projections") != projections
            or payload.get("criteria") != criteria
            or payload.get("launch_authorized") is not criteria["all"]):
        raise ProtocolRefused("throughput receipt arithmetic/decision drift")
    if not criteria["all"]:
        raise ProtocolRefused(
            "projected S3b screen/confirmation exceeds declared fleet budget")
    runtime = payload.get("runtime_identity")
    head = payload.get("git_sha")
    if (not isinstance(runtime, dict) or not isinstance(head, str)
            or len(head) != 40):
        raise ProtocolRefused("throughput receipt executable identity")
    return {
        "sha256": expected_sha256,
        "schema": PREFLIGHT_SCHEMA,
        "git_sha": head,
        "runtime_identity": runtime,
        "s0_parent": s0_parent,
        "champion_policy": champion,
        "budgets": budgets,
        "budget_role": BUDGET_ROLE,
        "strength_estimand_locked": True,
        "projections": projections,
        "launch_authorized": True,
        "strength_scores_persisted": False,
    }


def require_throughput_execution_identity(throughput_parent: dict,
                                          current_head: str,
                                          current_runtime: dict) -> None:
    if throughput_parent.get("git_sha") != current_head:
        raise ProtocolRefused(
            "launch executable git SHA differs from throughput preflight")
    parent_runtime = throughput_parent.get("runtime_identity")
    if (not isinstance(parent_runtime, dict)
            or parent_runtime != current_runtime):
        raise ProtocolRefused(
            "launch host/runtime/source differs from throughput preflight")


def observed_throughput(phase: str, manifests,
                        throughput_parent: dict) -> dict:
    """Re-derive actual fleet/wall cost and the next launch's projection."""
    wall_seconds = [float(manifest["wall_seconds"])
                    for _, manifest in manifests]
    fleet_hours = sum(wall_seconds) / 3_600
    max_shard_wall_hours = max(wall_seconds) / 3_600
    budgets = throughput_parent["budgets"]
    observed = {
        "fleet_hours": fleet_hours,
        "max_shard_wall_hours": max_shard_wall_hours,
    }
    if phase == "screen":
        cluster_ratio = (PROTOCOLS["confirm"]["clusters"] /
                         PROTOCOLS["screen"]["clusters"])
        shard_ratio = (PROTOCOLS["confirm"]["clusters_per_shard"] /
                       PROTOCOLS["screen"]["clusters_per_shard"])
        projected_next = {
            "safety_factor": SCREEN_TO_CONFIRM_SAFETY_FACTOR,
            "fleet_hours": (fleet_hours * cluster_ratio *
                            SCREEN_TO_CONFIRM_SAFETY_FACTOR),
            "max_shard_wall_hours": (
                max_shard_wall_hours * shard_ratio *
                SCREEN_TO_CONFIRM_SAFETY_FACTOR),
        }
        criteria = {
            "screen_actual_fleet_hours_within_cap": (
                fleet_hours <= budgets["screen_fleet_hours"]),
            "screen_actual_shard_wall_within_cap": (
                max_shard_wall_hours <=
                budgets["screen_max_shard_wall_hours"]),
            "confirmation_projected_fleet_hours_within_cap": (
                projected_next["fleet_hours"] <=
                budgets["confirm_fleet_hours"]),
            "confirmation_projected_shard_wall_within_cap": (
                projected_next["max_shard_wall_hours"] <=
                budgets["confirm_max_shard_wall_hours"]),
        }
    else:
        projected_next = None
        criteria = {
            "confirmation_actual_fleet_hours_within_cap": (
                fleet_hours <= budgets["confirm_fleet_hours"]),
            "confirmation_actual_shard_wall_within_cap": (
                max_shard_wall_hours <=
                budgets["confirm_max_shard_wall_hours"]),
        }
    criteria["all"] = all(criteria.values())
    return {
        "observed": observed,
        "next_phase_projection": projected_next,
        "criteria": criteria,
    }


def _valid_counter_object(counters: object) -> bool:
    if not isinstance(counters, dict) or set(counters) != set(COUNTER_FIELDS):
        return False
    for field in INTEGER_COUNTER_FIELDS:
        value = counters[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return False
    seconds = counters["search_secs"]
    return (not isinstance(seconds, bool)
            and isinstance(seconds, (int, float))
            and math.isfinite(seconds) and seconds >= 0)


def aggregate_work_problems(totals: object) -> list[str]:
    """Validate score-free counter totals such as the preflight receipt."""
    problems = []
    labels = {"exact", "champion", "null"}
    if not isinstance(totals, dict) or set(totals) != labels:
        return ["counter totals label population"]
    for label in labels:
        sides = totals[label]
        if not isinstance(sides, dict) or set(sides) != {"arm", "opp"}:
            problems.append(f"{label}: counter totals side population")
            continue
        for side, counters in sides.items():
            where = f"{label}/{side}"
            if not _valid_counter_object(counters):
                problems.append(f"{where}: malformed counter totals")
                continue
            if counters["sample_attempts"] != (
                    counters["accepted_worlds"] + counters["failed_worlds"]):
                problems.append(f"{where}: sampler totals do not reconcile")
            for field in FORBIDDEN_WORK_FIELDS:
                if counters[field]:
                    problems.append(f"{where}: nonzero {field}")
            if label == "exact" and side == "arm":
                if counters["exact_endgame_sessions"] != \
                        counters["accepted_worlds"]:
                    problems.append(
                        f"{where}: exact sessions != accepted worlds")
                if counters["exact_endgames"] <= 0:
                    problems.append(f"{where}: sampled exact was never used")
                if counters["exact_endgame_attempts"] != \
                        counters["exact_endgames"]:
                    problems.append(f"{where}: exact calls do not reconcile")
            elif any(counters[field] for field in EXACT_COUNTER_FIELDS):
                problems.append(f"{where}: non-treatment exact work")
    return sorted(set(problems))


def record_problems(records: dict[str, list]) -> list[str]:
    """Validate coverage and the exact treatment's sampler/work boundary."""
    problems = []
    expected = None
    for label, rows in records.items():
        keys = [(row.get("seed"), row.get("flip")) for row in rows]
        if len(keys) != len(set(keys)):
            problems.append(f"{label}: duplicate seed/flip record")
        if expected is None:
            expected = set(keys)
        elif set(keys) != expected:
            problems.append(f"{label}: seed/flip coverage differs")
        for row_index, row in enumerate(rows):
            for side in ("arm", "opp"):
                counters = row.get(side)
                where = f"{label}/{side}/row{row_index}"
                if not _valid_counter_object(counters):
                    problems.append(f"{where}: malformed counter contract")
                    continue
                attempts = counters["sample_attempts"]
                accepted = counters["accepted_worlds"]
                failed = counters["failed_worlds"]
                if attempts != accepted + failed:
                    problems.append(f"{where}: sampler counters do not reconcile")
                if counters["rollouts"] < accepted:
                    problems.append(f"{where}: fewer rollouts than accepted worlds")
                for field in FORBIDDEN_WORK_FIELDS:
                    if counters[field]:
                        problems.append(f"{where}: nonzero {field}")

                is_treatment = label == "exact" and side == "arm"
                if is_treatment:
                    if counters["exact_endgame_sessions"] != accepted:
                        problems.append(
                            f"{where}: exact sessions != accepted worlds")
                    if counters["exact_endgame_attempts"] != \
                            counters["exact_endgames"]:
                        problems.append(
                            f"{where}: exact attempts/calls do not reconcile")
                    if counters["exact_endgames"] > counters["rollouts"]:
                        problems.append(f"{where}: more exact calls than rollouts")
                    if (counters["exact_endgames"] > 0
                            and counters["exact_endgame_nodes"] <= 0):
                        problems.append(f"{where}: exact calls used zero nodes")
                else:
                    for field in EXACT_COUNTER_FIELDS:
                        if counters[field]:
                            problems.append(
                                f"{where}: non-treatment has nonzero {field}")
    if records.get("exact"):
        calls = sum(row["arm"].get("exact_endgames", 0)
                    for row in records["exact"]
                    if isinstance(row.get("arm"), dict))
        if calls <= 0:
            problems.append("exact/arm: sampled exact continuation was never used")
    return sorted(set(problems))


def contrast(records: dict[str, list], a: str, b: str) -> dict:
    mean, half, clusters = paired_by_seed(records[a], records[b])
    return {"a": a, "b": b, "mean": mean,
            "half_width_95": half, "clusters": clusters}


def all_contrasts(records: dict[str, list]) -> dict:
    return {
        "exact-champion": contrast(records, "exact", "champion"),
        "exact-null": contrast(records, "exact", "null"),
        "null-champion": contrast(records, "null", "champion"),
    }


def counter_totals(records: dict[str, list]) -> dict:
    out = {}
    for label, rows in records.items():
        out[label] = {}
        for side in ("arm", "opp"):
            values = {}
            for field in COUNTER_FIELDS:
                total = sum(row[side][field] for row in rows)
                values[field] = round(total, 4) if field == "search_secs" \
                    else int(total)
            out[label][side] = values
    return out


def gate_criteria(stats: dict, totals: dict) -> dict[str, bool]:
    exact_work = totals.get("exact", {}).get("arm", {})
    criteria = {
        "exact_champion_lcb_gt_0": (
            stats["exact-champion"]["mean"] -
            stats["exact-champion"]["half_width_95"] > 0),
        "exact_null_lcb_gt_0": (
            stats["exact-null"]["mean"] -
            stats["exact-null"]["half_width_95"] > 0),
        "null_champion_interval_contains_0": (
            abs(stats["null-champion"]["mean"]) <=
            stats["null-champion"]["half_width_95"]),
        "sampled_exact_use_gt_0": exact_work.get("exact_endgames", 0) > 0,
        "exact_refusals_eq_0": (
            exact_work.get("exact_endgame_refusals", -1) == 0),
        "exact_budget_overflow_eq_0": (
            exact_work.get("exact_endgame_budget_exceeded", -1) == 0),
    }
    criteria["all"] = all(criteria.values())
    return criteria


def runtime_without_host(runtime: dict) -> dict:
    return {key: value for key, value in runtime.items() if key != "host"}


def resolve_evidence_path(aggregate_path: Path, raw_path) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise ProtocolRefused("screen input has an invalid evidence path")
    path = Path(raw_path)
    if path.is_absolute():
        raise ProtocolRefused("screen input evidence paths must be relative")
    resolved = (aggregate_path.parent / path).resolve()
    try:
        resolved.relative_to(aggregate_path.parent.resolve())
    except ValueError as exc:
        raise ProtocolRefused(
            "screen input evidence path escapes aggregate directory") from exc
    return resolved


def load_bound_screen_inputs(aggregate_path: os.PathLike | str,
                             inputs: list) -> tuple[list, dict[str, list]]:
    """Reopen the exact raw screen manifests and JSONL named by an aggregate."""
    aggregate_path = Path(aggregate_path).resolve()
    required = {
        "manifest_path", "manifest_sha256", "records_path",
        "records_sha256", "shard_index",
    }
    if not isinstance(inputs, list) or len(inputs) != SHARD_COUNT:
        raise ProtocolRefused("screen aggregate input-shard population")
    manifests = []
    records: dict[str, list] = {}
    seen_manifests = set()
    seen_records = set()
    for item in inputs:
        if not isinstance(item, dict) or set(item) != required:
            raise ProtocolRefused("screen aggregate input-shard schema")
        manifest_path = resolve_evidence_path(
            aggregate_path, item["manifest_path"])
        records_path = resolve_evidence_path(
            aggregate_path, item["records_path"])
        if manifest_path in seen_manifests or records_path in seen_records:
            raise ProtocolRefused("screen aggregate repeats an input path")
        seen_manifests.add(manifest_path)
        seen_records.add(records_path)
        if (not is_sha256(item["manifest_sha256"])
                or not manifest_path.is_file()
                or sha256(manifest_path) != item["manifest_sha256"]):
            raise ProtocolRefused(
                f"screen shard manifest digest mismatch: {manifest_path}")
        if (not is_sha256(item["records_sha256"])
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
                            f"blank screen record at {records_path}:{line_number}")
                    row = json.loads(line)
                    if (not isinstance(row, dict)
                            or "_source" in row
                            or not isinstance(row.get("label"), str)):
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


def load_screen_parent(path: os.PathLike | str, expected_sha256: str,
                       s0_parent: dict) -> dict:
    """Require a passing screen and reproduce it from bound raw records."""
    path = Path(path).resolve()
    if (not is_sha256(expected_sha256) or not path.is_file()
            or sha256(path) != expected_sha256):
        raise ProtocolRefused("screen parent digest mismatch")
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ProtocolRefused(f"screen parent unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProtocolRefused("screen parent is not an object")
    champion = s0_parent["champion_policy"]
    labels = labels_for(champion)
    expected_contracts = {
        name: policy_contract(name) for name in labels.values()}
    expected_ballots = arm_ballots(labels.values())
    if (payload.get("schema") != AGGREGATE_SCHEMA
            or payload.get("phase") != "screen"
            or payload.get("claim") != PROTOCOLS["screen"]["claim"]
            or payload.get("complete") is not True
            or payload.get("production_promotion") is not False
            or payload.get("evaluation_unit") != "one_complete_round"
            or payload.get("primary_outcome") != "signed_level_utility"
            or payload.get("multi_round_progression_tested") is not False
            or payload.get("clusters") != 2_048
            or payload.get("seed0") != 139_000_000
            or payload.get("seed_hi") != 139_002_047
            or payload.get("s0_parent") != s0_parent
            or payload.get("champion_policy") != champion
            or payload.get("labels") != labels
            or payload.get("selection_rule") != SELECTION_RULE
            or payload.get("policy_contracts") != expected_contracts
            or payload.get("ballots") != expected_ballots
            or payload.get("mechanics_commit") != MECHANICS_COMMIT
            or payload.get("mechanics_asset_sha256") !=
            MECHANICS_ASSET_SHA256
            or payload.get("screen_parent") is not None
            or not isinstance(payload.get("throughput_parent"), dict)
            or payload.get("confirmation_authorized") is not True
            or payload.get("strength_confirmed") is not None):
        raise ProtocolRefused("screen aggregate identity/authorization")
    runtime = payload.get("runtime_identity")
    head = payload.get("git_sha")
    if (not isinstance(runtime, dict) or not isinstance(head, str)
            or len(head) != 40):
        raise ProtocolRefused("screen aggregate executable identity")
    manifests, records = load_bound_screen_inputs(
        path, payload.get("input_shards"))
    problems = validate_population(
        "screen", manifests, records, runtime, head, s0_parent, None,
        payload.get("throughput_parent"),
        check_current_protocol=False,
    )
    totals = counter_totals(records) if not problems else {}
    stats = all_contrasts(records) if not problems else {}
    criteria = gate_criteria(stats, totals) if not problems else {}
    throughput = (observed_throughput(
        "screen", manifests, payload["throughput_parent"])
        if not problems else {})
    if payload.get("record_counts") != {
            label: len(rows) for label, rows in records.items()}:
        problems.append("screen aggregate/raw record counts differ")
    if payload.get("counter_totals") != totals:
        problems.append("screen aggregate/raw counter totals differ")
    if payload.get("stats") != stats:
        problems.append("screen aggregate/raw paired statistics differ")
    if payload.get("criteria") != criteria:
        problems.append("screen aggregate/raw criteria differ")
    if payload.get("throughput") != throughput:
        problems.append("screen aggregate/raw throughput differs")
    authorized = (criteria.get("all") is True
                  and throughput.get("criteria", {}).get("all") is True)
    if payload.get("confirmation_authorized") is not authorized:
        problems.append("screen aggregate/raw authorization differs")
    if not authorized:
        problems.append("screen raw evidence does not authorize confirmation")
    if problems:
        raise ProtocolRefused(
            "screen parent evidence: " + "; ".join(sorted(set(problems))))
    return {
        "path": str(path),
        "sha256": expected_sha256,
        "schema": payload["schema"],
        "git_sha": head,
        "runtime_identity": runtime,
        "champion_policy": payload["champion_policy"],
        "throughput_parent": payload["throughput_parent"],
        "confirmation_authorized": True,
        "raw_evidence_sha256": stable_digest(payload["input_shards"]),
    }


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
            or runtime_without_host(parent_runtime) !=
            runtime_without_host(current_runtime)):
        raise ProtocolRefused(
            "confirmation executable runtime/source differs from frozen screen")


def parent_args(args) -> tuple[dict, dict | None, dict]:
    s0_parent = load_s0_parent(
        args.s0_packet, args.expected_s0_packet_sha256,
        args.s0_closeout, args.expected_s0_closeout_sha256,
    )
    if args.phase == "confirm":
        if not args.screen_parent or not args.expected_screen_parent_sha256:
            raise ProtocolRefused(
                "confirmation requires the exact authorizing screen parent")
        screen_parent = load_screen_parent(
            args.screen_parent, args.expected_screen_parent_sha256, s0_parent)
    else:
        if args.screen_parent or args.expected_screen_parent_sha256:
            raise ProtocolRefused("screen may not accept a screen-result parent")
        screen_parent = None
    if (not args.throughput_receipt
            or not args.expected_throughput_receipt_sha256):
        raise ProtocolRefused(
            "strength launch requires the exact score-free throughput receipt")
    throughput_parent = load_throughput_parent(
        args.throughput_receipt,
        args.expected_throughput_receipt_sha256,
        s0_parent,
    )
    if (screen_parent is not None
            and screen_parent.get("throughput_parent") != throughput_parent):
        raise ProtocolRefused(
            "confirmation throughput receipt differs from frozen screen")
    return s0_parent, screen_parent, throughput_parent


def run_shard(args) -> None:
    _, runtime = require_runtime()
    spec = PROTOCOLS[args.phase]
    if not 0 <= args.shard_index < SHARD_COUNT:
        raise ProtocolRefused(f"shard-index must satisfy 0 <= i < {SHARD_COUNT}")
    s0_parent, screen_parent, throughput_parent = parent_args(args)
    champion = s0_parent["champion_policy"]
    problems = protocol_problems(champion)
    if problems:
        raise ProtocolRefused(
            "S3b strength protocol drift:\n  - " + "\n  - ".join(problems))
    head = git("rev-parse", "HEAD")
    dirty = git("status", "--porcelain")
    if dirty and not args.smoke:
        raise ProtocolRefused("full S3b shard refuses a dirty tree")
    require_screen_execution_identity(screen_parent, head, runtime)
    require_throughput_execution_identity(throughput_parent, head, runtime)

    clusters = 2 if args.smoke else spec["clusters_per_shard"]
    seed0 = spec["seed0"] + args.shard_index * spec["clusters_per_shard"]
    run_id = (f"{SCHEMA}_{args.phase}_shard{args.shard_index:02d}_"
              f"{head[:10]}" + ("_SMOKE" if args.smoke else ""))
    out = Path(args.out or f"runs/logs/{run_id}.jsonl")
    manifest_path = Path(str(out) + ".manifest.json")
    records_partial = Path(str(out) + ".partial")
    manifest_partial = Path(str(manifest_path) + ".partial")
    for path in (out, records_partial, manifest_path, manifest_partial,
                 Path(str(out) + ".FAILED"),
                 Path(str(manifest_path) + ".FAILED")):
        if path.exists():
            raise ProtocolRefused(f"refusing to overwrite {path}")
    out.parent.mkdir(parents=True, exist_ok=True)

    labels = labels_for(champion)
    manifest = {
        "schema": SCHEMA,
        "phase": args.phase,
        "claim": spec["claim"],
        "run_id": run_id,
        "evidence_grade": not args.smoke,
        "screen_only": args.phase == "screen",
        "production_promotion": False,
        "evaluation_unit": "one_complete_round",
        "primary_outcome": "signed_level_utility",
        "multi_round_progression_tested": False,
        "git_sha": head,
        "tree_dirty": bool(dirty),
        "dirty_files": dirty.splitlines() if dirty else [],
        **runtime,
        "mechanics_commit": MECHANICS_COMMIT,
        "mechanics_asset_sha256": MECHANICS_ASSET_SHA256,
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
        "throughput_parent": throughput_parent,
        "policy_contracts": {
            name: policy_contract(name) for name in labels.values()},
        "ballots": arm_ballots(labels.values()),
        "started": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
    }
    with manifest_partial.open("x") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())

    records = {}
    elapsed_by_label = {}
    shard_started = time.perf_counter()
    with records_partial.open("x") as fh:
        for label, policy in labels.items():
            print(f"\n{label}: {policy} vs {champion}", flush=True)
            label_started = time.perf_counter()
            records[label] = run_arm(
                label, policy, champion, clusters, seed0, fh, run_id,
                progress_scores=False)
            elapsed_by_label[label] = time.perf_counter() - label_started
        fh.flush()
        os.fsync(fh.fileno())
    wall_seconds = time.perf_counter() - shard_started

    problems = record_problems(records)
    manifest.update({
        "records_sha256": sha256(records_partial),
        "record_counts": {label: len(rows)
                          for label, rows in records.items()},
        "counter_totals": counter_totals(records),
        "wall_seconds": wall_seconds,
        "wall_seconds_by_label": elapsed_by_label,
        "completed": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "problems": problems,
        "complete": not problems,
    })
    with manifest_partial.open("w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    suffix = "" if not problems else ".FAILED"
    publish_partial_exclusive(records_partial, Path(str(out) + suffix))
    publish_partial_exclusive(
        manifest_partial, Path(str(manifest_path) + suffix))
    if problems:
        raise ProtocolRefused(
            "S3b shard failed closed:\n  - " + "\n  - ".join(problems))
    print(f"\nrecords: {out}\nmanifest: {manifest_path}")


def load_population(pattern: str, phase: str):
    paths = [Path(raw).resolve() for raw in sorted(glob.glob(pattern))]
    if len(paths) != SHARD_COUNT or len(set(paths)) != len(paths):
        raise ProtocolRefused(
            f"pattern resolved {len(paths)} unique manifests, expected 8")
    manifests = []
    records: dict[str, list] = {}
    for path in paths:
        try:
            manifest = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ProtocolRefused(f"manifest unreadable: {path}: {exc}") from exc
        if (not isinstance(manifest, dict)
                or manifest.get("schema") != SCHEMA
                or manifest.get("phase") != phase
                or manifest.get("evidence_grade") is not True):
            raise ProtocolRefused(f"unexpected/non-evidence manifest: {path}")
        record_path = Path(str(path).removesuffix(".manifest.json"))
        if not record_path.is_file():
            raise ProtocolRefused(f"manifest has no records: {path}")
        if (not is_sha256(manifest.get("records_sha256"))
                or manifest["records_sha256"] != sha256(record_path)):
            raise ProtocolRefused(f"manifest/record digest drift: {path}")
        manifests.append((path, manifest))
        try:
            with record_path.open() as fh:
                for line_number, line in enumerate(fh, 1):
                    if not line.strip():
                        raise ProtocolRefused(
                            f"blank record at {record_path}:{line_number}")
                    row = json.loads(line)
                    if (not isinstance(row, dict)
                            or "_source" in row
                            or not isinstance(row.get("label"), str)):
                        raise ProtocolRefused(
                            f"malformed record at {record_path}:{line_number}")
                    row["_source"] = str(record_path)
                    records.setdefault(row["label"], []).append(row)
        except (OSError, json.JSONDecodeError) as exc:
            raise ProtocolRefused(
                f"records unreadable: {record_path}: {exc}") from exc
    return manifests, records


def _record_shape_problem(row: dict) -> bool:
    return set(row) != {
        "run", "label", "policy", "seed", "flip", "won",
        "level_utility", "arm", "opp", "_source",
    }


def validate_population(phase: str, manifests, records,
                        current_runtime: dict, current_head: str,
                        s0_parent: dict, screen_parent: dict | None,
                        throughput_parent: dict,
                        *, check_current_protocol: bool = True) -> list[str]:
    spec = PROTOCOLS[phase]
    champion = s0_parent["champion_policy"]
    labels = labels_for(champion)
    expected_contracts = {
        name: policy_contract(name) for name in labels.values()}
    expected_ballots = arm_ballots(labels.values())
    problems = []
    if len(manifests) != SHARD_COUNT:
        problems.append(f"found {len(manifests)} shards, expected {SHARD_COUNT}")
    indices = [manifest.get("shard_index") for _, manifest in manifests]
    if (any(isinstance(index, bool) or not isinstance(index, int)
            for index in indices)
            or sorted(index for index in indices
                      if isinstance(index, int) and not isinstance(index, bool)) !=
            list(range(SHARD_COUNT))):
        problems.append(f"shard indices are {indices}")
    stable_fields = (
        "git_sha", "python", "fast_engine", "require_voids",
        "experimental_sampler_flags", "digests", "labels", "ballots",
        "policy_contracts", "selection_rule", "claim", "shard_count",
        "total_clusters", "champion_policy", "opponent", "s0_parent",
        "screen_parent", "throughput_parent", "mechanics_commit",
        "mechanics_asset_sha256", "production_promotion", "evaluation_unit",
        "primary_outcome", "multi_round_progression_tested",
    )
    for key in stable_fields:
        values = {json.dumps(manifest.get(key), sort_keys=True)
                  for _, manifest in manifests}
        if len(values) > 1:
            problems.append(f"shards disagree on {key}")
    run_by_source = {}
    for path, manifest in manifests:
        index = manifest.get("shard_index")
        valid_index = (not isinstance(index, bool)
                       and isinstance(index, int)
                       and 0 <= index < SHARD_COUNT)
        expected_run_id = (
            f"{SCHEMA}_{phase}_shard{index:02d}_{current_head[:10]}"
            if valid_index else None)
        if not manifest.get("complete") or manifest.get("problems"):
            problems.append(f"incomplete/failed manifest {path}")
        if (manifest.get("schema") != SCHEMA
                or manifest.get("phase") != phase
                or manifest.get("run_id") != expected_run_id):
            problems.append(f"{path}: exact phase/run identity drift")
        if (manifest.get("tree_dirty") is not False
                or manifest.get("dirty_files") != []
                or manifest.get("evidence_grade") is not True):
            problems.append(f"dirty/non-evidence manifest {path}")
        if manifest.get("production_promotion") is not False:
            problems.append(f"manifest claims production promotion {path}")
        if (manifest.get("evaluation_unit") != "one_complete_round"
                or manifest.get("primary_outcome") != "signed_level_utility"
                or manifest.get("multi_round_progression_tested") is not False):
            problems.append(f"manifest overclaims its evaluation unit {path}")
        if manifest.get("screen_only") is not (phase == "screen"):
            problems.append(f"manifest screen/confirmation identity {path}")
        if (manifest.get("claim") != spec["claim"]
                or manifest.get("selection_rule") != SELECTION_RULE
                or manifest.get("labels") != labels
                or manifest.get("champion_policy") != champion
                or manifest.get("opponent") != champion
                or manifest.get("shard_count") != SHARD_COUNT
                or manifest.get("total_clusters") != spec["clusters"]
                or manifest.get("policy_contracts") != expected_contracts
                or manifest.get("ballots") != expected_ballots):
            problems.append(f"{path}: frozen policy/claim contract drift")
        if manifest.get("git_sha") != current_head:
            problems.append(f"{path}: git SHA differs from verifier")
        observed_runtime = {key: manifest.get(key) for key in current_runtime}
        if runtime_without_host(observed_runtime) != \
                runtime_without_host(current_runtime):
            problems.append(f"{path}: executable runtime differs from verifier")
        if manifest.get("s0_parent") != s0_parent:
            problems.append(f"{path}: terminal S0 parent drift")
        if manifest.get("screen_parent") != screen_parent:
            problems.append(f"{path}: screen parent drift")
        if manifest.get("throughput_parent") != throughput_parent:
            problems.append(f"{path}: throughput parent drift")
        if manifest.get("host") != throughput_parent.get(
                "runtime_identity", {}).get("host"):
            problems.append(f"{path}: worker host differs from timed preflight")
        wall_seconds = manifest.get("wall_seconds")
        elapsed_by_label = manifest.get("wall_seconds_by_label")
        if (isinstance(wall_seconds, bool)
                or not isinstance(wall_seconds, (int, float))
                or not math.isfinite(wall_seconds) or wall_seconds <= 0
                or not isinstance(elapsed_by_label, dict)
                or set(elapsed_by_label) != set(labels)
                or any(isinstance(value, bool)
                       or not isinstance(value, (int, float))
                       or not math.isfinite(value) or value <= 0
                       for value in elapsed_by_label.values())
                or sum(elapsed_by_label.values()) > wall_seconds * 1.001):
            problems.append(f"{path}: malformed shard wall-time accounting")
        if (manifest.get("mechanics_commit") != MECHANICS_COMMIT
                or manifest.get("mechanics_asset_sha256") !=
                MECHANICS_ASSET_SHA256):
            problems.append(f"{path}: mechanics parent drift")
        if valid_index:
            want = spec["seed0"] + index * spec["clusters_per_shard"]
            if (manifest.get("seed0") != want
                    or manifest.get("seed_hi") !=
                    want + spec["clusters_per_shard"] - 1):
                problems.append(f"shard {index}: seed block drift")
        if manifest.get("clusters") != spec["clusters_per_shard"]:
            problems.append(f"{path}: cluster count drift")
        source = str(path).removesuffix(".manifest.json")
        run_by_source[source] = manifest.get("run_id")
        by_label = {
            label: [row for row in rows if row.get("_source") == source]
            for label, rows in records.items()
        }
        if manifest.get("record_counts") != {
                label: len(rows) for label, rows in by_label.items()}:
            problems.append(f"{path}: record counts differ from records")
        try:
            observed_totals = counter_totals(by_label)
        except (KeyError, TypeError, ValueError):
            observed_totals = None
        if manifest.get("counter_totals") != observed_totals:
            problems.append(f"{path}: counter totals differ from records")
        if valid_index:
            expected_keys = {
                (seed, flip)
                for seed in range(
                    spec["seed0"] + index * spec["clusters_per_shard"],
                    spec["seed0"] + (index + 1) *
                    spec["clusters_per_shard"])
                for flip in (0, 1)
            }
            for label in labels:
                rows = by_label.get(label, [])
                keys = {(row.get("seed"), row.get("flip")) for row in rows}
                if len(rows) != len(expected_keys) or keys != expected_keys:
                    problems.append(f"{path}: {label} local shard coverage")

    if set(records) != set(labels):
        problems.append(f"record labels {sorted(records)} != {sorted(labels)}")
    expected_keys = {
        (seed, flip)
        for seed in range(spec["seed0"], spec["seed0"] + spec["clusters"])
        for flip in (0, 1)
    }
    for label, rows in records.items():
        keys = [(row.get("seed"), row.get("flip")) for row in rows]
        if len(rows) != 2 * spec["clusters"]:
            problems.append(f"{label}: {len(rows)} records")
        if len(keys) != len(set(keys)) or set(keys) != expected_keys:
            problems.append(f"{label}: exact seed/flip coverage differs")
        for row in rows:
            if _record_shape_problem(row):
                problems.append(f"{label}: record schema drift")
                continue
            if row["policy"] != labels[label]:
                problems.append(f"{label}: policy identity drift")
            if row["run"] != run_by_source.get(row["_source"]):
                problems.append(f"{label}: record/run identity drift")
            if (isinstance(row["seed"], bool)
                    or not isinstance(row["seed"], int)
                    or row["flip"] not in (0, 1)
                    or isinstance(row["flip"], bool)
                    or row["won"] not in (0, 1)
                    or isinstance(row["won"], bool)
                    or isinstance(row["level_utility"], bool)
                    or not isinstance(row["level_utility"], int)
                    or row["level_utility"] == 0
                    or (row["level_utility"] > 0) != bool(row["won"])):
                problems.append(f"{label}: malformed outcome record")
    problems += record_problems(records)
    if check_current_protocol:
        problems += protocol_problems(champion)
    return sorted(set(problems))


def aggregate(args) -> None:
    _, runtime = require_runtime()
    if git("status", "--porcelain"):
        raise ProtocolRefused("S3b aggregate refuses a dirty tree")
    head = git("rev-parse", "HEAD")
    s0_parent, screen_parent, throughput_parent = parent_args(args)
    require_screen_execution_identity(screen_parent, head, runtime)
    require_throughput_execution_identity(throughput_parent, head, runtime)
    manifests, records = load_population(args.pattern, args.phase)
    problems = validate_population(
        args.phase, manifests, records, runtime, head,
        s0_parent, screen_parent, throughput_parent)
    if problems:
        raise ProtocolRefused(
            "S3b aggregation refused:\n  - " + "\n  - ".join(problems))
    totals = counter_totals(records)
    stats = all_contrasts(records)
    criteria = gate_criteria(stats, totals)
    throughput = observed_throughput(
        args.phase, manifests, throughput_parent)
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
        "evaluation_unit": "one_complete_round",
        "primary_outcome": "signed_level_utility",
        "multi_round_progression_tested": False,
        "git_sha": head,
        "runtime_identity": runtime,
        "mechanics_commit": MECHANICS_COMMIT,
        "mechanics_asset_sha256": MECHANICS_ASSET_SHA256,
        "clusters": spec["clusters"],
        "seed0": spec["seed0"],
        "seed_hi": spec["seed0"] + spec["clusters"] - 1,
        "champion_policy": champion,
        "labels": labels,
        "selection_rule": SELECTION_RULE,
        "s0_parent": s0_parent,
        "screen_parent": screen_parent,
        "throughput_parent": throughput_parent,
        "policy_contracts": {
            name: policy_contract(name) for name in labels.values()},
        "ballots": arm_ballots(labels.values()),
        "input_shards": [
            {
                "manifest_path": evidence_path(path),
                "manifest_sha256": sha256(path),
                "records_path": evidence_path(
                    str(path).removesuffix(".manifest.json")),
                "records_sha256": manifest["records_sha256"],
                "shard_index": manifest["shard_index"],
            }
            for path, manifest in sorted(
                manifests, key=lambda item: item[1]["shard_index"])
        ],
        "record_counts": {label: len(rows)
                          for label, rows in records.items()},
        "counter_totals": totals,
        "stats": stats,
        "criteria": criteria,
        "throughput": throughput,
        "confirmation_authorized": (
            criteria["all"] and throughput["criteria"]["all"]
            if args.phase == "screen" else None),
        "strength_confirmed": (
            criteria["all"] if args.phase == "confirm" else None),
        "production_promotion": False,
        "claim_boundary": (
            "Exact partnership-minimax only inside each sampled fully "
            "determinized <=4-card world; not exact imperfect-information "
            "Shengji. The evaluator covers one complete deal/round with "
            "signed level utility, not multi-round progression; a later "
            "mirrored progression gate and explicit deployment review remain."
        ),
    }
    write_exclusive_atomic(args.out, result)
    print(json.dumps(result, indent=2, sort_keys=True))


def add_parent_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--s0-packet", required=True)
    parser.add_argument("--expected-s0-packet-sha256", required=True)
    parser.add_argument("--s0-closeout", required=True)
    parser.add_argument("--expected-s0-closeout-sha256", required=True)
    parser.add_argument("--screen-parent")
    parser.add_argument("--expected-screen-parent-sha256")
    parser.add_argument("--throughput-receipt", required=True)
    parser.add_argument("--expected-throughput-receipt-sha256", required=True)


def add_s0_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--s0-packet", required=True)
    parser.add_argument("--expected-s0-packet-sha256", required=True)
    parser.add_argument("--s0-closeout", required=True)
    parser.add_argument("--expected-s0-closeout-sha256", required=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--out", required=True)
    preflight.add_argument("--screen-fleet-hour-cap", type=float, required=True)
    preflight.add_argument("--screen-shard-wall-hour-cap", type=float,
                           required=True)
    preflight.add_argument("--confirm-fleet-hour-cap", type=float, required=True)
    preflight.add_argument("--confirm-shard-wall-hour-cap", type=float,
                           required=True)
    add_s0_arguments(preflight)
    run = sub.add_parser("run")
    run.add_argument("phase", choices=tuple(PROTOCOLS))
    run.add_argument("--shard-index", type=int, required=True)
    run.add_argument("--smoke", action="store_true")
    run.add_argument("--out")
    add_parent_arguments(run)
    agg = sub.add_parser("aggregate")
    agg.add_argument("phase", choices=tuple(PROTOCOLS))
    agg.add_argument("--pattern", required=True)
    agg.add_argument("--out", required=True)
    add_parent_arguments(agg)
    args = parser.parse_args()
    if args.command == "preflight":
        run_throughput_preflight(args)
    elif args.command == "run":
        run_shard(args)
    else:
        aggregate(args)


if __name__ == "__main__":
    try:
        main()
    except ProtocolRefused as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc

#!/usr/bin/env python3
"""Fresh, conditional deployment choice between the two S0 LCB policies.

S0b established that the report-LCB rule replicated, but did not resolve the
increment from adaptive allocation.  This protocol asks the narrower product
question on a new population: if and only if terminal S0 promotes the frozen
``mc-s0-adaptive`` bundle, is its extra allocation complexity measurably better
than the simpler ``mc-s0-report-lcb`` policy?

Eight shards cover exactly 16,384 mirrored deal clusters at seeds
147,000,000--147,016,383.  Adaptive, report-LCB, current and current-null all
play the same deals against the same current opponent.  Each candidate must
independently clear current and current-null.  If neither clears, current stays;
if exactly one clears, that candidate enters deployment review; if both clear,
adaptive enters review only when its paired 95% lower bound over report-LCB is
positive.  Otherwise the simpler report-LCB enters review.

This is separate from S0.  It cannot rescue SELECT NONE, reinterpret S0c,
automatically deploy a policy, retry a seed block, or extend the sample after
inspection.  The runner emits dose-only progress; no partial score is printed.
"""
from __future__ import annotations

import argparse
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
from shengji.ai.registry import S0_REPORT_WORLDS, make_bot  # noqa: E402
from shengji.evaluation import (arm_ballots, paired_by_seed,  # noqa: E402
                                run_arm)


SCHEMA = "s0-deployment-choice-shard-v1"
AGGREGATE_SCHEMA = "s0-deployment-choice-aggregate-v1"
CLAIM = "conditional_fresh_adaptive_vs_report_lcb_deployment_choice"
RETIRED_REASON = (
    "S0e v1 is permanently retired: its current-null stream has lag-17 "
    "cross-cluster collisions and its parent bypasses the corrected S0c "
    "dependency decision; only a separately frozen v2 may run"
)
SHARD_COUNT = 8
TOTAL_CLUSTERS = 16_384
CLUSTERS_PER_SHARD = 2_048
SEED0 = 147_000_000
SEED_HI = 147_016_383
OPPONENT = "mc-strong"
LABELS = {
    "adaptive": "mc-s0-adaptive",
    "report_lcb": "mc-s0-report-lcb",
    "current": "mc-strong",
    "current_null": "mc-strong-null",
}
EXPECTED_S0_PHASES = ["s0a", "s0b-lcb", "s0c-adaptive-lcb"]
EXPECTED_S0_GIT_SHA = "be1e39cd9281f752d610ff770f6a280098024388"
FREEZE_RECEIPT_SCHEMA = "s0-deployment-choice-freeze-v1"
FREEZE_RECEIPT_PATH = Path(__file__).with_name(
    "s0_deployment_choice_freeze.v1.json")
PARENT_LOCK_SCHEMA = "s0-deployment-choice-parent-lock-v1"
PARENT_LOCK_PATH = Path(__file__).with_name(
    "s0_deployment_choice_parent.v1.json")
RUN_NAMESPACE = "s0e-deployment-choice-147m-v1"
RUN_DIR = SERVER / "runs" / "logs" / RUN_NAMESPACE
AGGREGATE_PATH = RUN_DIR / "aggregate.json"
SELECTION_RULE = (
    "Run only after an independently regenerated terminal S0 packet says "
    "PROMOTE mc-s0-adaptive. Over exactly 16,384 fresh mirrored seed clusters, "
    "a candidate is eligible only if its paired two-sided 95% lower bounds "
    "versus current and current-null are both >0 and the current-null minus "
    "current 95% interval contains zero. If neither candidate is eligible, "
    "KEEP_CURRENT. If exactly one is eligible, send that candidate to explicit "
    "deployment review. If both are eligible, send adaptive to review only if "
    "LCB(adaptive-report_lcb)>0; otherwise send the simpler report-LCB policy. "
    "No automatic deployment, retry, seed substitution, sample extension, S0 "
    "reinterpretation or report-LCB fallback after S0 SELECT NONE is allowed."
)
CLAIM_BOUNDARY = (
    "Fresh one-round paired deployment choice only. A named candidate requires "
    "explicit deployment review and later mirrored multi-round progression; "
    "this artifact never changes production automatically."
)
SAMPLER_FLAGS = (
    "SHENGJI_WEIGHTED_SPLITS",
    "SHENGJI_UNIFORM_DEAL",
    "SHENGJI_PHYSICAL_FILLS",
    "SHENGJI_ALLOW_BALLOT_MISMATCH",
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
FORBIDDEN_COUNTER_FIELDS = (
    "void_fallbacks", "rejected_worlds", "failed_worlds",
    "short_searches", "zero_world", "exact_endgames",
    "exact_endgame_attempts", "exact_endgame_refusals",
    "exact_endgame_budget_exceeded", "exact_endgame_sessions",
    "exact_endgame_nodes", "exact_endgame_cache_hits",
)


class ProtocolRefused(RuntimeError):
    """The requested artifact cannot support the frozen deployment claim."""


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


def is_sha256(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def load_freeze_receipt() -> dict:
    try:
        value = json.loads(FREEZE_RECEIPT_PATH.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolRefused(f"S0e freeze receipt unreadable: {exc}") from exc
    expected_keys = {
        "schema", "frozen_protocol_sha256", "frozen_source_sha256s",
        "frozen_policy_contract_sha256s", "selection_digest", "python",
        "fast_binary_sha256", "execution_host", "execution_root",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise ProtocolRefused("S0e freeze receipt schema fields drifted")
    if value.get("schema") != FREEZE_RECEIPT_SCHEMA:
        raise ProtocolRefused("S0e freeze receipt schema drifted")
    return value


def load_parent_lock() -> dict:
    try:
        value = json.loads(PARENT_LOCK_PATH.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolRefused(f"S0e parent lock unreadable: {exc}") from exc
    expected_keys = {
        "schema", "authorized", "terminal_state", "decision",
        "packet_sha256", "closeout_sha256", "s0c_aggregate_sha256",
        "freeze_receipt_sha256", "binding_rule",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise ProtocolRefused("S0e parent lock schema fields drifted")
    if value.get("schema") != PARENT_LOCK_SCHEMA:
        raise ProtocolRefused("S0e parent lock schema drifted")
    if not isinstance(value.get("authorized"), bool):
        raise ProtocolRefused("S0e parent lock authorization is not boolean")
    if value.get("binding_rule") != (
            "Bind exact terminal hashes regardless of PASS/FAIL; authorize "
            "only exact PROMOTE mc-s0-adaptive; SELECT NONE remains locked"):
        raise ProtocolRefused("S0e parent binding rule drifted")
    return value


def frozen_source_paths() -> dict[str, Path]:
    return {
        "runner": Path(__file__),
        "package_init": SERVER / "shengji" / "__init__.py",
        "evaluation": SERVER / "shengji" / "evaluation.py",
        "ai_init": SERVER / "shengji" / "ai" / "__init__.py",
        "ai_bury": SERVER / "shengji" / "ai" / "bury.py",
        "ai_endgame": SERVER / "shengji" / "ai" / "endgame.py",
        "ai_env": SERVER / "shengji" / "ai" / "env.py",
        "ai_heuristic": SERVER / "shengji" / "ai" / "heuristic.py",
        "ai_legacy_init": (
            SERVER / "shengji" / "ai" / "legacy_b3f8f61" / "__init__.py"),
        "ai_legacy_mcbot": (
            SERVER / "shengji" / "ai" / "legacy_b3f8f61" / "mcbot.py"),
        "ai_legacy_memory": (
            SERVER / "shengji" / "ai" / "legacy_b3f8f61" / "memory.py"),
        "ai_mcbot": SERVER / "shengji" / "ai" / "mcbot.py",
        "ai_memory": SERVER / "shengji" / "ai" / "memory.py",
        "ai_registry": SERVER / "shengji" / "ai" / "registry.py",
        "ai_smart": SERVER / "shengji" / "ai" / "smart.py",
        "engine_init": SERVER / "shengji" / "engine" / "__init__.py",
        "engine_ballot": SERVER / "shengji" / "engine" / "ballot.py",
        "engine_cards": SERVER / "shengji" / "engine" / "cards.py",
        "engine_combos": SERVER / "shengji" / "engine" / "combos.py",
        "engine_fast": SERVER / "shengji" / "engine" / "fast.py",
        "engine_game": SERVER / "shengji" / "engine" / "game.py",
        "engine_legal": SERVER / "shengji" / "engine" / "legal.py",
        "engine_round": SERVER / "shengji" / "engine" / "round.py",
        "s0_closeout": SERVER / "scripts" / "s0_closeout.py",
    }


def current_source_sha256s() -> dict[str, str]:
    return {name: sha256(path) for name, path in frozen_source_paths().items()}


def selection_identity() -> dict:
    return {
        "schema": SCHEMA,
        "aggregate_schema": AGGREGATE_SCHEMA,
        "claim": CLAIM,
        "shard_count": SHARD_COUNT,
        "total_clusters": TOTAL_CLUSTERS,
        "clusters_per_shard": CLUSTERS_PER_SHARD,
        "seed0": SEED0,
        "seed_hi": SEED_HI,
        "opponent": OPPONENT,
        "labels": LABELS,
        "expected_s0_phases": EXPECTED_S0_PHASES,
        "expected_s0_git_sha": EXPECTED_S0_GIT_SHA,
        "selection_rule": SELECTION_RULE,
        "claim_boundary": CLAIM_BOUNDARY,
        "run_namespace": RUN_NAMESPACE,
    }


def selection_digest() -> str:
    return stable_digest(selection_identity())


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=SERVER.parent, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def git_is_ancestor(ancestor: str, descendant: str) -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=SERVER.parent, capture_output=True, text=True,
    ).returncode == 0


def _repo_relative(path: os.PathLike | str) -> str:
    try:
        return str(Path(path).resolve().relative_to(SERVER.parent.resolve()))
    except ValueError as exc:
        raise ProtocolRefused(
            f"S0e authority path is outside the registered repository: {path}"
        ) from exc


def git_file_commits(path: os.PathLike | str) -> list[str]:
    rel = _repo_relative(path)
    output = git("log", "--follow", "--format=%H", "--", rel)
    return [line for line in output.splitlines() if line]


def git_blob(commit: str, path: os.PathLike | str) -> bytes:
    rel = _repo_relative(path)
    result = subprocess.run(
        ["git", "show", f"{commit}:{rel}"], cwd=SERVER.parent,
        capture_output=True,
    )
    if result.returncode:
        raise ProtocolRefused(
            f"cannot reopen {rel} from authority commit {commit}")
    return result.stdout


def _is_untracked(path: os.PathLike | str) -> bool:
    rel = _repo_relative(path)
    return git("status", "--porcelain", "--", rel).startswith("?? ")


def immutable_freeze_problems() -> list[str]:
    """Prove the receipt still equals its one pre-outcome Git introduction."""
    try:
        commits = git_file_commits(FREEZE_RECEIPT_PATH)
    except (ProtocolRefused, subprocess.SubprocessError) as exc:
        return [f"immutable freeze history unreadable: {exc}"]
    if not commits:
        # Bootstrap is accepted only while both new authority files are
        # visibly untracked. Actual execution separately requires a clean,
        # pushed HEAD, so this branch can support precommit tests but no job.
        if _is_untracked(FREEZE_RECEIPT_PATH) \
                and _is_untracked(PARENT_LOCK_PATH):
            return []
        return ["immutable freeze receipt has no Git introduction"]
    if len(commits) != 1:
        return [
            "immutable freeze receipt changed after its pre-outcome "
            f"introduction: {len(commits)} commits"
        ]
    try:
        frozen = git_blob(commits[0], FREEZE_RECEIPT_PATH)
        current = FREEZE_RECEIPT_PATH.read_bytes()
    except (OSError, ProtocolRefused) as exc:
        return [f"immutable freeze receipt cannot be reopened: {exc}"]
    if current != frozen:
        return ["immutable freeze receipt bytes differ from Git introduction"]
    return []


def parent_transition_problems(lock: dict) -> list[str]:
    """Allow exactly preterminal -> one terminal lock transition in Git."""
    try:
        commits = git_file_commits(PARENT_LOCK_PATH)
    except (ProtocolRefused, subprocess.SubprocessError) as exc:
        return [f"parent-lock history unreadable: {exc}"]
    if not commits:
        if (_is_untracked(FREEZE_RECEIPT_PATH)
                and _is_untracked(PARENT_LOCK_PATH)
                and lock.get("terminal_state") is None):
            return []
        return ["parent lock has no Git introduction"]
    if len(commits) not in (1, 2):
        return [
            "parent lock has more than one terminal transition: "
            f"{len(commits) - 1} changes after introduction"
        ]
    try:
        initial = json.loads(git_blob(commits[-1], PARENT_LOCK_PATH))
        current = json.loads(PARENT_LOCK_PATH.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError,
            ProtocolRefused) as exc:
        return [f"parent-lock transition cannot be reopened: {exc}"]
    mutable = {
        "authorized", "terminal_state", "decision", "packet_sha256",
        "closeout_sha256", "s0c_aggregate_sha256",
    }
    if (not isinstance(initial, dict) or set(initial) != set(current)
            or any(initial.get(key) != current.get(key)
                   for key in set(current) - mutable)):
        return ["parent-lock immutable fields changed after introduction"]
    if (initial.get("authorized") is not False
            or any(initial.get(key) is not None for key in (
                "terminal_state", "decision", "packet_sha256",
                "closeout_sha256", "s0c_aggregate_sha256"))):
        return ["parent-lock Git introduction was not preterminal and closed"]
    if len(commits) == 1:
        if current != initial:
            return ["uncommitted parent-lock transition is not admissible"]
        if lock.get("terminal_state") is not None:
            return ["terminal parent lock has no committed transition"]
    elif lock.get("terminal_state") not in {
            "S0_COMPLETE_SELECT_NONE", "S0_COMPLETE_PROMOTE"}:
        return ["committed parent-lock transition is not terminal"]
    return []


def publish_partial_exclusive(partial: os.PathLike | str,
                              final: os.PathLike | str) -> None:
    """Publish completed bytes without replacing a competing artifact."""
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
    digests = current_source_sha256s()
    digests.update({
        "freeze_receipt": sha256(FREEZE_RECEIPT_PATH),
        "parent_lock": sha256(PARENT_LOCK_PATH),
        "fast_router_runtime": sha256(fast.__file__),
        "fast_binary": sha256(fast._fast.__file__),
    })
    return {
        "host": os.uname().nodename,
        "python": platform.python_version(),
        "fast_engine": True,
        "require_voids": True,
        "experimental_sampler_flags": [],
        "digests": digests,
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
    receipt = load_freeze_receipt()
    if os.uname().nodename != receipt.get("execution_host"):
        raise ProtocolRefused(
            f"host {os.uname().nodename!r} != frozen S0e execution host "
            f"{receipt.get('execution_host')!r}")
    if str(SERVER.resolve()) != receipt.get("execution_root"):
        raise ProtocolRefused(
            f"server root {SERVER.resolve()} != frozen S0e execution root "
            f"{receipt.get('execution_root')!r}")
    if platform.python_version() != receipt.get("python"):
        raise ProtocolRefused(
            f"Python {platform.python_version()} != frozen "
            f"{receipt.get('python')}")
    binary = sha256(fast._fast.__file__)
    if binary != receipt.get("fast_binary_sha256"):
        raise ProtocolRefused("compiled engine binary differs from frozen S0e")
    return fast, runtime_identity(fast)


def require_clean_pushed_head() -> str:
    dirty = git("status", "--porcelain")
    if dirty:
        raise ProtocolRefused(f"deployment-choice tree is dirty: {dirty}")
    head = git("rev-parse", "HEAD")
    if not git_is_ancestor(head, "origin/main"):
        raise ProtocolRefused(
            f"deployment-choice HEAD {head} is not published on origin/main")
    return head


def uppercase_contract(bot) -> dict:
    out = {}
    for name in dir(bot):
        if not name.isupper():
            continue
        value = getattr(bot, name)
        if not isinstance(value, (bool, int, float, str, type(None))):
            raise ProtocolRefused(
                f"non-serializable policy contract {name}={value!r}")
        out[name] = value
    return out


def policy_contract(name: str) -> dict:
    bot = make_bot(name, seed=7)
    return {
        "policy": name,
        "class": type(bot).__name__,
        "uppercase": uppercase_contract(bot),
        "rollout_policy_class": type(bot.rollout_policy).__name__,
        "ballot": arm_ballots([name])[name],
    }


def policy_contract_sha256s() -> dict[str, str]:
    return {
        name: stable_digest(policy_contract(name))
        for name in sorted(set(LABELS.values()))
    }


def parent_lock_problems(lock: dict) -> list[str]:
    problems = []
    try:
        if lock.get("freeze_receipt_sha256") != sha256(FREEZE_RECEIPT_PATH):
            problems.append("parent lock does not bind immutable freeze receipt")
    except OSError as exc:
        problems.append(f"immutable freeze receipt digest unavailable: {exc}")
    hashes = [lock.get(name) for name in (
        "packet_sha256", "closeout_sha256", "s0c_aggregate_sha256")]
    state = lock.get("terminal_state")
    decision = lock.get("decision")
    authorized = lock.get("authorized")
    if state is None:
        if authorized or decision is not None or any(value is not None
                                                      for value in hashes):
            problems.append("preterminal parent lock is not empty and closed")
    elif state == "S0_COMPLETE_SELECT_NONE":
        if (authorized
                or decision != "SELECT NONE; production remains mc-strong"
                or not all(is_sha256(value) for value in hashes)):
            problems.append("SELECT NONE parent lock is not permanently closed")
    elif state == "S0_COMPLETE_PROMOTE":
        if (authorized is not True
                or decision != "PROMOTE mc-s0-adaptive"
                or not all(is_sha256(value) for value in hashes)):
            problems.append("PROMOTE parent lock is incomplete or unauthorized")
    else:
        problems.append(f"unregistered parent-lock terminal state {state!r}")
    return problems


def protocol_problems() -> list[str]:
    # This historical source remains readable for diagnosis, but no v1 job is
    # admissible. Deliberately changing these source bytes also trips its
    # immutable freeze receipt, providing a second fail-closed witness.
    problems = [RETIRED_REASON]
    exact_labels = {
        "adaptive": "mc-s0-adaptive",
        "report_lcb": "mc-s0-report-lcb",
        "current": "mc-strong",
        "current_null": "mc-strong-null",
    }
    if (SHARD_COUNT != 8 or TOTAL_CLUSTERS != 16_384
            or CLUSTERS_PER_SHARD != 2_048
            or TOTAL_CLUSTERS != SHARD_COUNT * CLUSTERS_PER_SHARD
            or SEED0 != 147_000_000 or SEED_HI != 147_016_383
            or SEED_HI != SEED0 + TOTAL_CLUSTERS - 1):
        problems.append("registered shard geometry/147M seed block drifted")
    if LABELS != exact_labels or OPPONENT != "mc-strong":
        problems.append("registered deployment-choice policy labels drifted")
    if EXPECTED_S0_PHASES != [
            "s0a", "s0b-lcb", "s0c-adaptive-lcb"]:
        problems.append("registered terminal S0 parent path drifted")
    if EXPECTED_S0_GIT_SHA != \
            "be1e39cd9281f752d610ff770f6a280098024388":
        problems.append("registered terminal S0 Git identity drifted")
    try:
        receipt = load_freeze_receipt()
        lock = load_parent_lock()
    except ProtocolRefused as exc:
        problems.append(str(exc))
        return sorted(set(problems))
    problems += immutable_freeze_problems()
    problems += parent_lock_problems(lock)
    problems += parent_transition_problems(lock)
    sources = current_source_sha256s()
    if receipt.get("frozen_protocol_sha256") != sources.get("runner"):
        problems.append("pre-outcome runner identity drifted")
    if receipt.get("frozen_source_sha256s") != sources:
        problems.append("pre-outcome transitive source identity drifted")
    if receipt.get("selection_digest") != selection_digest():
        problems.append("predeclared selection digest drifted")
    try:
        bots = {label: make_bot(name, seed=7)
                for label, name in LABELS.items()}
        contracts = {label: uppercase_contract(bot)
                     for label, bot in bots.items()}
    except Exception as exc:
        problems.append(
            f"policy construction failed: {type(exc).__name__}: {exc}")
        return sorted(set(problems))

    for label in ("adaptive", "report_lcb"):
        contract = contracts[label]
        if contract.get("N_DETERMINIZATIONS") != 30:
            problems.append(f"{label}: N is not 30")
        if contract.get("REQUIRE_EXACT_WORK") is not True:
            problems.append(f"{label}: exact work is off")
        if contract.get("REPORT_FOLD_WORLDS") != 300:
            problems.append(f"{label}: report dose is not 300")
        if contract.get("REPORT_RULE") != "lcb":
            problems.append(f"{label}: report rule is not LCB")
        if contract.get("REPORT_MIN_GAIN") != 0.0:
            problems.append(f"{label}: report minimum gain is not zero")
        if S0_REPORT_WORLDS != 300:
            problems.append("registry S0 report dose drifted")
    if contracts["adaptive"].get("ADAPTIVE_ALLOCATION") is not True:
        problems.append("adaptive allocation is not enabled")
    if contracts["adaptive"].get("RANDOM_ALLOCATION") is True:
        problems.append("adaptive arm uses random allocation")
    if contracts["report_lcb"].get("ADAPTIVE_ALLOCATION") is True:
        problems.append("report-LCB unexpectedly uses adaptive allocation")
    for label in ("adaptive", "report_lcb"):
        if contracts[label].get("REPORT_T_CRITICAL") != 1.70:
            problems.append(f"{label}: report t-critical drifted")
        if contracts[label].get("CONFIDENCE_Z") != 1.64:
            problems.append(f"{label}: allocation confidence z drifted")

    if contracts["current"].get("N_DETERMINIZATIONS") != 30:
        problems.append("current is not N=30")
    if contracts["current_null"] != contracts["current"]:
        problems.append("current-null search contract differs from current")
    if type(bots["current_null"].rollout_policy) is not \
            type(bots["current"].rollout_policy):
        problems.append("current-null rollout policy differs from current")
    if bots["current_null"].rng.getstate() == bots["current"].rng.getstate():
        problems.append("current-null does not shift the RNG stream")
    for label, bot in bots.items():
        if any(getattr(bot, field, False) for field in
               ("MC_BURY", "STRUCTURED_BURY", "EXACT_ENDGAME")):
            problems.append(f"{label}: out-of-scope S3 feature enabled")
    try:
        ballots = arm_ballots(LABELS.values())
        if len(set(ballots.values())) != 1:
            problems.append(f"deployment-choice ballots differ: {ballots}")
    except Exception as exc:
        problems.append(f"ballot preflight failed: {type(exc).__name__}: {exc}")
    try:
        if receipt.get("frozen_policy_contract_sha256s") != \
                policy_contract_sha256s():
            problems.append("full frozen policy-contract digests drifted")
    except Exception as exc:
        problems.append(
            f"policy-contract digest failed: {type(exc).__name__}: {exc}")
    return sorted(set(problems))


def _terminal_decision(packet_text: str, status: str) -> str:
    prefix = "Final production decision from registered rule: "
    decisions = [line.removeprefix(prefix) for line in packet_text.splitlines()
                 if line.startswith(prefix)]
    if len(decisions) != 1:
        raise ProtocolRefused(
            f"terminal S0 packet has {len(decisions)} production decisions")
    if status != "S0_COMPLETE_PROMOTE" or \
            decisions[0] != "PROMOTE mc-s0-adaptive":
        raise ProtocolRefused(
            "deployment choice is admissible only after exact terminal "
            "PROMOTE mc-s0-adaptive; SELECT NONE closes S0")
    return "mc-s0-adaptive"


def _aggregate_line(packet_text: str) -> str:
    prefix = "s0c-adaptive-lcb aggregate: "
    lines = [line for line in packet_text.splitlines()
             if line.startswith(prefix)]
    if len(lines) != 1:
        raise ProtocolRefused(
            f"terminal packet has {len(lines)} adaptive S0c aggregate lines")
    return lines[0]


def load_s0_parent(packet_path: os.PathLike | str, packet_sha256: str,
                   closeout_path: os.PathLike | str, closeout_sha256: str,
                   aggregate_path: os.PathLike | str,
                   aggregate_sha256: str) -> dict:
    packet_path = Path(packet_path).resolve()
    closeout_path = Path(closeout_path).resolve()
    aggregate_path = Path(aggregate_path).resolve()
    expected = (packet_sha256, closeout_sha256, aggregate_sha256)
    lock = load_parent_lock()
    lock_problems = parent_lock_problems(lock)
    if lock_problems:
        raise ProtocolRefused(
            "S0e parent lock is invalid: " + "; ".join(lock_problems))
    frozen = (
        lock.get("packet_sha256"),
        lock.get("closeout_sha256"),
        lock.get("s0c_aggregate_sha256"),
    )
    if not lock.get("authorized"):
        raise ProtocolRefused(
            "S0e parent hash lock is not authorized; terminal S0 must bind a "
            "separate immutable admission commit")
    if (lock.get("terminal_state") != "S0_COMPLETE_PROMOTE"
            or lock.get("decision") != "PROMOTE mc-s0-adaptive"):
        raise ProtocolRefused(
            "S0e parent lock does not name exact PROMOTE mc-s0-adaptive")
    if not all(is_sha256(value) for value in frozen):
        raise ProtocolRefused("authorized S0e parent hash lock is incomplete")
    if not all(is_sha256(value) for value in expected):
        raise ProtocolRefused("all terminal S0 expected hashes must be SHA-256")
    if expected != frozen:
        raise ProtocolRefused(
            "caller-supplied terminal S0 hashes differ from the frozen S0e "
            "parent lock")
    for name, path, digest in (
            ("packet", packet_path, packet_sha256),
            ("closeout", closeout_path, closeout_sha256),
            ("S0c aggregate", aggregate_path, aggregate_sha256)):
        if not path.is_file() or sha256(path) != digest:
            raise ProtocolRefused(f"terminal S0 {name} digest mismatch")
    try:
        packet_text = packet_path.read_text()
        closeout = json.loads(closeout_path.read_text())
        aggregate = json.loads(aggregate_path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolRefused(f"terminal S0 parent unreadable: {exc}") from exc
    if closeout.get("schema") != "s0-terminal-closeout-v1":
        raise ProtocolRefused("terminal S0 closeout schema")
    status = closeout.get("state")
    if status not in S0_CLOSEOUT.TERMINAL_STATES:
        raise ProtocolRefused(f"S0 closeout is not terminal: {status!r}")
    if closeout.get("packet_sha256") != packet_sha256:
        raise ProtocolRefused("S0 closeout is not bound to the packet")
    phases = S0_CLOSEOUT.packet_phases(packet_text)
    if phases != EXPECTED_S0_PHASES or closeout.get("phases") != phases:
        raise ProtocolRefused(
            f"S0 closeout/packet phase path differs: {phases!r}")
    problems = S0_CLOSEOUT.packet_problems(packet_text, status)
    if problems:
        raise ProtocolRefused(
            "terminal S0 packet contract: " + "; ".join(problems))
    champion = _terminal_decision(packet_text, status)
    aggregate_line = _aggregate_line(packet_text)
    if (f"sha256={aggregate_sha256}" not in aggregate_line
            or "survivor='mc-s0-adaptive'" not in aggregate_line
            or "promotion=True" not in aggregate_line):
        raise ProtocolRefused(
            "terminal packet is not bound to the supplied promoted S0c "
            "aggregate")
    expected_aggregate = {
        "schema": "s0-mechanism-aggregate-v1",
        "phase": "s0c-adaptive-lcb",
        "promotion": True,
        "clusters": 8_192,
        "seed0": 135_000_000,
        "seed_hi": 135_008_191,
        "survivor_label": "arm",
        "survivor_policy": "mc-s0-adaptive",
        "git_sha": EXPECTED_S0_GIT_SHA,
    }
    drift = {
        key: {"actual": aggregate.get(key), "expected": value}
        for key, value in expected_aggregate.items()
        if aggregate.get(key) != value
    }
    criteria = aggregate.get("criteria")
    if not isinstance(criteria, dict) or criteria.get("all") is not True:
        drift["criteria.all"] = {
            "actual": criteria.get("all") if isinstance(criteria, dict) else None,
            "expected": True,
        }
    if not isinstance(aggregate.get("runtime_identity"), dict):
        drift["runtime_identity"] = {
            "actual": aggregate.get("runtime_identity"), "expected": "dict"}
    expected_counts = {"arm": 16_384, "null": 16_384,
                       "reference": 16_384}
    if aggregate.get("record_counts") != expected_counts:
        drift["record_counts"] = {
            "actual": aggregate.get("record_counts"),
            "expected": expected_counts,
        }
    expected_stats = {"arm-reference", "arm-null", "null-reference"}
    stats = aggregate.get("stats")
    if (not isinstance(stats, dict) or set(stats) != expected_stats
            or any(not isinstance(value, dict)
                   or value.get("clusters") != 8_192
                   for value in stats.values())):
        drift["stats"] = {
            "actual": stats, "expected": "three exact 8,192-cluster contrasts"}
    aggregate_parent = aggregate.get("parent")
    if (not isinstance(aggregate_parent, dict)
            or aggregate_parent.get("phase") != "s0b-lcb"
            or aggregate_parent.get("survivor_policy") != "mc-s0-adaptive"
            or not is_sha256(aggregate_parent.get("sha256"))):
        drift["parent"] = {
            "actual": aggregate_parent,
            "expected": "exact adaptive s0b-lcb parent",
        }
    if drift:
        raise ProtocolRefused(f"terminal promoted S0c aggregate drift: {drift}")
    return {
        "terminal_state": status,
        "champion_policy": champion,
        "packet_path": str(packet_path),
        "packet_sha256": packet_sha256,
        "closeout_path": str(closeout_path),
        "closeout_sha256": closeout_sha256,
        "s0c_aggregate_path": str(aggregate_path),
        "s0c_aggregate_sha256": aggregate_sha256,
        "s0c_git_sha": aggregate.get("git_sha"),
        "s0c_runtime_identity": aggregate.get("runtime_identity"),
        "phases": phases,
        "verification_boundary": (
            "exact independently regenerated terminal packet/closeout and "
            "the exact promoted adaptive S0c aggregate named by that packet"
        ),
    }


def _counter_problem(label: str, side: str, counters: object) -> list[str]:
    prefix = f"{label}/{side}"
    if not isinstance(counters, dict) or set(counters) != set(COUNTER_FIELDS):
        return [f"{prefix}: counter schema drift"]
    problems = []
    for field in INTEGER_COUNTER_FIELDS:
        value = counters[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            problems.append(f"{prefix}: malformed {field}")
    seconds = counters["search_secs"]
    if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds) or seconds < 0):
        problems.append(f"{prefix}: malformed search_secs")
    if problems:
        return problems
    if counters["sample_attempts"] != (
            counters["accepted_worlds"] + counters["failed_worlds"]):
        problems.append(f"{prefix}: sampler counters do not reconcile")
    for field in FORBIDDEN_COUNTER_FIELDS:
        if counters[field]:
            problems.append(f"{prefix}: nonzero {field}")
    # Every opponent and both current controls are plain N=30 MC. Report-LCB
    # consumes exactly 30 selection plus 300 disjoint report worlds per search.
    # Adaptive consumes at least that amount; pruning can increase the number
    # of selection-world draws while keeping candidate-rollout work fixed.
    searches = counters["searches"]
    accepted = counters["accepted_worlds"]
    if searches and counters["rollouts"] <= 0:
        problems.append(f"{prefix}: searches consumed no candidate rollouts")
    if side == "opp" or label in {"current", "current_null"}:
        if accepted != 30 * searches:
            problems.append(f"{prefix}: plain N=30 accepted dose differs")
    elif label == "report_lcb":
        if accepted != (30 + S0_REPORT_WORLDS) * searches:
            problems.append(
                f"{prefix}: fixed selection+report accepted dose differs")
    elif accepted < (30 + S0_REPORT_WORLDS) * searches:
        problems.append(
            f"{prefix}: adaptive accepted fewer than base+report dose")
    return problems


def record_problems(records: object,
                    expected_keys: set[tuple[int, int]] | None = None) \
        -> list[str]:
    if not isinstance(records, dict) or set(records) != set(LABELS):
        return ["record labels differ from frozen labels"]
    problems = []
    shared_keys = None
    for label, rows in records.items():
        if not isinstance(rows, list):
            problems.append(f"{label}: rows are not a list")
            continue
        keys = [
            (row.get("seed"), row.get("flip"))
            if isinstance(row, dict) else (None, None)
            for row in rows
        ]
        if len(keys) != len(set(keys)):
            problems.append(f"{label}: duplicate seed/flip record")
        if shared_keys is None:
            shared_keys = set(keys)
        elif set(keys) != shared_keys:
            problems.append(f"{label}: seed/flip coverage differs")
        if expected_keys is not None and set(keys) != expected_keys:
            problems.append(f"{label}: exact seed/flip coverage differs")
        for row in rows:
            if not isinstance(row, dict):
                problems.append(f"{label}: row is not a mapping")
                continue
            required = {
                "run", "label", "policy", "seed", "flip", "won",
                "level_utility", "arm", "opp",
            }
            if not required.issubset(row):
                problems.append(f"{label}: record schema drift")
                continue
            if (row["label"] != label or row["policy"] != LABELS.get(label)
                    or isinstance(row["seed"], bool)
                    or not isinstance(row["seed"], int)
                    or isinstance(row["flip"], bool)
                    or row["flip"] not in (0, 1)
                    or isinstance(row["won"], bool)
                    or row["won"] not in (0, 1)
                    or isinstance(row["level_utility"], bool)
                    or not isinstance(row["level_utility"], int)
                    or row["level_utility"] == 0
                    or (row["level_utility"] > 0) != bool(row["won"])):
                problems.append(f"{label}: malformed outcome record")
            problems += _counter_problem(label, "arm", row.get("arm"))
            problems += _counter_problem(label, "opp", row.get("opp"))
    return sorted(set(problems))


def counter_totals(records: dict[str, list]) -> dict:
    return {
        label: {
            side: {
                field: sum(row[side][field] for row in rows)
                for field in COUNTER_FIELDS
            }
            for side in ("arm", "opp")
        }
        for label, rows in records.items()
    }


def contrast(records: dict[str, list], a: str, b: str) -> dict:
    mean, half, clusters = paired_by_seed(records[a], records[b])
    return {"a": a, "b": b, "mean": mean,
            "half_width_95": half, "clusters": clusters}


def all_contrasts(records: dict[str, list]) -> dict:
    return {
        "adaptive-current": contrast(records, "adaptive", "current"),
        "adaptive-current_null": contrast(
            records, "adaptive", "current_null"),
        "report_lcb-current": contrast(records, "report_lcb", "current"),
        "report_lcb-current_null": contrast(
            records, "report_lcb", "current_null"),
        "adaptive-report_lcb": contrast(
            records, "adaptive", "report_lcb"),
        "current_null-current": contrast(
            records, "current_null", "current"),
    }


def _lcb(value: dict) -> float:
    return float(value["mean"]) - float(value["half_width_95"])


def gate_criteria(stats: dict) -> dict[str, bool]:
    names = {
        "adaptive-current", "adaptive-current_null",
        "report_lcb-current", "report_lcb-current_null",
        "adaptive-report_lcb", "current_null-current",
    }
    well_shaped = (
        isinstance(stats, dict) and set(stats) == names
        and all(isinstance(value, dict) for value in stats.values())
    )
    exact = well_shaped and all(
        value.get("clusters") == TOTAL_CLUSTERS for value in stats.values())
    if not well_shaped:
        return {
            "exact_registered_clusters": False,
            "finite_paired_statistics": False,
            "current_null_interval_contains_0": False,
            "adaptive_current_lcb_gt_0": False,
            "adaptive_current_null_lcb_gt_0": False,
            "report_lcb_current_lcb_gt_0": False,
            "report_lcb_current_null_lcb_gt_0": False,
            "adaptive_report_lcb_lcb_gt_0": False,
            "adaptive_eligible": False,
            "report_lcb_eligible": False,
        }
    finite = all(
        math.isfinite(float(value.get("mean", float("nan"))))
        and math.isfinite(float(value.get("half_width_95", float("nan"))))
        and float(value.get("half_width_95", -1)) >= 0
        for value in stats.values()
    )
    null = stats["current_null-current"]
    null_sane = (
        exact and finite
        and abs(float(null["mean"])) <= float(null["half_width_95"])
    )
    criteria = {
        "exact_registered_clusters": exact,
        "finite_paired_statistics": finite,
        "current_null_interval_contains_0": null_sane,
        "adaptive_current_lcb_gt_0": _lcb(stats["adaptive-current"]) > 0,
        "adaptive_current_null_lcb_gt_0": (
            _lcb(stats["adaptive-current_null"]) > 0),
        "report_lcb_current_lcb_gt_0": (
            _lcb(stats["report_lcb-current"]) > 0),
        "report_lcb_current_null_lcb_gt_0": (
            _lcb(stats["report_lcb-current_null"]) > 0),
        "adaptive_report_lcb_lcb_gt_0": (
            _lcb(stats["adaptive-report_lcb"]) > 0),
    }
    criteria["adaptive_eligible"] = (
        null_sane and criteria["adaptive_current_lcb_gt_0"]
        and criteria["adaptive_current_null_lcb_gt_0"])
    criteria["report_lcb_eligible"] = (
        null_sane and criteria["report_lcb_current_lcb_gt_0"]
        and criteria["report_lcb_current_null_lcb_gt_0"])
    return criteria


def deployment_decision(criteria: dict[str, bool]) -> tuple[str, str | None]:
    if (not criteria["exact_registered_clusters"]
            or not criteria["finite_paired_statistics"]):
        return "REFUSE_INVALID_EVIDENCE", None
    if not criteria["current_null_interval_contains_0"]:
        return "REFUSE_NULL_CALIBRATION", None
    adaptive = criteria["adaptive_eligible"]
    report = criteria["report_lcb_eligible"]
    if not adaptive and not report:
        return "KEEP_CURRENT", None
    if adaptive and not report:
        return "ADAPTIVE_FOR_DEPLOYMENT_REVIEW", "mc-s0-adaptive"
    if report and not adaptive:
        return "REPORT_LCB_FOR_DEPLOYMENT_REVIEW", "mc-s0-report-lcb"
    if criteria["adaptive_report_lcb_lcb_gt_0"]:
        return "ADAPTIVE_FOR_DEPLOYMENT_REVIEW", "mc-s0-adaptive"
    return "REPORT_LCB_FOR_DEPLOYMENT_REVIEW", "mc-s0-report-lcb"


def _parent_from_args(args) -> dict:
    return load_s0_parent(
        args.s0_packet, args.expected_s0_packet_sha256,
        args.s0_closeout, args.expected_s0_closeout_sha256,
        args.s0c_aggregate, args.expected_s0c_aggregate_sha256,
    )


def _record_path(manifest_path: os.PathLike | str) -> Path:
    return Path(str(manifest_path).removesuffix(".manifest.json"))


def canonical_record_path(shard_index: int) -> Path:
    return RUN_DIR / f"shard{shard_index:02d}.jsonl"


def canonical_manifest_path(shard_index: int) -> Path:
    return Path(str(canonical_record_path(shard_index)) + ".manifest.json")


def canonical_manifest_paths() -> list[Path]:
    return [canonical_manifest_path(index) for index in range(SHARD_COUNT)]


def canonical_aggregate_path() -> Path:
    return AGGREGATE_PATH


def _shard_artifact_paths(shard_index: int) -> set[Path]:
    record = canonical_record_path(shard_index)
    manifest = canonical_manifest_path(shard_index)
    return {
        record,
        Path(str(record) + ".partial"),
        Path(str(record) + ".FAILED"),
        manifest,
        Path(str(manifest) + ".partial"),
        Path(str(manifest) + ".FAILED"),
    }


def canonical_namespace_problems(stage: str,
                                 shard_index: int | None = None) -> list[str]:
    """Reject alternate output names, retries, residue and path substitution."""
    if stage not in {"run", "aggregate", "verify"}:
        return [f"unknown namespace validation stage {stage!r}"]
    if RUN_DIR.is_symlink():
        return ["canonical S0e run directory is a symlink"]
    if RUN_DIR.exists() and not RUN_DIR.is_dir():
        return ["canonical S0e run namespace is not a directory"]

    shard_paths = set().union(*(
        _shard_artifact_paths(index) for index in range(SHARD_COUNT)))
    aggregate = canonical_aggregate_path()
    aggregate_partial = Path(str(aggregate) + ".partial")
    allowed = shard_paths | {aggregate, aggregate_partial}
    problems = []
    if RUN_DIR.exists():
        for path in RUN_DIR.iterdir():
            if path.is_symlink():
                problems.append(f"canonical namespace contains symlink {path}")
            if path not in allowed:
                problems.append(f"canonical namespace contains unknown {path}")

    failed = sorted(
        str(path) for path in shard_paths
        if str(path).endswith(".FAILED") and path.exists())
    partial = sorted(
        str(path) for path in shard_paths
        if str(path).endswith(".partial") and path.exists())
    finals = {
        canonical_record_path(index) for index in range(SHARD_COUNT)
    } | {
        canonical_manifest_path(index) for index in range(SHARD_COUNT)
    }

    if stage == "run":
        if isinstance(shard_index, bool) or not isinstance(shard_index, int) \
                or not 0 <= shard_index < SHARD_COUNT:
            problems.append(f"invalid canonical shard index {shard_index!r}")
        else:
            collisions = sorted(
                str(path) for path in _shard_artifact_paths(shard_index)
                if path.exists())
            if collisions:
                problems.append(
                    f"canonical shard {shard_index} already attempted: "
                    f"{collisions}")
        if failed:
            problems.append(f"canonical namespace contains failed shard: {failed}")
        if aggregate.exists() or aggregate_partial.exists():
            problems.append("canonical aggregate already attempted")
    elif stage == "aggregate":
        missing = sorted(str(path) for path in finals if not path.is_file())
        if missing:
            problems.append(f"canonical final shard artifacts missing: {missing}")
        if partial:
            problems.append(f"canonical namespace has partial residue: {partial}")
        if failed:
            problems.append(f"canonical namespace has failed residue: {failed}")
        if aggregate.exists() or aggregate_partial.exists():
            problems.append("canonical aggregate already attempted")
    else:
        missing = sorted(str(path) for path in finals if not path.is_file())
        if missing:
            problems.append(f"canonical final shard artifacts missing: {missing}")
        if partial:
            problems.append(f"canonical namespace has partial residue: {partial}")
        if failed:
            problems.append(f"canonical namespace has failed residue: {failed}")
        if not aggregate.is_file():
            problems.append("canonical aggregate is missing")
        if aggregate_partial.exists():
            problems.append("canonical aggregate has partial residue")
    return sorted(set(problems))


def load_population(manifest_paths: list[os.PathLike | str]) \
        -> tuple[list[tuple[Path, dict]], dict[str, list]]:
    manifests = []
    records: dict[str, list] = {}
    for raw_path in manifest_paths:
        path = Path(raw_path).resolve()
        try:
            manifest = json.loads(path.read_text())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolRefused(
                f"canonical manifest unreadable: {path}: {exc}") from exc
        if manifest.get("schema") != SCHEMA or not manifest.get("promotable"):
            raise ProtocolRefused(
                f"canonical manifest is not admissible: {path}")
        record_path = _record_path(path)
        if not record_path.is_file():
            raise ProtocolRefused(f"manifest has no records: {path}")
        if sha256(record_path) != manifest.get("records_sha256"):
            raise ProtocolRefused(f"record digest differs from manifest: {path}")
        manifests.append((path, manifest))
        try:
            for line in record_path.read_text().splitlines():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ProtocolRefused(
                        f"record is not a mapping in {record_path}")
                row["_source"] = str(record_path)
                records.setdefault(row.get("label"), []).append(row)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolRefused(f"malformed records {record_path}: {exc}") \
                from exc
    return manifests, records


def validate_population(manifests: list[tuple[Path, dict]],
                        records: dict[str, list], runtime: dict, head: str,
                        parent: dict, *, check_protocol: bool = True) -> list[str]:
    problems = []
    if len(manifests) != SHARD_COUNT:
        problems.append(f"found {len(manifests)} shards, expected {SHARD_COUNT}")
    indices = [manifest.get("shard_index") for _, manifest in manifests]
    valid_indices = all(
        not isinstance(index, bool) and isinstance(index, int)
        for index in indices
    )
    if not valid_indices or sorted(indices) != list(range(SHARD_COUNT)):
        problems.append(f"shard indices are {indices!r}")
    policy_contracts = {
        name: policy_contract(name) for name in sorted(set(LABELS.values()))
    }
    ballots = arm_ballots(sorted(set(LABELS.values())))
    run_by_source = {}
    for path, manifest in manifests:
        expected_manifest = {
            "schema": SCHEMA,
            "claim": CLAIM,
            "claim_boundary": CLAIM_BOUNDARY,
            "complete": True,
            "promotable": True,
            "problems": [],
            "production_promotion": False,
            "automatic_deployment": False,
            "retry_or_extension_authorized": False,
            "score_blind_progress": True,
            "shard_statistics_persisted": False,
            "git_sha": head,
            "tree_dirty": False,
            "runtime_identity": runtime,
            "shard_count": SHARD_COUNT,
            "total_clusters": TOTAL_CLUSTERS,
            "clusters": CLUSTERS_PER_SHARD,
            "opponent": OPPONENT,
            "labels": LABELS,
            "selection_rule": SELECTION_RULE,
            "selection_digest": selection_digest(),
            "s0_parent": parent,
            "policy_contracts": policy_contracts,
            "ballots": ballots,
        }
        for key, value in expected_manifest.items():
            if manifest.get(key) != value:
                problems.append(f"{path}: {key} drift")
        forbidden_result_keys = {
            "stats", "criteria", "decision", "wins", "win_rate",
            "paired_vs_reference", "deployment_review_candidate",
        }
        leaked = sorted(forbidden_result_keys.intersection(manifest))
        if leaked:
            problems.append(f"{path}: shard manifest is not score-blind: {leaked}")
        index = manifest.get("shard_index")
        if isinstance(index, bool) or not isinstance(index, int) \
                or not 0 <= index < SHARD_COUNT:
            problems.append(f"{path}: invalid shard index")
            continue
        want_lo = SEED0 + index * CLUSTERS_PER_SHARD
        if (manifest.get("seed0") != want_lo
                or manifest.get("seed_hi") != want_lo +
                CLUSTERS_PER_SHARD - 1):
            problems.append(f"{path}: seed block drift")
        expected_run_id = f"{SCHEMA}_shard{index:02d}_{head[:10]}"
        if manifest.get("run_id") != expected_run_id:
            problems.append(f"{path}: run identity drift")
        source = str(_record_path(path))
        run_by_source[source] = manifest.get("run_id")
        by_label = {
            label: [row for row in rows if row.get("_source") == source]
            for label, rows in records.items()
        }
        if manifest.get("record_counts") != {
                label: len(by_label.get(label, [])) for label in LABELS}:
            problems.append(f"{path}: record counts differ")
        try:
            observed_totals = counter_totals(by_label)
        except (KeyError, TypeError, ValueError):
            observed_totals = None
        if manifest.get("counter_totals") != observed_totals:
            problems.append(f"{path}: counter totals differ")
        expected_keys = {
            (seed, flip)
            for seed in range(want_lo, want_lo + CLUSTERS_PER_SHARD)
            for flip in (0, 1)
        }
        for label in LABELS:
            rows = by_label.get(label, [])
            keys = {(row.get("seed"), row.get("flip")) for row in rows}
            if len(rows) != len(expected_keys) or keys != expected_keys:
                problems.append(f"{path}: {label} local shard coverage")

    if set(records) != set(LABELS):
        problems.append(
            f"record labels {sorted(map(str, records))} != "
            f"{sorted(LABELS)}")
    expected_keys = {
        (seed, flip)
        for seed in range(SEED0, SEED0 + TOTAL_CLUSTERS)
        for flip in (0, 1)
    }
    for label, rows in records.items():
        keys = [(row.get("seed"), row.get("flip")) for row in rows]
        if len(rows) != 2 * TOTAL_CLUSTERS:
            problems.append(f"{label}: {len(rows)} records")
        if len(keys) != len(set(keys)) or set(keys) != expected_keys:
            problems.append(f"{label}: exact seed/flip coverage differs")
        for row in rows:
            if row.get("run") != run_by_source.get(row.get("_source")):
                problems.append(f"{label}: record/run identity drift")
    problems += record_problems(records, expected_keys)
    if check_protocol:
        problems += protocol_problems()
    return sorted(set(problems))


def run_shard(args) -> None:
    _, runtime = require_runtime()
    head = require_clean_pushed_head()
    problems = protocol_problems()
    if problems:
        raise ProtocolRefused(
            "deployment-choice policy drift:\n  - " + "\n  - ".join(problems))
    if not 0 <= args.shard_index < SHARD_COUNT:
        raise ProtocolRefused(
            f"shard-index must satisfy 0 <= i < {SHARD_COUNT}")
    namespace_problems = canonical_namespace_problems(
        "run", args.shard_index)
    if namespace_problems:
        raise ProtocolRefused(
            "canonical no-retry namespace refused:\n  - "
            + "\n  - ".join(namespace_problems))
    parent = _parent_from_args(args)
    seed0 = SEED0 + args.shard_index * CLUSTERS_PER_SHARD
    run_id = (
        f"{SCHEMA}_shard{args.shard_index:02d}_{head[:10]}"
    )
    out = canonical_record_path(args.shard_index)
    manifest_path = canonical_manifest_path(args.shard_index)
    record_partial = Path(str(out) + ".partial")
    manifest_partial = Path(str(manifest_path) + ".partial")
    collisions = [path for path in (
        out, record_partial, manifest_path, manifest_partial,
        Path(str(out) + ".FAILED"), Path(str(manifest_path) + ".FAILED"),
    ) if path.exists()]
    if collisions:
        raise ProtocolRefused(f"refusing to overwrite {collisions}")
    out.parent.mkdir(parents=True, exist_ok=True)
    policies = sorted(set(LABELS.values()))
    manifest = {
        "schema": SCHEMA,
        "claim": CLAIM,
        "claim_boundary": CLAIM_BOUNDARY,
        "run_id": run_id,
        "complete": False,
        "promotable": True,
        "problems": [],
        "production_promotion": False,
        "automatic_deployment": False,
        "retry_or_extension_authorized": False,
        "score_blind_progress": True,
        "shard_statistics_persisted": False,
        "git_sha": head,
        "tree_dirty": False,
        "runtime_identity": runtime,
        "shard_index": args.shard_index,
        "shard_count": SHARD_COUNT,
        "total_clusters": TOTAL_CLUSTERS,
        "clusters": CLUSTERS_PER_SHARD,
        "seed0": seed0,
        "seed_hi": seed0 + CLUSTERS_PER_SHARD - 1,
        "opponent": OPPONENT,
        "labels": LABELS,
        "selection_rule": SELECTION_RULE,
        "selection_digest": selection_digest(),
        "s0_parent": parent,
        "policy_contracts": {name: policy_contract(name) for name in policies},
        "ballots": arm_ballots(policies),
        "started": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
    }
    with manifest_partial.open("x") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())

    records = {}
    try:
        with record_partial.open("x") as fh:
            for label, policy in LABELS.items():
                print(
                    f"{label}: starting {CLUSTERS_PER_SHARD} clusters; "
                    "strength scores hidden",
                    flush=True,
                )
                records[label] = run_arm(
                    label, policy, OPPONENT, CLUSTERS_PER_SHARD, seed0, fh,
                    run_id, progress_scores=False,
                )
            fh.flush()
            os.fsync(fh.fileno())
        local_keys = {
            (seed, flip)
            for seed in range(seed0, seed0 + CLUSTERS_PER_SHARD)
            for flip in (0, 1)
        }
        problems = record_problems(records, local_keys)
        try:
            totals = counter_totals(records)
        except (KeyError, TypeError, ValueError) as exc:
            totals = None
            problems.append(f"counter aggregation failed: {exc}")
        manifest.update({
            "complete": not problems,
            "problems": problems,
            "record_counts": {label: len(rows)
                              for label, rows in records.items()},
            "counter_totals": totals,
            "records_sha256": sha256(record_partial),
            "completed": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        })
        with manifest_partial.open("w") as fh:
            json.dump(manifest, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        if problems:
            os.replace(record_partial, Path(str(out) + ".FAILED"))
            os.replace(
                manifest_partial, Path(str(manifest_path) + ".FAILED"))
            raise ProtocolRefused(
                "deployment-choice shard failed:\n  - " +
                "\n  - ".join(problems))
        publish_partial_exclusive(record_partial, out)
        publish_partial_exclusive(manifest_partial, manifest_path)
    except Exception:
        # Preserve nonempty partials for diagnosis; they are never admissible.
        raise
    print(
        f"complete {CLUSTERS_PER_SHARD}/{CLUSTERS_PER_SHARD} clusters; "
        f"records={out}; manifest={manifest_path}",
        flush=True,
    )


def _evidence_path(path: Path, aggregate_dir: Path) -> str:
    return os.path.relpath(path.resolve(), aggregate_dir)


def aggregate(args) -> None:
    _, runtime = require_runtime()
    head = require_clean_pushed_head()
    parent = _parent_from_args(args)
    namespace_problems = canonical_namespace_problems("aggregate")
    if namespace_problems:
        raise ProtocolRefused(
            "canonical no-retry namespace refused:\n  - "
            + "\n  - ".join(namespace_problems))
    manifests, records = load_population(canonical_manifest_paths())
    problems = validate_population(manifests, records, runtime, head, parent)
    if problems:
        raise ProtocolRefused(
            "deployment-choice aggregation refused:\n  - " +
            "\n  - ".join(problems))
    stats = all_contrasts(records)
    criteria = gate_criteria(stats)
    decision, candidate = deployment_decision(criteria)
    totals = counter_totals(records)
    out = canonical_aggregate_path().resolve()
    result = {
        "schema": AGGREGATE_SCHEMA,
        "claim": CLAIM,
        "complete": True,
        "git_sha": head,
        "runtime_identity": runtime,
        "clusters": TOTAL_CLUSTERS,
        "seed0": SEED0,
        "seed_hi": SEED_HI,
        "shard_count": SHARD_COUNT,
        "labels": LABELS,
        "opponent": OPPONENT,
        "selection_rule": SELECTION_RULE,
        "selection_digest": selection_digest(),
        "s0_parent": parent,
        "policy_contracts": {
            name: policy_contract(name) for name in sorted(set(LABELS.values()))
        },
        "ballots": arm_ballots(sorted(set(LABELS.values()))),
        "input_shards": [
            {
                "shard_index": manifest["shard_index"],
                "manifest_path": _evidence_path(path, out.parent),
                "manifest_sha256": sha256(path),
                "records_path": _evidence_path(_record_path(path), out.parent),
                "records_sha256": manifest["records_sha256"],
            }
            for path, manifest in sorted(
                manifests, key=lambda item: item[1]["shard_index"])
        ],
        "record_counts": {label: len(rows) for label, rows in records.items()},
        "counter_totals": totals,
        "stats": stats,
        "criteria": criteria,
        "decision": decision,
        "deployment_review_candidate": candidate,
        "production_promotion": False,
        "automatic_deployment": False,
        "retry_or_extension_authorized": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    write_exclusive_atomic(out, result)
    print(json.dumps(result, indent=2, sort_keys=True))


def _resolve_input(aggregate_path: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        raise ProtocolRefused("aggregate input path is invalid")
    path = Path(raw)
    if path.is_absolute():
        raise ProtocolRefused("aggregate input paths must be relative")
    return (aggregate_path.parent / path).resolve()


def reopen_aggregate(path: os.PathLike | str, expected_sha256: str,
                     runtime: dict, head: str, parent: dict) -> dict:
    path = Path(path).resolve()
    if path != canonical_aggregate_path().resolve():
        raise ProtocolRefused(
            f"deployment-choice aggregate is not canonical: {path}")
    namespace_problems = canonical_namespace_problems("verify")
    if namespace_problems:
        raise ProtocolRefused(
            "canonical evidence namespace refused:\n  - "
            + "\n  - ".join(namespace_problems))
    if not is_sha256(expected_sha256) or not path.is_file() \
            or sha256(path) != expected_sha256:
        raise ProtocolRefused("deployment-choice aggregate digest mismatch")
    try:
        payload = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolRefused(f"deployment-choice aggregate unreadable: {exc}") \
            from exc
    inputs = payload.get("input_shards")
    if not isinstance(inputs, list) or len(inputs) != SHARD_COUNT:
        raise ProtocolRefused("aggregate does not name exactly eight inputs")
    manifests = []
    records: dict[str, list] = {}
    for entry in inputs:
        if not isinstance(entry, dict):
            raise ProtocolRefused("aggregate input entry is malformed")
        index = entry.get("shard_index")
        if isinstance(index, bool) or not isinstance(index, int) \
                or not 0 <= index < SHARD_COUNT:
            raise ProtocolRefused("aggregate input shard index is malformed")
        manifest_path = _resolve_input(path, entry.get("manifest_path"))
        record_path = _resolve_input(path, entry.get("records_path"))
        if (manifest_path != canonical_manifest_path(index).resolve()
                or record_path != canonical_record_path(index).resolve()):
            raise ProtocolRefused(
                "aggregate input does not use canonical shard paths")
        if (not manifest_path.is_file() or not record_path.is_file()
                or sha256(manifest_path) != entry.get("manifest_sha256")
                or sha256(record_path) != entry.get("records_sha256")):
            raise ProtocolRefused("aggregate input digest mismatch")
        try:
            manifest = json.loads(manifest_path.read_text())
            rows = [json.loads(line)
                    for line in record_path.read_text().splitlines()]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolRefused(f"aggregate input unreadable: {exc}") from exc
        if any(not isinstance(row, dict) for row in rows):
            raise ProtocolRefused("aggregate input record is not a mapping")
        if manifest.get("records_sha256") != entry.get("records_sha256"):
            raise ProtocolRefused("aggregate/manifest record digest differs")
        if entry.get("shard_index") != manifest.get("shard_index"):
            raise ProtocolRefused("aggregate/manifest shard index differs")
        manifests.append((manifest_path, manifest))
        for row in rows:
            row["_source"] = str(record_path)
            records.setdefault(row.get("label"), []).append(row)
    problems = validate_population(manifests, records, runtime, head, parent)
    if problems:
        raise ProtocolRefused(
            "reopened deployment evidence refused:\n  - " +
            "\n  - ".join(problems))
    stats = all_contrasts(records)
    criteria = gate_criteria(stats)
    decision, candidate = deployment_decision(criteria)
    expected_payload = {
        "schema": AGGREGATE_SCHEMA,
        "claim": CLAIM,
        "complete": True,
        "git_sha": head,
        "runtime_identity": runtime,
        "clusters": TOTAL_CLUSTERS,
        "seed0": SEED0,
        "seed_hi": SEED_HI,
        "shard_count": SHARD_COUNT,
        "labels": LABELS,
        "opponent": OPPONENT,
        "selection_rule": SELECTION_RULE,
        "selection_digest": selection_digest(),
        "s0_parent": parent,
        "policy_contracts": {
            name: policy_contract(name) for name in sorted(set(LABELS.values()))
        },
        "ballots": arm_ballots(sorted(set(LABELS.values()))),
        "record_counts": {label: len(rows) for label, rows in records.items()},
        "counter_totals": counter_totals(records),
        "stats": stats,
        "criteria": criteria,
        "decision": decision,
        "deployment_review_candidate": candidate,
        "production_promotion": False,
        "automatic_deployment": False,
        "retry_or_extension_authorized": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    drift = [key for key, value in expected_payload.items()
             if payload.get(key) != value]
    if drift:
        raise ProtocolRefused(
            f"aggregate differs from reopened raw evidence: {drift}")
    return payload


def verify(args) -> None:
    _, runtime = require_runtime()
    head = require_clean_pushed_head()
    parent = _parent_from_args(args)
    payload = reopen_aggregate(
        canonical_aggregate_path(), args.expected_aggregate_sha256,
        runtime, head, parent,
    )
    print(json.dumps({
        "schema": "s0-deployment-choice-verification-v1",
        "aggregate_sha256": args.expected_aggregate_sha256,
        "decision": payload["decision"],
        "deployment_review_candidate": payload["deployment_review_candidate"],
        "raw_reopened": True,
        "production_promotion": False,
    }, indent=2, sort_keys=True))


def add_parent_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--s0-packet", required=True)
    parser.add_argument("--expected-s0-packet-sha256", required=True)
    parser.add_argument("--s0-closeout", required=True)
    parser.add_argument("--expected-s0-closeout-sha256", required=True)
    parser.add_argument("--s0c-aggregate", required=True)
    parser.add_argument("--expected-s0c-aggregate-sha256", required=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--shard-index", type=int, required=True)
    add_parent_arguments(run)
    agg = sub.add_parser("aggregate")
    add_parent_arguments(agg)
    check = sub.add_parser("verify")
    check.add_argument("--expected-aggregate-sha256", required=True)
    add_parent_arguments(check)
    args = parser.parse_args()
    if args.command == "run":
        run_shard(args)
    elif args.command == "aggregate":
        aggregate(args)
    else:
        verify(args)


if __name__ == "__main__":
    try:
        main()
    except ProtocolRefused as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc

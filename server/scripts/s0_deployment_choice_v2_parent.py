#!/usr/bin/env python3
"""Exclusive corrected-S0 authority for any future S0e-v2 experiment.

The historical S0e-v1 runner is permanently retired.  This module is the only
admission seam for its successor: one Git transition binds the exact corrected
dependency-audit output and its score-blind input seal.  A corrected SELECT
NONE closes the lane permanently; only an exact corrected PROMOTE may authorize
future v2 work.  This module launches no experiment and changes no production
policy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "server"
SCRIPTS = SERVER / "scripts"
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPTS))

import s0_dependency_audit as DEPENDENCY  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.evaluation import arm_ballots  # noqa: E402


SCHEMA = "s0-deployment-choice-v2-parent-lock-v1"
FREEZE_SCHEMA = "s0-deployment-choice-v2-parent-freeze-v1"
FREEZE_PATH = Path(__file__).with_name(
    "s0_deployment_choice_v2_parent_freeze.v1.json")
LOCK_PATH = Path(__file__).with_name(
    "s0_deployment_choice_v2_parent.v1.json")
REGISTRY_PATH = SERVER / "shengji" / "ai" / "registry.py"
SEED0 = 148_000_000
CLUSTERS = 16_384
SEED_HI = SEED0 + CLUSTERS - 1
NULL_OFFSET = 50_000_003
TEAMMATE_OFFSET = 500_000
OPPONENT_OFFSETS = (1_000_000, 1_500_000)
LABELS = {
    "adaptive": "mc-s0-adaptive",
    "report_lcb": "mc-s0-report-lcb",
    "current": "mc-strong",
    "current_null": "mc-strong-null-s0e-v2",
}
BINDING_RULE = (
    "Bind exactly one corrected S0 dependency-audit output SHA and its exact "
    "score-blind input-seal SHA. Authorize only complete=true, "
    "promotion_admissible=true, final_state=S0_COMPLETE_PROMOTE and decision "
    "PROMOTE mc-s0-adaptive. Corrected SELECT NONE, missing output, refusal or "
    "any identity drift permanently leaves S0e-v2 closed."
)


class ParentRefused(RuntimeError):
    """Corrected terminal S0 does not authorize a downstream experiment."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: os.PathLike | str) -> str:
    return sha256_bytes(DEPENDENCY.read_regular_bytes(Path(path)))


def stable_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def is_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError as exc:
        raise ParentRefused(f"authority path is outside repository: {path}") \
            from exc


def file_commits(path: Path) -> list[str]:
    output = git("log", "--follow", "--format=%H", "--", _relative(path))
    return [line for line in output.splitlines() if line]


def git_blob(commit: str, path: Path) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{commit}:{_relative(path)}"], cwd=ROOT,
        capture_output=True,
    )
    if result.returncode:
        raise ParentRefused(f"cannot reopen {_relative(path)} at {commit}")
    return result.stdout


def git_is_ancestor(ancestor: str, descendant: str) -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=ROOT,
    ).returncode == 0


def _untracked(path: Path) -> bool:
    return git("status", "--porcelain", "--", _relative(path)).startswith("?? ")


def load_json(path: Path, description: str) -> dict:
    try:
        value = json.loads(DEPENDENCY.read_regular_bytes(path))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError,
            DEPENDENCY.AuditRefused) as exc:
        raise ParentRefused(f"{description} unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise ParentRefused(f"{description} is not a JSON object")
    return value


def load_freeze() -> dict:
    value = load_json(FREEZE_PATH, "S0e-v2 parent freeze")
    expected = {
        "schema", "script_sha256", "binding_digest",
        "dependency_script_sha256", "dependency_freeze_sha256",
        "registry_sha256", "evidence_root",
    }
    if set(value) != expected or value.get("schema") != FREEZE_SCHEMA:
        raise ParentRefused("S0e-v2 parent freeze schema drift")
    return value


def load_lock() -> dict:
    value = load_json(LOCK_PATH, "S0e-v2 parent lock")
    expected = {
        "schema", "transition", "authorized", "dependency_audit_sha256",
        "input_seal_sha256", "input_set_sha256", "final_state",
        "final_production_decision", "freeze_sha256", "binding_rule",
    }
    if set(value) != expected or value.get("schema") != SCHEMA:
        raise ParentRefused("S0e-v2 parent-lock schema drift")
    return value


def freeze_problems() -> list[str]:
    problems = []
    for path in (Path(__file__), FREEZE_PATH):
        commits = file_commits(path)
        if not commits:
            if _untracked(Path(__file__)) and _untracked(FREEZE_PATH) \
                    and _untracked(LOCK_PATH):
                continue
            problems.append(f"{path.name}: no Git introduction")
            continue
        if len(commits) != 1:
            problems.append(f"{path.name}: changed after frozen introduction")
            continue
        if DEPENDENCY.read_regular_bytes(path) != git_blob(commits[0], path):
            problems.append(f"{path.name}: differs from Git introduction")
    try:
        frozen = load_freeze()
    except ParentRefused as exc:
        problems.append(str(exc))
        return sorted(set(problems))
    expected = {
        "script_sha256": sha256(__file__),
        "binding_digest": stable_digest(BINDING_RULE),
        "dependency_script_sha256": sha256(DEPENDENCY.__file__),
        "dependency_freeze_sha256": sha256(DEPENDENCY.FREEZE_PATH),
        "registry_sha256": sha256(REGISTRY_PATH),
        "evidence_root": str(DEPENDENCY.EVIDENCE_SERVER),
    }
    problems.extend(
        f"S0e-v2 parent freeze {key} drift"
        for key, wanted in expected.items() if frozen.get(key) != wanted
    )
    return sorted(set(problems))


def lock_problems(lock: dict) -> list[str]:
    problems = []
    if lock.get("binding_rule") != BINDING_RULE:
        problems.append("S0e-v2 binding rule drift")
    if lock.get("freeze_sha256") != sha256(FREEZE_PATH):
        problems.append("S0e-v2 lock does not bind its immutable freeze")
    transition = lock.get("transition")
    mutable = (
        "dependency_audit_sha256", "input_seal_sha256", "input_set_sha256",
        "final_state", "final_production_decision",
    )
    if transition == "PRETERMINAL":
        if lock.get("authorized") is not False or any(
                lock.get(key) is not None for key in mutable):
            problems.append("preterminal S0e-v2 lock is not empty and closed")
    elif transition == "TERMINAL":
        if not all(is_sha256(lock.get(key)) for key in mutable[:3]):
            problems.append("terminal S0e-v2 lock lacks exact hashes")
        state = lock.get("final_state")
        decision = lock.get("final_production_decision")
        if state == "S0_COMPLETE_PROMOTE":
            if (lock.get("authorized") is not True
                    or decision != "PROMOTE mc-s0-adaptive"):
                problems.append("PROMOTE S0e-v2 lock is not exactly authorized")
        elif state == "S0_COMPLETE_SELECT_NONE":
            if (lock.get("authorized") is not False
                    or decision != "SELECT NONE; production remains mc-strong"):
                problems.append("SELECT-NONE S0e-v2 lock is not permanently closed")
        else:
            problems.append(f"unregistered corrected S0 state: {state!r}")
    else:
        problems.append(f"unregistered S0e-v2 transition: {transition!r}")
    return problems


def transition_problems(lock: dict) -> list[str]:
    commits = file_commits(LOCK_PATH)
    if not commits:
        if (_untracked(Path(__file__)) and _untracked(FREEZE_PATH)
                and _untracked(LOCK_PATH)
                and lock.get("transition") == "PRETERMINAL"):
            return []
        return ["S0e-v2 parent lock has no Git introduction"]
    if len(commits) not in (1, 2):
        return ["S0e-v2 parent lock has more than one terminal transition"]
    try:
        initial = json.loads(git_blob(commits[-1], LOCK_PATH))
    except (UnicodeDecodeError, json.JSONDecodeError, ParentRefused) as exc:
        return [f"S0e-v2 initial lock cannot be reopened: {exc}"]
    immutable = {"schema", "freeze_sha256", "binding_rule"}
    if (not isinstance(initial, dict) or set(initial) != set(lock)
            or any(initial.get(key) != lock.get(key) for key in immutable)):
        return ["S0e-v2 parent immutable lock fields changed"]
    if (initial.get("transition") != "PRETERMINAL"
            or initial.get("authorized") is not False
            or any(initial.get(key) is not None for key in (
                "dependency_audit_sha256", "input_seal_sha256",
                "input_set_sha256", "final_state",
                "final_production_decision"))):
        return ["S0e-v2 Git introduction was not preterminal and closed"]
    if len(commits) == 1:
        if lock != initial:
            return ["uncommitted S0e-v2 parent transition is forbidden"]
    else:
        try:
            latest = git_blob(commits[0], LOCK_PATH)
            current = DEPENDENCY.read_regular_bytes(LOCK_PATH)
        except (OSError, DEPENDENCY.AuditRefused, ParentRefused) as exc:
            return [f"S0e-v2 terminal lock cannot be reopened: {exc}"]
        if current != latest:
            return ["S0e-v2 terminal lock differs from latest Git transition"]
        if lock.get("transition") != "TERMINAL":
            return ["committed S0e-v2 parent transition is not terminal"]
    return []


def require_clean_pushed_introduced(*, terminal: bool) -> str:
    """Refuse authority use until its exact Git phase is clean and pushed."""
    dirty = git("status", "--porcelain")
    if dirty:
        raise ParentRefused(f"S0e-v2 parent checkout is dirty: {dirty}")
    head = git("rev-parse", "HEAD")
    if not git_is_ancestor(head, "origin/main"):
        raise ParentRefused(
            f"S0e-v2 parent HEAD {head} is not pushed on origin/main")
    expected_counts = {
        Path(__file__): 1,
        FREEZE_PATH: 1,
        LOCK_PATH: 2 if terminal else 1,
    }
    for path, expected in expected_counts.items():
        commits = file_commits(path)
        if len(commits) != expected:
            raise ParentRefused(
                f"{path.name}: expected {expected} pushed Git "
                f"introduction(s), found {len(commits)}")
        try:
            current = DEPENDENCY.read_regular_bytes(path)
            committed = git_blob(commits[0], path)
        except (OSError, DEPENDENCY.AuditRefused, ParentRefused) as exc:
            raise ParentRefused(
                f"{path.name}: cannot reopen pushed authority: {exc}") \
                from exc
        if current != committed:
            raise ParentRefused(
                f"{path.name}: current bytes differ from latest Git commit")
    return head


def effective_streams(label: str, seed: int) -> tuple[int, ...]:
    shift = NULL_OFFSET if label == "current_null" else 0
    return (
        seed + shift,
        seed + TEAMMATE_OFFSET + shift,
        seed + OPPONENT_OFFSETS[0],
        seed + OPPONENT_OFFSETS[1],
    )


def stream_witness() -> dict:
    owners: dict[int, set[int]] = {}
    for seed in range(SEED0, SEED_HI + 1):
        for label in LABELS:
            for stream in effective_streams(label, seed):
                owners.setdefault(stream, set()).add(seed)
    cross = {stream: sorted(seeds) for stream, seeds in owners.items()
             if len(seeds) > 1}
    return {
        "seed0": SEED0,
        "seed_hi": SEED_HI,
        "clusters": CLUSTERS,
        "null_offset": NULL_OFFSET,
        "cross_seed_collision_count": len(cross),
        "cross_seed_collisions": cross,
    }


def protocol_problems() -> list[str]:
    problems = freeze_problems()
    try:
        lock = load_lock()
    except ParentRefused as exc:
        problems.append(str(exc))
        return sorted(set(problems))
    problems += lock_problems(lock)
    problems += transition_problems(lock)
    if (SEED0 != 148_000_000 or CLUSTERS != 16_384
            or SEED_HI != 148_016_383 or NULL_OFFSET != 50_000_003):
        problems.append("S0e-v2 population/null geometry drift")
    witness = stream_witness()
    if witness["cross_seed_collision_count"] != 0:
        problems.append("S0e-v2 retains a cross-seed RNG collision")
    try:
        current = make_bot(LABELS["current"], seed=7)
        null = make_bot(LABELS["current_null"], seed=7)
        current_contract = {
            key: getattr(current, key) for key in dir(current)
            if key.isupper() and key != "NULL_SEED_OFFSET"
            and isinstance(getattr(current, key), (bool, int, float, str,
                                                   type(None)))
        }
        null_contract = {
            key: getattr(null, key) for key in dir(null)
            if key.isupper() and key != "NULL_SEED_OFFSET"
            and isinstance(getattr(null, key), (bool, int, float, str,
                                                type(None)))
        }
        if current_contract != null_contract:
            problems.append("S0e-v2 current-null search contract differs")
        if getattr(null, "NULL_SEED_OFFSET", None) != NULL_OFFSET:
            problems.append("S0e-v2 null policy offset differs")
        if null.rng.getstate() == current.rng.getstate():
            problems.append("S0e-v2 current-null RNG is not shifted")
        ballots = arm_ballots(LABELS.values())
        if len(set(ballots.values())) != 1:
            problems.append("S0e-v2 policy ballots differ")
    except Exception as exc:
        problems.append(f"S0e-v2 policy preflight failed: {exc}")
    return sorted(set(problems))


def _derive_from_artifacts() -> dict:
    """Reopen exact corrected bytes and derive their only lock payload."""
    try:
        dependency_head_before = DEPENDENCY.require_runtime()
    except DEPENDENCY.AuditRefused as exc:
        raise ParentRefused(
            f"corrected S0 dependency runtime refused: {exc}") from exc
    audit_bytes = DEPENDENCY.read_regular_bytes(DEPENDENCY.OUTPUT)
    seal_bytes = DEPENDENCY.read_regular_bytes(DEPENDENCY.SEAL)
    try:
        audit = json.loads(audit_bytes)
        seal = json.loads(seal_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ParentRefused(f"corrected S0 authority is unreadable: {exc}") \
            from exc
    if not isinstance(audit, dict) or not isinstance(seal, dict):
        raise ParentRefused("corrected S0 authority is not JSON objects")
    audit_sha = sha256_bytes(audit_bytes)
    seal_sha = sha256_bytes(seal_bytes)
    try:
        verified_seal = DEPENDENCY.load_and_verify_seal(
            audit.get("git_sha"), expected_sha256=seal_sha)
        seal_attempt_bytes = DEPENDENCY.read_regular_bytes(
            DEPENDENCY.SEAL_ATTEMPT)
        evaluation_attempt_bytes = DEPENDENCY.read_regular_bytes(
            DEPENDENCY.EVALUATE_ATTEMPT)
        evaluation_attempt = json.loads(evaluation_attempt_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError,
            DEPENDENCY.AuditRefused) as exc:
        raise ParentRefused(
            f"corrected S0 seal/attempt cannot be reopened: {exc}") from exc
    expected_attempt_keys = {
        "schema", "action", "git_sha", "selection_digest",
        "freeze_sha256", "input_seal_path", "input_seal_sha256",
        "started_unix_ns", "outcomes_parsed",
    }
    if not isinstance(evaluation_attempt, dict) \
            or set(evaluation_attempt) != expected_attempt_keys:
        raise ParentRefused("corrected S0 evaluation-attempt schema drift")
    if verified_seal.get("seal_attempt_sha256") != \
            sha256_bytes(seal_attempt_bytes):
        raise ParentRefused("corrected S0 seal-attempt digest drift")
    state = audit.get("final_state")
    decision = audit.get("final_production_decision")
    promoted = state == "S0_COMPLETE_PROMOTE"
    expected_decision = (
        "PROMOTE mc-s0-adaptive" if promoted
        else "SELECT NONE; production remains mc-strong")
    checks = (
        audit.get("schema") == DEPENDENCY.SCHEMA,
        audit.get("complete") is True,
        audit.get("selection_digest") ==
            DEPENDENCY.stable_digest(DEPENDENCY.SELECTION_RULE),
        audit.get("git_sha") == evaluation_attempt.get("git_sha"),
        audit.get("input_seal_path") == str(DEPENDENCY.SEAL),
        audit.get("input_seal_sha256") == seal_sha,
        audit.get("input_set_sha256") == verified_seal.get("input_set_sha256"),
        audit.get("evaluation_attempt_path") ==
            str(DEPENDENCY.EVALUATE_ATTEMPT),
        audit.get("evaluation_attempt_sha256") ==
            sha256_bytes(evaluation_attempt_bytes),
        seal.get("schema") == DEPENDENCY.SEAL_SCHEMA,
        seal.get("complete") is True,
        seal.get("outcomes_parsed") is False,
        seal == verified_seal,
        evaluation_attempt.get("schema") == DEPENDENCY.ATTEMPT_SCHEMA,
        evaluation_attempt.get("action") == "evaluate",
        evaluation_attempt.get("selection_digest") ==
            DEPENDENCY.stable_digest(DEPENDENCY.SELECTION_RULE),
        evaluation_attempt.get("freeze_sha256") ==
            sha256(DEPENDENCY.FREEZE_PATH),
        evaluation_attempt.get("input_seal_path") == str(DEPENDENCY.SEAL),
        evaluation_attempt.get("input_seal_sha256") == seal_sha,
        evaluation_attempt.get("outcomes_parsed") is False,
        state in {"S0_COMPLETE_PROMOTE", "S0_COMPLETE_SELECT_NONE"},
        decision == expected_decision,
        audit.get("promotion_admissible") is promoted,
        (audit.get("original_terminal_state") == "S0_COMPLETE_PROMOTE"
         if promoted else audit.get("original_terminal_state") in {
             "S0_COMPLETE_PROMOTE", "S0_COMPLETE_SELECT_NONE"}),
        audit.get("automatic_deployment") is False,
        audit.get("retry_or_extension_authorized") is False,
    )
    if not all(checks):
        raise ParentRefused("corrected S0 output/seal contract drift")
    if promoted and audit.get("dependency_repair_pass") is not True:
        raise ParentRefused("corrected PROMOTE lacks dependency-repair pass")
    try:
        blobs = DEPENDENCY.read_sealed_inputs(verified_seal)
        terminal, packet_text, aggregate_sha = \
            DEPENDENCY.verify_original_terminal(blobs)
        recomputed = DEPENDENCY.run(
            audit["git_sha"], verified_seal, blobs, terminal,
            packet_text, aggregate_sha,
        )
        stable_inputs = DEPENDENCY.read_sealed_inputs(verified_seal)
        stable_output = DEPENDENCY.read_regular_bytes(DEPENDENCY.OUTPUT)
        stable_seal = DEPENDENCY.read_regular_bytes(DEPENDENCY.SEAL)
        stable_seal_attempt = DEPENDENCY.read_regular_bytes(
            DEPENDENCY.SEAL_ATTEMPT)
        stable_attempt = DEPENDENCY.read_regular_bytes(
            DEPENDENCY.EVALUATE_ATTEMPT)
        dependency_head_after = DEPENDENCY.require_runtime()
    except (KeyError, DEPENDENCY.AuditRefused, RuntimeError) as exc:
        raise ParentRefused(
            f"corrected S0 result cannot be reproduced: {exc}") from exc
    if audit != recomputed:
        raise ParentRefused(
            "published corrected S0 result differs from sealed recomputation")
    if (stable_inputs != blobs or stable_output != audit_bytes
            or stable_seal != seal_bytes
            or stable_seal_attempt != seal_attempt_bytes
            or stable_attempt != evaluation_attempt_bytes):
        raise ParentRefused(
            "corrected S0 authority changed during parent derivation")
    if dependency_head_after != dependency_head_before:
        raise ParentRefused(
            "corrected S0 dependency runtime changed during parent derivation")
    return {
        "schema": SCHEMA,
        "transition": "TERMINAL",
        "authorized": promoted,
        "dependency_audit_sha256": audit_sha,
        "input_seal_sha256": seal_sha,
        "input_set_sha256": audit["input_set_sha256"],
        "final_state": state,
        "final_production_decision": decision,
        "freeze_sha256": sha256(FREEZE_PATH),
        "binding_rule": BINDING_RULE,
    }


def derive_terminal_lock() -> dict:
    """Derive the one admissible Git transition from exact corrected bytes."""
    require_clean_pushed_introduced(terminal=False)
    problems = protocol_problems()
    if problems:
        raise ParentRefused("S0e-v2 parent protocol: " + "; ".join(problems))
    lock = load_lock()
    if lock.get("transition") != "PRETERMINAL":
        raise ParentRefused("S0e-v2 parent is already terminal")
    return _derive_from_artifacts()


def verify_terminal_lock(*, require_authorized: bool = True) -> dict:
    require_clean_pushed_introduced(terminal=True)
    problems = protocol_problems()
    if problems:
        raise ParentRefused("S0e-v2 parent protocol: " + "; ".join(problems))
    lock = load_lock()
    if lock.get("transition") != "TERMINAL":
        raise ParentRefused("corrected S0e-v2 parent is still preterminal")
    derived = _derive_from_artifacts()
    if derived != lock:
        raise ParentRefused("S0e-v2 lock differs from corrected authority")
    if require_authorized and lock.get("authorized") is not True:
        raise ParentRefused("corrected SELECT NONE permanently closes S0e-v2")
    return lock


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("render", "verify"))
    args = parser.parse_args()
    result = (derive_terminal_lock() if args.command == "render"
              else verify_terminal_lock(require_authorized=False))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (ParentRefused, DEPENDENCY.AuditRefused) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc

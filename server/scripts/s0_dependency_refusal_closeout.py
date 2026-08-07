#!/usr/bin/env python3
"""Outcome-blind terminal closeout for the burned S0 dependency evaluation.

The registered dependency evaluator created its durable one-shot attempt and
then refused before decoding an outcome because the keepalive supervisor had
overwritten its terminal state.  Its own contract forbids deleting that
attempt, retrying, extending the population, or repairing the result after an
outcome is known.

This closeout therefore does exactly one conservative thing: it reopens only
the score-blind seal and attempt receipts, proves all 18 sealed input *bytes*
are unchanged without decoding them, binds the exact nonterminal supervisor
refusal, and permanently closes S0 as SELECT NONE.  It cannot emit PROMOTE and
it cannot authorize production or another evaluation of this population.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "server"
SCRIPTS = SERVER / "scripts"
sys.path.insert(0, str(SCRIPTS))

import s0_dependency_audit as AUDIT  # noqa: E402
import s0_deployment_choice_v2_parent as PARENT  # noqa: E402


SCHEMA = "s0-dependency-evaluation-refusal-closeout-v1"
ATTEMPT_SCHEMA = "s0-dependency-refusal-closeout-attempt-v1"
SEALED_HEAD = "29529291271f6f3b51e56557371d74abca9affa9"
EXPECTED_SEAL_SHA256 = (
    "b6a48e9dbabad008a15e3ace0b19fecff9304849435b5d9c4f69da30ddc29d10"
)
EXPECTED_SEAL_ATTEMPT_SHA256 = (
    "3da45785a7b7032785573bae4f1ba2e3b740f726d29e5e6efb46021511e3c1f8"
)
EXPECTED_EVALUATION_ATTEMPT_SHA256 = (
    "97d3b22f656f9b43a8b34acf4085896706bb40b48c88f3b095cb08592725f9c5"
)
EXPECTED_INPUT_SET_SHA256 = (
    "14a74a76b14bc6fd731f3de5cf332ee50060c18f7baba1ad77614766e35b1361"
)
EXPECTED_BLOCKED_STATE_SHA256 = (
    "ed80b0e18c5d843354271fb17554cda447b85f103a4def23f74b41c2bfcff378"
)
STATE = AUDIT.LOGS / "s0_pipeline_supervisor.state.json"
ATTEMPT = AUDIT.LOGS / "s0c-dependency-refusal-closeout-v1.attempt.json"
OUTPUT = AUDIT.LOGS / "s0c-dependency-refusal-closeout-v1.json"
FINAL_STATE = "S0_COMPLETE_SELECT_NONE"
# This exact phrase is part of the already-frozen S0e-v2 parent contract.  It
# records what formal S0 was allowed to authorize; it is not a claim about a
# separate, manually approved production deployment made after that freeze.
FINAL_DECISION = "SELECT NONE; production remains mc-strong"
FAILURE_REASON = (
    "The frozen one-shot dependency evaluation refused before outcome "
    "decoding because its independently regenerated terminal packet consulted "
    "a keepalive-overwritten nonterminal supervisor state. The durable "
    "evaluation attempt is nonretryable, so this population cannot authorize "
    "promotion."
)


class CloseoutRefused(RuntimeError):
    """The burned evaluation cannot support even conservative closeout."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: os.PathLike | str) -> str:
    return sha256_bytes(AUDIT.read_regular_bytes(Path(path)))


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def git_is_ancestor(ancestor: str, descendant: str) -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=ROOT,
    ).returncode == 0


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError as exc:
        raise CloseoutRefused(f"path is outside repository: {path}") from exc


def _file_commits(path: Path) -> list[str]:
    return [line for line in git(
        "log", "--follow", "--format=%H", "--", _relative(path)
    ).splitlines() if line]


def _git_blob(commit: str, path: Path) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{_relative(path)}"],
        cwd=ROOT, capture_output=True,
    )
    if completed.returncode:
        raise CloseoutRefused(f"cannot reopen {_relative(path)} at {commit}")
    return completed.stdout


def _load_json(path: Path, description: str) -> dict:
    try:
        value = json.loads(AUDIT.read_regular_bytes(path))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError,
            AUDIT.AuditRefused) as exc:
        raise CloseoutRefused(f"{description} unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise CloseoutRefused(f"{description} is not a JSON object")
    return value


def require_runtime(*, terminal_lock: bool) -> str:
    """Require one pushed closeout introduction and the exact parent phase."""
    dirty = git("status", "--porcelain")
    if dirty:
        raise CloseoutRefused(f"refusal-closeout checkout is dirty: {dirty}")
    head = git("rev-parse", "HEAD")
    if not git_is_ancestor(head, "origin/main"):
        raise CloseoutRefused(f"closeout HEAD {head} is not pushed")
    if not git_is_ancestor(SEALED_HEAD, head):
        raise CloseoutRefused("closeout does not descend from score-blind seal")
    commits = _file_commits(Path(__file__))
    if len(commits) != 1:
        raise CloseoutRefused(
            f"refusal closeout must have one Git introduction, found {len(commits)}"
        )
    if (AUDIT.read_regular_bytes(Path(__file__))
            != _git_blob(commits[0], Path(__file__))):
        raise CloseoutRefused("refusal closeout differs from Git introduction")
    try:
        PARENT.require_clean_pushed_introduced(terminal=terminal_lock)
    except PARENT.ParentRefused as exc:
        raise CloseoutRefused(f"S0 parent authority refused: {exc}") from exc
    problems = PARENT.protocol_problems()
    if problems:
        raise CloseoutRefused("S0 parent protocol: " + "; ".join(problems))
    return head


def validate_burned_authority() -> dict:
    """Validate receipts and sealed bytes without decoding any outcome input."""
    exact = (
        (AUDIT.SEAL, EXPECTED_SEAL_SHA256, "input seal"),
        (AUDIT.SEAL_ATTEMPT, EXPECTED_SEAL_ATTEMPT_SHA256, "seal attempt"),
        (AUDIT.EVALUATE_ATTEMPT, EXPECTED_EVALUATION_ATTEMPT_SHA256,
         "evaluation attempt"),
        (STATE, EXPECTED_BLOCKED_STATE_SHA256, "blocked supervisor state"),
    )
    for path, wanted, description in exact:
        if sha256(path) != wanted:
            raise CloseoutRefused(f"{description} digest drift")

    try:
        seal = AUDIT.load_and_verify_seal(
            SEALED_HEAD, expected_sha256=EXPECTED_SEAL_SHA256)
    except AUDIT.AuditRefused as exc:
        raise CloseoutRefused(f"score-blind seal refused: {exc}") from exc
    if (seal.get("input_set_sha256") != EXPECTED_INPUT_SET_SHA256
            or seal.get("outcomes_parsed") is not False
            or seal.get("canonical_input_count") != 18):
        raise CloseoutRefused("score-blind seal identity drift")
    # Hash canonical bytes twice through the frozen reader. Never call
    # read_sealed_inputs: that would materialize outcome-bearing payloads.
    first = AUDIT.snapshot_inputs(AUDIT.canonical_input_paths())
    second = AUDIT.snapshot_inputs(AUDIT.canonical_input_paths())
    if first != seal.get("inputs") or second != first:
        raise CloseoutRefused("sealed canonical inputs changed")

    evaluation = _load_json(
        AUDIT.EVALUATE_ATTEMPT, "dependency evaluation attempt")
    expected_evaluation_keys = {
        "schema", "action", "git_sha", "selection_digest",
        "freeze_sha256", "input_seal_path", "input_seal_sha256",
        "started_unix_ns", "outcomes_parsed",
    }
    if set(evaluation) != expected_evaluation_keys:
        raise CloseoutRefused("dependency evaluation-attempt schema drift")
    expected_evaluation = {
        "schema": AUDIT.ATTEMPT_SCHEMA,
        "action": "evaluate",
        "git_sha": SEALED_HEAD,
        "selection_digest": AUDIT.stable_digest(AUDIT.SELECTION_RULE),
        "freeze_sha256": sha256(AUDIT.FREEZE_PATH),
        "input_seal_path": str(AUDIT.SEAL),
        "input_seal_sha256": EXPECTED_SEAL_SHA256,
        "outcomes_parsed": False,
    }
    drift = {key: {"actual": evaluation.get(key), "expected": value}
             for key, value in expected_evaluation.items()
             if evaluation.get(key) != value}
    if drift or type(evaluation.get("started_unix_ns")) is not int:
        raise CloseoutRefused(
            f"dependency evaluation-attempt identity drift: {drift}")

    state = _load_json(STATE, "blocked supervisor state")
    if (state.get("status") != "BLOCKED"
            or state.get("error") !=
            "RuntimeError: packet stdout differs from durable packet"):
        raise CloseoutRefused("registered pre-outcome refusal state drift")
    if AUDIT.OUTPUT.exists() or Path(str(AUDIT.OUTPUT) + ".partial").exists():
        raise CloseoutRefused(
            "dependency evaluator unexpectedly published a decision")
    return {"seal": seal, "evaluation": evaluation, "state": state}


def _closeout_attempt(head: str) -> dict:
    return {
        "schema": ATTEMPT_SCHEMA,
        "action": "close_burned_evaluation_select_none",
        "git_sha": head,
        "input_seal_sha256": EXPECTED_SEAL_SHA256,
        "input_set_sha256": EXPECTED_INPUT_SET_SHA256,
        "evaluation_attempt_sha256": EXPECTED_EVALUATION_ATTEMPT_SHA256,
        "blocked_state_sha256": EXPECTED_BLOCKED_STATE_SHA256,
        "started_unix_ns": time.time_ns(),
        "outcomes_parsed": False,
    }


def _result(head: str, attempt_sha256: str) -> dict:
    return {
        "schema": SCHEMA,
        "complete": True,
        "git_sha": head,
        "input_seal_path": str(AUDIT.SEAL),
        "input_seal_sha256": EXPECTED_SEAL_SHA256,
        "input_set_sha256": EXPECTED_INPUT_SET_SHA256,
        "evaluation_attempt_path": str(AUDIT.EVALUATE_ATTEMPT),
        "evaluation_attempt_sha256": EXPECTED_EVALUATION_ATTEMPT_SHA256,
        "blocked_state_path": str(STATE),
        "blocked_state_sha256": EXPECTED_BLOCKED_STATE_SHA256,
        "closeout_attempt_path": str(ATTEMPT),
        "closeout_attempt_sha256": attempt_sha256,
        "outcomes_parsed": False,
        "outcome_records_decoded": False,
        "original_dependency_output_absent": True,
        "dependency_repair_pass": None,
        "promotion_admissible": False,
        "final_state": FINAL_STATE,
        "final_production_decision": FINAL_DECISION,
        "automatic_deployment": False,
        "retry_or_extension_authorized": False,
        "claim_boundary": (
            "Formal S0 evidence authority only. A separately approved manual "
            "production policy is outside this artifact."
        ),
        "failure_reason": FAILURE_REASON,
    }


def close() -> dict:
    head = require_runtime(terminal_lock=False)
    existing = [path for path in (
        ATTEMPT, OUTPUT, Path(str(OUTPUT) + ".partial"))
        if path.exists() or path.is_symlink()]
    if existing:
        raise CloseoutRefused(f"refusal closeout already attempted: {existing}")
    AUDIT.write_attempt(ATTEMPT, _closeout_attempt(head))
    authority = validate_burned_authority()
    if authority["evaluation"].get("outcomes_parsed") is not False:
        raise CloseoutRefused("evaluation attempt is not score blind")
    result = _result(head, sha256(ATTEMPT))
    AUDIT.write_exclusive(OUTPUT, result)
    return result


def validate_output() -> tuple[dict, str]:
    validate_burned_authority()
    output = _load_json(OUTPUT, "refusal closeout")
    attempt = _load_json(ATTEMPT, "refusal closeout attempt")
    expected_attempt_keys = set(_closeout_attempt(output.get("git_sha", "")))
    if set(attempt) != expected_attempt_keys:
        raise CloseoutRefused("refusal closeout-attempt schema drift")
    stable_attempt = dict(attempt)
    stable_attempt.pop("started_unix_ns", None)
    wanted_attempt = _closeout_attempt(output.get("git_sha", ""))
    wanted_attempt.pop("started_unix_ns", None)
    if (stable_attempt != wanted_attempt
            or type(attempt.get("started_unix_ns")) is not int):
        raise CloseoutRefused("refusal closeout-attempt identity drift")
    expected = _result(output.get("git_sha", ""), sha256(ATTEMPT))
    if output != expected:
        raise CloseoutRefused("published refusal closeout identity drift")
    head = git("rev-parse", "HEAD")
    if not git_is_ancestor(output["git_sha"], head):
        raise CloseoutRefused("refusal closeout Git identity is not an ancestor")
    return output, sha256(OUTPUT)


def terminal_lock(output: dict, output_sha256: str) -> dict:
    lock = PARENT.load_lock()
    if lock.get("transition") != "PRETERMINAL":
        raise CloseoutRefused("S0 parent lock is not preterminal")
    return {
        **lock,
        "transition": "TERMINAL",
        "authorized": False,
        "dependency_audit_sha256": output_sha256,
        "input_seal_sha256": output["input_seal_sha256"],
        "input_set_sha256": output["input_set_sha256"],
        "final_state": FINAL_STATE,
        "final_production_decision": FINAL_DECISION,
    }


def render_lock() -> dict:
    require_runtime(terminal_lock=False)
    output, output_sha256 = validate_output()
    return terminal_lock(output, output_sha256)


def verify() -> dict:
    require_runtime(terminal_lock=True)
    output, output_sha256 = validate_output()
    lock = PARENT.load_lock()
    # Reconstruct the terminal payload from the immutable introduction rather
    # than calling terminal_lock(), which correctly requires PRETERMINAL.
    initial = json.loads(PARENT.git_blob(
        PARENT.file_commits(PARENT.LOCK_PATH)[-1], PARENT.LOCK_PATH))
    expected = {
        **initial,
        "transition": "TERMINAL",
        "authorized": False,
        "dependency_audit_sha256": output_sha256,
        "input_seal_sha256": output["input_seal_sha256"],
        "input_set_sha256": output["input_set_sha256"],
        "final_state": FINAL_STATE,
        "final_production_decision": FINAL_DECISION,
    }
    if lock != expected:
        raise CloseoutRefused("terminal S0 parent lock differs from refusal")
    return lock


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("close", "render-lock", "verify"))
    args = parser.parse_args()
    result = (close() if args.command == "close" else
              render_lock() if args.command == "render-lock" else verify())
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (CloseoutRefused, AUDIT.AuditRefused,
            PARENT.ParentRefused) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc

#!/usr/bin/env python3
"""Turn the sealed Teacher audit verdict into one bounded next-work packet.

This adapter is intentionally not a Stage-C launcher.  It reopens the exact
terminal audit gate and the supervisor's final JSONL, checks that they describe
the same one-shot attempt, then emits one of two plans that were fixed before
the outcome was known:

* PASS -> design and independently review a fresh hard-tail Stage-C packet;
* FAIL/INCONCLUSIVE -> diagnose the existing audit only, with no new labels.

Both branches deny compute, bulk labeling, training, promotion, and retry.  A
later reviewed experiment packet must name all executable geometry before work
can start.  This keeps a favorable terminal result from silently becoming an
authorization to scale the ordinary-state labeler.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


SCHEMA = "teacher-v3-terminal-adapter-v2"
AUDIT_GATE_SCHEMA = "teacher-v1-champion-audit-gate-v2"
SUPERVISOR_SCHEMA = "teacher-v1-champion-audit-supervisor-v2"
AUDIT_ID = "teacher-v3-report-lcb-audit-v2"
RUN_ID = "teacher-v3-report-lcb-audit-v3-mini-149m"
AUDIT_GIT = "f78e9047b50e7e254c76f8a1ff9490bc9aa75700"
AUDIT_SCRIPT_SHA256 = (
    "0a79aa6c3dc2f2bfef81e035bead8ac22974c0c27561908a60a38cd1edbf413a"
)
SUPERVISOR_SCRIPT_SHA256 = (
    "07284fc0c99e678df0a1d02f8aabc06d7fa8d38837aa46099110ff908ae2f47f"
)
PREPARER_SCRIPT_SHA256 = (
    "c6f24b58eabe0ffaccb1ce38f6724100133075f4ebda0851e5615adba2bc4346"
)
RECEIPT_SHA256 = (
    "e293858c728437d6016a3f02a62a355c38a37a6028ad0d83e49423e1caf4a10d"
)
PREPARATION_SHA256 = (
    "83892930fa8e7e8148960511ef0a87c3becbe77a87eaebf3c912458863644c39"
)
RECEIPT_PATH = (
    "/Users/jerryyu/Projects/shengji-teacher-audit-v3-mini/server/"
    "runs/logs/teacher-v1-entry-149m-v5/champion_audit_receipt_v2.json"
)
GATE_PATH = (
    "/Users/jerryyu/Projects/shengji-teacher-audit-v3-mini/server/"
    "runs/logs/teacher-v1-entry-149m-v5/champion_audit_gate_v2.json"
)
SUPERVISOR_PROGRESS_PATH = (
    "/Users/jerryyu/Projects/shengji-teacher-audit-v3-mini/server/"
    "runs/logs/teacher-v1-entry-149m-v5/"
    "champion_audit_supervisor_v2.jsonl"
)
OUTPUT_PATH = (
    "/Users/jerryyu/Projects/shengji-teacher-audit-v3-mini/server/"
    "runs/logs/teacher-v1-entry-149m-v5/teacher_terminal_adapter_v2.json"
)
COMPILED_ENGINE_SHA256 = (
    "ef7c161829c607aad790e949e0a0bae7e04d8a3be7aea51b80d5108a1f566b4d"
)
EXPECTED_HOST = "Jerrys-Mac-mini.local"
EXPECTED_PYTHON = "3.14.6"
STAGE_B_STATE_SHA256 = (
    "90956da86f4f03074a1b4dc2d7198a3da5958470b733eacd104e066c523b4dc6"
)
STAGE_B_GATE_SHA256 = (
    "f607b48986aaa8b05194f88e8638540bc5c9360f09f3c28a7565d8d8cac89694"
)
CONSUMED_AUDIT_STATE_SHA256 = (
    "d04d1c0fa507bab680da4d53eeb72325a97c8ca058aac0d01c16dfdcf44f7a34"
)
AUDIT_STATE_SHA256 = (
    "82da0fd8a2f362dd2a8340847ccb7caaba1c2d58840cd0809d2353751999d94c"
)
PARENT_NAMESPACE = "runs/logs/teacher-v1-entry-149m-v3"
AUDIT_NAMESPACE = "runs/logs/teacher-v1-entry-149m-v5"
OUTPUT_NAME = "teacher_terminal_adapter_v2.json"
EXPECTED_FOLDS = {"champion_selection": 32, "champion_report": 32}
EXPECTED_ADMISSION = {
    "schema": "teacher-v3-champion-continuation-admission-v1",
    "accepted_worlds": {"selection": 30, "report": 300},
    "selection_attempt_cap": 1_200,
    "report_attempt_cap": 12_000,
    "allow_failed_determinization_retries": True,
    "require_full_accepted_dose": True,
    "refuse_attempt_cap_hit": True,
    "require_strict_voids": True,
    "score_failed_attempts": False,
    "counter_identity": "sample_attempts=accepted_worlds+failed_worlds",
}
EXPECTED_CONTINUATION = {
    "policy": "mc-s0-report-lcb",
    "selection_worlds": 30,
    "report_worlds": 300,
    "report_rule": "lcb",
    "report_alpha": 0.05,
    "report_min_gain": 0.0,
    "report_t_critical": 1.70,
    "require_exact_work": True,
    "adaptive_allocation": False,
    "random_allocation": False,
    "admission": EXPECTED_ADMISSION,
}


PASS_CONTRACT = {
    "packet_id": "teacher-v3-hard-tail-stage-c-design-v1",
    "decision": "DESIGN_HARD_TAIL_STAGE_C",
    "objective": (
        "Build counterfactual labels where the live champion is uncertain, "
        "using a stronger continuation on the hard tail rather than scaling "
        "ordinary cheap-label imitation."
    ),
    "fresh_namespace_required": True,
    "live_parent": {
        "policy": "mc-s0-report-lcb",
        "authenticator": "live-champion-parent-v1",
        "must_reopen_at_packet_freeze": True,
    },
    "state_contract_required": {
        "fresh_non_evaluation_deals": True,
        "one_state_per_deal": True,
        "known_evaluation_assets_excluded": True,
        "selection_and_report_folds_disjoint": True,
        "selection_outcomes_cannot_enter_report": True,
        "required_strata": [
            "phase_role_decision_representative",
            "cheap_vs_gold_or_champion_disagreement",
            "high_selection_se_or_low_margin",
            "late_ply_exact_eligible",
            "ordinary_random_anchor",
        ],
        "stratum_counts_and_seed_block_must_be_frozen_before_labels": True,
    },
    "label_routing_required": {
        "ordinary_anchor": "cheap_proxy_only_under_passed_audit_contract",
        "uncertainty_or_disagreement": "gold_report_lcb_or_deeper",
        "exact_eligible_late_ply": "information_set_legal_exact_late",
        "oracle_hidden_card_features_for_deployable_targets": False,
        "raw_candidate_tensor_preserved": True,
    },
    "separate_gates_required": [
        "hard_tail_regret_upper_bound",
        "ordinary_anchor_regret_upper_bound",
        "exact_work_and_zero_fallbacks",
        "proposal_recall_vs_same_budget_random_diversity",
    ],
    "model_work_authorized_only_after_teacher_gate": True,
    "next_authority": "AUTHORIZE_STAGE_C_PACKET_REVIEW",
}


NONPASS_CONTRACT = {
    "packet_id": "teacher-v3-audit-diagnostic-design-v1",
    "decision": "DIAGNOSE_EXISTING_AUDIT_ONLY",
    "objective": (
        "Name the smallest continuation or selection failure from frozen "
        "audit evidence before proposing another labeler."
    ),
    "allowed_inputs": [
        "terminal_gate",
        "eight_frozen_audit_shards",
        "frozen_cheap_and_n30_parent_choices",
    ],
    "required_cuts": [
        "all_64_vs_representative_48",
        "boundary_vs_uncertainty",
        "phase_role_decision",
        "cheap_choice_vs_n30_choice",
        "input_problem_vs_regret_failure",
    ],
    "new_states_authorized": False,
    "new_worlds_authorized": False,
    "same_recipe_extension_authorized": False,
    "next_authority": "AUTHORIZE_MINIMAL_TEACHER_REDESIGN_REVIEW",
}


class AdapterRefusal(RuntimeError):
    """The terminal evidence or publication boundary is not exact."""


@dataclass(frozen=True)
class Config:
    gate: Path
    expected_gate_sha256: str
    supervisor_progress: Path
    expected_supervisor_sha256: str
    expected_git: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def artifact_partial(path: Path) -> Path:
    return Path(str(path) + ".partial")


def is_regular_unlinked(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except FileNotFoundError:
        return False


def _canonical_path_problems(path: Path, expected: str, *,
                             allow_missing_leaf: bool = False) -> list[str]:
    """Require one lexical path whose complete parent chain has no symlink."""
    problems: list[str] = []
    expected_path = Path(expected)
    if path != expected_path:
        return [f"noncanonical path {path}; expected {expected_path}"]
    for component in reversed(expected_path.parents):
        try:
            mode = component.lstat().st_mode
        except FileNotFoundError:
            problems.append(f"missing canonical parent {component}")
            continue
        if stat.S_ISLNK(mode):
            problems.append(f"symlinked canonical parent {component}")
        elif not stat.S_ISDIR(mode):
            problems.append(f"non-directory canonical parent {component}")
    if os.path.lexists(expected_path):
        if stat.S_ISLNK(expected_path.lstat().st_mode):
            problems.append(f"symlinked canonical artifact {expected_path}")
    elif not allow_missing_leaf:
        problems.append(f"missing canonical artifact {expected_path}")
    return problems


def _artifact_problems(path: Path, expected_sha256: str) -> list[str]:
    problems: list[str] = []
    if not is_sha256(expected_sha256):
        problems.append(f"invalid expected SHA-256 for {path}")
    if not is_regular_unlinked(path):
        problems.append(f"missing/nonregular artifact {path}")
    elif is_sha256(expected_sha256) and sha256_file(path) != expected_sha256:
        problems.append(f"artifact SHA drift {path}")
    if os.path.lexists(artifact_partial(path)):
        problems.append(f"artifact partial exists {artifact_partial(path)}")
    return problems


def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise AdapterRefusal(f"cannot reopen JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AdapterRefusal(f"JSON root is not an object: {path}")
    return payload


def _load_jsonl(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        payloads = [json.loads(line) for line in lines if line.strip()]
    except (OSError, ValueError) as exc:
        raise AdapterRefusal(f"cannot reopen JSONL {path}: {exc}") from exc
    if not payloads or any(not isinstance(item, dict) for item in payloads):
        raise AdapterRefusal(f"JSONL has no exact object population: {path}")
    return payloads


def _gate_problems(gate: dict) -> list[str]:
    problems: list[str] = []
    verdict = gate.get("verdict")
    passed = verdict == "PASS"
    if (gate.get("schema") != AUDIT_GATE_SCHEMA
            or gate.get("audit_id") != AUDIT_ID
            or gate.get("complete") is not True
            or gate.get("terminal") is not True
            or gate.get("extension_authorized") is not False):
        problems.append("audit gate identity/terminal contract")
    if verdict not in {"PASS", "FAIL", "INCONCLUSIVE"}:
        problems.append("audit gate terminal verdict")
    if (gate.get("champion_fidelity_qualified") is not passed
            or gate.get("stage_c_authorized") is not passed):
        problems.append("audit gate verdict/authorization mismatch")
    if (gate.get("producer_run_id") != RUN_ID
            or gate.get("git") != AUDIT_GIT
            or gate.get("tree_dirty") is not False
            or gate.get("promotable") is not True
            or gate.get("host") != EXPECTED_HOST
            or gate.get("python") != EXPECTED_PYTHON
            or gate.get("fast_engine") is not True
            or gate.get("require_voids") is not True
            or gate.get("experimental_sampler_ballot_flags") != []):
        problems.append("audit gate execution identity")
    source_digests = gate.get("source_digests")
    if (not isinstance(source_digests, dict)
            or source_digests.get("audit_script") != AUDIT_SCRIPT_SHA256
            or source_digests.get("compiled_engine")
            != COMPILED_ENGINE_SHA256):
        problems.append("audit gate script identity")
    if gate.get("folds_contract") != EXPECTED_FOLDS:
        problems.append("audit gate fold contract")
    if gate.get("continuation_contract") != EXPECTED_CONTINUATION:
        problems.append("audit gate continuation contract")
    expected_bindings = {
        "stage_b_state_set": {
            "path": f"{PARENT_NAMESPACE}/stage_b_states.json",
            "sha256": STAGE_B_STATE_SHA256,
        },
        "stage_b_gate": {
            "path": f"{PARENT_NAMESPACE}/stage_b_gate_v2.json",
            "sha256": STAGE_B_GATE_SHA256,
        },
        "consumed_audit_state_set": {
            "path": (
                f"{AUDIT_NAMESPACE}/"
                "champion_audit_consumed_states_v1.json"),
            "sha256": CONSUMED_AUDIT_STATE_SHA256,
        },
        "audit_state_set": {
            "path": f"{AUDIT_NAMESPACE}/champion_audit_states_v2.json",
            "sha256": AUDIT_STATE_SHA256,
        },
    }
    for name, binding in expected_bindings.items():
        if gate.get(name) != binding:
            problems.append(f"audit gate {name} binding")
    receipt = gate.get("producer_receipt")
    if (not isinstance(receipt, dict)
            or set(receipt) != {"path", "sha256", "run_id", "nonce"}
            or receipt.get("path") != RECEIPT_PATH
            or receipt.get("sha256") != RECEIPT_SHA256
            or receipt.get("run_id") != RUN_ID
            or not is_sha256(receipt.get("nonce"))):
        problems.append("audit gate receipt binding")
    if gate.get("n_states") != 64:
        problems.append("audit gate state count")
    if not isinstance(gate.get("problems"), list):
        problems.append("audit gate problem population")
    elif passed and gate.get("problems"):
        problems.append("passing audit gate has problems")
    inputs = gate.get("inputs")
    if not isinstance(inputs, list) or len(inputs) != 8:
        problems.append("audit gate exact eight inputs")
    else:
        expected_fields = {"path", "sha256", "shard_index"}
        if any(not isinstance(item, dict)
               or set(item) != expected_fields for item in inputs):
            problems.append("audit gate input item schema")
        else:
            paths = [item["path"] for item in inputs]
            digests = [item["sha256"] for item in inputs]
            indices = [item["shard_index"] for item in inputs]
            if (any(not isinstance(path, str) or not path for path in paths)
                    or len(set(paths)) != 8):
                problems.append("audit gate input path population")
            if (any(not is_sha256(digest) for digest in digests)
                    or len(set(digests)) != 8):
                problems.append("audit gate input digest population")
            if indices != list(range(8)):
                problems.append("audit gate ordered shard population")
    for name in ("cheap_inputs", "n30_inputs"):
        items = gate.get(name)
        if (not isinstance(items, list) or len(items) != 8
                or [item.get("shard_index") for item in items
                    if isinstance(item, dict)] != list(range(8))
                or any(not isinstance(item, dict)
                       or not isinstance(item.get("path"), str)
                       or not is_sha256(item.get("sha256"))
                       for item in items)):
            problems.append(f"audit gate {name} population")
    return sorted(set(problems))


def _supervisor_problems(events: list[dict], gate: dict,
                         gate_sha256: str) -> list[str]:
    problems: list[str] = []
    if any(event.get("schema") != SUPERVISOR_SCHEMA for event in events):
        problems.append("supervisor event schema")
    admitted = [event for event in events
                if event.get("phase") == "supervisor"
                and event.get("status") == "admitted"]
    terminal = [event for event in events
                if event.get("phase") == "supervisor"
                and event.get("status") == "terminal"]
    if len(admitted) != 1:
        problems.append("supervisor exact admitted event")
    else:
        admitted_event = admitted[0]
        execution = admitted_event.get("execution_predeclaration")
        if (admitted_event.get("run_id") != RUN_ID
                or admitted_event.get("host") != EXPECTED_HOST
                or admitted_event.get("audit_git") != AUDIT_GIT
                or admitted_event.get("audit_script_sha256")
                != AUDIT_SCRIPT_SHA256
                or admitted_event.get("supervisor_sha256")
                != SUPERVISOR_SCRIPT_SHA256
                or admitted_event.get("receipt_sha256") != RECEIPT_SHA256
                or admitted_event.get("preparation_sha256")
                != PREPARATION_SHA256
                or admitted_event.get("preparer_sha256")
                != PREPARER_SCRIPT_SHA256
                or admitted_event.get("shard_count") != 8
                or admitted_event.get("selection_worlds") != 32
                or admitted_event.get("report_worlds") != 32
                or not isinstance(execution, dict)
                or execution.get("git") != AUDIT_GIT
                or execution.get("audit_script_sha256")
                != AUDIT_SCRIPT_SHA256):
            problems.append("supervisor admitted identity")
    if len(terminal) != 1 or events[-1] is not terminal[-1]:
        problems.append("supervisor exact final terminal event")
    else:
        event = terminal[0]
        expected_code = 0 if gate.get("verdict") == "PASS" else 4
        labels = event.get("label_sha256s")
        admitted_event = admitted[0] if len(admitted) == 1 else {}
        receipt = gate.get("producer_receipt")
        if (event.get("run_id") != RUN_ID
                or event.get("host") != EXPECTED_HOST
                or event.get("audit_git") != AUDIT_GIT
                or event.get("audit_script_sha256") != AUDIT_SCRIPT_SHA256
                or event.get("supervisor_sha256")
                != SUPERVISOR_SCRIPT_SHA256
                or event.get("receipt_sha256") != RECEIPT_SHA256
                or event.get("preparation_sha256") != PREPARATION_SHA256
                or event.get("preparer_sha256") != PREPARER_SCRIPT_SHA256
                or event.get("receipt_sha256")
                != admitted_event.get("receipt_sha256")
                or event.get("preparation_sha256")
                != admitted_event.get("preparation_sha256")
                or event.get("preparer_sha256")
                != admitted_event.get("preparer_sha256")
                or not isinstance(receipt, dict)
                or event.get("receipt_sha256") != receipt.get("sha256")
                or event.get("gate_sha256") != gate_sha256
                or event.get("gate_verdict") != gate.get("verdict")
                or event.get("gate_returncode") != expected_code
                or event.get("retry_authorized") is not False):
            problems.append("supervisor terminal binding")
        if (not isinstance(labels, list) or len(labels) != 8
                or any(not is_sha256(value) for value in labels)
                or len(set(labels)) != 8):
            problems.append("supervisor exact label population")
        else:
            inputs = gate.get("inputs")
            if (not isinstance(inputs, list) or len(inputs) != 8
                    or any(not isinstance(item, dict)
                           or set(item) != {"path", "sha256", "shard_index"}
                           for item in inputs)
                    or labels != [item["sha256"] for item in inputs]):
                problems.append("supervisor/gate label digest binding")
    return sorted(set(problems))


def runtime_contract(expected_git: str) -> dict:
    if (not isinstance(expected_git, str) or len(expected_git) != 40
            or any(character not in "0123456789abcdef"
                   for character in expected_git)):
        raise AdapterRefusal("invalid expected adapter git")
    root = Path(__file__).resolve().parents[1]
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True,
            capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, check=True,
            capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise AdapterRefusal(f"cannot establish adapter git: {exc}") from exc
    if head != expected_git:
        raise AdapterRefusal("adapter exact git predeclaration")
    if dirty:
        raise AdapterRefusal("adapter refuses a dirty tree")
    return {
        "git": head,
        "tree_dirty": False,
        "python": sys.version.split()[0],
        "adapter_source_sha256": sha256_file(Path(__file__).resolve()),
    }


def reopen_inputs(config: Config) -> tuple[dict, list[dict]]:
    problems = _canonical_path_problems(config.gate, GATE_PATH)
    problems += _canonical_path_problems(
        config.supervisor_progress, SUPERVISOR_PROGRESS_PATH)
    problems += _artifact_problems(config.gate, config.expected_gate_sha256)
    problems += _artifact_problems(
        config.supervisor_progress, config.expected_supervisor_sha256)
    if problems:
        raise AdapterRefusal("; ".join(sorted(set(problems))))
    gate = _load_json(config.gate)
    events = _load_jsonl(config.supervisor_progress)
    problems = _gate_problems(gate)
    problems += _supervisor_problems(
        events, gate, config.expected_gate_sha256)
    if problems:
        raise AdapterRefusal("; ".join(sorted(set(problems))))
    return gate, events


def build_payload(config: Config, gate: dict, events: list[dict],
                  runtime: dict) -> dict:
    del events  # Its exact bytes and terminal binding are evidence, not output.
    verdict = gate["verdict"]
    contract = PASS_CONTRACT if verdict == "PASS" else NONPASS_CONTRACT
    return {
        "schema": SCHEMA,
        "complete": True,
        "terminal_audit_verdict": verdict,
        "branch": "PASS" if verdict == "PASS" else "NONPASS",
        "evidence": {
            "audit_id": AUDIT_ID,
            "run_id": RUN_ID,
            "audit_git": AUDIT_GIT,
            "audit_script_sha256": AUDIT_SCRIPT_SHA256,
            "supervisor_script_sha256": SUPERVISOR_SCRIPT_SHA256,
            "preparer_script_sha256": PREPARER_SCRIPT_SHA256,
            "receipt_sha256": RECEIPT_SHA256,
            "preparation_sha256": PREPARATION_SHA256,
            "compiled_engine_sha256": COMPILED_ENGINE_SHA256,
            "stage_b_state_sha256": STAGE_B_STATE_SHA256,
            "consumed_audit_state_sha256": CONSUMED_AUDIT_STATE_SHA256,
            "fresh_audit_state_sha256": AUDIT_STATE_SHA256,
            "gate": {
                "path": str(config.gate),
                "sha256": config.expected_gate_sha256,
            },
            "supervisor_progress": {
                "path": str(config.supervisor_progress),
                "sha256": config.expected_supervisor_sha256,
            },
        },
        "contract": copy.deepcopy(contract),
        "compute_authorized": False,
        "bulk_label_authorized": False,
        "training_authorized": False,
        "production_promotion": False,
        "audit_retry_authorized": False,
        "external_review_required": True,
        "runtime": copy.deepcopy(runtime),
    }


def _exclusive_publish(partial: Path, final: Path) -> None:
    try:
        os.link(partial, final)
    except FileExistsError as exc:
        raise AdapterRefusal(f"refusing to overwrite {final}") from exc
    os.unlink(partial)


def write_verified(path: Path, payload: dict, verify) -> None:
    partial = artifact_partial(path)
    if os.path.lexists(path) or os.path.lexists(partial):
        raise AdapterRefusal(f"refusing existing output or partial {path}")
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":"))
           + "\n").encode()
    try:
        with partial.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        reopened = json.loads(partial.read_bytes())
        if reopened != payload:
            raise AdapterRefusal("adapter partial differs from candidate")
        verify(reopened)
        _exclusive_publish(partial, path)
        if path.read_bytes() != raw:
            raise AdapterRefusal("adapter final differs from candidate bytes")
    except BaseException:
        # Preserve an owned partial as fail-closed evidence.
        raise


def create(config: Config, out: Path) -> dict:
    output_problems = _canonical_path_problems(
        out, OUTPUT_PATH, allow_missing_leaf=True)
    if output_problems:
        raise AdapterRefusal("; ".join(output_problems))
    runtime = runtime_contract(config.expected_git)
    gate, events = reopen_inputs(config)
    payload = build_payload(config, gate, events, runtime)

    def verify(reopened: dict) -> None:
        current_runtime = runtime_contract(config.expected_git)
        current_gate, current_events = reopen_inputs(config)
        expected = build_payload(
            config, current_gate, current_events, current_runtime)
        if reopened != expected:
            raise AdapterRefusal("published adapter full recomputation drift")

    write_verified(out, payload, verify)
    return payload


def verify(config: Config, path: Path, expected_sha256: str) -> dict:
    path_problems = _canonical_path_problems(path, OUTPUT_PATH)
    if path_problems:
        raise AdapterRefusal("; ".join(path_problems))
    problems = _artifact_problems(path, expected_sha256)
    if problems:
        raise AdapterRefusal("; ".join(problems))
    payload = _load_json(path)
    gate, events = reopen_inputs(config)
    expected = build_payload(
        config, gate, events, runtime_contract(config.expected_git))
    if payload != expected:
        raise AdapterRefusal("adapter full recomputation drift")
    return payload


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    for mode in ("create", "verify"):
        command = sub.add_parser(mode)
        command.add_argument("--gate", required=True)
        command.add_argument("--expected-gate-sha256", required=True)
        command.add_argument("--supervisor-progress", required=True)
        command.add_argument(
            "--expected-supervisor-progress-sha256", required=True)
        command.add_argument("--expected-git", required=True)
        if mode == "create":
            command.add_argument("--out", required=True)
        else:
            command.add_argument("--adapter", required=True)
            command.add_argument("--expected-adapter-sha256", required=True)
    return ap


def main() -> None:
    args = parser().parse_args()
    config = Config(
        gate=Path(args.gate),
        expected_gate_sha256=args.expected_gate_sha256,
        supervisor_progress=Path(args.supervisor_progress),
        expected_supervisor_sha256=args.expected_supervisor_progress_sha256,
        expected_git=args.expected_git,
    )
    try:
        if args.mode == "create":
            payload = create(config, Path(args.out))
        else:
            payload = verify(
                config, Path(args.adapter), args.expected_adapter_sha256)
    except (AdapterRefusal, OSError, ValueError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(3)
    print(json.dumps({
        "schema": payload["schema"],
        "terminal_audit_verdict": payload["terminal_audit_verdict"],
        "branch": payload["branch"],
        "decision": payload["contract"]["decision"],
        "compute_authorized": payload["compute_authorized"],
    }, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()

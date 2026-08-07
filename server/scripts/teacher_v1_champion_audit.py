"""Frozen report-LCB continuation audit for Teacher-v3 Stage B.

This is a new experiment boundary, not an extra fold appended to the running
N=30 attribution gate.  ``freeze`` consumes only the immutable Stage-B state
set and selects a fixed 64-state subset before any N=30 label outcome is read.
Later modes will bind exact cheap/N=30 parents and evaluate both frozen choices
under the deployed report-LCB continuation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import teacher_v1_label as teacher_label                         # noqa: E402
import teacher_v1_states as teacher_states                       # noqa: E402
from shengji.ai.registry import make_bot                          # noqa: E402
from shengji.teacher_v1 import (CAPTURE_PACKET_ID, CAPTURE_PYTHON,  # noqa: E402
                                EXPERIMENTAL_SAMPLER_BALLOT_FLAGS,
                                REPRESENTATIVE_CELLS,
                                STATE_SET_SCHEMA, TeacherProtocolError,
                                stable_digest)


AUDIT_ID = "teacher-v3-report-lcb-audit-v1"
AUDIT_STATE_SCHEMA = "teacher-v1-champion-audit-state-set-v1"
STAGE_B_STATE_SHA256 = (
    "90956da86f4f03074a1b4dc2d7198a3da5958470b733eacd104e066c523b4dc6"
)
AUDIT_STATES = 64
REPRESENTATIVE_PER_CELL = 4
BOUNDARY_STATES = 8
UNCERTAINTY_STATES = 8
AUDIT_FOLDS = {"champion_selection": 32, "champion_report": 32}
CONTINUATION_POLICY = "mc-s0-report-lcb"
CONTINUATION_CONTRACT = {
    "policy": CONTINUATION_POLICY,
    "selection_worlds": 30,
    "report_worlds": 300,
    "report_rule": "lcb",
    "report_alpha": 0.05,
    "report_min_gain": 0.0,
    "report_t_critical": 1.70,
    "require_exact_work": True,
    "adaptive_allocation": False,
    "random_allocation": False,
}
REGRET_LIMIT = 0.10
T_CRITICAL_ALL_64 = 1.67
T_CRITICAL_REPRESENTATIVE_48 = 1.68


def sha256_file(path: str | os.PathLike) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_output(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True,
    ).stdout.strip()


def source_digests() -> dict[str, str]:
    from shengji.ai import mcbot, memory, registry
    from shengji.engine import fast
    import shengji.teacher_v1 as teacher

    paths = {
        "audit_script": __file__,
        "label_script": teacher_label.__file__,
        "state_script": teacher_states.__file__,
        "teacher_contract": teacher.__file__,
        "mcbot": mcbot.__file__,
        "memory": memory.__file__,
        "registry": registry.__file__,
        "fast_router": fast.__file__,
        "compiled_engine": fast._fast.__file__,
    }
    return {
        name: sha256_file(path) for name, path in sorted(paths.items())
    }


def runtime_contract(*, smoke: bool) -> dict:
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise TeacherProtocolError("set SHENGJI_REQUIRE_VOIDS=1")
    if os.environ.get("SHENGJI_FAST") != "1":
        raise TeacherProtocolError("set SHENGJI_FAST=1")
    enabled = [name for name in EXPERIMENTAL_SAMPLER_BALLOT_FLAGS
               if name in os.environ]
    if enabled:
        raise TeacherProtocolError(
            f"experimental sampler/ballot flags must be unset: {enabled}")
    python = sys.version.split()[0]
    if not smoke and python != CAPTURE_PYTHON:
        raise TeacherProtocolError(
            f"real champion audit requires Python {CAPTURE_PYTHON}, got {python}")
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise TeacherProtocolError("compiled engine requested but not active")
    dirty = git_output("status", "--porcelain")
    if dirty and not smoke:
        raise TeacherProtocolError("real champion audit refuses a dirty tree")
    return {
        "git": git_output("rev-parse", "HEAD"),
        "tree_dirty": bool(dirty),
        "promotable": not smoke,
        "host": os.uname().nodename,
        "python": python,
        "fast_engine": True,
        "require_voids": True,
        "experimental_sampler_ballot_flags": [],
    }


def selection_key(state: dict) -> tuple[str, str]:
    state_id = state.get("state_id")
    return stable_digest({
        "audit_id": AUDIT_ID,
        "purpose": "state_selection",
        "state_id": state_id,
    }), str(state_id)


def live_continuation_contract() -> dict:
    bot = make_bot(CONTINUATION_POLICY, seed=1)
    return {
        "policy": CONTINUATION_POLICY,
        "selection_worlds": bot.N_DETERMINIZATIONS,
        "report_worlds": bot.REPORT_FOLD_WORLDS,
        "report_rule": bot.REPORT_RULE,
        "report_alpha": bot.REPORT_ALPHA,
        "report_min_gain": bot.REPORT_MIN_GAIN,
        "report_t_critical": bot.REPORT_T_CRITICAL,
        "require_exact_work": bot.REQUIRE_EXACT_WORK,
        "adaptive_allocation": bot.ADAPTIVE_ALLOCATION,
        "random_allocation": bot.RANDOM_ALLOCATION,
    }


def select_states(states: list[dict]) -> tuple[list[dict], list[str]]:
    """Select only from pre-label state metadata under a literal hash rule."""
    bad = []
    ids = [state.get("state_id") for state in states]
    deals = [state.get("seed") for state in states]
    if any(not isinstance(state_id, str) or not state_id for state_id in ids):
        bad.append("Stage-B parent has invalid state identities")
    if any(isinstance(deal, bool) or not isinstance(deal, int)
           for deal in deals):
        bad.append("Stage-B parent has invalid deal identities")
    if len(ids) != len(set(ids)):
        bad.append("Stage-B parent has duplicate state identities")
    if len(deals) != len(set(deals)):
        bad.append("Stage-B parent has duplicate deal identities")

    selected = []
    for cell in REPRESENTATIVE_CELLS:
        pool = sorted(
            [state for state in states
             if state.get("kind") == "representative"
             and (state.get("phase"), state.get("role"),
                  state.get("decision")) == cell],
            key=selection_key,
        )
        if len(pool) < REPRESENTATIVE_PER_CELL:
            bad.append(f"representative supply {cell}: {len(pool)}")
        selected.extend(pool[:REPRESENTATIVE_PER_CELL])
    for kind, required in (
        ("boundary", BOUNDARY_STATES),
        ("uncertainty", UNCERTAINTY_STATES),
    ):
        pool = sorted(
            [state for state in states if state.get("kind") == kind],
            key=selection_key,
        )
        if len(pool) < required:
            bad.append(f"{kind} supply: {len(pool)}")
        selected.extend(pool[:required])

    selected = sorted(selected, key=lambda state: str(state.get("state_id")))
    selected_ids = [state.get("state_id") for state in selected]
    selected_deals = [state.get("seed") for state in selected]
    if len(selected) != AUDIT_STATES:
        bad.append(f"selected {len(selected)} states, required {AUDIT_STATES}")
    if len(selected_ids) != len(set(selected_ids)):
        bad.append("selected duplicate state identities")
    if len(selected_deals) != len(set(selected_deals)):
        bad.append("selected duplicate deal identities")
    return selected, sorted(set(bad))


def audit_state_set_problems(payload: dict, parent: dict,
                             parent_sha256: str) -> list[str]:
    bad = []
    if (payload.get("schema") != AUDIT_STATE_SCHEMA
            or payload.get("audit_id") != AUDIT_ID
            or payload.get("complete") is not True):
        bad.append("audit state-set identity/completion")
    if payload.get("stage_b_parent") != {
        "sha256": parent_sha256,
        "states_digest": parent.get("states_digest"),
    }:
        bad.append("audit state-set exact Stage-B parent binding")
    if parent_sha256 != STAGE_B_STATE_SHA256:
        bad.append("audit Stage-B parent SHA-256 drift")
    expected, selection_bad = select_states(parent.get("states", []))
    bad += selection_bad
    if payload.get("states") != expected:
        bad.append("audit state selection recomputation drift")
    if payload.get("states_digest") != stable_digest(expected):
        bad.append("audit state digest")
    if payload.get("selected") != len(expected):
        bad.append("audit selected count")
    expected_contract = {
        "method": "hash_smallest_within_frozen_stratum",
        "hash_domain": "stable_digest(audit_id,purpose=state_selection,state_id)",
        "representative_per_cell": REPRESENTATIVE_PER_CELL,
        "boundary": BOUNDARY_STATES,
        "uncertainty": UNCERTAINTY_STATES,
        "label_outcomes_read": False,
    }
    if payload.get("selection_contract") != expected_contract:
        bad.append("audit selection contract")
    if payload.get("continuation_contract") != CONTINUATION_CONTRACT:
        bad.append("audit continuation contract")
    if payload.get("folds") != AUDIT_FOLDS:
        bad.append("audit fold contract")
    return sorted(set(bad))


def freeze(args) -> None:
    runtime = runtime_contract(smoke=args.smoke)
    parent = teacher_label.load_pinned(
        args.stage_b_state_set, args.expected_stage_b_state_set_sha256)
    bad = teacher_label.state_set_problems(parent, "b", smoke=args.smoke)
    if not args.smoke:
        bad += teacher_states.state_set_packet_problems(parent)
    if (parent.get("schema") != STATE_SET_SCHEMA
            or parent.get("packet_id") != CAPTURE_PACKET_ID):
        bad.append("audit parent packet identity")
    if args.expected_stage_b_state_set_sha256 != STAGE_B_STATE_SHA256:
        bad.append("audit parent is not the registered Stage-B state set")
    if live_continuation_contract() != CONTINUATION_CONTRACT:
        bad.append("deployed report-LCB continuation contract drift")
    selected, selection_bad = select_states(parent.get("states", []))
    bad += selection_bad
    for state in selected:
        try:
            teacher_label.replay_state(state)
        except Exception as exc:
            bad.append(
                f"{state.get('state_id')}: replay {type(exc).__name__}: {exc}")
    if bad:
        raise TeacherProtocolError("audit freeze preflight: " + "; ".join(bad))

    payload = {
        "schema": AUDIT_STATE_SCHEMA,
        "audit_id": AUDIT_ID,
        "complete": True,
        **runtime,
        "source_digests": source_digests(),
        "stage_b_parent": {
            "sha256": args.expected_stage_b_state_set_sha256,
            "states_digest": parent.get("states_digest"),
        },
        "selection_contract": {
            "method": "hash_smallest_within_frozen_stratum",
            "hash_domain": (
                "stable_digest(audit_id,purpose=state_selection,state_id)"),
            "representative_per_cell": REPRESENTATIVE_PER_CELL,
            "boundary": BOUNDARY_STATES,
            "uncertainty": UNCERTAINTY_STATES,
            "label_outcomes_read": False,
        },
        "continuation_contract": CONTINUATION_CONTRACT,
        "folds": AUDIT_FOLDS,
        "selected": len(selected),
        "states": selected,
        "states_digest": stable_digest(selected),
    }
    violations = audit_state_set_problems(
        payload, parent, args.expected_stage_b_state_set_sha256)
    if violations:
        raise TeacherProtocolError(
            "audit state-set contract: " + "; ".join(violations))

    frozen_runtime = dict(runtime)
    frozen_sources = dict(payload["source_digests"])

    def verify() -> None:
        if os.path.islink(args.out) or not os.path.isfile(args.out):
            raise TeacherProtocolError(
                "published audit state set is missing/non-regular")
        with open(args.out, "rb") as fh:
            raw = fh.read()
        reopened = json.loads(raw)
        if hashlib.sha256(raw).hexdigest() != sha256_file(
                args.out + ".partial"):
            raise TeacherProtocolError(
                "published audit state set differs from partial bytes")
        if reopened != payload:
            raise TeacherProtocolError(
                "published audit state set differs from candidate bytes")
        if runtime_contract(smoke=args.smoke) != frozen_runtime:
            raise TeacherProtocolError(
                "audit runtime changed during publication")
        if source_digests() != frozen_sources:
            raise TeacherProtocolError(
                "audit sources changed during publication")
        current_parent = teacher_label.load_pinned(
            args.stage_b_state_set,
            args.expected_stage_b_state_set_sha256)
        current_bad = audit_state_set_problems(
            reopened, current_parent,
            args.expected_stage_b_state_set_sha256)
        if current_bad:
            raise TeacherProtocolError(
                "published audit state-set contract: "
                + "; ".join(current_bad))

    teacher_label.write_complete(args.out, payload, verify=verify)
    print(json.dumps({
        "audit_id": AUDIT_ID,
        "out": args.out,
        "selected": len(selected),
        "states_digest": payload["states_digest"],
    }, sort_keys=True), flush=True)


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    freeze_ = sub.add_parser("freeze")
    freeze_.add_argument("--stage-b-state-set", required=True)
    freeze_.add_argument(
        "--expected-stage-b-state-set-sha256", required=True)
    freeze_.add_argument("--out", required=True)
    freeze_.add_argument("--smoke", action="store_true")
    return ap


def main() -> None:
    args = parser().parse_args()
    try:
        freeze(args)
    except (OSError, ValueError, TeacherProtocolError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3)


if __name__ == "__main__":
    main()

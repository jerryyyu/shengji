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
from collections import Counter
from collections.abc import Callable

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
AUDIT_PROGRESS_WORLD_INTERVAL = 1
CHAMPION_TELEMETRY_FIELDS = (
    "decisions",
    "searched_decisions",
    "unsearched_decisions",
    "selection_worlds",
    "report_worlds",
    "selection_candidate_rollouts",
    "report_candidate_rollouts",
    "total_candidate_rollouts",
    *teacher_label.SAMPLER_COUNTERS,
)


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


def _zero_champion_telemetry() -> Counter:
    return Counter({name: 0 for name in CHAMPION_TELEMETRY_FIELDS})


def champion_decision_telemetry(policy, sampler_counters: dict) -> dict:
    """Validate one downstream report-LCB decision and return exact work.

    A legal single-action or tractor-lock decision performs no search and has
    no decision record.  Every contested decision must consume the complete
    registered N=30 selection and R=300 report folds.  Checking both the live
    cumulative delta and the decision record prevents a short/fallback search
    from being accepted merely because one of those observability paths was
    stale or incomplete.
    """
    telemetry = _zero_champion_telemetry()
    telemetry["decisions"] = 1
    if set(sampler_counters) != set(teacher_label.SAMPLER_COUNTERS):
        raise TeacherProtocolError("champion sampler counter schema mismatch")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
           for value in sampler_counters.values()):
        raise TeacherProtocolError("champion sampler counters are not integers")

    record = getattr(policy, "last_decision_record", None)
    searches = int(getattr(policy, "search_calls", 0))
    rollouts = int(getattr(policy, "rollouts", 0))
    if record is None:
        if searches or rollouts or any(sampler_counters.values()):
            raise TeacherProtocolError(
                "unsearched champion decision consumed or recorded work")
        telemetry["unsearched_decisions"] = 1
        return dict(telemetry)

    telemetry["searched_decisions"] = 1
    if searches != 1:
        raise TeacherProtocolError(
            f"champion decision search count {searches}, expected 1")
    if (record.get("policy") != CONTINUATION_POLICY
            or record.get("n_determinizations")
            != CONTINUATION_CONTRACT["selection_worlds"]
            or record.get("report_worlds_requested")
            != CONTINUATION_CONTRACT["report_worlds"]
            or record.get("report_rule")
            != CONTINUATION_CONTRACT["report_rule"]
            or record.get("report_alpha")
            != CONTINUATION_CONTRACT["report_alpha"]
            or record.get("report_min_gain")
            != CONTINUATION_CONTRACT["report_min_gain"]
            or record.get("adaptive_allocation") is not False
            or record.get("random_allocation") is not False):
        raise TeacherProtocolError("champion decision policy contract drift")

    candidates = record.get("candidates")
    n_by = record.get("n_by_candidate")
    candidate_count = len(candidates) if isinstance(candidates, list) else 0
    selection_worlds = CONTINUATION_CONTRACT["selection_worlds"]
    report_worlds = CONTINUATION_CONTRACT["report_worlds"]
    selection_rollouts = candidate_count * selection_worlds
    report_rollouts = 2 * report_worlds
    if (candidate_count < 2
            or n_by != [selection_worlds] * candidate_count
            or record.get("worlds") != selection_worlds):
        raise TeacherProtocolError("champion selection dose is incomplete")

    alloc = record.get("alloc", {})
    if (alloc.get("mode") != "uniform"
            or alloc.get("short") is not False
            or alloc.get("worlds") != selection_worlds
            or alloc.get("budget") != selection_rollouts
            or alloc.get("rollouts") != selection_rollouts
            or alloc.get("decision_rollouts") != selection_rollouts
            or alloc.get("dummy_rollouts") != 0
            or alloc.get("n_by_candidate") != n_by):
        raise TeacherProtocolError("champion selection work does not reconcile")

    report = record.get("report_fold", {})
    if (report.get("fold") != "report"
            or report.get("rule") != "lcb"
            or report.get("worlds") != report_worlds
            or report.get("attempts") != report_worlds
            or report.get("rejected") != 0
            or report.get("complete") is not True
            or report.get("critical")
            != CONTINUATION_CONTRACT["report_t_critical"]
            or report.get("min_gain")
            != CONTINUATION_CONTRACT["report_min_gain"]):
        raise TeacherProtocolError("champion report fold is incomplete")

    work = record.get("work", {})
    total_rollouts = selection_rollouts + report_rollouts
    if (work.get("selection_budget") != selection_rollouts
            or work.get("selection_rollouts") != selection_rollouts
            or work.get("report_budget") != report_rollouts
            or work.get("report_rollouts") != report_rollouts
            or work.get("total_budget") != total_rollouts
            or work.get("total_rollouts") != total_rollouts
            or work.get("complete") is not True
            or rollouts != total_rollouts):
        raise TeacherProtocolError("champion total work does not reconcile")

    if record.get("reason") not in {
            "report_lcb_override", "report_lcb_below_min_gain"}:
        raise TeacherProtocolError("champion decision ended outside report-LCB")
    played_index = record.get("played_index")
    if (isinstance(played_index, bool) or not isinstance(played_index, int)
            or not 0 <= played_index < candidate_count
            or record.get("played") != candidates[played_index]):
        raise TeacherProtocolError("champion played-action telemetry drift")

    expected_sampler = {
        "sample_attempts": selection_worlds + report_worlds,
        "accepted_worlds": selection_worlds + report_worlds,
        "failed_worlds": 0,
        "rejected_worlds": 0,
        "impossible_worlds": 0,
        "short_search_decisions": 0,
        "zero_world_decisions": 0,
    }
    if sampler_counters != expected_sampler:
        raise TeacherProtocolError(
            "champion live sampler dose is not exact: "
            f"{sampler_counters!r}")
    record_sampler = record.get("sampler_counters", {}).get("delta")
    if record_sampler != {
            name: expected_sampler[name] for name in (
                "sample_attempts", "accepted_worlds", "failed_worlds",
                "rejected_worlds", "impossible_worlds") }:
        raise TeacherProtocolError("champion record/live sampler delta drift")

    telemetry.update(expected_sampler)
    telemetry["selection_worlds"] = selection_worlds
    telemetry["report_worlds"] = report_worlds
    telemetry["selection_candidate_rollouts"] = selection_rollouts
    telemetry["report_candidate_rollouts"] = report_rollouts
    telemetry["total_candidate_rollouts"] = total_rollouts
    return dict(telemetry)


def _decision_record_digest(record: dict | None) -> str | None:
    if record is None:
        return None
    semantic = dict(record)
    # Wall time is observability, not experiment semantics.  Excluding it makes
    # an exact replay produce the same trace digest on a different host.
    semantic.pop("search_secs", None)
    return stable_digest(semantic)


def rollout_champion(rnd, seat: int, hands, buried, candidate, *,
                     experiment_id: str, state_id: str, deal_seed: int,
                     fold: str, candidate_index: int, world_index: int):
    """Roll one action to terminal under fresh report-LCB information sets."""
    clone = teacher_label._clone_world(
        rnd, seat, hands, buried, candidate)
    counters = Counter({name: 0 for name in teacher_label.SAMPLER_COUNTERS})
    telemetry = _zero_champion_telemetry()
    trace = []
    decision_index = 0
    while clone.phase == "play":
        actor_seat = clone.turn
        if actor_seat is None:
            raise TeacherProtocolError("champion continuation has no actor")
        stream = teacher_label.derive_stream(
            experiment_id=experiment_id,
            deal_seed=deal_seed,
            state_id=state_id,
            purpose="continuation",
            fold=fold,
            candidate=candidate_index,
            world=world_index,
            decision=decision_index,
            seat=actor_seat,
            policy=CONTINUATION_POLICY,
        )
        policy = make_bot(CONTINUATION_POLICY, seed=stream["seed"])
        before = teacher_label.sampler_snapshot(policy)
        try:
            action = policy.decide_play(clone, actor_seat)
            delta = teacher_label.sampler_delta(before, policy)
            decision_work = champion_decision_telemetry(policy, delta)
        except Exception as exc:
            raise TeacherProtocolError(
                f"{state_id}/{fold}/c{candidate_index}/w{world_index}/"
                f"d{decision_index}: invalid champion continuation: "
                f"{type(exc).__name__}: {exc}") from exc
        counters.update(delta)
        telemetry.update(decision_work)
        trace.append({
            "decision": decision_index,
            "seat": actor_seat,
            "seed": stream["seed"],
            "action": list(action),
            "decision_record_digest": _decision_record_digest(
                policy.last_decision_record),
        })
        try:
            clone.play(actor_seat, list(action))
        except Exception as exc:
            raise TeacherProtocolError(
                f"{state_id}/{fold}/c{candidate_index}/w{world_index}/"
                f"d{decision_index}: illegal champion action: "
                f"{type(exc).__name__}: {exc}") from exc
        decision_index += 1
    return (
        float(clone.attacker_points),
        dict(counters),
        stable_digest(trace),
        len(trace),
        dict(telemetry),
    )


def score_champion_fold(rnd, seat: int, candidates, worlds, fold_meta: dict,
                        *, state: dict, fold: str,
                        progress: Callable[[dict], None] | None = None) -> dict:
    """Score every candidate on common outer worlds under report-LCB."""
    tensor = teacher_label._empty_tensor()
    trace_digests, continuation_decisions = [], []
    inner_counters = Counter({
        name: 0 for name in teacher_label.SAMPLER_COUNTERS})
    continuation_telemetry = _zero_champion_telemetry()
    acting_is_attacker = rnd.is_attacker(seat)
    for world_index, (hands, buried) in enumerate(worlds):
        rows = {name: [] for name in tensor}
        digest_row, decisions_row = [], []
        for candidate_index, candidate in enumerate(candidates):
            (points, counters, trace_digest, n_decisions,
             telemetry) = rollout_champion(
                rnd, seat, hands, buried, candidate,
                experiment_id=state["experiment_id"],
                state_id=state["state_id"],
                deal_seed=state["seed"],
                fold=fold,
                candidate_index=candidate_index,
                world_index=world_index,
            )
            inner_counters.update(counters)
            continuation_telemetry.update(telemetry)
            outcome = teacher_label.targets(points, acting_is_attacker)
            for name in rows:
                rows[name].append(outcome[name])
            digest_row.append(trace_digest)
            decisions_row.append(n_decisions)
        for name in tensor:
            tensor[name].append(rows[name])
        trace_digests.append(digest_row)
        continuation_decisions.append(decisions_row)
        worlds_complete = world_index + 1
        if (progress is not None
                and (worlds_complete % AUDIT_PROGRESS_WORLD_INTERVAL == 0
                     or worlds_complete == len(worlds))):
            progress({
                "kind": "champion-fold",
                "state_id": state["state_id"],
                "fold": fold,
                "worlds_complete": worlds_complete,
                "worlds_total": len(worlds),
            })
    result = {
        **fold_meta,
        "continuation_policy": CONTINUATION_POLICY,
        "continuation_contract": CONTINUATION_CONTRACT,
        "continuation_seed_derivation": (
            "sha256(canonical JSON of experiment_id,deal_seed,state_id,"
            "purpose,fold,candidate,world,decision,seat,policy)[:16]"),
        "continuation_trace_digests": trace_digests,
        "continuation_decisions": continuation_decisions,
        "inner_sampler_counters": dict(inner_counters),
        "continuation_telemetry": dict(continuation_telemetry),
        "tensor": tensor,
    }
    bad = teacher_label.tensor_problems(
        result, len(worlds), len(candidates))
    if bad:
        raise TeacherProtocolError(
            f"{state['state_id']}/{fold}: {'; '.join(bad)}")
    return result


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

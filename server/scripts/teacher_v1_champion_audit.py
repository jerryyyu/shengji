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
import math
import os
import secrets
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import teacher_v1_label as teacher_label                         # noqa: E402
import teacher_v1_gate as teacher_gate                           # noqa: E402
import teacher_v1_states as teacher_states                       # noqa: E402
from shengji.ai.registry import make_bot                          # noqa: E402
from shengji.teacher_v1 import (CAPTURE_PACKET_ID, CAPTURE_PYTHON,  # noqa: E402
                                EXPERIMENTAL_SAMPLER_BALLOT_FLAGS,
                                REPRESENTATIVE_CELLS,
                                STATE_SET_SCHEMA, TeacherProtocolError,
                                stable_digest)


AUDIT_ID = "teacher-v3-report-lcb-audit-v1"
AUDIT_STATE_SCHEMA = "teacher-v1-champion-audit-state-set-v1"
AUDIT_RECEIPT_SCHEMA = "teacher-v1-champion-audit-receipt-v1"
AUDIT_SHARD_SCHEMA = "teacher-v1-champion-audit-shard-v1"
AUDIT_GATE_SCHEMA = "teacher-v1-champion-audit-gate-v1"
STAGE_B_STATE_SHA256 = (
    "90956da86f4f03074a1b4dc2d7198a3da5958470b733eacd104e066c523b4dc6"
)
AUDIT_STATE_SHA256 = (
    "d04d1c0fa507bab680da4d53eeb72325a97c8ca058aac0d01c16dfdcf44f7a34"
)
AUDIT_STATE_FREEZE_GIT = "7040489b458db86a68576b146a280fd4598bbac0"
AUDIT_TRANSITION_PARENT = "c40a31c2d58c171f2172496d928f719932247730"
AUDIT_TRANSITION_PATHS = {
    "server/scripts/teacher_v1_champion_audit.py",
    "server/tests/test_teacher_v1_champion_audit.py",
}
AUDIT_STATES = 64
REPRESENTATIVE_PER_CELL = 4
BOUNDARY_STATES = 8
UNCERTAINTY_STATES = 8
AUDIT_FOLDS = {"champion_selection": 32, "champion_report": 32}
AUDIT_SHARDS = 8
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
CONTINUATION_EXECUTION_LOCK = {
    "schema": "teacher-v1-champion-continuation-lock-v1",
    "policy": CONTINUATION_POLICY,
    "policy_class": "MCS0ReportLCB",
    "rollout_policy_class": "HeuristicBot",
    "ballot": {
        "name": "mc_candidates",
        "version": 1,
        "source": "MCBot._candidates",
        "config": [
            ["FOLLOW_MAX_CANDIDATES", 12],
            ["LEAD_MAX_CANDIDATES", 14],
            ["MAX_CANDIDATES", 8],
            ["RISKY_THROWS", False],
            ["TRUMP_BALLOT", False],
            ["V3_LEAD_RANDOM", False],
            ["V3_LEAD_SINGLES", False],
            ["WIDE_FOLLOW_BALLOT", True],
            ["WIDE_LEAD_BALLOT", True],
        ],
        "source_digest": "3710a9113a2bcfbc",
        "note": "",
        "digest": "c008dd47b0b7",
        "display": "mc_candidates@v1[c008dd47b0b7]",
    },
    "source_sha256s": {
        "ai_bury": "2fd2ca71ed7594b99e907d5dbcb65bb95302a7b8c16660769115ed4ddfafe610",
        "ai_endgame": "f01d8f937fabf5a1a736ec238b0d0add23ab11b31369518848238eb63ed3799e",
        "ai_env": "04b1d18e2ad4783c5160913b66c2adf568625de1aaf6bdf300c6a4b00c2f0d8b",
        "ai_heuristic": "a99dfb089fd17e7c17ddcc4d76542552d317598fbe233269c3e7c0501b9b15ef",
        "ai_mcbot": "45a82f44b95d1bce5126c63b1a5af6baaed54270aca9d55677b2e0bbb9c9d957",
        "ai_memory": "905873b332fd54471070b25ce24f100b813c9a9f234c1b50254d00895140cf51",
        "ai_registry": "3e2831616645f74b025e09b3663e73001b6798e94eafaebc0353665bdc8ceea3",
        "ai_smart": "facfb6a9bb67f82d1bddb855f01ce49adf5f0caaca92bfb5da09ba343c29512c",
        "engine_ballot": "63e2e94ca12f9ebf8dce30c1a1bdbe3fe9cf6223603677173d4eb75e334845d5",
        "engine_cards": "42452b157818da1792f4490c3a50c10060eda1a02bb6b2c91544a62fbc0d000a",
        "engine_combos": "2b0b0acceb0786b4ce781475c0f3e3d656ebe349fdf00bfffd668d6847885486",
        "engine_fast": "f2506d5c51b8ad37303f04dce59899de0d7c1179633b08ce61f48eb86cec1a3e",
        "engine_fast_pyx": "a7525f756c654ab19aae6aaa9b09df30e9120553ab77d45c8312efbb9fefebc0",
        "engine_game": "613c5dd72a1cbd3b50a96eef6e0b84746052dc2b0b28fb08005ff34455359e43",
        "engine_legal": "12256869a3d3d01b070be04d2a2821b021b6932ad95e66dc54b0e0111192079b",
        "engine_round": "7a91b3573ecb34c488e3960008d21ebfda283e01003f6454a1ffd62c41b9b679",
        "compiled_engine": "ef7c161829c607aad790e949e0a0bae7e04d8a3be7aea51b80d5108a1f566b4d",
    },
}
AUDIT_STATE_SOURCE_DIGESTS = {
    "audit_script": "8c29c74605de2fa1887530b15cfd3e5da661751d3650f28c2b7936ee2f40c9ba",
    "compiled_engine": "ef7c161829c607aad790e949e0a0bae7e04d8a3be7aea51b80d5108a1f566b4d",
    "fast_router": "f2506d5c51b8ad37303f04dce59899de0d7c1179633b08ce61f48eb86cec1a3e",
    "label_script": "58c833fd3707a3ce5403cf7d0e8a23aa518c332976aa7ab4dd3ceb98010386dc",
    "mcbot": "45a82f44b95d1bce5126c63b1a5af6baaed54270aca9d55677b2e0bbb9c9d957",
    "memory": "905873b332fd54471070b25ce24f100b813c9a9f234c1b50254d00895140cf51",
    "registry": "3e2831616645f74b025e09b3663e73001b6798e94eafaebc0353665bdc8ceea3",
    "state_script": "c967d2b610820c03432317ab1b4491a2c4cb7ba8d20b2b4fc009ddfd97e87c2b",
    "teacher_contract": "99848ffbf1f41bcd6aa699c2f17b1031eafee651289bbdae33e9853b5e13a250",
}
REGRET_LIMIT = 0.10
T_CRITICAL_ALL_64 = 1.67
T_CRITICAL_REPRESENTATIVE_48 = 1.68
T_CRITICAL_CHALLENGE_8 = 1.90
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
RUNTIME_BINDING_FIELDS = (
    "git", "tree_dirty", "promotable", "host", "python", "fast_engine",
    "require_voids", "experimental_sampler_ballot_flags",
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
        "gate_script": teacher_gate.__file__,
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


def continuation_source_digests() -> dict[str, str]:
    """Hash every material actor/rollout/engine source named by the lock."""
    from shengji.ai import (bury, endgame, env, heuristic, mcbot, memory,
                            registry, smart)
    from shengji.engine import ballot, cards, combos, fast, game, legal, round

    paths = {
        "ai_bury": bury.__file__,
        "ai_endgame": endgame.__file__,
        "ai_env": env.__file__,
        "ai_heuristic": heuristic.__file__,
        "ai_mcbot": mcbot.__file__,
        "ai_memory": memory.__file__,
        "ai_registry": registry.__file__,
        "ai_smart": smart.__file__,
        "engine_ballot": ballot.__file__,
        "engine_cards": cards.__file__,
        "engine_combos": combos.__file__,
        "engine_fast": fast.__file__,
        "engine_fast_pyx": os.path.join(
            os.path.dirname(fast.__file__), "_fast.pyx"),
        "engine_game": game.__file__,
        "engine_legal": legal.__file__,
        "engine_round": round.__file__,
        "compiled_engine": fast._fast.__file__,
    }
    return {name: sha256_file(path) for name, path in sorted(paths.items())}


def live_continuation_execution_lock() -> dict:
    from shengji.ai.mcbot import _ballot_identity

    bot = make_bot(CONTINUATION_POLICY, seed=1)
    return teacher_label.json_canonical({
        "schema": CONTINUATION_EXECUTION_LOCK["schema"],
        "policy": CONTINUATION_POLICY,
        "policy_class": type(bot).__name__,
        "rollout_policy_class": type(bot.rollout_policy).__name__,
        "ballot": _ballot_identity(bot),
        "source_sha256s": continuation_source_digests(),
    })


def continuation_execution_lock_problems() -> list[str]:
    actual = live_continuation_execution_lock()
    expected = CONTINUATION_EXECUTION_LOCK
    bad = []
    for key in ("schema", "policy", "policy_class", "rollout_policy_class"):
        if actual.get(key) != expected.get(key):
            bad.append(f"continuation execution {key} drift")
    if actual.get("ballot") != expected.get("ballot"):
        bad.append("continuation execution ballot drift")
    expected_sources = expected["source_sha256s"]
    actual_sources = actual.get("source_sha256s", {})
    for name in sorted(set(expected_sources) | set(actual_sources)):
        if actual_sources.get(name) != expected_sources.get(name):
            bad.append(f"continuation execution source {name} drift")
    return bad


def audit_transition_problems() -> list[str]:
    head = git_output("rev-parse", "HEAD")
    if subprocess.run(
            ["git", "merge-base", "--is-ancestor",
             AUDIT_TRANSITION_PARENT, head], capture_output=True).returncode:
        return ["audit execution is not descended from frozen transition parent"]
    changed = set(filter(None, git_output(
        "diff", "--name-only", f"{AUDIT_TRANSITION_PARENT}..{head}").splitlines()))
    extra = sorted(changed - AUDIT_TRANSITION_PATHS)
    return ([f"audit transition changed unregistered paths {extra}"]
            if extra else [])


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
    if not smoke:
        problems = audit_transition_problems()
        problems += continuation_execution_lock_problems()
        if problems:
            raise TeacherProtocolError(
                "champion audit execution lock: " + "; ".join(problems))
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


def _ballot_action_contract(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    required = ("name", "version", "source", "config")
    if not all(key in value for key in required):
        return None
    return teacher_label.json_canonical({key: value[key] for key in required})


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
    code = record.get("code", {})
    expected_ballot = CONTINUATION_EXECUTION_LOCK["ballot"]
    if (record.get("policy") != CONTINUATION_POLICY
            or record.get("policy_class")
            != CONTINUATION_EXECUTION_LOCK["policy_class"]
            or code.get("mcbot_sha256")
            != CONTINUATION_EXECUTION_LOCK["source_sha256s"]["ai_mcbot"]
            or _ballot_action_contract(record.get("ballot"))
            != _ballot_action_contract(expected_ballot)
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
            experiment_id=AUDIT_ID,
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
        "continuation_execution_lock": CONTINUATION_EXECUTION_LOCK,
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


def _matrix_means(matrix: list[list[float]]) -> list[float]:
    return [sum(row[index] for row in matrix) / len(matrix)
            for index in range(len(matrix[0]))]


def continuation_telemetry_problems(fold: dict) -> list[str]:
    bad = []
    if fold.get("continuation_execution_lock") != \
            CONTINUATION_EXECUTION_LOCK:
        bad.append("champion continuation execution lock")
    telemetry = fold.get("continuation_telemetry", {})
    if set(telemetry) != set(CHAMPION_TELEMETRY_FIELDS):
        return ["champion telemetry schema"]
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
           for value in telemetry.values()):
        return ["champion telemetry non-negative integer values"]
    decisions = telemetry["decisions"]
    searched = telemetry["searched_decisions"]
    unsearched = telemetry["unsearched_decisions"]
    if decisions != searched + unsearched:
        bad.append("champion decision accounting")
    if telemetry["selection_worlds"] != 30 * searched:
        bad.append("champion selection-world dose")
    if telemetry["report_worlds"] != 300 * searched:
        bad.append("champion report-world dose")
    selection_rollouts = telemetry["selection_candidate_rollouts"]
    if (selection_rollouts < 60 * searched
            or selection_rollouts % 30 != 0):
        bad.append("champion selection candidate-rollout dose")
    if telemetry["report_candidate_rollouts"] != 600 * searched:
        bad.append("champion report candidate-rollout dose")
    if telemetry["total_candidate_rollouts"] != (
            selection_rollouts + telemetry["report_candidate_rollouts"]):
        bad.append("champion total candidate-rollout dose")
    if (telemetry["sample_attempts"] != 330 * searched
            or telemetry["accepted_worlds"] != 330 * searched):
        bad.append("champion accepted sampler dose")
    forbidden = {name: telemetry[name] for name in (
        "failed_worlds", "rejected_worlds", "impossible_worlds",
        "short_search_decisions", "zero_world_decisions",
    ) if telemetry[name]}
    if forbidden:
        bad.append(f"champion forbidden counters {forbidden}")
    expected_inner = {
        name: telemetry[name] for name in teacher_label.SAMPLER_COUNTERS}
    if fold.get("inner_sampler_counters") != expected_inner:
        bad.append("champion telemetry/inner-counter drift")
    return bad


def selected_parent_records(audit_states: list[dict], cheap_records: list[dict],
                            gold_records: list[dict]
                            ) -> list[tuple[dict, dict, dict]]:
    """Join the outcome-blind audit subset to exact cheap/N=30 records."""
    problems = []
    cheap_by = {record.get("state_id"): record for record in cheap_records}
    gold_by = {record.get("state_id"): record for record in gold_records}
    if len(cheap_by) != len(cheap_records):
        problems.append("duplicate cheap parent state")
    if len(gold_by) != len(gold_records):
        problems.append("duplicate N=30 parent state")
    if set(cheap_by) != set(gold_by):
        problems.append("cheap/N=30 parent population mismatch")
    joined = []
    for state in audit_states:
        state_id = state.get("state_id")
        cheap = cheap_by.get(state_id)
        gold = gold_by.get(state_id)
        if cheap is None or gold is None:
            problems.append(f"{state_id}: missing parent label")
            continue
        candidates = cheap.get("candidates", [])
        cheap_i = cheap.get("cheap_selected_index")
        n30_i = gold.get("gold_reference_index")
        if cheap.get("state") != state or gold.get("state") != state:
            problems.append(f"{state_id}: audit/parent replay state drift")
        if gold.get("candidates") != candidates:
            problems.append(f"{state_id}: cheap/N=30 candidate order drift")
        if (not candidates
                or isinstance(cheap_i, bool) or not isinstance(cheap_i, int)
                or isinstance(n30_i, bool) or not isinstance(n30_i, int)
                or not 0 <= cheap_i < len(candidates)
                or not 0 <= n30_i < len(candidates)):
            problems.append(f"{state_id}: frozen parent action index")
        joined.append((state, cheap, gold))
    if problems:
        raise TeacherProtocolError(
            "audit parent join: " + "; ".join(sorted(set(problems))))
    return joined


def audit_record(cheap: dict, gold: dict, sampler,
                 counts: dict[str, int], *,
                 progress: Callable[[dict], None] | None = None) -> dict:
    """Label one frozen state against a report-LCB continuation reference."""
    state = cheap["state"]
    state_id = state["state_id"]
    selected_parent_records([state], [cheap], [gold])
    rnd = teacher_label.replay_state(state)
    seat = state["seat"]
    candidates = cheap["candidates"]
    bad = teacher_label.ballot_problems(rnd, seat, candidates)
    if bad:
        raise TeacherProtocolError(f"{state_id}: {'; '.join(bad)}")

    folds = {}
    outer_totals = Counter({
        name: 0 for name in teacher_label.SAMPLER_COUNTERS})
    inner_totals = Counter({
        name: 0 for name in teacher_label.SAMPLER_COUNTERS})
    telemetry_totals = _zero_champion_telemetry()
    started = time.perf_counter()
    for fold in ("champion_selection", "champion_report"):
        worlds, meta = teacher_label.draw_common_worlds(
            sampler, rnd, seat, counts[fold],
            experiment_id=AUDIT_ID,
            state_id=state_id,
            deal_seed=state["seed"],
            fold=fold,
        )
        outer_totals.update(meta["sampler_counters"])
        folds[fold] = score_champion_fold(
            rnd, seat, candidates, worlds, meta,
            state=state, fold=fold, progress=progress)
        inner_totals.update(folds[fold]["inner_sampler_counters"])
        telemetry_totals.update(folds[fold]["continuation_telemetry"])

    selection = folds["champion_selection"]["tensor"][
        "signed_level_utility"]
    selection_means = _matrix_means(selection)
    champion_i = max(
        range(len(candidates)), key=lambda index: (selection_means[index], -index))
    choice_indices = {
        "cheap": cheap["cheap_selected_index"],
        "n30": gold["gold_reference_index"],
    }
    report = folds["champion_report"]["tensor"]["signed_level_utility"]
    regrets = {}
    for name, choice_i in choice_indices.items():
        values = [row[champion_i] - row[choice_i] for row in report]
        regrets[name] = {
            "mean": sum(values) / len(values),
            "moments": teacher_label.paired_moments(values),
        }
    outer_work = len(candidates) * sum(counts.values())
    continuation_work = telemetry_totals["total_candidate_rollouts"]
    return {
        "state_id": state_id,
        "deal_seed": state["seed"],
        "split": state["split"],
        "kind": state["kind"],
        "stratum": {
            "phase": state["phase"],
            "role": state["role"],
            "decision": state["decision"],
        },
        "state": state,
        "replay_digest": stable_digest(state),
        "ballot_spec": cheap["ballot_spec"],
        "candidates": candidates,
        "candidate_count": len(candidates),
        "parent_record_digests": {
            "cheap": stable_digest(teacher_gate.deterministic_record(cheap)),
            "n30": stable_digest(teacher_gate.deterministic_record(gold)),
        },
        "choice_indices": choice_indices,
        "champion_reference_index": champion_i,
        "champion_selection_means": selection_means,
        "champion_report_regret": regrets,
        "folds": folds,
        "outer_sampler_counters": dict(outer_totals),
        "inner_sampler_counters": dict(inner_totals),
        "continuation_telemetry": dict(telemetry_totals),
        "outer_candidate_world_work": outer_work,
        "continuation_candidate_rollouts": continuation_work,
        "total_rollout_work": outer_work + continuation_work,
        "elapsed_seconds": time.perf_counter() - started,
    }


def _audit_fold_stream_problems(record: dict, fold_name: str,
                                fold: dict) -> list[str]:
    state = record["state"]
    expected = teacher_label.derive_stream(
        experiment_id=AUDIT_ID,
        deal_seed=state["seed"],
        state_id=state["state_id"],
        purpose="belief",
        fold=fold_name,
    )
    bad = []
    if fold.get("stream") != expected:
        bad.append(f"{fold_name} belief stream")
    expected_ids = [stable_digest({"stream": expected, "index": index})
                    for index in range(fold.get("requested_worlds", 0))]
    if fold.get("draw_ids") != expected_ids:
        bad.append(f"{fold_name} draw identity")
    return bad


def audit_record_problems(record: dict, cheap: dict, gold: dict,
                          counts: dict[str, int]) -> list[str]:
    state_id = record.get("state_id", "?")
    bad = []
    for key, expected in (
        ("state_id", cheap.get("state_id")),
        ("deal_seed", cheap.get("deal_seed")),
        ("split", cheap.get("split")),
        ("kind", cheap.get("kind")),
        ("stratum", cheap.get("stratum")),
        ("state", cheap.get("state")),
        ("replay_digest", cheap.get("replay_digest")),
        ("ballot_spec", cheap.get("ballot_spec")),
        ("candidates", cheap.get("candidates")),
        ("candidate_count", cheap.get("candidate_count")),
    ):
        if record.get(key) != expected:
            bad.append(f"{state_id}: parent {key} drift")
    candidates = record.get("candidates", [])
    try:
        rnd = teacher_label.replay_state(record["state"])
    except Exception as exc:
        return [f"{state_id}: replay {type(exc).__name__}: {exc}"]
    bad += [f"{state_id}: {problem}" for problem in
            teacher_label.ballot_problems(rnd, record["state"]["seat"], candidates)]
    expected_parent_digests = {
        "cheap": stable_digest(teacher_gate.deterministic_record(cheap)),
        "n30": stable_digest(teacher_gate.deterministic_record(gold)),
    }
    if record.get("parent_record_digests") != expected_parent_digests:
        bad.append(f"{state_id}: parent record digest")
    expected_choices = {
        "cheap": cheap.get("cheap_selected_index"),
        "n30": gold.get("gold_reference_index"),
    }
    if record.get("choice_indices") != expected_choices:
        bad.append(f"{state_id}: frozen choice index drift")

    folds = record.get("folds", {})
    outer = Counter({name: 0 for name in teacher_label.SAMPLER_COUNTERS})
    inner = Counter({name: 0 for name in teacher_label.SAMPLER_COUNTERS})
    telemetry = _zero_champion_telemetry()
    for fold_name in ("champion_selection", "champion_report"):
        fold = folds.get(fold_name, {})
        bad += [f"{state_id}/{fold_name}: {problem}" for problem in
                teacher_label.tensor_problems(
                    fold, counts[fold_name], len(candidates))]
        bad += [f"{state_id}: {problem}" for problem in
                _audit_fold_stream_problems(record, fold_name, fold)]
        counters = fold.get("sampler_counters", {})
        bad += [f"{state_id}/{fold_name}: {problem}" for problem in
                teacher_label.counter_problems(counters, counts[fold_name])]
        outer.update(counters)
        bad += [f"{state_id}/{fold_name}: {problem}" for problem in
                continuation_telemetry_problems(fold)]
        if set(fold.get("inner_sampler_counters", {})) == set(
                teacher_label.SAMPLER_COUNTERS):
            inner.update(fold["inner_sampler_counters"])
        fold_telemetry = fold.get("continuation_telemetry", {})
        if set(fold_telemetry) == set(CHAMPION_TELEMETRY_FIELDS):
            telemetry.update(fold_telemetry)
        for name in ("continuation_trace_digests", "continuation_decisions"):
            matrix = fold.get(name)
            if (not isinstance(matrix, list)
                    or len(matrix) != counts[fold_name]
                    or any(not isinstance(row, list)
                           or len(row) != len(candidates) for row in matrix)):
                bad.append(f"{state_id}/{fold_name}: {name} shape")
        decisions_matrix = fold.get("continuation_decisions")
        fold_telemetry = fold.get("continuation_telemetry", {})
        if (isinstance(decisions_matrix, list)
                and all(isinstance(row, list) for row in decisions_matrix)
                and isinstance(fold_telemetry.get("decisions"), int)
                and sum(sum(row) for row in decisions_matrix)
                != fold_telemetry["decisions"]):
            bad.append(f"{state_id}/{fold_name}: decision count/trace drift")
        if (fold.get("continuation_policy") != CONTINUATION_POLICY
                or fold.get("continuation_contract") != CONTINUATION_CONTRACT):
            bad.append(f"{state_id}/{fold_name}: continuation contract")
    if set(folds.get("champion_selection", {}).get("draw_ids", [])) & set(
            folds.get("champion_report", {}).get("draw_ids", [])):
        bad.append(f"{state_id}: champion fold draw overlap")
    if record.get("outer_sampler_counters") != dict(outer):
        bad.append(f"{state_id}: outer sampler total")
    if record.get("inner_sampler_counters") != dict(inner):
        bad.append(f"{state_id}: inner sampler total")
    if record.get("continuation_telemetry") != dict(telemetry):
        bad.append(f"{state_id}: continuation telemetry total")

    selection = folds.get("champion_selection", {}).get("tensor", {}).get(
        "signed_level_utility")
    report = folds.get("champion_report", {}).get("tensor", {}).get(
        "signed_level_utility")
    if selection and report and candidates:
        means = _matrix_means(selection)
        champion_i = max(
            range(len(candidates)), key=lambda index: (means[index], -index))
        if record.get("champion_reference_index") != champion_i:
            bad.append(f"{state_id}: champion action not frozen on selection")
        stored_means = record.get("champion_selection_means", [])
        if (len(stored_means) != len(means)
                or any(not math.isclose(a, b, rel_tol=0.0, abs_tol=1e-12)
                       for a, b in zip(stored_means, means))):
            bad.append(f"{state_id}: champion selection means")
        expected_regrets = {}
        for name, choice_i in expected_choices.items():
            if (isinstance(choice_i, bool) or not isinstance(choice_i, int)
                    or not 0 <= choice_i < len(candidates)):
                bad.append(f"{state_id}: invalid {name} choice index")
                continue
            values = [row[champion_i] - row[choice_i] for row in report]
            expected_regrets[name] = {
                "mean": sum(values) / len(values),
                "moments": teacher_label.paired_moments(values),
            }
        if record.get("champion_report_regret") != expected_regrets:
            bad.append(f"{state_id}: champion-report regret")

    expected_outer_work = len(candidates) * sum(counts.values())
    continuation_work = telemetry["total_candidate_rollouts"]
    if record.get("outer_candidate_world_work") != expected_outer_work:
        bad.append(f"{state_id}: outer candidate-world work")
    if record.get("continuation_candidate_rollouts") != continuation_work:
        bad.append(f"{state_id}: continuation candidate-rollout work")
    if record.get("total_rollout_work") != expected_outer_work + continuation_work:
        bad.append(f"{state_id}: total rollout work")
    return sorted(set(bad))


def _regret_group(records: list[dict], choice: str,
                  critical: float) -> dict:
    values = [record["champion_report_regret"][choice]["mean"]
              for record in records]
    moments = teacher_label.paired_moments(values)
    upper = moments["mean"] + critical * moments["se"]
    return {
        **moments,
        "critical": critical,
        "upper_95": upper,
        "limit": REGRET_LIMIT,
        "passed": upper <= REGRET_LIMIT,
    }


def champion_regret(records: list[dict], cheap_by: dict[str, dict],
                    gold_by: dict[str, dict]) -> dict:
    problems = []
    if len(records) != AUDIT_STATES:
        problems.append(f"audit records {len(records)}, required {AUDIT_STATES}")
    ids = [record.get("state_id") for record in records]
    deals = [record.get("deal_seed") for record in records]
    if len(ids) != len(set(ids)):
        problems.append("duplicate audit state identity")
    if len(deals) != len(set(deals)):
        problems.append("audit is not one-state-per-deal")
    for record in records:
        state_id = record.get("state_id")
        cheap = cheap_by.get(state_id)
        gold = gold_by.get(state_id)
        if cheap is None or gold is None:
            problems.append(f"{state_id}: missing exact parent")
            continue
        problems += audit_record_problems(record, cheap, gold, AUDIT_FOLDS)
    representative = [record for record in records
                      if record.get("kind") == "representative"]
    boundary = [record for record in records if record.get("kind") == "boundary"]
    uncertainty = [record for record in records
                   if record.get("kind") == "uncertainty"]
    if (len(representative), len(boundary), len(uncertainty)) != (48, 8, 8):
        problems.append("audit stratum counts are not 48/8/8")
    rep_cells = Counter(
        (record.get("stratum", {}).get("phase"),
         record.get("stratum", {}).get("role"),
         record.get("stratum", {}).get("decision"))
        for record in representative)
    for cell in REPRESENTATIVE_CELLS:
        if rep_cells[cell] != REPRESENTATIVE_PER_CELL:
            problems.append(f"audit representative cell {cell}: {rep_cells[cell]}")
    if problems:
        return {
            "passed": False,
            "inconclusive": True,
            "problems": sorted(set(problems)),
            "n_states": len(records),
            "choices": {},
        }

    choices = {}
    for choice in ("cheap", "n30"):
        choices[choice] = {
            "all_64": _regret_group(
                records, choice, T_CRITICAL_ALL_64),
            "representative_48": _regret_group(
                representative, choice, T_CRITICAL_REPRESENTATIVE_48),
            "boundary_8_diagnostic": _regret_group(
                boundary, choice, T_CRITICAL_CHALLENGE_8),
            "uncertainty_8_diagnostic": _regret_group(
                uncertainty, choice, T_CRITICAL_CHALLENGE_8),
        }
    passed = all(
        choices[choice][group]["passed"]
        for choice in ("cheap", "n30")
        for group in ("all_64", "representative_48")
    )
    return {
        "passed": passed,
        "inconclusive": False,
        "problems": [],
        "n_states": len(records),
        "choices": choices,
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


def audit_state_set_self_problems(payload: dict) -> list[str]:
    bad = []
    states = payload.get("states", [])
    if (payload.get("schema") != AUDIT_STATE_SCHEMA
            or payload.get("audit_id") != AUDIT_ID
            or payload.get("complete") is not True):
        bad.append("audit state-set identity/completion")
    if payload.get("selected") != AUDIT_STATES or len(states) != AUDIT_STATES:
        bad.append("audit state count")
    if payload.get("states_digest") != stable_digest(states):
        bad.append("audit state digest")
    if ((payload.get("stage_b_parent") or {}).get("sha256")
            != STAGE_B_STATE_SHA256):
        bad.append("audit Stage-B parent SHA-256")
    if payload.get("continuation_contract") != CONTINUATION_CONTRACT:
        bad.append("audit continuation contract")
    if payload.get("folds") != AUDIT_FOLDS:
        bad.append("audit fold contract")
    ids = [state.get("state_id") for state in states]
    deals = [state.get("seed") for state in states]
    if (len(ids) != len(set(ids)) or not all(
            isinstance(state_id, str) and state_id for state_id in ids)):
        bad.append("audit state identities")
    if (len(deals) != len(set(deals)) or not all(
            isinstance(deal, int) and not isinstance(deal, bool)
            for deal in deals)):
        bad.append("audit deal identities")
    return sorted(set(bad))


def audit_state_execution_lock_problems(payload: dict) -> list[str]:
    """Prove the outcome-blind state freeze used the registered actor bytes."""
    bad = []
    if payload.get("git") != AUDIT_STATE_FREEZE_GIT:
        bad.append("audit state-set freeze git drift")
    if payload.get("tree_dirty") is not False:
        bad.append("audit state-set freeze was dirty")
    if payload.get("source_digests") != AUDIT_STATE_SOURCE_DIGESTS:
        bad.append("audit state-set frozen source identity drift")
    if payload.get("continuation_contract") != CONTINUATION_CONTRACT:
        bad.append("audit state-set frozen continuation contract drift")
    return bad


def _ordered_items(paths: list[str], expected_sha256s: list[str],
                   manifests: list[dict], actual_sha256s: list[str],
                   *, population: str) -> tuple[list[dict], list[str]]:
    bad = []
    if not (len(paths) == len(expected_sha256s)
            == len(manifests) == len(actual_sha256s) == AUDIT_SHARDS):
        bad.append(f"{population} exact eight-artifact population")
    items = []
    for path, expected, manifest, actual in zip(
            paths, expected_sha256s, manifests, actual_sha256s):
        if not teacher_label.is_sha256(expected) or actual != expected:
            bad.append(f"{population} exact artifact SHA-256")
        items.append({
            "path": path,
            "sha256": actual,
            "shard_index": manifest.get("shard_index"),
        })
    items.sort(key=lambda item: (
        item["shard_index"] if isinstance(item["shard_index"], int) else 999))
    if [item["shard_index"] for item in items] != list(range(AUDIT_SHARDS)):
        bad.append(f"{population} shard indices")
    return items, bad


def load_parent_population(*, cheap_paths: list[str],
                           cheap_sha256s: list[str],
                           gold_paths: list[str],
                           gold_sha256s: list[str],
                           stage_b_gate_path: str,
                           stage_b_gate_sha256: str,
                           expected_states: list[dict]) -> dict:
    """Reopen and validate the complete cheap/N=30 parents and Stage-B PASS."""
    problems = []
    cheap_actual: list[str] = []
    cheap_manifests, cheap_records, cheap_bad = teacher_gate.load_shards(
        cheap_paths,
        schema=teacher_label.CHEAP_SHARD_SCHEMA,
        stage="b",
        mode="cheap",
        expected_states=expected_states,
        expected_state_sha256=STAGE_B_STATE_SHA256,
        verify_receipts=True,
        artifact_sha256s=cheap_actual,
    )
    gold_actual: list[str] = []
    gold_manifests, gold_records, gold_bad = teacher_gate.load_shards(
        gold_paths,
        schema=teacher_label.GOLD_SHARD_SCHEMA,
        stage="b",
        mode="gold",
        expected_states=expected_states,
        expected_state_sha256=STAGE_B_STATE_SHA256,
        verify_receipts=True,
        artifact_sha256s=gold_actual,
    )
    problems += cheap_bad
    problems += [f"N=30: {problem}" for problem in gold_bad]
    cheap_items, item_bad = _ordered_items(
        cheap_paths, cheap_sha256s, cheap_manifests, cheap_actual,
        population="cheap parent")
    problems += item_bad
    gold_items, item_bad = _ordered_items(
        gold_paths, gold_sha256s, gold_manifests, gold_actual,
        population="N=30 parent")
    problems += item_bad

    for record in cheap_records:
        problems += teacher_gate.cheap_record_problems(
            record, teacher_label.CHEAP_FOLDS)
    cheap_by = {record.get("state_id"): record for record in cheap_records}
    for record in gold_records:
        cheap = cheap_by.get(record.get("state_id"))
        if cheap is None:
            problems.append(f"{record.get('state_id')}: no cheap parent")
        else:
            problems += teacher_gate.gold_record_problems(
                record, cheap, teacher_label.GOLD_FOLDS)
    problems += teacher_gate.stage_contract_problems(cheap_records, "b")
    if set(cheap_by) != {record.get("state_id") for record in gold_records}:
        problems.append("cheap/N=30 complete state population mismatch")

    if cheap_manifests and gold_manifests:
        for key in (
            "git", "source_digests", "state_contract",
            "state_input_sha256", "target_schema", "packet_id",
            "capture_packet", "capture_coverage",
        ):
            if cheap_manifests[0].get(key) != gold_manifests[0].get(key):
                problems.append(f"cheap/N=30 {key} drift")
        current_sources = teacher_label.source_digests()
        if cheap_manifests[0].get("source_digests") != current_sources:
            problems.append("parent/current teacher executable source drift")
        cheap_parent_by_shard = {
            item["shard_index"]: item["sha256"] for item in cheap_items}
        for manifest in gold_manifests:
            if manifest.get("input_sha256") != cheap_parent_by_shard.get(
                    manifest.get("shard_index")):
                problems.append("N=30 shard exact cheap-parent drift")

    try:
        stage_b_gate, actual_gate_sha = teacher_gate.load_json_artifact(
            stage_b_gate_path)
    except Exception as exc:
        stage_b_gate = {}
        actual_gate_sha = None
        problems.append(
            f"Stage-B gate unreadable: {type(exc).__name__}: {exc}")
    if (not teacher_label.is_sha256(stage_b_gate_sha256)
            or actual_gate_sha != stage_b_gate_sha256):
        problems.append("Stage-B gate exact SHA-256")
    if (stage_b_gate.get("schema") != teacher_gate.GATE_SCHEMA
            or stage_b_gate.get("stage") != "B"
            or stage_b_gate.get("complete") is not True
            or stage_b_gate.get("verdict") != "PASS"
            or stage_b_gate.get("stage_c_authorized") is not True
            or (stage_b_gate.get("regret") or {}).get("passed") is not True):
        problems.append("Stage-B terminal PASS/authorization")
    if (stage_b_gate.get("state_set") or {}).get("sha256") \
            != STAGE_B_STATE_SHA256:
        problems.append("Stage-B gate exact state-set parent")
    if stage_b_gate.get("cheap_inputs") != cheap_items:
        problems.append("Stage-B gate/receipt cheap population drift")
    if stage_b_gate.get("gold_inputs") != gold_items:
        problems.append("Stage-B gate/receipt N=30 population drift")
    problems += teacher_gate.artifact_drift_problems(
        cheap_paths, cheap_actual, population="audit cheap parent")
    problems += teacher_gate.artifact_drift_problems(
        gold_paths, gold_actual, population="audit N=30 parent")
    if problems:
        raise TeacherProtocolError(
            "audit parent population: " + "; ".join(sorted(set(problems))))
    gold_by = {record["state_id"]: record for record in gold_records}
    return {
        "cheap_items": cheap_items,
        "gold_items": gold_items,
        "cheap_records": cheap_records,
        "gold_records": gold_records,
        "cheap_by": cheap_by,
        "gold_by": gold_by,
        "stage_b_gate": stage_b_gate,
        "stage_b_gate_item": {
            "path": stage_b_gate_path,
            "sha256": stage_b_gate_sha256,
        },
    }


def load_audit_context(*, stage_b_state_set_path: str,
                       stage_b_state_set_sha256: str,
                       audit_state_set_path: str,
                       audit_state_set_sha256: str,
                       cheap_paths: list[str], cheap_sha256s: list[str],
                       gold_paths: list[str], gold_sha256s: list[str],
                       stage_b_gate_path: str,
                       stage_b_gate_sha256: str,
                       smoke: bool) -> dict:
    if stage_b_state_set_sha256 != STAGE_B_STATE_SHA256:
        raise TeacherProtocolError("audit Stage-B state-set SHA drift")
    stage_b = teacher_label.load_pinned(
        stage_b_state_set_path, stage_b_state_set_sha256)
    bad = teacher_label.state_set_problems(stage_b, "b", smoke=smoke)
    if not smoke:
        bad += teacher_states.state_set_packet_problems(stage_b)
    audit_states = teacher_label.load_pinned(
        audit_state_set_path, audit_state_set_sha256)
    bad += audit_state_set_problems(
        audit_states, stage_b, stage_b_state_set_sha256)
    bad += audit_state_set_self_problems(audit_states)
    if not smoke:
        if audit_state_set_sha256 != AUDIT_STATE_SHA256:
            bad.append("audit state set is not the registered frozen asset")
        bad += audit_state_execution_lock_problems(audit_states)
    if bad:
        raise TeacherProtocolError(
            "audit state lineage: " + "; ".join(sorted(set(bad))))
    parents = load_parent_population(
        cheap_paths=cheap_paths,
        cheap_sha256s=cheap_sha256s,
        gold_paths=gold_paths,
        gold_sha256s=gold_sha256s,
        stage_b_gate_path=stage_b_gate_path,
        stage_b_gate_sha256=stage_b_gate_sha256,
        expected_states=stage_b.get("states", []),
    )
    joined = selected_parent_records(
        audit_states["states"], parents["cheap_records"],
        parents["gold_records"])
    return {
        "stage_b_state_set": stage_b,
        "audit_state_set": audit_states,
        "parents": parents,
        "joined": joined,
    }


def audit_receipt_problems(payload: dict, *, runtime: dict,
                           sources: dict[str, str]) -> list[str]:
    bad = []
    if (payload.get("schema") != AUDIT_RECEIPT_SCHEMA
            or payload.get("audit_id") != AUDIT_ID
            or payload.get("complete") is not True):
        bad.append("audit receipt identity/completion")
    if not teacher_label.is_run_id(payload.get("run_id")):
        bad.append("audit receipt run id")
    if not teacher_label.is_sha256(payload.get("nonce")):
        bad.append("audit receipt nonce")
    if payload.get("shard_count") != AUDIT_SHARDS:
        bad.append("audit receipt shard count")
    if payload.get("folds") != AUDIT_FOLDS:
        bad.append("audit receipt fold dose")
    if payload.get("continuation_contract") != CONTINUATION_CONTRACT:
        bad.append("audit receipt continuation contract")
    if payload.get("continuation_execution_lock") != \
            CONTINUATION_EXECUTION_LOCK:
        bad.append("audit receipt continuation execution lock")
    if payload.get("state_selection_read_label_outcomes") is not False:
        bad.append("audit receipt outcome-blind state-selection claim")
    for key in RUNTIME_BINDING_FIELDS:
        if payload.get(key) != runtime.get(key):
            bad.append(f"audit receipt/runtime {key} drift")
    if payload.get("source_digests") != sources:
        bad.append("audit receipt executable source drift")
    stage_b = payload.get("stage_b_state_set", {})
    audit_states = payload.get("audit_state_set", {})
    stage_b_gate = payload.get("stage_b_gate", {})
    if stage_b.get("sha256") != STAGE_B_STATE_SHA256:
        bad.append("audit receipt Stage-B state set")
    for name, binding in (
        ("audit state set", audit_states),
        ("Stage-B gate", stage_b_gate),
    ):
        if (not isinstance(binding.get("path"), str)
                or not teacher_label.is_sha256(binding.get("sha256"))):
            bad.append(f"audit receipt {name} binding")
    for name in ("cheap_inputs", "n30_inputs"):
        items = payload.get(name, [])
        if (not isinstance(items, list) or len(items) != AUDIT_SHARDS
                or [item.get("shard_index") for item in items]
                != list(range(AUDIT_SHARDS))
                or any(not isinstance(item.get("path"), str)
                       or not teacher_label.is_sha256(item.get("sha256"))
                       for item in items)):
            bad.append(f"audit receipt {name}")
    return sorted(set(bad))


def context_from_receipt(receipt: dict, *, smoke: bool) -> dict:
    cheap_items = receipt.get("cheap_inputs", [])
    n30_items = receipt.get("n30_inputs", [])
    return load_audit_context(
        stage_b_state_set_path=receipt["stage_b_state_set"]["path"],
        stage_b_state_set_sha256=receipt["stage_b_state_set"]["sha256"],
        audit_state_set_path=receipt["audit_state_set"]["path"],
        audit_state_set_sha256=receipt["audit_state_set"]["sha256"],
        cheap_paths=[item["path"] for item in cheap_items],
        cheap_sha256s=[item["sha256"] for item in cheap_items],
        gold_paths=[item["path"] for item in n30_items],
        gold_sha256s=[item["sha256"] for item in n30_items],
        stage_b_gate_path=receipt["stage_b_gate"]["path"],
        stage_b_gate_sha256=receipt["stage_b_gate"]["sha256"],
        smoke=smoke,
    )


def load_audit_receipt(path: str, expected_sha256: str, *, runtime: dict,
                       sources: dict[str, str], smoke: bool
                       ) -> tuple[dict, dict, dict]:
    receipt = teacher_label.load_pinned(path, expected_sha256)
    bad = audit_receipt_problems(receipt, runtime=runtime, sources=sources)
    if bad:
        raise TeacherProtocolError(
            "audit receipt contract: " + "; ".join(bad))
    context = context_from_receipt(receipt, smoke=smoke)
    binding = {
        "path": path,
        "sha256": expected_sha256,
        "run_id": receipt["run_id"],
        "nonce": receipt["nonce"],
    }
    return receipt, binding, context


def create_receipt(args) -> None:
    runtime = runtime_contract(smoke=args.smoke)
    sources = source_digests()
    if not teacher_label.is_run_id(args.run_id):
        raise TeacherProtocolError("audit receipt run id must be 8-128 safe chars")
    context = load_audit_context(
        stage_b_state_set_path=args.stage_b_state_set,
        stage_b_state_set_sha256=args.expected_stage_b_state_set_sha256,
        audit_state_set_path=args.audit_state_set,
        audit_state_set_sha256=args.expected_audit_state_set_sha256,
        cheap_paths=args.cheap,
        cheap_sha256s=args.expected_cheap_sha256,
        gold_paths=args.n30,
        gold_sha256s=args.expected_n30_sha256,
        stage_b_gate_path=args.stage_b_gate,
        stage_b_gate_sha256=args.expected_stage_b_gate_sha256,
        smoke=args.smoke,
    )
    parents = context["parents"]
    payload = {
        "schema": AUDIT_RECEIPT_SCHEMA,
        "audit_id": AUDIT_ID,
        "complete": True,
        "run_id": args.run_id,
        "nonce": secrets.token_hex(32),
        "created_time_ns": time.time_ns(),
        "creator_pid": os.getpid(),
        "shard_count": AUDIT_SHARDS,
        "folds": AUDIT_FOLDS,
        "continuation_contract": CONTINUATION_CONTRACT,
        "continuation_execution_lock": CONTINUATION_EXECUTION_LOCK,
        "state_selection_read_label_outcomes": False,
        **runtime,
        "source_digests": sources,
        "stage_b_state_set": {
            "path": args.stage_b_state_set,
            "sha256": args.expected_stage_b_state_set_sha256,
        },
        "audit_state_set": {
            "path": args.audit_state_set,
            "sha256": args.expected_audit_state_set_sha256,
        },
        "stage_b_gate": parents["stage_b_gate_item"],
        "cheap_inputs": parents["cheap_items"],
        "n30_inputs": parents["gold_items"],
    }
    bad = audit_receipt_problems(payload, runtime=runtime, sources=sources)
    if bad:
        raise TeacherProtocolError(
            "audit receipt candidate: " + "; ".join(bad))
    frozen_context_digest = stable_digest({
        "audit_states": context["audit_state_set"],
        "cheap_items": parents["cheap_items"],
        "n30_items": parents["gold_items"],
        "stage_b_gate": parents["stage_b_gate_item"],
    })

    def verify() -> None:
        reopened = teacher_label.load_pinned(args.out, sha256_file(
            args.out + ".partial"))
        if reopened != payload:
            raise TeacherProtocolError("published audit receipt bytes drift")
        if runtime_contract(smoke=args.smoke) != runtime:
            raise TeacherProtocolError("audit receipt runtime changed")
        if source_digests() != sources:
            raise TeacherProtocolError("audit receipt sources changed")
        current = context_from_receipt(reopened, smoke=args.smoke)
        current_digest = stable_digest({
            "audit_states": current["audit_state_set"],
            "cheap_items": current["parents"]["cheap_items"],
            "n30_items": current["parents"]["gold_items"],
            "stage_b_gate": current["parents"]["stage_b_gate_item"],
        })
        if current_digest != frozen_context_digest:
            raise TeacherProtocolError("audit receipt inputs changed")

    teacher_label.write_complete(args.out, payload, verify=verify)
    print(json.dumps({
        "audit_id": AUDIT_ID,
        "mode": "receipt",
        "out": args.out,
        "run_id": args.run_id,
    }, sort_keys=True), flush=True)


def deterministic_audit_record(record: dict) -> dict:
    out = dict(record)
    out.pop("elapsed_seconds", None)
    return out


def audit_records_digest(records: list[dict]) -> str:
    return stable_digest([
        deterministic_audit_record(record) for record in records])


def audit_shard_problems(payload: dict, *, receipt: dict,
                         receipt_binding: dict, context: dict,
                         runtime: dict, sources: dict[str, str],
                         smoke: bool) -> list[str]:
    bad = []
    if (payload.get("schema") != AUDIT_SHARD_SCHEMA
            or payload.get("audit_id") != AUDIT_ID
            or payload.get("complete") is not True):
        bad.append("audit shard identity/completion")
    if payload.get("producer_run_id") != receipt.get("run_id"):
        bad.append("audit shard producer run")
    if payload.get("producer_receipt") != receipt_binding:
        bad.append("audit shard receipt binding")
    fold_counts = payload.get("folds_contract")
    if (not isinstance(fold_counts, dict)
            or set(fold_counts) != set(AUDIT_FOLDS)
            or any(isinstance(value, bool) or not isinstance(value, int)
                   or value <= 0 for value in fold_counts.values())
            or (not smoke and fold_counts != AUDIT_FOLDS)):
        bad.append("audit shard fold contract")
        fold_counts = AUDIT_FOLDS
    if payload.get("continuation_contract") != CONTINUATION_CONTRACT:
        bad.append("audit shard continuation contract")
    if payload.get("continuation_execution_lock") != \
            CONTINUATION_EXECUTION_LOCK:
        bad.append("audit shard continuation execution lock")
    if payload.get("target_schema") != teacher_label.TARGET_SCHEMA:
        bad.append("audit shard target schema")
    for key in RUNTIME_BINDING_FIELDS:
        if payload.get(key) != runtime.get(key):
            bad.append(f"audit shard/runtime {key} drift")
    if payload.get("source_digests") != sources:
        bad.append("audit shard executable source drift")
    parents = context["parents"]
    if payload.get("audit_state_set") != receipt.get("audit_state_set"):
        bad.append("audit shard state-set binding")
    if payload.get("stage_b_gate") != parents["stage_b_gate_item"]:
        bad.append("audit shard Stage-B gate binding")
    if payload.get("cheap_inputs") != parents["cheap_items"]:
        bad.append("audit shard cheap population binding")
    if payload.get("n30_inputs") != parents["gold_items"]:
        bad.append("audit shard N=30 population binding")

    shard_index = payload.get("shard_index")
    shard_count = payload.get("shard_count")
    if (isinstance(shard_index, bool) or not isinstance(shard_index, int)
            or isinstance(shard_count, bool) or not isinstance(shard_count, int)
            or not 0 <= shard_index < shard_count):
        bad.append("audit shard index/count")
        expected_states = []
    else:
        if not smoke and shard_count != AUDIT_SHARDS:
            bad.append("real audit shard count")
        expected_states = teacher_label.canonical_state_partition(
            context["audit_state_set"]["states"], shard_index, shard_count)
    expected_ids = [state["state_id"] for state in expected_states]
    records = payload.get("records", [])
    record_ids = [record.get("state_id") for record in records]
    partition = payload.get("state_partition", {})
    if (record_ids != expected_ids
            or partition.get("assignment")
            != "sorted_state_id_then_interleaved_position"
            or partition.get("shard_index") != shard_index
            or partition.get("shard_count") != shard_count
            or partition.get("state_ids") != expected_ids
            or partition.get("state_ids_sha256") != stable_digest(expected_ids)):
        bad.append("audit shard exact state partition")
    if payload.get("n_records") != len(records):
        bad.append("audit shard record count")
    if not smoke and len(records) != AUDIT_STATES // AUDIT_SHARDS:
        bad.append("real audit records per shard")
    if payload.get("records_digest") != audit_records_digest(records):
        bad.append("audit shard records digest")

    outer = Counter({name: 0 for name in teacher_label.SAMPLER_COUNTERS})
    inner = Counter({name: 0 for name in teacher_label.SAMPLER_COUNTERS})
    telemetry = _zero_champion_telemetry()
    for record in records:
        state_id = record.get("state_id")
        cheap = parents["cheap_by"].get(state_id)
        gold = parents["gold_by"].get(state_id)
        if cheap is None or gold is None:
            bad.append(f"{state_id}: audit shard missing exact parent")
            continue
        bad += audit_record_problems(record, cheap, gold, fold_counts)
        if set(record.get("outer_sampler_counters", {})) == set(
                teacher_label.SAMPLER_COUNTERS):
            outer.update(record["outer_sampler_counters"])
        if set(record.get("inner_sampler_counters", {})) == set(
                teacher_label.SAMPLER_COUNTERS):
            inner.update(record["inner_sampler_counters"])
        if set(record.get("continuation_telemetry", {})) == set(
                CHAMPION_TELEMETRY_FIELDS):
            telemetry.update(record["continuation_telemetry"])
    if payload.get("outer_sampler_counters") != dict(outer):
        bad.append("audit shard outer sampler totals")
    if payload.get("inner_sampler_counters") != dict(inner):
        bad.append("audit shard inner sampler totals")
    if payload.get("continuation_telemetry") != dict(telemetry):
        bad.append("audit shard continuation telemetry totals")
    for field in (
        "outer_candidate_world_work", "continuation_candidate_rollouts",
        "total_rollout_work",
    ):
        if payload.get(field) != sum(record.get(field, -1)
                                     for record in records):
            bad.append(f"audit shard {field}")
    return sorted(set(bad))


def label_shard(args) -> None:
    runtime = runtime_contract(smoke=args.smoke)
    sources = source_digests()
    if not 0 <= args.shard_index < args.shard_count:
        raise TeacherProtocolError("invalid audit shard index/count")
    if not args.smoke and args.shard_count != AUDIT_SHARDS:
        raise TeacherProtocolError(
            f"real audit requires exactly {AUDIT_SHARDS} shards")
    counts = {
        "champion_selection": args.selection_worlds,
        "champion_report": args.report_worlds,
    }
    if not args.smoke and counts != AUDIT_FOLDS:
        raise TeacherProtocolError("real audit requires exact 32/32 folds")
    receipt, binding, context = load_audit_receipt(
        args.receipt, args.expected_receipt_sha256,
        runtime=runtime, sources=sources, smoke=args.smoke)
    if args.shard_count != receipt.get("shard_count"):
        raise TeacherProtocolError("audit shard/receipt count drift")
    selected_states = teacher_label.canonical_state_partition(
        context["audit_state_set"]["states"],
        args.shard_index, args.shard_count)
    joined_by = {
        state["state_id"]: (cheap, gold)
        for state, cheap, gold in context["joined"]}
    sampler = make_bot(CONTINUATION_POLICY, seed=1)

    def emit_progress(fields: dict) -> None:
        print(json.dumps({
            "event": "teacher-v1-champion-audit-progress",
            "audit_id": AUDIT_ID,
            "shard_index": args.shard_index,
            "shard_count": args.shard_count,
            **fields,
        }, sort_keys=True), flush=True)

    records = []
    for state_index, state in enumerate(selected_states, 1):
        cheap, gold = joined_by[state["state_id"]]
        records.append(audit_record(
            cheap, gold, sampler, counts, progress=emit_progress))
        emit_progress({
            "kind": "state",
            "state_id": state["state_id"],
            "states_complete": state_index,
            "states_total": len(selected_states),
        })
    outer = Counter({name: 0 for name in teacher_label.SAMPLER_COUNTERS})
    inner = Counter({name: 0 for name in teacher_label.SAMPLER_COUNTERS})
    telemetry = _zero_champion_telemetry()
    for record in records:
        outer.update(record["outer_sampler_counters"])
        inner.update(record["inner_sampler_counters"])
        telemetry.update(record["continuation_telemetry"])
    payload = teacher_label.json_canonical({
        "schema": AUDIT_SHARD_SCHEMA,
        "audit_id": AUDIT_ID,
        "complete": True,
        **runtime,
        "source_digests": sources,
        "target_schema": teacher_label.TARGET_SCHEMA,
        "producer_run_id": receipt["run_id"],
        "producer_receipt": binding,
        "audit_state_set": receipt["audit_state_set"],
        "stage_b_gate": context["parents"]["stage_b_gate_item"],
        "cheap_inputs": context["parents"]["cheap_items"],
        "n30_inputs": context["parents"]["gold_items"],
        "folds_contract": counts,
        "continuation_contract": CONTINUATION_CONTRACT,
        "continuation_execution_lock": CONTINUATION_EXECUTION_LOCK,
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "state_partition": {
            "assignment": "sorted_state_id_then_interleaved_position",
            "shard_index": args.shard_index,
            "shard_count": args.shard_count,
            "state_ids": [record["state_id"] for record in records],
            "state_ids_sha256": stable_digest(
                [record["state_id"] for record in records]),
        },
        "n_records": len(records),
        "records": records,
        "records_digest": audit_records_digest(records),
        "outer_sampler_counters": dict(outer),
        "inner_sampler_counters": dict(inner),
        "continuation_telemetry": dict(telemetry),
        "outer_candidate_world_work": sum(
            record["outer_candidate_world_work"] for record in records),
        "continuation_candidate_rollouts": sum(
            record["continuation_candidate_rollouts"] for record in records),
        "total_rollout_work": sum(
            record["total_rollout_work"] for record in records),
        "measured_record_seconds": sum(
            record["elapsed_seconds"] for record in records),
    })
    bad = audit_shard_problems(
        payload, receipt=receipt, receipt_binding=binding, context=context,
        runtime=runtime, sources=sources, smoke=args.smoke)
    if bad:
        raise TeacherProtocolError(
            "audit shard candidate: " + "; ".join(bad))
    frozen_context_digest = stable_digest({
        "receipt": receipt,
        "audit_states": context["audit_state_set"],
        "parents": {
            "cheap": context["parents"]["cheap_items"],
            "n30": context["parents"]["gold_items"],
            "gate": context["parents"]["stage_b_gate_item"],
        },
    })

    def verify() -> None:
        reopened = teacher_label.load_pinned(
            args.out, sha256_file(args.out + ".partial"))
        if reopened != payload:
            raise TeacherProtocolError("published audit shard bytes drift")
        current_receipt, current_binding, current_context = load_audit_receipt(
            args.receipt, args.expected_receipt_sha256,
            runtime=runtime_contract(smoke=args.smoke),
            sources=source_digests(), smoke=args.smoke)
        current_digest = stable_digest({
            "receipt": current_receipt,
            "audit_states": current_context["audit_state_set"],
            "parents": {
                "cheap": current_context["parents"]["cheap_items"],
                "n30": current_context["parents"]["gold_items"],
                "gate": current_context["parents"]["stage_b_gate_item"],
            },
        })
        if current_digest != frozen_context_digest:
            raise TeacherProtocolError("audit shard inputs changed")
        published_bad = audit_shard_problems(
            reopened, receipt=current_receipt,
            receipt_binding=current_binding, context=current_context,
            runtime=runtime, sources=sources, smoke=args.smoke)
        if published_bad:
            raise TeacherProtocolError(
                "published audit shard: " + "; ".join(published_bad))

    teacher_label.write_complete(args.out, payload, verify=verify)
    print(json.dumps({
        "audit_id": AUDIT_ID,
        "mode": "label",
        "out": args.out,
        "shard_index": args.shard_index,
        "records": len(records),
        "records_digest": payload["records_digest"],
    }, sort_keys=True), flush=True)


def load_audit_shards(paths: list[str], expected_sha256s: list[str], *,
                      receipt: dict, receipt_binding: dict, context: dict,
                      runtime: dict, sources: dict[str, str], smoke: bool
                      ) -> tuple[list[dict], list[dict], list[dict], list[str]]:
    manifests = []
    actual_sha256s = []
    problems = []
    if len(paths) != len(expected_sha256s):
        problems.append("audit shard path/hash population")
    for path, expected in zip(paths, expected_sha256s):
        try:
            manifest, actual = teacher_gate.load_json_artifact(path)
        except Exception as exc:
            problems.append(
                f"{path}: unreadable: {type(exc).__name__}: {exc}")
            continue
        manifests.append(manifest)
        actual_sha256s.append(actual)
        if not teacher_label.is_sha256(expected) or actual != expected:
            problems.append(f"{path}: exact SHA-256")
        problems += [f"{path}: {problem}" for problem in
                     audit_shard_problems(
                         manifest, receipt=receipt,
                         receipt_binding=receipt_binding, context=context,
                         runtime=runtime, sources=sources, smoke=smoke)]
    items, item_bad = _ordered_items(
        paths, expected_sha256s, manifests, actual_sha256s,
        population="champion audit shard")
    problems += item_bad
    if not smoke and len(manifests) != AUDIT_SHARDS:
        problems.append("champion audit exact eight shards")
    indices = [manifest.get("shard_index") for manifest in manifests]
    if sorted(index for index in indices if isinstance(index, int)) != \
            list(range(len(manifests))):
        problems.append("champion audit shard indices")
    if manifests:
        first = manifests[0]
        for manifest in manifests[1:]:
            for key in (
                "audit_id", "git", "tree_dirty", "promotable", "host",
                "python", "fast_engine", "require_voids",
                "experimental_sampler_ballot_flags", "source_digests",
                "target_schema", "producer_run_id", "producer_receipt",
                "audit_state_set", "stage_b_gate", "cheap_inputs",
                "n30_inputs", "folds_contract", "continuation_contract",
                "continuation_execution_lock", "shard_count",
            ):
                if manifest.get(key) != first.get(key):
                    problems.append(f"audit shard {key} drift")
    records = [record for manifest in manifests
               for record in manifest.get("records", [])]
    ids = [record.get("state_id") for record in records]
    if len(ids) != len(set(ids)):
        problems.append("duplicate state across audit shards")
    expected_ids = {state["state_id"]
                    for state in context["audit_state_set"]["states"]}
    if set(ids) != expected_ids:
        problems.append("audit shards do not cover exact frozen state set")
    problems += teacher_gate.artifact_drift_problems(
        paths, actual_sha256s, population="champion audit shard")
    return manifests, records, items, sorted(set(problems))


def build_gate_payload(*, receipt: dict, receipt_binding: dict,
                       context: dict, shard_items: list[dict],
                       manifests: list[dict], records: list[dict],
                       input_problems: list[str], runtime: dict,
                       sources: dict[str, str]) -> dict:
    parents = context["parents"]
    regret = champion_regret(
        records, parents["cheap_by"], parents["gold_by"])
    problems = sorted(set(input_problems + regret.get("problems", [])))
    passed = not problems and regret.get("passed") is True
    verdict = "PASS" if passed else (
        "INCONCLUSIVE" if problems or regret.get("inconclusive") else "FAIL")
    return {
        "schema": AUDIT_GATE_SCHEMA,
        "audit_id": AUDIT_ID,
        "complete": True,
        "terminal": True,
        "extension_authorized": False,
        **runtime,
        "source_digests": sources,
        "verdict": verdict,
        "champion_fidelity_qualified": passed,
        "stage_c_authorized": passed,
        "problems": problems,
        "regret": regret,
        "n_states": len(records),
        "producer_run_id": receipt["run_id"],
        "producer_receipt": receipt_binding,
        "audit_state_set": receipt["audit_state_set"],
        "stage_b_state_set": receipt["stage_b_state_set"],
        "stage_b_gate": parents["stage_b_gate_item"],
        "cheap_inputs": parents["cheap_items"],
        "n30_inputs": parents["gold_items"],
        "inputs": shard_items,
        "folds_contract": AUDIT_FOLDS,
        "continuation_contract": CONTINUATION_CONTRACT,
        "continuation_execution_lock": CONTINUATION_EXECUTION_LOCK,
        "outer_candidate_world_work": sum(
            manifest.get("outer_candidate_world_work", 0)
            for manifest in manifests),
        "continuation_candidate_rollouts": sum(
            manifest.get("continuation_candidate_rollouts", 0)
            for manifest in manifests),
        "total_rollout_work": sum(
            manifest.get("total_rollout_work", 0)
            for manifest in manifests),
    }


def gate_payload_problems(payload: dict, expected: dict) -> list[str]:
    bad = []
    if payload != expected:
        bad.append("audit gate full recomputation drift")
    if (payload.get("schema") != AUDIT_GATE_SCHEMA
            or payload.get("audit_id") != AUDIT_ID
            or payload.get("complete") is not True
            or payload.get("terminal") is not True
            or payload.get("extension_authorized") is not False):
        bad.append("audit gate identity/terminal contract")
    passed = (not payload.get("problems")
              and (payload.get("regret") or {}).get("passed") is True)
    expected_verdict = "PASS" if passed else (
        "INCONCLUSIVE" if payload.get("problems")
        or (payload.get("regret") or {}).get("inconclusive") else "FAIL")
    if (payload.get("verdict") != expected_verdict
            or payload.get("champion_fidelity_qualified") is not passed
            or payload.get("stage_c_authorized") is not passed):
        bad.append("audit gate verdict/authorization")
    return sorted(set(bad))


def run_gate(args) -> str:
    runtime = runtime_contract(smoke=args.smoke)
    sources = source_digests()
    receipt, binding, context = load_audit_receipt(
        args.receipt, args.expected_receipt_sha256,
        runtime=runtime, sources=sources, smoke=args.smoke)
    manifests, records, items, problems = load_audit_shards(
        args.input, args.expected_input_sha256,
        receipt=receipt, receipt_binding=binding, context=context,
        runtime=runtime, sources=sources, smoke=args.smoke)
    payload = build_gate_payload(
        receipt=receipt, receipt_binding=binding, context=context,
        shard_items=items, manifests=manifests, records=records,
        input_problems=problems, runtime=runtime, sources=sources)
    frozen_payload = payload

    def verify() -> None:
        reopened = teacher_label.load_pinned(
            args.out, sha256_file(args.out + ".partial"))
        current_runtime = runtime_contract(smoke=args.smoke)
        current_sources = source_digests()
        current_receipt, current_binding, current_context = load_audit_receipt(
            args.receipt, args.expected_receipt_sha256,
            runtime=current_runtime, sources=current_sources,
            smoke=args.smoke)
        (current_manifests, current_records, current_items,
         current_problems) = load_audit_shards(
            args.input, args.expected_input_sha256,
            receipt=current_receipt, receipt_binding=current_binding,
            context=current_context, runtime=current_runtime,
            sources=current_sources, smoke=args.smoke)
        expected = build_gate_payload(
            receipt=current_receipt, receipt_binding=current_binding,
            context=current_context, shard_items=current_items,
            manifests=current_manifests, records=current_records,
            input_problems=current_problems, runtime=current_runtime,
            sources=current_sources)
        bad = gate_payload_problems(reopened, expected)
        if reopened != frozen_payload:
            bad.append("audit gate changed during publication")
        if bad:
            raise TeacherProtocolError(
                "published audit gate: " + "; ".join(sorted(set(bad))))

    teacher_label.write_complete(args.out, payload, verify=verify)
    print(json.dumps(payload, indent=2, sort_keys=True), flush=True)
    return payload["verdict"]


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
    receipt = sub.add_parser("receipt")
    receipt.add_argument("--run-id", required=True)
    receipt.add_argument("--stage-b-state-set", required=True)
    receipt.add_argument(
        "--expected-stage-b-state-set-sha256", required=True)
    receipt.add_argument("--audit-state-set", required=True)
    receipt.add_argument(
        "--expected-audit-state-set-sha256", required=True)
    receipt.add_argument("--stage-b-gate", required=True)
    receipt.add_argument("--expected-stage-b-gate-sha256", required=True)
    receipt.add_argument("--cheap", action="append", required=True)
    receipt.add_argument(
        "--expected-cheap-sha256", action="append", required=True)
    receipt.add_argument("--n30", action="append", required=True)
    receipt.add_argument(
        "--expected-n30-sha256", action="append", required=True)
    receipt.add_argument("--out", required=True)
    receipt.add_argument("--smoke", action="store_true")
    label = sub.add_parser("label")
    label.add_argument("--receipt", required=True)
    label.add_argument("--expected-receipt-sha256", required=True)
    label.add_argument("--shard-index", type=int, required=True)
    label.add_argument("--shard-count", type=int, default=AUDIT_SHARDS)
    label.add_argument(
        "--selection-worlds", type=int,
        default=AUDIT_FOLDS["champion_selection"])
    label.add_argument(
        "--report-worlds", type=int,
        default=AUDIT_FOLDS["champion_report"])
    label.add_argument("--out", required=True)
    label.add_argument("--smoke", action="store_true")
    gate = sub.add_parser("gate")
    gate.add_argument("--receipt", required=True)
    gate.add_argument("--expected-receipt-sha256", required=True)
    gate.add_argument("--input", action="append", required=True)
    gate.add_argument(
        "--expected-input-sha256", action="append", required=True)
    gate.add_argument("--out", required=True)
    gate.add_argument("--smoke", action="store_true")
    return ap


def main() -> None:
    args = parser().parse_args()
    try:
        if args.mode == "freeze":
            freeze(args)
        elif args.mode == "receipt":
            create_receipt(args)
        elif args.mode == "label":
            label_shard(args)
        else:
            verdict = run_gate(args)
            if verdict != "PASS":
                raise SystemExit(4)
    except (KeyError, OSError, TypeError, ValueError,
            TeacherProtocolError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3)


if __name__ == "__main__":
    main()

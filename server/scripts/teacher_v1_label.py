"""Fail-closed teacher-v1 cheap and gold continuation labeller.

The expensive 2,048-state wave is deliberately not a mode in this script.
It implements only the two entry gates from ``TEACHER_V1_SPEC.md``:

* ``cheap`` labels a frozen Stage-A (64) or Stage-B (128) state set with 256
  selection plus 256 report common worlds and deterministic heuristic
  continuation.
* ``gold`` reads a completed 128-state cheap shard and adds 64 gold-selection
  plus 64 gold-report worlds using production ``mc-strong`` N=30 for every
  downstream partial-information decision.

Real runs require a clean tree, compiled engine, strict void sampling, exact
registered counts and a pinned input digest.  Output is an exclusive atomic
completion marker; a short/rejected/illegal row leaves no final artifact.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shengji.ai.memory import Memory                              # noqa: E402
from shengji.ai.registry import make_bot                          # noqa: E402
from shengji.engine.ballot import mc_ballot                       # noqa: E402
from shengji.engine.round import Round, Trick, TrickPlay          # noqa: E402
from shengji.teacher_v1 import (CAPTURE_PACKET_ID, CAPTURE_PYTHON,   # noqa: E402
                                CAPTURE_SEED_END, CAPTURE_SHARDS,
                                CHEAP_FOLDS, CHEAP_SHARD_SCHEMA,
                                EXPERIMENT, EXPERIMENTAL_SAMPLER_BALLOT_FLAGS,
                                GOLD_FOLDS,
                                GOLD_SHARD_SCHEMA,
                                PRODUCER_RECEIPT_SCHEMA,
                                REPRESENTATIVE_CELLS, SEED_START,
                                SAMPLER_COUNTERS, STAGE_A_OTHER_STATES,
                                STAGE_A_REPRESENTATIVE_PER_CELL,
                                STAGE_A_STATES, STAGE_B_STATES,
                                STAGE_B_BOUNDARY_STATES,
                                STAGE_B_REPRESENTATIVE_PER_CELL,
                                STAGE_B_UNCERTAINTY_STATES,
                                STATE_SET_SCHEMA, TeacherProtocolError,
                                TARGET_SCHEMA,
                                action_key, ballot_problems,
                                canonical_state_partition,
                                capture_coverage, capture_packet,
                                counter_problems, derive_stream,
                                is_run_id, is_sha256,
                                paired_moments, replay_state,
                                sampler_delta, sampler_snapshot,
                                stable_digest, targets, tensor_problems)


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
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def source_digests() -> dict[str, str]:
    """Executable boundaries for state, ballot, sampler and continuations."""
    import shengji.ai.heuristic as heuristic
    import shengji.ai.mcbot as mcbot
    import shengji.ai.memory as memory
    import shengji.ai.registry as registry
    import shengji.engine.combos as combos
    import shengji.engine.fast as fast
    import shengji.engine.legal as legal
    import shengji.engine.round as round_mod
    import shengji.rl.actions as rl_actions
    import shengji.rl.encode as rl_encode
    import shengji.teacher_v1 as teacher

    paths = {
        "label_script": __file__,
        "producer_receipt_script": Path(__file__).with_name(
            "teacher_v1_receipt.py"),
        "teacher_contract": teacher.__file__,
        "mcbot_sampler": mcbot.__file__,
        "memory": memory.__file__,
        "registry": registry.__file__,
        "heuristic_continuation": heuristic.__file__,
        "engine_round": round_mod.__file__,
        "engine_legal": legal.__file__,
        "engine_combos": combos.__file__,
        "fast_router": fast.__file__,
        "state_freezer": Path(__file__).with_name("teacher_v1_states.py"),
        "action_enumerator": rl_actions.__file__,
        "action_encoder": rl_encode.__file__,
    }
    if not fast.HAVE_FAST or fast._fast is None:
        raise TeacherProtocolError("compiled engine is unavailable")
    paths["compiled_engine"] = fast._fast.__file__
    return {name: sha256_file(path) for name, path in sorted(paths.items())}


def runtime_contract(smoke: bool) -> dict:
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise TeacherProtocolError("set SHENGJI_REQUIRE_VOIDS=1")
    if os.environ.get("SHENGJI_FAST") != "1":
        raise TeacherProtocolError("set SHENGJI_FAST=1")
    enabled = [name for name in EXPERIMENTAL_SAMPLER_BALLOT_FLAGS
               if name in os.environ]
    if enabled:
        raise TeacherProtocolError(
            f"experimental sampler/ballot flags must be unset: {enabled}"
        )
    python = sys.version.split()[0]
    if not smoke and python != CAPTURE_PYTHON:
        raise TeacherProtocolError(
            f"real teacher work requires Python {CAPTURE_PYTHON}, got {python}"
        )
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise TeacherProtocolError("compiled engine requested but not active")
    dirty = git_output("status", "--porcelain")
    if dirty and not smoke:
        raise TeacherProtocolError("real teacher labelling refuses a dirty tree")
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


def _world_payload(hands, buried) -> dict:
    return {
        "hands": {str(seat): sorted(cards)
                  for seat, cards in sorted(hands.items())},
        "buried": sorted(buried),
    }


def draw_common_worlds(bot, rnd, seat: int, count: int, *, experiment_id: str,
                       state_id: str, deal_seed: int, fold: str):
    """Take exactly ``count`` strict draws; the first rejection is fatal."""
    stream = derive_stream(
        experiment_id=experiment_id,
        deal_seed=deal_seed,
        state_id=state_id,
        purpose="belief",
        fold=fold,
    )
    original_rng = bot.rng
    before = sampler_snapshot(bot)
    worlds = []
    try:
        bot.rng = random.Random(stream["seed"])
        mem = Memory(rnd, seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
        for draw_index in range(count):
            sampled = bot._sample_hands(rnd, seat, mem)
            if sampled is None:
                raise TeacherProtocolError(
                    f"{state_id}/{fold}: strict world {draw_index} rejected"
                )
            worlds.append(sampled)
    finally:
        bot.rng = original_rng
    counters = sampler_delta(before, bot)
    bad = counter_problems(counters, count)
    if bad:
        raise TeacherProtocolError(f"{state_id}/{fold}: {'; '.join(bad)}")
    payloads = [_world_payload(hands, buried) for hands, buried in worlds]
    return worlds, {
        "requested_worlds": count,
        "stream": stream,
        # Draw occurrence identity is disjoint by fold even when independent
        # draws legitimately realise the same small-support world.
        "draw_ids": [stable_digest({"stream": stream, "index": i})
                     for i in range(count)],
        "world_digests": [stable_digest(payload) for payload in payloads],
        "realised_support_collisions": count - len({stable_digest(payload)
                                                     for payload in payloads}),
        "sampler_counters": counters,
    }


def _empty_tensor() -> dict[str, list]:
    return {name: [] for name in (
        "attacker_points", "signed_points", "bracket", "signed_level_utility"
    )}


def score_cheap_fold(bot, rnd, seat: int, candidates, worlds, fold_meta: dict,
                     *, experiment_id: str, state_id: str, deal_seed: int,
                     fold: str) -> dict:
    tensor = _empty_tensor()
    continuation_seeds, evaluation_seeds = [], []
    acting_is_attacker = rnd.is_attacker(seat)
    for world_index, (hands, buried) in enumerate(worlds):
        rows = {name: [] for name in tensor}
        cont_row, eval_row = [], []
        for candidate_index, candidate in enumerate(candidates):
            continuation = derive_stream(
                experiment_id=experiment_id, deal_seed=deal_seed,
                state_id=state_id, purpose="continuation", fold=fold,
                candidate=candidate_index, world=world_index,
                policy="heuristic",
            )
            evaluation = derive_stream(
                experiment_id=experiment_id, deal_seed=deal_seed,
                state_id=state_id, purpose="evaluation", fold=fold,
                candidate=candidate_index, world=world_index,
                target="terminal",
            )
            # Heuristic continuation is deterministic, but its independent
            # stream is still bound now so replacing it with a stochastic
            # policy cannot silently invent a new experiment identity.
            cont_row.append(continuation["seed"])
            eval_row.append(evaluation["seed"])
            outcome = targets(
                bot._rollout(rnd, seat, hands, buried, list(candidate)),
                acting_is_attacker,
            )
            for name in rows:
                rows[name].append(outcome[name])
        for name in tensor:
            tensor[name].append(rows[name])
        continuation_seeds.append(cont_row)
        evaluation_seeds.append(eval_row)
    result = {
        **fold_meta,
        "continuation_policy": "heuristic",
        "continuation_seeds": continuation_seeds,
        "evaluation_seeds": evaluation_seeds,
        "tensor": tensor,
    }
    bad = tensor_problems(result, len(worlds), len(candidates))
    if bad:
        raise TeacherProtocolError(f"{state_id}/{fold}: {'; '.join(bad)}")
    return result


def paired_vs_candidate0(fold: dict) -> list[dict]:
    matrix = fold["tensor"]["signed_level_utility"]
    n_candidates = len(matrix[0])
    return [paired_moments([row[i] - row[0] for row in matrix])
            for i in range(n_candidates)]


def cheap_record(state: dict, bot, counts: dict[str, int]) -> dict:
    rnd = replay_state(state)
    seat = state["seat"]
    candidates = [list(action_key(action))
                  for action in bot._candidates(rnd, seat)]
    bad = ballot_problems(rnd, seat, candidates)
    if bad:
        raise TeacherProtocolError(f"{state['state_id']}: {'; '.join(bad)}")
    ballot = asdict(mc_ballot(bot))
    ballot["digest"] = mc_ballot(bot).digest
    folds = {}
    sampler_total = Counter()
    t0 = time.perf_counter()
    for fold in ("selection", "report"):
        worlds, meta = draw_common_worlds(
            bot, rnd, seat, counts[fold],
            experiment_id=state["experiment_id"],
            state_id=state["state_id"], deal_seed=state["seed"], fold=fold,
        )
        sampler_total.update(meta["sampler_counters"])
        folds[fold] = score_cheap_fold(
            bot, rnd, seat, candidates, worlds, meta,
            experiment_id=state["experiment_id"],
            state_id=state["state_id"], deal_seed=state["seed"], fold=fold,
        )
    selection = folds["selection"]["tensor"]["signed_level_utility"]
    means = [sum(row[i] for row in selection) / len(selection)
             for i in range(len(candidates))]
    selected = max(range(len(candidates)), key=lambda i: (means[i], -i))
    return {
        "state_id": state["state_id"], "deal_seed": state["seed"],
        "split": state["split"], "kind": state["kind"],
        "stratum": {
            "phase": state["phase"], "role": state["role"],
            "decision": state["decision"],
        },
        "selection_probability": state["selection_probability"],
        "state": state,
        "replay_digest": stable_digest(state),
        "ballot_spec": ballot,
        "candidates": candidates,
        "candidate_count": len(candidates),
        "cheap_selected_index": selected,
        "cheap_selection_means": means,
        "folds": folds,
        "paired_vs_candidate0": {
            fold: paired_vs_candidate0(folds[fold]) for fold in folds
        },
        "sampler_counters": dict(sampler_total),
        "candidate_world_work": len(candidates) * sum(counts.values()),
        "elapsed_seconds": time.perf_counter() - t0,
    }


def _clone_world(rnd: Round, seat: int, hands, buried, candidate) -> Round:
    clone: Round = copy.copy(rnd)
    clone.hands = [sorted(hands.get(s, rnd.hands[s])) for s in range(4)]
    clone.hands[seat] = sorted(rnd.hands[seat])
    clone.buried = sorted(buried)
    assert rnd.trick is not None
    clone.trick = Trick(
        leader=rnd.trick.leader,
        plays=[TrickPlay(play.seat, list(play.cards))
               for play in rnd.trick.plays],
    )
    clone.history = list(rnd.history)
    clone.last_trick = rnd.last_trick
    clone.message = None
    # Gold is a correctness gate, so validate every downstream follow.  The
    # ordinary rollout fast path trusts heuristic follows; production N=30 is
    # a different continuation and an illegal generated action must fail the
    # shard instead of being removed from the hand unchecked.
    clone._trusted_rollout = False
    clone.play(seat, list(candidate))
    return clone


def rollout_gold(rnd, seat: int, hands, buried, candidate, *,
                 experiment_id: str, state_id: str, deal_seed: int,
                 fold: str, candidate_index: int, world_index: int):
    """Information-set-legal production N=30 continuation with fixed seeds."""
    clone = _clone_world(rnd, seat, hands, buried, candidate)
    counters = Counter({name: 0 for name in SAMPLER_COUNTERS})
    trace = []
    decision_index = 0
    continuation_rollouts = 0
    continuation_searches = 0
    while clone.phase == "play":
        actor_seat = clone.turn
        assert actor_seat is not None
        stream = derive_stream(
            experiment_id=experiment_id, deal_seed=deal_seed,
            state_id=state_id, purpose="continuation", fold=fold,
            candidate=candidate_index, world=world_index,
            decision=decision_index, seat=actor_seat,
            policy="mc-strong",
        )
        policy = make_bot("mc-strong", seed=stream["seed"])
        before = sampler_snapshot(policy)
        action = policy.decide_play(clone, actor_seat)
        delta = sampler_delta(before, policy)
        counters.update(delta)
        continuation_rollouts += int(getattr(policy, "rollouts", 0))
        continuation_searches += int(getattr(policy, "search_calls", 0))
        forbidden = {name: delta[name] for name in (
            "failed_worlds", "rejected_worlds", "impossible_worlds",
            "short_search_decisions", "zero_world_decisions",
        ) if delta[name]}
        if (delta["sample_attempts"] != delta["accepted_worlds"]
                + delta["failed_worlds"] or forbidden):
            raise TeacherProtocolError(
                f"{state_id}/{fold}/c{candidate_index}/w{world_index}/"
                f"d{decision_index}: invalid gold continuation counters "
                f"{dict(delta)}"
            )
        trace.append({
            "decision": decision_index, "seat": actor_seat,
            "seed": stream["seed"], "action": list(action),
        })
        clone.play(actor_seat, list(action))
        decision_index += 1
    return (float(clone.attacker_points), dict(counters), stable_digest(trace),
            len(trace), continuation_rollouts, continuation_searches)


def score_gold_fold(sampler, rnd, seat: int, candidates, worlds, fold_meta: dict,
                    *, state: dict, fold: str) -> dict:
    tensor = _empty_tensor()
    continuation_trace_digests, continuation_decisions = [], []
    inner_counters = Counter({name: 0 for name in SAMPLER_COUNTERS})
    continuation_rollouts = 0
    continuation_searches = 0
    acting_is_attacker = rnd.is_attacker(seat)
    for world_index, (hands, buried) in enumerate(worlds):
        rows = {name: [] for name in tensor}
        digest_row, decisions_row = [], []
        for candidate_index, candidate in enumerate(candidates):
            (points, counters, trace_digest, n_decisions,
             inner_rollouts, inner_searches) = rollout_gold(
                rnd, seat, hands, buried, candidate,
                experiment_id=state["experiment_id"],
                state_id=state["state_id"], deal_seed=state["seed"],
                fold=fold, candidate_index=candidate_index,
                world_index=world_index,
            )
            inner_counters.update(counters)
            continuation_rollouts += inner_rollouts
            continuation_searches += inner_searches
            outcome = targets(points, acting_is_attacker)
            for name in rows:
                rows[name].append(outcome[name])
            digest_row.append(trace_digest)
            decisions_row.append(n_decisions)
        for name in tensor:
            tensor[name].append(rows[name])
        continuation_trace_digests.append(digest_row)
        continuation_decisions.append(decisions_row)
    result = {
        **fold_meta,
        "continuation_policy": "mc-strong",
        "continuation_n": 30,
        "continuation_seed_derivation": (
            "sha256(canonical JSON of experiment_id,deal_seed,state_id,"
            "purpose,fold,candidate,world,decision,seat,policy)[:16]"
        ),
        "continuation_trace_digests": continuation_trace_digests,
        "continuation_decisions": continuation_decisions,
        "continuation_rollouts": continuation_rollouts,
        "continuation_searches": continuation_searches,
        "inner_sampler_counters": dict(inner_counters),
        "tensor": tensor,
    }
    bad = tensor_problems(result, len(worlds), len(candidates))
    if bad:
        raise TeacherProtocolError(
            f"{state['state_id']}/{fold}: {'; '.join(bad)}"
        )
    return result


def gold_record(cheap: dict, sampler, counts: dict[str, int]) -> dict:
    state = cheap["state"]
    rnd = replay_state(state)
    seat = state["seat"]
    candidates = cheap["candidates"]
    bad = ballot_problems(rnd, seat, candidates)
    if bad:
        raise TeacherProtocolError(f"{state['state_id']}: {'; '.join(bad)}")
    if cheap.get("replay_digest") != stable_digest(state):
        raise TeacherProtocolError(f"{state['state_id']}: cheap replay digest drift")
    live_ballot = mc_ballot(sampler)
    if cheap.get("ballot_spec", {}).get("digest") != live_ballot.digest:
        raise TeacherProtocolError(f"{state['state_id']}: cheap/live ballot drift")
    selection = cheap["folds"]["selection"]
    n_candidates = len(candidates)
    if tensor_problems(selection, CHEAP_FOLDS["selection"], n_candidates):
        raise TeacherProtocolError(f"{state['state_id']}: invalid cheap selection tensor")
    cheap_i = cheap["cheap_selected_index"]
    means = [sum(row[i] for row in selection["tensor"]["signed_level_utility"])
             / len(selection["tensor"]["signed_level_utility"])
             for i in range(n_candidates)]
    if cheap_i != max(range(n_candidates), key=lambda i: (means[i], -i)):
        raise TeacherProtocolError(f"{state['state_id']}: cheap action was not frozen on selection")

    folds = {}
    outer_totals = Counter()
    inner_totals = Counter()
    t0 = time.perf_counter()
    for fold in ("gold_selection", "gold_report"):
        worlds, meta = draw_common_worlds(
            sampler, rnd, seat, counts[fold],
            experiment_id=state["experiment_id"], state_id=state["state_id"],
            deal_seed=state["seed"], fold=fold,
        )
        outer_totals.update(meta["sampler_counters"])
        folds[fold] = score_gold_fold(
            sampler, rnd, seat, candidates, worlds, meta, state=state, fold=fold
        )
        inner_totals.update(folds[fold]["inner_sampler_counters"])
    gold_selection = folds["gold_selection"]["tensor"]["signed_level_utility"]
    gold_means = [sum(row[i] for row in gold_selection) / len(gold_selection)
                  for i in range(n_candidates)]
    gold_i = max(range(n_candidates), key=lambda i: (gold_means[i], -i))
    report = folds["gold_report"]["tensor"]["signed_level_utility"]
    regret_vector = [row[gold_i] - row[cheap_i] for row in report]
    outer_candidate_worlds = n_candidates * sum(counts.values())
    continuation_rollouts = sum(
        fold["continuation_rollouts"] for fold in folds.values())
    continuation_searches = sum(
        fold["continuation_searches"] for fold in folds.values())
    return {
        "state_id": state["state_id"], "deal_seed": state["seed"],
        "split": state["split"], "kind": state["kind"],
        "stratum": cheap["stratum"], "state": state,
        "replay_digest": cheap["replay_digest"],
        "ballot_spec": cheap["ballot_spec"], "candidates": candidates,
        "candidate_count": n_candidates,
        "cheap_selected_index": cheap_i,
        "gold_reference_index": gold_i,
        "gold_selection_means": gold_means,
        "gold_report_regret": sum(regret_vector) / len(regret_vector),
        "gold_report_regret_moments": paired_moments(regret_vector),
        "folds": folds,
        "outer_sampler_counters": dict(outer_totals),
        "inner_sampler_counters": dict(inner_totals),
        "candidate_world_work": outer_candidate_worlds,
        "continuation_rollouts": continuation_rollouts,
        "continuation_searches": continuation_searches,
        "total_rollout_work": outer_candidate_worlds + continuation_rollouts,
        "elapsed_seconds": time.perf_counter() - t0,
    }


def state_set_problems(payload: dict, stage: str, *, smoke: bool) -> list[str]:
    bad = []
    if payload.get("schema") != STATE_SET_SCHEMA:
        bad.append("state-set schema")
    if payload.get("experiment_id") != EXPERIMENT:
        bad.append("experiment identity")
    if payload.get("stage") != stage:
        bad.append("state-set stage")
    if not payload.get("complete"):
        bad.append("state set is incomplete")
    states = payload.get("states", [])
    if payload.get("states_digest") != stable_digest(states):
        bad.append("state-set record digest")
    required = STAGE_A_STATES if stage == "a" else STAGE_B_STATES
    if not smoke and len(states) != required:
        bad.append(f"state count {len(states)}, required {required}")
    ids = [state.get("state_id") for state in states]
    deals = [state.get("seed") for state in states]
    if len(ids) != len(set(ids)):
        bad.append("duplicate state identity")
    if len(deals) != len(set(deals)):
        bad.append("more than one state per deal")
    if not smoke:
        if payload.get("packet_id") != CAPTURE_PACKET_ID:
            bad.append("state-set capture packet id")
        if payload.get("capture_packet") != capture_packet():
            bad.append("state-set capture packet identity/range")
        coverage = payload.get("capture_coverage", {})
        for key, value in capture_coverage().items():
            if coverage.get(key) != value:
                bad.append(f"state-set capture coverage {key}")
        diagnostic_inputs = payload.get("diagnostic_inputs", [])
        shard_indices = [item.get("capture_shard_index")
                         for item in diagnostic_inputs
                         if isinstance(item, dict)]
        diagnostic_hashes = [item.get("sha256") for item in diagnostic_inputs
                             if isinstance(item, dict)]
        if (len(diagnostic_inputs) != CAPTURE_SHARDS
                or not all(isinstance(index, int) for index in shard_indices)
                or sorted(shard_indices) != list(range(CAPTURE_SHARDS))):
            bad.append("state-set exact diagnostic shard population")
        if (len(diagnostic_hashes) != CAPTURE_SHARDS
                or len(set(diagnostic_hashes)) != CAPTURE_SHARDS
                or any(not is_sha256(value) for value in diagnostic_hashes)):
            bad.append("state-set diagnostic artifact hashes")
        parent_map = coverage.get("capture_parent_sha256", {})
        diagnostic_map = coverage.get("diagnostic_records_sha256", {})
        expected_keys = {str(index) for index in range(CAPTURE_SHARDS)}
        for name, values in (
            ("capture-parent", parent_map),
            ("diagnostic-record", diagnostic_map),
        ):
            if (not isinstance(values, dict) or set(values) != expected_keys
                    or any(not is_sha256(value) for value in values.values())):
                bad.append(f"state-set {name} coverage map")
        for item in diagnostic_inputs:
            if not isinstance(item, dict):
                continue
            index = item.get("capture_shard_index")
            if parent_map.get(str(index)) != item.get("capture_parent_sha256"):
                bad.append("state-set capture-parent binding")
            if diagnostic_map.get(str(index)) != item.get(
                    "diagnostic_records_sha256"):
                bad.append("state-set diagnostic-record binding")
        if payload.get("tree_dirty") or not payload.get("promotable"):
            bad.append("state set is dirty or non-promotable")
        if not payload.get("fast_engine") or not payload.get("require_voids"):
            bad.append("state set lacks compiled/strict provenance")
        if payload.get("python") != CAPTURE_PYTHON:
            bad.append(f"state set Python is not {CAPTURE_PYTHON}")
        if payload.get("experimental_sampler_ballot_flags") != []:
            bad.append("state set has experimental sampler/ballot flags")
        if payload.get("seed_start") != SEED_START:
            bad.append(f"fresh-deal seed start is not {SEED_START}")
        if any(not isinstance(seed, int)
               or not SEED_START <= seed <= CAPTURE_SEED_END
               for seed in deals):
            bad.append("state outside the fresh teacher seed range")
        exclusion = payload.get("exam_exclusion", {})
        if (not exclusion.get("verified") or exclusion.get("overlap") != 0
                or not exclusion.get("sources")):
            bad.append("DEV/CALIB/REPORT exclusion is not verified")
        actor = payload.get("actor", {})
        if actor.get("policy") != "mc-strong" or not actor.get("identity"):
            bad.append("production-champion actor identity is not pinned")
        if stage == "b":
            stage_a_gate = payload.get("stage_a_gate") or {}
            if (stage_a_gate.get("verdict") != "PASS"
                    or not stage_a_gate.get("sha256")
                    or stage_a_gate.get("state_set_sha256")
                    != (payload.get("excluded_stage_a") or {}).get("sha256")):
                bad.append("Stage B lacks an exact passing Stage-A gate binding")
    if not smoke:
        representative_per_cell = (
            STAGE_A_REPRESENTATIVE_PER_CELL if stage == "a"
            else STAGE_B_REPRESENTATIVE_PER_CELL)
        representative = Counter(
            (s.get("phase"), s.get("role"), s.get("decision"))
            for s in states if s.get("kind") == "representative"
        )
        for cell in REPRESENTATIVE_CELLS:
            if representative[cell] != representative_per_cell:
                bad.append(f"representative cell {cell}: {representative[cell]}")
        boundary_want = (STAGE_A_OTHER_STATES // 2 if stage == "a"
                         else STAGE_B_BOUNDARY_STATES)
        uncertainty_want = (STAGE_A_OTHER_STATES // 2 if stage == "a"
                            else STAGE_B_UNCERTAINTY_STATES)
        boundary = sum(s.get("kind") == "boundary" for s in states)
        uncertainty = sum(s.get("kind") == "uncertainty" for s in states)
        if boundary != boundary_want:
            bad.append(f"boundary states {boundary}, required {boundary_want}")
        if uncertainty != uncertainty_want:
            bad.append(
                f"uncertainty states {uncertainty}, required {uncertainty_want}")
    for state in states:
        if not isinstance(state.get("selection_probability"), (int, float)) \
                or state.get("selection_probability", 0) <= 0:
            bad.append(f"{state.get('state_id')}: selection probability")
        metadata = state.get("selection_metadata", {})
        if state.get("kind") == "representative":
            if metadata.get("deployment_weightable") is not True:
                bad.append(f"{state.get('state_id')}: representative weighting")
        elif (metadata.get("deployment_weightable") is not False
              or state.get("selection_probability") != 1.0):
            bad.append(f"{state.get('state_id')}: challenge weighting contract")
        try:
            replay_state(state)
        except Exception as exc:
            bad.append(f"{state.get('state_id')}: replay {type(exc).__name__}: {exc}")
    return bad


def state_source_problems(payload: dict, runtime: dict,
                          digests: dict[str, str]) -> list[str]:
    """Bind capture/freezing to the exact executable used for labelling."""
    bad = []
    for key in (
        "git", "python", "fast_engine", "require_voids",
        "experimental_sampler_ballot_flags",
    ):
        if payload.get(key) != runtime.get(key):
            bad.append(f"state-set {key} differs from labeller")
    if payload.get("state_script_sha256") != digests.get("state_freezer"):
        bad.append("state freezer source drift")
    if payload.get("fast_router_sha256") != digests.get("fast_router"):
        bad.append("state-set fast router drift")
    if payload.get("fast_binary_sha256") != digests.get("compiled_engine"):
        bad.append("state-set compiled engine drift")

    actor = payload.get("actor", {})
    actor_sources = actor.get("source_digests", {})
    source_map = {
        "mcbot": "mcbot_sampler",
        "memory": "memory",
        "registry": "registry",
        "engine_round": "engine_round",
        "teacher_replay": "teacher_contract",
    }
    for actor_name, label_name in source_map.items():
        if actor_sources.get(actor_name) != digests.get(label_name):
            bad.append(f"state actor {actor_name} source drift")
    try:
        current_ballot = mc_ballot(make_bot("mc-strong", seed=1)).digest
    except Exception as exc:
        bad.append(f"current actor construction failed: {type(exc).__name__}: {exc}")
    else:
        if actor.get("ballot", {}).get("digest") != current_ballot:
            bad.append("state actor ballot drift")
    return bad


def label_packet_problems(payload: dict) -> list[str]:
    """Validate the immutable capture/state-set lineage on one label shard."""
    bad = []
    contract = payload.get("state_contract", {})
    if not is_run_id(payload.get("producer_run_id")):
        bad.append("label producer run identity")
    receipt = payload.get("producer_receipt", {})
    if (not isinstance(receipt, dict)
            or receipt.get("run_id") != payload.get("producer_run_id")
            or not is_sha256(receipt.get("sha256"))
            or not is_sha256(receipt.get("nonce"))
            or receipt.get("role") not in {
                "stage-a-primary", "stage-a-rerun",
                "stage-b-cheap", "stage-b-gold"}
            or not isinstance(receipt.get("path"), str)):
        bad.append("label producer receipt binding")
    if (payload.get("packet_id") != CAPTURE_PACKET_ID
            or contract.get("packet_id") != CAPTURE_PACKET_ID):
        bad.append("label capture packet id")
    if (payload.get("capture_packet") != capture_packet()
            or contract.get("capture_packet") != capture_packet()):
        bad.append("label capture packet identity/range")
    manifest_coverage = payload.get("capture_coverage", {})
    contract_coverage = contract.get("capture_coverage", {})
    for key, value in capture_coverage().items():
        if (manifest_coverage.get(key) != value
                or contract_coverage.get(key) != value):
            bad.append(f"label capture coverage {key}")
    if manifest_coverage != contract_coverage:
        bad.append("label top-level/state-contract coverage drift")
    inputs = contract.get("diagnostic_inputs", [])
    indices = [item.get("capture_shard_index") for item in inputs
               if isinstance(item, dict)]
    hashes = [item.get("sha256") for item in inputs
              if isinstance(item, dict)]
    if (len(inputs) != CAPTURE_SHARDS
            or not all(isinstance(index, int) for index in indices)
            or sorted(indices) != list(range(CAPTURE_SHARDS))):
        bad.append("label diagnostic shard population")
    if (len(hashes) != CAPTURE_SHARDS or len(set(hashes)) != CAPTURE_SHARDS
            or any(not is_sha256(value) for value in hashes)):
        bad.append("label diagnostic artifact hashes")
    parent_map = contract_coverage.get("capture_parent_sha256", {})
    diagnostic_map = contract_coverage.get("diagnostic_records_sha256", {})
    expected_keys = {str(index) for index in range(CAPTURE_SHARDS)}
    for name, values in (
        ("capture-parent", parent_map),
        ("diagnostic-record", diagnostic_map),
    ):
        if (not isinstance(values, dict) or set(values) != expected_keys
                or any(not is_sha256(value) for value in values.values())):
            bad.append(f"label {name} coverage map")
    for item in inputs:
        if not isinstance(item, dict):
            continue
        index = item.get("capture_shard_index")
        if parent_map.get(str(index)) != item.get("capture_parent_sha256"):
            bad.append("label capture-parent binding")
        if diagnostic_map.get(str(index)) != item.get(
                "diagnostic_records_sha256"):
            bad.append("label diagnostic-record binding")
    state_sha = contract.get("state_set_sha256")
    if (not is_sha256(state_sha)
            or payload.get("state_input_sha256") != state_sha):
        bad.append("label exact state-set binding")
    partition = payload.get("state_partition", {})
    records = payload.get("records", [])
    record_ids = [record.get("state_id") for record in records]
    if (partition.get("schema") != "teacher-v1-state-partition-v1"
            or partition.get("shard_index") != payload.get("shard_index")
            or partition.get("shard_count") != payload.get("shard_count")
            or partition.get("state_ids") != record_ids
            or partition.get("state_ids_sha256") != stable_digest(record_ids)
            or partition.get("assignment")
            != "sorted_state_id_then_interleaved_position"):
        bad.append("label state partition identity")
    return sorted(set(bad))


def cheap_parent_problems(payload: dict, runtime: dict,
                          digests: dict[str, str], *, smoke: bool) -> list[str]:
    """Reject a corrupt or executable-mismatched cheap parent before gold work."""
    bad = []
    records = payload.get("records", [])
    if payload.get("records_digest") != deterministic_records_digest(records):
        bad.append("cheap-parent records digest")
    if payload.get("n_records") != len(records):
        bad.append("cheap-parent record count")
    if payload.get("git") != runtime.get("git"):
        bad.append("cheap-parent git differs from gold labeller")
    if payload.get("source_digests") != digests:
        bad.append("cheap-parent executable source drift")
    if payload.get("target_schema") != TARGET_SCHEMA:
        bad.append("cheap-parent target schema drift")
    if not payload.get("fast_engine") or not payload.get("require_voids"):
        bad.append("cheap-parent compiled/strict runtime contract")
    if not smoke and payload.get("counts") != CHEAP_FOLDS:
        bad.append("cheap-parent world-count drift")
    if payload.get("candidate_world_work") != sum(
        int(record.get("candidate_world_work", -1)) for record in records
    ):
        bad.append("cheap-parent work total")
    if not smoke:
        bad += label_packet_problems(payload)
    return bad


def _load_json_bytes(path: str, *, allow_partial: bool = False
                     ) -> tuple[dict, str]:
    """Parse and hash the same opened bytes, avoiding a hash/open race."""
    partial = str(path) + ".partial"
    if not allow_partial and os.path.lexists(partial):
        raise TeacherProtocolError(f"partial artifact remains at {partial}")
    if os.path.islink(path) or not os.path.isfile(path):
        raise TeacherProtocolError(f"missing or non-regular artifact {path}")
    with open(path, "rb") as fh:
        raw = fh.read()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def load_pinned(path: str, expected: str) -> dict:
    if not is_sha256(expected):
        raise TeacherProtocolError("--expected-input-sha256 is required")
    payload, actual = _load_json_bytes(path)
    if actual != expected:
        raise TeacherProtocolError(
            f"input digest mismatch: expected {expected}, got {actual}"
        )
    return payload


def producer_receipt_problems(receipt: dict, *, runtime: dict,
                              digests: dict[str, str], stage: str, mode: str,
                              state_set_sha256: str) -> list[str]:
    """Validate the pre-existing population receipt before expensive work."""
    bad = []
    roles = {
        "stage-a-primary": ("a", "cheap"),
        "stage-a-rerun": ("a", "cheap"),
        "stage-b-cheap": ("b", "cheap"),
        "stage-b-gold": ("b", "gold"),
    }
    if (receipt.get("schema") != PRODUCER_RECEIPT_SCHEMA
            or receipt.get("complete") is not True
            or receipt.get("experiment_id") != EXPERIMENT):
        bad.append("producer receipt identity/completion")
    if (receipt.get("packet_id") != CAPTURE_PACKET_ID
            or receipt.get("capture_packet") != capture_packet()):
        bad.append("producer receipt capture packet")
    if not is_run_id(receipt.get("run_id")):
        bad.append("producer receipt run identity")
    role = receipt.get("role")
    if (roles.get(role) != (stage, mode)
            or receipt.get("stage") != stage
            or receipt.get("mode") != mode):
        bad.append("producer receipt role/stage/mode")
    if ((receipt.get("state_set") or {}).get("sha256")
            != state_set_sha256):
        bad.append("producer receipt exact state-set binding")
    nonce = receipt.get("nonce")
    if not is_sha256(nonce):
        bad.append("producer receipt nonce")
    if not isinstance(receipt.get("created_time_ns"), int):
        bad.append("producer receipt creation time")
    for key in RUNTIME_BINDING_FIELDS:
        if receipt.get(key) != runtime.get(key):
            bad.append(f"producer receipt/runtime {key} drift")
    if receipt.get("tree_dirty") or receipt.get("promotable") is not True:
        bad.append("producer receipt runtime is dirty/non-promotable")
    if receipt.get("python") != CAPTURE_PYTHON:
        bad.append(f"producer receipt Python is not {CAPTURE_PYTHON}")
    if receipt.get("experimental_sampler_ballot_flags") != []:
        bad.append("producer receipt has experimental sampler/ballot flags")
    if receipt.get("source_digests") != digests:
        bad.append("producer receipt executable source drift")
    return sorted(set(bad))


def load_producer_receipt(*, path: str | None, expected: str | None,
                          smoke: bool, runtime: dict,
                          digests: dict[str, str], stage: str, mode: str,
                          state_set_sha256: str) -> tuple[dict, dict]:
    if smoke:
        role = ("stage-a-primary" if stage == "a" else
                "stage-b-cheap" if mode == "cheap" else "stage-b-gold")
        receipt = {
            "schema": PRODUCER_RECEIPT_SCHEMA, "run_id": "smoke-run",
            "role": role, "nonce": stable_digest("smoke-receipt"),
        }
        return receipt, {
            "path": None, "sha256": stable_digest(receipt),
            "run_id": receipt["run_id"], "role": role,
            "nonce": receipt["nonce"],
        }
    if not path or not expected or not is_sha256(expected):
        raise TeacherProtocolError(
            "real labels require --producer-receipt and its exact SHA-256")
    receipt = load_pinned(path, expected)
    bad = producer_receipt_problems(
        receipt, runtime=runtime, digests=digests, stage=stage, mode=mode,
        state_set_sha256=state_set_sha256)
    if bad:
        raise TeacherProtocolError("invalid producer receipt: " + "; ".join(bad))
    return receipt, {
        "path": path, "sha256": expected,
        "run_id": receipt["run_id"], "role": receipt["role"],
        "nonce": receipt["nonce"],
    }


def revalidate_publication_inputs(
        *, parent_path: str, parent_sha256: str, expected_parent: dict,
        receipt_path: str | None, receipt_sha256: str | None,
        expected_receipt: dict, expected_receipt_binding: dict,
        smoke: bool, runtime: dict, digests: dict[str, str],
        stage: str, mode: str, state_set_sha256: str) -> None:
    """Reopen every long-run parent and runtime immediately around publish."""
    if load_pinned(parent_path, parent_sha256) != expected_parent:
        raise TeacherProtocolError("label parent changed after initial load")
    current_runtime = runtime_contract(smoke)
    if current_runtime != runtime:
        raise TeacherProtocolError("teacher runtime changed during labelling")
    if source_digests() != digests:
        raise TeacherProtocolError(
            "teacher executable digests changed during labelling")
    receipt, binding = load_producer_receipt(
        path=receipt_path, expected=receipt_sha256, smoke=smoke,
        runtime=current_runtime, digests=digests, stage=stage, mode=mode,
        state_set_sha256=state_set_sha256,
    )
    if receipt != expected_receipt or binding != expected_receipt_binding:
        raise TeacherProtocolError(
            "producer receipt changed after initial admission")


def write_complete(path: str, payload: dict,
                   *, verify: Callable[[], None] | None = None) -> None:
    partial = path + ".partial"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        with open(partial, "x", encoding="utf-8") as fh:
            json.dump(payload, fh, sort_keys=True, separators=(",", ":"))
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
    except FileExistsError as exc:
        raise TeacherProtocolError(
            f"refusing existing partial artifact {partial}; no resume or "
            "replacement"
        ) from exc
    try:
        os.link(partial, path)
    except FileExistsError as exc:
        raise TeacherProtocolError(
            f"refusing to overwrite {path}; completed partial remains at "
            f"{partial}"
        ) from exc
    if verify is not None:
        # Keep the completed partial as a refusal marker until the final hard
        # link and every parent/runtime check have been reopened successfully.
        verify()
    try:
        os.unlink(partial)
    except OSError as exc:
        raise TeacherProtocolError(
            f"published {path} but could not remove partial {partial}"
        ) from exc


def verify_published_label(path: str, expected_payload: dict,
                           *, smoke: bool,
                           allow_partial: bool = False) -> str:
    """Reopen the final name and rerun its local contract before success."""
    payload, digest = _load_json_bytes(path, allow_partial=allow_partial)
    if payload != expected_payload:
        raise TeacherProtocolError("published label differs from candidate bytes")
    if not smoke:
        bad = label_packet_problems(payload)
        if bad:
            raise TeacherProtocolError(
                "published label packet contract: " + "; ".join(bad))
    return digest


def deterministic_records_digest(records: list[dict]) -> str:
    """Hash evidence, excluding wall time which must differ on a rerun."""
    canonical = []
    for record in records:
        item = dict(record)
        item.pop("elapsed_seconds", None)
        canonical.append(item)
    return stable_digest(canonical)


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("cheap", "gold"))
    ap.add_argument("--input", required=True)
    ap.add_argument("--expected-input-sha256", required=True)
    ap.add_argument("--stage", choices=("a", "b"), required=True)
    ap.add_argument("--shard-index", type=int, default=0)
    ap.add_argument("--shard-count", type=int, default=CAPTURE_SHARDS)
    ap.add_argument("--producer-receipt")
    ap.add_argument("--expected-producer-receipt-sha256")
    ap.add_argument("--out", required=True)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--selection-worlds", type=int, default=CHEAP_FOLDS["selection"])
    ap.add_argument("--report-worlds", type=int, default=CHEAP_FOLDS["report"])
    ap.add_argument("--gold-selection-worlds", type=int,
                    default=GOLD_FOLDS["gold_selection"])
    ap.add_argument("--gold-report-worlds", type=int,
                    default=GOLD_FOLDS["gold_report"])
    return ap


def main() -> None:
    args = parser().parse_args()
    try:
        runtime = runtime_contract(args.smoke)
        frozen_source_digests = source_digests()
        if not 0 <= args.shard_index < args.shard_count:
            raise TeacherProtocolError("invalid shard index/count")
        if not args.smoke and args.shard_count != CAPTURE_SHARDS:
            raise TeacherProtocolError(
                f"real teacher gates require exactly {CAPTURE_SHARDS} shards"
            )
        if args.mode == "cheap":
            if not args.smoke and (args.selection_worlds, args.report_worlds) != (
                CHEAP_FOLDS["selection"], CHEAP_FOLDS["report"]
            ):
                raise TeacherProtocolError("real cheap run requires 256/256 worlds")
            source = load_pinned(args.input, args.expected_input_sha256)
            bad = state_set_problems(source, args.stage, smoke=args.smoke)
            bad += state_source_problems(
                source, runtime, frozen_source_digests)
            if bad:
                raise TeacherProtocolError("invalid state set: " + "; ".join(bad))
            if source.get("experiment_id") != EXPERIMENT:
                raise TeacherProtocolError("input experiment identity drift")
            receipt, receipt_binding = load_producer_receipt(
                path=args.producer_receipt,
                expected=args.expected_producer_receipt_sha256,
                smoke=args.smoke, runtime=runtime,
                digests=frozen_source_digests, stage=args.stage, mode=args.mode,
                state_set_sha256=args.expected_input_sha256)
            state_set_sha256 = args.expected_input_sha256
            all_records = source["states"]
            selected = canonical_state_partition(
                all_records, args.shard_index, args.shard_count)
            expected_per_shard = (
                STAGE_A_STATES if args.stage == "a" else STAGE_B_STATES
            ) // CAPTURE_SHARDS
            if not args.smoke and len(selected) != expected_per_shard:
                raise TeacherProtocolError(
                    f"state shard {args.shard_index} has {len(selected)} rows, "
                    f"expected {expected_per_shard}"
                )
            if not selected:
                raise TeacherProtocolError("empty shard")
            bot = make_bot("mc-strong", seed=1)
            counts = {"selection": args.selection_worlds,
                      "report": args.report_worlds}
            records = [cheap_record(state, bot, counts) for state in selected]
            schema = CHEAP_SHARD_SCHEMA
            continuation = "heuristic"
            input_experiment = source.get("experiment_id")
        else:
            if args.stage != "b":
                raise TeacherProtocolError("gold continuation is a Stage-B gate")
            if not args.smoke and (
                args.gold_selection_worlds, args.gold_report_worlds
            ) != (GOLD_FOLDS["gold_selection"], GOLD_FOLDS["gold_report"]):
                raise TeacherProtocolError("real gold run requires 64/64 worlds")
            source = load_pinned(args.input, args.expected_input_sha256)
            if source.get("schema") != CHEAP_SHARD_SCHEMA or not source.get("complete"):
                raise TeacherProtocolError("gold input is not a complete cheap shard")
            if (not args.smoke and (source.get("tree_dirty")
                                    or not source.get("promotable"))):
                raise TeacherProtocolError(
                    "real gold run refuses dirty/non-promotable cheap parent")
            if source.get("experiment_id") != EXPERIMENT:
                raise TeacherProtocolError("input experiment identity drift")
            if source.get("stage") != "b":
                raise TeacherProtocolError("gold input was not labelled for Stage B")
            bad = cheap_parent_problems(
                source, runtime, frozen_source_digests, smoke=args.smoke)
            if bad:
                raise TeacherProtocolError(
                    "invalid cheap parent: " + "; ".join(bad))
            receipt, receipt_binding = load_producer_receipt(
                path=args.producer_receipt,
                expected=args.expected_producer_receipt_sha256,
                smoke=args.smoke, runtime=runtime,
                digests=frozen_source_digests, stage=args.stage, mode=args.mode,
                state_set_sha256=source.get("state_input_sha256"))
            state_set_sha256 = source.get("state_input_sha256")
            cheap_records = source.get("records", [])
            # A gold shard is the one-to-one continuation of its cheap shard.
            # Re-sharding an already-sharded input would keep only 1/N of it,
            # while launching every parent shard that way would silently label
            # only 1/N of the 128-state gate.
            if (args.shard_index != source.get("shard_index")
                    or args.shard_count != source.get("shard_count")):
                raise TeacherProtocolError(
                    "gold shard index/count must match its cheap parent exactly"
                )
            selected = cheap_records
            if not selected:
                raise TeacherProtocolError("empty shard")
            if not args.smoke and len(selected) != STAGE_B_STATES // CAPTURE_SHARDS:
                raise TeacherProtocolError(
                    f"gold parent shard has {len(selected)} rows, expected "
                    f"{STAGE_B_STATES // CAPTURE_SHARDS}"
                )
            bot = make_bot("mc-strong", seed=1)
            counts = {"gold_selection": args.gold_selection_worlds,
                      "gold_report": args.gold_report_worlds}
            records = [gold_record(record, bot, counts) for record in selected]
            schema = GOLD_SHARD_SCHEMA
            continuation = "mc-strong@N=30"
            input_experiment = source.get("experiment_id")

        if input_experiment != EXPERIMENT:
            raise TeacherProtocolError(
                f"input experiment {input_experiment!r}, expected {EXPERIMENT!r}"
            )
        elapsed = sum(record["elapsed_seconds"] for record in records)
        revalidate_publication_inputs(
            parent_path=args.input,
            parent_sha256=args.expected_input_sha256,
            expected_parent=source,
            receipt_path=args.producer_receipt,
            receipt_sha256=args.expected_producer_receipt_sha256,
            expected_receipt=receipt,
            expected_receipt_binding=receipt_binding,
            smoke=args.smoke,
            runtime=runtime,
            digests=frozen_source_digests,
            stage=args.stage,
            mode=args.mode,
            state_set_sha256=state_set_sha256,
        )
        payload = {
            "schema": schema, "experiment_id": EXPERIMENT,
            "packet_id": source.get("packet_id"),
            "capture_packet": source.get(
                "capture_packet",
                (source.get("state_contract") or {}).get("capture_packet")),
            "capture_coverage": source.get(
                "capture_coverage",
                (source.get("state_contract") or {}).get("capture_coverage")),
            "target_schema": TARGET_SCHEMA,
            "stage": args.stage, "mode": args.mode,
            "producer_run_id": receipt["run_id"],
            "producer_receipt": receipt_binding,
            **runtime, "source_digests": frozen_source_digests,
            "input": args.input, "input_sha256": args.expected_input_sha256,
            "state_input_sha256": (
                args.expected_input_sha256 if args.mode == "cheap"
                else source.get("input_sha256")
            ),
            "shard_index": args.shard_index, "shard_count": args.shard_count,
            "state_partition": {
                "schema": "teacher-v1-state-partition-v1",
                "assignment": "sorted_state_id_then_interleaved_position",
                "shard_index": args.shard_index,
                "shard_count": args.shard_count,
                "state_ids": [record["state_id"] for record in records],
                "state_ids_sha256": stable_digest(
                    [record["state_id"] for record in records]),
            },
            "continuation": continuation, "counts": counts,
            "state_contract": source.get("state_contract", {
                "one_state_per_deal": source.get("one_state_per_deal"),
                "exam_exclusion": source.get("exam_exclusion"),
                "actor": source.get("actor"),
                "packet_id": source.get("packet_id"),
                "capture_packet": source.get("capture_packet"),
                "capture_coverage": source.get("capture_coverage"),
                "diagnostic_inputs": source.get("diagnostic_inputs"),
                "state_set_sha256": args.expected_input_sha256,
            }),
            "complete": True, "n_records": len(records), "records": records,
            "records_digest": deterministic_records_digest(records),
            "candidate_world_work": sum(r["candidate_world_work"] for r in records),
            "measured_record_seconds": elapsed,
            "projected_2048_seconds": elapsed / len(records) * 2048,
        }
        if not args.smoke:
            bad = label_packet_problems(payload)
            if bad:
                raise TeacherProtocolError(
                    "label packet contract: " + "; ".join(bad))
        def verify_publication() -> None:
            verify_published_label(
                args.out, payload, smoke=args.smoke, allow_partial=True)
            # The partial remains until this post-link provenance check passes.
            revalidate_publication_inputs(
                parent_path=args.input,
                parent_sha256=args.expected_input_sha256,
                expected_parent=source,
                receipt_path=args.producer_receipt,
                receipt_sha256=args.expected_producer_receipt_sha256,
                expected_receipt=receipt,
                expected_receipt_binding=receipt_binding,
                smoke=args.smoke,
                runtime=runtime,
                digests=frozen_source_digests,
                stage=args.stage,
                mode=args.mode,
                state_set_sha256=state_set_sha256,
            )

        write_complete(args.out, payload, verify=verify_publication)
        print(
            f"wrote {args.out}: {len(records)} records, "
            f"digest {payload['records_digest']}, {elapsed:.1f}s",
            flush=True,
        )
    except (OSError, ValueError, TeacherProtocolError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3)


if __name__ == "__main__":
    main()

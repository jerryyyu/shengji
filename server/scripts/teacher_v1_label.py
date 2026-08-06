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
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shengji.ai.memory import Memory                              # noqa: E402
from shengji.ai.registry import make_bot                          # noqa: E402
from shengji.engine.ballot import mc_ballot                       # noqa: E402
from shengji.engine.round import Round, Trick, TrickPlay          # noqa: E402
from shengji.teacher_v1 import (CHEAP_FOLDS, CHEAP_SHARD_SCHEMA,  # noqa: E402
                                EXPERIMENT, GOLD_FOLDS,
                                GOLD_SHARD_SCHEMA,
                                REPRESENTATIVE_CELLS,
                                SAMPLER_COUNTERS, STAGE_A_OTHER_STATES,
                                STAGE_A_REPRESENTATIVE_PER_CELL,
                                STAGE_A_STATES, STAGE_B_STATES,
                                STAGE_B_BOUNDARY_STATES,
                                STAGE_B_REPRESENTATIVE_PER_CELL,
                                STAGE_B_UNCERTAINTY_STATES,
                                STATE_SET_SCHEMA, TeacherProtocolError,
                                TARGET_SCHEMA,
                                action_key, ballot_problems,
                                counter_problems, derive_stream,
                                paired_moments, replay_state,
                                sampler_delta, sampler_snapshot,
                                stable_digest, targets, tensor_problems)


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
        "python": sys.version.split()[0],
        "fast_engine": True,
        "require_voids": True,
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
        if payload.get("tree_dirty") or not payload.get("promotable"):
            bad.append("state set is dirty or non-promotable")
        if not payload.get("fast_engine") or not payload.get("require_voids"):
            bad.append("state set lacks compiled/strict provenance")
        if payload.get("seed_start") != 120_000_000:
            bad.append("fresh-deal seed start is not 120000000")
        if any(not isinstance(seed, int) or seed < 120_000_000 for seed in deals):
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
    if payload.get("git") != runtime.get("git"):
        bad.append("state-set git differs from labeller")
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
    return bad


def load_pinned(path: str, expected: str) -> dict:
    if not expected:
        raise TeacherProtocolError("--expected-input-sha256 is required")
    actual = sha256_file(path)
    if actual != expected:
        raise TeacherProtocolError(
            f"input digest mismatch: expected {expected}, got {actual}"
        )
    with open(path) as fh:
        return json.load(fh)


def write_complete(path: str, payload: dict) -> None:
    partial = path + ".partial"
    if os.path.exists(path) or os.path.exists(partial):
        raise TeacherProtocolError(f"refusing to overwrite {path}")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        with open(partial, "x") as fh:
            json.dump(payload, fh, sort_keys=True, separators=(",", ":"))
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(partial, path)
    except Exception:
        if os.path.exists(partial):
            os.remove(partial)
        raise


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
    ap.add_argument("--shard-count", type=int, default=1)
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
            all_records = source["states"]
            selected = all_records[args.shard_index::args.shard_count]
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
        if source_digests() != frozen_source_digests:
            raise TeacherProtocolError(
                "teacher executable digests changed during labelling")
        payload = {
            "schema": schema, "experiment_id": EXPERIMENT,
            "target_schema": TARGET_SCHEMA,
            "stage": args.stage, "mode": args.mode,
            **runtime, "source_digests": frozen_source_digests,
            "input": args.input, "input_sha256": args.expected_input_sha256,
            "state_input_sha256": (
                args.expected_input_sha256 if args.mode == "cheap"
                else source.get("input_sha256")
            ),
            "shard_index": args.shard_index, "shard_count": args.shard_count,
            "continuation": continuation, "counts": counts,
            "state_contract": source.get("state_contract", {
                "one_state_per_deal": source.get("one_state_per_deal"),
                "exam_exclusion": source.get("exam_exclusion"),
                "actor": source.get("actor"),
            }),
            "complete": True, "n_records": len(records), "records": records,
            "records_digest": deterministic_records_digest(records),
            "candidate_world_work": sum(r["candidate_world_work"] for r in records),
            "measured_record_seconds": elapsed,
            "projected_2048_seconds": elapsed / len(records) * 2048,
        }
        write_complete(args.out, payload)
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

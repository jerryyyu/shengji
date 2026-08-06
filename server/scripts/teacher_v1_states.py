"""Capture, diagnose and freeze fresh teacher-v1 gate states.

This is state selection only.  It never computes or stores the 512-world
teacher tensor.  Every deal is assigned one target decision, one data split
and one representative/challenge pool from named hash streams before play.
The small N=30/v11 selector diagnostic is a separate immutable artifact; the
freezer may inspect only those named diagnostics when selecting boundary and
uncertainty rows.

Typical sequence (commands shown for one shard; capture/diagnose can be
sharded):

  teacher_v1_states.py capture --shard-count 8 --shard-index 0 --out ...
  teacher_v1_states.py diagnose --input ... --expected-input-sha256 ... --out ...
  teacher_v1_states.py freeze --stage a --input diagnosed-0.json ... --out ...

No mode launches Stage C or reads candidate outcomes from DEV/CALIB/REPORT.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shengji.ai.memory import Memory                              # noqa: E402
from shengji.ai.registry import make_bot                          # noqa: E402
from shengji.engine.ballot import mc_ballot                       # noqa: E402
from shengji.engine.game import Game                              # noqa: E402
from shengji.teacher_v1 import (EXPERIMENT, REPRESENTATIVE_CELLS, # noqa: E402
                                SAMPLER_COUNTERS, SEED_START,
                                STAGE_A_OTHER_STATES,
                                STAGE_A_REPRESENTATIVE_PER_CELL,
                                STAGE_A_STATES, STAGE_B_STATES,
                                STAGE_B_BOUNDARY_STATES,
                                STAGE_B_REPRESENTATIVE_PER_CELL,
                                STAGE_B_UNCERTAINTY_STATES,
                                STATE_SCHEMA, STATE_SET_SCHEMA,
                                TeacherProtocolError, action_key,
                                ballot_problems, derive_stream,
                                phase_for_trick, replay_state,
                                sampler_delta, sampler_snapshot,
                                split_for_deal, stable_digest, state_id)

CAPTURE_SCHEMA = "teacher-v1-capture-shard-v1"
DIAGNOSTIC_SCHEMA = "teacher-v1-selector-diagnostic-v1"
ACTOR = "mc-strong"
SELECTOR_WORLDS = 30
V11_CHECKPOINT_SHA256 = (
    "cd89d6ed7e9d5f798d69ce546107c4dfbef682c5385de39af527026e39e1c003"
)
DEFAULT_EXAM_SPLITS = (
    "rl_data/corpus_split.v1.json",
    "rl_data/corpus_split_late.v1.json",
    "rl_data/deep_lead_split.v1.json",
)
DEFAULT_EXAM_SPLIT_SHA256 = {
    "rl_data/corpus_split.v1.json":
        "bbc061f9c08f19f490d8b789d5c8f15542e28bdaa5504efb1adfe7ba40d9edc2",
    "rl_data/corpus_split_late.v1.json":
        "9b974ab16f3a76fb089efe8541690d9ecbfdcad9b174bb0623b7d456d0b2aa1c",
    "rl_data/deep_lead_split.v1.json":
        "9d72dcafffc1d8ac983be81f0f33275236f21f850aed019f9d081e0291812df6",
}


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_output(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def write_exclusive(path: str, payload: dict) -> None:
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


def runtime(smoke: bool) -> dict:
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise TeacherProtocolError("set SHENGJI_REQUIRE_VOIDS=1")
    if os.environ.get("SHENGJI_FAST") != "1":
        raise TeacherProtocolError("set SHENGJI_FAST=1")
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise TeacherProtocolError("compiled engine requested but not active")
    dirty = git_output("status", "--porcelain")
    if dirty and not smoke:
        raise TeacherProtocolError("real teacher state work refuses a dirty tree")
    return {
        "git": git_output("rev-parse", "HEAD"), "tree_dirty": bool(dirty),
        "promotable": not smoke,
        "host": os.uname().nodename, "python": sys.version.split()[0],
        "fast_engine": True, "require_voids": True,
        "fast_router_sha256": sha256_file(fast.__file__),
        "fast_binary_sha256": sha256_file(fast._fast.__file__),
        "state_script_sha256": sha256_file(__file__),
    }


def actor_identity() -> dict:
    import shengji.ai.mcbot as mcbot
    import shengji.ai.memory as memory
    import shengji.ai.registry as registry
    import shengji.engine.round as round_mod
    import shengji.teacher_v1 as teacher
    bot = make_bot(ACTOR, seed=1)
    ballot = mc_ballot(bot)
    paths = {
        "mcbot": mcbot.__file__, "memory": memory.__file__,
        "registry": registry.__file__, "engine_round": round_mod.__file__,
        "teacher_replay": teacher.__file__,
    }
    return {
        "policy": ACTOR,
        "identity": stable_digest({
            "files": {name: sha256_file(path) for name, path in sorted(paths.items())},
            "ballot": asdict(ballot),
        }),
        "source_digests": {name: sha256_file(path)
                           for name, path in sorted(paths.items())},
        "ballot": {**asdict(ballot), "digest": ballot.digest},
        "checkpoint": None,
    }


def target_for_deal(experiment_id: str, seed: int) -> dict:
    """Pre-play target, split and selector pool for one deal."""
    stream = derive_stream(
        experiment_id=experiment_id, deal_seed=seed,
        state_id=f"deal:{seed}", purpose="state_selection", fold="capture",
    )
    raw = hashlib.sha256(str(stream["seed"]).encode()).digest()
    phase = ("early", "mid", "late")[raw[0] % 3]
    if phase == "early":
        trick = raw[1] % 5
    elif phase == "mid":
        trick = 5 + raw[1] % 7
    else:
        trick = 12 + raw[1] % 8
    decision = "lead" if raw[2] % 2 == 0 else "follow"
    position = 0 if decision == "lead" else 1 + raw[3] % 3
    # 3/4 representative, 1/4 challenge: the same population proportions as
    # 1,536/512 in the full pilot and 48/16 in Stage A.
    pool = "representative" if raw[4] % 4 else "challenge"
    return {
        "stream": stream, "phase": phase, "trick": trick,
        "decision": decision, "position": position,
        "selector_pool": pool, "split": split_for_deal(experiment_id, seed),
    }


def load_exam_exclusion(paths: list[str]) -> tuple[set[int], dict]:
    seeds: set[int] = set()
    sources = []
    required = {os.path.realpath(path): digest
                for path, digest in DEFAULT_EXAM_SPLIT_SHA256.items()}
    observed_required = set()
    for path in paths:
        if not os.path.exists(path):
            raise TeacherProtocolError(f"missing exam split identity {path}")
        with open(path) as fh:
            payload = json.load(fh)
        digest = sha256_file(path)
        resolved = os.path.realpath(path)
        if resolved in required:
            observed_required.add(resolved)
            if digest != required[resolved]:
                raise TeacherProtocolError(
                    f"exam split digest drift for {path}: {digest}, expected "
                    f"{required[resolved]}")
        assigned = {int(seed) for seed in payload.get("assign", {})}
        seeds |= assigned
        sources.append({
            "path": path, "sha256": digest,
            "deals": len(assigned),
        })
    missing = sorted(path for path in required if path not in observed_required)
    if missing:
        raise TeacherProtocolError(
            f"required DEV/CALIB/REPORT split identities missing: {missing}")
    return seeds, {"verified": True, "overlap": 0, "sources": sources,
                   "excluded_deals": len(seeds)}


def _all_bot_counters(policies) -> dict[str, int]:
    return {name: sum(int(getattr(bot, name, 0)) for bot in policies)
            for name in SAMPLER_COUNTERS}


def _clean_actor_counters(counters: dict) -> list[str]:
    bad = []
    if counters["sample_attempts"] != (
        counters["accepted_worlds"] + counters["failed_worlds"]
    ):
        bad.append("actor sampler attempts do not reconcile")
    forbidden = {name: counters[name] for name in (
        "failed_worlds", "rejected_worlds", "impossible_worlds",
        "short_search_decisions", "zero_world_decisions",
    ) if counters[name]}
    if forbidden:
        bad.append(f"actor strict counters {forbidden}")
    return bad


def capture_deal(seed: int, target: dict, actor: dict) -> dict | None:
    game = Game(random.Random(seed))
    rnd = game.start_round()
    policies = []
    actor_seeds = []
    for seat in range(4):
        stream = derive_stream(
            experiment_id=EXPERIMENT, deal_seed=seed,
            state_id=f"deal:{seed}", purpose="actor", fold="self_play",
            seat=seat, policy=ACTOR,
        )
        actor_seeds.append(stream)
        policies.append(make_bot(ACTOR, seed=stream["seed"]))
    declarations = []
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = policies[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({
                "stage": "deal", "deal_pos": rnd._deal_pos,
                "seat": seat, "cards": list(cards),
            })
    for seat in range(4):
        cards = policies[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({
                "stage": "final", "deal_pos": rnd._deal_pos,
                "seat": seat, "cards": list(cards),
            })
    rnd.finalize_declare()
    assert rnd.banker is not None
    buried = policies[rnd.banker].decide_bury(rnd, rnd.banker)
    final_decl = None if rnd.declaration is None else {
        "seat": rnd.declaration["seat"], "cards": list(rnd.declaration["cards"]),
        "strength": rnd.declaration["strength"],
    }
    setup = {
        "deck": list(rnd.deck), "initial_banker": None,
        "trump_rank": rnd.trump_rank, "banker": rnd.banker,
        "trump_suit": rnd.trump_suit, "trump_is_nt": rnd.trump_is_nt,
        "declarations": declarations, "final_declaration": final_decl,
        "buried": list(buried),
    }
    rnd.bury(rnd.banker, buried)
    plays = []
    while rnd.phase == "play":
        if (len(rnd.history) == target["trick"] and rnd.trick is not None
                and len(rnd.trick.plays) == target["position"]):
            counters = _all_bot_counters(policies)
            bad = _clean_actor_counters(counters)
            if bad:
                raise TeacherProtocolError(f"seed {seed}: {'; '.join(bad)}")
            seat = rnd.turn
            assert seat is not None
            role = "attacker" if rnd.is_attacker(seat) else "defender"
            row = {
                "schema": STATE_SCHEMA, "experiment_id": EXPERIMENT,
                "seed": seed, "seat": seat, "ply": len(plays),
                "trick": len(rnd.history), "phase": phase_for_trick(len(rnd.history)),
                "decision": "lead" if not rnd.trick.plays else "follow",
                "role": role, "split": target["split"],
                "selector_pool": target["selector_pool"],
                "selection_stream": target["stream"],
                "target_position": target["position"],
                "actor_seeds": actor_seeds, "actor_identity": actor["identity"],
                "actor_counters": counters, "setup": setup, "plays": plays,
            }
            row["state_id"] = state_id(row)
            # The target is fixed before play; a mismatch means the event loop
            # reached a different estimand and must not be silently accepted.
            if row["phase"] != target["phase"] or row["decision"] != target["decision"]:
                raise TeacherProtocolError(f"seed {seed}: target stratum drift")
            # Selection probability is assigned only when the finite reservoir
            # is frozen; a raw capture is not yet an admitted training row.
            replay_state({**row, "selection_probability": 1.0, "kind": "raw"})
            return row
        seat = rnd.turn
        assert seat is not None
        cards = policies[seat].decide_play(rnd, seat)
        rnd.play(seat, list(cards))
        plays.append({"seat": seat, "cards": list(cards)})
        bad = _clean_actor_counters(_all_bot_counters(policies))
        if bad:
            raise TeacherProtocolError(f"seed {seed}: {'; '.join(bad)}")
    return None


def capture(args) -> None:
    live = runtime(args.smoke)
    actor = actor_identity()
    exam, exclusion = load_exam_exclusion(args.exam_split)
    if args.seed0 < SEED_START:
        raise TeacherProtocolError(f"seed0 must be at least {SEED_START}")
    if not 0 <= args.shard_index < args.shard_count:
        raise TeacherProtocolError("invalid shard index/count")
    records, unreachable = [], 0
    scanned = list(range(
        args.seed0 + args.shard_index,
        args.seed0 + args.max_deals,
        args.shard_count,
    ))
    for index, seed in enumerate(scanned, 1):
        if seed in exam:
            exclusion["overlap"] += 1
            raise TeacherProtocolError(f"fresh seed {seed} overlaps an exam deal")
        row = capture_deal(seed, target_for_deal(EXPERIMENT, seed), actor)
        if row is None:
            unreachable += 1
        else:
            records.append(row)
        if index % 25 == 0:
            print(f"  {index}/{len(scanned)} deals, {len(records)} states", flush=True)
    payload = {
        "schema": CAPTURE_SCHEMA, "experiment_id": EXPERIMENT, **live,
        "seed_start": SEED_START, "seed0": args.seed0,
        "max_deals": args.max_deals, "shard_index": args.shard_index,
        "shard_count": args.shard_count, "actor": actor,
        "exam_exclusion": exclusion, "one_state_per_deal": True,
        "target_rule": "named hash -> phase/trick/position/pool before play",
        "complete": True, "scanned_deals": len(scanned),
        "unreachable_targets": unreachable, "n_records": len(records),
        "records": records, "records_digest": stable_digest(records),
    }
    write_exclusive(args.out, payload)
    print(f"wrote {args.out}: {len(records)} fresh replay states", flush=True)


def _paired_se(diffs: list[float]) -> float:
    if len(diffs) < 2:
        return float("inf")
    mean = sum(diffs) / len(diffs)
    variance = sum((x - mean) ** 2 for x in diffs) / (len(diffs) - 1)
    return math.sqrt(variance / len(diffs))


def diagnose_row(row: dict, bot, v11) -> dict:
    state = {**row, "selection_probability": 1.0, "kind": "raw"}
    rnd = replay_state(state)
    seat = state["seat"]
    candidates = [list(action_key(action)) for action in bot._candidates(rnd, seat)]
    bad = ballot_problems(rnd, seat, candidates)
    if bad:
        raise TeacherProtocolError(f"{state['state_id']}: {'; '.join(bad)}")
    stream = derive_stream(
        experiment_id=EXPERIMENT, deal_seed=state["seed"],
        state_id=state["state_id"], purpose="belief", fold="selector_n30",
    )
    original_rng = bot.rng
    before = sampler_snapshot(bot)
    values = []
    try:
        bot.rng = random.Random(stream["seed"])
        mem = Memory(rnd, seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
        for world_index in range(SELECTOR_WORLDS):
            sampled = bot._sample_hands(rnd, seat, mem)
            if sampled is None:
                raise TeacherProtocolError(
                    f"{state['state_id']}: selector world {world_index} rejected"
                )
            hands, buried = sampled
            sign = 1 if rnd.is_attacker(seat) else -1
            values.append([
                sign * bot._score(bot._rollout(rnd, seat, hands, buried, candidate))
                for candidate in candidates
            ])
    finally:
        bot.rng = original_rng
    counters = sampler_delta(before, bot)
    bad = _clean_actor_counters(counters)
    if counters["accepted_worlds"] != SELECTOR_WORLDS:
        bad.append("selector did not accept exactly 30 worlds")
    if bad:
        raise TeacherProtocolError(f"{state['state_id']}: {'; '.join(bad)}")
    means = [sum(row_[i] for row_ in values) / len(values)
             for i in range(len(candidates))]
    best = bot._pick_index(candidates, means, list(range(len(candidates))))
    gap = means[best] - means[0]
    picked = best if best != 0 and gap >= bot.MARGIN else 0
    diffs = [row_[best] - row_[0] for row_ in values]

    v11_seed = derive_stream(
        experiment_id=EXPERIMENT, deal_seed=state["seed"],
        state_id=state["state_id"], purpose="selector_policy",
        fold="v11pair", policy="rl-override-v11pair",
    )
    # A new seeded policy per state makes inference order irrelevant.  The net
    # is deterministic today; the seed still binds a future stochastic edit.
    v11 = make_bot("rl-override-v11pair", seed=v11_seed["seed"])
    v11_action = list(action_key(v11.decide_play(rnd, seat)))
    if v11_action not in candidates:
        raise TeacherProtocolError(
            f"{state['state_id']}: v11 action is outside current ballot"
        )
    smart_action = candidates[0]
    n30_action = candidates[picked]
    return {
        "state": row, "state_id": state["state_id"],
        "selector_stream": stream, "selector_counters": counters,
        "candidates": candidates, "means": means,
        "best_index": best, "n30_index": picked,
        "gap": gap, "gap_se": _paired_se(diffs),
        "smart_action": smart_action, "n30_action": n30_action,
        "v11_action": v11_action, "v11_stream": v11_seed,
        "disagreement": len({action_key(smart_action), action_key(n30_action),
                             action_key(v11_action)}) > 1,
    }


def diagnose(args) -> None:
    live = runtime(args.smoke)
    if sha256_file(args.input) != args.expected_input_sha256:
        raise TeacherProtocolError("capture input digest mismatch")
    with open(args.input) as fh:
        capture_payload = json.load(fh)
    if capture_payload.get("schema") != CAPTURE_SCHEMA \
            or not capture_payload.get("complete"):
        raise TeacherProtocolError("input is not a complete capture shard")
    if (not args.smoke and (capture_payload.get("tree_dirty")
                            or not capture_payload.get("promotable"))):
        raise TeacherProtocolError(
            "real selector diagnostics refuse dirty/non-promotable capture")
    for key in ("git", "python", "fast_binary_sha256",
                "fast_router_sha256", "state_script_sha256"):
        if capture_payload.get(key) != live.get(key):
            raise TeacherProtocolError(f"capture/diagnostic {key} drift")
    stored_actor = capture_payload.get("actor", {})
    live_actor = actor_identity()
    if (stored_actor.get("identity") != live_actor["identity"]
            or stored_actor.get("source_digests") != live_actor["source_digests"]
            or stored_actor.get("ballot", {}).get("digest")
            != live_actor["ballot"]["digest"]):
        raise TeacherProtocolError("capture actor identity drift")
    bot = make_bot("mc-strong", seed=1)
    rows = capture_payload.get("records", [])
    diagnostics = []
    for index, row in enumerate(rows, 1):
        diagnostics.append(diagnose_row(row, bot, None))
        if index % 25 == 0:
            print(f"  {index}/{len(rows)} selector diagnostics", flush=True)
    v11_path = "snapshots_v11pair/ep07.npz"
    v11_digest = sha256_file(v11_path)
    if v11_digest != V11_CHECKPOINT_SHA256:
        raise TeacherProtocolError(
            f"frozen v11 selector checkpoint {v11_digest}, expected "
            f"{V11_CHECKPOINT_SHA256}")
    payload = {
        "schema": DIAGNOSTIC_SCHEMA, "experiment_id": EXPERIMENT, **live,
        "input": args.input, "input_sha256": args.expected_input_sha256,
        "actor": capture_payload["actor"],
        "exam_exclusion": capture_payload["exam_exclusion"],
        "one_state_per_deal": True, "selector_worlds": SELECTOR_WORLDS,
        "selector_policy": "current mc-strong N=30 raw-point objective",
        "v11_policy": "rl-override-v11pair@0.02",
        "v11_checkpoint": v11_path,
        "v11_checkpoint_sha256": v11_digest,
        "complete": True, "n_records": len(diagnostics),
        "records": diagnostics, "records_digest": stable_digest(diagnostics),
    }
    write_exclusive(args.out, payload)
    print(f"wrote {args.out}: {len(diagnostics)} selector diagnostics", flush=True)


def selection_priority(stage: str, kind: str, row: dict) -> str:
    return hashlib.sha256(
        f"{EXPERIMENT}|{stage}|{kind}|{row['state_id']}".encode()
    ).hexdigest()


def _selected_state(diag: dict, kind: str, probability: float, *,
                    design: str, eligible: int, selected: int,
                    rank: int, deployment_weightable: bool) -> dict:
    state = dict(diag["state"])
    state["kind"] = kind
    state["selection_probability"] = probability
    state["selection_metadata"] = {
        "design": design, "eligible": eligible, "selected": selected,
        "rank": rank, "deployment_weightable": deployment_weightable,
    }
    return state


def select_gate_states(diagnostics: list[dict], stage: str,
                       excluded_deals: set[int]) -> tuple[list[dict], list[str]]:
    rep_q = (STAGE_A_REPRESENTATIVE_PER_CELL if stage == "a"
             else STAGE_B_REPRESENTATIVE_PER_CELL)
    boundary_q = (STAGE_A_OTHER_STATES // 2 if stage == "a"
                  else STAGE_B_BOUNDARY_STATES)
    uncertainty_q = (STAGE_A_OTHER_STATES // 2 if stage == "a"
                     else STAGE_B_UNCERTAINTY_STATES)
    problems = []
    eligible = [diag for diag in diagnostics
                if diag["state"]["seed"] not in excluded_deals]
    by_cell = defaultdict(list)
    for diag in eligible:
        state = diag["state"]
        if state["selector_pool"] == "representative":
            by_cell[(state["phase"], state["role"], state["decision"])].append(diag)
    selected, used = [], set()
    for cell in REPRESENTATIVE_CELLS:
        rows = sorted(by_cell[cell], key=lambda row: selection_priority(stage, "rep", row))
        if len(rows) < rep_q:
            problems.append(f"representative {cell}: {len(rows)} available, need {rep_q}")
            continue
        probability = rep_q / len(rows)
        for rank, diag in enumerate(rows[:rep_q], 1):
            selected.append(_selected_state(
                diag, "representative", probability,
                design="hash_reservoir_within_stratum", eligible=len(rows),
                selected=rep_q, rank=rank, deployment_weightable=True))
            used.add(diag["state_id"])

    challenge = [diag for diag in eligible
                 if diag["state"]["selector_pool"] == "challenge"
                 and diag["state_id"] not in used]
    boundary = sorted(
        challenge,
        key=lambda row: (abs(row["gap"] - 5.0),
                         selection_priority(stage, "boundary", row)),
    )
    if len(boundary) < boundary_q:
        problems.append(f"boundary supply {len(boundary)}, need {boundary_q}")
    boundary = boundary[:boundary_q]
    boundary_ids = {row["state_id"] for row in boundary}
    # These are deterministic challenge ranks, not a probability sample from
    # deployment.  Record conditional inclusion as 1 and explicitly forbid
    # inverse-probability use; q/N here would be a plausible-looking lie.
    selected += [_selected_state(
        row, "boundary", 1.0,
        design="deterministic_closest_to_margin", eligible=len(challenge),
        selected=boundary_q, rank=rank, deployment_weightable=False)
        for rank, row in enumerate(boundary, 1)]

    remaining = [row for row in challenge if row["state_id"] not in boundary_ids]
    disagree = sorted(
        [row for row in remaining if row["disagreement"]],
        key=lambda row: (-row["gap_se"],
                         selection_priority(stage, "uncertainty", row)),
    )
    fallback = sorted(
        [row for row in remaining if not row["disagreement"]],
        key=lambda row: (-row["gap_se"],
                         selection_priority(stage, "uncertainty-fill", row)),
    )
    uncertainty = (disagree + fallback)[:uncertainty_q]
    if len(uncertainty) < uncertainty_q:
        problems.append(f"uncertainty supply {len(uncertainty)}, need {uncertainty_q}")
    selected += [_selected_state(
        row, "uncertainty", 1.0,
        design="deterministic_disagreement_then_se", eligible=len(remaining),
        selected=uncertainty_q, rank=rank, deployment_weightable=False)
        for rank, row in enumerate(uncertainty, 1)]
    selected.sort(key=lambda state: selection_priority(
        stage, state["kind"], {"state_id": state["state_id"]}
    ))
    return selected, problems


def freeze(args) -> None:
    live = runtime(args.smoke)
    diagnostics, manifests, problems = [], [], []
    for path in args.input:
        with open(path) as fh:
            payload = json.load(fh)
        manifests.append(payload)
        if payload.get("schema") != DIAGNOSTIC_SCHEMA or not payload.get("complete"):
            problems.append(f"{path}: incomplete/wrong diagnostic schema")
        if not args.smoke and (payload.get("tree_dirty")
                               or not payload.get("promotable")):
            problems.append(f"{path}: dirty/non-promotable diagnostics")
        if payload.get("records_digest") != stable_digest(payload.get("records", [])):
            problems.append(f"{path}: diagnostic record digest")
        diagnostics.extend(payload.get("records", []))
    if not manifests:
        problems.append("no diagnostic inputs")
    else:
        first = manifests[0]
        for index, payload in enumerate(manifests[1:], 1):
            for key in ("git", "actor", "exam_exclusion", "selector_worlds",
                        "selector_policy", "v11_checkpoint_sha256", "python",
                        "fast_binary_sha256", "fast_router_sha256",
                        "state_script_sha256"):
                if payload.get(key) != first.get(key):
                    problems.append(f"diagnostic {index}: {key} drift")
    ids = [diag.get("state_id") for diag in diagnostics]
    deals = [diag.get("state", {}).get("seed") for diag in diagnostics]
    if len(ids) != len(set(ids)) or len(deals) != len(set(deals)):
        problems.append("diagnostic inputs duplicate a state/deal")
    excluded_deals: set[int] = set()
    if args.stage == "b":
        if not args.exclude_state_set and not args.smoke:
            problems.append("Stage B requires --exclude-state-set Stage-A.json")
        elif args.exclude_state_set:
            with open(args.exclude_state_set) as fh:
                previous = json.load(fh)
            if previous.get("schema") != STATE_SET_SCHEMA:
                problems.append("excluded Stage-A set schema")
            excluded_deals = {state["seed"] for state in previous.get("states", [])}
    if problems:
        raise TeacherProtocolError("freeze preflight: " + "; ".join(problems))
    states, selection_problems = select_gate_states(
        diagnostics, args.stage, excluded_deals
    )
    problems += selection_problems
    required = STAGE_A_STATES if args.stage == "a" else STAGE_B_STATES
    if len(states) != required:
        problems.append(f"selected {len(states)}, required {required}")
    if len({state["seed"] for state in states}) != len(states):
        problems.append("selected more than one state per deal")
    for state in states:
        try:
            replay_state(state)
        except Exception as exc:
            problems.append(f"{state.get('state_id')}: replay {exc}")
    if problems:
        raise TeacherProtocolError("freeze refused: " + "; ".join(problems))
    first = manifests[0]
    payload = {
        "schema": STATE_SET_SCHEMA, "experiment_id": EXPERIMENT,
        "stage": args.stage, **live, "seed_start": SEED_START,
        "actor": first["actor"], "exam_exclusion": first["exam_exclusion"],
        "one_state_per_deal": True,
        "split_rule": "sha256(experiment_id|split|deal_seed) mod 20 = 70/15/15",
        "selector_contract": {
            "representative_per_cell": (
                STAGE_A_REPRESENTATIVE_PER_CELL if args.stage == "a"
                else STAGE_B_REPRESENTATIVE_PER_CELL
            ),
            "boundary": STAGE_A_OTHER_STATES // 2 if args.stage == "a"
                        else STAGE_B_BOUNDARY_STATES,
            "uncertainty": STAGE_A_OTHER_STATES // 2 if args.stage == "a"
                           else STAGE_B_UNCERTAINTY_STATES,
            "boundary_target_margin": 5.0,
            "uncertainty_order": "disagreement first, then paired SE",
            "challenge_deployment_weightable": False,
            "diagnostics_inspected": (
                "N30 gap-to-5, paired SE, Smart/N30/v11 disagreement only"
            ),
        },
        "diagnostic_inputs": [
            {"path": path, "sha256": sha256_file(path)} for path in args.input
        ],
        "excluded_stage_a": (
            None if not args.exclude_state_set else {
                "path": args.exclude_state_set,
                "sha256": sha256_file(args.exclude_state_set),
                "deals": len(excluded_deals),
            }
        ),
        "complete": True, "requested": required, "selected": len(states),
        "states": states, "states_digest": stable_digest(states),
    }
    write_exclusive(args.out, payload)
    print(f"wrote frozen Stage {args.stage.upper()} set {args.out}: {len(states)} states")


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    cap = sub.add_parser("capture")
    cap.add_argument("--seed0", type=int, default=SEED_START)
    cap.add_argument("--max-deals", type=int, default=2048)
    cap.add_argument("--shard-index", type=int, default=0)
    cap.add_argument("--shard-count", type=int, default=1)
    cap.add_argument("--exam-split", action="append",
                     default=list(DEFAULT_EXAM_SPLITS))
    cap.add_argument("--out", required=True)
    cap.add_argument("--smoke", action="store_true")
    diag = sub.add_parser("diagnose")
    diag.add_argument("--input", required=True)
    diag.add_argument("--expected-input-sha256", required=True)
    diag.add_argument("--out", required=True)
    diag.add_argument("--smoke", action="store_true")
    freeze_ = sub.add_parser("freeze")
    freeze_.add_argument("--stage", choices=("a", "b"), required=True)
    freeze_.add_argument("--input", action="append", required=True)
    freeze_.add_argument("--exclude-state-set")
    freeze_.add_argument("--out", required=True)
    freeze_.add_argument("--smoke", action="store_true")
    return ap


def main() -> None:
    args = parser().parse_args()
    try:
        if args.mode == "capture":
            capture(args)
        elif args.mode == "diagnose":
            diagnose(args)
        else:
            freeze(args)
    except (OSError, ValueError, TeacherProtocolError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3)


if __name__ == "__main__":
    main()

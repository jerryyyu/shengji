"""Shared current-production rollout tensors and final R4/W32 decision audit.

Collect once over the UNION of the three admitted action sets. Rank-only arms
and rank+MC-weighted arms then consume identical selection/report tensors.
Nothing changes the shipped bot, continuation, sampler or production registry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import time

from ..ai.cwv_policy import sample_worlds
from ..ai.mcbot import _child_seed
from ..ai.registry import REGISTRY
from .cwv_bury_diagnostic import reopen_state, derived_seed
from .search_screen import _publish
from .r4_w32_weight_diagnostic import require_capture_binding

BASE = REGISTRY["mc-s0-report-lcb"]


def moments(values, weights=None):
    if weights is None:
        return sum(values)/len(values), BASE._paired_se(sum(values), sum(x*x for x in values), len(values))
    if len(values) != len(weights) or sum(weights) != 10**9 or any(w <= 0 for w in weights):
        raise ValueError("positive normalized paired weights required")
    ws = [w/1e9 for w in weights]
    mean = math.fsum(w*v for w,v in zip(ws, values))
    square = math.fsum(w*w for w in ws)
    if len(values) < 2 or square >= 1:
        raise ValueError("insufficient effective report population")
    variance = math.fsum(w*w*(v-mean)**2 for w,v in zip(ws, values))/(1-square)
    return mean, math.sqrt(max(0, variance))


def nominate(actions, admitted, matrix, weights=None):
    bot = BASE(seed=0)
    values = [moments([row[i] for row in matrix], weights)[0] for i in admitted]
    ordered = [actions[i] for i in admitted]
    if len(admitted) == 1:
        return admitted[0], None, values
    raw = bot._pick_index(ordered, values, range(len(admitted)))
    challenger = bot._pick_index(ordered, values, range(1, len(admitted)))
    return admitted[raw], admitted[challenger], values


def finalize(incumbent, challenger, matrix, weights=None):
    if challenger is None:
        return {"played": incumbent, "reason": "no_report_challenger"}
    bot = BASE(seed=0)
    gap, se = moments([row[challenger]-row[incumbent] for row in matrix], weights)
    critical = bot._report_critical(len(matrix))
    statistic = gap-critical*se
    override = statistic >= bot.REPORT_MIN_GAIN
    return {"played": challenger if override else incumbent,
            "gap": gap, "se": se, "statistic": statistic,
            "critical": critical, "threshold": bot.REPORT_MIN_GAIN,
            "reason": "report_lcb_override" if override else "report_lcb_below_min_gain"}


def collect(args):
    root = args.capture_root
    capture = json.loads((root/"private-world-values.json").read_bytes())
    rank = json.loads((root/"rank-comparison-typed-v2.json").read_bytes())
    require_capture_binding(root/"private-world-values.json", rank, root/"r4-marginals.json")
    raw = Path(capture["record_path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != capture["record_sha256"]:
        raise ValueError("saved source trajectory changed")
    row = json.loads(raw)
    rnd = reopen_state(row["state"])
    rnd.bury(rnd.banker, row["buried"])
    for play in row["transcript"][:capture["decision"]]:
        rnd.play(play["seat"], play["attempted"])
    seat = rnd.turn
    if seat != capture["seat"]:
        raise ValueError("reopened acting seat differs")
    union = sorted(set(rank["baseline_shortlist"]).union(
        *(set(arm["shortlist"]) for arm in rank["arms"].values())))
    seed = derived_seed("r4-w32-shared-dev-20260910-v1", row["state"]["index"])
    report_seed = _child_seed(random.Random(seed).getstate(), "s0-report")
    args.out.mkdir(parents=True, exist_ok=True)
    for fold, n, stream in (("selection", 30, seed), ("report", 300, report_seed)):
        directory = args.out/fold
        output = directory/"private-world-values.json"
        if output.exists():
            previous = json.loads(output.read_bytes())
            if (previous["parent_actor_sha256"] != capture["actor_sha256"]
                    or previous["union_indices"] != union or previous["world_seed"] != stream):
                raise ValueError("completed MC fold differs from requested actor/actions/stream")
            continue
        bot = BASE(seed=stream)
        worlds, attempts = sample_worlds(bot, rnd, seat, n)
        if len(worlds) != n:
            raise ValueError("MC fold underfilled")
        matrix = []
        started = time.monotonic()
        for wi, (hands, buried) in enumerate(worlds):
            sampled = {other: hands[other] for other in range(4) if other != seat}
            exact = bot._new_exact_world_session(rnd, buried)
            values = []
            for index in union:
                value = bot._score(bot._rollout(rnd, seat, sampled, buried,
                    capture["actions"][index], exact_session=exact))
                values.append(value if rnd.is_attacker(seat) else -value)
            matrix.append(values)
            if (wi+1) % 30 == 0:
                print(json.dumps({"fold": fold, "worlds": wi+1, "total": n,
                                  "wall_s": round(time.monotonic()-started, 2)}), flush=True)
        directory.mkdir(parents=True, exist_ok=True)
        _publish(directory/"actor.json", json.loads((root/"actor.json").read_bytes()))
        result = {**capture, "actions": [capture["actions"][i] for i in union],
                  "means": [sum(r[i] for r in matrix)/n for i in range(len(union))],
                  "values_world_major": matrix, "worlds": worlds, "world_seed": stream,
                  "sampling_attempts": attempts, "union_indices": union,
                  "parent_actor_sha256": capture["actor_sha256"], "fold": fold,
                  "schema": "r4-w32-mc-fold-dev-v1", "ranking_wall_s": 0,
                  "rollout_wall_s": time.monotonic()-started,
                  "scope": "shared full-game production-continuation scores, not gameplay strength"}
        _publish(output, result)


def reduce(args, *, emit=True):
    root = args.capture_root
    capture = json.loads((root/"private-world-values.json").read_bytes())
    ranking = json.loads((root/getattr(args, "rank_file", "rank-comparison-typed-v2.json")).read_bytes())
    require_capture_binding(root/"private-world-values.json", ranking, root/"r4-marginals.json")
    expected = getattr(args, "expected_energy_multiplier", None)
    if expected is not None and ranking.get("energy_multiplier", 1) != expected:
        raise ValueError("ranking energy multiplier differs from requested experiment")
    folds = {f: json.loads((args.out/f/"private-world-values.json").read_bytes()) for f in ("selection", "report")}
    weights = {f: json.loads((args.out/f/getattr(args, "weights_file", "weights-v2.json")).read_bytes()) for f in folds}
    union = folds["selection"]["union_indices"]
    if union != folds["report"]["union_indices"]:
        raise ValueError("selection/report action identity differs")
    for f in folds:
        require_capture_binding(args.out/f/"private-world-values.json", weights[f], root/"r4-marginals.json")
        if folds[f]["fold"] != f or len(folds[f]["worlds"]) != (30 if f == "selection" else 300):
            raise ValueError("MC selection/report fold population differs")
        if capture["actor_sha256"] != folds[f]["actor_sha256"] or capture["actor_sha256"] != weights[f]["actor_sha256"]:
            raise ValueError("MC fold or weights actor differs")
        if weights[f].get("energy_multiplier", 1) != ranking.get("energy_multiplier", 1):
            raise ValueError("ranking and MC energy multipliers differ")
    baseline = ranking["baseline_shortlist"]
    missing = sorted(set(baseline).union(*(set(a["shortlist"]) for a in ranking["arms"].values()))-set(union))
    if missing:
        raise ValueError(f"missing admitted actions in retained MC tensor: {missing}")
    decisions = {}
    recipes = [("ordinary", baseline, None)]
    for arm in ranking["arms"]:
        recipes += [(arm+":rank-only", ranking["arms"][arm]["shortlist"], None),
                    (arm+":rank+mc", ranking["arms"][arm]["shortlist"], arm),
                    (arm+":mc-only", baseline, arm)]
    for name, admitted, weighted_arm in recipes:
        chosen = [union.index(i) for i in admitted]
        sw = None if weighted_arm is None else weights["selection"]["arms"][weighted_arm]["world_weights_ppb"]
        rw = None if weighted_arm is None else weights["report"]["arms"][weighted_arm]["world_weights_ppb"]
        raw, challenger, values = nominate(folds["selection"]["actions"], chosen,
            folds["selection"]["values_world_major"], sw)
        final = finalize(chosen[0], challenger, folds["report"]["values_world_major"], rw)
        decisions[name] = {**final, "played": union[final["played"]],
            "raw_winner": union[raw], "challenger": None if challenger is None else union[challenger],
            "selection_means": values, "admitted": admitted}
    result = {"schema": "r4-w32-final-mc-dev-v1", "actor_sha256": capture["actor_sha256"],
              "energy_multiplier": ranking.get("energy_multiplier", 1),
              "decisions": decisions, "selection_worlds": 30, "report_worlds": 300,
              "strength_claim": False, "scope": "shared-world fixed-state diagnostic; weighted bound is exploratory"}
    target = args.out/getattr(args, "result_file", "final-decisions-v2.json")
    if target.exists():
        saved = json.loads(target.read_bytes())
        saved.setdefault("energy_multiplier", 1)
        if saved != result:
            raise ValueError("completed MC reduction differs from current inputs")
    else:
        _publish(target, result)
    if emit:
        print(json.dumps(result, indent=2))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("collect", "reduce"))
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rank-file", default="rank-comparison-typed-v2.json")
    parser.add_argument("--weights-file", default="weights-v2.json")
    parser.add_argument("--result-file", default="final-decisions-v2.json")
    args = parser.parse_args(argv)
    (collect if args.mode == "collect" else reduce)(args)


if __name__ == "__main__":
    main()

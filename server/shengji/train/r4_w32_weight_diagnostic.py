"""Reduce shared W32 values under archived R4 marginal-ratio energies.

This is an admission/ranking diagnostic, not a gameplay test or a claim that
marginal probabilities define a joint posterior. No temperature fitting.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys


def require_capture_binding(capture_path, result, predictions_path=None):
    if result.get("capture_file_sha256") != hashlib.sha256(capture_path.read_bytes()).hexdigest():
        raise ValueError("weight/rank source capture bytes differ")
    if predictions_path is not None and result.get("predictions_file_sha256") != hashlib.sha256(
            predictions_path.read_bytes()).hexdigest():
        raise ValueError("weight/rank prediction bytes differ")


def cell_count(world, seat, card, receiver):
    if receiver == "hidden-kitty":
        cards = world[1]
    elif receiver in ("seat-relative-1", "seat-relative-2", "seat-relative-3"):
        cards = world[0][(seat + int(receiver[-1])) % 4]
    else:
        raise ValueError("unexpected hidden receiver")
    count = Counter(cards)[card]
    if not 0 <= count <= 2:
        raise ValueError("world violates physical card count")
    return count


def marginal_energies(ownership, worlds, reference, seat):
    """PR179's mean log ratio with independent N256 Jeffreys reference."""
    if len(reference) != 256 or not worlds:
        raise ValueError("requires independent 256-world reference and nonempty ranking worlds")
    rows = sorted(ownership["count_probabilities"], key=lambda r: (r["card"], r["receiver"]))
    if not rows or len({(r["card"], r["receiver"]) for r in rows}) != len(rows):
        raise ValueError("empty or duplicate marginal cells")
    refs = []
    for row in rows:
        p = row["count_probability_ppb"]
        if len(p) != 3 or any(type(x) is not int or x < 0 for x in p) or sum(p) != 10**9:
            raise ValueError("invalid marginal probability mass")
        counts = Counter(cell_count(w, seat, row["card"], row["receiver"]) for w in reference)
        refs.append([(counts[n] + .5) / 257.5 for n in range(3)])
    scores = []
    for world in worlds:
        log_ratio = 0.0
        for row, ref in zip(rows, refs, strict=True):
            count = cell_count(world, seat, row["card"], row["receiver"])
            log_ratio += math.log(max(row["count_probability_ppb"][count] / 1e9, 1e-12) / ref[count])
        scores.append(round(log_ratio / len(rows) * 1e9))
    return tuple(scores)


def shortlist(actions, means, incumbent, k=4):
    keys = [tuple(sorted(a)) for a in actions]
    base = keys.index(tuple(sorted(incumbent)))
    return [base, *sorted((i for i in range(len(keys)) if i != base),
                         key=lambda i: (-means[i], keys[i]))[:k]]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--archive-server", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--energy-multiplier", type=int, choices=(1, 4), default=1,
                        help="fixed DEV contrast, not a fitted temperature")
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error("choose a fresh output")
    capture, predictions = [json.loads(p.read_bytes()) for p in (args.capture, args.predictions)]
    if capture["actor_sha256"] != predictions["actor_sha256"]:
        raise ValueError("capture/model actor mismatch")
    # Standalone process; keep EXACT archived temperature/quantization policy.
    if "shengji" in sys.modules:
        raise RuntimeError("run reducer as a standalone process")
    sys.path.insert(0, str(args.archive_server.resolve()))
    from shengji.rl.belief_policy_weighting import common_tempered_world_weights, world_log_ratio_nanonats
    from shengji.rl.belief_reopen import actor_observation_from_dict_allow_incomplete
    from shengji.rl.belief_reference import SampledOwnershipWorldV1, ReceiverCardsV1, reference_ownership
    from shengji.rl.belief_corpus import canonical_json_bytes
    from shengji.rl.belief_ownership import ownership_from_bytes
    from shengji.rl.belief_v2_scoring import v2_scoring_actor
    from shengji.rl.belief_v2_human_corpus import UNIVERSAL_POLICY_IDS
    source_actor = actor_observation_from_dict_allow_incomplete(
        json.loads((args.capture.parent / "actor.json").read_bytes()))
    if source_actor.sha256() != capture["actor_sha256"]:
        raise ValueError("capture/actor bytes mismatch")
    actor = v2_scoring_actor(source_actor)

    def typed_world(world):
        rows = [ReceiverCardsV1(f"seat-relative-{r}", tuple(sorted(Counter(
            world[0][(capture["seat"] + r) % 4]).items()))) for r in (1, 2, 3)]
        if actor.hidden_burial_size:
            rows.append(ReceiverCardsV1("hidden-kitty", tuple(sorted(Counter(world[1]).items()))))
        return SampledOwnershipWorldV1(actor.sha256(), tuple(rows))

    reference = reference_ownership(actor, tuple(map(typed_world, capture["reference_worlds"])),
        sampler_source_sha256=hashlib.sha256(args.capture.read_bytes()).hexdigest(),
        behavior_policy_ids=UNIVERSAL_POLICY_IDS)
    typed_worlds = tuple(map(typed_world, capture["worlds"]))
    arms = ("synthetic-primary", "hard-geometry-label-permutation")
    energies = [marginal_energies(predictions["arms"][arm]["ownership"],
                                 capture["worlds"], capture["reference_worlds"], capture["seat"])
                for arm in arms]
    for arm, scores in zip(arms, energies, strict=True):
        ownership = ownership_from_bytes(actor, canonical_json_bytes(predictions["arms"][arm]["ownership"]))
        exact = world_log_ratio_nanonats(actor, ownership, reference, typed_worlds)
        if scores != exact:
            raise ValueError("marginal-energy calculation differs from archived typed implementation")
    weighted = common_tempered_world_weights(*(
        tuple(score * args.energy_multiplier for score in arm) for arm in energies))
    matrix = capture["values_world_major"]
    if (len(matrix) != len(capture["worlds"]) or
            any(len(row) != len(capture["actions"]) or any(not math.isfinite(v) for v in row)
                for row in matrix)):
        raise ValueError("nonfinite or mismatched world/action matrix")
    baseline = capture["means"]
    base_set = shortlist(capture["actions"], baseline, capture["incumbent"])
    result = {"schema": "r4-w32-weight-rank-dev-v1", "actor_sha256": capture["actor_sha256"],
              "capture_file_sha256": hashlib.sha256(args.capture.read_bytes()).hexdigest(),
              "predictions_file_sha256": hashlib.sha256(args.predictions.read_bytes()).hexdigest(),
              "actions": len(baseline), "worlds": len(matrix), "baseline_shortlist": base_set,
              "ranking_wall_s": capture["ranking_wall_s"], "arms": {},
              "final_mc_evaluated": False, "strength_claim": False,
              "typed_world_constraints_passed": True, "archived_energy_exact_parity": True,
              "energy_multiplier": args.energy_multiplier,
              "scope": "fixed mean-energy multiplier with PR179 concentration guard; unchanged-production proposal"}
    for arm, weights in zip(arms, weighted, strict=True):
        means = [math.fsum(row[a] * w / 1e9 for row, w in zip(
            matrix, weights.normalized_weight_ppb, strict=True)) for a in range(len(baseline))]
        selected = shortlist(capture["actions"], means, capture["incumbent"])
        result["arms"][arm] = {"shortlist": selected,
            "changed_admitted_actions": len(set(selected) - set(base_set)),
            "means": means, "max_value_shift": max(abs(a-b) for a,b in zip(means, baseline)),
            "ess_fraction": weights.ess_ppb / 1e9 / len(matrix), "alpha_ppb": weights.alpha_ppb,
            "world_weights_ppb": list(weights.normalized_weight_ppb)}
    with args.out.open("x") as stream:
        json.dump(result, stream, sort_keys=True)
        stream.write("\n")
    print(json.dumps({**result, "arms": {a: {k:v for k,v in r.items() if k not in (
        "means", "world_weights_ppb")} for a,r in result["arms"].items()}}, indent=2))


if __name__ == "__main__":
    main()

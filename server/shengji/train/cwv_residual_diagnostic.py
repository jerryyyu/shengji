"""DEV diagnostic for shared-world model-corrected rollout estimates.

No policy registration or live search change. Both matrices are acting-team
signed levels. A fresh uniform subset is shared across candidates; the full
matrix is a finite-world reference, NOT hidden-state truth or independent
gameplay evidence. Admission must not be chosen using these diagnostic worlds.
"""
from __future__ import annotations

import random
import time

import numpy as np


def _matrix(value):
    a = np.asarray(value, dtype=np.float64)
    if a.ndim != 2 or min(a.shape) < 1 or not np.isfinite(a).all():
        raise ValueError("expected finite nonempty world-by-action matrix")
    return a


def corrected_estimate(model, rollout_subset, indices):
    """mean_N(V) + mean_m(R-V), with caller-sampled shared world indices."""
    v, r = _matrix(model), _matrix(rollout_subset)
    ids = list(indices)
    if (not ids or any(type(i) is not int or not 0 <= i < len(v) for i in ids)
            or len(set(ids)) != len(ids) or r.shape != (len(ids), v.shape[1])):
        raise ValueError("residual subset must be unique aligned world indices")
    return v.mean(axis=0) + (r - v[ids]).mean(axis=0)


def compare_estimators(model, rollout, *, subset_worlds, repeats=256, seed=1):
    v, r = _matrix(model), _matrix(rollout)
    if v.shape != r.shape:
        raise ValueError("model and reference world/action matrices must align")
    if (type(subset_worlds) is not int or not 1 <= subset_worlds <= len(v)
            or type(repeats) is not int or repeats < 1 or type(seed) is not int):
        raise ValueError("invalid subset/repetition recipe")
    rng = random.Random(seed)
    reference = r.mean(axis=0)
    # All pairwise action differences, not absolute state-value fit.
    left, right = np.triu_indices(v.shape[1], k=1)
    truth_gaps = reference[left] - reference[right]
    sums = {name: {"pair_gap_squared_error": 0., "finite_reference_regret": 0.,
                   "top1_matches": 0} for name in ("small_mc", "corrected")}
    for _ in range(repeats):
        ids = rng.sample(range(len(v)), subset_worlds)
        estimates = {"small_mc": r[ids].mean(axis=0),
                     "corrected": corrected_estimate(v, r[ids], ids)}
        for name, estimate in estimates.items():
            row = sums[name]
            delta = estimate[left] - estimate[right] - truth_gaps
            row["pair_gap_squared_error"] += float(np.mean(delta ** 2)) if len(delta) else 0.
            chosen = int(np.argmax(estimate))
            row["finite_reference_regret"] += float(reference.max() - reference[chosen])
            row["top1_matches"] += int(chosen == int(np.argmax(reference)))
    return {"schema": "cwv-residual-diagnostic-v1", "units": "acting-team-signed-level",
            "worlds": len(v), "actions": v.shape[1], "subset_worlds": subset_worlds,
            "repeats": repeats, "subset_seed": seed,
            "reference_means": reference.tolist(),
            "estimates": {name: {key: value / repeats for key, value in row.items()}
                          for name, row in sums.items()},
            "interpretation": "subsets reuse one finite world population; not independent games or a strength claim"}


def collect_reference(rnd, seat, actions, evaluator, *, worlds=64, seed=1, batch_size=128):
    """Real sampler + actual MC continuations; bounded saved-state diagnostic.

    Rollouts remain the existing heuristic MC continuation. Model leaves use
    the existing engine-root/finish-trick convention. No true opponent hand
    enters sampling or action selection. The supplied ballot is frozen before
    these worlds are drawn; this function never chooses it from model scores.
    """
    from ..ai.cwv_policy import afterstate, sample_worlds
    from ..ai.registry import make_bot
    from ..engine.legal import check_in_hand, uniform_suit, validate_follow
    from ..rl.value_afterstate import category_signed_level, signed_level_category

    if (type(worlds) is not int or worlds < 2 or type(batch_size) is not int
            or batch_size < 1 or type(seed) is not int):
        raise ValueError("invalid reference recipe")
    if rnd.phase != "play" or seat != rnd.turn or not actions:
        raise ValueError("reference requires acting seat and frozen nonempty ballot")
    keys = [tuple(sorted(a)) for a in actions]
    if len(set(keys)) != len(keys):
        raise ValueError("reference ballot contains duplicate actions")
    for action in actions:
        check_in_hand(rnd.hands[seat], action)
        if rnd.trick.plays:
            validate_follow(action, rnd.hands[seat], rnd.trick.plays[0].cards, rnd.ordering)
        elif uniform_suit(action, rnd.ordering) is None:
            raise ValueError("reference lead must have one effective suit")
    bot = make_bot("mc-s0-report-lcb", seed=seed)
    wall, cpu = time.perf_counter(), time.process_time()
    sampled, attempts = sample_worlds(bot, rnd, seat, worlds)
    if len(sampled) != worlds:
        raise ValueError("reference legal world population underfilled")
    v, r, point_scores = (np.empty((worlds, len(actions)), dtype=np.float64) for _ in range(3))
    pending, locations = [], []

    def flush():
        if not pending:
            return
        values = np.asarray(evaluator.score(pending, seat), dtype=np.float64)
        if values.shape != (len(pending),) or not np.isfinite(values).all():
            raise ValueError("model must return one finite acting-team value per leaf")
        for location, value in zip(locations, values, strict=True):
            v[location] = value
        pending.clear()
        locations.clear()

    attack = rnd.is_attacker(seat)
    for world, (hands, buried) in enumerate(sampled):
        session = bot._new_exact_world_session(rnd, buried)
        for index, action in enumerate(actions):
            pending.append(afterstate(rnd, seat, hands, buried, action, finish_trick=True))
            locations.append((world, index))
            if len(pending) >= batch_size:
                flush()
            opponents = {s: hands[s] for s in range(4) if s != seat}
            points = bot._rollout(rnd, seat, opponents, buried, action, exact_session=session)
            if not np.isfinite(points) or float(points) != int(points):
                raise ValueError("reference rollout points must be an integral terminal score")
            r[world, index] = category_signed_level(signed_level_category(int(points), attack))
            point_scores[world, index] = bot._score(points) * (1 if attack else -1)
    flush()
    return {"model": v.tolist(), "rollout": r.tolist(), "actions": [list(k) for k in keys],
            "units": "acting-team-signed-level", "world_seed": seed,
            "sample_attempts": attempts, "worlds": worlds,
            "model_rows": worlds * len(actions), "full_rollouts": worlds * len(actions),
            "mc_points_means": point_scores.mean(axis=0).tolist(),
            "mc_points_top1": int(np.argmax(point_scores.mean(axis=0))),
            "mc_levels_top1": int(np.argmax(r.mean(axis=0))),
            "wall_seconds": time.perf_counter() - wall,
            "cpu_seconds": time.process_time() - cpu}


def main(argv=None):
    """Reopen retained throw-probe roots; preserve each completed diagnostic."""
    import argparse
    import hashlib
    import json
    from pathlib import Path
    from ..ai.cwv_policy import shared_evaluator
    from ..engine.combos import decompose
    from ..luna.game import _round_from_snapshot
    from .search_screen import _publish, bind_output_config, execution_source_identity
    from .cwv_shortlist_screen import screen_output_lock

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--states', type=Path, required=True,
                        help='retained throw-probe JSON with results[].snapshot')
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--worlds', type=int, default=64)
    parser.add_argument('--subset-worlds', type=int, default=16)
    parser.add_argument('--repeats', type=int, default=256)
    parser.add_argument('--seed', type=int, required=True)
    args = parser.parse_args(argv)
    if not 1 <= args.subset_worlds <= args.worlds or args.worlds < 2 or args.repeats < 1:
        parser.error('require 2 <= worlds, 1 <= subset <= worlds, positive repeats')
    raw = args.states.read_bytes()
    rows = json.loads(raw)['results']
    if not rows:
        parser.error('no saved roots')
    evaluator = shared_evaluator(str(args.checkpoint), threads=1, max_batch=128,
                                 encoding='mlp-static')
    recipe = {'schema': 'cwv-residual-reference-v1',
              'input_sha256': hashlib.sha256(raw).hexdigest(),
              'checkpoint_sha256': evaluator.checkpoint_sha256,
              'worlds': args.worlds, 'subset_worlds': args.subset_worlds,
              'repeats': args.repeats, 'seed': args.seed,
              'units': 'acting-team-signed-level', 'states': len(rows)}
    recipe['source_sha256'] = execution_source_identity(Path(__file__).resolve().parents[1])
    with screen_output_lock(args.out):
        bind_output_config(args.out, recipe)
        for index, row in enumerate(rows):
            path = args.out / f'state-{index:04d}.json'
            if path.exists():
                retained = json.loads(path.read_bytes())
                if retained.get('recipe') != recipe or retained.get('state_index') != index:
                    raise ValueError('retained diagnostic state identity mismatch')
                print(f'{index + 1}/{len(rows)} retained', flush=True)
                continue
            rnd = _round_from_snapshot(row['snapshot'])
            # Frozen saved actions, plus public direct components. No model
            # score from this population chooses or truncates the ballot.
            actions = [row['incumbent'], row['submitted']]
            if not rnd.trick.plays:
                actions += [c.cards for c in decompose(row['submitted'], rnd.ordering).components]
            actions = [list(a) for a in dict.fromkeys(tuple(sorted(a)) for a in actions)]
            matrix = collect_reference(rnd, row['seat'], actions, evaluator,
                                       worlds=args.worlds, seed=args.seed + index)
            result = compare_estimators(matrix['model'], matrix['rollout'],
                                        subset_worlds=args.subset_worlds,
                                        repeats=args.repeats, seed=args.seed + 1000000 + index)
            _publish(path, {'state_index': index, 'recipe': recipe,
                            'reference': matrix, 'comparison': result})
            print(f'{index + 1}/{len(rows)} complete: {result["estimates"]}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

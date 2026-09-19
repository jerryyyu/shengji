"""Read-only paired world-count ablation for sealed policy_world_duel runs.

Only W may change. Both policy-only arms must face the SAME fixed MC control;
policy-world is not eligible because its world count changes with the arm.
Prints candidate-minus-baseline paired-deal bootstrap, never pools two CIs.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import numpy as np


def _read(directory):
    directory = Path(directory)
    recipe = json.loads((directory / 'recipe.json').read_text())
    summary = json.loads((directory / 'summary.json').read_text())
    required = ('schema', 'seed0', 'deals', 'checkpoint_sha256', 'worlds', 'cap',
                'control', 'control_effective', 'policy', 'decision_timeout_seconds',
                'source_git_sha', 'harness_sha256', 'policy_module_sha256', 'runtime')
    if any(k not in recipe for k in required):
        raise ValueError('incomplete recipe')
    if recipe['schema'] != 'policy-world-duel-v1':
        raise ValueError('unknown recipe schema')
    n, seed0 = recipe['deals'], recipe['seed0']
    if type(n) is not int or not 2 <= n <= 4000 or type(seed0) is not int:
        raise ValueError('require 2..4000 paired deals with integer seed0')
    if summary.get('errors') != [] or summary.get('aggregation_error'):
        raise ValueError('unsealed or refused result')
    if summary.get('complete') != n or summary.get('expected') != n:
        raise ValueError('incomplete summary')
    rows = [json.loads(line) for line in (directory / 'pairs.jsonl').read_text().splitlines()]
    by_seed = {}
    for row in rows:
        seed = row.get('seed')
        if type(seed) is not int or seed in by_seed:
            raise ValueError('invalid or duplicate seed')
        if row.get('error') or row.get('timeout'):
            raise ValueError('refused pair')
        mirrors = np.asarray(row.get('mirrors', []), dtype=float)
        utility = float(row['utility'])
        if (mirrors.shape != (2,) or not np.isfinite(mirrors).all()
                or not np.isfinite(utility) or utility != float(mirrors.mean())):
            raise ValueError('invalid mirror utility')
        by_seed[seed] = utility
    expected = list(range(seed0, seed0 + n))
    if set(by_seed) != set(expected):
        raise ValueError('missing or unexpected seeds')
    values = np.array([by_seed[s] for s in expected])
    if not np.isclose(values.mean(), summary.get('mean_utility', np.nan), rtol=0, atol=1e-12):
        raise ValueError('summary differs from pairs')
    return recipe, values


def compare(baseline, candidate):
    a, av = _read(baseline)
    b, bv = _read(candidate)
    def fixed(recipe):
        r = copy.deepcopy(recipe)
        if r['control'] not in ('mc-smart4', 'mc-lcb') or r['policy'].get('mode') != 'policy':
            raise ValueError('requires policy-only arms against fixed MC control')
        if r['policy'].get('worlds') != r['worlds']:
            raise ValueError('inconsistent world count')
        if type(r['worlds']) is not int or not 1 <= r['worlds'] <= 128:
            raise ValueError('invalid world count')
        # Paths may differ while the checkpoint content hash remains identical.
        r.pop('checkpoint', None)
        r.pop('worlds')
        r['policy'].pop('worlds')
        return r
    if fixed(a) != fixed(b):
        raise ValueError('recipes differ beyond world count or checkpoint path')
    if a['worlds'] == b['worlds']:
        raise ValueError('world counts must differ')
    delta = bv - av
    rng = np.random.default_rng(20260919)
    boot = np.concatenate([
        delta[rng.integers(0, len(delta), (min(256, 10000 - i), len(delta)))].mean(axis=1)
        for i in range(0, 10000, 256)])
    return {'estimand': 'candidate-minus-baseline signed levels, matched deal means',
            'deals': len(delta), 'seed0': a['seed0'],
            'baseline_worlds': a['worlds'], 'candidate_worlds': b['worlds'],
            'baseline_mean': float(av.mean()), 'candidate_mean': float(bv.mean()),
            'paired_delta': float(delta.mean()),
            'ci95': np.quantile(boot, [.025, .975]).tolist(),
            'bootstrap_replicates': 10000, 'bootstrap_seed': 20260919,
            'interpretation': 'exploratory comparison; no multiple-testing correction'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--candidate', required=True)
    args = parser.parse_args()
    print(json.dumps(compare(args.baseline, args.candidate), indent=2))

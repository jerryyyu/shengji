"""Paired statistics for a predeclared depth screen, not a launch/recipe verifier.

Callers must validate frozen recipes and seed reservations before consumption.
No partial-family strength inference or qualification-seed reuse is permitted.
"""
import json
from pathlib import Path

import numpy as np


ARMS = ('CURRENT_TRICK', 'EXTRA_TRICK_HEURISTIC', 'EXTRA_TRICK_POLICY')
QUALIFICATION_SEEDS = range(626700000, 626700012)
MODES = ('policy-value', 'policy-heuristic-lookahead', 'policy-lookahead')
WORK_KEYS = ('decisions', 'sample_attempts', 'worlds', 'capped_decisions',
             'value_evaluations', 'value_batches', 'continuation_plies',
             'continuation_worlds', 'continuation_sample_attempts',
             'continuation_capped_decisions', 'unique_worlds', 'duplicate_worlds',
             'fallback_decisions', 'budget_fallbacks', 'error_fallbacks')


def _costs(rows):
    """Reconstruct costs from pair records, including work on failed pairs."""
    result = {}
    for role in ('policy', 'control'):
        sides = [row['sides'][role] for row in rows]
        counts = {}
        for key in WORK_KEYS:
            values = [side[key] for side in sides]
            if any(type(v) is not int or v < 0 for v in values):
                raise ValueError(f'invalid {role} counter {key}')
            counts[key] = sum(values)
        times = np.asarray([t for side in sides for t in side['seconds']], dtype=float)
        if (times.ndim != 1 or not np.isfinite(times).all() or (times < 0).any()
                or len(times) != counts['decisions']):
            raise ValueError(f'invalid {role} decision times')
        counts['timing'] = {
            'mean_seconds': float(times.mean()) if len(times) else None,
            'p95_seconds': float(np.quantile(times, .95)) if len(times) else None,
            'max_seconds': float(times.max()) if len(times) else None,
            'total_seconds': float(times.sum()),
        }
        result[role] = counts
    rss = [row['max_rss_kib'] for row in rows]
    if any(type(v) is not int or v < 0 for v in rss):
        raise ValueError('invalid per-process RSS')
    result.update(max_process_rss_kib=max(rss, default=0),
                  failed_pairs=sum(bool(row.get('error')) for row in rows),
                  timed_out_pairs=sum(bool(row.get('timeout')) for row in rows))
    return result


def readout(directory, frozen_recipes, *, replicates=10000, bootstrap_seed=20260922):
    """Read a saved three-arm screen against caller-supplied REVIEWED recipes.

    Never derive expected recipes from the observed run. Equality covers the
    entire recipe, including source, model, control, engine and budget fields.
    The caller owns freeze provenance/seed reservation; this function neither
    reserves seeds nor authorizes a run. It writes no artifacts.
    """
    if set(frozen_recipes) != set(ARMS):
        raise ValueError('three frozen recipes required')
    first = frozen_recipes[ARMS[0]]
    seed0, count = first['seed0'], first['deals']
    if type(seed0) is not int or type(count) is not int or count < 1:
        raise ValueError('invalid frozen seed population')
    seeds = list(range(seed0, seed0 + count))
    if set(seeds).intersection(QUALIFICATION_SEEDS):
        raise ValueError('qualification seeds cannot enter strength readout')
    for arm, mode in zip(ARMS, MODES):
        recipe = frozen_recipes[arm]
        if (recipe['seed0'] != seed0 or recipe['deals'] != count
                or recipe['control'] != 'production-pv-r29'
                or recipe['worlds'] != 64 or recipe['policy']['candidates'] != 8
                or recipe['policy']['mode'] != mode
                or recipe['control_effective'] != first['control_effective']):
            raise ValueError(f'{arm}: inconsistent frozen depth family')
    data, costs, issues = {}, {}, {}
    for arm in ARMS:
        path = Path(directory) / arm
        try:
            actual = json.loads((path / 'recipe.json').read_text())
            if actual != frozen_recipes[arm]:
                raise ValueError('frozen recipe drift')
            data[arm] = [json.loads(line) for line in
                         (path / 'pairs.jsonl').read_text().splitlines() if line.strip()]
            costs[arm] = _costs(data[arm])
            summary = json.loads((path / 'summary.json').read_text())
            wall = float(summary['wall_seconds'])
            if not np.isfinite(wall) or wall < 0:
                raise ValueError('invalid wall time')
            costs[arm]['wall_seconds'] = wall
            if (summary.get('errors') != [] or summary.get('aggregation_error')
                    or summary.get('expected') != count or summary.get('complete') != count):
                raise ValueError('unsealed or failed arm summary')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            issues[arm] = str(exc)
    if issues:
        return {'status': 'incomplete_or_unclean', 'family_complete': False,
                'expected_pairs': count, 'issues': issues, 'costs': costs}
    result = compare_records(data, seeds, replicates=replicates, bootstrap_seed=bootstrap_seed)
    result['costs'] = costs
    result['recipe_check'] = 'exact equality against caller-supplied frozen recipes'
    return result


def compare_records(arms, expected_seeds, *, replicates=10000, bootstrap_seed=20260922):
    """Jointly resample mirrored deal means, retaining cross-arm covariance.

    Missing/failed records return diagnostics without estimates. Bad declarations
    raise instead. Source/recipe validation and operational cost reporting belong
    to the consuming screen reader, not this statistics function.
    """
    seeds = list(expected_seeds)
    if (not seeds or len(set(seeds)) != len(seeds)
            or any(type(s) is not int for s in seeds)
            or set(seeds).intersection(QUALIFICATION_SEEDS)):
        raise ValueError('expected seeds must be unique, nonempty, fresh integers')
    if set(arms) != set(ARMS):
        raise ValueError('all three declared arms are required')
    if type(replicates) is not int or replicates < 2:
        raise ValueError('at least two bootstrap replicates required')
    issues, columns = {}, []
    for name in ARMS:
        by_seed, problems = {}, []
        for row in arms[name]:
            seed = row.get('seed')
            if type(seed) is not int:
                problems.append('invalid seed')
                continue
            if seed in by_seed:
                problems.append(f'duplicate seed {seed}')
            by_seed[seed] = row
            if row.get('error') or row.get('timeout'):
                problems.append(f'failed seed {seed}')
            try:
                mirrors = np.asarray(row['mirrors'], dtype=float)
                utility = float(row['utility'])
                if (mirrors.shape != (2,) or not np.isfinite(mirrors).all()
                        or not np.isfinite(utility)
                        or not np.isclose(utility, mirrors.mean(), rtol=0, atol=1e-12)):
                    raise ValueError('mirror mismatch')
            except (KeyError, TypeError, ValueError):
                problems.append(f'invalid mirror mean {seed}')
            # Missing telemetry cannot certify a clean production control.
            control = row.get('sides', {}).get('control', {})
            if any(control.get(key) != 0 for key in
                   ('fallback_decisions', 'budget_fallbacks', 'error_fallbacks')):
                problems.append(f'unclean or missing control telemetry {seed}')
        missing, extra = set(seeds) - set(by_seed), set(by_seed) - set(seeds)
        if missing:
            problems.append(f'missing seeds {sorted(missing)}')
        if extra:
            problems.append(f'unexpected seeds {sorted(extra)}')
        if problems:
            issues[name] = problems
        else:
            columns.append([float(by_seed[s]['utility']) for s in seeds])
    if issues:
        return {'status': 'incomplete_or_unclean', 'family_complete': False,
                'expected_pairs': len(seeds), 'issues': issues}
    matrix = np.asarray(columns).T
    rng = np.random.default_rng(bootstrap_seed)
    boots = np.concatenate([
        matrix[rng.integers(0, len(seeds), (min(128, replicates-i), len(seeds)))].mean(axis=1)
        for i in range(0, replicates, 128)])

    def estimate(values, samples, confidence):
        tail = (1 - confidence) / 2
        return {'mean': float(values.mean()),
                'interval': np.quantile(samples, [tail, 1-tail]).tolist(),
                'confidence': confidence}

    return {
        'status': 'complete', 'family_complete': True, 'pairs': len(seeds),
        'family_size': 2,
        'primaries_vs_production': {
            ARMS[i]: estimate(matrix[:, i], boots[:, i], .975) for i in (1, 2)},
        'current_trick_diagnostic': estimate(matrix[:, 0], boots[:, 0], .95),
        'exploratory_component_contrasts': {
            f'{ARMS[i]}_minus_{ARMS[j]}':
                estimate(matrix[:, i]-matrix[:, j], boots[:, i]-boots[:, j], .95)
            for i, j in ((1, 0), (2, 0), (2, 1))},
        'bootstrap_seed': bootstrap_seed, 'bootstrap_replicates': replicates,
        'interpretation': 'Two depth-versus-production primaries, Bonferroni 97.5%. '
            'Component contrasts are matched common-opponent differences, not direct duels. '
            'Whole mirrored deals resampled jointly; null is not equivalence. '
            'Card-play scope, unequal budgets; no deployment approval.',
    }

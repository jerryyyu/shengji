"""Paired statistics for a predeclared depth screen, not a launch/recipe verifier.

Callers must validate frozen recipes and seed reservations before consumption.
No partial-family strength inference or qualification-seed reuse is permitted.
"""
import numpy as np


ARMS = ('CURRENT_TRICK', 'EXTRA_TRICK_HEURISTIC', 'EXTRA_TRICK_POLICY')
QUALIFICATION_SEEDS = range(626700000, 626700012)


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

"""Frozen W/K screen: joint deal bootstrap, no partial or qualification results."""
import argparse
import copy
import json

import numpy as np

from . import policy_strength_compare as base
from .policy_world_compare import _read

SEED0 = 625500000
ARMS = (('W4_K8', 4, 8), ('W16_K8', 16, 8), ('W4_K16', 4, 16))


def fixed(recipe, worlds, candidates):
    expected = base.policy_recipe('policy-value')
    expected.update(worlds=worlds, candidates=candidates)
    if (recipe.get('seed0') != SEED0 or recipe.get('worlds') != worlds
            or recipe.get('policy') != expected):
        raise ValueError('not the frozen W/K screen recipe')
    # Validate all shared identities through the existing strict screen guard.
    # Only the three explicitly checked experimental fields are normalized.
    normalized = copy.deepcopy(recipe)
    normalized.update(seed0=base.SEED0, worlds=4,
                      policy=base.policy_recipe('policy-value'))
    return base._fixed(normalized, 'policy-value')


def compare_wk(paths):
    if len(paths) != 3:
        raise ValueError('exactly three ordered arms required')
    runs = [_read(path) for path in paths]
    recipes = [fixed(recipe, worlds, candidates)
               for (recipe, _), (_, worlds, candidates) in zip(runs, ARMS)]
    if recipes[1:] != [recipes[0], recipes[0]]:
        raise ValueError('non-experimental recipe drift across arms')
    values = np.column_stack([v for _, v in runs])
    rng = np.random.default_rng(base.BOOTSTRAP_SEED)
    boot = np.concatenate([
        values[rng.integers(0, base.DEALS,
               (min(128, base.REPLICATES-i), base.DEALS))].mean(axis=1)
        for i in range(0, base.REPLICATES, 128)])

    def result(observed, samples, family_size):
        interval = np.quantile(samples, [.05/(2*family_size),
                                         1-.05/(2*family_size)]).tolist()
        return dict(mean=float(observed.mean()),
                    ci95=np.quantile(samples, [.025, .975]).tolist(),
                    ci_familywise95_bonferroni=interval,
                    family_size=family_size,
                    positive_after_adjustment=interval[0] > 0)

    return dict(seed0=SEED0, deals=base.DEALS,
        source_git_sha=base.SOURCE, checkpoint_sha256=base.CHECKPOINT,
        bootstrap_seed=base.BOOTSTRAP_SEED, bootstrap_replicates=base.REPLICATES,
        estimand='signed levels against common MC-LCB, mirrored deal means',
        scope='card play; shared heuristic declare/bury; not production approval',
        primary={name: result(values[:, i], boot[:, i], 3)
                 for i, (name, _, _) in enumerate(ARMS)},
        components={ARMS[i][0]+' minus W4_K8':
                    result(values[:, i]-values[:, 0], boot[:, i]-boot[:, 0], 2)
                    for i in (1, 2)},
        interpretation='Approximate percentile-bootstrap intervals; separate '
            'three-primary and two-component families. Components compare '
            'performance against a common opponent, not direct head-to-head. '
            'Qualification excluded; no optional extension.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs=3, help='W4_K8 W16_K8 W4_K16 directories')
    print(json.dumps(compare_wk(parser.parse_args().paths), indent=2))

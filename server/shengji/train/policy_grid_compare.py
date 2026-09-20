"""Frozen paired JS-M1/JS-G1 comparison; qualification and partial runs refused."""
import argparse
import copy
import json

import numpy as np

from . import policy_strength_compare as base
from .policy_world_compare import _read

SEED0 = 625600000
ARMS = (
    ('JS_M1_W4_K8', 'a5248cc5ae97e69687910e892b1905613a1735cb47cbdc5e73a76e41d61e3f38'),
    ('JS_G1_W4_K8', '9ee9fedb38950aa3630cf246d3eca0608f4dce516650182522ce69e7a0960cf0'),
)


def fixed(recipe, checksum):
    if recipe.get('seed0') != SEED0 or recipe.get('checkpoint_sha256') != checksum:
        raise ValueError('not the frozen joint-grid model/seed identity')
    normalized = copy.deepcopy(recipe)
    # Only these two intentionally varied identities may differ from the
    # already-qualified strength harness; all remaining guards still apply.
    normalized.update(seed0=base.SEED0, checkpoint_sha256=base.CHECKPOINT)
    return base._fixed(normalized, 'policy-value')


def compare_grid(paths):
    if len(paths) != 2:
        raise ValueError('exactly two ordered arms required: M1 then G1')
    runs = [_read(path) for path in paths]
    recipes = [fixed(recipe, checksum) for (recipe, _), (_, checksum) in zip(runs, ARMS)]
    if recipes[0] != recipes[1]:
        raise ValueError('non-model recipe drift across arms')
    values = np.column_stack([value for _, value in runs])
    rng = np.random.default_rng(base.BOOTSTRAP_SEED)
    bootstrap = np.concatenate([
        values[rng.integers(0, base.DEALS,
               (min(128, base.REPLICATES-i), base.DEALS))].mean(axis=1)
        for i in range(0, base.REPLICATES, 128)])

    def result(observed, samples, family):
        interval = np.quantile(samples, [.05/(2*family), 1-.05/(2*family)]).tolist()
        return dict(mean=float(observed.mean()),
                    ci95=np.quantile(samples, [.025, .975]).tolist(),
                    family_size=family, ci_familywise95_bonferroni=interval,
                    positive_after_adjustment=interval[0] > 0)

    return dict(seed0=SEED0, deals=base.DEALS, source_git_sha=base.SOURCE,
        checkpoints=dict(ARMS), bootstrap_seed=base.BOOTSTRAP_SEED,
        bootstrap_replicates=base.REPLICATES,
        primary={name: result(values[:, i], bootstrap[:, i], 2)
                 for i, (name, _) in enumerate(ARMS)},
        matched_grid_minus_mlp=result(values[:, 1]-values[:, 0],
                                      bootstrap[:, 1]-bootstrap[:, 0], 1),
        estimand='signed levels against common MC-LCB; mirrored deal means',
        interpretation='Two primary comparisons at97.5% each; predeclared paired '
            'architecture contrast at95%. Approximate percentile-bootstrap intervals. '
            'Not direct G1-vs-M1 games, equivalence, or production approval. '
            'Qualification excluded; no optional extension.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs=2, help='JS_M1_W4_K8 JS_G1_W4_K8 directories')
    print(json.dumps(compare_grid(parser.parse_args().paths), indent=2))

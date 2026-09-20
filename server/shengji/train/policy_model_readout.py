"""Frozen W16 soft/M1/G1 model-package readout, jointly resampling mirrored deals."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from .policy_world_compare import _read

ARMS = ('SOFT_W16_K8', 'JS_M1_W16_K8', 'JS_G1_W16_K8')
REFERENCE_HASHES = (
    '1c4a9848bc47ef04459506b916c945f7ec7bb1f0d06e08cdc06a597e7b90850e',
    '6b7bf152926993578e69da8a8314d56a36a09bf6528f5dd5c0ba07e21d8be8ff',
    '1631d05bafb69d54f5712e7020c3835ee6732e945db3a2ec890e21c6c9f9d355')
SEED0 = 626100000
DEALS = 800


def compare(root, qualification_root):
    values = []
    for arm, digest in zip(ARMS, REFERENCE_HASHES):
        raw = (Path(qualification_root) / arm / 'recipe.json').read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('qualification recipe identity mismatch')
        expected = json.loads(raw)
        expected.update(seed0=SEED0, deals=DEALS)
        recipe, utility = _read(Path(root) / arm)
        def normalized(r):
            r = copy.deepcopy(r)
            r.pop('checkpoint', None)  # Exact content identity remains checked.
            return r
        if normalized(recipe) != normalized(expected):
            raise ValueError('frozen model-comparison recipe drift')
        values.append(utility)
    values = np.column_stack(values)
    rng = np.random.default_rng(20260920)
    boot = np.concatenate([values[rng.integers(0, DEALS,
        (min(128, 10000-i), DEALS))].mean(axis=1) for i in range(0, 10000, 128)])
    def result(v, b, family):
        interval = np.quantile(b, [.05/(2*family), 1-.05/(2*family)]).tolist()
        return dict(mean=float(v.mean()), ci95=np.quantile(b, [.025, .975]).tolist(),
            family_size=family, ci_familywise95_bonferroni=interval,
            positive_after_adjustment=interval[0] > 0)
    return dict(seed0=SEED0, deals=DEALS, bootstrap_seed=20260920,
        bootstrap_replicates=10000, qualification_recipe_hashes=list(REFERENCE_HASHES),
        primary={arm: result(values[:, i], boot[:, i], 3) for i, arm in enumerate(ARMS)},
        components={ARMS[i]+' minus JS_M1_W16_K8': result(values[:, i]-values[:, 1],
            boot[:, i]-boot[:, 1], 2) for i in (0, 2)},
        interpretation='Three arm-vs-MC primaries98.333333% each. Model packages, not isolated '
            'training objectives; two model contrasts97.5% each. Mirrored-deal percentile bootstrap. '
            'Common opponent, not direct candidate duels. Qualification excluded; no optional '
            'extension. Null is not equivalence. No deployment approval.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root')
    parser.add_argument('--qualification-root', required=True)
    args = parser.parse_args()
    print(json.dumps(compare(args.root, args.qualification_root), indent=2))

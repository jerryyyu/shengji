"""Frozen production comparison; qualification and incomplete screens refused."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from .policy_world_compare import _read

REFERENCE_SHA256 = '0ecec6b862291f893a1e2c2d98d1df017d2af23fc57a643b9dbc03f98533ba86'
SEED0 = 625800000
DEALS = 800


def readout(directory, qualification_recipe):
    # Exact sealed qualification receipt pins the entire effective control,
    # environment, module digests and both models, not just friendly names.
    raw = Path(qualification_recipe).read_bytes()
    if hashlib.sha256(raw).hexdigest() != REFERENCE_SHA256:
        raise ValueError('qualification recipe identity mismatch')
    expected = json.loads(raw)
    expected.update(seed0=SEED0, deals=DEALS)
    recipe, values = _read(directory)
    def normalized(r):
        r = copy.deepcopy(r)
        r.pop('checkpoint', None)  # Content hashes remain pinned.
        r['control_effective'].pop('checkpoint', None)
        return r
    if normalized(recipe) != normalized(expected):
        raise ValueError('frozen production screen recipe drift')
    rng = np.random.default_rng(20260920)
    boot = np.concatenate([values[rng.integers(0, DEALS,
        (min(128, 10000-i), DEALS))].mean(axis=1) for i in range(0, 10000, 128)])
    interval = np.quantile(boot, [.025, .975]).tolist()
    return dict(deals=DEALS, seed0=SEED0, mean=float(values.mean()), ci95=interval,
        bootstrap_seed=20260920, bootstrap_replicates=10000,
        positive=interval[0] > 0, qualification_recipe_sha256=REFERENCE_SHA256,
        estimand='soft W16/K8 minus production-play; signed levels, mirrored deal means',
        interpretation='Single primary approximate percentile-bootstrap interval. '
            'Qualification excluded. No optional extension. Null is not equivalence. '
            'Card play only, not full Fly package or deployment approval.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    parser.add_argument('--qualification-recipe', required=True)
    args = parser.parse_args()
    print(json.dumps(readout(args.directory, args.qualification_recipe), indent=2))

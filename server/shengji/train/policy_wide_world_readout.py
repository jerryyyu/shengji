"""Complete W64/128/256 strength ladder; qualification rows never enter inference.

Two predeclared primary contrasts against W64, not three independent arm wins.
Recipes inherit the measured qualification exactly except fresh deals and paths.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from .policy_joint_production_readout import normalized
from .policy_world_compare import _read

QUALIFICATION_HASHES = {
    'SOFT_W64_K8': '5a22353b377d90d4f4facdc16edce94e916dc12fc6b75c4d7838fdc24c8ecb77',
    'SOFT_W128_K8': '55f72ed1938bacb0278a649b926db09c0fc21f15d172c1862c4116dfed0cf114',
    'SOFT_W256_K8': '1bf91e10d16fecbd8c9b895d327e72ea6b939b431aace0306c79cd607c9308b4',
}
DEALS, SEED0 = 800, 626600000
BOOTSTRAP_SEED, REPLICATES = 20260921, 10000


def validate_qualification(directory):
    """Require all measured arms to be sealed; no promotion of partial runs."""
    for name, digest in QUALIFICATION_HASHES.items():
        arm = Path(directory) / name
        if hashlib.sha256((arm / 'recipe.json').read_bytes()).hexdigest() != digest:
            raise ValueError(f'{name}: qualification recipe identity mismatch')
        _read(arm)  # complete seed coverage, finite mirror means, no errors/timeouts


def readout(directory, qualification):
    validate_qualification(qualification)
    values = []
    for name, digest in QUALIFICATION_HASHES.items():
        raw = (Path(qualification) / name / 'recipe.json').read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError(f'{name}: qualification recipe identity mismatch')
        expected = json.loads(raw)
        expected.update(seed0=SEED0, deals=DEALS)
        recipe, data = _read(Path(directory) / name)
        if normalized(recipe) != normalized(expected):
            raise ValueError(f'{name}: frozen wide-world recipe drift')
        values.append(data)
    matrix = np.stack(values, axis=1)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    boots = np.concatenate([
        matrix[rng.integers(0, DEALS, (min(128, REPLICATES-i), DEALS))].mean(axis=1)
        for i in range(0, REPLICATES, 128)])
    names = list(QUALIFICATION_HASHES)
    primaries = {}
    for i in (1, 2):
        interval = np.quantile(boots[:, i] - boots[:, 0], [.0125, .9875]).tolist()
        primaries[f'{names[i]}_minus_{names[0]}'] = {
            'mean': float((matrix[:, i] - matrix[:, 0]).mean()),
            'ci97_5': interval, 'positive': interval[0] > 0}
    return {
        'deals': DEALS, 'seed0': SEED0, 'family_size': 2, 'family_complete': True,
        'primaries': primaries,
        'exploratory_vs_shortlist': {
            name: {'mean': float(matrix[:, i].mean()),
                   'ci95': np.quantile(boots[:, i], [.025, .975]).tolist()}
            for i, name in enumerate(names)},
        'exploratory_w256_minus_w128': {
            'mean': float((matrix[:, 2]-matrix[:, 1]).mean()),
            'ci95': np.quantile(boots[:, 2]-boots[:, 1], [.025, .975]).tolist()},
        'bootstrap_seed': BOOTSTRAP_SEED, 'bootstrap_replicates': REPLICATES,
        'qualification_recipe_sha256': dict(QUALIFICATION_HASHES),
        'interpretation': 'Two primary matched common-opponent contrasts, '
            'W128-W64 and W256-W64, Bonferroni97.5%; not direct head-to-head games. '
            'Other intervals are exploratory95%. Whole mirrored deals jointly resampled. '
            'Qualification excluded; no optional extension; null is not equivalence. '
            'Operational costs separate; not serving-package or deployment approval.',
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    parser.add_argument('--qualification', required=True)
    args = parser.parse_args()
    print(json.dumps(readout(args.directory, args.qualification), indent=2))

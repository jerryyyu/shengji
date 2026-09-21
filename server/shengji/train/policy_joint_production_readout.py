"""Frozen joint-model W64/K8 comparisons against production card play."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from .policy_world_compare import _read

QUALIFICATION_HASHES = {
    'JS_M1_W64_K8': '1cc1bac4671cefedcec432658cacb4e97768448eaa814f0792762fcdeb203152',
    'JS_G1_W64_K8': 'a93bf124b4bafc08b68b13f178bb1ebb7d8f1d160fb46eb19f2da0b8e67065e0',
}
DEALS, SEED0 = 800, 625800000
BOOTSTRAP_SEED, REPLICATES = 20260921, 10000


def normalized(recipe):
    recipe = copy.deepcopy(recipe)
    recipe.pop('checkpoint', None)
    recipe['control_effective'].pop('checkpoint', None)
    return recipe


def readout(directory, qualification):
    values = []
    for name, digest in QUALIFICATION_HASHES.items():
        raw = (Path(qualification) / name / 'recipe.json').read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('qualification recipe identity mismatch')
        expected = json.loads(raw)
        expected.update(seed0=SEED0, deals=DEALS)
        recipe, data = _read(Path(directory) / name)
        if normalized(recipe) != normalized(expected):
            raise ValueError('frozen joint production recipe drift')
        values.append(data)
    matrix = np.stack(values, axis=1)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    boots = np.concatenate([
        matrix[rng.integers(0, DEALS, (min(128, REPLICATES-i), DEALS))].mean(axis=1)
        for i in range(0, REPLICATES, 128)])
    primaries = {}
    for i, name in enumerate(QUALIFICATION_HASHES):
        interval = np.quantile(boots[:, i], [.0125, .9875]).tolist()
        primaries[name] = dict(mean=float(matrix[:, i].mean()), ci97_5=interval,
                              positive=interval[0] > 0)
    return dict(deals=DEALS, seed0=SEED0, primaries=primaries,
        exploratory_g1_minus_m1=dict(mean=float((matrix[:, 1]-matrix[:, 0]).mean()),
            ci95=np.quantile(boots[:, 1]-boots[:, 0], [.025, .975]).tolist()),
        bootstrap_seed=BOOTSTRAP_SEED, bootstrap_replicates=REPLICATES,
        qualification_recipe_sha256=dict(QUALIFICATION_HASHES),
        interpretation='Two primaries versus pinned production card play, Bonferroni97.5%. '
            'Exploratory model contrast is matched common-opponent, not a direct duel. '
            'Qualification excluded; no optional extension. Null is not equivalence. '
            'Not full Fly package or deployment approval. Report operational summaries separately.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    parser.add_argument('--qualification', required=True)
    args = parser.parse_args()
    print(json.dumps(readout(args.directory, args.qualification), indent=2))

"""Held complete four-model production comparison; never analyze a subset.

GEN4/GEN3 qualification identities must be frozen in a reviewed release after
qualification. No CLI override, inferred digest, or partial-family fallback.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from .policy_joint_production_readout import DEALS, SEED0, normalized
from .policy_world_compare import _read


QUALIFICATION_HASHES = {
    'JS_M1_W64_K8': '1cc1bac4671cefedcec432658cacb4e97768448eaa814f0792762fcdeb203152',
    'JS_G1_W64_K8': 'a93bf124b4bafc08b68b13f178bb1ebb7d8f1d160fb46eb19f2da0b8e67065e0',
    'GEN4_W64_K8': None,
    'GEN3_W64_K8': None,
}
BOOTSTRAP_SEED, REPLICATES = 20260921, 10000


def readout(directory, joint_qualification, gen4_qualification, gen3_qualification):
    if any(digest is None for digest in QUALIFICATION_HASHES.values()):
        raise ValueError('readout held: gen4/gen3 qualification identities not frozen')
    roots = [joint_qualification, joint_qualification,
             gen4_qualification, gen3_qualification]
    names = list(QUALIFICATION_HASHES)
    values = []
    for (name, digest), root in zip(QUALIFICATION_HASHES.items(), roots, strict=True):
        raw = (Path(root) / name / 'recipe.json').read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError(f'{name}: qualification recipe identity mismatch')
        expected = json.loads(raw)
        expected.update(seed0=SEED0, deals=DEALS)
        recipe, data = _read(Path(directory) / name)
        if normalized(recipe) != normalized(expected):
            raise ValueError(f'{name}: frozen full-screen recipe drift')
        values.append(data)
    matrix = np.stack(values, axis=1)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    boots = np.concatenate([
        matrix[rng.integers(0, DEALS, (min(128, REPLICATES-i), DEALS))].mean(axis=1)
        for i in range(0, REPLICATES, 128)])
    primaries = {}
    for i, name in enumerate(names):
        interval = np.quantile(boots[:, i], [.00625, .99375]).tolist()
        primaries[name] = {'mean': float(matrix[:, i].mean()),
                           'ci98_75': interval, 'positive': interval[0] > 0}
    contrasts = {}
    for i, name in enumerate(names):
        for j in range(i):
            contrasts[f'{name}_minus_{names[j]}'] = {
                'mean': float((matrix[:, i] - matrix[:, j]).mean()),
                'ci95': np.quantile(boots[:, i] - boots[:, j], [.025, .975]).tolist(),
            }
    return {
        'deals': DEALS, 'seed0': SEED0, 'family_size': 4, 'family_complete': True,
        'primaries': primaries, 'exploratory_model_contrasts': contrasts,
        'bootstrap_seed': BOOTSTRAP_SEED, 'bootstrap_replicates': REPLICATES,
        'qualification_recipe_sha256': dict(QUALIFICATION_HASHES),
        'interpretation': 'Four primaries versus pinned production card play, '
            'Bonferroni98.75%. Exploratory model contrasts use jointly resampled '
            'matched deals against a common opponent, not direct duels; their '
            '95% intervals are unadjusted and not model-selection confirmation. '
            'Qualification excluded; no optional extension; null is not equivalence. '
            'Not full Fly package or deployment approval. Operational costs separate.',
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    parser.add_argument('--joint-qualification', required=True)
    parser.add_argument('--gen4-qualification', required=True)
    parser.add_argument('--gen3-qualification', required=True)
    args = parser.parse_args()
    print(json.dumps(readout(args.directory, args.joint_qualification,
                            args.gen4_qualification, args.gen3_qualification), indent=2))

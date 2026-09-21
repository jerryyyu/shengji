"""M1/G1 subset of the preregistered FOUR-model production comparison family.

Keep the original two-model reader unchanged. Gen4/gen3 are not validated by
this reader: their complete recipes must be frozen after qualification. An
M1/G1 result here is not a complete family report or a model-selection verdict.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from . import policy_joint_production_readout as joint
from .policy_world_compare import _read

FAMILY_SIZE = 4
PENDING_MODELS = ('GEN4_W64_K8', 'GEN3_W64_K8')


def readout(directory, qualification):
    values = []
    for name, digest in joint.QUALIFICATION_HASHES.items():
        raw = (Path(qualification) / name / 'recipe.json').read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('qualification recipe identity mismatch')
        expected = json.loads(raw)
        expected.update(seed0=joint.SEED0, deals=joint.DEALS)
        recipe, data = _read(Path(directory) / name)
        if joint.normalized(recipe) != joint.normalized(expected):
            raise ValueError('frozen joint production recipe drift')
        values.append(data)
    matrix = np.stack(values, axis=1)
    rng = np.random.default_rng(joint.BOOTSTRAP_SEED)
    boots = np.concatenate([
        matrix[rng.integers(0, joint.DEALS,
                           (min(128, joint.REPLICATES-i), joint.DEALS))].mean(axis=1)
        for i in range(0, joint.REPLICATES, 128)])
    tail = .05 / FAMILY_SIZE / 2
    primaries = {}
    for i, name in enumerate(joint.QUALIFICATION_HASHES):
        interval = np.quantile(boots[:, i], [tail, 1-tail]).tolist()
        primaries[name] = dict(mean=float(matrix[:, i].mean()), ci98_75=interval,
                              positive=interval[0] > 0)
    return dict(deals=joint.DEALS, seed0=joint.SEED0, primaries=primaries,
        family_size=FAMILY_SIZE, family_complete=False, pending_models=list(PENDING_MODELS),
        bootstrap_seed=joint.BOOTSTRAP_SEED, bootstrap_replicates=joint.REPLICATES,
        qualification_recipe_sha256=dict(joint.QUALIFICATION_HASHES),
        interpretation='M1/G1 subset of four preregistered primaries versus production card play; '
            'Bonferroni98.75% per primary, never reduce family size to completed arms. '
            'Gen4/gen3 remain pending; this is not a four-model selection verdict. '
            'Qualification excluded; no optional extension; null is not equivalence. '
            'Not full Fly package or deployment approval. Report operational summaries separately.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    parser.add_argument('--qualification', required=True)
    args = parser.parse_args()
    print(json.dumps(readout(args.directory, args.qualification), indent=2))

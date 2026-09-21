"""Frozen 48-pair cutoff screen: reject drift before computing any contrasts."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from .policy_world_compare import _read

QUALIFICATION_HASHES = {
    'VALUE_CUTOFF_T1': '239167159cbc56df876c5c90ba54fe105467eca0d124b68fcd68ed33610dcd28',
    'LEARNED_CUTOFF_T1': '7a335129f26beffc7d09dbec5232d55f990bfdc0c9ef6b2edc6236adcc289270',
}
ARMS = ('VALUE_T1_VS_TERMINAL', 'MODEL_T1_VS_TERMINAL')
DEALS, SEED0 = 48, 626200000


def normalized(recipe):
    recipe = copy.deepcopy(recipe)
    recipe.pop('checkpoint', None)  # Content identity remains pinned.
    return recipe


def expected_recipes(qualification):
    refs = {}
    for name, digest in QUALIFICATION_HASHES.items():
        raw = (Path(qualification) / name / 'recipe.json').read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('qualification recipe identity mismatch')
        refs[name] = json.loads(raw)
    value = refs['VALUE_CUTOFF_T1']
    model = refs['LEARNED_CUTOFF_T1']
    # The new model arm faces the SAME terminal-level control as the value arm,
    # not its qualification's heuristic-cutoff control. Only this planned
    # substitution and sample/worker counts may differ from sealed recipes.
    model['control'] = value['control']
    model['control_effective'] = copy.deepcopy(value['control_effective'])
    for recipe in (value, model):
        recipe.update(seed0=SEED0, deals=DEALS, workers=12)
    return value, model


def readout(directory, qualification):
    values = []
    for name, expected in zip(ARMS, expected_recipes(qualification)):
        recipe, data = _read(Path(directory) / name)
        if normalized(recipe) != normalized(expected):
            raise ValueError('frozen cutoff screen recipe drift')
        values.append(data)
    matrix = np.stack(values, axis=1)
    rng = np.random.default_rng(20260921)
    boots = np.concatenate([matrix[rng.integers(0, DEALS,
        (min(128, 10000-i), DEALS))].mean(axis=1) for i in range(0, 10000, 128)])
    primaries = {}
    for i, name in enumerate(ARMS):
        primaries[name] = dict(mean=float(matrix[:, i].mean()),
            ci97_5=np.quantile(boots[:, i], [.0125, .9875]).tolist(),
            descriptive_ci95=np.quantile(boots[:, i], [.025, .975]).tolist())
    return dict(deals=DEALS, seed0=SEED0, primaries=primaries,
        exploratory_model_minus_value=dict(mean=float((matrix[:, 1]-matrix[:, 0]).mean()),
            ci95=np.quantile(boots[:, 1]-boots[:, 0], [.025, .975]).tolist()),
        bootstrap_seed=20260921, bootstrap_replicates=10000,
        interpretation='Two primaries versus heuristic terminal-level MC, Bonferroni97.5%. '
            'Component is a matched common-opponent difference, not a direct duel. '
            'Not point-utility MC-LCB. Qualification excluded; no optional extension. '
            'Null is not equivalence; no production approval.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    parser.add_argument('--qualification', required=True)
    args = parser.parse_args()
    print(json.dumps(readout(args.directory, args.qualification), indent=2))

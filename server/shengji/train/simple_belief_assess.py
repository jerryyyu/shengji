"""Retained, paired ownership readout against the corrected ordinary sampler.

Outcome-blind phase-spread positions on internal belief check deals. This is
not a gameplay result and does not claim these value-fit deals are fresh W32
holdout. No weight fitting or hyperparameter selection occurs here.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import time

import numpy as np

from .simple_belief_data import canonical, digest, load_fit_records, select_records
from .harvest_labels import replay_checked
from .simple_belief_reference import corrected_reference


def _assess_deal(task):
    key, records, predictions, masks, targets, path, identity, worlds = task
    path = Path(path)
    if path.exists():
        result = json.loads(path.read_bytes())
        if result['identity'] != identity:
            raise ValueError('assessment shard belongs to a different recipe')
        return result
    rows = []
    for (state, record), predicted, allowed, truth in zip(records, predictions, masks, targets):
        rnd, diffs = replay_checked(record)
        if diffs or rnd.turn != record['seat']:
            raise ValueError('assessment reconstruction differs')
        seed = int(digest(('simple-belief-reference-v1|' + state).encode())[:16], 16)
        baseline = corrected_reference(rnd, record['seat'], seed=seed, n=worlds)
        uncertain = allowed.sum(axis=-1) > 1
        actual = np.eye(3)[truth]
        model_error = np.square(predicted-actual).sum(axis=-1)
        raw_error = np.square(baseline['probabilities']-actual).sum(axis=-1)
        corrected = raw_error-baseline['brier_correction']
        rows.append({'state_key': state, 'ply': len(record['plays_prefix']),
                     'seat': record['seat'], 'trump_rank': rnd.trump_rank,
                     'is_nt': bool(rnd.trump_is_nt), 'is_banker': rnd.banker == record['seat'],
                     'uncertain_cells': int(uncertain.sum()),
                     'model_brier': float(model_error[uncertain].mean()) if uncertain.any() else 0.,
                     'reference_raw_brier': float(raw_error[uncertain].mean()) if uncertain.any() else 0.,
                     'reference_corrected_brier': float(corrected[uncertain].mean()) if uncertain.any() else 0.,
                     'reference_wall_seconds': baseline['wall_seconds'],
                     'reference_unique_worlds': baseline['unique_worlds'],
                     'reference_attempts': baseline['attempts'],
                     'probabilities': predicted.tolist(), 'reference_probabilities': baseline['probabilities'].tolist(),
                     'targets': truth.tolist(), 'uncertain': uncertain.tolist()})
    result = {'identity': identity, 'deal_key': key, 'rows': rows}
    temporary = path.with_suffix('.partial.json')
    temporary.write_bytes(canonical(result))
    temporary.replace(path)
    return result


def assess(cache, source, checkpoint, output, *, worlds=256, workers=4, positions=3):
    import torch
    from .simple_belief_train import _validate_recipe, _load_checkpoint, _load_file
    from .simple_belief_model import SimpleBeliefMLP, masked_count_probabilities
    from .simple_belief_features import FEATURE_DIM
    if worlds < 2 or workers < 1 or positions < 1:
        raise ValueError('positive workers/positions and at least two worlds required')
    torch.set_num_threads(2)
    started = time.monotonic()
    cache, output, checkpoint = Path(cache), Path(output), Path(checkpoint)
    recipe, recipe_sha = _validate_recipe(cache)
    payload = _load_checkpoint(checkpoint, recipe_sha)
    model = SimpleBeliefMLP(FEATURE_DIM, payload['config']['width'], payload['config']['hidden'])
    model.load_state_dict(payload['model'])
    model.eval()
    grouped, _, _ = load_fit_records(source)
    from . import simple_belief_reference
    spec = {'schema': 'simple-belief-reference-readout-v1', 'cache_recipe_sha256': recipe_sha,
            'producer_sha256': digest(Path(__file__).read_bytes() +
                                      Path(simple_belief_reference.__file__).read_bytes()),
            'checkpoint_sha256': digest(checkpoint.read_bytes()), 'epoch': payload['completed_epochs'],
            'worlds': worlds, 'positions_per_deal': positions, 'split': 'check',
            'scope': 'internal belief-only check; baseline value-fit deals, not fresh gameplay'}
    output.mkdir(parents=True, exist_ok=True)
    specpath = output / 'recipe.json'
    if specpath.exists() and specpath.read_bytes() != canonical(spec):
        raise ValueError('assessment recipe differs')
    specpath.write_bytes(canonical(spec))
    tasks = []
    for descriptor in recipe['deals']:
        if descriptor['split'] != 'check':
            continue
        key = descriptor['deal_key']
        selected = select_records(grouped[key], recipe['positions_per_deal'])
        x, mask, targets = _load_file(cache, descriptor)
        with np.load(cache / descriptor['path'], allow_pickle=False) as saved:
            if saved['state_keys'].tolist() != [k for k, _ in selected]:
                raise ValueError('assessment positions differ from cache')
        ix = np.linspace(0, len(x)-1, min(positions, len(x)), dtype=int)
        with torch.no_grad():
            p = masked_count_probabilities(model(torch.from_numpy(x[ix])), torch.from_numpy(mask[ix])).numpy()
        identity = digest(canonical([spec, key, [selected[i][0] for i in ix]]))
        tasks.append((key, [selected[i] for i in ix], p, mask[ix], targets[ix],
                      str(output / (key.removeprefix('deck:') + '.json')), identity, worlds))
    results = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(_assess_deal, tasks):
            results.append(result)
            if len(results) % 10 == 0 or len(results) == len(tasks):
                print(json.dumps({'stage': 'paired_reference', 'deals': len(results), 'total': len(tasks),
                                  'percent': 100*len(results)/len(tasks),
                                  'wall_seconds': time.monotonic()-started}), flush=True)
    # Each deal is one independent cluster; late deterministic positions do
    # not dilute scores with trivial zeros and are reported as skipped below.
    rows = [row for result in results for row in result['rows'] if row['uncertain_cells']]
    deltas = np.asarray([np.mean([row['reference_corrected_brier']-row['model_brier']
                                 for row in result['rows'] if row['uncertain_cells']])
                         for result in results if any(row['uncertain_cells'] for row in result['rows'])])
    rng = np.random.default_rng(20260910)
    bootstrap = deltas[rng.integers(0, len(deltas), (2000, len(deltas)))].mean(axis=1)
    summary = {'schema': spec['schema'], 'epoch': spec['epoch'], 'deals': len(results), 'positions': len(rows),
               'deterministic_positions_skipped': sum(len(r['rows']) for r in results)-len(rows),
               'mean_model_brier': float(np.mean([r['model_brier'] for r in rows])),
               'mean_reference_raw_brier': float(np.mean([r['reference_raw_brier'] for r in rows])),
               'mean_reference_corrected_brier': float(np.mean([r['reference_corrected_brier'] for r in rows])),
               'equal_deal_mean_brier_improvement': float(deltas.mean()),
               'equal_deal_bootstrap95': np.quantile(bootstrap, [.025, .975]).tolist(),
               'wall_seconds': time.monotonic()-started, 'scope': spec['scope']}
    temporary = output / 'summary.partial.json'
    temporary.write_bytes(canonical(summary))
    temporary.replace(output / 'summary.json')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('cache', 'source', 'checkpoint', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--worlds', type=int, default=256)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--positions', type=int, default=3)
    args = parser.parse_args()
    print(json.dumps(assess(**vars(args)), indent=2))


if __name__ == '__main__':
    main()

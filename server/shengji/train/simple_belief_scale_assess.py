"""Re-score fixed saved ownership states; reuse MC and R4, never resample."""
import argparse
import copy
import json
from pathlib import Path

import numpy as np
import torch

from .simple_belief_data import canonical, digest
from .simple_belief_features import FEATURE_DIM
from .simple_belief_model import SimpleBeliefMLP, masked_count_probabilities
from .simple_belief_train import _validate_recipe, _load_checkpoint, _load_file
from .simple_belief_scale import write_once
from .simple_belief_receiver_readout import analyze
from .simple_belief_calibration import analyze as calibration


def replace_predictions(rows, states, predictions, masks, targets):
    lookup = {key: i for i, key in enumerate(states)}
    result = copy.deepcopy(rows)
    for row in result:
        i = lookup[row['state_key']]
        uncertain = masks[i].sum(axis=-1) > 1
        if not np.array_equal(targets[i], row['targets']) or not np.array_equal(uncertain, row['uncertain']):
            raise ValueError('saved state labels/masks differ')
        p = predictions[i]
        error = np.square(p-np.eye(3)[targets[i]]).sum(axis=-1)
        row['probabilities'] = p.tolist()
        row['model_brier'] = float(error[uncertain].mean()) if uncertain.any() else 0.
    return result


def assess(cache, checkpoint, old_cache, reference, r4, output):
    torch.set_num_threads(2)
    cache, checkpoint, old_cache = Path(cache), Path(checkpoint), Path(old_cache)
    reference, r4, output = Path(reference), Path(r4), Path(output)
    recipe, recipe_sha = _validate_recipe(cache)
    payload = _load_checkpoint(checkpoint, recipe_sha)
    old, _ = _validate_recipe(old_cache)
    trained = {d['deal_key'] for d in recipe['deals'] if d['split'] == 'train'}
    check = [d for d in old['deals'] if d['split'] == 'check']
    if trained & {d['deal_key'] for d in check}:
        raise ValueError('evaluation deal reached training')
    model = SimpleBeliefMLP(FEATURE_DIM, payload['config']['width'], payload['config']['hidden'])
    model.load_state_dict(payload['model'])
    model.eval()
    spec = json.loads((reference/'recipe.json').read_bytes())
    spec.update(checkpoint_sha256=digest(checkpoint.read_bytes()), cache_recipe_sha256=recipe_sha,
                epoch=payload['completed_epochs'], reused_reference=str(reference))
    write_once(output/'reference'/'recipe.json', spec)
    for desc in check:
        name = desc['deal_key'].removeprefix('deck:')+'.json'
        identity = digest(canonical([spec, desc['deal_key']]))
        destination = output/'reference'/name
        if destination.exists():
            if json.loads(destination.read_bytes())['identity'] != identity:
                raise ValueError('saved prediction identity differs')
            continue
        x, mask, target = _load_file(old_cache, desc)
        with np.load(old_cache/desc['path'], allow_pickle=False) as saved:
            states = saved['state_keys'].tolist()
        with torch.no_grad():
            p = masked_count_probabilities(model(torch.from_numpy(x)), torch.from_numpy(mask)).numpy()
        original = json.loads((reference/name).read_bytes())
        rows = replace_predictions(original['rows'], states, p, mask, target)
        write_once(output/'reference'/name, {**original,
                   'identity': identity, 'rows': rows})
    source_summary = json.loads((reference/'summary.json').read_bytes())
    write_once(output/'reference'/'summary.json', {'schema': spec['schema'], 'deals': len(check),
               'positions': source_summary['positions'],
               'deterministic_positions_skipped': source_summary['deterministic_positions_skipped'],
               'note': 'recomputed model only; ordinary/R4 predictions retained unchanged'})
    result = analyze(output/'reference', r4)
    write_once(output/'receivers.json', result)
    write_once(output/'calibration.json', calibration(output/'reference'))
    print(json.dumps({'checkpoint': str(checkpoint), 'population': result['population'],
                      'brier': result['equal_deal_mean_brier'], 'paired': result['paired']}), flush=True)
    return result


def assess_fresh(cache, checkpoint, gameplay, reference, r4, output):
    from .simple_belief_fresh_assess import _replay_states, _state_key
    from .simple_belief_features import actor_features, ownership_targets
    torch.set_num_threads(2)
    reference, output = Path(reference), Path(output)
    recipe, recipe_sha = _validate_recipe(Path(cache))
    payload = _load_checkpoint(Path(checkpoint), recipe_sha)
    trained = {d['deal_key'] for d in recipe['deals'] if d['split'] == 'train'}
    model = SimpleBeliefMLP(FEATURE_DIM, payload['config']['width'], payload['config']['hidden'])
    model.load_state_dict(payload['model'])
    model.eval()
    spec = json.loads((reference/'recipe.json').read_bytes())
    spec.update(checkpoint_sha256=digest(Path(checkpoint).read_bytes()),
                cache_recipe_sha256=recipe_sha, epoch=payload['completed_epochs'],
                reused_reference=str(reference))
    write_once(output/'reference'/'recipe.json', spec)
    clusters = sorted(Path(gameplay).glob('cluster-*.json'))
    for file in clusters:
        cluster = json.loads(file.read_bytes())
        ordinary = [r for r in cluster['records'] if r['arm'] == 'ordinary']
        if len(ordinary) != 1:
            raise ValueError('one common ordinary arm required')
        key, snapshots, outcome = _replay_states(cluster['spec'], ordinary[0])
        if key in trained:
            raise ValueError('fresh evaluation deal reached training')
        name = key.removeprefix('deck:')+'.json'
        original = json.loads((reference/name).read_bytes())
        states, predictions, masks, targets = [], [], [], []
        for index, (rnd, seat) in sorted(snapshots.items()):
            x, mask = actor_features(rnd, seat)
            with torch.no_grad():
                p = masked_count_probabilities(model(torch.from_numpy(x[None])),
                                                torch.from_numpy(mask[None])).numpy()[0]
            # Label reconstruction occurs only after prediction.
            targets.append(ownership_targets(rnd, seat))
            predictions.append(p)
            masks.append(mask)
            states.append(_state_key(key, index, outcome['transcript']))
        rows = replace_predictions(original['rows'], states, np.asarray(predictions),
                                   np.asarray(masks), np.asarray(targets))
        write_once(output/'reference'/name, {**original, 'rows': rows,
                   'identity': digest(canonical([spec, key]))})
    summary = json.loads((reference/'summary.json').read_bytes())
    if len(clusters) != summary['deals']:
        raise ValueError('fresh population incomplete')
    write_once(output/'reference'/'summary.json', summary)
    result = analyze(output/'reference', r4)
    result['note'] = 'Fixed 14 earlier DEV gameplay deals excluded from all training; ownership only, not a new gameplay test.'
    write_once(output/'receivers.json', result)
    write_once(output/'calibration.json', calibration(output/'reference'))
    print(json.dumps({'fresh_population': result['population'],
                      'brier': result['equal_deal_mean_brier']}), flush=True)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('cache', 'checkpoint', 'reference', 'r4', 'output'):
        p.add_argument('--'+name, required=True)
    p.add_argument('--old-cache')
    p.add_argument('--fresh-gameplay')
    args = vars(p.parse_args())
    gameplay = args.pop('fresh_gameplay')
    if gameplay:
        args.pop('old_cache')
        assess_fresh(gameplay=gameplay, **args)
    else:
        assess(**args)


if __name__ == '__main__':
    main()

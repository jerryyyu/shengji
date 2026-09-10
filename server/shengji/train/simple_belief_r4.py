"""Read-only old-R4 inference on the same saved simple-belief check positions.

Reuses the retained actor-only subprocess bridge. Does not reopen an R4 test
dataset, train an ensemble, or introduce hidden state into model inputs.
"""
import argparse
import json
from pathlib import Path
import time

import numpy as np

from ..rl.encode import CARD_INDEX
from .simple_belief_data import canonical, digest, load_fit_records, select_records
from .harvest_labels import replay_checked
from .r4_runtime_client import R4RuntimeClient, actor_for_round


def ownership_array(actor, ownership):
    """Extend explicit sparse R4 cells with only logically known zero/kitty."""
    receivers = {f'seat-relative-{r}': r-1 for r in range(1, 4)}
    if actor.hidden_burial_size:
        receivers['hidden-kitty'] = 3
    expected = {(card, rec) for card, _ in actor.deductions.unseen for rec in receivers}
    p = np.zeros((4, 54, 3), dtype=np.float64)
    p[..., 0] = 1
    seen = set()
    if ownership.get('probability_scale') != 1_000_000_000:
        raise ValueError('R4 probability scale differs')
    for cell in ownership['count_probabilities']:
        key = cell['card'], cell['receiver']
        if key not in expected or key in seen:
            raise ValueError('R4 cell population differs')
        seen.add(key)
        values = cell['count_probability_ppb']
        if len(values) != 3 or any(type(v) is not int or v < 0 for v in values) \
                or sum(values) != 1_000_000_000:
            raise ValueError('R4 count probabilities invalid')
        p[receivers[key[1]], CARD_INDEX[key[0]]] = np.asarray(values)/1e9
    if seen != expected:
        raise ValueError('R4 sparse cells missing')
    if not actor.hidden_burial_size:
        for card, count in actor.actor_known_burial:
            p[3, CARD_INDEX[card]] = np.eye(3)[count]
    return p


def compare(source, reference, archive_server, training_root, output):
    reference, output = Path(reference), Path(output)
    summary = json.loads((reference / 'summary.json').read_bytes())
    recipe = json.loads((reference / 'recipe.json').read_bytes())
    grouped, _, _ = load_fit_records(source)
    inputs = [json.loads(path.read_bytes()) for path in sorted(reference.glob('*.json'))
              if path.name not in ('summary.json', 'recipe.json')]
    if len(inputs) != summary['deals']:
        raise ValueError('R4 comparison deal population differs')
    started = time.monotonic()
    output.mkdir(parents=True, exist_ok=True)
    results = []
    with R4RuntimeClient(archive_server, training_root) as client:
        spec = {'schema': 'simple-belief-r4-compare-v1', 'reference_recipe': recipe,
                'r4_identity': client.identity, 'archive_server': str(archive_server),
                'producer_sha256': digest(Path(__file__).read_bytes()),
                'scope': 'same internal-belief check deals, not R4 original test or gameplay'}
        specpath = output / 'recipe.json'
        if specpath.exists() and specpath.read_bytes() != canonical(spec):
            raise ValueError('R4 comparison recipe differs')
        specpath.write_bytes(canonical(spec))
        for item in inputs:
            key = item['deal_key']
            selected = dict(select_records(grouped[key], len(grouped[key])))
            identity = digest(canonical([spec, key, item['identity']]))
            path = output / (key.removeprefix('deck:') + '.json')
            if path.exists():
                result = json.loads(path.read_bytes())
                if result['identity'] != identity:
                    raise ValueError('R4 comparison shard differs')
                results.append(result)
                continue
            rows = []
            for row in item['rows']:
                if not row['uncertain_cells']:
                    continue
                rnd, diffs = replay_checked(selected[row['state_key']])
                if diffs or rnd.turn != row['seat']:
                    raise ValueError('R4 comparison reconstruction differs')
                actor = actor_for_round(rnd, row['seat'], archive_server)
                response = client.predict(actor)
                uncertain = np.asarray(row['uncertain'])
                truth = np.eye(3)[np.asarray(row['targets'])]
                arms = {}
                for name, payload in response['arms'].items():
                    p = ownership_array(actor, payload['ownership'])
                    arms[name] = {'probabilities': p.tolist(),
                                  'brier': float(np.square(p-truth).sum(axis=-1)[uncertain].mean())}
                rows.append({'state_key': row['state_key'], 'ply': row['ply'],
                             'actor_sha256': actor.sha256(),
                             'incomplete_declaration_history': not actor.declaration_history_complete,
                             'inference_seconds_both_cohorts': response['inference_wall_s'],
                             'model_brier': row['model_brier'],
                             'reference_corrected_brier': row['reference_corrected_brier'], 'arms': arms})
            result = {'deal_key': key, 'identity': identity, 'rows': rows}
            temporary = path.with_suffix('.partial.json')
            temporary.write_bytes(canonical(result))
            temporary.replace(path)
            results.append(result)
            if len(results) % 10 == 0 or len(results) == len(inputs):
                print(json.dumps({'stage': 'r4_same_states', 'deals': len(results), 'total': len(inputs),
                                  'wall_seconds': time.monotonic()-started}), flush=True)
    rows = [r for result in results for r in result['rows']]
    report = {'deals': len(results), 'positions': len(rows),
              'model_brier': float(np.mean([r['model_brier'] for r in rows])),
              'reference_corrected_brier': float(np.mean([r['reference_corrected_brier'] for r in rows])),
              'r4_brier': {name: float(np.mean([r['arms'][name]['brier'] for r in rows]))
                           for name in client.identity},
              'inference_seconds_both_cohorts': sum(r['inference_seconds_both_cohorts'] for r in rows),
              'wall_seconds': time.monotonic()-started, 'scope': spec['scope']}
    temporary = output / 'summary.partial.json'
    temporary.write_bytes(canonical(report))
    temporary.replace(output / 'summary.json')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'reference', 'archive-server', 'training-root', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    print(json.dumps(compare(**vars(parser.parse_args())), indent=2))


if __name__ == '__main__':
    main()

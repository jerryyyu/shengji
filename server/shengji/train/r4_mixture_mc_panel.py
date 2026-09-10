"""Bounded DEV mixture readout on retained W32 selection/report worlds.

Fit only from model probabilities + sampled-world counts. Reuse old rollouts;
extend only missing admitted columns. No new worlds, models, games or outcomes.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .r4_w32_extend import extend
from .r4_w32_weight_diagnostic import cell_count, require_capture_binding
from .search_screen import _publish
from .world_mixture_fit import fit_world_mixture
from .world_mixture_mc import mixture_decision, reduce_mixture_arms


def _read(path):
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def run_position(row, out):
    started = time.monotonic()
    root = Path(row['capture']).parent
    capture, capture_sha = _read(Path(row['capture']))
    pred, pred_sha = _read(root/'r4-marginals.json')
    old_rank, _ = _read(root/'rank-comparison-typed-v2.json')
    require_capture_binding(Path(row['capture']), old_rank, root/'r4-marginals.json')
    if capture_sha != row['capture_sha256'] or pred_sha != row['prediction_sha256'] \
            or not old_rank['typed_world_constraints_passed'] \
            or pred['actor_sha256'] != capture['actor_sha256']:
        raise ValueError('mixture source binding differs')
    ranking = {**old_rank, 'arms': row['arms']}
    if set(ranking['arms']) != set(pred['arms']) or row['baseline_shortlist'] != old_rank['baseline_shortlist']:
        raise ValueError('mixture rank arm or baseline differs')
    out.mkdir(parents=True, exist_ok=True)
    binding = {'capture_sha256': capture_sha, 'predictions_sha256': pred_sha,
               'rank_sha256': hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest(),
               'code_sha256': hashlib.sha256(b''.join(Path(p).read_bytes() for p in (
                   __file__, Path(__file__).with_name('world_mixture_fit.py'),
                   Path(__file__).with_name('world_mixture_mc.py')))).hexdigest(),
               'fold_sha256': {}}
    folds = {}
    for fold, n in (('selection', 30), ('report', 300)):
        path = root/'mc'/fold/'private-world-values.json'
        data, sha = _read(path)
        old_weights, _ = _read(root/'mc'/fold/'weights-v2.json')
        require_capture_binding(path, old_weights, root/'r4-marginals.json')
        if not old_weights['typed_world_constraints_passed'] or data['actor_sha256'] != capture['actor_sha256'] \
                or len(data['worlds']) != n or data['fold'] != fold:
            raise ValueError('retained MC world constraints or identity differ')
        binding['fold_sha256'][fold] = sha
        folds[fold] = data
    terminal = out/'result.json'
    if terminal.exists():
        saved, _ = _read(terminal)
        if saved['binding'] != binding:
            raise ValueError('completed mixture readout inputs differ')
        return saved
    fit_path = out/'fold-fits.json'
    if fit_path.exists():
        fits, _ = _read(fit_path)
        if fits['binding'] != binding:
            raise ValueError('saved fold fits inputs differ')
    else:
        fits = {'binding': binding, 'folds': {}}
        # No true trajectory is reopened before all fold/arm fits finish.
        for fold, data in folds.items():
            fits['folds'][fold] = {}
            for name, arm in pred['arms'].items():
                cells = arm['ownership']['count_probabilities']
                counts = np.array([[cell_count(w, capture['seat'], c['card'], c['receiver'])
                                    for c in cells] for w in data['worlds']])
                probs = np.array([c['count_probability_ppb'] for c in cells])/1e9
                fits['folds'][fold][name] = fit_world_mixture(counts, probs)
        _publish(fit_path, fits)
    # Existing implementation validates a retained rollout before new columns.
    extend(root, ranking, out/'mc')
    augmented = {f: _read(out/'mc'/f/'private-world-values.json')[0] for f in folds}
    union = augmented['selection']['union_indices']
    if union != augmented['report']['union_indices']:
        raise ValueError('extended MC action identity differs')
    for f, data in augmented.items():
        old = folds[f]
        if data['worlds'] != old['worlds'] or any(
                row_new[:len(old['union_indices'])] != row_old
                for row_new, row_old in zip(data['values_world_major'], old['values_world_major'], strict=True)):
            raise ValueError('extension changed saved worlds or rollout columns')
    actions = augmented['selection']['actions']
    baseline = [union.index(i) for i in ranking['baseline_shortlist']]
    ranked = {name: [union.index(i) for i in a['shortlist']] for name, a in ranking['arms'].items()}
    weights = {f: {n: fit['weights'] for n, fit in arms.items()} for f, arms in fits['folds'].items()}
    selection, report = (augmented[f]['values_world_major'] for f in ('selection', 'report'))
    decisions = reduce_mixture_arms(actions, baseline, ranked, selection, report, weights)
    uniform = mixture_decision(actions, baseline, selection, report, np.full(30, 1/30), np.full(300, 1/300))
    if uniform != decisions['ordinary']:
        raise ValueError('uniform mixture changed ordinary final consumer')
    for d in decisions.values():
        for key in ('played', 'raw_winner', 'challenger'):
            if d[key] is not None:
                d[key] = union[d[key]]
        d['admitted'] = [union[i] for i in d['admitted']]
    old_final, _ = _read(root/'mc'/'final-decisions-v2.json')
    if decisions['ordinary'] != old_final['decisions']['ordinary']:
        raise ValueError('ordinary decision drifted from saved production consumer')
    result = {'panel': row['panel'], 'index': row['index'], 'binding': binding,
              'decisions': decisions, 'uniform_final_parity': True, 'ordinary_saved_parity': True,
              'extension_rollouts': sum(d['extension_rollouts'] for d in augmented.values()),
              'witness_rollouts': sum(d['extension_witness_rollouts'] for d in augmented.values()),
              'new_worlds': 0, 'new_games': 0, 'strength_claim': False,
              'wall_s': time.monotonic()-started,
              'scope': '13 shared DEV deals at three prefixes; weighted report bound exploratory'}
    _publish(terminal, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mixture', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--workers', type=int, choices=(1, 2), default=2)
    parser.add_argument('--limit', type=int, default=39)
    args = parser.parse_args(argv)
    source, _ = _read(args.mixture)
    rows = source['rows'][:args.limit]
    started = time.monotonic()
    completed = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        pending = {pool.submit(run_position, row, args.out/row['panel']/f"position-{row['index']:02d}")
                   for row in rows}
        for future in as_completed(pending):
            result = future.result()
            completed.append(result)
            print(json.dumps({'completed': len(completed), 'total': len(rows),
                              'wall_s': round(time.monotonic()-started, 2),
                              'last_extension_rollouts': result['extension_rollouts']}), flush=True)
    completed.sort(key=lambda r: (r['panel'], r['index']))
    summary = {'positions': len(completed), 'new_worlds': 0, 'new_games': 0, 'strength_claim': False,
               'changed_final': {n: sum(r['decisions'][n]['played'] != r['decisions']['ordinary']['played']
                                        for r in completed) for n in completed[0]['decisions'] if n != 'ordinary'},
               'extension_rollouts': sum(r['extension_rollouts'] for r in completed),
               'witness_rollouts': sum(r['witness_rollouts'] for r in completed),
               'wall_s': time.monotonic()-started, 'rows': completed}
    _publish(args.out/f'summary-{len(rows)}.json', summary)
    print(json.dumps({k: v for k, v in summary.items() if k != 'rows'}, indent=2))


if __name__ == '__main__':
    main()

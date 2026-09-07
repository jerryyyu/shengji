#!/usr/bin/env python3
"""FIT-only nomination/selector substitutions using retained rollout matrices.

No neural inference, new native rollouts, training, or games. Cross-fitting
removes direct same-world choose/judge reuse, not prior analyst exposure.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from scripts.cwv_selector_objective_audit import digest, verify_control
from shengji.luna.game import _round_from_snapshot
from shengji.train.cwv_selector_objective_audit import replay_selector
from shengji.train.cwv_stage_substitution_audit import fold_plan
from shengji.train.search_screen import _publish, bind_output_config, execution_source_identity


def run_case(entry, saved, reference, matrices, *, seed, k=5):
    start = time.perf_counter()
    if entry.get('provenance', {}).get('split') != 'fit':
        raise ValueError('stage diagnostic accepts only FIT positions')
    if any(row['state_id'] != entry['id'] for row in (saved, reference, matrices)):
        raise ValueError('stage root identity mismatch')
    if (reference['binding']['entry_hash'] != digest(entry)
            or matrices['source_state_sha256'] != digest(saved)
            or matrices['reference_sha256'] != digest(reference)):
        raise ValueError('stage retained source mismatch')
    arms = {n: a for n, a in saved['arms'].items() if n.endswith('/finished')}
    actions = [tuple(sorted(a)) for a in matrices['actions']]
    expected = sorted({tuple(sorted(saved['actions'][i])) for a in arms.values() for i in a['shortlist_indices']})
    if actions != expected:
        raise ValueError('matrix action order or population mismatch')
    index = {a: i for i, a in enumerate(actions)}
    reference_actions = [tuple(sorted(a)) for a in reference['actions']]
    if len(set(reference_actions)) != len(reference_actions):
        raise ValueError('duplicate reference actions')
    ref_index = {a: i for i, a in enumerate(reference_actions)}
    refs = np.asarray(reference['returns']['levels'], dtype=float)
    if refs.shape != (1024, len(ref_index)):
        raise ValueError('reference world/action dimensions mismatch')
    refs = refs[:, [ref_index[a] for a in actions]]
    point_arrays = {f: np.asarray(matrices['folds'][f]['points'], dtype=float) for f in ('selection', 'report')}
    if point_arrays['selection'].shape != (30, len(actions)) or point_arrays['report'].shape != (300, len(actions)):
        raise ValueError('N30/R300 point matrix dimensions mismatch')
    incumbent = index[tuple(sorted(saved['incumbent']))]
    ballots = {n: [index[tuple(sorted(saved['actions'][i]))] for i in a['shortlist_indices']] for n, a in arms.items()}
    plans = fold_plan(refs, ballots, incumbent, k=k)
    rnd = _round_from_snapshot(entry['snapshot'])

    def replay(ballot):
        return replay_selector(rnd, rnd.turn, [list(actions[i]) for i in ballot],
                               point_arrays['selection'][:, ballot], point_arrays['report'][:, ballot],
                               seed=seed, objective='points')

    controls = {}
    for name, ballot in ballots.items():
        controls[name] = replay(ballot)
        verify_control(arms[name]['final_mc_record'], controls[name]['record'])
        if sorted(controls[name]['played']) != sorted(arms[name]['played']):
            raise ValueError('control played action mismatch')
    # All controls above must succeed before accepting any counterfactual cell.
    folds = []
    for plan in plans:
        reference_mc = replay(plan['reference_ballot'])
        reference_mc_pick = index[tuple(sorted(reference_mc['played']))]
        judged = np.asarray(plan['evaluation_means'])
        output = {}
        for name in ballots:
            picks = {'model_mc': index[tuple(sorted(controls[name]['played']))],
                     'reference_mc': reference_mc_pick,
                     'model_reference': plan['model_reference_picks'][name],
                     'reference_reference': plan['reference_pick']}
            output[name] = {cell: {'picked_index': pick,
                                   'final_lift_vs_incumbent': float(judged[pick] - judged[incumbent])}
                            for cell, pick in picks.items()}
        folds.append({'plan': plan, 'cells': output, 'reference_mc_record': reference_mc['record']})
    # Two equal-size world folds per root, then source-deal aggregation later.
    values = {name: {cell: float(np.mean([f['cells'][name][cell]['final_lift_vs_incumbent'] for f in folds]))
                     for cell in folds[0]['cells'][name]} for name in ballots}
    for name in ballots:
        if abs(values[name]['model_mc'] - matrices['arms'][name + '/points']['final_lift_vs_incumbent']) > 1e-12:
            raise ValueError('cross-fold baseline value drift')
    return {'state_id': entry['id'], 'deal_key': entry['deal_key'], 'provenance': entry['provenance'],
            'input_binding': {'entry': digest(entry), 'saved': digest(saved), 'reference': digest(reference), 'matrices': digest(matrices)},
            'actions': actions, 'union_sha256': digest(actions), 'model_ballots': ballots,
            'all_controls_reproduced': True, 'folds': folds, 'values': values,
            'fresh_rollouts': 0, 'wall_seconds': time.perf_counter() - start}


def summarize(rows):
    if not rows or not all(r['all_controls_reproduced'] for r in rows):
        raise ValueError('incomplete actual-consumer controls')
    grouped = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for row in rows:
        for model, cells in row['values'].items():
            for cell, value in cells.items():
                grouped[model][cell][row['deal_key']].append(value)
    means, contrasts = {}, {}
    for model, cells in grouped.items():
        arrays = {c: np.array([np.mean(v) for _, v in sorted(deals.items())]) for c, deals in cells.items()}
        means[model] = {c: float(v.mean()) for c, v in arrays.items()}
        comparisons = {'nomination_only': ('reference_mc', 'model_mc'),
                       'selector_only': ('model_reference', 'model_mc'),
                       'both': ('reference_reference', 'model_mc')}
        contrasts[model] = {}
        for label, (a, b) in comparisons.items():
            delta = arrays[a] - arrays[b]
            rng = np.random.default_rng(20260907)
            draws = delta[rng.integers(len(delta), size=(10000, len(delta)))].mean(1)
            contrasts[model][label] = {'mean': float(delta.mean()), 'ci95': np.quantile(draws, [.025, .975]).tolist()}
    return {'scope': 'finite-reference stage substitutions on previously inspected FIT roots; not oracle/gameplay/holdout',
            'menu': 'fixed union of four model shortlists; not full legal-action coverage',
            'aggregation': 'average opposite-world folds within root, then roots within deal, then equal deals',
            'ci_scope': '10000 deal bootstrap conditional on reference draws, not multiplicity adjusted',
            'comparison': 'reference substitutions are not equal-compute or a calibrated deployable selector',
            'states': len(rows), 'deals': len({r['deal_key'] for r in rows}),
            'all_controls_reproduced': True, 'fresh_rollouts': sum(r['fresh_rollouts'] for r in rows),
            'means': means, 'contrasts': contrasts, 'wall_seconds': sum(r['wall_seconds'] for r in rows)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--matrices', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--max-new-states', type=int)
    args = parser.parse_args(argv)
    upstream = json.loads((args.matrices / 'config.json').read_text())
    decision_dir, reference_dir = Path(upstream['decisions']), Path(upstream['references'])
    source_config = json.loads((decision_dir / 'config.json').read_text())
    panel = json.loads(Path(source_config['panel_path']).read_text())
    if digest(panel) != upstream['panel_sha256']:
        raise ValueError('panel binding mismatch')
    config = {'matrices': str(args.matrices.resolve()), 'upstream': digest(upstream), 'panel': digest(panel),
              'script': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'source': execution_source_identity(Path(__file__).resolve().parents[1] / 'shengji')}
    bind_output_config(args.out, config)
    rows, new_count = [], 0
    for entry in panel['entries']:
        filename = f"state-{entry['id']}.json"
        inputs = [json.loads((directory / filename).read_text()) for directory in (decision_dir, reference_dir, args.matrices)]
        binding = dict(zip(('entry', 'saved', 'reference', 'matrices'), map(digest, (entry, *inputs))))
        path = args.out / filename
        if path.exists():
            row = json.loads(path.read_text())
            if row['input_binding'] != binding:
                raise ValueError('resumed inputs drift')
        elif args.max_new_states is not None and new_count >= args.max_new_states:
            continue
        else:
            seed = int(entry['id'][:15], 16) ^ upstream['seed']
            row = run_case(entry, *inputs, seed=seed)
            _publish(path, row)
            new_count += 1
        rows.append(row)
        print(f'{len(rows)}/{len(panel["entries"])} complete', flush=True)
    result = summarize(rows)
    result['complete'] = len(rows) == len(panel['entries'])
    _publish(args.out / 'summary.json', result)


if __name__ == '__main__':
    main()

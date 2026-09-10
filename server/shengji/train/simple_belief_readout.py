"""Combine retained belief gameplay, ownership and cost; never rerun a policy."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from . import simple_belief_gameplay as gameplay
from .cwv_bury_readout import interval
from .simple_belief_calibration import analyze as calibration
from .simple_belief_receiver_readout import analyze as receivers


def distribution(values):
    values = np.asarray(values, dtype=float)
    if not np.isfinite(values).all():
        raise ValueError('nonfinite measured cost')
    return {'n': len(values), 'mean': float(values.mean()) if len(values) else None,
            'p50_p95_p99': np.quantile(values, [.5, .95, .99]).tolist() if len(values) else []}


def gameplay_readout(shards):
    """Mirrors share a deal: average mirrors before computing an interval."""
    summary = gameplay.summarize(shards)
    pairs = [('new-small', 'uniform-pool'), ('r4-synthetic-primary', 'uniform-pool'),
             ('new-small', 'r4-synthetic-primary')]
    contrasts = {}
    for treatment, control in pairs:
        levels, wins = [], []
        for shard in shards:
            rows = {(r['arm'], r['focal_team']): r for r in shard['records']}
            dl, dw = [], []
            for team in (0, 1):
                sign = 1 if team == 0 else -1
                a = sign * rows[treatment, team]['outcome']['team0_signed_levels']
                b = sign * rows[control, team]['outcome']['team0_signed_levels']
                dl.append(a-b)
                dw.append(int(a > 0)-int(b > 0))
            levels.append(sum(dl)/2)
            wins.append(sum(dw)/2)
        contrasts[treatment+' vs '+control] = {
            'signed_levels': interval(levels), 'wins': interval(wins)}
    costs = {}
    for arm in ('ordinary', *gameplay.ARMS):
        rows = [r for s in shards for r in s['records'] if r['arm'] == arm]
        decisions = [d for r in rows for d in r['outcome']['transcript']
                     if arm == 'ordinary' or d['seat'] % 2 == r['focal_team']]
        beliefs = [d['last_belief'] for d in decisions if d.get('last_belief')]
        pools = [b for b in beliefs if b.get('pool_worlds')]
        fits = [b['fit'] for b in pools if b.get('fit')]
        costs[arm] = {
            'rounds': len(rows), 'inherited_controls': sum(bool(r.get('inherited_control')) for r in rows),
            'round_wall_seconds': distribution([r['wall_s'] for r in rows]),
            'focal_decision_seconds': distribution([d['decision_wall_s'] for d in decisions]),
            'summed_parent_cpu_seconds': sum(r['work']['parent_cpu_seconds'] for r in rows),
            'summed_child_inference_wall_seconds': sum(r['work']['child_inference_wall_seconds'] for r in rows),
            'rollouts': sum(r['work']['total_rollouts'] for r in rows),
            'sampled_decisions': sum(b.get('delivered', 0) > 0 for b in beliefs),
            'pool_decisions': len(pools), 'fits': len(fits),
            'converged_fits': sum(bool(f['converged']) for f in fits),
            'strict_rejections': sum(b.get('strict_rejections', 0) for b in beliefs),
            'invalid_pool_proposals': sum(b.get('invalid_proposals', 0) for b in pools),
            'pool_seconds': distribution([b['pool_seconds'] for b in pools]),
            'inference_seconds': distribution([b['inference_seconds'] for b in pools if 'inference_seconds' in b]),
            'unique_support_worlds': distribution([b['unique_pool_worlds'] for b in pools]),
            'unique_indices_drawn': distribution([b['unique_pool_indices_drawn'] for b in pools]),
            'ess_fraction': distribution([f['ess_fraction'] for f in fits]),
            'uniform_model_error': distribution([f['uniform_model_squared_error'] for f in fits]),
            'fitted_model_error': distribution([f['guarded_fit_model_squared_error'] for f in fits]),
        }
    return {'vs_ordinary': summary, 'learned_weighting_contrasts': contrasts, 'cost_and_diversity': costs,
            'notes': ['Positive gameplay differences favor the first arm; intervals cluster by deal, not mirror or decision.',
                      'Cost quantiles are descriptive, not matched-state speedups; policies change game length.',
                      'Pool timing includes proposal, inference and fitting; do not add inference twice.',
                      'ESS is over pool indices. Duplicate physical worlds can make physical diversity lower.',
                      'Fitted error measures matching the model, not matching truth; marginal fitting is not a joint posterior.',
                      'Parent CPU excludes R4 child CPU; child inference wall is reported separately.']}


def analyze(gameplay_root, ownership_root, curves_path):
    gameplay_root, ownership_root, curves_path = map(Path, (gameplay_root, ownership_root, curves_path))
    config_bytes = (gameplay_root/'config.json').read_bytes()
    config = json.loads(config_bytes)
    if config['config_sha256'] != gameplay._config_hash(config):
        raise ValueError('gameplay config differs')
    shards = [gameplay.read_cluster(gameplay_root/f'cluster-{i:05d}.json', config, i)
              for i in range(gameplay.PLANNED_DEALS)]
    combined = json.loads((ownership_root/'perdeal.json').read_bytes())
    if combined['config_sha256'] != config['config_sha256'] or sorted(
            d['spec']['index'] for d in combined['deals']) != list(range(gameplay.PLANNED_DEALS)):
        raise ValueError('fresh ownership population/config differs')
    ownership = receivers(ownership_root/'reference', ownership_root/'r4')
    if ownership['population']['deals'] != gameplay.PLANNED_DEALS:
        raise ValueError('derived ownership deal population differs')
    ownership['note'] = ('Fresh namespace, common ordinary-policy states, disjoint from all 768 small-model source deals. '
                         'This is exploratory DEV, not confirmation; retained old-R4 training metadata does not prove deal-level exclusion.')
    curves = json.loads(curves_path.read_bytes())
    selected = min(curves, key=lambda r: (r['dev_ce'], r['epoch']))
    return {'schema': 'simple-belief-combined-readout-v1',
            'gameplay_config_sha256': config['config_sha256'],
            'gameplay_config_file_sha256': hashlib.sha256(config_bytes).hexdigest(),
            'source': config['source'], 'small_checkpoint_sha256': config['small_checkpoint_sha256'],
            'value_checkpoint_sha256': config['checkpoint_sha256'],
            'curves_sha256': hashlib.sha256(curves_path.read_bytes()).hexdigest(),
            'training': {'curves': curves, 'best_dev_ce_epoch': selected['epoch'],
                         'selection_note': 'Selected by dev CE before check/gameplay; no outcome-based checkpoint reselection.'},
            'gameplay': gameplay_readout(shards), 'fresh_ownership': ownership,
            'fresh_calibration_and_examples': calibration(ownership_root/'reference'),
            'production_authorized': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gameplay-root', type=Path, required=True)
    parser.add_argument('--ownership-root', type=Path, required=True)
    parser.add_argument('--curves', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error('use a new report path; existing evidence is retained')
    result = analyze(args.gameplay_root, args.ownership_root, args.curves)
    temporary = args.output.with_suffix('.partial.json')
    temporary.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False)+'\n')
    temporary.replace(args.output)
    print(json.dumps({'output': str(args.output), 'deals': gameplay.PLANNED_DEALS}))


if __name__ == '__main__':
    main()

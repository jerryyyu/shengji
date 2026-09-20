"""Read-only, pre-specified three-arm MC-LCB strength screen readout.

Reject partial runs and recipe drift. Resample deals jointly across arms,
never individual seat mirrors. Component contrasts measure relative performance
against a common opponent, not direct head-to-head wins between candidates.
"""
import argparse
import copy
import json

import numpy as np

from .policy_world_compare import _read

SOURCE = '75bc524a1580d8fe8d306b4977f1a6346a9d1027'
CHECKPOINT = '8ecd4feaec480f1e76c1cc0119aed8996472512fa48eaa868415ff3d2318dd01'
SEED0 = 625400000  # Proposal: must be reserved before the launch hold is released.
DEALS = 800
REPLICATES = 10000
BOOTSTRAP_SEED = 20260920
MODES = ('policy-value', 'policy-selective-mc', 'policy-lookahead')


def policy_recipe(mode):
    return dict(
        mode=mode, **{'class': dict(zip(MODES, ('PolicyValueBot',
            'PolicySelectiveMCBot', 'PolicyLookaheadBot')))[mode]},
        candidates=8, value_head='outcome', value_batch_size=128,
        verification=({'gap': .1, 'worlds': 8, 'candidates': 2,
            'rollout_policy': 'HeuristicBot', 'utility': 'root-team half-level',
            'seed_offset': 1000000007, 'exact_endgame': False}
            if mode == 'policy-selective-mc' else None),
        extra_plies=4 if mode == 'policy-lookahead' else 0,
        continuation_worlds=1 if mode == 'policy-lookahead' else 0,
        worlds=4, cap=4000, seed_formula='seed*4+seat',
        declare_bury='shared HeuristicBot')


def _fixed(recipe, mode):
    expected = dict(seed0=SEED0, deals=DEALS, workers=12, worlds=4, cap=4000,
                    control='mc-lcb', checkpoint_sha256=CHECKPOINT,
                    source_git_sha=SOURCE, decision_timeout_seconds=300)
    if any(recipe.get(k) != v for k, v in expected.items()):
        raise ValueError('not the frozen strength screen recipe')
    if recipe.get('policy') != policy_recipe(mode):
        raise ValueError('policy configuration drift')
    control = recipe.get('control_effective', {})
    required_control = dict(requested='mc-lcb', registry_policy='mc-s0-report-lcb',
        **{'class': 'MCS0ReportLCB'}, N_DETERMINIZATIONS=30,
        REPORT_FOLD_WORLDS=300, REPORT_RULE='lcb', REQUIRE_EXACT_WORK=True,
        rollout_policy='HeuristicBot')
    if any(control.get(k) != v for k, v in required_control.items()) or not control.get('all_uppercase_attributes'):
        raise ValueError('MC-LCB effective configuration missing or changed')
    environment = recipe.get('runtime', {}).get('environment', {})
    if environment != dict(MKL_NUM_THREADS='1', OMP_NUM_THREADS='1',
                           OPENBLAS_NUM_THREADS='1', SHENGJI_REQUIRE_VOIDS='1'):
        raise ValueError('runtime environment drift')
    for key in ('policy_value_module_sha256', 'policy_selective_mc_module_sha256',
                'policy_lookahead_module_sha256', 'harness_sha256', 'policy_module_sha256'):
        value = recipe.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('missing module identity')
    fixed = copy.deepcopy(recipe)
    fixed.pop('checkpoint', None)  # Content identity is still mandatory.
    fixed.pop('policy')
    return fixed


def compare_strength(value, selective, lookahead):
    runs = [_read(path) for path in (value, selective, lookahead)]
    fixed = [_fixed(recipe, mode) for (recipe, _), mode in zip(runs, MODES)]
    if fixed[1:] != [fixed[0], fixed[0]]:
        raise ValueError('non-policy recipe drift across arms')
    values = np.column_stack([v for _, v in runs])
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    boot = np.concatenate([
        values[rng.integers(0, DEALS, (min(128, REPLICATES-i), DEALS))].mean(axis=1)
        for i in range(0, REPLICATES, 128)])

    def result(observed, samples, primary):
        result = dict(mean=float(observed.mean()),
                      ci95=np.quantile(samples, [.025, .975]).tolist())
        if primary:
            low, high = np.quantile(samples, [.05/6, 1-.05/6]).tolist()
            result.update(ci_familywise95_bonferroni=[low, high],
                          positive_after_adjustment=low > 0)
        return result

    return dict(
        estimand='signed levels against common MC-LCB, mirrored deal means',
        scope='card play; shared heuristic declare/bury; DEV screen, not production approval',
        deals=DEALS, seed0=SEED0, checkpoint_sha256=CHECKPOINT, source_git_sha=SOURCE,
        bootstrap_replicates=REPLICATES, bootstrap_seed=BOOTSTRAP_SEED,
        primary={mode: result(values[:, i], boot[:, i], True) for i, mode in enumerate(MODES)},
        exploratory_components={MODES[i]+' minus policy-value':
            result(values[:, i]-values[:, 0], boot[:, i]-boot[:, 0], False) for i in (1, 2)},
        interpretation='Approximate percentile-bootstrap intervals; three primary comparisons adjusted. '
            'Components exploratory, not direct candidate head-to-head. No optional extension.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('value', 'selective', 'lookahead'):
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args()
    print(json.dumps(compare_strength(args.value, args.selective, args.lookahead), indent=2))

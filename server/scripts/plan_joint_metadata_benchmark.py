"""Print the held #569 actual-corpus command set; never execute or write it.

References: gen4_run1 (default), or explicit gen4_run4 soft targets. Release still requires
an exclusive Mini slot, reviewed source twins, input identity checks and
host/resource guards. This planner deliberately has no --run mode.
"""
import argparse
import difflib
import json
from pathlib import Path


CORPORA = ('runA runC runD runE runF2 runG runH runI runK runL '
           'runJS1 runJS2 runJS3 runJS4 runJS5 runJS6 runJS7 runJS8 runJS9 runJS10').split()
SOURCE_HEAD = '209b3c65d8a4245ddb9bc27d985be8c92eec871f'
INIT_SHA256 = 'a5248cc5ae97e69687910e892b1905613a1735cb47cbdc5e73a76e41d61e3f38'
NEEDLE = '"rng": rng, "window": window, "decode_workers": decode_workers,\n            "include_metadata": False,'


def retained_metadata_patch(source):
    """Fail closed on source drift; only the optimizer iterator may differ."""
    if source.count(NEEDLE) != 1:
        raise ValueError('expected exactly one reviewed optimizer metadata switch')
    changed = source.replace(NEEDLE, NEEDLE.replace('False', 'True'))
    return ''.join(difflib.unified_diff(
        source.splitlines(True), changed.splitlines(True),
        fromfile='a/server/shengji/train/train_cwv.py',
        tofile='b/server/shengji/train/train_cwv.py'))


def plan(base, omitted_source, retained_source, python, output, *, recipe='gen4-run1'):
    if recipe not in ('gen4-run1', 'gen4-run4-soft'):
        raise ValueError('unknown reference recipe')
    paths = [Path(p) for p in (base, omitted_source, retained_source, python, output)]
    if not all(p.is_absolute() for p in paths):
        raise ValueError('all paths must be absolute')
    base, omitted_source, retained_source, python, output = paths
    if omitted_source.resolve() == retained_source.resolve():
        raise ValueError('source twins must be separate worktrees')
    if output.exists():
        raise ValueError('output must be fresh; this planner never resumes/overwrites')
    common = [str(python), '-P', '-B', 'scripts/train_cwv.py', 'train']
    for corpus in CORPORA:
        common += ['--data', str(base / 'traj-out' / corpus)]
    common += ['--eval-luna', str(base / 'harvest-out/luna-rpc.private.jsonl'),
               '--arch', 'mlp', '--device', 'mps', '--aux-points', '--select-metric', 'val_ce',
               '--cache-dir', str(base / 'train-out/cwv/cache'),
               '--public-head', str(base / 'train-out/leaf/runAB-points/best.pt'),
               '--decode-workers', '6']
    for name, file in [('roomlog', 'room-log.labels.jsonl'), ('luna', 'luna-rpc.labels.private.jsonl'),
                       ('highn', 'highn.labels.jsonl'), ('pt1', 'pt1.labels.private.jsonl')]:
        common += ['--eval-holdout', f'{name}={base / "harvest-out/labels-1x" / file}']
    common += ['--seed', '1', '--aux-weight', '1.0', '--encoder-version', '2', '--epochs', '1',
               '--lr', '0.0003', '--hidden', '330', '--trunk-layers', '4', '--trunk-block', 'residual',
               '--search-head', '--search-head-weight', '1.0', '--search-mean-sidecar',
               str(base / 'train-out/cwv/sidecar-search-mean-v2'), '--policy-head', '--policy-rows',
               str(base / 'fl-pilot/policy_rows_v9'), '--policy-eval',
               str(base / 'fl-pilot/policy_rows_v3_eval'), '--policy-weight', '0.2',
               '--policy-listwise-weight', '1.0', '--policy-batch-fraction', '0.25', '--init',
               str(base / 'train-out/cwv/JS-M1-policy-w0.2-full/best.pt'), '--init-exclude-exposed']
    if recipe == 'gen4-run4-soft':
        common[common.index('--policy-rows') + 1] = str(base / 'fl-pilot/policy_rows_v10')
        common[common.index('--policy-weight') + 1] = '1.0'
        at = common.index('--init')
        common[at:at] = ['--policy-soft-targets', '--policy-soft-temperature', '1.0']
    arms = []
    for name, source, timing in [('attribution', omitted_source, True),
                                 ('metadata-retained', retained_source, False),
                                 ('metadata-omitted', omitted_source, False)]:
        env = {k: '1' for k in ('SHENGJI_FAST', 'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS',
                               'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS')}
        env['PYTHONPATH'] = str(source / 'server')
        arms.append(dict(name=name, cwd=str(source / 'server'), environment=env,
                         argv=common + (['--loader-stage-timing'] if timing else [])
                         + ['--out', str(output / name)]))
    return dict(status='HELD_NOT_ARMED', reference_recipe=recipe,
                reference_source=SOURCE_HEAD, init_sha256=INIT_SHA256,
                arms=arms, retained_source_delta='optimizer include_metadata False -> True only',
                completion='All three processes complete normally, including final candidate pass/holdouts.',
                measurement='Report setup/train/validation/final evaluation/total wall, memory, exposures, '
                            'checkpoint tensors and value/policy metrics. Timing OFF in both throughput twins. '
                            'Fixed retained-then-omitted order has cache/order confounding; no causal speedup '
                            'claim without assessing that limitation.',
                release='After reserved Mini chain; independently verify free host, inputs and source twins. '
                        'No launch, waiter edits, full-corpus hash/copy, or authority implied by this plan.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipe', choices=('gen4-run1', 'gen4-run4-soft'), default='gen4-run1')
    for key in ('base', 'omitted-source', 'retained-source', 'python', 'output'):
        parser.add_argument('--' + key, required=True)
    args = parser.parse_args()
    result = plan(args.base, args.omitted_source, args.retained_source, args.python, args.output,
                  recipe=args.recipe)
    trainer = Path(args.omitted_source) / 'server/shengji/train/train_cwv.py'
    result['retained_metadata_patch'] = retained_metadata_patch(trainer.read_text())
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

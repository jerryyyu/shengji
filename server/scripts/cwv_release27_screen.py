#!/usr/bin/env python3
"""Resumable paired research screen against the frozen release-27 policy."""
import argparse
from dataclasses import asdict
from pathlib import Path
import platform

from shengji.ai.cwv_policy import file_sha256
from shengji.train import cwv_shortlist_screen as screen
from shengji.train.cwv_release27_search import M1_SHA, PRIOR_SHA, make_release27_side
from shengji.train.cwv_shortlist import CWVShortlistConfig
from shengji.train.search_screen import (
    _publish, _run_pending, bind_output_config, execution_source_identity,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-checkpoint', required=True, type=Path)
    parser.add_argument('--prior-checkpoint', required=True, type=Path)
    parser.add_argument('--arm-checkpoint', required=True, type=Path)
    parser.add_argument('--mode', choices=('puct', 'truncated', 'policy'), required=True)
    parser.add_argument('--control', choices=('release27', 'matched-continuation'), default='release27')
    guidance = parser.add_mutually_exclusive_group()
    guidance.add_argument('--guided-tricks', type=int, default=1)
    guidance.add_argument('--full-guidance', action='store_true',
                          help='Use the policy throughout the continuation, not just its first trick')
    parser.add_argument('--full-continuation', action='store_true')
    parser.add_argument('--sweeps', type=int, default=8)
    parser.add_argument('--depth', type=int, default=8)
    parser.add_argument('--continuation-tricks', type=int, default=1)
    parser.add_argument('--seed0', type=int, required=True)
    parser.add_argument('--clusters', type=int, required=True)
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(argv)
    if min(args.clusters, args.workers, args.sweeps, args.depth) < 1:
        parser.error('counts and depth must be positive')
    if args.continuation_tricks < 0:
        parser.error('continuation-tricks must be nonnegative')
    if args.guided_tricks < 0:
        parser.error('guided-tricks must be nonnegative')
    if args.full_guidance and args.mode != 'policy':
        parser.error('full-guidance requires policy mode')
    if args.mode != 'policy' and args.control != 'release27':
        parser.error('matched-continuation requires policy mode')
    if args.mode == 'puct' and args.full_continuation:
        parser.error('PUCT does not use continuation flags')
    if file_sha256(args.baseline_checkpoint) != M1_SHA or file_sha256(args.prior_checkpoint) != PRIOR_SHA:
        parser.error('baseline/prior assets do not match frozen release27')
    recipe = dict(baseline_checkpoint=str(args.baseline_checkpoint.resolve()),
                  prior_checkpoint=str(args.prior_checkpoint.resolve()),
                  arm_checkpoint=str(args.arm_checkpoint.resolve()),
                  arm_sha256=file_sha256(args.arm_checkpoint), mode=args.mode,
                  sweeps=args.sweeps, depth=args.depth,
                  continuation_tricks=None if args.full_continuation else args.continuation_tricks,
                  guided_tricks=None if args.full_guidance else args.guided_tricks,
                  control=args.control)
    # Fail on unsupported assets/constructors before allocating pair workers.
    for side in ('baseline', 'arm'):
        make_release27_side(side=side, seed=args.seed0, **recipe)
    config = dict(schema='cwv-shortlist-config-v1', arm='learned',
        checkpoint=recipe['arm_checkpoint'], checkpoint_sha256=recipe['arm_sha256'],
        shortlist=asdict(CWVShortlistConfig(worlds=32, selection_worlds=30,
                         alternatives=4, batch_size=128, uniform=False)),
        report_worlds=300, production_multiplier=1, target_wall_multiplier=1,
        seed0=args.seed0, clusters=args.clusters, release27_search=recipe,
        baseline_asset_sha256=M1_SHA, prior_asset_sha256=PRIOR_SHA,
        decision_deadline=dict(screen.DEADLINE_RECIPE),
        source_sha256=execution_source_identity(Path(screen.__file__).resolve().parents[1]),
        runner_sha256=file_sha256(Path(__file__)),
        runtime=dict(python=platform.python_version(), platform=platform.platform()))
    with screen.screen_output_lock(args.out):
        bind_output_config(args.out, config)
        shards, pending = [], []
        for cluster in range(args.clusters):
            path = args.out / f'cluster-{cluster:05}.json'
            if path.exists():
                shards.append(screen.reopen_shard(path, config, cluster))
            else:
                pending.append(cluster)
        try:
            _run_pending(config, pending, shards, output=args.out, workers=args.workers,
                         task_fn=screen.run_cluster)
        finally:
            if shards:
                _publish(args.out / 'summary.json', screen.summary_for(
                    sorted(shards, key=lambda s: s['cluster']), config))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

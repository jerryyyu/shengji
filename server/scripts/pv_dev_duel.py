"""Run one explicit PV candidate/control DEV shard with the shared duel engine.

Both JSON env files must name their exact SHENGJI_BOT. This driver never reads
outcomes or resumes an existing output directory. Admission and seed clearance
belong to the caller; invoking this command is an experiment launch.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts import cwv_duel as duel


def register_pair(control, candidate):
    from shengji.ai.registry import REGISTRY
    from shengji.train.pv_search_policy import pv_env_recipe, pv_registry_entries

    names, factories = [], {}
    for env in (control, candidate):
        name = env.get('SHENGJI_BOT')
        recipe = pv_env_recipe(env)
        if not name or recipe is None:
            raise ValueError('each arm requires an explicit PV recipe and SHENGJI_BOT')
        entries = pv_registry_entries(**recipe)
        if name not in entries:
            raise ValueError('SHENGJI_BOT does not match the derived PV recipe')
        names.append(name)
        factories[name] = entries[name]
    if names[0] == names[1]:
        raise ValueError('candidate and control must have distinct recipe identities')
    # Construct both before publishing either factory to the shared registry.
    for factory in factories.values():
        factory(seed=0)
    REGISTRY.update(factories)
    return names[0], names[1]


def run(control, candidate, *, out, seed0, pairs, ranks, cluster0=0):
    if pairs < 1 or seed0 < 0 or cluster0 < 0:
        raise ValueError('positive pairs and nonnegative seeds/cluster offset required')
    plan = duel.rank_plan(ranks)
    if not plan:
        raise ValueError('explicit nonempty trump ranks required')
    baseline, treatment = register_pair(control, candidate)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    meta = dict(schema='pv-dev-duel-v1', control=baseline, candidate=treatment,
                control_env=control, candidate_env=candidate, seed0=seed0,
                pairs=pairs, cluster0=cluster0, ranks=plan)
    (out / 'run.json').write_text(json.dumps(meta, sort_keys=True, indent=2))
    sink = duel.ShardSink(str(out / 'rounds.jsonl'))
    # Global cluster indices preserve rank phase when a run is split into shards.
    rows = duel.play_shard('pv-dev', [('candidate', treatment)],
                           range(cluster0, cluster0 + pairs), seed0, ranks,
                           baseline, sink=sink, progress=True)
    if len(rows) != pairs * 2 or sink.written != pairs * 2:
        raise RuntimeError('incomplete shard; output preserved without DONE')
    with (out / 'DONE').open('x') as fh:
        fh.write(f'{pairs} complete pairs\n')
        fh.flush()
        os.fsync(fh.fileno())
    return meta


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control-env', required=True, type=Path)
    parser.add_argument('--candidate-env', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--seed0', required=True, type=int)
    parser.add_argument('--pairs', required=True, type=int)
    parser.add_argument('--cluster0', default=0, type=int)
    parser.add_argument('--ranks', required=True)
    args = parser.parse_args(argv)
    run(json.loads(args.control_env.read_text()), json.loads(args.candidate_env.read_text()),
        out=args.out, seed0=args.seed0, pairs=args.pairs, ranks=args.ranks,
        cluster0=args.cluster0)


if __name__ == '__main__':
    main()

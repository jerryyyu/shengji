"""Run one explicit PV candidate/control DEV shard with the shared duel engine.

Both JSON env files must name their exact SHENGJI_BOT. This driver never reads
outcomes or resumes an existing output directory. Admission and seed clearance
belong to the caller; invoking this command is an experiment launch.
"""
from __future__ import annotations

import argparse
import json
import os
import math
import statistics
import time
from collections import Counter
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


def capacity_summary(rows, play_wall_seconds):
    """Project only operational fields; never inspect utilities or winners."""
    sides = {}
    for side in ('arm', 'opp'):
        counts = Counter()
        for row in rows:
            counts.update(row[f'{side}_play_health'])
        sides[side] = dict(health=dict(counts),
                           decisions=sum(r[f'{side}_play_decisions'] for r in rows),
                           decision_seconds=sum(r[f'{side}_play_wall_secs'] for r in rows),
                           max_decision_seconds=max(r[f'{side}_play_max_secs'] for r in rows))
    return dict(schema='pv-dev-capacity-v1', rounds=len(rows),
                play_wall_seconds=play_wall_seconds, sides=sides)


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
    started = time.perf_counter()
    # Global cluster indices preserve rank phase when a run is split into shards.
    rows = duel.play_shard('pv-dev', [('candidate', treatment)],
                           range(cluster0, cluster0 + pairs), seed0, ranks,
                           baseline, sink=sink, progress=True)
    if len(rows) != pairs * 2 or sink.written != pairs * 2:
        raise RuntimeError('incomplete shard; output preserved without DONE')
    with (out / 'health.json').open('x') as fh:
        json.dump(capacity_summary(rows, time.perf_counter() - started), fh, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    with (out / 'DONE').open('x') as fh:
        fh.write(f'{pairs} complete pairs\n')
        fh.flush()
        os.fsync(fh.fileno())
    return meta


def read(out, expected):
    """Read a completed shard only after the caller's seal/ownership checks.

    ``expected`` is the pre-run metadata, not reconstructed from outcome files.
    Confidence intervals cluster by deal, never by individual seat mirror.
    """
    out = Path(out)
    if (expected.get('schema') != 'pv-dev-duel-v1'
            or expected['control'] == expected['candidate'] or not expected['ranks']):
        raise ValueError('invalid expected plan')
    if json.loads((out / 'run.json').read_text()) != expected:
        raise ValueError('run metadata differs from expected plan')
    n = expected['pairs']
    if n < 2 or (out / 'DONE').read_text() != f'{n} complete pairs\n':
        raise ValueError('requires at least two completed pairs and exact terminal marker')
    raw = (out / 'rounds.jsonl').read_bytes()
    if not raw.endswith(b'\n'):
        raise ValueError('torn completed shard')
    rows = [json.loads(line) for line in raw.splitlines()]
    start = expected['cluster0']
    wanted = {(expected['seed0'] + i, flip): expected['ranks'][i % len(expected['ranks'])]
              for i in range(start, start + n) for flip in (0, 1)}
    seen, health, scores, by_rank = set(), {'arm': Counter(), 'opp': Counter()}, {}, {}
    for row in rows:
        key = (row['seed'], row['flip'])
        if key in seen or key not in wanted or row['trump_rank'] != wanted[key]:
            raise ValueError('duplicate or unexpected seed/flip/rank')
        if (row['policy'] != expected['candidate'] or row['label'] != 'candidate'
                or row['opponent'] != expected['control']):
            raise ValueError('arm identity drift')
        seen.add(key)
        won = int(row['winner_team'] == row['flip'])
        value = (1 if won else -1) * max(1, row['level_change'])
        if (type(row['level_change']) is not int or row['level_change'] < 0
                or row['winner_team'] not in (0, 1) or row['won'] != won
                or row['level_utility'] != value):
            raise ValueError('inconsistent round score')
        scores[row['seed']] = scores.get(row['seed'], 0) + value / 2
        by_rank[row['seed']] = row['trump_rank']
        for side in health:
            counts = row[f'{side}_play_health']
            if any(type(v) is not int or v < 0 for v in counts.values()):
                raise ValueError('invalid health counter')
            decisions = counts.get('decisions', 0)
            if (decisions <= 0 or decisions != row[f'{side}_play_decisions'] or decisions != sum(
                    counts.get(k, 0) for k in ('pv_complete', 'pv_incomplete',
                                               'pv_fallback', 'non_pv_record'))):
                raise ValueError('health counters do not cover decisions')
            health[side].update(counts)
    if seen != set(wanted):
        raise ValueError('missing mirrored rounds')
    values = list(scores.values())
    mean = statistics.fmean(values)
    se = statistics.stdev(values) / math.sqrt(n)
    ci = [mean - 1.96 * se, mean + 1.96 * se]
    issues = [f'{side}:{key}={counts[key]}' for side, counts in health.items()
              for key in ('pv_incomplete', 'pv_fallback', 'non_pv_record',
                          'lead_alias_refill_abandoned') if counts.get(key, 0)]
    return dict(pairs=n, rounds=2*n, mean_levels_per_round=mean,
                ci95_normal=ci, ci95_bootstrap=list(duel.bootstrap_ci(values)),
                mde80=2.8*se, health={k: dict(v) for k, v in health.items()},
                quality_issues=issues,
                verdict=('QUALITY_FAIL' if issues else 'POSITIVE' if ci[0] > 0
                         else 'NEGATIVE' if ci[1] < 0 else 'INCONCLUSIVE'),
                by_rank={rank: dict(pairs=sum(r == rank for r in by_rank.values()),
                                    mean=statistics.fmean(scores[s] for s in scores
                                                          if by_rank[s] == rank))
                         for rank in sorted(set(by_rank.values()))})


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

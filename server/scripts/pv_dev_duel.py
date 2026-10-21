"""Run one explicit PV candidate/control DEV shard with the shared duel engine.

Both JSON env files must name their exact SHENGJI_BOT. This driver never reads
outcomes or resumes an existing output directory. Admission and seed clearance
belong to the caller; invoking this command is an experiment launch.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing
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


def run(control, candidate, *, out, seed0, pairs, ranks, cluster0=0,
        round_kind='first_round'):
    if pairs < 1 or seed0 < 0 or cluster0 < 0:
        raise ValueError('positive pairs and nonnegative seeds/cluster offset required')
    # Reject an invalid setup before creating the output directory.
    duel.validate_round_kind(round_kind, ranks)
    plan = duel.rank_plan(ranks)
    if not plan:
        raise ValueError('explicit nonempty trump ranks required')
    baseline, treatment = register_pair(control, candidate)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    meta = dict(schema='pv-dev-duel-v1', control=baseline, candidate=treatment,
                control_env=control, candidate_env=candidate, seed0=seed0,
                pairs=pairs, cluster0=cluster0, ranks=plan)
    if round_kind == 'fixed_banker':
        meta['round_kind'] = round_kind
        meta['initial_banker'] = duel.FIXED_BANKER_RULE
    (out / 'run.json').write_text(json.dumps(meta, sort_keys=True, indent=2))
    sink = duel.ShardSink(str(out / 'rounds.jsonl'))
    started = time.perf_counter()
    # Global cluster indices preserve rank phase when a run is split into shards.
    rows = duel.play_shard('pv-dev', [('candidate', treatment)],
                           range(cluster0, cluster0 + pairs), seed0, ranks,
                           baseline, sink=sink, progress=True,
                           round_kind=round_kind)
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
    return _summarize(_load_shard(out, expected), expected)


def _run_shard(payload):
    return run(**payload)


def run_shards(control, candidate, *, out, seed0, pairs, ranks, workers,
               cluster0=0, round_kind='first_round'):
    """Run disjoint contiguous shards without reading scientific outcomes.

    The caller owns host admission, process-group lifetime and the wall cap.
    No shard is retried or overwritten. A failure preserves all outputs and
    leaves the parent without DONE; the separate reader consumes successful
    shards against the independently supplied complete plan.
    """
    if (type(workers) is not int or workers < 1 or type(pairs) is not int
            or pairs < 2 * workers or type(cluster0) is not int or cluster0 < 0
            or type(seed0) is not int or seed0 < 0):
        raise ValueError('nonnegative schedule and at least two pairs per worker required')
    duel.validate_round_kind(round_kind, ranks)
    if not duel.rank_plan(ranks):
        raise ValueError('explicit nonempty trump ranks required')
    register_pair(control, candidate)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    payloads = []
    cursor = cluster0
    for index in range(workers):
        count = pairs // workers + int(index < pairs % workers)
        payloads.append(dict(control=control, candidate=candidate,
                             out=str(out / f'shard-{index:03d}'), seed0=seed0,
                             pairs=count, ranks=ranks, cluster0=cursor,
                             round_kind=round_kind))
        cursor += count
    with (out / 'shards.json').open('x') as fh:
        json.dump(payloads, fh, sort_keys=True, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    # Spawn keeps each registry and model cache local to its worker.
    with ProcessPoolExecutor(max_workers=workers,
                             mp_context=multiprocessing.get_context('spawn')) as pool:
        futures = [pool.submit(_run_shard, payload) for payload in payloads]
        metadata = [future.result() for future in futures]
    with (out / 'DONE').open('x') as fh:
        fh.write(f'{pairs} complete pairs in {workers} shards\n')
        fh.flush()
        os.fsync(fh.fileno())
    return [(payload['out'], meta) for payload, meta in zip(payloads, metadata)]


def read_shards(shards, expected):
    """Combine explicit (directory, pre-run plan) shards after seal checks.

    Shard boundaries must partition the complete plan. Statistics cluster by
    deal across the whole population, never by shard or individual mirror.
    """
    if any(type(expected.get(k)) is not int for k in ('seed0', 'cluster0', 'pairs')):
        raise ValueError('expected schedule requires integer seeds and counts')
    start = expected['cluster0']
    stop = start + expected['pairs']
    cursor, rows = start, []
    for directory, plan in sorted(shards, key=lambda item: item[1]['cluster0']):
        if any(type(plan.get(k)) is not int for k in ('cluster0', 'pairs')):
            raise ValueError('shard schedule requires integers')
        if (plan['cluster0'] != cursor or plan['pairs'] < 2
                or cursor + plan['pairs'] > stop):
            raise ValueError('shard schedules overlap or leave a gap')
        if plan != {**expected, 'cluster0': cursor, 'pairs': plan['pairs']}:
            raise ValueError('shard recipe differs from complete plan')
        records = _load_shard(directory, plan)
        wanted = {(expected['seed0'] + i, f)
                  for i in range(cursor, cursor + plan['pairs']) for f in (0, 1)}
        keys = [(r.get('seed'), r.get('flip')) for r in records]
        if len(keys) != len(wanted) or set(keys) != wanted:
            raise ValueError('shard records do not match their assigned schedule')
        rows.extend(records)
        cursor += plan['pairs']
    if cursor != stop or not rows:
        raise ValueError('shards do not cover the complete plan')
    return _summarize(rows, expected)


def _load_shard(out, expected):
    out = Path(out)
    if any(type(expected.get(k)) is not int for k in ('seed0', 'cluster0', 'pairs')):
        raise ValueError('expected schedule requires integer seeds and counts')
    expected_kind = expected.get('round_kind', 'first_round')
    duel.validate_round_kind(expected_kind, ','.join(expected.get('ranks', [])))
    if (expected_kind == 'fixed_banker'
            and expected.get('initial_banker') != duel.FIXED_BANKER_RULE):
        raise ValueError('fixed_banker header missing initial_banker rule')
    if expected_kind == 'first_round' and 'initial_banker' in expected:
        raise ValueError('first_round header cannot carry initial_banker')
    if (expected.get('schema') != 'pv-dev-duel-v1'
            or expected['control'] == expected['candidate'] or not expected['ranks']):
        raise ValueError('invalid expected plan')
    actual = json.loads((out / 'run.json').read_text())
    if (any(type(actual.get(k)) is not int for k in ('seed0', 'cluster0', 'pairs'))
            or actual != expected):
        raise ValueError('run metadata differs from expected plan')
    n = expected['pairs']
    if n < 2 or (out / 'DONE').read_text() != f'{n} complete pairs\n':
        raise ValueError('requires at least two completed pairs and exact terminal marker')
    raw = (out / 'rounds.jsonl').read_bytes()
    if not raw.endswith(b'\n'):
        raise ValueError('torn completed shard')
    return [json.loads(line) for line in raw.splitlines()]


def _summarize(rows, expected):
    n = expected['pairs']
    expected_kind = expected.get('round_kind', 'first_round')
    start = expected['cluster0']
    wanted = {(expected['seed0'] + i, flip): expected['ranks'][i % len(expected['ranks'])]
              for i in range(start, start + n) for flip in (0, 1)}
    seen, health, scores, by_rank = set(), {'arm': Counter(), 'opp': Counter()}, {}, {}
    for row in rows:
        if any(type(row.get(k)) is not int for k in (
                'seed', 'flip', 'winner_team', 'won', 'level_change', 'level_utility',
                'arm_play_decisions', 'opp_play_decisions')):
            raise ValueError('round identity, scores and decision counts require integers')
        key = (row['seed'], row['flip'])
        if key in seen or key not in wanted or row['trump_rank'] != wanted[key]:
            raise ValueError('duplicate or unexpected seed/flip/rank')
        if (row['policy'] != expected['candidate'] or row['label'] != 'candidate'
                or row['opponent'] != expected['control']):
            raise ValueError('arm identity drift')
        row_kind = row.get('round_kind', 'first_round')
        duel.validate_round_record(row)
        if row_kind != expected_kind:
            raise ValueError('round_kind metadata drift')
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
    rank_groups = {}
    for name, is_two in (('rank_2', True), ('rank_not_2', False)):
        group = [scores[s] for s in scores if (by_rank[s] == '2') == is_two]
        group_se = statistics.stdev(group) / math.sqrt(len(group)) if len(group) > 1 else None
        group_mean = statistics.fmean(group) if group else None
        rank_groups[name] = dict(
            pairs=len(group), rounds=2*len(group), mean_levels_per_round=group_mean,
            ci95_normal=([group_mean - 1.96*group_se, group_mean + 1.96*group_se]
                         if group_se is not None else None))
    return dict(pairs=n, rounds=2*n, mean_levels_per_round=mean,
                by_rank_group=rank_groups,
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
    parser.add_argument('--round-kind', choices=duel.ROUND_KINDS, default='first_round')
    parser.add_argument('--workers', type=int, help='run a bounded pool of contiguous shards')
    args = parser.parse_args(argv)
    runner = run if args.workers is None else run_shards
    extra = {} if args.workers is None else dict(workers=args.workers)
    runner(json.loads(args.control_env.read_text()), json.loads(args.candidate_env.read_text()),
        out=args.out, seed0=args.seed0, pairs=args.pairs, ranks=args.ranks,
        cluster0=args.cluster0, round_kind=args.round_kind, **extra)


if __name__ == '__main__':
    main()

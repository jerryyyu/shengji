"""In-memory matched-deal reduction; no filesystem or sealed-output access."""
import math

from shengji.oracle.screen import cluster_bootstrap
from window_plan import CLUSTERS


def paired_result(windows, records):
    """Reduce already-admitted records, keeping both seat mirrors in one cluster.

    The caller must verify source, identities, seals and reader reservation.
    Records are keyed by the exact planned window output, not discovery order.
    """
    outputs = [window['output'] for window in windows]
    if len(outputs) != 20 or len(set(outputs)) != 20 or set(records) != set(outputs):
        raise ValueError('exactly the twenty planned windows are required')
    sides = {'candidate': {}, 'comparator': {}}
    for window in windows:
        side = sides[window['side']]
        rows = records[window['output']]
        if len(rows) != CLUSTERS * 2:
            raise ValueError('incomplete mirrored window')
        seen = set()
        ranks = window['ranks'].split(',')
        for row in rows:
            cluster, mirror = row['cluster'], row['mirror']
            if (type(cluster) is not int or not 0 <= cluster < CLUSTERS
                    or type(mirror) is not int or mirror not in (0, 1)):
                raise ValueError('invalid cluster/mirror')
            key = (window['seed'] + cluster, mirror)
            if key in seen or key in side:
                raise ValueError('duplicate deal/mirror')
            seen.add(key)
            if row['seed'] != key[0] or row['trump_rank'] != ranks[cluster % len(ranks)]:
                raise ValueError('deal schedule drift')
            if window['round_kind'] == 'fixed_banker' and row['banker'] != cluster % 4:
                raise ValueError('fixed banker drift')
            utility = row['arm_utility']
            if type(utility) not in (int, float) or not math.isfinite(utility):
                raise ValueError('invalid utility')
            side[key] = (window['round_kind'], row['trump_rank'], utility)
    candidate, comparator = sides['candidate'], sides['comparator']
    if len(candidate) != 10400 or candidate.keys() != comparator.keys():
        raise ValueError('unmatched candidate/comparator deals')
    deltas = {}
    populations = {}
    for key, (kind, rank, value) in candidate.items():
        other_kind, other_rank, other_value = comparator[key]
        if (kind, rank) != (other_kind, other_rank):
            raise ValueError('paired population drift')
        deltas.setdefault(key[0], []).append((value - other_value) / 2)
        populations[key[0]] = (kind, rank)
    values = [sum(deltas[seed]) for seed in sorted(deltas)]
    splits = {}
    for label, predicate in (
            ('rank2', lambda kind, rank: rank == '2'),
            ('rank_ne2', lambda kind, rank: rank != '2'),
            ('first', lambda kind, rank: kind == 'first'),
            ('fixed_banker', lambda kind, rank: kind == 'fixed_banker')):
        selected = [sum(deltas[seed]) for seed in sorted(deltas)
                    if predicate(*populations[seed])]
        splits[label] = dict(clusters=len(selected), mean=sum(selected) / len(selected))
    return dict(schema='s58combo-paired-reduction-v1',
                candidate_minus_comparator_levels_per_round=cluster_bootstrap(
                    values, replicates=1000, seed=17),
                mirrored_rounds=len(candidate),
                descriptive_splits=splits,
                claim='paired common-control contrast; not head-to-head or deployment evidence')

"""Synthetic producer-format records only; never opens a scientific artifact."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paired_result import paired_result
from window_plan import queue_windows, CLUSTERS


def fixture(tmp_path):
    windows = queue_windows([{'name': 'a'}, {'name': 'b'}],
                            [1000 * i for i in range(10)], tmp_path)
    records = {}
    for w in windows:
        records[w['output']] = [
            dict(cluster=c, mirror=m, seed=w['seed'] + c,
                 trump_rank=w['ranks'].split(',')[c % len(w['ranks'].split(','))],
                 banker=c % 4, trump_suit='S', arm_utility=(1 if m == 0 else -1)
                 if w['side'] == 'candidate' else 0)
            for c in range(CLUSTERS) for m in (0, 1)]
    return windows, records


def test_mirrors_are_one_bootstrap_unit_and_order_does_not_matter(tmp_path):
    windows, records = fixture(tmp_path)
    for rows in records.values():
        rows.reverse()
    with pytest.raises(ValueError, match='degenerate'):
        paired_result(list(reversed(windows)), records)


def test_window_pool_matches_existing_consumer_and_preserves_heterogeneity(tmp_path):
    from shengji.eval.paired_window_stats import pool_windows

    windows, records = fixture(tmp_path)
    for index, window in enumerate(windows[:10]):
        for row in records[window['output']]:
            row['arm_utility'] = (1 if index < 5 else -1) + (row['cluster'] % 2)
    result = paired_result(windows, records)
    rows = result['windows']
    stats = result['candidate_minus_comparator_levels_per_round']
    assert stats == pool_windows([r['delta'] for r in rows], [r['se'] for r in rows])
    assert stats['tau'] > 1 and stats['ci95'][0] < 0 < stats['ci95'][1]
    assert sum(r['clusters'] for r in rows) == 5200
    for rows in records.values():
        rows.reverse()
    assert paired_result(list(reversed(windows)), records) == result
    assert result['mirrored_rounds'] == 10400
    assert result['descriptive_splits']['first']['clusters'] == 2080
    assert result['descriptive_splits']['fixed_banker']['clusters'] == 3120
    assert result['descriptive_splits']['rank2']['clusters'] == 2320
    assert result['descriptive_splits']['rank_ne2']['clusters'] == 2880


def test_contrast_sign_and_per_round_scale(tmp_path):
    windows, records = fixture(tmp_path)
    for w in windows:
        for row in records[w['output']]:
            row['arm_utility'] = 2 + row['cluster'] % 2 if w['side'] == 'candidate' else -1
    stats = paired_result(windows, records)['candidate_minus_comparator_levels_per_round']
    assert stats['mean'] == pytest.approx(3.5)
    assert 3 < stats['ci95'][0] < 3.5 < stats['ci95'][1] < 4


@pytest.mark.parametrize('defect', ['missing', 'duplicate', 'seed', 'rank', 'banker', 'suit', 'nan'])
def test_refuses_partial_or_mismatched_producer_records(tmp_path, defect):
    windows, records = fixture(tmp_path)
    rows = records[windows[1]['output']]
    if defect == 'missing':
        rows.pop()
    elif defect == 'duplicate':
        rows[1] = copy.deepcopy(rows[0])
    else:
        key, value = {'seed': ('seed', -1), 'rank': ('trump_rank', 'A'),
                      'banker': ('banker', 3), 'suit': ('trump_suit', 'H'),
                      'nan': ('arm_utility', float('nan'))}[defect]
        rows[0][key] = value
    with pytest.raises(ValueError):
        paired_result(windows, records)

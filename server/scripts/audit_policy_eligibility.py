"""Bounded record-only policy-target eligibility audit; never builds caches or scores a model."""
from __future__ import annotations

import argparse
from collections import Counter
from itertools import islice
import json
from pathlib import Path

from shengji.engine.combos import decompose
from shengji.harvest.rebuild import state_for_record
from shengji.train.data import ShardRef, iter_records
from shengji.train.served_policy_rows import classify


def audit(records, *, max_records):
    if isinstance(max_records, bool) or not isinstance(max_records, int) or max_records <= 0:
        raise ValueError('max_records must be a positive integer')
    totals, cells, errors = Counter(), Counter(), Counter()
    for rec in islice(records, max_records):
        totals['records'] += 1
        if not isinstance(rec, dict):
            raise ValueError('record must be an object')
        if rec.get('decision_kind') != 'play':
            totals['non_play_records'] += 1
            continue
        totals['play_records'] += 1
        try:
            target, reason, _, _ = classify(rec)
            eligibility = 'target:' + target if target is not None else 'excluded:' + str(reason)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
            eligibility = 'unknown:classification_error'
            errors['classify:' + type(exc).__name__] += 1
        kind = 'unknown'
        try:
            root = state_for_record(rec)
            if root.phase != 'play' or root.turn != rec['seat']:
                errors['context:turn_mismatch'] += 1
            elif root.trick.plays:
                kind = 'follow'
            else:
                action = rec['action']
                if not isinstance(action, list) or not action:
                    raise ValueError('missing played action')
                parts = decompose(action, root.ordering).components
                name = 'single' if len(action) == 1 else parts[0].kind if len(parts) == 1 else 'throw'
                if name not in ('single', 'pair', 'tractor', 'throw'):
                    raise ValueError('unknown action type')
                kind = 'lead:' + name
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, AssertionError) as exc:
            errors['context:' + type(exc).__name__] += 1
        cells[kind, eligibility] += 1
    groups = {}
    for kind in ('lead:single', 'lead:pair', 'lead:tractor', 'lead:throw', 'follow', 'unknown'):
        counts = {outcome: n for (group, outcome), n in sorted(cells.items()) if group == kind}
        n = sum(counts.values())
        excluded = sum(v for k, v in counts.items() if k.startswith('excluded:'))
        groups[kind] = dict(play_records=n, eligibility=counts,
                            excluded_fraction=excluded / n if n else None)
    assert sum(g['play_records'] for g in groups.values()) == totals['play_records']
    return dict(schema='policy-eligibility-audit-v1', totals=dict(totals), groups=groups,
                errors=dict(sorted(errors.items())), max_records=max_records,
                reached_limit=totals['records'] == max_records,
                scope='Target eligibility before encoding and seed/deal exclusions; not final cache inclusion. '
                      'Action type is the recorded attempted action. Unknown contexts remain in denominators. '
                      'A bounded prefix is descriptive, not an unbiased population estimate.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('shards', nargs='+', type=Path)
    p.add_argument('--max-records', required=True, type=int)
    a = p.parse_args()
    def records():
        for path in a.shards:
            yield from iter_records(ShardRef(path=str(path), label='', sha256='', records=None, cluster=None, store=''))
    result = audit(records(), max_records=a.max_records)
    result['inputs'] = [str(p.resolve()) for p in a.shards]
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()

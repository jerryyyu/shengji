"""Summarize explicit collector output; no sampling, policy inference or game launch.

The 15 percentage-point gap is an implementation gate, not a strength result.
External pilot rows must be reported separately from the self-play collection.
"""
import argparse
from collections import Counter
import json
import math


def summarize(rows):
    keys, risky = set(), []
    counts = Counter(leads=0, throws=0, unavailable_throws=0)
    identity = None
    for row in rows:
        key = tuple(row[k] for k in ('seed', 'game', 'round', 'trick', 'seat'))
        if key in keys:
            raise ValueError('duplicate decision')
        keys.add(key)
        current = row['collection']
        if identity is None:
            identity = current
        elif current != identity:
            raise ValueError('mixed collection identities')
        rec = row['throw_calibration']
        if rec['schema'] != 'throw-calibration-v1' or type(rec['is_throw']) is not bool:
            raise ValueError('invalid calibration record')
        if sorted(rec['attempted']) != sorted(row['attempted']):
            raise ValueError('attempted action drift')
        accepted = rec['accepted']
        if not accepted or Counter(accepted) - Counter(rec['attempted']):
            raise ValueError('invalid accepted action')
        if type(rec['succeeded']) is not bool or rec['succeeded'] != (Counter(accepted) == Counter(rec['attempted'])):
            raise ValueError('outcome inconsistency')
        counts['leads'] += 1
        if not rec['is_throw']:
            continue
        counts['throws'] += 1
        if rec['unavailable'] is not None:
            counts['unavailable_throws'] += 1
            continue
        p = rec['predicted_success']
        if type(p) not in (float, int) or not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError('invalid probability')
        if type(rec['worlds']) is not int or rec['worlds'] <= 0:
            raise ValueError('invalid world count')
        if type(rec['unseen_union_risky']) is not bool:
            raise ValueError('invalid public risk classification')
        if rec['unseen_union_risky']:
            risky.append((p, int(rec['succeeded'])))
    n = len(risky)
    predicted = sum(p for p, _ in risky) / n if n else None
    realized = sum(y for _, y in risky) / n if n else None
    gap = predicted - realized if n else None
    if counts['unavailable_throws']:
        verdict = 'INCOMPLETE'
    elif counts['throws'] < 1000 or not n:
        verdict = 'INSUFFICIENT'
    else:
        verdict = 'CALIBRATION_GAP' if gap >= 0.15 else 'BAR_NOT_MET'
    return dict(counts=dict(counts), risky_throws=n, predicted_success=predicted,
                realized_success=realized, overprediction=gap, verdict=verdict,
                claim='Calibration only; no evidence of gain from a throw guard', collection=identity)


def validated_summary(rows, journal):
    """Require the actual producer's completed journal and matching lead actions."""
    if not journal or journal[0].get('kind') != 'start' or journal[-1].get('kind') != 'terminal':
        raise ValueError('missing collection terminal')
    terminal = journal[-1]
    if terminal.get('reason') not in ('max_positions', 'max_rounds'):
        raise ValueError('collection did not complete')
    if sum(r.get('kind') == 'terminal' for r in journal) != 1:
        raise ValueError('multiple terminals')
    if terminal.get('positions') != len(rows):
        raise ValueError('collection position count drift')
    if not rows or any(r['collection'] != journal[0]['identity'] or r['seed'] != journal[0]['seed'] for r in rows):
        raise ValueError('collection binding drift')
    leads = [r for r in journal if r.get('kind') == 'decision' and r.get('lead')]
    if len(leads) < len(rows):
        raise ValueError('missing decision journal')
    for row, decision in zip(rows, leads):
        if (row['round'], row['seat'], sorted(row['attempted'])) != (
                decision['round'], decision['seat'], sorted(decision['played'])):
            raise ValueError('journal decision drift')
    result = summarize(rows)
    result['terminal'] = terminal
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('output')
    parser.add_argument('--journal', required=True, help='Collector --cost-out JSONL')
    args = parser.parse_args(argv)
    with open(args.input) as source:
        rows = [json.loads(line) for line in source if line.strip()]
    with open(args.journal) as source:
        journal = [json.loads(line) for line in source if line.strip()]
    result = validated_summary(rows, journal)
    with open(args.output, 'x') as target:
        json.dump(result, target, indent=2, allow_nan=False)
        target.write('\n')


if __name__ == '__main__':
    main()

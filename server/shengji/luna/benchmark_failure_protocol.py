"""Opt-in terminal-attempt classification, not retry or launch authority.

The caller must authenticate the frozen runner and receipt bytes. A JSON
classification cannot by itself prove that an engine rejection occurred.
Legacy failures are deliberately not inferred from exception text.
"""
from __future__ import annotations
import math
import statistics

FAIL_STOP = 'fail-stop-v1'
PRESERVE_ILLEGAL = 'preserve-model-illegal-v1'


def attempt_disposition(row: dict, *, protocol: str = FAIL_STOP) -> str:
    """Return complete, retained-model-failure, unattempted, or stop.

    A retained failure consumes its scheduled slot. It must never be passed
    to a continuation's retry branch or counted as completed gameplay.
    """
    if protocol not in (FAIL_STOP, PRESERVE_ILLEGAL):
        raise ValueError('unknown benchmark failure protocol')
    if not isinstance(row, dict):
        return 'stop'
    if row.get('complete') is True:
        return 'complete' if not row.get('error') and 'failure' not in row else 'stop'
    if row.get('complete') is not False:
        return 'stop'
    if row.get('status') == 'not_run':
        return ('unattempted' if not row.get('calls') and not row.get('events')
                and 'failure' not in row else 'stop')
    if protocol == FAIL_STOP or row.get('status') is not None:
        return 'stop'
    failure, events, flip = row.get('failure'), row.get('events'), row.get('flip')
    if (type(failure) is not dict or set(failure) != {
            'schema', 'category', 'stage', 'seat', 'attempted_cards', 'event_index'}
            or failure['schema'] != 'benchmark-action-failure-v1'
            or failure['category'] != 'model_illegal_action'
            or failure['stage'] != 'engine_play'
            or type(flip) is not int or flip not in (0, 1)
            or type(failure['seat']) is not int or failure['seat'] not in range(4)
            or failure['seat'] % 2 != flip
            or type(events) is not list or not events
            or type(failure['event_index']) is not int
            or failure['event_index'] != len(events) - 1):
        return 'stop'
    cards, event = failure['attempted_cards'], events[-1]
    if (type(cards) is not list or any(type(c) is not str for c in cards)
            or type(event) is not dict or type(event.get('seat')) is not int
            or event['seat'] != failure['seat'] or event.get('attempted_cards') != cards
            or type(row.get('error')) is not str or not row['error']):
        return 'stop'
    return 'retained-model-failure'


def summarize_scheduled(rows: list[dict], *, failure_limit: int = 8) -> dict:
    """Descriptive paired endpoints only; no imputation of unattempted slots.

    Signed levels are from the LLM partnership's perspective. The benchmark
    scale's minimum decisive margin is one level, hence model illegality=-1.
    Confidence intervals remain the owning reader's responsibility.
    """
    if type(failure_limit) is not int or failure_limit <= 0:
        raise ValueError('positive failure limit required')
    groups, seen = {}, set()
    for row in rows:
        mode, seed, flip = row.get('information'), row.get('seed'), row.get('flip')
        if (mode not in ('actor-only', 'perfect') or type(seed) is not int
                or type(flip) is not int or flip not in (0, 1)):
            raise ValueError('invalid scheduled identity')
        key = (mode, seed, flip)
        if key in seen:
            raise ValueError('duplicate scheduled mirror')
        seen.add(key)
        disposition = attempt_disposition(row, protocol=PRESERVE_ILLEGAL)
        if disposition == 'stop':
            raise ValueError('unclassified failure requires stop')
        score = None
        if disposition == 'complete':
            score = row.get('signed_levels')
            if type(score) not in (int, float) or not math.isfinite(score):
                raise ValueError('finite signed-level score required')
        group = groups.setdefault(mode, {'scheduled': 0, 'failed': 0, 'completed': 0,
                                          'unattempted': 0, 'pairs': {}})
        group['scheduled'] += 1
        group['failed'] += disposition == 'retained-model-failure'
        group['completed'] += disposition == 'complete'
        group['unattempted'] += disposition == 'unattempted'
        group['pairs'].setdefault(seed, {})[flip] = (disposition, score)
    result = {}
    for mode, group in groups.items():
        complete, forfeit = [], []
        for pair in group.pop('pairs').values():
            if set(pair) != {0, 1}:
                raise ValueError('schedule must declare both flips')
            values = [pair[flip] for flip in (0, 1)]
            if all(d == 'complete' for d, _ in values):
                complete.append(sum(s for _, s in values) / 2)
            if all(d in ('complete', 'retained-model-failure') for d, _ in values):
                forfeit.append(sum(-1 if d == 'retained-model-failure' else s
                                   for d, s in values) / 2)
        group.update(failure_rate=group['failed'] / group['scheduled'],
                     completed_pair_count=len(complete), forfeit_pair_count=len(forfeit),
                     completed_paired_mean=statistics.fmean(complete) if complete else None,
                     forfeit_paired_mean=statistics.fmean(forfeit) if forfeit else None)
        result[mode] = group
    failures = sum(g['failed'] for g in result.values())
    return {'protocol': PRESERVE_ILLEGAL, 'forfeit_signed_levels': -1,
            'failure_limit': failure_limit, 'stop_required': failures >= failure_limit,
            'failed': failures, 'scheduled': len(rows),
            'failure_rate': failures / len(rows) if rows else None, 'modes': result}

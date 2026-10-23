"""Greedy-finish receipt shapes and exact-skip activation before estimation."""
FIELDS = ('leaf_greedy_finish_applied', 'leaf_greedy_reply_plays',
          'leaf_greedy_reply_evaluations', 'leaf_greedy_reply_differs_heuristic',
          'leaf_greedy_policy_rows', 'leaf_greedy_uncached_leaves')
SKIP = 'leaf_greedy_finish_exact_skipped'


def greedy_shape(rec, enabled):
    """Return the admitted shape, rejecting incomplete or impossible counters."""
    if not isinstance(rec, dict):
        raise ValueError('greedy receipt is not an object')
    schema = rec.get('schema')
    if schema not in ('pv-search-decision-v1', 'pv-search-fallback-v1'):
        raise ValueError('unknown greedy receipt schema')
    fallback = schema == 'pv-search-fallback-v1'
    if fallback or not enabled:
        if any(key in rec for key in (*FIELDS, SKIP)):
            raise ValueError('greedy fields on disabled arm or fallback')
        if fallback and rec.get('reason') not in ('budget', 'search-error'):
            raise ValueError('unknown fallback reason')
        return 'fallback' if fallback else 'disabled'
    applied, skipped = rec.get(FIELDS[0]), rec.get(SKIP)
    counts = [rec.get(key) for key in FIELDS[1:]]
    if (type(applied) is not bool or type(skipped) is not bool
            or any(type(n) is not int or not 0 <= n <= 10**12 for n in counts)):
        raise ValueError('missing or mistyped greedy fields')
    plays, evaluations, differs, rows, uncached = counts
    exact = (rec.get('exact_lead_status') in ('skipped_budget', 'abandoned', 'complete')
             or rec.get('exact_follow_attempted') is True)
    if skipped != exact:
        raise ValueError('greedy skip disagrees with exact gate')
    if uncached or rows > plays or differs > rows or not 2 * rows <= evaluations <= 5 * rows:
        raise ValueError('inconsistent greedy work counters')
    if skipped or not applied:
        if applied or any(counts):
            raise ValueError('greedy work on skipped or unapplied decision')
        return 'skipped' if skipped else 'not_applied'
    if plays < 1:
        raise ValueError('applied finish has no reply plays')
    return 'applied'


def check_greedy(plan, shards):
    counts = {side: dict(search=0, applied=0, skipped=0) for side in ('candidate', 'comparator')}
    reasons = []
    for side in counts:
        config = plan['arms'][side]['identity']['config']
        enabled = side == 'candidate'
        if any(config.get(key) is not enabled for key in ('leaf_greedy_finish', 'leaf_greedy_finish_exact_skip')):
            reasons.append(f'{side}: frozen greedy recipe mismatch')
    for window in plan['windows']:
        side = window['side']
        for shard in shards[window['output']]:
            for trace in shard.get('decision_traces', []):
                if trace.get('side') != 'arm':
                    continue
                for rec in trace.get('decisions', []):
                    try:
                        shape = greedy_shape(rec, side == 'candidate')
                    except ValueError as exc:
                        reasons.append(f'{side}: {exc}')
                        continue
                    counts[side]['search'] += int(shape != 'fallback')
                    if shape in ('applied', 'skipped'):
                        counts[side][shape] += 1
    if any(not counts[side]['search'] for side in counts):
        reasons.append('missing search population')
    if not counts['candidate']['applied'] or not counts['candidate']['skipped']:
        reasons.append('candidate must exercise both finish and exact skip')
    return dict(verdict='SCREEN_INVALID' if reasons else 'VALID', counts=counts, reasons=reasons[:20])

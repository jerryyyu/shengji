"""Pure exact-stage validators extracted from the established v103s58 reader.

Source: ~/.claude/jobs/68f9c8bd/tmp/fl-pilot/v103s58/v103s58_reader/v103s58_reader.py
Only the observer policy name is supplied by the caller instead of a global.
No artifact reads or run authority.
"""
import collections
import math

def _nonneg_int(value):
    return type(value) is int and value >= 0

EX_EXPECT = dict(candidate=True, comparator=True)

EX_CARDS = 7

EX_LEAD_STATUSES = ('ineligible', 'single_candidate', 'skipped_budget', 'abandoned', 'complete')

EX_LEAD_BASE = ('exact_deep_cards', 'exact_lead_cache_hits', 'exact_lead_changed', 'exact_lead_nodes', 'exact_lead_status', 'exact_lead_worlds_completed')

EX_LEAD_ABANDONED = EX_LEAD_BASE + ('exact_lead_abandon_error', 'exact_lead_abandon_reason', 'exact_lead_seconds')

EX_LEAD_COMPLETE = EX_LEAD_BASE + ('exact_lead_base_level_mean', 'exact_lead_base_played', 'exact_lead_base_played__len', 'exact_lead_base_selected_index', 'exact_lead_base_value_means__len', 'exact_lead_change_kind', 'exact_lead_seconds', 'exact_lead_selected_level_delta', 'exact_lead_selected_level_mean')

EX_CHANGE_KINDS = ('unchanged', 'higher', 'tie', 'lower', 'post_selection_override')

EX_FOLLOW_COMPLETE = ('exact_follow_abandoned', 'exact_follow_applied', 'exact_follow_attempted', 'exact_follow_nodes', 'exact_follow_scores__len', 'exact_follow_worlds')

EX_FOLLOW_ABANDONED = ('exact_follow_abandoned', 'exact_follow_applied', 'exact_follow_attempted', 'exact_follow_error')

EX_REASONS = ('soft_budget', 'hard_budget', 'error')

EX_REFUSAL = dict(lead='ExactEndgameRefusal', follow='ExactFollowRefusal')

EX_TRACE_LIST_MAX = 16

EX_ABANDON_CAP = 0.02

def empty_ex():

    def stage(**extra):
        return dict(eligible=0, complete=0, soft_budget=0, hard_budget=0, refusal=0, other_error=0, nodes=0, **extra)
    return dict(policy_records=0, policy_mismatch=0, other_side_keyed=0, unlinked=0, refused_throws=0, search_records=0, valid=0, missing=0, invalid=0, lead_mismatch=0, follow_missing=0, follow_unexpected=0, context=dict(lead_eligible=0, follow_eligible=0), lead=stage(ineligible=0, single_candidate=0, skipped_budget=0, changed=0, kinds=dict.fromkeys(EX_CHANGE_KINDS, 0)), follow=stage(ineligible=0, applied=0, score_unavailable=0), by_cards=dict(lead={str(n): 0 for n in range(1, EX_CARDS + 1)}, follow={str(n): 0 for n in range(1, EX_CARDS + 1)}), lead_seconds=dict(complete=[], abandoned=[]), decision_seconds=dict(lead=[], follow=[]), errors=[])

def _ex_finite(value):
    return type(value) in (int, float) and math.isfinite(value)

def _ex_numbers(value, n):
    return isinstance(value, list) and len(value) == n and all((_ex_finite(v) for v in value))

def _ex_cards(value):
    return isinstance(value, list) and bool(value) and all((type(c) is str and c for c in value))

def ex_contexts(shard):
    (out, bad, seen) = ({}, set(), set())
    records = shard.get('records')
    for rec in records if isinstance(records, list) else ():
        mirror = rec.get('mirror') if isinstance(rec, dict) else None
        history = rec.get('committed_history') if isinstance(rec, dict) else None
        if type(mirror) is not int or mirror in seen:
            bad.add(mirror)
            continue
        seen.add(mirror)
        plays = []
        for play in history if isinstance(history, list) else ():
            if not isinstance(play, list) or len(play) != 2 or type(play[0]) is not int or (not 0 <= play[0] < 4) or (not _ex_cards(play[1])):
                plays = None
                break
            plays.append((play[0], list(play[1])))
        if not plays or len(plays) % 4:
            bad.add(mirror)
            continue
        tricks = [plays[i:i + 4] for i in range(0, len(plays), 4)]
        total = [0] * 4
        for (seat, cards) in plays:
            total[seat] += len(cards)
        if len(set(total)) != 1 or any((sorted((s for (s, _) in t)) != [0, 1, 2, 3] or len({len(c) for (_, c) in t}) != 1 for t in tricks)):
            bad.add(mirror)
            continue
        used = [0] * 4
        for (t, trick) in enumerate(tricks):
            for (i, (seat, cards)) in enumerate(trick):
                hands = [total[q] - used[q] - sum((len(c) for (s, c) in trick[:i] if s == q)) for q in range(4)]
                out[mirror, seat, t] = (i == 0, max(hands), cards)
            for (seat, cards) in trick:
                used[seat] += len(cards)
    return (out, bad)

def _ex_lead_outcome(rec, status, n):
    keys = {k for k in rec if k.startswith('exact_lead_') or k == 'exact_deep_cards'}
    if status in ('ineligible', 'single_candidate', 'skipped_budget'):
        ok = keys == set(EX_LEAD_BASE) and type(rec['exact_lead_worlds_completed']) is int and (rec['exact_lead_worlds_completed'] == 0) and (rec['exact_lead_nodes'] is None) and (rec['exact_lead_cache_hits'] is None) and (rec['exact_lead_changed'] is False)
        return (status, False, None, 0, None, None) if ok else None
    if status == 'abandoned':
        (reason, error, seconds) = (rec.get(k) for k in ('exact_lead_abandon_reason', 'exact_lead_abandon_error', 'exact_lead_seconds'))
        ok = keys == set(EX_LEAD_ABANDONED) and rec['exact_lead_worlds_completed'] is None and (rec['exact_lead_nodes'] is None) and (rec['exact_lead_cache_hits'] is None) and (rec['exact_lead_changed'] is False) and (reason in EX_REASONS) and (type(reason) is str) and (type(error) is str) and (error != '') and _ex_finite(seconds) and (seconds >= 0)
        if not ok:
            return None
        outcome = reason if reason != 'error' else 'refusal' if error == EX_REFUSAL['lead'] else 'other_error'
        return (outcome, False, None, 0, float(seconds), f'lead {reason} {error}')
    whole = 'exact_lead_base_value_means' in rec
    (kind, changed, worlds) = (rec.get('exact_lead_change_kind'), rec.get('exact_lead_changed'), rec.get('exact_lead_worlds_completed'))
    (delta, selected, based) = (rec.get(k) for k in ('exact_lead_selected_level_delta', 'exact_lead_selected_level_mean', 'exact_lead_base_level_mean'))
    (played, base_played, seconds) = (rec.get('played'), rec.get('exact_lead_base_played'), rec.get('exact_lead_seconds'))
    (index, nodes) = (rec.get('exact_lead_base_selected_index'), rec.get('exact_lead_nodes'))
    ok = keys == set(EX_LEAD_COMPLETE) | ({'exact_lead_base_value_means'} if whole else set()) and kind in EX_CHANGE_KINDS and (type(kind) is str) and (type(changed) is bool) and (changed == (kind != 'unchanged')) and (type(worlds) is int) and (worlds > 0) and (worlds == rec.get('worlds')) and (type(rec.get('worlds')) is int) and _nonneg_int(nodes) and _nonneg_int(rec.get('exact_lead_cache_hits')) and all((_ex_finite(v) for v in (delta, selected, based))) and _ex_finite(seconds) and (seconds >= 0) and _ex_cards(played) and _ex_cards(base_played) and (rec.get('exact_lead_base_played__len') == len(base_played)) and (type(rec.get('exact_lead_base_played__len')) is int) and _nonneg_int(index) and (index < n) and (rec.get('exact_lead_base_value_means__len') == n) and (type(rec.get('exact_lead_base_value_means__len')) is int) and (n <= EX_TRACE_LIST_MAX and _ex_numbers(rec['exact_lead_base_value_means'], n) if whole else n > EX_TRACE_LIST_MAX)
    if ok:
        ok = changed == (sorted(played) != sorted(base_played)) and math.isclose(delta, selected - based, rel_tol=1e-12, abs_tol=1e-12)
    if ok and kind in ('higher', 'tie', 'lower'):
        ok = delta > 0 if kind == 'higher' else delta < 0 if kind == 'lower' else delta == 0
    return ('complete', changed, kind, nodes, float(seconds), None) if ok else None

def _ex_follow_outcome(rec, n):
    keys = {k for k in rec if k.startswith('exact_follow_')}
    (attempted, applied, reason) = (rec.get(k) for k in ('exact_follow_attempted', 'exact_follow_applied', 'exact_follow_abandoned'))
    if attempted is not True or type(applied) is not bool or 'exact_follow_abandoned' not in rec:
        return None
    if reason is not None:
        error = rec.get('exact_follow_error')
        if keys != set(EX_FOLLOW_ABANDONED) or type(reason) is not str or reason not in EX_REASONS or (applied is not False) or (type(error) is not str) or (error == ''):
            return None
        outcome = reason if reason != 'error' else 'refusal' if error == EX_REFUSAL['follow'] else 'other_error'
        return (outcome, False, 0, False, f'follow {reason} {error}')
    whole = 'exact_follow_scores' in rec
    (worlds, nodes, slen) = (rec.get(k) for k in ('exact_follow_worlds', 'exact_follow_nodes', 'exact_follow_scores__len'))
    ok = keys == set(EX_FOLLOW_COMPLETE) | ({'exact_follow_scores'} if whole else set()) and type(worlds) is int and (worlds > 0) and (worlds == rec.get('worlds')) and (type(rec.get('worlds')) is int) and _nonneg_int(nodes) and (type(slen) is int) and (slen == n) and (n > 1) and (n <= EX_TRACE_LIST_MAX and _ex_numbers(rec['exact_follow_scores'], n) if whole else n > EX_TRACE_LIST_MAX)
    if ok and whole:
        (scores, indices, selected) = (rec['exact_follow_scores'], rec.get('admitted_indices'), rec.get('selected_index'))
        ok = isinstance(indices, list) and len(indices) == n and all((_nonneg_int(i) for i in indices)) and (len(set(indices)) == n) and _nonneg_int(selected) and (selected in indices)
        if ok:
            at = indices.index(selected)
            first = max(range(n), key=lambda i: (scores[i], -i))
            ok = scores[at] == max(scores) and (not applied or at == first)
    return ('complete', applied, nodes, not whole, None) if ok else None

def observe_ex(acc, shard, side, name):
    traces = shard.get('decision_traces')
    (contexts, bad) = ex_contexts(shard)
    for trace in traces if isinstance(traces, list) else ():
        if not isinstance(trace, dict) or trace.get('side') != 'arm':
            continue
        records = trace.get('decisions')
        mirror = trace.get('mirror')
        seats = {rec.get('seat') for rec in records if isinstance(rec, dict)} if isinstance(records, list) else set()
        for (index, rec) in enumerate(records if isinstance(records, list) else ()):
            if not isinstance(rec, dict):
                continue
            acc['policy_records'] += 1
            acc['policy_mismatch'] += int(rec.get('policy') != name)
            keyed = any((isinstance(k, str) and k.startswith('exact_') for k in rec))
            (seat, trick, played) = (rec.get('seat'), rec.get('trick'), rec.get('played'))
            ctx = contexts.get((mirror, seat, trick)) if type(mirror) is int and mirror not in bad and (type(seat) is int) and (type(trick) is int) and (trick == index) and (len(seats) == 1) else None
            linked = ctx is not None and _ex_cards(played)
            if linked:
                (leading, largest, cards) = ctx
                if leading:
                    linked = not collections.Counter(cards) - collections.Counter(played)
                    acc['refused_throws'] += int(linked and sorted(cards) != sorted(played))
                else:
                    linked = sorted(cards) == sorted(played)
            acc['unlinked'] += int(not linked)
            search = rec.get('schema') == 'pv-search-decision-v1'
            n = rec.get('admitted__len')
            if linked and search and _nonneg_int(n) and (n >= 1) and (largest <= EX_CARDS) and (n > 1):
                acc['context']['lead_eligible' if leading else 'follow_eligible'] += 1
            if not EX_EXPECT[side] or not search:
                acc['other_side_keyed'] += int(keyed)
                continue
            acc['search_records'] += 1
            if not linked:
                continue
            if not keyed:
                acc['missing'] += 1
                continue
            lead_keys = {k for k in rec if k.startswith('exact_lead_') or k == 'exact_deep_cards'}
            follow_keys = {k for k in rec if k.startswith('exact_follow_')}
            status = rec.get('exact_lead_status')
            if not _nonneg_int(n) or n < 1 or {k for k in rec if k.startswith('exact_')} != lead_keys | follow_keys or (type(rec.get('exact_deep_cards')) is not int) or (rec.get('exact_deep_cards') != EX_CARDS) or (type(status) is not str) or (status not in EX_LEAD_STATUSES):
                acc['invalid'] += 1
                continue
            expected = 'ineligible' if not leading or largest > EX_CARDS else 'single_candidate' if n == 1 else 'eligible'
            if not (status == expected or (expected == 'eligible' and status in ('skipped_budget', 'abandoned', 'complete'))):
                acc['lead_mismatch'] += 1
                continue
            follow_eligible = not leading and largest <= EX_CARDS and (n > 1)
            if follow_eligible and (not follow_keys):
                acc['follow_missing'] += 1
                continue
            if follow_keys and (not follow_eligible):
                acc['follow_unexpected'] += 1
                continue
            lead = _ex_lead_outcome(rec, status, n)
            follow = _ex_follow_outcome(rec, n) if follow_eligible else None
            seconds = rec.get('seconds')
            if lead is None or (follow_eligible and follow is None) or (not (_ex_finite(seconds) and seconds >= 0)):
                acc['invalid'] += 1
                continue
            acc['valid'] += 1
            (outcome, changed, kind, nodes, stage_seconds, error) = lead
            (L, X) = (acc['lead'], acc['follow'])
            if expected == 'eligible':
                L['eligible'] += 1
                acc['by_cards']['lead'][str(largest)] += 1
                acc['decision_seconds']['lead'].append(float(seconds))
            L[outcome] += 1
            L['nodes'] += nodes
            if outcome == 'complete':
                L['changed'] += int(changed)
                L['kinds'][kind] += 1
                acc['lead_seconds']['complete'].append(stage_seconds)
            elif stage_seconds is not None:
                acc['lead_seconds']['abandoned'].append(stage_seconds)
            if error is not None:
                acc['errors'].append(error)
            if follow_eligible:
                (outcome, applied, nodes, unavailable, error) = follow
                X['eligible'] += 1
                X[outcome] += 1
                X['nodes'] += nodes
                X['applied'] += int(applied)
                X['score_unavailable'] += int(unavailable)
                acc['by_cards']['follow'][str(largest)] += 1
                acc['decision_seconds']['follow'].append(float(seconds))
                if error is not None:
                    acc['errors'].append(error)
            elif not leading:
                X['ineligible'] += 1

def ex_abandons(w):
    (L, X) = (w['lead'], w['follow'])
    abandons = L['skipped_budget'] + L['soft_budget'] + L['hard_budget'] + L['other_error'] + X['soft_budget'] + X['hard_budget'] + X['other_error']
    return (abandons, L['eligible'] + X['eligible'])


def check_exact(plan, shards):
    """Apply the same D7/X7 receipt and activation gates to both arms."""
    counts = {side: empty_ex() for side in ('candidate', 'comparator')}
    reasons = []
    for window in plan['windows']:
        side = window['side']
        for shard in shards[window['output']]:
            try:
                observe_ex(counts[side], shard, side, plan['arms'][side]['name'])
            except (KeyError, TypeError, ValueError, IndexError):
                reasons.append(f'{side}: malformed exact-stage record')
    for side, tally in counts.items():
        for key in ('policy_mismatch', 'unlinked', 'other_side_keyed', 'missing', 'invalid',
                    'lead_mismatch', 'follow_missing', 'follow_unexpected'):
            if tally[key]:
                reasons.append(f'{side}: {key}={tally[key]}')
        if not (tally['valid'] > 0 and tally['valid'] == tally['search_records']
                and tally['lead']['complete'] > 0 and tally['follow']['complete'] > 0
                and tally['lead']['changed'] > 0 and tally['follow']['applied'] > 0):
            reasons.append(f'{side}: exact stages not fully witnessed')
        abandoned, eligible = ex_abandons(tally)
        if abandoned > EX_ABANDON_CAP * eligible:
            reasons.append(f'{side}: exact abandonment ceiling exceeded')
    return dict(verdict='SCREEN_INVALID' if reasons else 'VALID', reasons=reasons, counts=counts)

EX_FOLLOW_SUMMARY_KEYS = ('attempted', 'complete', 'applied', 'soft_budget', 'hard_budget', 'refusal', 'other_error', 'score_unavailable')

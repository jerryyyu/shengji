"""Symmetric play coverage, delivered-world and declaration completion checks."""
import validity


def check_decisions(plan, shards):
    arms = ('candidate', 'comparator')
    counts = {a: dict(decisions=0, play_fallback=0, search=0, belief_fallback=0) for a in arms}
    worlds, declares, reasons = [], [], []
    expected_worlds = {a: plan['arms'][a]['identity']['config']['worlds'] for a in arms}
    declare_worlds = {a: plan['arms'][a]['identity']['config']['value_declare_worlds'] for a in arms}
    for window in plan['windows']:
        arm = window['side']
        for shard in shards[window['output']]:
            expected, seen = set(), set()
            for row in shard['records']:
                history = row.get('committed_history')
                if not isinstance(history, list) or not history:
                    reasons.append(f'{arm}: missing committed history')
                    continue
                for index, play in enumerate(history):
                    if (not isinstance(play, list) or len(play) != 2 or type(play[0]) is not int
                            or not 0 <= play[0] <= 3 or not isinstance(play[1], list) or not play[1]):
                        reasons.append(f'{arm}: malformed committed play')
                        continue
                    if play[0] % 2 == row['mirror']:
                        expected.add((row['mirror'], index, play[0]))
            traces = shard.get('decision_traces')
            if not isinstance(traces, list):
                reasons.append(f'{arm}: missing decision traces')
                continue
            for trace in traces:
                if not isinstance(trace, dict) or trace.get('side') not in ('arm', 'baseline'):
                    reasons.append(f'{arm}: malformed trace')
                    continue
                if trace['side'] != 'arm':
                    continue
                decisions = trace.get('decisions')
                if not isinstance(decisions, list):
                    reasons.append(f'{arm}: missing decisions')
                    continue
                for rec in decisions:
                    if not isinstance(rec, dict):
                        reasons.append(f'{arm}: malformed decision')
                        continue
                    key = (trace.get('mirror'), rec.get('trick'), rec.get('seat'))
                    if any(type(v) is not int for v in key) or key not in expected or key in seen:
                        reasons.append(f'{arm}: duplicate or unexpected decision')
                        continue
                    seen.add(key)
                    counts[arm]['decisions'] += 1
                    schema = rec.get('schema')
                    status = {'pv-search-decision-v1': 'search', 'pv-search-fallback-v1': 'fallback'}.get(schema, 'unknown')
                    worlds.append((arm, status, rec.get('worlds')))
                    if status == 'fallback':
                        counts[arm]['play_fallback'] += 1
                    elif status == 'search':
                        counts[arm]['search'] += 1
                        fallback = rec.get('belief_fallback')
                        if type(fallback) is not int or fallback not in (0, 1):
                            reasons.append(f'{arm}: invalid belief fallback count')
                        else:
                            counts[arm]['belief_fallback'] += fallback
                declarations = trace.get('declare_decisions', [])
                if not isinstance(declarations, list):
                    reasons.append(f'{arm}: malformed declarations')
                    continue
                for rec in declarations:
                    declares.append(dict(arm=arm, evaluated=rec.get('evaluated'),
                                         worlds=rec.get('worlds'), completed=rec.get('worlds_completed'))
                                    if isinstance(rec, dict) else rec)
            if seen != expected or not expected:
                reasons.append(f'{arm}: incomplete play coverage')
    ceilings = dict(play_fallback=0, belief_fallback=.01, bury_fallback=None, declare_abandon=None)
    checks = [dict(check='committed_play_coverage', verdict='SCREEN_INVALID' if reasons else 'VALID', reasons=reasons[:20]),
              validity.arm_fault_ceilings(counts, ceilings, arms=arms, tier='SCREEN'),
              validity.worlds_delivered(worlds, expected_worlds, tier='SCREEN'),
              validity.completion_shape(declares, expected_worlds_by_arm=declare_worlds, tier='SCREEN')]
    return dict(validity.combine(checks, tier='SCREEN'), counts=counts, ceilings=ceilings)

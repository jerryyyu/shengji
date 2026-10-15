"""Pure descriptive consumer for a sealed latency packet's measurement rows.

The caller owns seals, provenance, exclusive read access and host calibration.
This helper reads no files and issues no qualification or strength verdict.
"""
import math
from collections import Counter


def summarize(rows, roots, *, arm, pass_label):
    """Require one successful transaction per captured root, without filtering.

    Optional-stage abandonment is NOT a failed server transaction: those rows
    stay in every wall-time statistic and their statuses are reported separately.
    """
    def need(ok, why):
        if not ok:
            raise ValueError(why)

    need(arm in ('r45', 'dx') and isinstance(pass_label, str) and pass_label, 'invalid arm/pass')
    expected = {}
    for root in roots:
        index = root.get('root_index')
        need(type(index) is int and index >= 0 and index not in expected, 'invalid/duplicate root')
        need(type(root.get('lead')) is bool, 'invalid root lead')
        need(type(root.get('max_hand')) is int and 1 <= root['max_hand'] <= 6, 'invalid root size')
        need(type(root.get('hand_size')) is int and 1 <= root['hand_size'] <= root['max_hand'], 'invalid acting hand')
        expected[index] = root
    need(bool(expected), 'empty root population')
    groups = {'lead': [], 'follow': []}
    seen = set()
    for row in rows:
        index = row.get('root_index')
        need(type(index) is int and index in expected and index not in seen, 'unknown/duplicate measured root')
        seen.add(index)
        root = expected[index]
        need(row.get('arm') == arm and row.get('pass_label') == pass_label, 'arm/pass drift')
        if arm == 'r45':
            need(not any(key.startswith('exact_') for key in row), 'baseline carries exact-stage telemetry')
        need(row.get('committed_once') is True, 'server transaction did not commit')
        for key in ('lead', 'max_hand', 'hand_size', 'trick', 'deal_seed'):
            need(key in root and type(row.get(key)) is type(root[key]) and row[key] == root[key], 'root context drift: ' + key)
        need(row.get('captured_lead') is root['lead'], 'captured lead drift')
        for key in ('wall_step_seconds', 'wall_commit_seconds', 'wall_total_seconds', 'compute_seconds'):
            value = row.get(key)
            need(type(value) in (int, float) and math.isfinite(value) and value >= 0, 'invalid timing: ' + key)
        need(math.isclose(row['wall_total_seconds'], row['wall_step_seconds'] + row['wall_commit_seconds'],
                          rel_tol=1e-9, abs_tol=1e-9), 'wall accounting drift')
        need(isinstance(row.get('schema'), str) and row['schema'], 'missing decision schema')
        groups['lead' if root['lead'] else 'follow'].append(row)
    need(seen == set(expected), 'incomplete measured population')
    result = {}
    for kind, group in groups.items():
        walls = sorted(row['wall_total_seconds'] for row in group)
        counts = Counter()
        for row in group:
            if kind == 'lead':
                status = row.get('exact_lead_status', 'not_recorded')
            elif row.get('exact_follow_attempted') is True:
                status = row.get('exact_follow_abandoned') or 'complete'
            else:
                status = 'not_attempted'
            need(isinstance(status, str), 'invalid stage status')
            counts[status] += 1
        result[kind] = dict(count=len(group),
                           p50_seconds=walls[math.ceil(.5 * len(walls)) - 1] if walls else None,
                           p90_seconds=walls[math.ceil(.9 * len(walls)) - 1] if walls else None,
                           max_seconds=max(walls) if walls else None,
                           whole_turn_over_3s=sum(t > 3 for t in walls),
                           stage_statuses=dict(sorted(counts.items())),
                           decision_schemas=dict(sorted(Counter(r['schema'] for r in group).items())))
    return dict(arm=arm, pass_label=pass_label, roots=len(expected), by_turn=result,
                scope='Whole-turn wall on this host; includes optional-stage abandonments. '
                      'Not a Fly qualification, stage-success rate, or strength result.')

"""Bind a saved first-divergence locator to two supplied mirror records."""
from collections import Counter
from replay import replay_root


def bind_locator(locator, rows):
    """Reconstruct the common root, retaining both attempted and accepted actions."""
    if len(rows) != 2 or {row.get('mirror') for row in rows} != {0, 1}:
        raise ValueError('both distinct seat mirrors required')
    rows = sorted(rows, key=lambda row: row['mirror'])
    index = locator.get('index')
    if type(index) is not int or index < 0 or locator.get('phase') != 'P':
        raise ValueError('a play-decision locator is required')
    for row in rows:
        if (row.get('seed') != locator['seed'] or row.get('round_kind') != locator['kind']
                or row.get('trump_rank') != locator['rank'] or index >= len(row['dtrace'])):
            raise ValueError('locator and row identity drift')
    t0, t1 = (row['dtrace'] for row in rows)
    if t0[:index] != t1[:index] or t0[index][:5] != t1[index][:5] or t0[index] == t1[index]:
        raise ValueError('locator is not the first action-only divergence')
    expected = ['P', locator['seat'], locator['trick'], locator['lead'], locator['hand']]
    if t0[index][:5] != expected:
        raise ValueError('locator context drift')
    actor_mirror = locator['seat'] % 2
    for mirror, name in ((actor_mirror, 'exploiter_action'), (1 - actor_mirror, 'release46_action')):
        if Counter(rows[mirror]['dtrace'][index][5]) != Counter(locator[name]):
            raise ValueError('locator policy-action label drift')
    play_index = sum(entry[0] == 'P' for entry in t0[:index])
    roots, witnesses = zip(*(replay_root(row, play_index) for row in rows))
    for key in ('hands', 'buried', 'banker', 'trump_rank', 'trump_suit', 'trump_is_nt',
                'turn', 'phase', 'history', 'attacker_points', 'notice'):
        if getattr(roots[0], key) != getattr(roots[1], key):
            raise ValueError('reconstructed mirrors do not share one root')
    return roots[0], dict(seed=locator['seed'], trace_index=index, play_index=play_index,
        release46=witnesses[1 - actor_mirror], exploiter=witnesses[actor_mirror])

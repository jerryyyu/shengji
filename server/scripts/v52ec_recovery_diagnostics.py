"""Direction-suppressed S8 recovery diagnostics; no file access or estimator.

Inputs are validated mirror-summed utilities and the pinned primary's SE.
This module alone is NOT a qualified reader or authority to reread the lane.
"""
import math
import re


def trace_fingerprint(shard, *, coverage):
    """Internal in-memory comparison data, never a published result.

    Caller supplies the pinned play-call coverage audit for this same shard.
    Identity is (seed, cluster, mirror). Attempts compare card multisets at
    (side, seat, trick); container order is irrelevant, but each seat's calls
    must be in increasing trick order. This is NOT a committed transcript or
    an assertion about chronological turn order between seats.
    """
    seed, cluster = shard.get('seed'), shard.get('cluster')
    if type(seed) is not int or type(cluster) is not int:
        raise ValueError('invalid trace identity')
    records = shard.get('records')
    if (not isinstance(records, list) or len(records) != 2
            or any(not isinstance(r, dict) for r in records)
            or any(type(r.get('mirror')) is not int for r in records)
            or [r['mirror'] for r in records] != [0, 1]):
        raise ValueError('invalid mirrored trace records')
    out = {}
    for mirror, record in enumerate(records):
        if (type(record.get('seed')) is not int or record['seed'] != seed
                or type(record.get('cluster')) is not int or record['cluster'] != cluster):
            raise ValueError('trace record identity mismatch')
        plays, history = record.get('plays'), record.get('history_sha256_16')
        if (type(plays) is not int or not 4 <= plays <= 100 or plays % 4
                or not isinstance(history, str) or not re.fullmatch('[0-9a-f]{16}', history)):
            raise ValueError('invalid history digest or play count')
        attempts = {}
        valid = coverage.get('covered') is True
        traces = shard.get('decision_traces')
        if not isinstance(traces, list):
            valid = False
            traces = []
        selected = [t for t in traces if isinstance(t, dict) and t.get('mirror') == mirror]
        if len(selected) != 4:
            valid = False
        containers = set()
        for trace in selected:
            side, decisions = trace.get('side'), trace.get('decisions')
            if side not in ('arm', 'baseline') or not isinstance(decisions, list) or not decisions:
                valid = False
                continue
            expected_seats = {mirror, mirror + 2} if side == 'arm' else {1 - mirror, 3 - mirror}
            last_trick, container_seat = -1, None
            for d in decisions:
                if not isinstance(d, dict):
                    valid = False
                    continue
                seat, trick, cards = d.get('seat'), d.get('trick'), d.get('played')
                if (type(seat) is not int or seat not in expected_seats
                        or type(trick) is not int or not 0 <= trick < plays // 4
                        or trick <= last_trick
                        or not isinstance(cards, list) or not 1 <= len(cards) <= 25
                        or any(not isinstance(c, str) or not re.fullmatch(
                            r'(?:[SHDC](?:[2-9]|10|J|Q|K|A)|LJ|BJ)', c) for c in cards)
                        or any(cards.count(c) > 2 for c in cards)):
                    valid = False
                    continue
                if container_seat is not None and container_seat != seat:
                    valid = False
                container_seat, last_trick = seat, trick
                key = (side, seat, trick)
                if key in attempts:
                    valid = False
                attempts[key] = tuple(sorted(cards))
            if container_seat is None or (side, container_seat) in containers:
                valid = False
            containers.add((side, container_seat))
        expected = {(('arm' if seat % 2 == mirror else 'baseline'), seat, trick)
                    for seat in range(4) for trick in range(plays // 4)}
        valid = valid and set(attempts) == expected
        out[(seed, cluster, mirror)] = {
            'history': (plays, history),
            'attempts': tuple(sorted(attempts.items())) if valid else None,
        }
    return out


def trace_agreement(candidate, comparator):
    """Publish counts only; missing attempts stay unavailable, never unequal."""
    if not candidate or set(candidate) != set(comparator):
        raise ValueError('unpaired trace population')
    equal_hash, comparable, equal_attempt = 0, 0, 0
    for key in candidate:
        a, b = candidate[key], comparator[key]
        equal_hash += a['history'] == b['history']
        if a['attempts'] is not None and b['attempts'] is not None:
            comparable += 1
            equal_attempt += a['attempts'] == b['attempts']
    return {
        'history_digest_agreement': {
            'label': 'HASH AGREEMENT ONLY', 'matched_mirrors': len(candidate),
            'agreeing_play_count_and_digest': equal_hash,
        },
        'attempt_trace_equality': {
            'label': 'ATTEMPTED CARD MULTISETS BY SIDE/SEAT/TRICK ONLY',
            'matched_mirrors': len(candidate), 'comparable_mirrors': comparable,
            'unavailable_mirrors': len(candidate) - comparable,
            'equal_mirrors': equal_attempt if comparable else None,
        },
    }


def numeric_diagnostics(candidate, comparator, *, bootstrap_se, clusters=520):
    """Return only r5's counts/flags, never outcomes or their direction.

    A nonfinite population leaves outcome-dependent counts undefined rather
    than accidentally counting NaN != 0 as an observed nonzero difference.
    SE zero is observed from the pinned bootstrap, not inferred from a tie.
    Structural failures use fixed messages without interpolating utilities.
    """
    if type(clusters) is not int or clusters < 2:
        raise ValueError('invalid expected population')
    if set(candidate) != set(comparator) or len(candidate) != clusters:
        raise ValueError('paired population mismatch')
    values = list(candidate.values()) + list(comparator.values())
    if any(type(v) not in (int, float) for v in values):
        raise ValueError('invalid utility type')
    if type(bootstrap_se) not in (int, float):
        raise ValueError('invalid bootstrap SE type')
    finite = {
        'candidate': all(math.isfinite(v) for v in candidate.values()),
        'comparator': all(math.isfinite(v) for v in comparator.values()),
    }
    deltas = [(candidate[k] - comparator[k]) / 2 for k in candidate]
    finite_deltas = all(math.isfinite(d) for d in deltas)
    finite_se = math.isfinite(bootstrap_se)
    observed = all(finite.values()) and finite_deltas
    return {
        'cluster_count': {'candidate': len(candidate), 'comparator': len(comparator)},
        'all_finite': finite,
        'paired_deltas_finite': finite_deltas,
        'bootstrap_se_finite': finite_se,
        'bootstrap_se_nonnegative': bootstrap_se >= 0 if finite_se else None,
        'n_nonzero_delta': sum(d != 0 for d in deltas) if observed else None,
        'se_zero': bootstrap_se == 0 if finite_se else None,
        'constant_nonzero': (
            deltas[0] != 0 and all(d == deltas[0] for d in deltas)
        ) if observed else None,
        'exact_committed_play_equality': {
            'status': 'UNIDENTIFIABLE', 'count': None,
            'reason': 'Only attempted-action traces and a 64-bit history digest persist; '
                      'the committed transcript is absent.',
        },
    }

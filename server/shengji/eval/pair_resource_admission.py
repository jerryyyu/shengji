"""Offline pair-resource admission hypothesis, NOT a served policy.

Consume a caller-supplied legal action pool and fixed policy ranking. No model,
sampling, replay, value labels or default-policy mutation. This partitions the
existing diversity tests by what happens to pairs in the actor's own hand;
it does not rank preservation above spending, nor model tractor sequences or
singleton trump control.
"""
from collections import Counter

from ..train.policy_value_search import structure_key, _near_duplicate


def _pair_inputs(rnd, seat, actions, ranked, anchor_index, k, max_per_structure):
    n = len(actions)
    if (not n or type(seat) is not int or not 0 <= seat < 4
            or type(k) is not int or k < 1
            or type(max_per_structure) is not int or max_per_structure < 1
            or type(anchor_index) is not int or not 0 <= anchor_index < n
            or len(ranked) != n or any(type(i) is not int for i in ranked)
            or set(ranked) != set(range(n))):
        raise ValueError('invalid fixed admission inputs')
    hand = Counter(rnd.hands[seat])
    pairs = sorted(c for c, count in hand.items() if count == 2)
    counts, signatures = [], []
    for action in actions:
        used = Counter(action)
        if not used or any(count > hand[c] for c, count in used.items()):
            raise ValueError('action must be a nonempty subset of actor hand')
        counts.append(used)
        signatures.append(tuple(2 - used[c] for c in pairs))
    return counts, signatures


def pair_resource_ballot(rnd, seat, actions, ranked, anchor_index, *, k=8,
                         max_per_structure=2):
    """Return indices using a fixed anchor, ranked greedy pass and ranked backfill.

    Each exact card pair initially held has state 0 (both spent), 1 (split),
    or 2 (both retained) after the proposed action. Structure caps and overlap
    suppression compare only within equal pair-state signatures. Rejected
    candidates still backfill in policy-rank order when needed, just as before.
    No pairs means precisely the existing diversity algorithm.
    """
    counts, signatures = _pair_inputs(
        rnd, seat, actions, ranked, anchor_index, k, max_per_structure
    )
    chosen = [anchor_index]
    capped = Counter([(structure_key(rnd, actions[anchor_index]), signatures[anchor_index])])
    accepted = {signatures[anchor_index]: [(len(actions[anchor_index]), counts[anchor_index])]}
    skipped = []
    for i in ranked:
        if len(chosen) >= k:
            break
        if i == anchor_index:
            continue
        signature = signatures[i]
        bucket = (structure_key(rnd, actions[i]), signature)
        peers = accepted.get(signature, [])
        if (capped[bucket] >= max_per_structure
                or _near_duplicate(counts[i], len(actions[i]), peers)):
            skipped.append(i)
            continue
        chosen.append(i)
        capped[bucket] += 1
        accepted.setdefault(signature, []).append((len(actions[i]), counts[i]))
    backfill = skipped[:max(0, k - len(chosen))]
    chosen.extend(backfill)
    return {'chosen': chosen, 'skipped': skipped[len(backfill):]}


def pair_resource_rank_repair(rnd, seat, actions, ranked, baseline):
    """Offline single-swap hypothesis; caller supplies the legacy ballot.

    Keep its anchor and size, and every covered played shape AND exact pair
    state. Consider excluded actions in supplied policy order; replace the
    worst-ranked removable non-anchor only with a better-ranked action that
    overlaps a retained action using different pair resources. Do not introduce
    same-resource overlap. Stop after one swap, returning its explicit indices.

    This does NOT preserve shape multiplicities, every action, tractor/control
    value, or utility. It cannot assert why the original selector omitted an
    action; it only tests a bounded alternative to global filter relaxation.
    """
    if (not baseline or any(type(i) is not int for i in baseline)
            or len(set(baseline)) != len(baseline)
            or any(not 0 <= i < len(actions) for i in baseline)):
        raise ValueError('invalid baseline ballot')
    counts, signatures = _pair_inputs(
        rnd, seat, actions, ranked, baseline[0], len(baseline), 1
    )
    shapes = {}

    def shape(i):
        if i not in shapes:
            shapes[i] = structure_key(rnd, actions[i])
        return shapes[i]

    chosen = list(baseline)
    covered_shapes = {shape(i) for i in chosen}
    covered_resources = {signatures[i] for i in chosen}
    rank = {i: position for position, i in enumerate(ranked)}
    for candidate in ranked:
        if candidate in chosen:
            continue
        for removed in sorted(chosen[1:], key=rank.get, reverse=True):
            if rank[candidate] >= rank[removed]:
                continue
            retained = [i for i in chosen if i != removed]
            overlaps = [i for i in retained if _near_duplicate(
                counts[candidate], len(actions[candidate]),
                [(len(actions[i]), counts[i])]
            )]
            if not overlaps or any(signatures[i] == signatures[candidate] for i in overlaps):
                continue
            if not covered_shapes <= {shape(i) for i in retained} | {shape(candidate)}:
                continue
            if not covered_resources <= {signatures[i] for i in retained} | {signatures[candidate]}:
                continue
            chosen[chosen.index(removed)] = candidate
            return {'chosen': chosen, 'swap': {'removed': removed, 'added': candidate}}
    return {'chosen': chosen, 'swap': None}

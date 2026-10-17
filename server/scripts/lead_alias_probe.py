"""Offline ballot-refill probe; never installed in the serving policy.

Aliases here mean identical executed leads in every supplied world, not equal
average values. They do not imply equal public information after a failed
throw, nor equivalence under an arbitrary continuation policy.
"""

from shengji.harvest.legal import resolve_lead


def refill_lead_aliases(rnd, seat, admitted, ranked_actions, worlds):
    """Keep first representatives, refill in policy order, preserve ballot size.

    Callers supply the original sampled worlds and the already-ranked legal
    listing. If too few distinct signatures exist, retained duplicate actions
    fill the remaining slots. The first admitted action is never removed.
    """
    if rnd.trick is None or rnd.trick.plays or rnd.turn != seat:
        raise ValueError("alias refill requires the acting seat at a lead")
    if not worlds or not admitted:
        raise ValueError("alias refill requires worlds and an admitted ballot")
    if len(ranked_actions) > 4000 or len(admitted) > 512 or len(worlds) > 512:
        raise ValueError("offline probe input exceeds its bounded ballot/world cap")
    actor = sorted(rnd.hands[seat])
    if any(sorted(hands[seat]) != actor for hands, _ in worlds):
        raise ValueError("sampled worlds must preserve the actor hand")
    keys = [tuple(sorted(action)) for action in admitted]
    if len(set(keys)) != len(keys):
        raise ValueError("admitted actions must be distinct multisets")
    cache = {}

    def signature(action):
        key = tuple(sorted(action))
        if key not in cache:
            cache[key] = tuple(
                tuple(sorted(resolve_lead(rnd, seat, action, hands)[0]))
                for hands, _ in worlds
            )
        return cache[key]

    retained, duplicates, seen = [], [], set()
    for action in admitted:
        sig = signature(action)
        if sig in seen:
            duplicates.append(list(action))
        else:
            retained.append(list(action))
            seen.add(sig)
    alias_count = len(duplicates)
    for action in ranked_actions:
        if len(retained) == len(admitted):
            break
        sig = signature(action)
        if sig not in seen:
            retained.append(list(action))
            seen.add(sig)
    replacements = len(retained) - (len(admitted) - alias_count)
    retained.extend(duplicates[:len(admitted) - len(retained)])
    return {"admitted": retained, "alias_slots": alias_count,
            "replacement_slots": replacements, "examined_actions": len(cache)}


def score_refill(bot, rnd, seat, admitted, ranked_actions, worlds):
    """Score both ballots through the real leaf/value consumer on fixed worlds.

    The maximum-mean delta is evaluator-relative, not a selected-move or
    strength result. In particular, this does not apply downstream reselect
    rules, exact search, or hidden-information continuation penalties.
    """
    result = refill_lead_aliases(rnd, seat, admitted, ranked_actions, worlds)
    before, _ = bot._value_means(rnd, seat, admitted, worlds)
    after, _ = bot._value_means(rnd, seat, result["admitted"], worlds)
    return {**result, "original_means": before.tolist(),
            "refilled_means": after.tolist(),
            "max_mean_delta": float(max(after) - max(before))}

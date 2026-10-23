"""Bounded paired continuations over explicitly supplied worlds; no artifact IO."""
from copy import deepcopy
import math
import random

from replay import branch_action


def _public_root(rnd):
    return (rnd.phase, rnd.turn, rnd.banker, rnd.trump_rank, rnd.trump_suit,
            rnd.trump_is_nt, rnd.attacker_points, rnd.kitty_bonus, rnd.declaration,
            rnd.notice, tuple(map(len, rnd.hands)), tuple(sorted(rnd.hands[rnd.turn])),
            tuple(tuple((p.seat, tuple(sorted(p.cards))) for p in trick.plays)
                  for trick in rnd.history))


def compare_continuations(worlds, weights, actions, *, tricks, reply_factory, evaluate,
                          seed, reply_identity, evaluator_identity, served_ballot):
    """Compare actions with shared world weights and independently seeded replies.

    Reply callbacks return cards and an explicit fallback boolean. Endpoint
    values are supplied by a separate evaluator in the root mover's team frame.
    This diagnostic does not establish optimality or authorize a run.
    """
    if type(tricks) is not int or tricks not in (2, 3):
        raise ValueError('two or three completed tricks required')
    if not 1 <= len(worlds) <= 64 or len(weights) != len(worlds):
        raise ValueError('invalid world inventory')
    if (any(type(w) not in (int, float) or not math.isfinite(w) or w < 0 for w in weights)
            or not math.isclose(sum(weights), 1., rel_tol=0, abs_tol=1e-12)):
        raise ValueError('weights must be finite, nonnegative and sum to one')
    if not 2 <= len(actions) <= 8 or type(seed) is not int:
        raise ValueError('invalid action inventory or seed')
    if not reply_identity or not evaluator_identity:
        raise ValueError('reply and endpoint evaluator identities required')
    keys = [tuple(sorted(cards)) for cards in actions]
    if len(set(keys)) != len(keys) or any(not cards for cards in actions):
        raise ValueError('empty or duplicate action')
    ballot_keys = {tuple(sorted(cards)) for cards in served_ballot}
    if not ballot_keys or any(not cards for cards in served_ballot):
        raise ValueError('served ballot witness required')
    first = worlds[0]
    for world in worlds:
        if (world.phase != 'play' or world.trick is None or world.trick.plays
                or max(map(len, world.hands)) <= 7 or _public_root(world) != _public_root(first)):
            raise ValueError('worlds must share one public lead root above exact coverage')
    team = first.turn % 2
    reports = []
    for action in actions:
        values, witnesses = [], []
        for index, world in enumerate(worlds):
            start = len(world.history)
            state, initial = branch_action(world, action)
            policy = reply_factory(random.Random(seed + index))
            replies = []
            while state.phase == 'play' and len(state.history) - start < tricks:
                if len(replies) >= 4 * tricks - 1:
                    raise ValueError('continuation failed to complete within play cap')
                record = policy(deepcopy(state), state.turn)
                if (not isinstance(record, dict) or type(record.get('fallback')) is not bool
                        or record['fallback'] or not isinstance(record.get('cards'), list)):
                    raise ValueError('missing reply evidence or fallback')
                state, accepted = branch_action(state, record['cards'])
                replies.append(accepted)
            completed = len(state.history) - start
            if completed < tricks and state.phase == 'play':
                raise ValueError('incomplete continuation')
            value = evaluate(deepcopy(state), team)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError('invalid endpoint value')
            values.append(value)
            witnesses.append(dict(initial=initial, replies=replies, completed_tricks=completed,
                                  terminal=state.phase != 'play', endpoint_value=value))
        reports.append(dict(attempted=list(action), in_served_ballot=tuple(sorted(action)) in ballot_keys,
                            worlds=witnesses,
                            weighted_value=sum(w * value for w, value in zip(weights, values))))
    baseline = reports[0]['weighted_value']
    for report in reports:
        report['delta_from_first'] = report['weighted_value'] - baseline
    return dict(schema='s61-paired-continuation-v1', tricks=tricks, weights=list(weights),
                seed=seed, perspective_team=team, reply_identity=reply_identity,
                evaluator_identity=evaluator_identity, actions=reports,
                claim='diagnostic endpoint contrast, not gameplay strength or optimality')

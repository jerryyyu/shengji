"""One offline reply ply with an actor-conditioned belief and stochastic policy."""
from collections import Counter
from itertools import chain, islice

import numpy as np

from ..ai.belief_numpy import decision_inputs
from ..ai.cwv_policy import afterstate
from ..ai.refusal import observe_refusal, on_record
from ..ai.heuristic import HeuristicBot
from ..engine.legal import beats, validate_follow
from ..engine.round import actual_play_after
from ..harvest.legal import iter_follow_actions
from ..rl.value_afterstate import terminal_distribution
from .belief_tree_teacher import draw_depth_worlds, paired_reply_values
from .belief_tree_transition import lead_refusal_after
from .cwv_data import LEVEL_SUPPORT
from .cwv_prior_admission import root_clone
from .pv_tree_search import single_component_leads
from .unified_slots import LeafFrame, _preferences, leaf_features_batch, policy_from_states


def _softmax(logits):
    weights = np.exp(logits - logits.max(axis=-1, keepdims=True))
    return weights / weights.sum(axis=-1, keepdims=True)


def unified_trick_frame(root, ledger, model):
    """Return the acting seat's card states and a value scorer for this trick."""
    actor = root.turn
    inp = decision_inputs(root, actor, ledger)
    q, g = model.card_states(inp, model.trunk.encode_history(inp))
    frame = LeafFrame.at_states(None, root, actor, model, q, g)

    def score(leaves, seat):
        indices, planes, scalars = leaf_features_batch(frame, leaves)
        values = np.empty(len(leaves))
        if indices:
            sign = 1 if (seat - actor) % 2 == 0 else -1
            values[indices] = sign * (model.leaf_value_probs(frame.cache(model), planes, scalars)
                                      @ LEVEL_SUPPORT)
        terminal = [i for i, leaf in enumerate(leaves) if leaf.phase == "round_end"]
        if len(indices) + len(terminal) != len(leaves):
            raise ValueError("leaf outside the unified trick value frame")
        for i in terminal:
            values[i] = terminal_distribution(leaves[i], seat) @ LEVEL_SUPPORT
        return values

    return q, score


def _reply_node(child, ledger, model, replies):
    q, score = unified_trick_frame(child, ledger, model)
    return _preferences(policy_from_states(model, q), replies), score


def _bounded_replies(child, cap, cover_winning_follow):
    hand = child.hands[child.turn]
    if not child.trick.plays:
        return [list(cards) for cards in islice(single_component_leads(hand, child.ordering), cap)]
    lead = child.trick.plays[0].cards
    replies = [list(cards) for cards in islice(iter_follow_actions(hand, lead, child.ordering), cap)]
    if cover_winning_follow and len(replies) == cap:
        bot = HeuristicBot()
        _, suit, top = bot._current_winner(child)
        if not any(beats(cards, lead, suit, top, child.ordering)[0] for cards in replies):
            winner = bot._cheapest_winning(sorted(hand), lead, suit, top, child.ordering)
            if winner is not None:
                validate_follow(winner, hand, lead, child.ordering)
                replies[-1] = sorted(winner)
    return replies


def root_reply_backup(root, actions, root_worlds, *, belief, model, refusals, seed, depth_worlds,
                      reply_cap, batch_size, reply_value_weight, cover_winning_follow=False):
    """Expected root-team values, indexed by supplied outer world and root action.

    Each reply distribution starts with the unified policy prior from the acting
    seat's information. Tilt it by exp(weight * expected acting-team value), with the
    weight in inverse value units. Zero weight evaluates the prior alone. Sum over
    the stochastic replies exactly on the original outer deal to preserve the
    root's known cards. The caller supplies the same root worlds as flat search.
    Each column names the attempted play, including throws the engine reduces
    in some worlds. Replies see that world's accepted cards and public notice.
    """
    if (root.phase != "play" or not actions or not root_worlds or seed < 0 or depth_worlds < 1
            or reply_cap < 1 or batch_size < 1 or not np.isfinite(reply_value_weight) or reply_value_weight < 0):
        raise ValueError("expected a play root, actions, worlds and valid backup settings")
    if any(not a for a in actions) or len({tuple(sorted(a)) for a in actions}) != len(actions):
        raise ValueError("empty or duplicate root action")
    seat = root.turn
    if root.trick.plays:
        for action in actions:
            validate_follow(action, root.hands[seat], root.trick.plays[0].cards, root.ordering)
    ledger = tuple(refusals)
    notice = observe_refusal(root)
    if (len(set(ledger)) != len(ledger) or any(r.trick_index < 0 or not on_record(root, r) for r in ledger)
            or (notice is not None and notice not in ledger)):
        raise ValueError("root refusal ledger disagrees with public record")
    result = np.empty((len(root_worlds), len(actions)))
    sizes = [len(hand) for hand in root.hands]
    pool = Counter(chain.from_iterable((*root.hands, root.buried)))
    for w, (hands, buried) in enumerate(root_worlds):
        if ([len(hand) for hand in hands] != sizes or len(buried) != len(root.buried)
                or Counter(chain.from_iterable((*hands, buried))) != pool):
            raise ValueError("incomplete outer world")
        if (sorted(hands[seat]) != sorted(root.hands[seat])
                or (seat == root.banker and sorted(buried) != sorted(root.buried))):
            raise ValueError("outer world changes root information")
        paired_seed = int(np.random.SeedSequence([seed, w]).generate_state(1, dtype=np.uint64)[0])
        for a, action in enumerate(actions):
            branch_ledger = ledger
            if root.trick.plays:
                child = afterstate(root, seat, hands, buried, action)
                if Counter(actual_play_after(child, seat, root.last_trick)) != Counter(action):
                    raise ValueError("engine substituted a root follow")
            else:
                child = root_clone(root, hands, buried)
                # Observation needs the normal engine path so the reply sees the failed throw.
                child._trusted_rollout = False
                child.play(seat, list(action))
                refusal = lead_refusal_after(child, seat, action, root.last_trick)
                if refusal is not None:
                    branch_ledger = (*ledger, refusal)
            if child.phase == "round_end":
                result[w, a] = terminal_distribution(child, seat) @ LEVEL_SUPPORT
                continue
            replies = _bounded_replies(child, reply_cap, cover_winning_follow)
            log_prior, score = _reply_node(child, branch_ledger, model, replies)
            outer = [(child.hands, child.buried)]
            outer_values = paired_reply_values(child, replies, outer, batch_size=batch_size,
                                              score=score, value_seat=seat)[0]
            if len(replies) == 1:
                result[w, a] = outer_values[0]
                continue
            if reply_value_weight:
                inner = draw_depth_worlds(child, belief=belief, refusals=branch_ledger,
                                          seed=paired_seed, worlds=depth_worlds)
                values = paired_reply_values(child, replies, inner, batch_size=batch_size,
                                             score=score)
                log_prior += reply_value_weight * values.mean(axis=0)
            result[w, a] = _softmax(log_prior) @ outer_values
    if not np.isfinite(result).all():
        raise ValueError("nonfinite stochastic reply backup")
    return result

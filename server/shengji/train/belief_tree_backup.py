"""One offline reply ply with an actor-conditioned belief and stochastic policy."""
from collections import Counter
from itertools import chain, islice

import numpy as np

from ..ai.belief_numpy import decision_inputs
from ..ai.cwv_policy import afterstate
from ..ai.refusal import observe_refusal, on_record
from ..engine.legal import validate_follow
from ..engine.round import actual_play_after
from ..harvest.legal import iter_follow_actions
from ..rl.value_afterstate import terminal_distribution
from .belief_tree_teacher import draw_depth_worlds, paired_reply_values
from .cwv_data import LEVEL_SUPPORT
from .pv_tree_search import single_component_leads
from .unified_slots import LeafFrame, _preferences, leaf_features_batch, policy_from_states


def _softmax(logits):
    weights = np.exp(logits - logits.max(axis=-1, keepdims=True))
    return weights / weights.sum(axis=-1, keepdims=True)


def _reply_node(child, ledger, model, replies):
    """Policy and value share the acting seat's explicit public-history frame."""
    actor = child.turn
    inp = decision_inputs(child, actor, ledger)
    q, g = model.card_states(inp, model.trunk.encode_history(inp))
    frame = LeafFrame.at_states(None, child, actor, model, q, g)
    prior = _preferences(policy_from_states(model, q), replies)

    def score(leaves, seat):
        indices, planes, scalars = leaf_features_batch(frame, leaves)
        values = np.empty(len(leaves))
        if indices:
            sign = 1 if (seat - actor) % 2 == 0 else -1
            values[indices] = sign * (model.leaf_value_probs(frame.cache(model), planes, scalars)
                                      @ LEVEL_SUPPORT)
        terminal = [i for i, leaf in enumerate(leaves) if leaf.phase == "round_end"]
        if len(indices) + len(terminal) != len(leaves):
            raise ValueError("reply leaf outside the unified value frame")
        for i in terminal:
            values[i] = terminal_distribution(leaves[i], seat) @ LEVEL_SUPPORT
        return values

    return prior, score


def root_reply_backup(root, actions, root_worlds, *, belief, model, refusals, seed, depth_worlds,
                      reply_cap, batch_size, reply_value_weight):
    """Expected root-team values, indexed by supplied outer world and root action.

    Each reply distribution starts with the unified policy prior from the acting
    seat's information. Tilt it by exp(weight * expected acting-team value), with the
    weight in inverse value units. Zero weight evaluates the prior alone. Sum over
    the stochastic replies exactly on the original outer deal to preserve the
    root's known cards. The caller supplies the same root worlds as flat search.
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
            child = afterstate(root, seat, hands, buried, action)
            if sorted(actual_play_after(child, seat, root.last_trick)) != sorted(action):
                raise ValueError("engine substituted a root action")
            if child.phase == "round_end":
                result[w, a] = terminal_distribution(child, seat) @ LEVEL_SUPPORT
                continue
            reply_seat = child.turn
            hand = child.hands[reply_seat]
            choices = (iter_follow_actions(hand, child.trick.plays[0].cards, child.ordering)
                       if child.trick.plays else single_component_leads(hand, child.ordering))
            replies = [list(cards) for cards in islice(choices, reply_cap)]
            log_prior, score = _reply_node(child, ledger, model, replies)
            outer = [(child.hands, child.buried)]
            outer_values = paired_reply_values(child, replies, outer, batch_size=batch_size,
                                              score=score, value_seat=seat)[0]
            if len(replies) == 1:
                result[w, a] = outer_values[0]
                continue
            if reply_value_weight:
                inner = draw_depth_worlds(child, belief=belief, refusals=ledger,
                                          seed=paired_seed, worlds=depth_worlds)
                values = paired_reply_values(child, replies, inner, batch_size=batch_size,
                                             score=score)
                log_prior += reply_value_weight * values.mean(axis=0)
            result[w, a] = _softmax(log_prior) @ outer_values
    if not np.isfinite(result).all():
        raise ValueError("nonfinite stochastic reply backup")
    return result

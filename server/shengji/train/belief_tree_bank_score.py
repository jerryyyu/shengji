"""Score one independently replayed lead in the offline belief-tree bank."""
import hashlib
import json
from math import isfinite

from ..harvest.common import action_key
from ..harvest.legal import enumerate_legal, resolve_lead
from .belief_tree_compare import SingleAdmittedLead, compare_replayed_lead
from .belief_tree_replay import TrancheRoot
from .belief_tree_yardsticks import true_deal_yardsticks


def _stream_seed(source, arm):
    """Separate the draw streams while keeping each independent of bank order."""
    return int.from_bytes(hashlib.sha256(b"s165-bank-v1:" + arm + b":" + source).digest()[:8], "big")


def _accepted_cards(root, action):
    if not action:
        raise ValueError("bank comparison is missing a lead action")
    accepted, _ = resolve_lead(root.round, root.target.seat, action)
    return list(action_key(accepted))


def score_bank_root(root: TrancheRoot, *, make_bot, policy: str, seed: int, depth_worlds: int,
                    reply_cap: int, batch_size: int, reply_value_weight: float,
                    cover_winning_follow: bool = False) -> dict:
    """Score the entire paired ballot with the flat, tree and true-deal consumers.

    Only a complete singleton legal set or a singleton from a valid flat pass
    is ineligible. A scoring, sampling or engine fault propagates to the bank
    runner. The final served action is recorded separately from the base
    estimator's first-argmax action.
    """
    tgt = root.target
    rnd = root.round
    if (rnd.phase != "play" or rnd.trick is None or rnd.trick.plays or rnd.turn != tgt.seat
            or type(seed) is not int or seed < 0 or not policy
            or any(type(v) is not int or v < 1 for v in (depth_worlds, reply_cap, batch_size))
            or not isfinite(reply_value_weight) or reply_value_weight < 0):
        raise ValueError("expected a replayed lead and a valid bank scoring configuration")
    identity = dict(deal_key=root.deal_key, decision_index=tgt.decision_index, mirror=tgt.mirror,
                    ply=tgt.ply, seat=tgt.seat, policy=policy)
    legal = enumerate_legal(rnd, tgt.seat, cap=2)
    if legal.complete and len(legal.actions) == 1:
        return {**identity, "eligible": False, "ineligible_reason": "single_legal_action",
                "ballot": [list(action_key(legal.actions[0]))]}

    source = json.dumps([seed, root.deal_key, tgt.decision_index, tgt.mirror, tgt.ply, tgt.seat],
                        separators=(",", ":")).encode("ascii")
    flat_bot = make_bot(_stream_seed(source, b"flat"))
    if flat_bot.policy_name != policy:
        raise ValueError("bank scorer needs the pinned flat policy")
    try:
        paired = compare_replayed_lead(
            root, flat_bot, seed=_stream_seed(source, b"tree"), depth_worlds=depth_worlds,
            reply_cap=reply_cap, batch_size=batch_size, reply_value_weight=reply_value_weight,
            record_final_action=True, cover_winning_follow=cover_winning_follow,
        )
    except SingleAdmittedLead as single:
        return {**identity, "eligible": False, "ineligible_reason": "single_admitted_action",
                "ballot": [list(single.action)], "flat_means": [single.flat_mean],
                "flat_final_action": list(single.final_action),
                "flat_final_accepted": _accepted_cards(root, single.final_action)}
    accepted = _accepted_cards(root, paired.flat_final_action)
    values = true_deal_yardsticks(root, paired.actions, model=flat_bot.unified_value_model,
                                 make_reply_bot=make_bot, expected_policy_name=policy,
                                 seed=_stream_seed(source, b"yardstick"))
    contrast = paired.contrast(values)
    ballot = [action_key(action) for action in paired.actions]
    return {
        **identity,
        **contrast,
        "eligible": True,
        "ineligible_reason": None,
        "ballot": [list(action) for action in ballot],
        "flat_action": list(contrast["flat_action"]),
        "flat_final_action": list(paired.flat_final_action),
        "flat_final_accepted": accepted,
        "tree_action": list(contrast["tree_action"]),
        "flat_means": paired.flat_means.tolist(),
        "tree_means": paired.reply_values.mean(axis=0).tolist(),
        "yardsticks": [{"action": list(action), "accepted": _accepted_cards(root, action),
                        "sf": values[action][0], "vt": values[action][1]}
                       for action in ballot],
    }

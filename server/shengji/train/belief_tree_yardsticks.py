"""True-deal finishes for the paired offline lead comparison."""
import copy

import numpy as np

from ..ai.cwv_policy import default_finisher
from ..ai.refusal import RefusalLedger, observe_refusal, on_record
from ..engine.round import actual_play_after
from ..harvest.common import action_key
from .belief_tree_backup import unified_trick_frame
from .belief_tree_replay import TrancheRoot
from .pv_search_policy import RECORD_SCHEMA


def _commit(position, seat, action):
    previous = position.last_trick
    position.play(seat, list(action))
    if action_key(actual_play_after(position, seat, previous)) != action_key(action):
        raise ValueError("engine substituted a true-deal yardstick action")


def _serve_reply(bot, position, seat, ledger):
    previous = bot._refusals
    bot._refusals = copy.deepcopy(ledger)
    try:
        cards = bot.decide_play(position, seat)
        record = bot.last_decision_record or {}
        unified = record.get("unified", {})
        if (not cards or record.get("schema") != RECORD_SCHEMA or record.get("work_complete") is not True
                or record.get("worlds") != bot.worlds or record.get("belief_fallback_all_draws") != 0
                or not record.get("played") or action_key(record["played"]) != action_key(cards)
                or unified.get("package") != bot.unified_sha256[:8]
                or unified.get("value_left") != 0 or unified.get("reply_left") != 0):
            raise ValueError("incomplete or fallback served reply in true-deal yardstick")
        if bot._refusals.refusals != ledger.refusals or bot._refusals.key != ledger.key:
            raise ValueError("served reply changed the true-deal refusal ledger")
        return cards
    finally:
        bot._refusals = previous


def _finish(position, target, ledger, choose):
    for _ in range(3):
        if (position.phase != "play" or len(position.history) != target - 1
                or position.trick is None or not 1 <= len(position.trick.plays) < 4):
            raise ValueError("true-deal yardstick reply is outside the root trick")
        seat = position.turn
        _commit(position, seat, choose(position, seat, ledger))
        ledger.observe(position)
    if (len(position.history) != target or position.phase not in ("play", "round_end")
            or (position.phase == "play" and (position.trick is None or position.trick.plays))):
        raise ValueError("true-deal yardstick did not complete exactly the root trick")
    return position


def true_deal_yardsticks(root: TrancheRoot, actions, *, model, make_reply_bot,
                         expected_policy_name: str, seed: int):
    """Map the canonical action keys to (served, heuristic) true-deal values.

    The real dealt hands fix the world. Each responding seat's fresh served bot
    starts every alternative at the same seed and public refusal ledger.
    Both finishes stop at the end of the root trick and use the same root-seat
    unified value frame, with exact value at terminal states.
    """
    rnd = root.round
    seat = root.target.seat
    actions = tuple(actions)
    action_keys = tuple(action_key(action) for action in actions)
    if (rnd.phase != "play" or rnd.trick is None or rnd.trick.plays or rnd.turn != seat
            or type(seed) is not int or seed < 0 or not expected_policy_name
            or len(action_keys) < 2 or any(not key for key in action_keys)
            or len(set(action_keys)) != len(action_keys)):
        raise ValueError("expected a replayed lead and a distinct nonempty ballot")
    notice = observe_refusal(rnd)
    if (len(set(root.refusals)) != len(root.refusals)
            or any(r.trick_index < 0 or not on_record(rnd, r) for r in root.refusals)
            or (notice is not None and notice not in root.refusals)):
        raise ValueError("true-deal yardstick refusal ledger disagrees with the public record")

    prototypes = {}
    for actor in range(4):
        if actor == seat:
            continue
        paired_seed = int(np.random.SeedSequence([seed, actor]).generate_state(1, dtype=np.uint64)[0])
        bot = make_reply_bot(paired_seed)
        if (bot.policy_name != expected_policy_name or bot.worlds != 64 or bot.candidates != 8
                or bot.serving_budget_seconds is not None or bot.leaf_greedy_deadline_ms
                or bot.oracle_worlds or bot.oracle_mix_k or bot.oracle_pin_q
                or not bot.refusal_constraints
                or getattr(getattr(bot, "unified_value_model", None), "package_sha256", None)
                != model.package_sha256):
            raise ValueError("expected the pinned served reply bot with lifted deadlines")
        prototypes[actor] = bot

    def served(position, actor, ledger):
        return _serve_reply(copy.deepcopy(prototypes[actor]), position, actor, ledger)

    heuristic = default_finisher()
    target = len(rnd.history) + 1
    canonical = copy.deepcopy(rnd)
    canonical.hands = [sorted(hand) for hand in rnd.hands]
    canonical.buried = sorted(rnd.buried)
    leaves = []
    for action in actions:
        child = copy.deepcopy(canonical)
        _commit(child, seat, action)
        ledger = RefusalLedger()
        ledger.key = tuple(child.deck)
        ledger.refusals = list(root.refusals)
        ledger.observe(child)
        leaves.append(_finish(copy.deepcopy(child), target, copy.deepcopy(ledger), served))
        leaves.append(_finish(child, target, ledger, lambda p, s, _: heuristic.decide_play(p, s)))

    _, score = unified_trick_frame(rnd, root.refusals, model)
    values = score(leaves, seat)
    if values.shape != (2 * len(action_keys),) or not np.isfinite(values).all():
        raise ValueError("true-deal yardstick did not score every action")
    return {key: (float(sf), float(vt)) for key, (sf, vt) in zip(action_keys, values.reshape(-1, 2))}

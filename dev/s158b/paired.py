"""Play a prepared deal on the served trajectory and compare eight-card follow picks."""
from time import process_time
from unittest.mock import patch

from shengji.ai.endgame import _clone_for_play
from shengji.ai.endgame_compact import CompactWorldSession
from shengji.ai.env import observe_committed_play
from shengji.train.pv_exact_follow import rerank_follow


class ReferenceTimeout(Exception):
    """The full-world comparator ran out of its stage CPU allowance."""


def _full_pick(rnd, seat, admitted, worlds, baseline, max_nodes):
    deadline = process_time() + 20

    def guard():
        if process_time() > deadline:
            raise ReferenceTimeout

    try:
        result = rerank_follow(rnd, seat, admitted, worlds, baseline_index=baseline,
                               max_hand_cards=8, max_nodes=max_nodes,
                               solver="compact-level", check_budget=guard)
        guard()
    except ReferenceTimeout:
        return None
    return result.winner


def _pi_points(rnd, seat, admitted):
    deadline = process_time() + 60

    def guard():
        if process_time() > deadline:
            raise TimeoutError("true-deal reference did not finish")

    session = CompactWorldSession(rnd, max_hand_cards=8, max_nodes=2_000_000_000,
                                  check_budget=guard, alpha_beta=True, level=True)
    values = []
    for action in admitted:
        child = _clone_for_play(rnd)
        child.play(seat, list(action))
        values.append(child.attacker_points if child.phase == "round_end"
                      else session.solve_points(child))
        guard()
    return values


def paired_play(bot, rnd, seat):
    """Decide once. Return the served cards to commit, plus a matched row if eligible."""
    if not bot.exact_follow_anytime_eight or bot.serving_budget_seconds != 3:
        raise ValueError("paired play requires the three-second eight-card arm")
    if not rnd.trick.plays or max(map(len, rnd.hands)) != 8:
        cards = bot.decide_play(rnd, seat)
        if not (bot.last_decision_record or {}).get("work_complete"):
            raise ValueError("incomplete base play")
        return cards, None

    captured = []
    value_pass = bot._value_means

    def capture(root, acting, actions, worlds, check_budget=None):
        captured.append((root, acting, actions, worlds))
        return value_pass(root, acting, actions, worlds, check_budget)

    with patch.object(bot, "_value_means", capture):
        cards = bot.decide_play(rnd, seat)
    rec = bot.last_decision_record or {}
    if not rec.get("work_complete") or rec.get("fallback"):
        raise ValueError("incomplete eight-card decision")
    admitted = rec["admitted"]
    if len(admitted) == 1 and sorted(cards) == sorted(admitted[0]):
        return cards, None
    if len(captured) != 1 or not rec.get("exact_follow_attempted"):
        raise ValueError("missing unique value ballot or eight-card attempt")
    root, acting, actions, worlds = captured[0]
    if (root is not rnd or acting != seat or list(actions) != admitted
            or len(worlds) != rec["worlds"] or len(worlds) != 64):
        raise ValueError("value ballot or sampled worlds differ from the final decision")
    baseline = rec["exact_follow_baseline_index"]
    arm = rec["admitted_indices"].index(rec["selected_index"])
    abandon = rec["exact_follow_abandoned"]
    if (type(baseline) is not int or not 0 <= baseline < len(admitted)
            or sorted(admitted[arm]) != sorted(cards)
            or abandon not in (None, "hard_budget", "soft_budget")
            or (abandon and arm != baseline)):
        raise ValueError("inconsistent or faulted arm decision")
    full = _full_pick(rnd, seat, admitted, worlds, baseline, bot.exact_follow_max_nodes)
    return list(admitted[baseline]), dict(
        seat=seat, attacker=bool(rnd.is_attacker(seat)), admitted=admitted,
        served=baseline, arm=arm, full=full, full_censored=full is None,
        worlds=len(worlds), abandoned=abandon, stage_seconds=rec["exact_follow_seconds"],
        pi_attacker_points=_pi_points(rnd, seat, admitted))


def play_deal(rnd, bots):
    """Consume one prepared round. Any fault propagates before a deal result is returned."""
    rows = []
    decisions = 0
    while rnd.phase == "play":
        seat = rnd.turn
        cards, row = paired_play(bots[seat], rnd, seat)
        if row is not None:
            rows.append(dict(row, play_index=decisions))
        rnd.play(seat, list(cards))
        observe_committed_play(rnd, bots)
        decisions += 1
    if not decisions or rnd.phase != "round_end":
        raise ValueError("incomplete deal")
    return dict(decisions=decisions, eligible=rows, attacker_points=rnd.attacker_points)

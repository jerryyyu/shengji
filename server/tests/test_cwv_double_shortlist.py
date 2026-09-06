"""Focused witnesses for the bounded privileged double shortlist."""
from __future__ import annotations

import copy

import numpy as np
import pytest

from shengji.ai.cwv_policy import afterstate
from shengji.ai.heuristic import HeuristicBot
from shengji.ai.mcbot import MCBot
from shengji.harvest.legal import enumerate_legal
from shengji.train.cwv_double_shortlist import (
    CWVDoubleShortlistBot,
    DoubleShortlistError,
)
from shengji.train.cwv_shortlist import CWVShortlistBot, CWVShortlistConfig
from tests.test_world_shortlist import play_state, round_signature


class PointsNet:
    """Deterministic fake with a deliberately action-sensitive inner value."""

    def __init__(self):
        self.calls: list[tuple[int, list[int]]] = []
        self.root_calls = 0

    @staticmethod
    def _action(position):
        if position.trick is not None and position.trick.plays:
            return position.trick.plays[-1].cards
        return position.history[-1].plays[-1].cards

    def score(self, positions, seat):
        self.root_calls += 1
        return np.asarray([float(p.attacker_points) for p in positions])

    def score_many(self, positions, seats):
        self.calls.append((len(positions), list(seats)))
        # The action code is only a ranking witness; final values still come
        # from known-world heuristic completion in the double shortlist.
        return np.asarray([
            float(p.attacker_points) + sum(
                ord(ch) for card in self._action(p) for ch in card) / 10000.0
            for p in positions
        ])


def _world_and_actions(rnd, count=2):
    seat = rnd.turn
    return seat, ([list(h) for h in rnd.hands], list(rnd.buried)), \
        enumerate_legal(rnd, seat, cap=None).actions[:count]


def test_heuristic_mode_is_flat_rollout_and_keeps_inner_net_idle():
    rnd = play_state()
    original = round_signature(rnd)
    seat, world, actions = _world_and_actions(rnd)
    bot = CWVDoubleShortlistBot(
        PointsNet(), seed=9, inner_mode="heuristic", inner_worlds=1)
    got = bot._lockstep_values(rnd, seat, [world], actions, stage="selection")
    expected = []
    sampled = {s: list(world[0][s]) for s in range(4) if s != seat}
    for action in actions:
        expected.append(bot._rollout(rnd, seat, sampled, world[1], action))
    assert got.tolist() == [expected]
    assert bot.last_double_shortlist["inner_net_rows"] == 0
    assert bot.last_double_shortlist["inner_full_rollouts"] == 0
    assert round_signature(rnd) == original


def test_learned_inner_path_changes_actual_continuation_values_and_is_batched():
    rnd = play_state()
    seat, world, actions = _world_and_actions(rnd)
    net = PointsNet()
    bot = CWVDoubleShortlistBot(net, seed=3, inner_mode="learned",
                                inner_worlds=1, inner_batch_size=7)
    learned = bot._lockstep_values(rnd, seat, [world], actions, stage="report")
    flat = CWVDoubleShortlistBot(net, seed=3, inner_mode="heuristic",
                                 inner_worlds=1)._lockstep_values(
                                     rnd, seat, [world], actions, stage="report")
    assert not np.array_equal(learned, flat)
    detail = bot.last_double_shortlist
    assert detail["inner_net_rows"] > 0
    assert detail["inner_full_rollouts"] > 0
    assert max(size for size, _ in net.calls) <= 7
    assert any(seats and len(set(seats)) == 1 for _, seats in net.calls)


def test_uniform_inner_has_no_evaluator_dependency_and_retains_incumbent():
    rnd = play_state()
    seat, world, actions = _world_and_actions(rnd)
    from shengji.train.cwv_shortlist import CWVShortlistConfig
    bot = CWVDoubleShortlistBot(
        None, seed=12, config=CWVShortlistConfig(uniform=True),
        inner_mode="uniform", inner_worlds=1)
    values = bot._lockstep_values(rnd, seat, [world], actions, stage="selection")
    assert values.shape == (1, len(actions))
    assert bot.last_double_shortlist["inner_net_rows"] == 0
    assert bot.last_double_shortlist["inner_full_rollouts"] > 0


def test_inner_evaluation_does_not_mutate_round_or_parent_rng():
    rnd = play_state()
    original = round_signature(rnd)
    seat, world, actions = _world_and_actions(rnd)
    bot = CWVDoubleShortlistBot(PointsNet(), seed=31, inner_worlds=1)
    rng_before = bot.rng.getstate()
    bot._lockstep_values(rnd, seat, [world], actions, stage="selection")
    assert round_signature(rnd) == original
    assert bot.rng.getstate() == rng_before


def test_exact_endgame_is_explicitly_refused():
    class Exact(CWVDoubleShortlistBot):
        EXACT_ENDGAME = True

    with pytest.raises(DoubleShortlistError, match="does not support EXACT_ENDGAME"):
        Exact(PointsNet())


def test_inherited_production_hooks_are_reused():
    from shengji.train.net_rollout import MCNetRolloutSearch

    assert CWVDoubleShortlistBot._report_fold_gap is MCNetRolloutSearch._report_fold_gap
    assert CWVDoubleShortlistBot._decide_adaptive is MCNetRolloutSearch._decide_adaptive


def test_real_decide_play_heuristic_mode_matches_flat_selection_and_report():
    rnd = play_state()
    cfg = CWVShortlistConfig(worlds=1, selection_worlds=1, batch_size=31)
    flat = CWVShortlistBot(PointsNet(), seed=17, config=cfg)
    double = CWVDoubleShortlistBot(
        PointsNet(), seed=17, config=cfg, inner_mode="heuristic",
        inner_worlds=1)
    for bot in (flat, double):
        bot.REPORT_FOLD_WORLDS = 30
        bot.REPORT_RULE = "lcb"
    flat_play = flat.decide_play(copy.deepcopy(rnd), rnd.turn)
    double_play = double.decide_play(copy.deepcopy(rnd), rnd.turn)
    assert double_play == flat_play
    a, b = flat.last_decision_record, double.last_decision_record
    assert len(b["candidates"]) == len(a["candidates"]) == 5
    assert b["candidates"] == a["candidates"]
    assert b["means"] == a["means"]
    assert b["paired_se"] == a["paired_se"]
    assert b["report_fold"] == a["report_fold"]
    assert b["sampler_counters"]["delta"] == a["sampler_counters"]["delta"]
    assert double.rng.getstate() == flat.rng.getstate()
    assert double.last_double_shortlist["actual_inner_worlds"] == 0


def test_real_decide_play_learned_reaches_both_consumers():
    # Synthetic two-card hands and fixed sampled worlds isolate consumer
    # wiring; the screen test covers a natural state and the real sampler.
    rnd = copy.deepcopy(play_state())
    rnd.hands = [["SA", "D5"], ["SK", "D6"], ["S3", "C4"], ["S4", "D4"]]
    bot = CWVDoubleShortlistBot(
        PointsNet(), seed=23,
        config=CWVShortlistConfig(worlds=1, selection_worlds=1),
        inner_mode="learned", inner_worlds=1, inner_batch_size=19)
    # A small mean report still exercises the independent report consumer;
    # the production LCB minimum is covered by the screen integration.
    bot.REPORT_FOLD_WORLDS = 3
    bot.REPORT_RULE = "mean"
    fixed = [list(hand) for hand in rnd.hands]
    sampled = {s: list(fixed[s]) for s in range(4) if s != rnd.turn}
    bot._sample_hands = lambda *args: (sampled, [])
    bot._complete_determinized_hands = lambda *args, **kwargs: [
        list(hand) for hand in fixed]
    bot._prepare_report_world = lambda *args, **kwargs: type(
        "Prepared", (), {"hands": tuple(tuple(h) for h in fixed), "buried": ()})()
    bot.decide_play(rnd, rnd.turn)
    detail = bot.last_decision_record["cwv_double_shortlist"]
    assert [row["stage"] for row in detail["stages"]] == ["selection", "report"]
    assert [row["actual_inner_worlds"] for row in detail["stages"]] == [1, 3]
    assert [row["guidance_numerator"] for row in detail["stages"]] == [1, 1]
    assert [row["guidance_denominator"] for row in detail["stages"]] == [1, 1]
    assert detail["inner_net_rows"] > 0
    assert detail["inner_full_rollouts"] > 0
    assert detail["inner_net_rows"] == bot.double_shortlist_counts["inner_net_rows"]
    outer = bot.last_decision_record["work"]["total_rollouts"]
    assert bot.rollouts == outer + detail["inner_full_rollouts"]


def test_uniform_inner_keeps_learned_root_scoring_but_calls_no_inner_net():
    class RootOnly(PointsNet):
        def score_many(self, positions, seats):
            raise AssertionError("uniform inner must not invoke score_many")

    rnd = play_state()
    net = RootOnly()
    bot = CWVDoubleShortlistBot(net, seed=29, inner_mode="uniform",
                                inner_worlds=1)
    bot.REPORT_FOLD_WORLDS = 0
    bot.REPORT_RULE = "none"
    bot.decide_play(rnd, rnd.turn)
    assert net.calls == []
    assert net.root_calls > 0
    assert bot.last_shortlist["shortlist"]
    assert bot.last_double_shortlist["inner_net_rows"] == 0
    assert bot.last_double_shortlist["inner_actions"] > 0


def test_inner_finalists_retain_incumbent_and_can_admit_off_ballot_action():
    rnd = play_state()
    seat, world, _ = _world_and_actions(rnd)
    root = MCBot(seed=0)
    production = root._candidates(rnd, seat)
    root_leaf = afterstate(rnd, seat, *world, production[0], finish_trick=True)
    mover = root_leaf.turn
    assert mover is not None
    legal = enumerate_legal(root_leaf, mover, cap=None)
    ballot = {tuple(sorted(a)) for a in MCBot(seed=0)._candidates(root_leaf, mover)}
    target = next(tuple(a) for a in legal.actions if tuple(a) not in ballot)
    target_leaf = afterstate(root_leaf, mover, root_leaf.hands,
                             root_leaf.buried, target, finish_trick=True)
    target_sig = round_signature(target_leaf)

    class TargetNet(PointsNet):
        def score_many(self, positions, seats):
            return np.asarray([
                1000.0 if round_signature(p) == target_sig else 0.0
                for p in positions
            ])

    bot = CWVDoubleShortlistBot(TargetNet(), inner_worlds=1)
    stats = {"inner_actions": 0, "inner_finalist_actions": 0,
             "inner_net_rows": 0, "inner_batches": 0,
             "inner_full_rollouts": 0}
    finalists, _ = bot._rank_inner(root_leaf, mover, (0, 0, 0), stats, legal)
    incumbent = tuple(sorted(bot.rollout_policy.decide_play(root_leaf, mover)))
    assert finalists[0] == incumbent
    assert target in finalists
    assert len(finalists) <= 5


@pytest.mark.parametrize("is_follow", [False, True])
def test_follow_horizon_is_current_trick_plus_one_and_world_cap_is_exact(monkeypatch, is_follow):
    root = play_state()
    policy = HeuristicBot()
    mid = copy.deepcopy(root)
    if is_follow:
        mid.play(mid.turn, policy.decide_play(mid, mid.turn))
    original = round_signature(mid)
    seat, world, actions = _world_and_actions(mid, 1)
    bot = CWVDoubleShortlistBot(PointsNet(), inner_worlds=1,
                                inner_batch_size=13)
    inner_histories = []
    original_rank = bot._rank_inner

    def record_rank(state, *args, **kwargs):
        inner_histories.append(len(state.history))
        return original_rank(state, *args, **kwargs)

    monkeypatch.setattr(bot, "_rank_inner", record_rank)
    values = bot._lockstep_values(mid, seat, [world, world], actions, stage="selection")
    detail = bot.last_double_shortlist
    assert detail["actual_inner_worlds"] == 1
    assert detail["one_extra_trick_horizon"] == len(mid.history) + 2
    assert detail["inner_full_rollouts"] > 0
    assert inner_histories == [len(mid.history) + 1] * 4
    flat = CWVDoubleShortlistBot(PointsNet(), inner_mode="heuristic")
    expected = flat._lockstep_values(mid, seat, [world], actions, stage="selection")
    assert values[1].tolist() == expected[0].tolist()
    assert round_signature(mid) == original


def test_terminal_root_bypasses_inner_net():
    root = play_state()
    terminal = copy.deepcopy(root)
    for hand in terminal.hands:
        del hand[1:]
    seat = terminal.turn
    action = [terminal.hands[seat][0]]
    world = ([list(h) for h in terminal.hands], list(terminal.buried))
    net = PointsNet()
    bot = CWVDoubleShortlistBot(net, inner_worlds=1)
    out = bot._lockstep_values(terminal, seat, [world], [action], stage="report")
    assert np.isfinite(out).all()
    assert bot.last_double_shortlist["inner_net_rows"] == 0
    assert net.calls == []


def test_guidance_fraction_ceil_zero_and_saturation_without_rollout_cost(monkeypatch):
    class FakeState:
        phase = "play"
        history = []
        turn = 0

    def run(bot, count, stage="selection"):
        seen = []
        monkeypatch.setattr(bot, "_root_leaf",
                            lambda *args, **kwargs: FakeState())
        monkeypatch.setattr(bot, "_finish_heuristic", lambda state: 0.0)
        monkeypatch.setattr(bot, "_guided_many",
                            lambda branches, stats: seen.append(len(branches))
                            or [0.0] * len(branches))
        worlds = [([], []) for _ in range(count)]
        root = type("Root", (), {"history": []})()
        bot._lockstep_values(root, 0, worlds, [["A"]], stage=stage)
        return bot.last_double_shortlist["stages"][-1], seen

    bot = CWVDoubleShortlistBot(None,
                                config=CWVShortlistConfig(uniform=True),
                                inner_mode="uniform", inner_worlds=4)
    bot.N_DETERMINIZATIONS = 30
    stage, seen = run(bot, 30)
    assert stage["guidance_numerator"] == 4
    assert stage["guidance_denominator"] == 30
    assert stage["target_inner_worlds"] == stage["actual_inner_worlds"] == 4
    assert seen == [4]
    stage, seen = run(bot, 300, stage="report")
    assert stage["target_inner_worlds"] == stage["actual_inner_worlds"] == 40
    assert seen == [40]
    stage, seen = run(bot, 3)
    assert stage["target_inner_worlds"] == stage["actual_inner_worlds"] == 1
    assert seen == [1]
    stage, seen = run(bot, 0)
    assert stage["target_inner_worlds"] == stage["actual_inner_worlds"] == 0
    assert seen == []
    bot.inner_worlds = 99
    stage, seen = run(bot, 12)
    assert stage["guidance_numerator"] == stage["guidance_denominator"] == 30
    assert stage["target_inner_worlds"] == stage["actual_inner_worlds"] == 12
    assert seen == [12]


def test_guided_branches_share_cross_parent_partial_batch_with_row_movers(monkeypatch):
    from shengji.train import cwv_double_shortlist as module

    root = copy.deepcopy(play_state())
    # A real engine state with two cards per seat leaves one legal action per
    # seat after the current and extra trick, making the parent tails small.
    root.hands = [["SA", "D5"], ["SK", "D6"], ["S3", "C4"], ["S4", "D4"]]
    assert root.turn == 2 and root.trump_suit != "S"
    seat = root.turn
    candidate = [root.hands[seat][0]]
    world_a = ([list(h) for h in root.hands], list(root.buried))
    real_afterstate = module.afterstate

    def tag_actual_mover(*args, **kwargs):
        leaf = real_afterstate(*args, **kwargs)
        if kwargs.get("finish_trick") is True:
            leaf._test_mover = args[1]
        return leaf

    class SeatCheckingNet(PointsNet):
        def score_many(self, positions, seats):
            assert list(seats) == [p._test_mover for p in positions]
            return super().score_many(positions, seats)

    monkeypatch.setattr(module, "afterstate", tag_actual_mover)
    bot = CWVDoubleShortlistBot(
        SeatCheckingNet(), config=CWVShortlistConfig(selection_worlds=1),
        inner_worlds=2, inner_batch_size=6)
    # Swap two hidden hands to make the sampled-world branches have different
    # winners/movers while preserving the same real Round input.
    world_b_hands = [list(h) for h in root.hands]
    world_b_hands[0], world_b_hands[1] = world_b_hands[1], world_b_hands[0]
    world_b = (world_b_hands, list(root.buried))
    result = bot._lockstep_values(
        root, seat, [world_a, world_b], [candidate], stage="selection")
    detail = bot.last_double_shortlist
    assert result.shape == (2, 1)
    assert detail["actual_inner_worlds"] == 2
    assert detail["inner_cross_parent_batches"] > 0
    assert detail["inner_net_rows"] > detail["inner_batch_size"]
    assert max(size for size, _ in bot.evaluator.calls) <= 6
    assert all(len(seats) == size for size, seats in bot.evaluator.calls)
    assert any(len(set(seats)) > 1 for _, seats in bot.evaluator.calls)
    serial = CWVDoubleShortlistBot(SeatCheckingNet(), inner_worlds=1, inner_batch_size=6)
    expected = np.vstack([serial._lockstep_values(
        root, seat, [world], [candidate], stage="selection") for world in (world_a, world_b)])
    np.testing.assert_array_equal(result, expected)


@pytest.mark.parametrize("prior_plays,attack", [(1, True), (2, False)])
@pytest.mark.parametrize("tie", [False, True])
def test_inner_chooser_uses_movers_terminal_value_and_incumbent_ties(
        monkeypatch, prior_plays, attack, tie):
    from shengji.train import cwv_double_shortlist as module

    state = play_state()
    heuristic = HeuristicBot()
    for _ in range(prior_plays):
        state.play(state.turn, heuristic.decide_play(state, state.turn))
    mover = state.turn
    assert state.is_attacker(mover) is attack
    incumbent = tuple(sorted(heuristic.decide_play(state, mover)))
    legal = enumerate_legal(state, mover, cap=None).actions
    bot = CWVDoubleShortlistBot(PointsNet(), inner_alternatives=len(legal))
    outcomes = {}
    for action in legal:
        leaf = afterstate(state, mover, state.hands, state.buried, action,
                          finish_trick=True)
        outcomes[tuple(action)] = bot._finish_heuristic(leaf)
    assert min(outcomes.values()) < max(outcomes.values())
    if tie:
        monkeypatch.setattr(bot, "_score", lambda value: 0.0)
    chosen = []
    real_afterstate = module.afterstate

    def record_actual_choice(*args, **kwargs):
        if kwargs.get("finish_trick") is False:
            chosen.append(tuple(args[4]))
        return real_afterstate(*args, **kwargs)

    monkeypatch.setattr(module, "afterstate", record_actual_choice)
    stats = {"inner_actions": 0, "inner_finalist_actions": 0,
             "inner_net_rows": 0, "inner_batches": 0, "inner_full_rollouts": 0}
    bot._guided_root_value(state, (0, 0, 0), stats)
    if tie:
        assert chosen[0] == incumbent
    else:
        optimum = max(outcomes.values()) if attack else min(outcomes.values())
        assert outcomes[chosen[0]] == optimum

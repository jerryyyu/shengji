"""Witness the live root -> selection -> fresh report -> recorded decision."""
from __future__ import annotations

import copy
import random

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.registry import make_bot
from shengji.engine.game import Game
from shengji.harvest.legal import enumerate_legal
from shengji.train.search_policy import LearnedSearchBot, SearchConfig, SearchError, terminal_utility


def play_state(seed=431):
    game = Game(random.Random(seed))
    rnd = game.start_round()
    policy = HeuristicBot()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = policy.decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = policy.decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, policy.decide_bury(rnd, rnd.banker))
    return rnd


def signature(rnd):
    return (rnd.phase, rnd.turn, rnd.attacker_points,
            tuple(tuple(h) for h in rnd.hands), tuple(rnd.buried),
            tuple(tuple((p.seat, tuple(p.cards)) for p in t.plays) for t in rnd.history),
            None if rnd.trick is None else tuple((p.seat, tuple(p.cards)) for p in rnd.trick.plays))


class Heads:
    def __init__(self, target=None):
        self.target = target
        self.prior_actions = None
        self.leaves = []

    def priors(self, rnd, seat, actions):
        self.prior_actions = [tuple(a) for a in actions]
        if self.target is None:
            return [1 / len(actions)] * len(actions)
        index = self.prior_actions.index(self.target)
        return [1.0 if i == index else 0.0 for i in range(len(actions))]

    def values(self, states):
        self.leaves.extend(states)
        return [2.0] * len(states)


def test_complete_prior_population_includes_off_ballot_and_preserves_input():
    rnd = play_state()
    seat = rnd.turn
    before = signature(rnd)
    production = make_bot("mc-s0-report-lcb", seed=3)._candidates(rnd, seat)
    legal = enumerate_legal(rnd, seat, cap=None)
    off = next(tuple(a) for a in legal.actions if a not in production)
    heads = Heads(off)
    bot = LearnedSearchBot(heads, config=SearchConfig(arm="prior"))
    rng_before = bot.rng.getstate()
    actions = bot._candidates(rnd, seat)
    assert set(map(tuple, actions)) == set(map(tuple, legal.actions))
    assert len(actions) == legal.count == len(heads.prior_actions)
    assert tuple(actions[0]) == tuple(production[0])
    prior = bot._root["priors"]
    assert prior[actions.index(list(off))] > .9
    assert all(p > 0 for p in prior)
    assert sum(prior) == pytest.approx(1)
    assert signature(rnd) == before
    assert bot.rng.getstate() == rng_before


def test_enumeration_overflow_refuses_instead_of_searching_a_prefix():
    rnd = play_state()
    bot = LearnedSearchBot(Heads(), config=SearchConfig(legal_limit=2))
    with pytest.raises(SearchError, match=r"^exhaustive legal set exceeds supported limit:"):
        bot.decide_play(rnd, rnd.turn)
    assert bot.search_calls == bot.rollouts == 0


@pytest.mark.parametrize("depth", [0, 1, 3])
def test_value_leaf_depth_team_conversion_and_sampled_hidden_world(depth):
    rnd = play_state()
    policy = HeuristicBot()
    seen_parities = set()
    heads = Heads()
    bot = LearnedSearchBot(heads, config=SearchConfig(arm="value", leaf_tricks=depth))
    # Four successive starting seats expose both same-team and opposing-team
    # next actors; sign is based on partnership, not ply depth.
    for _ in range(32):
        seat = rnd.turn
        before = signature(rnd)
        sampled = {s: list(h) for s, h in enumerate(rnd.hands) if s != seat}
        action = policy.decide_play(rnd, seat)
        initial_history = len(rnd.history)
        result = bot._selection_values(rnd, seat, sampled, list(rnd.buried), [action], None)
        leaf = heads.leaves[-1]
        same_team = leaf.turn % 2 == seat % 2
        seen_parities.add(same_team)
        assert result == [80.0 if same_team else -80.0]
        expected_tricks = depth if depth else int(len(rnd.trick.plays) == 3)
        assert len(leaf.history) == initial_history + expected_tricks
        assert signature(rnd) == before
        assert leaf is not rnd and leaf.hands is not rnd.hands
        rnd.play(seat, action)
        if seen_parities == {False, True}:
            break
    assert seen_parities == {False, True}


def test_true_hidden_twin_cannot_change_leaf_when_sampled_world_is_fixed():
    rnd = play_state()
    policy = HeuristicBot()
    rnd.play(rnd.turn, policy.decide_play(rnd, rnd.turn))
    seat = rnd.turn
    assert seat != rnd.banker
    sampled = {s: list(h) for s, h in enumerate(rnd.hands) if s != seat}
    buried = list(rnd.buried)
    twin = copy.deepcopy(rnd)
    hidden = next(s for s in range(4) if s != seat)
    i = next(i for i, c in enumerate(twin.hands[hidden]) if c != twin.buried[0])
    twin.hands[hidden][i], twin.buried[0] = twin.buried[0], twin.hands[hidden][i]
    heads = Heads()
    bot = LearnedSearchBot(heads, config=SearchConfig(arm="value"))
    action = policy.decide_play(rnd, seat)
    first = bot._selection_values(rnd, seat, sampled, buried, [action], None)
    first_leaf = signature(heads.leaves[-1])
    second = bot._selection_values(twin, seat, sampled, buried, [action], None)
    assert first == second
    assert first_leaf == signature(heads.leaves[-1])


def test_terminal_leaf_uses_engine_outcome_without_network():
    rnd = play_state()
    policy = HeuristicBot()
    while sum(map(len, rnd.hands)) > 4 or len(rnd.trick.plays) != 3:
        rnd.play(rnd.turn, policy.decide_play(rnd, rnd.turn))
    seat = rnd.turn
    heads = Heads()
    bot = LearnedSearchBot(heads, config=SearchConfig(arm="value"))
    action = policy.decide_play(rnd, seat)
    sampled = {s: list(h) for s, h in enumerate(rnd.hands) if s != seat}
    values = bot._selection_values(rnd, seat, sampled, list(rnd.buried), [action], None)
    truth = copy.deepcopy(rnd)
    truth.play(seat, action)
    assert values == [40 * terminal_utility(truth, seat % 2)]
    assert not heads.leaves
    assert bot.learned_counts["terminal_leaves"] == 1


def test_real_decision_keeps_production_report_and_records_actual_counts(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rnd = play_state()
    seat = rnd.turn
    legal = enumerate_legal(rnd, seat, cap=None)
    production = make_bot("mc-s0-report-lcb")._candidates(rnd, seat)
    target = next(tuple(a) for a in legal.actions if a not in production)
    heads = Heads(target)
    bot = LearnedSearchBot(heads, seed=13, config=SearchConfig(arm="both"))
    bot.N_DETERMINIZATIONS = 1
    bot.REPORT_FOLD_WORLDS = 30
    before = signature(rnd)
    result = bot.decide_play(rnd, seat)
    rec = bot.last_decision_record
    assert rec["report_fold"]["complete"]
    assert rec["report_fold"]["worlds"] == 30
    assert rec["work"]["report_rollouts"] == 60
    assert rec["learned_search"]["counts"]["full_rollout_calls"] == 60
    assert rec["learned_search"]["counts"]["value_evaluations"] == rec["alloc"]["budget"]
    assert rec["learned_search"]["counts"]["off_ballot_selections"] > 0
    assert rec["learned_search"]["legal_size"] == legal.count
    assert rec["learned_search"]["report_evaluator"] == "production full heuristic rollout, point units"
    assert rec["report_candidate_index"] != 0
    assert rec["played"] == result == rec["candidates"][rec["played_index"]]
    assert sum(rec["learned_search"]["allocation_visits"]) == rec["alloc"]["worlds"]
    assert rec["work"]["complete"]
    assert signature(rnd) == before


def test_incumbent_investigation_is_one_evaluation_not_a_duplicate_pair(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rnd = play_state()
    seat = rnd.turn
    incumbent = tuple(make_bot("mc-s0-report-lcb")._candidates(rnd, seat)[0])
    bot = LearnedSearchBot(Heads(incumbent), seed=13,
                           config=SearchConfig(arm="both", self_play=True,
                                               root_noise_fraction=0))
    bot.N_DETERMINIZATIONS = 4
    calls = []

    def evaluate(rnd, seat, hands, buried, actions, session):
        keys = [tuple(a) for a in actions]
        calls.append(keys)
        return [100.0 if key == incumbent else 0.0 for key in keys]

    monkeypatch.setattr(bot, "_selection_values", evaluate)
    bot.decide_play(rnd, seat)
    rec = bot.last_decision_record
    alloc, visits = rec["alloc"], rec["learned_search"]["allocation_visits"]
    assert visits[0] > 0
    assert all(len(keys) == len(set(keys)) for keys in calls)
    assert alloc["n_by_candidate"][0] == alloc["worlds"]
    assert sum(visits) == alloc["worlds"]
    assert sum(map(len, calls)) == alloc["budget"]
    assert 2 * sum(visits) - visits[0] + alloc["dummy_rollouts"] == alloc["budget"]
    assert rec["learned_search"]["allocation_visits"][rec["played_index"]] > 0


def test_self_play_explores_on_separate_stream_and_emits_visits(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rnd = play_state()
    seat = rnd.turn
    cfg = SearchConfig(arm="both", self_play=True)
    a, b = [LearnedSearchBot(Heads(), seed=42, config=cfg) for _ in range(2)]
    for bot in (a, b):
        bot.N_DETERMINIZATIONS = 1
    result_a = a.decide_play(rnd, seat)
    result_b = b.decide_play(rnd, seat)
    assert result_a == result_b
    assert a.rng.getstate() == b.rng.getstate()
    rec = a.last_decision_record
    assert rec["reason"] == "self_play_root_visits"
    assert rec["work"]["report_rollouts"] == 0
    assert rec["learned_search"]["counts"]["self_play_samples"] == 1
    assert len(set(rec["learned_search"]["priors"])) > 1
    assert rec["learned_search"]["allocation_visits"][rec["played_index"]] > 0


def test_value_only_keeps_production_candidate_population():
    rnd = play_state()
    bot = LearnedSearchBot(Heads(), config=SearchConfig(arm="value"))
    production = make_bot("mc-s0-report-lcb")._candidates(rnd, rnd.turn)
    assert bot._candidates(rnd, rnd.turn) == production


def test_bad_prior_cannot_enter_search():
    rnd = play_state()
    heads = Heads()
    heads.priors = lambda r, s, a: [float("nan")] * len(a)
    bot = LearnedSearchBot(heads)
    with pytest.raises(SearchError, match=r"^prior must normalize over the exact legal population$"):
        bot.decide_play(rnd, rnd.turn)


def test_paired_advantage_changes_allocation_and_final_challenger():
    """Raw candidate means and paired gaps disagree when worlds differ."""
    class ControlledBot(LearnedSearchBot):
        def __init__(self, config):
            super().__init__(Heads(), seed=9, config=config)
            self.N_DETERMINIZATIONS = 4
            self.world = 0
            self.controlled_candidates = None

        def _candidates(self, rnd, seat):
            self.controlled_candidates = [[rnd.hands[seat][i]] for i in range(3)]
            self._root = {
                "production_keys": {tuple(sorted(self.controlled_candidates[0]))},
                "production_size": 2,
                "production_would_search": True,
                "priors": [0.33, 0.34, 0.33],
                "visits": [0, 0, 0],
                "enumeration_secs": 0.0,
            }
            return self.controlled_candidates

        def _sample_hands(self, *args):
            self.world += 1
            return ({}, [])

        def _new_exact_world_session(self, *args):
            return None

        def _selection_values(self, rnd, seat, hands, buried, actions, exact_session):
            baseline = (-100.0, -100.0, -100.0, 0.0)[self.world - 1]
            out = []
            for action in actions:
                index = next(i for i, candidate in enumerate(self.controlled_candidates)
                             if candidate is action)
                out.append(baseline if index == 0 else (-30.0 if index == 1 else 0.0))
            return out

    rnd = play_state()
    seat = rnd.turn
    configs = [SearchConfig(arm="both", puct_scale=1.0, paired_advantage=flag)
               for flag in (False, True)]
    bots = [ControlledBot(config) for config in configs]
    for bot in bots:
        bot.REPORT_RULE = "none"
        bot.REPORT_FOLD_WORLDS = 0
        bot.MARGIN = 0.0
        bot.POINT_SHY_EPS = 0.0
        bot.decide_play(rnd, seat)

    raw, paired = [bot.last_decision_record for bot in bots]
    assert raw["learned_search"]["ranking_basis"] == "absolute_value_mean"
    assert paired["learned_search"]["ranking_basis"] == "paired_advantage"
    assert raw["learned_search"]["allocation_visits"] != paired["learned_search"]["allocation_visits"]
    assert raw["report_candidate_index"] == 2
    assert paired["report_candidate_index"] == 1
    assert paired["means"][0] == 0.0
    assert paired["means"][1] != raw["means"][1]


@pytest.mark.parametrize("value", [0, 1, 1.0, "true", None])
def test_paired_advantage_requires_strict_bool(value):
    with pytest.raises(ValueError, match="paired_advantage must be a bool"):
        SearchConfig(paired_advantage=value)

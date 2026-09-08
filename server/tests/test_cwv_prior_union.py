"""Witness the DEV value/public-prior candidate union."""
import copy
import numpy as np
import pytest

from shengji.ai.registry import REGISTRY
from shengji.ai.cwv_puct import PublicPriorHead
from shengji.ai.mcbot import MCBot
from shengji.harvest.legal import enumerate_legal
from shengji.train.cwv_prior_union import CWVPriorUnionBot
from shengji.train.cwv_shortlist import CWVShortlistBot, CWVShortlistConfig
from tests.test_cwv_shortlist import Values
from tests.test_world_shortlist import play_state, round_signature, tiny_model


class Prior:
    checkpoint_sha256 = "p" * 64

    def __init__(self, values):
        self.values = np.asarray(values, dtype=float)
        self.calls = []

    def probabilities(self, rnd, seat, actions):
        self.calls.append((rnd, seat, list(actions)))
        return self.values


def test_union_appends_distinct_prior_candidates_after_value_candidates():
    rnd = play_state()
    legal = enumerate_legal(rnd, rnd.turn, cap=None).actions
    production = REGISTRY["mc-s0-report-lcb"](seed=13)._candidates(rnd, rnd.turn)
    keys = [tuple(sorted(action)) for action in legal]
    base = keys.index(tuple(sorted(production[0])))
    value_order = sorted((i for i in range(len(legal)) if i != base),
                         key=lambda i: keys[i])
    value_set = set(value_order[:4])
    extras = [i for i in value_order if i not in value_set][:2]
    probabilities = np.full(len(legal), 0.0)
    probabilities[base] = 0.5
    probabilities[extras] = [0.3, 0.2]
    prior = Prior(probabilities)
    bot = CWVPriorUnionBot(
        Values(), prior, seed=13,
        config=CWVShortlistConfig(worlds=1, batch_size=17))
    bot._means = lambda r, s, actions, worlds: np.zeros(len(actions))
    chosen = bot._candidates(rnd, rnd.turn)
    assert len(chosen) == 7
    assert len({tuple(action) for action in chosen}) == 7
    assert prior.calls and len(prior.calls[0][2]) == len(legal)
    assert bot.last_shortlist["prior_union"]["value_alternatives"] == 4
    assert bot.last_shortlist["prior_union"]["added_prior_count"] == 2
    assert bot.last_shortlist["shortlist"] == chosen
    assert bot.last_shortlist["shortlist_indices"] == [base, *value_order[:4], *extras]
    assert bot.last_shortlist["prior_union"]["added_prior_indices"] == extras


def test_prior_only_candidate_reaches_real_mc_selection_report_and_play(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rnd = play_state()
    seat = rnd.turn
    original = round_signature(rnd)
    legal = enumerate_legal(rnd, seat, cap=None).actions
    production = REGISTRY["mc-s0-report-lcb"](seed=13)._candidates(rnd, seat)
    incumbent = tuple(sorted(production[0]))
    value_order = sorted((i for i, a in enumerate(legal) if tuple(a) != incumbent),
                         key=lambda i: tuple(legal[i]))
    target_index = value_order[-1]
    target = legal[target_index]
    probabilities = np.zeros(len(legal))
    probabilities[target_index] = 1.0
    bot = CWVPriorUnionBot(Values(), Prior(probabilities), seed=13,
                          config=CWVShortlistConfig(worlds=1, selection_worlds=2))
    bot.REPORT_FOLD_WORLDS = 30
    monkeypatch.setattr(bot, "_means", lambda r, s, actions, worlds: np.zeros(len(actions)))
    calls = []

    def rollout(r, s, hands, buried, action, **kwargs):
        calls.append(list(action))
        value = 100.0 if list(action) == target else 0.0
        return value if rnd.is_attacker(seat) else -value

    monkeypatch.setattr(bot, "_rollout", rollout)
    assert bot._decide_adaptive.__func__ is MCBot._decide_adaptive
    assert bot._report_fold_gap.__func__ is MCBot._report_fold_gap
    assert bot._report_rollout.__func__ is MCBot._report_rollout
    assert bot.decide_play(rnd, seat) == target
    record = bot.last_decision_record
    detail = record["cwv_shortlist"]
    assert record["candidates"] == detail["shortlist"]
    assert target in calls and target not in detail["shortlist"][1:5]
    assert target_index in detail["prior_union"]["added_prior_indices"]
    assert record["report_fold"]["complete"] is True
    assert record["report_fold"]["worlds"] == 30
    assert record["work"]["report_rollouts"] == 60
    assert detail["counts"]["shortlisted_actions"] == 7
    assert round_signature(rnd) == original


def test_overlap_skips_every_existing_candidate_and_ties_are_deterministic():
    actions = [["S2"], ["S3"], ["S4"], ["S5"], ["S6"]]
    # Incumbent and top value action dominate prior, but do not occupy extra slots.
    bot = CWVPriorUnionBot(Values(), Prior([0.5, 0.2, 0.1, 0.1, 0.1]),
                          config=CWVShortlistConfig(alternatives=1))
    state = bot.rng.getstate()
    assert bot._choose_alternatives(None, 0, actions, [0, 10, 9, 8, 7], 0) == [1, 2, 3]
    assert bot.rng.getstate() == state


def test_public_prior_hidden_twins_and_visible_positive_control():
    rnd = play_state()
    policy = REGISTRY["mc-s0-report-lcb"](seed=9)
    rnd.play(rnd.turn, policy.canonical_lead(rnd, rnd.turn))
    seat = rnd.turn
    assert seat != rnd.banker
    twin = copy.deepcopy(rnd)
    hidden = next(s for s in range(4) if s != seat and twin.hands[s])
    twin.hands[hidden][0], twin.buried[0] = twin.buried[0], twin.hands[hidden][0]
    actions = enumerate_legal(rnd, seat, cap=None).actions
    head = PublicPriorHead(None, model=tiny_model())
    obs, candidates = head.encode(rnd, seat, actions)
    twin_obs, twin_candidates = head.encode(twin, seat, actions)
    assert np.array_equal(obs, twin_obs)
    assert np.array_equal(candidates, twin_candidates)
    assert np.array_equal(head.probabilities(rnd, seat, actions),
                          head.probabilities(twin, seat, actions))
    visible = copy.deepcopy(rnd)
    index = next(i for i, c in enumerate(visible.hands[hidden]) if c != visible.hands[seat][0])
    visible.hands[seat][0], visible.hands[hidden][index] = (
        visible.hands[hidden][index], visible.hands[seat][0])
    assert not np.array_equal(obs, head.encode(visible, seat, actions)[0])


def test_singleton_clears_prior_metadata_and_does_not_call_prior():
    rnd = play_state()
    rnd.hands[rnd.turn] = rnd.hands[rnd.turn][:1]
    prior = Prior([1])
    bot = CWVPriorUnionBot(Values(), prior)
    bot._prior_union_detail = {"stale": True}
    assert len(bot._candidates(rnd, rnd.turn)) == 1
    assert bot._prior_union_detail is None
    assert "prior_union" not in bot.last_shortlist
    assert prior.calls == []


def test_default_hook_matches_original_inline_rule():
    actions = [["S4"], ["S2"], ["S3"], ["S5"]]
    means = [1.0, 0.0, 1.0, -1.0]
    bot = CWVShortlistBot(Values(), seed=13, config=CWVShortlistConfig(alternatives=2))
    rng = bot.rng.getstate()
    keys = [tuple(sorted(a)) for a in actions]
    old = sorted([0, 2, 3], key=lambda i: (-means[i], keys[i]))[:2]
    assert bot._choose_alternatives(None, 0, actions, means, 1) == old
    assert bot.rng.getstate() == rng


@pytest.mark.parametrize("bad", [[], [float("nan")], [0.5]])
def test_malformed_prior_refuses(bad):
    rnd = play_state()
    bot = CWVPriorUnionBot(Values(), Prior(bad))
    with pytest.raises(ValueError, match="probabilities"):
        bot._candidates(rnd, rnd.turn)


def test_absent_uniform_and_invalid_prior_width_refuse():
    with pytest.raises(ValueError, match="public prior head"):
        CWVPriorUnionBot(Values(), None)
    with pytest.raises(ValueError, match="uniform"):
        CWVPriorUnionBot(Values(), Prior([1]),
                         config=CWVShortlistConfig(uniform=True))
    with pytest.raises(ValueError, match="prior_count"):
        CWVPriorUnionBot(Values(), Prior([1]), prior_alternatives=0)

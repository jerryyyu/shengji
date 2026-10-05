import copy
import json

import numpy as np
import pytest

from shengji.eval.fixed_tape_policy import capture_policy_ranks
from shengji.train.pv_search_policy import PVSearchBot
from test_policy_world_search import state


def setup():
    root = state()
    seat = root.turn
    actions = [[c] for c in dict.fromkeys(root.hands[seat])]
    worlds = [(copy.deepcopy(root.hands), list(root.buried)) for _ in range(2)]
    bot = object.__new__(PVSearchBot)
    bot.version = 2
    bot.predict = lambda x: np.tile(np.arange(54), (len(x), 1))
    def forbidden(*args, **kwargs):
        raise AssertionError('sampling/value/admission forbidden')
    bot._worlds = bot._value_means = bot._leaf = bot._admit = forbidden
    return bot, root, seat, actions, worlds


def test_matches_canonical_scores_and_does_not_mutate_inputs():
    bot, root, seat, actions, worlds = setup()
    before = copy.deepcopy((root.hands, actions, worlds))
    expected = bot.scores(root, seat, actions, worlds).mean(axis=0)
    calls = []
    predict = bot.predict
    bot.predict = lambda x: calls.append(x.copy()) or predict(x)
    result = capture_policy_ranks(bot, root, seat, actions, worlds)
    assert len(calls) == 1
    assert result['preferences'] == expected.tolist()
    assert result['ranked_indices'] == sorted(range(len(actions)), key=lambda i: (-expected[i], i))
    assert (root.hands, actions, worlds) == before
    assert not result['provenance_verified']
    result['actions'][0].append('BJ')
    assert actions == before[1]


def test_ties_preserve_supplied_order():
    bot, root, seat, actions, worlds = setup()
    bot.predict = lambda x: np.zeros((len(x), 54))
    result = capture_policy_ranks(bot, root, seat, list(reversed(actions)), worlds)
    assert result['ranked_indices'] == list(range(len(actions)))


@pytest.mark.parametrize('damage', ['missing', 'extra', 'substitute', 'kitty'])
def test_nonconserving_tape_refuses_before_prediction(damage):
    bot, root, seat, actions, worlds = setup()
    other = (seat + 1) % 4
    hands, buried = worlds[-1]
    if damage == 'missing':
        hands[other].pop()
    elif damage == 'extra':
        hands[other].append(hands[other][0])
    elif damage == 'substitute':
        hands[other][0] = next(c for c in root.deck if c != hands[other][0])
    else:
        buried.pop()
    calls = []
    bot.predict = lambda x: calls.append(x) or np.zeros((len(x), 54))
    with pytest.raises(ValueError):
        capture_policy_ranks(bot, root, seat, actions, worlds)
    assert calls == []


def test_json_tape_with_completed_and_partial_tricks_keeps_order():
    from shengji.ai.heuristic import HeuristicBot

    bot, root, _, _, _ = setup()
    for _ in range(5):
        root.play(root.turn, HeuristicBot().decide_play(root, root.turn))
    assert root.history and root.trick.plays
    seat = root.turn
    actions = [[c] for c in dict.fromkeys(root.hands[seat])]
    worlds = json.loads(json.dumps([
        (copy.deepcopy(root.hands), root.buried),
        ([list(reversed(h)) for h in root.hands], list(reversed(root.buried))),
    ]))
    before = copy.deepcopy(worlds)
    expected = bot.scores(root, seat, actions, worlds).mean(axis=0).tolist()
    result = capture_policy_ranks(bot, root, seat, actions, worlds)
    assert result['preferences'] == expected
    assert worlds == before
    assert result['provenance_verified'] is False


def test_scores_use_supplied_worlds_not_live_hidden_hands():
    bot, root, seat, actions, worlds = setup()
    others = [s for s in range(4) if s != seat]
    worlds[1][0][others[0]], worlds[1][0][others[1]] = (
        worlds[1][0][others[1]], worlds[1][0][others[0]])
    seen = []
    def predict(x):
        seen.append(x.copy())
        return np.tile(np.arange(54), (len(x), 1))
    bot.predict = predict
    first = capture_policy_ranks(bot, root, seat, actions, worlds)
    root.hands[others[0]], root.hands[others[1]] = root.hands[others[1]], root.hands[others[0]]
    second = capture_policy_ranks(bot, root, seat, actions, worlds)
    assert first == second
    assert np.array_equal(seen[0], seen[1])
    assert not np.array_equal(seen[0][0], seen[0][1])


@pytest.mark.parametrize('failure', ['nan', 'shape', 'override', 'empty', 'actor', 'duplicate', 'seat'])
def test_invalid_inputs_or_predictions_refuse(failure):
    bot, root, seat, actions, worlds = setup()
    if failure == 'nan':
        bot.predict = lambda x: np.full((len(x), 54), np.nan)
    elif failure == 'shape':
        bot.predict = lambda x: np.zeros((len(x), 53))
    elif failure == 'override':
        bot.scores = lambda *a: np.zeros((2, len(actions)))
    elif failure == 'empty':
        worlds = []
    elif failure == 'actor':
        worlds[0][0][seat] = []
    elif failure == 'duplicate':
        actions.append(actions[0])
    else:
        seat = True
    with pytest.raises(ValueError):
        capture_policy_ranks(bot, root, seat, actions, worlds)


@pytest.mark.parametrize('expire_at', [1, 2])
def test_budget_expiry_before_or_after_prediction_returns_no_result(expire_at):
    args = setup()
    checks = []
    def budget():
        checks.append(1)
        if len(checks) == expire_at:
            raise TimeoutError('observation budget')
    with pytest.raises(TimeoutError):
        capture_policy_ranks(*args, check_budget=budget)

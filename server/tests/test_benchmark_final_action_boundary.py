import random

import pytest

from shengji.ai.env import prepare_round
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.luna.benchmark_games import play_mirror


@pytest.mark.parametrize('option', [{}, {'classify_final_action_failures': False}])
def test_default_semantic_rejection_remains_policy_error(option):
    game = Game(random.Random(733))
    prepare_round(game, [HeuristicBot() for _ in range(4)])
    row = play_mirror(game, flip=game.round.turn % 2, information='actor-only',
                      planner_factory=lambda seat: lambda packet: {'cards': [], 'memory': ''},
                      baseline_factory=lambda seat, seed: HeuristicBot(), seed=733, **option)
    assert row['error'] == 'ValueError: invalid planner cards or memory'
    assert not row['events']
    assert 'failure' not in row
    assert 'classify_final_action_failures' not in row


@pytest.mark.parametrize('option', [None, 0, 1, 'true'])
def test_final_action_option_requires_bool_before_factory_calls(option):
    def forbidden(*args):
        pytest.fail('invalid flag reached factory')
    with pytest.raises(ValueError, match='classify_final_action_failures must be bool'):
        play_mirror(None, flip=0, information='actor-only', planner_factory=forbidden,
                    baseline_factory=forbidden, seed=0, classify_final_action_failures=option)

@pytest.mark.parametrize('flip', [0, 1])
@pytest.mark.parametrize('information', ['actor-only', 'perfect'])
@pytest.mark.parametrize('cards', [[], ['NOT_A_CARD'], ['♠A'], [''], ['c3'],
                                  ['C3', 'NOT_A_CARD'], ['C3'] * 3, ['C3'] * 500])
def test_semantic_final_illegality_reaches_engine(cards, flip, information):
    game = Game(random.Random(733))
    prepare_round(game, [HeuristicBot() for _ in range(4)])
    row = play_mirror(game, flip=flip, information=information,
                      planner_factory=lambda seat: lambda packet: {'cards': cards, 'memory': ''},
                      baseline_factory=lambda seat, seed: HeuristicBot(), seed=733, classify_final_action_failures=True)
    assert row['complete'] is False
    assert row['error'].split(':', 1)[0] in {'IllegalPlay', 'KeyError', 'ValueError'}
    assert row['failure']['stage'] == 'engine_play'
    assert row['failure']['seat'] % 2 == flip
    assert row['events'][-1]['attempted_cards'] == cards
    assert row['failure']['category'] == 'model_illegal_action'
    assert row['failure']['schema'] == 'benchmark-action-failure-v1'
    assert row['failure']['event_index'] == len(row['events']) - 1
    assert 'signed_levels' not in row


@pytest.mark.parametrize('error', [KeyError('internal'), KeyError('C3'),
                                  ValueError('internal'), ValueError('play too large')])
def test_native_errors_on_valid_proposal_are_not_forfeits(error):
    from shengji.luna.benchmark_games import _native_action_rejection
    assert not _native_action_rejection(['C3'], ['C3'], error)


def test_native_classifier_does_not_mask_corrupt_hand_or_unrelated_error():
    from shengji.luna.benchmark_games import _native_action_rejection
    assert not _native_action_rejection(['BAD'], ['CORRUPT'], KeyError('BAD'))
    assert not _native_action_rejection(['BAD'], ['C3'], KeyError('internal'))
    assert not _native_action_rejection(['C3'] * 500, ['C3'], ValueError('internal'))


@pytest.mark.parametrize('hand', [None, 3, 'C3', [], [['C3']], ['C3'] * 3,
                                 ['C3'] * 129])
def test_corrupt_preplay_hand_stays_infrastructure_failure(hand):
    from shengji.luna.benchmark_games import _native_action_rejection
    assert not _native_action_rejection(['BAD'], hand, KeyError('BAD'))
    assert not _native_action_rejection(['C3'] * 500, hand, ValueError('play too large'))


@pytest.mark.parametrize('error', [KeyError('internal'), ValueError('play too large')])
def test_actual_engine_internal_error_with_valid_action_stops(monkeypatch, error):
    game = Game(random.Random(733))
    prepare_round(game, [HeuristicBot() for _ in range(4)])
    cards = HeuristicBot().decide_play(game.round, game.round.turn)
    flip = game.round.turn % 2
    def broken_play(self, seat, proposed):
        assert proposed == cards
        raise error
    monkeypatch.setattr(type(game.round), 'play', broken_play)
    row = play_mirror(game, flip=flip, information='actor-only',
                      planner_factory=lambda seat: lambda packet: {'cards': cards, 'memory': ''},
                      baseline_factory=lambda seat, seed: HeuristicBot(), seed=733, classify_final_action_failures=True)
    assert row['error'] == f'{type(error).__name__}: {error}'
    assert 'failure' not in row


def test_planner_error_is_not_final_engine_rejection():
    game = Game(random.Random(733))
    prepare_round(game, [HeuristicBot() for _ in range(4)])
    def broken_planner(packet):
        raise KeyError('NOT_A_CARD')
    row = play_mirror(game, flip=game.round.turn % 2, information='actor-only',
                      planner_factory=lambda seat: broken_planner,
                      baseline_factory=lambda seat, seed: HeuristicBot(), seed=733, classify_final_action_failures=True)
    assert not row['events']
    assert 'failure' not in row


@pytest.mark.parametrize('flip', [0, 1])
@pytest.mark.parametrize('cards', [['NOT_A_CARD'], ['C3'] * 500])
def test_baseline_native_rejection_is_never_model_forfeit(cards, flip):
    class BadBaseline(HeuristicBot):
        def decide_play(self, rnd, seat):
            return cards
    game = Game(random.Random(733))
    prepare_round(game, [HeuristicBot() for _ in range(4)])
    # Make the first acting seat a baseline; test both team assignments.
    game.round.turn = 1 - flip
    row = play_mirror(game, flip=flip, information='actor-only',
                      planner_factory=lambda seat: lambda packet: {'cards': [], 'memory': ''},
                      baseline_factory=lambda seat, seed: BadBaseline(), seed=733, classify_final_action_failures=True)
    assert not row['complete']
    assert 'failure' not in row


@pytest.mark.parametrize('reply', [
    {'cards': [1], 'memory': ''}, {'cards': 'C3', 'memory': ''},
    {'cards': [], 'memory': None}, {'cards': []},
    {'cards': [], 'memory': '', 'extra': True},
])
def test_malformed_final_reply_still_stops_campaign(reply):
    game = Game(random.Random(733))
    prepare_round(game, [HeuristicBot() for _ in range(4)])
    row = play_mirror(game, flip=0, information='actor-only',
                      planner_factory=lambda seat: lambda packet: reply,
                      baseline_factory=lambda seat, seed: HeuristicBot(), seed=733, classify_final_action_failures=True)
    assert row['complete'] is False
    assert row['error'].startswith('ValueError:')
    assert 'failure' not in row

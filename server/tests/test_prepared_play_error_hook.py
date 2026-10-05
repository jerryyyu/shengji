"""Prepared-round error diagnostics must coexist with committed-play observers."""
from types import SimpleNamespace

import pytest

from shengji.ai.env import play_prepared_round


def setup(*, engine_error=None, policy_error=None, observer_error=None):
    events = []
    rnd = SimpleNamespace(phase='play', turn=0, last_trick=None,
                          trump_rank='2', banker=0)

    def play(seat, cards):
        events.append(('play', seat, cards))
        if engine_error is not None:
            raise engine_error
        rnd.phase = 'done'

    def decide(rnd, seat):
        if policy_error is not None:
            raise policy_error
        return ['S2']

    def observe(rnd):
        events.append('observed')
        if observer_error is not None:
            raise observer_error

    rnd.play = play
    game = SimpleNamespace(round=rnd, finish_round=lambda: SimpleNamespace(
        attacker_points=0, winner_team=0, level_change=3))
    policies = [SimpleNamespace(decide_play=decide, observe_public=observe)
                for _ in range(4)]
    return game, policies, events


@pytest.mark.parametrize('callback_error', [None, RuntimeError('callback'), KeyboardInterrupt()])
def test_engine_error_preserved_and_not_observed_as_committed(callback_error):
    original = ValueError('engine rejected')
    game, policies, events = setup(engine_error=original)
    calls = []

    def hook(seat, cards, exc):
        calls.append((seat, cards, exc))
        if callback_error is not None:
            raise callback_error

    with pytest.raises(ValueError) as caught:
        play_prepared_round(game, policies, on_play_error=hook)
    assert caught.value is original
    assert calls == [(0, ['S2'], original)]
    assert events == [('play', 0, ['S2'])]


def test_success_notifies_all_policies_without_error_callback():
    game, policies, events = setup()
    calls = []
    result = play_prepared_round(game, policies, on_play_error=lambda *a: calls.append(a))
    assert calls == []
    assert events == [('play', 0, ['S2'])] + ['observed'] * 4
    assert result.attacker_points == 0


@pytest.mark.parametrize('stage', ['policy_error', 'observer_error'])
def test_non_engine_errors_do_not_trigger_hook(stage):
    original = RuntimeError(stage)
    game, policies, _ = setup(**{stage: original})
    calls = []
    with pytest.raises(RuntimeError) as caught:
        play_prepared_round(game, policies, on_play_error=lambda *a: calls.append(a))
    assert caught.value is original
    assert calls == []

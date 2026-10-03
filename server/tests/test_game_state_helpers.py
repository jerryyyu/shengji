"""Shared setup must remain deterministic and never share mutable game state."""
import pickle
import random

from game_state_helpers import state_after


def test_state_after_is_deterministic_without_touching_global_rng():
    rng_before = random.getstate()
    first = state_after(41, 25)
    second = state_after(41, 25)
    assert pickle.dumps(first) == pickle.dumps(second)
    assert random.getstate() == rng_before


def test_state_after_returns_independent_nested_mutable_state():
    first = state_after(41, 25)
    second = state_after(41, 25)
    before = pickle.dumps(second)
    assert first is not second
    assert first.history is not second.history
    assert first.hands is not second.hands
    assert all(a is not b for a, b in zip(first.hands, second.hands))
    first.hands[0].clear()
    first.history.clear()
    assert pickle.dumps(second) == before


def test_state_after_stops_at_terminal_instead_of_playing_extra_actions():
    terminal = state_after(41, 100)
    assert terminal.phase == "round_end"
    assert pickle.dumps(terminal) == pickle.dumps(state_after(41, 200))

"""Natural, outcome-blind R4 policy-root selection witnesses."""

from __future__ import annotations

from shengji.ai.mcbot import MCBot
from shengji.rl import belief_policy_population as population
from shengji.rl.belief_capture import CHAMPION_POLICY
from shengji.rl.belief_policy_protocol import policy_round_coordinates


class _FastPolicy(MCBot):
    N_DETERMINIZATIONS = 1
    REQUIRE_EXACT_WORK = False
    REPORT_FOLD_WORLDS = 0
    REPORT_RULE = "none"


def _fast_make_bot(name: str, **kwargs):
    assert name == CHAMPION_POLICY
    bot = _FastPolicy(seed=kwargs.get("seed"))
    bot.policy_name = name
    return bot


def test_natural_root_is_contested_replayable_and_hash_selected(
        monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(population, "make_bot", _fast_make_bot)
    coordinate = policy_round_coordinates()[0]
    root = population.select_natural_policy_root(coordinate)
    assert root is not None
    population.validate_selected_policy_root(root)
    assert root.coordinate == coordinate
    assert len(root.candidates) >= 2
    assert root.round_state.turn == root.actor_seat
    assert root.actor.trump_rank == coordinate.trump_rank


def test_root_selection_does_not_depend_on_hidden_true_world_bytes(
        monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(population, "make_bot", _fast_make_bot)
    root = population.select_natural_policy_root(
        policy_round_coordinates()[1])
    assert root is not None
    original_key = root.selection_key
    hidden = [seat for seat in range(4) if seat != root.actor_seat]
    left, right = next(
        (left, right) for index, left in enumerate(hidden)
        for right in hidden[index + 1:]
        if len(root.round_state.hands[left])
        == len(root.round_state.hands[right]))
    root.round_state.hands[left], root.round_state.hands[right] = (
        root.round_state.hands[right], root.round_state.hands[left])
    # Selection identity is already bound solely to the public actor and
    # decision index. The hidden mutation changes neither input.
    assert root.selection_key == original_key

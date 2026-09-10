from collections import Counter
from copy import deepcopy
from dataclasses import replace
import random

import pytest

from shengji.ai.smart import SmartBot
from shengji.engine.cards import make_deck
from shengji.engine.round import Round
from shengji.train.declare_completion import (
    PublicDeclaration, baseline_action, build_sampled_prefix,
    capture_observation, sample_completion_deck,
)


def public_prefix():
    rnd = Round('7', None, random.Random(91))
    for index, card in enumerate(('S7', 'LJ', 'BJ', 'H7', 'S7', 'LJ', 'BJ')):
        source = rnd.deck.index(card, index)
        rnd.deck[index], rnd.deck[source] = rnd.deck[source], rnd.deck[index]
    rnd.kitty = rnd.deck[100:]
    history = []
    for pos in range(1, 80):
        rnd.deal_next()
        action = {1: (0, ('S7',)), 5: (0, ('S7', 'S7')), 6: (1, ('LJ', 'LJ'))}.get(pos)
        if action:
            seat, cards = action
            rnd.declare(seat, list(cards))
            history.append(PublicDeclaration(seat, cards, pos))
    return rnd, tuple(history)


def test_sampled_engine_prefix_preserves_cards_sizes_reveals_and_options():
    rnd, history = public_prefix()
    obs = capture_observation(rnd, 2, history)
    assert obs.options == (('BJ', 'BJ'),)
    decks = set()
    for seed in range(24):
        sampled = build_sampled_prefix(obs, seed)
        decks.add(tuple(sampled.deck))
        assert Counter(sampled.deck) == Counter(make_deck())
        assert Counter(sampled.hands[2]) == Counter(rnd.hands[2])
        assert [len(h) for h in sampled.hands] == [20, 20, 20, 19]
        assert sampled._deal_pos == 79 and sampled.phase == 'deal'
        assert sampled.declaration == rnd.declaration
        assert sampled.declare_options(2) == rnd.declare_options(2)
        for event in history:
            seen_hand = Counter(sampled.deck[event.seat:event.deal_pos:4])
            assert not Counter(event.cards)-seen_hand
        assert sampled.hands[0].count('S7') == 2  # Overwritten evidence retained.
        assert sampled.hands[1].count('LJ') == 2
    assert len(decks) == 24
    assert tuple(rnd.deck) not in decks


def test_hidden_twins_and_future_deck_changes_leave_actual_samples_identical():
    rnd, history = public_prefix()
    twin = deepcopy(rnd)
    # Swap unrevealed private cards, preserve capacities and every public fact.
    first = next(i for i, c in enumerate(twin.hands[0]) if c != 'S7')
    second = next(i for i, c in enumerate(twin.hands[3]) if c != twin.hands[0][first])
    twin.hands[0][first], twin.hands[3][second] = twin.hands[3][second], twin.hands[0][first]
    twin.deck[4*first], twin.deck[4*second+3] = twin.deck[4*second+3], twin.deck[4*first]
    twin.deck[79:] = reversed(twin.deck[79:])
    twin.kitty = twin.deck[100:]
    a = capture_observation(rnd, 2, history)
    b = capture_observation(twin, 2, history)
    assert a == b
    for seed in (8, 19):
        assert build_sampled_prefix(a, seed).deck == build_sampled_prefix(b, seed).deck
    # Positive control: changing a visible card changes the samples.
    modified = deepcopy(rnd)
    removed = modified.hands[2][0]
    donor = next(i for i, c in enumerate(modified.hands[3]) if c != removed
                 and modified.hands[2].count(c) == 0 and not c.endswith('7'))
    modified.hands[2][0], modified.hands[3][donor] = modified.hands[3][donor], removed
    modified.deck[2], modified.deck[4*donor+3] = modified.deck[4*donor+3], removed
    changed = capture_observation(modified, 2, history)
    assert changed != a
    assert sample_completion_deck(a, 8) != sample_completion_deck(changed, 8)


def test_capture_and_baseline_cannot_read_hidden_round_channels():
    rnd, history = public_prefix()
    expected_options = rnd.declare_options(2)
    expected_action = SmartBot().decide_declare(rnd, 2)
    class Hands:
        def __getitem__(self, seat):
            assert seat == 2, 'hidden hand accessed'
            return rnd.hands[2]
    class VisibleOnly:
        phase, trump_rank, banker = rnd.phase, rnd.trump_rank, rnd.banker
        _deal_pos, declaration, passed = rnd._deal_pos, rnd.declaration, rnd.passed
        hands = Hands()
        def declare_options(self, seat):
            assert seat == 2
            return expected_options
        def __getattr__(self, name):
            raise AssertionError(f'hidden round attribute accessed: {name}')
    obs = capture_observation(VisibleOnly(), 2, history)
    assert baseline_action(obs) == (None if expected_action is None else tuple(expected_action))
    assert build_sampled_prefix(obs, 7).declare_options(2) == expected_options


def test_missing_history_and_invalid_physical_or_timing_evidence_refused():
    rnd, history = public_prefix()
    with pytest.raises(ValueError, match='public history does not match'):
        capture_observation(rnd, 2, ())
    obs = capture_observation(rnd, 2, history)
    with pytest.raises(ValueError, match='strengths must strictly increase'):
        sample_completion_deck(replace(obs, shown=(*history, history[-1])), 1)
    with pytest.raises(ValueError, match='shown cards exceed hand capacity'):
        sample_completion_deck(replace(obs, shown=(PublicDeclaration(0, ('S7', 'S7'), 1),)), 1)
    with pytest.raises(ValueError, match='physical population'):
        sample_completion_deck(replace(obs, own_hand=('LJ',)*20), 1)
    with pytest.raises(ValueError, match='callback'):
        sample_completion_deck(replace(obs, final=True), 1)
    with pytest.raises(ValueError, match='reproduce actor hand/legal options'):
        build_sampled_prefix(replace(obs, options=(('S7',),)), 1)


def test_own_shown_copy_is_not_double_counted_on_later_pair():
    rnd, history = public_prefix()
    rnd.deal_next()
    rnd.deal_next()
    obs = capture_observation(rnd, 0, history)
    for seed in range(8):
        sampled = build_sampled_prefix(obs, seed)
        assert Counter(sampled.hands[0]) == Counter(rnd.hands[0])
        assert sampled.deck[0] == 'S7' and sampled.deck[4] == 'S7'
        assert sum(c == 'S7' for c in sampled.deck) == 2


def test_actual_counterfactual_consumer_is_hidden_twin_identical():
    from shengji.train.declare_completion_evaluation import evaluate_actions
    from shengji.train.declare_completion_screen import digest
    rnd, history = public_prefix()
    twin = deepcopy(rnd)
    twin.deck[79:] = reversed(twin.deck[79:])
    twin.kitty = twin.deck[100:]
    def score(completed, *, focal_team, seed):
        assert completed.phase == 'bury'
        assert sorted(map(len, completed.hands)) == [25, 25, 25, 33]
        assert Counter(c for h in completed.hands for c in h) == Counter(make_deck())
        return {'focal_signed_levels': 1 if completed.trump_is_nt else -1,
                'world': digest(completed.deck), 'seed': seed, 'focal_team': focal_team}
    first = evaluate_actions(capture_observation(rnd, 2, history), seeds=(17, 23), evaluator=score)
    second = evaluate_actions(capture_observation(twin, 2, history), seeds=(17, 23), evaluator=score)
    assert first == second

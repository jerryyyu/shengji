import copy
from dataclasses import asdict
import json

import pytest

from shengji.engine.round import actual_play_after
from shengji.eval.s11_public_view import public_s11_fixture
from shengji.eval.s11_reconstruction import reconstruct_s11_trajectory
from shengji.eval.public_refusal_history import public_root_with_ledger
from shengji.eval.tactical import TacticalError, public_round
from shengji.engine.cards import card_suit, make_deck
from shengji.harvest.legal import enumerate_legal
from shengji.harvest.rebuild import deck_from_seed, round_from_setup


@pytest.fixture(scope='module')
def trajectory():
    deck = deck_from_seed('2', 0, 17)
    declarer = deck[:100].index('C2') % 4
    setup = {'trump_rank': '2', 'banker': 0,
             'declarations': [{'seat': declarer, 'cards': ['C2']}],
             'trump_suit': 'C', 'trump_is_nt': False, 'buried': deck[-8:]}
    rnd = round_from_setup(deck, setup)
    rows, prefix = [], []
    for ply in range(100):
        seat = rnd.turn
        action = ['S10', 'S4'] if ply == 0 else enumerate_legal(rnd, seat, cap=1).actions[0]
        previous = rnd.last_trick
        rnd.play(seat, action)
        actual = actual_play_after(rnd, seat, previous)
        rows.append({'ply': ply, 'deck': list(deck), 'round_seed': 17,
                     'setup': copy.deepcopy(setup), 'source_ref': f'run:0:0:{seat}:{ply}',
                     'decision_kind': 'play', 'seat': seat, 'action': list(action),
                     'engine_play': actual, 'plays_prefix': copy.deepcopy(prefix)})
        prefix.append({'seat': seat, 'cards': actual})
    assert rnd.phase == 'round_end'
    return rows


@pytest.mark.parametrize('ply', [0, 1, 4, 21, 98])
def test_public_projection_only_exports_actor_information(trajectory, ply):
    before = copy.deepcopy(trajectory)
    fixture = public_s11_fixture(trajectory, ply, root_id='opaque-case')
    real = reconstruct_s11_trajectory(trajectory, ply)
    assert sorted(fixture.hand) == sorted(real['root'].hands[fixture.seat])
    assert len(fixture.plays) == ply
    assert fixture.observed == {}
    assert fixture.source == {'kind': 's11-public-projection', 'cadence': 'per-seat-decision'}
    if fixture.seat == fixture.setup['banker']:
        assert sorted(fixture.setup['buried']) == sorted(real['root'].buried)
    else:
        assert fixture.setup['buried'] is None
    serialized = json.dumps(fixture.to_json())
    for private_key in ('"deck"', '"round_seed"', '"source_ref"', '"hands"',
                        '"outcome"', '"action_values"', '"plays_prefix"'):
        assert private_key not in serialized
    assert trajectory == before


def test_failed_throw_and_actor_cadence_survive_public_conversion(trajectory):
    selected = next(i for i in range(1, len(trajectory)) if trajectory[i]['seat'] == 0)
    real = reconstruct_s11_trajectory(trajectory, selected)
    assert len(real['ledger'].refusals) == 1
    fixture = public_s11_fixture(trajectory, selected, root_id='case')
    assert fixture.plays[0]['attempted'] == ['S10', 'S4']
    assert fixture.plays[0]['cards'] == trajectory[0]['engine_play']
    for fill_seed in (0, 31):
        root, ledger, receipt = public_root_with_ledger(
            fixture, mode='history-primed', fill_seed=fill_seed)
        assert receipt['retained_refusals'] == [asdict(r) for r in real['ledger'].refusals]
        assert ledger.key == tuple(root.deck)
        assert root.deck != real['root'].deck


def test_labels_and_private_metadata_cannot_enter_fixture(trajectory):
    other = copy.deepcopy(trajectory)
    for row in other:
        row.update(outcome={'signed_levels': 999}, action_values=[-999],
                   private_note='SECRET_SENTINEL')
    a = public_s11_fixture(trajectory, 21, root_id='case')
    b = public_s11_fixture(other, 21, root_id='case')
    assert a.to_json() == b.to_json()
    assert 'SECRET_SENTINEL' not in json.dumps(b.to_json())


def test_future_terminal_validation_is_not_skipped(trajectory):
    with pytest.raises(ValueError, match='terminally truncated'):
        public_s11_fixture(trajectory[:-1], 0, root_id='case')


def test_kitty_flip_preserves_failed_throw_projection(trajectory):
    other = copy.deepcopy(trajectory)
    for row in other:
        row['setup']['declarations'] = []
    selected = next(i for i in range(1, len(other)) if other[i]['seat'] == 0)
    real = reconstruct_s11_trajectory(other, selected)
    fixture = public_s11_fixture(other, selected, root_id='case')
    for fill_seed in (0, 31):
        _, _, receipt = public_root_with_ledger(fixture, mode='history-primed', fill_seed=fill_seed)
        assert receipt['retained_refusals'] == [asdict(r) for r in real['ledger'].refusals]


@pytest.fixture(scope='module', params=['C', 'D', 'H', 'S'])
def undeclared_trajectory(request):
    seed, deck = next((seed, deck) for seed in range(100)
                      for deck in [deck_from_seed('2', 0, seed)]
                      if next(card_suit(c) for c in deck[-8:] if card_suit(c)) == request.param)
    setup = {'trump_rank': '2', 'banker': 0, 'declarations': [],
             'trump_suit': request.param, 'trump_is_nt': False, 'buried': deck[-8:]}
    rnd = round_from_setup(deck, setup)
    rows, prefix = [], []
    for ply in range(100):
        seat = rnd.turn
        action = enumerate_legal(rnd, seat, cap=1).actions[0]
        previous = rnd.last_trick
        rnd.play(seat, action)
        actual = actual_play_after(rnd, seat, previous)
        rows.append({'ply': ply, 'deck': list(deck), 'setup': copy.deepcopy(setup),
                     'round_seed': seed,
                     'source_ref': f'synthetic:0:0:{seat}:{ply}',
                     'decision_kind': 'play', 'seat': seat, 'action': list(action),
                     'engine_play': actual, 'plays_prefix': copy.deepcopy(prefix)})
        prefix.append({'seat': seat, 'cards': actual})
    assert rnd.phase == 'round_end'
    return rows


@pytest.mark.parametrize('ply', [0, 1, 2, 3, 21, 98])
def test_undeclared_public_state_all_suits_and_seats(undeclared_trajectory, ply):
    before = copy.deepcopy(undeclared_trajectory)
    actual = reconstruct_s11_trajectory(undeclared_trajectory, ply)['root']
    fixture = public_s11_fixture(undeclared_trajectory, ply, root_id='undeclared')
    assert fixture.setup['declarations'] == []
    assert fixture.setup['buried'] is None or fixture.seat == actual.banker
    for fill_seed in (0, 17, 31):
        root = public_round(fixture, fill_seed=fill_seed)
        assert root.declaration is None
        assert root.trump_suit == actual.trump_suit
        assert root.trump_is_nt is False
        assert sorted(root.hands[root.turn]) == sorted(actual.hands[actual.turn])
        assert root.banker == actual.banker
        assert root.history == actual.history
        assert root.trick == actual.trick
        assert sorted(root.deck) == sorted(make_deck())
    assert undeclared_trajectory == before


def test_undeclared_nt_remains_an_explicit_refusal(undeclared_trajectory):
    fixture = public_s11_fixture(undeclared_trajectory, 1, root_id='case')
    fixture.setup.update(trump_suit=None, trump_is_nt=True)
    with pytest.raises(TacticalError, match='impossible undeclared trump'):
        public_round(fixture)


def test_public_flip_cannot_invent_a_card_outside_unseen_pool(trajectory):
    fixture = public_s11_fixture(trajectory, 3, root_id='impossible')
    fixture.seat = 3
    fixture.setup.update(banker=0, declarations=[], buried=None,
                         trump_suit='C', trump_is_nt=False)
    fixture.hand = [c for c in make_deck() if card_suit(c) == 'C']
    fixture.hand.remove('C2')
    fixture.plays = [{'seat': 0, 'cards': ['D3']},
                     {'seat': 1, 'cards': ['C2']},
                     {'seat': 2, 'cards': ['D4']}]
    # All clubs are actor-known or played by another non-banker; none can
    # have been in the banker's original kitty. Do not steal an actor card.
    with pytest.raises(TacticalError, match='no unseen card'):
        public_round(fixture)


@pytest.mark.parametrize('kwargs', [{'root_id': ''}, {'root_id': 'x', 'fill_seed': True}])
def test_invalid_projection_arguments_refuse(trajectory, kwargs):
    with pytest.raises(ValueError):
        public_s11_fixture(trajectory, 0, **kwargs)

import copy
from dataclasses import asdict
import json

import pytest

from shengji.engine.round import actual_play_after
from shengji.eval.s11_public_view import public_s11_fixture
from shengji.eval.s11_reconstruction import reconstruct_s11_trajectory
from shengji.eval.public_refusal_history import public_root_with_ledger
from shengji.eval.tactical import TacticalError
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


def test_unsupported_kitty_flip_is_explicit_not_a_private_fallback(trajectory):
    other = copy.deepcopy(trajectory)
    for row in other:
        row['setup']['declarations'] = []
    with pytest.raises(TacticalError, match='kitty-flipped'):
        public_s11_fixture(other, 0, root_id='case')


@pytest.mark.parametrize('kwargs', [{'root_id': ''}, {'root_id': 'x', 'fill_seed': True}])
def test_invalid_projection_arguments_refuse(trajectory, kwargs):
    with pytest.raises(ValueError):
        public_s11_fixture(trajectory, 0, **kwargs)

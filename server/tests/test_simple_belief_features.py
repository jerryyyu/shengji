from collections import Counter
from copy import deepcopy
import random

import numpy as np

from shengji.ai.smart import SmartBot
from shengji.engine.round import Round
from shengji.rl.encode import CARD_INDEX
from shengji.train.simple_belief_features import actor_features, ownership_targets, FEATURE_DIM


def round_fixture(seed=4):
    rnd = Round('2', 0, random.Random(seed))
    while rnd.phase == 'deal':
        rnd.deal_next()
    option = rnd.declare_options(0)[0]
    rnd.declare(0, option)
    rnd.finalize_declare()
    shown = set(option)
    bury = [c for c in rnd.hands[0] if c in shown]
    rest = list(rnd.hands[0])
    for c in bury:
        rest.remove(c)
    bury += rest[:8-len(bury)]
    rnd.bury(0, bury)
    rnd.play(0, [rnd.hands[0][0]])
    return rnd


def test_banker_declared_card_can_be_buried_not_pinned_to_hand():
    rnd = round_fixture()
    code = rnd.declaration['cards'][0]
    assert code in rnd.buried and code not in rnd.hands[0]
    features, allowed = actor_features(rnd, 1)
    labels = ownership_targets(rnd, 1)
    assert features.shape == (FEATURE_DIM,)
    assert allowed.shape == (4, 54, 3)
    banker_receiver = (0-1) % 4-1
    assert allowed[banker_receiver, CARD_INDEX[code], 0]
    assert allowed[3, CARD_INDEX[code], 1]
    assert np.take_along_axis(allowed, labels[..., None], axis=-1).all()


def test_hidden_twins_change_labels_not_features_or_masks():
    rnd = round_fixture()
    twin = deepcopy(rnd)
    a = twin.hands[2][0]
    j = next(i for i, c in enumerate(twin.hands[3]) if c != a)
    twin.hands[2][0], twin.hands[3][j] = twin.hands[3][j], a
    twin.deck.reverse()  # A hidden reconstruction key is not an inference input.
    first, second = actor_features(rnd, 1), actor_features(twin, 1)
    for a, b in zip(first, second):
        np.testing.assert_array_equal(a, b)
    assert not np.array_equal(ownership_targets(rnd, 1), ownership_targets(twin, 1))
    # Move a hidden buried card into the banker's remaining hand as a separate twin.
    other = deepcopy(rnd)
    other.buried[0], other.hands[0][0] = other.hands[0][0], other.buried[0]
    for a, b in zip(first, actor_features(other, 1)):
        np.testing.assert_array_equal(a, b)
    # The banker DOES know this difference, and the exact kitty target is masked in.
    fa, ma = actor_features(rnd, 0)
    fb, mb = actor_features(other, 0)
    assert not np.array_equal(fa, fb)
    assert not np.array_equal(ma[3], mb[3])
    np.testing.assert_array_equal(ma[3].sum(axis=-1), np.ones(54))
    assert np.take_along_axis(ma, ownership_targets(rnd, 0)[..., None], axis=-1).all()


def test_actual_features_do_not_read_hidden_cards_or_call_target_builder(monkeypatch):
    import shengji.train.simple_belief_features as features
    rnd = round_fixture()
    class SizeOnly:
        def __init__(self, n): self.n = n
        def __len__(self): return self.n
        def __iter__(self): raise AssertionError('hidden card iteration')
    class Hands:
        def __getitem__(self, seat):
            assert seat == 1, 'hidden hand indexed'
            return rnd.hands[1]
        def __iter__(self):
            return iter([SizeOnly(len(h)) for h in rnd.hands])
    class ActorView:
        hands = Hands()
        def __getattr__(self, name):
            assert name not in ('deck', 'buried', 'kitty', 'rng'), f'hidden {name} read'
            return getattr(rnd, name)
    def forbidden(*args, **kwargs):
        raise AssertionError('target constructor called during inference')
    monkeypatch.setattr(features, 'ownership_targets', forbidden)
    expected = actor_features(rnd, 1)
    actual = actor_features(ActorView(), 1)
    for a, b in zip(expected, actual):
        np.testing.assert_array_equal(a, b)


def test_masks_admit_true_targets_through_whole_round_and_exclude_played_cards():
    rnd = round_fixture()
    bot = SmartBot()
    rows = void_cells = absent_cells = 0
    while rnd.phase == 'play':
        seat = rnd.turn
        x, mask = actor_features(rnd, seat)
        target = ownership_targets(rnd, seat)
        assert np.take_along_axis(mask, target[..., None], axis=-1).all()
        assert np.isfinite(x).all()
        absent = target.sum(axis=0) == 0
        assert mask[:, absent, 0].all() and not mask[:, absent, 1:].any()
        absent_cells += int(absent.sum())
        void_cells += int((mask.sum(axis=-1) == 1).sum())
        rnd.play(seat, bot.decide_play(rnd, seat))
        rows += 1
    assert rows > 20 and void_cells > 0 and absent_cells > 0

"""Synthetic PV admission witness for the opt-in tractor reservation."""

from types import SimpleNamespace

import numpy as np

from shengji.engine.cards import Ordering
from shengji.train.policy_value_search import PolicyValueBot


class _Evaluator:
    pass


def _round(*, follow=False):
    return SimpleNamespace(
        ordering=Ordering("H", "7"),
        trick=SimpleNamespace(plays=[object()] if follow else []),
    )


def _actions():
    return [
        ["C2"],                         # heuristic anchor
        ["S9"], ["D9"], ["C10"],       # policy-ranked non-tractors
        ["S3", "S3", "S4", "S4"],      # omitted pure tractor
    ]


def _bot(**kwargs):
    return PolicyValueBot(lambda *_: None, evaluator=_Evaluator(), candidates=4,
                          **kwargs)


def test_default_admission_keeps_byte_compatible_ranked_prefix():
    rnd, actions = _round(), _actions()
    preferences = np.asarray([0.0, 4.0, 3.0, 2.0, 1.0])
    bot = _bot()
    chosen = bot._admit(rnd, 0, actions, preferences, anchor_index=0)
    assert chosen == [0, 1, 2, 3]


def test_opt_in_reserves_one_pure_tractor_without_widening_or_moving_anchor():
    rnd, actions = _round(), _actions()
    preferences = np.asarray([0.0, 4.0, 3.0, 2.0, 1.0])
    bot = _bot(tractor_reservation=True)
    chosen = bot._admit(rnd, 0, actions, preferences, anchor_index=0)
    assert chosen == [0, 1, 2, 4]
    assert chosen[0] == 0 and len(chosen) == 4 and len(set(chosen)) == 4


def test_reservation_does_not_change_follow_admission():
    rnd, actions = _round(follow=True), _actions()
    preferences = np.asarray([0.0, 4.0, 3.0, 2.0, 1.0])
    plain = _bot()._admit(rnd, 0, actions, preferences, anchor_index=0)
    reserved = _bot(tractor_reservation=True)._admit(
        rnd, 0, actions, preferences, anchor_index=0)
    assert plain == reserved == [0, 1, 2, 3]


def test_existing_tractor_is_not_replaced_or_duplicated():
    rnd, actions = _round(), _actions()
    actions[2] = actions[4]
    preferences = np.asarray([0.0, 4.0, 3.0, 2.0, 1.0])
    bot = _bot(tractor_reservation=True)
    chosen = bot._admit(rnd, 0, actions, preferences, anchor_index=0)
    assert chosen == [0, 1, 2, 3]
    assert len(chosen) == len(set(chosen)) == 4


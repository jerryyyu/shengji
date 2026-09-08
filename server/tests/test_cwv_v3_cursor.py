"""Encoder-v3 relative next-to-act cursor contracts."""

from __future__ import annotations

import copy
import random

import numpy as np
import pytest

from shengji.ai import cwv_static_encoding as static
from shengji.ai.smart import SmartBot
from shengji.engine.game import Game
from shengji.rl.encode_versions import (OBS_DIM_BY_VERSION, OBS_SCHEMA_BY_VERSION,
                                         encode_obs)
from shengji.rl import value_afterstate_v2 as afterstate


def _play_state(plies: int = 4):
    game = Game(random.Random(109))
    rnd = game.start_round()
    bot = SmartBot()
    while rnd.phase == "deal":
        rnd.deal_next()
    for seat in range(4):
        cards = bot.decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    for _ in range(plies):
        rnd.play(rnd.turn, bot.decide_play(rnd, rnd.turn))
    return rnd


def test_v3_declares_width_schema_and_appends_cursor():
    rnd = _play_state()
    seat = rnd.turn
    v2 = encode_obs(rnd, seat, version=2)
    v3 = encode_obs(rnd, seat, version=3)
    assert OBS_DIM_BY_VERSION == {1: 531, 2: 560, 3: 564}
    assert OBS_SCHEMA_BY_VERSION[3] == "rl-observation-v3-relative-cursor"
    assert v3[:560] == v2
    assert v3[560:564] == [1.0, 0.0, 0.0, 0.0]

    for root in range(4):
        row = encode_obs(rnd, root, version=3)
        assert row[560 + (rnd.turn - root) % 4] == 1.0


def test_v3_rejects_malformed_live_cursor_and_zeros_terminal():
    rnd = _play_state()
    for bad in (None, True, -1, 4, 1.0, "1"):
        mutant = copy.deepcopy(rnd)
        mutant.turn = bad
        with pytest.raises(ValueError, match="v3 live-play turn"):
            encode_obs(mutant, 0, version=3)

    while rnd.phase == "play":
        rnd.play(rnd.turn, SmartBot().decide_play(rnd, rnd.turn))
    assert rnd.turn is None
    assert encode_obs(rnd, 0, version=3)[560:564] == [0.0] * 4


def test_v3_reference_and_static_rows_match_including_terminal():
    rnd = _play_state(4)
    checked = 0
    while rnd.phase == "play":
        for root in range(4):
            reference = afterstate.tensors_from_round(rnd, root, version=3)
            fast = static.tensors_from_round_static(rnd, root, version=3)
            assert reference.public.shape == (565,)
            assert np.array_equal(reference.public, fast.public)
            assert np.array_equal(reference.world, fast.world)
            assert np.array_equal(reference.perspective, fast.perspective)
            checked += 1
        rnd.play(rnd.turn, SmartBot().decide_play(rnd, rnd.turn))
    assert checked > 100
    reference = afterstate.tensors_from_round(rnd, 0, version=3)
    fast = static.tensors_from_round_static(rnd, 0, version=3)
    assert np.array_equal(reference.public, fast.public)
    assert np.all(reference.public[560:564] == 0.0)


def test_v3_cursor_uses_public_turn_not_hidden_hands():
    rnd = _play_state(4)
    root = (rnd.banker + 1) % 4
    others = [s for s in range(4) if s != root]
    twin = copy.deepcopy(rnd)
    a, b = others[:2]
    twin.hands[a], twin.hands[b] = twin.hands[b], twin.hands[a]
    # Same public information, different hidden complete world.
    assert encode_obs(twin, root, version=3) == encode_obs(rnd, root, version=3)
    changed = copy.deepcopy(rnd)
    changed.turn = (rnd.turn + 1) % 4
    original = encode_obs(rnd, root, version=3)
    altered = encode_obs(changed, root, version=3)
    assert altered[:560] == original[:560]
    assert altered[560:] != original[560:]


def test_v3_public_packing_roundtrips_cursor_without_changing_v2():
    from shengji.train.data import obs_layout_for
    rnd = _play_state(4)
    rows = np.asarray([encode_obs(rnd, root, version=3) for root in range(4)],
                      dtype=np.float32)
    layout = obs_layout_for(3)
    packed = layout.pack(rows)
    restored = layout.unpack(**packed)
    assert np.array_equal(restored, rows)

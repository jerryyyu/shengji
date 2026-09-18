"""Encoder v6: the banker's burial removed from the unseen pool (#477, Jerry 2026-09-17).

The hazard these tests exist for was MEASURED, not imagined: checkpoint dispatch is by width, so
a corrected net emitted at v2's 560 columns is indistinguishable from a plain v2 net and would be
served the uncorrected plane -- 8 of 54 unseen columns wrong on every banker decision, with no
width mismatch and no version disagreement.  Receipt:
~/shengji-archive/2026-09-13/readouts/kitty-serve-mismatch-probe.txt
"""
import random

import pytest

from shengji.ai.memory import Memory
from shengji.ai.smart import SmartBot
from shengji.engine.game import Game
from shengji.rl.encode import N_CARDS, _counts
from shengji.rl.encode_versions import OBS_DIM_BY_VERSION, encode_obs, encoder_version_for
from shengji.rl.encode_banker_kitty_corrected import UNSEEN, correct_in_place
from shengji.rl.value_afterstate_v2 import widen_to
from shengji.rl.value_afterstate import tensors_from_round as v1_tensors

#: v5's appended block is [kitty_known, 54 kitty columns, kitty_points]
V5_KITTY_PLANE = slice(OBS_DIM_BY_VERSION[2] + 1, OBS_DIM_BY_VERSION[2] + 1 + N_CARDS)


def _banker_round(seed, plays=6):
    game = Game(random.Random(seed))
    rnd = game.start_round()
    while rnd.phase == "deal":
        rnd.deal_next()
    bot = SmartBot()
    for s in range(4):
        c = bot.decide_declare(rnd, s, final=True)
        if c:
            rnd.declare(s, c)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    for _ in range(plays):
        rnd.play(rnd.turn, bot.decide_play(rnd, rnd.turn))
    return rnd


def test_every_encoder_width_is_unique_so_dispatch_cannot_collide():
    """THE reason v6 is 561 and not 560.  A checkpoint states its width; if two versions share
    one, a net is served the wrong encoder silently."""
    widths = OBS_DIM_BY_VERSION
    assert len(set(widths.values())) == len(widths), f"width collision: {widths}"
    assert widths[6] == 561 and encoder_version_for(561) == 6
    assert encoder_version_for(560) == 2, "v6 must not answer to v2's width"


@pytest.mark.parametrize("seed", [20260917, 7, 991])
def test_v6_unseen_plane_is_the_pool_the_world_sampler_actually_draws(seed):
    """The whole point: the net's input stops contradicting the worlds the search scores."""
    rnd = _banker_round(seed)
    seat = rnd.banker
    v6 = encode_obs(rnd, seat, version=6)
    assert v6[UNSEEN] == _counts(Memory(rnd, seat, own_kitty=True).unseen.elements())
    v2 = encode_obs(rnd, seat, version=2)
    assert v2[UNSEEN] != v6[UNSEEN], "v2 already correct? then the bug is gone and v6 is moot"
    differing = sum(1 for a, b in zip(v2[UNSEEN], v6[UNSEEN]) if abs(a - b) > 1e-9)
    assert differing == len(set(rnd.buried)), "one column per distinct buried card"


@pytest.mark.parametrize("seed", [20260917, 7, 991])
def test_v6_from_a_v5_row_equals_v6_encoded_directly(seed):
    """TRAIN/SERVE AGREEMENT, and the reason one v5 extract can feed this arm.

    Training derives v6 by subtracting v5's kitty plane from a stored v5 row; serving encodes v6
    live.  If those two disagree the net is trained on one input and played on another -- exactly
    the failure the width choice is meant to make impossible.  Pin that they agree EXACTLY.
    """
    rnd = _banker_round(seed)
    for seat in range(4):
        v5 = encode_obs(rnd, seat, version=5)
        derived = correct_in_place(list(v5[:OBS_DIM_BY_VERSION[2]]), list(v5[V5_KITTY_PLANE]))
        derived.append(v5[OBS_DIM_BY_VERSION[2]])          # v5's kitty_known IS v6's flag
        assert derived == encode_obs(rnd, seat, version=6), f"seat {seat} disagrees"


@pytest.mark.parametrize("seed", [20260917, 991])
def test_a_non_banker_seat_is_v2_plus_the_flag_and_nothing_moves(seed):
    """Only the banker has a burial to remove; every other seat must be untouched."""
    rnd = _banker_round(seed)
    for seat in range(4):
        if seat == rnd.banker:
            continue
        v6 = encode_obs(rnd, seat, version=6)
        assert v6[:OBS_DIM_BY_VERSION[2]] == encode_obs(rnd, seat, version=2)
        assert v6[-1] == 0.0, "kitty_known must be 0 for a non-banker"


def test_widen_to_refuses_v6_rather_than_returning_an_uncorrected_vector():
    """widen_to rebuilds any version >= 2 as 'v1 tensor + appended columns'.  For v6 that would
    silently keep the UNCORRECTED plane and still pass every width and identity check."""
    rnd = _banker_round(20260917)
    v1 = v1_tensors(rnd, rnd.banker)
    for version in (2, 5):
        widen_to(v1, rnd, rnd.banker, version)             # these round-trip fine
    with pytest.raises(ValueError, match="cannot be widened"):
        widen_to(v1, rnd, rnd.banker, 6)


def test_correct_in_place_refuses_a_plane_that_does_not_contain_the_burial():
    """If the offsets are ever wrong the subtraction goes negative; fail rather than clamp."""
    rnd = _banker_round(20260917)
    obs = list(encode_obs(rnd, rnd.banker, version=2))
    with pytest.raises(ValueError, match="offsets are wrong"):
        correct_in_place(obs, [1.0] * N_CARDS)
    with pytest.raises(ValueError, match="54 columns"):
        correct_in_place(obs, [0.0] * 3)

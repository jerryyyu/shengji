"""Encoder v6 is published but the TENSOR layer cannot produce it (#493 follow-up).

Found while staging a v6 cache on perf, and reproduced there before being written down:
``prepare_stores(..., version=6)`` -- the trainer's own cache path -- dies with v6's refusal.

    prepare_stores -> ensure_caches -> build_caches -> tensors_from_round -> widen_to
    ValueError: encoder v6 corrects the v1 unseen plane and cannot be widened from a v1
    tensor; encode it directly with encode_obs(..., version=6)

``value_afterstate_v2.tensors_from_round`` widens UNCONDITIONALLY::

    version = check_version(version)
    return widen_to(_tensors_from_round_v1(rnd, root_seat), rnd, root_seat, version)

and ``widen_to`` refuses v6 on purpose, because v6 corrects bytes INSIDE the v1 block (the
unseen plane at 432:486), so "v1 tensor + appended columns" would hand back an uncorrected
vector that still passes every width and identity check.  The refusal is right.  What is
missing is the alternative: there is no direct-encode branch in the tensor layer, so every
consumer that reaches tensors through ``tensors_from_round`` -- which is the trainer, and
therefore ``--encoder-version 6`` end to end -- cannot build a v6 tensor at all.

WHY THE EXISTING SUITE DOES NOT CATCH THIS.  The v6 tests exercise ``encode_obs`` directly and
pin the v5-row -> v6 derivation.  Both are true and both still pass.  Neither goes through
``tensors_from_round``, which is the only route the trainer takes -- the same shape as the
registration gaps muse caught on #493: published in the tables the tests read, absent from the
path the work takes.

This test is xfail(strict=True) DELIBERATELY.  It fails today, which is the point; when the
tensor layer learns to encode v6 directly it will XPASS, and strict mode turns that into a CI
failure so the marker has to be removed along with the fix.  It is a placeholder for a defect,
not a disabled test.
"""
import random

import pytest

from shengji.ai.smart import SmartBot
from shengji.engine.game import Game
from shengji.rl.encode_versions import OBS_DIM_BY_VERSION, encode_obs
from shengji.rl.value_afterstate_v2 import public_dim, tensors_from_round


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


def test_the_tensor_layer_can_build_v2_today():
    """The control: v2 goes through the same call and works, so a v6 failure is about v6."""
    rnd = _banker_round(20260919)
    t = tensors_from_round(rnd, rnd.banker, version=2)
    assert t.public.shape[-1] == public_dim(2) == 561


@pytest.mark.xfail(strict=True, reason="v6 has no direct-encode path in the tensor layer; "
                                       "tensors_from_round widens unconditionally and widen_to "
                                       "refuses v6. Remove this marker with the fix.")
@pytest.mark.parametrize("seed", [20260919, 7])
def test_the_tensor_layer_can_build_v6(seed):
    """What the trainer needs and cannot get: a v6 tensor, corrected, at v6's width.

    Asserted against ``encode_obs(..., version=6)`` rather than against a constant, so the test
    pins AGREEMENT WITH THE ENCODER and not a number I typed.
    """
    rnd = _banker_round(seed)
    seat = rnd.banker
    t = tensors_from_round(rnd, seat, version=6)
    assert t.public.shape[-1] == public_dim(6) == 562
    obs = encode_obs(rnd, seat, version=6)
    assert len(obs) == OBS_DIM_BY_VERSION[6] == 561
    assert list(t.public[:OBS_DIM_BY_VERSION[6]]) == list(obs), \
        "the tensor layer's v6 block must equal what the encoder emits directly"

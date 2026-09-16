"""Exact input contract for history-free prior admission."""
import random

import numpy as np
import pytest
from tests.test_cwv_numpy_joint import joint  # noqa: F401

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.train import policy_prior as pp


@pytest.mark.parametrize("seed", [3, 19, 41])
def test_all_seats_opening_follow_lead_and_terminal(seed):
    rnd = Game(random.Random(seed)).start_round()
    bot = HeuristicBot()
    while rnd.phase != "play":
        if rnd.phase == "deal":
            rnd.deal_next()
        elif rnd.phase == "declare":
            rnd.finalize_declare()
        else:
            rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    while True:
        for seat in range(4):
            expected = pp.flat_input(pp.root_tensors(rnd, seat))
            actual = pp.root_flat_input(rnd, seat)
            assert actual.dtype == expected.dtype
            assert actual.tobytes() == expected.tobytes()
        if rnd.phase == "round_end":
            break
        rnd.play(rnd.turn, bot.decide_play(rnd, rnd.turn))


def test_nonopening_does_not_call_reference_root_builder(monkeypatch):
    from tests.test_policy_prior import _round_in_play
    rnd = _round_in_play(3, plays=5)
    expected = pp.flat_input(pp.root_tensors(rnd, rnd.turn))
    def forbidden(*args, **kwargs):
        raise AssertionError("unused history builder called")
    monkeypatch.setattr(pp, "root_tensors", forbidden)
    np.testing.assert_array_equal(pp.root_flat_input(rnd, rnd.turn), expected)


def test_hidden_hands_and_kitty_swaps():
    from tests.test_policy_prior import _round_in_play
    from shengji.train.cwv_prior_admission import root_clone
    rnd = _round_in_play(41, plays=17)
    seat = rnd.turn
    hands = [list(hand) for hand in rnd.hands]
    buried = list(rnd.buried)
    other = (seat + 1) % 4
    hands[other][0], buried[0] = buried[0], hands[other][0]
    swapped = root_clone(rnd, hands, buried)
    for actor in range(4):
        expected = pp.flat_input(pp.root_tensors(swapped, actor))
        assert pp.root_flat_input(swapped, actor).tobytes() == expected.tobytes()


def test_joint_numpy_admission_pool_matches_reference(joint, monkeypatch):
    import hashlib
    from tests.test_policy_prior import _round_in_play
    from tests.test_cwv_shortlist import Values
    from shengji.train.cwv_prior_admission import CWVPriorAdmissionBot, CWVPriorAdmissionConfig
    from shengji.train.cwv_shortlist import CWVShortlistConfig
    _, _, package, _ = joint
    with open(package, "rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    optimized = pp.root_flat_input
    for plies in (0, 5, 17, 60):
        rnd = _round_in_play(41, plies)
        results = []
        for builder in (lambda r, s: pp.flat_input(pp.root_tensors(r, s)), optimized):
            monkeypatch.setattr(pp, "root_flat_input", builder)
            bot = CWVPriorAdmissionBot(
                Values(), seed=13, config=CWVShortlistConfig(worlds=2),
                prior=CWVPriorAdmissionConfig(checkpoint=package,
                                             checkpoint_sha256=digest, threshold=4, top=8))
            assert bot._prior_kind == "joint-numpy"
            selected = bot._candidates(rnd, rnd.turn)
            # Compare every decision/score field; wall clocks necessarily differ.
            bot.last_shortlist.pop("wall_seconds")
            bot.last_shortlist.get("prior_admission", {}).pop("prior_seconds", None)
            results.append((selected, bot.last_shortlist))
        assert results[0] == results[1]

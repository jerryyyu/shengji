"""Fixed-root checks for the three picks and the action committed to the game."""
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from shengji.train import pv_search_policy as pv

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server/tests"))
from test_pv_exact_follow import eight_card_last_seat, predict, ZeroEvaluator
import paired


def bot_for_fixture():
    bot = pv.PVSearchBot(predict, evaluator=ZeroEvaluator(), version=2,
        config=pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=64, candidates=8,
                                 cap=4000, serving_budget_seconds=3, exact_follow=True,
                                 exact_follow_max_cards=7, exact_follow_solver="compact-level",
                                 exact_follow_anytime_eight=True),
        checkpoint="/dev/null", seed=7)
    bot._worlds = lambda rnd, seat, check: ([(rnd.hands, rnd.buried)] * 64, 64)
    bot.scores = lambda rnd, seat, actions, worlds: np.zeros((len(worlds), len(actions)))
    bot._value_means = lambda rnd, seat, actions, worlds, check: (np.arange(len(actions)), 1)
    return bot


def test_same_root_references_commit_and_finish():
    rnd = eight_card_last_seat()
    bots = [bot_for_fixture() for _ in range(4)]
    result = paired.play_deal(rnd, bots)
    row, = result["eligible"]
    assert result["decisions"] == 5 and rnd.phase == "round_end"
    assert row["worlds"] == 64 and not row["full_censored"]
    assert row["seat"] == 3 and row["abandoned"] is None
    assert len(row["pi_attacker_points"]) == len(row["admitted"])
    assert sorted(rnd.history[0].plays[-1].cards) == sorted(row["admitted"][row["served"]])
    assert row["pi_attacker_points"][row["served"]] == result["attacker_points"]


def test_timed_out_full_reference_keeps_other_picks(monkeypatch):
    rnd = eight_card_last_seat()
    tick = iter([0., 21.])
    monkeypatch.setattr(paired, "process_time", lambda: next(tick, 21.))
    cards, row = paired.paired_play(bot_for_fixture(), rnd, rnd.turn)
    assert row["full_censored"] and row["full"] is None
    assert cards == row["admitted"][row["served"]]
    assert 0 <= row["arm"] < len(row["pi_attacker_points"])


def test_base_fallback_cannot_disappear_from_denominator():
    rnd = eight_card_last_seat()
    bot = SimpleNamespace(exact_follow_anytime_eight=True, serving_budget_seconds=3,
                          _value_means=None, decide_play=lambda *_: [],
                          last_decision_record={"work_complete": False})
    with pytest.raises(ValueError, match="incomplete eight-card decision"):
        paired.paired_play(bot, rnd, rnd.turn)


def test_a_different_arm_pick_does_not_steer_the_deal(monkeypatch):
    from dataclasses import replace
    from shengji.train import pv_exact_follow

    original = pv_exact_follow.rerank_eight_card_follow

    def choose_other(*args, **kwargs):
        result = original(*args, **kwargs)
        other = next(i for i in result.retained if i != kwargs["baseline_index"])
        return replace(result, winner=other)

    monkeypatch.setattr(pv_exact_follow, "rerank_eight_card_follow", choose_other)
    rnd = eight_card_last_seat()
    result = paired.play_deal(rnd, [bot_for_fixture() for _ in range(4)])
    row, = result["eligible"]
    assert row["arm"] != row["served"]
    assert sorted(rnd.history[0].plays[-1].cards) == sorted(row["admitted"][row["served"]])

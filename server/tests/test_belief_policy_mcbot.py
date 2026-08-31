"""Production-search seam behavior-preservation witnesses."""

from __future__ import annotations

from shengji.ai.mcbot import MCBot, point_shy_pick_index
from shengji.ai.registry import make_bot


def test_public_point_shy_seam_is_the_production_picker():
    bot = make_bot("mc-s0-report-lcb", seed=17)
    assert isinstance(bot, MCBot)
    candidates = [["S5"], ["H10"], ["D5"]]
    means = [2.0, 2.4, 2.1]
    expected = point_shy_pick_index(
        candidates, means, (0, 1, 2), epsilon=bot.POINT_SHY_EPS)
    assert bot._pick_index(candidates, means, (0, 1, 2)) == expected


def test_decide_play_consumes_search_entry_early_pick(monkeypatch):
    bot = make_bot("mc-s0-report-lcb", seed=17)
    assert isinstance(bot, MCBot)
    # This test pins the new wiring at the production caller; unit-testing only
    # _search_entry would not catch a future decide_play bypass.
    monkeypatch.setattr(bot, "_search_entry", lambda rnd, seat: (None, ["S5"]))

    class FakeRound:
        trick = object()
        ordering = object()

    assert bot.decide_play(FakeRound(), 0) == ["S5"]  # type: ignore[arg-type]

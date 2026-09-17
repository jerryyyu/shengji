"""The admission prior's per-decision diagnostics reach the room log (#419).

The prior has always built a diagnostic dict per decision, but nothing carried it
off the machine: production room logs record timings and nothing about admission,
so "how much of the wide tail does the threshold actually prune in live play, and
does top-N ever clip the played action" was unanswerable from `/data/logs`.

Two properties are load-bearing here.  First, a BELOW-threshold decision now also
leaves a diagnostic, so the log can show how often the prior nearly fired and not
only what it did when it fired.  Second, because of that, `triggered` -- not the
mere presence of a dict -- is what marks a shortlist as prior-admitted; treating
presence as proof would claim a fully evaluated legal population had been pruned.
"""
from __future__ import annotations

import types

import pytest

from shengji.api.server import _log_bot_timing
from shengji.train.cwv_prior_admission import CWVPriorAdmissionBot
from shengji.train.cwv_shortlist import CWVShortlistConfig
from tests.test_cwv_prior_admission import prior_ckpt, recipe  # noqa: F401
from tests.test_cwv_shortlist import Values
from tests.test_world_shortlist import play_state


def test_below_threshold_records_the_legal_count_without_claiming_admission(prior_ckpt):
    rnd = play_state()
    bot = CWVPriorAdmissionBot(Values(), seed=13, prior=recipe(prior_ckpt, threshold=10 ** 9),
                               config=CWVShortlistConfig(worlds=2))
    bot._candidates(rnd, rnd.turn)
    d = bot._prior_diagnostics
    assert d is not None and d["triggered"] is False
    assert d["legal_count"] == bot.last_shortlist["legal_count"] and d["threshold"] == 10 ** 9
    # the shortlist detail must be untouched: the full population WAS evaluated
    assert "prior_admission" not in bot.last_shortlist
    assert bot.last_shortlist.get("full_legal_world_means_complete") is not False
    assert bot.last_shortlist.get("ranking_basis") != "prior-union-then-world-mean"
    assert bot.shortlist_counts["prior_decisions"] == 0


def test_above_threshold_records_the_pool_and_still_marks_the_shortlist(prior_ckpt):
    rnd = play_state()
    seat = rnd.turn
    bot = CWVPriorAdmissionBot(Values(), seed=13, prior=recipe(prior_ckpt, threshold=1, top=8),
                               config=CWVShortlistConfig(worlds=2))
    bot._candidates(rnd, seat)
    d = bot._prior_diagnostics
    assert d["triggered"] is True
    assert d["legal_count"] >= d["pool_action_count"] >= d["union_size"] >= 1
    assert bot.last_shortlist["prior_admission"] is d
    assert bot.last_shortlist["full_legal_world_means_complete"] is False


def _prepared(bot_copy, phase="play"):
    snapshot = types.SimpleNamespace(seat=2, phase=phase, mode="bot", bot_copy=bot_copy)
    return types.SimpleNamespace(decision=types.SimpleNamespace(snapshot=snapshot),
                                 compute_seconds=1.25, pacing_seconds=0.0, turn_seconds=1.25)


class _Room:
    def __init__(self):
        self.events = []

    def log_event(self, name, **fields):
        self.events.append((name, fields))


@pytest.mark.parametrize("triggered", [True, False])
def test_the_room_log_carries_the_prior_fields(triggered):
    diagnostic = ({"triggered": True, "legal_count": 4312, "union_size": 271,
                   "anchors_added": 2, "pool_action_count": 273, "pool_evaluations": 8736,
                   "prior_seconds": 0.0421, "recipe": {"threshold": 1000, "top": 256}}
                  if triggered else
                  {"triggered": False, "legal_count": 37, "threshold": 1000})
    bot = types.SimpleNamespace(policy_name="mc-shortlist-test", _prior_diagnostics=diagnostic)
    room = _Room()
    _log_bot_timing(room, _prepared(bot), acted=True)
    (name, f), = room.events
    assert name == "bot_timing"
    assert f["prior_triggered"] is triggered
    assert f["prior_threshold"] == 1000            # from either shape
    assert f["prior_legal_count"] == diagnostic["legal_count"]
    if triggered:
        assert f["prior_pool_actions"] == 273 and f["prior_union_size"] == 271
        assert f["prior_anchors_added"] == 2 and f["prior_pool_evaluations"] == 8736
        assert f["prior_seconds"] == pytest.approx(0.0421)
    else:
        # nothing was pruned, so no pool figures may be implied
        assert not any(k.startswith("prior_pool") or k == "prior_union_size" for k in f)


def test_a_bury_turn_never_reports_the_previous_play_turn_s_admission():
    """The room keeps the bot between turns; the dict must not leak across phases.

    `room.bot = snapshot.bot_copy`, and `decide_bury` never resets
    `_prior_diagnostics`, so on a bury turn the attribute still holds whatever the
    last PLAY decision measured.  Logging that under phase="bury" would put a
    number in the record that was never measured for that decision.
    """
    stale = {"triggered": True, "legal_count": 4312, "union_size": 271,
             "anchors_added": 2, "pool_action_count": 273, "pool_evaluations": 8736,
             "prior_seconds": 0.0421, "recipe": {"threshold": 1000, "top": 256}}
    bot = types.SimpleNamespace(policy_name="mc-shortlist-test", _prior_diagnostics=stale,
                                last_bury_record=None)
    room = _Room()
    _log_bot_timing(room, _prepared(bot, phase="bury"), acted=True)
    (_, f), = room.events
    assert f["phase"] == "bury"
    assert not any(k.startswith("prior_") for k in f)

    # the same bot on a play turn still reports, so this scopes rather than disables
    room2 = _Room()
    _log_bot_timing(room2, _prepared(bot, phase="play"), acted=True)
    (_, g), = room2.events
    assert g["prior_triggered"] is True and g["prior_pool_actions"] == 273


def test_a_bot_without_a_prior_adds_no_prior_fields():
    bot = types.SimpleNamespace(policy_name="mc-s0-report-lcb")
    room = _Room()
    _log_bot_timing(room, _prepared(bot), acted=True)
    (_, f), = room.events
    assert not any(k.startswith("prior_") for k in f)
    assert f["compute_seconds"] == 1.25

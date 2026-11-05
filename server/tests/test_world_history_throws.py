"""The history test's accepted-throw form (``world_history_throws``, ``wht``), OFF BY DEFAULT.

A multi-component lead that stood says no other hand then could beat any of
its components.  With ``SHENGJI_PV_WORLD_HISTORY_THROWS=1`` (which needs
``SHENGJI_PV_WORLD_HISTORY_LEGAL=1``) the history-legal draw rejects a world in
which such a throw would have been refused (`ai.history_legality.throw_events`).
Off, the draw, its record and release 50's name and decisions are main's
(`test_r50_flag_off_parity`).  On, at ADKY round 3 (seat 2's D7 D7 DA throw at
trick 11 stood; a world giving seat 0 the DJ pair would have refused it) no
checked world contradicts the throw, and at trick 12 the served bot's lead
changes to the card the true deal prices better for it.

Correctness and identity witnesses only, not a strength claim.
"""
import json

import pytest

import r50_flag_positions as P
from shengji.ai import history_legality as hl
from shengji.ai.endgame import _clone_for_play
from shengji.ai.endgame_compact import CompactWorldSession
from shengji.ai.mcbot import MCBot
from shengji.ai.memory import Memory
from shengji.train import pv_search_policy as pv
from test_release46_fly_config import fly_env
from test_release50_fly_config import (BELIEF_SHA, BELIEF_VOLUME_PATH, PRIOR_SHA,  # noqa: F401
                                       PRIOR_VOLUME_PATH, RELEASE50, VALUE_SHA, VALUE_VOLUME_PATH,
                                       release50_packages, served_bot)

FLAG = "SHENGJI_PV_WORLD_HISTORY_THROWS"
#: release 50 with this rule on
WHT50 = ("pv-search-f4f4127e-prior-1fa201b2-w64-k8-div-rc-whl-whd-wht-bw-tb-ele-la-dtr-dtrx-vd-"
         "vdef-lgf-lgfx-lgfd2000-ed7-xf7-xfcompactlevel-lcc32-r8da389e2-bury-hybrid-bwv-bbw-"
         "d97f8e2fd5bc-sc8")
THROW = ("D7", "D7", "DA")
#: the lead after the throw where the rule changes the served pick
AFTER_THROW = ("ADKY3", 12, 0)
#: main's pick there (`test_r50_flag_off_parity`)
PINNED_PICK = json.loads(P.PINNED.read_text())["decisions"][P.label(*AFTER_THROW)]["cards"]


def dj_pair_world(rnd):
    """The true hands with seat 3's DJ moved to seat 0 (for its S5): seat 0
    then holds the DJ pair, which beats the D7 pair of the throw."""
    hands = [list(h) for h in rnd.hands]
    hands[0][hands[0].index("S5")], hands[3][hands[3].index("DJ")] = "DJ", "S5"
    return hands


def attacker_points(rnd, seat, action) -> int:
    child = _clone_for_play(rnd)
    child.play(seat, list(action))
    if child.phase == "round_end":
        return child.attacker_points
    return CompactWorldSession(rnd, max_hand_cards=7, max_nodes=50_000_000,
                               alpha_beta=True).solve(child).attacker_points


def names(monkeypatch, extra):
    from shengji.ai import cwv_policy

    by_path = {VALUE_VOLUME_PATH: VALUE_SHA, PRIOR_VOLUME_PATH: PRIOR_SHA,
               BELIEF_VOLUME_PATH: BELIEF_SHA}
    monkeypatch.setattr(cwv_policy, "checkpoint_id", lambda path: by_path[str(path)][:8])
    monkeypatch.setattr(pv, "file_sha256", lambda path: by_path[str(path)])
    return list(pv.singleton_registry_entries(**pv.pv_env_recipe({**fly_env(), **extra})))


def draw(rnd, seed, **kw):
    """The served history-legal draw (``-whl -whd``) for the acting seat."""
    seat = rnd.turn
    sampler = MCBot(seed=seed)
    mem = Memory(rnd, seat, own_kitty=getattr(sampler, "BANKER_KITTY", True))
    return hl.sample_worlds_history_legal(sampler, rnd, seat, 64, (), mem=mem, constrain=True, **kw)


def test_throw_events_are_the_accepted_throws_only():
    rnd = P.replay("ADKY3", 11, 1)
    event, = hl.throw_events(rnd)
    assert (event.seat, event.cards, event.trick) == (2, THROW, 10)
    # what each seat played from that trick on: so far only the throw
    assert event.later == ((), (), THROW, ())
    later = hl.throw_events(P.replay("ADKY3", 13, 0))
    assert [(e.seat, e.cards, e.trick) for e in later] == [(2, THROW, 10)]
    # tricks 11 and 12: three cards to the throw's trick, one to the next
    assert [len(cards) for cards in later[0].later] == [4, 4, 4, 4]
    assert later[0].later[2][:3] == THROW
    # SDUS round 2: the throws of tricks 4 and 7, not its pairs or tractor
    sdus = hl.throw_events(P.replay("SDUS2", 14, 0))
    assert [(e.trick, e.cards) for e in sdus] == [(3, ("SA", "SQ", "SQ")),
                                                 (6, ("S10", "S6", "S9", "SJ"))]
    # WJLB round 2: the refused throw of trick 16 is on record as its forced DK
    assert all(e.trick != 15 for e in hl.throw_events(P.replay("WJLB2", 17, 0)))


def test_true_deal_passes_and_the_dj_pair_world_fails():
    rnd = P.replay("ADKY3", 11, 1)
    throws = hl.throw_events(rnd)
    assert hl.first_throw_violation(throws, rnd.hands, rnd.ordering) is None
    assert hl.first_throw_violation(throws, dj_pair_world(rnd), rnd.ordering) == 0
    assert hl.first_throw_violation([], dj_pair_world(rnd), rnd.ordering) is None
    later = P.replay("ADKY3", 13, 0)
    assert hl.first_throw_violation(hl.throw_events(later), later.hands, later.ordering) is None


@pytest.mark.parametrize("seed", [3, 11])
def test_off_the_draw_is_unchanged_and_on_no_checked_world_contradicts_a_throw(seed):
    rnd = P.replay(*AFTER_THROW)
    throws = hl.throw_events(rnd)
    plain = draw(rnd, seed)
    assert draw(rnd, seed, throws=False) == plain
    worlds, _, stats = plain
    assert not {"history_throw_events", "history_throw_rejections"} & set(stats)
    off_bad = sum(hl.first_throw_violation(throws, w, rnd.ordering) is not None for w, _ in worlds)
    assert off_bad > 0
    worlds, _, stats = draw(rnd, seed, throws=True)
    assert len(worlds) == 64
    assert stats["history_throw_events"] == 1 and stats["history_throw_rejections"] > 0
    assert stats["history_unchecked_worlds"] == 0 and stats["history_fill_worlds"] == 0
    assert all(hl.first_throw_violation(throws, w, rnd.ordering) is None for w, _ in worlds)
    # the follow test still holds on every world
    events = hl.follow_events(rnd, rnd.turn)
    assert all(hl.first_violation(events, w, rnd.ordering) is None for w, _ in worlds)


def test_rule_identity(monkeypatch):
    sha = "f" * 64
    base = dict(checkpoint_sha256=sha, world_history_legal=True)
    off = pv.recipe_payload(pv.PVSearchConfig(**base))
    assert "world_history_throws" not in off
    assert pv.recipe_payload(pv.PVSearchConfig(**base, world_history_throws=True)) == {
        **off, "world_history_throws": True}
    with pytest.raises(pv.PVSearchPolicyError, match="world_history_throws requires"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=sha, world_history_throws=True))
    tokens = [t for _, t in pv.RULE_TOKENS]
    assert tokens.index("wht") == tokens.index("whd") + 1 == tokens.index("bw") - 1
    assert pv.PVSearchBot.world_history_throws is False
    for unset in ({}, {FLAG: "0"}, {FLAG: ""}):
        assert names(monkeypatch, unset) == [RELEASE50]
    assert names(monkeypatch, {FLAG: "1"}) == [WHT50]
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        names(monkeypatch, {FLAG: "on"})


def test_served_bot_drops_the_contradicting_worlds_and_changes_the_lead(release50_packages,
                                                                         monkeypatch):
    rnd = P.replay(*AFTER_THROW)
    seat = rnd.turn
    throws = hl.throw_events(rnd)
    env = fly_env()
    seen = {}
    for label, extra, expected_name in (("off", {}, RELEASE50), ("wht", {FLAG: "1"}, WHT50)):
        name, bot = served_bot(release50_packages, monkeypatch,
                               env={**env, **extra, "SHENGJI_BOT": expected_name}, seed=P.SEED)
        assert name == bot.policy_name == expected_name
        assert ("world_history_throws" in vars(bot)) is (label == "wht")
        drawn = []
        original = bot._worlds

        def capture(*args, _original=original, _drawn=drawn, **kwargs):
            out = _original(*args, **kwargs)
            _drawn.append(out[0])
            return out
        bot._worlds = capture
        cards = sorted(P.lift(bot).decide_play(rnd, seat))
        record = bot.last_decision_record
        assert record["belief_fallback"] == 0 and record["history_unchecked_worlds"] == 0
        bad = sum(hl.first_throw_violation(throws, w, rnd.ordering) is not None
                  for w, _ in drawn[0])
        seen[label] = (cards, bad, record)
    (off_cards, off_bad, off_record), (on_cards, on_bad, on_record) = seen["off"], seen["wht"]
    assert off_cards == PINNED_PICK == ["D9"] and off_bad > 0
    assert "history_throw_rejections" not in off_record
    assert on_bad == 0
    assert on_record["history_throw_events"] == 1 and on_record["history_throw_rejections"] > 0
    # the defending seat's lead changes to DQ, 25 points better on the true deal
    assert on_cards == ["DQ"] and not rnd.is_attacker(seat)
    assert attacker_points(rnd, seat, ["DQ"]) == 65 < 90 == attacker_points(rnd, seat, ["D9"])

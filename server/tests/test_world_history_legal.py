"""The OPTIONAL history-legal world test of the pv-search bot
(``world_history_legal``, `ai.history_legality`).

Torch-free: a stub predictor and a stub evaluator on heuristic-played rounds,
production's sampler and the real engine.

Witnesses: on a fixture state production's draw returns worlds in which an
earlier follow by another seat is illegal (one of them through a card the seat
played later), while the true deal passes; every world the rule returns
replays through the REAL engine (`Round.play` from the first play, every hand
as the world has it then); the rule off draws exactly production's worlds and
adds no record keys, and on with no follow to test draws them too; the history
budget is bounded and its shortfall drawn as today; it composes with the
refusal rule (both tests hold); the production and release-45 names are
unchanged off and gain ``-whl`` on; the env flag accepts only 0/1; the oracle
diagnostics refuse it; the record fields.
"""
import copy
import random
import asyncio
import tomllib
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from shengji.ai import history_legality as HL
from shengji.ai import refusal as R
from shengji.ai.cwv_policy import sample_worlds
from shengji.ai.heuristic import HeuristicBot
from shengji.ai.mcbot import MCBot
from shengji.ai.memory import Memory
from shengji.engine.game import Game
from shengji.engine.legal import IllegalPlay
from shengji.harvest.legal import enumerate_legal
from shengji.train import pv_search_policy as pv
from test_refusal_constraints import (PRODUCTION_ENV, PRODUCTION_NAME, PRODUCTION_SHA,
                                      ZeroEvaluator, predict, thrown)
from test_encoder_round_compat import pinned_production_package  # noqa: F401

RULE_KEYS = {"history_follow_events", "history_rejections", "history_fallback_worlds",
             "history_rejections_by_age"}
W = 16
SEED = 7
RELEASE45_NAME = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-radd86676-bury-hybrid-bwv-7a73e8fbf1a8"
RELEASE45_ENV = {
    **PRODUCTION_ENV,
    "SHENGJI_PV_ADMISSION_DIVERSITY": "1", "SHENGJI_PV_REFUSAL_CONSTRAINTS": "1",
    "SHENGJI_PV_TIEBREAK_POINTS": "1", "SHENGJI_PV_LEAD_ANCHOR": "1",
    "SHENGJI_PV_DOOMED_THROW_RESELECT": "1", "SHENGJI_PV_VALUE_DECLARE": "1",
    "SHENGJI_PV_BURY_WIDE_VALUE": "1", "SHENGJI_PV_BURY_WIDE_K": "64",
}


def served(seed=SEED, worlds=W, **rules):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=worlds, candidates=4,
                               cap=400, batch_size=16, **rules)
    return pv.PVSearchBot(predict, evaluator=ZeroEvaluator(), version=2, config=config,
                          checkpoint="/dev/null", seed=seed)


def started(game_seed):
    """A heuristic round at its first play, and the heuristic."""
    h = HeuristicBot()
    rnd = Game(random.Random(game_seed)).start_round()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = h.decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = h.decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, h.decide_bury(rnd, rnd.banker))
    return rnd, h


def plain_violations(rnd, seat, seed=SEED):
    worlds, _ = sample_worlds(MCBot(seed=seed), rnd, seat, W,
                              mem=Memory(rnd, seat, own_kitty=True))
    events = HL.follow_events(rnd, seat)
    return worlds, [HL.first_violation(events, hands, rnd.ordering) for hands, _ in worlds]


_FIXTURE = {}


def fixture():
    """``(start, now, seat)``: the first state of a heuristic round with no
    throw on record at which production's draw returns a history-illegal world
    whose violation needs a card the seat played later."""
    if not _FIXTURE:
        for game_seed in range(40):
            start, h = started(game_seed)
            rnd = copy.deepcopy(start)
            while rnd.phase == "play":
                seat = rnd.turn
                if len(rnd.history) >= 3:
                    worlds, bad = plain_violations(rnd, seat)
                    events = HL.follow_events(rnd, seat)
                    for (hands, _), b in zip(worlds, bad):
                        if b is None:
                            continue
                        ev = events[b]
                        own = Counter(hands[ev.seat])
                        if any(own[c] for c in ev.later):
                            _FIXTURE["state"] = (start, copy.deepcopy(rnd), seat)
                            break
                    if _FIXTURE:
                        break
                cards = h.decide_play(rnd, seat)
                if not rnd.trick.plays and len(cards) > 1 and len(set(cards)) > 1 \
                        and len(cards) != 2 * len(set(cards)):
                    break          # keep the fixture free of throws
                rnd.play(seat, cards)
            if _FIXTURE:
                break
    assert _FIXTURE, "no fixture state found"
    start, now, seat = _FIXTURE["state"]
    return copy.deepcopy(start), copy.deepcopy(now), seat


def engine_replays(start, now, seat, world):
    """Drive the REAL engine: the round from its first play with every hand as
    this world has it then, replaying every committed play."""
    clone = copy.deepcopy(start)
    played = {s: [] for s in range(4)}
    tricks = list(now.history) + ([now.trick] if now.trick and now.trick.plays else [])
    for trick in tricks:
        for play in trick.plays:
            played[play.seat].extend(play.cards)
    clone.hands = [list(world[s]) + played[s] if s != seat else list(start.hands[s])
                   for s in range(4)]
    try:
        for trick in tricks:
            for play in trick.plays:
                clone.play(play.seat, list(play.cards))
    except IllegalPlay:
        return False
    return True


# ------------------------------------------------------------- the fixture

def test_production_draw_returns_impossible_worlds_and_the_truth_passes():
    start, now, seat = fixture()
    worlds, bad = plain_violations(now, seat)
    assert any(b is not None for b in bad)
    assert HL.history_legal(now, seat, now.hands)
    assert engine_replays(start, now, seat, now.hands)
    for (hands, _), b in zip(worlds, bad):
        assert engine_replays(start, now, seat, hands) == (b is None)


def test_every_world_the_rule_returns_replays_through_the_engine():
    start, now, seat = fixture()
    bot = served(world_history_legal=True)
    worlds, attempts = bot._worlds(now, seat)
    stats = bot._last_sampling
    assert len(worlds) == W and stats["history_fallback_worlds"] == 0
    assert stats["history_rejections"] >= 1
    assert attempts >= W + stats["history_rejections"]
    assert sum(stats["history_rejections_by_age"].values()) == stats["history_rejections"]
    for hands, _ in worlds:
        assert HL.history_legal(now, seat, hands)
        assert engine_replays(start, now, seat, hands)


def test_events_are_the_other_seats_follows_with_their_later_cards():
    start, now, seat = fixture()
    events = HL.follow_events(now, seat)
    tricks = list(now.history) + ([now.trick] if now.trick.plays else [])
    follows = [(i, p) for i, t in enumerate(tricks) for p in t.plays[1:] if p.seat != seat]
    assert [(e.trick, e.seat, list(e.cards)) for e in events] == \
        [(i, p.seat, p.cards) for i, p in follows]
    for e in events:
        assert list(e.lead) == tricks[e.trick].plays[0].cards
        assert Counter(e.later) == Counter(c for t in tricks[e.trick:] for p in t.plays
                                           if p.seat == e.seat for c in p.cards)


# --------------------------------------------------------- off == before

def test_rule_off_draws_production_worlds_and_adds_no_record_keys():
    start, now, seat = fixture()
    off = served()
    assert off.world_history_legal is False
    worlds, attempts = off._worlds(now, seat)
    expected, expected_attempts = sample_worlds(MCBot(seed=SEED), now, seat, W,
                                                mem=Memory(now, seat, own_kitty=True))
    assert worlds == expected and attempts == expected_attempts
    bot = served()
    bot.decide_play(copy.deepcopy(now), seat)
    assert bot.last_decision_record["schema"] == pv.RECORD_SCHEMA
    assert not RULE_KEYS & set(bot.last_decision_record)
    # on, at the first play of the round (no follow to test): production's worlds
    on = served(world_history_legal=True)
    assert on._worlds(start, start.turn)[0] == served()._worlds(start, start.turn)[0]
    assert on._last_sampling["history_follow_events"] == 0


def test_worlds_on_are_the_legal_subsequence_of_the_same_stream():
    start, now, seat = fixture()
    on = served(world_history_legal=True)
    got, _ = on._worlds(now, seat)
    stream, _ = sample_worlds(MCBot(seed=SEED), now, seat, 4 * W,
                              mem=Memory(now, seat, own_kitty=True))
    events = HL.follow_events(now, seat)
    legal = [w for w in stream if HL.first_violation(events, w[0], now.ordering) is None]
    assert got == legal[:W]


# ----------------------------------------------------- bounded attempts

def test_history_budget_is_bounded_and_the_rest_is_drawn_as_today(monkeypatch):
    start, now, seat = fixture()
    monkeypatch.setattr(HL, "first_violation", lambda events, hands, ordering: 0)
    bot = served(world_history_legal=True)
    worlds, attempts = bot._worlds(now, seat)
    stats = bot._last_sampling
    assert len(worlds) == W
    assert stats["history_rejections"] == W * HL.HISTORY_ATTEMPT_FACTOR
    assert stats["history_fallback_worlds"] == W
    # after the budget: production's stream, continued
    stream, _ = sample_worlds(MCBot(seed=SEED), now, seat,
                              W * (HL.HISTORY_ATTEMPT_FACTOR + 1),
                              mem=Memory(now, seat, own_kitty=True))
    assert worlds == stream[W * HL.HISTORY_ATTEMPT_FACTOR:]
    calls = []

    def check_budget():
        calls.append(1)
        if len(calls) > 5:
            raise pv.PVSearchBudgetExceeded("expired")
    with pytest.raises(pv.PVSearchBudgetExceeded):
        served(world_history_legal=True)._worlds(now, seat, check_budget)
    assert len(calls) == 6


# ------------------------------------------------------ with the refusal rule

@pytest.mark.parametrize("pair_len", [0, 1])
def test_composes_with_the_refusal_rule(pair_len):
    before, after, attempted, forced = thrown(pair_len)
    h = HeuristicBot()
    while len(after.history) < 2:
        after.play(after.turn, h.decide_play(after, after.turn))
    seat = after.turn
    bot = served(seed=5, refusal_constraints=True, world_history_legal=True)
    worlds, _ = bot._worlds(after, seat)
    stats = bot._last_sampling
    assert stats["refusal_observations"] == 1 and stats["refusal_fallback_worlds"] == 0
    refusal, = bot._refusals.refusals
    for hands, _ in worlds:
        assert R.refusal_consistent(after, hands, refusal)
        assert HL.history_legal(after, seat, hands)
    bot.decide_play(copy.deepcopy(after), seat)
    record = bot.last_decision_record
    assert RULE_KEYS <= set(record) and "refusal_rejections" in record


# ------------------------------------------------------ name / env / record

@pytest.fixture
def production_package(monkeypatch):
    import shengji.ai.cwv_policy as cwv
    monkeypatch.setattr(cwv, "checkpoint_id", lambda path: PRODUCTION_SHA[:8])


def names(env):
    return list(pv.pv_registry_entries(**pv.pv_env_recipe(env)))


def test_names_unchanged_off_and_distinct_on(production_package):
    assert names(PRODUCTION_ENV) == [PRODUCTION_NAME]
    assert names({**PRODUCTION_ENV, "SHENGJI_PV_WORLD_HISTORY_LEGAL": "0"}) == [PRODUCTION_NAME]
    on, = names({**PRODUCTION_ENV, "SHENGJI_PV_WORLD_HISTORY_LEGAL": "1"})
    assert on.startswith("pv-search-491ee4bf-w64-k8-whl-r") and "-bury-hybrid-" in on
    r45, = names(RELEASE45_ENV)
    with_rule, = names({**RELEASE45_ENV, "SHENGJI_PV_WORLD_HISTORY_LEGAL": "1"})
    assert "-rc-tb-" in r45 and "-rc-whl-tb-" in with_rule
    assert with_rule != r45
    config = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0)
    assert pv.recipe_digest(config) == "4a09aef5"
    assert "world_history_legal" not in pv.recipe_payload(config)
    whl = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                            world_history_legal=True)
    assert pv.recipe_payload(whl)["world_history_legal"] is True
    assert pv.recipe_digest(whl) != "4a09aef5"
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA,
                                            world_history_legal=1))


def test_release45_name_is_pinned(production_package):
    assert names(RELEASE45_ENV) == [RELEASE45_NAME]


@pytest.mark.parametrize("bad", ["2", "true", "yes", "on", " 1"])
def test_env_flag_refuses_anything_but_0_or_1(bad):
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, "SHENGJI_PV_WORLD_HISTORY_LEGAL": bad})


@pytest.mark.parametrize("oracle", [dict(oracle_worlds=True), dict(oracle_mix_k=4),
                                    dict(oracle_pin_q=0.5)])
def test_refused_with_the_oracle_diagnostics(oracle):
    config = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, world_history_legal=True,
                               **oracle)
    with pytest.raises(pv.PVSearchPolicyError, match="world_history_legal and the oracle"):
        pv.recipe_payload(config)


def test_decision_record_carries_the_rule_fields_when_on():
    start, now, seat = fixture()
    bot = served(world_history_legal=True)
    played = bot.decide_play(copy.deepcopy(now), seat)
    record = bot.last_decision_record
    assert record["schema"] == pv.RECORD_SCHEMA and record["worlds"] == W
    assert RULE_KEYS <= set(record)
    assert record["history_follow_events"] == len(HL.follow_events(now, seat))
    assert record["history_rejections"] >= 1 and record["history_fallback_worlds"] == 0
    assert not {"refusal_observations"} & set(record)
    assert played in [list(a) for a in enumerate_legal(now, seat, cap=400).actions]


def test_follow_check_uses_the_active_engine():
    from shengji.engine import legal
    import os
    expected = ("shengji.engine._fast" if os.environ.get("SHENGJI_FAST") == "1"
                else "shengji.engine.legal")
    assert legal.validate_follow.__module__ == expected
    assert np.isfinite(HL.HISTORY_ATTEMPT_FACTOR)


def test_a_proposal_source_plugs_in_at_the_draw():
    start, now, seat = fixture()
    sampler = MCBot(seed=SEED)
    calls = []

    def propose(rnd, s, mem):
        calls.append(s)
        return sampler._sample_hands(rnd, s, mem)
    worlds, attempts, stats = HL.sample_worlds_history_legal(
        sampler, now, seat, W, mem=Memory(now, seat, own_kitty=True), propose=propose)
    assert len(calls) == attempts and set(calls) == {seat}
    assert worlds == served(world_history_legal=True)._worlds(now, seat)[0]
    assert all(HL.history_legal(now, seat, hands) for hands, _ in worlds)


def test_pinned_serving_factory_snapshot_and_commit(pinned_production_package, tmp_path):
    """No stub model/sampler: the enabled env recipe reaches the live consumer."""
    from shengji.api import server as srv
    env = tomllib.loads((Path(__file__).resolve().parents[2] / 'fly.toml').read_text())['env']
    env.update(SHENGJI_PV_CKPT=str(pinned_production_package),
               SHENGJI_PV_WORLD_HISTORY_LEGAL='1')
    entries = pv.pv_registry_entries(**pv.pv_env_recipe(env))
    name, = entries
    bot = entries[name](seed=SEED)
    assert bot.world_history_legal and '-whl-' in name
    assert bot.evaluator.backend == 'numpy'
    _, rnd, seat = fixture()

    async def scenario():
        game = Game(random.Random(0))
        game.round = rnd
        room = srv.Room(code='WHL', game=game, bot=bot,
            seats=[srv.Seat(str(s), is_bot=True) for s in range(4)], log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        events = []
        room.log_event = lambda kind, **data: events.append((kind, data))
        before = list(rnd.hands[seat])
        rng_before = bot.sampler.rng.getstate()
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None
        assert room.bot is bot and bot.sampler.rng.getstate() == rng_before
        assert rnd.hands[seat] == before
        record = prepared.decision.snapshot.bot_copy.last_decision_record
        assert record['schema'] == pv.RECORD_SCHEMA and record['work_complete']
        assert record['worlds'] == 64 and RULE_KEYS <= record.keys()
        assert record['history_rejections'] > 0
        assert record['history_follow_events'] == len(HL.follow_events(rnd, seat))
        played = list(prepared.decision.cards)
        assert record['played'] == played
        assert srv._commit_bot_turn(room, prepared)
        assert len(rnd.hands[seat]) == len(before) - len(played)
        assert not srv._commit_bot_turn(room, prepared), 'stale decision must not commit twice'
        assert any(kind == 'model_search' for kind, _ in events)

    asyncio.run(scenario())

"""Event-complete refusal observation (#707 board S8): ``refusal_event_complete``.

Torch-free, on the stubs of `test_refusal_constraints` (fixed log-odds, a zero
evaluator) and the real engine.  Witnesses:

(a) FLAG OFF is identity: release 38's registry name and digest are unchanged
    with the flag unset or ``0``; the flag on adds ``-rcec`` after ``-rc`` and a
    distinct digest; a flag-off bot's `observe_public` is a no-op and its
    decisions and records are byte-identical to a bot that was never hooked.
    The flag without ``refusal_constraints`` is REFUSED (config, env, bot).
(b) The partner fixture (#745): driven by `ai.env.observe_committed_play` after
    every committed play, EVERY seat's ledger retains 8 of 8 refusals, where
    the decision-time read alone retains 6 of 8 at the actor's seat.
(c) The server: a room game with failed throws at every lead, three humans and
    one bot seat, through the real commit paths (`_paced_bot_step` +
    `_commit_bot_turn`, `handle_action`): the PERSISTING room bot -- the
    deep-copied snapshot that each commit installs -- ends the round holding
    every notice posted; the same game with the flag off holds fewer.
(d) `observe_public` never raises into the game loop, and the hook is a no-op
    for a bot without the method (every non-PV bot) and for a flag-off bot.
`RefusalLedger.observe` is idempotent for a notice already held, so the
decision-time and post-commit reads never double-count.
"""
import asyncio
import copy
import random
from pathlib import Path

import pytest

from shengji.ai import env as E
from shengji.ai import refusal as R
from shengji.ai.heuristic import HeuristicBot
from shengji.api import server as srv
from shengji.engine.game import Game
from shengji.engine.legal import validate_lead
from shengji.eval import tactical as T
from shengji.eval.public_refusal_history import public_root_with_observation_schedule
from shengji.train import pv_search_policy as pv
from test_policy_world_search import state
from test_refusal_constraints import (PRODUCTION_ENV, PRODUCTION_SHA, ZeroEvaluator,
                                      predict, served, thrown)

FLAG = "SHENGJI_PV_REFUSAL_EVENT_COMPLETE"
RELEASE38_ENV = {**PRODUCTION_ENV, "SHENGJI_PV_ADMISSION_DIVERSITY": "1",
                 "SHENGJI_PV_REFUSAL_CONSTRAINTS": "1", "SHENGJI_PV_TIEBREAK_POINTS": "1",
                 "SHENGJI_PV_LEAD_ANCHOR": "1"}
RELEASE38 = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-r7092480e-bury-hybrid-5517ddbd7457"
PARTNER_FIXTURE = "pvr8-c2-m0-p43-partner-overtake-control"
FIXTURES = Path(__file__).parent / "tactical" / "public_observations.jsonl"


@pytest.fixture
def production_package(monkeypatch):
    import shengji.ai.cwv_policy as cwv
    monkeypatch.setattr(cwv, "checkpoint_id", lambda path: PRODUCTION_SHA[:8])


def names(env):
    return list(pv.pv_registry_entries(**pv.pv_env_recipe(env)))


def on(seed=5, **rules):
    return served(seed=seed, refusal_constraints=True, refusal_event_complete=True, **rules)


# ------------------------------------------------------- (a) flag off == before

def test_release38_name_and_digest_unchanged_off_and_distinct_on(production_package):
    assert names(RELEASE38_ENV) == [RELEASE38]
    assert names({**RELEASE38_ENV, FLAG: "0"}) == [RELEASE38]
    assert names({**RELEASE38_ENV, FLAG: ""}) == [RELEASE38]
    assert names(PRODUCTION_ENV) == ["pv-search-491ee4bf-w64-k8-r4a09aef5-bury-hybrid-355958b4db25"]
    arm, = names({**RELEASE38_ENV, FLAG: "1"})
    assert arm != RELEASE38
    assert arm.startswith("pv-search-491ee4bf-w64-k8-div-rc-rcec-tb-la-r") and "-bury-hybrid-" in arm
    r38 = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                            admission_diversity=True, refusal_constraints=True,
                            tiebreak_points=True, lead_anchor=True)
    assert pv.recipe_digest(r38) == "7092480e"
    assert "refusal_event_complete" not in pv.recipe_payload(r38)
    ec = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                           admission_diversity=True, refusal_constraints=True,
                           refusal_event_complete=True, tiebreak_points=True, lead_anchor=True)
    assert pv.recipe_payload(ec)["refusal_event_complete"] is True
    assert pv.recipe_digest(ec) != "7092480e"
    assert pv.recipe_payload(ec) == {**pv.recipe_payload(r38), "refusal_event_complete": True}
    assert pv.pv_env_recipe({**RELEASE38_ENV, FLAG: "1"})["refusal_event_complete"] is True
    assert "refusal_event_complete" not in pv.pv_env_recipe(RELEASE38_ENV)
    assert pv.RULE_FLAGS["REFUSAL_EVENT_COMPLETE"] == "refusal_event_complete"
    assert [t for _, t in pv.RULE_TOKENS] == ["div", "fs", "rc", "rcec", "tb", "ak16", "wla", "la", "lp", "dts", "sjg", "aw", "awl"]
    assert pv.SAMPLER_DEFAULTS["refusal_event_complete"] is False
    assert on().refusal_event_complete is True and served().refusal_event_complete is False


@pytest.mark.parametrize("bad", ["2", "true", "yes", "on", " 1"])
def test_env_flag_refuses_anything_but_0_or_1(bad):
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        pv.pv_env_recipe({**RELEASE38_ENV, FLAG: bad})


def test_flag_requires_refusal_constraints(production_package):
    with pytest.raises(pv.PVSearchPolicyError, match="requires refusal_constraints"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA,
                                            refusal_event_complete=True))
    with pytest.raises(pv.PVSearchPolicyError, match="requires refusal_constraints"):
        names({**PRODUCTION_ENV, FLAG: "1"})
    with pytest.raises(pv.PVSearchPolicyError, match="requires refusal_constraints"):
        names({**RELEASE38_ENV, "SHENGJI_PV_REFUSAL_CONSTRAINTS": "0", FLAG: "1"})
    with pytest.raises(pv.PVSearchPolicyError, match="requires refusal_constraints"):
        served(refusal_event_complete=True)
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA,
                                            refusal_constraints=True, refusal_event_complete=1))


def _decision(bot, rnd, seat):
    """The play and the record, less the one wall-clock field."""
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    record = dict(bot.last_decision_record)
    del record["seconds"]
    return played, record


@pytest.mark.parametrize("pair_len", [0, 1])
def test_flag_off_hook_is_a_no_op_and_decisions_are_byte_identical(pair_len):
    before, after, attempted, forced = thrown(pair_len)
    refusal = R.observe_refusal(after)
    # the production bot (no sampler rule): hooked, its ledger never starts
    off = served(seed=21)
    off.observe_public(after)
    assert off._refusals.key is None and off._refusals.refusals == []
    assert _decision(off, after, 1) == _decision(served(seed=21), after, 1)
    # release 38's sampler rule, flag off: the hook is a no-op, the ledger is fed
    # inside the decision exactly as before, the decision and record are the same
    rc = served(seed=21, refusal_constraints=True)
    rc.observe_public(after)
    assert rc._refusals.key is None and rc._refusals.refusals == []
    assert _decision(rc, after, 1) == _decision(served(seed=21, refusal_constraints=True), after, 1)
    assert rc._refusals.refusals == [refusal]
    assert rc.last_decision_record["refusal_observations"] == 1
    # the arm: the hook feeds the ledger; the decision that follows sees the same
    # single refusal the decision-time read would have found, so it is identical
    arm = on(seed=21)
    arm.observe_public(after)
    arm.observe_public(after)
    assert arm._refusals.refusals == [refusal]          # idempotent: once
    assert _decision(arm, after, 1) == _decision(served(seed=21, refusal_constraints=True), after, 1)
    assert arm._refusals.refusals == [refusal]
    # the hook reads only: no RNG draw, no play
    state = arm.sampler.rng.getstate()
    arm.observe_public(after)
    assert arm.sampler.rng.getstate() == state


def test_ledger_observe_is_idempotent_and_the_copy_keeps_it():
    before, after, attempted, forced = thrown(0)
    refusal = R.observe_refusal(after)
    ledger = R.RefusalLedger()
    for _ in range(3):
        assert ledger.observe(after) == [refusal]
    assert ledger.refusals == [refusal]
    assert copy.deepcopy(ledger).refusals == [refusal]
    assert R.RefusalLedger().observe(before) == []


# ------------------------------------------------ (b) the partner fixture, 8 of 8

@pytest.fixture(scope="module")
def partner():
    return next(fx for fx in T.load_fixtures(FIXTURES) if fx.id == PARTNER_FIXTURE)


def _replay(fx, fill_seed, bots, decision_time=True):
    """The fixture's 43 public plays on per-seat bots: the acting seat's bot reads
    the notice at its decision (as `_worlds` does), then every bot is hooked
    after the committed play (as `ai.env.play_prepared_round` does)."""
    root = T.public_round(fx, fill_seed)
    rnd = T.round_from_setup(list(root.deck), dict(fx.setup, buried=list(root.buried)))
    posted = []
    for play in fx.plays:
        if decision_time and bots[rnd.turn].refusal_constraints:
            bots[rnd.turn]._refusals.observe(rnd)
        T._replay_public(rnd, [play], fx.seat)
        E.observe_committed_play(rnd, bots)
        if rnd.notice is not None and rnd.notice["id"] not in [n["id"] for _, n in posted]:
            posted.append((len(rnd.history), dict(rnd.notice)))   # the throw led this trick
    assert rnd.hands == root.hands and rnd.history == root.history
    return rnd, posted


@pytest.mark.parametrize("fill_seed", [0, 1])
def test_partner_fixture_every_seat_retains_8_of_8_with_the_hook(partner, fill_seed):
    fx = partner
    assert fx.seat == 0
    arms = [on(seed=s) for s in range(4)]
    rnd, posted = _replay(fx, fill_seed, arms)
    assert len(posted) == 8
    retained = [b._refusals.observe(rnd) for b in arms]
    assert [len(r) for r in retained] == [8, 8, 8, 8]
    assert all(r == retained[0] for r in retained)
    assert [(r.trick_index, r.seat, r.attempted, r.forced) for r in retained[0]] == [
        (index, int(n["seat"]), tuple(n["attempted"]), tuple(n["forced"]))
        for index, n in posted]
    # release 38 (the rule on, no hook): the actor's seat retains 6 of 8 (#745)
    r38 = [served(seed=s, refusal_constraints=True) for s in range(4)]
    rnd38, _ = _replay(fx, fill_seed, r38)
    assert len(r38[0]._refusals.observe(rnd38)) == 6
    # (observed on this fixture: which seat misses what is a matter of where the
    # replacements fall relative to each seat's turns; only seat 2 sees all 8)
    assert [len(b._refusals.observe(rnd38)) for b in r38] == [6, 7, 8, 7]
    # the two the actor missed are its own throws, posted after its decisions
    missed = [r for r in retained[0] if r not in r38[0]._refusals.observe(rnd38)]
    assert [(r.trick_index, r.seat) for r in missed] == [(0, 0), (7, 0)]
    # the hook alone (no decision-time read at all) is already complete
    hook_only = [on(seed=s) for s in range(4)]
    rnd_h, _ = _replay(fx, fill_seed, hook_only, decision_time=False)
    assert [len(b._refusals.observe(rnd_h)) for b in hook_only] == [8, 8, 8, 8]
    # the production bot (no sampler rule) at the same table: untouched
    prod = [served(seed=s) for s in range(4)]
    _replay(fx, fill_seed, prod)
    assert all(b._refusals.key is None and b._refusals.refusals == [] for b in prod)


def test_partner_fixture_schedule_form_of_the_same_claim(partner):
    """`public_refusal_history`'s explicit schedule, observing before every
    historical play (= after every committed play, plus the start): 8 of 8."""
    every = list(range(len(partner.plays)))
    root, ledger, receipt = public_root_with_observation_schedule(
        partner, observed_play_indices=every)
    assert len(receipt["retained_refusals"]) == 8
    assert receipt["historical_observations"][-1]["play_index"] == len(partner.plays) - 1
    actor_turns = [i for i, _ in enumerate(partner.plays)
                   if receipt["historical_observations"][i]["seat"] == partner.seat]
    _, _, primed = public_root_with_observation_schedule(
        partner, observed_play_indices=actor_turns)
    assert len(primed["retained_refusals"]) == 6


# --------------------------------------------------- (c) the server's commit paths

def _refusable_throw(rnd, seat):
    """A pair-plus-single throw in one suit the engine refuses, or None."""
    hand, o = rnd.hands[seat], rnd.ordering
    others = [rnd.hands[s] for s in range(4) if s != seat]
    by_suit = {}
    for c in hand:
        by_suit.setdefault(o.eff_suit(c), []).append(c)
    for cards in by_suit.values():
        pair = next((c for c in cards if cards.count(c) >= 2), None)
        single = next((c for c in cards if c != pair), None)
        if pair is None or single is None:
            continue
        cand = [pair, pair, single]
        played, message = validate_lead(cand, hand, others, o)
        if message is not None and len(played) < len(cand):
            return cand
    return None


def script(rnd, seat):
    """The table's play: a refusable throw at every lead that has one (so
    notices are posted and replaced), the heuristic otherwise."""
    if rnd.trick is not None and not rnd.trick.plays:
        cand = _refusable_throw(rnd, seat)
        if cand is not None:
            return cand
    return HeuristicBot().decide_play(rnd, seat)


class ScriptedPV(pv.PVSearchBot):
    """The served wrapper with the search replaced by `script`; the decision-time
    ledger read of `_worlds` is kept (that is the release-38 observation)."""
    policy_name = "pv-search-event-complete-witness"

    def decide_play(self, rnd, seat):
        if self.refusal_constraints:
            self._refusals.observe(rnd)
        self.last_decision_record = None
        return script(rnd, seat)


def _scripted(seed, event_complete):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=4, candidates=4, cap=400,
                               batch_size=16, refusal_constraints=True,
                               refusal_event_complete=event_complete)
    return ScriptedPV(predict, evaluator=ZeroEvaluator(), version=2, config=config,
                      checkpoint="/dev/null", seed=seed)


def _room(seed, bot, bot_seat, tmp_path):
    game = Game(random.Random(seed))
    rnd = game.start_round()
    helper = HeuristicBot()
    while rnd.phase != "play":
        if rnd.phase == "deal":
            rnd.deal_next()
        elif rnd.phase == "declare":
            rnd.finalize_declare()
        elif rnd.phase == "bury":
            rnd.bury(rnd.banker, helper.decide_bury(rnd, rnd.banker))
    room = srv.Room(code=f"EC{seed}", game=game, bot=bot, log_dir=tmp_path,
                    seats=[srv.Seat(name=f"S{s}", is_bot=(s == bot_seat)) for s in range(4)])
    room.ids = [{index * 4 + seat: card for index, card in enumerate(rnd.hands[seat])}
                for seat in range(4)]
    room._kitty_given = True
    room.log_event = lambda kind, **data: None
    return room


async def _play_room_round(room, bot_seat):
    """Every committed play through the server's own paths; returns the notices
    posted (by id) and the number of bot commits that installed a new copy."""
    rnd = room.round
    posted, installs = {}, 0
    while rnd.phase == "play":
        seat = rnd.turn
        if seat == bot_seat:
            live = room.bot
            held = list(live._refusals.refusals)
            prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
            assert prepared is not None
            async with room.lock:
                assert srv._commit_bot_turn(room, prepared)
            assert room.bot is prepared.decision.snapshot.bot_copy and room.bot is not live
            # the deep-copied snapshot carried the ledger into the committed bot
            assert all(r in room.bot._refusals.refusals for r in held)
            installs += 1
        else:
            codes = script(rnd, seat)
            ids = room.ids_for_codes(seat, codes)
            async with room.lock:
                await srv.handle_action(room, seat, {"type": "play", "card_ids": ids})
        if rnd.notice is not None:
            posted.setdefault(rnd.notice["id"], R.observe_refusal(rnd))
    assert room.game.result is not None
    return posted, installs


@pytest.mark.parametrize("bot_seat", [0, 2])
def test_room_bot_ledger_is_event_complete_through_the_commit_paths(bot_seat, tmp_path):
    witnessed = False
    for seed in range(12):
        arm = _scripted(seed, event_complete=True)
        room = _room(seed, arm, bot_seat, tmp_path)
        posted, installs = asyncio.run(_play_room_round(room, bot_seat))
        # one commit per trick: every one installed the snapshot's copy
        assert installs == len(room.round.history) >= 20 and room.bot is not arm
        expected = sorted(posted.values(), key=lambda r: r.trick_index)
        assert all(R.on_record(room.round, r) for r in expected)
        # the PERSISTING room bot holds every notice this round posted
        assert sorted(room.bot._refusals.refusals, key=lambda r: r.trick_index) == expected
        assert room.bot._refusals.key == tuple(room.round.deck)
        # the same game, release 38's observation (the flag off): plays and
        # notices are identical, the persisting bot's ledger is not complete
        r38 = _scripted(seed, event_complete=False)
        room38 = _room(seed, r38, bot_seat, tmp_path)
        posted38, _ = asyncio.run(_play_room_round(room38, bot_seat))
        assert posted38 == posted and room38.round.history == room.round.history
        kept = room38.bot._refusals.refusals
        assert all(r in expected for r in kept)
        if len(kept) < len(expected) and len(expected) >= 3:
            missed = [r for r in expected if r not in kept]
            # what the flag-off bot missed were its own failed throws (posted
            # after its decision and replaced before its next turn)
            assert missed and all(r.seat == bot_seat for r in missed)
            witnessed = True
            break
    assert witnessed, "no seed in range(12) produced a replaced bot notice; fixture not exercising #745"


class CountingPV(ScriptedPV):
    """`observe_public` counted; the count rides the deep copies with the ledger."""
    observed = 0

    def observe_public(self, rnd):
        self.observed += 1
        super().observe_public(rnd)


def _counting(seed):
    bot = _scripted(seed, event_complete=True)
    bot.__class__ = CountingPV
    return bot


def test_takeover_and_human_paths_observe_only_committed_plays(tmp_path, monkeypatch):
    """Seat 0 a bot, seat 1 a disconnected human the bot plays for (takeover),
    seats 2 and 3 humans: one observation per accepted live play, none for a
    stale snapshot or a rejected human play, and the persisting bot ends the
    round holding every notice."""
    monkeypatch.setattr(srv, "now", lambda: 1e9)
    seed = 2
    room = _room(seed, _counting(seed), 0, tmp_path)
    absent = room.seats[1]
    absent.connected, absent.left_at = False, 1e9 - 2 * srv.TAKEOVER_AFTER
    rnd = room.round
    posted, plays, takeovers = {}, 0, 0

    async def run():
        nonlocal plays, takeovers
        while rnd.phase == "play":
            seat = rnd.turn
            if seat in (0, 1):
                mode = "bot" if seat == 0 else "takeover"
                assert srv._turn_eligible(room, seat, mode)
                prepared = await srv._paced_bot_step(room, seat, mode=mode, minimum_turn_seconds=0)
                assert prepared is not None
                async with room.lock:
                    assert srv._commit_bot_turn(room, prepared)
                takeovers += seat == 1
            else:
                codes = script(rnd, seat)
                # a rejected play first: not the seat's turn / unknown ids
                async with room.lock:
                    with pytest.raises(srv.IllegalPlay):
                        await srv.handle_action(room, (seat + 1) % 4,
                                                {"type": "play", "card_ids": [10 ** 6]})
                    await srv.handle_action(room, seat, {"type": "play",
                                                         "card_ids": room.ids_for_codes(seat, codes)})
            plays += 1
            if rnd.notice is not None:
                posted.setdefault(rnd.notice["id"], R.observe_refusal(rnd))
    asyncio.run(run())
    assert takeovers == len(rnd.history) >= 20 and plays == 4 * len(rnd.history)
    assert room.bot.observed == plays           # one read per committed play, no more
    assert len(posted) >= 3
    assert sorted(room.bot._refusals.refusals, key=lambda r: r.trick_index) == \
        sorted(posted.values(), key=lambda r: r.trick_index)
    # a stale snapshot: the seat is claimed between search and commit -- no play,
    # no observation, the live bot untouched
    fresh = _room(seed, _counting(seed), 0, tmp_path)
    while fresh.round.turn != 0:
        _human_play(fresh, fresh.round.turn)
    before = fresh.bot.observed
    prepared = asyncio.run(srv._paced_bot_step(fresh, 0, minimum_turn_seconds=0))
    fresh.seats[0].is_bot, fresh.seats[0].connected = False, True
    assert srv._commit_bot_turn(fresh, prepared) is False
    assert fresh.bot.observed == before and prepared.decision.snapshot.bot_copy.observed == before


def test_hook_resets_the_ledger_on_a_new_deck_and_dedups_repeats():
    before, after, attempted, forced = thrown(0)
    refusal = R.observe_refusal(after)
    arm = on(seed=11)
    for _ in range(3):
        arm.observe_public(after)
    assert arm._refusals.refusals == [refusal]
    other = Game(random.Random(7)).start_round()
    assert tuple(other.deck) != tuple(after.deck)
    next_deal = state()                 # the pre-throw fixture round, another deck
    next_deal.deck = list(other.deck)
    arm.observe_public(next_deal)
    assert arm._refusals.key == tuple(other.deck) and arm._refusals.refusals == []
    arm.observe_public(after)
    assert arm._refusals.refusals == [refusal]


# --------------------------------------------------------- (d) never into the loop

def _human_play(room, seat):
    codes = script(room.round, seat)
    ids = room.ids_for_codes(seat, codes)

    async def go():
        async with room.lock:
            await srv.handle_action(room, seat, {"type": "play", "card_ids": ids})
    asyncio.run(go())


def test_hook_is_a_no_op_for_other_bots_and_never_raises_into_the_loop(tmp_path, caplog):
    # a bot without the method: every non-PV bot
    room = _room(3, HeuristicBot(), 0, tmp_path)
    assert not hasattr(room.bot, "observe_public")
    seat = room.round.turn
    while seat != 0:
        _human_play(room, seat)
        seat = room.round.turn
    prepared = asyncio.run(srv._paced_bot_step(room, 0, minimum_turn_seconds=0))
    hand = len(room.round.hands[0])
    assert srv._commit_bot_turn(room, prepared) and len(room.round.hands[0]) < hand
    direct = _room(4, HeuristicBot(), 0, tmp_path)
    while direct.round.turn != 0:
        _human_play(direct, direct.round.turn)
    hand = len(direct.round.hands[0])
    assert srv.bot_step(direct, 0) is True and len(direct.round.hands[0]) < hand

    # a hook that raises: the play is committed and logged, the loop continues
    class Broken(ScriptedPV):
        def observe_public(self, rnd):
            raise RuntimeError("ledger witness")
    broken = _scripted(5, event_complete=True)
    broken.__class__ = Broken
    room = _room(5, broken, 0, tmp_path)
    seat = room.round.turn
    with caplog.at_level("WARNING"):
        while seat != 0:
            hand = len(room.round.hands[seat])
            _human_play(room, seat)
            assert len(room.round.hands[seat]) < hand
            seat = room.round.turn
        prepared = asyncio.run(srv._paced_bot_step(room, 0, minimum_turn_seconds=0))
        hand = len(room.round.hands[0])
        assert srv._commit_bot_turn(room, prepared) and len(room.round.hands[0]) < hand
    assert any("observe_public failed: RuntimeError: ledger witness" in rec.message
               for rec in caplog.records)
    # the direct path too
    direct = _room(6, broken, 0, tmp_path)
    while direct.round.turn != 0:
        _human_play(direct, direct.round.turn)
    assert srv.bot_step(direct, 0) is True

    # a flag-off PV bot: hooked at every commit, its ledger is only ever fed by
    # its own decisions
    off = _scripted(7, event_complete=False)
    room = _room(7, off, 0, tmp_path)
    posted, _ = asyncio.run(_play_room_round(room, 0))
    assert room.bot.refusal_event_complete is False
    assert all(r in posted.values() for r in room.bot._refusals.refusals)

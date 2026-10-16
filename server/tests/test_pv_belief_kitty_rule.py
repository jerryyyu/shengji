"""The OPTIONAL bury-rule kitty of the S17 belief proposal
(``belief_kitty_rule``, `ai.kitty_rule.kitty_rule_split` inside
`ai.belief_numpy.BeliefProposal`).

Witnesses: off, the production, release-45 and ``bw`` names and digests are
unchanged and the proposal's stream is byte-identical; on, the name gains
``-bwk`` after ``-bw`` and the digest names the kitty-rule proposal and its
world model; the flag needs ``belief_worlds``; a non-banker's worlds carry a
kitty the served bury's incumbent rule would discard from the banker's dealt
cards (no trump, sizes kept, the banker's voids and draw constraints kept),
the banker's own draw is untouched, the budget bounds the rule's tries; the
served draw with the flag is history-legal, seeded, recorded, falls back on
any error and reaches the live consumer.
"""
import copy
from collections import Counter

import pytest

from shengji.ai import belief_numpy as bn
from shengji.ai import history_legality as HL
from shengji.ai import kitty_rule as kr
from shengji.ai.memory import Memory
from shengji.engine.cards import TRUMP
from shengji.train import pv_search_policy as pv
from test_refusal_constraints import PRODUCTION_ENV, PRODUCTION_NAME, PRODUCTION_SHA
from test_world_history_legal import RELEASE45_ENV, RELEASE45_NAME, W, fixture, served
from test_pv_belief_worlds import BELIEF_KEYS, _SHAS, names, package, production_package  # noqa: F401
from test_encoder_round_compat import pinned_production_package  # noqa: F401

#: the S17 package the v86 arm serves (`s17_full_h.npz`) and that arm's name
S17_SHA = "cb02e1b67ecd6910d44a5928bf626f54fbe22606a3f04404332c738246f33acb"
BW_NAME = "pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-la-dtr-vd-rf3d08fa0-bury-hybrid-bwv-358a544ea5fb"
FLAG = "SHENGJI_PV_BELIEF_KITTY_RULE"
KITTY_KEYS = {"belief_kitty_worlds", "belief_kitty_rejections", "belief_kitty_fallback"}


def bw_env(ckpt, sha):
    return {**RELEASE45_ENV, "SHENGJI_PV_WORLD_HISTORY_LEGAL": "1",
            "SHENGJI_PV_WORLD_HISTORY_DRAW": "1", "SHENGJI_PV_BELIEF_WORLDS": "1",
            "SHENGJI_PV_BELIEF_CKPT": ckpt, "SHENGJI_PV_BELIEF_SHA256": sha}


def test_names_unchanged_off_and_distinct_on(production_package):
    _SHAS["s17_full_h.npz"] = S17_SHA
    assert names(PRODUCTION_ENV) == [PRODUCTION_NAME]
    assert names(RELEASE45_ENV) == [RELEASE45_NAME]
    bw = bw_env("s17_full_h.npz", S17_SHA)
    assert names(bw) == [BW_NAME]
    assert names({**bw, FLAG: "0"}) == [BW_NAME]
    bwk, = names({**bw, FLAG: "1"})
    assert "-whl-whd-bw-bwk-tb-" in bwk and bwk != BW_NAME
    assert bwk.split("-bury-")[1].startswith("hybrid-bwv-")
    _SHAS.pop("s17_full_h.npz")
    base = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                             world_history_legal=True, world_history_draw=True,
                             belief_worlds=True, belief_sha256=S17_SHA)
    on = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                           world_history_legal=True, world_history_draw=True,
                           belief_worlds=True, belief_sha256=S17_SHA, belief_kitty_rule=True)
    pb, po = pv.recipe_payload(base), pv.recipe_payload(on)
    assert "belief_kitty_rule" not in pb and po["belief_kitty_rule"] is True
    assert pb["belief_worlds_package"]["proposal"] == bn.PROPOSAL
    assert "kitty_rule_model" not in pb["belief_worlds_package"]
    assert po["belief_worlds_package"]["proposal"] == bn.PROPOSAL_KITTY_RULE
    assert po["belief_worlds_package"]["kitty_rule_model"] == kr.KITTY_RULE_MODEL
    same = ("schema", "sha256", "prep_seconds", "fallback")
    assert {k: po["belief_worlds_package"][k] for k in same} == \
        {k: pb["belief_worlds_package"][k] for k in same}
    assert pv.recipe_digest(base) != pv.recipe_digest(on)
    assert pv.RULE_FLAGS["BELIEF_KITTY_RULE"] == "belief_kitty_rule"
    assert pv.SAMPLER_DEFAULTS["belief_kitty_rule"] is False
    assert pv.RULE_TOKENS[pv.RULE_TOKENS.index(("belief_worlds", "bw")) + 1] == \
        ("belief_kitty_rule", "bwk")


def test_flag_contract(production_package):
    with pytest.raises(pv.PVSearchPolicyError, match="requires belief_worlds"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA,
                                            belief_kitty_rule=True))
    with pytest.raises(pv.PVSearchPolicyError, match="requires belief_worlds"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA,
                                            world_history_legal=True, world_history_draw=True,
                                            belief_kitty_rule=True))
    with pytest.raises(pv.PVSearchPolicyError, match="requires belief_worlds"):
        served(world_history_legal=True, world_history_draw=True, belief_kitty_rule=True)
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "yes"})
    with pytest.raises(pv.PVSearchPolicyError, match="requires belief_worlds"):
        names({**RELEASE45_ENV, FLAG: "1"})
    assert "belief_kitty_rule" not in pv.pv_env_recipe({**RELEASE45_ENV, FLAG: "0"})
    assert served(world_history_legal=True, world_history_draw=True, belief_worlds=True,
                  belief_sha256=S17_SHA).belief_kitty_rule is False
    assert served(world_history_legal=True, world_history_draw=True, belief_worlds=True,
                  belief_sha256=S17_SHA, belief_kitty_rule=True).belief_kitty_rule is True


# ------------------------------------------------------------------ the rule

def nonbanker_states(n_games):
    from test_world_history_draw import states
    for rnd, seat in states(n_games=n_games):
        if seat != rnd.banker and len(rnd.buried) > 0:
            yield rnd, seat


def test_kitty_rule_split_keeps_the_rule_and_the_bankers_constraints():
    """On the true deal: the split of the banker's unplayed cards plus the real
    kitty is a kitty of the right size with no trump, hand plus kitty is the
    union, and a union the banker's voids cannot absorb is rejected."""
    checked = rejected = 0
    for rnd, seat in nonbanker_states(6):
        mem = Memory(rnd, seat, own_kitty=True)
        banker = rnd.banker
        union = list(rnd.hands[banker]) + list(rnd.buried)
        played = sorted(mem.played_by[banker].elements())
        split = kr.kitty_rule_split(rnd, mem, union, played, (), len(rnd.buried))
        if split is None:
            rejected += 1
            continue
        hand, kitty = split
        assert len(kitty) == len(rnd.buried)
        assert Counter(hand) + Counter(kitty) == Counter(union)
        assert not any(rnd.ordering.eff_suit(c) == TRUMP for c in kitty)
        assert not any(rnd.ordering.eff_suit(c) in mem.voids[banker] for c in hand)
        # the rule's keep order: the kitty is the lowest-kept eight of the union
        again = kr.heuristic_bury_kitty(union + played, union, rnd.ordering, len(rnd.buried))
        assert sorted(again) == sorted(kitty)
        # a forbidden code the rule keeps in the hand rejects the world
        keep = [c for c in hand if rnd.ordering.eff_suit(c) != TRUMP]
        if keep:
            assert kr.kitty_rule_split(rnd, mem, union, played, {keep[0]},
                                       len(rnd.buried)) is None
        checked += 1
    assert checked > 20


def test_proposal_with_the_rule_discards_by_the_rule_and_off_is_identical(package):
    """Through `BeliefProposal` (real inputs, mask, projection, constraints) on
    real non-banker states: every rule world's kitty is what the rule would
    discard from that world's banker cards; the banker's hand keeps its voids
    and forbidden codes; sizes hold; the stream is seeded; and with the flag
    off the proposal's worlds are byte-identical to a proposal built without
    the keyword."""
    model = bn.load_belief_numpy(package["path"], package["sha256"])
    rule_worlds = fallback = states = 0
    for rnd, seat in nonbanker_states(4):
        states += 1
        constraints = HL.draw_constraints(rnd, seat)
        mem = Memory(rnd, seat, own_kitty=True)
        banker = rnd.banker
        played = sorted(mem.played_by[banker].elements())
        forbidden = {c for (s, _), cs in constraints.items() if s == banker for c in cs}
        on = bn.BeliefProposal(model, rnd, seat, (), seed=3, batch=16, forbidden=constraints,
                               kitty_rule=True)
        assert on.kitty_rule and on.kitty_hidden and on.banker_forbidden == forbidden
        drawn = [on(rnd, seat, mem) for _ in range(16)]
        assert on.kitty_worlds + on.kitty_fallback == 16
        rule_worlds += on.kitty_worlds
        fallback += on.kitty_fallback
        for hands, buried in drawn:
            assert len(buried) == len(rnd.buried)
            for s in range(4):
                if s != seat:
                    assert len(hands[s]) == len(rnd.hands[s])
        if on.kitty_fallback == 0:
            for hands, buried in drawn:
                union = hands[banker] + buried
                assert not any(rnd.ordering.eff_suit(c) == TRUMP for c in buried)
                assert sorted(kr.heuristic_bury_kitty(union + played, union, rnd.ordering,
                                                      len(buried))) == sorted(buried)
                assert not any(rnd.ordering.eff_suit(c) in mem.voids[banker]
                               or c in forbidden for c in hands[banker])
        again = bn.BeliefProposal(model, rnd, seat, (), seed=3, batch=16, forbidden=constraints,
                                  kitty_rule=True)
        assert [again(rnd, seat, mem) for _ in range(16)] == drawn
        off = bn.BeliefProposal(model, rnd, seat, (), seed=3, batch=16, forbidden=constraints,
                                kitty_rule=False)
        plain = bn.BeliefProposal(model, rnd, seat, (), seed=3, batch=16, forbidden=constraints)
        off_worlds = [off(rnd, seat, mem) for _ in range(16)]
        assert off_worlds == [plain(rnd, seat, mem) for _ in range(16)]
        assert off.kitty_worlds == off.kitty_rejections == off.kitty_fallback == 0
        # the rule only re-splits the banker's cards and the kitty: the other
        # two seats' hands are the plain draw's whenever no world was redrawn
        if on.kitty_rejections == 0:
            for (h_on, _), (h_off, _) in zip(drawn, off_worlds):
                for s in range(4):
                    if s not in (seat, banker):
                        assert h_on[s] == h_off[s]
    assert states >= 20 and rule_worlds > 10 * states
    assert fallback < rule_worlds


def test_the_rule_leaves_the_bankers_own_draw_untouched(package):
    from test_world_history_draw import states
    model = bn.load_belief_numpy(package["path"], package["sha256"])
    checked = 0
    for rnd, seat in states(n_games=4):
        if seat != rnd.banker:
            continue
        mem = Memory(rnd, seat, own_kitty=True)
        on = bn.BeliefProposal(model, rnd, seat, (), seed=3, batch=8, kitty_rule=True)
        off = bn.BeliefProposal(model, rnd, seat, (), seed=3, batch=8)
        assert [on(rnd, seat, mem) for _ in range(8)] == [off(rnd, seat, mem) for _ in range(8)]
        assert on.kitty_worlds == on.kitty_rejections == on.kitty_fallback == 0
        checked += 1
    assert checked >= 4


def test_the_rule_budget_bounds_the_tries_and_falls_back_plain(package, monkeypatch):
    model = bn.load_belief_numpy(package["path"], package["sha256"])
    rnd, seat = next(nonbanker_states(1))
    mem = Memory(rnd, seat, own_kitty=True)
    monkeypatch.setattr(kr, "kitty_rule_split", lambda *a, **k: None)
    on = bn.BeliefProposal(model, rnd, seat, (), seed=3, batch=4, kitty_rule=True)
    plain = bn.BeliefProposal(model, rnd, seat, (), seed=3, batch=4)
    worlds = [on(rnd, seat, mem) for _ in range(4)]
    assert on.kitty_worlds == 0 and on.kitty_fallback == 4
    assert on.kitty_rejections == 4 * bn.KITTY_RULE_BATCHES
    # the fallback worlds are the last batch's plain draw, in draw order
    for _ in range(4 * (bn.KITTY_RULE_BATCHES - 1)):
        plain(rnd, seat, mem)
    assert worlds == [plain(rnd, seat, mem) for _ in range(4)]
    with pytest.raises(bn.BeliefNumpyError, match="memory"):
        bn.BeliefProposal(model, rnd, seat, (), seed=3, batch=4, kitty_rule=True)(rnd, seat, None)


def test_the_rule_proposal_never_deals_a_forbidden_twin(package):
    from test_world_history_draw import breaks_constraints, states
    model = bn.load_belief_numpy(package["path"], package["sha256"])
    checked = constrained = 0
    for rnd, seat in states(n_games=4):
        constraints = HL.draw_constraints(rnd, seat)
        propose = bn.BeliefProposal(model, rnd, seat, (), seed=3, batch=16, forbidden=constraints,
                                    kitty_rule=True)
        mem = Memory(rnd, seat, own_kitty=True)
        for _ in range(16):
            hands, _ = propose(rnd, seat, mem)
            full = [hands.get(s, rnd.hands[s]) for s in range(4)]
            assert not breaks_constraints(constraints, full, rnd.ordering)
            for s in range(4):
                assert len(full[s]) == len(rnd.hands[s])
            checked += 1
        constrained += bool(constraints)
    assert checked > 100 and constrained > 3


# ------------------------------------------------------------------ the served draw

def belief_bot(package, seed=7, kitty_rule=True):
    bot = served(seed=seed, world_history_legal=True, world_history_draw=True, belief_worlds=True,
                 belief_sha256=package["sha256"], belief_kitty_rule=kitty_rule)
    bot.belief_model = bn.load_belief_numpy(package["path"], package["sha256"])
    return bot


def test_served_draw_with_the_rule_is_history_legal_seeded_and_recorded(package):
    _, now, seat = fixture()
    assert seat != now.banker
    bot = belief_bot(package)
    worlds, _ = bot._worlds(copy.deepcopy(now), seat)
    stats = bot._last_sampling
    assert len(worlds) == W
    assert stats["belief_fallback"] == 0 and stats["belief_proposed"] >= W
    assert KITTY_KEYS <= set(stats)
    assert stats["belief_kitty_worlds"] + stats["belief_kitty_fallback"] >= W
    mem = Memory(now, seat, own_kitty=True)
    hidden = sum((Counter(h) for s, h in enumerate(worlds[0][0]) if s != seat), Counter())
    for hands, buried in worlds:
        assert hands[seat] == sorted(now.hands[seat])
        assert len(buried) == len(now.buried)
        for s in range(4):
            assert len(hands[s]) == len(now.hands[s])
            if s != seat:
                assert not any(now.ordering.eff_suit(c) in mem.voids[s] for c in hands[s])
        assert HL.history_legal(now, seat, hands)
    assert sum(hidden.values()) == sum(len(now.hands[s]) for s in range(4) if s != seat)
    again, _ = belief_bot(package)._worlds(copy.deepcopy(now), seat)
    assert again == worlds
    # the flag changes the split, not the proposal's stream: the plain arm's
    # worlds on the same seed are a different legal sample of the same state
    plain, _ = belief_bot(package, kitty_rule=False)._worlds(copy.deepcopy(now), seat)
    assert len(plain) == W and plain != worlds
    assert not KITTY_KEYS & set(belief_bot(package, kitty_rule=False)._sampler_record())
    bot.decide_play(copy.deepcopy(now), seat)
    record = bot.last_decision_record
    assert BELIEF_KEYS | KITTY_KEYS <= set(record) and record["belief_fallback"] == 0
    snap = copy.deepcopy(bot)
    assert snap.belief_model is bot.belief_model and snap.belief_kitty_rule is True


def test_any_error_falls_back_to_the_history_legal_draw(package, monkeypatch):
    _, now, seat = fixture()
    bot = belief_bot(package)
    monkeypatch.setattr(kr, "kitty_rule_split",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    worlds, _ = bot._worlds(copy.deepcopy(now), seat)
    assert len(worlds) == W
    assert bot._last_sampling["belief_fallback"] == 1
    assert bot._last_sampling["belief_error"] == "RuntimeError"
    assert all(HL.history_legal(now, seat, hands) for hands, _ in worlds)


def test_budget_expiry_is_not_swallowed(package):
    _, now, seat = fixture()
    bot = belief_bot(package)

    def expired():
        raise pv.PVSearchBudgetExceeded("pv-search serving budget expired")
    with pytest.raises(pv.PVSearchBudgetExceeded):
        bot._worlds(copy.deepcopy(now), seat, check_budget=expired)


def test_pinned_serving_factory_snapshot_and_commit(pinned_production_package, package, tmp_path):
    """No stub model or sampler: the enabled env recipe reaches the live
    consumer through the server's snapshot and commit path."""
    import asyncio
    import random
    import tomllib
    from pathlib import Path
    from shengji.api import server as srv
    from shengji.engine.game import Game
    env = tomllib.loads((Path(__file__).resolve().parents[2] / "fly.toml").read_text())["env"]
    env.update(SHENGJI_PV_CKPT=str(pinned_production_package),
               SHENGJI_PV_WORLD_HISTORY_LEGAL="1", SHENGJI_PV_WORLD_HISTORY_DRAW="1",
               SHENGJI_PV_BELIEF_WORLDS="1", SHENGJI_PV_BELIEF_KITTY_RULE="1",
               SHENGJI_PV_BELIEF_CKPT=package["path"], SHENGJI_PV_BELIEF_SHA256=package["sha256"])
    entries = pv.pv_registry_entries(**pv.pv_env_recipe(env))
    name, = entries
    bot = entries[name](seed=7)
    assert bot.belief_worlds and bot.belief_kitty_rule and "-whl-whd-bw-bwk-" in name
    assert bot.belief_model.package_sha256 == package["sha256"]
    _, rnd, seat = fixture()

    async def scenario():
        game = Game(random.Random(0))
        game.round = rnd
        room = srv.Room(code="BWK", game=game, bot=bot,
                        seats=[srv.Seat(str(s), is_bot=True) for s in range(4)], log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        room.log_event = lambda kind, **data: None
        before = list(rnd.hands[seat])
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None
        record = prepared.decision.snapshot.bot_copy.last_decision_record
        assert record["schema"] == pv.RECORD_SCHEMA and record["work_complete"]
        assert record["worlds"] == 64 and BELIEF_KEYS | KITTY_KEYS <= record.keys()
        assert record["belief_fallback"] == 0 and record["belief_proposed"] >= 64
        assert srv._commit_bot_turn(room, prepared)
        assert len(rnd.hands[seat]) == len(before) - len(prepared.decision.cards)

    asyncio.run(scenario())

"""The OPTIONAL S17 belief proposal of the pv-search bot (``belief_worlds``,
`ai.belief_numpy.BeliefProposal` inside `ai.history_legality`).

Witnesses: off, the production and release-45 names and the history-legal
digest are unchanged; on, the name gains ``-bw`` after ``-whl`` and the digest
the package sha; the flag needs ``world_history_legal`` and the package pair;
the served draw returns W worlds that keep sizes, voids and pins and pass the
history test, records the rule's fields, and falls back to the history-legal
production draw on any error; the model is shared across a bot snapshot.
"""
import copy
import json

import numpy as np
import pytest

from shengji.ai import belief_numpy as bn
from shengji.ai import history_legality as HL
from shengji.ai.memory import Memory
from shengji.train import pv_search_policy as pv
from test_refusal_constraints import PRODUCTION_ENV, PRODUCTION_NAME, PRODUCTION_SHA
from test_world_history_legal import RELEASE45_ENV, RELEASE45_NAME, W, fixture, served
from test_encoder_round_compat import pinned_production_package  # noqa: F401

BELIEF_KEYS = {"belief_fallback", "belief_proposed", "belief_ms"}


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    torch = pytest.importorskip("torch")
    from shengji.train import belief_seq as bs
    from shengji.train.belief_sampler import export
    torch.manual_seed(5)
    model = bs.build_model(d=16, heads=2, enc_layers=1, xattn_layers=1, x_hidden=16).eval()
    root = tmp_path_factory.mktemp("bw")
    torch.save({"model": model.state_dict(), "config": model.config,
                "args": {"no_history": False}, "epoch": 1, "calib_ll": 1.0}, root / "best.pt")
    info = export(str(root / "best.pt"), str(root / "s17.npz"), temperature=1.0)
    return {"path": str(root / "s17.npz"), "sha256": info["sha256"]}


@pytest.fixture
def production_package(monkeypatch):
    import shengji.ai.cwv_policy as cwv
    monkeypatch.setattr(cwv, "checkpoint_id", lambda path: PRODUCTION_SHA[:8])
    monkeypatch.setattr(pv, "file_sha256", lambda path: _SHAS.get(str(path), PRODUCTION_SHA))


_SHAS: dict = {}


def names(env):
    return list(pv.pv_registry_entries(**pv.pv_env_recipe(env)))


def test_names_unchanged_off_and_distinct_on(production_package, package):
    _SHAS[package["path"]] = package["sha256"]
    assert names(PRODUCTION_ENV) == [PRODUCTION_NAME]
    assert names(RELEASE45_ENV) == [RELEASE45_NAME]
    off = {**RELEASE45_ENV, "SHENGJI_PV_WORLD_HISTORY_LEGAL": "1",
           "SHENGJI_PV_WORLD_HISTORY_DRAW": "1"}
    whl, = names(off)
    assert names({**off, "SHENGJI_PV_BELIEF_WORLDS": "0"}) == [whl]
    on = {**off, "SHENGJI_PV_BELIEF_WORLDS": "1", "SHENGJI_PV_BELIEF_CKPT": package["path"],
          "SHENGJI_PV_BELIEF_SHA256": package["sha256"]}
    bw, = names(on)
    assert "-rc-whl-whd-bw-tb-" in bw and bw != whl
    base = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                             world_history_legal=True, world_history_draw=True)
    assert "belief_worlds" not in pv.recipe_payload(base)
    assert "belief_sha256" not in pv.recipe_payload(base)
    a = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                          world_history_legal=True, world_history_draw=True, belief_worlds=True,
                          belief_sha256="a" * 64)
    b = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                          world_history_legal=True, world_history_draw=True, belief_worlds=True,
                          belief_sha256="b" * 64)
    pa = pv.recipe_payload(a)
    assert pa["belief_worlds"] is True and pa["belief_worlds_package"]["sha256"] == "a" * 64
    assert len({pv.recipe_digest(base), pv.recipe_digest(a), pv.recipe_digest(b)}) == 3


def test_flag_contract(production_package, package):
    with pytest.raises(pv.PVSearchPolicyError, match="requires world_history_legal and"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, belief_worlds=True,
                                            belief_sha256="a" * 64))
    with pytest.raises(pv.PVSearchPolicyError, match="requires world_history_legal and"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, belief_worlds=True,
                                            world_history_legal=True, belief_sha256="a" * 64))
    with pytest.raises(pv.PVSearchPolicyError, match="full sha256"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, belief_worlds=True,
                                            world_history_legal=True, world_history_draw=True))
    with pytest.raises(pv.PVSearchPolicyError, match="needs belief_worlds"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA,
                                            belief_sha256="a" * 64))
    with pytest.raises(pv.PVSearchPolicyError, match="go together"):
        pv.pv_env_recipe({**PRODUCTION_ENV, "SHENGJI_PV_BELIEF_CKPT": package["path"]})
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, "SHENGJI_PV_BELIEF_WORLDS": "yes"})
    with pytest.raises(pv.PVSearchPolicyError, match="BELIEF_(CKPT|SHA256)"):
        names({**PRODUCTION_ENV, "SHENGJI_PV_WORLD_HISTORY_LEGAL": "1",
               "SHENGJI_PV_WORLD_HISTORY_DRAW": "1", "SHENGJI_PV_BELIEF_WORLDS": "1"})
    _SHAS[package["path"]] = "c" * 64
    with pytest.raises(pv.PVSearchPolicyError, match="does not match"):
        names({**PRODUCTION_ENV, "SHENGJI_PV_WORLD_HISTORY_LEGAL": "1",
               "SHENGJI_PV_WORLD_HISTORY_DRAW": "1", "SHENGJI_PV_BELIEF_WORLDS": "1", "SHENGJI_PV_BELIEF_CKPT": package["path"],
               "SHENGJI_PV_BELIEF_SHA256": package["sha256"]})
    _SHAS.pop(package["path"])


def belief_bot(package, seed=7):
    bot = served(seed=seed, world_history_legal=True, world_history_draw=True, belief_worlds=True,
                 belief_sha256=package["sha256"])
    bot.belief_model = bn.load_belief_numpy(package["path"], package["sha256"])
    return bot


def test_served_draw_is_belief_proposed_and_history_legal(package):
    _, now, seat = fixture()
    bot = belief_bot(package)
    worlds, _ = bot._worlds(copy.deepcopy(now), seat)
    stats = bot._last_sampling
    assert len(worlds) == W
    assert stats["belief_fallback"] == 0 and stats["belief_proposed"] >= W
    constraints = HL.draw_constraints(now, seat)
    assert stats["history_draw_constraints"] == len(constraints) >= 1
    mem = Memory(now, seat, own_kitty=True)
    hidden = sum((__import__("collections").Counter(h) for s, h in enumerate(worlds[0][0])
                  if s != seat), __import__("collections").Counter())
    for hands, buried in worlds:
        assert hands[seat] == sorted(now.hands[seat])
        for s in range(4):
            assert len(hands[s]) == len(now.hands[s])
            if s != seat:
                assert not any(now.ordering.eff_suit(c) in mem.voids[s] for c in hands[s])
        assert HL.history_legal(now, seat, hands)
    assert sum(hidden.values()) == sum(len(now.hands[s]) for s in range(4) if s != seat)
    # the same seed draws the same worlds
    again, _ = belief_bot(package)._worlds(copy.deepcopy(now), seat)
    assert again == worlds


def test_any_error_falls_back_to_the_history_legal_draw(package, monkeypatch):
    _, now, seat = fixture()
    bot = belief_bot(package)
    monkeypatch.setattr(bn.BeliefNumpy, "marginals",
                        lambda self, inp: (_ for _ in ()).throw(RuntimeError("boom")))
    worlds, _ = bot._worlds(copy.deepcopy(now), seat)
    assert len(worlds) == W
    assert bot._last_sampling["belief_fallback"] == 1
    assert bot._last_sampling["belief_error"] == "RuntimeError"
    assert all(HL.history_legal(now, seat, hands) for hands, _ in worlds)
    unbound = served(world_history_legal=True, world_history_draw=True, belief_worlds=True,
                     belief_sha256=package["sha256"])
    worlds, _ = unbound._worlds(copy.deepcopy(now), seat)
    assert len(worlds) == W and unbound._last_sampling["belief_fallback"] == 1


def test_budget_expiry_is_not_swallowed(package):
    _, now, seat = fixture()
    bot = belief_bot(package)

    def expired():
        raise pv.PVSearchBudgetExceeded("pv-search serving budget expired")
    with pytest.raises(pv.PVSearchBudgetExceeded):
        bot._worlds(copy.deepcopy(now), seat, check_budget=expired)


@pytest.mark.parametrize('stage', ['entry', 'features', 'model'])
@pytest.mark.parametrize('error', [pv.PVSearchBudgetExceeded, pv._AdaptiveWorldsExpired])
def test_expired_belief_preparation_stops_before_next_stage(package, monkeypatch, stage, error):
    _, now, seat = fixture()
    bot = belief_bot(package)
    expired = stage == 'entry'
    calls = []
    rng_before = bot.sampler.rng.getstate()
    original_inputs, original_model = bn.decision_inputs, bn.BeliefNumpy.marginals

    def check():
        if expired:
            raise error('expired')

    def inputs(*args, **kwargs):
        nonlocal expired
        calls.append('features')
        result = original_inputs(*args, **kwargs)
        expired = stage == 'features'
        return result

    def model(self, inp):
        nonlocal expired
        calls.append('model')
        result = original_model(self, inp)
        expired = stage == 'model'
        return result

    def forbidden(*args, **kwargs):
        pytest.fail('expired preparation must not project or start either sampler')

    from shengji.train import belief_seq
    monkeypatch.setattr(bn, 'decision_inputs', inputs)
    monkeypatch.setattr(bn.BeliefNumpy, 'marginals', model)
    monkeypatch.setattr(belief_seq, 'project_sizes', forbidden)
    monkeypatch.setattr(pv, 'sample_worlds_history_legal', forbidden)
    with pytest.raises(error):
        bot._worlds(copy.deepcopy(now), seat, check_budget=check)
    assert calls == {'entry': [], 'features': ['features'], 'model': ['features', 'model']}[stage]
    if stage == 'entry':
        assert bot.sampler.rng.getstate() == rng_before


def test_record_and_snapshot(package):
    _, now, seat = fixture()
    bot = belief_bot(package)
    bot.decide_play(copy.deepcopy(now), seat)
    record = bot.last_decision_record
    assert BELIEF_KEYS <= set(record) and record["belief_fallback"] == 0
    json.dumps(record)
    snap = copy.deepcopy(bot)
    assert snap.belief_model is bot.belief_model
    off = served(world_history_legal=True, world_history_draw=True)
    off.decide_play(copy.deepcopy(now), seat)
    assert not BELIEF_KEYS & set(off.last_decision_record)


def test_pinned_serving_factory_snapshot_and_commit(pinned_production_package, package, tmp_path):
    """No stub model or sampler: the enabled env recipe reaches the live
    consumer through the server's snapshot and commit path."""
    import asyncio
    import random
    import tomllib
    from pathlib import Path
    from shengji.api import server as srv
    from shengji.engine.game import Game
    env = _r49_env()
    env.update(SHENGJI_PV_CKPT=str(pinned_production_package),
               SHENGJI_PV_WORLD_HISTORY_LEGAL="1", SHENGJI_PV_WORLD_HISTORY_DRAW="1",
               SHENGJI_PV_BELIEF_WORLDS="1",
               SHENGJI_PV_BELIEF_CKPT=package["path"], SHENGJI_PV_BELIEF_SHA256=package["sha256"])
    entries = pv.pv_registry_entries(**pv.pv_env_recipe(env))
    name, = entries
    bot = entries[name](seed=7)
    assert bot.belief_worlds and "-whl-whd-bw-" in name
    assert bot.belief_model.package_sha256 == package["sha256"]
    _, rnd, seat = fixture()

    async def scenario():
        game = Game(random.Random(0))
        game.round = rnd
        room = srv.Room(code="BW", game=game, bot=bot,
                        seats=[srv.Seat(str(s), is_bot=True) for s in range(4)], log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        room.log_event = lambda kind, **data: None
        before = list(rnd.hands[seat])
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None
        record = prepared.decision.snapshot.bot_copy.last_decision_record
        assert record["schema"] == pv.RECORD_SCHEMA and record["work_complete"]
        assert record["worlds"] == 64 and BELIEF_KEYS <= record.keys()
        assert record["belief_fallback"] == 0 and record["belief_proposed"] >= 64
        assert srv._commit_bot_turn(room, prepared)
        assert len(rnd.hands[seat]) == len(before) - len(prepared.decision.cards)

    asyncio.run(scenario())


def test_the_proposal_never_deals_a_forbidden_twin(package):
    """Every proposed hand (not only the accepted ones) honours the draw-time
    constraints, on states with follow history; the truth always does."""
    from test_world_history_draw import breaks_constraints, states
    model = bn.load_belief_numpy(package["path"], package["sha256"])
    checked = constrained = 0
    for rnd, seat in states(n_games=4):
        constraints = HL.draw_constraints(rnd, seat)
        assert not breaks_constraints(constraints, rnd.hands, rnd.ordering)
        propose = bn.BeliefProposal(model, rnd, seat, (), seed=3, batch=16, forbidden=constraints)
        mem = Memory(rnd, seat, own_kitty=True)
        for _ in range(16):
            hands, _ = propose(rnd, seat, mem)
            full = [hands.get(s, rnd.hands[s]) for s in range(4)]
            assert not breaks_constraints(constraints, full, rnd.ordering)
            checked += 1
        constrained += bool(constraints)
    assert checked > 100 and constrained > 3


def _r49_env():
    """Release 49's ``fly.toml`` env: the repo's, with release 50 rolled back (the
    release-49 recipe the identities in this module are derived from)."""
    from test_release49_fly_config import fly_env
    return fly_env()


def test_depth_redraw_pairs_replies_from_public_state(package):
    import torch

    from shengji.ai.cwv_policy import CompleteWorldEvaluator, afterstate
    from shengji.ai.refusal import observe_refusal, refusal_consistent
    from shengji.engine.legal import IllegalPlay
    from shengji.engine.round import actual_play_after
    from shengji.rl.value_model import ValueModelConfig, ValueNetwork
    from shengji.train.belief_tree_teacher import draw_depth_worlds, paired_reply_values
    from test_world_history_legal import started

    root, heuristic = started(13)
    root.play(root.turn, ["BJ", "H10"])
    refusal = observe_refusal(root)
    assert refusal is not None
    action = heuristic.decide_play(root, root.turn)
    child = afterstate(root, root.turn, root.hands, root.buried, action)
    seat = child.turn
    lead = child.trick.plays[0].cards[0]
    suit = child.ordering.eff_suit(lead)
    replies = [[card] for card in sorted(set(child.hands[seat]))
               if child.ordering.eff_suit(card) == suit][:2]
    assert len(replies) == 2
    belief = bn.load_belief_numpy(package["path"], package["sha256"])
    options = dict(belief=belief, refusals=(refusal,), seed=7, worlds=3)
    original = copy.deepcopy(child)
    worlds = draw_depth_worlds(child, **options)
    assert all(hands[seat] == sorted(child.hands[seat]) and HL.history_legal(child, seat, hands)
               and refusal_consistent(child, hands, refusal) for hands, _ in worlds)

    permuted = copy.deepcopy(child)
    permuted.deck.reverse()
    # A hidden hand and kitty can change together without changing this actor's view.
    other = (seat + 1) % 4
    i, j = next((i, j) for i, held in enumerate(permuted.hands[other])
                for j, buried in enumerate(permuted.buried) if held != buried)
    permuted.hands[other][i], permuted.buried[j] = permuted.buried[j], permuted.hands[other][i]
    assert draw_depth_worlds(permuted, **options) == worlds

    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(17)
        model = ValueNetwork(ValueModelConfig(architecture="mlp", width=16))
    evaluator = CompleteWorldEvaluator(None, model=model)
    scored = []

    def score(leaves, actor):
        assert actor == seat
        for leaf in leaves:
            world_index, reply_index = divmod(len(scored), len(replies))
            hands, buried = worlds[world_index]
            assert (leaf.hands[other], leaf.buried) == (hands[other], buried)
            assert actual_play_after(leaf, seat, child.last_trick) == replies[reply_index]
            scored.append(leaf)
        return evaluator.score(leaves, actor)

    values = paired_reply_values(child, replies, worlds, batch_size=4, score=score)
    assert values.shape == (3, 2)
    np.testing.assert_allclose(values.ravel(), evaluator.score(scored, seat), atol=1e-6)
    from_other_team = paired_reply_values(child, replies, worlds, batch_size=4,
                                         score=evaluator.score, value_seat=other)
    np.testing.assert_allclose(from_other_team.ravel(), evaluator.score(scored, other), atol=1e-6)
    with pytest.raises(IllegalPlay):
        paired_reply_values(child, [[*replies[0], *replies[1]]], worlds, batch_size=4,
                            score=evaluator.score)
    assert (child.hands, child.buried, child.turn, child.trick.plays, child.notice) == (
        original.hands, original.buried, original.turn, original.trick.plays, original.notice)
    with pytest.raises(ValueError, match="ledger disagrees"):
        draw_depth_worlds(child, **{**options, "refusals": ()})
    for broken_score in (
        lambda leaves, actor: [np.nan] * len(leaves),
        lambda leaves, actor: [0.] * (len(leaves) - 1),
    ):
        with pytest.raises(ValueError, match="finite root-team score"):
            paired_reply_values(child, replies, worlds, batch_size=4, score=broken_score)


def test_depth_redraw_keeps_banker_kitty_and_refuses_incomplete_draw(package, monkeypatch):
    from shengji.train import belief_tree_teacher as teacher
    from test_world_history_legal import started

    child, _ = started(13)
    assert child.turn == child.banker
    belief = bn.load_belief_numpy(package["path"], package["sha256"])
    options = dict(belief=belief, refusals=(), seed=9, worlds=2)
    worlds = teacher.draw_depth_worlds(child, **options)
    assert all(buried == child.buried for _, buried in worlds)
    hands, buried = worlds[0]
    action = [hands[child.turn][0]]
    def fail_score(leaves, actor):
        pytest.fail("invalid world was scored")

    with pytest.raises(ValueError, match="incomplete depth world"):
        teacher.paired_reply_values(child, [action], [(hands[:-1], buried)],
                                    batch_size=1, score=fail_score)
    other_card = next(c for c in hands[(child.turn + 1) % 4] if c != buried[0])
    with pytest.raises(ValueError, match="information known to the actor"):
        teacher.paired_reply_values(child, [action], [(hands, [other_card, *buried[1:]])],
                                    batch_size=1, score=fail_score)
    with pytest.raises(ValueError, match="substituted a depth reply"):
        teacher.paired_reply_values(child, [["BJ", "H10"]],
                                    [(child.hands, child.buried)], batch_size=1,
                                    score=lambda leaves, actor: pytest.fail("refused reply was scored"))

    # A draw shortfall must never supply duplicate, unchecked, or true hands.
    monkeypatch.setattr(teacher, "first_violation", lambda *args: 0)
    with pytest.raises(ValueError, match="0 of 2 history-legal worlds"):
        teacher.draw_depth_worlds(child, **options)

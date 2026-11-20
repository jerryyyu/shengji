"""The search-free card play (`train.search_free_play`): off by default, own-information only, legal,
deterministic, and its candidate description equals the history token the same play becomes."""
from __future__ import annotations

import copy
import random
from collections import Counter

import numpy as np
import pytest

from shengji.ai import belief_numpy as bn
from shengji.ai import registry
from shengji.ai import unified_numpy as un
from shengji.ai.env import observe_committed_play, play_prepared_round, prepare_round
from shengji.ai.heuristic import HeuristicBot
from shengji.ai.memory import Memory
from shengji.engine.game import Game
from shengji.engine.round import actual_play_after
from shengji.harvest.legal import enumerate_legal, is_legal
from shengji.train import search_free_play as sf

SMALL = {"d": 16, "heads": 4, "enc_layers": 1, "xattn_layers": 1, "x_hidden": 16, "card_self_attn": True}
CONFIG = {"trunk": SMALL, "heads": {"q_hidden": 8, "policy_hidden": 8}}


def _weights(shapes, rng):
    return {k: (0.3 * rng.standard_normal(s)).astype(np.float32) for k, s in shapes.items()}


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    rng = np.random.default_rng(5)
    path = tmp_path_factory.mktemp("sf") / "sf.npz"
    sha = sf.save_package(path, CONFIG, _weights(bn.expected_shapes(SMALL, **bn.DIMS), rng),
                          _weights(un.head_shapes(CONFIG), rng), _weights(sf.cand_shapes(CONFIG), rng), {"note": "test"})
    return str(path), sha


@pytest.fixture(scope="module")
def model(package):
    return sf.load_package(package[0], sha256=package[1])


def _play(make, seed):
    bots = [make(seat) for seat in range(4)]
    game = Game(random.Random(seed))
    prepare_round(game, bots)
    log = play_prepared_round(game, bots, record=True)
    return bots, game, log


def _states(seed, every=5):
    """Play states of a heuristic round, each just before a decision."""
    bots = [HeuristicBot() for _ in range(4)]
    game = Game(random.Random(seed))
    rnd = prepare_round(game, bots)
    k = 0
    while rnd.phase == "play":
        seat = rnd.turn
        if k % every == 0:
            yield copy.deepcopy(rnd), seat
        k += 1
        rnd.play(seat, bots[seat].decide_play(rnd, seat))
        observe_committed_play(rnd, bots)


def test_off_by_default_no_name_and_the_served_bot_is_untouched(package, monkeypatch):
    monkeypatch.delenv(sf.ENV_CKPT, raising=False)
    monkeypatch.delenv(sf.ENV_SHA256, raising=False)
    assert sf.registry_entries(registry.REGISTRY, {}) == {}
    assert not [n for n in registry.REGISTRY if f"-{sf.TOKEN}" in n and n.endswith(package[1][:8])]
    before = dict(registry.REGISTRY)
    plain = _play(lambda seat: registry.make_bot("smart", seed=11 + seat), 7)[2]
    env = {sf.ENV_CKPT: package[0], sf.ENV_SHA256: package[1], "SHENGJI_BOT": "smart"}
    entries = sf.registry_entries(registry.REGISTRY, env)
    assert list(entries) == [f"smart-{sf.TOKEN}{package[1][:8]}"]
    assert registry.REGISTRY == before
    again = _play(lambda seat: registry.make_bot("smart", seed=11 + seat), 7)[2]
    assert plain.history == again.history and plain.attacker_points == again.attacker_points


def test_one_variable_alone_or_an_unknown_base_refuses(package):
    with pytest.raises(sf.SearchFreeError):
        sf.registry_entries(registry.REGISTRY, {sf.ENV_CKPT: package[0]})
    with pytest.raises(sf.SearchFreeError):
        sf.registry_entries(registry.REGISTRY, {sf.ENV_CKPT: package[0], sf.ENV_SHA256: package[1], "SHENGJI_BOT": "nope"})
    with pytest.raises(sf.SearchFreeError):
        sf.load_package(package[0], sha256="0" * 64)


def test_declare_and_bury_are_the_wrapped_bots(package):
    env = {sf.ENV_CKPT: package[0], sf.ENV_SHA256: package[1], "SHENGJI_BOT": "smart"}
    (name, make), = sf.registry_entries(registry.REGISTRY, env).items()
    for seed in (3, 4):
        wrapped = [make(seed=20 + s) for s in range(4)]
        plain = [registry.make_bot("smart", seed=20 + s) for s in range(4)]
        assert all(b.policy_name == name for b in wrapped)
        a = prepare_round(Game(random.Random(seed)), wrapped)
        b = prepare_round(Game(random.Random(seed)), plain)
        assert (a.banker, a.trump_suit, a.declaration, sorted(a.buried)) == (b.banker, b.trump_suit, b.declaration, sorted(b.buried))
        assert [sorted(h) for h in a.hands] == [sorted(h) for h in b.hands]


def test_every_play_is_legal_accepted_and_repeatable(model):
    def make(seat):
        return sf.SearchFreeBot(HeuristicBot(), model)
    for seed in (1, 2, 3):
        runs = []
        for _ in range(2):
            bots = [make(s) for s in range(4)]
            game = Game(random.Random(seed))
            rnd = prepare_round(game, bots)
            plays = []
            while rnd.phase == "play":
                seat = rnd.turn
                anchor = HeuristicBot().decide_play(rnd, seat)
                cards = bots[seat].decide_play(rnd, seat)
                rec = bots[seat].last_decision_record
                assert rec["schema"] == sf.DECISION_SCHEMA and rec["candidates"] <= sf.CANDIDATES
                assert is_legal(rnd, seat, cards)
                prev = rnd.last_trick
                rnd.play(seat, cards)
                actual = actual_play_after(rnd, seat, prev)
                if sorted(cards) != sorted(anchor):
                    assert sorted(actual) == sorted(cards), "a proposed play other than the heuristic's is never refused"
                plays.append((seat, tuple(cards), tuple(rec["logits"] or ())))
                observe_committed_play(rnd, bots)
            assert sum(b.search_free_fallbacks for b in bots) == 0
            runs.append(plays)
        assert runs[0] == runs[1]


def test_the_candidate_token_is_the_history_token_of_the_accepted_play():
    checked = 0
    for seed in (11, 12, 13, 14):
        for rnd, seat in _states(seed, every=7):
            legal = enumerate_legal(rnd, seat, cap=40)
            for action in legal.actions[:40]:
                after = copy.deepcopy(rnd)
                prev = after.last_trick
                after.play(seat, list(action))
                if Counter(actual_play_after(after, seat, prev)) != Counter(action):
                    continue
                tok = bn.history_tokens(after)
                ints, f, cards, att = sf.candidate_token(rnd, seat, action)
                assert tuple(int(x) for x in tok["tok_int"][-1]) == ints
                assert np.allclose(tok["tok_f"][-1], f, atol=2e-3)
                assert np.array_equal(tok["tok_cards"][-1], cards) and not att.any() and not tok["tok_att"][-1].any()
                checked += 1
    assert checked > 300


def test_the_decision_reads_no_hidden_card(model):
    bot = sf.SearchFreeBot(HeuristicBot(), model)
    rng = random.Random(9)
    compared = 0
    for seed in (21, 22, 23):
        for rnd, seat in _states(seed, every=6):
            played = bot.decide_play(rnd, seat)
            rec = dict(bot.last_decision_record)
            other = copy.deepcopy(rnd)
            seats = [s for s in range(4) if s != seat]
            pool = [c for s in seats for c in other.hands[s]]
            rng.shuffle(pool)
            for s in seats:
                n = len(other.hands[s])
                other.hands[s][:] = pool[:n]
                del pool[:n]
            assert Counter(Memory(other, seat, own_kitty=True).unseen) == Counter(Memory(rnd, seat, own_kitty=True).unseen)
            again = sf.SearchFreeBot(HeuristicBot(), model)
            # the heuristic's own play is public-information too; the same anchor keeps the comparison about this module
            assert again.decide_play(other, seat) == played
            assert again.last_decision_record["logits"] == rec["logits"]
            compared += 1
    assert compared > 20


def test_a_model_error_plays_the_heuristic_and_is_recorded(model, monkeypatch):
    bot = sf.SearchFreeBot(HeuristicBot(), model)
    rnd, seat = next(iter(_states(31, every=1)))
    monkeypatch.setattr(sf, "propose", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert sorted(bot.decide_play(rnd, seat)) == sorted(HeuristicBot().decide_play(rnd, seat))
    rec = bot.last_decision_record
    assert rec["schema"] == sf.FALLBACK_SCHEMA and rec["error_class"] == "RuntimeError" and bot.search_free_fallbacks == 1


def test_the_proposal_holds_the_heuristics_play_first_and_no_refusable_lead(model):
    for rnd, seat in _states(41, every=4):
        anchor = HeuristicBot().decide_play(rnd, seat)
        inp = bn.decision_inputs(rnd, seat, ())
        logits = model.trunk_states(inp)["card_logits"]
        for rank in ("mean", "sum"):
            prop = sf.propose(rnd, seat, anchor, logits, rank=rank)
            acts = prop["actions"]
            assert sorted(acts[0]) == sorted(anchor) and len(acts) <= sf.CANDIDATES
            assert len({tuple(sorted(a)) for a in acts}) == len(acts)
            for a in acts[1:]:
                assert is_legal(rnd, seat, a)
                if prop["lead"]:
                    after = copy.deepcopy(rnd)
                    prev = after.last_trick
                    after.play(seat, list(a))
                    assert Counter(actual_play_after(after, seat, prev)) == Counter(a)

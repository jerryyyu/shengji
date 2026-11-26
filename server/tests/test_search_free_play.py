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
    monkeypatch.setattr(model, "trunk_states", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
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


def test_candidate_shard_restores_pre_play_inputs_across_hidden_deals(tmp_path, model):
    from shengji.ai.refusal import Refusal
    from shengji.engine.round import Round, Trick
    from shengji.engine.cards import Ordering
    from shengji.train.search_free_candidates import convert

    attempt = ["C5", "C5", "D5", "D5", "H5", "H5"]
    ballot = [attempt, ["S8"]]
    resolved = []
    sizes = []
    for opponents in ([["LJ", "LJ"], ["C8"], ["D8"]], [["LJ", "C8"], ["LJ"], ["D8"]]):
        rnd = Round("5", 0, random.Random(1))
        rnd.phase, rnd.turn, rnd.trump_suit = "play", 0, "H"
        rnd.ordering = Ordering("H", "5")
        rnd.hands = [attempt + ["S8"], *opponents]
        rnd.trick = Trick(leader=0)
        for action in ballot:
            after = copy.deepcopy(rnd)
            after.play(0, action)
            forced = after.trick.plays[0].cards
            if action == attempt:
                sizes.append(len(forced))
            resolved.append(bn.history_tokens(after, [Refusal(0, tuple(action), tuple(forced), 0)]))
    assert sizes == [2, 6]

    source, dest = tmp_path / "resolved.npz", tmp_path / "public.npz"
    labels = dict(n_rows=2, row=[0, 0, 1, 1], slot=[0, 1, 0, 1],
                  mean=[0.4, 0.6, 0.8, 0.2], played=[False, True, True, False])
    tokens = {k: np.concatenate([t[k] for t in resolved]) for k in resolved[0]}
    # Candidate shards store float features at full precision, unlike rounded history inputs.
    tokens["tok_f"] = tokens["tok_f"].astype(np.float32)
    tokens["tok_f"][:, 7] = [0.4, 0, 1.2, 0]
    for key in ("tok_cards", "tok_att"):
        tokens[key] = tokens[key].astype(np.uint8)
    np.savez(source, **labels, **tokens)
    assert convert(source, dest) == 1
    with pytest.raises(FileExistsError):
        convert(source, dest)
    expected = [sf.candidate_token(rnd, 0, a) for a in ballot]
    inp = bn.decision_inputs(rnd, 0)
    states = model.trunk_states(inp)
    with np.load(dest) as cand:
        for k, v in labels.items():
            np.testing.assert_array_equal(cand[k], v)
        for row in (0, 1):
            batch = list(zip(*(cand[k][cand["row"] == row] for k in
                               ("tok_int", "tok_f", "tok_cards", "tok_att"))))
            for tok, live in zip(batch, expected):
                for field, served in zip(tok, live):
                    np.testing.assert_array_equal(field, served)
            np.testing.assert_array_equal(model.score(inp, states, batch), model.score(inp, states, expected))


@pytest.mark.parametrize("level", ["standard", "beginner"])
def test_single_action_skips_the_trunk_and_preserves_the_next_draw(package, monkeypatch, level):
    from shengji.train import relaxed_play as rp

    build = rp.build_casual if level == "standard" else rp.build_beginner
    path, digest = package
    fast = build(HeuristicBot(), path, seed=31, sha256=digest)
    reference = build(HeuristicBot(), path, seed=31, sha256=digest)
    player = reference.player
    trunk = player.model.trunk_states
    calls = []

    def count(inp):
        calls.append(1)
        return trunk(inp)

    def always_encode(rnd, seat, anchor, refusals):
        inp = bn.decision_inputs(rnd, seat, refusals)
        states = trunk(inp)
        prop = sf.propose(rnd, seat, anchor, states["card_logits"], candidates=player.candidates, cap=player.cap)
        if len(prop["actions"]) == 1:
            return prop, None, None
        tokens = [sf.candidate_token(rnd, seat, action) for action in prop["actions"]]
        return prop, *player.model.score(inp, states, tokens)

    monkeypatch.setattr(player, "_scored_proposal", always_encode)
    monkeypatch.setattr(fast.player.model, "trunk_states", count)
    forced = branching = 0
    for rnd, seat in _states(31, every=1):
        single = len(enumerate_legal(rnd, seat, cap=fast.player.cap).actions) == 1
        before = len(calls)
        assert fast.decide_play(rnd, seat) == reference.decide_play(rnd, seat)
        assert fast.last_decision_record["schema"] == rp.RECORD_SCHEMA
        assert fast.rng.getstate() == reference.rng.getstate()
        assert fast.player._ledger.refusals == reference.player._ledger.refusals
        assert len(calls) - before == int(not single)
        forced += single
        branching += not single
    assert forced and branching


@pytest.mark.parametrize("trusted", [False, True])
@pytest.mark.parametrize("extra, winner", [("H9", 3), ("H8", 2)])
def test_all_single_throw_overruff_reaches_the_search_free_ballot(trusted, extra, winner):
    from shengji.engine.cards import Ordering
    from shengji.engine.round import Round, Trick

    rnd = Round("7", 0, random.Random(11))
    rnd.phase, rnd.turn, rnd.trump_suit = "play", 0, "H"
    rnd.ordering = Ordering("H", "7")
    rnd.trick = Trick(leader=0)
    rnd.hands = [["CA", "CK", "S2", "S3"], ["D2", "D3", "D4", "D6"],
                 ["H4", "H8", "S4", "S5"], ["H2", "H3", extra, "S6"]]
    rnd._trusted_rollout = trusted
    for seat, action in enumerate((["CA", "CK"], ["D2", "D3"], ["H4", "H8"])):
        rnd.play(seat, action)
    anchor = HeuristicBot().decide_play(rnd, 3)
    assert is_legal(rnd, 3, anchor)
    proposal = sf.propose(rnd, 3, anchor, np.zeros(54))
    assert Counter(proposal["actions"][0]) == Counter(anchor)
    rnd.play(3, proposal["actions"][0])
    assert rnd.last_trick.winner == winner
    assert rnd.last_trick.points == 10
    if winner == 3:
        assert Counter(anchor) == Counter(["H2", "H9"])


@pytest.mark.parametrize("trusted", [False, True])
@pytest.mark.parametrize("lead, ruff, low, high", [
    (["CA", "CA", "CK"], ["H6", "H6", "HA"], ["H2", "H2"], ["H8", "H8"]),
    (["CQ", "CQ", "CK", "CK", "CA"], ["H4", "H4", "H5", "H5", "HA"],
     ["H2", "H2", "H3", "H3"], ["H8", "H8", "H9", "H9"]),
])
def test_mixed_throw_overruff_reaches_ballot_and_wins(trusted, lead, ruff, low, high):
    from shengji.engine.cards import Ordering
    from shengji.engine.round import Round, Trick

    rnd = Round("7", 0, random.Random(11))
    rnd.phase, rnd.turn, rnd.trump_suit = "play", 0, "H"
    rnd.ordering = Ordering("H", "7")
    rnd.trick = Trick(leader=0)
    discard = ["D2", "D3", "D4", "D5", "D6"][:len(lead)]
    follow_hand = low + high + ["S6"]
    fillers = len(follow_hand) - len(lead)
    rnd.hands = [lead + ["S2", "S3", "S4", "S5"][:fillers],
                 discard + ["S8", "S9", "S10", "SJ"][:fillers],
                 ruff + ["SQ", "SK", "SA", "D8"][:fillers], follow_hand]
    rnd._trusted_rollout = trusted
    for seat, cards in enumerate((lead, discard, ruff)):
        rnd.play(seat, cards)
    anchor = HeuristicBot().decide_play(rnd, 3)
    assert Counter(anchor) == Counter(high + ["H2"])
    proposal = sf.propose(rnd, 3, anchor, np.zeros(54))
    assert Counter(proposal["actions"][0]) == Counter(anchor)
    rnd.play(3, proposal["actions"][0])
    assert rnd.last_trick.winner == 3


@pytest.mark.parametrize("trusted", [False, True])
@pytest.mark.parametrize("spare,winner", [("H3", 3), ("S3", 2)])
def test_pair_throw_overruff_avoids_a_lower_filler_pair(trusted, spare, winner):
    from shengji.engine.cards import Ordering
    from shengji.engine.round import Round, Trick

    rnd = Round("7", 0, random.Random(11))
    rnd.phase, rnd.turn, rnd.trump_suit = "play", 0, "H"
    rnd.ordering = Ordering("H", "7")
    rnd.trick = Trick(leader=0)
    lead = ["CA", "CA", "CK", "CQ"]
    discard = ["D2", "D3", "D4", "D6"]
    ruff = ["H6", "H6", "HJ", "HA"]
    rnd.hands = [lead + ["S2"], discard + ["S4"], ruff + ["S5"],
                 ["H2", "H2", "H8", "H8", spare]]
    rnd._trusted_rollout = trusted
    for seat, cards in enumerate((lead, discard, ruff)):
        rnd.play(seat, cards)
    anchor = HeuristicBot().decide_play(rnd, 3)
    assert is_legal(rnd, 3, anchor)
    proposal = sf.propose(rnd, 3, anchor, np.zeros(54))
    rnd.play(3, proposal["actions"][0])
    assert rnd.last_trick.winner == winner
    if winner == 3:
        assert Counter(anchor) == Counter(["H8", "H8", "H2", "H3"])


def test_overruff_matches_cheapest_engine_winner_for_every_throw_shape():
    from itertools import combinations, combinations_with_replacement
    from shengji.engine.cards import Ordering, TRUMP, points
    from shengji.engine.legal import beats

    o = Ordering("H", "7")
    bot = HeuristicBot()
    leads = [
        ["CA", "CK"], ["CA", "CA", "CK"], ["CA", "CA", "CK", "CJ"],
        ["CA", "CA", "CJ", "CJ"], ["CA", "CA", "CJ", "CJ", "CK"],
        ["CA", "CA", "CK", "CK", "CJ", "C9"],
        ["CA", "CA", "CK", "CK", "C9", "C9"],
    ]
    for cards in combinations_with_replacement(["H3", "H4", "H5", "H8", "D7"], 7):
        if max(Counter(cards).values()) > 2:
            continue
        for lead in leads:
            plays = set(combinations(cards, len(lead)))
            for incumbent in ("H3", "H5", "H8"):
                floor = o.level(incumbent)
                def cost(play):
                    return (beats(list(play), lead, TRUMP, floor, o)[1], sum(map(points, play)),
                            tuple(sorted(map(o.level, play), reverse=True)), tuple(sorted(play)))
                winners = (p for p in plays if beats(list(p), lead, TRUMP, floor, o)[0])
                expected = min(winners, key=cost, default=())
                actual = bot._cheapest_winning(list(cards), lead, TRUMP, floor, o)
                assert Counter(actual or ()) == Counter(expected), (cards, lead, incumbent)

    # Two disjoint tractors compete for overlapping trump pairs. Breaking
    # unused copies into singles can change which tractor the engine matches.
    hand = [c for c in ("H2", "H3", "H4", "H5", "H8", "H9") for _ in range(2)]
    for extra in ([], ["CJ"]):
        lead = [c for c in ("CA", "CK", "C8", "C9") for _ in range(2)] + extra
        for floor in map(o.level, ("H3", "H5", "H9")):
            valid = []
            for play in set(combinations(hand, len(lead))):
                wins, top = beats(list(play), lead, TRUMP, floor, o)
                if wins:
                    valid.append((top, sum(map(points, play)), tuple(sorted(map(o.level, play), reverse=True)),
                                  tuple(sorted(play))))
            actual = bot._cheapest_winning(hand, lead, TRUMP, floor, o)
            assert tuple(sorted(actual or ())) == (min(valid)[-1] if valid else ())

    # At the same winning rank the off-suit level cards tie. Code order is
    # deterministic even if the pair codes entered the hand in reverse.
    hand = ["S7", "S7", "C7", "C7", "H5", "H8"]
    assert Counter(bot._cheapest_winning(hand, leads[1], TRUMP, o.level("HA"), o)) == Counter(["C7","C7","H8"])


def test_partner_ruff_keeps_the_original_ballot_choice(monkeypatch):
    from shengji.engine.cards import Ordering, TRUMP

    bot = HeuristicBot()
    o = Ordering("H", "7")
    def forbidden(*args):
        pytest.fail("exact overruff search reached outside an opposing ruff")
    monkeypatch.setattr(bot, "_overruff", forbidden)
    hand = ["H2", "H2", "H8", "H8", "H3"]
    lead = ["CA", "CA", "CK", "CQ"]
    assert bot._cheapest_winning(hand, lead, TRUMP, o.level("H6"), o, opposing=False) is None
    assert bot._cheapest_winning(hand, lead, "C", o.level("CA"), o) is not None
    assert bot._cheapest_winning(hand + ["C3"], lead, TRUMP, 0, o) is None
    assert bot._cheapest_winning(hand[:2], lead, TRUMP, 0, o) is None

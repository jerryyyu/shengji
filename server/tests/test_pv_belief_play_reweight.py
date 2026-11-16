"""The OPTIONAL play-likelihood resample of the belief proposal's worlds
(``belief_play_reweight``, `train.belief_play_reweight`).

Witnesses: off, names and digests are unchanged, the module is never entered and the draw is
the belief proposal's own; on, the name gains ``-bpr`` and the digest names the rule; the flag
needs ``belief_worlds``; the rewound past states equal deep-copied snapshots of the table (the
public fields, the prior's rows and the legal sets, a refused throw on record included); the
lead normaliser equals the enumerated one; a candidate that could not have made a play has
weight zero; the served draw with the flag is seeded, history-legal, drawn from the candidates
and recorded; no finite candidate keeps the plain draw; a budget expiry is not swallowed.
"""
import copy
import math

import numpy as np
import pytest

from shengji.ai import belief_numpy as bn
from shengji.ai import history_legality as HL
from shengji.ai.heuristic import HeuristicBot
from shengji.harvest import legal as harvest_legal
from shengji.train import belief_play_reweight as bpr
from shengji.train import pv_search_policy as pv
from shengji.train.cwv_prior_admission import root_clone
from shengji.train.policy_prior import CARD_INDEX, flat_input, root_tensors
from test_refusal_constraints import PRODUCTION_ENV, PRODUCTION_NAME, PRODUCTION_SHA
from test_world_history_legal import RELEASE45_ENV, RELEASE45_NAME, W, fixture, served, started
from test_pv_belief_worlds import BELIEF_KEYS, _SHAS, names, package, production_package  # noqa: F401

FLAG = "SHENGJI_PV_BELIEF_PLAY_REWEIGHT"
REWEIGHT_KEYS = {"play_reweight_candidates", "play_reweight_alive", "play_reweight_ess",
                 "play_reweight_degenerate", "play_reweight_distinct", "play_reweight_ms"}


def bw_env(package):
    return {**RELEASE45_ENV, "SHENGJI_PV_WORLD_HISTORY_LEGAL": "1",
            "SHENGJI_PV_WORLD_HISTORY_DRAW": "1", "SHENGJI_PV_BELIEF_WORLDS": "1",
            "SHENGJI_PV_BELIEF_CKPT": package["path"], "SHENGJI_PV_BELIEF_SHA256": package["sha256"]}


def belief_bot(package, seed=7, reweight=True):
    rules = dict(world_history_legal=True, world_history_draw=True, belief_worlds=True,
                 belief_sha256=package["sha256"])
    if reweight:
        rules["belief_play_reweight"] = True
    bot = served(seed=seed, **rules)
    bot.belief_model = bn.load_belief_numpy(package["path"], package["sha256"])
    return bot


def test_names_unchanged_off_and_distinct_on(production_package, package):
    _SHAS[package["path"]] = package["sha256"]
    assert names(PRODUCTION_ENV) == [PRODUCTION_NAME]
    assert names(RELEASE45_ENV) == [RELEASE45_NAME]
    bw, = names(bw_env(package))
    assert names({**bw_env(package), FLAG: "0"}) == [bw]
    on, = names({**bw_env(package), FLAG: "1"})
    assert "-whl-whd-bw-bpr-tb-" in on and on != bw and "-bpr-" not in bw
    _SHAS.pop(package["path"])
    common = dict(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                  world_history_legal=True, world_history_draw=True, belief_worlds=True,
                  belief_sha256=package["sha256"])
    off_payload = pv.recipe_payload(pv.PVSearchConfig(**common))
    on_payload = pv.recipe_payload(pv.PVSearchConfig(**common, belief_play_reweight=True))
    assert "belief_play_reweight" not in off_payload and "belief_play_reweight_rule" not in off_payload
    assert on_payload["belief_play_reweight"] is True
    assert on_payload["belief_play_reweight_rule"] == bpr.IDENTITY
    assert pv.recipe_digest(pv.PVSearchConfig(**common)) != pv.recipe_digest(
        pv.PVSearchConfig(**common, belief_play_reweight=True))


def test_flag_wiring_defaults_and_requirement(package):
    assert pv.RULE_FLAGS["BELIEF_PLAY_REWEIGHT"] == "belief_play_reweight"
    assert pv.SAMPLER_DEFAULTS["belief_play_reweight"] is False
    assert ("belief_play_reweight", "bpr") in pv.SAMPLER_TOKENS
    assert bpr.CANDIDATES == 512 and bpr.TAU == 2.0
    with pytest.raises(pv.PVSearchPolicyError, match="requires belief_worlds"):
        served(world_history_legal=True, world_history_draw=True, belief_play_reweight=True)
    with pytest.raises(pv.PVSearchPolicyError):
        pv.pv_env_recipe({**RELEASE45_ENV, FLAG: "yes"})
    assert belief_bot(package, reweight=False).belief_play_reweight is False
    assert belief_bot(package).belief_play_reweight is True


def _game_with_snapshots(game_seed, throw=False):
    """A heuristic round played out, a deep copy of the table before every play.  ``throw``
    submits, at the first lead where the engine refuses it, a seat's whole side suit."""
    rnd, h = started(game_seed)
    snaps, thrown = [], False
    while rnd.phase == "play":
        seat = rnd.turn
        cards = h.decide_play(rnd, seat)
        if throw and not thrown and not rnd.trick.plays:
            o = rnd.ordering
            for suit in "SHDC":
                attempt = [c for c in rnd.hands[seat] if o.eff_suit(c) == suit]
                if len(set(attempt)) < 2:
                    continue
                probe = copy.deepcopy(rnd)
                probe.play(seat, list(attempt))
                if probe.notice is not None and probe.notice.get("kind") == "failed_throw":
                    cards, thrown = attempt, True
                    break
        snaps.append(copy.deepcopy(rnd))
        rnd.play(seat, list(cards))
    return rnd, snaps, thrown


def _same_public(a, b):
    assert a.turn == b.turn and a.phase == b.phase == "play"
    assert a.attacker_points == b.attacker_points
    assert [(t.leader, t.winner, t.points, [(p.seat, p.cards) for p in t.plays]) for t in a.history] == \
        [(t.leader, t.winner, t.points, [(p.seat, p.cards) for p in t.plays]) for t in b.history]
    assert a.trick.leader == b.trick.leader
    assert [(p.seat, p.cards) for p in a.trick.plays] == [(p.seat, p.cards) for p in b.trick.plays]


@pytest.mark.parametrize("game_seed,throw", [(0, False), (3, False), (5, True), (11, True)])
def test_rewound_states_equal_the_snapshots(game_seed, throw):
    rnd, snaps, thrown = _game_with_snapshots(game_seed, throw)
    # the last decision state of the round and one mid-round state are rewound to every earlier ply
    checked = 0
    for at in (len(snaps) - 1, len(snaps) // 2):
        now = snaps[at]
        plays = bpr.past_plays(now)
        assert len(plays) == at
        for t, (k, j, seat, cards) in enumerate(plays):
            snap = snaps[t]
            past = bpr.rewind(now, k, j)
            assert snap.turn == seat
            _same_public(past, snap)
            a = root_clone(past, snap.hands, snap.buried)
            b = root_clone(snap, snap.hands, snap.buried)
            for viewer in range(4):
                ra = flat_input(root_tensors(a, viewer, 2), 2)
                rb = flat_input(root_tensors(b, viewer, 2), 2)
                assert np.array_equal(ra, rb)
            la = harvest_legal.enumerate_legal(a, seat, cap=200).actions
            lb = harvest_legal.enumerate_legal(b, seat, cap=200).actions
            assert la == lb
            assert harvest_legal.is_legal(a, seat, sorted(cards))
            checked += 1
    assert checked > 100
    if throw:
        assert thrown, "the parametrized game has no refused throw to cover"


def test_lead_normaliser_equals_the_enumerated_one():
    rnd, snaps, _ = _game_with_snapshots(2)
    rng = np.random.default_rng(0)
    seen = 0
    for snap in snaps[-24:]:
        if snap.trick.plays or not 1 <= len(snap.hands[snap.turn]) <= 6:
            continue
        seat = snap.turn
        lg = rng.normal(size=54)
        legal = harvest_legal.enumerate_legal(root_clone(snap, snap.hands, snap.buried), seat, cap=None)
        assert legal.complete
        sums = [sum(lg[CARD_INDEX[c]] for c in action) for action in legal.actions]
        brute = math.log(sum(math.exp(x) for x in sums))
        assert bpr.lead_logsumexp(snap.hands[seat], snap.ordering, lg) == pytest.approx(brute, abs=1e-9)
        seen += 1
    assert seen >= 2


def _contradicted_void(now, seat):
    """The true deal, and a copy in which a seat that showed out of a led suit holds a card of
    that suit it never played (swapped in from a third seat); None when the state has no such
    play."""
    truth = ([sorted(h) for h in now.hands], sorted(now.buried))
    o = now.ordering
    for trick in list(now.history) + [now.trick]:
        if not trick.plays:
            continue
        led = o.eff_suit(trick.plays[0].cards[0])
        for p in trick.plays[1:]:
            if p.seat == seat or all(o.eff_suit(c) == led for c in p.cards):
                continue
            for giver in range(4):
                if giver in (seat, p.seat):
                    continue
                give = [c for c in truth[0][giver] if o.eff_suit(c) == led]
                back = [c for c in truth[0][p.seat] if o.eff_suit(c) != led]
                if give and back:
                    hands = [list(h) for h in truth[0]]
                    hands[giver].remove(give[0]); hands[giver].append(back[0])
                    hands[p.seat].remove(back[0]); hands[p.seat].append(give[0])
                    return truth, ([sorted(h) for h in hands], truth[1])
    return None


def test_loglik_is_finite_for_the_true_deal_and_zero_weight_for_an_impossible_hand(package):
    from test_world_history_draw import states
    bot = belief_bot(package)
    checked = 0
    for now, seat in states(n_games=4, every=7, min_trick=6):
        pair = _contradicted_void(now, seat)
        if pair is None:
            continue
        ll = bpr.play_loglik(bot, now, seat, list(pair))
        assert np.isfinite(ll[0]) and ll[0] < 0.0
        assert ll[1] == -math.inf
        assert np.array_equal(ll, bpr.play_loglik(bot, now, seat, list(pair)))
        checked += 1
    assert checked >= 3
    assert bpr.ess([0.0, -math.inf]) == 1.0 and bpr.ess([-math.inf]) == 0.0


def test_served_draw_with_the_flag_is_seeded_history_legal_and_recorded(package, monkeypatch):
    _, now, seat = fixture()
    monkeypatch.setattr(bpr, "CANDIDATES", 48)
    bot = belief_bot(package)
    seen = {}
    real = bpr.resample

    def spy(bot_, rnd, seat_, candidates, count, seed, check_budget=None):
        seen["candidates"] = list(candidates)
        return real(bot_, rnd, seat_, candidates, count, seed, check_budget)
    monkeypatch.setattr(bpr, "resample", spy)
    worlds, _ = bot._worlds(copy.deepcopy(now), seat)
    stats = dict(bot._last_sampling)
    assert len(worlds) == W and len(seen["candidates"]) == 48
    assert all(w in seen["candidates"] for w in worlds)
    assert stats["belief_fallback"] == 0 and stats["belief_proposed"] >= 48
    assert REWEIGHT_KEYS <= set(stats)
    assert stats["play_reweight_candidates"] == 48 and stats["play_reweight_degenerate"] == 0
    assert 1 <= stats["play_reweight_distinct"] <= W and 0 < stats["play_reweight_ess"] <= 48
    for hands, _ in worlds:
        assert hands[seat] == sorted(now.hands[seat])
        assert HL.history_legal(now, seat, hands)
    again, _ = belief_bot(package)._worlds(copy.deepcopy(now), seat)
    assert again == worlds
    other, _ = belief_bot(package, seed=8)._worlds(copy.deepcopy(now), seat)
    assert other != worlds
    bot.decide_play(copy.deepcopy(now), seat)
    record = bot.last_decision_record
    assert BELIEF_KEYS <= set(record) and REWEIGHT_KEYS <= set(record)
    first = belief_bot(package).decide_play(copy.deepcopy(now), seat)
    second = belief_bot(package).decide_play(copy.deepcopy(now), seat)
    assert first == second


def test_flag_off_never_enters_the_module_and_draws_the_proposal_itself(package, monkeypatch):
    _, now, seat = fixture()

    def boom(*a, **k):
        raise AssertionError("the resample ran with the flag off")
    monkeypatch.setattr(bpr, "resample", boom)
    monkeypatch.setattr(bpr, "play_loglik", boom)
    batches = []
    real = bn.BeliefProposal

    class Spy(real):
        def __init__(self, *a, **k):
            batches.append(k["batch"])
            super().__init__(*a, **k)
    monkeypatch.setattr(bn, "BeliefProposal", Spy)
    off = belief_bot(package, reweight=False)
    worlds, _ = off._worlds(copy.deepcopy(now), seat)
    assert batches == [W] and not REWEIGHT_KEYS & set(off._last_sampling)
    # a bot object without the attribute (an older snapshot) takes the same path, the same worlds
    bare = belief_bot(package, reweight=False)
    del bare.belief_play_reweight
    assert bare._worlds(copy.deepcopy(now), seat)[0] == worlds
    play = belief_bot(package, reweight=False).decide_play(copy.deepcopy(now), seat)
    bare2 = belief_bot(package, reweight=False)
    del bare2.belief_play_reweight
    assert bare2.decide_play(copy.deepcopy(now), seat) == play
    assert not REWEIGHT_KEYS & set(bare2.last_decision_record)


def test_no_finite_candidate_keeps_the_plain_draw(package, monkeypatch):
    _, now, seat = fixture()
    monkeypatch.setattr(bpr, "CANDIDATES", 48)
    monkeypatch.setattr(bpr, "play_loglik",
                        lambda bot, rnd, seat, cands, check_budget=None: np.full(len(cands), -math.inf))
    kept = {}
    real = bpr.resample

    def spy(bot_, rnd, seat_, candidates, count, seed, check_budget=None):
        kept["first"] = list(candidates[:count])
        return real(bot_, rnd, seat_, candidates, count, seed, check_budget)
    monkeypatch.setattr(bpr, "resample", spy)
    bot = belief_bot(package)
    worlds, _ = bot._worlds(copy.deepcopy(now), seat)
    assert worlds == kept["first"] and bot._last_sampling["play_reweight_degenerate"] == 1
    assert bot._last_sampling["belief_fallback"] == 0


def test_budget_expiry_is_not_swallowed(package, monkeypatch):
    _, now, seat = fixture()
    monkeypatch.setattr(bpr, "CANDIDATES", 48)
    bot = belief_bot(package)
    calls = {"n": 0}
    real = bpr.play_loglik

    def late(bot_, rnd, seat_, cands, check_budget=None):
        def expired():
            raise pv.PVSearchBudgetExceeded("pv-search serving budget expired")
        return real(bot_, rnd, seat_, cands, expired)
    monkeypatch.setattr(bpr, "play_loglik", late)
    with pytest.raises(pv.PVSearchBudgetExceeded):
        bot._worlds(copy.deepcopy(now), seat)

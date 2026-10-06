"""The OPTIONAL doomed-throw swap of the pv-search bot (``doomed_throw_swap``,
``SHENGJI_PV_DOOMED_THROW_SWAP``): on a LEAD whose selected action is a throw the
engine refuses in EVERY sampled world with ONE forced component, the forced
component is played instead.  The throw's leaf already is that component played
(a rollout clone posts no failed-throw notice), so the value pass cannot tell
them apart; the swap removes only the public notice and the cards it shows.

The production case: room OXPS round 1, the lead of trick 2, banker seat 1 (release
38) led C2 D6 D6 DQ DQ (diamonds trump, rank 2).  C2 is beaten by any higher trump
single and seat 1, the banker, holds or buried every card but the other three
hands, so the throw fails in every deal and the engine plays C2.  The search
valued the throw exactly at C2's value (and C2 D2 DQ DQ, the other C2 throw,
identically); first-argmax admission order picked the throw.

Torch-free and package-free: the real deal and the real engine, the served
wrapper's own sampler, a stub policy that ranks the production throw first and a
stub value head that only sees the leaf state.  Witnesses: (a) the real decision
swaps to C2 with the value means, ballot and selection unchanged; (b) the engine
plays C2 either way and only the throw posts a notice; (c) a throw that stands in
every world, in only some worlds, or is forced to different components is played
unchanged; (d) follows and single leads are untouched; (e) off == before, on the
real decision and on the shared fixture's lead and follow; (f) budget; (g) name /
env / digest.
"""
import copy

import numpy as np
import pytest

from shengji.ai.memory import Memory
from shengji.ai.refusal import RefusalLedger, pin_unplayed_attempt
from shengji.harvest.legal import forced_lead
from shengji.rl.replay_log import rebuild_round
from shengji.train import policy_value_search as module
from shengji.train import pv_search_policy as pv
from shengji.train.policy_value_search import PolicyValueBot
from test_policy_world_search import state
from test_pv_adaptive_k import follow_position
from test_pv_admission_rules import (PRODUCTION_ENV, PRODUCTION_SHA, ZeroEvaluator, names,
                                     predict, production_package)  # noqa: F401

# Room OXPS round 1 (logs/OXPS.jsonl, release 38): the deal, the declaration, the
# bury and the first trick -- everything `rebuild_round` and the play replay need
# to reach seat 1's lead of trick 2.  No player names.
OXPS_DECK = (
    "H2 D6 C9 S9 S9 S5 C8 H3 H8 D7 H4 D4 H10 S6 HQ SJ C6 S7 H6 C5 C2 C3 BJ H7 S4 DK HQ "
    "CQ SK C6 S7 S6 SQ DQ H2 D10 D7 D2 C4 S8 D10 C10 SJ C8 CA C4 LJ H3 S2 D6 CK D9 S5 D2 "
    "BJ SA HK D5 D5 C3 H7 H9 DA HJ D4 LJ S8 H10 H6 DJ D3 S3 HK H8 SA DA C7 H5 D3 S3 DK CK "
    "HA D8 HJ CJ HA C5 S10 C7 SQ H4 DJ C9 CQ H5 S2 S4 CA D9 H9 DQ CJ S10 D8 C10 C2 SK"
).split()
OXPS_EVENTS = [
    {"e": "round_start", "trump_rank": "2", "banker": None, "deck": OXPS_DECK},
    {"e": "declare", "seat": 1, "cards": ["D2", "D2"]},
    {"e": "trump", "suit": "D", "rank": "2", "banker": 1},
    {"e": "bury", "seat": 1, "cards": ["C3", "S4", "C4", "S6", "S7", "C6", "H8", "C7"]},
    {"e": "play", "seat": 1, "cards": ["C10", "C10", "CJ", "CJ"]},
    {"e": "play", "seat": 2, "cards": ["C4", "C8", "C9", "CQ"]},
    {"e": "play", "seat": 3, "cards": ["C3", "C5", "C5", "CQ"]},
    {"e": "play", "seat": 0, "cards": ["S4", "C6", "C7", "CA"]},
]
SEAT = 1
THROW = ["C2", "D6", "D6", "DQ", "DQ"]
OTHER_C2_THROW = ["C2", "D2", "DQ", "DQ"]
FORCED = ["C2"]
#: release 38's four rules, as served
RELEASE38_RULES = dict(admission_diversity=True, refusal_constraints=True,
                       tiebreak_points=True, lead_anchor=True)
RULE_KEYS = {"doomed_throw_swap_applied", "doomed_throw_swap_from", "doomed_throw_swap_to",
             "doomed_throw_swap_worlds", "doomed_throw_swap_refused_worlds",
             "doomed_throw_swap_forced_variants"}


def oxps():
    rnd = rebuild_round(OXPS_EVENTS)
    for e in OXPS_EVENTS:
        if e["e"] == "play":
            rnd.play(e["seat"], list(e["cards"]))
    assert module.leading(rnd) and rnd.turn == SEAT and len(rnd.history) == 1
    return rnd


class LeafEvaluator:
    """A stub value head that reads only the leaf STATE: 1 when the root seat's
    play in the resolved trick is C2 alone, plus a small term in the trick's
    points.  Identical leaves score identically, as with the real head."""
    backend = "numpy"
    max_batch = 128

    def score(self, leaves, seat):
        out = []
        for leaf in leaves:
            trick = leaf.last_trick
            mine = next(p.cards for p in trick.plays if p.seat == SEAT)
            out.append((1.0 if sorted(mine) == FORCED else 0.0) + 0.001 * trick.points)
        return np.asarray(out, dtype=np.float64)


def throw_first_scores(rnd, seat, actions, worlds):
    """A stub policy: the production throw first, the other C2 throw second, then
    the enumeration order (so the forced single, if admitted, comes later)."""
    prefs = np.array([-float(i) for i in range(len(actions))])
    for i, action in enumerate(actions):
        if sorted(action) == sorted(THROW):
            prefs[i] = 100.0
        elif sorted(action) == sorted(OTHER_C2_THROW):
            prefs[i] = 99.0
    return np.tile(prefs, (len(worlds), 1))


def served(evaluator=None, worlds=16, **rules):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=worlds, candidates=8,
                               cap=4000, batch_size=128, **rules)
    bot = pv.PVSearchBot(predict, evaluator=evaluator or LeafEvaluator(), version=2,
                         config=config, checkpoint="/dev/null", seed=17)
    return bot


def harness(evaluator=None, worlds=16, **rules):
    rules.pop("refusal_constraints", None)    # a served-wrapper rule (`ai.refusal`)
    return PolicyValueBot(predict, evaluator=evaluator or LeafEvaluator(), worlds=worlds,
                          candidates=8, cap=4000, seed=17, **rules)


def decide(bot, rnd, seat=SEAT, scores=throw_first_scores):
    if scores is not None:
        bot.scores = scores
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    return played, bot.last_decision_record


# ------------------------------------------------------- the fixture is the production position

def test_fixture_is_the_production_position():
    rnd = oxps()
    hand = rnd.hands[SEAT]
    assert rnd.trump_suit == "D" and rnd.banker == SEAT
    assert all(hand.count(c) >= THROW.count(c) for c in THROW)
    # the real deal refuses the throw and forces C2, as production logged
    assert forced_lead(rnd, SEAT, THROW) == FORCED
    assert forced_lead(rnd, SEAT, OTHER_C2_THROW) == FORCED


# ------------------------------------------------------- (a) the production decision

@pytest.mark.parametrize("build", [served, harness], ids=["served", "harness"])
def test_production_throw_is_swapped_to_its_forced_card(build):
    rnd = oxps()
    off_played, off = decide(build(**RELEASE38_RULES), rnd)
    on_played, on = decide(build(doomed_throw_swap=True, **RELEASE38_RULES), rnd)
    # the search selects the throw (the alias tie resolved by admission order) ...
    admitted = [list(a) for a in on["admitted"]] if "admitted" in on else None
    assert sorted(off_played) == sorted(THROW)
    # ... and, with the rule on, the forced card is played instead
    assert on_played == FORCED
    # nothing the search computed moved: ballot, means, selection
    for key in ("admitted_indices", "value_means", "selected_index"):
        assert on[key] == off[key]
    if admitted is not None:
        sel = on["admitted_indices"].index(on["selected_index"])
        assert sorted(admitted[sel]) == sorted(THROW)
        # the throw's mean IS the forced card's: the other C2 throw ties it exactly
        other = next(i for i, a in enumerate(admitted) if sorted(a) == sorted(OTHER_C2_THROW))
        assert on["value_means"][sel] == on["value_means"][other]
        assert on["played"] == FORCED and off["played"] == off_played
    assert on["doomed_throw_swap_applied"] is True
    assert on["doomed_throw_swap_from"] == " ".join(off_played)
    assert on["doomed_throw_swap_to"] == "C2"
    assert on["doomed_throw_swap_worlds"] == on["doomed_throw_swap_refused_worlds"] == 16
    assert on["doomed_throw_swap_forced_variants"] == 1
    assert set(on) - set(off) == RULE_KEYS
    assert all(type(on[k]) in (bool, str, int) for k in RULE_KEYS)    # scalars only


def test_swap_is_deterministic_across_seeds():
    rnd = oxps()
    for seed in (0, 1, 2):
        bot = served(doomed_throw_swap=True, **RELEASE38_RULES)
        bot.sampler.rng.seed(seed)
        played, record = decide(bot, rnd)
        assert played == FORCED and record["doomed_throw_swap_applied"] is True


# ------------------------------------------------------- (b) the engine: same card, no notice

def test_engine_plays_the_same_card_and_only_the_throw_posts_a_notice():
    thrown, swapped = oxps(), oxps()
    thrown.play(SEAT, list(THROW))
    swapped.play(SEAT, list(FORCED))
    assert thrown.trick.plays[-1].cards == swapped.trick.plays[-1].cards == FORCED
    assert sorted(thrown.hands[SEAT]) == sorted(swapped.hands[SEAT])
    assert thrown.notice is not None and thrown.notice["attempted"] == THROW
    assert swapped.notice is None


@pytest.mark.parametrize("observer", [0, 2, 3])
def test_same_committed_play_can_expose_different_cards_to_other_seats(observer):
    """A lower failed-throw count need not mean different committed cards.

    Extend the existing matched-state witness through the real public-memory
    path, without sampling worlds or attributing the screen's strength result.
    """
    thrown, swapped = oxps(), oxps()
    thrown.play(SEAT, list(THROW))
    swapped.play(SEAT, list(FORCED))
    assert thrown.hands == swapped.hands
    assert thrown.trick.plays == swapped.trick.plays
    assert thrown.turn == swapped.turn
    assert thrown.history == swapped.history

    exposed = Memory(thrown, observer, own_kitty=True)
    quiet = Memory(swapped, observer, own_kitty=True)
    assert exposed.known == quiet.known
    failures = RefusalLedger().observe(thrown)
    assert len(failures) == 1
    assert RefusalLedger().observe(swapped) == []
    assert pin_unplayed_attempt(exposed, thrown, failures[0], observer) == 2
    for card in ("D6", "DQ"):
        assert exposed.known[card] == (SEAT, 2)
        assert card not in quiet.known
    # The forced card was played, not information about an unplayed holding.
    assert "C2" not in exposed.known
    assert pin_unplayed_attempt(exposed, thrown, failures[0], observer) == 0


# ------------------------------------------------------- (c) throws that are not doomed everywhere

def standing_world(rnd):
    """A deal in which nobody holds a trump: every trump throw stands."""
    hands = [list(h) for h in rnd.hands]
    plain = [c for c in OXPS_DECK if rnd.ordering.eff_suit(c) != "T"]
    for s in range(4):
        if s != SEAT:
            hands[s] = plain[s * 5:(s + 1) * 5]
    return hands, list(rnd.buried)


class CardCountEvaluator(LeafEvaluator):
    """Prefers the leaf where the root seat put the most cards on the table, so
    a throw that stands outscores everything else in that world."""

    def score(self, leaves, seat):
        return np.asarray([float(len(next(p.cards for p in leaf.last_trick.plays if p.seat == SEAT)))
                           for leaf in leaves], dtype=np.float64)


def pair_only_world(rnd):
    """Opponents hold DK DK and no trump above C2 as a single: the engine forces
    the lowest beatable component, D6 D6, not C2."""
    hands, buried = standing_world(rnd)
    hands[0] = hands[0] + ["DK", "DK"]
    return hands, buried


def sampled_worlds(rnd, n=16):
    return served(**RELEASE38_RULES)._worlds(rnd, SEAT)[0][:n]


def test_world_verdicts_are_what_the_tests_claim():
    rnd = oxps()
    assert forced_lead(rnd, SEAT, THROW, standing_world(rnd)[0]) is None
    assert forced_lead(rnd, SEAT, THROW, pair_only_world(rnd)[0]) == ["D6", "D6"]
    assert all(forced_lead(rnd, SEAT, THROW, h) == FORCED for h, _ in sampled_worlds(rnd))


@pytest.mark.parametrize("case", ["stands-everywhere", "stands-somewhere", "two-forced"])
def test_unit_rule_leaves_a_throw_that_is_not_uniformly_doomed(case):
    rnd = oxps()
    real = sampled_worlds(rnd, 8)
    worlds = {"stands-everywhere": [standing_world(rnd)] * 8,
              "stands-somewhere": real[:4] + [standing_world(rnd)] * 4,
              "two-forced": real[:4] + [pair_only_world(rnd)] * 4}[case]
    bot = served(doomed_throw_swap=True)
    assert bot._swap_doomed_throw(rnd, SEAT, THROW, worlds) == THROW
    record = bot._doomed_throw_record()
    assert record["doomed_throw_swap_applied"] is False
    assert record["doomed_throw_swap_to"] == record["doomed_throw_swap_from"]
    assert record["doomed_throw_swap_refused_worlds"] == {"stands-everywhere": 0,
                                                          "stands-somewhere": 4,
                                                          "two-forced": 8}[case]
    assert record["doomed_throw_swap_forced_variants"] == {"stands-everywhere": 0,
                                                           "stands-somewhere": 1,
                                                           "two-forced": 2}[case]
    # and every world uniformly doomed to one component: swapped
    assert bot._swap_doomed_throw(rnd, SEAT, THROW, real) == FORCED
    assert bot._swap_doomed_throw(rnd, SEAT, THROW, [pair_only_world(rnd)] * 3) == ["D6", "D6"]


@pytest.mark.parametrize("case", ["stands-everywhere", "stands-somewhere"])
def test_decision_with_a_throw_that_stands_somewhere_is_unchanged(case):
    rnd = oxps()
    real = sampled_worlds(rnd, 8)
    worlds = {"stands-everywhere": [standing_world(rnd)] * 8,
              "stands-somewhere": real[:4] + [standing_world(rnd)] * 4}[case]
    out = {}
    for flag in (False, True):
        bot = served(CardCountEvaluator(), worlds=8, doomed_throw_swap=flag, **RELEASE38_RULES)
        bot._worlds = lambda rnd_, seat_, check_budget=None, w=worlds: (list(w), len(w))
        out[flag] = decide(bot, rnd)
    (off_played, off), (on_played, on) = out[False], out[True]
    assert len(off_played) >= 2 and on_played == off_played
    assert on["value_means"] == off["value_means"] and on["selected_index"] == off["selected_index"]
    assert on["doomed_throw_swap_applied"] is False


# ------------------------------------------------------- (d) follows and single leads

def test_follow_and_single_selection_are_untouched():
    rnd = oxps()
    bot = served(doomed_throw_swap=True)
    worlds = sampled_worlds(rnd, 4)
    assert bot._swap_doomed_throw(rnd, SEAT, ["C2"], worlds) == ["C2"]
    assert bot._doomed_throw_record()["doomed_throw_swap_refused_worlds"] == 0
    assert bot._swap_doomed_throw(rnd, SEAT, ["DQ", "DQ"], worlds) == ["DQ", "DQ"]
    follow = follow_position()
    off_played, off = decide(served(worlds=2), follow, follow.turn, scores=None)
    on_played, on = decide(served(worlds=2, doomed_throw_swap=True), follow, follow.turn,
                           scores=None)
    assert on_played == off_played and on["doomed_throw_swap_applied"] is False
    assert on["doomed_throw_swap_refused_worlds"] == 0


# ------------------------------------------------------- (e) off == before

@pytest.mark.parametrize("build", [served, harness], ids=["served", "harness"])
def test_off_is_the_legacy_decision_and_record(build):
    assert module.DOOMED_THROW_DEFAULTS["doomed_throw_swap"] is False
    positions = [(oxps(), SEAT, throw_first_scores), (oxps(), SEAT, None)]
    for rnd in (state(), follow_position()):
        positions.append((rnd, rnd.turn, None))
    for rnd, seat, scores in positions:
        default = build(evaluator=ZeroEvaluator(), worlds=2, **RELEASE38_RULES)
        explicit = build(evaluator=ZeroEvaluator(), worlds=2, doomed_throw_swap=False,
                         **RELEASE38_RULES)
        assert default.doomed_throw_swap is False
        a_played, a = decide(default, rnd, seat, scores)
        b_played, b = decide(explicit, rnd, seat, scores)
        assert a_played == b_played
        if "admitted" in a:
            assert a_played == a["admitted"][a["admitted_indices"].index(a["selected_index"])]
        drop = {"seconds"}
        assert {k: v for k, v in a.items() if k not in drop} == \
            {k: v for k, v in b.items() if k not in drop}
        assert not RULE_KEYS & set(a)


# ------------------------------------------------------- (f) budget

def test_budget_expiry_abandons_the_swap_and_plays_the_selection():
    rnd = oxps()
    bot = served(doomed_throw_swap=True)
    worlds = sampled_worlds(rnd, 16) * 2      # 32 worlds: one strided check inside
    calls = [0]

    def check_budget():
        calls[0] += 1
        raise pv.PVSearchBudgetExceeded("pv-search serving budget expired")
    assert bot._swap_doomed_throw(rnd, SEAT, THROW, worlds, check_budget) == THROW
    record = bot._doomed_throw_record()
    assert calls[0] == 1 and record["doomed_throw_swap_applied"] is False
    assert record["doomed_throw_swap_abandoned"] == "budget"
    # a non-budget error is not swallowed
    with pytest.raises(RuntimeError):
        bot._swap_doomed_throw(rnd, SEAT, THROW, worlds, lambda: (_ for _ in ()).throw(RuntimeError()))


def test_no_extra_value_calls():
    rnd = oxps()
    counts = {}
    for flag in (False, True):
        bot = served(doomed_throw_swap=flag, **RELEASE38_RULES)
        n = [0]
        score = bot.evaluator.score

        def counted(leaves, s, score=score, n=n):
            n[0] += len(leaves)
            return score(leaves, s)
        bot.evaluator.score = counted
        decide(bot, rnd)
        counts[flag] = (n[0], bot.last_decision_record["value_batches"])
    assert counts[False] == counts[True]


# ------------------------------------------------------- (g) name / env / digest

RELEASE38_ENV = {**PRODUCTION_ENV, "SHENGJI_PV_ADMISSION_DIVERSITY": "1",
                 "SHENGJI_PV_REFUSAL_CONSTRAINTS": "1", "SHENGJI_PV_TIEBREAK_POINTS": "1",
                 "SHENGJI_PV_LEAD_ANCHOR": "1"}
RELEASE38_NAME = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-r7092480e-bury-hybrid-5517ddbd7457"


def test_release38_name_unchanged_when_off_and_dts_when_on(production_package):
    assert names(RELEASE38_ENV) == [RELEASE38_NAME]
    assert names({**RELEASE38_ENV, "SHENGJI_PV_DOOMED_THROW_SWAP": "0"}) == [RELEASE38_NAME]
    assert names({**RELEASE38_ENV, "SHENGJI_PV_DOOMED_THROW_SWAP": ""}) == [RELEASE38_NAME]
    on, = names({**RELEASE38_ENV, "SHENGJI_PV_DOOMED_THROW_SWAP": "1"})
    assert on.startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-r") and "-bury-hybrid-" in on
    assert on != RELEASE38_NAME
    every, = names({**RELEASE38_ENV, "SHENGJI_PV_LEAD_TIEBREAK_PRIOR": "1",
                    "SHENGJI_PV_DOOMED_THROW_SWAP": "1"})
    assert every.startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-la-lp-dts-r")
    config = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0)
    assert pv.recipe_digest(config) == "4a09aef5"
    assert "doomed_throw_swap" not in pv.recipe_payload(config)
    swap = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                             doomed_throw_swap=True)
    assert pv.recipe_payload(swap)["doomed_throw_swap"] is True
    assert pv.recipe_digest(swap) != pv.recipe_digest(config)
    assert pv.RULE_FLAGS["DOOMED_THROW_SWAP"] == "doomed_throw_swap"


@pytest.mark.parametrize("bad", ["2", "true", "yes", "on", " 1"])
def test_env_flag_refuses_anything_but_0_or_1(bad):
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, "SHENGJI_PV_DOOMED_THROW_SWAP": bad})
    assert "doomed_throw_swap" not in pv.pv_env_recipe({**PRODUCTION_ENV, "SHENGJI_PV_DOOMED_THROW_SWAP": "0"})
    assert pv.pv_env_recipe({**PRODUCTION_ENV, "SHENGJI_PV_DOOMED_THROW_SWAP": "1"})["doomed_throw_swap"] is True


def test_bad_values_are_refused():
    with pytest.raises(ValueError, match="doomed_throw_swap must be a bool"):
        PolicyValueBot(predict, evaluator=ZeroEvaluator(), doomed_throw_swap=1)
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, doomed_throw_swap="1"))

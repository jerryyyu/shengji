"""The OPTIONAL doomed-throw RE-SELECT of the pv-search bot
(``doomed_throw_reselect``, ``SHENGJI_PV_DOOMED_THROW_RESELECT``): when the
selected lead is a throw the engine refuses in EVERY sampled world with ONE
forced component (the swap's test), neither the throw nor its forced component
is played; the bot's own selection rules re-select over the remaining admitted
candidates.  Exclusive with the swap (``doomed_throw_swap``, release 42).

The production case: room YJQJ round 1 (logs/YJQJ.jsonl, release 42), banker
seat 2, clubs trump, rank 2.  Seat 2 selected ``S4 S4 SJ`` at the lead of trick 6
(refused 64/64, forced ``SJ``), and the swap played ``SJ`` into an outstanding
``SA`` (-20 points); at the lead of trick 13 it selected ``CA CJ CQ`` (forced
``CJ``) and the swap played ``CJ``, lost to a trump 2 (-10 points).

Torch-free and package-free.  The real deal is replayed with the real engine to
each decision, and the decision's TAIL (`_select` then `_swap_doomed_throw`, the
exact served order) is run on the LOGGED admitted ballot, value means and
policy priors, over worlds drawn by the served sampler: the value pass is the
only thing not re-run (it needs the production package).  Witnesses: (a) the
YJQJ decisions: release 42 plays SJ / CJ as logged; the re-select plays a
non-doomed admitted candidate chosen by the selection rules; (b) a full served
decision in the YJQJ position (stub policy and leaf-state value head); (c) off
and on agree on every decision the swap leaves alone, over seeded self-play;
(d) non-doomed throws, follows, the all-excluded guard, the budget; (e)
exclusivity, tree refusal, env / name / digest.
"""
import copy
import hashlib

import numpy as np
import pytest

from shengji.engine.combos import decompose
from shengji.harvest.legal import forced_lead
from shengji.rl.replay_log import rebuild_round
from shengji.train import policy_value_search as module
from shengji.train import pv_search_policy as pv
from shengji.train.policy_value_search import PolicyValueBot, leading
from test_pv_adaptive_worlds import RELEASE42_ENV, RELEASE42_NAME, RELEASE42_RULES
from test_pv_admission_rules import (PRODUCTION_ENV, PRODUCTION_SHA, ZeroEvaluator, names,
                                     predict, production_package)  # noqa: F401
from test_pv_small_joker_lead import (RELEASE38_ENV, RELEASE38_NAME, PointsEvaluator,
                                      _fresh_round)

FLAG = "SHENGJI_PV_DOOMED_THROW_RESELECT"
AW_NAME = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-aw-reba5b0fc-bury-hybrid-0fc096017bf0"
AWL_NAME = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-awl-r7965ea65-bury-hybrid-ed3b15d1e9a0"
RULE_KEYS = {"doomed_throw_reselect_applied", "doomed_throw_reselect_from",
             "doomed_throw_reselect_to", "doomed_throw_reselect_doomed_candidates",
             "doomed_throw_reselect_forced_excluded", "doomed_throw_reselect_fallback_forced"}
SWAP_KEYS = {"doomed_throw_swap_applied", "doomed_throw_swap_from", "doomed_throw_swap_to",
             "doomed_throw_swap_worlds", "doomed_throw_swap_refused_worlds",
             "doomed_throw_swap_forced_variants"}
#: release 42 without its swap: the rules the re-select runs beside
DTR_RULES = {k: v for k, v in RELEASE42_RULES.items() if k != "doomed_throw_swap"}

# Room YJQJ round 1: the deal, the declaration, the bury and the plays through
# seat 2's lead of trick 13 (no failed throw among them).  No player names.
YJQJ_DECK = (
    "C10 C4 DQ LJ S6 D2 C2 DJ D9 HA S9 S6 H9 SQ CK S10 C3 CA C9 C7 D7 HQ S5 HJ S10 C5 S2 "
    "LJ H4 HK SA H8 H10 CJ BJ D5 SK CK D4 D8 C7 C8 HJ D5 H7 HK CQ S8 H10 C8 H6 HQ DJ S3 D3 "
    "D7 CQ S5 H2 D4 H4 SA S8 H5 D9 D3 DA H9 H6 H8 DA SK D10 C9 C5 BJ SQ C10 CJ S9 S3 SJ D2 "
    "H2 DK S2 S7 S7 D6 C4 C2 D10 H3 DQ DK D6 HA C6 C3 H3 H5 S4 H7 D8 CA SJ C6 S4"
).split()
YJQJ_SETUP = [
    {"e": "round_start", "trump_rank": "2", "banker": None, "deck": YJQJ_DECK},
    {"e": "declare", "seat": 2, "cards": ["C2"]},
    {"e": "declare", "seat": 2, "cards": ["C2", "C2"]},
    {"e": "trump", "suit": "C", "rank": "2", "banker": 2},
    {"e": "bury", "seat": 2, "cards": ["D3", "D4", "H6", "H7", "S7", "D8", "S8", "S9"]},
]
YJQJ_PLAYS = [
    (2, "DA DA DK"), (3, "D4 D5 D5"), (0, "D9 D9 D10"), (1, "D3 DQ S3"),
    (2, "SA"), (3, "S9"), (0, "S10"), (1, "SJ"),
    (2, "HJ"), (3, "HQ"), (0, "HA"), (1, "H8"),
    (0, "H10 H10"), (1, "HK HK"), (2, "DQ H5"), (3, "H5 HJ"),
    (1, "HA"), (2, "C5"), (3, "H8"), (0, "H3"),
    (2, "SJ"), (3, "S10"), (0, "SK"), (1, "SA"),           # trick 6: the swap's SJ
    (1, "C8 C8"), (2, "C2 C2"), (3, "LJ LJ"), (0, "C3 C7"),
    (3, "BJ"), (0, "CQ"), (1, "C10"), (2, "C6"),
    (3, "D10"), (0, "DK"), (1, "CK"), (2, "H2"),
    (2, "D2"), (3, "C7"), (0, "C10"), (1, "C9"),
    (2, "S4 S4"), (3, "S7 S8"), (0, "S3 S6"), (1, "S5 SQ"),
    (2, "BJ S2"), (3, "H2 H9"), (0, "H6 H7"), (1, "C6 CJ"),
    (2, "CJ"),                                             # trick 13: the swap's CJ
]
SEAT = 2
#: the logged decisions: play index, the logged play, admitted ballot, value
#: means and policy priors (the decision record), the selected throw's position
DECISIONS = {
    "SJ": dict(
        plays=20, played=["SJ"], selected=1, throw=["S4", "S4", "SJ"],
        admitted=[["S4", "S4"], ["S4", "S4", "SJ"], ["S4"], ["CA"], ["CA", "CJ"], ["CJ"],
                  ["CA", "CJ", "D2"], ["SJ"]],
        means=[-0.3667891807595821, -0.3301816985442509, -0.48287461379829716,
               -0.3543194585979947, -0.3802761540691634, -0.3802761540691634,
               -0.3802761540691634, -0.3301816985442509],
        priors=[0.5774466885426258, 0.3218966928053158, 0.2887233442713129,
                0.12509598993623963, 0.01778062831005878, -0.10731536162618083,
                -0.1729399615382063, -0.25554999573731]),
    "CJ": dict(
        plays=48, played=["CJ"], selected=4, throw=["CA", "CJ", "CQ"],
        admitted=[["S5"], ["CQ"], ["CA"], ["CA", "CQ"], ["CA", "CJ", "CQ"], ["C3", "CJ"],
                  ["C3", "C9", "CQ"], ["C3", "CA", "CJ", "CQ"]],
        means=[-0.5002896442927878, -0.5002775590114655, -0.5002582920198121,
               -0.5002775590114655, -0.5002011508487991, -0.5005205190766728,
               -0.5005205190766728, -0.5005205190766728],
        priors=[-0.05777457895904303, -0.24051633300380598, -0.29673711464165003,
                -0.537253447645456, -0.9799849930963348, -0.9863475086234647,
                -1.3961586755905997, -1.5236009562689203]),
}


def yjqj(plays):
    rnd = rebuild_round(YJQJ_SETUP)
    for seat, cards in YJQJ_PLAYS[:plays]:
        rnd.play(seat, cards.split())
    assert leading(rnd) and rnd.turn == SEAT
    return rnd


def served(evaluator=None, worlds=64, seed=17, **rules):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=worlds, candidates=8,
                               cap=4000, batch_size=128, **rules)
    return pv.PVSearchBot(predict, evaluator=evaluator or ZeroEvaluator(), version=2,
                          config=config, checkpoint="/dev/null", seed=seed)


def tail(bot, rnd, d, worlds, check_budget=None, admitted=None, means=None, priors=None):
    """The served decision's tail on a logged ballot: `_select`, then
    `_swap_doomed_throw` (`PVSearchBot._search`'s order)."""
    admitted = d["admitted"] if admitted is None else admitted
    means = np.asarray(d["means"] if means is None else means, dtype=np.float64)
    priors = d["priors"] if priors is None else priors
    winner = bot._select(rnd, SEAT, admitted, means, worlds=worlds,
                         check_budget=check_budget, priors=priors)
    played = bot._swap_doomed_throw(rnd, SEAT, admitted[winner], worlds, check_budget)
    return winner, played


def draw(rnd, seed, n=64):
    bot = served(**DTR_RULES)
    bot.sampler.rng.seed(seed)
    return bot._worlds(copy.deepcopy(rnd), SEAT)[0][:n]


# ------------------------------------------------------- the fixture is the production position

@pytest.mark.parametrize("key", sorted(DECISIONS))
def test_fixture_is_the_production_position(key):
    d = DECISIONS[key]
    rnd = yjqj(d["plays"])
    assert rnd.trump_suit == "C" and rnd.banker == SEAT and len(rnd.history) == d["plays"] // 4
    hand = rnd.hands[SEAT]
    for action in d["admitted"]:
        assert all(hand.count(c) >= action.count(c) for c in action)
    # the real deal refuses the selected throw and forces the logged card
    assert forced_lead(rnd, SEAT, d["throw"]) == d["played"]
    assert d["admitted"][d["selected"]] == d["throw"]
    # the logged play at this decision is the forced card
    assert YJQJ_PLAYS[d["plays"]] == (SEAT, " ".join(d["played"]))


# ------------------------------------------------------- (a) the YJQJ decisions

@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
@pytest.mark.parametrize("key", sorted(DECISIONS))
def test_yjqj_release42_plays_the_forced_card_and_reselect_does_not(key, seed):
    d = DECISIONS[key]
    rnd = yjqj(d["plays"])
    worlds = draw(rnd, seed)
    # release 42: the selection is the throw and the swap plays its forced card
    r42 = served(**RELEASE42_RULES)
    winner, played = tail(r42, rnd, d, worlds)
    assert winner == d["selected"] and played == d["played"]
    assert r42._doomed_throw_record()["doomed_throw_swap_applied"] is True
    # the re-select: neither the throw nor its forced card
    bot = served(doomed_throw_reselect=True, **DTR_RULES)
    winner, played = tail(bot, rnd, d, worlds)
    record = bot._doomed_throw_record()
    assert set(record) == RULE_KEYS
    assert played == d["admitted"][winner]      # selected_index describes the play
    assert played != d["played"] and winner != d["selected"]
    assert bot._doomed_component(rnd, SEAT, played, worlds) is None
    assert record["doomed_throw_reselect_applied"] is True
    assert record["doomed_throw_reselect_from"] == " ".join(d["throw"])
    assert record["doomed_throw_reselect_to"] == " ".join(played)
    assert record["doomed_throw_reselect_doomed_candidates"] == 1
    assert record["doomed_throw_reselect_fallback_forced"] is False
    # the selection rules chose it: their own run with the excluded means masked
    masked = np.asarray(d["means"], dtype=np.float64)
    excluded = [i for i, a in enumerate(d["admitted"])
                if sorted(a) in (sorted(d["throw"]), sorted(d["played"]))]
    masked[excluded] = -np.inf
    ref = served(**DTR_RULES)
    assert ref._select(rnd, SEAT, d["admitted"], masked, worlds=worlds,
                       priors=d["priors"]) == winner
    assert bot._tiebreak == ref._tiebreak     # the records describe the final run
    if key == "SJ":
        # the admitted SJ single is the throw's alias (equal means) and is excluded
        assert record["doomed_throw_reselect_forced_excluded"] == 1
        assert played in (["CA"], ["S4", "S4"])
    else:
        assert record["doomed_throw_reselect_forced_excluded"] == 0
        assert played == ["CA"]


def test_yjqj_alias_would_win_without_the_forced_exclusion():
    """Why the forced component is excluded too: the throw's leaf IS that card
    played, so their means tie exactly and masking only the throw re-selects it."""
    d = DECISIONS["SJ"]
    assert d["means"][1] == d["means"][7] and d["admitted"][7] == d["played"]
    masked = np.asarray(d["means"], dtype=np.float64)
    masked[1] = -np.inf
    rnd = yjqj(d["plays"])
    assert served(**DTR_RULES)._select(rnd, SEAT, d["admitted"], masked,
                                       worlds=draw(rnd, 0), priors=d["priors"]) == 7


def test_yjqj_census_of_what_reselect_plays():
    out = {}
    for key, d in sorted(DECISIONS.items()):
        rnd = yjqj(d["plays"])
        for seed in range(5):
            bot = served(doomed_throw_reselect=True, **DTR_RULES)
            out.setdefault(key, []).append(" ".join(tail(bot, rnd, d, draw(rnd, seed))[1]))
    print(f"\nYJQJ re-select (5 world seeds): {out}")
    assert set(out["CJ"]) == {"CA"} and "SJ" not in out["SJ"]


# ------------------------------------------------------- (b) a full served decision

class LoggedLeafEvaluator:
    """The value head's YJQJ means as a function of the leaf STATE: the root
    seat's committed cards in the resolved trick (a refused throw's leaf is its
    forced card, so the throw and the card score the same, as in production;
    a forced card that was not admitted takes its throw's logged mean)."""
    backend = "numpy"
    max_batch = 128

    def __init__(self, d, rnd):
        self.table = {tuple(sorted(a)): m for a, m in zip(d["admitted"], d["means"])}
        for a, m in zip(d["admitted"], d["means"]):
            forced = forced_lead(rnd, SEAT, a)
            if forced is not None:
                self.table.setdefault(tuple(sorted(forced)), m)

    def score(self, leaves, seat):
        return np.asarray([self.table.get(tuple(sorted(next(p.cards for p in leaf.last_trick.plays
                                                             if p.seat == SEAT))), -1.0)
                           for leaf in leaves], dtype=np.float64)


def logged_first_scores(d):
    order = {tuple(sorted(a)): 1000.0 - i for i, a in enumerate(d["admitted"])}

    def scores(rnd, seat, actions, worlds):
        prefs = np.array([order.get(tuple(sorted(a)), -float(i)) for i, a in enumerate(actions)])
        return np.tile(prefs, (len(worlds), 1))
    return scores


@pytest.mark.parametrize("key", sorted(DECISIONS))
def test_full_served_decision_in_the_yjqj_position(key):
    d = DECISIONS[key]
    rnd = yjqj(d["plays"])
    out = {}
    for flags in (dict(doomed_throw_swap=True), dict(doomed_throw_reselect=True)):
        bot = served(LoggedLeafEvaluator(d, rnd), worlds=32, **DTR_RULES, **flags)
        bot.scores = logged_first_scores(d)
        played = bot.decide_play(copy.deepcopy(rnd), SEAT)
        out[next(iter(flags))] = (played, bot.last_decision_record)
    (swap_played, swap), (dtr_played, dtr) = out["doomed_throw_swap"], out["doomed_throw_reselect"]
    # release 42 selects the throw and plays its forced card
    assert swap["doomed_throw_swap_applied"] is True and swap_played == d["played"]
    # the re-select plays its selection, which is neither
    sel = dtr["admitted_indices"].index(dtr["selected_index"])
    assert dtr_played == dtr["played"] == dtr["admitted"][sel]
    assert sorted(dtr_played) not in (sorted(d["played"]), sorted(d["throw"]))
    assert dtr["doomed_throw_reselect_applied"] is True
    assert dtr["doomed_throw_reselect_from"] == swap["doomed_throw_swap_from"]
    # nothing the search computed moved, and no swap key leaks
    assert dtr["admitted_indices"] == swap["admitted_indices"]
    assert dtr["value_means"] == swap["value_means"]
    assert not SWAP_KEYS & set(dtr) and not RULE_KEYS & set(swap)


# ------------------------------------------------------- (c) parity over seeded self-play

class HashNoiseEvaluator(PointsEvaluator):
    """`PointsEvaluator` plus deterministic world-dependent noise (stateless)."""

    def score(self, leaves, seat):
        base = super().score(leaves, seat)
        noise = [int(hashlib.sha256(repr([sorted(h) for h in leaf.hands]).encode())
                     .hexdigest()[:8], 16) / 2 ** 32 - 0.5 for leaf in leaves]
        return base + 0.2 * np.asarray(noise)


def throw_loving_scores(rnd, seat, actions, worlds):
    """A stub policy that ranks multi-component leads first (so throws, doomed
    ones included, reach the ballot and the selection)."""
    prefs = []
    for i, a in enumerate(actions):
        comps = len(decompose(list(a), rnd.ordering).components) if len(a) > 1 else 1
        prefs.append(10.0 * comps + len(a) - 1e-3 * i)
    return np.tile(np.asarray(prefs), (len(worlds), 1))


SELF_PLAY_SEEDS = tuple(range(707001, 707007))


def _comparable(record):
    return {k: v for k, v in record.items()
            if k != "seconds" and not k.startswith("doomed_throw_")}


@pytest.mark.parametrize("policy", ["stub", "throw-loving"])
def test_reselect_is_release42_wherever_the_swap_does_not_apply(policy):
    evaluator = HashNoiseEvaluator()
    decisions = applied = fallbacks = 0
    for seed in SELF_PLAY_SEEDS:
        rnd = _fresh_round(seed)
        swap = [served(evaluator, worlds=8, seed=100 + s, **RELEASE42_RULES) for s in range(4)]
        dtr = [served(evaluator, worlds=8, seed=100 + s, doomed_throw_reselect=True, **DTR_RULES)
               for s in range(4)]
        if policy == "throw-loving":
            for bot in swap + dtr:
                bot.scores = throw_loving_scores
        while rnd.phase == "play":
            seat = rnd.turn
            dtr[seat].sampler.rng.setstate(swap[seat].sampler.rng.getstate())
            a = swap[seat].decide_play(copy.deepcopy(rnd), seat)
            b = dtr[seat].decide_play(copy.deepcopy(rnd), seat)
            ra, rb = swap[seat].last_decision_record, dtr[seat].last_decision_record
            assert set(rb) & SWAP_KEYS == set() and RULE_KEYS <= set(rb)
            sel = rb["admitted_indices"].index(rb["selected_index"])
            decisions += 1
            if rb["doomed_throw_reselect_fallback_forced"]:
                # every admitted candidate excluded: the swap's play, the same record
                fallbacks += 1
                assert ra["doomed_throw_swap_applied"] is True and a == b == rb["played"]
                assert rb["admitted"][sel] == rb["doomed_throw_reselect_from"].split()
                assert _comparable(ra) == _comparable(rb)
                rnd.play(seat, a)
                continue
            assert b == rb["played"] == rb["admitted"][sel]
            if not ra["doomed_throw_swap_applied"]:
                # the swap left it alone: the same decision, record and stream
                assert a == b and _comparable(ra) == _comparable(rb)
                assert rb["doomed_throw_reselect_applied"] is False
                assert rb["doomed_throw_reselect_to"] == rb["doomed_throw_reselect_from"]
                assert dtr[seat].sampler.rng.getstate() == swap[seat].sampler.rng.getstate()
            else:
                applied += 1
                assert rb["doomed_throw_reselect_applied"] is True
                assert rb["doomed_throw_reselect_from"] == ra["doomed_throw_swap_from"]
                assert b != a and sorted(b) != sorted(ra["doomed_throw_swap_from"].split())
                assert ra["value_means"] == rb["value_means"]
            rnd.play(seat, a)      # one trajectory: release 42's
    print(f"\ndoomed_throw_reselect parity [{policy}]: decisions={decisions} "
          f"reselected={applied} all_excluded_fallbacks={fallbacks}")
    assert decisions >= 150
    if policy == "throw-loving":
        assert applied > 0


# ------------------------------------------------------- (d) units

def test_one_component_leads_are_never_doomed_and_cost_nothing(monkeypatch):
    d = DECISIONS["SJ"]
    rnd = yjqj(d["plays"])
    worlds = draw(rnd, 0, 8)
    bot = served(doomed_throw_reselect=True)
    calls = []
    monkeypatch.setattr(module, "forced_lead", lambda *a, **k: calls.append(a) or ["X"])
    for action in (["SJ"], ["S4", "S4"]):
        assert bot._doomed_component(rnd, SEAT, action, worlds) is None
    assert calls == []
    monkeypatch.undo()
    # and the shortcut agrees with the engine: a one-component lead stands
    for action in (["SJ"], ["S4", "S4"], ["C2", "C2"]):
        assert all(forced_lead(rnd, SEAT, action, h) is None for h, _ in worlds)


def test_a_throw_that_stands_somewhere_is_played_as_selected():
    d = DECISIONS["SJ"]
    rnd = yjqj(d["plays"])
    worlds = draw(rnd, 0, 8)
    standing = [list(h) for h in worlds[0][0]]
    for s in range(4):        # no other hand holds a spade: the throw stands
        if s != SEAT:
            standing[s] = [c for c in standing[s] if rnd.ordering.eff_suit(c) != "S"]
    mixed = worlds[:4] + [(standing, worlds[0][1])] * 4
    assert forced_lead(rnd, SEAT, d["throw"], standing) is None
    for w in (mixed, [(standing, worlds[0][1])] * 4):
        bot = served(doomed_throw_reselect=True)
        winner, played = tail(bot, rnd, d, w, admitted=d["admitted"], means=d["means"])
        assert winner == 1 and played == d["throw"]
        assert bot._doomed_throw_record()["doomed_throw_reselect_applied"] is False
        assert bot._doomed_throw_record()["doomed_throw_reselect_doomed_candidates"] == 0


def test_follow_is_untouched():
    rnd = yjqj(DECISIONS["SJ"]["plays"])
    rnd.play(SEAT, ["SJ"])
    assert not leading(rnd)
    bot = served(doomed_throw_reselect=True)
    winner = bot._select(rnd, rnd.turn, [["S10"], ["S10", "S10"]], np.array([0.0, 1.0]),
                         worlds=draw(rnd, 0, 4))
    assert winner == 1
    assert bot._doomed_throw_record()["doomed_throw_reselect_applied"] is False


def test_next_choice_is_tested_in_turn():
    """Two doomed throws ranked first: both are excluded in selection order and
    the next non-doomed candidate is played."""
    d = DECISIONS["CJ"]
    rnd = yjqj(d["plays"])
    worlds = draw(rnd, 0)
    means = [0.0, 0.0, 0.0, 0.0, 0.9, 0.8, 0.0, 0.7]     # CA CJ CQ, C3 CJ, C3 CA CJ CQ
    means[1] = 0.5                                        # then CQ
    bot = served(doomed_throw_reselect=True)
    winner, played = tail(bot, rnd, d, worlds, means=means)
    record = bot._doomed_throw_record()
    assert played == ["CQ"] and winner == 1
    assert record["doomed_throw_reselect_doomed_candidates"] == 3
    assert record["doomed_throw_reselect_from"] == "CA CJ CQ"


@pytest.mark.parametrize("case", ["alias", "two-throws"])
def test_all_excluded_falls_back_to_the_forced_component(case):
    key = {"alias": "SJ", "two-throws": "CJ"}[case]
    d = DECISIONS[key]
    rnd = yjqj(d["plays"])
    worlds = draw(rnd, 0)
    admitted = {"alias": [["S4", "S4", "SJ"], ["SJ"]],
                "two-throws": [["CA", "CJ", "CQ"], ["C3", "CJ"]]}[case]
    bot = served(doomed_throw_reselect=True, **DTR_RULES)
    winner, played = tail(bot, rnd, d, worlds, admitted=admitted, means=[0.5, 0.4],
                          priors=[0.0, 0.0])
    record = bot._doomed_throw_record()
    assert winner == 0 and played == d["played"]           # the swap's forced card
    assert record["doomed_throw_reselect_fallback_forced"] is True
    assert record["doomed_throw_reselect_applied"] is False
    assert record["doomed_throw_reselect_to"] == " ".join(d["played"])


class Expire:
    """A serving deadline that expires at its ``at``-th check."""

    def __init__(self, at):
        self.at, self.calls = at, 0

    def __call__(self):
        self.calls += 1
        if self.calls >= self.at:
            raise pv.PVSearchBudgetExceeded("pv-search serving budget expired")


@pytest.mark.parametrize("at", [1, 4, 5, 8])
def test_budget_expiry_abandons_and_plays_the_first_selection(at):
    """64 worlds: each throw's test checks at worlds 16, 32, 48 and once after.
    Expiry inside the first or the second doomed test plays the first selection
    with the selection records restored (the swap's expiry semantics)."""
    d = DECISIONS["CJ"]
    rnd = yjqj(d["plays"])
    worlds = draw(rnd, 0)
    means = [0.0, 0.5, 0.0, 0.0, 0.9, 0.8, 0.0, 0.7]
    bot = served(doomed_throw_reselect=True, lead_tiebreak_prior=True)
    clean = served(lead_tiebreak_prior=True)
    clean._select(rnd, SEAT, d["admitted"], np.asarray(means), worlds=worlds, priors=d["priors"])
    expire = Expire(at)
    winner, played = tail(bot, rnd, d, worlds, check_budget=expire, means=means)
    record = bot._doomed_throw_record()
    assert winner == 4 and played == d["throw"]
    assert record["doomed_throw_reselect_abandoned"] == "budget"
    assert record["doomed_throw_reselect_applied"] is False
    assert bot._lead_tiebreak == clean._lead_tiebreak
    # a non-budget error is not swallowed
    with pytest.raises(RuntimeError):
        tail(bot, rnd, d, worlds, check_budget=lambda: (_ for _ in ()).throw(RuntimeError()),
             means=means)


def _reselect_budget_case(at, **rules):
    """YJQJ SJ position, the throw first, CA then S4 S4; 64 worlds, so the
    throw's doomed test makes checks 1-4 (worlds 16, 32, 48, then once after)."""
    d = DECISIONS["SJ"]
    rnd = yjqj(d["plays"])
    worlds = draw(rnd, 0)
    admitted = [d["throw"], ["CA"], ["S4", "S4"]]
    means, priors = [0.9, 0.5, 0.49], [0.0, 0.0, 0.0]
    clean = served(**rules)
    clean._select(rnd, SEAT, admitted, np.asarray(means), worlds=worlds, priors=priors)
    bot = served(doomed_throw_reselect=True, **rules)
    expire = Expire(at)
    result = tail(bot, rnd, d, worlds, check_budget=expire, admitted=admitted, means=means,
                  priors=priors)
    return result, bot, clean, expire, d


def test_expiry_absorbed_by_the_masked_points_rule_abandons_the_reselect():
    """Codex HOLD on #946: the masked `_select_rules` runs `_select_by_points`,
    which absorbs the expiry and returns its argmax (CA, a single: no further
    doomed check).  The latched deadline still abandons the re-selection."""
    (winner, played), bot, clean, expire, d = _reselect_budget_case(5, tiebreak_points=True)
    record = bot._doomed_throw_record()
    assert (winner, played) == (0, d["throw"])
    assert record["doomed_throw_reselect_abandoned"] == "budget"
    assert record["doomed_throw_reselect_applied"] is False
    assert record["doomed_throw_reselect_to"] == record["doomed_throw_reselect_from"]
    # the first selection's rule records, exactly
    assert bot._tiebreak == clean._tiebreak
    assert "tiebreak_abandoned" not in bot._tiebreak


@pytest.mark.parametrize("rules", [{}, {"lead_tiebreak_prior": True}], ids=["bare", "lp"])
def test_expiry_at_the_final_check_before_publishing_abandons_the_reselect(rules):
    """No rule checks the deadline in the masked selection here (no points
    rule) and CA is a single, so the 5th check is the final one before the
    replacement is published."""
    (winner, played), bot, clean, expire, d = _reselect_budget_case(5, **rules)
    record = bot._doomed_throw_record()
    assert expire.calls == 5
    assert (winner, played) == (0, d["throw"])
    assert record["doomed_throw_reselect_abandoned"] == "budget"
    assert record["doomed_throw_reselect_applied"] is False
    assert bot._lead_tiebreak == clean._lead_tiebreak
    # one check later the replacement is published
    (winner, played), bot, _, expire, _ = _reselect_budget_case(6, **rules)
    assert (winner, played) == (1, ["CA"]) and expire.calls == 5
    assert bot._doomed_throw_record()["doomed_throw_reselect_applied"] is True


def test_the_swap_is_unchanged_by_the_shared_test():
    """`_swap_doomed_throw` now runs `_doomed_verdicts`; its verdicts and record
    are what they were on the YJQJ throws and on one-component leads."""
    for d in DECISIONS.values():
        rnd = yjqj(d["plays"])
        worlds = draw(rnd, 0)
        bot = served(**RELEASE42_RULES)
        assert bot._swap_doomed_throw(rnd, SEAT, d["throw"], worlds) == d["played"]
        assert bot._doomed_throw_record() == {
            "doomed_throw_swap_applied": True, "doomed_throw_swap_from": " ".join(d["throw"]),
            "doomed_throw_swap_to": " ".join(d["played"]), "doomed_throw_swap_worlds": 64,
            "doomed_throw_swap_refused_worlds": 64, "doomed_throw_swap_forced_variants": 1}


# ------------------------------------------------------- (e) exclusivity, tree, name, env

def test_swap_and_reselect_are_exclusive(production_package):
    with pytest.raises(ValueError, match="are exclusive"):
        PolicyValueBot(predict, evaluator=ZeroEvaluator(), doomed_throw_swap=True,
                       doomed_throw_reselect=True)
    with pytest.raises(ValueError, match="are exclusive"):
        served(doomed_throw_swap=True, doomed_throw_reselect=True)
    with pytest.raises(pv.PVSearchPolicyError, match="are exclusive"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, doomed_throw_swap=True,
                                            doomed_throw_reselect=True))
    with pytest.raises(pv.PVSearchPolicyError, match="are exclusive"):
        names({**RELEASE42_ENV, FLAG: "1"})


def test_tree_is_refused():
    from shengji.train.pv_tree_config import PVTreeConfig
    from shengji.train.pv_tree_search import PVTreeSearchBot
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, tree=PVTreeConfig(sims=8),
                               doomed_throw_reselect=True)
    with pytest.raises(pv.PVSearchPolicyError, match="does not combine with the tree"):
        pv.recipe_payload(config)
    with pytest.raises(pv.PVSearchPolicyError, match="does not combine with the tree"):
        PVTreeSearchBot(predict, evaluator=ZeroEvaluator(), version=2, config=config,
                        checkpoint="/dev/null")


def test_release_names_unchanged_when_off(production_package):
    assert names(RELEASE38_ENV) == [RELEASE38_NAME]
    assert names(RELEASE42_ENV) == [RELEASE42_NAME]
    assert names({**RELEASE42_ENV, "SHENGJI_PV_ADAPTIVE_WORLDS": "1"}) == [AW_NAME]
    assert names({**RELEASE42_ENV, "SHENGJI_PV_ADAPTIVE_WORLDS_LEADS": "1"}) == [AWL_NAME]
    for raw in ("0", ""):
        assert names({**RELEASE42_ENV, FLAG: raw}) == [RELEASE42_NAME]
        assert names({**RELEASE38_ENV, FLAG: raw}) == [RELEASE38_NAME]
    config = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0)
    assert pv.recipe_digest(config) == "4a09aef5"
    assert "doomed_throw_reselect" not in pv.recipe_payload(config)
    assert module.DOOMED_THROW_RESELECT_DEFAULTS["doomed_throw_reselect"] is False
    assert PolicyValueBot.doomed_throw_reselect is False      # the class-level off default


def test_dtr_token_last_and_digest_when_on(production_package):
    env = {**RELEASE38_ENV, FLAG: "1"}
    on, = names(env)
    assert on.startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-r") and "-bury-hybrid-" in on
    assert on != RELEASE42_NAME
    every, = names({**env, "SHENGJI_PV_SMALL_JOKER_GUARD": "1",
                    "SHENGJI_PV_ADAPTIVE_WORLDS_LEADS": "1"})
    assert every.startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-la-sjg-awl-dtr-r")
    wide, = names({**env, "SHENGJI_PV_WIDE_LEAD_ADMISSION": "1"})    # #945's width slot
    assert wide.startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-wla-la-dtr-r")
    assert pv.RULE_TOKENS[-2] == ("doomed_throw_reselect", "dtr")   # then vd
    assert pv.RULE_FLAGS["DOOMED_THROW_RESELECT"] == "doomed_throw_reselect"
    base = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0)
    swap = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                             doomed_throw_swap=True)
    dtr = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                            doomed_throw_reselect=True)
    payload = pv.recipe_payload(dtr)
    assert payload["doomed_throw_reselect"] is True and "doomed_throw_swap" not in payload
    assert len({pv.recipe_digest(c) for c in (base, swap, dtr)}) == 3


@pytest.mark.parametrize("bad", ["2", "true", "yes", "on", " 1"])
def test_env_flag_refuses_anything_but_0_or_1(bad):
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: bad})
    assert "doomed_throw_reselect" not in pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "0"})
    assert pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "1"})["doomed_throw_reselect"] is True


def test_bad_values_are_refused():
    with pytest.raises(ValueError, match="doomed_throw_reselect must be a bool"):
        PolicyValueBot(predict, evaluator=ZeroEvaluator(), doomed_throw_reselect=1)
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, doomed_throw_reselect="1"))

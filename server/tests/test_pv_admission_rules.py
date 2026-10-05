"""The two OPTIONAL admission rules of the pv-search bot (#676 A/C, #677
strategy 1): ``admission_diversity`` and ``admit_forced_single``.

Torch-free: a stub predictor (fixed log-odds) and a stub evaluator (zeros) on
the real fixture round, the real legal enumeration and the real engine.

Witnesses: with both rules OFF the admitted indices are exactly the ranked
prefix the pre-rule code produced and the record carries no rule keys; the
production registry name derived from the fly.toml env is unchanged with both
off and distinct with each on; the env recipe refuses anything but 0/1; the
diversity cap admits at most two of seven same-structure variants, back-fills
with the next-best other structures, fills K and records the skipped indices;
the overlap rule skips a one-card variant; the forced component admitted next
to a throw is the one the REAL ``Round.play`` forces on that deal, and the
fraction threshold is honoured.
"""
import copy
from collections import Counter
import random

import numpy as np
import pytest

from shengji.harvest.legal import enumerate_legal, forced_lead, resolve_lead
from shengji.engine.combos import decompose
from shengji.train import policy_value_search as module
from shengji.train import pv_search_policy as pv
from shengji.train.policy_value_search import PolicyValueBot, structure_key
from test_policy_world_search import state


def _pair_preservation_follow():
    """Complete double-deck allocation; seat1 is void in a legal trump lead."""
    from shengji.engine.cards import Ordering, make_deck
    from shengji.engine.round import Round, Trick
    deck = make_deck()
    follower = ['S6', 'S6', 'S8', 'D8', 'C2', 'C4', 'C4']
    for card in follower:
        deck.remove(card)
    ordering = Ordering('H', '7')
    for card in list(deck):
        if len(follower) == 25:
            break
        if ordering.eff_suit(card) != 'T':
            follower.append(card)
            deck.remove(card)
    lead = ['BJ', 'BJ', 'LJ']
    for card in lead:
        deck.remove(card)
    leader = lead + deck[:22]
    deck = deck[22:]
    rnd = Round('7', 0, random.Random(0))
    rnd.hands = [leader, follower, deck[:25], deck[25:50]]
    rnd.buried = deck[50:]
    rnd.phase, rnd.turn, rnd.trump_suit = 'play', 0, 'H'
    rnd.ordering, rnd.trick = ordering, Trick(0)
    assert len(rnd.buried) == 8
    assert Counter(sum(rnd.hands, []) + rnd.buried) == Counter(make_deck())
    rnd.play(0, lead)
    assert Counter(rnd.trick.plays[0].cards) == Counter(lead)
    assert rnd.turn == 1
    return rnd


def test_pair_preserving_legal_follow_can_be_suppressed_by_overlap(monkeypatch):
    """A mechanism witness, not proof of the historical M9 exclusion cause.

    Current diversity uses played structure/overlap, not remaining resources.
    Policy ranks here are constructed; no model or strength claim is made.
    """
    rnd = _pair_preservation_follow()
    bot = harness(admission_diversity=True)
    legal = enumerate_legal(rnd, 1, cap=4000)
    actions = list(legal.actions)
    anchor = ('C2', 'D8', 'S6')
    preserving = ('C2', 'D8', 'S8')
    keys = [tuple(sorted(a)) for a in actions]
    a, b = keys.index(anchor), keys.index(preserving)
    assert structure_key(rnd, actions[a]) == structure_key(rnd, actions[b])
    for index, remaining in [(a, 1), (b, 2)]:
        played = copy.deepcopy(rnd)
        played.play(1, list(actions[index]))
        assert Counter(played.hands[1])['S6'] == remaining
    ranked = [a, b] + [i for i in range(len(actions)) if i not in (a, b)]
    chosen = bot._admit_diverse(rnd, actions, ranked, a, k=8)
    assert len(chosen) == 8 and chosen[0] == a
    assert b not in chosen and b in bot._diversity_skipped
    # Raising the structure cap alone cannot rescue it: overlap is independent.
    bot.max_per_structure = 1000
    assert b not in bot._admit_diverse(rnd, actions, ranked, a, k=8)
    # Isolate the cause, without proposing removal of the overlap protection.
    bot.max_per_structure = 2
    monkeypatch.setattr(module, '_near_duplicate', lambda *args: False)
    assert bot._admit_diverse(rnd, actions, ranked, a, k=8)[:2] == [a, b]

PRODUCTION_NAME = "pv-search-491ee4bf-w64-k8-r4a09aef5-bury-hybrid-355958b4db25"
PRODUCTION_SHA = "491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670"
PRODUCTION_ENV = {   # fly.toml, release 36
    "SHENGJI_PV_CKPT": "/data/models/smv3out-491ee4bf.npz",
    "SHENGJI_PV_SHA256": PRODUCTION_SHA,
    "SHENGJI_PV_WORLDS": "64", "SHENGJI_PV_CANDIDATES": "8", "SHENGJI_PV_CAP": "4000",
    "SHENGJI_PV_BATCH_SIZE": "128", "SHENGJI_PV_SERVING_BUDGET_SECONDS": "3",
    "SHENGJI_PV_BURY_ARM": "hybrid", "SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS": "2",
}


class ZeroEvaluator:
    backend = "numpy"
    max_batch = 128

    def score(self, leaves, seat):
        return np.zeros(len(leaves))


def predict(X):
    return np.tile(np.arange(54, dtype=np.float64), (len(X), 1))


def legacy_admission(preferences, anchor_index, k):
    """A copy of the pre-rule selection (`PolicyValueBot.decide_play` before
    this change): anchor first, then the ranked preferences, K in all."""
    ranked = sorted(range(len(preferences)), key=lambda i: (-preferences[i], i))
    chosen = [anchor_index]
    chosen.extend(i for i in ranked if i != anchor_index)
    return chosen[:k]


def harness(**rules):
    return PolicyValueBot(predict, evaluator=ZeroEvaluator(), worlds=2, candidates=8,
                          cap=4000, seed=17, **rules)


def served(**rules):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=2, candidates=8,
                               cap=4000, batch_size=128, **rules)
    return pv.PVSearchBot(predict, evaluator=ZeroEvaluator(), version=2, config=config,
                          checkpoint="/dev/null", seed=17)


def crafted_preferences(bot, rnd, seat, top):
    """Monkeypatch-free: a ``scores`` that ranks the ``top`` legal indices first
    (in that order), every single last, everything else by enumeration order."""
    legal = enumerate_legal(rnd, seat, cap=bot.cap)

    def scores(rnd_, seat_, actions, worlds):
        assert [list(a) for a in actions[:len(legal.actions)]] == [list(a) for a in legal.actions]
        prefs = np.array([-float(i) for i in range(len(actions))])
        for rank, index in enumerate(top):
            prefs[index] = 1000.0 - rank
        for i, a in enumerate(actions):
            if len(a) == 1 and i not in top:
                prefs[i] = -1e6 - i
        return np.tile(prefs, (len(worlds), 1))
    bot.scores = scores
    return legal


# ------------------------------------------------------- (a) off == before

def test_both_rules_off_admit_exactly_the_legacy_prefix_and_no_rule_keys():
    rnd = state(); seat = rnd.turn
    bot = harness()
    assert bot.admission_diversity is False and bot.admit_forced_single is False
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    # the same preferences, the legacy selection
    legal = enumerate_legal(rnd, seat, cap=bot.cap, must_include=[module.HeuristicBot().decide_play(rnd, seat)])
    worlds, _ = PolicyValueBot(predict, evaluator=ZeroEvaluator(), worlds=2, seed=17)._worlds(rnd, seat)
    preferences = bot.scores(rnd, seat, list(legal.actions), worlds).mean(axis=0)
    anchor = record["admitted_indices"][0]
    assert record["admitted_indices"] == legacy_admission(preferences, anchor, 8)
    assert len(record["admitted_indices"]) == 8
    assert played == list(legal.actions[record["selected_index"]])
    assert not {"diversity_skipped", "forced_single_added", "forced_single_detail"} & set(record)
    # the served wrapper, same seed and package stub: same indices, no rule keys
    bot2 = served()
    assert bot2.decide_play(copy.deepcopy(rnd), seat) == played
    rec2 = bot2.last_decision_record
    assert rec2["admitted_indices"] == record["admitted_indices"]
    assert rec2["schema"] == pv.RECORD_SCHEMA
    assert not {"diversity_skipped", "forced_single_added", "forced_single_detail"} & set(rec2)


# ------------------------------------------------------- (d) registry names

@pytest.fixture
def production_package(monkeypatch):
    """The production package is not on disk here; its on-disk id check is the
    only thing `pv_registry_entries` needs from it."""
    import shengji.ai.cwv_policy as cwv
    monkeypatch.setattr(cwv, "checkpoint_id", lambda path: PRODUCTION_SHA[:8])


def names(env):
    return list(pv.pv_registry_entries(**pv.pv_env_recipe(env)))


def test_production_name_unchanged_with_both_off_and_distinct_with_each_on(production_package):
    assert names(PRODUCTION_ENV) == [PRODUCTION_NAME]
    assert names({**PRODUCTION_ENV, "SHENGJI_PV_ADMISSION_DIVERSITY": "0",
                  "SHENGJI_PV_ADMIT_FORCED_SINGLE": "0"}) == [PRODUCTION_NAME]
    div, = names({**PRODUCTION_ENV, "SHENGJI_PV_ADMISSION_DIVERSITY": "1"})
    fs, = names({**PRODUCTION_ENV, "SHENGJI_PV_ADMIT_FORCED_SINGLE": "1"})
    both, = names({**PRODUCTION_ENV, "SHENGJI_PV_ADMISSION_DIVERSITY": "1",
                   "SHENGJI_PV_ADMIT_FORCED_SINGLE": "1"})
    assert len({PRODUCTION_NAME, div, fs, both}) == 4
    assert div.startswith("pv-search-491ee4bf-w64-k8-div-r") and "-bury-hybrid-" in div
    assert fs.startswith("pv-search-491ee4bf-w64-k8-fs-r")
    assert both.startswith("pv-search-491ee4bf-w64-k8-div-fs-r")
    # the recipe payload with both off is the pre-rule payload: no rule keys at all
    config = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0)
    assert pv.recipe_digest(config) == "4a09aef5"
    assert not {"admission_diversity", "admit_forced_single", "max_per_structure",
                "forced_min_fraction"} & set(pv.recipe_payload(config))
    on = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                           admission_diversity=True)
    assert pv.recipe_payload(on)["admission_diversity"] is True
    assert pv.recipe_payload(on)["max_per_structure"] == 2


@pytest.mark.parametrize("flag", ["SHENGJI_PV_ADMISSION_DIVERSITY", "SHENGJI_PV_ADMIT_FORCED_SINGLE"])
@pytest.mark.parametrize("bad", ["2", "true", "yes", "on", " 1"])
def test_env_recipe_refuses_anything_but_0_or_1(flag, bad):
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, flag: bad})
    assert "admission_diversity" not in pv.pv_env_recipe({**PRODUCTION_ENV, flag: ""})
    assert pv.pv_env_recipe({**PRODUCTION_ENV, flag: "1"})[pv.ADMISSION_RULES[flag[len("SHENGJI_PV_"):]]] is True


def test_non_bool_rule_flags_are_refused_everywhere():
    with pytest.raises(ValueError, match="must be a bool"):
        PolicyValueBot(predict, evaluator=ZeroEvaluator(), admission_diversity=1)
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, admit_forced_single="1"))


# ------------------------------------------------------- (b) diversity

def test_diversity_caps_seven_variants_at_two_backfills_and_fills_k():
    rnd = state(); seat = rnd.turn
    bot = harness(admission_diversity=True)
    legal = enumerate_legal(rnd, seat, cap=bot.cap)
    key = ("C", 3, (("C", 0), ("C", 1)))         # single + pair in clubs: 12 variants
    variants = [i for i, a in enumerate(legal.actions) if structure_key(rnd, a) == key][:7]
    assert len(variants) == 7
    crafted_preferences(bot, rnd, seat, variants)
    bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    chosen = record["admitted_indices"]
    assert len(chosen) == 8 and len(set(chosen)) == 8
    actions = legal.actions
    anchor_key = structure_key(rnd, actions[chosen[0]])
    admitted_keys = Counter(structure_key(rnd, actions[i]) for i in chosen)
    assert admitted_keys[key] <= 2
    assert all(n <= 2 for k, n in admitted_keys.items())
    admitted_variants = [i for i in chosen if i in variants]
    skipped = record["diversity_skipped"]
    assert set(skipped) >= set(variants) - set(admitted_variants)
    assert len(set(variants) - set(admitted_variants)) >= 5
    # the back-fill is the next-best OTHER structures, never a single (ranked last)
    assert all(len(actions[i]) >= 2 for i in chosen[1:])
    # a skipped index is never admitted, and every skipped index outranks the
    # admitted non-variants it made room for
    assert not set(skipped) & set(chosen)
    assert record["value_evaluations"] == 2 * 8


def test_overlap_rule_skips_a_one_card_variant_but_backfills_when_k_is_short():
    rnd = state(); seat = rnd.turn
    bot = harness(admission_diversity=True)
    bot.candidates = 3
    actions = [["C3"], ["C10", "C3"], ["C10", "C5"], ["C3", "C3"], ["D2", "D2"]]
    ranked = [1, 2, 3, 4]
    chosen = bot._admit_diverse(rnd, actions, ranked, 0)
    # [C10,C5] shares one of two cards with the admitted [C10,C3]: skipped;
    # [C3,C3] shares one card with [C10,C3] (a different structure): skipped;
    # [D2,D2] fills the third slot
    assert chosen == [0, 1, 4]
    assert bot._diversity_skipped == [2, 3]
    bot.candidates = 4                     # one slot short: the best skipped backfills
    assert bot._admit_diverse(rnd, actions, ranked, 0) == [0, 1, 4, 2]
    assert bot._diversity_skipped == [3]
    assert module._near_duplicate(Counter(["C3"]), 1, [(1, Counter(["C5"]))]) is False


# ------------------------------------------------------- (c) forced single

def test_forced_component_matches_the_real_engine_and_is_admitted():
    rnd = state(); seat = rnd.turn
    assert not rnd.trick.plays
    actions = enumerate_legal(rnd, seat, cap=4000).actions
    throw = ["C10", "CA"]
    throw_index = actions.index(throw)
    forced = forced_lead(rnd, seat, throw)
    assert forced == ["C10"]
    # the REAL engine's notice on this deal agrees with the helper
    live = copy.deepcopy(rnd)
    live.play(seat, list(throw))
    assert live.notice["kind"] == "failed_throw" and live.notice["forced"] == forced
    assert live.notice["attempted"] == throw and live.trick.plays[0].cards == forced
    assert resolve_lead(rnd, seat, throw)[0] == forced
    # a single component always stands; a deal with no higher club lets the throw stand
    assert forced_lead(rnd, seat, ["C3", "C3"]) is None
    tame = [list(h) if s == seat else ["H3"] * len(h) for s, h in enumerate(rnd.hands)]
    assert forced_lead(rnd, seat, throw, tame) is None
    assert rnd.hands == copy.deepcopy(state()).hands      # pure
    # the bot, in ONE world that is the real deal
    bot = harness(admit_forced_single=True)
    bot._worlds = lambda *a: ([([sorted(h) for h in rnd.hands], sorted(rnd.buried))], 1)
    crafted_preferences(bot, rnd, seat, [throw_index])
    bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    forced_index = actions.index(forced)
    assert record["forced_single_added"] == [forced_index]
    assert record["admitted_indices"][-1] == forced_index
    assert record["admitted_indices"][1] == throw_index
    assert len(record["admitted_indices"]) <= 8 + module.FORCED_EXTRA_SLOTS
    first = record["forced_single_detail"][0]
    assert first["throw_index"] == throw_index and first["forced"] == forced
    assert first["worlds_forced"] == 1 and first["fraction"] == 1.0 and first["admitted"] is True
    assert record["value_evaluations"] == len(record["admitted_indices"])


def test_forced_single_honours_the_world_fraction_and_the_extra_slot_cap():
    rnd = state(); seat = rnd.turn
    actions = enumerate_legal(rnd, seat, cap=4000).actions
    throw = ["C10", "CA"]
    real = [sorted(h) for h in rnd.hands]
    tame = [list(h) if s == seat else ["H3"] * len(h) for s, h in enumerate(real)]
    worlds = [(real, sorted(rnd.buried))] + [(tame, sorted(rnd.buried))] * 3   # forced in 1 of 4
    for fraction, expect in ((0.25, [actions.index(["C10"])]), (0.5, [])):
        bot = harness(admit_forced_single=True, forced_min_fraction=fraction)
        bot._worlds = lambda *a: (worlds, 4)
        crafted_preferences(bot, rnd, seat, [actions.index(throw)])
        bot.decide_play(copy.deepcopy(rnd), seat)
        record = bot.last_decision_record
        assert record["forced_single_added"] == expect
        assert record["forced_single_detail"][0]["fraction"] == 0.25
    # many admitted throws, each forcing a different single: at most two extras
    throws = [i for i, a in enumerate(actions) if len(a) >= 2
              and len(decompose(list(a), rnd.ordering).components) >= 2
              and forced_lead(rnd, seat, a) is not None]
    distinct, seen = [], set()
    for i in throws:
        f = tuple(forced_lead(rnd, seat, actions[i]))
        if f not in seen:
            seen.add(f); distinct.append(i)
        if len(distinct) == 5:
            break
    bot = harness(admit_forced_single=True)
    bot._worlds = lambda *a: ([(real, sorted(rnd.buried))], 1)
    crafted_preferences(bot, rnd, seat, distinct)
    bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    assert len(record["forced_single_added"]) == module.FORCED_EXTRA_SLOTS
    assert len(record["admitted_indices"]) == 8 + module.FORCED_EXTRA_SLOTS
    assert len(set(record["admitted_indices"])) == len(record["admitted_indices"])


def test_forced_single_is_inert_on_a_follow():
    rnd = state()
    rnd.play(rnd.turn, module.HeuristicBot().decide_play(rnd, rnd.turn))
    seat = rnd.turn
    bot = harness(admit_forced_single=True, admission_diversity=True)
    bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    assert record["forced_single_added"] == [] and record["forced_single_detail"] == []
    assert len(record["admitted_indices"]) <= 8


# ------------------------------------------------------- the served wrapper

def test_served_wrapper_carries_the_rules_and_records_them():
    rnd = state(); seat = rnd.turn
    bot = served(admission_diversity=True, admit_forced_single=True)
    assert bot.admission_diversity and bot.admit_forced_single
    bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    assert record["schema"] == pv.RECORD_SCHEMA and record["work_complete"] is True
    assert "diversity_skipped" in record and "forced_single_added" in record
    k = len(record["admitted_indices"])
    assert 8 <= k <= 8 + module.FORCED_EXTRA_SLOTS
    assert len(record["admitted"]) == k == len(record["value_means"]) == len(record["policy_log_odds_admitted"])
    assert record["value_evaluations"] == 2 * k
    assert all(0 <= i < record["actions"] for i in record["admitted_indices"])
    assert len(set(record["admitted_indices"])) == k


# ------------------------------------- the harvest ballot (Codex HOLD on #680, P1 #1)

def _trajectory_bot(explore_rate, explore_k, **rules):
    """A torch-free served bot re-classed onto the PV trajectory mixin exactly as
    `make_trajectory_bot` does it."""
    import random
    from shengji.harvest import trajectory
    bot = served(**rules)
    bot.__class__ = trajectory.pv_trajectory_class(type(bot))
    bot._trajectory_init(random.Random(1))
    bot.EXPLORE_RATE = float(explore_rate)
    bot.EXPLORE_K = int(explore_k)
    bot.LEGAL_CAP = 256
    return bot


@pytest.mark.parametrize("explore", [(0.0, 0), (1.0, 1)])
def test_forced_extras_are_in_the_harvested_production_ballot(explore):
    """The mixin captures the ballot at the admission boundary; the forced extras
    must be inside it, so `pv_fields_from_record` (the harvester's alignment
    guard) accepts the record: the FINAL scored ballot, its production partition
    (anchor, policy picks, forced extras) and its exploration partition (the
    draw) agree with the record.  On d7eef7f6 the extras were appended after the
    capture and this raised TrajectoryError (a 9-action record vs an 8-action
    ballot)."""
    from collections import Counter as _Counter
    from shengji.harvest import trajectory
    from shengji.harvest.common import action_key
    rnd = state(); seat = rnd.turn
    actions = enumerate_legal(rnd, seat, cap=4000).actions
    throw = ["C10", "CA"]
    bot = _trajectory_bot(*explore, admit_forced_single=True)
    bot._worlds = lambda *a, **k: ([([sorted(h) for h in rnd.hands], sorted(rnd.buried))] * 2, 2)
    crafted_preferences(bot, rnd, seat, [actions.index(throw)])
    action = bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    # the REAL harvest path FIRST: on d7eef7f6 this raised TrajectoryError
    # ("admitted a different ballot") from pv_fields_from_record's alignment guard
    stats = _Counter()
    fields = trajectory._play_fields({}, "run", 0, 0, rnd, seat, [], action, bot, 256, stats)
    assert record["forced_single_added"] == [actions.index(["C10"])]
    assert len(record["admitted_indices"]) == 9 + (1 if explore[1] else 0)
    ballot = bot.last_ballot
    assert len(ballot) == len(record["admitted"]) == len(record["value_means"])
    assert [action_key(a) for a in ballot] == [action_key(a) for a in record["admitted"]]
    production = bot.last_production_ballot
    assert action_key(["C10"]) in {action_key(a) for a in production}
    assert production == ballot[:len(production)]
    draw = [a for a in ballot if a not in production]
    if explore[1]:
        assert bot.last_exploration is not None and len(draw) == len(bot.last_exploration["added"]) == 1
    else:
        assert draw == [] and production == ballot
    # the record was accepted and the partitions are stamped
    assert stats["searched"] == 1
    assert fields["ballot"] == ballot and len(fields["action_values"]["means"]) == len(ballot)
    assert fields["allocation"]["played_index"] == record["admitted_indices"].index(record["selected_index"])
    assert action_key(fields["ballot"][fields["allocation"]["played_index"]]) == action_key(action)
    if explore[1]:
        assert fields["production_ballot"] == production and fields["exploration"]["added"] == draw
    else:
        assert fields["production_ballot"] is None and fields["exploration"] is None
    # the harvester's own alignment guard still bites on a misaligned ballot
    with pytest.raises(trajectory.TrajectoryError, match="different ballot"):
        trajectory.pv_fields_from_record(record, ballot[:-1])


def test_capped_missing_exploration_component_is_not_reclassified_as_production(monkeypatch):
    """A forced component absent from the served cap is unavailable to production.

    The exploration mixin may append that card to the scored set.  It then becomes
    eligible for forced-single admission, but that must not rewrite the captured
    production ballot: a no-exploration bot at the *same* cap could not have
    admitted it.  In particular, do not retain `_forced_added` blindly while the
    mixin removes a missing exploration draw from its production partition.
    """
    import random
    from shengji.harvest import trajectory

    rnd = state(); seat = rnd.turn
    throw, forced = ["CA", "CJ"], ["CJ"]
    assert forced_lead(rnd, seat, throw) == forced
    # The cap retains C10; the forced CJ singleton is absent.  The anchor is
    # force-included, making this a real capped served ballot with one throw.
    assert enumerate_legal(rnd, seat, cap=1).actions == [["C10"]]
    world = [([sorted(hand) for hand in rnd.hands], sorted(rnd.buried))]

    def fresh():
        config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=1,
                                   candidates=2, cap=1, batch_size=128,
                                   admit_forced_single=True)
        bot = pv.PVSearchBot(predict, evaluator=ZeroEvaluator(), version=2,
                             config=config, checkpoint="/dev/null", seed=17)
        bot._worlds = lambda *a, **k: (world, 1)

        def scores(rnd_, seat_, actions, worlds_):
            values = np.array([1000.0 if action == throw else -float(i)
                               for i, action in enumerate(actions)])
            return np.tile(values, (len(worlds_), 1))
        bot.scores = scores
        return bot

    served_bot, harvest_bot = fresh(), fresh()
    original = module.HeuristicBot.decide_play
    monkeypatch.setattr(
        module.HeuristicBot, "decide_play",
        lambda self, rnd_, seat_: list(throw) if self in (served_bot, harvest_bot)
        else original(self, rnd_, seat_))

    # The actual served policy cannot price CJ: it is absent from cap=1 plus
    # the force-included anchor.  Its detail witnesses the unavailable index.
    assert served_bot.decide_play(copy.deepcopy(rnd), seat) == throw
    served_record = served_bot.last_decision_record
    assert served_record["admitted"] == [throw, ["C10"]]
    assert served_record["forced_single_added"] == []
    assert served_record["forced_single_detail"] == [{
        "throw_index": 1, "forced": forced, "index": None,
        "worlds_forced": 1, "fraction": 1.0, "admitted": False,
    }]

    # A missing exploration draw makes CJ available only to the harvesting bot.
    # Resolution still runs over the served set, so CJ is an exploration action,
    # not a forced extra; it must stay outside the production partition.
    harvest_bot.__class__ = trajectory.pv_trajectory_class(type(harvest_bot))
    harvest_bot._trajectory_init(random.Random(1))
    harvest_bot.EXPLORE_RATE, harvest_bot.EXPLORE_K, harvest_bot.LEGAL_CAP = 1.0, 1, 256
    monkeypatch.setattr(trajectory, "sample_off_ballot", lambda *a, **k: ([forced], 1))
    assert harvest_bot.decide_play(copy.deepcopy(rnd), seat) == throw
    record = harvest_bot.last_decision_record
    assert record["admitted"] == [throw, ["C10"], forced]
    assert record["forced_single_added"] == []
    assert record["forced_single_detail"] == [{
        "throw_index": 1, "forced": forced, "index": None,
        "worlds_forced": 1, "fraction": 1.0, "admitted": False,
    }]
    assert len(record["admitted_indices"]) == 3 <= harvest_bot.candidates + module.FORCED_EXTRA_SLOTS
    assert len(set(record["admitted_indices"])) == 3
    assert harvest_bot.last_production_ballot == served_record["admitted"]
    assert harvest_bot.last_ballot == record["admitted"]
    assert harvest_bot.last_exploration["added"] == [forced]


def test_missing_draw_cannot_consume_forced_extra_quota():
    """The production partition equals admission over the served scored set.

    This is a targeted admission witness: three real engine-refused club throws
    have three distinct forced components.  C10 is a missing exploration draw;
    C3 and C5 are in the served scored set.  The missing draw must not take one
    of the two forced-extra slots and thereby suppress C5 from production.
    """
    import random
    from shengji.harvest import trajectory
    from shengji.harvest.common import action_key

    rnd = state(); seat = rnd.turn
    throws = [["C10", "CA"], ["C3", "CA"], ["C5", "CJ"]]
    missing, present = ["C10"], [["C3"], ["C5"]]
    assert [forced_lead(rnd, seat, action) for action in throws] == [missing, *present]
    actions = [*throws, missing, *present]
    preferences = np.array([0.0, 30.0, 20.0, -999.0, 0.0, 0.0])
    world = [([sorted(hand) for hand in rnd.hands], sorted(rnd.buried))]

    # The no-exploration control has exactly the served scored set: missing C10
    # cannot be priced, while C3 and C5 consume the two genuine forced slots.
    control = served(admit_forced_single=True)
    control.candidates = 3
    served_indices = [0, 1, 2, 4, 5]
    served_actions = [actions[i] for i in served_indices]
    served_preferences = preferences[served_indices]
    expected = control._admission(rnd, seat, served_actions, served_preferences, 0, world)
    expected_ballot = [served_actions[i] for i in expected]
    assert expected_ballot == [*throws, *present]
    assert control._forced_added == [3, 4]

    # The harvesting action list contains C10 only because exploration appended
    # it.  Its production partition must still equal the same-cap control, with
    # all diagnostics remapped to the widened action indices.
    bot = served(admit_forced_single=True)
    bot.candidates = 3
    bot.__class__ = trajectory.pv_trajectory_class(type(bot))
    bot._trajectory_init(random.Random(1))
    bot._draw_keys = {action_key(missing)}
    bot._forced_draw_keys = {action_key(missing)}
    bot.LEGAL_CAP = 256
    chosen = bot._admission(rnd, seat, actions, preferences, 0, world)
    assert chosen == [0, 1, 2, 4, 5, 3]
    assert bot.last_production_ballot == expected_ballot
    assert bot.last_ballot == [*expected_ballot, missing]
    assert bot._forced_added == [4, 5]
    assert bot._forced_detail == [
        {"throw_index": 0, "forced": missing, "index": None,
         "worlds_forced": 1, "fraction": 1.0, "admitted": False},
        {"throw_index": 1, "forced": ["C3"], "index": 4,
         "worlds_forced": 1, "fraction": 1.0, "admitted": True},
        {"throw_index": 2, "forced": ["C5"], "index": 5,
         "worlds_forced": 1, "fraction": 1.0, "admitted": True},
    ]
    assert len(bot._forced_added) == module.FORCED_EXTRA_SLOTS


def test_missing_draw_cannot_backfill_a_diverse_production_ballot():
    """A masked missing draw must not fill the diversity quota by back-fill."""
    import random
    from shengji.harvest import trajectory
    from shengji.harvest.common import action_key

    rnd = state(); seat = rnd.turn
    actions = [["C10", "C10", "C3"], ["C3", "C3", "C5"],
               ["C10", "C10", "C5"]]
    missing = actions[2]
    assert len({structure_key(rnd, action) for action in actions}) == 1
    preferences = np.array([0.0, 10.0, -999.0])

    control = served(admission_diversity=True)
    control.candidates = 3
    expected = control._admission(rnd, seat, actions[:2], preferences[:2], 0, [])
    expected_ballot = [actions[:2][i] for i in expected]
    assert expected_ballot == actions[:2]

    bot = served(admission_diversity=True)
    bot.candidates = 3
    bot.__class__ = trajectory.pv_trajectory_class(type(bot))
    bot._trajectory_init(random.Random(1))
    bot._draw_keys = {action_key(missing)}
    bot._forced_draw_keys = {action_key(missing)}
    bot.LEGAL_CAP = 256
    assert bot._admission(rnd, seat, actions, preferences, 0, []) == [0, 1, 2]
    assert bot.last_production_ballot == expected_ballot
    assert bot.last_ballot == actions
    assert bot._diversity_skipped == []


# ------------------------------- the serving deadline (Codex HOLD on #680, P1 #2)

def test_deadline_firing_inside_the_forced_extras_loop_is_a_clean_fallback(monkeypatch):
    """Mocked clock: every engine validation inside the throw-resolution loop
    advances it, so the deadline fires INSIDE `_forced_extras` (after the stride
    checkpoint) before any value batch exists.  The contract: the heuristic anchor
    is played, the record is the fallback record, the sampler RNG is restored, no
    value batch ran; and the same bot with a generous budget completes."""
    rnd = state(); seat = rnd.turn
    clock = [0.0]
    monkeypatch.setattr(pv.time, "perf_counter", lambda: clock[0])
    validations = []

    def slow_forced_lead(rnd_, seat_, cards, hands=None):
        validations.append(1)
        clock[0] += 0.1                       # 16 validations cross a 1 s deadline
        return forced_lead(rnd_, seat_, cards, hands)
    monkeypatch.setattr(module, "forced_lead", slow_forced_lead)

    class CountingEvaluator(ZeroEvaluator):
        calls = 0

        def score(self, leaves, seat_):
            type(self).calls += 1
            return np.zeros(len(leaves))

    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=64, candidates=8, cap=4000,
                               batch_size=128, serving_budget_seconds=1.0, admit_forced_single=True)
    bot = pv.PVSearchBot(predict, evaluator=CountingEvaluator(), version=2, config=config,
                         checkpoint="/dev/null", seed=41)
    actions = enumerate_legal(rnd, seat, cap=4000).actions
    crafted_preferences(bot, rnd, seat, [actions.index(["C10", "CA"])])
    anchor = module.HeuristicBot().decide_play(copy.deepcopy(rnd), seat)
    before = bot.sampler.rng.getstate()
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    assert played == list(anchor)
    assert record["schema"] == pv.FALLBACK_SCHEMA and record["reason"] == "budget"
    assert record["error_class"] == "PVSearchBudgetExceeded" and record["work_complete"] is False
    assert bot.sampler.rng.getstate() == before
    assert CountingEvaluator.calls == 0
    # the deadline fired at a stride checkpoint inside the world loop: bounded work
    # (a literal, so a tree without the in-loop checkpoint fails on the COUNT: it
    # resolves all 64 worlds of the first throw before any check)
    assert 0 < len(validations) <= 32
    assert module.FORCED_BUDGET_STRIDE == 16
    # a generous budget completes with the extras admitted, and consumes the stream
    clock[0] = 0.0
    bot.serving_budget_seconds = 1e9
    bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    assert record["schema"] == pv.RECORD_SCHEMA and record["forced_single_added"] == [actions.index(["C10"])]
    assert bot.sampler.rng.getstate() != before


def test_both_forced_slots_plus_an_exploration_draw_pass_the_budget_guard():
    """#687 stacking found: the served candidate-budget guard counted the harvest
    mixin's exploration draw, so on the DATA path (no serving budget, no fallback)
    K=8 + 2 forced extras + 1 forced-in draw = 11 raised PVSearchPolicyError.  The
    guard now bounds the PRODUCTION ballot at the admission boundary (K + the
    forced extras), before the mixin appends its draw; the record then goes
    through the real harvest path."""
    from collections import Counter as _Counter
    from shengji.harvest import trajectory
    from shengji.harvest.common import action_key
    rnd = state(); seat = rnd.turn
    actions = enumerate_legal(rnd, seat, cap=4000).actions
    throws = [i for i, a in enumerate(actions) if len(a) >= 2
              and len(decompose(list(a), rnd.ordering).components) >= 2
              and forced_lead(rnd, seat, a) is not None]
    distinct, seen = [], set()
    for i in throws:
        f = tuple(forced_lead(rnd, seat, actions[i]))
        if f not in seen:
            seen.add(f); distinct.append(i)
        if len(distinct) == 5:
            break
    real = [sorted(h) for h in rnd.hands]
    for draw_seed in range(1, 20):           # a draw that lands OUTSIDE the ballot
        bot = _trajectory_bot(1.0, 1, admit_forced_single=True)
        import random as _random
        bot.explore_rng = _random.Random(draw_seed)
        bot._worlds = lambda *a, **k: ([(real, sorted(rnd.buried))], 1)
        crafted_preferences(bot, rnd, seat, distinct)
        action = bot.decide_play(copy.deepcopy(rnd), seat)      # raised on f78ecbe1
        record = bot.last_decision_record
        assert len(record["forced_single_added"]) == module.FORCED_EXTRA_SLOTS
        if len(record["admitted_indices"]) == 8 + module.FORCED_EXTRA_SLOTS + 1:
            break
    else:
        pytest.fail("no draw seed put the exploration draw outside the ballot")
    production = bot.last_production_ballot
    assert len(production) == 8 + module.FORCED_EXTRA_SLOTS
    assert len(bot.last_ballot) == len(production) + 1 == len(record["admitted"])
    assert bot.last_ballot[:len(production)] == production
    assert [action_key(a) for a in bot.last_ballot] == [action_key(a) for a in record["admitted"]]
    stats = _Counter()
    fields = trajectory._play_fields({}, "run", 0, 0, rnd, seat, [], action, bot, 256, stats)
    assert stats["searched"] == 1 and fields["production_ballot"] == production
    assert fields["exploration"]["added"] == bot.last_ballot[len(production):]
    assert len(fields["action_values"]["means"]) == len(bot.last_ballot)
    # the guard still bounds the PRODUCTION ballot: a hook that over-admits is refused
    class Over(pv.PVSearchBot):
        def _admit(self, rnd_, seat_, actions_, preferences, anchor_index):
            base = super()._admit(rnd_, seat_, actions_, preferences, anchor_index)
            return base + [i for i in range(len(actions_)) if i not in base][:module.FORCED_EXTRA_SLOTS + 1]
    with pytest.raises(pv.PVSearchPolicyError, match="candidate budget"):
        over = served(admit_forced_single=True)
        over.__class__ = Over
        over._worlds = lambda *a, **k: ([(real, sorted(rnd.buried))], 1)
        crafted_preferences(over, rnd, seat, distinct)
        over.decide_play(copy.deepcopy(rnd), seat)

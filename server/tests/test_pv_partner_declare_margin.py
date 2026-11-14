"""The OPTIONAL partner-declaration margin of the value declaration
(``partner_declare_margin_milli``, ``SHENGJI_PV_PARTNER_DECLARE_MARGIN``, token
``pdm<milli>``): when the current declaration is the seat's partner's, the
partner's outcome (PASS) is the incumbent and an overcall is played only when its
decided mean beats PASS by at least the margin.

Torch-free and package-free: stub value means on the real engine and the real
heuristic.  Witnesses: (a) off (unset, empty or 0): the served release-52 name and
payload are unchanged and the token appears only when set; (b) a differential over
seeded deals: the flag changes no decision and no record field where the current
declaration is not the partner's (none, an opponent's, the seat's own); (c) the
four logged production overcalls (their outcome means) as fixtures at a 0.20
margin: gains 0.091 and 0.192 are blocked, 0.208 and 0.555 kept; (d) a
heuristic reinforcement of the partner's own outcome is kept; (e) the env refuses
bad values and an orphan flag.
"""
import copy
import random

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.cards import RANKS
from shengji.engine.round import Round
from shengji.eval import served_config as sc
from shengji.train import pv_search_policy as pv
from shengji.train import value_declare as vdm
from test_pv_admission_rules import ZeroEvaluator, predict
from test_served_config import FLY, MAP, pinned_hashes  # noqa: F401

ENV = "SHENGJI_PV_PARTNER_DECLARE_MARGIN"
HEURISTIC = HeuristicBot()


def served(margin_milli=0, seed=17, **rules):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=8, candidates=8, cap=4000,
                               batch_size=128, value_declare=True,
                               partner_declare_margin_milli=margin_milli, **rules)
    return pv.PVSearchBot(predict, evaluator=ZeroEvaluator(), version=2, config=config,
                          checkpoint="/dev/null", seed=seed)


def fresh(seed):
    return Round(RANKS[seed % len(RANKS)], None if seed % 5 == 0 else seed % 4,
                 random.Random(seed))


def state_at(seed, dealt):
    """The deal ``seed`` after ``dealt`` cards, heuristic declarations applied
    before the last card's call; returns (rnd, seat of the last card)."""
    rnd = fresh(seed)
    seat = None
    while rnd.phase == "deal" and sum(len(h) for h in rnd.hands) < dealt:
        if seat is not None:
            choice = HEURISTIC.decide_declare(rnd, seat)
            if choice:
                rnd.declare(seat, choice)
        seat, _, _ = rnd.deal_next()
    return rnd, seat


def hashed_means(bot):
    """A deterministic, outcome-dependent stub head: every outcome gets a mean
    from a hash of the seat's view and the option, so decisions vary by chance."""
    def means(rnd, seat, options, check_budget=None, progress=None):
        out = []
        for option in options:
            key = repr((sorted(rnd.hands[seat]), rnd.declaration, option))
            out.append(random.Random(key).uniform(-1.0, 1.0))
        if progress is not None:
            progress["worlds_completed"] = bot.value_declare_worlds
        return np.array(out)
    return means


def logged_means(pass_mean, gain):
    """The stub head of a logged chance: the partner's outcome scores
    ``pass_mean``, every other outcome ``pass_mean + gain``."""
    def factory(bot):
        def means(rnd, seat, options, check_budget=None, progress=None):
            keep = vdm.outcome_key(rnd, seat, None)
            if progress is not None:
                progress["worlds_completed"] = bot.value_declare_worlds
            return np.array([pass_mean if vdm.outcome_key(rnd, seat, o) == keep
                             else pass_mean + gain for o in options])
        return means
    return factory


def relation(rnd, seat):
    current = rnd.declaration
    if current is None:
        return "none"
    if current["seat"] == seat:
        return "self"
    return "partner" if current["seat"] % 2 == seat % 2 else "opponent"


# ------------------------------------------------------------ (a) off: identity

def test_served_release_name_is_unchanged_unset_and_gains_the_token_only_when_set(pinned_hashes):
    served_name = FLY["SHENGJI_BOT"]
    base = sc.served_env(mappings=MAP)
    assert ENV not in base
    assert sc.registry_name(base) == served_name
    for raw in ("", "0"):
        assert sc.registry_name({**base, ENV: raw}) == served_name
    on = sc.served_env(mappings=MAP, overrides=["pdm200"])
    assert on[ENV] == "0.2"
    name = sc.registry_name(on)
    assert name != served_name and "-pdm200-" in name and served_name.count("pdm") == 0
    # the token sits right after the value declaration's tokens
    assert "-vd-vdef-pdm200-" in name
    assert name.endswith("-sc8") == served_name.endswith("-sc8")


def test_off_payload_and_bot_attributes_are_unchanged():
    base = pv.PVSearchConfig(checkpoint_sha256="f" * 64, value_declare=True)
    payload = pv.recipe_payload(base)
    assert "partner_declare_margin" not in payload
    assert "partner_declare_margin_milli" not in payload
    on = pv.PVSearchConfig(checkpoint_sha256="f" * 64, value_declare=True,
                           partner_declare_margin_milli=200)
    assert pv.recipe_payload(on)["partner_declare_margin"] == {
        "margin_milli": 200, "rule": pv.PARTNER_DECLARE_MARGIN_RULE_ID}
    assert pv.recipe_digest(on) != pv.recipe_digest(base)
    assert pv.PVSearchBot.partner_declare_margin_milli == 0
    assert "partner_declare_margin_milli" not in vars(served())


# ------------------------------------------------------------ (b) differential

@pytest.mark.parametrize("seed", range(40))
def test_the_flag_changes_only_partner_declaration_chances(seed):
    """Drive one deal with the flag-off bot (the canonical loop); at every
    admitted chance also ask a flag-on bot at the same state: outside a
    partner's declaration its choice and record equal the flag-off ones."""
    off, on = served(0), served(200)
    off._value_declare_means = hashed_means(off)
    on._value_declare_means = hashed_means(on)
    rnd = fresh(seed)
    seen = {"none": 0, "self": 0, "opponent": 0, "partner": 0}

    def call(seat, final):
        before = copy.deepcopy(rnd)
        choice = off.decide_declare(rnd, seat, final=final)
        record = off.last_declare_record
        other = on.decide_declare(copy.deepcopy(before), seat, final=final)
        other_record = on.last_declare_record
        assert "partner_declare" not in (record or {})
        if record is None:
            assert other_record is None and other == choice
        else:
            kind = relation(before, seat)
            seen[kind] += 1
            if kind != "partner":
                assert other == choice
                assert other_record.pop("partner_declare") is None
                for rec in (record, other_record):
                    rec.pop("seconds"), rec.pop("policy")
                assert other_record == record
            else:
                verdict = other_record["partner_declare"]
                assert verdict["partner_seat"] == before.declaration["seat"]
                kept = verdict["gain"] >= 0.2 and verdict["best"] != vdm.PASS
                assert verdict["overcall_kept"] == (kept and vdm.outcome_key(
                    before, seat, None if verdict["best"] == vdm.PASS
                    else verdict["best"].split()) != vdm.outcome_key(before, seat, None))
                if not verdict["overcall_kept"]:
                    keep = vdm.outcome_key(before, seat, None)
                    assert other is None or vdm.outcome_key(before, seat, other) == keep
        if choice:
            rnd.declare(seat, choice)

    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        call(seat, False)
    for seat in range(4):
        call(seat, True)
    assert sum(seen.values()) >= 1


def test_the_differential_covers_every_relation():
    """The seeds above reach no-declaration, own, opponent and partner chances."""
    seen = set()
    for seed in range(40):
        rnd = fresh(seed)
        while rnd.phase == "deal":
            seat, _, _ = rnd.deal_next()
            if rnd.declare_options(seat):
                seen.add(relation(rnd, seat))
            choice = HEURISTIC.decide_declare(rnd, seat)
            if choice:
                rnd.declare(seat, choice)
    assert seen == {"none", "self", "opponent", "partner"}


# ------------------------------------------------------------ (c) logged overcalls

#: synthetic states of the logged kinds (found by scanning seeds 0..399):
#: a fixed banker and a first round where the heuristic overcalls the partner's
#: suit with a suit pair, and a first round where the heuristic passes and the
#: every-first gate admits the chance (a joker pair is the option)
HEURISTIC_OVERCALL_FIXED = (22, 91)      # seat 2 holds CJ CJ over partner seat 0's DJ
HEURISTIC_OVERCALL_FIRST = (135, 89)     # seat 0 holds C7 C7 over partner seat 2's H7
HEURISTIC_PASS_FIRST = (20, 95)          # seat 2 holds LJ LJ over partner seat 0's S9

#: room, round: (PASS mean, overcall mean) from the production value-declare record
LOGGED = {"PJ7T r6": (0.6422172665164559, 0.7336608959242927),
          "QJIC r1": (0.4861567104070375, 0.6779099086898607),
          "TFVA r15": (0.1502867546319074, 0.35806362732715624),
          "2ZPH r16": (0.5123982154025548, 1.0675880742930919)}
BLOCKED_AT_020 = {"PJ7T r6": True, "QJIC r1": True, "TFVA r15": False, "2ZPH r16": False}


@pytest.mark.parametrize("case", sorted(LOGGED))
@pytest.mark.parametrize("state", [HEURISTIC_OVERCALL_FIXED, HEURISTIC_OVERCALL_FIRST,
                                   HEURISTIC_PASS_FIRST])
def test_logged_gains_at_a_020_margin(case, state):
    pass_mean, overcall_mean = LOGGED[case]
    gain = overcall_mean - pass_mean
    rnd, seat = state_at(*state)
    assert relation(rnd, seat) == "partner" and rnd.declare_options(seat)
    heuristic = HEURISTIC.decide_declare(rnd, seat)
    gates = {"value_declare_every_first": True}
    off, on = served(0, **gates), served(200, **gates)
    off._value_declare_means = logged_means(pass_mean, gain)(off)
    on._value_declare_means = logged_means(pass_mean, gain)(on)
    before = copy.deepcopy(rnd)
    today = off.decide_declare(copy.deepcopy(rnd), seat)
    choice = on.decide_declare(rnd, seat)
    assert rnd.hands == before.hands and rnd.declaration == before.declaration
    # today every one of these gains (> 0) overcalls the partner
    assert today is not None and vdm.outcome_key(before, seat, today) != \
        vdm.outcome_key(before, seat, None)
    record = on.last_declare_record
    verdict = record["partner_declare"]
    assert verdict["gain"] == pytest.approx(gain)
    assert verdict["incumbent_mean"] == pytest.approx(pass_mean)
    if BLOCKED_AT_020[case]:
        assert choice is None and record["played"] == vdm.PASS
        assert verdict["overcall_kept"] is False
        assert record["changed"] == (heuristic is not None)
    else:
        assert choice == today and choice in before.declare_options(seat)
        assert verdict["overcall_kept"] is True
    assert record["value_choice"] == off.last_declare_record["value_choice"]


def test_an_opponent_declaration_is_never_held():
    """The same small gain over an OPPONENT's declaration still overcalls."""
    for seed in range(400):
        rnd = fresh(seed)
        while rnd.phase == "deal":
            seat, _, _ = rnd.deal_next()
            if relation(rnd, seat) == "opponent" and rnd.declare_options(seat):
                bot = served(200, value_declare_every_first=True)
                bot._value_declare_means = logged_means(0.5, 0.05)(bot)
                ref = served(0, value_declare_every_first=True)
                ref._value_declare_means = logged_means(0.5, 0.05)(ref)
                assert bot.decide_declare(copy.deepcopy(rnd), seat) == \
                    ref.decide_declare(copy.deepcopy(rnd), seat)
                if bot.last_declare_record is not None:
                    assert bot.last_declare_record["partner_declare"] is None
                    assert bot.last_declare_record["played"] != vdm.PASS
                    return
            choice = HEURISTIC.decide_declare(rnd, seat)
            if choice:
                rnd.declare(seat, choice)
    pytest.fail("no admitted opponent-declaration chance in seeds 0..399")


# ------------------------------------------------------------ (d) the choice rule

def test_partner_declare_choice_rule():
    rnd, seat = state_at(*HEURISTIC_OVERCALL_FIXED)
    options = rnd.declare_options(seat)
    heuristic = HEURISTIC.decide_declare(rnd, seat)
    outcomes = vdm.candidate_outcomes(rnd, seat, options, heuristic)
    keep = vdm.outcome_key(rnd, seat, None)
    p = next(i for i, (key, _) in enumerate(outcomes) if key == keep)
    o = next(i for i in range(len(outcomes)) if i != p)
    decided = np.zeros(len(outcomes))
    decided[o] = 0.2
    assert pv.partner_declare_choice(rnd, seat, outcomes, decided, o, 0.2) == (True, o, True)
    decided[o] = 0.199
    assert pv.partner_declare_choice(rnd, seat, outcomes, decided, o, 0.2) == (False, p, True)
    # not a partner: the caller's rule stands
    other = copy.deepcopy(rnd)
    other.declaration = {**other.declaration, "seat": (seat + 1) % 4}
    assert pv.partner_declare_choice(other, seat, outcomes, decided, o, 0.2) == (False, o, False)
    other.declaration = None
    assert pv.partner_declare_choice(other, seat, outcomes, decided, o, 0.2) == (False, o, False)


def test_an_abandoned_evaluation_falls_back_to_the_heuristic_unchanged():
    rnd, seat = state_at(*HEURISTIC_OVERCALL_FIXED)
    bot = served(200)

    def boom(*args, **kwargs):
        raise RuntimeError("value head failed")
    bot._value_declare_means = boom
    assert bot.decide_declare(rnd, seat) == HEURISTIC.decide_declare(rnd, seat)
    assert bot.last_declare_record["partner_declare"] is None
    assert bot.last_declare_record["fallback_reason"] == "error"


# ------------------------------------------------------------ (e) env

def test_env_parses_and_refuses():
    from test_pv_admission_rules import PRODUCTION_ENV
    vd = {**PRODUCTION_ENV, "SHENGJI_PV_VALUE_DECLARE": "1"}
    assert "partner_declare_margin_milli" not in pv.pv_env_recipe(vd)
    for raw in ("", "0"):
        assert "partner_declare_margin_milli" not in pv.pv_env_recipe({**vd, ENV: raw})
    assert pv.pv_env_recipe({**vd, ENV: "0.2"})["partner_declare_margin_milli"] == 200
    for bad, match in (("x", "not a number"), ("0.2005", "whole thousandths"),
                       ("-0.1", "0 \\(off\\) or an int"), ("nan", "whole thousandths"),
                       ("2.5", "0 \\(off\\) or an int")):
        with pytest.raises(pv.PVSearchPolicyError, match=match):
            pv.pv_env_recipe({**vd, ENV: bad})
    with pytest.raises(pv.PVSearchPolicyError, match="requires value_declare"):
        pv.pv_env_recipe({**PRODUCTION_ENV, ENV: "0.2"})
    with pytest.raises(pv.PVSearchPolicyError, match="requires value_declare"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64,
                                            partner_declare_margin_milli=200))

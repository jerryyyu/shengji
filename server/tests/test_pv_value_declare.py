"""The OPTIONAL value-guided trump declaration of the pv-search bot
(``value_declare``, ``SHENGJI_PV_VALUE_DECLARE``): where the heuristic would
declare, or in the final grace window, every declare option and PASS is scored
by the value head on sampled complete deals and the argmax replaces the
heuristic's choice only past a margin; an expiry or error falls back to the
heuristic (`PVSearchBot.decide_declare`, world model `value_declare`).

Torch-free and package-free: stub evaluators on the real engine and the real
heuristic.  Witnesses: (a) off: the release names, digests and payload are
unchanged and ``decide_declare`` is the heuristic's on every call of seeded
deals, with no record and no model call; (b) on: the ``vd`` token is last and the
digest moves with each parameter; the env refuses bad flags and orphan
parameters; (c) on: every return is legal, the gate admits only final calls and
heuristic declarations, a value-indifferent head never changes anything;
(d) a head that prefers no-trump redirects a suit declaration to the joker pair
(``changed``), a margin above the gap keeps the heuristic; (e) an expired
budget and an evaluator exception fall back to the heuristic with the reason
recorded, an interrupt propagates, no bot RNG moves; (f) the world model: the
seat's hand, the public declaration and card conservation; PASS takes the
engine's no-declaration path; (g) the screen wrapper counts declare records.
"""
import copy
import random
from collections import Counter

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.cards import RANKS, is_joker, make_deck
from shengji.engine.round import Round
from shengji.train import pv_search_policy as pv
from shengji.train import value_declare as vdm
from test_pv_adaptive_worlds import RELEASE42_ENV, RELEASE42_NAME
from test_pv_admission_rules import (PRODUCTION_ENV, PRODUCTION_NAME, PRODUCTION_SHA,
                                     ZeroEvaluator, names, predict,
                                     production_package)  # noqa: F401
from test_pv_small_joker_lead import RELEASE38_ENV, RELEASE38_NAME

FLAG = "SHENGJI_PV_VALUE_DECLARE"
HEURISTIC = HeuristicBot()


class NTEvaluator:
    """Prefers no-trump: 1 for a no-trump position, else 0."""
    backend = "numpy"
    max_batch = 128

    def __init__(self):
        self.calls = 0

    def score(self, positions, seat):
        self.calls += 1
        return np.array([1.0 if p.trump_is_nt else 0.0 for p in positions])


class RaisingEvaluator:
    backend = "numpy"
    max_batch = 128

    def __init__(self, exc=RuntimeError):
        self.exc, self.calls = exc, 0

    def score(self, positions, seat):
        self.calls += 1
        raise self.exc("value head failed")


def served(evaluator=None, budget=None, seed=17, **rules):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=8, candidates=8, cap=4000,
                               batch_size=128, serving_budget_seconds=budget, **rules)
    return pv.PVSearchBot(predict, evaluator=evaluator or ZeroEvaluator(), version=2,
                          config=config, checkpoint="/dev/null", seed=seed)


def fresh(seed):
    """A seeded deal: every rank, a known banker or (every fifth) a first round."""
    return Round(RANKS[seed % len(RANKS)], None if seed % 5 == 0 else seed % 4,
                 random.Random(seed))


def drive(seed, bot, check=None):
    """The canonical declare loop (`ai.env.prepare_round`) with ``bot`` at every
    seat; ``check(rnd_before, seat, final, choice, record)`` sees every call."""
    rnd = fresh(seed)

    def call(seat, final):
        before = copy.deepcopy(rnd)
        choice = bot.decide_declare(rnd, seat, final=final)
        if check is not None:
            check(before, seat, final, choice, getattr(bot, "last_declare_record", None))
        if choice:
            rnd.declare(seat, choice)

    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        call(seat, False)
    for seat in range(4):
        call(seat, True)
    return rnd


def state_at(seed, dealt):
    """The deal ``seed`` after ``dealt`` cards, heuristic declarations applied
    BEFORE the last card's call; returns (rnd, seat of the last card)."""
    rnd = fresh(seed)
    seat = None
    while rnd.phase == "deal" and sum(len(h) for h in rnd.hands) < dealt:
        if seat is not None:
            choice = HEURISTIC.decide_declare(rnd, seat)
            if choice:
                rnd.declare(seat, choice)
        seat, _, _ = rnd.deal_next()
    return rnd, seat


#: seed 22, the 81st card: seat 0's heuristic declares a suit while a joker
#: pair is among its options (found by scanning seeds 0..399)
NT_CASE = (22, 81)


# ------------------------------------------------------------ (a) off: identity

def test_release_names_unchanged_when_off(production_package):
    assert names(PRODUCTION_ENV) == [PRODUCTION_NAME]
    assert names(RELEASE38_ENV) == [RELEASE38_NAME]
    assert names(RELEASE42_ENV) == [RELEASE42_NAME]
    for raw in ("0", ""):
        assert names({**RELEASE42_ENV, FLAG: raw}) == [RELEASE42_NAME]
    config = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0)
    assert pv.recipe_digest(config) == "4a09aef5"
    payload = pv.recipe_payload(config)
    assert not any(key.startswith("value_declare") for key in payload)
    assert pv.PVSearchBot.value_declare is False
    assert pv.PVSearchBot.last_declare_record is None


@pytest.mark.parametrize("seed", range(12))
def test_off_is_the_heuristic_on_every_call(seed):
    bot = served(RaisingEvaluator())        # any model call would raise
    calls = []

    def check(before, seat, final, choice, record):
        assert choice == HEURISTIC.decide_declare(before, seat, final=final)
        assert record is None
        calls.append(final)

    drive(seed, bot, check)
    assert calls.count(True) == 4 and len(calls) == 104
    assert bot.evaluator.calls == 0
    assert "last_declare_record" not in vars(bot) and "value_declare" not in vars(bot)


# ------------------------------------------------------------ (b) name, digest, env

def test_vd_token_last_and_digest_when_on(production_package):
    on, = names({**RELEASE42_ENV, FLAG: "1"})
    assert on.startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-vd-r")
    assert "-bury-hybrid-" in on and on != RELEASE42_NAME
    every, = names({**RELEASE42_ENV, FLAG: "1", "SHENGJI_PV_ADAPTIVE_WORLDS_LEADS": "1"})
    assert every.startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-awl-vd-r")
    assert pv.RULE_TOKENS[-1] == ("value_declare", "vd")
    assert pv.RULE_FLAGS["VALUE_DECLARE"] == "value_declare"
    worlds, = names({**RELEASE42_ENV, FLAG: "1", "SHENGJI_PV_VALUE_DECLARE_WORLDS": "32"})
    margin, = names({**RELEASE42_ENV, FLAG: "1", "SHENGJI_PV_VALUE_DECLARE_MARGIN": "0.05"})
    assert len({RELEASE42_NAME, on, worlds, margin}) == 4
    base = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA)
    vd = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, value_declare=True)
    payload = pv.recipe_payload(vd)
    assert payload["value_declare"] is True and payload["value_declare_worlds"] == 16
    assert payload["value_declare_margin"] == 0.0
    assert payload["value_declare_model"] == vdm.MODEL
    assert pv.recipe_digest(base) != pv.recipe_digest(vd)


@pytest.mark.parametrize("bad", ["2", "true", "yes", "on", " 1"])
def test_env_flag_refuses_anything_but_0_or_1(bad):
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: bad})
    assert "value_declare" not in pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "0"})
    recipe = pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "1",
                               "SHENGJI_PV_VALUE_DECLARE_WORLDS": "24",
                               "SHENGJI_PV_VALUE_DECLARE_MARGIN": "0.1"})
    assert (recipe["value_declare"], recipe["value_declare_worlds"],
            recipe["value_declare_margin"]) == (True, 24, 0.1)


@pytest.mark.parametrize("env,match", [
    ({"SHENGJI_PV_VALUE_DECLARE_WORLDS": "8"}, "needs SHENGJI_PV_VALUE_DECLARE=1"),
    ({FLAG: "0", "SHENGJI_PV_VALUE_DECLARE_MARGIN": "0.1"}, "needs SHENGJI_PV_VALUE_DECLARE=1"),
    ({FLAG: "1", "SHENGJI_PV_VALUE_DECLARE_WORLDS": "0"}, "positive int"),
    ({FLAG: "1", "SHENGJI_PV_VALUE_DECLARE_WORLDS": "1.5"}, "not a number"),
    ({FLAG: "1", "SHENGJI_PV_VALUE_DECLARE_MARGIN": "-0.1"}, ">= 0"),
    ({FLAG: "1", "SHENGJI_PV_VALUE_DECLARE_MARGIN": "nan"}, ">= 0"),
])
def test_env_refuses_bad_or_orphan_parameters(env, match):
    with pytest.raises(pv.PVSearchPolicyError, match=match):
        pv.pv_env_recipe({**PRODUCTION_ENV, **env})


def test_bad_config_values_are_refused():
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, value_declare=1))
    with pytest.raises(pv.PVSearchPolicyError, match="need value_declare"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, value_declare_worlds=8))
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        served(value_declare="1")
    with pytest.raises(pv.PVSearchPolicyError, match="positive int"):
        served(value_declare=True, value_declare_worlds=0)


# ------------------------------------------------------------ (c) on: legality, gate

@pytest.mark.parametrize("seed", range(12))
def test_on_returns_legal_choices_and_gates_like_documented(seed):
    bot = served(NTEvaluator(), value_declare=True)
    seen = {"records": 0}

    def check(before, seat, final, choice, record):
        options = before.declare_options(seat)
        heuristic = HEURISTIC.decide_declare(before, seat, final=final)
        assert choice is None or choice in options
        admitted = bool(options) and (final or heuristic is not None)
        assert (record is not None) == admitted
        if record is None:
            assert choice == heuristic
            return
        seen["records"] += 1
        assert record["schema"] == pv.VALUE_DECLARE_RECORD_SCHEMA
        assert record["evaluated"] is True and record["fallback_reason"] is None
        assert record["worlds_completed"] == record["worlds"] == 16
        assert record["heuristic"] == (vdm.PASS if heuristic is None else " ".join(heuristic))
        assert record["played"] == (vdm.PASS if choice is None else " ".join(choice))
        assert record["changed"] == (choice != heuristic)
        if not final and choice is None:
            assert record["changed"]            # a withheld mid-deal declaration

    drive(seed, bot, check)
    assert seen["records"] >= 1


@pytest.mark.parametrize("seed", range(6))
def test_an_indifferent_head_never_changes_anything(seed):
    bot = served(ZeroEvaluator(), value_declare=True)
    changed = []

    def check(before, seat, final, choice, record):
        assert choice == HEURISTIC.decide_declare(before, seat, final=final)
        if record is not None:
            assert record["evaluated"] and not record["changed"]
            changed.append(record["changed"])

    drive(seed, bot, check)
    assert changed


# ------------------------------------------------------------ (d) a changed decision

def test_a_no_trump_head_redirects_the_suit_declaration_to_the_joker_pair():
    rnd, seat = state_at(*NT_CASE)
    heuristic = HEURISTIC.decide_declare(rnd, seat)
    assert heuristic and not is_joker(heuristic[0])
    assert any(is_joker(o[0]) for o in rnd.declare_options(seat))
    before = copy.deepcopy(rnd)
    bot = served(NTEvaluator(), value_declare=True)
    choice = bot.decide_declare(rnd, seat)
    assert rnd.hands == before.hands and rnd.declaration == before.declaration
    assert choice in rnd.declare_options(seat) and is_joker(choice[0])
    record = bot.last_declare_record
    assert record["changed"] is True and record["evaluated"] is True
    assert record["value_choice"] == record["played"] == " ".join(choice)
    assert record["heuristic"] == " ".join(heuristic)
    assert record["best_mean"] == 1.0 and record["heuristic_mean"] == 0.0
    # the same evaluation, deterministic per decision: no bot stream is involved
    state = bot.sampler.rng.getstate()
    assert served(NTEvaluator(), value_declare=True).decide_declare(rnd, seat) == choice
    assert bot.sampler.rng.getstate() == state


def test_a_margin_above_the_gap_keeps_the_heuristic():
    rnd, seat = state_at(*NT_CASE)
    bot = served(NTEvaluator(), value_declare=True, value_declare_margin=1.0)
    assert bot.decide_declare(rnd, seat) == HEURISTIC.decide_declare(rnd, seat)
    record = bot.last_declare_record
    assert record["changed"] is False and record["value_choice"].startswith(("BJ", "LJ"))


# ------------------------------------------------------------ (e) fallbacks

def test_an_expired_budget_falls_back_to_the_heuristic():
    rnd, seat = state_at(*NT_CASE)
    evaluator = NTEvaluator()
    bot = served(evaluator, budget=1e-9, value_declare=True)
    assert bot.decide_declare(rnd, seat) == HEURISTIC.decide_declare(rnd, seat)
    record = bot.last_declare_record
    assert record["evaluated"] is False and record["changed"] is False
    assert (record["fallback_reason"], record["fallback_error"]) == \
        ("hard_budget", "PVSearchBudgetExceeded")
    assert record["worlds_completed"] == 0 and record["value_choice"] is None
    assert evaluator.calls == 0


def test_a_budget_that_holds_publishes_the_value_choice():
    rnd, seat = state_at(*NT_CASE)
    bot = served(NTEvaluator(), budget=60.0, value_declare=True)
    assert is_joker(bot.decide_declare(rnd, seat)[0])
    assert bot.last_declare_record["fallback_reason"] is None


def test_an_evaluator_exception_falls_back_and_records_the_reason():
    rnd, seat = state_at(*NT_CASE)
    for budget in (None, 60.0):
        bot = served(RaisingEvaluator(), budget=budget, value_declare=True)
        assert bot.decide_declare(rnd, seat) == HEURISTIC.decide_declare(rnd, seat)
        record = bot.last_declare_record
        assert (record["fallback_reason"], record["fallback_error"]) == ("error", "RuntimeError")
        assert record["evaluated"] is False and bot.evaluator.calls == 1


def test_an_interrupt_propagates():
    rnd, seat = state_at(*NT_CASE)
    bot = served(RaisingEvaluator(KeyboardInterrupt), value_declare=True)
    with pytest.raises(KeyboardInterrupt):
        bot.decide_declare(rnd, seat)


def test_a_world_model_error_falls_back(monkeypatch):
    rnd, seat = state_at(*NT_CASE)

    def broken(*a, **k):
        raise vdm.ValueDeclareError("refused")
    monkeypatch.setattr(vdm, "sample_declare_world", broken)
    bot = served(NTEvaluator(), value_declare=True)
    assert bot.decide_declare(rnd, seat) == HEURISTIC.decide_declare(rnd, seat)
    assert bot.last_declare_record["fallback_error"] == "ValueDeclareError"


# ------------------------------------------------------------ (f) the world model

@pytest.mark.parametrize("seed", [0, 3, 22, 41])
def test_sampled_worlds_keep_the_view_and_conserve_cards(seed):
    rnd, seat = state_at(seed, 70)
    declarer = rnd.declaration["seat"] if rnd.declaration else None
    rng = random.Random(seed)
    for _ in range(5):
        hands, kitty = vdm.sample_declare_world(rnd, seat, rng)
        assert [len(h) for h in hands] == [25] * 4 and len(kitty) == 8
        assert Counter(sum(hands, []) + kitty) == Counter(make_deck())
        assert hands[seat][:len(rnd.hands[seat])] == rnd.hands[seat]
        if declarer is not None and declarer != seat:
            assert not Counter(rnd.declaration["cards"]) - Counter(hands[declarer])


def test_pass_without_a_declaration_takes_the_engine_flip():
    rnd = Round("5", None, random.Random(3))
    for _ in range(40):
        rnd.deal_next()
    assert rnd.declaration is None
    hands, kitty = vdm.sample_declare_world(rnd, 1, random.Random(0))
    position = vdm.declare_outcome_position(rnd, 1, hands, kitty, None)
    flipped = next(c for c in kitty if not is_joker(c))
    assert position.banker == 0 and position.trump_suit == flipped[0]
    assert position.phase == "play" and len(position.history) == 1
    assert vdm.outcome_key(rnd, 1, None) == (0, "flip")
    assert rnd.phase == "deal" and len(rnd.hands[1]) == 10      # never mutated


def test_outcomes_merge_single_and_pair_of_one_suit():
    rnd = Round("2", 1, random.Random(0))
    rnd.hands[0] = ["S2", "S2", "H2", "BJ", "BJ", "LJ", "LJ"]
    options = rnd.declare_options(0)
    outcomes = vdm.candidate_outcomes(rnd, 0, options, ["H2"])
    assert outcomes == [((1, "H"), ["H2"]), ((1, "NT"), ["BJ", "BJ"]),
                        ((1, "S"), ["S2", "S2"]), ((1, "flip"), None)]


# ------------------------------------------------------------ (g) the screen record

def test_the_screen_wrapper_counts_declare_records():
    from shengji.train.search_screen import TimedPolicy
    on = TimedPolicy(served(NTEvaluator(), value_declare=True))
    off = TimedPolicy(served(ZeroEvaluator()))
    for policy in (on, off):
        drive(4, policy)
    assert "declare_decisions" not in vars(off)
    rows = on.declare_decisions
    assert rows and all(r["phase"] == "declare" and isinstance(r["changed"], bool)
                        and "evaluated" in r and "worlds_completed" in r for r in rows)
    assert [r["outcome_means"] for r in rows if r["outcome_means__len"] <= 8]


def deadline_factory():
    from shengji.train.search_screen import TimedPolicy
    return TimedPolicy(served(NTEvaluator(), value_declare=True))


def test_the_deadline_worker_returns_declare_records():
    """The screen's spawned per-move worker (`screen_deadline`) carries the
    declare receipts back to the parent like the bury ones."""
    from shengji.train.screen_deadline import DeadlineSession
    rnd, seat = state_at(*NT_CASE)
    session = DeadlineSession(deadline_factory, 30)
    try:
        remote = session.register()
        choice = remote.decide_declare(copy.deepcopy(rnd), seat)
        assert is_joker(choice[0])
        row, = remote.declare_decisions
        assert row["phase"] == "declare" and row["changed"] is True
        assert remote.decide_declare(copy.deepcopy(rnd), (seat + 1) % 4) is None
        assert len(remote.declare_decisions) == 1          # a gated call adds none
        assert "declare_decisions" not in remote.session.checkpoints[remote.index]["timing"]
    finally:
        session.close()

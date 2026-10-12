"""The two OPTIONAL first-round declaration rules of the pv-search bot (#707
"Declare-frequency diagnostic"), both OFF BY DEFAULT:

* ``value_declare_every_first`` (``SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST``, token
  ``vdef``, requires ``value_declare``): in a round with no fixed banker the
  value-declare gate admits every chance with an option; with a fixed banker
  the gate is unchanged.  Only `PVSearchBot._declare_gate_name` changes; the
  record gains ``gate``.
* ``declare_asap_first`` (``SHENGJI_PV_DECLARE_ASAP_FIRST``, token ``asap``,
  exclusive with ``value_declare``): no model call; in a round with no fixed
  banker the strongest available option is declared at every chance that has
  one (so the seat overcalls itself when a strictly stronger one appears); with
  a fixed banker the decision is the heuristic's.  Record
  ``pv-declare-asap-decision-v1``.

Torch-free and package-free (stub evaluators, the real engine and heuristic).
Witnesses: (a) off: the release names are unchanged, the declare sequence of
12 seeded deals is the heuristic's with value declare off and the plain gate's
with it on, no new attribute is set; (b) names, digest, env parsing and the
refusals (vdef without vd, asap with vd); (c) vdef: every first-round chance
with an option is admitted (gate ``every_first`` exactly where the plain gate
would not have), the fixed-banker gate is unchanged, the served gate the
server reads agrees; (d) asap: the first chance with an option declares the
strongest, a strictly stronger later option is an overcall (self included),
fixed-banker rounds are exactly the heuristic, the record has its schema;
(e) the screen wrapper carries both records.
"""
import copy
import random
import tomllib
from pathlib import Path

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.cards import RANKS
from shengji.engine.round import Round
from shengji.train import pv_search_policy as pv
from test_pv_adaptive_worlds import RELEASE42_ENV, RELEASE42_NAME
from test_pv_admission_rules import (PRODUCTION_ENV, PRODUCTION_SHA, ZeroEvaluator, names,
                                     production_package)  # noqa: F401
from test_pv_value_declare import NTEvaluator, RaisingEvaluator, served

VD = "SHENGJI_PV_VALUE_DECLARE"
VDEF = "SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST"
ASAP = "SHENGJI_PV_DECLARE_ASAP_FIRST"
HEURISTIC = HeuristicBot()
#: release 43 (fly.toml at this head) with each flag, checkpoint id stubbed
RELEASE43_NAME = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-r91979586-bury-hybrid-28570365d86b"
RELEASE43_VD = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-radd86676-bury-hybrid-6c1fb26b80e6"
RELEASE43_VDEF = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-vdef-rf4c6c3c2-bury-hybrid-2be7b44246f4"
RELEASE43_ASAP = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-asap-r4a86f516-bury-hybrid-f6c937cfae7f"


def fresh(seed, first):
    """A seeded deal: a first round (no banker) or a fixed banker."""
    return Round(RANKS[seed % len(RANKS)], None if first else seed % 4, random.Random(seed))


def plain_gate(before, seat, final):
    """The gate as it was before this change (`PVSearchBot.declare_gate`, #952)."""
    options = before.declare_options(seat)
    return bool(options) and (final or HEURISTIC.decide_declare(before, seat, final=final) is not None)


def drive(rnd, bot, check=None):
    """The canonical declare loop (`ai.env.prepare_round`) with ``bot`` at every
    seat; ``check(rnd_before, seat, final, choice, record)`` sees every call."""
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


def sequence(rnd, bot):
    out = []
    drive(rnd, bot, lambda before, seat, final, choice, record: out.append((seat, final, choice)))
    return out


def fly_env():
    """The RELEASE-43 env: production's fly.toml minus the value-declare line.

    Production is release 44 (release 43 + SHENGJI_PV_VALUE_DECLARE), so the flag-off
    identities below are derived from the documented release-43 rollback, exactly as
    test_bury_arms / test_fixed_tape_policy derive release 38."""
    env = tomllib.loads((Path(__file__).parents[2] / "fly.toml").read_text())["env"]
    assert env.get(VD) == "1"
    return {k: v for k, v in env.items() if k != VD}


# ------------------------------------------------------------ (a) off: identity

def test_release_names_and_defaults_unchanged_when_off(production_package):
    assert names(RELEASE42_ENV) == [RELEASE42_NAME]
    assert names(fly_env()) == [RELEASE43_NAME]
    for flag in (VDEF, ASAP):
        for raw in ("0", ""):
            assert names({**RELEASE42_ENV, flag: raw}) == [RELEASE42_NAME]
            assert names({**RELEASE42_ENV, VD: "1", flag: raw}) == names({**RELEASE42_ENV, VD: "1"})
    config = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0)
    assert pv.recipe_digest(config) == "4a09aef5"
    payload = pv.recipe_payload(config)
    assert "value_declare_every_first" not in payload and "declare_asap_first" not in payload
    on = pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, value_declare=True))
    assert "value_declare_every_first" not in on and "declare_asap_first" not in on
    assert pv.PVSearchBot.value_declare_every_first is False
    assert pv.PVSearchBot.declare_asap_first is False


@pytest.mark.parametrize("first", [True, False])
@pytest.mark.parametrize("seed", range(12))
def test_off_declare_sequence_is_the_heuristic_with_value_declare_off(seed, first):
    bot = served(RaisingEvaluator())

    def check(before, seat, final, choice, record):
        assert choice == HEURISTIC.decide_declare(before, seat, final=final)
        assert record is None

    drive(fresh(seed, first), bot, check)
    assert bot.evaluator.calls == 0
    assert not {"last_declare_record", "value_declare", "value_declare_every_first",
                "declare_asap_first"} & vars(bot).keys()


@pytest.mark.parametrize("first", [True, False])
@pytest.mark.parametrize("seed", range(12))
def test_off_declare_sequence_is_the_plain_gate_with_value_declare_on(seed, first):
    """With both new flags off, a value-declare bot admits exactly the chances
    the pre-change gate admitted and its records name only those gates; its
    declare sequence equals a bot pinned to the pre-change gate."""
    bot = served(NTEvaluator(), value_declare=True, value_declare_worlds=4)

    def check(before, seat, final, choice, record):
        assert (record is not None) == plain_gate(before, seat, final)
        if record is not None:
            assert record["gate"] == ("final" if final else "heuristic")
            assert record["schema"] == pv.VALUE_DECLARE_RECORD_SCHEMA

    got = []
    drive(fresh(seed, first), bot,
          lambda b, s, f, c, r: (check(b, s, f, c, r), got.append((s, f, c))))
    pinned = served(NTEvaluator(), value_declare=True, value_declare_worlds=4)
    pinned._declare_gate_name = (lambda rnd, seat, final, heuristic:
                                 (("final" if final else "heuristic")
                                  if plain_gate(rnd, seat, final) else None))
    assert got == sequence(fresh(seed, first), pinned)
    assert not {"value_declare_every_first", "declare_asap_first"} & vars(bot).keys()


# ------------------------------------------------------------ (b) names, env, refusals

def test_vdef_token_follows_vd_and_asap_takes_the_declare_slot(production_package):
    env = fly_env()
    assert names({**env, VD: "1"}) == [RELEASE43_VD]
    assert names({**env, VD: "1", VDEF: "1"}) == [RELEASE43_VDEF]
    assert names({**env, ASAP: "1"}) == [RELEASE43_ASAP]
    vdef, = names({**RELEASE42_ENV, VD: "1", VDEF: "1"})
    assert vdef.startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-vd-vdef-r")
    asap, = names({**RELEASE42_ENV, ASAP: "1"})
    assert asap.startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-asap-r")
    awl, = names({**RELEASE42_ENV, "SHENGJI_PV_ADAPTIVE_WORLDS_LEADS": "1", ASAP: "1"})
    assert awl.startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-awl-asap-r")
    assert pv.RULE_TOKENS[-4:-1] == (("value_declare", "vd"), ("value_declare_every_first", "vdef"),
                                     ("declare_asap_first", "asap"))   # then the value-leaf rule lpft
    assert pv.RULE_FLAGS["VALUE_DECLARE_EVERY_FIRST"] == "value_declare_every_first"
    assert pv.RULE_FLAGS["DECLARE_ASAP_FIRST"] == "declare_asap_first"
    vd = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, value_declare=True)
    every = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, value_declare=True,
                              value_declare_every_first=True)
    first = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, declare_asap_first=True)
    base = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA)
    assert len({pv.recipe_digest(c) for c in (base, vd, every, first)}) == 4
    assert pv.recipe_payload(every)["value_declare_every_first"] is True
    assert pv.recipe_payload(first)["declare_asap_first"] is True
    assert not any(k.startswith("value_declare") for k in pv.recipe_payload(first))


@pytest.mark.parametrize("flag", [VDEF, ASAP])
@pytest.mark.parametrize("bad", ["2", "true", "yes", " 1"])
def test_env_flags_refuse_anything_but_0_or_1(flag, bad):
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, VD: "1", flag: bad})


def test_env_parses_the_flags():
    recipe = pv.pv_env_recipe({**PRODUCTION_ENV, VD: "1", VDEF: "1"})
    assert recipe["value_declare"] is True and recipe["value_declare_every_first"] is True
    recipe = pv.pv_env_recipe({**PRODUCTION_ENV, ASAP: "1"})
    assert recipe["declare_asap_first"] is True and "value_declare" not in recipe


def test_vdef_requires_value_declare(production_package):
    with pytest.raises(pv.PVSearchPolicyError, match="requires value_declare"):
        names({**RELEASE42_ENV, VDEF: "1"})
    with pytest.raises(pv.PVSearchPolicyError, match="requires value_declare"):
        names({**RELEASE42_ENV, VD: "0", VDEF: "1"})
    with pytest.raises(pv.PVSearchPolicyError, match="requires value_declare"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64,
                                            value_declare_every_first=True))
    with pytest.raises(pv.PVSearchPolicyError, match="requires value_declare"):
        served(value_declare_every_first=True)
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        served(value_declare=True, value_declare_every_first=1)


def test_asap_is_exclusive_with_value_declare(production_package):
    with pytest.raises(pv.PVSearchPolicyError, match="exclusive"):
        names({**RELEASE42_ENV, VD: "1", ASAP: "1"})
    with pytest.raises(pv.PVSearchPolicyError, match="exclusive"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, value_declare=True,
                                            declare_asap_first=True))
    with pytest.raises(pv.PVSearchPolicyError, match="exclusive"):
        served(value_declare=True, declare_asap_first=True)
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        served(declare_asap_first="1")
    # asap alone also refuses the value-declare parameters (they need value_declare)
    with pytest.raises(pv.PVSearchPolicyError, match="need value_declare"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, declare_asap_first=True,
                                            value_declare_worlds=8))


# ------------------------------------------------------------ (c) vdef: the gate

@pytest.mark.parametrize("seed", range(12))
def test_vdef_admits_every_first_round_chance_with_an_option(seed):
    bot = served(NTEvaluator(), value_declare=True, value_declare_every_first=True,
                 value_declare_worlds=4)
    assert bot.value_declare_every_first is True
    gates = []

    def check(before, seat, final, choice, record):
        options = before.declare_options(seat)
        assert (record is not None) == bool(options)
        assert choice is None or choice in options
        if record is None:
            assert choice == HEURISTIC.decide_declare(before, seat, final=final)
            return
        assert record["schema"] == pv.VALUE_DECLARE_RECORD_SCHEMA
        assert record["gate"] in pv.VALUE_DECLARE_GATES
        assert (record["gate"] == "every_first") == (not plain_gate(before, seat, final))
        assert record["worlds"] == record["worlds_completed"] == 4
        assert record["evaluated"] and record["fallback_reason"] is None
        gates.append(record["gate"])
        # the served gate (what the server reads) agrees with the decision's
        assert bot.declare_gate(before, seat, final)[1] is True

    drive(fresh(seed, True), bot, check)
    # a grace-window chance exists only while some seat still has an option
    # (often none: with every chance admitted the strongest declaration is in early)
    assert "every_first" in gates


@pytest.mark.parametrize("seed", range(12))
def test_vdef_leaves_the_fixed_banker_gate_unchanged(seed):
    bot = served(NTEvaluator(), value_declare=True, value_declare_every_first=True,
                 value_declare_worlds=4)
    plain = served(NTEvaluator(), value_declare=True, value_declare_worlds=4)

    def check(before, seat, final, choice, record):
        assert before.banker is not None
        assert (record is not None) == plain_gate(before, seat, final)
        if record is not None:
            assert record["gate"] == ("final" if final else "heuristic")
        assert bot.declare_gate(before, seat, final) == plain.declare_gate(before, seat, final)

    got = []
    drive(fresh(seed, False), bot, lambda b, s, f, c, r: (check(b, s, f, c, r), got.append((s, f, c))))
    assert got == sequence(fresh(seed, False), plain)


def test_vdef_gate_names_direct():
    bot = served(ZeroEvaluator(), value_declare=True, value_declare_every_first=True)
    rnd = Round("2", None, random.Random(3))
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        heuristic = HEURISTIC.decide_declare(rnd, seat)
        gate = bot._declare_gate_name(rnd, seat, False, heuristic)
        if not rnd.declare_options(seat):
            assert gate is None
        elif heuristic is not None:
            assert gate == "heuristic"
        else:
            assert gate == "every_first"
        if heuristic:
            rnd.declare(seat, heuristic)
    for seat in range(4):
        heuristic = HEURISTIC.decide_declare(rnd, seat, final=True)
        gate = bot._declare_gate_name(rnd, seat, True, heuristic)
        assert gate == ("final" if rnd.declare_options(seat) else None)


# ------------------------------------------------------------ (d) asap

def strongest(rnd, options):
    return max(rnd._declaration_strength(o) for o in options)


@pytest.mark.parametrize("seed", range(12))
def test_asap_declares_the_strongest_option_at_every_first_round_chance(seed):
    bot = served(RaisingEvaluator(), declare_asap_first=True)
    assert bot.declare_asap_first is True and bot.value_declare is False
    firsts, overcalls, self_overcalls = [], [], []

    def check(before, seat, final, choice, record):
        options = before.declare_options(seat)
        assert (record is not None) == bool(options) == (choice is not None)
        if record is None:
            return
        assert choice in options
        assert before._declaration_strength(choice) == strongest(before, options)
        assert record["schema"] == pv.DECLARE_ASAP_RECORD_SCHEMA
        assert record["seat"] == seat and record["final"] is final
        assert record["cards_dealt"] == sum(len(h) for h in before.hands)
        assert record["options"] == len(options)
        assert record["chosen"] == " ".join(choice)
        assert record["strength"] == before._declaration_strength(choice)
        assert record["overcall"] == (before.declaration is not None)
        assert record["overcall_self"] == (before.declaration is not None
                                           and before.declaration["seat"] == seat)
        if before.declaration is None:
            firsts.append(record["cards_dealt"])
        else:
            assert record["strength"] > before.declaration["strength"]
            overcalls.append(record)
            if record["overcall_self"]:
                self_overcalls.append(record)

    rnd = drive(fresh(seed, True), bot, check)
    assert bot.evaluator.calls == 0
    assert len(firsts) == 1                  # one first declaration per deal ...
    assert rnd.declaration is not None
    # ... at the first chance any seat had an option
    probe = fresh(seed, True)
    while probe.phase == "deal":
        seat, _, _ = probe.deal_next()
        if probe.declare_options(seat):
            break
    assert firsts[0] == sum(len(h) for h in probe.hands)
    assert all(r["strength"] >= 1 for r in overcalls + self_overcalls)


def test_asap_self_overcalls_when_a_strictly_stronger_option_appears():
    """Across the seeded deals, some seat that declared a single later holds
    the pair and takes it; no seat ever re-declares at equal strength."""
    found = False
    for seed in range(40):
        bot = served(RaisingEvaluator(), declare_asap_first=True)
        records = []
        drive(fresh(seed, True), bot,
              lambda b, s, f, c, r: records.append((copy.deepcopy(b), s, r)) if r else None)
        for before, seat, record in records:
            current = before.declaration
            if current is not None:
                assert record["strength"] > current["strength"]
            if record["overcall_self"]:
                found = True
                assert current["seat"] == seat
        if found:
            break
    assert found


def test_asap_prefers_the_longer_suit_among_equal_strengths():
    bot = served(ZeroEvaluator(), declare_asap_first=True)
    rnd = Round("2", None, random.Random(0))
    rnd.hands[0] = ["S2", "H2", "S5", "S7", "S9", "H3"]
    rnd.hands[1] = []
    rnd.hands[2] = []
    rnd.hands[3] = []
    options = rnd.declare_options(0)
    assert sorted(o[0] for o in options) == ["H2", "S2"]
    assert bot.decide_declare(rnd, 0) == ["S2"]
    assert bot.last_declare_record["chosen"] == "S2" and bot.last_declare_record["strength"] == 1
    rnd.hands[0] = ["S2", "H2", "H5", "H7", "H9", "S3"]
    assert bot.decide_declare(rnd, 0) == ["H2"]
    rnd.hands[0] = ["S2", "H2", "H2", "H5", "S7", "S9", "S3"]
    assert bot.decide_declare(rnd, 0) == ["H2", "H2"]      # a pair beats any single
    rnd.hands[0] = ["S2", "H2", "H2", "BJ", "BJ", "LJ", "LJ"]
    assert bot.decide_declare(rnd, 0) == ["BJ", "BJ"]
    assert bot.last_declare_record["strength"] == 4


@pytest.mark.parametrize("seed", range(12))
def test_asap_is_exactly_the_heuristic_with_a_fixed_banker(seed):
    bot = served(RaisingEvaluator(), declare_asap_first=True)

    def check(before, seat, final, choice, record):
        assert before.banker is not None
        assert choice == HEURISTIC.decide_declare(before, seat, final=final)
        assert record is None

    drive(fresh(seed, False), bot, check)
    assert bot.last_declare_record is None and bot.evaluator.calls == 0


def test_asap_served_gate_stays_inline():
    """The server runs `decide_declare` inline (no copy, no off-loop worker)
    for a bot whose ``value_declare`` is off; asap is such a bot."""
    bot = served(ZeroEvaluator(), declare_asap_first=True)
    rnd = Round("2", None, random.Random(1))
    seat, _, _ = rnd.deal_next()
    assert getattr(bot, "value_declare") is False
    assert bot.declare_gate(rnd, seat)[1] is False


# ------------------------------------------------------------ (e) the screen wrapper

def test_the_screen_wrapper_carries_both_records():
    from shengji.train.search_screen import TimedPolicy
    asap = TimedPolicy(served(ZeroEvaluator(), declare_asap_first=True))
    every = TimedPolicy(served(NTEvaluator(), value_declare=True, value_declare_every_first=True,
                               value_declare_worlds=2))
    off = TimedPolicy(served(ZeroEvaluator()))
    for policy in (asap, every, off):
        drive(fresh(5, True), policy)
    assert "declare_decisions" not in vars(off)
    rows = asap.declare_decisions
    assert rows and all(r["schema"] == pv.DECLARE_ASAP_RECORD_SCHEMA and r["phase"] == "declare"
                        and isinstance(r["strength"], int) and isinstance(r["chosen"], str)
                        and isinstance(r["overcall_self"], bool) for r in rows)
    assert sum(1 for r in rows if not r["overcall"]) == 1
    rows = every.declare_decisions
    assert rows and "every_first" in {r["gate"] for r in rows}
    assert {r["gate"] for r in rows} <= set(pv.VALUE_DECLARE_GATES)
    assert all(r["schema"] == pv.VALUE_DECLARE_RECORD_SCHEMA for r in rows)

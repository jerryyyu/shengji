"""The OPTIONAL every-round gate of the pv-search value declaration, OFF BY
DEFAULT: ``value_declare_every_round`` (``SHENGJI_PV_VALUE_DECLARE_EVERY_ROUND``,
token ``vdea``, requires ``value_declare``, excludes ``value_declare_every_first``).
The gate admits every declare chance with an option in every round: a first
round exactly as ``vdef`` (gate ``every_first``), a round with a fixed banker
as well (gate ``every_round``).  Only `PVSearchBot._declare_gate_name` changes.

Torch-free and package-free (stub evaluators, the real engine and heuristic).
Witnesses: (a) off: release 45's name is unchanged with the flag 0 or empty,
no attribute is set; (b) the name, digest, env parsing and refusals; (c) on:
every fixed-banker chance with an option is admitted (``every_round`` exactly
where the plain gate would not), the served gate agrees, and first rounds are
decision-for-decision ``vdef``'s.
"""
import pytest

from shengji.train import pv_search_policy as pv
from test_pv_admission_rules import PRODUCTION_ENV, PRODUCTION_SHA, names, production_package  # noqa: F401
from test_pv_declare_first_round import HEURISTIC, drive, fresh, plain_gate, sequence
from test_pv_declare_served_bury import RELEASE45, fly_env
from test_pv_value_declare import NTEvaluator, served

VD = "SHENGJI_PV_VALUE_DECLARE"
VDEF = "SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST"
VDEA = "SHENGJI_PV_VALUE_DECLARE_EVERY_ROUND"


# ------------------------------------------------------------ (a) off: identity

def test_release45_name_unchanged_when_off(production_package):
    env = fly_env()
    assert names(env) == [RELEASE45]
    for raw in ("0", ""):
        assert names({**env, VDEA: raw}) == [RELEASE45]
    assert pv.PVSearchBot.value_declare_every_round is False
    on = pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, value_declare=True))
    assert "value_declare_every_round" not in on
    bot = served(NTEvaluator(), value_declare=True)
    assert "value_declare_every_round" not in vars(bot)


# ------------------------------------------------------------ (b) names, env, refusals

def test_vdea_token_follows_vdef_slot(production_package):
    env = fly_env()
    on, = names({**env, VDEA: "1"})
    assert on.startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-vdea-r")
    assert on.endswith("-bury-hybrid-bwv-" + on.rsplit("-", 1)[1]) and on != RELEASE45
    tokens = [t for _, t in pv.RULE_TOKENS]
    assert tokens.index("vdea") == tokens.index("vdef") + 1 == tokens.index("vdsb") - 1
    assert pv.RULE_FLAGS["VALUE_DECLARE_EVERY_ROUND"] == "value_declare_every_round"
    assert "every_round" in pv.VALUE_DECLARE_GATES
    vd = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, value_declare=True)
    vdef = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, value_declare=True,
                             value_declare_every_first=True)
    vdea = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, value_declare=True,
                             value_declare_every_round=True)
    assert len({pv.recipe_digest(c) for c in (vd, vdef, vdea)}) == 3
    assert pv.recipe_payload(vdea)["value_declare_every_round"] is True


@pytest.mark.parametrize("bad", ["2", "true", " 1"])
def test_env_refuses_anything_but_0_or_1(bad):
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, VD: "1", VDEA: bad})


def test_refusals(production_package):
    with pytest.raises(pv.PVSearchPolicyError, match="requires value_declare"):
        names({**PRODUCTION_ENV, VDEA: "1"})
    with pytest.raises(pv.PVSearchPolicyError, match="already contains"):
        names({**PRODUCTION_ENV, VD: "1", VDEF: "1", VDEA: "1"})
    with pytest.raises(pv.PVSearchPolicyError, match="requires value_declare"):
        served(value_declare_every_round=True)
    with pytest.raises(pv.PVSearchPolicyError, match="already contains"):
        served(value_declare=True, value_declare_every_first=True, value_declare_every_round=True)
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        served(value_declare=True, value_declare_every_round=1)


# ------------------------------------------------------------ (c) the gate

@pytest.mark.parametrize("seed", range(12))
def test_vdea_admits_every_fixed_banker_chance_with_an_option(seed):
    bot = served(NTEvaluator(), value_declare=True, value_declare_every_round=True,
                 value_declare_worlds=4)
    gates = []

    def check(before, seat, final, choice, record):
        assert before.banker is not None
        options = before.declare_options(seat)
        assert (record is not None) == bool(options)
        assert choice is None or choice in options
        if record is None:
            assert choice == HEURISTIC.decide_declare(before, seat, final=final)
            return
        assert (record["gate"] == "every_round") == (not plain_gate(before, seat, final))
        assert record["evaluated"] and record["fallback_reason"] is None
        gates.append(record["gate"])
        assert bot.declare_gate(before, seat, final)[1] is True

    rnd = drive(fresh(seed, False), bot, check)
    assert rnd.banker == seed % 4
    assert "every_round" in gates


@pytest.mark.parametrize("seed", range(12))
def test_vdea_first_round_is_vdef(seed):
    vdea = served(NTEvaluator(), value_declare=True, value_declare_every_round=True,
                  value_declare_worlds=4)
    vdef = served(NTEvaluator(), value_declare=True, value_declare_every_first=True,
                  value_declare_worlds=4)
    records = []
    got = []
    drive(fresh(seed, True), vdea,
          lambda b, s, f, c, r: (got.append((s, f, c)), records.append(r and r["gate"])))
    assert got == sequence(fresh(seed, True), vdef)
    assert "every_round" not in records

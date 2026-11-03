"""The decision records' ``model_ids`` (`PVSearchBot.model_ids`): a play, bury and
value-declare record names the value, prior and belief packages that stage consults,
as `MODEL_ID_CHARS`-hex sha256 prefixes, and nothing else about the record changes
(decision identity: ``test_degradation_telemetry_identity.py``; the served packages:
``test_release_manifests.py``)."""
import copy

import pytest

from shengji.train import pv_search_policy as pv
from test_cwv_bury_wide_value import served_bury
from test_cwv_leaf_policy_first_trick import bury_state
from test_policy_world_search import state
from test_pv_declare_served_bury import bot as declare_bot
from test_pv_value_declare import drive
from test_world_history_legal import served


class Hashed:
    """A stand-in bound object carrying only a package hash."""

    def __init__(self, **attrs):
        self.__dict__.update(attrs)


def test_ids_read_the_bound_packages_per_stage():
    bot = served(worlds=8)
    bot.evaluator = Hashed(checkpoint_sha256="a" * 64)
    bot.predict = Hashed(sha256="b" * 64)
    bot.belief_model = Hashed(package_sha256="c" * 64)
    assert pv.MODEL_ID_CHARS == 8
    assert bot.model_ids("declare") == {"value": "a" * 8, "prior": None, "belief": None}
    assert bot.model_ids("bury") == {"value": "a" * 8, "prior": None, "belief": None}
    # the belief id only where the play worlds are the belief proposal's
    assert bot.belief_worlds is False
    assert bot.model_ids("play") == {"value": "a" * 8, "prior": "b" * 8, "belief": None}
    bot.belief_worlds = True
    assert bot.model_ids("play") == {"value": "a" * 8, "prior": "b" * 8, "belief": "c" * 8}
    # the policy head reaches declare and bury only through the lpft rule
    bot.leaf_policy_first_trick = True
    assert bot.model_ids("declare")["prior"] == bot.model_ids("bury")["prior"] == "b" * 8
    with pytest.raises(ValueError, match="unknown decision stage"):
        bot.model_ids("lead")


def test_stand_ins_without_a_hash_read_as_none():
    bot = served(worlds=8)
    bot.evaluator, bot.predict = object(), object()
    assert bot.model_ids("play") == {"value": None, "prior": None, "belief": None}


def test_play_records_carry_the_ids():
    bot = served(worlds=8)
    rnd = copy.deepcopy(state())
    bot.decide_play(copy.deepcopy(rnd), rnd.turn)
    record = bot.last_decision_record
    assert record["schema"] == pv.RECORD_SCHEMA
    assert record["model_ids"] == bot.model_ids("play")


def test_fallback_play_records_carry_the_ids(monkeypatch):
    bot = served(worlds=8)
    bot.serving_budget_seconds = 3.0

    def boom(*args, **kwargs):
        raise RuntimeError("search failed")
    monkeypatch.setattr(bot, "_search", boom)
    rnd = copy.deepcopy(state())
    bot.decide_play(copy.deepcopy(rnd), rnd.turn)
    record = bot.last_decision_record
    assert record["schema"] == pv.FALLBACK_SCHEMA
    assert record["model_ids"] == bot.model_ids("play")


def test_bury_records_carry_the_ids():
    bot = served_bury(bury_wide_value=True, bury_wide_k=16)
    rnd = bury_state(0)
    bot.decide_bury(copy.deepcopy(rnd), rnd.banker)
    record = bot.last_bury_record
    assert record["schema"] == "cwv-bury-policy-v1"
    assert record["model_ids"] == bot.model_ids("bury")
    assert record["model_ids"]["prior"] is None and record["model_ids"]["belief"] is None


def test_value_declare_records_carry_the_ids():
    b = declare_bot()
    seen = []

    def check(before, seat, final, choice, record):
        if record is not None:
            seen.append(record)
    drive(3, b, check)
    assert seen
    for record in seen:
        assert record["schema"] == pv.VALUE_DECLARE_RECORD_SCHEMA
        assert record["model_ids"] == b.model_ids("declare")

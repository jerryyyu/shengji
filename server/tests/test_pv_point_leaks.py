"""The last-seat points rule (``last_seat_points_milli``, ``lsp<milli>``), OFF BY DEFAULT.

In the last seat every candidate's trick winner and points are certain; with
``SHENGJI_PV_LAST_SEAT_POINTS=<margin>`` the candidate banking the most signed
trick points among those within the margin of the best value mean is played,
and the exact follow stage still re-ranks from that choice.  Off, release 52's
name and payload are byte-identical.  The three ballots in
``fixtures/pv_point_leaks.json`` are logged production decisions (rounds
replayed from their events; no player data): A withholds a partner's points,
B feeds an opponent with an exact-stage tie, C is an exact-stage override the
rule must not undo.  Correctness and identity witnesses only, not a strength
claim.
"""
import importlib.util
import json
from pathlib import Path

import pytest

from shengji.rl.replay_log import rebuild_round
from shengji.train import pv_search_policy as pv
from shengji.train.pv_tree_config import PVTreeConfig
from test_release46_fly_config import fly_env as production_env
from test_release50_fly_config import (BELIEF_SHA, BELIEF_VOLUME_PATH, PRIOR_SHA,  # noqa: F401
                                       PRIOR_VOLUME_PATH, VALUE_SHA, VALUE_VOLUME_PATH,
                                       release50_packages, served_bot)
from test_release52_fly_config import RELEASE52

FLAG = "SHENGJI_PV_LAST_SEAT_POINTS"
FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "pv_point_leaks.json").read_text())
LSP150 = ("pv-search-f4f4127e-prior-1fa201b2-w64-k8-div-rc-rcec-whl-whd-wht-bw-tb-ele-elt-elm-la-"
          "dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-els1600-xf7-xfcompactlevel-lsp150-r5a44eca8-bury-"
          "hybrid-bwv-bbw-c5d1c7ffa049-sc8")
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "point_leak_counters.py"


def counters():
    spec = importlib.util.spec_from_file_location("point_leak_counters", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def names(monkeypatch, extra):
    from shengji.ai import cwv_policy

    by_path = {VALUE_VOLUME_PATH: VALUE_SHA, PRIOR_VOLUME_PATH: PRIOR_SHA,
               BELIEF_VOLUME_PATH: BELIEF_SHA}
    monkeypatch.setattr(cwv_policy, "checkpoint_id", lambda path: by_path[str(path)][:8])
    monkeypatch.setattr(pv, "file_sha256", lambda path: by_path[str(path)])
    return list(pv.singleton_registry_entries(**pv.pv_env_recipe({**production_env(), **extra})))


def position(label, drop_last=0):
    case = FIXTURES[label]
    events = case["events"][:len(case["events"]) - drop_last]
    rnd = rebuild_round(events)
    for event in events:
        if event["e"] == "play":
            rnd.play(event["seat"], event["cards"])
    return rnd, case


def selector(milli):
    """A bare bot carrying only the selection state `_select_rules` reads; the
    harness's ``tb`` is off here (on these ballots it leaves the argmax)."""
    bot = object.__new__(pv.PVSearchBot)
    bot.tiebreak_points = False
    bot.lead_tiebreak_prior = False
    if milli:
        bot.last_seat_points_milli = milli
    return bot


def test_off_is_release52_byte_for_byte(monkeypatch):
    assert names(monkeypatch, {}) == [RELEASE52]
    assert names(monkeypatch, {FLAG: "0"}) == [RELEASE52]
    assert names(monkeypatch, {FLAG: ""}) == [RELEASE52]
    sha = "0" * 64
    off = pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=sha))
    assert "last_seat_points" not in off and "last_seat_points_milli" not in off
    assert pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=sha, last_seat_points_milli=0)) == off


def test_on_adds_its_token_and_digests_its_margin(monkeypatch):
    assert names(monkeypatch, {FLAG: "0.15"}) == [LSP150]
    both = names(monkeypatch, {FLAG: "0.15", "SHENGJI_PV_EXACT_FOLLOW_POINTS": "1"})[0]
    assert "-xfcompactlevel-xfpt-lsp150-r" in both
    sha = "0" * 64
    payload = pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=sha, last_seat_points_milli=150))
    assert payload["last_seat_points"] == {"margin_milli": 150, "rule": pv.LAST_SEAT_POINTS_RULE_ID}
    other = pv.recipe_digest(pv.PVSearchConfig(checkpoint_sha256=sha, last_seat_points_milli=100))
    assert other != pv.recipe_digest(pv.PVSearchConfig(checkpoint_sha256=sha, last_seat_points_milli=150))
    assert pv.pv_env_recipe({**production_env(), FLAG: "0.15"})["last_seat_points_milli"] == 150


@pytest.mark.parametrize("raw", ["abc", "0.0005", "1.5", "-0.1", "inf", "nan"])
def test_env_refuses_a_bad_margin(raw):
    with pytest.raises(pv.PVSearchPolicyError):
        pv.pv_env_recipe({**production_env(), FLAG: raw})


@pytest.mark.parametrize("milli", [True, 1001, -5, 1.5, "150"])
def test_config_refuses_a_bad_margin(milli):
    with pytest.raises(pv.PVSearchPolicyError):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="0" * 64, last_seat_points_milli=milli))


def test_the_tree_is_refused():
    with pytest.raises(pv.PVSearchPolicyError):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="0" * 64, last_seat_points_milli=150,
                                            tree=PVTreeConfig(sims=8)))


@pytest.mark.parametrize("label", sorted(FIXTURES))
def test_logged_ballots_reproduce_the_counter(label):
    """The served pick is reconstructed from the logged ballot, and each arm's
    pick is the counter's."""
    rnd, case = position(label)
    seat = case["seat"]
    signed = [pv.last_seat_signed_points(rnd, seat, a) for a in case["admitted"]]
    assert signed == case["signed_points"]
    module = counters()
    arms = {"R52": (False, None), "xfpt": (True, None), "lsp150": (False, 0.15),
            "xfpt+lsp150": (True, 0.15)}
    picks = {name: module.arm_pick(case["value_means"], signed, case["exact_follow_scores"],
                                   xfpt=x, margin=m) for name, (x, m) in arms.items()}
    assert picks["R52"] == case["served_played_index"]
    assert picks == case["expected_index"]


def test_withheld_partner_points_go_to_the_partner():
    rnd, case = position("A")
    bot = selector(150)
    pick = bot._select_rules(rnd, case["seat"], case["admitted"], case["value_means"])
    assert case["admitted"][pick] == ["S10"]
    record = bot._last_seat_points_record()
    assert record["last_seat_points_applied"] is True and record["last_seat_points_to"] == "S10"
    assert 0 < record["last_seat_points_value_gap"] <= 0.15
    # the margin is the window: 0.02 leaves the argmax
    narrow = selector(20)
    assert narrow._select_rules(rnd, case["seat"], case["admitted"], case["value_means"]) == 1


def test_off_and_earlier_seats_leave_the_selection():
    rnd, case = position("B")
    argmax = max(range(len(case["value_means"])), key=lambda i: case["value_means"][i])
    off = selector(0)
    assert off._select_rules(rnd, case["seat"], case["admitted"], case["value_means"]) == argmax
    assert off._last_seat_points_record() == {}
    on = selector(150)
    assert case["admitted"][on._select_rules(rnd, case["seat"], case["admitted"],
                                             case["value_means"])] == ["H3", "H6"]
    early, _ = position("B", drop_last=1)
    assert len(early.trick.plays) == 2
    assert on._select_rules(early, early.turn, case["admitted"], case["value_means"]) == argmax
    assert on._last_seat_points_record()["last_seat_points_eligible"] is False


def test_the_exact_stage_keeps_its_override_on_the_logged_ballot():
    """Case C: the rule prefers the certain take LJ, the exact scores rank DQ
    first, and the exact winner is what the counter plays."""
    rnd, case = position("C")
    pick = selector(150)._select_rules(rnd, case["seat"], case["admitted"], case["value_means"])
    assert case["admitted"][pick] == ["LJ"]
    assert case["admitted"][case["expected_index"]["xfpt+lsp150"]] == ["DQ"]


def test_served_bot_exact_follow_reranks_from_the_rule(release50_packages, monkeypatch):
    """Release 52 plus the rule on the real packages at case C (five cards, the
    exact follow stage runs): the rule's choice is the exact stage's baseline and
    the played card is the exact stage's winner."""
    rnd, case = position("C")
    env = {**production_env(), FLAG: "0.15", "SHENGJI_BOT": LSP150}
    name, bot = served_bot(release50_packages, monkeypatch, env=env)
    assert name == bot.policy_name == LSP150
    bot.serving_budget_seconds = 600.0
    bot.exact_lead_max_seconds = 300.0
    bot.leaf_greedy_deadline_ms = 600_000
    played = sorted(bot.decide_play(rnd, case["seat"]))
    record = bot.last_decision_record
    assert record["last_seat_points_eligible"] is True
    assert record["exact_follow_attempted"] is True and record["exact_follow_abandoned"] is None
    admitted = [sorted(a) for a in record["admitted"]]
    scores = record["exact_follow_scores"]
    baseline = admitted.index(sorted(record["last_seat_points_to"].split(" ")))
    winner = admitted.index(played)
    assert scores[winner] == max(scores)
    if scores[baseline] == max(scores):
        assert winner == baseline

"""The OPTIONAL pass-conditioned declare worlds (``value_declare_pass_worlds``,
``SHENGJI_PV_VALUE_DECLARE_PASS_WORLDS``, token ``vdpw``; #707 S15(4);
`train.declare_pass_worlds`): each value-declare world is drawn from the
uniform posterior and accepted with the likelihood of the other seats'
silence, ``(1 - HAZARD) ** d`` per seat that has held a combination stronger
than the current declaration for ``d`` of its own cards.

Torch-free and package-free (stub predictor and evaluators on the real engine,
the real heuristic, the real sampler and the real leaves), except the served
construction on the serving test's tiny package and the real-package server
smoke (``SHENGJI_PV_PACKAGE_PATH``; required under
``SHENGJI_REQUIRE_PV_PACKAGE=1``).  Witnesses: (a) off: release 45's name,
digest and payload are unchanged, the declare decisions AND records of a
release-45 style bot on seeded deals are byte-identical to a tape taken on main
before this change, and neither the bot nor the record gains anything; (b) the
name: ``-vdpw`` after ``-vd``/``-vdef``/``-vdsb``, the digest and the payload move, the
env and the constructors refuse the rule without ``value_declare`` or with a
non-0/1 value; (c) the likelihood: silent cards, dealt counts, which seats
count, and the weight; (d) the sampler: the seat's view and card conservation,
determinism, acceptance matching the reweighted posterior, the hard limit and
the starvation fallback; (e) on: the bot scores exactly the sampler's worlds
from the decision's own stream, records the counts, moves no bot RNG, and an
error or expiry falls back to the heuristic; (f) the served construction.
"""
import copy
import hashlib
import json
import random
from collections import Counter

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.cards import make_deck
from shengji.engine.round import HAND_SIZE, KITTY_SIZE
from shengji.train import declare_pass_worlds as dpw
from shengji.train import pv_search_policy as pv
from shengji.train import value_declare as vdm
from shengji.train.policy_prior import CARD_INDEX
from test_cwv_leaf_policy_first_trick import BURY, SMALL, CountingPredict
from test_encoder_round_compat import PACKAGE_SHA, pinned_production_package  # noqa: F401
from test_pv_admission_rules import names, production_package  # noqa: F401
from test_pv_search_serving import package  # noqa: F401
from test_pv_value_declare import NT_CASE, drive, fresh, state_at

FLAG = "SHENGJI_PV_VALUE_DECLARE_PASS_WORLDS"
HEURISTIC = HeuristicBot()
#: production (fly.toml): release 45
RELEASE45 = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-radd86676-bury-hybrid-bwv-7a73e8fbf1a8"
#: release 45 with the rule on
RELEASE45_VDPW = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-vdpw-ra03b9199-bury-hybrid-bwv-1bf9067173dc"
#: sha256 of `tape()` taken on main at d1f0e9d4 (before this rule; the same
#: tape #994 pins): the flag-off declare decisions and records must reproduce
#: it byte for byte
OFF_TAPE_SHA256 = "c30a9691b5b81f7eff259fe6a5ada0523436556c2c8420091d70219bff54960a"
TAPE_SEEDS = (0, 3, 5, 22)


def fly_env():
    import tomllib
    from pathlib import Path
    env = tomllib.loads((Path(__file__).parents[2] / "fly.toml").read_text())["env"]
    assert env["SHENGJI_BOT"] == RELEASE45
    return dict(env)


class KittyEvaluator:
    """A deterministic value head that sees the first trick, the buried cards,
    the trump and the scoring seat (so the world, the declaration and the
    perspective all move it).  Remembers every scored position's hands."""
    backend = "numpy"
    max_batch = 128

    def __init__(self):
        self.calls = 0
        self.hands = []

    def score(self, positions, seat):
        self.calls += 1
        out = []
        for p in positions:
            self.hands.append(p)
            trick = sum(CARD_INDEX[c] for play in p.history[0].plays for c in play.cards)
            buried = sum(CARD_INDEX[c] * (i + 1) for i, c in enumerate(sorted(p.buried)))
            trump = 5 if p.trump_is_nt else "SHDC".index(p.trump_suit) if p.trump_suit else 6
            raw = (trick * 7 + buried * 3 + trump * 11 + p.banker * 13) % 101
            sign = 1.0 if (p.banker - seat) % 2 == 0 else -1.0
            out.append(sign * (raw / 101.0 - 0.5))
        return np.array(out)


def bot(evaluator=None, *, on=True, budget=None, seed=17, **rules):
    """A release-45 shaped bot (vd on, the wide chooser on) at test widths."""
    rules.setdefault("value_declare", True)
    if on:
        rules["value_declare_pass_worlds"] = True
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, serving_budget_seconds=budget,
                               **SMALL, **rules)
    return pv.PVSearchBuryBot(CountingPredict(), evaluator=evaluator or KittyEvaluator(),
                              version=2, config=config, checkpoint="/dev/null", seed=seed,
                              bury_arm="hybrid", bury_config=BURY, bury_wide_value=True,
                              bury_wide_k=64)


def tape(make):
    """Every declare call of the seeded deals: the choice and the record
    (``seconds`` dropped), as one canonical JSON digest."""
    rows = []
    for seed in TAPE_SEEDS:
        b = make()

        def check(before, seat, final, choice, record):
            if record is not None:
                record = {k: v for k, v in record.items() if k != "seconds"}
            rows.append([seed, seat, final, choice, record])
        drive(seed, b, check)
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


# ------------------------------------------------------------ (a) off: identity

def test_release45_name_digest_and_payload_unchanged_when_off(production_package):
    env = fly_env()
    assert names(env) == [RELEASE45]
    for raw in ("0", ""):
        assert names({**env, FLAG: raw}) == [RELEASE45]
    recipe = pv.pv_env_recipe(env)
    assert "value_declare_pass_worlds" not in recipe
    config = pv.PVSearchConfig(checkpoint_sha256=recipe["sha256"], worlds=64, candidates=8,
                               cap=4000, batch_size=128, serving_budget_seconds=3.0,
                               admission_diversity=True, refusal_constraints=True,
                               tiebreak_points=True, lead_anchor=True,
                               doomed_throw_reselect=True, value_declare=True)
    assert pv.recipe_digest(config) == "add86676"
    payload = pv.recipe_payload(config)
    assert not any("pass" in key for key in payload)
    assert payload["value_declare_model"] == vdm.MODEL
    assert pv.PVSearchBot.value_declare_pass_worlds is False


def test_off_declare_decisions_and_records_match_the_main_tape():
    assert tape(lambda: bot(on=False)) == OFF_TAPE_SHA256


def test_off_bot_state_and_record_carry_nothing_new(monkeypatch):
    b = bot(on=False)
    assert "value_declare_pass_worlds" not in vars(b)
    called = []
    monkeypatch.setattr(dpw, "sample_pass_world", lambda *a, **k: called.append(1))
    rnd, seat = state_at(*NT_CASE)
    b.decide_declare(rnd, seat)
    assert "pass_worlds" not in b.last_declare_record
    assert b.last_declare_record["evaluated"] is True and not called


# ------------------------------------------------------------ (b) name, digest, refusals

def test_the_token_the_digest_and_the_payload_when_on(production_package):
    env = fly_env()
    on, = names({**env, FLAG: "1"})
    assert on == RELEASE45_VDPW
    assert on.startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-vdpw-r")
    tokens = [token for _, token in pv.RULE_TOKENS]
    assert tokens.index("vdpw") == tokens.index("vdsb") + 1 == tokens.index("asap") - 1
    assert pv.RULE_FLAGS["VALUE_DECLARE_PASS_WORLDS"] == "value_declare_pass_worlds"
    every, = names({**env, FLAG: "1", "SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST": "1"})
    assert "-vd-vdef-vdpw-r" in every
    lpft, = names({**env, FLAG: "1", "SHENGJI_PV_LEAF_POLICY_FIRST_TRICK": "1"})
    assert "-vd-vdpw-lpft-r" in lpft
    served, = names({**env, FLAG: "1", "SHENGJI_PV_VALUE_DECLARE_SERVED_BURY": "1"})
    assert "-vd-vdsb-vdpw-r" in served
    vd = pv.PVSearchConfig(checkpoint_sha256="f" * 64, value_declare=True)
    pw = pv.PVSearchConfig(checkpoint_sha256="f" * 64, value_declare=True,
                           value_declare_pass_worlds=True)
    payload = pv.recipe_payload(pw)
    assert payload["value_declare_pass_worlds"] is True
    assert payload["value_declare_model"] == vdm.MODEL.replace("uniform-unseen",
                                                               "pass-conditioned-unseen")
    assert (payload["value_declare_pass_hazard"],
            payload["value_declare_pass_max_attempts"]) == (0.02, 32)
    assert pv.recipe_digest(pw) != pv.recipe_digest(vd)
    both = pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, value_declare=True,
                                               value_declare_pass_worlds=True,
                                               leaf_policy_first_trick=True))
    assert both["value_declare_model"] == ("pass-conditioned-unseen|no-counter-declare|"
                                           "heuristic-bury|policy-first-trick|"
                                           "value-head-seat-team")


@pytest.mark.parametrize("env,match", [
    ({FLAG: "2"}, "must be 0 or 1"),
    ({FLAG: "yes"}, "must be 0 or 1"),
    ({FLAG: "1", "SHENGJI_PV_VALUE_DECLARE": "0"}, "requires value_declare"),
    ({FLAG: "1", "SHENGJI_PV_VALUE_DECLARE": ""}, "requires value_declare"),
])
def test_env_refuses_bad_values_and_a_rule_with_no_effect(production_package, env, match):
    with pytest.raises(pv.PVSearchPolicyError, match=match):
        names({**fly_env(), **env})


def test_constructors_refuse_a_rule_with_no_effect(package):
    with pytest.raises(pv.PVSearchPolicyError, match="requires value_declare"):
        bot(value_declare=False)
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, **SMALL,
                               value_declare_pass_worlds=True)
    with pytest.raises(pv.PVSearchPolicyError, match="requires value_declare"):
        pv.PVSearchBot(CountingPredict(), evaluator=KittyEvaluator(), version=2,
                       config=config, checkpoint="/dev/null")
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, value_declare=True,
                                            value_declare_pass_worlds=1))
    path, sha = package
    with pytest.raises(pv.PVSearchPolicyError, match="requires value_declare"):
        pv.make_pv_search_bot(path, sha256=sha, value_declare_pass_worlds=True)


# ------------------------------------------------------------ (c) the likelihood

@pytest.mark.parametrize("dealt,current,silent", [
    ([], 0, 0),
    (["S3", "H4", "D5"], 0, 0),                    # no trump-rank card (rank 2)
    (["S2", "H4", "D5"], 0, 2),                    # a single from the first card
    (["H4", "D5", "S2"], 0, 0),                    # completed by the last card
    (["S2", "H4", "D5"], 1, 0),                    # a single does not beat a single
    (["S2", "H4", "S2", "D5", "C6"], 1, 2),        # the pair beats it from the third card
    (["S2", "H4", "S2", "D5", "C6"], 2, 0),        # nor a pair a pair
    (["LJ", "LJ", "C6"], 2, 1),                    # the small-joker pair beats a pair
    (["LJ", "LJ", "C6"], 3, 0),
    (["BJ", "C6", "BJ", "C7", "C8", "C9"], 3, 3),  # the big-joker pair beats everything
])
def test_silent_cards(dealt, current, silent):
    assert dpw.silent_cards(dealt, "2", current) == silent


@pytest.mark.parametrize("seed", range(6))
def test_dealt_counts_are_the_public_hand_sizes(seed):
    rnd = fresh(seed)
    while rnd.phase == "deal":
        assert dpw.dealt_counts(rnd) == [len(h) for h in rnd.hands]
        rnd.deal_next()
    assert dpw.dealt_counts(rnd) == [HAND_SIZE] * 4


def _round_with(rank, hands, declaration=None):
    rnd = fresh(1)
    rnd.trump_rank = rank
    rnd.hands = [list(h) for h in hands]
    rnd.declaration = declaration
    return rnd


def test_the_weight_counts_every_silent_seat_but_the_decider_and_the_declarer():
    filler = ["C3", "C4", "C5", "C6", "C7", "C8"]
    hands = [["S2"] + filler[:5],            # the deciding seat: never counts
             ["H2"] + filler[:5],            # a single from card 1: 5 silent cards
             ["D4", "D2", "D2"] + filler[:3],  # a pair from card 3: 3 silent cards
             ["C2"] + filler[:5]]            # the declarer: never counts
    rnd = _round_with("2", hands)
    assert dpw.silence_weight(rnd, 0, hands) == pytest.approx(0.98 ** (5 + 5 + 4))
    declared = _round_with("2", hands, {"seat": 3, "cards": ["C2"], "strength": 1})
    # against a single only the pair counts, and seat 3 is the declarer
    assert dpw.silence_weight(declared, 0, hands) == pytest.approx(0.98 ** 3)
    assert dpw.silence_weight(declared, 0, hands, hazard=0.5) == pytest.approx(0.5 ** 3)
    # only the dealt prefix counts: cards after the seat's dealt count are future
    longer = [h + ["H2", "H2"] for h in hands]
    assert dpw.silence_weight(declared, 0, longer) == pytest.approx(0.98 ** 3)


# ------------------------------------------------------------ (d) the sampler

@pytest.mark.parametrize("seed,dealt", [(22, 81), (3, 40), (5, 100), (7, 9)])
def test_pass_worlds_keep_the_view_conserve_cards_and_are_deterministic(seed, dealt):
    rnd, seat = state_at(seed, dealt)
    before = copy.deepcopy(rnd)
    draws = []
    for _ in range(2):
        rng = vdm.decision_rng(17, rnd, seat)
        draws.append([dpw.sample_pass_world(rnd, seat, rng) for _ in range(8)])
    assert draws[0] == draws[1]
    for hands, kitty in draws[0]:
        assert hands[seat][:len(rnd.hands[seat])] == rnd.hands[seat]
        assert [len(h) for h in hands] == [HAND_SIZE] * 4 and len(kitty) == KITTY_SIZE
        assert Counter(c for h in hands for c in h) + Counter(kitty) == Counter(make_deck())
        if rnd.declaration is not None and rnd.declaration["seat"] != seat:
            held = Counter(hands[rnd.declaration["seat"]])
            assert all(held[c] >= n for c, n in Counter(rnd.declaration["cards"]).items())
    assert vars(rnd).keys() == vars(before).keys()
    assert rnd.hands == before.hands and rnd.declaration == before.declaration


def test_acceptance_reweights_the_uniform_posterior(monkeypatch):
    """The accepted worlds' distribution is the uniform posterior times the
    silence weight: the mean number of trump-rank cards and jokers already
    dealt to the other seats matches its importance-weighted uniform mean,
    and the conditioning moves it."""
    rnd, seat = state_at(3, 60)
    monkeypatch.setattr(dpw, "HAZARD", 0.05)   # a stronger hazard so the shift is visible
    counts = dpw.dealt_counts(rnd)

    def held(hands):
        return sum(1 for s in range(4) if s != seat for c in hands[s][:counts[s]]
                   if c in ("LJ", "BJ") or c[1:] == rnd.trump_rank)
    rng = random.Random(5)
    uniform = [vdm.sample_declare_world(rnd, seat, rng)[0] for _ in range(6000)]
    weights = np.array([dpw.silence_weight(rnd, seat, h) for h in uniform])
    x = np.array([held(h) for h in uniform], dtype=float)
    expected = float((weights * x).sum() / weights.sum())
    rng = random.Random(6)
    stats = {}
    accepted = np.array([held(dpw.sample_pass_world(rnd, seat, rng, stats)[0])
                         for _ in range(6000)], dtype=float)
    assert x.mean() > expected + 0.1               # the conditioning matters here
    assert accepted.mean() == pytest.approx(expected, abs=4 * accepted.std() / np.sqrt(6000) + 0.02)
    assert stats["worlds"] == 6000 and stats["fallbacks"] == 0
    assert stats["attempts"] / stats["worlds"] == pytest.approx(1 / weights.mean(), rel=0.1)


def test_a_hard_hazard_excludes_every_silent_holder(monkeypatch):
    rnd, seat = state_at(3, 60)
    monkeypatch.setattr(dpw, "HAZARD", 1.0)
    rng = random.Random(9)
    stats = {}
    for _ in range(200):
        hands, _ = dpw.sample_pass_world(rnd, seat, rng, stats)
        if stats["fallbacks"] == 0:
            assert dpw.silence_weight(rnd, seat, hands) == 1.0


def test_starvation_returns_the_last_draw_and_counts_it(monkeypatch):
    rnd, seat = state_at(*NT_CASE)
    monkeypatch.setattr(dpw, "silence_weight", lambda *a, **k: 0.0)
    rng = vdm.decision_rng(17, rnd, seat)
    stats = {}
    hands, kitty = dpw.sample_pass_world(rnd, seat, rng, stats)
    replay = vdm.decision_rng(17, rnd, seat)
    for _ in range(dpw.MAX_ATTEMPTS):
        last = vdm.sample_declare_world(rnd, seat, replay)
        replay.random()
    assert (hands, kitty) == last
    assert stats == {"worlds": 1, "attempts": dpw.MAX_ATTEMPTS, "fallbacks": 1}


def test_the_weight_floor_keeps_acceptance_bounded():
    """The worst case is three counted seats silent for a whole hand."""
    floor = (1 - dpw.HAZARD) ** (3 * HAND_SIZE)
    assert floor > 0.2
    assert (1 - floor) ** dpw.MAX_ATTEMPTS < 1e-3


# ------------------------------------------------------------ (e) on: wiring

def test_on_scores_exactly_the_samplers_worlds_and_records_the_counts(monkeypatch):
    rnd, seat = state_at(*NT_CASE)
    b = bot()
    rng_state = b.sampler.rng.getstate()
    seen = []
    real = vdm.declare_outcome_position

    def spy(r, s, hands, kitty, option, *a, **k):
        seen.append((copy.deepcopy(hands), list(kitty)))
        return real(r, s, hands, kitty, option, *a, **k)
    monkeypatch.setattr(vdm, "declare_outcome_position", spy)
    choice = b.decide_declare(rnd, seat)
    assert choice is None or choice in rnd.declare_options(seat)
    record = b.last_declare_record
    assert record["evaluated"] is True
    outcomes = len(record["outcome_means"])
    worlds = b.value_declare_worlds
    expected_stats = {}
    stream = vdm.decision_rng(b.seed, rnd, seat)
    expected = [dpw.sample_pass_world(rnd, seat, stream, expected_stats) for _ in range(worlds)]
    assert [seen[i * outcomes] for i in range(worlds)] == [(h, k) for h, k in expected]
    assert record["pass_worlds"] == {"hazard": dpw.HAZARD, "max_attempts": dpw.MAX_ATTEMPTS,
                                     **expected_stats}
    assert record["pass_worlds"]["worlds"] == record["worlds_completed"] == worlds
    assert b.sampler.rng.getstate() == rng_state


def test_on_decisions_are_legal_and_record_the_counts():
    rows = []

    def check(before, seat, final, choice, record):
        assert choice is None or choice in before.declare_options(seat)
        if record is not None:
            rows.append(record)
    for seed in TAPE_SEEDS:
        drive(seed, bot(), check)
    assert rows and all("pass_worlds" in r for r in rows if r["evaluated"])
    assert all(r["pass_worlds"]["fallbacks"] == 0 for r in rows)


def test_with_the_served_bury_both_passes_draw_pass_conditioned_worlds(monkeypatch):
    """With ``vdsb`` on too, its second pass re-scores the first 16 worlds of
    the SAME pass-conditioned stream (so its worlds stay paired with the
    ordinary pass's); only the ordinary pass's draws are counted."""
    rnd, seat = state_at(*NT_CASE)
    b = bot(value_declare_served_bury=True, value_declare_worlds=24)
    seen = []
    real = vdm.declare_outcome_position

    def spy(r, s, hands, kitty, option, *a, **k):
        seen.append((copy.deepcopy(hands), list(kitty)))
        return real(r, s, hands, kitty, option, *a, **k)
    monkeypatch.setattr(vdm, "declare_outcome_position", spy)
    choice = b.decide_declare(rnd, seat)
    assert choice is None or choice in rnd.declare_options(seat)
    record = b.last_declare_record
    assert record["evaluated"] is True and record["served_bury"]["worlds_completed"] == 16
    assert record["pass_worlds"]["worlds"] == 24
    stream = vdm.decision_rng(b.seed, rnd, seat)
    expected = [dpw.sample_pass_world(rnd, seat, stream) for _ in range(24)]
    outcomes = len(record["outcome_means"])
    ordinary = [seen[i * outcomes] for i in range(24)]
    second = [seen[24 * outcomes + i * 4] for i in range(16)]
    assert ordinary == expected and second == expected[:16]


def test_a_sampler_error_falls_back_to_the_heuristic(monkeypatch):
    rnd, seat = state_at(*NT_CASE)
    b = bot()

    def broken(*a, **k):
        raise vdm.ValueDeclareError("bad world")
    monkeypatch.setattr(dpw, "sample_pass_world", broken)
    assert b.decide_declare(rnd, seat) == HEURISTIC.decide_declare(rnd, seat)
    record = b.last_declare_record
    assert record["evaluated"] is False and record["changed"] is False
    assert (record["fallback_reason"], record["fallback_error"]) == ("error", "ValueDeclareError")
    assert record["pass_worlds"]["worlds"] == 0


def test_a_budget_expiring_while_sampling_falls_back(monkeypatch):
    rnd, seat = state_at(*NT_CASE)
    b = bot(budget=60.0)
    real = dpw.sample_pass_world
    calls = []

    def slow(*a, **k):
        calls.append(1)
        if len(calls) == 2:
            monkeypatch.setattr(pv.time, "perf_counter", lambda: 1e12)
        return real(*a, **k)
    monkeypatch.setattr(dpw, "sample_pass_world", slow)
    assert b.decide_declare(rnd, seat) == HEURISTIC.decide_declare(rnd, seat)
    record = b.last_declare_record
    assert record["evaluated"] is False
    assert (record["fallback_reason"], record["fallback_error"]) == \
        ("hard_budget", "PVSearchBudgetExceeded")


def test_an_interrupt_inside_the_sampler_propagates(monkeypatch):
    rnd, seat = state_at(*NT_CASE)
    b = bot()

    def cancelled(*a, **k):
        raise KeyboardInterrupt("cancelled")
    monkeypatch.setattr(dpw, "sample_pass_world", cancelled)
    with pytest.raises(KeyboardInterrupt):
        b.decide_declare(rnd, seat)


# ------------------------------------------------------------ (f) the served construction

def test_the_served_construction_with_the_flag_on_decides_a_declaration(package):
    path, sha = package
    small = dict(worlds=3, candidates=4, cap=400, batch_size=16)
    b = pv.make_pv_search_bot(path, sha256=sha, seed=5, bury_arm="hybrid", bury_config=BURY,
                              bury_serving_budget_seconds=30, bury_wide_value=True,
                              bury_wide_k=64, value_declare=True, value_declare_worlds=4,
                              value_declare_pass_worlds=True, **small)
    assert isinstance(b, pv.PVSearchBuryBot) and b.value_declare_pass_worlds is True
    rnd, seat = state_at(*NT_CASE)
    choice = b.decide_declare(rnd, seat)
    assert choice is None or choice in rnd.declare_options(seat)
    record = b.last_declare_record
    assert record["evaluated"] is True and record["pass_worlds"]["worlds"] == 4


def test_production_package_pass_worlds_server_smoke(pinned_production_package):
    """The real package through the server's off-loop declare path with the
    rule on: a logged record with the counts, and a legal declaration."""
    import asyncio

    from shengji.api import server as srv
    from shengji.engine.game import Game

    room = srv.Room(code="PKGW")
    room.game = Game(random.Random(91))
    rnd = room.game.start_round()
    while rnd.phase == "deal":
        rnd.deal_next()
    room.seats = [srv.Seat(name=f"Bot {s}", is_bot=True) for s in range(4)]
    events = []
    room.log_event = lambda kind, **data: events.append((kind, data))
    room.bot = pv.make_pv_search_bot(
        str(pinned_production_package), sha256=PACKAGE_SHA,
        worlds=64, candidates=8, cap=4000, batch_size=128,
        serving_budget_seconds=3.0, value_declare=True, value_declare_pass_worlds=True,
        bury_arm="hybrid", bury_wide_value=True, bury_wide_k=64)
    seat = next(s for s in range(4) if rnd.declare_options(s))
    legal = rnd.declare_options(seat)
    assert asyncio.run(srv._bot_declares(room, [seat], final=True))
    record = next(data["record"] for kind, data in events if kind == "declare_decision")
    assert record["evaluated"] is True and record["worlds_completed"] == 64
    assert record["pass_worlds"]["worlds"] == 64 and record["pass_worlds"]["fallbacks"] == 0
    assert record["played"] == vdm.PASS or record["played"].split() in legal

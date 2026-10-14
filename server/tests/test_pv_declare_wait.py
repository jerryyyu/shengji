"""The OPTIONAL wait option of the value declaration (``value_declare_wait``,
``SHENGJI_PV_VALUE_DECLARE_WAIT``, token ``vdw``; #707 S15; `train.declare_wait`):
when the value declaration decides to declare during the deal, NOW and WAIT
are compared on the same silence-consistent worlds of the ordinary stream:
both branches play out the rest of the deal with the other seats declaring by
the heuristic, the bot silent, then the bot's one end-of-deal choice is made
from its own view and scored in the outer world.

Torch-free and package-free (stub predictor and evaluators on the real
engine and the real heuristic), except the served construction, which builds
the bot on the serving test's tiny package.  Witnesses: (a) off: release 45's
name, digest and payload are unchanged, the declare decisions AND records of a
release-45 style bot on seeded deals reproduce the frozen main tape, and the
off record carries no ``wait`` key; (b) the name ``-vdw`` after ``-vdsb``, the
digest and payload move, the env and constructors refuse it without
``value_declare`` or as a non-bool; (c) the world model: on the TRUE deal the
continuation reproduces the engine's own deal and the heuristic's
declarations, the silence filter is exactly "no other seat would declare now",
the end choice samples from the bot's end-of-deal view; (d) paired worlds:
the wait pass's draws are the ordinary pass's own first draws, both branches
of an accepted world share its hands, kitty and inner stream, NOW carries the
bot's declaration, a world whose branches end on one outcome is scored once
and counts for both, no bot RNG moves; (e) the decision rule: the margin, the
grace window and a value PASS never run the pass; (f) budget and error
fallbacks keep the VALUE declaration's choice (not the heuristic's), an
interrupt propagates; (g) the served construction decides a declaration.
The `OptionalStage` contract runs on this stage in
``test_optional_stage_contract.py``.
"""
import copy
import random
from collections import Counter

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.round import HAND_SIZE
from shengji.train import declare_wait as dw
from shengji.train import pv_search_policy as pv
from shengji.train import value_declare as vdm
from test_cwv_leaf_policy_first_trick import BURY, SMALL, CountingPredict
from test_pv_admission_rules import names, production_package  # noqa: F401
from test_pv_declare_served_bury import (OFF_TAPE_SHA256, RELEASE45, KittyEvaluator, fly_env,
                                         tape)
from test_pv_search_serving import package  # noqa: F401
from test_pv_value_declare import NT_CASE, drive, state_at

FLAG = "SHENGJI_PV_VALUE_DECLARE_WAIT"
HEURISTIC = HeuristicBot()
#: release 45 with the rule on
RELEASE45_VDW = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-vdw-r8546b3a6-bury-hybrid-bwv-53ae6cbe55b8"
#: seed 11 after 49 cards: seat 0's heuristic declares DK with nothing standing
WAIT_CASE = (11, 49)


class OtherDeclarerEvaluator:
    """1 for a position whose standing declaration is ANOTHER seat's, else 0:
    waiting (and passing at the end) reaches it whenever another seat declares
    during the rest of the deal; declaring now reaches it only through an
    overcall."""
    backend = "numpy"
    max_batch = 128

    def __init__(self):
        self.calls = 0
        self.scored = 0

    def score(self, positions, seat):
        self.calls += 1
        self.scored += len(positions)
        return np.array([1.0 if p.declaration and p.declaration["seat"] != seat else 0.0
                         for p in positions])


def bot(evaluator=None, *, wait=True, budget=None, seed=17, **rules):
    """A release-45 shaped bot (vd on, the wide chooser on) at test widths."""
    rules.setdefault("value_declare", True)
    if wait:
        rules["value_declare_wait"] = True
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, serving_budget_seconds=budget,
                               **SMALL, **rules)
    return pv.PVSearchBuryBot(CountingPredict(), evaluator=evaluator or KittyEvaluator(),
                              version=2, config=config, checkpoint="/dev/null", seed=seed,
                              bury_arm="hybrid", bury_config=BURY, bury_wide_value=True,
                              bury_wide_k=64)


def heuristic_best(b, monkeypatch):
    """Make the ordinary pass keep the heuristic's declaration (index 0 best)."""
    def means(rnd, seat, candidates, check_budget=None, progress=None, worlds=None,
              buries=None):
        progress["worlds_completed"] = b.value_declare_worlds
        return np.array([1.0] + [0.0] * (len(candidates) - 1))
    monkeypatch.setattr(b, "_value_declare_means", means)


def true_world(rnd):
    """The deal's own complete hands (in deal order) and kitty."""
    hands = [[rnd.deck[i] for i in range(4 * HAND_SIZE) if i % 4 == s] for s in range(4)]
    return hands, list(rnd.deck[4 * HAND_SIZE:])


# ------------------------------------------------------------ (a) off: identity

def test_release45_name_digest_and_payload_unchanged_when_off(production_package):
    env = fly_env()
    assert names(env) == [RELEASE45]
    for raw in ("0", ""):
        assert names({**env, FLAG: raw}) == [RELEASE45]
    recipe = pv.pv_env_recipe(env)
    assert "value_declare_wait" not in recipe
    config = pv.PVSearchConfig(checkpoint_sha256=recipe["sha256"], worlds=64, candidates=8,
                               cap=4000, batch_size=128, serving_budget_seconds=3.0,
                               admission_diversity=True, refusal_constraints=True,
                               tiebreak_points=True, lead_anchor=True,
                               doomed_throw_reselect=True, value_declare=True)
    assert pv.recipe_digest(config) == "add86676"
    assert not any("wait" in key for key in pv.recipe_payload(config))
    assert pv.PVSearchBot.value_declare_wait is False


def test_off_declare_decisions_and_records_match_the_main_tape():
    assert tape(lambda: bot(wait=False)) == OFF_TAPE_SHA256


def test_off_bot_state_and_record_carry_nothing_new():
    b = bot(wait=False)
    assert "value_declare_wait" not in vars(b)
    rnd, seat = state_at(*NT_CASE)
    b.decide_declare(rnd, seat)
    assert "wait" not in b.last_declare_record


# ------------------------------------------------------------ (b) name, digest, refusals

def test_the_token_the_digest_and_the_payload_when_on(production_package):
    env = fly_env()
    on, = names({**env, FLAG: "1"})
    assert on == RELEASE45_VDW
    tokens = [token for _, token in pv.RULE_TOKENS]
    assert tokens.index("vdw") == tokens.index("vdpw") + 1 == tokens.index("asap") - 1
    assert pv.RULE_FLAGS["VALUE_DECLARE_WAIT"] == "value_declare_wait"
    both, = names({**env, FLAG: "1", "SHENGJI_PV_VALUE_DECLARE_SERVED_BURY": "1"})
    assert "-vd-vdsb-vdw-r" in both
    pw, = names({**env, FLAG: "1", "SHENGJI_PV_VALUE_DECLARE_PASS_WORLDS": "1"})
    assert "-vd-vdpw-vdw-r" in pw
    three, = names({**env, FLAG: "1", "SHENGJI_PV_VALUE_DECLARE_PASS_WORLDS": "1",
                    "SHENGJI_PV_VALUE_DECLARE_SERVED_BURY": "1"})
    assert "-vd-vdsb-vdpw-vdw-r" in three
    every, = names({**env, FLAG: "1", "SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST": "1"})
    assert "-vd-vdef-vdw-r" in every
    lpft, = names({**env, FLAG: "1", "SHENGJI_PV_LEAF_POLICY_FIRST_TRICK": "1"})
    assert "-vd-vdw-lpft-r" in lpft
    vd = pv.PVSearchConfig(checkpoint_sha256="f" * 64, value_declare=True)
    vdw = pv.PVSearchConfig(checkpoint_sha256="f" * 64, value_declare=True,
                            value_declare_wait=True)
    payload = pv.recipe_payload(vdw)
    assert payload["value_declare_wait"] is True
    assert payload["value_declare_model"] == vdm.MODEL     # the ordinary pass is unchanged
    assert (payload["value_declare_wait_model"], payload["value_declare_wait_worlds"],
            payload["value_declare_wait_inner_worlds"]) == (dw.MODEL, 32, 8)
    assert pv.recipe_digest(vdw) != pv.recipe_digest(vd)


@pytest.mark.parametrize("env,match", [
    ({FLAG: "2"}, "must be 0 or 1"),
    ({FLAG: "yes"}, "must be 0 or 1"),
    ({FLAG: "1", "SHENGJI_PV_VALUE_DECLARE": "0"}, "requires value_declare"),
])
def test_env_refuses_bad_values_and_a_rule_with_no_effect(production_package, env, match):
    with pytest.raises(pv.PVSearchPolicyError, match=match):
        names({**fly_env(), **env})


def test_constructors_refuse_a_rule_with_no_effect(package):
    with pytest.raises(pv.PVSearchPolicyError, match="requires value_declare"):
        bot(value_declare=False)
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, **SMALL, value_declare_wait=True)
    with pytest.raises(pv.PVSearchPolicyError, match="requires value_declare"):
        pv.PVSearchBot(CountingPredict(), evaluator=KittyEvaluator(), version=2,
                       config=config, checkpoint="/dev/null")
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, value_declare=True,
                                            value_declare_wait=1))
    path, sha = package
    with pytest.raises(pv.PVSearchPolicyError, match="requires value_declare"):
        pv.make_pv_search_bot(path, sha256=sha, value_declare_wait=True, worlds=3)


# ------------------------------------------------------------ (c) the world model

@pytest.mark.parametrize("seed,dealt", [(3, 30), (11, 49), (22, 81), (7, 99)])
def test_the_continuation_on_the_true_deal_is_the_engines_own(seed, dealt):
    rnd, seat = state_at(seed, dealt)
    hands, kitty = true_world(rnd)
    sim = dw.continuation_round(rnd, seat, hands, kitty)
    assert sim.hands == rnd.hands and sim.declaration == rnd.declaration
    dw.play_out_deal(sim, seat)
    # the engine, continued with the heuristic at every other seat, the decider silent
    real = copy.deepcopy(rnd)
    while real.phase == "deal":
        receiver, _, _ = real.deal_next()
        if receiver != seat:
            choice = HEURISTIC.decide_declare(real, receiver)
            if choice:
                real.declare(receiver, choice)
    assert sim.hands == real.hands and sim.phase == real.phase == "declare"
    assert sim.declaration == real.declaration


def test_continuation_never_mutates_the_round_and_refuses_a_foreign_hand():
    rnd, seat = state_at(*NT_CASE)
    before = copy.deepcopy(rnd)
    hands, kitty = vdm.sample_declare_world(rnd, seat, random.Random(1))
    sim = dw.continuation_round(rnd, seat, hands, kitty)
    dw.play_out_deal(sim, seat)
    assert rnd.hands == before.hands and rnd.declaration == before.declaration
    assert rnd._deal_pos == before._deal_pos and rnd.phase == before.phase
    swapped = [list(h) for h in hands]
    swapped[seat], swapped[(seat + 1) % 4] = swapped[(seat + 1) % 4], swapped[seat]
    with pytest.raises(vdm.ValueDeclareError):
        dw.continuation_round(rnd, seat, swapped, kitty)


def test_the_silence_filter_is_exactly_no_other_seat_would_declare_now():
    rnd, seat = state_at(9, 89)      # late in the deal: many worlds fail the filter
    rng = random.Random(5)
    seen = {True: 0, False: 0}
    for _ in range(64):
        hands, kitty = vdm.sample_declare_world(rnd, seat, rng)
        sim = dw.continuation_round(rnd, seat, hands, kitty)
        expected = all(HEURISTIC.decide_declare(sim, s) is None for s in range(4) if s != seat)
        assert dw.silence_consistent(sim, seat) is expected
        seen[expected] += 1
    assert seen[True] and seen[False]


def test_the_end_choice_samples_from_the_bots_own_end_of_deal_view(monkeypatch):
    rnd, seat = state_at(*WAIT_CASE)
    hands, kitty = true_world(rnd)
    sim = dw.continuation_round(rnd, seat, hands, kitty)
    dw.play_out_deal(sim, seat)
    b = bot(OtherDeclarerEvaluator())
    views = []
    real = vdm.sample_declare_world

    def spy(r, s, rng):
        assert r is sim and s == seat
        views.append((len(r.hands[s]), r.phase))
        world = real(r, s, rng)
        assert world[0][seat] == sim.hands[seat]      # its own 25 cards, nothing else pinned
        return world
    monkeypatch.setattr(vdm, "sample_declare_world", spy)
    outcomes = dw.end_candidates(sim, seat)
    choice, scored = b._declare_wait_end_choice(sim, seat, random.Random(3), None, None)
    if len(outcomes) == 1:
        assert (choice, scored, views) == (outcomes[0][1], False, [])
        return
    assert scored is True and views == [(HAND_SIZE, "declare")] * dw.INNER_WORLDS_DEFAULT
    assert outcomes[0][1] is None                      # PASS first
    assert choice in [option for _, option in outcomes]


# ------------------------------------------------------------ (d) paired worlds

def test_the_wait_pass_draws_the_ordinary_streams_worlds_and_pairs_its_branches(monkeypatch):
    rnd, seat = state_at(*WAIT_CASE)
    b = bot(OtherDeclarerEvaluator())
    now = HEURISTIC.decide_declare(rnd, seat)
    assert now is not None and rnd.declaration is None
    outer, built, played, inner = [], [], [], []
    sample, cont, play, irng = (vdm.sample_declare_world, dw.continuation_round,
                                dw.play_out_deal, dw.inner_rng)

    def spy_sample(r, s, rng):
        world = sample(r, s, rng)
        if r is rnd:
            outer.append(world)
        return world

    def spy_cont(r, s, hands, kitty):
        built.append((id(hands), id(kitty)))
        return cont(r, s, hands, kitty)

    def spy_play(sim, s):
        played.append((copy.deepcopy(sim.declaration), [list(h) for h in sim.hands]))
        return play(sim, s)

    def spy_inner(seed, r, s, world):
        inner.append(world)
        return irng(seed, r, s, world)
    monkeypatch.setattr(vdm, "sample_declare_world", spy_sample)
    monkeypatch.setattr(dw, "continuation_round", spy_cont)
    monkeypatch.setattr(dw, "play_out_deal", spy_play)
    monkeypatch.setattr(dw, "inner_rng", spy_inner)
    rng_state = b.sampler.rng.getstate()
    played_now, record = b._declare_wait_decision(rnd, seat, now, None)
    assert record["evaluated"] is True
    accepted, draws = record["worlds_accepted"], record["draws"]
    assert accepted == dw.WORLDS_DEFAULT and record["worlds_completed"] == accepted
    assert draws == len(outer) >= accepted
    # the outer draws are the ordinary pass's own first draws
    ref = vdm.decision_rng(b.seed, rnd, seat)
    assert outer == [sample(rnd, seat, ref) for _ in range(draws)]
    # one filter build per draw, then two branch builds per accepted world, all
    # on that draw's hands and kitty
    assert len(built) == draws + 2 * accepted and len(played) == 2 * accepted
    uses = Counter(built)
    assert sorted(uses.values()) == [1] * (draws - accepted) + [3] * accepted
    assert all(built[i] == built[i + 1] == built[i + 2]
               for i in range(len(built)) if uses[built[i]] == 3 and built[i] != built[i - 1])
    for k in range(accepted):
        (now_decl, now_hands), (wait_decl, wait_hands) = played[2 * k], played[2 * k + 1]
        assert now_hands == wait_hands                 # the same world, the same dealt prefix
        assert now_decl == {"seat": seat, "cards": list(now),
                            "strength": rnd._declaration_strength(list(now))}
        assert wait_decl is None                       # nothing stood; the bot stayed silent
    # both branches of world k use world k's inner stream
    assert inner == [k for k in range(accepted) for _ in range(2)]
    assert b.sampler.rng.getstate() == rng_state and b.last_bury_record is None


def test_a_world_ending_on_one_outcome_is_scored_once_and_counts_for_both(monkeypatch):
    rnd, seat = state_at(*WAIT_CASE)
    evaluator = KittyEvaluator()
    b = bot(evaluator)
    now = HEURISTIC.decide_declare(rnd, seat)
    monkeypatch.setattr(dw, "play_out_deal", lambda sim, s: 0)

    def end(sim, s, rng, leaf, check):
        # NOW keeps its declaration; WAIT declares the same combo at the end
        return (None if sim.declaration else list(now)), False
    monkeypatch.setattr(b, "_declare_wait_end_choice", end)
    _, record = b._declare_wait_decision(rnd, seat, now, None)
    assert record["same_outcome_worlds"] == record["worlds_accepted"] == dw.WORLDS_DEFAULT
    assert record["now_mean"] == record["wait_mean"] and record["waited"] is False
    assert len(evaluator.scored) == dw.WORLDS_DEFAULT


def test_no_consistent_world_abandons_to_the_value_choice(monkeypatch):
    rnd, seat = state_at(*WAIT_CASE)
    b = bot(OtherDeclarerEvaluator())
    now = HEURISTIC.decide_declare(rnd, seat)
    monkeypatch.setattr(dw, "silence_consistent", lambda sim, s: False)
    played, record = b._declare_wait_decision(rnd, seat, now, None)
    assert played == now and record["evaluated"] is False and record["waited"] is False
    assert (record["fallback_reason"], record["fallback_error"]) == ("error", "ValueDeclareError")
    assert record["draws"] == dw.DRAWS_CAP and record["worlds_accepted"] == 0


# ------------------------------------------------------------ (e) the decision rule

@pytest.mark.parametrize("values,margin,waited", [
    ([0.2, 0.3], 0.0, True),
    ([0.3, 0.2], 0.0, False),
    ([0.2, 0.2], 0.0, False),           # an exact tie declares now
    ([0.2, 0.3], 0.15, False),          # the margin binds
])
def test_wait_beats_now_only_past_the_margin(monkeypatch, values, margin, waited):
    rnd, seat = state_at(*NT_CASE)
    b = bot(value_declare_margin=margin)
    heuristic_best(b, monkeypatch)

    def means(r, s, now, check_budget=None, progress=None):
        assert check_budget is None and list(now) == HEURISTIC.decide_declare(rnd, seat)
        return np.array(values)
    monkeypatch.setattr(b, "_declare_wait_values", means)
    heuristic = HEURISTIC.decide_declare(rnd, seat)
    choice = b.decide_declare(rnd, seat)
    record = b.last_declare_record
    assert choice == (None if waited else heuristic)
    assert record["value_choice"] == " ".join(heuristic)
    assert record["played"] == (vdm.PASS if waited else " ".join(heuristic))
    assert record["changed"] is waited
    assert record["wait"]["waited"] is waited
    assert (record["wait"]["now_mean"], record["wait"]["wait_mean"]) == tuple(values)


def test_the_grace_window_and_a_value_pass_never_run_the_wait_pass(monkeypatch):
    rnd, seat = state_at(*NT_CASE)
    b = bot()
    monkeypatch.setattr(b, "_declare_wait_values",
                        lambda *a, **k: pytest.fail("the wait pass ran"))
    b.decide_declare(copy.deepcopy(rnd), seat, final=True)
    assert b.last_declare_record["wait"] is None

    def pass_best(r, s, candidates, check_budget=None, progress=None, worlds=None,
                  buries=None):
        return np.array([1.0 if c is None else 0.0 for c in candidates])
    monkeypatch.setattr(b, "_value_declare_means", pass_best)
    assert b.decide_declare(copy.deepcopy(rnd), seat) is None
    assert b.last_declare_record["played"] == vdm.PASS and b.last_declare_record["wait"] is None


@pytest.mark.parametrize("seed", [0, 11])
def test_on_returns_legal_choices_keeps_the_gate_and_waits_only_mid_deal(seed):
    b = bot()
    seen = []

    def check(before, seat, final, choice, record):
        options = before.declare_options(seat)
        heuristic = HEURISTIC.decide_declare(before, seat, final=final)
        assert choice is None or choice in options
        assert (record is not None) == (bool(options) and (final or heuristic is not None))
        if record is None:
            return
        wait = record["wait"]
        if final or record["value_choice"] == vdm.PASS:
            assert wait is None
            return
        seen.append(wait)
        assert wait["evaluated"] is True and wait["now"] == record["value_choice"]
        assert choice is None if wait["waited"] else choice == wait["now"].split()

    drive(seed, b, check)
    assert seen


# ------------------------------------------------------------ (f) fallbacks

def test_a_budget_expiring_inside_the_wait_pass_keeps_the_value_choice(monkeypatch):
    rnd, seat = state_at(*NT_CASE)
    b = bot(budget=60.0)
    heuristic_best(b, monkeypatch)
    real = dw.play_out_deal

    def slow(sim, s):
        monkeypatch.setattr(pv.time, "perf_counter", lambda: 1e12)
        return real(sim, s)
    monkeypatch.setattr(dw, "play_out_deal", slow)
    heuristic = HEURISTIC.decide_declare(rnd, seat)
    assert b.decide_declare(rnd, seat) == heuristic
    record = b.last_declare_record
    assert record["evaluated"] is True and record["fallback_reason"] is None
    wait = record["wait"]
    assert wait["evaluated"] is False and wait["waited"] is False
    assert (wait["fallback_reason"], wait["fallback_error"]) == \
        ("hard_budget", "PVSearchBudgetExceeded")


def test_the_value_choice_not_the_heuristics_survives_a_wait_error(monkeypatch):
    rnd, seat = state_at(*NT_CASE)
    b = bot()
    options = rnd.declare_options(seat)
    heuristic = HEURISTIC.decide_declare(rnd, seat)
    outcomes = vdm.candidate_outcomes(rnd, seat, options, heuristic)
    other = next(i for i, (_, o) in enumerate(outcomes) if o is not None and o != heuristic)

    def means(r, s, candidates, check_budget=None, progress=None, worlds=None, buries=None):
        return np.array([1.0 if i == other else 0.0 for i in range(len(candidates))])
    monkeypatch.setattr(b, "_value_declare_means", means)
    def boom(sim, s):
        raise RuntimeError("boom")
    monkeypatch.setattr(dw, "play_out_deal", boom)
    choice = b.decide_declare(rnd, seat)
    assert choice == list(outcomes[other][1]) != heuristic
    wait = b.last_declare_record["wait"]
    assert (wait["fallback_reason"], wait["fallback_error"]) == ("error", "RuntimeError")


def test_an_interrupt_inside_the_wait_pass_propagates(monkeypatch):
    rnd, seat = state_at(*NT_CASE)
    b = bot()
    heuristic_best(b, monkeypatch)

    def cancelled(*a, **k):
        raise KeyboardInterrupt("cancelled")
    monkeypatch.setattr(dw, "play_out_deal", cancelled)
    with pytest.raises(KeyboardInterrupt):
        b.decide_declare(rnd, seat)


def test_a_head_preferring_another_seats_declaration_waits():
    rnd, seat = state_at(*WAIT_CASE)
    b = bot(OtherDeclarerEvaluator())
    now = HEURISTIC.decide_declare(rnd, seat)
    played, record = b._declare_wait_decision(rnd, seat, now, None)
    assert record["now_mean"] < record["wait_mean"]
    assert played is None and record["waited"] is True


# ------------------------------------------------------------ (g) the served construction

def test_the_served_construction_with_the_flag_on_decides_a_declaration(package):
    path, sha = package
    small = dict(worlds=3, candidates=4, cap=400, batch_size=16)
    b = pv.make_pv_search_bot(path, sha256=sha, seed=5, value_declare=True,
                              value_declare_worlds=4, value_declare_wait=True, **small)
    assert b.value_declare_wait is True
    rnd, seat = state_at(*WAIT_CASE)
    choice = b.decide_declare(rnd, seat)
    assert choice is None or choice in rnd.declare_options(seat)
    wait = b.last_declare_record["wait"]
    assert wait is None or wait["evaluated"] is True

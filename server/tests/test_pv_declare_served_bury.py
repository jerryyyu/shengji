"""The OPTIONAL served bury inside the value declaration's worlds
(``value_declare_served_bury``, ``SHENGJI_PV_VALUE_DECLARE_SERVED_BURY``,
token ``vdsb``; #707 S15(2); `train.declare_served_bury`): the ordinary
value-declare pass nominates one challenger, and the heuristic's outcome and
the challenger are re-scored on the first 16 worlds of the same stream with
the world banker burying by the served wide value-only chooser (16 candidates
x 8 banker-view worlds) and compared by the control-variate means.

Torch-free and package-free (stub predictor and evaluators on the real
engine, the real heuristic, the real ballot, the real sampler and the real
leaves), except the served construction, which builds the served bot on the
serving test's tiny package.  Witnesses: (a) off: release 45's name, digest
and payload are unchanged, the declare decisions AND records of a release-45
style bot on seeded deals are byte-identical to a tape taken on main before
this change, and the flag-off record has no ``served_bury`` key; (b) the
name: ``-vdsb`` after ``-vd``/``-vdef``, the digest and the payload move, the
env and the constructors refuse the rule without ``value_declare`` or the
wide chooser; (c) on: every bury the second pass's world banker makes is the
SERVED chooser's (the bot's own `_decide_bury` at the reduced width on the
same bury-phase world), the scored positions carry it, the worlds are the
first 16 of the ordinary stream, no bot RNG or bury record moves; (d) the
decision rule: the challenger, the control-variate means, the margin, ties
and the single-outcome skip; (e) a budget expiry or an error inside the
served pass falls back to the heuristic declaration; (f) the served
construction with the flag on builds a bot that decides a declaration.
"""
import copy
import hashlib
import json

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.train import cwv_bury_policy as bury_policy
from shengji.train import declare_served_bury as dsb
from shengji.train import pv_search_policy as pv
from shengji.train import value_declare as vdm
from shengji.train.policy_prior import CARD_INDEX
from test_cwv_leaf_policy_first_trick import BURY, SMALL, CountingPredict
from test_pv_admission_rules import names, production_package  # noqa: F401
from test_pv_search_serving import package  # noqa: F401
from test_pv_value_declare import NT_CASE, drive, state_at

FLAG = "SHENGJI_PV_VALUE_DECLARE_SERVED_BURY"
HEURISTIC = HeuristicBot()
#: production (fly.toml): release 45
RELEASE45 = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-radd86676-bury-hybrid-bwv-7a73e8fbf1a8"
#: release 45 with the rule on
RELEASE45_VDSB = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-vdsb-re3dffedd-bury-hybrid-bwv-795be79f52eb"
#: sha256 of `tape()` taken on main at d1f0e9d4 (before this rule): the
#: flag-off declare decisions and records must reproduce it byte for byte
OFF_TAPE_SHA256 = "c30a9691b5b81f7eff259fe6a5ada0523436556c2c8420091d70219bff54960a"
TAPE_SEEDS = (0, 3, 5, 22)


def fly_env():
    import tomllib
    from pathlib import Path
    env = tomllib.loads((Path(__file__).parents[2] / "fly.toml").read_text())["env"]
    # production is release 46 (release 45 + the SHENGJI_PV_EXACT_* search, #1039); the
    # release-45 base is the documented rollback, the env without those six lines
    assert env["SHENGJI_BOT"].startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-ele-")
    return {k: v for k, v in env.items() if not k.startswith("SHENGJI_PV_EXACT_")}


class KittyEvaluator:
    """A deterministic value head that sees the first trick, the buried cards,
    the trump and the scoring seat (so the bury, the declaration and the
    perspective all move it).  Counts calls and remembers each scored
    position's ``(banker, buried)``; no deep copies."""
    backend = "numpy"
    max_batch = 128

    def __init__(self):
        self.calls = 0
        self.scored = []

    def score(self, positions, seat):
        self.calls += 1
        out = []
        for p in positions:
            self.scored.append((p.banker, tuple(sorted(p.buried))))
            trick = sum(CARD_INDEX[c] for play in p.history[0].plays for c in play.cards)
            buried = sum(CARD_INDEX[c] * (i + 1) for i, c in enumerate(sorted(p.buried)))
            trump = 5 if p.trump_is_nt else "SHDC".index(p.trump_suit) if p.trump_suit else 6
            raw = (trick * 7 + buried * 3 + trump * 11 + p.banker * 13) % 101
            sign = 1.0 if (p.banker - seat) % 2 == 0 else -1.0
            out.append(sign * (raw / 101.0 - 0.5))
        return np.array(out)


class RaisingAfter(KittyEvaluator):
    """Raises on the ``on``-th call."""

    def __init__(self, on):
        super().__init__()
        self.on = on

    def score(self, positions, seat):
        if self.calls + 1 >= self.on:
            self.calls += 1
            raise RuntimeError("value head failed")
        return super().score(positions, seat)


def bot(evaluator=None, *, served=True, wide=True, arm="hybrid", budget=None, seed=17,
        **rules):
    """A release-45 shaped bot (vd on, the wide chooser on) at test widths."""
    rules.setdefault("value_declare", True)
    if served:
        rules["value_declare_served_bury"] = True
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, serving_budget_seconds=budget,
                               **SMALL, **rules)
    extra = {"bury_wide_value": True, "bury_wide_k": 64} if wide else {}
    return pv.PVSearchBuryBot(CountingPredict(), evaluator=evaluator or KittyEvaluator(),
                              version=2, config=config, checkpoint="/dev/null", seed=seed,
                              bury_arm=arm, bury_config=BURY, **extra)


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
    assert "value_declare_served_bury" not in recipe
    config = pv.PVSearchConfig(checkpoint_sha256=recipe["sha256"], worlds=64, candidates=8,
                               cap=4000, batch_size=128, serving_budget_seconds=3.0,
                               admission_diversity=True, refusal_constraints=True,
                               tiebreak_points=True, lead_anchor=True,
                               doomed_throw_reselect=True, value_declare=True)
    assert pv.recipe_digest(config) == "add86676"
    payload = pv.recipe_payload(config)
    assert not any("served_bury" in key for key in payload)
    assert payload["value_declare_model"] == vdm.MODEL
    assert pv.PVSearchBot.value_declare_served_bury is False


def test_off_declare_decisions_and_records_match_the_main_tape():
    assert tape(lambda: bot(served=False)) == OFF_TAPE_SHA256


def test_off_bot_state_and_record_carry_nothing_new():
    b = bot(served=False)
    assert "value_declare_served_bury" not in vars(b)
    rnd, seat = state_at(*NT_CASE)
    b.decide_declare(rnd, seat)
    assert "served_bury" not in b.last_declare_record


# ------------------------------------------------------------ (b) name, digest, refusals

def test_the_token_the_digest_and_the_payload_when_on(production_package):
    env = fly_env()
    on, = names({**env, FLAG: "1"})
    assert on == RELEASE45_VDSB
    assert on.startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-vdsb-r")
    assert on.endswith(RELEASE45_VDSB[-len("-bury-hybrid-bwv-795be79f52eb"):])
    tokens = [token for _, token in pv.RULE_TOKENS]
    assert tokens.index("vdsb") == tokens.index("vdef") + 1 == tokens.index("vdpw") - 1
    assert pv.RULE_FLAGS["VALUE_DECLARE_SERVED_BURY"] == "value_declare_served_bury"
    every, = names({**env, FLAG: "1", "SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST": "1"})
    assert "-vd-vdef-vdsb-r" in every
    lpft, = names({**env, FLAG: "1", "SHENGJI_PV_LEAF_POLICY_FIRST_TRICK": "1"})
    assert "-vd-vdsb-lpft-r" in lpft
    vd = pv.PVSearchConfig(checkpoint_sha256="f" * 64, value_declare=True)
    sb = pv.PVSearchConfig(checkpoint_sha256="f" * 64, value_declare=True,
                           value_declare_served_bury=True)
    payload = pv.recipe_payload(sb)
    assert payload["value_declare_served_bury"] is True
    assert payload["value_declare_model"] == vdm.MODEL.replace("heuristic-bury",
                                                               "served-wide-value-bury")
    assert (payload["value_declare_served_bury_k"],
            payload["value_declare_served_bury_model_worlds"],
            payload["value_declare_served_bury_worlds"],
            payload["value_declare_served_bury_outcomes"]) == (16, 8, 16, 2)
    assert pv.recipe_digest(sb) != pv.recipe_digest(vd)
    both = pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, value_declare=True,
                                               value_declare_served_bury=True,
                                               leaf_policy_first_trick=True))
    assert both["value_declare_model"] == ("uniform-unseen|no-counter-declare|"
                                           "served-wide-value-bury|policy-first-trick|"
                                           "value-head-seat-team")


@pytest.mark.parametrize("env,match", [
    ({FLAG: "2"}, "must be 0 or 1"),
    ({FLAG: "1", "SHENGJI_PV_VALUE_DECLARE": "0"}, "requires value_declare"),
    ({FLAG: "1", "SHENGJI_PV_BURY_WIDE_VALUE": "", "SHENGJI_PV_BURY_WIDE_K": ""},
     "needs the served wide"),
    ({FLAG: "1", "SHENGJI_PV_BURY_ARM": "", "SHENGJI_PV_BURY_WIDE_VALUE": "",
      "SHENGJI_PV_BURY_WIDE_K": ""}, "needs the served wide"),
])
def test_env_refuses_bad_values_and_a_rule_with_no_effect(production_package, env, match):
    with pytest.raises(pv.PVSearchPolicyError, match=match):
        names({**fly_env(), **env})


def test_constructors_refuse_a_rule_with_no_effect():
    with pytest.raises(pv.PVSearchPolicyError, match="requires value_declare"):
        bot(value_declare=False)
    with pytest.raises(pv.PVSearchPolicyError, match="needs the served wide"):
        bot(wide=False)
    with pytest.raises(pv.PVSearchPolicyError, match="needs the served wide"):
        bot(wide=False, arm="heuristic")
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, **SMALL, value_declare=True,
                               value_declare_served_bury=True)
    with pytest.raises(pv.PVSearchPolicyError, match="needs the served wide"):
        pv.PVSearchBot(CountingPredict(), evaluator=KittyEvaluator(), version=2,
                       config=config, checkpoint="/dev/null")
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, value_declare=True,
                                            value_declare_served_bury=1))


# ------------------------------------------------------------ (c) on: the served bury is used

def test_every_second_pass_bury_is_the_served_choosers(monkeypatch):
    rnd, seat = state_at(*NT_CASE)
    evaluator = KittyEvaluator()
    b = bot(evaluator)
    # the reference: the bot's OWN served chooser (`PVSearchBuryBot._decide_bury`,
    # the wide value-only path release 45 serves) at the declare pass's width
    reference = bot(KittyEvaluator(), served=False)
    reference.bury_wide_k = dsb.K_DEFAULT
    reference.bury_config = bury_policy.CWVBuryConfig(
        max_candidates=BURY.max_candidates, model_worlds=dsb.MODEL_WORLDS_DEFAULT,
        selection_worlds=BURY.selection_worlds, alternatives=BURY.alternatives)
    real = dsb.served_bury
    calls = []

    def spy(owner, world, banker, **kw):
        assert owner is b and world.phase == "bury" and world.banker == banker
        assert len(world.hands[banker]) == 33
        assert (kw["k"], kw["model_worlds"]) == (dsb.K_DEFAULT, dsb.MODEL_WORLDS_DEFAULT)
        expected = reference._decide_bury(copy.deepcopy(world), banker)
        chosen = real(owner, world, banker, **kw)
        assert chosen == expected
        calls.append((banker, tuple(sorted(chosen)),
                      tuple(sorted(HEURISTIC.decide_bury(copy.deepcopy(world), banker)))))
        return chosen

    monkeypatch.setattr(dsb, "served_bury", spy)
    rng_state = b.sampler.rng.getstate()
    b.decide_declare(rnd, seat)
    record = b.last_declare_record
    assert record["evaluated"] is True
    served = record["served_bury"]
    assert served["challenger"] is not None
    assert served["worlds_completed"] == dsb.WORLDS_DEFAULT
    # one served bury per (second-pass world, competing outcome)
    assert len(calls) == dsb.WORLDS_DEFAULT * dsb.OUTCOMES
    # it is not the heuristic bury (the evaluator rewards other kitties)
    assert any(chosen != heuristic for _, chosen, heuristic in calls)
    # the positions scored by the second pass carry the served buries
    scored = set(evaluator.scored)
    assert all((banker, chosen) in scored for banker, chosen, _ in calls)
    # no bot stream and no bury record moved
    assert b.sampler.rng.getstate() == rng_state
    assert b.last_bury_record is None


def test_the_second_pass_worlds_are_the_first_of_the_ordinary_stream(monkeypatch):
    rnd, seat = state_at(*NT_CASE)
    b = bot()
    drawn = []
    real = vdm.sample_declare_world

    def spy(r, s, rng):
        hands, kitty = real(r, s, rng)
        drawn.append((copy.deepcopy(hands), list(kitty)))
        return hands, kitty
    monkeypatch.setattr(vdm, "sample_declare_world", spy)
    b.decide_declare(rnd, seat)
    ordinary, second = drawn[:b.value_declare_worlds], drawn[b.value_declare_worlds:]
    assert len(second) == dsb.WORLDS_DEFAULT
    assert second == ordinary[:dsb.WORLDS_DEFAULT]


@pytest.mark.parametrize("seed", [0, 3])
def test_on_returns_legal_choices_and_keeps_the_gate(seed):
    b = bot()
    seen = []

    def check(before, seat, final, choice, record):
        options = before.declare_options(seat)
        heuristic = HEURISTIC.decide_declare(before, seat, final=final)
        assert choice is None or choice in options
        admitted = bool(options) and (final or heuristic is not None)
        assert (record is not None) == admitted
        if record is None:
            assert choice == heuristic
            return
        seen.append(record)
        assert record["evaluated"] is True and set(record["served_bury"]) == {
            "ordinary_choice", "challenger", "k", "model_worlds", "worlds",
            "worlds_completed", "heuristic_bury_means", "served_bury_means",
            "adjusted_means", "seconds"}
        assert record["played"] in (record["heuristic"], record["served_bury"]["challenger"])

    drive(seed, b, check)
    assert seen


# ------------------------------------------------------------ (d) the decision rule

def fake_means(ordinary, twin):
    def means(rnd, seat, candidates, check_budget=None, progress=None, worlds=None,
              buries=None):
        if buries is None:
            assert worlds is None and len(candidates) == len(ordinary)
            return np.array(ordinary, dtype=float)
        assert worlds == dsb.WORLDS_DEFAULT and len(candidates) == 4
        assert buries[:2] == [None, None] and all(callable(f) for f in buries[2:])
        assert candidates[:2] == candidates[2:]
        progress["worlds_completed"] = worlds
        return np.array(twin, dtype=float)
    return means


@pytest.mark.parametrize("ordinary,twin,switch,best", [
    # the challenger is the best non-heuristic outcome by the ordinary means
    ([0.0, 0.3, 0.2], [0.1, 0.1, 0.1, 0.5], True, 0.7),
    # served bury reverses the ordinary preference
    ([0.0, 0.3, 0.2], [0.1, 0.1, 0.6, 0.1], False, 0.5),
    # the ordinary pass kept the heuristic; the served bury switches to the runner-up
    ([0.5, 0.3, 0.4], [0.0, 0.0, 0.0, 0.3], True, 0.7),
    # an exact tie keeps the heuristic
    ([0.0, 0.3], [0.0, 0.0, 0.3, 0.0], False, 0.3),
])
def test_control_variate_means_and_the_margin(monkeypatch, ordinary, twin, switch, best):
    rnd, seat = state_at(*NT_CASE)
    b = bot()
    outcomes = vdm.candidate_outcomes(rnd, seat, rnd.declare_options(seat),
                                      HEURISTIC.decide_declare(rnd, seat))
    ordinary = (ordinary + [-1.0] * len(outcomes))[:len(outcomes)]
    monkeypatch.setattr(b, "_value_declare_means", fake_means(ordinary, twin))
    choice = b.decide_declare(rnd, seat)
    record = b.last_declare_record
    served = record["served_bury"]
    challenger = max(range(1, len(outcomes)), key=lambda i: (ordinary[i], -i))
    expected = [ordinary[0] + twin[2] - twin[0], ordinary[challenger] + twin[3] - twin[1]]
    assert served["adjusted_means"] == pytest.approx(expected)
    assert record["heuristic_mean"] == pytest.approx(expected[0])
    assert record["best_mean"] == pytest.approx(best)
    assert record["outcome_means"] == pytest.approx(ordinary)
    heuristic = HEURISTIC.decide_declare(rnd, seat)
    want = outcomes[challenger][1] if switch else heuristic
    assert choice == (None if want is None else list(want))
    assert record["changed"] is switch
    # a margin above the adjusted gap keeps the heuristic
    if switch:
        m = bot(value_declare_margin=expected[1] - expected[0] + 0.01)
        monkeypatch.setattr(m, "_value_declare_means", fake_means(ordinary, twin))
        assert m.decide_declare(rnd, seat) == heuristic


def test_a_single_outcome_needs_no_second_pass(monkeypatch):
    rnd, seat = state_at(*NT_CASE)
    b = bot()
    monkeypatch.setattr(vdm, "candidate_outcomes",
                        lambda r, s, o, h: [(vdm.outcome_key(r, s, h), h)])
    called = []
    monkeypatch.setattr(dsb, "served_bury", lambda *a, **k: called.append(1))
    assert b.decide_declare(rnd, seat) == HEURISTIC.decide_declare(rnd, seat)
    served = b.last_declare_record["served_bury"]
    assert served["challenger"] is None and served["worlds_completed"] == 0
    assert not called


# ------------------------------------------------------------ (e) fallbacks

def test_an_error_inside_the_served_pass_falls_back_to_the_heuristic():
    rnd, seat = state_at(*NT_CASE)
    off = KittyEvaluator()
    bot(off, served=False).decide_declare(copy.deepcopy(rnd), seat)
    # the ordinary pass makes ``off.calls`` value calls; the next is the served pass's
    evaluator = RaisingAfter(on=off.calls + 1)
    b = bot(evaluator)
    assert b.decide_declare(rnd, seat) == HEURISTIC.decide_declare(rnd, seat)
    record = b.last_declare_record
    assert record["evaluated"] is False and record["changed"] is False
    assert (record["fallback_reason"], record["fallback_error"]) == ("error", "RuntimeError")


def test_a_budget_expiring_inside_the_served_pass_falls_back(monkeypatch):
    rnd, seat = state_at(*NT_CASE)
    b = bot(budget=60.0)
    real = dsb.served_bury

    def slow(owner, world, banker, check_budget=None, **kw):
        assert check_budget is not None
        monkeypatch.setattr(pv.time, "perf_counter", lambda: 1e12)
        return real(owner, world, banker, check_budget=check_budget, **kw)
    monkeypatch.setattr(dsb, "served_bury", slow)
    assert b.decide_declare(rnd, seat) == HEURISTIC.decide_declare(rnd, seat)
    record = b.last_declare_record
    assert record["evaluated"] is False
    assert (record["fallback_reason"], record["fallback_error"]) == \
        ("hard_budget", "PVSearchBudgetExceeded")


def test_an_interrupt_inside_the_served_pass_propagates(monkeypatch):
    rnd, seat = state_at(*NT_CASE)
    b = bot()

    def cancelled(*a, **k):
        raise KeyboardInterrupt("cancelled")
    monkeypatch.setattr(dsb, "served_bury", cancelled)
    with pytest.raises(KeyboardInterrupt):
        b.decide_declare(rnd, seat)


# ------------------------------------------------------------ (f) the served construction

def test_the_served_construction_with_the_flag_on_decides_a_declaration(package):
    path, sha = package
    small = dict(worlds=3, candidates=4, cap=400, batch_size=16)
    b = pv.make_pv_search_bot(path, sha256=sha, seed=5, bury_arm="hybrid", bury_config=BURY,
                              bury_serving_budget_seconds=30, bury_wide_value=True,
                              bury_wide_k=64, value_declare=True, value_declare_worlds=4,
                              value_declare_served_bury=True, **small)
    assert isinstance(b, pv.PVSearchBuryBot) and b.value_declare_served_bury is True
    rnd, seat = state_at(*NT_CASE)
    choice = b.decide_declare(rnd, seat)
    assert choice is None or choice in rnd.declare_options(seat)
    record = b.last_declare_record
    assert record["evaluated"] is True and record["served_bury"]["worlds_completed"] == 16
    with pytest.raises(pv.PVSearchPolicyError, match="needs the served wide"):
        pv.make_pv_search_bot(path, sha256=sha, bury_arm="hybrid", value_declare=True,
                              value_declare_served_bury=True, **small)

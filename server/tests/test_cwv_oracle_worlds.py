"""The pv-search PERFECT-INFORMATION diagnostic (#707 S16: ``oracle_worlds``,
``SHENGJI_PV_ORACLE_WORLDS``, token ``orc``; `train.pv_search_policy`): the W
sampled completions of the hidden hands are replaced by ONE world, the true
deal, supplied ONLY by the screen harness's hook
(`cwv_shortlist_screen.oracle_true_deal` through `PVSearchBot.bind_oracle_deal`).

Package-free except where noted (the tiny real package of
`test_pv_search_serving` for the registry build).  Witnesses:
(a) off: release 44's name, digest and payload are unchanged, and the
flag-off bot's every decision, record and sampler state over self-play are
those of a bot whose `_worlds` / `_decide_play` are main's verbatim;
(b) names: ``orc`` is the last rule token, it moves the digest, the env
reader refuses anything but 0/1, the registry carries the token;
(c) serving refuses: `make_pv_search_bot` and the registry factory raise
without the hook (before any package is read), a hook on a flag-off recipe
is refused, the two adaptive-worlds rules are refused with the oracle, and
the game server module refuses the environment flag at import (a real
subprocess import);
(d) privacy: with the rule on and NO hook bound the bot raises
`OracleWorldsError` -- with and without a serving budget, never a fallback
record, the sampler untouched -- and a hook whose deal breaks the world
contract fails the same way;
(e) on: at every play decision of a self-play round the worlds the search
scores are exactly ``[(true hands, true kitty)]``, the policy prior sees one
row, the value leaves carry the true kitty and hands, the record says one
world and one attempt, and the sampler's stream never moves;
(f) harness: the hook reads only the seat on turn of a play-phase round, the
flag reader and the build arguments, and `make_side` builds the oracle arm
with the hook only when the config recorded the diagnostic.
"""
import copy
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.registry import REGISTRY, make_bot, register_pv_search_policies
from shengji.api import server as srv
from shengji.train import cwv_shortlist_screen as screen
from shengji.train import pv_search_policy as pv
from shengji.train.pv_search_policy import (RECORD_SCHEMA, OracleWorldsError, PVSearchBudgetExceeded,
                                            PVSearchPolicyError)
from test_cwv_leaf_policy_first_trick import RELEASE44_LPFT, RELEASE44_NAME, fly_env
from test_pv_admission_rules import (PRODUCTION_SHA, ZeroEvaluator, names, predict,
                                     production_package)  # noqa: F401
from test_pv_search_serving import SMALL as SERVING_SMALL, _play_state, package  # noqa: F401
from test_pv_small_joker_lead import PointsEvaluator, _fresh_round, _strip

FLAG = "SHENGJI_PV_ORACLE_WORLDS"
#: release 44 (fly.toml at this head; checkpoint id stubbed) with the diagnostic
RELEASE44_ORC = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-orc-rac96cd35-bury-hybrid-0be57600e5e0"
RELEASE44_LPFT_ORC = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-lpft-orc-rb3d6c951-bury-hybrid-5b1d240cde61"
#: release 44's PLAY rules (the declare rule has no play-world effect)
RELEASE44_PLAY_RULES = dict(admission_diversity=True, refusal_constraints=True,
                            tiebreak_points=True, lead_anchor=True, doomed_throw_reselect=True)
HOOK = screen.oracle_true_deal
SELF_PLAY_SEEDS = tuple(range(716001, 716004))


# ------------------------------------------------------------ stubs

class CountingPredict:
    """`predict` with a row count: the prior scores one row per world."""

    def __init__(self):
        self.rows = []

    def __call__(self, X):
        self.rows.append(len(X))
        return predict(X)


class RecordingEvaluator(PointsEvaluator):
    """`PointsEvaluator` keeping every scored leaf."""

    def __init__(self):
        self.leaves = []

    def score(self, leaves, seat):
        self.leaves.extend(leaves)
        return super().score(leaves, seat)


def served(evaluator=None, worlds=4, seed=17, budget=None, predictor=predict, **rules):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=worlds, candidates=8,
                               cap=4000, batch_size=128, serving_budget_seconds=budget, **rules)
    return pv.PVSearchBot(predictor, evaluator=evaluator or PointsEvaluator(), version=2,
                          config=config, checkpoint="/dev/null", seed=seed)


def true_deal(rnd):
    return [sorted(hand) for hand in rnd.hands], sorted(rnd.buried)


class MainWorlds(pv.PVSearchBot):
    """The served bot with `_worlds` and `_decide_play` verbatim from main
    5516d1da (before the diagnostic)."""

    def _worlds(self, rnd, seat, check_budget=None):
        from shengji.ai.cwv_policy import sample_worlds
        from shengji.ai.memory import Memory
        from shengji.ai.refusal import sample_worlds_refusal_aware
        mem = Memory(rnd, seat, own_kitty=getattr(self.sampler, "BANKER_KITTY", True))
        self._last_sampling = {}
        refusals = self._refusals.observe(rnd) if self.refusal_constraints else ()
        if refusals:
            worlds, attempts, self._last_sampling = sample_worlds_refusal_aware(
                self.sampler, rnd, seat, self.worlds, refusals, mem=mem,
                check_budget=check_budget)
        else:
            worlds, attempts = sample_worlds(self.sampler, rnd, seat, self.worlds, mem=mem,
                                             check_budget=check_budget)
        if len(worlds) != self.worlds:
            raise PVSearchPolicyError(f"policy world sampling short: {len(worlds)}/{self.worlds}",
                                      stage="world_sampling_short")
        if any(rnd.ordering.eff_suit(c) in mem.voids[s]
               for hands, _ in worlds for s in range(4) if s != seat for c in hands[s]):
            raise PVSearchPolicyError("policy world sampling violates public voids",
                                      stage="world_sampling_void_check")
        return worlds, attempts

    def _decide_play(self, rnd, seat, started):
        self.last_decision_record = None
        anchor = HeuristicBot.decide_play(self, rnd, seat)
        if self.serving_budget_seconds is None:
            return self._search(rnd, seat, anchor, started)
        before = self.sampler.rng.getstate()

        def check_budget():
            if time.perf_counter() - started >= self.serving_budget_seconds:
                raise PVSearchBudgetExceeded("pv-search serving budget expired")

        try:
            return self._search(rnd, seat, anchor, started, check_budget)
        except Exception as exc:
            self.sampler.rng.setstate(before)
            self.last_decision_record = {
                "schema": pv.FALLBACK_SCHEMA, "policy": getattr(self, "policy_name", None),
                "action": list(anchor), "played": list(anchor),
                "reason": "budget" if isinstance(exc, PVSearchBudgetExceeded) else "search-error",
                "error_class": type(exc).__name__,
                "error_stage": getattr(exc, "stage", None),
                "error_message": str(exc)[:pv.ERROR_MESSAGE_MAX],
                "budget_seconds": self.serving_budget_seconds,
                "elapsed_seconds": time.perf_counter() - started,
                "work_complete": False,
            }
            return list(anchor)


def _bot(cls, seat, rules, budget=None, **flags):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=4, candidates=8, cap=4000,
                               batch_size=128, serving_budget_seconds=budget, **rules, **flags)
    return cls(predict, evaluator=PointsEvaluator(), version=2, config=config,
               checkpoint="/dev/null", seed=100 + seat)


# ------------------------------------------------------------ (a) off: identity

def test_release_names_digest_and_payload_unchanged_when_off(production_package):
    assert names(fly_env()) == [RELEASE44_NAME]
    for raw in ("0", ""):
        assert names({**fly_env(), FLAG: raw}) == [RELEASE44_NAME]
    config = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0)
    assert pv.recipe_digest(config) == "4a09aef5"
    payload = pv.recipe_payload(config)
    assert "oracle_worlds" not in payload and "oracle_worlds_information" not in payload
    assert pv.PVSearchBot.oracle_worlds is False and pv.PVSearchBot._oracle_deal is None
    bot = served()
    assert bot.oracle_worlds is False and bot._oracle_deal is None


@pytest.mark.parametrize("rules", [RELEASE44_PLAY_RULES, {}], ids=["release44", "bare"])
@pytest.mark.parametrize("budget", [None, 3.0], ids=["unbudgeted", "budgeted"])
def test_off_is_mains_decision_over_self_play(rules, budget):
    decisions = 0
    for seed in SELF_PLAY_SEEDS:
        rnd = _fresh_round(seed)
        off = [_bot(pv.PVSearchBot, s, rules, budget) for s in range(4)]
        main = [_bot(MainWorlds, s, rules, budget) for s in range(4)]
        while rnd.phase == "play":
            seat = rnd.turn
            a = off[seat].decide_play(copy.deepcopy(rnd), seat)
            b = main[seat].decide_play(copy.deepcopy(rnd), seat)
            assert a == b
            assert _strip(off[seat].last_decision_record) == _strip(main[seat].last_decision_record)
            assert off[seat].last_decision_record["schema"] == RECORD_SCHEMA
            assert off[seat].sampler.rng.getstate() == main[seat].sampler.rng.getstate()
            decisions += 1
            rnd.play(seat, a)
    assert decisions >= 75


# ------------------------------------------------------------ (b) names

def test_token_is_last_moves_the_digest_and_the_env_reader_refuses_bad_values(production_package):
    assert pv.RULE_TOKENS[-1] == ("oracle_worlds", "orc")
    assert pv.RULE_FLAGS["ORACLE_WORLDS"] == "oracle_worlds"
    assert names({**fly_env(), FLAG: "1"}) == [RELEASE44_ORC]
    assert names({**fly_env(), FLAG: "1", "SHENGJI_PV_LEAF_POLICY_FIRST_TRICK": "1"}) \
        == [RELEASE44_LPFT_ORC]
    assert names({**fly_env(), "SHENGJI_PV_LEAF_POLICY_FIRST_TRICK": "1"}) == [RELEASE44_LPFT]
    assert pv.pv_env_recipe({**fly_env(), FLAG: "1"})["oracle_worlds"] is True
    assert "oracle_worlds" not in pv.pv_env_recipe(fly_env())
    for bad in ("2", "true", "yes"):
        with pytest.raises(PVSearchPolicyError, match="0 or 1"):
            pv.pv_env_recipe({**fly_env(), FLAG: bad})
    off = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA)
    on = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, oracle_worlds=True)
    assert pv.recipe_digest(on) != pv.recipe_digest(off)
    payload = pv.recipe_payload(on)
    assert payload["oracle_worlds"] is True and payload["oracle_worlds_information"] == "true-deal"
    assert pv.pv_policy_name("491ee4bf", on).endswith(f"-orc-r{pv.recipe_digest(on)}")
    with pytest.raises(PVSearchPolicyError, match="bool"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, oracle_worlds=1))


# ------------------------------------------------------------ (c) serving refuses

def test_constructors_refuse_without_the_hook_before_any_package_is_read(tmp_path):
    missing = str(tmp_path / "absent.npz")
    with pytest.raises(PVSearchPolicyError, match="never served"):
        pv.make_pv_search_bot(missing, sha256="f" * 64, oracle_worlds=True)
    assert not os.path.exists(missing)
    # a hook on a flag-off recipe is refused too: a served bot carries none
    with pytest.raises(PVSearchPolicyError, match="rule off"):
        pv.make_pv_search_bot(missing, sha256="f" * 64, oracle_deal=HOOK)
    with pytest.raises(PVSearchPolicyError, match="bool"):
        pv.make_pv_search_bot(missing, sha256="f" * 64, oracle_worlds="1", oracle_deal=HOOK)


def test_registry_factory_refuses_the_servers_build(production_package):
    (name, factory), = pv.pv_registry_entries(**pv.pv_env_recipe({**fly_env(), FLAG: "1"})).items()
    assert name == RELEASE44_ORC
    # `make_bot(name, seed=)` is the game server's whole build: no hook
    with pytest.raises(PVSearchPolicyError, match="never served"):
        factory(seed=0)
    (name, factory), = pv.pv_registry_entries(**pv.pv_env_recipe(fly_env())).items()
    assert name == RELEASE44_NAME
    with pytest.raises(PVSearchPolicyError, match="rule off"):
        factory(seed=0, oracle_deal=HOOK)


def test_adaptive_worlds_rules_are_refused_with_the_oracle():
    for rule in ("adaptive_worlds", "adaptive_worlds_leads"):
        with pytest.raises(PVSearchPolicyError, match="exclusive"):
            pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, oracle_worlds=True,
                                                **{rule: True}))
        with pytest.raises(PVSearchPolicyError, match="exclusive"):
            served(oracle_worlds=True, **{rule: True})


def test_game_server_refuses_the_flag_at_import():
    for raw in (None, "", "0"):
        srv._refuse_pv_diagnostics({} if raw is None else {FLAG: raw})
    with pytest.raises(RuntimeError, match="never served"):
        srv._refuse_pv_diagnostics({FLAG: "1"})
    # the real thing: a server process with the flag cannot import its module
    env = {**os.environ, FLAG: "1"}
    env.pop("SHENGJI_PV_CKPT", None)
    proc = subprocess.run([sys.executable, "-B", "-c", "import shengji.api.server"],
                          cwd=str(Path(__file__).parents[1]), env=env,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode != 0
    assert "SHENGJI_PV_ORACLE_WORLDS" in proc.stderr and "never served" in proc.stderr
    env[FLAG] = "0"
    proc = subprocess.run([sys.executable, "-B", "-c", "import shengji.api.server"],
                          cwd=str(Path(__file__).parents[1]), env=env,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr


# ------------------------------------------------------------ (d) privacy

@pytest.mark.parametrize("budget", [None, 3.0], ids=["unbudgeted", "budgeted"])
def test_oracle_bot_refuses_without_a_hook_and_never_falls_back(budget):
    bot = served(budget=budget, oracle_worlds=True)
    assert bot.oracle_worlds is True and bot._oracle_deal is None
    rnd = _fresh_round(SELF_PLAY_SEEDS[0])
    before = bot.sampler.rng.getstate()
    with pytest.raises(OracleWorldsError, match="no harness hook"):
        bot.decide_play(copy.deepcopy(rnd), rnd.turn)
    assert bot.last_decision_record is None            # no fallback record, no play
    assert bot.sampler.rng.getstate() == before
    # the rule off: a hook is refused, and the bot plays as always
    off = served(budget=budget)
    with pytest.raises(PVSearchPolicyError, match="rule off"):
        off.bind_oracle_deal(HOOK)
    assert off._oracle_deal is None
    with pytest.raises(PVSearchPolicyError, match="callable"):
        bot.bind_oracle_deal("not a hook")


def _broken_hooks(rnd, seat):
    hands, buried = true_deal(rnd)
    others = [s for s in range(4) if s != seat]
    swapped = list(hands)
    swapped[seat], swapped[others[0]] = hands[others[0]], hands[seat]
    moved = [list(h) for h in hands]
    moved[others[1]].append(moved[others[0]].pop())        # sizes off
    duplicated = [list(h) for h in hands]
    duplicated[others[0]][0] = duplicated[others[1]][0]      # conservation off
    return {
        "three hands": lambda r, s: (hands[:3], buried),
        "not this seat's hand": lambda r, s: (swapped, buried),
        "sizes": lambda r, s: (moved, buried),
        "conservation": lambda r, s: (duplicated, buried),
        "raises": lambda r, s: (_ for _ in ()).throw(KeyError("no deal")),
    }


@pytest.mark.parametrize("budget", [None, 3.0], ids=["unbudgeted", "budgeted"])
def test_a_hook_breaking_the_world_contract_fails_closed(budget):
    rnd = _fresh_round(SELF_PLAY_SEEDS[1])
    seat = rnd.turn
    for label, hook in _broken_hooks(rnd, seat).items():
        bot = served(budget=budget, oracle_worlds=True)
        bot.bind_oracle_deal(hook)
        before = bot.sampler.rng.getstate()
        with pytest.raises(OracleWorldsError):
            bot.decide_play(copy.deepcopy(rnd), seat)
        assert bot.last_decision_record is None, label
        assert bot.sampler.rng.getstate() == before, label


# ------------------------------------------------------------ (e) on: the true deal

@pytest.mark.parametrize("rules", [RELEASE44_PLAY_RULES, {}], ids=["release44", "bare"])
@pytest.mark.parametrize("budget", [None, 3.0], ids=["unbudgeted", "budgeted"])
def test_the_search_scores_exactly_the_true_deal(rules, budget):
    decisions = 0
    for seed in SELF_PLAY_SEEDS:
        rnd = _fresh_round(seed)
        bots, predictors, evaluators, scored = [], [], [], []
        for s in range(4):
            predictor, evaluator = CountingPredict(), RecordingEvaluator()
            bot = served(evaluator, seed=100 + s, budget=budget, predictor=predictor,
                         oracle_worlds=True, **rules)
            bot.bind_oracle_deal(HOOK)
            log = []
            orig = bot._score_leaves

            def _score_leaves(rnd_, seat_, actions, worlds, *a, _orig=orig, _log=log, **kw):
                _log.append([(list(map(list, hands)), list(buried)) for hands, buried in worlds])
                return _orig(rnd_, seat_, actions, worlds, *a, **kw)
            bot._score_leaves = _score_leaves
            bots.append(bot)
            predictors.append(predictor)
            evaluators.append(evaluator)
            scored.append(log)
        while rnd.phase == "play":
            seat = rnd.turn
            bot = bots[seat]
            hands, kitty = true_deal(rnd)
            rng_before = bot.sampler.rng.getstate()
            n_leaves, n_rows, n_scored = (len(evaluators[seat].leaves), len(predictors[seat].rows),
                                          len(scored[seat]))
            played = bot.decide_play(copy.deepcopy(rnd), seat)
            rec = bot.last_decision_record
            assert rec["schema"] == RECORD_SCHEMA and rec["work_complete"]
            assert rec["worlds"] == 1 and rec["sample_attempts"] == 1
            assert bot.sampler.rng.getstate() == rng_before     # no draw
            # the prior: one row (one world); the search: exactly the true deal
            assert predictors[seat].rows[n_rows:] == [1]
            assert scored[seat][n_scored:] == [[(hands, kitty)]]
            # the value leaves: one per admitted candidate, the true kitty and,
            # for every other seat, a hand that is the true hand less its play
            leaves = evaluators[seat].leaves[n_leaves:]
            assert len(leaves) == len(rec["admitted"]) == rec["value_evaluations"]
            for leaf in leaves:
                assert sorted(leaf.buried) == kitty
                for s in range(4):
                    if s != seat:
                        assert not (Counter(leaf.hands[s]) - Counter(hands[s]))
                        gone = Counter(hands[s]) - Counter(leaf.hands[s])
                        play = next((Counter(p.cards) for p in leaf.last_trick.plays
                                     if p.seat == s), Counter())
                        assert not gone or gone == play       # its own play in the leaf's trick
            if rules:
                assert rec["refusal_observations"] == 0 and rec["refusal_fallback_worlds"] == 0
            decisions += 1
            rnd.play(seat, played)
    assert decisions >= 75


def test_the_decision_is_a_counterfactual_of_the_sampled_one_on_the_same_state():
    """Census only: the oracle's pick differs from the W-world pick on some
    decisions (it is a different evidence base), and both are legal."""
    rnd = _fresh_round(SELF_PLAY_SEEDS[2])
    changed = decisions = 0
    while rnd.phase == "play":
        seat = rnd.turn
        sampled = served(seed=100 + seat, **RELEASE44_PLAY_RULES)
        oracle = served(seed=100 + seat, oracle_worlds=True, **RELEASE44_PLAY_RULES)
        oracle.bind_oracle_deal(HOOK)
        a = sampled.decide_play(copy.deepcopy(rnd), seat)
        b = oracle.decide_play(copy.deepcopy(rnd), seat)
        assert sampled.last_decision_record["worlds"] == 4
        assert oracle.last_decision_record["worlds"] == 1
        changed += a != b
        decisions += 1
        rnd.play(seat, a)
    assert decisions >= 25
    print(f"\noracle census: decisions={decisions} played_changed={changed}")


# ------------------------------------------------------------ (f) the harness

def test_harness_hook_answers_only_the_seat_on_turn_of_a_play_round():
    rnd = _fresh_round(SELF_PLAY_SEEDS[0])
    seat = rnd.turn
    hands, buried = HOOK(rnd, seat)
    assert ([sorted(h) for h in hands], sorted(buried)) == true_deal(rnd)
    assert all(h is not rnd.hands[s] for s, h in enumerate(hands)) and buried is not rnd.buried
    with pytest.raises(ValueError, match="seat on turn"):
        HOOK(rnd, (seat + 1) % 4)
    from shengji.engine.round import Round
    from shengji.engine.cards import RANKS
    import random
    dealing = Round(RANKS[0], None, random.Random(1))
    with pytest.raises(ValueError, match="play-phase"):
        HOOK(dealing, 0)


def test_harness_requests_the_oracle_only_from_the_flag():
    assert screen.ORACLE_WORLDS_FLAG == FLAG
    assert screen.oracle_worlds_requested({}) is False
    for raw in ("", "0"):
        assert screen.oracle_worlds_requested({FLAG: raw}) is False
    assert screen.oracle_worlds_requested({FLAG: "1"}) is True
    with pytest.raises(ValueError, match="0 or 1"):
        screen.oracle_worlds_requested({FLAG: "2"})
    assert screen._arm_policy_kwargs({}) == {}
    assert screen._arm_policy_kwargs({"oracle_worlds": True}) == {"oracle_deal": HOOK}


@pytest.fixture
def oracle_registered(package):
    path, sha = package
    registered = register_pv_search_policies(path, sha256=sha, oracle_worlds=True, **SERVING_SMALL)
    plain = register_pv_search_policies(path, sha256=sha, **SERVING_SMALL)
    try:
        yield registered[0], plain[0]
    finally:
        for name in registered + plain:
            REGISTRY.pop(name, None)


def test_make_side_builds_the_oracle_arm_with_the_hook_only_when_recorded(oracle_registered):
    name, plain = oracle_registered
    assert "-orc-" in name and "-orc-" not in plain
    with pytest.raises(PVSearchPolicyError, match="never served"):
        make_bot(name, seed=5)                            # the server's build
    probe = make_bot(name, seed=0, **screen._arm_policy_kwargs({"oracle_worlds": True}))
    assert isinstance(probe, pv.PVSearchBot) and probe._oracle_deal is HOOK
    config = {"arm": "policy", "arm_policy": name, "oracle_worlds": True,
              "arm_policy_identity": screen._policy_identity(probe)}
    assert config["arm_policy_identity"]["config"]["oracle_worlds"] is True
    bot = screen.make_side(config, "arm", 3)
    assert bot.policy_name == name and bot._oracle_deal is HOOK and bot.oracle_worlds
    # the arm plays the true deal through the real package
    rnd = _play_state()
    before = bot.sampler.rng.getstate()
    bot.decide_play(copy.deepcopy(rnd), rnd.turn)
    rec = bot.last_decision_record
    assert rec["schema"] == RECORD_SCHEMA and rec["worlds"] == 1 and rec["sample_attempts"] == 1
    assert bot.sampler.rng.getstate() == before
    # the config without the diagnostic cannot build the oracle name ...
    with pytest.raises(PVSearchPolicyError, match="never served"):
        screen.make_side({**config, "oracle_worlds": False}, "arm", 3)
    # ... and the diagnostic cannot be hung on a plain name
    plain_probe = make_bot(plain, seed=0)
    with pytest.raises(PVSearchPolicyError, match="rule off"):
        screen.make_side({"arm": "policy", "arm_policy": plain, "oracle_worlds": True,
                          "arm_policy_identity": screen._policy_identity(plain_probe)}, "arm", 3)
    # the baseline side never sees the hook
    baseline = screen.make_side({**config, "base_policy": "heuristic"}, "baseline", 3)
    assert getattr(baseline, "_oracle_deal", None) is None


def test_summary_description_names_the_diagnostic():
    identity = {"bot_class": "PVSearchBuryBot"}
    plain = screen._arm_description({"arm": "policy", "arm_policy": RELEASE44_NAME,
                                     "arm_policy_identity": identity})
    assert plain.startswith("served registry policy") and "oracle" not in plain
    orc = screen._arm_description({"arm": "policy", "arm_policy": RELEASE44_ORC,
                                   "arm_policy_identity": identity, "oracle_worlds": True})
    assert orc.startswith("DIAGNOSTIC") and "never served" in orc and RELEASE44_ORC in orc

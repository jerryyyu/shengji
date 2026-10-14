"""The OPTIONAL second stage of the wide value-only bury (``bury_two_stage``,
``SHENGJI_PV_BURY_TWO_STAGE``, bury token ``bts``; #707 S15;
`train.bury_two_stage`): the stage-1 value top-N re-scored on fresh worlds
common to every candidate, each position played forward by the policy head
before the value head scores it, the stage-1 argmax kept unless stage 2 beats
it by the margin and by ``z`` paired standard errors; its own deadline and a
hard fallback to the stage-1 argmax.

Torch-free and package-free (the stub predictor and evaluators of the wide
chooser's tests on the real engine, ballot, sampler and policy player), except
the served construction on the serving test's tiny package.  Witnesses: (a)
off: release 45's name, recipe, bot state, decisions and records (the wide
chooser's frozen tape) are unchanged and the stage never runs; (b) common
worlds: every top candidate is scored on the SAME fresh worlds (the stage's own
seeded stream, not stage 1's), world-major, each played ``tricks`` tricks;
(c) the decision rule (margin, z, ties) and that a stage-2 winner replaces the
stage-1 argmax in the record; (d) the deadline: an expiry inside the stage, a
deadline the bury budget already used up, and an error all keep the stage-1
argmax (never the heuristic fallback), the play sampler untouched; (e) an
ended round is valued by its outcome; (f) the token, identity, env parsing,
refusals, registry and served construction.
"""
import copy
import hashlib
import json

import numpy as np
import pytest

from shengji.train.policy_prior import CARD_INDEX
from shengji.ai.registry import REGISTRY, make_bot, register_pv_search_policies
from shengji.train import bury_two_stage as bts
from shengji.train import bury_wide_value as bwv
from shengji.train import cwv_bury_policy as bury_policy
from shengji.train import pv_search_policy as pv
from test_cwv_bury_wide_value import (BURY, RECORD_KEYS, RELEASE44_BWV64, SWAPS1_TAPE_SHA256,
                                      CountingPredict, ExpireOnFourthPredict, TrickEvaluator,
                                      SMALL, bury_state, decide, fly_env, incumbent_of,
                                      jumping_clock, without_timing)  # noqa: F401
from test_pv_admission_rules import PRODUCTION_ENV, names, production_package  # noqa: F401
from test_pv_search_serving import package  # noqa: F401

FLAG = "SHENGJI_PV_BURY_TWO_STAGE"
WIDE = {"SHENGJI_PV_BURY_WIDE_VALUE": "1", "SHENGJI_PV_BURY_WIDE_K": "64"}
#: release 45 (fly.toml at this head) with the second stage at its defaults,
#: and with two-card swaps at K=128
RELEASE45_BTS = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-radd86676-bury-hybrid-bwv-bts-6ed2b3f6bff5"
RELEASE45_BWV2_128_BTS = ("pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-radd86676-bury-hybrid-"
                          "bwv2-bts-1cb6f139c9e3")
SMALL_STAGE = bts.TwoStageConfig(top=3, worlds=3, tricks=2)
ROOTS = (65, 66, 67)


class DeepEvaluator(TrickEvaluator):
    """`TrickEvaluator` over EVERY completed trick (identical on a one-trick
    position, so stage 1 sees exactly its values), at a trick boundary."""

    def score(self, positions, seat):
        self.calls += 1
        self.positions.extend(copy.deepcopy(positions))
        out = []
        for p in positions:
            assert p.history and p.trick is not None and not p.trick.plays
            trick = sum(CARD_INDEX[c] for t in p.history for play in t.plays for c in play.cards)
            buried = sum(CARD_INDEX[c] for c in p.buried)
            out.append(((trick * 7 + buried * 3) % 101) / 101.0 - 0.5)
        return np.array(out)


def served_bury(predict=None, evaluator=None, arm="hybrid", bury_budget=None, seed=17,
                bury_config=BURY, **rules):
    """The wide chooser's test builder, passing ``bury_two_stage`` through."""
    wide = {k: rules.pop(k) for k in ("bury_wide_value", "bury_wide_k", "bury_wide_swaps",
                                      "bury_two_stage") if k in rules}
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, **SMALL, **rules)
    return pv.PVSearchBuryBot(predict or CountingPredict(), evaluator=evaluator or DeepEvaluator(),
                              version=2, config=config, checkpoint="/dev/null", seed=seed,
                              bury_arm=arm, bury_config=bury_config,
                              bury_serving_budget_seconds=bury_budget, **wide)


def two_stage(config=SMALL_STAGE, k=64, **kw):
    return served_bury(bury_wide_value=True, bury_wide_k=k, bury_two_stage=config, **kw)


class StageEvaluator(DeepEvaluator):
    """Stage 1 (one completed trick) and stage 2 (``tricks`` completed) see
    different values: ``first`` wins stage 1 and ``second`` (second in stage
    1) wins stage 2; every other kitty is small and distinct."""

    def __init__(self, first, second, tricks):
        super().__init__()
        self.first, self.second, self.tricks = sorted(first), sorted(second), tricks
        self.stage2_calls = 0

    def score(self, positions, seat):
        self.calls += 1
        self.positions.extend(copy.deepcopy(positions))
        out = []
        for p in positions:
            kitty = sorted(p.buried)
            small = (hash(tuple(kitty)) % 97) / 1000.0
            if len(p.history) == self.tricks:
                out.append(1.0 if kitty == self.second else 0.0 if kitty == self.first else small)
            else:
                out.append(1.0 if kitty == self.first else 0.9 if kitty == self.second else small)
        if any(len(p.history) == self.tricks for p in positions):
            self.stage2_calls += 1
        return np.array(out)


def stage1_of(index, k=64):
    """The stage-1 candidates and their ranking (the release-45 chooser)."""
    bot = served_bury(bury_wide_value=True, bury_wide_k=k)
    chosen, record = decide(bot, index)
    means = record["model_means"]
    order = sorted(range(len(means)), key=lambda i: (-means[i], i))
    return record["candidates"], order, record


# ------------------------------------------------------------ (a) off: identity

def test_off_name_recipe_and_state_are_release_45s(production_package):
    assert names({**fly_env(), **WIDE}) == [RELEASE44_BWV64]
    for raw in ("0", ""):
        assert names({**fly_env(), **WIDE, FLAG: raw}) == [RELEASE44_BWV64]
        assert "bury_two_stage" not in pv.pv_env_recipe({**PRODUCTION_ENV, **WIDE, FLAG: raw})
    assert pv.PVSearchBuryBot.bury_two_stage is None
    for kw in ({}, {"bury_two_stage": None}):
        bot = served_bury(bury_wide_value=True, bury_wide_k=64, **kw)
        assert "bury_two_stage" not in vars(bot)
        assert vars(bot).keys() == vars(served_bury(bury_wide_value=True, bury_wide_k=64)).keys()


def test_off_decisions_and_records_reproduce_the_frozen_tape(monkeypatch):
    """The wide chooser's frozen tape (#974's code, K=32 and K=64 on the DEV
    roots 60-71) with ``bury_two_stage=None``, and the stage never runs."""
    def never(*a, **k):
        raise AssertionError("the second stage ran with the flag off")
    monkeypatch.setattr(bwv, "run_stage_two", never)
    tape = []
    for index in range(60, 72):
        for k in (32, 64):
            bot = served_bury(bury_wide_value=True, bury_wide_k=k, bury_budget=60.0,
                              bury_two_stage=None)
            chosen, record = decide(bot, index)
            assert tuple(record) == RECORD_KEYS + (bwv.RECORD_KEY,)
            wv = {key: v for key, v in record[bwv.RECORD_KEY].items() if key != "seconds"}
            tape.append([index, k, chosen, without_timing({**record, bwv.RECORD_KEY: wv})])
    digest = hashlib.sha256(json.dumps(tape, sort_keys=True).encode()).hexdigest()
    assert digest == SWAPS1_TAPE_SHA256


# ------------------------------------------------------------ (b) common worlds

@pytest.mark.parametrize("index", ROOTS)
def test_stage_two_scores_every_top_candidate_on_the_same_fresh_worlds(index):
    bot = two_stage(bury_budget=60.0)
    before = bot.sampler.rng.getstate()
    chosen, record = decide(bot, index)
    assert bot.sampler.rng.getstate() == before            # no RNG the bot owns moved
    ts = record[bts.RECORD_KEY]
    assert ts["completed"] is True and ts["fallback"] is None
    candidates, order, _ = stage1_of(index)
    assert record["candidates"] == candidates               # stage 1 is release 45's
    assert ts["stage1_index"] == order[0] and ts["top"] == order[:3]
    tricks, top, worlds = SMALL_STAGE.tricks, SMALL_STAGE.top, SMALL_STAGE.worlds
    stage2 = [p for p in bot.evaluator.positions if len(p.history) == tricks]
    stage1 = [p for p in bot.evaluator.positions if len(p.history) == 1]
    assert len(stage1) == len(candidates) * BURY.model_worlds
    assert len(stage2) == top * worlds == ts["positions"]
    banker = bury_state(index).banker

    def deal(position):
        """The position's pre-play hands of the three hidden seats: its hand
        plus what the seat played."""
        played = {seat: [] for seat in range(4)}
        for trick in position.history:
            for play in trick.plays:
                played[play.seat].extend(play.cards)
        return tuple(tuple(sorted(position.hands[s] + played[s])) for s in range(4) if s != banker)

    groups = [stage2[w * top:(w + 1) * top] for w in range(worlds)]
    for group in groups:
        assert len({deal(p) for p in group}) == 1           # ONE world for every candidate
        assert [sorted(p.buried) for p in group] == [sorted(candidates[i]) for i in ts["top"]]
    assert len({deal(group[0]) for group in groups}) == worlds   # distinct worlds
    # the stage's own seeded stream, not stage 1's
    rnd = bury_state(index)
    helper = make_bot("mc-s0-report-lcb", seed=bury_policy._seed(bts.SEED_LABEL, bot.seed))
    expected, attempts = bury_policy._worlds(helper, rnd, banker, worlds, "two-stage")
    assert [deal(g[0]) for g in groups] == [
        tuple(tuple(sorted(hands[s])) for s in range(4) if s != banker) for hands, _ in expected]
    assert ts["world_attempts"] == attempts
    assert not {deal(g[0]) for g in groups} & {deal(p) for p in stage1}
    # the policy head played every stage-2 trick
    assert ts["policy_plays"] == top * worlds * tricks * 4 and ts["policy_fallbacks"] == 0
    assert ts["terminal_positions"] == 0
    assert json.dumps(record)


def test_score_common_worlds_is_world_major_with_one_batch_per_chunk():
    index = 65
    rnd = bury_state(index)
    candidates = [incumbent_of(index)] + stage1_of(index)[0][1:3]
    helper = make_bot("mc-s0-report-lcb", seed=1)
    worlds, _ = bury_policy._worlds(helper, rnd, rnd.banker, 5, "t")

    class Small(DeepEvaluator):
        max_batch = 4
    evaluator = Small()
    player = bts.PolicyFirstTrick(CountingPredict(), 2, helper.rollout_policy)
    values = bts.score_common_worlds(rnd, candidates, worlds, evaluator, player, 1)
    assert values.shape == (5, 3) and np.isfinite(values).all()
    assert evaluator.calls == 4                              # ceil(15 / 4) value batches
    assert [sorted(p.buried) for p in evaluator.positions] == [sorted(c) for c in candidates] * 5


# ------------------------------------------------------------ (c) the decision

def test_the_decision_rule_margin_z_and_ties():
    flat = np.zeros((4, 3))
    assert bts.stage_two_choice(flat, 0.0, 0.0)[:2] == (0, False)       # a tie keeps stage 1
    better = np.array([[0.0, 0.5, 0.1]] * 4)
    assert bts.stage_two_choice(better, 0.0, 1.0)[:2] == (1, True)      # paired se 0
    assert bts.stage_two_choice(better, 0.5, 0.0)[:2] == (1, False)     # margin is strict
    assert bts.stage_two_choice(better, 0.49, 0.0)[:2] == (1, True)
    noisy = np.array([[0.0, 1.0, 0.0], [0.0, -0.6, 0.0], [0.0, 1.0, 0.0], [0.0, -0.6, 0.0]])
    best, switched, means, se = bts.stage_two_choice(noisy, 0.0, 1.0)
    assert best == 1 and means[1] == pytest.approx(0.2)
    assert se[1] == pytest.approx(np.std([1.0, -0.6, 1.0, -0.6], ddof=1) / 2)
    assert switched is False                                 # 0.2 < 1 x 0.46
    assert bts.stage_two_choice(noisy, 0.0, 0.0)[1] is True
    assert bts.stage_two_choice(noisy, 0.0, 0.4)[1] is True
    assert bts.stage_two_choice(np.array([[0.0, 0.3]]), 0.0, 5.0)[:2] == (1, True)  # one world
    for bad in (np.zeros((3, 1)), np.zeros(3), np.array([[0.0, np.nan]])):
        with pytest.raises(bury_policy.BuryPolicyError):
            bts.stage_two_choice(bad, 0.0, 1.0)


@pytest.mark.parametrize("index", ROOTS)
def test_a_stage_two_winner_replaces_the_stage_one_argmax(index):
    candidates, order, _ = stage1_of(index)
    first, second = candidates[order[0]], candidates[order[1]]
    bot = two_stage(evaluator=StageEvaluator(first, second, SMALL_STAGE.tricks), bury_budget=60.0)
    chosen, record = decide(bot, index)
    ts = record[bts.RECORD_KEY]
    # stage 1 under this evaluator: ``first`` wins, ``second`` is runner-up
    assert ts["stage1_index"] == candidates.index(first) and ts["top"][1] == candidates.index(second)
    assert ts["switched"] is True and ts["completed"] is True
    assert chosen == second and record["picked_index"] == ts["chosen_index"] == ts["top"][1]
    assert record[bwv.RECORD_KEY]["chosen_index"] == ts["chosen_index"]
    assert ts["means"][:2] == [0.0, 1.0] and ts["paired_se"][1] == 0.0
    assert tuple(record) == RECORD_KEYS + (bwv.RECORD_KEY, bts.RECORD_KEY)
    assert record["model_seconds"] <= record[bwv.RECORD_KEY]["seconds"] <= record["elapsed_seconds"]
    # a margin the stage-2 gap does not clear keeps the stage-1 argmax
    held = two_stage(config=bts.TwoStageConfig(top=3, worlds=3, tricks=2, margin=1.0),
                     evaluator=StageEvaluator(first, second, 2), bury_budget=60.0)
    chosen, record = decide(held, index)
    assert chosen == first and record[bts.RECORD_KEY]["switched"] is False
    assert record[bts.RECORD_KEY]["completed"] is True


# ------------------------------------------------------------ (d) the deadline and fallbacks

def assert_stage_one_kept(bot, index, before, reason):
    chosen, record = decide(bot, index)
    assert record["schema"] == "cwv-bury-policy-v1"          # NOT the heuristic fallback
    ts = record[bts.RECORD_KEY]
    assert ts["completed"] is False and ts["fallback"] == reason
    assert ts["switched"] is False and ts["means"] is None
    assert record["picked_index"] == ts["chosen_index"] == ts["stage1_index"]
    assert chosen == record["candidates"][ts["stage1_index"]]
    assert bot.sampler.rng.getstate() == before
    return chosen, record


def test_an_expiry_inside_stage_two_keeps_the_stage_one_argmax(jumping_clock):
    """The clock jumps past every deadline on the stage's fourth policy batch
    (the first trick's last play): no stage-2 value batch runs, the bury's own
    budget never fires (the stage never calls it), stage 1's choice stands."""
    index = 65
    bot = two_stage(predict=ExpireOnFourthPredict(jumping_clock), bury_budget=0.9)
    before = bot.sampler.rng.getstate()
    chosen, record = assert_stage_one_kept(bot, index, before, "budget")
    assert record[bts.RECORD_KEY]["error_class"] == "StageTwoExpired"
    assert bot.predict.calls == 4
    assert all(len(p.history) == 1 for p in bot.evaluator.positions)   # no stage-2 value batch
    assert chosen == stage1_of(index)[0][stage1_of(index)[1][0]]


def test_a_deadline_the_bury_budget_used_up_runs_nothing(monkeypatch):
    """``min(start + seconds, bury start + budget - reserve)``: with the reserve
    larger than the budget the stage expires before drawing a world."""
    monkeypatch.setattr(bts, "RESERVE_SECONDS", 1000.0)
    bot = two_stage(bury_budget=60.0)
    chosen, record = assert_stage_one_kept(bot, 66, bot.sampler.rng.getstate(), "budget")
    ts = record[bts.RECORD_KEY]
    assert ts["world_attempts"] is None and ts["deadline_seconds"] < 0
    assert bot.predict.calls == 0


def test_the_deadline_formula():
    config = bts.TwoStageConfig(seconds=1.0)
    assert bts.stage_two_deadline(config, started=10.0, stage_started=10.4, budget=None) == 11.4
    assert bts.stage_two_deadline(config, started=10.0, stage_started=10.4, budget=2.0) == 11.4
    assert bts.stage_two_deadline(config, started=10.0, stage_started=10.9, budget=2.0) == \
        10.0 + 2.0 - bts.RESERVE_SECONDS
    assert bts.RESERVE_SECONDS == 0.25


def test_an_error_inside_stage_two_keeps_the_stage_one_argmax():
    class BrokenStageTwo(DeepEvaluator):
        def score(self, positions, seat):
            if any(len(p.history) == 2 for p in positions):
                raise RuntimeError("value head failed in stage 2")
            return super().score(positions, seat)
    bot = two_stage(evaluator=BrokenStageTwo(), bury_budget=60.0)
    chosen, record = assert_stage_one_kept(bot, 67, bot.sampler.rng.getstate(), "error")
    assert record[bts.RECORD_KEY]["error_class"] == "RuntimeError"
    # without any bury budget the stage still keeps stage 1 (the stage is optional)
    bot = two_stage(evaluator=BrokenStageTwo())
    assert decide(bot, 67)[1][bts.RECORD_KEY]["fallback"] == "error"


def test_a_stage_one_expiry_still_falls_back_to_the_heuristic_and_never_runs_stage_two(
        monkeypatch):
    def never(*a, **k):
        raise AssertionError("stage two ran after stage one expired")
    monkeypatch.setattr(bwv, "run_stage_two", never)
    bot = two_stage(bury_budget=1e-9)
    chosen = bot.decide_bury(bury_state(65), bury_state(65).banker)
    assert chosen == incumbent_of(65)
    assert bot.last_bury_record["schema"] == "cwv-bury-fallback-v1"
    assert bts.RECORD_KEY not in bot.last_bury_record


# ------------------------------------------------------------ (e) an ended round

def test_an_ended_round_is_valued_by_its_outcome():
    """``tricks`` = 25 plays every position to the end (a full policy
    playout): the value head is never called in stage 2 and every value is
    the outcome's signed level from the banker's team."""
    index = 65
    bot = two_stage(config=bts.TwoStageConfig(top=2, worlds=2, tricks=25), bury_budget=60.0)
    chosen, record = decide(bot, index)
    ts = record[bts.RECORD_KEY]
    assert ts["completed"] is True and ts["terminal_positions"] == 4 == ts["positions"]
    assert all(len(p.history) == 1 for p in bot.evaluator.positions)
    assert all(np.isfinite(ts["means"]))
    support = {bts.category_signed_level(c) for c in range(204)}
    rnd = bury_state(index)
    helper = make_bot("mc-s0-report-lcb", seed=bury_policy._seed(bts.SEED_LABEL, bot.seed))
    worlds, _ = bury_policy._worlds(helper, rnd, rnd.banker, 2, "two-stage")
    player = bts.PolicyFirstTrick(CountingPredict(), 2, helper.rollout_policy)
    values = bts.score_common_worlds(rnd, [record["candidates"][i] for i in ts["top"]], worlds,
                                     DeepEvaluator(), player, 25)
    assert set(values.ravel()) <= support
    assert values.mean(axis=0).tolist() == ts["means"]


# ------------------------------------------------------------ (f) names, identity, env, registry

def test_the_token_and_the_identity(production_package):
    assert names({**fly_env(), **WIDE, FLAG: "1"}) == [RELEASE45_BTS]
    play = RELEASE44_BWV64[:RELEASE44_BWV64.index("-bury-")]
    assert RELEASE45_BTS.startswith(play + "-bury-hybrid-bwv-bts-")   # the play digest is untouched
    two, = names({**fly_env(), **WIDE, "SHENGJI_PV_BURY_WIDE_K": "128",
                  "SHENGJI_PV_BURY_WIDE_SWAPS": "2", FLAG: "1"})
    assert two == RELEASE45_BWV2_128_BTS
    deeper, = names({**fly_env(), **WIDE, FLAG: "1", "SHENGJI_PV_BURY_TWO_STAGE_TRICKS": "4"})
    assert deeper.startswith(play + "-bury-hybrid-bwv-bts-") and deeper != RELEASE45_BTS
    explicit, = names({**fly_env(), **WIDE, FLAG: "1", "SHENGJI_PV_BURY_TWO_STAGE_TOP": "4",
                       "SHENGJI_PV_BURY_TWO_STAGE_MARGIN": "0", "SHENGJI_PV_BURY_TWO_STAGE_Z": "1"})
    assert explicit == RELEASE45_BTS                       # defaults spelled out: the same name
    assert bts.TOKEN == "bts" and bts.RECORD_KEY == "two_stage"
    assert bts.TwoStageConfig().identity() == {"chooser": bts.CHOOSER, "top": 4, "worlds": 32,
                                               "tricks": 2, "margin": 0.0, "z": 1.0,
                                               "seconds": 1.0}


def test_env_parsing_and_refusals():
    base = {**PRODUCTION_ENV, **WIDE}
    recipe = pv.pv_env_recipe({**base, FLAG: "1"})
    assert recipe["bury_two_stage"] == bts.TwoStageConfig()
    recipe = pv.pv_env_recipe({**base, FLAG: "1", "SHENGJI_PV_BURY_TWO_STAGE_TOP": "6",
                               "SHENGJI_PV_BURY_TWO_STAGE_WORLDS": "64",
                               "SHENGJI_PV_BURY_TWO_STAGE_TRICKS": "4",
                               "SHENGJI_PV_BURY_TWO_STAGE_MARGIN": "0.05",
                               "SHENGJI_PV_BURY_TWO_STAGE_Z": "2",
                               "SHENGJI_PV_BURY_TWO_STAGE_SECONDS": "0.8"})
    assert recipe["bury_two_stage"] == bts.TwoStageConfig(top=6, worlds=64, tricks=4, margin=0.05,
                                                          z=2.0, seconds=0.8)
    for bad in ("2", "true", " 1"):
        with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
            pv.pv_env_recipe({**base, FLAG: bad})
    with pytest.raises(pv.PVSearchPolicyError, match="needs SHENGJI_PV_BURY_WIDE_VALUE=1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "1"})
    for suffix in pv.BURY_TWO_STAGE_PARAMS:
        with pytest.raises(pv.PVSearchPolicyError, match="needs SHENGJI_PV_BURY_TWO_STAGE=1"):
            pv.pv_env_recipe({**base, "SHENGJI_PV_" + suffix: "1"})
    for suffix, bad in (("TOP", "1"), ("TOP", "17"), ("TOP", "x"), ("WORLDS", "0"),
                        ("TRICKS", "26"), ("TRICKS", "2.0"), ("MARGIN", "-0.1"), ("MARGIN", "nan"),
                        ("Z", "-1"), ("Z", "11"), ("SECONDS", "0"), ("SECONDS", "11"),
                        ("SECONDS", "inf")):
        with pytest.raises(pv.PVSearchPolicyError):
            pv.pv_env_recipe({**base, FLAG: "1", f"SHENGJI_PV_BURY_TWO_STAGE_{suffix}": bad})


def test_constructor_and_config_refusals():
    with pytest.raises(pv.PVSearchPolicyError, match="needs bury_wide_value"):
        served_bury(bury_two_stage=bts.TwoStageConfig())
    with pytest.raises(pv.PVSearchPolicyError, match="TwoStageConfig or None"):
        served_bury(bury_wide_value=True, bury_two_stage={"top": 4})
    with pytest.raises(pv.PVSearchPolicyError, match="needs bury_wide_value"):
        pv.pv_registry_entries("/dev/null", sha256="f" * 64, bury_arm="hybrid",
                               bury_two_stage=bts.TwoStageConfig())
    for kw in ({"top": 1}, {"top": True}, {"worlds": 257}, {"tricks": 0}, {"margin": -1.0},
               {"margin": float("inf")}, {"z": 10.5}, {"z": True}, {"seconds": 0.0},
               {"seconds": 10.5}):
        with pytest.raises(bury_policy.BuryPolicyError):
            bts.TwoStageConfig(**kw)
    assert bts.TwoStageConfig(margin=0, z=1, seconds=1) == bts.TwoStageConfig()
    assert type(bts.TwoStageConfig(margin=0).margin) is float


def test_the_served_construction_and_registry(package):
    path, sha = package
    small = dict(worlds=3, candidates=4, cap=400, batch_size=16)
    config = bts.TwoStageConfig(top=3, worlds=4, tricks=2)
    bot = pv.make_pv_search_bot(path, sha256=sha, seed=5, bury_arm="hybrid", bury_config=BURY,
                                bury_serving_budget_seconds=30, bury_wide_value=True,
                                bury_wide_k=48, bury_two_stage=config, **small)
    assert bot.bury_two_stage == config
    chosen, record = decide(bot, 65)
    ts = record[bts.RECORD_KEY]
    assert ts["completed"] is True and len(chosen) == 8 and ts["positions"] == 12
    registered = register_pv_search_policies(path, sha256=sha, bury_arm="hybrid", bury_config=BURY,
                                             bury_serving_budget_seconds=2, bury_wide_value=True,
                                             bury_wide_k=48, bury_two_stage=config, **small)
    try:
        name, = registered
        assert "-bury-hybrid-bwv-bts-" in name
        built = make_bot(name, seed=3)
        assert built.bury_two_stage == config
        assert built.bury_recipe_identity["wide_value"] == {"chooser": bwv.CHOOSER, "k": 48,
                                                            "two_stage": config.identity()}
        plain, = pv.pv_registry_entries(path, sha256=sha, bury_arm="hybrid", bury_config=BURY,
                                        bury_serving_budget_seconds=2, bury_wide_value=True,
                                        bury_wide_k=48, **small)
        assert "-bwv-bts-" not in plain and plain != name
        seen = {}

        class Probe(pv.PVSearchBuryBot):
            def __init__(self, *a, **kw):
                seen.clear()
                seen.update(kw)
                super().__init__(*a, **kw)
        pv.make_pv_search_bot(path, sha256=sha, bury_arm="hybrid", bury_config=BURY,
                              bot_factory=Probe, bury_wide_value=True, **small)
        assert "bury_two_stage" not in seen                  # off: the call it always was
        pv.make_pv_search_bot(path, sha256=sha, bury_arm="hybrid", bury_config=BURY,
                              bot_factory=Probe, bury_wide_value=True, bury_two_stage=config,
                              **small)
        assert seen["bury_two_stage"] == config
        import pickle
        again = pickle.loads(pickle.dumps(copy.deepcopy(built)))
        assert again.bury_two_stage == config
    finally:
        for n in registered:
            REGISTRY.pop(n, None)


def test_exports():
    assert set(bts.__all__) == {
        "TOKEN", "RECORD_KEY", "CHOOSER", "TOP_DEFAULT", "WORLDS_DEFAULT", "TRICKS_DEFAULT",
        "MARGIN_DEFAULT", "Z_DEFAULT", "SECONDS_DEFAULT", "TOP_MAX", "WORLDS_MAX", "TRICKS_MAX",
        "Z_MAX", "SECONDS_MAX", "RESERVE_SECONDS", "SEED_LABEL", "TwoStageConfig",
        "StageTwoExpired", "stage_two_deadline", "terminal_value", "score_common_worlds",
        "stage_two_choice", "run_stage_two"}

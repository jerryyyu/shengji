"""The OPTIONAL policy-played value leaf of the pv-search bot
(``leaf_policy_first_trick``, ``SHENGJI_PV_LEAF_POLICY_FIRST_TRICK``, token
``lpft``; Jerry 2026-10-11: "where we use heuristics, it may be better to use
the model"): in both value leaves -- the bury scoring of the hybrid/value arms
(`cwv_bury.score_bury_candidates`) and the value declaration's outcome position
(`value_declare.declare_outcome_position`) -- the first trick the frozen
encoder needs is played by the policy head's argmax over each seat's legal
actions (`leaf_first_trick.PolicyFirstTrick`) instead of the heuristic.

Torch-free and package-free: stub predictors and stub evaluators on the real
engine, the real heuristic, the real enumeration and the real leaves.
Witnesses: (a) off: the release names, digest and payload are unchanged, the
bury choice and the declare sequence on seeded states are those of a bot
whose predictor would raise (no policy call reaches a leaf), the records say
``heuristic``; (b) names: the token is last, the digest moves, the env refuses
bad values, the rule refuses a bot with no leaf it changes; (c) on: every
play of the leaf's first trick is the stub policy's argmax over the legal set
(the batch player, the sequential player and a manual argmax agree on both
leaves; the bot's scored positions carry that trick); (d) a predictor that
raises, returns garbage or an empty legal set falls back to the heuristic
seat by seat with the count recorded (all seats: the off decision); (e) a
budget that expires INSIDE the leaf falls back to the stage's incumbent (the
heuristic bury; the heuristic declaration); (f) the leaf helper's own
contract (exclusive first-trick arguments; counters; a deadline is never
swallowed).
"""
import copy
import time
import tomllib
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from shengji.ai.cwv_policy import default_finisher
from shengji.ai.heuristic import HeuristicBot
from shengji.harvest.legal import enumerate_legal
from shengji.train import cwv_bury
from shengji.train import cwv_bury_policy as bury_policy
from shengji.train import leaf_first_trick as lft
from shengji.train import pv_search_policy as pv
from shengji.train import value_declare as vdm
from shengji.train.cwv_bury_diagnostic import capture_state, reopen_state
from shengji.train.cwv_prior_admission import action_scores
from shengji.train.policy_prior import CARD_INDEX, N_CARDS, input_dim
from test_pv_adaptive_worlds import RELEASE42_ENV, RELEASE42_NAME
from test_pv_admission_rules import (PRODUCTION_ENV, PRODUCTION_SHA, names,
                                     production_package)  # noqa: F401
from test_pv_declare_first_round import RELEASE43_VD, drive as drive_declare, fresh as fresh_deal
from test_pv_value_declare import NTEvaluator

FLAG = "SHENGJI_PV_LEAF_POLICY_FIRST_TRICK"
VD = "SHENGJI_PV_VALUE_DECLARE"
ASAP = "SHENGJI_PV_DECLARE_ASAP_FIRST"
HEURISTIC = HeuristicBot()
#: release 44 (fly.toml at this head; checkpoint id stubbed) and with the flag
RELEASE44_NAME = RELEASE43_VD
RELEASE44_LPFT = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-lpft-r157694cf-bury-hybrid-e5d85f7dcf5a"
BURY = bury_policy.CWVBuryConfig(max_candidates=4, model_worlds=2, selection_worlds=2, alternatives=1)
SMALL = dict(worlds=2, candidates=8, cap=4000, batch_size=128)


# ------------------------------------------------------------ stubs

#: fixed log-odds vectors with no exact ties between action sums: every card
#: negative (the argmax over any legal set is a SINGLE: the card with the
#: highest log-odds among the legal ones; a pair doubles the penalty, a throw
#: adds penalties), and a mixed vector (positive cards make throws attractive)
_RNG = np.random.default_rng(20261011)
NEGATIVE = -1.0 - _RNG.uniform(0.0, 1.0, N_CARDS)
MIXED = _RNG.normal(0.0, 1.0, N_CARDS)


class CountingPredict:
    """The all-negative log-odds; counts calls and rows.  Differs from the heuristic."""
    log_odds = NEGATIVE

    def __init__(self):
        self.calls = 0
        self.rows = 0

    def __call__(self, X):
        X = np.asarray(X)
        assert X.ndim == 2 and X.shape[1] == input_dim(2)
        self.calls += 1
        self.rows += len(X)
        return np.tile(self.log_odds, (len(X), 1))


class ThrowPredict(CountingPredict):
    """The mixed log-odds (the throw-happy policy)."""
    log_odds = MIXED


class RaisingPredict(CountingPredict):
    def __call__(self, X):
        self.calls += 1
        raise RuntimeError("policy head failed")


class GarbagePredict(CountingPredict):
    """The wrong shape, then NaN: both are refused as log-odds."""

    def __call__(self, X):
        self.calls += 1
        if self.calls % 2:
            return np.zeros((len(X), N_CARDS - 1))
        out = np.zeros((len(X), N_CARDS))
        out[0, 0] = np.nan
        return out


class SleepingPredict(CountingPredict):
    def __init__(self, seconds):
        super().__init__()
        self.seconds = seconds

    def __call__(self, X):
        time.sleep(self.seconds)
        return super().__call__(X)


class TrickEvaluator:
    """A real-looking value head: a deterministic function of the position's
    first trick AND its buried cards, so the leaf's trick moves the values and
    two burys can be told apart.  Records every scored position."""
    backend = "numpy"
    max_batch = 128

    def __init__(self):
        self.calls = 0
        self.positions = []

    def score(self, positions, seat):
        self.calls += 1
        self.positions.extend(copy.deepcopy(positions))
        out = []
        for p in positions:
            assert len(p.history) == 1 and p.trick is not None and not p.trick.plays
            trick = sum(CARD_INDEX[c] for play in p.history[0].plays for c in play.cards)
            buried = sum(CARD_INDEX[c] for c in p.buried)
            out.append(((trick * 7 + buried * 3) % 101) / 101.0 - 0.5)
        return np.array(out)


# ------------------------------------------------------------ builders

def served(predict=None, evaluator=None, budget=None, seed=17, **rules):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, serving_budget_seconds=budget,
                               **SMALL, **rules)
    return pv.PVSearchBot(predict or CountingPredict(), evaluator=evaluator or NTEvaluator(),
                          version=2, config=config, checkpoint="/dev/null", seed=seed)


def served_bury(predict=None, evaluator=None, arm="value", bury_budget=None, seed=17, **rules):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, **SMALL, **rules)
    return pv.PVSearchBuryBot(predict or CountingPredict(), evaluator=evaluator or TrickEvaluator(),
                              version=2, config=config, checkpoint="/dev/null", seed=seed,
                              bury_arm=arm, bury_config=BURY,
                              bury_serving_budget_seconds=bury_budget)


def bury_state(index):
    rnd = reopen_state(capture_state(index))
    assert rnd.phase == "bury"
    return rnd


def fly_env():
    """The RELEASE-44 env: production's fly.toml minus the two wide-bury lines and the six
    exact-endgame lines.

    Production is release 46 (release 44 + SHENGJI_PV_BURY_WIDE_VALUE/_K, #974, + the
    SHENGJI_PV_EXACT_* search, #1039), so the release-44 identities here and in the modules
    that import this helper are derived from the documented rollbacks."""
    env = tomllib.loads((Path(__file__).parents[2] / "fly.toml").read_text())["env"]
    assert env.get(VD) == "1"
    assert (env.get("SHENGJI_PV_BURY_WIDE_VALUE"), env.get("SHENGJI_PV_BURY_WIDE_K")) == ("1", "64")
    return {k: v for k, v in env.items()
            if k not in ("SHENGJI_PV_BURY_WIDE_VALUE", "SHENGJI_PV_BURY_WIDE_K")
            and not k.startswith("SHENGJI_PV_EXACT_")}


def best_single(cards, log_odds=NEGATIVE):
    """`CountingPredict`'s argmax over a set holding singles: its highest card."""
    return [max(cards, key=lambda c: log_odds[CARD_INDEX[c]])]


def expected_lead(position):
    return best_single(position.hands[position.turn])


def trick_plays(position):
    """The engine's record of the first trick: what was ACTUALLY played (a
    doomed throw is forced to its component by `Round.play`)."""
    return [(play.seat, list(play.cards)) for play in position.history[0].plays]


def manual_first_trick(position, predict, cap=None):
    """The policy argmax trick, computed by hand from the harness pieces -- the
    served admission's way: the COMPLETE `enumerate_legal` set (uncapped and
    asserted complete; a 25-card hand can hold more than the served 4000) scored
    by `action_scores`, first max.  ``(submitted actions, engine plays)``."""
    from shengji.train.policy_prior import flat_input, root_tensors
    position = copy.deepcopy(position)
    submitted = []
    for _ in range(4):
        seat = position.turn
        legal = enumerate_legal(position, seat, cap=cap)
        assert legal.complete
        actions = [list(a) for a in legal.actions]
        row = flat_input(root_tensors(position, seat, 2), 2)[None].astype(np.float32)
        scores = action_scores(np.asarray(predict(row)), actions)[0]
        best = min(range(len(actions)), key=lambda i: (-scores[i], i))
        submitted.append((seat, list(actions[best])))
        position.play(seat, actions[best])
    return submitted, trick_plays(position)


def pre_trick_positions(kind, seed=3):
    """Leaf positions with the first trick still to play: the bury leaf's
    (`_post_bury_validated` on sampled worlds) or the declare leaf's
    (`declare_outcome_position(first_trick=False)`)."""
    if kind == "bury":
        from shengji.ai.cwv_policy import sample_worlds
        from shengji.ai.registry import make_bot
        rnd = bury_state(65)
        banker = rnd.banker
        worlds, _ = sample_worlds(make_bot("mc-s0-report-lcb", seed=seed), rnd, banker, 3)
        candidates = cwv_bury.bury_candidates(rnd, make_bot("mc-s0-report-lcb", seed=seed + 1))[:2]
        out = []
        for hands, _buried in worlds:
            canonical = cwv_bury._validated_world_hands(rnd, hands, banker)
            for candidate in candidates:
                out.append(cwv_bury._post_bury_validated(rnd, banker, canonical, candidate))
        return out
    rnd = fresh_deal(seed, True)
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        if rnd.declare_options(seat):
            break
    options = rnd.declare_options(seat)
    assert options
    rng = vdm.decision_rng(0, rnd, seat)
    out = []
    for _ in range(3):
        hands, kitty = vdm.sample_declare_world(rnd, seat, rng)
        for option in (options[0], None):
            out.append(vdm.declare_outcome_position(rnd, seat, hands, kitty, option, first_trick=False))
    return out


# ------------------------------------------------------------ (a) off: identity

def test_release_names_digest_and_payload_unchanged_when_off(production_package):
    assert names(fly_env()) == [RELEASE44_NAME]
    assert names(RELEASE42_ENV) == [RELEASE42_NAME]
    for raw in ("0", ""):
        assert names({**fly_env(), FLAG: raw}) == [RELEASE44_NAME]
        assert names({**RELEASE42_ENV, FLAG: raw}) == [RELEASE42_NAME]
    config = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0)
    assert pv.recipe_digest(config) == "4a09aef5"
    assert "leaf_policy_first_trick" not in pv.recipe_payload(config)
    on = pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, value_declare=True))
    assert "leaf_policy_first_trick" not in on
    assert on["value_declare_model"] == vdm.MODEL
    assert pv.PVSearchBot.leaf_policy_first_trick is False
    assert pv.PVSearchBot._leaf_bury_arm is None
    assert "heuristic-first-trick" in vdm.MODEL


@pytest.mark.parametrize("arm", ["hybrid", "value"])
@pytest.mark.parametrize("index", [65, 66, 67])
def test_off_bury_makes_no_policy_call_and_the_record_says_heuristic(arm, index):
    """The off bury on a predictor that would RAISE equals the off bury on a
    predictor that would differ: no policy call reaches the leaf."""
    rnd = bury_state(index)
    raising = served_bury(RaisingPredict(), arm=arm)
    differing = served_bury(CountingPredict(), arm=arm)
    a = raising.decide_bury(copy.deepcopy(rnd), rnd.banker)
    b = differing.decide_bury(copy.deepcopy(rnd), rnd.banker)
    assert a == b
    assert raising.predict.calls == 0 and differing.predict.calls == 0
    for bot in (raising, differing):
        record = bot.last_bury_record
        assert record["schema"] == "cwv-bury-policy-v1"
        assert record["leaf_first_trick"] == "heuristic"
        assert record["leaf_first_trick_fallbacks"] == 0
        assert "leaf_policy_first_trick" not in vars(bot)
    assert raising.last_bury_record["model_means"] == differing.last_bury_record["model_means"]
    assert raising.last_bury_record["picked_index"] == differing.last_bury_record["picked_index"]
    # every scored leaf carries exactly one heuristic-played trick
    for position in raising.evaluator.positions:
        assert len(position.history) == 1 and len(position.history[0].plays) == 4


@pytest.mark.parametrize("seed", range(8))
def test_off_declare_makes_no_policy_call_and_the_record_says_heuristic(seed):
    raising = served(RaisingPredict(), NTEvaluator(), value_declare=True, value_declare_worlds=4)
    differing = served(CountingPredict(), NTEvaluator(), value_declare=True, value_declare_worlds=4)
    got = {}
    for label, bot in (("raising", raising), ("differing", differing)):
        rows = []

        def check(before, seat, final, choice, record, rows=rows):
            rows.append((seat, final, choice))
            if record is not None:
                assert record["leaf_first_trick"] == "heuristic"
                assert record["leaf_first_trick_fallbacks"] == 0
        drive_declare(fresh_deal(seed, seed % 2 == 0), bot, check)
        got[label] = rows
        assert bot.predict.calls == 0
        assert "leaf_policy_first_trick" not in vars(bot)
    assert got["raising"] == got["differing"]


def test_off_leaf_helpers_are_untouched():
    """The leaves' flag-off calls are the pre-rule ones: the heuristic policy
    position by position, and `declare_outcome_position` plays the trick."""
    rnd = bury_state(65)
    from shengji.ai.cwv_policy import sample_worlds
    from shengji.ai.registry import make_bot
    worlds, _ = sample_worlds(make_bot("mc-s0-report-lcb", seed=5), rnd, rnd.banker, 2)
    candidates = cwv_bury.bury_candidates(rnd, make_bot("mc-s0-report-lcb", seed=6))[:2]
    evaluator = TrickEvaluator()
    values = cwv_bury.score_bury_candidates(rnd, candidates, worlds, evaluator,
                                            first_trick_policy=HeuristicBot())
    assert values.shape == (2, 2)
    with pytest.raises(cwv_bury.BuryValueError, match="exclusive"):
        cwv_bury.score_bury_candidates(rnd, candidates, worlds, evaluator,
                                       first_trick_policy=HeuristicBot(),
                                       first_trick_batch=lambda positions: None)
    for position in pre_trick_positions("declare"):
        assert position.phase == "play" and not position.history and position.turn == position.banker
    played = vdm.declare_outcome_position(*_declare_args())
    assert len(played.history) == 1


def _declare_args(seed=3):
    rnd = fresh_deal(seed, True)
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        if rnd.declare_options(seat):
            break
    hands, kitty = vdm.sample_declare_world(rnd, seat, vdm.decision_rng(0, rnd, seat))
    return rnd, seat, hands, kitty, rnd.declare_options(seat)[0]


# ------------------------------------------------------------ (b) names, env, refusals

def test_token_is_last_digest_moves_and_payload_names_the_policy_leaf(production_package):
    assert names({**fly_env(), FLAG: "1"}) == [RELEASE44_LPFT]
    lpft, = names({**RELEASE42_ENV, FLAG: "1"})            # hybrid bury: a leaf exists
    assert lpft.startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-lpft-r")
    asap, = names({**RELEASE42_ENV, ASAP: "1", FLAG: "1"})
    assert asap.startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-asap-lpft-r")
    vd, = names({**RELEASE42_ENV, VD: "1", "SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST": "1", FLAG: "1"})
    assert vd.startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-vd-vdef-lpft-r")
    assert pv.RULE_TOKENS[-8:-1] == (("value_declare", "vd"), ("value_declare_every_first", "vdef"),
                                     ("value_declare_served_bury", "vdsb"),
                                     ("value_declare_pass_worlds", "vdpw"),
                                     ("value_declare_wait", "vdw"),
                                     ("declare_asap_first", "asap"),
                                     ("leaf_policy_first_trick", "lpft"))   # then the diagnostic orc
    assert pv.RULE_FLAGS["LEAF_POLICY_FIRST_TRICK"] == "leaf_policy_first_trick"
    base = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA)
    on = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, leaf_policy_first_trick=True)
    vd_on = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, value_declare=True,
                              leaf_policy_first_trick=True)
    vd_off = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, value_declare=True)
    assert len({pv.recipe_digest(c) for c in (base, on, vd_on, vd_off)}) == 4
    assert pv.recipe_payload(on)["leaf_policy_first_trick"] is True
    assert pv.recipe_payload(vd_on)["value_declare_model"] == vdm.MODEL_POLICY_FIRST_TRICK
    assert "policy-first-trick" in vdm.MODEL_POLICY_FIRST_TRICK
    assert vdm.MODEL_POLICY_FIRST_TRICK != vdm.MODEL
    assert pv.recipe_payload(vd_off)["value_declare_model"] == vdm.MODEL


@pytest.mark.parametrize("bad", ["2", "true", "yes", " 1"])
def test_env_flag_refuses_anything_but_0_or_1(bad):
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: bad})


def test_env_parses_the_flag():
    assert pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "1"})["leaf_policy_first_trick"] is True
    assert "leaf_policy_first_trick" not in pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "0"})


def test_the_rule_refuses_a_bot_with_no_leaf_it_changes(production_package):
    no_bury = {k: v for k, v in PRODUCTION_ENV.items() if not k.startswith("SHENGJI_PV_BURY")}
    with pytest.raises(pv.PVSearchPolicyError, match="needs a value leaf"):
        names({**no_bury, FLAG: "1"})
    with pytest.raises(pv.PVSearchPolicyError, match="needs a value leaf"):
        names({**PRODUCTION_ENV, "SHENGJI_PV_BURY_ARM": "mc", FLAG: "1"})
    with pytest.raises(pv.PVSearchPolicyError, match="needs a value leaf"):
        names({**PRODUCTION_ENV, "SHENGJI_PV_BURY_ARM": "heuristic", FLAG: "1"})
    assert names({**no_bury, VD: "1", FLAG: "1"})            # the declare leaf suffices
    assert names({**PRODUCTION_ENV, "SHENGJI_PV_BURY_ARM": "value", FLAG: "1"})
    with pytest.raises(pv.PVSearchPolicyError, match="needs a value leaf"):
        served(leaf_policy_first_trick=True)
    for arm in ("mc", "heuristic"):
        with pytest.raises(pv.PVSearchPolicyError, match="needs a value leaf"):
            served_bury(arm=arm, leaf_policy_first_trick=True)
    assert served(value_declare=True, leaf_policy_first_trick=True).leaf_policy_first_trick is True
    for arm in ("hybrid", "value"):
        assert served_bury(arm=arm, leaf_policy_first_trick=True).leaf_policy_first_trick is True
    assert served_bury(arm="mc", value_declare=True, leaf_policy_first_trick=True).leaf_policy_first_trick
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        served(value_declare=True, leaf_policy_first_trick=1)
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, leaf_policy_first_trick="1"))


# ------------------------------------------------------------ (c) on: the leaf is the policy argmax

@pytest.mark.parametrize("kind", ["bury", "declare"])
@pytest.mark.parametrize("predict_class", [CountingPredict, ThrowPredict])
def test_batch_sequential_and_manual_argmax_agree_on_both_leaves(kind, predict_class):
    positions = pre_trick_positions(kind)
    assert len(positions) == 6
    manual = [manual_first_trick(p, predict_class()) for p in positions]
    sequential = []
    for position, (submitted, _) in zip(positions, manual):
        player = lft.PolicyFirstTrick(predict_class(), 2, HeuristicBot())
        p = copy.deepcopy(position)
        actions = []
        for _ in range(4):
            seat = p.turn
            action = player.decide_play(p, seat)
            actions.append((seat, list(action)))
            p.play(seat, action)
        assert actions == submitted                   # the same submitted actions ...
        sequential.append(trick_plays(p))             # ... and so the same engine plays
        assert player.policy_plays == 4 and player.fallbacks == 0 and player.batches == 4
    batched = lft.PolicyFirstTrick(predict_class(), 2, HeuristicBot())
    batch = [copy.deepcopy(p) for p in positions]
    batched.play_first_tricks(batch)
    assert batched.batches == 4                       # one predictor call per play
    assert batched.predict.rows == 4 * len(positions)
    assert batched.policy_plays == 4 * len(positions) and batched.fallbacks == 0
    batched_plays = [trick_plays(p) for p in batch]
    for position, plays, seq, (_, man) in zip(batch, batched_plays, sequential, manual):
        assert len(position.history) == 1 and position.trick is not None and not position.trick.plays
        assert plays == seq == man
    if predict_class is CountingPredict:
        # the known argmax: the single of the leader's highest-log-odds card
        for position, plays in zip(positions, batched_plays):
            assert plays[0] == (position.turn, expected_lead(position))
            assert all(len(cards) == 1 for _, cards in plays)
    heuristic = []
    for position in positions:
        p = copy.deepcopy(position)
        for _ in range(4):
            seat = p.turn
            p.play(seat, default_finisher().decide_play(p, seat))
        heuristic.append(trick_plays(p))
    assert heuristic != batched_plays                 # the stub policy does differ


@pytest.mark.parametrize("kind", ["bury", "declare"])
@pytest.mark.parametrize("seed", range(6))
def test_structured_argmax_equals_the_complete_enumeration_argmax(kind, seed):
    """The closed-form choice (`best_lead`, `best_follow`) is the argmax of the
    admission's score over the COMPLETE legal set at every play of every leaf,
    for a mixed log-odds vector (throws, pairs and singles all win somewhere)."""
    log_odds = np.random.default_rng(seed).normal(0.0, 1.0, N_CARDS)
    kinds = Counter()
    for position in pre_trick_positions(kind, seed=seed + 10):
        for _ in range(4):
            seat = position.turn
            legal = enumerate_legal(position, seat, cap=None)
            assert legal.complete
            actions = [list(a) for a in legal.actions]
            scores = action_scores(log_odds[None, :], actions)[0]
            expected = actions[int(np.argmax(scores))]
            chosen = lft.PolicyFirstTrick._choose(position, seat, log_odds)
            assert chosen == expected, (kind, seed, legal.kind, chosen, expected)
            kinds[(legal.kind, len(chosen))] += 1
            position.play(seat, chosen)
    assert ("lead", 1) in kinds or any(k == "lead" and n > 1 for k, n in kinds)


@pytest.mark.parametrize("arm", ["hybrid", "value"])
def test_on_bury_scores_leaves_whose_first_trick_is_the_policy_argmax(arm):
    rnd = bury_state(65)
    bot = served_bury(CountingPredict(), arm=arm, leaf_policy_first_trick=True)
    off = served_bury(CountingPredict(), arm=arm)
    chosen = bot.decide_bury(copy.deepcopy(rnd), rnd.banker)
    assert Counter(chosen) <= Counter(rnd.hands[rnd.banker]) and len(chosen) == 8
    record = bot.last_bury_record
    assert record["schema"] == "cwv-bury-policy-v1"
    assert record["leaf_first_trick"] == "policy" and record["leaf_first_trick_fallbacks"] == 0
    positions = bot.evaluator.positions
    assert len(positions) == record["model_positions"] == record["candidate_count"] * 2
    assert bot.predict.calls == 4 and bot.predict.rows == 4 * len(positions)
    for position in positions:
        plays = position.history[0].plays
        leader = plays[0].seat
        before = sorted(position.hands[leader] + list(plays[0].cards))
        assert plays[0].cards == best_single(before)
        assert all(len(play.cards) == 1 for play in plays)
    # the same decision as the off bot only by coincidence: the leaves differ
    off.decide_bury(copy.deepcopy(rnd), rnd.banker)
    assert off.last_bury_record["model_means"] != record["model_means"]
    assert off.evaluator.calls == bot.evaluator.calls


def test_on_declare_scores_leaves_whose_first_trick_is_the_policy_argmax():
    rnd, seat, _, _, _ = _declare_args()
    evaluator = TrickEvaluator()
    bot = served(CountingPredict(), evaluator, value_declare=True, value_declare_worlds=3,
                 leaf_policy_first_trick=True)
    choice = bot.decide_declare(rnd, seat, final=True)      # the grace window admits
    record = bot.last_declare_record
    assert record is not None and record["evaluated"] and record["gate"] == "final"
    assert record["leaf_first_trick"] == "policy" and record["leaf_first_trick_fallbacks"] == 0
    assert record["worlds_completed"] == 3
    assert choice is None or choice in rnd.declare_options(seat)
    outcomes = record["outcomes"].count("|") + 1
    assert len(evaluator.positions) == 3 * outcomes
    assert bot.predict.calls == 4 and bot.predict.rows == 4 * len(evaluator.positions)
    # the scored positions ARE the batch player's on the same worlds and outcomes
    rng = vdm.decision_rng(bot.seed, rnd, seat)
    candidates = [o for _, o in vdm.candidate_outcomes(rnd, seat, rnd.declare_options(seat),
                                                       HEURISTIC.decide_declare(rnd, seat, final=True))]
    rebuilt = []
    for _ in range(3):
        hands, kitty = vdm.sample_declare_world(rnd, seat, rng)
        for option in candidates:
            rebuilt.append(vdm.declare_outcome_position(rnd, seat, hands, kitty, option,
                                                        first_trick=False))
    lft.PolicyFirstTrick(CountingPredict(), 2, HeuristicBot()).play_first_tricks(rebuilt)
    for scored, again in zip(evaluator.positions, rebuilt):
        assert [(p.seat, p.cards) for p in scored.history[0].plays] == \
            [(p.seat, p.cards) for p in again.history[0].plays]
        assert scored.hands == again.hands
    # and differ from the heuristic leaf's values
    off = served(CountingPredict(), TrickEvaluator(), value_declare=True, value_declare_worlds=3)
    off.decide_declare(rnd, seat, final=True)
    assert off.last_declare_record["outcome_means"] != record["outcome_means"]
    assert off.evaluator.calls == evaluator.calls


# ------------------------------------------------------------ (d) fallback to the heuristic seat by seat

@pytest.mark.parametrize("predict_class", [RaisingPredict, GarbagePredict])
def test_a_failing_predictor_falls_back_to_the_heuristic_with_the_count(predict_class):
    rnd = bury_state(65)
    bot = served_bury(predict_class(), arm="value", leaf_policy_first_trick=True)
    off = served_bury(CountingPredict(), arm="value")
    assert bot.decide_bury(copy.deepcopy(rnd), rnd.banker) == off.decide_bury(copy.deepcopy(rnd), rnd.banker)
    record = bot.last_bury_record
    assert record["schema"] == "cwv-bury-policy-v1"
    assert record["leaf_first_trick"] == "policy"
    assert record["leaf_first_trick_fallbacks"] == 4 * record["model_positions"] > 0
    assert record["model_means"] == off.last_bury_record["model_means"]
    assert bot.predict.calls == 4
    rnd2, seat, _, _, _ = _declare_args()
    declare = served(predict_class(), NTEvaluator(), value_declare=True, value_declare_worlds=2,
                     leaf_policy_first_trick=True)
    plain = served(CountingPredict(), NTEvaluator(), value_declare=True, value_declare_worlds=2)
    assert declare.decide_declare(copy.deepcopy(rnd2), seat, final=True) == \
        plain.decide_declare(copy.deepcopy(rnd2), seat, final=True)
    record = declare.last_declare_record
    assert record["evaluated"] and record["fallback_reason"] is None
    assert record["leaf_first_trick"] == "policy"
    assert record["leaf_first_trick_fallbacks"] == 4 * 2 * (record["outcomes"].count("|") + 1)
    assert record["outcome_means"] == plain.last_declare_record["outcome_means"]


def test_a_seat_the_policy_cannot_rank_falls_back_for_that_seat_only(monkeypatch):
    """The lead choice returns nothing (or raises): the leader is the
    heuristic's, the three followers the policy's."""
    for failure in (lambda *a: None, lambda *a: 1 / 0):
        monkeypatch.setattr(lft, "best_lead", failure)
        positions = pre_trick_positions("bury")
        player = lft.PolicyFirstTrick(CountingPredict(), 2, HeuristicBot())
        player.play_first_tricks(positions)
        assert player.fallbacks == len(positions) and player.policy_plays == 3 * len(positions)
        assert player.batches == 4
        for position in positions:
            plays = position.history[0].plays
            assert len(position.history) == 1 and len(plays) == 4
            assert plays[0].seat == position.banker       # the banker led (heuristic)
    monkeypatch.undo()
    monkeypatch.setattr(lft, "best_follow", lambda *a, **k: None)
    positions = pre_trick_positions("bury")
    player = lft.PolicyFirstTrick(CountingPredict(), 2, HeuristicBot())
    player.play_first_tricks(positions)
    assert player.fallbacks == 3 * len(positions) and player.policy_plays == len(positions)


def test_an_incomplete_follow_enumeration_falls_back():
    positions = pre_trick_positions("bury")
    position = positions[0]
    position.play(position.turn, HEURISTIC.decide_play(position, position.turn))
    seat = position.turn
    lead = position.trick.plays[0].cards
    assert lft.best_follow(position.hands[seat], lead, position.ordering, NEGATIVE, CARD_INDEX) \
        is not None
    case, h_suit, _off, n = lft._follow_case(list(position.hands[seat]), list(lead), position.ordering)
    if case == "in-suit":
        assert lft.best_follow(position.hands[seat], lead, position.ordering, NEGATIVE, CARD_INDEX,
                               cap=0) is None


# ------------------------------------------------------------ (e) a budget expiring INSIDE the leaf

def test_bury_budget_expiring_inside_the_leaf_falls_back_to_the_heuristic_incumbent():
    rnd = bury_state(65)
    incumbent = HEURISTIC.decide_bury(copy.deepcopy(rnd), rnd.banker)
    bot = served_bury(SleepingPredict(0.6), arm="value", bury_budget=0.5,
                      leaf_policy_first_trick=True)
    before = bot.sampler.rng.getstate()
    assert bot.decide_bury(copy.deepcopy(rnd), rnd.banker) == list(incumbent)
    record = bot.last_bury_record
    assert record["schema"] == "cwv-bury-fallback-v1" and record["reason"] == "budget"
    assert record["error_class"] == "BuryBudgetExceeded"
    assert record["leaf_first_trick"] == "policy"
    assert record["leaf_first_trick_fallbacks"] == 0
    assert bot.predict.calls >= 1                         # the leaf had begun
    assert bot.evaluator.calls == 0                       # no batch was scored
    assert bot.sampler.rng.getstate() == before
    # the same budget with the flag off completes (no sleeping call in the leaf)
    off = served_bury(SleepingPredict(0.6), arm="value", bury_budget=0.5)
    off.decide_bury(copy.deepcopy(rnd), rnd.banker)
    assert off.last_bury_record["schema"] == "cwv-bury-policy-v1" and off.predict.calls == 0


def test_declare_budget_expiring_inside_the_leaf_falls_back_to_the_heuristic_choice():
    rnd, seat, _, _, _ = _declare_args()
    heuristic = HEURISTIC.decide_declare(copy.deepcopy(rnd), seat, final=True)
    bot = served(SleepingPredict(0.6), NTEvaluator(), budget=0.5, value_declare=True,
                 value_declare_worlds=2, leaf_policy_first_trick=True)
    gate_choice, admitted = bot.declare_gate(copy.deepcopy(rnd), seat, final=True)
    assert admitted and gate_choice == heuristic
    assert bot.decide_declare(copy.deepcopy(rnd), seat, final=True) == heuristic
    record = bot.last_declare_record
    assert not record["evaluated"] and record["fallback_reason"] == "hard_budget"
    assert record["fallback_error"] == "PVSearchBudgetExceeded"
    assert record["played"] == record["heuristic"] and record["changed"] is False
    assert record["leaf_first_trick"] == "policy" and record["leaf_first_trick_fallbacks"] == 0
    assert record["worlds_completed"] == 0 and bot.evaluator.calls == 0
    assert bot.predict.calls >= 1


def test_the_leaf_player_never_swallows_the_deadline():
    class Deadline(Exception):
        pass
    ticks = []

    def check():
        ticks.append(1)
        if len(ticks) >= 3:
            raise Deadline()
    player = lft.PolicyFirstTrick(RaisingPredict(), 2, HeuristicBot(), check_budget=check)
    positions = pre_trick_positions("declare")[:2]
    with pytest.raises(Deadline):
        player.play_first_tricks(positions)
    # play 1: before encoding, after encoding (the predictor then raises and both
    # seats fall back); play 2: before encoding -> the deadline
    assert len(ticks) == 3
    assert all(len(p.history) == 0 and len(p.trick.plays) == 1 for p in positions)
    assert player.fallbacks == 2                      # the raising predictor's first play
    with pytest.raises(Deadline):
        player.decide_play(positions[0], positions[0].turn)


def test_an_expiry_during_encoding_starts_no_predictor_call():
    """The check between the row encoding and the predictor dispatch: an
    expiry raised there (the second tick of a play) reaches the caller before
    the predictor runs, on both the batch and the sequential path."""
    class Deadline(Exception):
        pass
    ticks = []

    def check():
        ticks.append(1)
        if len(ticks) == 2:
            raise Deadline()
    predict = CountingPredict()
    player = lft.PolicyFirstTrick(predict, 2, HeuristicBot(), check_budget=check)
    positions = pre_trick_positions("declare")[:2]
    with pytest.raises(Deadline):
        player.play_first_tricks(positions)
    assert len(ticks) == 2 and predict.calls == 0 and player.batches == 0
    assert all(len(p.history) == 0 and not p.trick.plays for p in positions)
    assert player.fallbacks == 0 and player.policy_plays == 0
    ticks.clear()
    with pytest.raises(Deadline):
        player.decide_play(positions[0], positions[0].turn)
    assert len(ticks) == 2 and predict.calls == 0 and not positions[0].trick.plays


class ExpireOnFourthPredict(CountingPredict):
    """Codex's review-972 witness: the clock jumps past every deadline the
    moment the FOURTH policy batch (the trick's last play) returns."""

    def __init__(self, clock):
        super().__init__()
        self.clock = clock

    def __call__(self, X):
        result = super().__call__(X)
        if self.calls == 4:
            self.clock["expired"] = True
        return result


@pytest.fixture
def jumping_clock(monkeypatch):
    """`time.perf_counter` (the serving budgets' clock) plus 100 s once
    ``clock["expired"]`` is set."""
    clock = {"expired": False}
    real = time.perf_counter
    monkeypatch.setattr(time, "perf_counter",
                        lambda: real() + (100.0 if clock["expired"] else 0.0))
    return clock


def test_bury_expiry_on_the_fourth_policy_batch_starts_no_value_batch(jumping_clock):
    """Review 972 (Codex HOLD): the helper's final check, after the trick's
    last play and before `cwv_bury.score_bury_candidates.flush` scores the
    batch.  The stage still falls back to the heuristic incumbent; the value
    head is NEVER invoked."""
    rnd = bury_state(65)
    incumbent = HEURISTIC.decide_bury(copy.deepcopy(rnd), rnd.banker)
    bot = served_bury(ExpireOnFourthPredict(jumping_clock), arm="value", bury_budget=0.5,
                      leaf_policy_first_trick=True)
    assert bot.decide_bury(rnd, rnd.banker) == list(incumbent)
    record = bot.last_bury_record
    assert record["schema"] == "cwv-bury-fallback-v1" and record["reason"] == "budget"
    assert record["error_class"] == "BuryBudgetExceeded"
    assert bot.predict.calls == 4                         # the whole trick was played
    assert bot.evaluator.calls == 0                       # and no value batch began


def test_declare_expiry_on_the_fourth_policy_batch_starts_no_value_batch(jumping_clock):
    """Review 972 (Codex HOLD), the declare consumer
    (`PVSearchBot._value_declare_means.flush`)."""
    rnd, seat, _, _, _ = _declare_args()
    heuristic = HEURISTIC.decide_declare(copy.deepcopy(rnd), seat, final=True)
    bot = served(ExpireOnFourthPredict(jumping_clock), NTEvaluator(), budget=0.5,
                 value_declare=True, value_declare_worlds=2, leaf_policy_first_trick=True)
    assert bot.decide_declare(rnd, seat, final=True) == heuristic
    record = bot.last_declare_record
    assert not record["evaluated"] and record["fallback_reason"] == "hard_budget"
    assert record["fallback_error"] == "PVSearchBudgetExceeded"
    assert record["played"] == record["heuristic"] and record["changed"] is False
    assert record["worlds_completed"] == 0
    assert bot.predict.calls == 4                         # the whole trick was played
    assert bot.evaluator.calls == 0                       # and no value batch began


# ------------------------------------------------------------ (f) the screen wrapper carries the keys

def test_the_screen_wrapper_carries_the_leaf_keys():
    from shengji.train.search_screen import TimedPolicy
    policy = TimedPolicy(served(CountingPredict(), NTEvaluator(), value_declare=True,
                                value_declare_worlds=2, leaf_policy_first_trick=True))
    drive_declare(fresh_deal(5, True), policy)
    rows = policy.declare_decisions
    assert rows and all(r["leaf_first_trick"] == "policy" and r["leaf_first_trick_fallbacks"] == 0
                        for r in rows)
    assert set(lft.__all__) == {"FOLLOW_CAP", "TRICK_PLAYS", "PolicyFirstTrick", "best_lead",
                                "best_follow"}
    assert pv.LEAF_FIRST_TRICK_PLAYERS == ("heuristic", "policy")

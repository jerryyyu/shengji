"""#707 S9: telemetry-only sampler and transcript fields.

Torch-free: a stub predictor (fixed log-odds) and a stub evaluator (zeros) on
the real fixture round, production's sampler and the real engine.

Witnesses: the pv-search decision record carries PER-DECISION deltas of the
sampler's cumulative ``impossible_worlds`` / ``rejected_worlds`` counters; a
search-error fallback names its raise site (``error_stage``) and a bounded
``error_message`` -- on a forced public-void post-check failure, with the
void fallback visible in the same record; the screen trace keeps the new
fields as scalars; the screen round record keeps ``history_sha256_16`` and
adds the full ``history_sha256`` of the same serialization and the COMMITTED
transcript (``RoundLog.history``), which differs from the attempt on a failed
throw; and nothing a decision depends on moves: the same seed plays the same
cards with the same sampler stream, the records differ only by the new keys,
and the served recipe digest is unchanged.
"""
import copy
import hashlib
import json
import pickle
import random
import time

import numpy as np
import pytest

from shengji.ai.env import play_round
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.combos import decompose
from shengji.engine.legal import validate_lead
from shengji.harvest.legal import enumerate_legal
from shengji.oracle import screen as S
from shengji.train import pv_search_policy as pv
from shengji.train.search_screen import trace_fields
from test_policy_world_search import state

NEW_KEYS = {"impossible_worlds_delta", "rejected_worlds_delta"}
ERROR_KEYS = {"error_stage", "error_message"}


class ZeroEvaluator:
    backend = "numpy"
    max_batch = 128

    def score(self, leaves, seat):
        return np.zeros(len(leaves))


def predict(X):
    return np.tile(np.arange(54, dtype=np.float64), (len(X), 1))


def served(seed=5, worlds=8, serving_budget_seconds=None, **rules):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=worlds, candidates=4,
                               cap=400, batch_size=16,
                               serving_budget_seconds=serving_budget_seconds, **rules)
    return pv.PVSearchBot(predict, evaluator=ZeroEvaluator(), version=2, config=config,
                          checkpoint="/dev/null", seed=seed)


def positions(n=6):
    """``n`` decision points of the fixture round, heuristic play between them."""
    rnd = state()
    h = HeuristicBot()
    out = []
    while len(out) < n and rnd.phase == "play":
        out.append(copy.deepcopy(rnd))
        for _ in range(3):
            if rnd.phase != "play":
                break
            rnd.play(rnd.turn, h.decide_play(rnd, rnd.turn))
    assert len(out) == n
    return out


# ----------------------------------------------------- (i) per-decision deltas

def test_counter_deltas_are_per_decision_not_cumulative(monkeypatch):
    bumps = iter([(3, 1), (0, 2)])
    real = pv.sample_worlds

    def bumped(bot, *args, **kwargs):
        result = real(bot, *args, **kwargs)
        impossible, rejected = next(bumps)
        bot.impossible_worlds += impossible
        bot.rejected_worlds += rejected
        return result

    monkeypatch.setattr(pv, "sample_worlds", bumped)
    bot = served(seed=7)
    # a long-lived bot: the cumulative counters are already far from zero
    bot.sampler.impossible_worlds, bot.sampler.rejected_worlds = 100, 50
    first, second = positions(2)
    bot.decide_play(first, first.turn)
    rec = bot.last_decision_record
    assert rec["schema"] == pv.RECORD_SCHEMA
    assert (rec["impossible_worlds_delta"], rec["rejected_worlds_delta"]) == (3, 1)
    bot.decide_play(second, second.turn)
    rec = bot.last_decision_record
    assert (rec["impossible_worlds_delta"], rec["rejected_worlds_delta"]) == (0, 2)
    assert (bot.sampler.impossible_worlds, bot.sampler.rejected_worlds) == (103, 53)


def test_deltas_match_the_real_sampler_counters():
    bot = served(seed=11)
    for rnd in positions(4):
        before = (bot.sampler.impossible_worlds, bot.sampler.rejected_worlds)
        bot.decide_play(rnd, rnd.turn)
        rec = bot.last_decision_record
        assert rec["impossible_worlds_delta"] == bot.sampler.impossible_worlds - before[0]
        assert rec["rejected_worlds_delta"] == bot.sampler.rejected_worlds - before[1]


# ------------------------------------------- (ii) the error stage and message

def _voids_everywhere(monkeypatch):
    """After a normal draw, declare every sampled card's suit void for its
    holder, so the post-check (not the sampler) fails: the draw and its RNG
    use are production's own."""
    real = pv.sample_worlds

    def draw(bot, rnd, seat, n, *, mem, check_budget=None):
        worlds, attempts = real(bot, rnd, seat, n, mem=mem, check_budget=check_budget)
        bot.impossible_worlds += 2          # as the respect_voids=False fallback does
        for hands, _ in worlds:
            for s in range(4):
                if s != seat:
                    mem.voids[s].update(rnd.ordering.eff_suit(c) for c in hands[s])
        return worlds, attempts

    monkeypatch.setattr(pv, "sample_worlds", draw)


def test_void_check_failure_names_its_stage_and_message(monkeypatch):
    _voids_everywhere(monkeypatch)
    rnd = positions(1)[0]
    seat = rnd.turn
    bot = served(seed=13, serving_budget_seconds=60)
    before = bot.sampler.rng.getstate()
    anchor = HeuristicBot().decide_play(copy.deepcopy(rnd), seat)
    assert bot.decide_play(copy.deepcopy(rnd), seat) == list(anchor)
    rec = bot.last_decision_record
    assert rec["schema"] == pv.FALLBACK_SCHEMA and rec["reason"] == "search-error"
    assert rec["error_class"] == "PVSearchPolicyError"
    assert rec["error_stage"] == "world_sampling_void_check"
    assert rec["error_message"] == "policy world sampling violates public voids"
    assert rec["impossible_worlds_delta"] == 2 and rec["rejected_worlds_delta"] == 0
    assert bot.sampler.rng.getstate() == before            # the fallback's restore, unchanged
    # the screen trace keeps every new field, as a scalar
    trace = trace_fields(rec, skip=("played",))
    for key in NEW_KEYS | ERROR_KEYS:
        assert trace[key] == rec[key]
    # without a budget the error propagates, carrying the same stage
    strict = served(seed=13)
    with pytest.raises(pv.PVSearchPolicyError, match="public voids") as caught:
        strict.decide_play(copy.deepcopy(rnd), seat)
    assert caught.value.stage == "world_sampling_void_check"
    assert strict.last_decision_record is None


def test_error_message_is_bounded_and_unstaged_errors_say_none(monkeypatch):
    bot = served(seed=17, serving_budget_seconds=60)
    monkeypatch.setattr(bot, "_value_means",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x" * 500)))
    rnd = positions(1)[0]
    bot.decide_play(rnd, rnd.turn)
    rec = bot.last_decision_record
    assert rec["error_class"] == "RuntimeError" and rec["error_stage"] is None
    assert rec["error_message"] == "x" * pv.ERROR_MESSAGE_MAX


def test_stage_survives_pickling_and_defaults_to_none():
    exc = pv.PVSearchPolicyError("m", stage="admission_budget")
    revived = pickle.loads(pickle.dumps(exc))
    assert revived.stage == "admission_budget" and str(revived) == "m"
    assert pv.PVSearchPolicyError("m").stage is None
    assert pv.PVSearchBudgetExceeded("b").stage is None


def test_every_decision_time_raise_names_a_stage():
    import inspect
    source = inspect.getsource(pv.PVSearchBot)
    for stage in ("world_sampling_short", "world_sampling_void_check", "value_matrix_unfilled",
                  "admission_contract", "admission_budget"):
        assert f'stage="{stage}"' in source


# ------------------------------------------ (iii) the full transcript digest

def _legacy_digest(history):
    """``history_sha256_16`` exactly as it was computed before #707 S9."""
    payload = json.dumps([[seat, list(cards)] for seat, cards in history])
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def test_full_digest_is_the_same_serialization():
    log = play_round(_dealt(3), [HeuristicBot() for _ in range(4)], record=True)
    full = S._history_sha256(log.history)
    payload = json.dumps([[seat, list(cards)] for seat, cards in log.history])
    assert full == hashlib.sha256(payload.encode()).hexdigest() and len(full) == 64
    assert full[:16] == S._history_digest(log.history) == _legacy_digest(log.history)
    assert S._history_rows(log.history) == json.loads(payload)


def _dealt(seed):
    from shengji.engine.game import Game
    return Game(random.Random(seed))


# ------------------------- (iv) the committed transcript, with a failed throw

class Thrower:
    """The heuristic, except that each lead it first tries a throw the real
    engine refuses (checked against the true hands); records the attempts."""

    def __init__(self, log):
        self.log, self.h = log, HeuristicBot()

    def decide_play(self, rnd, seat):
        if rnd.trick is None or not rnd.trick.plays:
            others = [rnd.hands[s] for s in range(4) if s != seat]
            for action in enumerate_legal(rnd, seat, cap=4000).actions:
                if len(decompose(list(action), rnd.ordering).components) < 2:
                    continue
                if validate_lead(list(action), rnd.hands[seat], others, rnd.ordering)[1]:
                    self.log.append((seat, list(action)))
                    return list(action)
        return self.h.decide_play(rnd, seat)

    def __getattr__(self, name):
        return getattr(self.h, name)


def test_committed_history_is_the_engine_transcript_not_the_attempt(monkeypatch):
    captured, attempts = [], []
    real = S.play_round

    def capture(*args, **kwargs):
        log = real(*args, **kwargs)
        captured.append(log)
        return log

    monkeypatch.setattr(S, "play_round", capture)

    def factory(config, side, seed):
        return Thrower(attempts) if side == "arm" else HeuristicBot()

    for seed in range(1, 40):
        captured.clear()
        attempts.clear()
        record, _ = S.play_screen_round({"arm": "throw-test"}, 0, seed, 0,
                                        bot_factory=factory, counter_fn=lambda bots: {})
        if attempts:
            break
    assert attempts, "no seed produced a refused throw"
    log, = captured
    rows = [[seat, list(cards)] for seat, cards in log.history]
    assert record["committed_history"] == rows
    assert record["plays"] == len(rows)
    assert record["history_sha256"] == hashlib.sha256(json.dumps(rows).encode()).hexdigest()
    assert record["history_sha256_16"] == record["history_sha256"][:16] \
        == _legacy_digest(log.history)
    # the failed throw: what was committed is not what was attempted
    for seat, attempted in attempts:
        assert [seat, sorted(attempted)] not in [[s, sorted(c)] for s, c in rows]
    # the record round-trips through the shard's JSON
    assert json.loads(json.dumps(record))["committed_history"] == rows


# --------------------------------------------- (v) no behaviour change at all

def _strip(rec):
    return {k: v for k, v in rec.items()
            if k not in NEW_KEYS | ERROR_KEYS | {"seconds", "elapsed_seconds"}}


@pytest.mark.parametrize("budget", [None, 60])
@pytest.mark.parametrize("rules", [{}, {"refusal_constraints": True}])
def test_decisions_rng_and_records_are_unchanged(budget, rules):
    """The telemetry wraps ``_decide_play``; a twin driven through the bare
    ``_decide_play`` (no telemetry) plays the same cards, leaves the same
    sampler stream and counters, and differs only by the new keys."""
    ours = served(seed=19, serving_budget_seconds=budget, **rules)
    bare = served(seed=19, serving_budget_seconds=budget, **rules)
    for rnd in positions(6):
        seat = rnd.turn
        a = ours.decide_play(copy.deepcopy(rnd), seat)
        bare.last_decision_record = None
        b = pv.PVSearchBot._decide_play(bare, copy.deepcopy(rnd), seat, time.perf_counter())
        assert a == b
        assert ours.sampler.rng.getstate() == bare.sampler.rng.getstate()
        assert ours.sampler._sampler_snapshot() == bare.sampler._sampler_snapshot()
        assert set(ours.last_decision_record) - set(bare.last_decision_record) == NEW_KEYS
        assert _strip(ours.last_decision_record) == _strip(bare.last_decision_record)


def test_served_recipe_and_name_are_unchanged():
    """No config field moved: the default recipe payload has no new key and
    the production name is still the release-36 one (also pinned by
    ``test_bury_fly_config``)."""
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64)
    assert not any(key.endswith("_delta") or key.startswith("error_")
                   for key in pv.recipe_payload(config))

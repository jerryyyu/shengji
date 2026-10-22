"""The OPTIONAL belief deadline (``belief_deadline_ms``,
``SHENGJI_PV_BELIEF_DEADLINE_MS=<ms>``, token ``bwd<ms>`` after ``bw``): once the
belief path's clock passes the deadline, the history-legal worlds already
accepted are kept and the rest are proposals accepted without the history test;
a slow preparation is kept, never discarded for its time.

Torch-free and package-free (a uniform stand-in for the belief model).
Witnesses: (a) off, names, payloads and env recipes are unchanged; (b) a
deadline that is never reached draws the ``bw`` worlds, stream and record;
(c) a deadline that fires keeps the history-tested prefix, fills to W from the
proposal and records it; (d) a preparation over the limit falls back without
the flag and is kept with it; (e) the draw-level ``stop`` hook; (f) refusals.
"""
import copy

import numpy as np
import pytest

from shengji.ai import belief_numpy as bn
from shengji.ai import history_legality as HL
from shengji.ai.memory import Memory
from shengji.train import pv_search_policy as pv
from test_refusal_constraints import PRODUCTION_SHA
from test_world_history_legal import RELEASE45_ENV, W, fixture, served

NEW_KEYS = {"belief_deadline_fired", "belief_worlds_from_proposal",
            "belief_deadline_untested_worlds", "belief_prep_ms"}
BW_RULES = dict(world_history_legal=True, world_history_draw=True, belief_worlds=True,
                belief_sha256="a" * 64)
BW_ENV = {**RELEASE45_ENV, "SHENGJI_PV_WORLD_HISTORY_LEGAL": "1",
          "SHENGJI_PV_WORLD_HISTORY_DRAW": "1", "SHENGJI_PV_BELIEF_WORLDS": "1",
          "SHENGJI_PV_BELIEF_CKPT": "/data/models/belief.npz",
          "SHENGJI_PV_BELIEF_SHA256": "a" * 64}


class UniformBelief:
    """Stands in for `BeliefNumpy`: every feasible receiver equally likely."""

    def __init__(self, delay=None):
        self.delay = delay

    def marginals(self, inp):
        if self.delay is not None:
            self.delay()
        M = np.asarray(inp["M"], np.float64)
        s = M.sum(-1, keepdims=True)
        return np.where(s > 0, M / np.where(s > 0, s, 1.0), 0.0)


class FakeClock:
    """A clock that reads ``start`` for its first ``calls`` reads, then jumps."""

    def __init__(self, calls, jump=10.0):
        self.calls, self.jump, self.n = calls, jump, 0

    def __call__(self):
        self.n += 1
        return 0.0 if self.n <= self.calls else self.jump


def bot(deadline_ms=0, seed=7, model=None):
    b = served(seed=seed, belief_deadline_ms=deadline_ms, **BW_RULES)
    b.belief_model = model or UniformBelief()
    return b


def draw(b, now, seat):
    worlds, _ = b._worlds(copy.deepcopy(now), seat)
    return worlds, dict(b._last_sampling)


def _config(**kw):
    return pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                             **{**BW_RULES, **kw})


def test_off_names_payloads_and_env_are_unchanged():
    base = _config()
    assert pv.pv_policy_name("491ee4bf", base) == pv.pv_policy_name("491ee4bf", _config(belief_deadline_ms=0))
    assert "belief_deadline" not in pv.recipe_payload(base)
    assert "belief_deadline_ms" not in pv.recipe_payload(base)
    plain = pv.pv_env_recipe(BW_ENV)
    assert "belief_deadline_ms" not in plain
    for raw in ("", "0"):
        assert pv.pv_env_recipe({**BW_ENV, "SHENGJI_PV_BELIEF_DEADLINE_MS": raw}) == plain


def test_on_name_token_payload_and_env():
    on = _config(belief_deadline_ms=150, tiebreak_points=True)
    name = pv.pv_policy_name("491ee4bf", on)
    assert "-whd-bw-bwd150-tb-" in name
    assert name.replace("-bwd150", "") != pv.pv_policy_name("491ee4bf", _config(tiebreak_points=True))
    assert pv.recipe_payload(on)["belief_deadline"] == {"ms": 150, "rule": pv.BELIEF_DEADLINE_RULE_ID}
    assert pv.recipe_digest(on) != pv.recipe_digest(_config(belief_deadline_ms=151))
    recipe = pv.pv_env_recipe({**BW_ENV, "SHENGJI_PV_BELIEF_DEADLINE_MS": "150"})
    assert recipe["belief_deadline_ms"] == 150


@pytest.mark.parametrize("raw", ["1.5", "-3", "abc", "60001", "0x10", "²"])
def test_env_refuses_malformed_values(raw):
    with pytest.raises(pv.PVSearchPolicyError):
        pv.pv_env_recipe({**BW_ENV, "SHENGJI_PV_BELIEF_DEADLINE_MS": raw})


def test_the_deadline_requires_the_belief_proposal():
    with pytest.raises(pv.PVSearchPolicyError, match="requires belief_worlds"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA,
                                            belief_deadline_ms=150))
    with pytest.raises(pv.PVSearchPolicyError, match="requires belief_worlds"):
        pv.pv_env_recipe({**RELEASE45_ENV, "SHENGJI_PV_BELIEF_DEADLINE_MS": "150"})
    for bad in (True, 1.5, -1, 60_001):
        with pytest.raises(pv.PVSearchPolicyError, match="must be 0"):
            pv.recipe_payload(_config(belief_deadline_ms=bad))
    assert pv.PVSearchBot.belief_deadline_ms == 0
    assert "belief_deadline_ms" not in vars(bot())


def test_an_unreached_deadline_is_the_bw_draw():
    _, now, seat = fixture()
    off, on = bot(), bot(60_000)
    a, ra = draw(off, now, seat)
    b, rb = draw(on, now, seat)
    assert a == b
    assert off.sampler.rng.getstate() == on.sampler.rng.getstate()
    assert not NEW_KEYS & set(ra)
    assert rb["belief_deadline_fired"] == 0 and rb["belief_deadline_untested_worlds"] == 0
    assert rb["belief_worlds_from_proposal"] == W
    drop = NEW_KEYS | {"belief_ms"}
    assert {k: v for k, v in ra.items() if k not in drop} == {k: v for k, v in rb.items() if k not in drop}
    # the same seed draws the same worlds with the flag off
    assert draw(bot(), now, seat)[0] == a


@pytest.mark.parametrize("calls", [2, 8, 20])
def test_a_fired_deadline_keeps_the_tested_prefix_and_fills_from_the_proposal(calls):
    _, now, seat = fixture()
    off = bot()
    a, ra = draw(off, now, seat)
    on = bot(150)
    # read 1 sets the deadline, then one read before each attempt: the clock
    # passes the deadline after ``calls - 1`` attempts
    on._belief_clock = FakeClock(calls)
    b, rb = draw(on, now, seat)
    assert len(b) == W and rb["belief_fallback"] == 0
    assert rb["belief_deadline_fired"] == 1
    assert rb["belief_worlds_from_proposal"] == W
    kept = W - rb["belief_deadline_untested_worlds"]
    assert b[:kept] == a[:kept]
    # the kept worlds were history-tested; nothing after the stop was
    for hands, _ in b[:kept]:
        assert HL.history_legal(now, seat, hands)
    attempts_at_stop = calls - 1
    assert rb["history_rejections"] <= attempts_at_stop
    assert rb["belief_proposed"] <= attempts_at_stop + (W - kept) + rb.get("refusal_rejections", 0)
    for hands, _ in b:
        for s in range(4):
            assert len(hands[s]) == len(now.hands[s])


def test_a_deadline_past_at_preparation_draws_every_world_from_the_proposal():
    _, now, seat = fixture()
    on = bot(150)
    on._belief_clock = FakeClock(1)
    b, rb = draw(on, now, seat)
    assert len(b) == W and rb["belief_fallback"] == 0
    assert rb["belief_deadline_fired"] == 1
    assert rb["belief_deadline_untested_worlds"] == W == rb["belief_worlds_from_proposal"]
    assert rb["history_rejections"] == 0
    assert rb["belief_proposed"] == W + rb.get("refusal_rejections", 0)


def test_a_slow_preparation_is_kept_only_with_the_deadline(monkeypatch):
    _, now, seat = fixture()
    monkeypatch.setattr(bn, "PREP_SECONDS", 0.0)
    a, ra = draw(bot(), now, seat)
    assert ra["belief_fallback"] == 1 and ra["belief_error"] == "BeliefNumpyError"
    b, rb = draw(bot(60_000), now, seat)
    assert rb["belief_fallback"] == 0 and rb["belief_deadline_fired"] == 0
    assert rb["belief_prep_ms"] >= 0
    monkeypatch.setattr(bn, "PREP_SECONDS", 0.25)
    assert b == draw(bot(), now, seat)[0]


def test_a_slow_model_is_bounded_by_the_deadline():
    _, now, seat = fixture()
    clock = {"t": 0.0}
    on = bot(50, model=UniformBelief(delay=lambda: clock.__setitem__("t", clock["t"] + 0.2)))
    on._belief_clock = lambda: clock["t"]
    b, rb = draw(on, now, seat)
    assert len(b) == W and rb["belief_fallback"] == 0
    assert rb["belief_deadline_fired"] == 1
    assert rb["belief_deadline_untested_worlds"] == W


def test_other_belief_errors_still_fall_back_and_record_the_fields():
    _, now, seat = fixture()
    on = bot(150)
    on.belief_model = None
    b, rb = draw(on, now, seat)
    assert len(b) == W and rb["belief_fallback"] == 1
    assert rb["belief_deadline_fired"] == 0 and rb["belief_worlds_from_proposal"] == 0
    assert rb["belief_deadline_untested_worlds"] == 0


def test_the_decision_record_carries_the_fields_only_when_on():
    _, now, seat = fixture()
    for ms, present in ((0, False), (60_000, True)):
        b = bot(ms)
        b.decide_play(copy.deepcopy(now), seat)
        rec = b.last_decision_record
        assert (NEW_KEYS <= set(rec)) is present
        assert bool(NEW_KEYS & set(rec)) is present


def test_the_draw_stop_hook():
    _, now, seat = fixture()
    plain = served(seed=11, world_history_legal=True)
    mem = Memory(now, seat, own_kitty=True)
    a, n_a, sa = HL.sample_worlds_history_legal(plain.sampler, now, seat, W, mem=mem)
    assert not {"draw_stopped", "drawn_worlds", "stopped_untested"} & set(sa)
    stopped = served(seed=11, world_history_legal=True)
    reads = {"n": 0}

    def stop():
        reads["n"] += 1
        return reads["n"] > 5
    b, n_b, sb = HL.sample_worlds_history_legal(stopped.sampler, now, seat, W,
                                                mem=Memory(now, seat, own_kitty=True), stop=stop)
    assert len(b) == W and sb["draw_stopped"] is True and reads["n"] == 6
    kept = sb["drawn_worlds"] - sb["stopped_untested"]
    assert b[:kept] == a[:kept] and kept <= 5
    assert sb["history_rejections"] <= 5
    never = served(seed=11, world_history_legal=True)
    c, _, sc = HL.sample_worlds_history_legal(never.sampler, now, seat, W,
                                              mem=Memory(now, seat, own_kitty=True),
                                              stop=lambda: False)
    assert c == a and sc["draw_stopped"] is False and sc["stopped_untested"] == 0
    assert {k: v for k, v in sc.items() if k not in ("draw_stopped", "drawn_worlds", "stopped_untested")} == sa

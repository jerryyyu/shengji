"""Focused differential and ownership guards for report-world preparation."""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from types import MethodType

import pytest

from shengji.ai.mcbot import (
    DeterminizationContractError,
    MCBot,
)
from shengji.ai.memory import Memory
from shengji.ai.registry import make_bot
from shengji.rl.replay_log import rebuild_round


def _incident_state():
    fixture = Path(__file__).with_name("data") / "mc_override_variance.json"
    payload = json.loads(fixture.read_text())
    rnd = rebuild_round(payload["events"])
    seat = payload["seat"]
    for event in payload["events"]:
        if event["e"] != "play":
            continue
        if (rnd.trick is None or not rnd.trick.plays) and event["seat"] == seat:
            break
        rnd.play(event["seat"], list(event["cards"]))
    return rnd, seat


def _legacy_report(bot, rnd, seat, mem, i_attack, cand_a, cand_b, n, seed):
    """The pre-A3 report loop, retained narrowly as a test oracle."""
    d_sum = d_sq = 0.0
    deltas = []
    used = attempts = 0
    original_rng = bot.rng
    try:
        bot.rng = random.Random(seed)
        while used < n and attempts < n * bot.SAMPLE_ATTEMPT_FACTOR:
            attempts += 1
            sampled = bot._sample_hands(rnd, seat, mem)
            if sampled is None:
                continue
            hands, buried = sampled
            exact = bot._new_exact_world_session(rnd, buried)
            va = bot._score(bot._rollout(
                rnd, seat, hands, buried, list(cand_a),
                exact_session=exact))
            vb = bot._score(bot._rollout(
                rnd, seat, hands, buried, list(cand_b),
                exact_session=exact))
            if not i_attack:
                va, vb = -va, -vb
            delta = va - vb
            d_sum += delta
            d_sq += delta * delta
            deltas.append(delta)
            used += 1
    finally:
        bot.rng = original_rng
    return {
        "gap": d_sum / used if used else 0.0,
        "se": bot._paired_se(d_sum, d_sq, used),
        "worlds": used,
        "attempts": attempts,
        "rejected": attempts - used,
        "complete": used == n,
        "seed": seed,
        "deltas": deltas,
    }


def test_report_prepares_once_and_matches_literal_legacy():
    rnd, seat = _incident_state()
    candidates = make_bot("mc-s0-report-lcb", seed=238)._candidates(rnd, seat)
    assert len(candidates) >= 2
    kwargs = dict(rnd=rnd, seat=seat, mem=None, i_attack=rnd.is_attacker(seat),
                  cand_a=candidates[1], cand_b=candidates[0], n=30, seed=9123)

    optimized = make_bot("mc-s0-report-lcb", seed=238)
    legacy = make_bot("mc-s0-report-lcb", seed=238)
    mem = Memory(rnd, seat)
    kwargs["mem"] = mem
    calls = {"count": 0}
    complete = optimized._complete_determinized_hands

    def counted(self, *args, **kw):
        calls["count"] += 1
        return complete(*args, **kw)

    optimized._complete_determinized_hands = MethodType(counted, optimized)
    got = optimized._report_fold_gap(**kwargs, keep_deltas=True)
    expected = _legacy_report(legacy, rnd, seat, Memory(rnd, seat),
                              kwargs["i_attack"], candidates[1], candidates[0],
                              30, 9123)
    assert got == expected
    assert calls["count"] == got["worlds"] == 30
    assert optimized._sampler_snapshot() == legacy._sampler_snapshot()
    assert optimized.rng.getstate() == legacy.rng.getstate()


def test_prepared_report_rollouts_do_not_alias_hands_trick_or_history(monkeypatch):
    rnd, seat = _incident_state()
    bot = make_bot("mc-strong", seed=91)
    mem = Memory(rnd, seat)
    sampled = bot._sample_hands(rnd, seat, mem)
    assert sampled is not None
    hands, buried = sampled
    prepared = bot._prepare_report_world(rnd, seat, hands, buried=buried)
    original_hands = prepared.hands
    seen = []

    from shengji.engine.round import Round
    original_play = Round.play

    class _Stop(Exception):
        pass

    def capture_and_stop(self, actor, cards):
        seen.append(self)
        original_play(self, actor, cards)
        raise _Stop

    monkeypatch.setattr(Round, "play", capture_and_stop)
    candidate = bot._candidates(rnd, seat)[0]
    before = copy.deepcopy((rnd.hands, rnd.buried, rnd.trick, rnd.history))
    for _ in range(2):
        with pytest.raises(_Stop):
            bot._rollout(rnd, seat, hands, buried, candidate,
                         _prepared_report=prepared)
    assert prepared.hands == original_hands
    assert len(seen) == 2 and seen[0] is not seen[1]
    assert seen[0].trick is not seen[1].trick
    assert seen[0].history is not seen[1].history
    assert all(a is not b for a, b in zip(seen[0].hands, seen[1].hands))
    assert (rnd.hands, rnd.buried, rnd.trick, rnd.history) == before
    assert seen[0].buried is not seen[1].buried


def test_malformed_prepared_report_world_refuses():
    rnd, seat = _incident_state()
    bot = MCBot(seed=1)
    with pytest.raises(DeterminizationContractError):
        bot._prepare_report_world(rnd, seat, {}, buried=[])
    with pytest.raises(DeterminizationContractError):
        bot._rollout(rnd, seat, {}, [], ["SA"],
                     _prepared_report=object())


def test_malformed_report_world_refuses_through_report_wiring(monkeypatch):
    rnd, seat = _incident_state()
    bot = make_bot("mc-s0-report-lcb", seed=2)
    candidates = bot._candidates(rnd, seat)

    def malformed(_rnd, _seat, _mem):
        return {}, []

    monkeypatch.setattr(bot, "_sample_hands", malformed)
    original_rng = bot.rng
    original_rng_state = bot.rng.getstate()
    with pytest.raises(DeterminizationContractError,
                       match=r"sampled hand keys \[\] != opponents"):
        bot._report_fold_gap(
            rnd, seat, Memory(rnd, seat), rnd.is_attacker(seat),
            candidates[1], candidates[0], 1, seed=2)
    assert bot.rng is original_rng
    assert bot.rng.getstate() == original_rng_state


def test_report_override_falls_back_to_old_mapping_contract():
    rnd, seat = _incident_state()

    class SubclassStub(MCBot):
        def _rollout(self, _rnd, _seat, _sampled, _buried, _candidate, *,
                     exact_session=None):
            assert type(_sampled) is dict
            return 0.0

    for bot in (SubclassStub(seed=5), make_bot("mc-strong", seed=5)):
        if not isinstance(bot, SubclassStub):
            def instance_stub(self, _rnd, _seat, _sampled, _buried,
                              _candidate, *, exact_session=None):
                assert type(_sampled) is dict
                return 0.0
            bot._rollout = MethodType(instance_stub, bot)
        bot.N_DETERMINIZATIONS = 1
        bot.REPORT_FOLD_WORLDS = 30
        bot.REPORT_RULE = "lcb"
        mem = Memory(rnd, seat)
        cands = bot._candidates(rnd, seat)
        out = bot._report_fold_gap(
            rnd, seat, mem, rnd.is_attacker(seat), cands[1], cands[0], 30,
            seed=55)
        assert out["worlds"] == 30


def test_ordinary_rollout_without_prepared_value_is_repeatable():
    rnd, seat = _incident_state()
    bot = MCBot(seed=77)
    mem = Memory(rnd, seat)
    sampled = bot._sample_hands(rnd, seat, mem)
    assert sampled is not None
    hands, buried = sampled
    candidate = bot._candidates(rnd, seat)[0]
    first = bot._rollout(rnd, seat, hands, buried, candidate)
    second = bot._rollout(rnd, seat, hands, buried, candidate)
    assert first == second

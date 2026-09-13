"""Real spawned workers and real engine continuation, with short test budgets."""
import copy
import ctypes
import json
import os
import random
import time

import pytest

from shengji.ai.registry import make_bot
from shengji.ai.smart import SmartBot
from shengji.train import cwv_shortlist_screen as S
from shengji.train.screen_deadline import DeadlineSession, RECIPE, latency_summary
from tests.test_world_shortlist import play_state
from tests.test_cwv_shortlist_screen import cfg


class ProbeBot(SmartBot):
    def __init__(self, mode="fast"):
        self.mode = mode
        self.rng = random.Random(19)
        self.last_decision_record = None
        self.last_shortlist = None
        self.last_eval = None
        self.calls = 0

    def _candidates(self, rnd, seat):
        if self.mode == "enumeration":
            # PyDLL holds the GIL: no Python handler/thread inside this worker
            # can rescue it. The parent must kill the blocked process.
            ctypes.PyDLL(None).sleep(10)
        if self.mode == "total":
            time.sleep(.12)
        actions = [SmartBot().decide_play(rnd, seat)]
        self._sample_hands()
        self._means(rnd, seat, actions)
        return actions

    def _sample_hands(self):
        if self.mode == "sampling":
            ctypes.PyDLL(None).sleep(10)

    def _means(self, rnd, seat, actions):
        if self.mode == "ranking":
            ctypes.PyDLL(None).sleep(10)
        if self.mode == "total":
            time.sleep(.12)

    def _report_fold_gap(self):
        if self.mode == "report":
            ctypes.PyDLL(None).sleep(10)
        if self.mode == "total":
            time.sleep(.12)

    def decide_play(self, rnd, seat):
        if self.mode == "crash":
            os._exit(23)
        self.calls += 1
        self.rng.random()
        self.last_shortlist = {"complete": False, "partial_means": [999]}
        actions = self._candidates(rnd, seat)
        if self.mode == "selection":
            ctypes.PyDLL(None).sleep(10)
        self._report_fold_gap()
        self.last_shortlist = {"complete": True, "legal_count": 1}
        return actions[0]


def probe_factory(mode):
    return S.CwvTimedPolicy(ProbeBot(mode))


@pytest.mark.parametrize("phase", ["enumeration", "sampling", "ranking", "selection", "report"])
def test_external_timeout_discards_partial_state_and_next_move_recovers(phase):
    session = DeadlineSession(probe_factory, .20)
    try:
        policy = session.register(phase)
        # Poll-free startup has completed before the short play deadline.
        old_pid = session.process.pid
        before = policy.rng.getstate()
        rnd = play_state()
        started = time.monotonic()
        result = policy.decide_play(rnd, rnd.turn)
        assert time.monotonic() - started < 2
        assert result == SmartBot().decide_play(rnd, rnd.turn)
        assert session.process is None  # kill + reap, not a background search
        assert policy.calls == 0 and policy.rng.getstate() == before
        assert policy.last_shortlist is None and policy.last_decision_record is None
        trace = policy.decisions[-1]
        assert trace["report"] is None and trace["selection_N"] is None
        assert trace["reason"] == "decision_deadline"
        assert "cwv_shortlist" not in trace
        assert trace["deadline"]["timed_out"] is True
        assert trace["deadline"]["phase"] == phase
        assert trace["deadline"]["work_accounting_complete"] is False
        # Make the next state/request fast. A late response cannot replace it.
        session.checkpoints[0]["state"]["mode"] = "fast"
        session.seconds = 10  # include cold restart in the next decision
        rnd.play(rnd.turn, result)  # fallback is accepted by the real engine
        result2 = policy.decide_play(rnd, rnd.turn)
        assert result2 == SmartBot().decide_play(rnd, rnd.turn)
        assert session.process.pid != old_pid
        assert policy.calls == 1
        assert not policy.decisions[-1]["deadline"]["timed_out"]
        assert policy.decisions[-1]["cwv_shortlist"]["complete"]
    finally:
        session.close()


def test_one_budget_not_one_budget_per_phase():
    session = DeadlineSession(probe_factory, .29)
    try:
        policy = session.register("total")
        rnd = play_state()
        policy.decide_play(rnd, rnd.turn)
        assert policy.timeout_count == 1  # three .12s phases each below .29
        assert policy.decisions[-1]["deadline"]["phase"] == "report"
    finally:
        session.close()


def real_factory():
    bot = make_bot("mc-s0-report-lcb", seed=713)
    bot.N_DETERMINIZATIONS = 1
    bot.REPORT_FOLD_WORLDS = 30
    return S.CwvTimedPolicy(bot)


def without_times(value):
    if isinstance(value, dict):
        return {key: without_times(item) for key, item in value.items()
                if "secs" not in key and "seconds" not in key and key != "deadline"}
    if isinstance(value, list):
        return [without_times(item) for item in value]
    return value


def test_real_mc_success_preserves_action_rng_and_receipts():
    session = DeadlineSession(real_factory, 30)
    try:
        remote = session.register()
        direct = real_factory()
        rnd = play_state()
        for _ in range(2):
            expected = direct.decide_play(copy.deepcopy(rnd), rnd.turn)
            assert remote.decide_play(copy.deepcopy(rnd), rnd.turn) == expected
            assert remote.rng.getstate() == direct.rng.getstate()
            assert without_times(remote.last_decision_record) == without_times(direct.last_decision_record)
            assert remote.rollouts == direct.rollouts
            rnd.play(rnd.turn, expected)
    finally:
        session.close()


class FirstTrickBlocked(type(make_bot("mc-s0-report-lcb"))):
    def decide_play(self, rnd, seat):
        if not rnd.history:
            ctypes.PyDLL(None).sleep(10)
        self.last_decision_record = None
        return SmartBot().decide_play(rnd, seat)


def screen_factory(config, side, seed):
    return S.CwvTimedPolicy(FirstTrickBlocked(seed))


def test_real_cluster_both_sides_fallback_outcomes_and_summary(monkeypatch, tmp_path):
    # Real mirrored game driver and summary. Only policy work/budget is made tiny.
    recipe = dict(RECIPE, seconds=.05)
    monkeypatch.setattr(S, "DEADLINE_RECIPE", recipe)
    monkeypatch.setattr(S, "_deadline_side", screen_factory)
    # Fast tests use a 2s play budget so restart/import fits; native block is 10s.
    recipe["seconds"] = 2
    config = cfg("identity", decision_deadline=recipe)
    shard = S.run_cluster(config, 0)
    assert len(shard["records"]) == 2
    assert all(row["plays"] > 4 for row in shard["records"])
    summary = S.summary_for([shard], config)
    assert summary["complete"] and summary["completed_clusters"] == 1
    for side in ("arm", "baseline"):
        stats = summary["decision_latency"][side]
        assert stats["timeouts"] == 4
        assert stats["decisions"] > stats["timeouts"]
        assert stats["timeout_fraction"] == 4 / stats["decisions"]
    assert summary["arm_over_baseline_decision_cpu"] is None
    assert not summary["work_accounting_complete"]
    path = tmp_path / "cluster.json"
    path.write_text(json.dumps(shard))
    assert S.reopen_shard(path, config, 0) == shard
    legacy = dict(config)
    del legacy["decision_deadline"]
    with pytest.raises(ValueError, match="^completed shard does not match its mirrored pair and recipe$"):
        S.reopen_shard(path, legacy, 0)


def test_latency_bins_exact_and_separate():
    def trace(side, seconds, timeout):
        return {"side": side, "decisions": [{"deadline": {
            "elapsed_seconds": seconds, "timed_out": timeout}}]}
    result = latency_summary([{"decision_traces": [trace("arm", 301, True),
        trace("arm", 10, False), trace("baseline", 61, False)]}])
    assert result["arm"]["timeout_fraction"] == .5
    assert result["arm"]["above_seconds"]["300"] == {"count": 1, "fraction": .5}
    assert result["arm"]["above_seconds"]["10"]["count"] == 1
    assert result["baseline"]["above_seconds"]["60"]["count"] == 1
    assert result["baseline"]["timeouts"] == 0
    assert result["arm"]["p95"] == result["arm"]["max"] == 301


def test_child_crash_is_not_mislabeled_timeout_or_success():
    session = DeadlineSession(probe_factory, 10)
    try:
        policy = session.register("crash")
        rnd = play_state()
        with pytest.raises(RuntimeError, match="^deadline worker transport-error:"):
            policy.decide_play(rnd, rnd.turn)
        assert session.process is None
        assert policy.timeout_count == 0 and policy.decisions == []
    finally:
        session.close()


@pytest.mark.parametrize("extra,enabled", [([], True), (["--decision-deadline", "0"], False)])
def test_cli_binds_default_cap_and_explicit_legacy_mode(monkeypatch, tmp_path, extra, enabled):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    seen = []
    monkeypatch.setattr(S, "_run_pending", lambda config, *a, **kw: seen.append(config))
    assert S.main(["--arm", "identity", "--clusters", "1", "--workers", "1",
                   "--seed0", "17", "--out", str(tmp_path), *extra]) == 0
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved == seen[0]
    assert ("decision_deadline" in saved) is enabled
    if enabled:
        assert saved["decision_deadline"] == RECIPE

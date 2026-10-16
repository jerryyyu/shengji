"""One deadline child per pool worker (``--persistent-deadline-child``).

The harness imports torch, so this module runs in the policy-modes job (both
engines); the release-45 differential needs the pinned package and runs where
``SHENGJI_PV_PACKAGE_PATH`` is set.

The child outlives its cluster: ``DeadlineSession.reset`` drops every bot in it,
so a cluster never sees another cluster's bots, RNGs or receipts, while the
interpreter, its imports and the package weights persist.  With the flag off
the harness is today's one-child-per-cluster path.  The witness is the real
release-45 package: the same window with the flag off and on yields shards that
are byte-identical apart from the measured timing fields named in
``TIMING_FIELDS``.
"""
import copy
import ctypes
import hashlib
import json
import os
import random
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from shengji.ai.registry import REGISTRY, make_bot, register_pv_search_policies
from shengji.ai.smart import SmartBot
from shengji.train import cwv_shortlist_screen as S
from shengji.train import pv_search_policy as pv
from shengji.train import screen_deadline
from shengji.train.screen_deadline import DeadlineSession, DecisionExpired, RECIPE
from shengji.train.search_screen import _run_pending
from tests.test_cwv_shortlist_screen import cfg
from tests.test_encoder_round_compat import PACKAGE_SHA, pinned_production_package  # noqa: F401
from tests.test_release46_fly_config import without_combo
from tests.test_screen_deadline import ProbeBot, play_state

PER_WORKER = S.PER_WORKER_CHILD


class ResetProbe(ProbeBot):
    """``stuck-reset``: dropping the bot blocks the child natively (no Python
    handler can run), so a reset that must drop it never answers."""

    def __del__(self):
        if getattr(self, "mode", None) == "stuck-reset":
            ctypes.PyDLL(None).sleep(10)


def probe_factory(mode):
    return S.CwvTimedPolicy(ResetProbe(mode))


class Witness(type(make_bot("mc-s0-report-lcb"))):
    """Cheap plays that record which process built the bot and its first draw."""

    def __init__(self, seed):
        super().__init__(seed)
        self.built_in = os.getpid()
        self.calls = 0
        self.first_draw = None

    def decide_play(self, rnd, seat):
        self.calls += 1
        if self.first_draw is None:
            self.first_draw = self.rng.random()
        self.last_decision_record = None
        return SmartBot().decide_play(rnd, seat)


class CrashingArm(Witness):
    def decide_play(self, rnd, seat):
        if self.crash:
            os._exit(23)
        return super().decide_play(rnd, seat)


class FirstTrickBlocked(Witness):
    def decide_play(self, rnd, seat):
        if not rnd.history:
            ctypes.PyDLL(None).sleep(10)
        return super().decide_play(rnd, seat)


def witness_factory(config, side, seed):
    return S.CwvTimedPolicy(Witness(seed))


def crashing_factory(config, side, seed):
    # the arm seat of cluster 0 only (seed offsets are multiples of 500_000)
    bot = CrashingArm(seed)
    bot.crash = side == "arm" and (seed - config["seed0"]) % 500_000 == 0
    return S.CwvTimedPolicy(bot)


def blocked_factory(config, side, seed):
    return S.CwvTimedPolicy(FirstTrickBlocked(seed))


@pytest.fixture
def worker_state(monkeypatch):
    """A fresh per-worker slot, closed after the test."""
    state = S._worker_state
    monkeypatch.setattr(state, "session", None, raising=False)
    yield state
    held = getattr(state, "session", None)
    if held is not None:
        held.close()
        state.session = None


def test_reset_keeps_the_child_and_rebuilds_bots_from_scratch():
    session = DeadlineSession(probe_factory, 10)
    try:
        policy = session.register("fast")
        rnd = play_state()
        policy.decide_play(rnd, rnd.turn)
        pid = session.process.pid
        assert policy.calls == 1
        session.reset()
        assert session.process.pid == pid and session.process.is_alive()
        assert session.specs == [] and session.checkpoints == {}
        again = session.register("fast")
        assert again.index == 0
        assert again.calls == 0 and again.last_shortlist is None
        assert again.rng.getstate() == random.Random(19).getstate()
        assert session.process.pid == pid
        again.decide_play(rnd, rnd.turn)
        assert again.calls == 1
    finally:
        session.close()


def test_reset_reaps_a_child_that_died_idle_and_the_next_call_spawns_afresh():
    session = DeadlineSession(probe_factory, 10)
    try:
        session.register("fast")
        pid = session.process.pid
        session.process.kill()
        session.process.join(timeout=5)
        session.reset()
        assert session.process is None
        policy = session.register("fast")
        assert session.process.pid != pid
        rnd = play_state()
        policy.decide_play(rnd, rnd.turn)
        assert policy.calls == 1
    finally:
        session.close()


def test_reset_that_does_not_answer_kills_the_child_and_raises(monkeypatch):
    session = DeadlineSession(probe_factory, 10)
    try:
        # the cold start (imports) keeps the full budget; only the reset,
        # which the native block in ResetProbe.__del__ holds for 10 s, is bounded
        session.register("stuck-reset")
        monkeypatch.setattr(screen_deadline, "STARTUP_SECONDS", 1)
        with pytest.raises(DecisionExpired):
            session.reset()
        assert session.process is None
    finally:
        session.close()


def test_a_cluster_without_the_key_owns_its_child(monkeypatch, worker_state):
    monkeypatch.setattr(S, "_deadline_side", witness_factory)
    config = cfg("identity", decision_deadline=RECIPE)
    S.run_cluster(config, 0)
    assert getattr(worker_state, "session", None) is None


def test_the_key_requires_the_deadline_and_a_known_mode(worker_state):
    with pytest.raises(ValueError, match="unsupported deadline child mode"):
        S.run_cluster(cfg("identity", deadline_child=PER_WORKER), 0)
    with pytest.raises(ValueError, match="unsupported deadline child mode"):
        S.run_cluster(cfg("identity", decision_deadline=RECIPE, deadline_child="shared"), 0)


def test_per_worker_child_is_reused_and_every_cluster_gets_fresh_bots(monkeypatch, worker_state):
    monkeypatch.setattr(S, "_deadline_side", witness_factory)
    config = cfg("identity", decision_deadline=RECIPE, deadline_child=PER_WORKER)
    pids, witnesses = [], []
    for cluster in (0, 1):
        shard = S.run_cluster(config, cluster)
        session = worker_state.session
        assert session.process is not None and session.process.is_alive()
        pids.append(session.process.pid)
        states = [session.checkpoints[i]["state"] for i in range(8)]
        assert len(session.specs) == 8 and set(session.checkpoints) == set(range(8))
        witnesses.append(states)
        # every bot was built in the child, and its play count is this
        # cluster's alone: the two rounds' plays, nothing carried over
        assert {s["built_in"] for s in states} == {session.process.pid}
        assert sum(s["calls"] for s in states) == sum(r["plays"] for r in shard["records"])
        # a fresh RNG seeded from the registered spec, per cluster
        for (_config, _side, seed), state in zip(session.specs, states, strict=True):
            assert state["first_draw"] == random.Random(seed).random()
    assert pids[0] == pids[1]
    assert pids[0] != os.getpid()


def test_a_crash_fails_the_cluster_closed_and_the_next_cluster_gets_a_new_child(
        monkeypatch, worker_state, tmp_path):
    monkeypatch.setattr(S, "_deadline_side", crashing_factory)
    config = cfg("identity", decision_deadline=RECIPE, deadline_child=PER_WORKER, clusters=2)
    with pytest.raises(RuntimeError, match="^deadline worker transport-error:"):
        S.run_cluster(config, 0)
    assert worker_state.session.process is None
    shard = S.run_cluster(config, 1)
    assert len(shard["records"]) == 2 and shard["cluster"] == 1
    assert worker_state.session.process.is_alive()
    # through the pool driver: the failure is published, no shard is
    shards = []
    with pytest.raises(RuntimeError, match="^deadline worker transport-error:"):
        _run_pending(config, [0], shards, output=tmp_path, workers=1,
                     executor_factory=lambda n: ThreadPoolExecutor(max_workers=n),
                     task_fn=S.run_cluster)
    assert shards == [] and not list(tmp_path.glob("cluster-*.json"))
    failure = json.loads((tmp_path / "failure.json").read_text())
    assert failure["failed_clusters"] == [0] and failure["type"] == "RuntimeError"


def test_a_post_round_validation_failure_also_closes_the_child(monkeypatch, worker_state):
    """The rounds complete; the trump-rank witness the driver returns is wrong.
    The failure is after play, in the cluster's validation, and must still
    leave no reusable child."""
    monkeypatch.setattr(S, "_deadline_side", witness_factory)
    real = S.duel.play_screen_round

    def corrupted(*args, **kwargs):
        record, timing = real(*args, **kwargs)
        return {**record, "trump_rank": "K"}, timing

    config = cfg("identity", decision_deadline=RECIPE, deadline_child=PER_WORKER, clusters=2)
    S.run_cluster(config, 0)
    pid = worker_state.session.process.pid
    monkeypatch.setattr(S.duel, "play_screen_round", corrupted)
    with pytest.raises(ValueError, match="dealt trump rank 'K'"):
        S.run_cluster(config, 1)
    assert worker_state.session.process is None
    monkeypatch.setattr(S.duel, "play_screen_round", real)
    shard = S.run_cluster(config, 1)
    assert shard["cluster"] == 1 and worker_state.session.process.pid != pid
    # the default path raises the same error
    monkeypatch.setattr(S.duel, "play_screen_round", corrupted)
    with pytest.raises(ValueError, match="dealt trump rank 'K'"):
        S.run_cluster(cfg("identity", decision_deadline=RECIPE), 0)


def test_a_stuck_child_falls_back_per_cluster_exactly_as_the_owned_child(monkeypatch, worker_state):
    recipe = dict(RECIPE, seconds=2)
    monkeypatch.setattr(S, "DEADLINE_RECIPE", recipe)
    monkeypatch.setattr(S, "_deadline_side", blocked_factory)
    owned = cfg("identity", decision_deadline=recipe)
    shared = dict(owned, deadline_child=PER_WORKER)
    for cluster in (0, 1):
        expected = S.run_cluster(owned, cluster)
        actual = S.run_cluster(shared, cluster)
        assert without_timing(actual) == without_timing(expected)
        latency = S.summary_for([actual], shared)["decision_latency"]
        assert {side: stats["timeouts"] for side, stats in latency.items()} == {"arm": 4, "baseline": 4}
    # the kills mid-cluster respawned the child; the reset before cluster 1 ran on the respawn
    assert worker_state.session.process.is_alive()


def test_cli_binds_the_flag_outside_the_recipe(monkeypatch, tmp_path):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    seen = []
    monkeypatch.setattr(S, "_run_pending", lambda config, *a, **kw: seen.append(config))
    base = ["--arm", "identity", "--clusters", "1", "--workers", "1", "--seed0", "17"]
    assert S.main([*base, "--out", str(tmp_path / "off")]) == 0
    assert S.main([*base, "--out", str(tmp_path / "on"), "--persistent-deadline-child"]) == 0
    off, on = seen
    assert "deadline_child" not in off and on["deadline_child"] == PER_WORKER
    assert {k: v for k, v in on.items() if k != "deadline_child"} == off
    assert S._recipe(on) == S._recipe(off)
    with pytest.raises(SystemExit):
        S.main([*base, "--out", str(tmp_path / "x"), "--persistent-deadline-child",
                "--decision-deadline", "0"])


#: measured wall/CPU fields, the only differences the flag may produce
TIMING_FIELDS = {
    "records[].work.*": {"decision_cpu_seconds", "decision_wall_seconds", "shortlist_wall_seconds"},
    "timings[]": {"wall_secs", "arm_search_secs", "arm_prior_secs", "arm_wide_secs",
                  "baseline_search_secs"},
    "decision_traces[].decisions[]": {"seconds"},
    "decision_traces[].decisions[].deadline": {"elapsed_seconds", "overshoot_seconds"},
    "decision_traces[].bury_decisions[]": {"elapsed_seconds", "model_seconds", "rollout_seconds"},
    "decision_traces[].declare_decisions[]": {"seconds"},
}


def _timing_keys(path):
    if path.startswith("records[].work."):
        return TIMING_FIELDS["records[].work.*"]
    return TIMING_FIELDS.get(path, set())


def without_timing(value, path="", removed=None):
    """``value`` without the fields in TIMING_FIELDS; ``removed`` collects what went."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            here = f"{path}.{key}" if path else key
            if key in _timing_keys(path):
                if removed is not None:
                    removed.add(here)
                continue
            out[key] = without_timing(item, here, removed)
        return out
    if isinstance(value, list):
        return [without_timing(item, path + "[]", removed) for item in value]
    return value


def test_without_timing_keeps_the_deadline_recipe_and_budget_fields():
    shard = {"records": [{"work": {"arm": {"decision_cpu_seconds": 1.5, "decision_timeouts": 0}}}],
             "recipe": {"decision_deadline": {"seconds": 300.0}},
             "decision_traces": [{"decisions": [{"seconds": 0.2, "played": ["AS"],
                                                 "deadline": {"seconds": 300.0, "timed_out": False,
                                                              "elapsed_seconds": 0.2}}]}]}
    removed = set()
    assert without_timing(shard, removed=removed) == {
        "records": [{"work": {"arm": {"decision_timeouts": 0}}}],
        "recipe": {"decision_deadline": {"seconds": 300.0}},
        "decision_traces": [{"decisions": [{"played": ["AS"],
                                            "deadline": {"seconds": 300.0, "timed_out": False}}]}]}
    assert removed == {"records[].work.arm.decision_cpu_seconds",
                       "decision_traces[].decisions[].seconds",
                       "decision_traces[].decisions[].deadline.elapsed_seconds"}


def served_recipe(package):
    """Release 45's search, bury and rules from fly.toml (production without release
    46's combo lines) on the given package, with the serving budgets lifted so no
    decision depends on this host's load."""
    env = without_combo(tomllib.loads((Path(__file__).parents[2] / "fly.toml").read_text())["env"])
    env = {k: v for k, v in env.items() if k.startswith("SHENGJI_PV_")}
    env.update(SHENGJI_PV_CKPT=str(package), SHENGJI_PV_SHA256=PACKAGE_SHA,
               SHENGJI_PV_SERVING_BUDGET_SECONDS="1e9",
               SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS="1e9")
    return env


def run_window(out, name, clusters, *extra):
    S.main(["--arm", "policy", "--arm-policy", name, "--out", str(out), "--clusters", str(clusters),
            "--workers", "1", "--seed0", "103030910", "--decision-deadline", "300", *extra])
    assert not (out / "failure.json").exists()
    shards = [json.loads(p.read_text()) for p in sorted(out.glob("cluster-*.json"))]
    assert [s["cluster"] for s in shards] == list(range(clusters))
    return shards


def test_release45_window_is_bit_identical_with_the_flag_on(pinned_production_package, tmp_path, monkeypatch):
    """Two clusters of release 45 vs the MC-LCB control, one worker, so that with the flag
    on the second cluster runs in the child the first one used."""
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    for key, value in served_recipe(pinned_production_package).items():
        monkeypatch.setenv(key, value)
    name, = register_pv_search_policies(**pv.pv_env_recipe())
    try:
        off = run_window(tmp_path / "off", name, 2)
        on = run_window(tmp_path / "on", name, 2, "--persistent-deadline-child")
    finally:
        REGISTRY.pop(name, None)
    removed = set()
    assert [without_timing(s, removed=removed) for s in on] == [without_timing(s) for s in off]
    assert removed <= {f"{path.replace('.*', '.' + side)}.{field}"
                       for path, fields in TIMING_FIELDS.items() for field in fields
                       for side in ("arm", "baseline")}
    assert all(len(r["history_sha256"]) == 64 for s in off for r in s["records"])
    for shard in on:
        for trace in shard["decision_traces"]:
            assert all(not d["deadline"]["timed_out"] for d in trace["decisions"])
            assert all(d.get("reason") != "budget" for d in trace["decisions"] + trace["bury_decisions"])
    # the receipts bind the flag only in the config, never in the shard
    off_config = json.loads((tmp_path / "off" / "config.json").read_text())
    on_config = json.loads((tmp_path / "on" / "config.json").read_text())
    assert on_config.pop("deadline_child") == PER_WORKER and on_config == off_config
    assert all("deadline_child" not in s["recipe"] for s in on)
    assert S.reopen_shard(tmp_path / "on" / "cluster-00000.json", off_config, 0) == on[0]

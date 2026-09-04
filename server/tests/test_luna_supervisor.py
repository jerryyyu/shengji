"""Focused witnesses for the PT-Luna population supervisor boundary."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import sys
import threading
import time

import pytest

from shengji.luna import supervisor as supervisor
from shengji.luna import atomic_io as rpc_io
from shengji.luna import attempt as collection
from shengji.luna import transport as rpc_transport
from shengji.luna.attempt import AttemptReopen
from shengji.luna.turn import (
    DecisionPacket, PhaseContext, TeamMemory,
)
from shengji.luna.canonical import canonical_json_bytes
from test_luna_attempt import (
    FakeCodexRun, TransportFactory,
)


SECRET = b"pt-luna-supervisor-test-secret!!"
assert len(SECRET) == 32
RUNTIME = {"schema": "pt-luna-turn-rpc-runtime-v2",
           "boot_identity_sha256": "b" * 64}
COMPLETE = supervisor.COMPLETE_STATE_SOURCE_ACQUISITION
INCOMPLETE = supervisor.INCOMPLETE_STATE_SOURCE_ACQUISITION


class FakeRunner:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        root.chmod(0o700)
        self.attempts_root = root / "attempts"
        self.attempts_root.mkdir(parents=True, exist_ok=True)
        self.stop_event = threading.Event()
        self.calls = 0
        self.saw_launch = False

    def __call__(self, coordinate, mirror):
        self.calls += 1
        self.saw_launch = (self.attempts_root.parent / "census.json").exists()
        return object()


def _make(tmp_path, *, schedule=None, workers=1):
    runner = FakeRunner(tmp_path / "private")
    if schedule is None:
        schedule = [(('2', 0, 0), 0)]
    return supervisor.PTLunaRPCSupervisor(
        seed_secret=SECRET, private_root=tmp_path / "private",
        public_root=tmp_path / "public", runtime=RUNTIME,
        runner=runner, schedule=schedule, workers=workers), runner


def _packet(coordinate=("2", 0, 0), mirror=0):
    game = supervisor.selfplay.LunaSelfPlayGame(
        supervisor.selfplay.build_root(SECRET, coordinate),
        coordinate=coordinate, mirror=mirror, seed_secret=SECRET)
    team = game.acting_team
    return DecisionPacket.from_observation(
        game.session(team).observe(), coordinate=coordinate, mirror=mirror,
        team=team, decision_index=0,
        memory=TeamMemory.initial(
            team, supervisor.selfplay._state_digest(game.rnd, team)),
        phase=PhaseContext())


def _ledger(root, **overrides):
    values = dict(
        root=root, started_monotonic_nanoseconds=time.monotonic_ns(),
        wall_nanoseconds=1_000_000_000_000, token_cap=10_000,
        per_call_token_reserve=100, per_call_wall_reserve_milliseconds=1_000,
        boot_identity_sha256="b" * 64, runtime_sha256="c" * 64,
        namespace="supervisor-test")
    values.update(overrides)
    return collection.ScientificBudgetLedger(**values)


def test_schedule_rejects_duplicates_and_full_population_is_104():
    with pytest.raises(supervisor.RPCSupervisorError):
        supervisor.validate_schedule([(('2', 0, 0), 0), (('2', 0, 0), 0)])
    assert len(supervisor.schedule_for_games(SECRET, 104)) == 104


def test_schedule_for_games_takes_lowest_root_hashes_with_both_mirrors():
    rows = supervisor.selfplay.root_census(SECRET).serialized()["coordinates"]
    expected_coordinates = [
        tuple(row["coordinate"])
        for row in sorted(rows, key=lambda row: (
            row["root_sha256"], tuple(row["coordinate"])))[:16]
    ]
    schedule = supervisor.schedule_for_games(SECRET, 32)
    assert len(schedule) == 32
    assert list(dict.fromkeys(coordinate for coordinate, _ in schedule)) == \
        expected_coordinates
    assert all(
        [mirror for coordinate, mirror in schedule if coordinate == expected]
        == [0, 1]
        for expected in expected_coordinates)
    assert supervisor.schedule_for_games(SECRET, 32) == schedule
    assert schedule[:2] == supervisor.schedule_for_games(SECRET, 2)
    for games in (0, 1, 3, 106, True):
        with pytest.raises(supervisor.RPCSupervisorError,
                           match="game count"):
            supervisor.schedule_for_games(SECRET, games)


def test_root_census_binds_seed_and_scheduled_clusters():
    schedule = supervisor.schedule_for_games(SECRET, 4)
    census = supervisor.build_root_census(SECRET, schedule)
    assert census["coordinate_count"] == 2 and census["game_count"] == 4
    assert supervisor.validate_root_census(census, SECRET, schedule) \
        == census["census_sha256"]
    with pytest.raises(supervisor.RPCSupervisorError, match="seed drift"):
        supervisor.validate_root_census(census, b"x" * 32, schedule)
    with pytest.raises(supervisor.RPCSupervisorError, match="coverage"):
        supervisor.validate_root_census(census, SECRET, schedule[:2])
    forged = dict(census)
    forged["game_count"] = 6
    with pytest.raises(supervisor.RPCSupervisorError, match="hash drift"):
        supervisor.validate_root_census(forged, SECRET, schedule)


def test_run_lock_refuses_second_live_controller(tmp_path):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    first = supervisor._acquire_run_lock(root)
    try:
        with pytest.raises(supervisor.RPCSupervisorError,
                           match="already active"):
            supervisor._acquire_run_lock(root)
    finally:
        supervisor.fcntl.flock(first, supervisor.fcntl.LOCK_UN)
        supervisor.os.close(first)
    resumed = supervisor._acquire_run_lock(root)
    supervisor.fcntl.flock(resumed, supervisor.fcntl.LOCK_UN)
    supervisor.os.close(resumed)


def test_live_supervisor_owns_bound_runner_and_ledger(tmp_path, monkeypatch):
    schedule = supervisor.schedule_for_games(SECRET, 2)
    private_root = (tmp_path / "private").resolve()
    public_root = (tmp_path / "public").resolve()
    runtime = {
        "schema": "pt-luna-turn-rpc-runtime-v2",
        "boot_identity_sha256": "b" * 64,
        "source_set_sha256": "2" * 64,
        "codex_tool_catalog": {
            "schema": "pt-luna-codex-tool-catalog-v1"},
    }
    monkeypatch.setattr(
        collection, "source_identity", lambda _path: dict(runtime))
    with pytest.raises(supervisor.RPCSupervisorError, match="token cap"):
        supervisor.PTLunaRPCSupervisor(
            seed_secret=SECRET, private_root=private_root,
            public_root=public_root, runtime=runtime, schedule=schedule,
            codex_binary=Path("/usr/bin/true"))
    assert not private_root.exists()
    instance = supervisor.PTLunaRPCSupervisor(
        seed_secret=SECRET, private_root=private_root,
        public_root=public_root, runtime=runtime, schedule=schedule,
        codex_binary=Path("/usr/bin/true"), workers=2,
        token_cap=10_000, per_game_token_cap=1_000,
        per_call_token_reserve=50, per_call_wall_reserve_milliseconds=1_000,
        per_game_deadline_seconds=600, wall_seconds=10)
    assert instance._run_lock_fd is None
    assert instance.workers == 2
    assert type(instance.runner) is collection.RPCGameAttemptRunner
    assert type(instance.ledger) is collection.ScientificBudgetLedger
    assert instance.runner.seed_secret == SECRET
    assert instance.runner.attempts_root == private_root / "attempts"
    assert instance.runner.per_call_timeout_seconds == 1
    assert instance.runner.per_game_token_cap == 1_000
    assert instance.runner.per_game_deadline_ns == 600 * 1_000_000_000
    assert instance.ledger.root == private_root / "ledger"
    assert instance.ledger.token_cap == 10_000
    assert instance.ledger.wall_ns == 10 * 1_000_000_000
    assert instance.ledger.reserve_tokens == 50
    assert instance.ledger.runtime_sha256 == supervisor._sha(runtime)
    assert instance.runner.scientific_dispatch_reserver \
        == instance.ledger.reserve
    with pytest.raises(supervisor.RPCSupervisorError,
                       match="internally"):
        supervisor.PTLunaRPCSupervisor(
            seed_secret=SECRET, private_root=private_root,
            public_root=public_root, runtime=runtime, schedule=schedule,
            codex_binary=Path("/usr/bin/true"), token_cap=10_000,
            runner=instance.runner)

    def refuse_ledger(**_kwargs):
        raise collection.RPCCollectionError("injected constructor failure")

    monkeypatch.setattr(
        collection.ScientificBudgetLedger, "open_or_create", refuse_ledger)
    with pytest.raises(collection.RPCCollectionError,
                       match="injected constructor failure"):
        supervisor.PTLunaRPCSupervisor(
            seed_secret=SECRET, private_root=private_root,
            public_root=public_root, runtime=runtime, schedule=schedule,
            codex_binary=Path("/usr/bin/true"), token_cap=10_000)
    descriptor = supervisor._acquire_run_lock(private_root)
    supervisor.fcntl.flock(descriptor, supervisor.fcntl.LOCK_UN)
    supervisor.os.close(descriptor)


def test_injected_ledger_must_live_under_the_private_root(tmp_path):
    runner = FakeRunner(tmp_path / "private")
    ledger = _ledger(tmp_path / "elsewhere")
    with pytest.raises(supervisor.RPCSupervisorError, match="ledger binding"):
        supervisor.PTLunaRPCSupervisor(
            seed_secret=SECRET, private_root=tmp_path / "private",
            public_root=tmp_path / "public", runtime=RUNTIME,
            runner=runner, ledger=ledger, schedule=[(('2', 0, 0), 0)],
            ledger_namespace="supervisor-test")


def test_same_supervisor_refuses_concurrent_run(tmp_path, monkeypatch):
    instance, _runner = _make(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def blocked_run():
        entered.set()
        assert release.wait(timeout=2)
        return supervisor.SupervisorResult(INCOMPLETE, {"sentinel": True})

    monkeypatch.setattr(instance, "_run_locked", blocked_run)
    results = []
    thread = threading.Thread(target=lambda: results.append(instance.run()))
    thread.start()
    assert entered.wait(timeout=1)
    with pytest.raises(supervisor.RPCSupervisorError,
                       match="run already active"):
        instance.run()
    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert results[0].receipt == {"sentinel": True}


def test_terminal_publication_death_recovers_complete_staged_bytes(
        tmp_path, monkeypatch):
    target = tmp_path / "terminal.json"
    payload = {"schema": "terminal-sentinel", "complete": True}
    real_link = rpc_io.os.link
    died = False

    def die_once(source, destination, **kwargs):
        nonlocal died
        if not died:
            died = True
            raise KeyboardInterrupt("synthetic publication death")
        return real_link(source, destination, **kwargs)

    monkeypatch.setattr(rpc_io.os, "link", die_once)
    with pytest.raises(KeyboardInterrupt):
        supervisor._publish(target, payload)
    assert not target.exists()
    supervisor._publish(target, payload)
    assert json.loads(target.read_text()) == payload
    assert not rpc_io.partial_path(target).exists()


def test_terminal_death_after_link_restarts_without_second_runner_call(
        tmp_path, monkeypatch):
    class ProcessDeath(BaseException):
        pass

    instance, first_runner = _make(tmp_path)
    terminal = tmp_path / "public" / "terminal.json"
    real_link = rpc_io.os.link
    real_fsync = rpc_io._fsync_dir
    linked_terminal = False
    died = False

    def observe_terminal_link(source, destination, **kwargs):
        nonlocal linked_terminal
        value = real_link(source, destination, **kwargs)
        if Path(destination) == terminal:
            linked_terminal = True
        return value

    def die_after_terminal_link(path):
        nonlocal died
        if linked_terminal and not died:
            died = True
            raise ProcessDeath()
        return real_fsync(path)

    monkeypatch.setattr(rpc_io.os, "link", observe_terminal_link)
    monkeypatch.setattr(rpc_io, "_fsync_dir", die_after_terminal_link)
    with pytest.raises(ProcessDeath):
        instance.run()
    assert first_runner.calls == 1
    assert terminal.exists() and rpc_io.partial_path(terminal).exists()
    assert terminal.stat().st_ino == rpc_io.partial_path(terminal).stat().st_ino

    restarted, second_runner = _make(tmp_path)
    result = restarted.run()
    assert result.route == INCOMPLETE
    assert second_runner.calls == 0
    assert not rpc_io.partial_path(terminal).exists()
    assert terminal.stat().st_nlink == 1


def test_launch_facts_precede_provider_and_public_progress_has_no_score(
        tmp_path):
    instance, runner = _make(tmp_path)
    first = instance.run()
    assert first.route == INCOMPLETE
    assert runner.calls == 1
    assert runner.saw_launch
    census = json.loads((tmp_path / "private" / "census.json").read_text())
    assert census["census_sha256"] == instance.census_sha256
    stamped = json.loads((tmp_path / "private" / "runtime.json").read_text())
    assert stamped == RUNTIME
    progress = list((tmp_path / "public" / "progress").glob("*.json"))
    assert progress
    for path in progress:
        value = json.loads(path.read_text())
        assert not supervisor._forbidden(value)
    terminal = json.loads((tmp_path / "public" / "terminal.json").read_text())
    assert terminal["runtime_sha256"] == supervisor._sha(RUNTIME)
    assert not supervisor._forbidden(terminal)


def test_same_root_resume_cannot_mix_prompt_profiles(tmp_path):
    first, first_runner = _make(tmp_path)
    first.run()
    guided_runner = FakeRunner(tmp_path / "private")
    guided_runner.prompt_profile = "analysis-guided"
    resumed = supervisor.PTLunaRPCSupervisor(
        seed_secret=SECRET, private_root=tmp_path / "private",
        public_root=tmp_path / "public", runtime=RUNTIME,
        runner=guided_runner, schedule=[(("2", 0, 0), 0)],
        prompt_profile="analysis-guided")
    with pytest.raises(supervisor.RPCSupervisorError, match="profile"):
        resumed.run()
    assert guided_runner.calls == 0


def test_fresh_analysis_guided_root_seals_its_profile(tmp_path):
    runner = FakeRunner(tmp_path / "private")
    runner.prompt_profile = "analysis-guided"
    instance = supervisor.PTLunaRPCSupervisor(
        seed_secret=SECRET, private_root=tmp_path / "private",
        public_root=tmp_path / "public", runtime=RUNTIME,
        runner=runner, schedule=[(("2", 0, 0), 0)],
        prompt_profile="analysis-guided")
    result = instance.run()
    assert result.route == INCOMPLETE
    profile = json.loads(
        (tmp_path / "private" / "prompt-profile.json").read_text())
    assert profile["prompt_profile"] == "analysis-guided"

    resumed_runner = FakeRunner(tmp_path / "private")
    resumed = supervisor.PTLunaRPCSupervisor(
        seed_secret=SECRET, private_root=tmp_path / "private",
        public_root=tmp_path / "public", runtime=RUNTIME,
        runner=resumed_runner, schedule=[(("2", 0, 0), 0)],
        prompt_profile="analysis-guided")
    assert resumed.run().receipt == result.receipt
    assert resumed_runner.calls == 0


def test_legacy_root_without_profile_reopens_as_baseline(tmp_path):
    instance, runner = _make(tmp_path)
    result = instance.run()
    (tmp_path / "private" / "prompt-profile.json").unlink()

    resumed_runner = FakeRunner(tmp_path / "private")
    resumed = supervisor.PTLunaRPCSupervisor(
        seed_secret=SECRET, private_root=tmp_path / "private",
        public_root=tmp_path / "public", runtime=RUNTIME,
        runner=resumed_runner, schedule=[(("2", 0, 0), 0)])
    assert resumed.run().receipt == result.receipt
    assert resumed_runner.calls == 0
    profile = json.loads(
        (tmp_path / "private" / "prompt-profile.json").read_text())
    assert profile["prompt_profile"] == "baseline"


def test_partial_attempt_without_manifest_is_resumed_then_terminal_is_final(
        tmp_path, monkeypatch):
    instance, runner = _make(tmp_path)
    attempt = runner.attempts_root / "2-0-0-mirror-0"
    attempt.mkdir(mode=0o700)

    def seal(coordinate, mirror):
        runner.calls += 1
        path = runner.attempts_root / (
            f"{coordinate[0]}-{coordinate[1]}-{coordinate[2]}-mirror-{mirror}")
        (path / "manifest.json").write_text("{}")
        return object()

    monkeypatch.setattr(
        FakeRunner, "__call__",
        lambda self, coordinate, mirror: seal(coordinate, mirror))
    monkeypatch.setattr(
        supervisor, "reopen_attempt",
        lambda *args, **kwargs: AttemptReopen(
            "complete", "a" * 64, None, None, None,
            {"total_tokens": 7, "response_count": 1}))
    first = instance.run()
    assert first.route == COMPLETE
    assert runner.calls == 1
    second = instance.run()
    assert second.receipt == first.receipt
    assert runner.calls == 1


def test_self_sealed_complete_terminal_cannot_bypass_private_reconstruction(
        tmp_path):
    instance, runner = _make(tmp_path)
    body = {"schema": supervisor.TERMINAL_SCHEMA,
            "route": COMPLETE,
            "schedule_sha256": supervisor._schedule_sha(instance.schedule),
            "census_sha256": instance.census_sha256,
            "runtime_sha256": supervisor._sha(RUNTIME),
            "attempt_manifest": [{"index": 0, "coordinate": ["2", 0, 0],
                                  "mirror": 0, "status": "complete",
                                  "manifest_sha256": "4" * 64}],
            "completed_games": 1,
            "completed_deal_clusters": 1, "failed_games": 0,
            "pending_games": 0, "resource_totals": {},
            "ledger_terminal_accept_sha256": None}
    terminal = {**body, "receipt_sha256": hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()}
    supervisor.validate_terminal_receipt(terminal)
    path = tmp_path / "public" / "terminal.json"
    path.write_bytes(canonical_json_bytes(terminal))
    path.chmod(0o400)
    with pytest.raises(supervisor.RPCSupervisorError,
                       match="reconstruction drift"):
        instance.run()
    assert runner.calls == 0


def test_terminal_receipt_validation_refuses_forgery_and_leaks():
    instance_rows = [{"index": 0, "coordinate": ["2", 0, 0], "mirror": 0,
                      "status": None, "manifest_sha256": None}]
    body = {"schema": supervisor.TERMINAL_SCHEMA, "route": INCOMPLETE,
            "schedule_sha256": "1" * 64, "census_sha256": "2" * 64,
            "runtime_sha256": "3" * 64, "attempt_manifest": instance_rows,
            "completed_games": 0, "completed_deal_clusters": 0,
            "failed_games": 0, "pending_games": 1, "resource_totals": {},
            "ledger_terminal_accept_sha256": None}
    receipt = {**body, "receipt_sha256": supervisor._sha(body)}
    supervisor.validate_terminal_receipt(receipt)
    forged = {**receipt, "completed_games": 1}
    with pytest.raises(supervisor.RPCSupervisorError, match="schema drift"):
        supervisor.validate_terminal_receipt(forged)
    rehashed_body = {**body, "route": COMPLETE}
    with pytest.raises(supervisor.RPCSupervisorError, match="count"):
        supervisor.validate_terminal_receipt(
            {**rehashed_body,
             "receipt_sha256": supervisor._sha(rehashed_body)})
    leaking_body = {**body, "resource_totals": {"attacker_points": 80}}
    with pytest.raises(supervisor.RPCSupervisorError, match="schema drift"):
        supervisor.validate_terminal_receipt(
            {**leaking_body,
             "receipt_sha256": supervisor._sha(leaking_body)})


def test_unsealed_controller_death_is_restart_stable_incomplete(
        tmp_path, monkeypatch):
    instance, runner = _make(tmp_path)
    def die(_self, _coordinate, _mirror):
        runner.calls += 1
        raise KeyboardInterrupt("synthetic controller death")
    monkeypatch.setattr(FakeRunner, "__call__", die)
    first = instance.run()
    assert first.route == INCOMPLETE
    assert first.receipt["failed_games"] == 0
    assert first.receipt["pending_games"] == 1
    assert runner.calls == 1


def test_main_thread_interrupt_stops_and_cancels_pending_games(
        tmp_path, monkeypatch):
    schedule = [(('2', 0, 0), mirror) for mirror in (0, 1)] \
        + [(('3', 0, 0), 0)]
    instance, runner = _make(tmp_path, schedule=schedule)
    started = threading.Event()
    def wait_for_stop(self, _coordinate, _mirror):
        self.calls += 1
        started.set()
        self.stop_event.wait(timeout=2)
        time.sleep(0.05)
        raise RuntimeError("stopped")
    monkeypatch.setattr(FakeRunner, "__call__", wait_for_stop)
    def interrupt(_futures):
        assert started.wait(timeout=1)
        raise KeyboardInterrupt("controller interrupt")
    monkeypatch.setattr(supervisor, "as_completed", interrupt)
    first = instance.run()
    assert first.route == INCOMPLETE
    assert runner.calls == 1


def test_one_game_deadline_keeps_collecting_predeclared_independent_games(
        tmp_path, monkeypatch):
    schedule = [
        ((rank, 0, 0), 0) for rank in ("2", "3", "4", "5", "6")]
    barrier = threading.Barrier(4)
    calls = []
    calls_lock = threading.Lock()
    terminated = []
    expired_threads = set()
    real_monotonic_ns = time.monotonic_ns
    private_root = tmp_path / "private"
    private_root.mkdir(mode=0o700)
    private_root.chmod(0o700)

    def deadline_clock():
        now = real_monotonic_ns()
        if threading.get_ident() in expired_threads:
            return now + 601_000_000_000
        return now

    def expire_before_first_dispatch(_path):
        expired_threads.add(threading.get_ident())
        # The real runner refuses at its pre-dispatch deadline guard, before
        # this otherwise-unused transport is called.
        return object()

    class BoundaryRunner(collection.RPCGameAttemptRunner):
        def __init__(self):
            super().__init__(
                seed_secret=SECRET,
                attempts_root=private_root / "attempts",
                codex_binary=None, runtime=RUNTIME,
                per_game_deadline_seconds=600,
                per_game_token_cap=10_000,
                transport_factory=expire_before_first_dispatch)

        def __call__(self, coordinate, mirror):
            with calls_lock:
                calls.append((coordinate, mirror))
            if coordinate[0] != "6":
                assert barrier.wait(timeout=2) < 4
            if coordinate[0] == "2":
                return super().__call__(coordinate, mirror)
            path = supervisor._attempt_path(
                self.attempts_root, coordinate, mirror)
            path.mkdir(mode=0o700)
            # Keep these peers genuinely in flight while the real deadline
            # failure is handled; the fifth item must still run afterward.
            time.sleep(0.05)
            (path / "manifest.json").write_text("complete")
            return object()

        def terminate_active_calls(self):
            terminated.append(True)

    runner = BoundaryRunner()
    instance = supervisor.PTLunaRPCSupervisor(
        seed_secret=SECRET, private_root=private_root,
        public_root=tmp_path / "public", runtime=RUNTIME,
        runner=runner, schedule=schedule, workers=4)
    real_reopen = supervisor.reopen_attempt

    def reopen(path, **_kwargs):
        if path.name.startswith("2-"):
            return real_reopen(path, **_kwargs)
        status = (path / "manifest.json").read_text()
        return AttemptReopen(
            status, hashlib.sha256(str(path).encode()).hexdigest(),
            None, None, None, {"total_tokens": 0, "response_count": 0})

    monkeypatch.setattr(collection.time, "monotonic_ns", deadline_clock)
    monkeypatch.setattr(supervisor, "reopen_attempt", reopen)

    result = instance.run()

    assert result.route == supervisor.REFUSE_RESOURCE_OR_PROVIDER
    assert result.receipt["completed_games"] == 4
    assert result.receipt["failed_games"] == 1
    assert result.receipt["pending_games"] == 0
    assert {coordinate[0] for coordinate, _mirror in calls} \
        == {"2", "3", "4", "5", "6"}
    assert terminated == []
    assert not runner.stop_event.is_set()
    failed = instance._statuses[(("2", 0, 0), 0)]
    assert failed is not None
    assert failed.status == "incomplete"
    assert failed.failure_kind == "ResourceBoundaryError"
    assert failed.failure_class == "resource-provider"
    assert supervisor._attempt_path(
        runner.attempts_root, ("6", 0, 0), 0).is_dir()


def test_local_ledger_refusal_does_not_kill_peers_or_erase_queue(
        tmp_path, monkeypatch):
    schedule = [
        ((rank, 0, 0), 0) for rank in ("2", "3", "4", "5", "6")]
    barrier = threading.Barrier(4)
    calls = []
    terminated = []
    private_root = tmp_path / "private"
    private_root.mkdir(mode=0o700)
    private_root.chmod(0o700)
    ledger = _ledger(private_root / "ledger",
                     namespace="local-refusal-supervisor-test")

    class LocalFailureRunner(FakeRunner):
        def __call__(self, coordinate, mirror):
            calls.append((coordinate, mirror))
            if coordinate[0] != "6":
                assert barrier.wait(timeout=2) < 4
            path = supervisor._attempt_path(
                self.attempts_root, coordinate, mirror)
            path.mkdir(mode=0o700)
            if coordinate[0] == "2":
                packet = _packet(coordinate, mirror)
                ledger.reserve(packet)
                ledger.refuse({
                    "packet_sha256": packet.sha256,
                    "disposition_sha256": "e" * 64,
                    "total_tokens": 50,
                    "failure_kind": "CodexProviderResourceError",
                    "failure_class": "resource-provider",
                })
                (path / "manifest.json").write_text("incomplete")
                raise collection.RPCCollectionError(
                    "sealed game attempt is incomplete")
            time.sleep(0.05)
            (path / "manifest.json").write_text("complete")
            return object()

        def terminate_active_calls(self):
            terminated.append(True)

    runner = LocalFailureRunner(private_root)
    instance = supervisor.PTLunaRPCSupervisor(
        seed_secret=SECRET, private_root=private_root,
        public_root=tmp_path / "public", runtime=RUNTIME,
        runner=runner, schedule=schedule, workers=4)
    instance.ledger = ledger

    def reopen(path, **_kwargs):
        status = (path / "manifest.json").read_text()
        failure = ("CodexProviderResourceError"
                   if status == "incomplete" else None)
        failure_class = ("resource-provider"
                         if status == "incomplete" else None)
        return AttemptReopen(
            status, hashlib.sha256(str(path).encode()).hexdigest(),
            None, failure, failure_class,
            {"total_tokens": 50 if status == "incomplete" else 0,
             "response_count": 1 if status == "incomplete" else 0})

    monkeypatch.setattr(supervisor, "reopen_attempt", reopen)
    # The fake runner seals no journals; the ledger/journal reconciliation
    # is witnessed by the collection tests.
    monkeypatch.setattr(
        collection.ScientificBudgetLedger, "reconcile_attempt_journals",
        lambda self, paths: None)

    result = instance.run()

    assert result.route == supervisor.REFUSE_RESOURCE_OR_PROVIDER
    assert result.receipt["completed_games"] == 4
    assert result.receipt["failed_games"] == 1
    assert result.receipt["pending_games"] == 0
    assert {coordinate[0] for coordinate, _mirror in calls} \
        == {"2", "3", "4", "5", "6"}
    assert ledger.payload()["crossed"] is False
    assert terminated == []
    assert not runner.stop_event.is_set()


def test_global_budget_boundary_stops_inflight_and_queued_population(
        tmp_path, monkeypatch):
    schedule = [
        ((rank, 0, 0), 0) for rank in ("2", "3", "4")]
    instance, runner = _make(tmp_path, schedule=schedule, workers=2)
    manager = rpc_transport.ActiveCallManager()
    provider_pid_path = tmp_path / "global-budget-provider.pid"
    calls = []
    calls_lock = threading.Lock()

    class Budget:
        reserve_tokens = 100
        reserve_wall_ms = 1_000
        crossed = False

        def payload(self):
            return {
                "crossed": self.crossed, "spent_tokens": 0,
                "reserved_call_count": 0, "accepted_response_count": 0,
            }

        def snapshot(self):
            return {
                "remaining_scientific_tokens": (
                    0 if self.crossed else 1_000),
                "remaining_scientific_wall_ms": 2_000,
            }

        def reconcile_attempt_journals(self, _paths):
            return None

    budget = Budget()
    instance.ledger = budget

    def cross_budget_or_wait(self, coordinate, mirror):
        with calls_lock:
            calls.append((coordinate, mirror))
        path = supervisor._attempt_path(
            self.attempts_root, coordinate, mirror)
        path.mkdir(mode=0o700)
        if coordinate[0] == "2":
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline \
                    and not provider_pid_path.exists():
                time.sleep(0.01)
            assert provider_pid_path.exists()
            budget.crossed = True
            (path / "manifest.json").write_text("incomplete")
            raise collection.ResourceBoundaryError(
                "scientific budget crossed")
        result = rpc_transport._default_run(
            (sys.executable, "-c",
             "import os,pathlib,sys,time; "
             "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
             "time.sleep(8)", str(provider_pid_path)),
            b"", tmp_path, 10, _active_call_manager=manager)
        (path / "manifest.json").write_text("incomplete")
        raise collection.ResourceBoundaryError(
            f"collection stopped after global budget {result.returncode}")

    def reopen(path, **_kwargs):
        status = (path / "manifest.json").read_text()
        return AttemptReopen(
            status, hashlib.sha256(str(path).encode()).hexdigest(),
            None, "ResourceBoundaryError", "resource-provider",
            {"total_tokens": 0, "response_count": 0})

    monkeypatch.setattr(FakeRunner, "__call__", cross_budget_or_wait)
    monkeypatch.setattr(supervisor, "reopen_attempt", reopen)
    runner.terminate_active_calls = manager.terminate

    started = time.monotonic()
    result = instance.run()

    assert time.monotonic() - started < 5
    assert result.route == supervisor.REFUSE_RESOURCE_OR_PROVIDER
    assert result.receipt["completed_games"] == 0
    assert result.receipt["failed_games"] == 2
    assert result.receipt["pending_games"] == 1
    assert runner.stop_event.is_set()
    assert {coordinate[0] for coordinate, _mirror in calls} \
        == {"2", "3"}
    assert not supervisor._attempt_path(
        runner.attempts_root, ("4", 0, 0), 0).exists()
    provider_pid = int(provider_pid_path.read_text())
    with pytest.raises(ProcessLookupError):
        supervisor.os.kill(provider_pid, 0)


def test_main_interrupt_kills_a_real_active_provider_group(
        tmp_path, monkeypatch):
    instance, runner = _make(tmp_path)
    manager = rpc_transport.ActiveCallManager()
    runner.terminate_active_calls = manager.terminate
    pid_path = tmp_path / "active-provider.pid"
    def active_call(self, _coordinate, _mirror):
        self.calls += 1
        result = rpc_transport._default_run(
            (sys.executable, "-c",
             "import os,pathlib,sys,time; "
             "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
             "time.sleep(60)", str(pid_path)),
            b"", tmp_path, 60, _active_call_manager=manager)
        raise RuntimeError(f"provider stopped {result.returncode}")
    monkeypatch.setattr(FakeRunner, "__call__", active_call)
    def interrupt(_futures):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not pid_path.exists():
            time.sleep(0.01)
        assert pid_path.exists()
        raise KeyboardInterrupt("controller interrupt")
    monkeypatch.setattr(supervisor, "as_completed", interrupt)
    started = time.monotonic()
    first = instance.run()
    assert time.monotonic() - started < 5
    assert first.route == INCOMPLETE
    assert runner.calls == 1
    provider_pid = int(pid_path.read_text())
    with pytest.raises(ProcessLookupError):
        supervisor.os.kill(provider_pid, 0)
    second = instance.run()
    assert second.receipt == first.receipt
    assert runner.calls == 1


@pytest.mark.parametrize("failure_class,route", [
    ("mechanics-privacy", supervisor.REFUSE_MECHANICS_OR_PRIVACY),
    ("resource-provider", supervisor.REFUSE_RESOURCE_OR_PROVIDER),
])
def test_existing_incomplete_attempt_routes_without_provider_retry(
        failure_class, route, tmp_path, monkeypatch):
    instance, runner = _make(tmp_path)
    attempt = runner.attempts_root / "2-0-0-mirror-0"
    attempt.mkdir(mode=0o700)
    (attempt / "manifest.json").write_text("{}")
    monkeypatch.setattr(
        supervisor, "reopen_attempt",
        lambda *args, **kwargs: AttemptReopen(
            "incomplete", "b" * 64, None, "SyntheticFailure",
            failure_class, {"total_tokens": 9, "response_count": 1}))
    result = instance.run()
    assert result.route == route
    assert runner.calls == 0


def test_corrupt_sealed_manifest_routes_mechanics_stably_without_retry(
        tmp_path):
    instance, runner = _make(tmp_path)
    attempt = runner.attempts_root / "2-0-0-mirror-0"
    attempt.mkdir(mode=0o700)
    (attempt / "manifest.json").write_text("{}")
    first = instance.run()
    assert first.route == supervisor.REFUSE_MECHANICS_OR_PRIVACY
    assert runner.calls == 0

    second = instance.run()
    assert second.receipt == first.receipt
    assert runner.calls == 0


def test_corrupt_first_manifest_prevents_all_other_provider_dispatches(
        tmp_path):
    schedule = [(('2', 0, 0), 0), (('3', 0, 0), 0)]
    instance, runner = _make(tmp_path, schedule=schedule)
    attempt = runner.attempts_root / "2-0-0-mirror-0"
    attempt.mkdir(mode=0o700)
    (attempt / "manifest.json").write_text("{}")

    result = instance.run()

    assert result.route == supervisor.REFUSE_MECHANICS_OR_PRIVACY
    assert runner.calls == 0


def test_corrupt_partial_attempt_is_durable_mechanics_without_provider_call(
        tmp_path):
    class CountingFactory:
        calls = 0
        def __call__(self, _path):
            self.calls += 1
            raise AssertionError("provider transport must not be constructed")
    factory = CountingFactory()
    private = tmp_path / "private"
    public = tmp_path / "public"
    private.mkdir(mode=0o700)
    schedule = [(('2', 0, 0), 0)]

    def make_instance():
        runner = collection.RPCGameAttemptRunner(
            seed_secret=SECRET, attempts_root=private / "attempts",
            codex_binary=None, runtime=RUNTIME,
            per_game_deadline_seconds=600, per_game_token_cap=1_000,
            transport_factory=factory)
        return supervisor.PTLunaRPCSupervisor(
            seed_secret=SECRET, private_root=private, public_root=public,
            runtime=RUNTIME, runner=runner, schedule=schedule, workers=1)

    first_instance = make_instance()
    attempt = private / "attempts" / "2-0-0-mirror-0"
    attempt.mkdir(mode=0o700)
    (attempt / "attempt.json").write_bytes(canonical_json_bytes({}))
    (attempt / "attempt.json").chmod(0o400)

    first = first_instance.run()

    assert first.route == supervisor.REFUSE_MECHANICS_OR_PRIVACY
    assert factory.calls == 0
    refusal = attempt / "controller-refusal.json"
    assert refusal.is_file()
    assert json.loads(refusal.read_text())["failure_class"] \
        == "mechanics-privacy"

    second_instance = make_instance()
    second = second_instance.run()
    assert second.receipt == first.receipt
    assert factory.calls == 0


def test_broken_manifest_symlink_is_occupied_and_never_retried(tmp_path):
    instance, runner = _make(tmp_path)
    attempt = runner.attempts_root / "2-0-0-mirror-0"
    attempt.mkdir(mode=0o700)
    (attempt / "manifest.json").symlink_to(attempt / "missing-target")
    result = instance.run()
    assert result.route == supervisor.REFUSE_MECHANICS_OR_PRIVACY
    assert runner.calls == 0


def _sealed_run(tmp_path, *, games=2):
    """Collect ``games`` real attempts through the fake transport and seal."""
    root = tmp_path / "run"
    private = root / "private"
    public = root / "public"
    private.mkdir(parents=True, mode=0o700)
    private.chmod(0o700)
    schedule = supervisor.schedule_for_games(SECRET, games)
    ledger = _ledger(private / "ledger", token_cap=1_000_000,
                     per_call_token_reserve=1_000,
                     runtime_sha256=supervisor._sha(RUNTIME),
                     namespace=supervisor.SCHEMA)
    runner = collection.RPCGameAttemptRunner(
        seed_secret=SECRET, attempts_root=private / "attempts",
        codex_binary=None, runtime=RUNTIME,
        per_game_deadline_seconds=600, per_game_token_cap=100_000,
        per_call_token_reserve=1_000,
        transport_factory=TransportFactory(FakeCodexRun()))
    instance = supervisor.PTLunaRPCSupervisor(
        seed_secret=SECRET, private_root=private, public_root=public,
        runtime=RUNTIME, schedule=schedule, runner=runner, ledger=ledger,
        workers=2)
    return instance.run(), root


def test_verify_run_reconstructs_sealed_terminal_from_seed_and_root(tmp_path):
    result, root = _sealed_run(tmp_path)
    assert result.route == COMPLETE
    assert result.receipt["completed_games"] == 2
    assert result.receipt["completed_deal_clusters"] == 1
    assert result.receipt["ledger_terminal_accept_sha256"] is not None
    assert result.receipt["resource_totals"]["ledger_spent_tokens"] > 0
    terminal_path = root / "public" / "terminal.json"
    assert json.loads(terminal_path.read_text()) == result.receipt

    verified = supervisor.verify_run(root, seed_secret=SECRET)
    assert verified.route == COMPLETE
    assert verified.receipt == result.receipt

    with pytest.raises(supervisor.RPCSupervisorError, match="seed drift"):
        supervisor.verify_run(root, seed_secret=b"x" * 32)

    forged = dict(result.receipt)
    forged["completed_games"] = 3
    forged["failed_games"] = -1
    body = {key: value for key, value in forged.items()
            if key != "receipt_sha256"}
    forged["receipt_sha256"] = supervisor._sha(body)
    terminal_path.chmod(0o600)
    terminal_path.write_bytes(canonical_json_bytes(forged))
    terminal_path.chmod(0o400)
    with pytest.raises(supervisor.RPCSupervisorError):
        supervisor.verify_run(root, seed_secret=SECRET)

    # A forgery that passes the public shape check must still fail the
    # private reconstruction.
    totals = dict(result.receipt["resource_totals"])
    totals["ledger_spent_tokens"] += 1
    rebound = {**result.receipt, "resource_totals": totals}
    body = {key: value for key, value in rebound.items()
            if key != "receipt_sha256"}
    rebound["receipt_sha256"] = supervisor._sha(body)
    supervisor.validate_terminal_receipt(rebound)
    terminal_path.chmod(0o600)
    terminal_path.write_bytes(canonical_json_bytes(rebound))
    terminal_path.chmod(0o400)
    with pytest.raises(supervisor.RPCSupervisorError,
                       match="reconstruction drift"):
        supervisor.verify_run(root, seed_secret=SECRET)

    terminal_path.unlink()
    with pytest.raises(supervisor.RPCSupervisorError,
                       match="no sealed terminal"):
        supervisor.verify_run(root, seed_secret=SECRET)


def test_verify_run_reopens_attempts_against_rebuilt_roots(tmp_path):
    _result, root = _sealed_run(tmp_path)
    attempt = next((root / "private" / "attempts").iterdir())
    trajectory_path = attempt / "trajectory.json"
    trajectory = json.loads(trajectory_path.read_text())
    trajectory["events"][0]["candidate_index"] = 1
    trajectory_path.chmod(0o600)
    trajectory_path.write_bytes(canonical_json_bytes(trajectory))
    trajectory_path.chmod(0o400)
    # The tampered attempt no longer reopens, so the sealed acceptance can
    # not belong to a complete population.
    with pytest.raises(supervisor.RPCSupervisorError,
                       match="acceptance drift|reconstruction drift"):
        supervisor.verify_run(root, seed_secret=SECRET)


def test_verify_run_refuses_forged_ledger_acceptance_hash(tmp_path):
    """The sealed terminal's ledger-acceptance hash must match the ledger.

    A shape-valid receipt whose ``ledger_terminal_accept_sha256`` was swapped
    (self-hash recomputed, every total intact) passes the public checks and
    would reconstruct byte-equal against itself; only the ledger comparison
    catches it.
    """
    result, root = _sealed_run(tmp_path)
    forged = dict(result.receipt)
    forged["ledger_terminal_accept_sha256"] = "f" * 64
    body = {key: value for key, value in forged.items()
            if key != "receipt_sha256"}
    forged["receipt_sha256"] = supervisor._sha(body)
    supervisor.validate_terminal_receipt(forged)
    terminal_path = root / "public" / "terminal.json"
    terminal_path.chmod(0o600)
    terminal_path.write_bytes(canonical_json_bytes(forged))
    terminal_path.chmod(0o400)
    with pytest.raises(supervisor.RPCSupervisorError,
                       match="ledger acceptance drift"):
        supervisor.verify_run(root, seed_secret=SECRET)

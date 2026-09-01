"""End-to-end witnesses for durable supervisor-owned PT-Luna games."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading

import pytest

from shengji.rl import privileged_teacher_luna_rpc_collection as collection
from shengji.rl import privileged_teacher_luna_rpc_io as rpc_io
from shengji.rl.privileged_teacher_luna_rpc_transport import (
    CODE_MODE_DISABLED_DIAGNOSTIC,
    CodexExecPlannerTransport,
    InvocationResult,
)
from shengji.rl import privileged_teacher_luna_selfplay as selfplay
from shengji.rl.privileged_teacher_luna_turn_rpc import (
    DecisionPacket, Intent, PhaseContext, PlannerResponse, TeamMemory, Usage,
)
from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes


SECRET = b"pt-luna-rpc-collection-secret!!!"
assert len(SECRET) == 32
RUNTIME = {"schema": "pt-luna-turn-rpc-runtime-v1", "test": True,
           "boot_identity_sha256": "b" * 64}
LEDGER_BINDING = {
    "boot_identity_sha256": "b" * 64,
    "runtime_sha256": "c" * 64,
    "capacity_receipt_sha256": "d" * 64,
    "namespace": "pt-luna-test-namespace",
}


def _decision_sha(prompt: bytes) -> str:
    marker = b'"decision_sha256":"'
    start = prompt.index(marker) + len(marker)
    return prompt[start:start + 64].decode("ascii")


class FakeCodexRun:
    def __init__(self, *, total_tokens: int = 120,
                 crash_before_response: bool = False,
                 tool_event: bool = False, after_call=None):
        self.total_tokens = total_tokens
        self.crash_before_response = crash_before_response
        self.tool_event = tool_event
        self.after_call = after_call
        self.calls = 0

    def __call__(self, command, prompt, workspace, timeout):
        del workspace, timeout
        self.calls += 1
        if self.crash_before_response:
            raise KeyboardInterrupt("simulated controller death")
        final = {
            "schema": "pt-luna-provider-intent-v1",
            "decision_sha256": _decision_sha(prompt),
            "kind": "play", "candidate_index": 0,
            "confidence": "low", "candidate_indices": [],
            "continuations": [], "planning_note": "bounded",
        }
        final_path = Path(command[command.index("--output-last-message") + 1])
        final_path.write_bytes(canonical_json_bytes(final))
        input_tokens = max(0, self.total_tokens - 20)
        usage = {"input_tokens": input_tokens,
                 "cached_input_tokens": 0,
                 "cache_write_input_tokens": 0,
                 "output_tokens": self.total_tokens - input_tokens,
                 "reasoning_output_tokens": 0}
        item_type = "command_execution" if self.tool_event else "agent_message"
        rows = [
            {"type": "thread.started", "thread_id": "test"},
            {"type": "item.completed", "item": {
                "id": "diagnostic", "type": "error",
                "message": CODE_MODE_DISABLED_DIAGNOSTIC}},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {
                "id": "answer", "type": item_type,
                "text": canonical_json_bytes(final).decode("ascii").strip()}},
            {"type": "turn.completed", "usage": usage},
        ]
        trace = b"".join(canonical_json_bytes(row) for row in rows)
        if self.after_call is not None:
            self.after_call()
        return InvocationResult(0, trace, b"", 2)


class TransportFactory:
    def __init__(self, fake: FakeCodexRun):
        self.fake = fake
        self.calls = 0

    def __call__(self, path: Path):
        self.calls += 1
        return CodexExecPlannerTransport(
            codex_binary="/usr/bin/true", temp_root=path,
            run_command=self.fake,
            runtime_attestor=lambda _: {
                "schema": "pt-luna-codex-tool-catalog-v1"})


def _runner(tmp_path, factory, *, token_cap=100_000):
    return collection.RPCGameAttemptRunner(
        seed_secret=SECRET, attempts_root=tmp_path / "attempts",
        codex_binary=None, runtime=RUNTIME,
        per_game_deadline_seconds=600, per_game_token_cap=token_cap,
        transport_factory=factory)


def _packet(coordinate=("2", 0, 0), mirror=0):
    game = selfplay.LunaSelfPlayGame(
        selfplay.build_root(SECRET, coordinate), coordinate=coordinate,
        mirror=mirror, seed_secret=SECRET)
    team = game.acting_team
    observation = game.session(team).observe()
    return DecisionPacket.from_observation(
        observation, coordinate=coordinate, mirror=mirror, team=team,
        decision_index=0,
        memory=TeamMemory.initial(
            team, selfplay._state_digest(game.rnd, team)),
        phase=PhaseContext())


def test_live_transport_timeout_never_exceeds_durable_wall_reserve(
        tmp_path, monkeypatch):
    active_runtime = {
        **RUNTIME,
        "codex_tool_catalog": {
            "schema": "pt-luna-codex-tool-catalog-v1"},
    }
    seen = []
    class CaptureTransport:
        def __init__(self, **kwargs):
            seen.append(kwargs["timeout_seconds"])
    monkeypatch.setattr(collection, "CodexExecPlannerTransport",
                        CaptureTransport)
    monkeypatch.setattr(collection, "source_identity",
                        lambda _path: dict(active_runtime))
    runner = collection.RPCGameAttemptRunner(
        seed_secret=SECRET, attempts_root=tmp_path / "attempts",
        codex_binary=Path("/usr/bin/true"), runtime=active_runtime,
        per_game_deadline_seconds=600, per_game_token_cap=1_000,
        per_call_wall_reserve_milliseconds=25_999)
    runner.transport_factory(tmp_path)
    assert seen == [25]
    assert seen[0] * 1_000 <= runner.per_call_wall_reserve_milliseconds


def _response(packet, *, tokens=90, provider="d" * 64):
    return PlannerResponse(
        Intent("play", packet.decision_sha256, candidate_index=0,
               confidence="low"),
        Usage(tokens - 10, 10, tokens, 1), 0, packet.team,
        packet.sha256, packet.memory.sha256, "c" * 64, provider)


def test_scientific_ledger_reserves_concurrent_dispatch_before_spend(tmp_path):
    ledger = collection.ScientificBudgetLedger(
        root=tmp_path / "ledger",
        started_monotonic_nanoseconds=collection.time.monotonic_ns(),
        wall_nanoseconds=1_000_000_000_000, token_cap=150,
        per_call_token_reserve=100, **LEDGER_BINDING)
    first = _packet()
    second = _packet(("3", 0, 0))
    ledger.reserve(first)
    with pytest.raises(collection.ResourceBoundaryError,
                       match="reservation refused"):
        ledger.reserve(second)
    ledger.accept(_response(first, tokens=90))
    ledger.accept(_response(first, tokens=90))
    payload = ledger.payload()
    assert {key: payload[key] for key in (
        "spent_tokens", "reserved_call_count",
        "accepted_response_count", "crossed", "event_count")} == {
        "spent_tokens": 90, "reserved_call_count": 0,
        "accepted_response_count": 1, "crossed": False,
        "event_count": 2}
    reopened = collection.ScientificBudgetLedger(
        root=tmp_path / "ledger",
        started_monotonic_nanoseconds=ledger.started_ns,
        wall_nanoseconds=ledger.wall_ns, token_cap=ledger.token_cap,
        per_call_token_reserve=ledger.reserve_tokens, **LEDGER_BINDING)
    reopened.accept(_response(first, tokens=90))
    assert reopened.payload() == payload
    with pytest.raises(collection.RPCCollectionError,
                       match="genesis drift"):
        collection.ScientificBudgetLedger(
            root=tmp_path / "ledger",
            started_monotonic_nanoseconds=ledger.started_ns,
            wall_nanoseconds=ledger.wall_ns, token_cap=250,
            per_call_token_reserve=ledger.reserve_tokens,
            **LEDGER_BINDING)


@pytest.mark.parametrize("event_kind", ("reserve", "settle"))
@pytest.mark.parametrize("death_point", ("before-link", "after-link"))
def test_scientific_ledger_recovers_event_publication_death(
        tmp_path, monkeypatch, event_kind, death_point):
    class ProcessDeath(BaseException):
        pass

    ledger = collection.ScientificBudgetLedger(
        root=tmp_path / "ledger",
        started_monotonic_nanoseconds=collection.time.monotonic_ns(),
        wall_nanoseconds=1_000_000_000_000, token_cap=1_000,
        per_call_token_reserve=100, **LEDGER_BINDING)
    packet = _packet()
    if event_kind == "settle":
        ledger.reserve(packet)
    event_index = 0 if event_kind == "reserve" else 1
    event_name = f"{event_index:012d}.json"
    real_link = rpc_io.os.link
    real_fsync = rpc_io._fsync_dir
    linked = False
    died = False

    def interrupt_link(source, destination, **kwargs):
        nonlocal linked, died
        if str(destination).endswith(event_name) \
                and death_point == "before-link" and not died:
            died = True
            raise ProcessDeath()
        value = real_link(source, destination, **kwargs)
        if str(destination).endswith(event_name):
            linked = True
        return value

    def interrupt_fsync(path):
        nonlocal died
        if linked and death_point == "after-link" and not died:
            died = True
            raise ProcessDeath()
        return real_fsync(path)

    monkeypatch.setattr(rpc_io.os, "link", interrupt_link)
    monkeypatch.setattr(rpc_io, "_fsync_dir", interrupt_fsync)
    with pytest.raises(ProcessDeath):
        if event_kind == "reserve":
            ledger.reserve(packet)
        else:
            ledger.accept(_response(packet, tokens=90))
    assert died

    reopened = collection.ScientificBudgetLedger(
        root=tmp_path / "ledger",
        started_monotonic_nanoseconds=ledger.started_ns,
        wall_nanoseconds=ledger.wall_ns, token_cap=ledger.token_cap,
        per_call_token_reserve=ledger.reserve_tokens, **LEDGER_BINDING)
    payload = reopened.payload()
    if event_kind == "reserve":
        assert reopened.packet_state(packet.sha256) == "reserved"
        assert payload["reserved_call_count"] == 1
        assert payload["spent_tokens"] == 0
    else:
        assert reopened.packet_state(packet.sha256) == "settled"
        assert payload["reserved_call_count"] == 0
        assert payload["spent_tokens"] == 90
        assert payload["accepted_response_count"] == 1


def test_scientific_ledger_truncated_event_partial_refuses(tmp_path):
    ledger = collection.ScientificBudgetLedger(
        root=tmp_path / "ledger",
        started_monotonic_nanoseconds=collection.time.monotonic_ns(),
        wall_nanoseconds=1_000_000_000_000, token_cap=1_000,
        per_call_token_reserve=100, **LEDGER_BINDING)
    staged = rpc_io.partial_path(tmp_path / "ledger" / "000000000000.json")
    staged.write_bytes(b"truncated")
    staged.chmod(0o400)
    with pytest.raises(collection.RPCCollectionError,
                       match="partial recovery drift"):
        collection.ScientificBudgetLedger(
            root=tmp_path / "ledger",
            started_monotonic_nanoseconds=ledger.started_ns,
            wall_nanoseconds=ledger.wall_ns, token_cap=ledger.token_cap,
            per_call_token_reserve=ledger.reserve_tokens,
            **LEDGER_BINDING)


def test_scientific_ledger_over_reserve_response_fails_before_engine(tmp_path):
    ledger = collection.ScientificBudgetLedger(
        root=tmp_path / "ledger",
        started_monotonic_nanoseconds=collection.time.monotonic_ns(),
        wall_nanoseconds=1_000_000_000_000, token_cap=1_000,
        per_call_token_reserve=100, **LEDGER_BINDING)
    accepted_packet = _packet()
    packet = _packet(("3", 0, 0))
    ledger.reserve(accepted_packet)
    ledger.accept(_response(accepted_packet, tokens=90, provider="e" * 64))
    ledger.reserve(packet)
    with pytest.raises(collection.ResourceBoundaryError,
                       match="budget crossed"):
        ledger.accept(_response(packet, tokens=101))
    assert ledger.payload()["crossed"] is True
    ledger.accept(_response(
        accepted_packet, tokens=90, provider="e" * 64))
    reopened = collection.ScientificBudgetLedger(
        root=tmp_path / "ledger",
        started_monotonic_nanoseconds=ledger.started_ns,
        wall_nanoseconds=ledger.wall_ns, token_cap=ledger.token_cap,
        per_call_token_reserve=ledger.reserve_tokens, **LEDGER_BINDING)
    with pytest.raises(collection.ResourceBoundaryError,
                       match="budget crossed"):
        reopened.accept(_response(packet, tokens=101))
    reopened.accept(_response(
        accepted_packet, tokens=90, provider="e" * 64))


def test_scientific_ledger_charges_known_refusal_and_replays(tmp_path):
    ledger = collection.ScientificBudgetLedger(
        root=tmp_path / "ledger",
        started_monotonic_nanoseconds=collection.time.monotonic_ns(),
        wall_nanoseconds=1_000_000_000_000, token_cap=1_000,
        per_call_token_reserve=150, **LEDGER_BINDING)
    packet = _packet()
    ledger.reserve(packet)
    disposition = {
        "packet_sha256": packet.sha256,
        "disposition_sha256": "e" * 64,
        "total_tokens": 120,
        "failure_kind": "CodexToolEventError",
        "failure_class": "mechanics-privacy",
    }
    ledger.refuse(disposition)
    ledger.refuse(disposition)
    assert {key: ledger.payload()[key] for key in (
        "spent_tokens", "reserved_call_count", "accepted_response_count",
        "refused_response_count", "crossed")} == {
        "spent_tokens": 120, "reserved_call_count": 0,
        "accepted_response_count": 0, "refused_response_count": 1,
        "crossed": True}
    reopened = collection.ScientificBudgetLedger(
        root=tmp_path / "ledger",
        started_monotonic_nanoseconds=ledger.started_ns,
        wall_nanoseconds=ledger.wall_ns, token_cap=ledger.token_cap,
        per_call_token_reserve=ledger.reserve_tokens, **LEDGER_BINDING)
    reopened.refuse(disposition)
    assert reopened.payload() == ledger.payload()


def test_complete_game_reopens_without_another_provider_call(tmp_path):
    fake = FakeCodexRun()
    factory = TransportFactory(fake)
    runner = _runner(tmp_path, factory)
    coordinate = ("2", 0, 0)
    first = runner(coordinate, 0)
    assert first.trajectory.body["events"]
    provider_calls = fake.calls
    assert provider_calls > 0

    second = runner(coordinate, 0)
    assert second.payload() == first.payload()
    assert fake.calls == provider_calls
    assert factory.calls == 1
    attempt = collection.reopen_attempt(
        tmp_path / "attempts" / "2-0-0-mirror-0",
        seed_secret=SECRET)
    assert attempt.status == "complete"
    assert attempt.usage["response_count"] == provider_calls
    with pytest.raises(collection.RPCCollectionError,
                       match="scientific binding"):
        collection.reopen_attempt(
            tmp_path / "attempts" / "2-0-0-mirror-0",
            seed_secret=SECRET,
            expected_scientific_binding_sha256="e" * 64)


def test_returned_usage_crosses_cap_before_any_play_and_seals_refusal(tmp_path):
    fake = FakeCodexRun(total_tokens=120)
    runner = _runner(tmp_path, TransportFactory(fake), token_cap=50)
    with pytest.raises(collection.RPCCollectionError,
                       match="game attempt refused"):
        runner(("2", 0, 0), 0)
    attempt = collection.reopen_attempt(
        tmp_path / "attempts" / "2-0-0-mirror-0",
        seed_secret=SECRET)
    assert attempt.status == "incomplete"
    assert attempt.failure_kind == "ResourceBoundaryError"
    assert attempt.failure_class == "resource-provider"
    journal = json.loads((tmp_path / "attempts" / "2-0-0-mirror-0"
                          / "journal" / "000000-response.json").read_text())
    assert journal["response"]["usage"]["total_tokens"] == 120
    assert not (tmp_path / "attempts" / "2-0-0-mirror-0"
                / "trajectory.json").exists()


def test_unknown_provider_disposition_is_never_retried(tmp_path):
    fake = FakeCodexRun(crash_before_response=True)
    factory = TransportFactory(fake)
    runner = _runner(tmp_path, factory)
    with pytest.raises(KeyboardInterrupt, match="controller death"):
        runner(("2", 0, 0), 0)
    assert fake.calls == 1
    attempt_path = tmp_path / "attempts" / "2-0-0-mirror-0"
    assert not (attempt_path / "manifest.json").exists()

    fake.crash_before_response = False
    runner = _runner(tmp_path, factory)
    with pytest.raises(collection.RPCCollectionError,
                       match="game attempt refused"):
        runner(("2", 0, 0), 0)
    assert fake.calls == 1
    reopened = collection.reopen_attempt(
        attempt_path, seed_secret=SECRET)
    assert reopened.status == "incomplete"
    assert reopened.failure_kind == "UnknownProviderDisposition"
    assert reopened.failure_class == "resource-provider"


def test_unknown_provider_disposition_charges_global_reserve_on_restart(
        tmp_path):
    fake = FakeCodexRun(crash_before_response=True)
    ledger = collection.ScientificBudgetLedger(
        root=tmp_path / "ledger",
        started_monotonic_nanoseconds=collection.time.monotonic_ns(),
        wall_nanoseconds=1_000_000_000_000, token_cap=1_000,
        per_call_token_reserve=150, **LEDGER_BINDING)
    def make_runner(active_ledger):
        return collection.RPCGameAttemptRunner(
            seed_secret=SECRET, attempts_root=tmp_path / "attempts",
            codex_binary=None, runtime=RUNTIME,
            per_game_deadline_seconds=600, per_game_token_cap=1_000,
            per_call_token_reserve=150,
            scientific_budget_provider=active_ledger.snapshot,
            scientific_response_acceptor=active_ledger.accept,
            scientific_dispatch_reserver=active_ledger.reserve,
            scientific_refusal_acceptor=active_ledger.refuse,
            scientific_terminal_acceptor=active_ledger.assert_within_limits,
            transport_factory=TransportFactory(fake))
    with pytest.raises(KeyboardInterrupt, match="controller death"):
        make_runner(ledger)(("2", 0, 0), 0)
    assert ledger.payload()["reserved_call_count"] == 1
    reopened_ledger = collection.ScientificBudgetLedger(
        root=tmp_path / "ledger",
        started_monotonic_nanoseconds=ledger.started_ns,
        wall_nanoseconds=ledger.wall_ns, token_cap=ledger.token_cap,
        per_call_token_reserve=ledger.reserve_tokens, **LEDGER_BINDING)
    fake.crash_before_response = False
    with pytest.raises(collection.RPCCollectionError,
                       match="game attempt refused"):
        make_runner(reopened_ledger)(("2", 0, 0), 0)
    assert fake.calls == 1
    assert {key: reopened_ledger.payload()[key] for key in (
        "spent_tokens", "reserved_call_count", "refused_response_count",
        "crossed")} == {
        "spent_tokens": 150, "reserved_call_count": 0,
        "refused_response_count": 1, "crossed": True}
    reopened = collection.reopen_attempt(
        tmp_path / "attempts" / "2-0-0-mirror-0",
        seed_secret=SECRET)
    assert reopened.failure_kind == "UnknownProviderDisposition"
    assert reopened.failure_class == "resource-provider"


def test_peer_stop_after_reserve_before_provider_cancels_without_charge(
        tmp_path, monkeypatch):
    fake = FakeCodexRun()
    stop = threading.Event()
    ledger = collection.ScientificBudgetLedger(
        root=tmp_path / "ledger",
        started_monotonic_nanoseconds=collection.time.monotonic_ns(),
        wall_nanoseconds=1_000_000_000_000, token_cap=1_000,
        per_call_token_reserve=150, **LEDGER_BINDING)
    original_reserve = collection.ScientificBudgetLedger.reserve
    def reserve_then_stop(self, packet):
        original_reserve(self, packet)
        stop.set()
    monkeypatch.setattr(
        collection.ScientificBudgetLedger, "reserve", reserve_then_stop)
    def make_runner():
        return collection.RPCGameAttemptRunner(
            seed_secret=SECRET, attempts_root=tmp_path / "attempts",
            codex_binary=None, runtime=RUNTIME,
            per_game_deadline_seconds=600, per_game_token_cap=1_000,
            per_call_token_reserve=150, stop_event=stop,
            scientific_budget_provider=ledger.snapshot,
            scientific_response_acceptor=ledger.accept,
            scientific_dispatch_reserver=ledger.reserve,
            scientific_refusal_acceptor=ledger.refuse,
            scientific_terminal_acceptor=ledger.assert_within_limits,
            transport_factory=TransportFactory(fake))
    with pytest.raises(collection.RPCCollectionError):
        make_runner()(("2", 0, 0), 0)
    assert fake.calls == 0
    assert {key: ledger.payload()[key] for key in (
        "spent_tokens", "reserved_call_count", "cancelled_dispatch_count",
        "crossed")} == {
        "spent_tokens": 0, "reserved_call_count": 0,
        "cancelled_dispatch_count": 1, "crossed": False}
    attempt = tmp_path / "attempts" / "2-0-0-mirror-0"
    reopened = collection.reopen_attempt(attempt, seed_secret=SECRET)
    assert reopened.failure_class == "resource-provider"
    ledger.reconcile_attempt_journals([attempt])
    with pytest.raises(collection.RPCCollectionError,
                       match="sealed game attempt is incomplete"):
        make_runner()(("2", 0, 0), 0)
    assert fake.calls == 0


def test_global_wall_admission_refusal_is_zero_charge_and_reconciles(
        tmp_path):
    fake = FakeCodexRun()
    ledger = collection.ScientificBudgetLedger(
        root=tmp_path / "ledger",
        started_monotonic_nanoseconds=(
            collection.time.monotonic_ns() - 10_000_000_000),
        wall_nanoseconds=100_000_000_000, token_cap=1_000,
        per_call_token_reserve=150,
        per_call_wall_reserve_milliseconds=91_000,
        **LEDGER_BINDING)
    runner = collection.RPCGameAttemptRunner(
        seed_secret=SECRET, attempts_root=tmp_path / "attempts",
        codex_binary=None, runtime=RUNTIME,
        per_game_deadline_seconds=600, per_game_token_cap=1_000,
        per_call_token_reserve=150,
        per_call_wall_reserve_milliseconds=91_000,
        scientific_budget_provider=ledger.snapshot,
        scientific_response_acceptor=ledger.accept,
        scientific_dispatch_reserver=ledger.reserve,
        scientific_refusal_acceptor=ledger.refuse,
        scientific_terminal_acceptor=ledger.assert_within_limits,
        transport_factory=TransportFactory(fake))

    with pytest.raises(collection.RPCCollectionError,
                       match="game attempt refused"):
        runner(("2", 0, 0), 0)

    assert fake.calls == 0
    assert {key: ledger.payload()[key] for key in (
        "spent_tokens", "reserved_call_count", "cancelled_dispatch_count",
        "crossed", "event_count")} == {
        "spent_tokens": 0, "reserved_call_count": 0,
        "cancelled_dispatch_count": 1, "crossed": False,
        "event_count": 1}
    attempt = tmp_path / "attempts" / "2-0-0-mirror-0"
    reopened = collection.reopen_attempt(attempt, seed_secret=SECRET)
    assert reopened.failure_kind == "ResourceBoundaryError"
    assert reopened.failure_class == "resource-provider"
    ledger.reconcile_attempt_journals([attempt])


def test_rejected_sealed_response_charges_exact_usage_and_routes_mechanics(
        tmp_path):
    class WrongTeam:
        calls = 0
        def call(self, packet):
            self.calls += 1
            return PlannerResponse(
                Intent("play", packet.decision_sha256, candidate_index=0,
                       confidence="low", planning_note="wrong team"),
                Usage(80, 20, 100, 1), team=1 - packet.team,
                packet_sha256=packet.sha256,
                memory_sha256=packet.memory.sha256,
                provider_request_sha256=packet.sha256,
                provider_response_sha256="e" * 64)
    transport = WrongTeam()
    ledger = collection.ScientificBudgetLedger(
        root=tmp_path / "ledger",
        started_monotonic_nanoseconds=collection.time.monotonic_ns(),
        wall_nanoseconds=1_000_000_000_000, token_cap=1_000,
        per_call_token_reserve=150, **LEDGER_BINDING)
    runner = collection.RPCGameAttemptRunner(
        seed_secret=SECRET, attempts_root=tmp_path / "attempts",
        codex_binary=None, runtime=RUNTIME,
        per_game_deadline_seconds=600, per_game_token_cap=1_000,
        per_call_token_reserve=150,
        scientific_budget_provider=ledger.snapshot,
        scientific_response_acceptor=ledger.accept,
        scientific_dispatch_reserver=ledger.reserve,
        scientific_refusal_acceptor=ledger.refuse,
        scientific_terminal_acceptor=ledger.assert_within_limits,
        transport_factory=lambda _path: transport)
    with pytest.raises(collection.RPCCollectionError,
                       match="game attempt refused"):
        runner(("2", 0, 0), 0)
    assert transport.calls == 1
    assert {key: ledger.payload()[key] for key in (
        "spent_tokens", "reserved_call_count", "refused_response_count",
        "crossed")} == {
        "spent_tokens": 100, "reserved_call_count": 0,
        "refused_response_count": 1, "crossed": True}
    reopened = collection.reopen_attempt(
        tmp_path / "attempts" / "2-0-0-mirror-0",
        seed_secret=SECRET)
    assert reopened.failure_kind == "TurnValidationError"
    assert reopened.failure_class == "mechanics-privacy"
    attempt_path = tmp_path / "attempts" / "2-0-0-mirror-0"
    ledger.reconcile_attempt_journals([attempt_path])
    empty = collection.ScientificBudgetLedger(
        root=tmp_path / "empty-ledger",
        started_monotonic_nanoseconds=collection.time.monotonic_ns(),
        wall_nanoseconds=1_000_000_000_000, token_cap=1_000,
        per_call_token_reserve=150, **LEDGER_BINDING)
    with pytest.raises(collection.RPCCollectionError,
                       match="population drift"):
        empty.reconcile_attempt_journals([attempt_path])


def test_over_reserve_response_settles_once_and_seals_resource_failure(
        tmp_path):
    fake = FakeCodexRun(total_tokens=200)
    ledger = collection.ScientificBudgetLedger(
        root=tmp_path / "ledger",
        started_monotonic_nanoseconds=collection.time.monotonic_ns(),
        wall_nanoseconds=1_000_000_000_000, token_cap=1_000,
        per_call_token_reserve=150, **LEDGER_BINDING)
    def make_runner(active_ledger):
        return collection.RPCGameAttemptRunner(
            seed_secret=SECRET, attempts_root=tmp_path / "attempts",
            codex_binary=None, runtime=RUNTIME,
            per_game_deadline_seconds=600, per_game_token_cap=1_000,
            per_call_token_reserve=150,
            scientific_budget_provider=active_ledger.snapshot,
            scientific_response_acceptor=active_ledger.accept,
            scientific_dispatch_reserver=active_ledger.reserve,
            scientific_refusal_acceptor=active_ledger.refuse,
            scientific_terminal_acceptor=active_ledger.assert_within_limits,
            transport_factory=TransportFactory(fake))
    with pytest.raises(collection.RPCCollectionError,
                       match="game attempt refused"):
        make_runner(ledger)(("2", 0, 0), 0)
    assert fake.calls == 1
    assert {key: ledger.payload()[key] for key in (
        "spent_tokens", "reserved_call_count", "refused_response_count",
        "crossed", "event_count")} == {
        "spent_tokens": 200, "reserved_call_count": 0,
        "refused_response_count": 1, "crossed": True,
        "event_count": 2}
    attempt = tmp_path / "attempts" / "2-0-0-mirror-0"
    assert {item.name for item in attempt.iterdir()} >= {
        "attempt.json", "journal", "failure.json", "manifest.json"}
    reopened = collection.reopen_attempt(attempt, seed_secret=SECRET)
    assert reopened.failure_kind == "SettledResourceBoundaryError"
    assert reopened.failure_class == "resource-provider"

    reopened_ledger = collection.ScientificBudgetLedger(
        root=tmp_path / "ledger",
        started_monotonic_nanoseconds=ledger.started_ns,
        wall_nanoseconds=ledger.wall_ns, token_cap=ledger.token_cap,
        per_call_token_reserve=ledger.reserve_tokens, **LEDGER_BINDING)
    with pytest.raises(collection.RPCCollectionError,
                       match="sealed game attempt is incomplete"):
        make_runner(reopened_ledger)(("2", 0, 0), 0)
    assert fake.calls == 1
    assert reopened_ledger.payload() == ledger.payload()


def test_attempt_directory_symlink_cannot_redirect_resume_writes(tmp_path):
    fake = FakeCodexRun(crash_before_response=True)
    runner = _runner(tmp_path, TransportFactory(fake))
    with pytest.raises(KeyboardInterrupt):
        runner(("2", 0, 0), 0)
    attempt = tmp_path / "attempts" / "2-0-0-mirror-0"
    relocated = tmp_path / "relocated-attempt"
    attempt.rename(relocated)
    attempt.symlink_to(relocated, target_is_directory=True)
    fake.crash_before_response = False
    with pytest.raises(collection.RPCCollectionError,
                       match="attempt directory drift"):
        runner(("2", 0, 0), 0)
    assert fake.calls == 1
    assert not (relocated / "failure.json").exists()


def test_completed_attempt_symlink_cannot_redirect_reopen_reads(tmp_path):
    fake = FakeCodexRun()
    runner = _runner(tmp_path, TransportFactory(fake))
    runner(("2", 0, 0), 0)
    provider_calls = fake.calls
    attempt = tmp_path / "attempts" / "2-0-0-mirror-0"
    relocated = tmp_path / "relocated-complete"
    attempt.rename(relocated)
    attempt.symlink_to(relocated, target_is_directory=True)
    with pytest.raises(collection.RPCCollectionError,
                       match="attempt directory drift"):
        runner(("2", 0, 0), 0)
    assert fake.calls == provider_calls


def test_tool_event_seals_typed_incomplete_game(tmp_path):
    fake = FakeCodexRun(tool_event=True)
    runner = _runner(tmp_path, TransportFactory(fake))
    with pytest.raises(collection.RPCCollectionError):
        runner(("2", 0, 0), 0)
    reopened = collection.reopen_attempt(
        tmp_path / "attempts" / "2-0-0-mirror-0",
        seed_secret=SECRET)
    assert reopened.status == "incomplete"
    assert reopened.failure_kind == "CodexToolEventError"
    assert reopened.failure_class == "mechanics-privacy"
    assert reopened.usage["total_tokens"] == 120
    assert reopened.usage["response_count"] == 1
    root = tmp_path / "attempts" / "2-0-0-mirror-0"
    refusal = json.loads(
        (root / "journal" / "000000-refusal.json").read_text())
    assert refusal["tool_event_count"] == 1
    assert refusal["usage"]["total_tokens"] == 120
    assert refusal["provider_private_evidence"]["trace_base64"]


def test_tool_refusal_settles_global_ledger_with_actual_usage(tmp_path):
    fake = FakeCodexRun(tool_event=True)
    ledger = collection.ScientificBudgetLedger(
        root=tmp_path / "ledger",
        started_monotonic_nanoseconds=collection.time.monotonic_ns(),
        wall_nanoseconds=1_000_000_000_000, token_cap=1_000,
        per_call_token_reserve=150, **LEDGER_BINDING)
    runner = collection.RPCGameAttemptRunner(
        seed_secret=SECRET, attempts_root=tmp_path / "attempts",
        codex_binary=None, runtime=RUNTIME,
        per_game_deadline_seconds=600, per_game_token_cap=1_000,
        per_call_token_reserve=150,
        scientific_budget_provider=ledger.snapshot,
        scientific_response_acceptor=ledger.accept,
        scientific_dispatch_reserver=ledger.reserve,
        scientific_refusal_acceptor=ledger.refuse,
        scientific_terminal_acceptor=ledger.assert_within_limits,
        transport_factory=TransportFactory(fake))
    with pytest.raises(collection.RPCCollectionError):
        runner(("2", 0, 0), 0)
    assert {key: ledger.payload()[key] for key in (
        "spent_tokens", "reserved_call_count", "refused_response_count",
        "crossed")} == {
        "spent_tokens": 120, "reserved_call_count": 0,
        "refused_response_count": 1, "crossed": True}


def test_journal_refusal_route_survives_controller_death(tmp_path,
                                                         monkeypatch):
    fake = FakeCodexRun(tool_event=True)
    runner = _runner(tmp_path, TransportFactory(fake))
    original = runner._seal_failure
    monkeypatch.setattr(
        runner, "_seal_failure",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            KeyboardInterrupt("after journal refusal")))
    with pytest.raises(KeyboardInterrupt, match="journal refusal"):
        runner(("2", 0, 0), 0)
    provider_calls = fake.calls
    monkeypatch.setattr(runner, "_seal_failure", original)
    runner = _runner(tmp_path, TransportFactory(fake))
    with pytest.raises(collection.RPCCollectionError):
        runner(("2", 0, 0), 0)
    assert fake.calls == provider_calls
    reopened = collection.reopen_attempt(
        tmp_path / "attempts" / "2-0-0-mirror-0",
        seed_secret=SECRET)
    assert reopened.failure_kind == "CodexToolEventError"
    assert reopened.failure_class == "mechanics-privacy"


def test_global_ledger_restart_preserves_journal_refusal_route(
        tmp_path, monkeypatch):
    fake = FakeCodexRun(tool_event=True)
    ledger = collection.ScientificBudgetLedger(
        root=tmp_path / "ledger",
        started_monotonic_nanoseconds=collection.time.monotonic_ns(),
        wall_nanoseconds=1_000_000_000_000, token_cap=1_000,
        per_call_token_reserve=150, **LEDGER_BINDING)
    def make_runner():
        return collection.RPCGameAttemptRunner(
            seed_secret=SECRET, attempts_root=tmp_path / "attempts",
            codex_binary=None, runtime=RUNTIME,
            per_game_deadline_seconds=600, per_game_token_cap=1_000,
            per_call_token_reserve=150,
            scientific_budget_provider=ledger.snapshot,
            scientific_response_acceptor=ledger.accept,
            scientific_dispatch_reserver=ledger.reserve,
            scientific_refusal_acceptor=ledger.refuse,
            scientific_terminal_acceptor=ledger.assert_within_limits,
            transport_factory=TransportFactory(fake))
    runner = make_runner()
    monkeypatch.setattr(
        runner, "_seal_failure",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            KeyboardInterrupt("after journal refusal")))
    with pytest.raises(KeyboardInterrupt, match="journal refusal"):
        runner(("2", 0, 0), 0)
    provider_calls = fake.calls
    reopened_ledger = collection.ScientificBudgetLedger(
        root=tmp_path / "ledger",
        started_monotonic_nanoseconds=ledger.started_ns,
        wall_nanoseconds=ledger.wall_ns, token_cap=ledger.token_cap,
        per_call_token_reserve=ledger.reserve_tokens, **LEDGER_BINDING)
    ledger = reopened_ledger
    with pytest.raises(collection.RPCCollectionError,
                       match="sealed game attempt is incomplete"):
        make_runner()(("2", 0, 0), 0)
    assert fake.calls == provider_calls
    result = collection.reopen_attempt(
        tmp_path / "attempts" / "2-0-0-mirror-0",
        seed_secret=SECRET)
    assert result.failure_kind == "CodexToolEventError"
    assert result.failure_class == "mechanics-privacy"
    assert ledger.payload()["spent_tokens"] == 120


def test_response_crossing_deadline_cannot_mutate_engine(tmp_path, monkeypatch):
    class Clock:
        value = 1_000_000_000
        def __call__(self):
            return self.value
    clock = Clock()
    monkeypatch.setattr(collection.time, "monotonic_ns", clock)
    fake = FakeCodexRun(after_call=lambda: setattr(
        clock, "value", clock.value + 601_000_000_000))
    runner = _runner(tmp_path, TransportFactory(fake))
    with pytest.raises(collection.RPCCollectionError):
        runner(("2", 0, 0), 0)
    reopened = collection.reopen_attempt(
        tmp_path / "attempts" / "2-0-0-mirror-0",
        seed_secret=SECRET)
    assert reopened.failure_kind == "ResourceBoundaryError"
    assert reopened.failure_class == "resource-provider"
    assert reopened.usage["response_count"] == 1


def test_post_settlement_game_deadline_seals_once_and_reopens(
        tmp_path, monkeypatch):
    class Clock:
        value = 1_000_000_000
        def __call__(self):
            return self.value
    clock = Clock()
    monkeypatch.setattr(collection.time, "monotonic_ns", clock)
    fake = FakeCodexRun(after_call=lambda: setattr(
        clock, "value", clock.value + 601_000_000_000))
    ledger = collection.ScientificBudgetLedger(
        root=tmp_path / "ledger",
        started_monotonic_nanoseconds=clock(),
        wall_nanoseconds=1_000_000_000_000, token_cap=1_000,
        per_call_token_reserve=150, **LEDGER_BINDING)
    def make_runner(active_ledger):
        return collection.RPCGameAttemptRunner(
            seed_secret=SECRET, attempts_root=tmp_path / "attempts",
            codex_binary=None, runtime=RUNTIME,
            per_game_deadline_seconds=600, per_game_token_cap=1_000,
            per_call_token_reserve=150,
            scientific_budget_provider=active_ledger.snapshot,
            scientific_response_acceptor=active_ledger.accept,
            scientific_dispatch_reserver=active_ledger.reserve,
            scientific_refusal_acceptor=active_ledger.refuse,
            scientific_terminal_acceptor=active_ledger.assert_within_limits,
            transport_factory=TransportFactory(fake))
    with pytest.raises(collection.RPCCollectionError):
        make_runner(ledger)(("2", 0, 0), 0)
    assert {key: ledger.payload()[key] for key in (
        "spent_tokens", "reserved_call_count", "accepted_response_count",
        "refused_response_count", "crossed", "event_count")} == {
        "spent_tokens": 120, "reserved_call_count": 0,
        "accepted_response_count": 1, "refused_response_count": 0,
        "crossed": False, "event_count": 2}
    attempt = tmp_path / "attempts" / "2-0-0-mirror-0"
    reopened = collection.reopen_attempt(attempt, seed_secret=SECRET)
    assert reopened.failure_kind == "ResourceBoundaryError"
    assert reopened.failure_class == "resource-provider"
    provider_calls = fake.calls
    reopened_ledger = collection.ScientificBudgetLedger(
        root=tmp_path / "ledger",
        started_monotonic_nanoseconds=ledger.started_ns,
        wall_nanoseconds=ledger.wall_ns, token_cap=ledger.token_cap,
        per_call_token_reserve=ledger.reserve_tokens, **LEDGER_BINDING)
    with pytest.raises(collection.RPCCollectionError,
                       match="sealed game attempt is incomplete"):
        make_runner(reopened_ledger)(("2", 0, 0), 0)
    assert fake.calls == provider_calls
    assert reopened_ledger.payload() == ledger.payload()


def test_settled_rollout_mutation_routes_mechanics_without_double_debit(
        tmp_path, monkeypatch):
    class RolloutTransport:
        calls = 0
        def call(self, packet):
            self.calls += 1
            return PlannerResponse(
                Intent("rollout", packet.decision_sha256,
                       candidate_indices=(0,),
                       continuations=("smart-all",),
                       planning_note="bounded rollout"),
                Usage(80, 20, 100, 1), team=packet.team,
                packet_sha256=packet.sha256,
                memory_sha256=packet.memory.sha256,
                provider_request_sha256=packet.sha256,
                provider_response_sha256="f" * 64)
    transport = RolloutTransport()
    original = selfplay.LunaTeamSession.rollout
    def mutate(self, request):
        result = original(self, request)
        self.game.rnd.attacker_points += 1
        return result
    monkeypatch.setattr(selfplay.LunaTeamSession, "rollout", mutate)
    ledger = collection.ScientificBudgetLedger(
        root=tmp_path / "ledger",
        started_monotonic_nanoseconds=collection.time.monotonic_ns(),
        wall_nanoseconds=1_000_000_000_000, token_cap=1_000,
        per_call_token_reserve=150, **LEDGER_BINDING)
    def make_runner(active_ledger):
        return collection.RPCGameAttemptRunner(
            seed_secret=SECRET, attempts_root=tmp_path / "attempts",
            codex_binary=None, runtime=RUNTIME,
            per_game_deadline_seconds=600, per_game_token_cap=1_000,
            per_call_token_reserve=150,
            scientific_budget_provider=active_ledger.snapshot,
            scientific_response_acceptor=active_ledger.accept,
            scientific_dispatch_reserver=active_ledger.reserve,
            scientific_refusal_acceptor=active_ledger.refuse,
            scientific_terminal_acceptor=active_ledger.assert_within_limits,
            transport_factory=lambda _path: transport)

    with pytest.raises(collection.RPCCollectionError,
                       match="game attempt refused"):
        make_runner(ledger)(("2", 0, 0), 0)

    assert transport.calls == 1
    assert {key: ledger.payload()[key] for key in (
        "spent_tokens", "reserved_call_count", "accepted_response_count",
        "refused_response_count", "crossed", "event_count")} == {
        "spent_tokens": 100, "reserved_call_count": 0,
        "accepted_response_count": 1, "refused_response_count": 0,
        "crossed": False, "event_count": 2}
    attempt = tmp_path / "attempts" / "2-0-0-mirror-0"
    reopened = collection.reopen_attempt(attempt, seed_secret=SECRET)
    assert reopened.failure_kind == "TurnValidationError"
    assert reopened.failure_class == "mechanics-privacy"
    ledger.reconcile_attempt_journals([attempt])

    reopened_ledger = collection.ScientificBudgetLedger(
        root=tmp_path / "ledger",
        started_monotonic_nanoseconds=ledger.started_ns,
        wall_nanoseconds=ledger.wall_ns, token_cap=ledger.token_cap,
        per_call_token_reserve=ledger.reserve_tokens, **LEDGER_BINDING)
    with pytest.raises(collection.RPCCollectionError,
                       match="sealed game attempt is incomplete"):
        make_runner(reopened_ledger)(("2", 0, 0), 0)
    assert transport.calls == 1
    assert reopened_ledger.payload() == ledger.payload()


def test_final_engine_play_crossing_deadline_cannot_publish_complete(
        tmp_path, monkeypatch):
    class Clock:
        value = 1_000_000_000
        def __call__(self):
            return self.value
    clock = Clock()
    monkeypatch.setattr(collection.time, "monotonic_ns", clock)
    original = selfplay.LunaTeamSession.play
    def play(self, request):
        response = original(self, request)
        if response.get("status") == "round_end":
            clock.value += 601_000_000_000
        return response
    monkeypatch.setattr(selfplay.LunaTeamSession, "play", play)
    runner = _runner(tmp_path, TransportFactory(FakeCodexRun()))
    with pytest.raises(collection.RPCCollectionError,
                       match="game attempt refused"):
        runner(("2", 0, 0), 0)
    reopened = collection.reopen_attempt(
        tmp_path / "attempts" / "2-0-0-mirror-0",
        seed_secret=SECRET)
    assert reopened.status == "incomplete"
    assert reopened.failure_class == "resource-provider"


def test_scientific_terminal_wall_check_can_fail(tmp_path, monkeypatch):
    class Clock:
        value = 10
        def __call__(self):
            return self.value
    clock = Clock()
    monkeypatch.setattr(collection.time, "monotonic_ns", clock)
    ledger = collection.ScientificBudgetLedger(
        root=tmp_path / "ledger", started_monotonic_nanoseconds=10,
        wall_nanoseconds=2_000_000, token_cap=100,
        per_call_token_reserve=10,
        per_call_wall_reserve_milliseconds=1, **LEDGER_BINDING)
    ledger.assert_within_limits()
    clock.value = 2_000_011
    with pytest.raises(collection.ResourceBoundaryError,
                       match="terminal budget crossed"):
        ledger.assert_within_limits()


def test_post_game_publication_resumes_without_provider_retry(tmp_path,
                                                              monkeypatch):
    fake = FakeCodexRun()
    runner = _runner(tmp_path, TransportFactory(fake))
    original = collection._publish_or_verify
    published = 0
    def crash_after_first(path, payload):
        nonlocal published
        original(path, payload)
        published += 1
        if published == 1:
            raise KeyboardInterrupt("publication crash")
    monkeypatch.setattr(collection, "_publish_or_verify", crash_after_first)
    with pytest.raises(KeyboardInterrupt, match="publication crash"):
        runner(("2", 0, 0), 0)
    provider_calls = fake.calls
    root = tmp_path / "attempts" / "2-0-0-mirror-0"
    assert (root / "evidence.json").is_file()
    assert not (root / "manifest.json").exists()

    monkeypatch.setattr(collection, "_publish_or_verify", original)
    completed = runner(("2", 0, 0), 0)
    assert completed.trajectory.body["events"]
    assert fake.calls == provider_calls
    assert collection.reopen_attempt(
        root, seed_secret=SECRET).status == "complete"


def test_reopen_binds_scheduled_coordinate_and_mirror(tmp_path):
    runner = _runner(tmp_path, TransportFactory(FakeCodexRun()))
    runner(("2", 0, 0), 1)
    root = tmp_path / "attempts" / "2-0-0-mirror-1"

    assert collection.reopen_attempt(
        root, seed_secret=SECRET,
        expected_coordinate=("2", 0, 0), expected_mirror=1).status \
        == "complete"
    with pytest.raises(collection.RPCCollectionError,
                       match="scheduled identity drift"):
        collection.reopen_attempt(
            root, seed_secret=SECRET,
            expected_coordinate=("2", 0, 0), expected_mirror=0)


def test_failure_publication_resumes_without_changing_failure_kind(
        tmp_path, monkeypatch):
    fake = FakeCodexRun(tool_event=True)
    runner = _runner(tmp_path, TransportFactory(fake))
    original = collection._publish_or_verify
    def crash_before_failure_manifest(path, payload):
        if path.name == "manifest.json" \
                and payload.get("status") == "incomplete":
            raise KeyboardInterrupt("failure manifest crash")
        original(path, payload)
    monkeypatch.setattr(
        collection, "_publish_or_verify", crash_before_failure_manifest)
    with pytest.raises(KeyboardInterrupt, match="failure manifest crash"):
        runner(("2", 0, 0), 0)
    provider_calls = fake.calls
    root = tmp_path / "attempts" / "2-0-0-mirror-0"
    assert (root / "failure.json").is_file()
    assert not (root / "manifest.json").exists()

    monkeypatch.setattr(collection, "_publish_or_verify", original)
    with pytest.raises(collection.RPCCollectionError,
                       match="sealed game attempt is incomplete"):
        runner(("2", 0, 0), 0)
    assert fake.calls == provider_calls
    reopened = collection.reopen_attempt(root, seed_secret=SECRET)
    assert reopened.failure_kind == "CodexToolEventError"
    assert reopened.failure_class == "mechanics-privacy"


def test_failure_after_final_commit_is_still_reopenable(tmp_path,
                                                        monkeypatch):
    fake = FakeCodexRun()
    runner = _runner(tmp_path, TransportFactory(fake))
    original = collection._publish_or_verify
    failed = False
    def refuse_evidence_once(path, payload):
        nonlocal failed
        if path.name == "evidence.json" and not failed:
            failed = True
            raise collection.RPCCollectionError("synthetic finalization fault")
        original(path, payload)
    monkeypatch.setattr(collection, "_publish_or_verify", refuse_evidence_once)
    with pytest.raises(collection.RPCCollectionError):
        runner(("2", 0, 0), 0)
    root = tmp_path / "attempts" / "2-0-0-mirror-0"
    reopened = collection.reopen_attempt(root, seed_secret=SECRET)
    assert reopened.status == "incomplete"
    assert reopened.failure_kind == "RPCCollectionError"
    assert reopened.failure_class == "mechanics-privacy"


def test_coordinated_trajectory_and_manifest_rehash_still_refuses(tmp_path):
    runner = _runner(tmp_path, TransportFactory(FakeCodexRun()))
    runner(("2", 0, 0), 0)
    root = tmp_path / "attempts" / "2-0-0-mirror-0"
    trajectory_path = root / "trajectory.json"
    trajectory = json.loads(trajectory_path.read_text())
    trajectory["events"][0]["candidate_index"] = 1
    trajectory_raw = canonical_json_bytes(trajectory)
    trajectory_path.chmod(0o600)
    trajectory_path.write_bytes(trajectory_raw)
    trajectory_path.chmod(0o400)

    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["trajectory.json"] = hashlib.sha256(
        trajectory_raw).hexdigest()
    body = {key: value for key, value in manifest.items()
            if key != "manifest_sha256"}
    manifest["manifest_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()
    manifest_path.chmod(0o600)
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    manifest_path.chmod(0o400)
    with pytest.raises(Exception, match="trajectory|completed"):
        collection.reopen_attempt(root, seed_secret=SECRET)

"""Pilot output wiring, unknown cost accounting, and real engine consumption."""
from types import SimpleNamespace
import time
from dataclasses import replace
import hashlib
import sys

import pytest

from scripts import luna_token_pilot as pilot
from shengji.luna import game
from shengji.luna.turn import Intent, PlannerResponse, TurnDriver, Usage


def test_unknown_failed_call_does_not_report_complete_efficiency():
    rows = [{"arm": "batch4", "accepted": True,
             "decisions": [{}, {}, {}, {}],
             "usage": {"input_tokens": 100, "output_tokens": 20,
                       "cached_input_tokens": 50, "reasoning_output_tokens": 15,
                       "total_tokens": 120, "wall_ms": 1000}},
            {"arm": "batch4", "accepted": False, "decisions": [], "usage": None}]
    summary = pilot.summarize(rows)["batch4"]
    assert summary["usage"]["total_tokens"] == 120  # Not 4 * 120.
    assert summary["accepted_decisions"] == 4
    assert summary["unknown_usage_calls"] == 1
    assert summary["accepted_decisions_per_million_reported_tokens"] is None


def test_admission_refuses_before_provider_and_failure_cost_is_retained(tmp_path):
    calls = []

    class FailedTransport:
        def call(self, packet):
            calls.append(packet)
            raise RuntimeError("provider refused")

        def take_private_refusal_evidence(self, packet):
            return {"usage": Usage(12, 5, 17, 1).payload()}

    runner = object.__new__(pilot.Pilot)
    runner.root = tmp_path
    runner.args = SimpleNamespace(tokens=10, wall_seconds=1200, call_seconds=90)
    runner.created = time.time()
    runner.deadline_ns = time.monotonic_ns() + 1200_000_000_000
    runner.charged = 0
    runner.rows = []
    runner.base = FailedTransport()
    packet = SimpleNamespace(sha256="a" * 64, payload=lambda: {"test": True})
    with pytest.raises(RuntimeError, match="admission budget exhausted"):
        runner.call("baseline", 0, [packet])
    assert calls == []
    runner.args.tokens = 100_000
    row, responses = runner.call("baseline", 0, [packet])
    assert not row["accepted"] and responses is None
    assert runner.charged == 17
    assert pilot.load(tmp_path / "baseline-0000.json")["charged_tokens"] == 17
    # Reopening retains the failed call; it does not incur another invocation.
    runner.call("baseline", 0, [packet])
    assert len(calls) == 1


def test_transports_share_pilot_absolute_deadline(tmp_path, monkeypatch):
    from shengji.luna import token_batch

    class Transport:
        runtime = {}

        def __init__(self, **kwargs):
            self.deadline = kwargs["deadline_provider"]

    monkeypatch.setattr(pilot, "CodexExecPlannerTransport", Transport)
    monkeypatch.setattr(token_batch, "CompactBatchTransport", Transport)
    runner = pilot.Pilot(SimpleNamespace(out=tmp_path, codex_binary="unused",
        wall_seconds=1200, call_seconds=90))
    assert runner.base.deadline() == runner.compact.deadline() == runner.deadline_ns
    runner.deadline_ns = time.monotonic_ns() - 1
    assert runner.base.deadline() < time.monotonic_ns()
    assert runner.compact.deadline() < time.monotonic_ns()


def test_mixed_retained_game_folder_is_rejected(tmp_path, monkeypatch):
    folder = tmp_path / "attempts" / "mixed" / "journal"
    folder.mkdir(parents=True)
    secret = b"luna-rpc-transport-secret-32b!!!"
    packets = []
    for coordinate, index in [(("2", 0, 0), 0), (("5", 1, 0), 12)]:
        g = game.LunaSelfPlayGame(game.build_root(secret, coordinate),
                                  coordinate=coordinate, seed_secret=secret)
        d = TurnDriver(g, pilot.ReadyResponse())
        packet = replace(pilot.driver_packet(d), decision_index=index)
        import base64
        import json
        prompt = "DECISION_PACKET_JSON\n" + json.dumps(packet.payload())
        pilot.publish(folder / f"{index:06d}-response.json", {"response": {
            "provider_private_evidence": {"prompt_base64": base64.b64encode(prompt.encode()).decode()}}})
    with pytest.raises(ValueError, match="retained journal mixes independent deals"):
        pilot.retained_packets(tmp_path)


def test_crash_after_provider_dispatch_is_not_redispatched(tmp_path):
    calls = []

    class CrashTransport:
        def call(self, packet):
            calls.append(packet)
            assert (tmp_path / "pending" / "baseline-0000.json").exists()
            raise KeyboardInterrupt()  # Outside ordinary refusal handling.

    runner = object.__new__(pilot.Pilot)
    runner.root = tmp_path
    runner.args = SimpleNamespace(tokens=100_000, wall_seconds=1200, call_seconds=90)
    runner.created = time.time()
    runner.deadline_ns = time.monotonic_ns() + 1200_000_000_000
    runner.charged, runner.rows = 0, []
    runner.base = CrashTransport()
    packet = SimpleNamespace(sha256="a" * 64, payload=lambda: {"test": True})
    with pytest.raises(KeyboardInterrupt):
        runner.call("baseline", 0, [packet])
    assert not (tmp_path / "baseline-0000.json").exists()
    row, responses = runner.call("baseline", 0, [packet])
    assert len(calls) == 1
    assert not row["accepted"] and row["usage"] is None and responses is None
    assert runner.charged == 30_000


def test_full_round_consumer_finishes_and_preserves_all_four_trajectories(tmp_path):
    class FakePilot:
        root = tmp_path
        args = SimpleNamespace(arms=["batch4"])
        rows = []

        def configure(self, inputs):
            assert len(set(inputs)) == 4

        def call(self, arm, index, packets):
            assert len(set(p.coordinate for p in packets)) == len(packets)
            responses = tuple(PlannerResponse(
                Intent("play", p.decision_sha256, candidate_index=0,
                       confidence="low", planning_note=f"team-{p.team}"),
                Usage(10, 0, 10, 1), team=p.team,
                packet_sha256=p.sha256, memory_sha256=p.memory.sha256,
                provider_request_sha256="a" * 64,
                provider_response_sha256="b" * 64) for p in packets)
            row = {"accepted": True, "usage": {"total_tokens": 10 * len(packets)}}
            self.rows.append(row)
            return row, responses

        def finish(self, extra):
            return extra

    result = pilot.rounds(FakePilot())
    assert result["completed_rounds"] == 4
    assert result["completed_rounds_per_million_reported_tokens"] > 0
    for i in range(4):
        terminal = pilot.load(tmp_path / f"game-{i}-terminal.json")
        assert terminal["completion"]
        assert pilot.load(tmp_path / f"game-{i}-trajectory.json")["events"]
    assert all(row["state"]["phase"] == "round_end"
               for row in pilot.load(sorted(tmp_path.glob("state-*.json"))[-1]))


def test_wrong_game_response_refuses_before_commit():
    secret = b"luna-rpc-transport-secret-32b!!!"
    games = [game.LunaSelfPlayGame(game.build_root(secret, c), coordinate=c,
                                 seed_secret=secret)
             for c in (("2", 0, 0), ("5", 1, 0))]
    slots = [pilot.ReadyResponse() for _ in games]
    drivers = [TurnDriver(g, s) for g, s in zip(games, slots)]
    other = pilot.driver_packet(drivers[1])
    slots[0].response = PlannerResponse(Intent("play", other.decision_sha256,
        candidate_index=0, confidence="low"), Usage(1, 0, 1, 1),
        team=other.team, packet_sha256=other.sha256, memory_sha256=other.memory.sha256)
    before = game._state_snapshot(games[0].rnd)
    with pytest.raises(ValueError, match="planner transport exception"):
        drivers[0].step()
    assert game._state_snapshot(games[0].rnd) == before
    assert drivers[0].decision_index == 0


def _scale16_fake_pilot(tmp_path, *, fail_after_wave=False):
    calls = []

    class FakePilot:
        root = tmp_path
        args = SimpleNamespace(arms=["batch4"], population="scale16")
        rows = []
        charged = 0
        completed_games = 0
        target_games = 16

        def configure(self, inputs):
            self.roots = list(inputs)
            assert len(self.roots) == 16
            assert len(set(self.roots)) == 16

        def call(self, arm, index, packets):
            assert arm == "batch4"
            assert 1 <= len(packets) <= 4
            wave = {pilot.SCALE16_COORDINATES.index(p.coordinate) // 4
                    for p in packets}
            assert len(wave) == 1
            calls.append((index, tuple(p.coordinate for p in packets), wave.pop()))
            if fail_after_wave and calls[-1][2] >= 1:
                row = {"accepted": False, "usage": None, "decisions": []}
                self.rows.append(row)
                return row, None
            responses = tuple(PlannerResponse(
                Intent("play", p.decision_sha256, candidate_index=0,
                       confidence="low", planning_note="scale16"),
                Usage(1, 0, 1, 1), team=p.team, packet_sha256=p.sha256,
                memory_sha256=p.memory.sha256, provider_request_sha256="a" * 64,
                provider_response_sha256="b" * 64) for p in packets)
            row = {"accepted": True, "usage": {"total_tokens": 4},
                   "decisions": [{}, {}, {}, {}]}
            self.rows.append(row)
            return row, responses

        def finish(self, extra):
            return extra

    return FakePilot(), calls


def test_scale16_rounds_are_four_isolated_waves_and_fresh_roots(tmp_path):
    fake, calls = _scale16_fake_pilot(tmp_path)
    result = pilot.rounds(fake)
    assert result["completed_games"] == result["target_games"] == 16
    assert result["completed_rounds"] == 16
    tokens = sum(row["usage"]["total_tokens"] for row in fake.rows)
    assert result["completed_rounds_per_million_reported_tokens"] == 16e6 / tokens
    assert len({wave for _index, _coords, wave in calls}) == 4
    assert all(len(set(packets)) == len(packets)
               for _index, packets, _wave in calls)
    old_secret = hashlib.sha256(
        b"teacher-token-full-round-pilot-2026-09-05-v1").digest()
    old_coords = [("2", 0, 0), ("5", 1, 0), ("9", 0, 0), ("K", 1, 0)]
    old_roots = {game.LunaSelfPlayGame(game.build_root(old_secret, c),
                                       coordinate=c, seed_secret=old_secret).root_sha256
                 for c in old_coords}
    assert not old_roots.intersection(set(fake.roots))
    assert len(list(tmp_path.glob("game-*-terminal.json"))) == 16
    assert len(list(tmp_path.glob("game-*-trajectory.json"))) == 16


def test_scale16_late_refusal_keeps_first_wave_and_counts(tmp_path):
    fake, calls = _scale16_fake_pilot(tmp_path, fail_after_wave=True)
    result = pilot.rounds(fake)
    assert result["status"] == "stopped-on-refusal"
    assert result["completed_games"] == 4 and result["target_games"] == 16
    assert result["completed_rounds"] == 4
    assert len(list(tmp_path.glob("game-*-terminal.json"))) == 4
    assert len(calls) > 1 and all(wave == 0 for _index, _coords, wave in calls[:-1])


def test_scale16_actual_finish_persists_partial_round_count(tmp_path):
    fake, _calls = _scale16_fake_pilot(tmp_path, fail_after_wave=True)
    actual = object.__new__(pilot.Pilot)
    actual.root = tmp_path
    actual.args = SimpleNamespace(arms=["batch4"], population="scale16",
                                   mode="rounds", tokens=6_000_000,
                                   wall_seconds=10_800, call_seconds=90)
    actual.source = {}
    actual.created = time.time()
    actual.charged = 0
    actual.rows = []
    actual.completed_games = actual.completed_rounds = 0
    actual.target_games = 16
    actual.configure = fake.configure

    def call(arm, index, packets):
        row, responses = fake.call(arm, index, packets)
        actual.rows.append({**row, "arm": arm, "index": index})
        actual.charged += (row.get("usage") or {}).get("total_tokens", 0)
        return row, responses

    actual.call = call
    pilot.rounds(actual)
    persisted = pilot.load(tmp_path / "result.json")
    assert persisted["completed_rounds"] == 4
    assert persisted["completed_games"] == 4
    assert persisted["target_games"] == 16


@pytest.mark.parametrize("extra", [
    ["--population", "scale16", "snapshots", "--arms", "batch4"],
    ["--population", "scale16", "rounds", "--arms", "batch2"],
    ["--population", "scale16", "rounds", "--arms", "batch4",
     "--wall-seconds", "10801"],
    ["--population", "scale16", "rounds", "--arms", "batch4",
     "--call-seconds", "91"],
])
def test_scale16_argument_caps_and_mode_are_closed(monkeypatch, tmp_path, extra):
    monkeypatch.setattr(sys, "argv", ["pilot", *extra, "--out", str(tmp_path),
                                       "--codex-binary", "/usr/bin/true"])
    with pytest.raises(SystemExit):
        pilot.main()

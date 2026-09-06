from pathlib import Path
import json
from types import SimpleNamespace
import time

import pytest
from scripts import luna_quality_compare as compare
from scripts import luna_quality_games as gameplay
from scripts import luna_token_pilot as token_pilot
from shengji.ai.heuristic import HeuristicBot
from shengji.luna import game, quality_panel, token_batch
from shengji.luna.canonical import canonical_json_bytes
from shengji.luna.transport import CODE_MODE_DISABLED_DIAGNOSTIC, InvocationResult
from shengji.luna.turn import Intent, PlannerResponse, Usage


SECRET = bytes(range(32))


class FastProduction:
    def __init__(self, seed=None):
        del seed

    def _candidates(self, rnd, seat):
        return [HeuristicBot().decide_play(rnd, seat)]

    def decide_play(self, rnd, seat):
        return HeuristicBot().decide_play(rnd, seat)


def _panel(tmp_path, count=2):
    rows = [quality_panel.capture_coordinate(
        SECRET, coordinate, producer_factory=FastProduction)
            for coordinate in game.LunaDesign().root_coordinates[:count]]
    entries = []
    for row in rows:
        raw = canonical_json_bytes(row)
        quality_panel.shard_path(tmp_path, row["coordinate"]).write_bytes(raw)
        entries.append({"coordinate": row["coordinate"],
                        "sha256": compare._sha_bytes(raw),
                        "status": row["status"]})
    (tmp_path / "manifest.json").write_bytes(canonical_json_bytes({
        "schema": quality_panel.SCHEMA, "private": True, "shards": entries}))
    return rows


class FakePilot:
    instances = []

    def __init__(self, args):
        self.root = Path(args.out)
        self.rows = []
        self.calls = []
        FakePilot.instances.append(self)

    def configure(self, inputs):
        self.inputs = inputs

    def call(self, arm, index, packets):
        packets = tuple(packets)
        self.calls.append((arm, index, packets))
        responses = tuple(PlannerResponse(
            Intent("play", packet.decision_sha256, 0, "low",
                   planning_note=f"{arm}-agent{packet.agent_identity}"),
            Usage(1, 0, 1, 1), team=packet.team,
            packet_sha256=packet.sha256, memory_sha256=packet.memory.sha256,
            provider_request_sha256=f"{index + 1:064x}",
            provider_response_sha256=f"{index + 2:064x}")
            for packet in packets)
        row = {"arm": arm, "index": index, "packet_hashes": [p.sha256 for p in packets],
               "accepted": True, "decisions": [{} for _ in packets],
               "usage": {"total_tokens": len(packets)}}
        self.rows.append(row)
        return row, responses


class BadSecondPilot(FakePilot):
    def call(self, arm, index, packets):
        row, responses = super().call(arm, index, packets)
        if arm == "batch4" and len(responses) > 1:
            bad = responses[1]
            responses = (*responses[:1], PlannerResponse(
                Intent("play", bad.intent.decision_sha256, 999, "low"),
                bad.usage, team=bad.team, packet_sha256=bad.packet_sha256,
                memory_sha256=bad.memory_sha256,
                provider_request_sha256=bad.provider_request_sha256,
                provider_response_sha256=bad.provider_response_sha256))
        return row, responses


class RealBatchRunner:
    def __init__(self):
        self.calls = 0

    def __call__(self, command, prompt, workspace, timeout):
        del workspace, timeout
        self.calls += 1
        context = json.loads(prompt.decode().split("BATCH_CONTEXT_JSON\n", 1)[1])
        final = {"decisions": [{"slot": row["slot"], "candidate_index": 0,
                                 "confidence": "low", "planning_note": "cached-plan"}
                                for row in context]}
        raw = json.dumps(final, separators=(",", ":")).encode()
        Path(command[command.index("--output-last-message") + 1]).write_bytes(raw)
        usage = {"input_tokens": 11, "cached_input_tokens": 3,
                 "output_tokens": 9, "reasoning_output_tokens": 4,
                 "cache_write_input_tokens": 0}
        events = [{"type": "thread.started"},
                  {"type": "item.completed", "item": {
                      "id": "diagnostic", "type": "error",
                      "message": CODE_MODE_DISABLED_DIAGNOSTIC}},
                  {"type": "turn.started"},
                  {"type": "item.completed", "item": {
                      "id": "message", "type": "agent_message", "text": raw.decode()}},
                  {"type": "turn.completed", "usage": usage}]
        trace = b"".join(json.dumps(event, separators=(",", ":")).encode() + b"\n"
                          for event in events)
        return InvocationResult(0, trace, b"", 8)


def _real_pilot(out, temp_root, runner):
    pilot = object.__new__(token_pilot.Pilot)
    pilot.root = out
    pilot.args = SimpleNamespace(tokens=100_000, wall_seconds=1200,
                                 call_seconds=90)
    pilot.created = time.time()
    pilot.deadline_ns = time.monotonic_ns() + 1200 * 1_000_000_000
    pilot.charged = 0
    pilot.rows = []
    pilot.compact = token_batch.CompactBatchTransport(
        codex_binary="/usr/bin/true", temp_root=temp_root, run_command=runner,
        runtime_attestor=lambda _: {"schema": "pt-luna-codex-tool-catalog-v1"},
        deadline_provider=lambda: pilot.deadline_ns)
    return pilot


def test_two_mirrors_share_root_and_swap_real_agents(tmp_path):
    rows = _panel(tmp_path)
    result = gameplay.run_gameplay(tmp_path, tmp_path / "out",
                                   pilot_factory=FakePilot,
                                   require_population=False)
    assert result["status"] == "paired-gameplay-complete"
    assert result["completed_games"] == 2 * len(rows)
    pilot = FakePilot.instances[-1]
    assert pilot.inputs["transport"]["policy_mode"] == "play-only"
    assert any(len(packets) == 2 for arm, _, packets in pilot.calls if arm == "batch4")
    for row in rows:
        for mirror in (0, 1):
            terminal = gameplay._load_json(
                tmp_path / "out" / gameplay._game_name(tuple(row["coordinate"]), mirror, "terminal"))
            assert terminal["root_sha256"] == row["root_sha256"]
            assert terminal["mirror"] == mirror
    assert all(
        packet.agent_identity == game.agent_for_team(packet.mirror, packet.team)
        for _, _, packets in pilot.calls for packet in packets)
    assert all(
        packet.agent_identity == (0 if arm == "batch4" else 1)
        for arm, _, packets in pilot.calls for packet in packets)
    from scripts import luna_quality_games_analyze as readout
    gameplay._publish(tmp_path / "out" / "config.json", {"inputs": pilot.inputs})
    actual = readout.analyze(tmp_path / "out")
    assert actual["complete_pairs"] == len(rows)
    assert actual["completed_games"] == 2 * len(rows)
    assert actual["status"] == "complete-panel"


def test_cli_requires_explicit_provider_binary():
    with pytest.raises(SystemExit):
        gameplay.main(["--panel-root", "/missing", "--out", "/tmp/out"])


def test_eight_game_wave_fills_batch4_without_mixing_mirrors(tmp_path):
    _panel(tmp_path, count=8)
    result = gameplay.run_gameplay(tmp_path, tmp_path / "out",
                                   pilot_factory=FakePilot,
                                   require_population=False)
    pilot = FakePilot.instances[-1]
    assert result["completed_games"] == 16
    assert pilot.inputs["wave_size"] == 8
    batch_calls = [packets for arm, _, packets in pilot.calls if arm == "batch4"]
    assert len(batch_calls[0]) == 4  # Four-game mixed-arm waves only admit two.
    for packets in batch_calls:
        assert 1 <= len(packets) <= 4
        assert len({p.coordinate for p in packets}) == len(packets)
        assert len({p.mirror for p in packets}) == 1


def test_malformed_second_batch_response_advances_zero_games(tmp_path):
    _panel(tmp_path)
    with pytest.raises(gameplay.QualityGameplayError, match="candidate"):
        gameplay.run_gameplay(tmp_path, tmp_path / "out",
                              pilot_factory=BadSecondPilot,
                              require_population=False)
    states = list((tmp_path / "out").glob("progress-*.json"))
    assert len(states) == 1
    state = gameplay._load_json(states[0])["state"]["games"]
    assert all(item["decision_index"] == 0 for item in state)
    assert not list((tmp_path / "out").glob("*-terminal.json"))


def test_real_pilot_cached_call_reconstructs_and_consumes_once(tmp_path):
    runner = RealBatchRunner()
    out = tmp_path / "calls"
    out.mkdir(mode=0o700)
    temp_root = tmp_path / "temp"
    temp_root.mkdir(mode=0o700)
    coordinate = ("2", 0, 0)
    active = game.LunaSelfPlayGame(game.build_root(SECRET, coordinate),
                                   coordinate=coordinate, seed_secret=SECRET)
    driver = token_pilot.TurnDriver(active, token_pilot.ReadyResponse())
    packet = token_pilot.driver_packet(driver)
    first = _real_pilot(out, temp_root, runner)
    row, response = first.call("compact1", 0, (packet,))
    assert row["accepted"] and response is not None and runner.calls == 1
    charged = first.charged
    second = _real_pilot(out, temp_root, runner)
    cached, replay = second.call("compact1", 0, (packet,))
    assert cached == row and replay is None and runner.calls == 1
    reconstructed = gameplay._responses(cached, (packet,), replay)
    gameplay._preflight_responses((packet,), reconstructed)
    ready = token_pilot.ReadyResponse()
    resumed = token_pilot.TurnDriver(active, ready)
    ready.response = reconstructed[0]
    resumed.step()
    assert resumed.decision_index == 1
    assert second.charged == charged == row["charged_tokens"]
    assert cached["decisions"] == row["decisions"]


def test_cached_packet_usage_and_response_tamper_refuses(tmp_path):
    coordinate = ("2", 0, 0)
    active = game.LunaSelfPlayGame(game.build_root(SECRET, coordinate),
                                   coordinate=coordinate, seed_secret=SECRET)
    packet = token_pilot.driver_packet(
        token_pilot.TurnDriver(active, token_pilot.ReadyResponse()))
    out = tmp_path / "calls"
    out.mkdir(mode=0o700)
    temp_root = tmp_path / "temp"
    temp_root.mkdir(mode=0o700)
    first = _real_pilot(out, temp_root, RealBatchRunner())
    row, _ = first.call("compact1", 0, (packet,))
    path = out / "compact1-0000.json"
    original = gameplay._load_json(path)
    mutations = ("packets", "usage", "private_evidence")
    for field in mutations:
        tampered = json.loads(json.dumps(original))
        if field == "packets":
            tampered["private_evidence"]["packets"][0]["team"] ^= 1
        elif field == "usage":
            tampered["usage"]["total_tokens"] += 1
        else:
            tampered["private_evidence"]["final_base64"] = "eA=="
        path.write_bytes(canonical_json_bytes(tampered))
        cached, replay = _real_pilot(out, temp_root, RealBatchRunner()).call(
            "compact1", 0, (packet,))
        with pytest.raises(gameplay.QualityGameplayError):
            gameplay._responses(cached, (packet,), replay)
        path.write_bytes(canonical_json_bytes(original))


def test_full_gameplay_recovery_reuses_calls_and_matches_uninterrupted_games(tmp_path, monkeypatch):
    """Exercise the scheduler, real Pilot persistence/configure, and turn wiring."""
    panel = tmp_path / "panel"
    panel.mkdir()
    _panel(panel, count=2)
    clock = [1000.0]
    monkeypatch.setattr(token_pilot.time, "time", lambda: clock[0])

    def factory_for(runner, *, crash=False):
        instances = []
        fail_once = [crash]

        class PersistedPilot(token_pilot.Pilot):
            def __init__(self, args):
                self.args = args
                self.root = args.out
                self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
                self.rows, self.charged = [], 0
                self.created = time.time()
                self.deadline_ns = time.monotonic_ns() + args.wall_seconds * 10**9
                self.base = SimpleNamespace(runtime={"test": "fixed"},
                                            model=game.MODEL, reasoning_effort="medium")
                self.source = {"test": "same-source"}
                self.compact = token_batch.CompactBatchTransport(
                    codex_binary="/usr/bin/true", temp_root=self.root,
                    run_command=runner, timeout_seconds=args.call_seconds,
                    runtime_attestor=lambda _: {"schema": "pt-luna-codex-tool-catalog-v1"},
                    deadline_provider=lambda: self.deadline_ns)
                self.cache_hits = []
                instances.append(self)

            def configure(self, inputs):
                resuming = (self.root / "config.json").exists()
                before = time.monotonic_ns()
                super().configure(inputs)
                after = time.monotonic_ns()
                remaining = self.args.wall_seconds - (time.time() - self.created)
                if resuming:
                    assert before + int(remaining * 10**9) <= self.deadline_ns <= after + int(remaining * 10**9)
                self.remaining_at_configure = remaining

            def call(self, arm, index, packets):
                cached = (self.root / f"{arm}-{index:04d}.json").exists()
                result = super().call(arm, index, packets)
                if cached:
                    self.cache_hits.append(index)
                if fail_once[0] and index == 1:
                    fail_once[0] = False
                    raise RuntimeError("crash after provider publication, before turn commit")
                return result

        return PersistedPilot, instances

    interrupted_runner = RealBatchRunner()
    factory, instances = factory_for(interrupted_runner, crash=True)
    recovered = tmp_path / "recovered"
    with pytest.raises(RuntimeError, match="^crash after provider publication, before turn commit$"):
        gameplay.run_gameplay(panel, recovered, tokens=5_000_000,
                              wall_seconds=1200, pilot_factory=factory,
                              require_population=False)
    assert interrupted_runner.calls == 2
    assert not (recovered / "result.json").exists()
    saved = {p.name: p.read_bytes() for p in recovered.glob("state-*.json")}
    saved_calls = {p.name: p.read_bytes() for p in recovered.glob("*-000[01].json")}
    assert len(saved_calls) == 2 and saved
    original_config = (recovered / "config.json").read_bytes()
    clock[0] += 7
    result = gameplay.run_gameplay(panel, recovered, tokens=5_000_000,
                                   wall_seconds=1200, pilot_factory=factory,
                                   require_population=False)
    assert result["completed_games"] == 4
    assert instances[-1].cache_hits == [0, 1]
    assert (recovered / "config.json").read_bytes() == original_config
    assert instances[-1].remaining_at_configure == 1193
    for name, raw in {**saved, **saved_calls}.items():
        assert (recovered / name).read_bytes() == raw
    assert result["charged_tokens"] == sum(row["charged_tokens"] for row in instances[-1].rows)
    assert len({(row["arm"], row["index"]) for row in instances[-1].rows}) == result["call_count"]
    for row in instances[-1].rows:
        # Store only changed-game inspection snapshots, not 104 states/RPC.
        # Recovery is from retained calls and the bound roots.
        state = gameplay._load_json(recovered / f"state-{row['index']:08d}.json")
        assert {(tuple(item["coordinate"]), item["mirror"]) for item in state["games"]} == {
            (tuple(packet["coordinate"]), packet["mirror"]) for packet in row["packets"]}

    reference_runner = RealBatchRunner()
    reference_factory, _ = factory_for(reference_runner)
    reference = tmp_path / "reference"
    reference_result = gameplay.run_gameplay(panel, reference, tokens=5_000_000,
                                            wall_seconds=1200, pilot_factory=reference_factory,
                                            require_population=False)
    assert interrupted_runner.calls == reference_runner.calls == result["call_count"]
    assert result["charged_tokens"] == reference_result["charged_tokens"]
    for suffix in ("terminal", "trajectory", "metadata"):
        paths = sorted(reference.glob(f"game-*-{suffix}.json"))
        assert len(paths) == 4
        for path in paths:
            assert (recovered / path.name).read_bytes() == path.read_bytes()
    assert gameplay._load_json(recovered / f"state-{result['call_count'] - 1:08d}.json") == \
        gameplay._load_json(reference / f"state-{result['call_count'] - 1:08d}.json")

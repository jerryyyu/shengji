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
        decisions = [{"packet_sha256": response.packet_sha256,
                      "candidate_index": response.intent.candidate_index,
                      "confidence": response.intent.confidence,
                      "planning_note": response.intent.planning_note}
                     for response in responses]
        row = {"arm": arm, "index": index, "packet_hashes": [p.sha256 for p in packets],
               "accepted": True, "decisions": decisions,
               "usage": {"input_tokens": len(packets),
                         "cached_input_tokens": 0,
                         "output_tokens": 0,
                         "reasoning_output_tokens": 0,
                         "total_tokens": len(packets),
                         "wall_ms": len(packets)},
               "private_evidence": None}
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
    def __init__(self, refuse_at=None):
        self.calls = 0
        self.refuse_at = refuse_at

    def __call__(self, command, prompt, workspace, timeout):
        del workspace, timeout
        self.calls += 1
        if self.calls == self.refuse_at:
            raise TimeoutError("synthetic provider timeout, usage unknown")
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


@pytest.mark.parametrize("failed_arm", ["compact1", "batch4"])
def test_provider_refusal_quarantines_deals_not_whole_panel(tmp_path, failed_arm):
    _panel(tmp_path, count=4)

    class RefusingPilot(FakePilot):
        refused = None

        def call(self, arm, index, packets):
            row, responses = super().call(arm, index, packets)
            if arm == failed_arm and self.refused is None:
                self.refused = (index, tuple(p.coordinate for p in packets))
                row.update(accepted=False, decisions=[], error="synthetic provider timeout")
                return row, None
            assert self.refused is None or index != self.refused[0], "no retry"
            return row, responses

    result = gameplay.run_gameplay(tmp_path, tmp_path / "out",
                                   pilot_factory=RefusingPilot,
                                   require_population=False)
    pilot = FakePilot.instances[-1]
    refused_index, coordinates = pilot.refused
    assert result["status"] == "paired-gameplay-panel-complete-with-refusals"
    assert result["failed_games"] == 2 * len(coordinates)
    assert result["completed_games"] == 8 - 2 * len(coordinates) > 0
    assert len({index for _, index, _ in pilot.calls}) == len(pilot.calls)
    partial_metadata = list((tmp_path / "out").glob("*-partial-metadata-*.json"))
    partial_trajectories = list((tmp_path / "out").glob("*-partial-trajectory-*.json"))
    assert len(partial_metadata) == len(partial_trajectories) == result["failed_games"]
    for metadata_path in partial_metadata:
        metadata = gameplay._load_json(metadata_path)
        assert metadata["completed"] is False
        assert "terminal_outcome" not in metadata
        trajectory = gameplay._load_json(
            metadata_path.parent /
            metadata_path.name.replace("partial-metadata", "partial-trajectory"))
        assert metadata["trajectory_sha256"] == gameplay._sha(trajectory)
        assert metadata["root_sha256"] == trajectory["root_sha256"]
        assert metadata["coordinate"] == trajectory["coordinate"]
        assert metadata["mirror"] == trajectory["mirror"]
    for _, index, packets in pilot.calls:
        if index > refused_index:
            assert not set(p.coordinate for p in packets) & set(coordinates)
    refusal = gameplay._load_json(tmp_path / "out" / f"refusal-{refused_index:08d}.json")
    assert refusal["retry"] is False
    assert len(refusal["quarantined"]) == 2 * len(coordinates)
    from scripts import luna_quality_games_analyze as readout
    gameplay._publish(tmp_path / "out" / "config.json", {"inputs": pilot.inputs})
    actual = readout.analyze(tmp_path / "out")
    assert actual["complete_pairs"] == 4 - len(coordinates)
    assert actual["status"] == "partial-panel"


def test_real_pilot_direct_response_mismatch_refuses_before_step_and_cache_recovers(
        tmp_path, monkeypatch):
    _panel(tmp_path)
    out = tmp_path / "out"
    temp_root = tmp_path / "temp"
    temp_root.mkdir(mode=0o700)
    records, captured = [], {}
    make_games = gameplay._make_games

    def track_games(rows):
        records.extend(make_games(rows))
        return records

    monkeypatch.setattr(gameplay, "_make_games", track_games)
    runner = RealBatchRunner()

    def factory(args):
        pilot = _real_pilot(out, temp_root, runner)
        pilot.args = args
        pilot.base = SimpleNamespace(runtime={"test": True}, model=game.MODEL,
                                     reasoning_effort="medium")
        pilot.source = {"test": "same-source"}
        call = pilot.call

        def altered_call(arm, index, packets):
            row, responses = call(arm, index, packets)
            if index == 0:
                assert arm == "batch4" and len(responses) == 2
                captured.update(row=row, packets=packets)
                original = responses[1]
                altered = PlannerResponse(
                    Intent("play", original.intent.decision_sha256,
                           original.intent.candidate_index, original.intent.confidence,
                           planning_note="different-but-valid-direct-note"),
                    original.usage, original.tool_event_count, original.team,
                    original.packet_sha256, original.memory_sha256,
                    original.provider_request_sha256, original.provider_response_sha256)
                # Both responses individually pass TurnDriver's normal checks.
                # Only the new recorded-vs-returned binding can reject this.
                return row, (responses[0], altered)
            return row, responses

        pilot.call = altered_call
        return pilot

    with pytest.raises(gameplay.QualityGameplayError,
                       match="^provider response candidate decision drift$"):
        gameplay.run_gameplay(tmp_path, out, pilot_factory=factory,
                              require_population=False)
    assert runner.calls == 1 and records
    assert all(record.driver.decision_index == 0 for record in records)
    assert not list(out.glob("*-terminal.json"))

    # Recovery consumes the recorded original without another provider call.
    second_runner = RealBatchRunner()
    second = _real_pilot(out, temp_root, second_runner)
    cached, replay = second.call("batch4", 0, captured["packets"])
    assert cached == captured["row"] and replay is None and second_runner.calls == 0
    recovered = gameplay._responses(cached, captured["packets"], replay)
    assert [response.intent.planning_note for response in recovered] == ["cached-plan"] * 2
    gameplay._preflight_responses(captured["packets"], recovered)


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


@pytest.mark.parametrize("refuse_at", [None, 2])
def test_full_gameplay_recovery_reuses_calls_and_matches_uninterrupted_games(tmp_path, monkeypatch, refuse_at):
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

    interrupted_runner = RealBatchRunner(refuse_at=refuse_at)
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
    partial_before = {p.name: p.read_bytes() for p in recovered.glob("*-partial-*.json")}
    assert len(partial_before) == 8  # All four unfinished mirrors have data + metadata.
    partial_histories = [gameplay._load_json(path) for path in
                         recovered.glob("*-partial-trajectory-*.json")]
    assert any(row["events"] for row in partial_histories), "retain already-played moves"
    stop = gameplay._load_json(next(recovered.glob("progress-*.json")))
    stopped_games = {(tuple(row["coordinate"]), row["mirror"]): row
                     for row in stop["state"]["games"]}
    assert sum(row["decision_index"] for row in stopped_games.values()) > 0
    for partial in partial_histories:
        current = stopped_games[tuple(partial["coordinate"]), partial["mirror"]]
        if partial["events"]:
            assert partial["events"][-1]["state_after"] == current["state"]
        metadata_path = next(recovered.glob(gameplay._game_name(
            tuple(partial["coordinate"]), partial["mirror"], "partial-metadata-*")))
        metadata = gameplay._load_json(metadata_path)
        assert metadata["split"] == quality_panel.deal_split(tuple(partial["coordinate"]))
        assert metadata["completed"] is False
        assert metadata["trajectory_sha256"] == gameplay._sha(partial)
    assert not list(recovered.glob("*-terminal.json"))
    original_config = (recovered / "config.json").read_bytes()
    clock[0] += 7
    result = gameplay.run_gameplay(panel, recovered, tokens=5_000_000,
                                   wall_seconds=1200, pilot_factory=factory,
                                   require_population=False)
    assert result["completed_games"] == (4 if refuse_at is None else 2)
    assert result["failed_games"] == (0 if refuse_at is None else 2)
    assert instances[-1].cache_hits == [0, 1]
    assert (recovered / "config.json").read_bytes() == original_config
    assert instances[-1].remaining_at_configure == 1193
    for name, raw in {**saved, **saved_calls}.items():
        assert (recovered / name).read_bytes() == raw
    for name, raw in partial_before.items():
        assert (recovered / name).read_bytes() == raw
    assert result["charged_tokens"] == sum(row["charged_tokens"] for row in instances[-1].rows)
    assert len({(row["arm"], row["index"]) for row in instances[-1].rows}) == result["call_count"]
    for row in instances[-1].rows:
        if not row["accepted"]:
            refusal = gameplay._load_json(recovered / f"refusal-{row['index']:08d}.json")
            assert refusal["retry"] is False and len(refusal["quarantined"]) == 2
            assert row["usage"] is None and row["charged_tokens"] == 30_000
            continue
        # Store only changed-game inspection snapshots, not 104 states/RPC.
        # Recovery is from retained calls and the bound roots.
        state = gameplay._load_json(recovered / f"state-{row['index']:08d}.json")
        assert {(tuple(item["coordinate"]), item["mirror"]) for item in state["games"]} == {
            (tuple(packet["coordinate"]), packet["mirror"]) for packet in row["packets"]}

    reference_runner = RealBatchRunner(refuse_at=refuse_at)
    reference_factory, _ = factory_for(reference_runner)
    reference = tmp_path / "reference"
    reference_result = gameplay.run_gameplay(panel, reference, tokens=5_000_000,
                                            wall_seconds=1200, pilot_factory=reference_factory,
                                            require_population=False)
    assert interrupted_runner.calls == reference_runner.calls == result["call_count"]
    assert result["charged_tokens"] == reference_result["charged_tokens"]
    for suffix in ("terminal", "trajectory", "metadata"):
        paths = sorted(reference.glob(f"game-*-{suffix}.json"))
        assert len(paths) == result["completed_games"]
        for path in paths:
            assert (recovered / path.name).read_bytes() == path.read_bytes()
    assert gameplay._load_json(recovered / f"state-{result['call_count'] - 1:08d}.json") == \
        gameplay._load_json(reference / f"state-{result['call_count'] - 1:08d}.json")
